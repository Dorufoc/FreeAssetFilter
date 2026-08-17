"""测试覆盖清单：扫描源公开符号 vs 测试目标的缺失矩阵与孤儿告警。

功能：

* AST 扫描 ``freeassetfilter/**/*.py``，提取公开类/函数/方法清单；
* **显式排除**：``ui/demos/``、``core/native/src/**``（构建脚本区）、
  ``setup.py``、``__init__.py``、``py.typed``；
* 有效模块集合**并入 ``core/__init__.py`` 的 ``_MODULE_MAP`` /
  ``_SYMBOL_MAP`` 懒别名项** —— 它们把扁平旧路径（如
  ``core.settings_manager``）注册为 ``sys.modules`` 别名并指回真实
  模块，只扫物理文件会把引用扁平路径的测试误报为孤儿；
* AST 扫描 ``tests/**/test_*.py`` 提取测试名与目标模块引用；
* 输出**缺失矩阵（模块×方法）**；``--strict`` 时存在缺失即退出码 1；
* 输出**孤儿测试**告警（测试目标模块在有效集合中不存在）。

module↔test 映射规则：**按文件名模式**（``test_<module>.py`` 恰对应
一个源模块），**不按 import 图**。多模块测试文件（无同名源模块者，
如 ``test_previewers.py``）必须在文件头声明 ``# targets: ...`` 目标
模块集，声明优先读；文件名规则仅作无声明文件的默认值。孤儿判定仅针对
声明/文件名映射后仍无目标模块的文件。

符号覆盖判定规则（``Class.method`` 形式的类内方法/属性）：

* **标识符命中**：测试文件（目标命中该模块的）中出现类名 ``Class``
  或方法名 ``method`` 任一，即视为该符号已覆盖——方法名通过
  ``.method`` 属性访问、``Name``、字符串字面量（如
  ``monkeypatch.setattr(Class, "method", ...)``）均可命中；
* **命名约定命中**：测试函数名为 ``test_<module>_<method>``（``module``
  取源模块叶名），或测试类名为 ``Test<CamelModule><CamelMethod>``，
  也算已覆盖；
* 孤儿判定仅针对声明/文件名映射后仍无目标模块的文件。

用法：``python -m tests.support.coverage_manifest [--strict]``
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

#: 仓库根（本文件位于 tests/support/ 下，上溯两级）。
ROOT_DIR: Path = Path(__file__).resolve().parents[2]
SRC_DIR: Path = ROOT_DIR / "freeassetfilter"
TESTS_DIR: Path = ROOT_DIR / "tests"
CORE_INIT: Path = SRC_DIR / "core" / "__init__.py"

#: 显式排除的路径后缀（相对 SRC_DIR 的部件元组）。
EXCLUDED_PATH_SUFFIXES: Tuple[Tuple[str, ...], ...] = (
    ("ui", "demos"),
    ("core", "native", "src"),
)
#: 显式排除的文件名。
EXCLUDED_BASENAMES: frozenset[str] = frozenset({"__init__.py", "setup.py"})
#: 别名源：core/__init__.py 中的两个 dict 字面量名。
_ALIAS_DICT_NAMES: frozenset[str] = frozenset({"_MODULE_MAP", "_SYMBOL_MAP"})

#: 文件名校验回退时的优先级顺序（多候选歧义时的确定性选择）。
_PRIORITY_DIRS: tuple[str, ...] = (
    "core", "components", "widgets", "services",
    "ui", "utils", "app", "libs",
)


class ModuleInventory:
    """源模块清单：路径、公开符号与别名映射。"""

    def __init__(self) -> None:
        #: 物理模块名（如 freeassetfilter.components.unified_previewer）→ 路径。
        self.modules: Dict[str, Path] = {}
        #: 模块名 → 公开符号集合（类名/函数名/类限定方法名）。
        self.symbols: Dict[str, Set[str]] = {}
        #: 别名模块名（扁平旧路径）→ 真实模块名。
        self.alias_to_real: Dict[str, str] = {}
        #: 本次解析无法读取/parse 的源文件。
        self.parse_failures: List[str] = []

    @property
    def effective_names(self) -> Set[str]:
        """有效模块全集：物理模块 ∪ 别名模块。

        Returns:
            set[str]: 所有可被测试引用的合法模块名。
        """
        return set(self.modules) | set(self.alias_to_real)

    def resolve(self, module_name: str) -> Optional[str]:
        """把（可能为别名的）模块名解析为真实物理模块名。

        Args:
            module_name: 引用到的模块名。

        Returns:
            Optional[str]: 物理模块名；若连别名也不是则 None。
        """
        if module_name in self.modules:
            return module_name
        return self.alias_to_real.get(module_name)


def normalize_dotted(parts: Sequence[str]) -> str:
    """把部件序列拼成 ``freeassetfilter.`` 开头的模块名。

    Args:
        parts: 相对 SRC_DIR 的部件（不含 .py）。

    Returns:
        str: 完整 dotted 模块名。
    """
    return "freeassetfilter." + ".".join(parts)


def is_excluded(rel_parts: Tuple[str, ...]) -> bool:
    """判断相对路径部件是否命中显式排除规则。

    Args:
        rel_parts: 相对 SRC_DIR 的路径部件（含 .py 文件名）。

    Returns:
        bool: True 表示排除。
    """
    for excl in EXCLUDED_PATH_SUFFIXES:
        if len(rel_parts) >= len(excl) and rel_parts[: len(excl)] == excl:
            return True
    return rel_parts[-1] in EXCLUDED_BASENAMES


def _public(node_name: str) -> bool:
    return not node_name.startswith("_")


def _extract_public_symbols(tree: ast.Module) -> Set[str]:
    """提取模块的公开类/函数/方法名集合。

    Args:
        tree: 源文件的 AST。

    Returns:
        set[str]: 公开符号（方法以 ``ClassName.method`` 出现）。
    """
    found: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _public(node.name):
            found.add(node.name)
        elif isinstance(node, ast.ClassDef) and _public(node.name):
            found.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _public(child.name):
                    found.add(f"{node.name}.{child.name}")
    return found


def scan_source_modules(inventory: ModuleInventory) -> None:
    """扫描物理源模块并提取公开符号。

    Args:
        inventory: 结果容器。
    """
    for py_file in SRC_DIR.rglob("*.py"):
        if "__pycache__" in py_file.parts or py_file.name.endswith(".pyi"):
            continue
        rel = py_file.relative_to(SRC_DIR)
        rel_parts: Tuple[str, ...] = tuple(rel.parts)
        if is_excluded(rel_parts):
            continue
        module_name: str = normalize_dotted(rel_parts[:-1]) + "." + rel_parts[-1][:-3]
        inventory.modules[module_name] = py_file
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            inventory.parse_failures.append(str(py_file))
            continue
        inventory.symbols[module_name] = _extract_public_symbols(tree)


def extract_alias_modules() -> Dict[str, str]:
    """解析 core/__init__.py 的 _MODULE_MAP/_SYMBOL_MAP 别名。

    ``_MODULE_MAP`` 的扁平键生成 ``freeassetfilter.core.<flat>`` 别名
    模块名，值即真实模块；``_SYMBOL_MAP`` 的键是符号（不产生模块名），
    取值用于校验对应真实模块存在。

    Returns:
        dict[str, str]: 别名模块名 → 真实模块名。
    """
    alias_to_real: Dict[str, str] = {}
    try:
        core_tree = ast.parse(CORE_INIT.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return alias_to_real
    for node in core_tree.body:
        if isinstance(node, ast.Assign):
            targets: List[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            # 带类型注解的声明在 AST 中是 AnnAssign（如 _MODULE_MAP: dict = {...}）。
            targets = [node.target] if node.target is not None else []
        else:
            continue
        if len(targets) != 1:
            continue
        target = targets[0]
        if not isinstance(target, ast.Name) or target.id not in _ALIAS_DICT_NAMES:
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        pairs: List[Tuple[Optional[str], Optional[str]]] = []
        for key_node, val_node in zip(value.keys, value.values):
            key: Optional[str] = getattr(key_node, "value", None) if isinstance(key_node, ast.Constant) else None
            val: Optional[str] = getattr(val_node, "value", None) if isinstance(val_node, ast.Constant) else None
            pairs.append((key, val))
        if target.id == "_MODULE_MAP":
            for flat, real in pairs:
                if flat and real:
                    alias_to_real[f"freeassetfilter.core.{flat}"] = real
    return alias_to_real


class TestFile:
    """一枚测试文件的解析结果。"""

    def __init__(
        self,
        path: Path,
        test_names: List[str],
        imported_modules: Set[str],
        declared_targets: List[str],
        identifiers: Set[str],
    ) -> None:
        self.path: Path = path
        self.test_names: List[str] = test_names
        self.imported_modules: Set[str] = imported_modules
        self.declared_targets: List[str] = declared_targets
        self.identifiers: Set[str] = identifiers


def _extract_imported_modules(tree: ast.Module) -> Set[str]:
    """从测试文件的 import 语句提取 freeassetfilter 模块引用。

    Args:
        tree: 测试文件 AST。

    Returns:
        set[str]: 引用的模块名（别名/真实均可）。
    """
    refs: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("freeassetfilter."):
                    refs.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if (
                node.module.startswith("freeassetfilter.")
                or (node.level == 0 and node.module.split(".")[0] == "freeassetfilter")
            ):
                refs.add(node.module)
    return refs


def _read_declared_targets(path: Path) -> List[str]:
    """读取文件头 ``# targets:`` 声明行（支持多行续行）。

    声明块格式（首个 ``# targets:`` 行起，后续以 ``#`` 开头的模块名单
    续行，到非注释/非代码行止）：

    .. code:: text

        # targets: components.photo_viewer, components.video_player,
        #          components.pdf_previewer, components.text_previewer

    Args:
        path: 测试文件路径。

    Returns:
        list[str]: 声明的目标模块名（未声明时为空列表）。
    """
    try:
        lines: List[str] = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    names: List[str] = []
    in_block: bool = False
    # 声明块通常位于文件头（docstring 前后）；扫描前 80 行足够覆盖。
    for raw_line in lines[:80]:
        stripped: str = raw_line.strip()
        if not in_block:
            if stripped.startswith("# targets:"):
                in_block = True
                body: str = stripped[len("# targets:"):].strip().strip("#").strip()
                names.extend(_split_targets_line(body))
            continue
        # 声明块内：仅接受注释续行（含模块点路径或逗号）。
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            if body and (body.endswith(",") or _contains_module_path(body)):
                names.extend(_split_targets_line(body))
                continue
        in_block = False
        break
    return names


def _split_targets_line(body: str) -> List[str]:
    """把 ``# targets:`` 单行内容按逗号拆成模块名列表。

    Args:
        body: 去掉 ``# targets:`` 前缀后的原始文本。

    Returns:
        list[str]: 非空模块名列表。
    """
    return [item.strip() for item in body.split(",") if item.strip()]


def _contains_module_path(body: str) -> bool:
    """判断一行文本是否包含 ``foo.bar`` 形式的模块点路径。

    Args:
        body: 待判断文本。

    Returns:
        bool: 含点路径时 True。
    """
    for token in body.split(","):
        token = token.strip()
        if token and "." in token and not token.endswith(":"):
            return True
    return False


def scan_test_files() -> List[TestFile]:
    """扫描 tests/**/test_*.py 并解析测试名与目标引用。

    跳过 dot-dir（如 ``.omo_qa_smoke`` —— 瞬时 QA 探针，非真实套件）
    与 ``__pycache__``。

    Returns:
        list[TestFile]: 各测试文件的解析结果。
    """
    results: List[TestFile] = []
    for py_file in TESTS_DIR.rglob("test_*.py"):
        if "__pycache__" in py_file.parts:
            continue
        if any(part.startswith(".") for part in py_file.relative_to(TESTS_DIR).parts):
            continue
        try:
            tree: ast.Module = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        names: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                names.append(node.name)
        identifiers: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                # ``self.xxx``/``obj.method()`` 的属性/方法引用名：
                # 类内方法符号 ``Class.method`` 通过 ``.method`` 属性访问命中。
                identifiers.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 字符串字面量（如 ``monkeypatch.setattr(Cls, "method", ...)``）。
                identifiers.add(node.value)
        results.append(
            TestFile(
                path=py_file,
                test_names=names,
                imported_modules=_extract_imported_modules(tree),
                declared_targets=_read_declared_targets(py_file),
                identifiers=identifiers,
            )
        )
    return results


def filename_rule_source(file_stem: str, inventory: ModuleInventory) -> Optional[str]:
    """按 ``test_<module>.py`` 文件名规则定位唯一源模块。

    Args:
        file_stem: 测试文件名（含下划线，如 ``test_file_selector``）。
        inventory: 模块清单。

    Returns:
        Optional[str]: 匹配的模块名；无候选或歧义时为 None。
    """
    leaf: str = file_stem[5:]  # 去掉 "test_" 前缀
    if not leaf:
        return None
    candidates: List[str] = [
        name for name, path in inventory.modules.items() if path.stem == leaf
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    # 多候选歧义：按目录优先级取第一个，调用方会输出歧义告警。
    for priority_dir in _PRIORITY_DIRS:
        for candidate in candidates:
            if candidate.split(".")[1] == priority_dir:
                return candidate
    return candidates[0]


def resolve_test_targets(
    test_file: TestFile,
    inventory: ModuleInventory,
) -> Tuple[Set[str], List[str]]:
    """为测试文件解析目标模块集合（声明优先，文件名规则兜底）。

    Args:
        test_file: 测试文件解析结果。
        inventory: 模块清单。

    Returns:
        tuple[set[str], list[str]]: (解析后的物理目标模块名, 孤儿/歧义告警)。
    """
    warnings: List[str] = []
    resolved: Set[str] = set()

    declared_raw: List[str] = test_file.declared_targets
    if declared_raw:
        normalized: List[str] = []
        for name in declared_raw:
            full: str = name if name.startswith("freeassetfilter.") else f"freeassetfilter.{name}"
            normalized.append(full)
        for full in normalized:
            real: Optional[str] = inventory.resolve(full)
            if real is not None:
                resolved.add(real)
            else:
                warnings.append(
                    f"{test_file.path.name}: 声明的目标模块不存在 -> {full}"
                )
        return resolved, warnings

    # 文件名规则默认值
    module_name: Optional[str] = filename_rule_source(test_file.path.stem, inventory)
    if module_name is None:
        warnings.append(
            f"{test_file.path.name}: 无 # targets 声明且文件名不匹配任何源模块 -> 孤儿"
        )
        return resolved, warnings
    candidates: List[str] = [
        name for name, path in inventory.modules.items() if path.stem == test_file.path.stem[5:]
    ]
    if len(candidates) > 1:
        warnings.append(
            f"{test_file.path.name}: 文件名规则多候选歧义 "
            f"({', '.join(sorted(candidates))})，已按优先级取 {module_name}"
        )
    resolved.add(module_name)
    return resolved, warnings


def _symbol_covered(symbol: str, tester_ids: Set[str], test_names: List[str], module_leaf: str) -> bool:
    """判断符号是否被测试文件覆盖。

    Args:
        symbol: 源符号（``Class.method`` 或顶层 ``func``）。
        tester_ids: 测试文件收集到的标识符集合。
        test_names: 测试文件的全部测试函数名。
        module_leaf: 源模块叶名（如 ``file_selector``）。

    Returns:
        bool: True 表示已覆盖。
    """
    if symbol in tester_ids:
        return True
    if "." in symbol:
        class_name, method_name = symbol.split(".", 1)
        # 标识符命中：类名或方法名任一出现在测试文件即视为覆盖。
        if class_name in tester_ids or method_name in tester_ids:
            return True
        # 命名约定命中：test_<module>_<method> 或 Test<Module><Method>。
        prefix: str = f"test_{module_leaf}_{method_name}"
        camel_module: str = _to_camel(module_leaf)
        camel_method: str = _to_camel(method_name)
        class_form: str = f"Test{camel_module}{camel_method}"
        return any(
            name == prefix or name == class_form or name.startswith(prefix + "_")
            for name in test_names
        )
    return False


def _to_camel(name: str) -> str:
    """把 snake_case 转 CamelCase（``file_staging_pool`` → ``FileStagingPool``）。

    Args:
        name: snake_case 标识符。

    Returns:
        str: CamelCase 形式。
    """
    return "".join(part.capitalize() for part in name.split("_") if part)


def build_missing_matrix(
    test_files: List[TestFile],
    targets_by_file: Dict[str, Set[str]],
    inventory: ModuleInventory,
) -> List[Tuple[str, str]]:
    """计算模块×方法缺失矩阵。

    覆盖判定：模块被任一测试文件目标命中（含别名解析后的真实模块）且该
    文件中出现过方法/类/函数名（标识符任一命中）或符合
    ``test_<module>_<method>`` / ``Test<Module><Method>`` 命名约定，
    才视为"已覆盖"。

    Args:
        test_files: 全部测试文件。
        targets_by_file: 文件路径 → 目标模块名集合。
        inventory: 模块清单。

    Returns:
        list[tuple[str, str]]: 缺失的 (模块, 符号)，按模块名排序。
    """
    coverer_ids: Dict[str, Set[str]] = {}
    coverer_test_names: Dict[str, List[str]] = {}
    for tf in test_files:
        for module_name in targets_by_file.get(str(tf.path), set()):
            coverer_ids.setdefault(module_name, set()).update(tf.identifiers)
            coverer_test_names.setdefault(module_name, list()).extend(tf.test_names)

    missing: List[Tuple[str, str]] = []
    for module_name in sorted(inventory.modules):
        symbol_set: Set[str] = inventory.symbols.get(module_name, set())
        tester_ids: Set[str] = coverer_ids.get(module_name, set())
        if not symbol_set:
            continue
        if not tester_ids:
            missing.extend((module_name, symbol) for symbol in sorted(symbol_set))
            continue
        module_leaf: str = module_name.rsplit(".", 1)[-1]
        tester_names: List[str] = coverer_test_names.get(module_name, [])
        for symbol in sorted(symbol_set):
            if not _symbol_covered(symbol, tester_ids, tester_names, module_leaf):
                missing.append((module_name, symbol))
    return missing


def build_report(
    inventory: ModuleInventory,
    test_files: List[TestFile],
    targets_by_file: Dict[str, Set[str]],
    orphan_warnings: List[str],
    missing: List[Tuple[str, str]],
) -> List[str]:
    """汇总人类可读报告。

    Args:
        inventory: 模块清单。
        test_files: 测试文件。
        targets_by_file: 目标映射。
        orphan_warnings: 孤儿/歧义告警。
        missing: 缺失矩阵。

    Returns:
        list[str]: 报告行。
    """
    lines: List[str] = []
    lines.append(f"[coverage-manifest] 源模块: 物理 {len(inventory.modules)} "
                 f"+ 别名 {len(inventory.alias_to_real)} = 有效 {len(inventory.effective_names)}")
    lines.append(f"[coverage-manifest] 测试文件: {len(test_files)} "
                 f"(用例 {sum(len(tf.test_names) for tf in test_files)})")
    covered_modules: Set[str] = set()
    for targets in targets_by_file.values():
        covered_modules.update(targets)
    lines.append(f"[coverage-manifest] 覆盖到模块: {len(covered_modules)} / {len(inventory.modules)}")
    func_gaps = sum(1 for _, s in missing if "." not in s)
    method_gaps = len(missing) - func_gaps
    lines.append(f"[coverage-manifest] 缺失符号: {len(missing)} "
                 f"（函数/类 {func_gaps}，方法 {method_gaps}）")
    lines.append("[coverage-manifest] 缺失矩阵：")
    for module_name, symbol in missing:
        lines.append(f"  {module_name}  {symbol}")
    lines.append(f"[coverage-manifest] 孤儿测试告警: {len(orphan_warnings)}")
    for warning in orphan_warnings:
        lines.append(f"  WARN {warning}")
    return lines


def run(args: argparse.Namespace) -> int:
    """执行扫描并输出报告。

    Args:
        args: argparse 命名空间（--strict / --limit）。

    Returns:
        int: 退出码（--strict 且存在缺失时为 1，否则 0）。
    """
    inventory = ModuleInventory()
    scan_source_modules(inventory)
    inventory.alias_to_real = extract_alias_modules()
    test_files: List[TestFile] = scan_test_files()

    targets_by_file: Dict[str, Set[str]] = {}
    orphan_warnings: List[str] = []
    for tf in test_files:
        targets, warnings = resolve_test_targets(tf, inventory)
        targets_by_file[str(tf.path)] = targets
        orphan_warnings.extend(warnings)

    missing: List[Tuple[str, str]] = build_missing_matrix(
        test_files, targets_by_file, inventory
    )
    lines: List[str] = build_report(
        inventory, test_files, targets_by_file, orphan_warnings, missing
    )
    # --limit 截断缺失矩阵的打印行数（全量逻辑不受影响）。
    show_matrix: bool = not args.limit or len(missing) <= args.limit
    emitted: int = 0
    for line in lines:
        if line == "[coverage-manifest] 缺失矩阵：" and not show_matrix:
            print(line, file=sys.stdout)
            for module_name, symbol in missing[: args.limit]:
                print(f"  {module_name}  {symbol}", file=sys.stdout)
            print(f"  ... 其余 {len(missing) - args.limit} 行省略（--limit {args.limit}）", file=sys.stdout)
            emitted += 3
            continue
        print(line, file=sys.stdout)
        emitted += 1
    for py_file in inventory.parse_failures:
        print(f"[coverage-manifest] 源文件解析失败: {py_file}", file=sys.stderr)
    if args.strict:
        if missing:
            print(f"[coverage-manifest] --strict 触发：存在 {len(missing)} 个缺失符号", file=sys.stderr)
            return 1
        if orphan_warnings:
            print(f"[coverage-manifest] --strict 触发：存在 {len(orphan_warnings)} 个孤儿/歧义告警", file=sys.stderr)
            return 1
        print("[coverage-manifest] --strict 通过：无缺失、无孤儿", file=sys.stderr)
    return 0


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数；None 时取 sys.argv[1:]。

    Returns:
        argparse.Namespace: 参数对象。
    """
    parser = argparse.ArgumentParser(
        prog="coverage-manifest",
        description="扫描 freeassetfilter 公开符号并比对测试目标的缺失矩阵（测试基础设施）。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="存在缺失符号或孤儿告警时以退出码 1 结束（供 todo 28 严格 gate 使用）。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=400,
        help="缺失矩阵最多打印的行数（不影响 strict 判定；0 表示全部打印）。",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数。

    Returns:
        int: 退出码。
    """
    args: argparse.Namespace = _parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
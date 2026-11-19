# -*- coding: utf-8 -*-
"""从快捷键注册表生成用户键位表文档。

用法::

    python tools/gen_shortcut_doc.py            # 覆盖 .output/快捷键-键位表.md
    python tools/gen_shortcut_doc.py --check    # 只校验是否与注册表一致

设计意图：键位表的**唯一事实来源**是 ``sopeek/core/shortcuts/registry.py``。
本脚本把它渲染成 Markdown，避免文档与代码长期漂移（改键后忘记改文档）。

输出位置固定在 ``.output/``（AI 产出物暂存区，已被 ``.gitignore`` 忽略）：
生成的文档需**经人工确认后**再迁入 ``docs/``，不得直接写入 ``docs/``。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Sequence, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from sopeek.core.shortcuts.bindings import BindingKey  # noqa: E402
from sopeek.core.shortcuts.registry import ACTION_SPECS, ActionSpec  # noqa: E402

OUTPUT_PATH = os.path.join(_REPO_ROOT, ".output", "快捷键-键位表.md")

#: 分组标题与说明（顺序即文档章节顺序）。
SECTIONS: Tuple[Tuple[str, str, str], ...] = (
    (
        "global",
        "一、全局",
        "无论焦点在哪、是否全屏，都生效。"
        "**任何弹层（右键菜单 / 下拉弹层 / 弹窗 / 抽屉 / 浮动面板）打开时，"
        "本节 4 个键全部静默**（不区分弹层来源）。"
        "\n\n"
        "> 其他章节里的「再次按下关闭」类开关键（`Ctrl+F` / `Ctrl+G` / `Ctrl+L` / "
        "`Shift+F`）声明了可穿透，在自己的弹层打开时仍能派发；"
        "但 `QMenu` 来源下只有排序菜单（`Ctrl+L`）可穿透，其余一律阻断。"
        "\n\n"
        "> 抽屉开关键 `Shift+F` 是可打印组合键：焦点在可编辑输入框（筛选框、"
        "路径框、抽屉内搜索框、AI 输入框）时它只用于输入大写 `F`，不会开关抽屉；"
        "此时可用别名 `Ctrl+Shift+F` 或 `Esc`。",
    ),
    (
        "navigation",
        "二、焦点区切换",
        "在主界面的各区域之间移动键盘焦点。焦点在任意区域（含预览器）都生效。",
    ),
    (
        "selector",
        "三、文件选择器",
        "焦点在文件选择器（左侧文件列表）时生效。\n\n"
        "> 其中 `Ctrl+F` 筛选、`Ctrl+G` 收藏夹、`Ctrl+H` 刷新、`Ctrl+L` 排序"
        "**在整个主窗口都生效**（预览区、储存池、信息面板、全屏同样可用），"
        "不要求焦点在文件列表里。",
    ),
    (
        "pool",
        "四、文件储存池",
        "焦点在文件储存池时生效。",
    ),
    (
        "info",
        "五、文件信息面板",
        "焦点在预览区下方的文件信息面板时生效。",
    ),
    (
        "media",
        "六、视频 / 音频预览",
        "焦点在视频或音频预览器时生效；全屏时同样生效。\n\n"
        "> `Ctrl+\\` 全屏切换在主界面任意区域（文件列表、储存池、信息面板、"
        "路径框、全屏）都能触发。",
    ),
    (
        "image",
        "七、图像预览",
        "焦点在图像预览器时生效；全屏时同样生效。\n\n"
        "> `Ctrl+\\` 全屏切换在主界面任意区域都能触发。",
    ),
    (
        "pdf",
        "八、PDF 预览",
        "焦点在 PDF 预览器时生效；全屏时同样生效。\n\n"
        "> `Ctrl+\\` 全屏与 `Shift+F` 索引抽屉在主界面任意区域都能触发"
        "（输入框内 `Shift+F` 用于输入大写 F，此时用别名 `Ctrl+Shift+F`）。",
    ),
    (
        "text",
        "九、文本 / 代码预览",
        "焦点在文本或代码预览器时生效；全屏时同样生效。\n\n"
        "> `Ctrl+\\` 全屏与 `Shift+F` 搜索抽屉在主界面任意区域都能触发"
        "（输入框内 `Shift+F` 用于输入大写 F，此时用别名 `Ctrl+Shift+F`）。",
    ),
    (
        "font",
        "十、字体预览",
        "焦点在字体预览器时生效；全屏时同样生效。\n\n"
        "> `Ctrl+\\` 全屏切换在主界面任意区域都能触发。",
    ),
    (
        "archive",
        "十一、压缩包预览",
        "焦点在压缩包预览器时生效。\n\n"
        "> `Shift+F` 全包搜索在主界面任意区域都能触发（压缩包预览没有全屏）。"
        "包内搜索框聚焦时 `Shift+F` 用于输入大写 F，此时用别名 `Ctrl+Shift+F` 或 `Esc`。",
    ),
    (
        "folder",
        "十二、文件夹预览",
        "焦点在文件夹预览器时生效。",
    ),
)

#: region 前缀 → 章节 key（``preview.media`` → ``media``）。
_REGION_TO_SECTION: Dict[str, str] = {
    "global": "global",
    "app": "navigation",
    "selector": "selector",
    "pool": "pool",
    "info": "info",
    "preview.media": "media",
    "preview.image": "image",
    "preview.pdf": "pdf",
    "preview.text": "text",
    "preview.font": "font",
    "preview.archive": "archive",
    "preview.folder": "folder",
}

#: 重复策略 → 中文标注。
_REPEAT_LABEL: Dict[str, str] = {
    "none": "",
    "auto": "长按连续",
    "long_press": "短按切换 / 长按临时",
}

#: Qt 键名 → 面向用户的中文/符号显示。
_KEY_DISPLAY: Dict[str, str] = {
    "Up": "↑",
    "Down": "↓",
    "Left": "←",
    "Right": "→",
    "Return": "Enter",
    "Ctrl+Return": "Ctrl+Enter",
    "PgUp": "PageUp",
    "PgDown": "PageDown",
    "Space": "Space",
    "Escape": "Esc",
    "Backspace": "Backspace",
    "Tab": "Tab",
    "`": "`",
}


def _display_key(text: str) -> str:
    """把 ``QKeySequence`` 文本转成面向用户的显示形式。

    Args:
        text: ``BindingKey.text()`` 的结果。

    Returns:
        str: 显示文本（方向键转箭头、反引号转文字等）。
    """
    mapped = _KEY_DISPLAY.get(text)
    if mapped is not None:
        return mapped
    # 组合键里的方向键也换成箭头：Shift+Left → Shift+←
    for name, symbol in (("Up", "↑"), ("Down", "↓"), ("Left", "←"), ("Right", "→")):
        if text.endswith("+" + name):
            return text[: -len(name)] + symbol
    return text


def _keys_text(spec: ActionSpec) -> str:
    """把动作的默认键位渲染成 `` `Ctrl+F` / `Ctrl+G` `` 形式。

    反引号键（`` ` ``）用中文名「反引号」表示，否则会破坏 Markdown 行内代码。

    Args:
        spec: 动作定义。

    Returns:
        str: Markdown 键位单元格内容；无键位时返回 ``—``。
    """
    parts: List[str] = []
    for raw in spec.default_keys:
        key = BindingKey.parse(raw)
        key_text = key.text() if key is not None else raw
        if key_text == "Ctrl+\\":
            # 反斜杠键在中文键盘上打「、」：中文说明必须放在行内代码外，
            # 否则代码样式会把括号说明也染成等宽字体。
            cell = "`Ctrl+\\`（中文键盘为 `Ctrl+、`）"
            if cell not in parts:
                parts.append(cell)
            continue
        text = _display_key(key_text)
        if text == "`":
            # 反引号会破坏 Markdown 行内代码，改用中文描述
            parts.append("反引号键（`Esc` 下方）")
        elif f"`{text}`" not in parts:
            # 主键盘 Return 与小键盘 Enter 面向用户是同一个「Enter」：去重
            parts.append(f"`{text}`")
    return " / ".join(parts) if parts else "—"


def _collect_by_section() -> Dict[str, List[ActionSpec]]:
    """按章节归集动作（保持注册表顺序）。

    Returns:
        Dict[str, List[ActionSpec]]: 章节 key → 动作列表。
    """
    buckets: Dict[str, List[ActionSpec]] = {key: [] for key, _, _ in SECTIONS}
    for spec in ACTION_SPECS:
        section = _REGION_TO_SECTION.get(str(spec.region))
        if section is None:
            continue
        buckets[section].append(spec)
    return buckets


def render() -> str:
    """渲染完整 Markdown 文档。

    Returns:
        str: 文档全文。
    """
    lines: List[str] = []
    lines.append("# Sopeek 键盘快捷键")
    lines.append("")
    lines.append(
        "> 本文档由 `tools/gen_shortcut_doc.py` 从 "
        "`src/sopeek/core/shortcuts/registry.py` **自动生成**，"
        "请勿手工编辑。"
    )
    lines.append(">")
    lines.append(
        "> 改键位请改注册表后执行 `python tools/gen_shortcut_doc.py` 重新生成。"
    )
    lines.append(">")
    lines.append(
        "> **本文档位于 `.output/`（AI 产出物暂存区，不入库）。"
        "经人工确认后再迁入 `docs/`。**"
    )
    lines.append("")
    lines.append("## 约定")
    lines.append("")
    lines.append("| 标记 | 含义 |")
    lines.append("| --- | --- |")
    lines.append("| `Ctrl+\\` | 反斜杠键；中文输入法下该键打出顿号「、」，两者是同一个物理键 |")
    lines.append("| `+` / `=` | 主键盘的 `+` 需按 `Shift+=`，小键盘的 `+` 直接可用；两者都已绑定 |")
    lines.append("| 长按连续 | 按住不放会持续触发（如 seek、音量、翻页） |")
    lines.append("| 短按切换 / 长按临时 | 短按切到该值并保持；长按期间临时生效，松开恢复 |")
    lines.append("")
    lines.append("`Esc` 是上下文键，含义随当前状态逐级变化，见文末「Esc 优先级」。")
    lines.append("")
    lines.append("## 焦点区与生效范围")
    lines.append("")
    lines.append(
        "主界面有 5 个焦点区：**路径框 → 文件选择器 → 预览区 → 储存池 → 信息面板**"
        "（经典三栏中储存池在预览区之前）。按 `Ctrl+方向键` 或 `F6` 切换焦点区，"
        "当前区会闪一次描边；空预览区 / 空储存池 / 空信息面板会被跳过。"
    )
    lines.append("")
    lines.append(
        "除「全局」与显式声明跨区的动作外，按键只在**当前焦点区**生效；"
        "焦点在文本输入框内时，可打印字符一律留给输入框。"
    )
    lines.append("")
    lines.append(
        "> 主界面里 `Tab` 被绑定为「加入 / 移出储存池」，因此不能用它切换焦点；"
        "请使用 `Ctrl+方向键` / `F6`。弹窗与设置窗口内 `Tab` 仍走 Qt 默认焦点链。"
    )
    lines.append("")

    buckets = _collect_by_section()
    for section_key, title, intro in SECTIONS:
        specs = buckets.get(section_key) or []
        if not specs:
            continue
        lines.append(f"## {title}")
        lines.append("")
        if intro:
            lines.append(intro)
            lines.append("")
        lines.append("| 按键 | 功能 | 说明 |")
        lines.append("| --- | --- | --- |")
        for spec in specs:
            repeat = _REPEAT_LABEL.get(spec.repeat, "")
            desc = spec.description
            # 说明里已含「长按连续」时不再重复追加，避免「（长按连续）（长按连续）」
            if repeat and repeat not in desc:
                desc = f"{desc}（{repeat}）" if desc else repeat
            lines.append(f"| {_keys_text(spec)} | {spec.title} | {desc} |")
        lines.append("")

    lines.extend(_render_fixed_sections())
    return "\n".join(lines).rstrip() + "\n"


def _render_fixed_sections() -> List[str]:
    """渲染「不可改键 / 系统原生 / Esc 优先级」等固定章节。

    Returns:
        List[str]: Markdown 行列表。
    """
    lines: List[str] = []
    lines.append("## 十三、Esc 优先级")
    lines.append("")
    lines.append("`Esc` 不参与普通键位查表，而是分三段处理：")
    lines.append("**① 全局前置层 → ② 各区域消费链 → ③ 未消费则继续冒泡**。")
    lines.append("每段只执行第一个「已消费」的分支。")
    lines.append("")
    lines.append("### 13.1 全局前置层（早于一切区域）")
    lines.append("")
    lines.append("| 顺序 | 行为 | 生效范围 | 实现位置 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| 0 | 关闭最顶层抽屉（PDF 索引 / PDF AI / 文本搜索 / 文本 AI / 字体预览文本 / 字体 AI） | 任意区域 | 派发器 |")
    lines.append("| — | 关闭弹窗（等同取消） | 弹窗内部 | `StyledDialog` 自身 |")
    lines.append("| — | 退出全屏 | 全屏 | 全屏宿主自身 |")
    lines.append("")
    lines.append("> 抽屉关闭排在区域链**之前**：抽屉是普通子控件，焦点落到其内部列表时")
    lines.append("> `Esc` 会被列表吞掉，因此由派发器统一收口。")
    lines.append("> 弹窗与全屏由各自控件先行处理，派发器在检测到弹层时整体静默。")
    lines.append("")
    lines.append("### 13.2 各区域消费链（按顺序）")
    lines.append("")
    lines.append("| 区域 | 顺序 | 行为 |")
    lines.append("| --- | --- | --- |")
    lines.append("| 文件选择器 | 1 / 2 / 3 / 4 | 取消路径框编辑 → 退出批量选择（保留已选）→ 清除框选 → 返回上一级 |")
    lines.append("| 文件储存池 | 1 / 2 / 3 | 退出重命名编辑态 → 退出批量选择（保留已选）→ 清除框选 |")
    lines.append("| PDF 预览 | 1 / 2 | 关闭索引抽屉 → 关闭 AI 抽屉 |")
    lines.append("| 文本预览 | 1 / 2 | 关闭搜索抽屉 → 关闭 AI 抽屉 |")
    lines.append("| 压缩包预览 | 1 / 2 / 3 | 退出搜索态 → 返回包内上一级 → 已在包根目录时把焦点交还进入预览前的焦点区 |")
    lines.append("| 文件夹预览 | 1 / 2 | 返回上一级 → 已在根目录时把焦点交还进入预览前的焦点区 |")
    lines.append("| 图像预览 | — | 无区域链；取色态由预览器自身事件过滤器退出 |")
    lines.append("| 字体预览 | — | 无区域链；抽屉由 13.1 的全局前置层关闭 |")
    lines.append("| 视频 / 音频、Office、无法预览 | — | 无区域链；继续冒泡给主窗口兜底（清除框选） |")
    lines.append("")
    lines.append("> 例：图像取色模式下按 `Esc` 只退出取色，不会连带触发其它层级。")
    lines.append("> 例：PDF 索引抽屉打开时按 `Esc` 只关抽屉，第二次才走区域链。")
    lines.append("> 压缩包的搜索框是**内联搜索**（不是抽屉），`Esc` 由压缩包区域链退出搜索。")
    lines.append("")

    lines.append("## 十四、控件键盘操作")
    lines.append("")
    lines.append("以下控件获得焦点后支持键盘操作（与鼠标等价）：")
    lines.append("")
    lines.append("| 控件 | 按键 | 功能 |")
    lines.append("| --- | --- | --- |")
    lines.append("| 复选框 | `Space` / `Enter` | 切换勾选 |")
    lines.append("| 下拉框（未展开） | `↑` / `↓` | 切换当前值（跳过分隔项） |")
    lines.append("| 下拉框（未展开） | `Space` / `Enter` | 展开下拉 |")
    lines.append("| 下拉框（已展开） | `↑` / `↓` | 移动高亮 |")
    lines.append("| 下拉框（已展开） | `Enter` | 选中当前高亮项并关闭 |")
    lines.append("| 下拉框（已展开） | `Esc` | 关闭下拉（不改变当前值） |")
    lines.append("| 分段控件 | `←` `→` `Home` `End` | 切换分段 |")
    lines.append("| 弹窗 | `Esc` | 关闭（等同取消） |")
    lines.append("| 弹窗 | `Enter` | 触发当前焦点按钮；焦点不在按钮上时回退到主按钮（首个 primary / danger，或唯一按钮） |")
    lines.append("| 弹窗 | `Tab` / `Shift+Tab` | 按 Qt 默认焦点链移动 |")
    lines.append("| 弹窗 | `↑` `↓` `←` `→` | 按几何邻近在控件间移动焦点 |")
    lines.append("| 抽屉 | `Esc` | 关闭 |")
    lines.append("| 抽屉 | `↑` `↓` `←` `→` | 按几何邻近在控件间移动焦点 |")
    lines.append("| AI 输入框 | `Enter` | 发送 |")
    lines.append("| AI 输入框 | `Shift+Enter` | 换行 |")
    lines.append("")
    lines.append("> **滑动条不支持键盘操作**：自绘 `StyledSlider` 是 `NoFocus` 控件，")
    lines.append("> 只能用鼠标拖动（或点击轨道）。")
    lines.append("")

    lines.append("## 十五、不可改键 / 系统原生")
    lines.append("")
    lines.append("以下键位由 Qt 与 Windows 原生提供，**不受本应用键位影响**：")
    lines.append("")
    lines.append("| 来源 | 自带键位 |")
    lines.append("| --- | --- |")
    lines.append(
        "| 系统文件对话框 | `Esc` 取消、`Enter` 确认、`Ctrl+L` 地址栏、"
        "`Alt+←/→` 后退/前进、`Backspace` 上级、`F2` 重命名、`F5` 刷新 |"
    )
    lines.append(
        "| 右键菜单 | `↑↓` 移动、`←→` 子菜单、`Enter` 触发、`Esc` 关闭、"
        "首字母跳转 |"
    )
    lines.append(
        "| 文本输入框 | 标准编辑键（方向、`Home/End`、`Ctrl+A/C/V/X/Z`、"
        "`Backspace`、`Delete`） |"
    )
    lines.append(
        "| 压缩包 / 文件夹内部列表 | `↑↓` 移动、`PageUp/Down` 翻页、`Home/End` 首尾、"
        "`Enter` 进入目录（文件选择器与储存池的方向键由本应用接管） |"
    )
    lines.append(
        "| 压缩包预览列表 / 搜索框 | 列表首行 `↑` 跳到包内搜索框（未展开时自动展开）；"
        "搜索框 `↓` 回到列表首行、`Esc` 退出搜索 |"
    )
    lines.append("| 系统窗口 | `Alt+F4` 关闭、`Win+方向键` 贴边（DWM） |")
    lines.append("")
    lines.append("滚轮行为按预览器不同，**不是统一的「缩放」**：")
    lines.append("")
    lines.append("| 区域 | 无修饰滚轮 | `Ctrl+滚轮` |")
    lines.append("| --- | --- | --- |")
    lines.append("| 文件选择器 / 储存池 | 滚动列表 | 卡片缩放（储存池仅 New 布局） |")
    lines.append("| 图像预览 | 缩放 ±10%（以鼠标为锚点） | 同左 |")
    lines.append("| PDF 预览 | 平滑滚动 | 缩放 ×1.1 / ÷1.1 |")
    lines.append("| 文本 / 字体预览 | 平滑滚动 | 字号 ±1 |")
    lines.append("| 视频 / 音频 | 无 | 无 |")
    lines.append("")
    lines.append("## 十六、鼠标操作")
    lines.append("")
    lines.append(
        "鼠标操作不属于键盘快捷键，完整清单见 "
        "`.output/鼠标操作参考.md`。"
    )
    lines.append("")
    return lines


def _normalize(text: str) -> str:
    """归一化行尾，便于跨平台比较。"""
    return text.replace("\r\n", "\n").strip()


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表（默认取 ``sys.argv[1:]``）。

    Returns:
        int: 0 表示成功（``--check`` 模式下表示与注册表一致）。
    """
    parser = argparse.ArgumentParser(description="生成快捷键文档")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验文档是否与注册表一致（不一致返回 1）",
    )
    args = parser.parse_args(argv)

    content = render()

    if args.check:
        if not os.path.isfile(OUTPUT_PATH):
            print(f"[check] 文档不存在: {OUTPUT_PATH}")
            return 1
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing = f.read()
        if _normalize(existing) != _normalize(content):
            print("[check] 文档与注册表不一致，请重新生成")
            return 1
        print("[check] 文档与注册表一致")
        return 0

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"[gen] 已生成 {OUTPUT_PATH}（{len(content.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

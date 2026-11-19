"""快捷键派发器 —— 应用级事件过滤器 + 区域栈 + 长按状态机。

三层派发
========
1. **全局层**：``region="global"`` 的动作，任何位置都生效（全屏、弹窗）。
2. **上下文阻断**：检测到弹层（``QMenu`` / ``StyledDialog`` / 抽屉 /
   浮动面板 / 模态框）时，**区域层与全局层全部静默**，事件原样放行。
3. **区域层**：按「当前区域 → app」的顺序查表。

为什么需要上下文阻断
====================
``QMenu`` 自带方向键导航与**首字母跳转**（type-ahead）；``StyledDialog``
有按钮焦点链；``StyledComboBox`` 的下拉有独立导航。抢这些键会直接破坏
控件可用性。因此只要有任何弹层存在，一律放行。

``Escape`` 不走普通查表
=======================
``Escape`` 是**上下文键**：同一个键在不同子态下含义不同（退出取色 →
关闭抽屉 → 取消路径编辑 → 退批量 → 清框选 → 返回上级）。因此由各区域
提供有序消费链 ``escape_handlers()``，逐个尝试直到有一个返回 ``True``。

长按策略
========
``repeat="long_press"`` 的动作分两个处理器：

- ``{action_id}.press``：按下**立即**执行（保证短按零延迟反馈）；
- ``{action_id}.release``：接收 ``long_pressed: bool``，仅在长按时回滚。

派发器只在按下时启动一个「标记长按」的定时器，超时后置 ``entered=True``。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

from .bindings import BindingKey, parse_all
from .handlers import Handler, HandlerRegistry
from .registry import ACTION_SPECS, ActionSpec, Region

#: 区域栈的初始值。
_DEFAULT_REGION: Region = "app"

#: 总是参与回落的区域（焦点不在任何具体区域时）。
_FALLBACK_REGION: Region = "app"


class BindingTable:
    """``(region, key) → [action_id]`` 的只读索引（键位固定，构建后不变）。

    同一动作可以登记多个键（如 ``+`` / ``=`` / ``Shift+=`` 都映射到放大），
    也可以声明 ``also_in`` 在多个区域生效。

    为什么值是**列表**而不是单个 id
    -------------------------------
    ``also_in`` 把多个预览器的动作都展开到 ``fullscreen`` 区域（全屏时
    ``Left`` 既是媒体「后退」也是图像「上一个文件」）。这些动作属于**不同
    的预览器**，运行时只有当前预览器注册了 handler。因此索引保留候选列表，
    派发时按「谁有 handler」过滤——无 handler 的候选自然被跳过。

    同一区域内的**真实冲突**（两个动作都声明 ``region=X`` 且键相同）仍然
    在构建期抛 ``ValueError``。
    """

    def __init__(self, specs: Sequence[ActionSpec] = ACTION_SPECS) -> None:
        """用注册表构建索引。

        Args:
            specs: 动作定义序列。

        Raises:
            ValueError: 存在重复 ``action_id`` 或同区域重复键位时抛出。
        """
        self._specs: Dict[str, ActionSpec] = {}
        self._by_key: Dict[Tuple[str, BindingKey], List[str]] = {}
        self._own: Dict[Tuple[str, BindingKey], str] = {}
        self._by_action: Dict[str, List[BindingKey]] = {}
        self._build(specs)

    # ── 构建 ────────────────────────────────────────────────────

    def _build(self, specs: Sequence[ActionSpec]) -> None:
        """构建双向索引并校验冲突。"""
        for spec in specs:
            if spec.action_id in self._specs:
                raise ValueError(f"重复的 action_id: {spec.action_id}")
            self._specs[spec.action_id] = spec

        for spec in specs:
            keys = parse_all(spec.default_keys)
            self._by_action[spec.action_id] = keys
            regions: Tuple[Region, ...] = (spec.region,) + tuple(spec.also_in)
            for region in regions:
                for key in keys:
                    index_key = (str(region), key)
                    if region == spec.region:
                        existing = self._own.get(index_key)
                        if existing is not None and existing != spec.action_id:
                            raise ValueError(
                                f"区域 {region} 内键位冲突：{key.text()!r} "
                                f"同时绑定到 {existing} 与 {spec.action_id}"
                            )
                        self._own[index_key] = spec.action_id
                    bucket = self._by_key.setdefault(index_key, [])
                    if spec.action_id not in bucket:
                        bucket.append(spec.action_id)

    # ── 查询 ────────────────────────────────────────────────────

    def lookup_all(self, key: BindingKey, region: Region) -> Tuple[str, ...]:
        """按区域与键返回**全部候选**动作 id（保持注册顺序）。

        Args:
            key: 归一化键。
            region: 目标区域。

        Returns:
            Tuple[str, ...]: 候选动作 id；无候选返回空元组。
        """
        return tuple(self._by_key.get((str(region), key), ()))

    def lookup(self, key: BindingKey, region: Region) -> Optional[str]:
        """按区域与键查动作 id（只取第一个候选，兼容旧接口）。

        Args:
            key: 归一化键。
            region: 目标区域。

        Returns:
            Optional[str]: 命中返回动作 id，否则 ``None``。
        """
        candidates = self._by_key.get((str(region), key))
        return candidates[0] if candidates else None

    def spec_of(self, action_id: str) -> Optional[ActionSpec]:
        """取动作定义。

        Args:
            action_id: 动作 id。

        Returns:
            Optional[ActionSpec]: 动作定义；未登记返回 ``None``。
        """
        return self._specs.get(action_id)

    def keys_for(self, action_id: str) -> List[BindingKey]:
        """返回某动作登记的全部键位。

        Args:
            action_id: 动作 id。

        Returns:
            List[BindingKey]: 键位列表（可能为空）。
        """
        return list(self._by_action.get(action_id, ()))

    def action_ids(self) -> List[str]:
        """返回全部动作 id（排序）。"""
        return sorted(self._specs)

    def is_empty(self) -> bool:
        """注册表是否为空。"""
        return not self._specs


class _LongPressState:
    """单个长按动作的状态机（只负责「是否已超时」）。"""

    __slots__ = ("action_id", "key", "entered", "timer", "on_release")

    def __init__(
        self,
        action_id: str,
        key: BindingKey,
        threshold_ms: int,
        on_release: Optional[Callable[[bool], None]],
    ) -> None:
        self.action_id = action_id
        self.key = key
        self.entered = False
        self.on_release = on_release
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(max(1, int(threshold_ms)))
        self.timer.timeout.connect(self._mark_entered)

    def _mark_entered(self) -> None:
        """超时：标记为长按态（不重复执行动作）。"""
        self.entered = True

    def start(self) -> None:
        """启动超时计时。"""
        self.timer.start()

    def finish(self) -> bool:
        """结束一次长按，回调 ``on_release``。

        Returns:
            bool: 本次是否属于长按。
        """
        try:
            self.timer.stop()
        except RuntimeError:
            pass
        entered = self.entered
        callback = self.on_release
        if callback is not None:
            try:
                callback(entered)
            except (RuntimeError, TypeError):
                pass
        return entered

    def dispose(self) -> None:
        """释放定时器（对象销毁前调用）。"""
        try:
            self.timer.stop()
            self.timer.deleteLater()
        except RuntimeError:
            pass


class ShortcutDispatcher(QObject):
    """应用级快捷键派发器（安装在 ``QApplication`` 上）。"""

    def __init__(
        self,
        table: Optional[BindingTable] = None,
        handlers: Optional[HandlerRegistry] = None,
    ) -> None:
        """初始化派发器。

        Args:
            table: 绑定表；``None`` 时用默认注册表构建。
            handlers: 处理器注册表；``None`` 时新建。
        """
        super().__init__()
        self._table = table if table is not None else BindingTable()
        self.handlers = handlers if handlers is not None else HandlerRegistry()
        self._region: Region = _DEFAULT_REGION
        self._escape_providers: Dict[str, Any] = {}
        self._long_press: Optional[_LongPressState] = None
        self._app: Optional[QApplication] = None
        self._enabled: bool = True

    # ── 生命周期 ────────────────────────────────────────────────

    def install(self, app: Optional[QApplication] = None) -> bool:
        """安装为应用级事件过滤器（幂等）。

        Args:
            app: 目标应用；``None`` 时取 ``QApplication.instance()``。

        Returns:
            bool: 安装成功返回 True。
        """
        target = app or QApplication.instance()
        if target is None:
            return False
        if self._app is target:
            return True
        if self._app is not None:
            self.uninstall()
        target.installEventFilter(self)
        self._app = target
        return True

    def uninstall(self) -> None:
        """卸载事件过滤器（幂等）。"""
        app = self._app
        self._app = None
        if app is None:
            return
        try:
            app.removeEventFilter(self)
        except RuntimeError:
            pass

    def set_enabled(self, enabled: bool) -> None:
        """开/关派发（调试与灰度用）。

        Args:
            enabled: False 时派发器完全不介入。
        """
        self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        """派发是否开启。"""
        return self._enabled

    # ── 区域栈 ──────────────────────────────────────────────────

    def region(self) -> Region:
        """返回当前区域。"""
        return self._region

    def replace_region(self, region: Region) -> None:
        """替换当前区域（焦点变化时用）。

        Args:
            region: 目标区域。
        """
        if region != self._region:
            self._region = region

    def push_region(self, region: Region) -> None:
        """压入区域（全屏进出用；与 :meth:`pop_region` 成对调用）。

        Args:
            region: 目标区域。
        """
        self._region = region

    def pop_region(self, region: Region) -> None:
        """退出区域；仅在当前区域匹配时回落到 ``app``。

        Args:
            region: 要退出的区域。
        """
        if self._region == region:
            self._region = _DEFAULT_REGION

    # ── Escape 消费链 ───────────────────────────────────────────

    def register_escape_provider(self, region: Region, provider: Any) -> None:
        """登记某区域的 ``Escape`` 消费链提供者。

        Args:
            region: 区域名。
            provider: 需实现 ``escape_handlers() -> list[Callable[[], bool]]``。
        """
        self._escape_providers[str(region)] = provider

    def unregister_escape_provider(self, region: Region) -> None:
        """注销某区域的 ``Escape`` 消费链（幂等）。

        Args:
            region: 区域名。
        """
        self._escape_providers.pop(str(region), None)

    def _handle_escape(self, region: Region) -> bool:
        """按注册顺序尝试 ``Escape`` 消费链。

        Args:
            region: 当前区域。

        Returns:
            bool: 有处理器消费时返回 True。
        """
        provider = self._escape_providers.get(str(region))
        if provider is None:
            return False
        try:
            chain = provider.escape_handlers()
        except (AttributeError, RuntimeError):
            return False
        for handler in chain:
            try:
                if handler():
                    return True
            except RuntimeError:
                continue
        return False

    # ── 长按 ────────────────────────────────────────────────────

    def finish_long_press_if_any(self) -> None:
        """强制收尾在途长按（焦点切换 / 预览器销毁 / 窗口关闭时调用）。

        幂等：无长按在跑时为空操作。
        """
        state = self._long_press
        if state is None:
            return
        self._long_press = None
        state.finish()
        state.dispose()

    # ── 派发 ────────────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        """应用级事件过滤器：三层派发入口。

        Args:
            obj: 事件接收对象。
            event: 待派发事件。

        Returns:
            bool: True 表示事件已消费。
        """
        if not self._enabled:
            return False

        event_type = event.type()

        if event_type == QEvent.Type.KeyRelease:
            return self._handle_release(event)

        if event_type != QEvent.Type.KeyPress:
            return False

        return self._handle_press(event)

    def _handle_release(self, event: QKeyEvent) -> bool:
        """处理按键释放：长按状态机收尾 + ``auto`` 动作的释放回调。

        ``repeat="auto"`` 的动作可选注册 ``{action_id}.release``，用于
        「按住只移高亮、松开才加载」这类手势语义（文件选择器方向键）。
        """
        if event.isAutoRepeat():
            # 长按期间系统连发在部分平台会**成对**发 KeyRelease + KeyPress。
            # 这些伪释放不是真正松手：若照常触发 ``{action}.release``，
            # 文件导航会在按住方向键时连续加载预览（实测反馈的根因）。
            return True

        state = self._long_press
        if state is not None:
            key = BindingKey.from_event(event)
            if key is not None and key == state.key:
                self._long_press = None
                state.finish()
                state.dispose()
                return True

        if self._context_blocked():
            return False
        key = BindingKey.from_event(event)
        if key is None:
            return False
        if self._in_text_input() and not key.has_command_modifier():
            return False
        for region in self._region_chain():
            for candidate in self._table.lookup_all(key, region):
                handler = self.handlers.get(f"{candidate}.release")
                if handler is None:
                    continue
                try:
                    handler()
                except RuntimeError:
                    continue
                return True
        return False

    def _handle_press(self, event: QKeyEvent) -> bool:
        """处理按键按下：抽屉 Esc → 输入框守卫 → 上下文阻断 → 全局层 → Escape 链 → 区域层。"""
        key = BindingKey.from_event(event)
        if key is None:
            return False

        is_plain_escape = (
            key.key == int(Qt.Key.Key_Escape) and not key.has_modifier()
        )

        # ── Esc 第一优先级：关闭最顶层抽屉 ──
        # 必须排在上下文阻断之前：抽屉打开时阻断成立，若不在此处收口，
        # Esc 会被直接放行给内部列表（或被列表吃掉），抽屉永远关不掉。
        if is_plain_escape and self._close_top_drawer_if_any():
            return True

        # ── 输入框守卫（早于上下文阻断） ──
        # 可编辑控件里纯字符 / Shift+字符 一律放行，否则无法打字。
        # 必须排在上下文阻断之前：抽屉内的搜索框、AI 输入框都属于「弹层打开」
        # 场景，而抽屉开关键已改为 ``Shift+F``（可打印组合键）——若先走阻断
        # 分支的 works_in_context 穿透，用户输入大写 ``F`` 就会误开关抽屉。
        # 带 Ctrl/Alt/Meta 的键（含别名 ``Ctrl+Shift+F``）不受影响，仍可切换。
        in_text = self._in_text_input()
        if in_text and not key.has_command_modifier():
            return False

        if self._context_blocked():
            # 少数「再次按下应关闭」的全局开关（抽屉键 / 筛选 / 收藏夹 /
            # 排序菜单）需要在**自己打开的**弹层上仍然可派发，否则第二次
            # 按下会被上下文阻断吞掉。QMenu / 下拉弹层默认全阻断；只有
            # 显式声明 works_in_menu 的动作（排序菜单）能穿透。
            source = self._blocking_source()
            for region in self._region_chain():
                for candidate in self._table.lookup_all(key, region):
                    spec = self._table.spec_of(candidate)
                    if spec is None:
                        continue
                    if source == "menu":
                        if not spec.works_in_menu:
                            continue
                    elif not spec.works_in_context:
                        continue
                    if self._execute(
                        candidate,
                        key,
                        event,
                        allow_auto_repeat=True,
                        region=str(region),
                    ):
                        return True
            return False

        # ── 全局层 ──
        for candidate in self._table.lookup_all(key, "global"):
            if self._execute(candidate, key, event, allow_auto_repeat=True):
                return True

        # 输入框内继续派发带 Ctrl/Alt/Meta 的动作（如 Ctrl+F 筛选、Ctrl+H 刷新、
        # Ctrl+方向键切换焦点区）；无命令修饰键的键已在上面放行，不会走到这里。
        # 产品明确选择「文本框内优先切区」：中文场景不依赖 Ctrl+←/→ 按词移动。

        # ── Escape 特殊链 ──
        if is_plain_escape:
            if self._handle_escape(self._region):
                return True
            return False

        # ── 区域层（当前区域 → app 回落；多候选取「有 handler 的那个」） ──
        for region in self._region_chain():
            for candidate in self._table.lookup_all(key, region):
                if self._execute(
                    candidate,
                    key,
                    event,
                    allow_auto_repeat=True,
                    region=str(region),
                ):
                    return True
        return False

    def _region_chain(self) -> Tuple[Region, ...]:
        """返回区域查表顺序（当前区域 → app 回落）。

        注意：``app`` 动作（焦点区切换）必须**任何区域**都能命中，
        否则焦点在预览器时 ``Ctrl+方向键`` 会失效。因此这里始终追加
        ``app``，且当前区域已是 ``app`` 时不重复。
        """
        if self._region == _FALLBACK_REGION:
            return (_FALLBACK_REGION,)
        return (self._region, _FALLBACK_REGION)

    def _execute(
        self,
        action_id: str,
        key: BindingKey,
        event: QKeyEvent,
        *,
        allow_auto_repeat: bool,
        region: str = "",
    ) -> bool:
        """执行动作（含长按状态机）。

        Args:
            action_id: 动作 id。
            key: 归一化键。
            event: 按键事件。
            allow_auto_repeat: 是否允许 autoRepeat 重复执行。
            region: 当前查表区域；用于查找「区域备用 handler」
                （``{action_id}@{region}``），使同一动作可在非原生区域触发。

        Returns:
            bool: True 表示事件已消费。
        """
        spec = self._table.spec_of(action_id)
        if spec is None:
            return False

        if spec.repeat == "long_press":
            return self._execute_long_press(action_id, key, event)

        handler = None
        if region:
            handler = self.handlers.get(f"{action_id}@{region}")
        if handler is None:
            handler = self.handlers.get(action_id)
        if handler is None:
            return False

        if event.isAutoRepeat():
            if spec.repeat != "auto" or not allow_auto_repeat:
                # 非 auto 动作忽略系统连发，避免长按触发多次。
                return True

        try:
            result = handler()
        except RuntimeError:
            return False
        # handler 显式返回 False 表示「本次未消费」，继续向下层查找。
        return result is not False

    def _execute_long_press(
        self, action_id: str, key: BindingKey, event: QKeyEvent
    ) -> bool:
        """执行长按类动作：按下立即触发，释放时按是否长按决定回滚。"""
        if event.isAutoRepeat():
            return True
        if self._long_press is not None:
            return True

        press = self.handlers.get(f"{action_id}.press")
        release = self.handlers.get(f"{action_id}.release")
        if press is None:
            return False

        spec = self._table.spec_of(action_id)
        threshold = spec.long_press_ms if spec is not None else 350

        state = _LongPressState(
            action_id=action_id,
            key=key,
            threshold_ms=threshold,
            on_release=_adapt_release(release),
        )
        try:
            press()
        except RuntimeError:
            state.dispose()
            return False
        state.start()
        self._long_press = state
        return True

    # ── 上下文 / 焦点判定 ──────────────────────────────────────

    @staticmethod
    def _blocking_source() -> Optional[str]:
        """返回当前弹层的来源类型（无弹层返回 ``None``）。

        「再次按下应关闭」的开关动作（抽屉键 / 筛选 / 收藏夹 / 排序菜单）
        只在**自己打开的弹层**上需要放行；``QMenu`` / 下拉弹层必须保持
        全阻断，否则会破坏 type-ahead 与下拉导航。

        Returns:
            Optional[str]: ``"menu"`` / ``"dialog"`` / ``"drawer"`` /
                ``"panel"`` / ``None``。
        """
        try:
            if QApplication.activePopupWidget() is not None:
                return "menu"
            if QApplication.activeModalWidget() is not None:
                return "dialog"
        except RuntimeError:
            return "menu"

        try:
            from sopeek.ui.components import styled_dialog as _sd

            counter = getattr(_sd, "live_dialog_count", None)
            if callable(counter) and counter() > 0:
                return "dialog"
        except Exception:  # noqa: BLE001 - 组件缺失时按无弹窗处理
            pass

        for module_name, counter_name, label in (
            ("sopeek.ui.components.styled_drawer", "open_drawer_count", "drawer"),
            ("sopeek.ui.components.styled_floating_panel", "open_panel_count", "panel"),
        ):
            try:
                module = __import__(module_name, fromlist=[counter_name])
                counter = getattr(module, counter_name, None)
                if callable(counter) and counter() > 0:
                    return label
            except Exception:  # noqa: BLE001 - 组件缺失时跳过
                continue
        return None

    @staticmethod
    def _context_blocked() -> bool:
        """是否有弹层存在（存在则区域层与全局层全部静默）。

        Returns:
            bool: 有弹层返回 True。
        """
        return ShortcutDispatcher._blocking_source() is not None

    @staticmethod
    def _close_top_drawer_if_any() -> bool:
        """关闭最顶层抽屉（``Esc`` 优先级最高的一层）。

        抽屉是普通子控件：焦点落在其内部列表时，``Esc`` 会被列表消费或
        无法到达抽屉自身的 ``eventFilter``，因此由派发器统一收口。

        Returns:
            bool: 关闭了抽屉返回 True。
        """
        try:
            from sopeek.ui.components.styled_drawer import close_top_drawer

            return bool(close_top_drawer())
        except Exception:  # noqa: BLE001 - 组件缺失时视为无抽屉
            return False

    @staticmethod
    def _in_text_input() -> bool:
        """焦点是否在文本输入类控件内。

        Returns:
            bool: 是则返回 True（调用方据此放行可打印字符）。
        """
        try:
            widget = QApplication.focusWidget()
        except RuntimeError:
            return False
        if widget is None:
            return False
        if isinstance(widget, QLineEdit):
            # 只读输入框收不到可打印字符，不能让它吞掉纯键（尤其 ``Esc``：
            # 压缩包/文件夹预览器的只读路径框在焦点内时，Esc 仍应走区域链）。
            return not widget.isReadOnly()
        if isinstance(widget, (QTextEdit, QPlainTextEdit)) and not widget.isReadOnly():
            return True
        if isinstance(widget, (QAbstractSpinBox, QComboBox, QAbstractSlider)):
            return True
        # 自定义交互控件（下拉 / 复选框 / 分段 / 滑动条）通过动态属性声明
        # 「自己处理方向键」，避免被区域层的 ↑↓ 抢走。
        try:
            if widget.property("sp_owns_keys"):
                return True
        except RuntimeError:
            return False
        return False


def _adapt_release(
    handler: Optional[Handler],
) -> Optional[Callable[[bool], None]]:
    """把无参 / 单参的 release 处理器适配为 ``Callable[[bool], None]``。

    约定：release 处理器签名可以是 ``()`` 或 ``(long_pressed: bool)``。

    Args:
        handler: 注册的 release 处理器。

    Returns:
        Optional[Callable[[bool], None]]: 适配后的回调；``None`` 表示无回滚。
    """
    if handler is None:
        return None

    def _call(long_pressed: bool) -> None:
        try:
            handler(long_pressed)  # type: ignore[call-arg]
        except TypeError:
            handler()  # type: ignore[call-arg]

    return _call


# ── 单例 ────────────────────────────────────────────────────────

_dispatcher: Optional[ShortcutDispatcher] = None


def shortcut_dispatcher() -> ShortcutDispatcher:
    """返回进程内唯一的派发器（惰性创建，不自动安装）。

    Returns:
        ShortcutDispatcher: 全局派发器实例。
    """
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ShortcutDispatcher()
    return _dispatcher


def reset_dispatcher_for_tests() -> None:
    """销毁单例（仅供测试使用，避免用例间状态污染）。"""
    global _dispatcher
    old = _dispatcher
    _dispatcher = None
    if old is not None:
        old.finish_long_press_if_any()
        old.uninstall()


def enter_fullscreen_region() -> None:
    """进入全屏时调用：把当前区域替换为 ``fullscreen``。

    全屏宿主是**独立顶层窗口**，``focusChanged`` 解析不到区域，因此必须由
    进出全屏的代码显式切换。
    """
    try:
        shortcut_dispatcher().push_region("fullscreen")
    except Exception:  # noqa: BLE001 - 快捷键系统异常不影响全屏
        pass


def exit_fullscreen_region() -> None:
    """退出全屏时调用：回落到 ``app`` 区域。"""
    try:
        shortcut_dispatcher().pop_region("fullscreen")
    except Exception:  # noqa: BLE001 - 快捷键系统异常不影响全屏
        pass


def defer_call(fn) -> None:
    """把动作推迟到下一轮事件循环执行。

    为什么全屏切换必须延后：全屏进出会把预览器控件 **reparent** 到独立顶层
    窗口（或反之），Qt 在原生窗口重建期间若仍在按键事件派发栈内，会触发
    use-after-free（实测按 ``Ctrl+\\`` 直接崩溃）。推迟一帧即可脱离事件链。

    Args:
        fn: 无参可调用对象。
    """
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, fn)

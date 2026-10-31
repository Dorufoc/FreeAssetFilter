# -*- coding: utf-8 -*-
"""主布局装配 — 经典三栏 / 预览优先（workspace）两种组装 + 比例规则。

两种模式共用同一批叶子组件（文件选择 / 文件储存 / 统一预览器 / 文件信息面板），
仅「树结构 + 默认比例」不同：

- classic（经典三栏，与历史版本一致）::

      QSplitter(H) ─ [选择 | 储存 | QSplitter(V)〔预览 | 信息〕]

- workspace（预览优先，新布局）::

      QSplitter(H) ─ [选择 | QSplitter(V)〔预览 | QSplitter(H)〔储存 | 信息〕〕]

比例规则（workspace）：

- 主横条默认左 : 右 = 1 : 2（文件选择器宽 = ``default_left_width``，与经典
  布局首栏逐像素一致——两布局切换时选择器宽度不再有 3~4px 差）；
- 右竖条默认让「预览画布（显示区）」呈 16:9（见 ``PREVIEW_ASPECT`` 与
  ``PREVIEW_CHROME_PX``）：预览区高 = 右列宽 × 9/16 + 预览器顶栏高度，
  使 16:9 内容（如 4096×2304 图片按窗口自适应）正好铺满显示区左右与上下；
  该高度受三条约束钳制：

  * 底行 ≤ 右区可用高度一半（半高上限，预览始终至少占一半）；
  * 预览 ≥ 预览器最小总高（``WORKSPACE_PREVIEW_MIN_CONTENT_H`` + 顶栏，
    叶子实测值经 :meth:`MainLayout.set_leaf_minimums` 下发）；
  * 底行 ≥ 底行最小高（叶子实测：max(储存池一行 + 底栏, 信息面板最小高)）。

  三者在窗口过矮时冲突，此时下限优先（预览最小总高 / 底行最小高），
  主窗口最小尺寸已保证正常窗口下不冲突（见 ``MainWindow._apply_window_minimums``）。

- 用户拖拽右竖条后，本会话不再自动维持 16:9（交给用户）；竖向分隔条
  拖动只改高度，不反向调整宽度；
- 窗口缩放时（未拖拽）按当前右区宽度重算 16:9。

classic 比例：主横条 1:1:1、右竖条各半、信息区 ≤ 半高（与历史行为一致）；
信息面板最小尺寸（宽 = 修改时间行单行，高 = 文件名 + 路径 + 首行信息 +
折叠入口行）由叶子自身声明；仅经典布局的储存池可拖拽折叠。

布局切换（``MainWindow.set_layout_mode``）复用本模块：4 个叶子重新挂载即可，
组件本身不销毁重建。
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QFrame, QSplitter, QVBoxLayout, QWidget

from sopeek.ui.theme.app_stylesheet import register_widget_qss


# ── 模式 ──────────────────────────────────────────────────────────────
CLASSIC_MODE = "classic"
WORKSPACE_MODE = "workspace"
MODES = (CLASSIC_MODE, WORKSPACE_MODE)
DEFAULT_MODE = WORKSPACE_MODE

# ── 通用 ──────────────────────────────────────────────────────────────
HANDLE_WIDTH = 10  # 分隔条宽度（与既有三栏一致）

# ── workspace 比例常量（集中于此，便于调参） ─────────────────────────
#: 底行横条中「文件储存」占比：50:50，使储存与信息各占界面约 1/3 宽度
WORKSPACE_POOL_RATIO = 0.5
#: 预览显示区（画布）宽高比 16:9。预览区高 = 右列宽 × 本比例 + PREVIEW_CHROME_PX，
#: 使 16:9 内容（如 4096×2304 图片按窗口自适应）正好铺满显示区左右与上下。
PREVIEW_ASPECT = 9.0 / 16.0
#: 预览器顶栏（工具区）高度补偿：图片/文本/PDF/字体预览器顶部工具栏 48px。
#: 设为 0 表示「整体口径」（算预览区含工具区，不补偿顶栏）。
PREVIEW_CHROME_PX = 48
#: workspace 预览器内容区（画布）最小尺寸：16:9，对应 3840×2160 素材按窗口
#: 自适应时刚好无边铺满的显示口径；预览器最小总高 = 本高 + PREVIEW_CHROME_PX，
#: 由 ``MainWindow`` 下发到预览器与主布局（见 ``set_leaf_minimums``）。
WORKSPACE_PREVIEW_MIN_CONTENT_W = 640
WORKSPACE_PREVIEW_MIN_CONTENT_H = 360
#: 底行最小高度兜底值（叶子未就绪 / 未下发实测值时的缺省口径）。
#: 运行时会由叶子实测值覆盖：workspace 底行最小高 =
#: max(储存池一行卡片 + 其底栏, 信息面板最小高)，见 ``set_leaf_minimums``。
BOTTOM_MIN_PX = 200
#: 经典布局右列底部操作栏槽位高度（与预览器底栏一致，48px）
CLASSIC_ACTION_SLOT_PX = 48
#: 用户重置布局时的渐变时长（毫秒）
RESET_ANIM_DURATION_MS = 280


def default_left_width(width: int) -> int:
    """默认左栏（文件选择器）宽度：两布局统一口径。

    可用宽 = 容器宽 − 2 条分隔条，取三分之一（向下取整）。

    历史缺陷：workspace 主横条只有 1 条分隔条，旧公式
    ``round((宽 − 10) / 3)`` 比 classic 的 ``(宽 − 20) // 3`` 恒定宽
    3~4px——同为「左 1/3」却切换布局时肉眼可见不一致。本函数把两布局
    统一到同一口径（classic 数值保持历史不变；workspace 左栏收窄
    3~4px、右区相应加宽），使选择器宽度逐像素一致。

    Args:
        width: 布局容器宽（逻辑像素）。

    Returns:
        int: 左栏默认宽度；退化尺寸返回 0。
    """
    return max(0, width - 2 * HANDLE_WIDTH) // 3


#: 区域名 → zone frame objectName
_ZONE_OBJECT_NAMES = {
    "selector": "MainZoneSelector",
    "preview": "MainZonePreview",
    "pool": "MainZonePool",
    "info": "MainZoneInfo",
}


class MainLayout(QWidget):
    """主布局装配容器：持有分割条树与 4 个区域占位框。

    使用方式（MainWindow / 原型）：

    1. ``MainLayout(mode)`` 创建后，把叶子组件（或加载占位）加入
       ``zones[key].layout()``；
    2. 窗口显示、几何就绪后调用 :meth:`apply_default_ratios`；
    3. 之后窗口缩放 / 用户拖拽由内部规则接管：
       - 未拖拽右竖条时自动维持预览区 16:9；
       - 底行（workspace）或信息区（classic）永不超过右区半高。
    """

    def __init__(self, mode: str = DEFAULT_MODE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.mode = mode if mode in MODES else DEFAULT_MODE

        self.zones: Dict[str, QFrame] = {}
        self.splitters: Dict[str, QSplitter] = {}
        # 经典布局右列的底部操作栏槽位（workspace 模式为 None）
        self._classic_action_slot: Optional[QWidget] = None

        # 用户拖拽状态：拖拽右竖条后停止自动 16:9（当前会话）
        self._right_user_dragged = False
        # 默认比例只应用一次；此前若几何未就绪（尺寸为 0）则不置位
        self._defaults_applied = False
        # 防重入：setSizes 触发的级联布局不再次进入比例计算
        self._applying = False
        # 缩放/重排事件合并：singleShot(0) 里几何已刷新后再重算
        self._ratio_update_pending = False
        # 半高高频重算节流（<=2px 且未超限时跳过约束重写）
        self._last_half = 0
        # 进行中的「重置布局」渐变（QVariantAnimation；None 表示未在渐变）
        self._reset_anim: Optional[QVariantAnimation] = None
        # 叶子实测下限（MainWindow 在面板就绪 / 切换布局后经 set_leaf_minimums
        # 下发；缺省用兜底常量，未下发时行为与历史一致）：
        # - _bottom_min_px：底行最小高度（workspace：max(储存池一行 + 底栏, 信息最小高)）
        # - _preview_min_total_px：预览器最小总高（workspace：画布 360 + 顶栏 48）
        self._bottom_min_px = BOTTOM_MIN_PX
        self._preview_min_total_px = 0

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        for key, object_name in _ZONE_OBJECT_NAMES.items():
            zone = QFrame(self)
            zone.setObjectName(object_name)
            zone_layout = QVBoxLayout(zone)
            zone_layout.setContentsMargins(0, 0, 0, 0)
            zone_layout.setSpacing(0)
            # 区域容器本身完全透明（边框/填充由叶子组件各自的 section 样式绘制）
            register_widget_qss(
                zone,
                f"QFrame#{object_name} {{ background-color: transparent; border: none; }}",
            )
            self.zones[key] = zone

        if self.mode == WORKSPACE_MODE:
            main = self._make_splitter(Qt.Horizontal)
            right = self._make_splitter(Qt.Vertical)
            bottom = self._make_splitter(Qt.Horizontal)
            main.addWidget(self.zones["selector"])
            main.addWidget(right)
            right.addWidget(self.zones["preview"])
            right.addWidget(bottom)
            bottom.addWidget(self.zones["pool"])
            bottom.addWidget(self.zones["info"])
            self.splitters = {"main": main, "right": right, "bottom": bottom}
            root_layout.addWidget(main)
        else:
            main = self._make_splitter(Qt.Horizontal)
            right = self._make_splitter(Qt.Vertical)
            main.addWidget(self.zones["selector"])
            main.addWidget(self.zones["pool"])
            # 右列容器：垂直分割[预览 | 信息] + 底栏槽位（经典布局下把预览器的
            # 统一操作栏挂到信息面板下方，与左/中两栏的底栏同底对齐）
            right_col = QWidget(self)
            right_col_layout = QVBoxLayout(right_col)
            right_col_layout.setContentsMargins(0, 0, 0, 0)
            right_col_layout.setSpacing(HANDLE_WIDTH)
            right_col_layout.addWidget(right, stretch=1)
            self._classic_action_slot = QWidget(right_col)
            slot_layout = QVBoxLayout(self._classic_action_slot)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.setSpacing(0)
            self._classic_action_slot.setFixedHeight(CLASSIC_ACTION_SLOT_PX)
            right_col_layout.addWidget(self._classic_action_slot)
            main.addWidget(right_col)
            right.addWidget(self.zones["preview"])
            right.addWidget(self.zones["info"])
            self.splitters = {"main": main, "right": right}
            root_layout.addWidget(main)

        # 折叠策略：仅经典布局的储存池可折叠——列压到最小宽后继续拖边框即把
        # 储存池塌缩隐藏（只剩选择器与右列两栏），拖回恢复；其余子项不可折叠。
        main.setCollapsible(0, False)
        if self.mode == WORKSPACE_MODE:
            main.setCollapsible(1, False)
        else:
            main.setCollapsible(1, True)  # 储存池（经典布局第 2 栏）
            main.setCollapsible(2, False)  # 右列容器
        self.splitters["right"].setCollapsible(0, False)
        self.splitters["right"].setCollapsible(1, False)
        if "bottom" in self.splitters:
            self.splitters["bottom"].setCollapsible(0, False)
            self.splitters["bottom"].setCollapsible(1, False)

        # 用户拖拽跟踪：右竖条决定 16:9 自动维持；底行/信息区拖拽后补钳制
        self.splitters["right"].splitterMoved.connect(self._on_right_splitter_moved)
        if "bottom" in self.splitters:
            self.splitters["bottom"].splitterMoved.connect(self._on_bottom_splitter_moved)
        else:
            self.splitters["right"].splitterMoved.connect(self._on_bottom_splitter_moved)
        # 主横条拖拽（左/右分界）：右侧宽度变化后同步 16:9（未拖拽右竖条时）
        self.splitters["main"].splitterMoved.connect(self._on_main_splitter_moved)

    # ── 构造辅助 ─────────────────────────────────────────────────────

    @staticmethod
    def _make_splitter(orientation: Qt.Orientation) -> QSplitter:
        """创建统一样式的分隔条（透明把手、10px、不可折叠）。"""
        splitter = QSplitter(orientation)
        splitter.setHandleWidth(HANDLE_WIDTH)
        splitter.setChildrenCollapsible(False)
        register_widget_qss(
            splitter,
            """
            QSplitter::handle {
                background-color: transparent;
                width: 10px;
                height: 10px;
            }
            """,
        )
        return splitter

    # ── 公共 API ─────────────────────────────────────────────────────

    def zone(self, name: str) -> Optional[QFrame]:
        """返回指定区域容器（selector / preview / pool / info）。"""
        return self.zones.get(name)

    def classic_action_slot(self) -> Optional[QWidget]:
        """经典布局右列的底部操作栏槽位（信息面板下方）。

        Returns:
            Optional[QWidget]: 经典组装返回槽位控件；workspace 组装返回 ``None``。
        """
        return self._classic_action_slot

    def set_leaf_minimums(
        self, bottom_min_px: int, preview_min_total_px: int = 0
    ) -> None:
        """下发叶子组件的实测最小尺寸（面板就绪 / 切换布局后调用）。

        Args:
            bottom_min_px: 底行最小高度（px）。workspace 取
                ``max(储存池.minimum_row_height(), 信息面板.minimum_content_height())``；
                0 表示不限制。
            preview_min_total_px: 预览器最小总高（px，仅 workspace 有意义，
                如画布最小 360 + 顶栏 48 = 408）；0 表示不施加下限。
        """
        new_bottom = max(0, int(bottom_min_px))
        new_preview = max(0, int(preview_min_total_px))
        if (
            new_bottom == self._bottom_min_px
            and new_preview == self._preview_min_total_px
        ):
            return
        self._bottom_min_px = new_bottom
        self._preview_min_total_px = new_preview
        # 默认比例未应用时无需立即重算（首次应用即用新下限）；
        # 已应用时安排一轮延迟更新把新下限补钳到现有几何上。
        if self._defaults_applied:
            self._schedule_layout_update()

    def apply_default_ratios(self, animated: bool = False) -> None:
        """应用当前模式的默认比例（首次布局 / 布局切换 / 用户重置时调用）。

        - workspace：左 1/3、预览画布 16:9（受半高上限与底行下限钳制）、底行 50:50；
        - classic：三栏 1:1:1、右栏各半、信息区 ≤ 半高；
        - 同时把「右竖条用户拖拽」状态复位（恢复自动 16:9）。

        Args:
            animated: True 时用 :data:`RESET_ANIM_DURATION_MS` 的渐变把各区尺寸
                从当前值平滑移到默认值（用户点「重置布局」路径）；False 时立即
                应用（首次布局 / 布局切换路径，避免启动与切布局时出现过渡）。
        """
        self._right_user_dragged = False
        if animated:
            self._animate_default_ratios()
            return
        if self.mode == WORKSPACE_MODE:
            self._apply_workspace_ratios(force=True)
        else:
            self._apply_classic_ratios(force=True)

    # ── 内部：重置布局渐变 ───────────────────────────────────────────

    def _default_target_sizes(self) -> Optional[Dict[str, list]]:
        """按当前几何算出当前模式各 splitter 的默认尺寸（仅计算，不应用）。

        预览区高度依赖右区宽度，此处由主横条默认比例直接推得（与 ``_apply_*``
        先 ``setSizes(main)`` 再读右区几何的结果一致）；右区高度与底行宽度在
        渐变过程中不随其它轴变化，故可一次算全。
        """
        if self.width() <= 0 or self.height() <= 0:
            return None
        right = self.splitters["right"]
        if self.mode == WORKSPACE_MODE:
            avail_w = max(0, self.width() - HANDLE_WIDTH)
            left_w = default_left_width(self.width())
            right_w = max(0, avail_w - left_w)
            v_avail = max(0, (right.height() or self.height()) - HANDLE_WIDTH)
            preview_h = self._preview_height_for(right_w, v_avail)
            bottom_avail = max(0, right_w - HANDLE_WIDTH)
            pool_w = int(round(bottom_avail * WORKSPACE_POOL_RATIO))
            return {
                "main": [left_w, right_w],
                "right": [preview_h, max(0, v_avail - preview_h)],
                "bottom": [pool_w, max(0, bottom_avail - pool_w)],
            }
        avail_w = max(0, self.width() - 2 * HANDLE_WIDTH)
        third = default_left_width(self.width())
        right_h = right.height()
        if right_h <= 0:
            right_h = max(0, self.height() - CLASSIC_ACTION_SLOT_PX - 2 * HANDLE_WIDTH)
        v_avail = max(0, right_h - HANDLE_WIDTH)
        if v_avail <= 0:
            return {"main": [third, third, avail_w - 2 * third], "right": [1, 1]}
        half = v_avail // 2
        return {
            "main": [third, third, avail_w - 2 * third],
            "right": [v_avail - half, half],
        }

    def _animate_default_ratios(self) -> None:
        """把各 splitter 尺寸从当前值渐变到默认值（用户重置布局路径）。"""
        targets = self._default_target_sizes()
        if targets is None:
            return
        starts = {
            name: self.splitters[name].sizes()
            for name in targets
            if self.splitters[name].count() == len(targets[name])
        }
        if len(starts) != len(targets):
            # 几何/子项未就绪：退化为立即应用，避免插值下标错位
            self.apply_default_ratios()
            return

        self._stop_reset_animation()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(RESET_ANIM_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.valueChanged.connect(
            lambda progress: self._apply_reset_progress(starts, targets, float(progress))
        )
        anim.finished.connect(self._on_reset_anim_finished)
        self._reset_anim = anim
        anim.start()

    def _apply_reset_progress(self, starts, targets, progress: float) -> None:
        """渐变逐帧：按进度 ``progress``（0~1）插值各 splitter 尺寸并应用。"""
        self._applying = True
        try:
            for name, target in targets.items():
                splitter = self.splitters[name]
                if splitter.count() != len(target):
                    continue
                src = starts[name]
                splitter.setSizes([
                    int(round(src[i] + (target[i] - src[i]) * progress))
                    for i in range(len(target))
                ])
        finally:
            self._applying = False

    def _stop_reset_animation(self) -> None:
        """停止进行中的渐变（用户开始拖拽 / 发起新一次重置时调用）。"""
        anim = self._reset_anim
        if anim is None:
            return
        self._reset_anim = None
        anim.stop()
        anim.deleteLater()

    def _on_reset_anim_finished(self) -> None:
        """渐变结束：落到精确默认尺寸（消除逐帧取整误差）。"""
        anim = self._reset_anim
        self._reset_anim = None
        if anim is not None:
            anim.deleteLater()
        if self.mode == WORKSPACE_MODE:
            self._apply_workspace_ratios(force=True)
        else:
            self._apply_classic_ratios(force=True)

    # ── 事件 ─────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:  # noqa: N802
        """尺寸变化：首次几何就绪时应用默认比例；之后维持 16:9 与半高上限。

        维护路径经 ``singleShot(0)`` 合并延迟执行：resizeEvent 到达时子控件
        几何尚未随新尺寸刷新，延迟到事件循环下一轮读取到的才是最终值。
        """
        super().resizeEvent(event)
        if self.width() <= 0 or self.height() <= 0:
            return
        if not self._defaults_applied:
            # 几何首次就绪：应用默认比例（置位 _defaults_applied）
            if self.mode == WORKSPACE_MODE:
                self._apply_workspace_ratios(force=True)
            else:
                self._apply_classic_ratios(force=True)
            return
        self._schedule_layout_update()

    def showEvent(self, event) -> None:  # noqa: N802
        """显示/重新显示：子控件的最大高度约束会被 show 重置，需重新应用。

        实测（Qt 6.10 / Windows）：在隐藏状态下对嵌套 splitter 子控件
        ``setMaximumHeight``，随后的 ``show()``（含 hide→show）会把它重置回
        默认值。因此每次显示后都安排一次比例/上限更新（幂等）。
        """
        super().showEvent(event)
        if self.width() > 0 and self.height() > 0:
            self._schedule_layout_update()

    def _schedule_layout_update(self) -> None:
        """合并调度一次延迟比例更新（防抖：相邻 resize 只算最后一轮）。"""
        if self._ratio_update_pending:
            return
        self._ratio_update_pending = True
        QTimer.singleShot(0, self._run_layout_update)

    def _run_layout_update(self) -> None:
        """延迟回调：按最新几何维持 16:9（自动态）并重算半高上限。"""
        self._ratio_update_pending = False
        # 重置渐变进行中：逐帧尺寸由动画负责，避免与自动 16:9 互相覆盖；
        # 渐变结束时 _on_reset_anim_finished 会按最新几何重新落位。
        if self._reset_anim is not None:
            return
        if self.mode == WORKSPACE_MODE and not self._right_user_dragged:
            self._apply_workspace_ratios(force=False)
        self._ensure_bottom_cap()

    # ── 内部：拖拽回调 ───────────────────────────────────────────────

    def _on_right_splitter_moved(self, _pos: int, _index: int) -> None:
        """右竖条被用户拖拽：停止进行中的重置渐变，并补钳制（幂等）。"""
        self._stop_reset_animation()
        self._right_user_dragged = True
        self._ensure_bottom_cap(force=True)

    def _on_bottom_splitter_moved(self, _pos: int, _index: int) -> None:
        """底行（workspace）或信息区（classic）被用户拖拽：停止渐变并补钳制。"""
        self._stop_reset_animation()
        self._ensure_bottom_cap(force=True)

    def _on_main_splitter_moved(self, _pos: int, _index: int) -> None:
        """主横条被用户拖拽：停止进行中的重置渐变；右区宽度变化，未拖拽右竖条
        时同步 16:9。"""
        self._stop_reset_animation()
        if self.mode == WORKSPACE_MODE and not self._right_user_dragged:
            self._apply_workspace_ratios(force=False)
        self._ensure_bottom_cap()

    # ── 内部：比例计算 ───────────────────────────────────────────────

    def _apply_workspace_ratios(self, force: bool = False) -> None:
        """应用/维持 workspace 比例（幂等；``force`` 时同步主横条与底行比例）。

        Args:
            force: True 表示首次应用或布局切换（重置主横条/底行比例并置位）；
                False 表示窗口缩放/主横条拖拽维护路径（仅重算右侧 16:9）。
        """
        if self._applying:
            return
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        self._applying = True
        try:
            main = self.splitters["main"]
            right = self.splitters["right"]
            bottom = self.splitters["bottom"]

            # 1) 主横条：左 1/3（首次/强制时应用；窗口缩放不打扰用户分栏）。
            #    宽度口径与 classic 复用 default_left_width（两布局选择器
            #    逐像素一致；旧 round 公式比经典宽 3~4px，切换可见错位）。
            avail_w = max(0, width - HANDLE_WIDTH)
            left_w = default_left_width(width)
            right_w = max(0, avail_w - left_w)
            if force:
                main.setSizes([left_w, right_w])
            else:
                size_now = right.width()
                if size_now > 0:
                    right_w = size_now

            # 2) 右竖条：预览区 16:9（受半高上限/底行下限钳制）
            v_avail = right.height() if right.height() > 0 else height
            v_avail = max(0, v_avail - HANDLE_WIDTH)
            preview_h = self._preview_height_for(right_w, v_avail)
            right_sizes = right.sizes()
            if (
                len(right_sizes) == 2
                and abs(right_sizes[0] - preview_h) <= 2
                and abs(right_sizes[1] - (v_avail - preview_h)) <= 2
                and not force
            ):
                pass  # 与当前一致：跳过，避免拖拽路径上的无谓 setSizes
            else:
                right.setSizes([preview_h, max(0, v_avail - preview_h)])

            # 3) 底行：储存 55 : 信息 45（首次/强制时应用）。
            #    必须传实际像素而非小数值比例：QSplitter 在 setSizes 数值和
            #    远小于可用宽度、且子控件带最小宽度（真实储存池约 324px）时，
            #    不会按比例缩放（实测会把多余空间几乎全给第一个子项）。
            if force:
                bottom_avail = max(0, right_w - HANDLE_WIDTH)
                pool_w = int(round(bottom_avail * WORKSPACE_POOL_RATIO))
                bottom.setSizes([pool_w, max(0, bottom_avail - pool_w)])

            self._defaults_applied = True
            # 4) 半高上限
            self._ensure_bottom_cap()
        finally:
            self._applying = False

    def _preview_height_for(self, right_w: int, v_avail: int) -> int:
        """计算 16:9 预览区高度（含钳制与降级）。

        约束：
        - 预览 ≥ 半高（``v_avail - v_avail // 2`` 向上取整）→ 底行 ≤ ceil(v_avail / 2)；
        - 预览 ≥ ``_preview_min_total_px``（workspace 预览器最小总高，叶子下发）；
        - 底行 ≥ ``_bottom_min_px`` → preview_h ≤ v_avail - _bottom_min_px；
        - 冲突（窗口过矮）时下限优先；主窗口最小尺寸已保证正常不冲突
          （见 ``MainWindow._apply_window_minimums``）。
        """
        v_avail = max(0, v_avail)
        lower = max(v_avail - v_avail // 2, self._preview_min_total_px)
        target = int(round(right_w * PREVIEW_ASPECT)) + int(PREVIEW_CHROME_PX)
        upper = v_avail - self._bottom_min_px
        if upper < lower:
            preview_h = lower
        else:
            preview_h = max(lower, min(target, upper))
        return max(0, min(v_avail, preview_h))

    def _apply_classic_ratios(self, force: bool = False) -> None:
        """应用 classic 比例：三栏 1:1:1、右竖条各半、信息区 ≤ 半高。"""
        if self._applying:
            return
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        self._applying = True
        try:
            main = self.splitters["main"]
            right = self.splitters["right"]
            if force:
                avail_w = max(0, width - 2 * HANDLE_WIDTH)
                third = default_left_width(width)
                main.setSizes([third, third, avail_w - 2 * third])
                # 右分割区高度：优先取实际几何；几何未就绪时按
                # 「容器高 - 底部操作栏槽位 - 槽位间距 - 分隔条」估算
                right_h = right.height()
                if right_h <= 0:
                    right_h = max(
                        0,
                        height - CLASSIC_ACTION_SLOT_PX - 2 * HANDLE_WIDTH,
                    )
                v_avail = max(0, right_h - HANDLE_WIDTH)
                if v_avail > 0:
                    half = v_avail // 2
                    right.setSizes([v_avail - half, half])
                else:
                    right.setSizes([1, 1])
            self._defaults_applied = True
            self._ensure_bottom_cap()
        finally:
            self._applying = False

    # ── 内部：半高上限 ───────────────────────────────────────────────

    def _ensure_bottom_cap(self, force: bool = False) -> None:
        """把底行（workspace）或信息区（classic）限制在右区可用高度一半内。

        - workspace：上限打在底行 splitter 上（储存 + 信息整体 ≤ 半高）；
        - classic：上限打在信息区 frame 上（与历史 ``_content_bottom`` 语义一致）；
        - 节流：半高变化 <=2px 且未超限时跳过 maximumHeight/setSizes 重写，
          避免拖拽每帧递归触发布局。
        """
        right = self.splitters["right"]
        if right.height() > 0:
            right_h = right.height()
        elif self.mode == WORKSPACE_MODE:
            # workspace：右竖条基本占满容器高度，整窗高即右列高
            right_h = self.height()
        else:
            # classic：整窗高 - 底部操作栏槽位 - 槽位与内容区间距（HANDLE_WIDTH）
            right_h = max(0, self.height() - CLASSIC_ACTION_SLOT_PX - HANDLE_WIDTH)
        v_avail = max(0, right_h - HANDLE_WIDTH)
        if v_avail <= 0:
            return
        half = v_avail // 2
        target: QWidget = (
            self.splitters["bottom"] if self.mode == WORKSPACE_MODE else self.zones["info"]
        )
        over = target.height() > half
        # 节流：半高基本未变、未超限、且上限确已生效时才跳过。
        # 必须校验 maximumHeight（show 会重置隐藏期设置的约束，见 showEvent）。
        if (
            not force
            and abs(half - self._last_half) <= 2
            and not over
            and target.maximumHeight() == half
        ):
            return
        self._last_half = half
        if target.maximumHeight() != half:
            target.setMaximumHeight(half)
        if over and right.count() == 2:
            right.setSizes([v_avail - half, half])

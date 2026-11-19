"""快捷键动作注册表 —— 全部键位的唯一事实来源。

本模块只含**纯数据**（``ActionSpec`` 与 ``ACTION_SPECS``），不导入任何
Qt Widget，也不涉及派发逻辑，因此可无 ``QApplication`` 单测。

作用域（``Region``）
====================
派发按「全局层 → 区域层」两段查表：

- ``global``：任何位置都生效（含全屏、含弹窗）。仅 4 个动作。
- ``app``：主窗口内、无更具体区域命中时生效（焦点区切换）。
- 其余：焦点归属决定（见 ``dispatcher.py`` 的区域栈）。

``also_in`` 用于「同一动作在多个区域生效」。典型是全屏：全屏时焦点不在
预览器子控件里（宿主是独立顶层窗口），但按键语义与内嵌时完全相同，因此
所有 ``preview.*`` 动作都声明 ``also_in=("fullscreen",)``。

``repeat`` 三种策略
===================
- ``none``：按下一次触发一次。
- ``auto``：交给 Qt autoRepeat，长按连续触发（seek / 音量）。
- ``long_press``：区分短按与长按（倍速键），见 ``dispatcher._LongPressState``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: 所有可用区域。
Region = Literal[
    "global",
    "app",
    "path",
    "selector",
    "pool",
    "info",
    "preview.image",
    "preview.pdf",
    "preview.text",
    "preview.font",
    "preview.archive",
    "preview.folder",
    "preview.media",
    "preview.unsupported",
    "fullscreen",
    "settings",
]

#: 重复策略。
RepeatPolicy = Literal["none", "auto", "long_press"]


@dataclass(frozen=True)
class ActionSpec:
    """一个可绑定动作的静态定义（键位固定，无用户配置）。

    Attributes:
        action_id: 全局唯一 id，命名空间用点号（如 ``selector.refresh``）。
        title: 中文显示名（用于 README 生成与调试日志）。
        region: 生效区域。
        default_keys: ``QKeySequence`` 可移植文本列表；空元组表示无默认键。
        repeat: 重复策略。
        long_press_ms: ``long_press`` 策略的阈值（毫秒）。
        also_in: 额外生效区域（不得包含 ``region`` 自身）。
        works_in_context: 弹层打开时仍派发（仅限「再次按下关闭」的开关动作）。
        works_in_menu: ``QMenu`` 打开时仍派发（仅排序菜单这类由快捷键打开的
            菜单；其余动作在菜单打开时一律阻断以保护 type-ahead）。
        description: 一行行为说明。
    """

    action_id: str
    title: str
    region: Region
    default_keys: tuple[str, ...] = ()
    repeat: RepeatPolicy = "none"
    long_press_ms: int = 350
    also_in: tuple[Region, ...] = ()
    works_in_context: bool = False
    works_in_menu: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.action_id or "." not in self.action_id:
            raise ValueError(
                f"action_id 必须含命名空间（形如 'selector.refresh'）: {self.action_id!r}"
            )
        if self.repeat == "long_press" and self.long_press_ms <= 0:
            raise ValueError(
                f"{self.action_id}: repeat='long_press' 时 long_press_ms 必须 > 0"
            )
        if self.region in self.also_in:
            raise ValueError(
                f"{self.action_id}: region 不能出现在 also_in 中（重复声明）"
            )
        for region in self.also_in:
            if region == "global":
                raise ValueError(
                    f"{self.action_id}: also_in 不应包含 'global'（全局层独立派发）"
                )


#: 全屏也生效的预览器动作统一声明。
_FS = ("fullscreen",)

#: 全屏切换键的生效区域：任何焦点位置都能触发（用户要求）。
#:
#: 除预览器自身与全屏区域外，还覆盖 app / selector / pool / info / path，
#: 这样焦点在文件列表或路径框时也能直接按 ``Ctrl+\\`` 进出全屏。
_FS_TOGGLE_IN = ("fullscreen", "app", "selector", "pool", "info", "path")


# ─────────────────────────────────────────────────────────────────────
# 全局层（4 条）
# ─────────────────────────────────────────────────────────────────────
_GLOBAL_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="global.open_settings",
        title="打开设置",
        region="global",
        default_keys=("Ctrl+I",),
        description="打开设置窗口；已打开时关闭（任何弹层存在时静默）",
    ),
    ActionSpec(
        action_id="global.open_in_explorer",
        title="在资源管理器中打开",
        region="global",
        default_keys=("Ctrl+M",),
        description="用系统文件资源管理器打开并选中当前文件",
    ),
    ActionSpec(
        action_id="global.open_with_default",
        title="使用默认方式打开",
        region="global",
        default_keys=("Ctrl+K",),
        description="调用系统默认程序打开当前文件",
    ),
    ActionSpec(
        action_id="global.locate_in_app",
        title="在应用内定位",
        region="global",
        default_keys=("Ctrl+O",),
        description="跳转文件选择器并高亮当前文件所在目录",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 焦点区切换（4 条）
# ─────────────────────────────────────────────────────────────────────
_NAV_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="nav.next_zone",
        title="下一个区域",
        region="app",
        default_keys=("Ctrl+Right", "Ctrl+Down"),
        description="按当前布局顺序把焦点移到下一个区域",
    ),
    ActionSpec(
        action_id="nav.prev_zone",
        title="上一个区域",
        region="app",
        default_keys=("Ctrl+Left", "Ctrl+Up"),
        description="按当前布局顺序把焦点移到上一个区域",
    ),
    ActionSpec(
        action_id="nav.next_zone_f6",
        title="下一个区域（备用）",
        region="app",
        default_keys=("F6",),
        description="可访问性备用键，等价于 Ctrl+Right",
    ),
    ActionSpec(
        action_id="nav.prev_zone_f6",
        title="上一个区域（备用）",
        region="app",
        default_keys=("Shift+F6",),
        description="可访问性备用键，等价于 Ctrl+Left",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 文件选择器（26 条）
# ─────────────────────────────────────────────────────────────────────
_SELECTOR_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="selector.nav_up",
        title="上一个",
        region="selector",
        default_keys=("Up",),
        repeat="auto",
        description="切换预览到上一个条目（含文件夹），松开才加载预览",
    ),
    ActionSpec(
        action_id="selector.nav_down",
        title="下一个",
        region="selector",
        default_keys=("Down",),
        repeat="auto",
        description="切换预览到下一个条目（含文件夹），松开才加载预览",
    ),
    ActionSpec(
        action_id="selector.nav_left",
        title="前一个",
        region="selector",
        default_keys=("Left",),
        repeat="auto",
        description="按文件序切换到前一个条目",
    ),
    ActionSpec(
        action_id="selector.nav_right",
        title="后一个",
        region="selector",
        default_keys=("Right",),
        repeat="auto",
        description="按文件序切换到后一个条目",
    ),
    ActionSpec(
        action_id="selector.enter",
        title="进入文件夹 / 预览并移交焦点",
        region="selector",
        default_keys=("Return", "Enter"),
        description="文件夹进入；文件在应用内预览并把焦点交给预览器；批量态下不执行任何操作",
    ),
    ActionSpec(
        action_id="selector.toggle_pool",
        title="加入 / 移出储存池",
        region="selector",
        default_keys=("Tab",),
        description="把当前光标卡片加入或移出储存池；批量态一次性把选中项全部加入储存池",
    ),
    ActionSpec(
        action_id="selector.play_pause",
        title="播放 / 暂停",
        region="selector",
        default_keys=("Space",),
        description="当前预览为音视频时播放或暂停",
    ),
    ActionSpec(
        action_id="selector.speed_1",
        title="1x 倍速",
        region="selector",
        default_keys=("1",),
        repeat="long_press",
        description="短按切到 1x；长按期间临时 1x，松开恢复",
    ),
    ActionSpec(
        action_id="selector.speed_2",
        title="2x 倍速",
        region="selector",
        default_keys=("2",),
        repeat="long_press",
        description="短按切到 2x；长按期间临时 2x，松开恢复",
    ),
    ActionSpec(
        action_id="selector.speed_3",
        title="3x 倍速",
        region="selector",
        default_keys=("3",),
        repeat="long_press",
        description="短按切到 3x；长按期间临时 3x，松开恢复",
    ),
    ActionSpec(
        action_id="selector.speed_half",
        title="0.5x 倍速",
        region="selector",
        default_keys=("`",),
        repeat="long_press",
        description="短按切到 0.5x；长按期间临时 0.5x，松开恢复",
    ),
    ActionSpec(
        action_id="selector.seek_back",
        title="后退 5 秒",
        region="selector",
        default_keys=("Shift+Left",),
        repeat="auto",
        description="当前预览为音视频时后退 5 秒（长按连续）",
    ),
    ActionSpec(
        action_id="selector.seek_forward",
        title="前进 5 秒",
        region="selector",
        default_keys=("Shift+Right",),
        repeat="auto",
        description="当前预览为音视频时前进 5 秒（长按连续）",
    ),
    ActionSpec(
        action_id="selector.volume_up",
        title="音量 +",
        region="selector",
        default_keys=("Shift+Up",),
        repeat="auto",
        description="当前预览为音视频时音量 +5（长按连续）",
    ),
    ActionSpec(
        action_id="selector.volume_down",
        title="音量 −",
        region="selector",
        default_keys=("Shift+Down",),
        repeat="auto",
        description="当前预览为音视频时音量 −5（长按连续）",
    ),
    ActionSpec(
        action_id="selector.batch_up",
        title="批量选择（上）",
        region="selector",
        default_keys=("Alt+Up",),
        repeat="auto",
        description="进入批量选择并向上移动一格；经过的卡片被选中",
    ),
    ActionSpec(
        action_id="selector.batch_down",
        title="批量选择（下）",
        region="selector",
        default_keys=("Alt+Down",),
        repeat="auto",
        description="进入批量选择并向下移动一格",
    ),
    ActionSpec(
        action_id="selector.batch_left",
        title="批量选择（左）",
        region="selector",
        default_keys=("Alt+Left",),
        repeat="auto",
        description="进入批量选择并向左移动一格",
    ),
    ActionSpec(
        action_id="selector.batch_right",
        title="批量选择（右）",
        region="selector",
        default_keys=("Alt+Right",),
        repeat="auto",
        description="进入批量选择并向右移动一格",
    ),
    ActionSpec(
        action_id="selector.filter",
        title="筛选",
        region="selector",
        default_keys=("Ctrl+F",),
        works_in_context=True,
        also_in=("app", "fullscreen", "pool", "info"),
        description="按文件名正则筛选当前目录",
    ),
    ActionSpec(
        action_id="selector.favorites",
        title="收藏夹",
        region="selector",
        default_keys=("Ctrl+G",),
        also_in=("app", "fullscreen", "pool", "info"),
        works_in_context=True,
        description="打开路径收藏夹；已打开时再按关闭",
    ),
    ActionSpec(
        action_id="selector.refresh",
        title="刷新",
        region="selector",
        default_keys=("Ctrl+H",),
        also_in=("app", "fullscreen", "pool", "info"),
        description="重新扫描当前目录",
    ),
    ActionSpec(
        action_id="selector.sort_menu",
        title="排序",
        region="selector",
        default_keys=("Ctrl+L",),
        also_in=("app", "fullscreen", "pool", "info"),
        works_in_context=True,
        works_in_menu=True,
        description="打开排序菜单；已打开时再按关闭，关闭后焦点回到文件列表",
    ),
    ActionSpec(
        action_id="selector.gen_thumbs",
        title="生成缩略图",
        region="selector",
        default_keys=("Q",),
        description="为当前路径下所有可生成缩略图的文件生成缩略图",
    ),
    ActionSpec(
        action_id="selector.clear_thumbs",
        title="清除缩略图",
        region="selector",
        default_keys=("Shift+Q",),
        description="清除当前路径下所有文件的缩略图缓存",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 文件储存池（21 条）
# ─────────────────────────────────────────────────────────────────────
_POOL_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="pool.nav_up",
        title="上一个",
        region="pool",
        default_keys=("Up",),
        repeat="auto",
        description="按视觉顺序切到上一个卡片",
    ),
    ActionSpec(
        action_id="pool.nav_down",
        title="下一个",
        region="pool",
        default_keys=("Down",),
        repeat="auto",
        description="按视觉顺序切到下一个卡片",
    ),
    ActionSpec(
        action_id="pool.nav_left",
        title="前一个",
        region="pool",
        default_keys=("Left",),
        repeat="auto",
        description="按视觉顺序切到前一个卡片",
    ),
    ActionSpec(
        action_id="pool.nav_right",
        title="后一个",
        region="pool",
        default_keys=("Right",),
        repeat="auto",
        description="按视觉顺序切到后一个卡片",
    ),
    ActionSpec(
        action_id="pool.enter",
        title="预览",
        region="pool",
        default_keys=("Return", "Enter"),
        description="预览当前卡片并把焦点交给预览器；批量态下不执行任何操作（批量移出统一用 Tab）",
    ),
    ActionSpec(
        action_id="pool.toggle_pool",
        title="移出储存池 / 批量移出",
        region="pool",
        default_keys=("Tab",),
        description="把当前卡片移出储存池；批量态下一次移出全部选中项（需确认）",
    ),
    ActionSpec(
        action_id="pool.play_pause",
        title="播放 / 暂停",
        region="pool",
        default_keys=("Space",),
        description="当前预览为音视频时播放或暂停",
    ),
    ActionSpec(
        action_id="pool.speed_1",
        title="1x 倍速",
        region="pool",
        default_keys=("1",),
        repeat="long_press",
        description="短按切到 1x；长按临时 1x",
    ),
    ActionSpec(
        action_id="pool.speed_2",
        title="2x 倍速",
        region="pool",
        default_keys=("2",),
        repeat="long_press",
        description="短按切到 2x；长按临时 2x",
    ),
    ActionSpec(
        action_id="pool.speed_3",
        title="3x 倍速",
        region="pool",
        default_keys=("3",),
        repeat="long_press",
        description="短按切到 3x；长按临时 3x",
    ),
    ActionSpec(
        action_id="pool.speed_half",
        title="0.5x 倍速",
        region="pool",
        default_keys=("`",),
        repeat="long_press",
        description="短按切到 0.5x；长按临时 0.5x",
    ),
    ActionSpec(
        action_id="pool.seek_back",
        title="后退 5 秒",
        region="pool",
        default_keys=("Shift+Left",),
        repeat="auto",
        description="当前预览为音视频时后退 5 秒",
    ),
    ActionSpec(
        action_id="pool.seek_forward",
        title="前进 5 秒",
        region="pool",
        default_keys=("Shift+Right",),
        repeat="auto",
        description="当前预览为音视频时前进 5 秒",
    ),
    ActionSpec(
        action_id="pool.volume_up",
        title="音量 +",
        region="pool",
        default_keys=("Shift+Up",),
        repeat="auto",
        description="当前预览为音视频时音量 +5",
    ),
    ActionSpec(
        action_id="pool.volume_down",
        title="音量 −",
        region="pool",
        default_keys=("Shift+Down",),
        repeat="auto",
        description="当前预览为音视频时音量 −5",
    ),
    ActionSpec(
        action_id="pool.batch_up",
        title="批量选择（上）",
        region="pool",
        default_keys=("Alt+Up",),
        repeat="auto",
        description="进入批量选择并向上移动一格",
    ),
    ActionSpec(
        action_id="pool.batch_down",
        title="批量选择（下）",
        region="pool",
        default_keys=("Alt+Down",),
        repeat="auto",
        description="进入批量选择并向下移动一格",
    ),
    ActionSpec(
        action_id="pool.batch_left",
        title="批量选择（左）",
        region="pool",
        default_keys=("Alt+Left",),
        repeat="auto",
        description="进入批量选择并向左移动一格",
    ),
    ActionSpec(
        action_id="pool.batch_right",
        title="批量选择（右）",
        region="pool",
        default_keys=("Alt+Right",),
        repeat="auto",
        description="进入批量选择并向右移动一格",
    ),
    ActionSpec(
        action_id="pool.gen_thumbs",
        title="生成缩略图",
        region="pool",
        default_keys=("Q",),
        description="为池内全部文件生成缩略图",
    ),
    ActionSpec(
        action_id="pool.clear_thumbs",
        title="清除缩略图",
        region="pool",
        default_keys=("Shift+Q",),
        description="清除池内全部文件的缩略图缓存",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 文件信息面板（4 条）
# ─────────────────────────────────────────────────────────────────────
_INFO_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="info.nav_up",
        title="上一条目",
        region="info",
        default_keys=("Up",),
        repeat="auto",
        description="在可复制条目间向上移动",
    ),
    ActionSpec(
        action_id="info.nav_down",
        title="下一条目",
        region="info",
        default_keys=("Down",),
        repeat="auto",
        description="在可复制条目间向下移动",
    ),
    ActionSpec(
        action_id="info.copy_current",
        title="复制当前条目",
        region="info",
        default_keys=("Return", "Enter"),
        description="复制当前高亮条目的值",
    ),
    ActionSpec(
        action_id="info.copy_all",
        title="复制全部信息",
        region="info",
        default_keys=("Ctrl+Return", "Ctrl+Enter"),
        description="复制当前文件的全部信息（哈希未完成项标注「计算中」）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 视频 / 音频（11 条）
# ─────────────────────────────────────────────────────────────────────
_MEDIA_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.media.play_pause",
        title="播放 / 暂停",
        region="preview.media",
        default_keys=("Space",),
        also_in=_FS,
        description="切换播放与暂停，并显示 OSD",
    ),
    ActionSpec(
        action_id="preview.media.seek_back",
        title="后退 5 秒",
        region="preview.media",
        default_keys=("Left",),
        repeat="auto",
        also_in=_FS,
        description="后退 5 秒（长按连续）",
    ),
    ActionSpec(
        action_id="preview.media.seek_forward",
        title="前进 5 秒",
        region="preview.media",
        default_keys=("Right",),
        repeat="auto",
        also_in=_FS,
        description="前进 5 秒（长按连续）",
    ),
    ActionSpec(
        action_id="preview.media.volume_up",
        title="音量 +",
        region="preview.media",
        default_keys=("Up",),
        repeat="auto",
        also_in=_FS,
        description="音量 +5（长按连续）",
    ),
    ActionSpec(
        action_id="preview.media.volume_down",
        title="音量 −",
        region="preview.media",
        default_keys=("Down",),
        repeat="auto",
        also_in=_FS,
        description="音量 −5（长按连续）",
    ),
    ActionSpec(
        action_id="preview.media.speed_1",
        title="1x 倍速",
        region="preview.media",
        default_keys=("1",),
        repeat="long_press",
        also_in=_FS,
        description="短按切到 1x；长按临时 1x，松开恢复",
    ),
    ActionSpec(
        action_id="preview.media.speed_2",
        title="2x 倍速",
        region="preview.media",
        default_keys=("2",),
        repeat="long_press",
        also_in=_FS,
        description="短按切到 2x；长按临时 2x，松开恢复",
    ),
    ActionSpec(
        action_id="preview.media.speed_3",
        title="3x 倍速",
        region="preview.media",
        default_keys=("3",),
        repeat="long_press",
        also_in=_FS,
        description="短按切到 3x；长按临时 3x，松开恢复",
    ),
    ActionSpec(
        action_id="preview.media.speed_half",
        title="0.5x 倍速",
        region="preview.media",
        default_keys=("`",),
        repeat="long_press",
        also_in=_FS,
        description="短按切到 0.5x；长按临时 0.5x，松开恢复",
    ),
    ActionSpec(
        action_id="preview.media.toggle_mute",
        title="静音切换",
        region="preview.media",
        default_keys=("M",),
        also_in=_FS,
        description="切换静音并显示 OSD",
    ),
    ActionSpec(
        action_id="preview.media.fullscreen",
        title="全屏",
        region="preview.media",
        default_keys=("Ctrl+\\",),
        also_in=_FS_TOGGLE_IN,
        description="进入 / 退出播放器全屏（对称切换）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 图像（11 条）
# ─────────────────────────────────────────────────────────────────────
_IMAGE_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.image.prev_file",
        title="上一个文件",
        region="preview.image",
        default_keys=("Left",),
        repeat="auto",
        also_in=_FS,
        description="切换到上一个文件（跳过文件夹，末尾环绕）",
    ),
    ActionSpec(
        action_id="preview.image.next_file",
        title="下一个文件",
        region="preview.image",
        default_keys=("Right",),
        repeat="auto",
        also_in=_FS,
        description="切换到下一个文件（跳过文件夹，末尾环绕）",
    ),
    ActionSpec(
        action_id="preview.image.zoom_in",
        title="放大",
        region="preview.image",
        default_keys=("+", "=", "Shift+="),
        repeat="auto",
        also_in=_FS,
        description="放大 10%（50%–500%）；主键盘 + 与小键盘 + 均生效",
    ),
    ActionSpec(
        action_id="preview.image.zoom_out",
        title="缩小",
        region="preview.image",
        default_keys=("-",),
        repeat="auto",
        also_in=_FS,
        description="缩小 10%（50%–500%）",
    ),
    ActionSpec(
        action_id="preview.image.zoom_fit",
        title="适应窗口",
        region="preview.image",
        default_keys=("0",),
        also_in=_FS,
        description="恢复 100%（适应窗口）",
    ),
    ActionSpec(
        action_id="preview.image.rotate_cw",
        title="顺时针旋转",
        region="preview.image",
        default_keys=("R",),
        also_in=_FS,
        description="顺时针旋转 90°",
    ),
    ActionSpec(
        action_id="preview.image.flip_h",
        title="水平翻转",
        region="preview.image",
        default_keys=("H",),
        also_in=_FS,
        description="水平翻转",
    ),
    ActionSpec(
        action_id="preview.image.flip_v",
        title="垂直翻转",
        region="preview.image",
        default_keys=("V",),
        also_in=_FS,
        description="垂直翻转",
    ),
    ActionSpec(
        action_id="preview.image.color_picker",
        title="取色器",
        region="preview.image",
        default_keys=("I",),
        also_in=_FS,
        description="进入 / 退出取色模式",
    ),
    ActionSpec(
        action_id="preview.image.gif_toggle",
        title="GIF 播放 / 暂停",
        region="preview.image",
        default_keys=("Space",),
        also_in=_FS,
        description="GIF 动图播放或暂停",
    ),
    ActionSpec(
        action_id="preview.image.fullscreen",
        title="全屏",
        region="preview.image",
        default_keys=("Ctrl+\\",),
        also_in=_FS_TOGGLE_IN,
        description="进入 / 退出全屏（对称切换）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# PDF（10 条）
# ─────────────────────────────────────────────────────────────────────
_PDF_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.pdf.scroll_up",
        title="上翻",
        region="preview.pdf",
        default_keys=("Up",),
        repeat="auto",
        also_in=_FS,
        description="向上翻动视口高度的 80%",
    ),
    ActionSpec(
        action_id="preview.pdf.scroll_down",
        title="下翻",
        region="preview.pdf",
        default_keys=("Down",),
        repeat="auto",
        also_in=_FS,
        description="向下翻动视口高度的 80%",
    ),
    ActionSpec(
        action_id="preview.pdf.page_prev",
        title="上一页",
        region="preview.pdf",
        default_keys=("PgUp",),
        also_in=_FS,
        description="跳到上一页",
    ),
    ActionSpec(
        action_id="preview.pdf.page_next",
        title="下一页",
        region="preview.pdf",
        default_keys=("PgDown",),
        also_in=_FS,
        description="跳到下一页",
    ),
    ActionSpec(
        action_id="preview.pdf.zoom_in",
        title="放大",
        region="preview.pdf",
        default_keys=("+", "=", "Shift+="),
        repeat="auto",
        also_in=_FS,
        description="放大（×1.1）",
    ),
    ActionSpec(
        action_id="preview.pdf.zoom_out",
        title="缩小",
        region="preview.pdf",
        default_keys=("-",),
        repeat="auto",
        also_in=_FS,
        description="缩小（÷1.1）",
    ),
    ActionSpec(
        action_id="preview.pdf.zoom_reset",
        title="重置缩放",
        region="preview.pdf",
        default_keys=("0",),
        also_in=_FS,
        description="适应页宽",
    ),
    ActionSpec(
        action_id="preview.pdf.toggle_index",
        title="索引抽屉",
        region="preview.pdf",
        default_keys=("Shift+F", "Ctrl+Shift+F"),
        works_in_context=True,
        also_in=_FS_TOGGLE_IN,
        description="打开 / 关闭缩略图索引抽屉",
    ),
    ActionSpec(
        action_id="preview.pdf.copy_selection",
        title="复制选中文字",
        region="preview.pdf",
        default_keys=("Ctrl+C",),
        also_in=_FS,
        description="复制 PDF 中选中的文字（无选区时放行）",
    ),
    ActionSpec(
        action_id="preview.pdf.fullscreen",
        title="全屏",
        region="preview.pdf",
        default_keys=("Ctrl+\\",),
        also_in=_FS_TOGGLE_IN,
        description="进入 / 退出全屏（对称切换）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 文本 / 代码（8 条）
# ─────────────────────────────────────────────────────────────────────
_TEXT_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.text.scroll_up",
        title="上翻",
        region="preview.text",
        default_keys=("Up",),
        repeat="auto",
        also_in=_FS,
        description="向上翻动视口高度的 80%",
    ),
    ActionSpec(
        action_id="preview.text.scroll_down",
        title="下翻",
        region="preview.text",
        default_keys=("Down",),
        repeat="auto",
        also_in=_FS,
        description="向下翻动视口高度的 80%",
    ),
    ActionSpec(
        action_id="preview.text.font_up",
        title="字号 +",
        region="preview.text",
        default_keys=("+", "=", "Shift+="),
        repeat="auto",
        also_in=_FS,
        description="字号 +1（8–32px）",
    ),
    ActionSpec(
        action_id="preview.text.font_down",
        title="字号 −",
        region="preview.text",
        default_keys=("-",),
        repeat="auto",
        also_in=_FS,
        description="字号 −1（8–32px）",
    ),
    ActionSpec(
        action_id="preview.text.font_reset",
        title="重置字号",
        region="preview.text",
        default_keys=("Ctrl+0",),
        also_in=_FS,
        description="恢复默认字号",
    ),
    ActionSpec(
        action_id="preview.text.toggle_search",
        title="搜索抽屉",
        region="preview.text",
        default_keys=("Shift+F", "Ctrl+Shift+F"),
        works_in_context=True,
        also_in=_FS_TOGGLE_IN,
        description="打开 / 关闭站内搜索抽屉",
    ),
    ActionSpec(
        action_id="preview.text.toggle_render",
        title="源码 / 渲染切换",
        region="preview.text",
        default_keys=("Ctrl+E",),
        also_in=_FS,
        description="在源码视图与 Markdown 渲染视图之间切换",
    ),
    ActionSpec(
        action_id="preview.text.fullscreen",
        title="全屏",
        region="preview.text",
        default_keys=("Ctrl+\\",),
        also_in=_FS_TOGGLE_IN,
        description="进入 / 退出全屏（对称切换）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 字体（5 条）
# ─────────────────────────────────────────────────────────────────────
_FONT_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.font.weight_down",
        title="字重 −",
        region="preview.font",
        default_keys=("Left",),
        repeat="auto",
        also_in=_FS,
        description="字重减小 100（100–900）",
    ),
    ActionSpec(
        action_id="preview.font.weight_up",
        title="字重 +",
        region="preview.font",
        default_keys=("Right",),
        repeat="auto",
        also_in=_FS,
        description="字重增加 100（100–900）",
    ),
    ActionSpec(
        action_id="preview.font.size_up",
        title="字号 +",
        region="preview.font",
        default_keys=("+", "=", "Shift+="),
        repeat="auto",
        also_in=_FS,
        description="字号 +1（8–32px）",
    ),
    ActionSpec(
        action_id="preview.font.size_down",
        title="字号 −",
        region="preview.font",
        default_keys=("-",),
        repeat="auto",
        also_in=_FS,
        description="字号 −1（8–32px）",
    ),
    ActionSpec(
        action_id="preview.font.fullscreen",
        title="全屏",
        region="preview.font",
        default_keys=("Ctrl+\\",),
        also_in=_FS_TOGGLE_IN,
        description="进入 / 退出全屏（对称切换）",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 压缩包（2 条）
# ─────────────────────────────────────────────────────────────────────
# 注：``Esc`` 返回包内上一级 / 退出搜索由 ``escape_handlers()`` 链处理，
# 不在此登记（``Esc`` 是上下文键，见 dispatcher 模块说明）。
_ARCHIVE_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.archive.toggle_search",
        title="搜索",
        region="preview.archive",
        default_keys=("Shift+F", "Ctrl+Shift+F"),
        works_in_context=True,
        also_in=_FS_TOGGLE_IN,
        description="打开 / 关闭全包搜索",
    ),
    ActionSpec(
        action_id="preview.archive.enter_dir",
        title="进入目录",
        region="preview.archive",
        default_keys=("Return", "Enter"),
        description="进入选中的目录条目",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# 文件夹（1 条）
# ─────────────────────────────────────────────────────────────────────
# 注：``Esc`` 返回上一级由 ``escape_handlers()`` 链处理。
_FOLDER_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action_id="preview.folder.enter_dir",
        title="进入子目录",
        region="preview.folder",
        default_keys=("Return", "Enter"),
        description="进入选中的子目录",
    ),
)


#: 全部动作（唯一事实来源）。
ACTION_SPECS: tuple[ActionSpec, ...] = (
    _GLOBAL_SPECS
    + _NAV_SPECS
    + _SELECTOR_SPECS
    + _POOL_SPECS
    + _INFO_SPECS
    + _MEDIA_SPECS
    + _IMAGE_SPECS
    + _PDF_SPECS
    + _TEXT_SPECS
    + _FONT_SPECS
    + _ARCHIVE_SPECS
    + _FOLDER_SPECS
)


#: 设置页 / 文档的分组顺序（仅用于生成表格）。
CATEGORY_ORDER: tuple[str, ...] = (
    "global",
    "navigation",
    "selector",
    "pool",
    "info",
    "media",
    "image",
    "pdf",
    "text",
    "font",
    "archive",
    "folder",
)


def spec_by_id(action_id: str) -> ActionSpec | None:
    """按 id 查找动作定义。

    Args:
        action_id: 动作 id。

    Returns:
        Optional[ActionSpec]: 命中返回定义，否则 ``None``。
    """
    for spec in ACTION_SPECS:
        if spec.action_id == action_id:
            return spec
    return None

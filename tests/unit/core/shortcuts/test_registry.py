# -*- coding: utf-8 -*-
"""快捷键注册表与绑定表单元测试（纯 Python，无需 QApplication）。

覆盖：

* ``ACTION_SPECS`` 完整性（id 唯一、命名空间规范、``long_press`` 阈值）；
* ``BindingKey`` 归一化（物理键码、修饰键屏蔽、纯修饰键拒绝）；
* ``Ctrl+\\`` / ``Ctrl+,`` 与输入法无关（同一物理键码）；
* ``BindingTable`` 索引构建、``also_in`` 展开、真实冲突检测。

验证命令：
    python -m pytest tests/unit/core/shortcuts/test_registry.py -v
"""

from __future__ import annotations

import pytest

from sopeek.core.shortcuts.bindings import BindingKey, parse_all
from sopeek.core.shortcuts.dispatcher import BindingTable
from sopeek.core.shortcuts.registry import ACTION_SPECS, spec_by_id

pytestmark = pytest.mark.unit


# ── 注册表完整性 ──────────────────────────────────────────────────────


def test_action_ids_are_unique() -> None:
    """所有 action_id 必须唯一。"""
    ids = [spec.action_id for spec in ACTION_SPECS]
    assert len(ids) == len(set(ids))


def test_action_ids_use_namespace() -> None:
    """每个 action_id 必须含命名空间（点号分隔）。"""
    for spec in ACTION_SPECS:
        assert "." in spec.action_id, spec.action_id
        assert spec.action_id == spec.action_id.strip()


def test_long_press_threshold_positive() -> None:
    """``long_press`` 策略必须有正的阈值。"""
    for spec in ACTION_SPECS:
        if spec.repeat == "long_press":
            assert spec.long_press_ms > 0, spec.action_id


def test_also_in_excludes_own_region() -> None:
    """``also_in`` 不得包含自身 region，也不得包含 global。"""
    for spec in ACTION_SPECS:
        assert spec.region not in spec.also_in, spec.action_id
        assert "global" not in spec.also_in, spec.action_id


def test_all_default_keys_parse() -> None:
    """所有默认键位文本都必须能解析成 BindingKey。"""
    for spec in ACTION_SPECS:
        keys = parse_all(spec.default_keys)
        assert len(keys) == len(spec.default_keys), spec.action_id


def test_spec_by_id_returns_none_for_unknown() -> None:
    """未知 id 返回 None。"""
    assert spec_by_id("nope.not.exist") is None
    assert spec_by_id("selector.refresh") is not None


# ── BindingKey 归一化 ─────────────────────────────────────────────────


def test_parse_ctrl_backslash() -> None:
    """``Ctrl+\\`` 解析为 Key_Backslash + Ctrl（与中文输入法的「、」同键）。"""
    key = BindingKey.parse("Ctrl+\\")
    assert key is not None
    assert key.ctrl is True
    assert key.alt is False
    assert key.shift is False


def test_parse_ctrl_comma() -> None:
    """``Ctrl+,`` 解析为 Key_Comma + Ctrl（与全角逗号同键）。"""
    key = BindingKey.parse("Ctrl+,")
    assert key is not None
    assert key.ctrl is True


def test_parse_shift_q() -> None:
    """``Shift+Q`` 保留 Shift（输入框守卫据此放行）。"""
    key = BindingKey.parse("Shift+Q")
    assert key is not None
    assert key.shift is True
    assert key.has_command_modifier() is False


def test_parse_empty_returns_none() -> None:
    """空串 / 非法文本返回 None。"""
    assert BindingKey.parse("") is None
    assert BindingKey.parse("   ") is None
    assert BindingKey.parse("Ctrl+NotAKey") is None


def test_parse_all_dedupes() -> None:
    """``parse_all`` 保序去重并丢弃非法项。"""
    keys = parse_all(("Ctrl+F", "Ctrl+F", "Bogus+Key", "Ctrl+G"))
    assert len(keys) == 2
    assert keys[0].text() == "Ctrl+F"
    assert keys[1].text() == "Ctrl+G"

def test_roundtrip_text() -> None:
    """``parse`` → ``text`` 往返稳定。"""
    for text in ("Ctrl+F", "Shift+Q", "Alt+Left", "F6", "Space", "Ctrl+Return"):
        key = BindingKey.parse(text)
        assert key is not None
        assert key.text() == text


def test_has_modifier() -> None:
    """``has_modifier`` 覆盖任意修饰键。"""
    assert BindingKey.parse("Ctrl+F").has_modifier() is True
    assert BindingKey.parse("Shift+F").has_modifier() is True
    assert BindingKey.parse("F").has_modifier() is False


# ── BindingTable ─────────────────────────────────────────────────────


def test_table_builds() -> None:
    """默认注册表能成功建表（无真实冲突）。"""
    table = BindingTable()
    assert not table.is_empty()
    assert len(table.action_ids()) == len(ACTION_SPECS)


def test_nav_default_keys_are_ctrl_arrows() -> None:
    """焦点区切换默认使用 Ctrl+方向键（Alt 已释放给批量选择）。"""
    next_zone = spec_by_id("nav.next_zone")
    prev_zone = spec_by_id("nav.prev_zone")
    assert next_zone is not None
    assert prev_zone is not None
    assert set(next_zone.default_keys) == {"Ctrl+Right", "Ctrl+Down"}
    assert set(prev_zone.default_keys) == {"Ctrl+Left", "Ctrl+Up"}


def test_batch_default_keys_are_alt_arrows() -> None:
    """选择器 / 储存池的批量选择改用 Alt+方向键。"""
    for prefix, region in (("selector", "selector"), ("pool", "pool")):
        for direction, key in (
            ("up", "Alt+Up"),
            ("down", "Alt+Down"),
            ("left", "Alt+Left"),
            ("right", "Alt+Right"),
        ):
            spec = spec_by_id(f"{prefix}.batch_{direction}")
            assert spec is not None
            assert spec.region == region
            assert spec.default_keys == (key,)


def test_ctrl_arrows_resolve_to_nav_in_app() -> None:
    """Ctrl+方向键在 app 区域命中焦点区切换。"""
    table = BindingTable()
    assert table.lookup_all(BindingKey.parse("Ctrl+Right"), "app") == (
        "nav.next_zone",
    )
    assert table.lookup_all(BindingKey.parse("Ctrl+Down"), "app") == (
        "nav.next_zone",
    )
    assert table.lookup_all(BindingKey.parse("Ctrl+Left"), "app") == (
        "nav.prev_zone",
    )
    assert table.lookup_all(BindingKey.parse("Ctrl+Up"), "app") == (
        "nav.prev_zone",
    )
    assert table.lookup_all(BindingKey.parse("Alt+Right"), "app") == ()


def test_ctrl_arrows_not_shadowed_in_card_regions() -> None:
    """列表/池内不得再绑定 Ctrl+方向键，否则会挡住 app 回落的切区。"""
    table = BindingTable()
    for region in ("selector", "pool"):
        for text in ("Ctrl+Left", "Ctrl+Right", "Ctrl+Up", "Ctrl+Down"):
            assert table.lookup_all(BindingKey.parse(text), region) == (), (
                region,
                text,
            )


def test_alt_arrows_hit_batch_in_card_regions() -> None:
    """Alt+方向键在列表/池内命中批量选择。"""
    table = BindingTable()
    expectations = (
        ("selector", "Alt+Up", "selector.batch_up"),
        ("selector", "Alt+Down", "selector.batch_down"),
        ("selector", "Alt+Left", "selector.batch_left"),
        ("selector", "Alt+Right", "selector.batch_right"),
        ("pool", "Alt+Up", "pool.batch_up"),
        ("pool", "Alt+Down", "pool.batch_down"),
        ("pool", "Alt+Left", "pool.batch_left"),
        ("pool", "Alt+Right", "pool.batch_right"),
    )
    for region, text, action_id in expectations:
        assert table.lookup_all(BindingKey.parse(text), region) == (action_id,)


def test_lookup_selector_refresh() -> None:
    """选择器内 Ctrl+H 命中刷新。"""
    table = BindingTable()
    key = BindingKey.parse("Ctrl+H")
    assert table.lookup_all(key, "selector") == ("selector.refresh",)


def test_lookup_returns_empty_for_unknown_key() -> None:
    """未登记的键返回空元组。"""
    table = BindingTable()
    key = BindingKey.parse("Ctrl+Shift+Alt+Z")
    assert table.lookup_all(key, "selector") == ()


def test_also_in_expands_to_fullscreen() -> None:
    """``also_in=('fullscreen',)`` 使预览器动作在全屏区域也可命中。"""
    table = BindingTable()
    key = BindingKey.parse("Space")
    candidates = table.lookup_all(key, "fullscreen")
    assert "preview.media.play_pause" in candidates
    assert "preview.image.gif_toggle" in candidates


def test_fullscreen_multiple_candidates() -> None:
    """全屏区域同一键可有多个候选（不同预览器），由 handler 存在性过滤。"""
    table = BindingTable()
    key = BindingKey.parse("Left")
    candidates = table.lookup_all(key, "fullscreen")
    assert len(candidates) >= 2


def test_keys_for_action() -> None:
    """``keys_for`` 返回该动作的全部键位（含别名）。"""
    table = BindingTable()
    keys = table.keys_for("preview.image.zoom_in")
    texts = {k.text() for k in keys}
    assert "=" in texts
    assert "+" in texts


def test_duplicate_action_id_raises() -> None:
    """重复 action_id 在构建期抛 ValueError。"""
    from sopeek.core.shortcuts.registry import ActionSpec

    spec = ActionSpec(
        action_id="dup.a", title="A", region="selector", default_keys=("F1",)
    )
    with pytest.raises(ValueError, match="重复的 action_id"):
        BindingTable((spec, spec))


def test_same_region_key_conflict_raises() -> None:
    """同区域重复键位在构建期抛 ValueError。"""
    from sopeek.core.shortcuts.registry import ActionSpec

    first = ActionSpec(
        action_id="dup.a", title="A", region="selector", default_keys=("F1",)
    )
    second = ActionSpec(
        action_id="dup.b", title="B", region="selector", default_keys=("F1",)
    )
    with pytest.raises(ValueError, match="键位冲突"):
        BindingTable((first, second))


def test_different_region_same_key_allowed() -> None:
    """不同区域同键位允许（如 Ctrl+F 在 selector 与 preview.pdf 各一份）。"""
    from sopeek.core.shortcuts.registry import ActionSpec

    a = ActionSpec(
        action_id="x.a", title="A", region="selector", default_keys=("Ctrl+F",)
    )
    b = ActionSpec(
        action_id="x.b", title="B", region="preview.pdf", default_keys=("Ctrl+F",)
    )
    table = BindingTable((a, b))
    assert table.lookup_all(BindingKey.parse("Ctrl+F"), "selector") == ("x.a",)
    assert table.lookup_all(BindingKey.parse("Ctrl+F"), "preview.pdf") == ("x.b",)


# ── 实测反馈后的键位回归（防止改回旧键位） ────────────────────────────


def test_pdf_zoom_reset_uses_plain_zero() -> None:
    """PDF 重置缩放必须是无修饰键 ``0``（``Ctrl+0`` 已弃用）。"""
    table = BindingTable()
    assert table.lookup_all(BindingKey.parse("0"), "preview.pdf") == (
        "preview.pdf.zoom_reset",
    )
    assert table.lookup_all(BindingKey.parse("Ctrl+0"), "preview.pdf") == ()


def test_drawers_use_shift_f() -> None:
    """所有抽屉（PDF 目录 / 文本搜索 / 压缩包搜索）统一 ``Shift+F``。

    旧键 ``Ctrl+Shift+F`` 保留为别名：输入框内 ``Shift+F`` 会被放行（用于
    输入大写 F），此时仍可用旧键关闭抽屉。
    """
    table = BindingTable()
    for key_text in ("Shift+F", "Ctrl+Shift+F"):
        key = BindingKey.parse(key_text)
        assert "preview.pdf.toggle_index" in table.lookup_all(key, "preview.pdf")
        assert "preview.text.toggle_search" in table.lookup_all(key, "preview.text")
        assert "preview.archive.toggle_search" in table.lookup_all(
            key, "preview.archive"
        )
    # 旧键位（更早的 Ctrl+F）不能再命中预览器抽屉
    old = BindingKey.parse("Ctrl+F")
    assert "preview.pdf.toggle_index" not in table.lookup_all(old, "preview.pdf")
    assert "preview.text.toggle_search" not in table.lookup_all(old, "preview.text")


def test_selection_actions_are_global() -> None:
    """筛选 / 收藏夹 / 刷新 / 排序在 app、pool、fullscreen 均应命中。"""
    table = BindingTable()
    expectations = {
        "Ctrl+F": "selector.filter",
        "Ctrl+G": "selector.favorites",
        "Ctrl+H": "selector.refresh",
        "Ctrl+L": "selector.sort_menu",
    }
    for key_text, action_id in expectations.items():
        key = BindingKey.parse(key_text)
        for region in ("app", "pool", "fullscreen", "info"):
            assert action_id in table.lookup_all(key, region), (key_text, region)


def test_fullscreen_toggle_available_everywhere() -> None:
    """``Ctrl+\\`` 在任何区域都必须能查到全屏动作（用户要求）。"""
    table = BindingTable()
    key = BindingKey.parse("Ctrl+\\")
    for region in ("app", "selector", "pool", "info", "path", "fullscreen"):
        candidates = table.lookup_all(key, region)
        assert any(aid.endswith(".fullscreen") for aid in candidates), region


def test_zoom_and_font_actions_repeat_auto() -> None:
    """缩放 / 字号 / 字重必须 ``repeat="auto"``（长按连续生效）。"""
    for action_id in (
        "preview.image.zoom_in",
        "preview.image.zoom_out",
        "preview.pdf.zoom_in",
        "preview.pdf.zoom_out",
        "preview.text.font_up",
        "preview.text.font_down",
        "preview.font.size_up",
        "preview.font.size_down",
        "preview.font.weight_up",
        "preview.font.weight_down",
    ):
        spec = spec_by_id(action_id)
        assert spec is not None, action_id
        assert spec.repeat == "auto", action_id


def test_keypad_enter_aliases_enter_actions() -> None:
    """小键盘 Enter（``Key_Enter``）与主键盘 ``Return`` 命中同一批 Enter 动作。"""
    table = BindingTable()
    keypad = BindingKey.parse("Enter")
    main = BindingKey.parse("Return")
    assert keypad is not None and main is not None
    for action_id, region in (
        ("selector.enter", "selector"),
        ("pool.enter", "pool"),
        ("info.copy_current", "info"),
        ("preview.archive.enter_dir", "preview.archive"),
        ("preview.folder.enter_dir", "preview.folder"),
    ):
        assert action_id in table.lookup_all(main, region), action_id
        assert action_id in table.lookup_all(keypad, region), action_id


def test_keypad_ctrl_enter_copies_all() -> None:
    """``Ctrl+Enter``（小键盘）等价于 ``Ctrl+Return``：复制全部信息。"""
    table = BindingTable()
    keypad = BindingKey.parse("Ctrl+Enter")
    assert keypad is not None
    assert "info.copy_all" in table.lookup_all(keypad, "info")


# -*- coding: utf-8 -*-
"""``ui.mica.drag`` 的纯几何 / 控制器测试（无 Qt、无显示器依赖）。

这里锁定的都是**视觉正确性** invariants，而非实现细节：

* **密度守恒** —— 拖动场的网格密度必须等于常规烘焙的密度。这是"松手时不会
  出现糊→清晰跳变"的唯一保障，因为它保证 σ 相对窗口的物理半径不变。
* **覆盖范围** —— 偏移采样必须精确覆盖 ±cover，多一分浪费、少一分提前越界。
* **亚像素平滑** —— 源矩形必须是浮点的，否则放大后会出现台阶式抖动。
* **降级闭环** —— 越界能放大余量、触顶能冻结、长期不越界能回落。
"""

from __future__ import annotations

import numpy as np
import pytest

from freeassetfilter.ui.mica.config import MicaParams, bake_grid_size
from freeassetfilter.ui.mica.drag import (
    DRAG_BAKE_MS_ABORT,
    DRAG_COVER_DEFAULT_PX,
    DRAG_COVER_MAX_PX,
    DRAG_COVER_MIN_PX,
    DRAG_MAX_PAD_PX,
    DRAG_MISS_LIMIT,
    DRAG_QUALITY_LEVELS,
    DragField,
    DragSampler,
    _window_scale,
    fit_cover,
    grid_for_region,
)

_SIGMA = MicaParams().to_engine(dark=True).sigma

#: 覆盖常见窗口尺寸（含超宽、超小、小于网格长边）。
_WINDOW_SIZES = [(1600, 1000), (1000, 700), (600, 400), (200, 150), (3200, 900)]


def _make_field(plan, *, region=None) -> DragField:
    """由规划构造一块占位拖动场（像素内容全 0，几何为真）。"""
    grid = plan.grid
    return DragField(
        image=np.zeros((grid[1], grid[0], 3), dtype=np.uint8),
        region=region if region is not None else plan.region,
        grid=grid,
        win_size=plan.win_size,
        key=(),
        backend="test",
        duration_ms=1.0,
        cover=plan.cover,
        quality=plan.quality,
    )


def _plan(*, win=(1600, 1000), velocity=(0.0, 0.0), bake_ms=3.0, origin=(500, 300)):
    sampler = DragSampler()
    sampler.note_bake(bake_ms)
    return sampler.plan_for((origin[0], origin[1], win[0], win[1]), velocity, _SIGMA)


# ---------------------------------------------------------------------------
# 密度守恒（视觉一致性的核心保证）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_drag_density_matches_normal_bake(win: tuple) -> None:
    """拖动场的网格密度必须等于常规烘焙，否则松手会出现可见跳变。

    σ 以网格像素为单位，密度一变，色度低通相对窗口的物理半径就变了。
    """
    plan = _plan(win=win)
    normal_w, _ = bake_grid_size(*win)

    field_density = plan.grid[0] / plan.region[2]
    window_width_in_field = win[0] * field_density

    assert field_density == pytest.approx(normal_w / win[0], rel=5e-3)
    assert window_width_in_field == pytest.approx(float(normal_w), abs=1.0)
    assert plan.quality == DRAG_QUALITY_LEVELS[0], "默认应使用最高画质档"


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_grid_grows_with_cover_at_fixed_density(win: tuple) -> None:
    """余量翻倍时网格应按比例增大（密度不变），而非被压回长边上限。

    网格是整数，密度只能在 ``round()`` 的 ±0.5 网格像素量化误差内守恒，
    因此这里直接对照理想值断言，而不是拿两次取整结果相除（那会把量化误差
    放大到 0.3% 量级，反而掩盖真正的密度漂移）。
    """
    scale = _window_scale(win[0], win[1], DRAG_QUALITY_LEVELS[0])
    small = grid_for_region(win[0], win[1], 100, DRAG_QUALITY_LEVELS[0])
    large = grid_for_region(win[0], win[1], 200, DRAG_QUALITY_LEVELS[0])
    assert large[0] > small[0]

    for cover, grid in ((100, small), (200, large)):
        assert abs(grid[0] - (win[0] + 2 * cover) * scale) <= 0.5 + 1e-9
        assert abs(grid[1] - (win[1] + 2 * cover) * scale) <= 0.5 + 1e-9


# ---------------------------------------------------------------------------
# 覆盖范围与亚像素平滑
# ---------------------------------------------------------------------------


def test_source_rect_covers_exactly_cover_px() -> None:
    """偏移采样应精确覆盖 ±cover；多一分是浪费，少一分会提前越界。"""
    plan = _plan()
    field = _make_field(plan)
    x0, y0 = plan.region[0] + plan.cover, plan.region[1] + plan.cover

    ok = [d for d in range(-1500, 1501) if field.source_rect((x0 + d, y0, *plan.win_size))]
    assert ok, "中心位置必须可取样"
    assert min(ok) == pytest.approx(-plan.cover, abs=1)
    assert max(ok) == pytest.approx(plan.cover, abs=1)


def test_source_rect_is_subpixel_smooth() -> None:
    """源矩形必须随位移连续变化 —— 取整会导致放大后台阶式抖动。"""
    plan = _plan()
    field = _make_field(plan)
    x0, y0 = plan.region[0] + plan.cover, plan.region[1] + plan.cover

    base = field.source_rect((x0, y0, *plan.win_size))
    step = field.source_rect((x0 + 1, y0, *plan.win_size))
    assert base is not None and step is not None

    delta = step[0] - base[0]
    assert 0.0 < abs(delta) < 1.0, "1 虚拟像素的位移必须落在亚像素区间"


def test_source_rect_rejects_out_of_range() -> None:
    """跑出覆盖范围应返回 ``None``，由上层回退到旧色调场。"""
    plan = _plan()
    field = _make_field(plan)
    x0, y0 = plan.region[0] + plan.cover, plan.region[1] + plan.cover
    assert field.source_rect((x0 + plan.cover + 50, y0, *plan.win_size)) is None
    assert field.source_rect((x0 - plan.cover - 50, y0, *plan.win_size)) is None
    assert field.source_rect((x0, y0 + plan.cover + 50, *plan.win_size)) is None


def test_source_rect_disabled_while_resizing() -> None:
    """缩放中窗口尺寸不可预测，偏移采样必须自行禁用。"""
    plan = _plan()
    field = _make_field(plan)
    x0, y0 = plan.region[0] + plan.cover, plan.region[1] + plan.cover
    assert field.source_rect((x0, y0, plan.win_size[0] + 1, plan.win_size[1])) is None
    assert field.source_rect((x0, y0, plan.win_size[0], plan.win_size[1] + 1)) is None


# ---------------------------------------------------------------------------
# 预算约束
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_fit_cover_respects_pad_budget(win: tuple) -> None:
    """fit_cover 必须把 pad 面积压进 :data:`DRAG_MAX_PAD_PX`。"""
    for quality in DRAG_QUALITY_LEVELS:
        cover = fit_cover(win[0], win[1], DRAG_COVER_MAX_PX * 4, _SIGMA, quality)
        gw, gh = grid_for_region(win[0], win[1], cover, quality)
        from freeassetfilter.ui.mica.engine import margin_px

        margin = margin_px(gw, gh, _SIGMA)
        assert (gw + 2 * margin) * (gh + 2 * margin) <= DRAG_MAX_PAD_PX


def test_fit_cover_zero_is_last_resort() -> None:
    """极端尺寸下允许收缩到 0（退化为一次常规烘焙），但不得为负。"""
    cover = fit_cover(40_000, 30_000, DRAG_COVER_MAX_PX, _SIGMA, DRAG_QUALITY_LEVELS[0])
    assert cover >= 0


# ---------------------------------------------------------------------------
# 自适应控制器
# ---------------------------------------------------------------------------


def test_sampler_grows_cover_on_repeated_misses() -> None:
    """连续越界应按 1.5 倍放大余量，而不是每次越界都放大。"""
    sampler = DragSampler()
    assert sampler.cover == DRAG_COVER_DEFAULT_PX

    for _ in range(DRAG_MISS_LIMIT - 1):
        sampler.note_miss()
    assert sampler.cover == DRAG_COVER_DEFAULT_PX, "未达阈值不应动作"

    sampler.note_miss()
    assert sampler.cover > DRAG_COVER_DEFAULT_PX


def test_sampler_freezes_when_cover_exhausted() -> None:
    """余量已到上限仍持续越界 → 冻结，不再无谓地请求烘焙。"""
    sampler = DragSampler(cover=DRAG_COVER_MAX_PX)
    for _ in range(DRAG_MISS_LIMIT * 4):
        sampler.note_miss()
    assert sampler.frozen is True


def test_sampler_freezes_on_pathological_bake_time() -> None:
    """单次烘焙耗时离谱 → 直接冻结，避免持续空耗。"""
    sampler = DragSampler()
    sampler.note_bake(DRAG_BAKE_MS_ABORT + 1.0)
    assert sampler.frozen is True


def test_sampler_decays_cover_when_never_missing() -> None:
    """长期不越界说明余量过剩，应缓慢回落到基线以省开销。"""
    sampler = DragSampler(cover=DRAG_COVER_MAX_PX)
    for _ in range(40):
        sampler.note_bake(2.0)
    assert sampler.cover == DRAG_COVER_DEFAULT_PX


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_planning_never_steps_down_quality(win: tuple) -> None:
    """规划时绝不主动降档 —— 静止拖动也降密度会破坏密度守恒。

    即使预算把实际余量压得远小于期望值（极小窗口就是如此），也必须保持
    最高画质档；降档只能作为越界后的响应。
    """
    plan = _plan(win=win)
    assert plan.quality == DRAG_QUALITY_LEVELS[0]


def test_budget_limited_steps_quality_without_waiting_for_max_cover() -> None:
    """余量被预算钳死时，继续放大期望余量无用，应直接降画质档换覆盖。"""
    sampler = DragSampler()
    sampler.note_bake(3.0)

    tiny = (200, 150)  # 密度接近 1，余量必然被 pad 预算钳制
    plan = sampler.plan_for((0, 0, *tiny), (0.0, 0.0), _SIGMA)
    assert sampler.budget_limited is True
    assert plan.cover < sampler.cover, "预算必须真的把它压小，否则本用例无意义"

    for _ in range(DRAG_MISS_LIMIT):
        sampler.note_miss()
    assert sampler.quality == DRAG_QUALITY_LEVELS[1], "被钳死时应直接降一档画质"
    assert sampler.frozen is False


def test_reset_restores_full_quality_for_next_segment() -> None:
    """每段新拖动都应从头尝试全质量，上一段的降级不得被永久继承。"""
    sampler = DragSampler()
    sampler.note_bake(3.0)
    # 先用极小窗口制造预算钳制 —— 只有余量这条路走死才会降画质档。
    sampler.plan_for((0, 0, 200, 150), (0.0, 0.0), _SIGMA)
    for _ in range(DRAG_MISS_LIMIT):
        sampler.note_miss()
    assert sampler.quality == DRAG_QUALITY_LEVELS[1]

    sampler.reset()
    assert sampler.quality == DRAG_QUALITY_LEVELS[0]


def test_sampler_cover_never_below_min() -> None:
    sampler = DragSampler(cover=DRAG_COVER_MIN_PX)
    for _ in range(20):
        sampler.note_bake(1.0)
        for _ in range(DRAG_MISS_LIMIT):
            sampler.note_miss()
    assert sampler.cover >= DRAG_COVER_MIN_PX


def test_reset_clears_freeze_but_keeps_learned_timing() -> None:
    """新一段交互应重试（清除冻结），但保留跨段学到的耗时均值。"""
    sampler = DragSampler()
    sampler.note_bake(500.0)
    assert sampler.frozen is True
    sampler.reset()
    assert sampler.frozen is False
    assert sampler.bake_ms == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# 速度自适应
# ---------------------------------------------------------------------------


#: 快速甩动窗口的速度（虚拟像素 / 秒）：约 100 ms 内划过 900 px。
_FLICK_VELOCITY: float = 9000.0


def test_cover_grows_with_velocity_on_slow_device() -> None:
    """慢设备上高速拖动需要更大余量，否则一次烘焙周转就跑出范围。

    速度必须取得足够大，使"速度需求 = |v| × 延迟 × 安全系数"超过基线
    :data:`DRAG_COVER_DEFAULT_PX` —— 否则快慢设备都被基线拉平，测不出差异。
    """
    fast = DragSampler()
    fast.note_bake(3.0)
    slow = DragSampler()
    slow.note_bake(60.0)

    assert slow.desired_cover((_FLICK_VELOCITY, 0.0)) > fast.desired_cover(
        (_FLICK_VELOCITY, 0.0)
    )
    assert fast.desired_cover((0.0, 0.0)) == DRAG_COVER_DEFAULT_PX
    # 3000 px/s 属于慢速拖动，需求量低于基线，快慢设备都应回落到基线。
    assert slow.desired_cover((3000.0, 0.0)) == DRAG_COVER_DEFAULT_PX


def test_learned_cover_feeds_back_into_planning() -> None:
    """越界学到的余量必须真正进入规划 —— 否则自适应闭环是断的。

    这是一个回归测试：``desired_cover`` 曾只取 ``max(基线, 速度需求)``，
    把 :meth:`DragSampler.note_miss` 辛苦放大出来的余量晾在一边，结果连续
    越界只能一路放大到上限然后冻结，实际覆盖从未变大过。
    """
    sampler = DragSampler()
    sampler.note_bake(3.0)
    baseline = sampler.desired_cover((0.0, 0.0))

    for _ in range(DRAG_MISS_LIMIT):
        sampler.note_miss()

    learned = sampler.desired_cover((0.0, 0.0))
    assert learned > baseline, "越界放大出的余量必须抬高后续期望值"


def test_region_biases_forward_along_motion() -> None:
    """向右拖动时，拖动场应向右前移，让余量更多落在即将经过的一侧。"""
    still = _plan(velocity=(0.0, 0.0))
    right = _plan(velocity=(6000.0, 0.0), bake_ms=40.0)
    assert right.region[0] > still.region[0]

    # 前移量上限为半个余量，方向反转时反方向仍留有 50% 余量。
    assert right.region[0] - still.region[0] <= still.cover * 0.5 + 1


def test_high_velocity_may_step_down_quality() -> None:
    """极高速拖动下，为换取更大覆盖允许降到较低画质档（但不得越出档位表）。"""
    plan = _plan(velocity=(60_000.0, 0.0), bake_ms=60.0)
    assert plan.quality in DRAG_QUALITY_LEVELS
    assert plan.cover >= DRAG_COVER_MIN_PX

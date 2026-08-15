"""Unit tests for the styled-fluid math helper module."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QColor

# Keep the same path bootstrap used by the sibling styled-fluid tests so
# ``from components.xxx`` absolute imports resolve without touching the repo.
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
for _p in (_PROJECT_ROOT, _UI_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from components._styled_fluid_math import (
    ease_in_out_cubic,
    hsv_shift,
    mix_rgb,
    sdf_soft_blob,
    simplex_noise_2d,
    wrap_phase,
)


class TestSimplexNoise2d:
    """Tests for simplex_noise_2d determinism and range."""

    def test_deterministic_for_same_inputs(self) -> None:
        """Same (x, y, seed) must always produce the same value."""
        v1 = simplex_noise_2d(1.2, 3.4, seed=42)
        v2 = simplex_noise_2d(1.2, 3.4, seed=42)
        assert v1 == pytest.approx(v2)

    def test_output_within_minus_one_to_one(self) -> None:
        """All outputs are clamped to [-1.0, 1.0]."""
        values = [
            simplex_noise_2d(x * 0.5, y * 0.5, seed=0)
            for x in range(-5, 6)
            for y in range(-5, 6)
        ]
        assert all(-1.0 <= v <= 1.0 for v in values)

    def test_varies_across_coordinates(self) -> None:
        """Noise must not return a flat constant for different coordinates."""
        values = [simplex_noise_2d(x, y, seed=0) for x in range(10) for y in range(10)]
        assert len(set(values)) > 10

    def test_seed_changes_output(self) -> None:
        """Different seeds should produce different noise values."""
        assert simplex_noise_2d(0.5, 0.5, seed=0) != pytest.approx(
            simplex_noise_2d(0.5, 0.5, seed=1)
        )

    def test_non_finite_coordinates_return_zero(self) -> None:
        """Non-finite coordinate inputs return 0.0 rather than raising."""
        assert simplex_noise_2d(float("nan"), 1.0) == 0.0
        assert simplex_noise_2d(float("inf"), 1.0) == 0.0


class TestSdfSoftBlob:
    """Tests for the soft signed-distance blob field."""

    def test_center_returns_one(self) -> None:
        """The exact center evaluates to 1.0."""
        assert sdf_soft_blob(0.0, 0.0, 0.0, 0.0, 10.0) == 1.0

    def test_far_outside_returns_zero(self) -> None:
        """Well outside the blob returns 0.0."""
        assert sdf_soft_blob(100.0, 0.0, 0.0, 0.0, 10.0, falloff=0.5) == 0.0

    def test_soft_transition_is_between_zero_and_one(self) -> None:
        """A point in the falloff region has a value strictly between 0 and 1."""
        value = sdf_soft_blob(12.0, 0.0, 0.0, 0.0, 10.0, falloff=0.5)
        assert 0.0 < value < 1.0

    def test_negative_radius_returns_zero(self) -> None:
        """A non-positive radius yields a safe 0.0 fallback."""
        assert sdf_soft_blob(0.0, 0.0, 0.0, 0.0, -5.0) == 0.0
        assert sdf_soft_blob(0.0, 0.0, 0.0, 0.0, 0.0) == 0.0

    def test_zero_falloff_is_hard_step(self) -> None:
        """When falloff is 0 the field is a hard disk indicator."""
        assert sdf_soft_blob(5.0, 0.0, 0.0, 0.0, 10.0, falloff=0.0) == 1.0
        assert sdf_soft_blob(11.0, 0.0, 0.0, 0.0, 10.0, falloff=0.0) == 0.0

    def test_negative_falloff_is_clamped(self) -> None:
        """A negative falloff is treated as a hard step."""
        assert sdf_soft_blob(5.0, 0.0, 0.0, 0.0, 10.0, falloff=-1.0) == 1.0


class TestEaseInOutCubic:
    """Tests for cubic ease-in-out."""

    def test_endpoints(self) -> None:
        """0 maps to 0 and 1 maps to 1."""
        assert ease_in_out_cubic(0.0) == 0.0
        assert ease_in_out_cubic(1.0) == 1.0

    def test_midpoint(self) -> None:
        """The midpoint maps to 0.5."""
        assert ease_in_out_cubic(0.5) == pytest.approx(0.5)

    def test_inside_unit_interval(self) -> None:
        """Interior values move away from the linear baseline."""
        assert 0.0 < ease_in_out_cubic(0.25) < 0.25
        assert 0.75 < ease_in_out_cubic(0.75) < 1.0

    def test_clamps_outside_unit_interval(self) -> None:
        """Values below 0 and above 1 are clamped."""
        assert ease_in_out_cubic(-0.5) == 0.0
        assert ease_in_out_cubic(1.5) == 1.0

    def test_non_numeric_returns_zero(self) -> None:
        """Non-numeric inputs return 0.0 instead of raising."""
        assert ease_in_out_cubic("bad") == 0.0  # type: ignore[arg-type]


class TestWrapPhase:
    """Tests for phase wrapping."""

    def test_identity_inside_unit_range(self) -> None:
        """Values already in [0, 1) are unchanged."""
        assert wrap_phase(0.0) == pytest.approx(0.0)
        assert wrap_phase(0.3) == pytest.approx(0.3)
        assert wrap_phase(0.99) == pytest.approx(0.99)

    def test_one_wraps_to_zero(self) -> None:
        """Exactly 1.0 wraps to 0.0, matching a half-open interval."""
        assert wrap_phase(1.0) == pytest.approx(0.0)

    def test_positive_overflow_wraps(self) -> None:
        """Values above 1 wrap back into range."""
        assert wrap_phase(2.3) == pytest.approx(0.3)

    def test_negative_values_wrap(self) -> None:
        """Negative values wrap forward into range."""
        assert wrap_phase(-0.7) == pytest.approx(0.3)

    def test_non_finite_returns_zero(self) -> None:
        """Non-finite values return 0.0 rather than raising."""
        assert wrap_phase(float("nan")) == 0.0
        assert wrap_phase(float("inf")) == 0.0


class TestHsvShift:
    """Tests for HSV color shifting."""

    def test_preserves_alpha(self, qapp: Any) -> None:
        """Alpha channel is preserved by hsv_shift."""
        color = QColor.fromHsv(120, 100, 100, 128)
        shifted = hsv_shift(color, 30.0, 0.0, 0.0)
        assert shifted.alpha() == 128

    def test_hue_wraps_at_360(self, qapp: Any) -> None:
        """A hue shift past 360 wraps back to the low end."""
        color = QColor.fromHsv(350, 200, 200, 255)
        shifted = hsv_shift(color, 30.0, 0.0, 0.0)
        assert shifted.hue() == 20

    def test_saturation_and_value_clamp(self, qapp: Any) -> None:
        """Saturation and value offsets are clamped to [0, 255]."""
        color = QColor.fromHsv(120, 250, 250, 255)
        shifted = hsv_shift(color, 0.0, 100.0, -300.0)
        assert shifted.saturation() == 255
        assert shifted.value() == 0

    def test_invalid_color_returns_black(self, qapp: Any) -> None:
        """An invalid QColor returns opaque black."""
        invalid = QColor()
        assert not invalid.isValid()
        result = hsv_shift(invalid, 0.0, 0.0, 0.0)
        assert result.isValid()
        assert result.rgb() == QColor(0, 0, 0).rgb()


class TestMixRgb:
    """Tests for RGBA linear interpolation."""

    def test_t_zero_returns_start_color(self, qapp: Any) -> None:
        """t=0 returns the start color."""
        a = QColor(255, 0, 0, 255)
        b = QColor(0, 0, 255, 128)
        assert mix_rgb(a, b, 0.0) == a

    def test_t_one_returns_end_color(self, qapp: Any) -> None:
        """t=1 returns the end color."""
        a = QColor(255, 0, 0, 255)
        b = QColor(0, 0, 255, 128)
        assert mix_rgb(a, b, 1.0) == b

    def test_midpoint_interpolates_channels(self, qapp: Any) -> None:
        """t=0.5 averages all RGBA channels."""
        a = QColor(255, 0, 0, 255)
        b = QColor(0, 0, 255, 128)
        mid = mix_rgb(a, b, 0.5)
        assert mid.red() == 128
        assert mid.green() == 0
        assert mid.blue() == 128
        assert mid.alpha() == 192

    def test_clamps_t_to_unit_interval(self, qapp: Any) -> None:
        """t values outside [0, 1] are clamped."""
        a = QColor(0, 0, 0, 255)
        b = QColor(255, 255, 255, 255)
        assert mix_rgb(a, b, -1.0) == a
        assert mix_rgb(a, b, 2.0) == b

    def test_invalid_color_arguments_return_black(self, qapp: Any) -> None:
        """Non-QColor inputs return opaque black safely."""
        a = QColor(255, 0, 0, 255)
        result = mix_rgb(a, None, 0.5)  # type: ignore[arg-type]
        assert result.isValid()
        assert result.rgb() == QColor(0, 0, 0).rgb()


class TestEdgeBehavior:
    """Tests that invalid arguments never raise."""

    def test_sdf_does_not_raise_on_garbage(self) -> None:
        """sdf_soft_blob handles non-numeric arguments gracefully."""
        result = sdf_soft_blob("a", None, [], {}, -1, "x")  # type: ignore[arg-type]
        assert isinstance(result, float)

    def test_noise_does_not_raise_on_garbage_seed(self) -> None:
        """simplex_noise_2d handles an unhashable/invalid seed gracefully."""
        result = simplex_noise_2d(1.0, 1.0, seed=[])  # type: ignore[arg-type]
        assert isinstance(result, float)
        assert -1.0 <= result <= 1.0

    def test_wrap_phase_does_not_raise_on_objects(self) -> None:
        """wrap_phase handles non-numeric objects."""
        result = wrap_phase(object())  # type: ignore[arg-type]
        assert result == 0.0

    def test_hsv_shift_does_not_raise_on_garbage(self, qapp: Any) -> None:
        """hsv_shift handles invalid colors and non-numeric shifts."""
        color = QColor.fromHsv(120, 100, 100, 255)
        result = hsv_shift(color, "x", None, [])  # type: ignore[arg-type]
        assert result.isValid()

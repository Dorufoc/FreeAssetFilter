"""Unit tests for the static CPU fluid background renderer."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QColor, QPixmap

# Keep the same path bootstrap used by the sibling styled-fluid tests so
# ``from components.xxx`` absolute imports resolve without touching the repo.
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
for _p in (_PROJECT_ROOT, _UI_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from components._styled_fluid_cpu import render_static_frame


def _sample_palette() -> list[QColor]:
    """Return a deterministic 5-color palette for tests."""
    return [
        QColor(255, 80, 120, 255),
        QColor(80, 180, 255, 255),
        QColor(140, 90, 220, 255),
        QColor(40, 40, 80, 255),
        QColor(255, 200, 100, 255),
    ]


def _center_pixel(pixmap: QPixmap) -> QColor:
    """Return the color of the center pixel of *pixmap*."""
    image = pixmap.toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


@pytest.fixture
def sample_palette() -> list[QColor]:
    """Provide the shared test palette."""
    return _sample_palette()


@pytest.fixture
def evidence_path() -> Path:
    """Provide the evidence PNG path and ensure its parent directory exists."""
    path = (
        _PROJECT_ROOT
        / ".omo"
        / "evidence"
        / "styled-fluid-background-v2"
        / "task-2-cpu-renderer.png"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TestRenderStaticFrame:
    """Tests for ``render_static_frame`` output shape and contents."""

    def test_output_size_matches_request(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """The returned pixmap has exactly the requested width and height."""
        pixmap = render_static_frame(
            200,
            150,
            sample_palette,
            noise_seed=7,
            time=1.2,
            overlay_color=QColor(0, 0, 0, 51),
        )
        assert not pixmap.isNull()
        assert pixmap.width() == 200
        assert pixmap.height() == 150

    def test_deterministic_for_same_inputs(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """Identical inputs produce identical pixel values."""
        args = (120, 80, sample_palette, 42, 3.3, QColor(0, 0, 0, 40))
        pixmap_a = render_static_frame(*args)
        pixmap_b = render_static_frame(*args)

        image_a = pixmap_a.toImage()
        image_b = pixmap_b.toImage()
        for y in (0, image_a.height() // 2, image_a.height() - 1):
            for x in (0, image_a.width() // 2, image_a.width() - 1):
                assert image_a.pixel(x, y) == image_b.pixel(x, y)

    def test_overlay_color_tints_output(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """A colored overlay shifts the average color of the output."""
        base = render_static_frame(
            100, 80, sample_palette, noise_seed=1, time=0.0,
            overlay_color=QColor(0, 0, 0, 0),
        )
        tinted = render_static_frame(
            100, 80, sample_palette, noise_seed=1, time=0.0,
            overlay_color=QColor(255, 0, 0, 128),
        )

        base_center = _center_pixel(base)
        tinted_center = _center_pixel(tinted)
        # A red overlay should raise the red channel relative to the base.
        assert tinted_center.red() >= base_center.red()

    def test_output_is_not_fully_transparent(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """The baked image contains opaque pixels."""
        pixmap = render_static_frame(
            120, 90, sample_palette, noise_seed=2, time=0.0,
            overlay_color=QColor(0, 0, 0, 0),
        )
        image = pixmap.toImage()
        assert image.pixelColor(10, 10).alpha() > 0
        assert image.pixelColor(60, 45).alpha() > 0

    def test_zero_size_returns_null(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """A non-positive target size returns a null pixmap safely."""
        result = render_static_frame(
            0, 0, sample_palette, noise_seed=0, time=0.0,
            overlay_color=QColor(0, 0, 0, 0),
        )
        assert result.isNull()

    def test_negative_size_returns_null(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """Negative dimensions are treated as invalid and return a null pixmap."""
        result = render_static_frame(
            -10, 20, sample_palette, noise_seed=0, time=0.0,
            overlay_color=QColor(0, 0, 0, 0),
        )
        assert result.isNull()

    def test_400_300_bake_within_time_budget(
        self, qapp: Any, sample_palette: list[QColor]
    ) -> None:
        """A 400x300 frame bakes in at most 300 ms."""
        start = time.perf_counter()
        pixmap = render_static_frame(
            400, 300, sample_palette, noise_seed=5, time=2.0,
            overlay_color=QColor(0, 0, 0, 51),
        )
        elapsed = time.perf_counter() - start

        assert not pixmap.isNull()
        assert pixmap.width() == 400
        assert pixmap.height() == 300
        assert elapsed <= 0.3

    def test_evidence_png_is_written(
        self, qapp: Any, sample_palette: list[QColor], evidence_path: Path
    ) -> None:
        """Produce the acceptance evidence image for visual inspection."""
        pixmap = render_static_frame(
            400,
            300,
            sample_palette,
            noise_seed=11,
            time=4.0,
            overlay_color=QColor(0, 0, 0, 51),
        )
        assert not pixmap.isNull()
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        ok = pixmap.save(str(evidence_path), "PNG")
        assert ok
        assert evidence_path.exists()
        assert evidence_path.stat().st_size > 0

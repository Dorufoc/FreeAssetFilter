#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
``freeassetfilter.core.native`` — Native extension package.

Re-exports the Rust color extractor bridge from ``bridges/`` so that
``from freeassetfilter.core.native import rust_color_extractor`` works,
preserving the pre-restructure import path.
"""

from __future__ import annotations

from .bridges import rust_color_extractor

__all__ = [
    "rust_color_extractor",
]

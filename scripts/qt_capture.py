#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt Widget Screenshot Capture Utility

Provides functions to capture screenshots of Qt widgets for visual testing.
Uses offscreen rendering to avoid paint device conflicts.
"""

import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QImage
from PySide6.QtCore import Qt, QRect, QEvent, QBuffer, QIODevice, QPoint


def capture_widget(widget, output_path=None, size=None):
    """
    Capture a screenshot of a Qt widget using offscreen rendering.
    
    Args:
        widget: The Qt widget to capture
        output_path: Optional path to save the screenshot. If None, returns QPixmap.
        size: Optional tuple (width, height) to resize the widget before capture.
    
    Returns:
        QPixmap: The captured widget screenshot.
    """
    if size:
        widget.resize(size[0], size[1])
    
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    
    for _ in range(5):
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
    
    target_size = widget.size()
    if target_size.isEmpty() or target_size.width() <= 0 or target_size.height() <= 0:
        target_size = widget.sizeHint()
    
    pixmap = QPixmap(target_size)
    pixmap.fill(Qt.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    
    widget.hide()
    
    if output_path:
        dir_name = os.path.dirname(output_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        pixmap.save(output_path)
    
    return pixmap


def capture_multiple_states(widget, states, output_dir, prefix=""):
    """
    Capture screenshots of a widget in multiple states.
    
    Args:
        widget: The Qt widget to capture
        states: List of dicts with 'name', 'setup' (callable), and optional 'size'
        output_dir: Directory to save screenshots
        prefix: Prefix for output filenames
    
    Returns:
        dict: Mapping of state names to QPixmap objects
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    
    for state in states:
        name = state['name']
        setup_fn = state.get('setup')
        size = state.get('size')
        
        if setup_fn:
            setup_fn(widget)
        
        QApplication.processEvents()
        
        output_path = os.path.join(output_dir, f"{prefix}_{name}.png" if prefix else f"{name}.png")
        pixmap = capture_widget(widget, output_path=output_path, size=size)
        results[name] = pixmap
    
    return results


def compare_screenshots(pixmap1, pixmap2, threshold=0.95):
    """
    Compare two screenshots for similarity.
    
    Args:
        pixmap1: First QPixmap
        pixmap2: Second QPixmap
        threshold: Similarity threshold (0.0 to 1.0)
    
    Returns:
        tuple: (is_similar: bool, similarity_score: float)
    """
    img1 = pixmap1.toImage()
    img2 = pixmap2.toImage()
    
    if img1.size() != img2.size():
        return False, 0.0
    
    width = img1.width()
    height = img1.height()
    total_pixels = width * height
    similar_pixels = 0
    
    for y in range(height):
        for x in range(width):
            if img1.pixel(x, y) == img2.pixel(x, y):
                similar_pixels += 1
    
    similarity = similar_pixels / total_pixels if total_pixels > 0 else 0.0
    return similarity >= threshold, similarity

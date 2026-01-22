# -*- coding: utf-8 -*-
"""
FreeAssetFilter 平滑滚动工具
使用 QScroller 实现触摸惯性滚动和丝滑滚动体验
"""

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QScrollArea, QAbstractItemView, QScroller, QScrollerProperties


def _get_target_widget(widget):
    """
    获取需要抓取手势的目标控件
    对于 QScrollArea，返回其 viewport
    """
    if isinstance(widget, QScrollArea):
        return widget.viewport()
    return widget


class SmoothScroller:
    """
    平滑滚动管理器
    为控件添加触摸惯性滚动效果
    """
    
    @staticmethod
    def apply(widget, gesture_type=QScroller.TouchGesture):
        """
        为控件应用平滑滚动
        
        Args:
            widget: 要应用平滑滚动的控件 (QScrollArea, QListWidget, QTreeWidget 等)
            gesture_type: 手势类型 (默认 TouchGesture 只启用触摸滑动)
                - QScroller.TouchGesture: 触摸滑动
                - QScroller.LeftMouseButtonGesture: 鼠标左键拖动
                - QScroller.MiddleMouseButtonGesture: 鼠标中键拖动
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 0.2)
        properties.setScrollMetric(QScrollerProperties.OvershootDragDistanceFactor, 0.1)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 200)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.8)
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.6)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def apply_to_scroll_area(scroll_area, gesture_type=QScroller.TouchGesture):
        """
        为 QScrollArea 应用平滑滚动
        
        Args:
            scroll_area: QScrollArea 实例
            gesture_type: 手势类型
        """
        if not isinstance(scroll_area, QScrollArea):
            return None
        
        SmoothScroller._configure_scroll_area(scroll_area)
        return SmoothScroller.apply(scroll_area, gesture_type)
    
    @staticmethod
    def _configure_scroll_area(scroll_area):
        """
        配置滚动区域为像素级滚动模式
        注意：QScrollArea 没有 setScrollMode 方法，仅对 QAbstractItemView 子类生效
        """
        if isinstance(scroll_area, QAbstractItemView):
            scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    
    @staticmethod
    def apply_ios_style(widget, gesture_type=QScroller.TouchGesture):
        """
        为控件应用 iOS 风格的滚动效果
        
        Args:
            widget: 要应用平滑滚动的控件
            gesture_type: 手势类型
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.9)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.5)
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 0.3)
        properties.setScrollMetric(QScrollerProperties.OvershootDragDistanceFactor, 0.2)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 300)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def apply_quick_style(widget, gesture_type=QScroller.TouchGesture):
        """
        为控件应用快速响应风格的滚动效果
        
        Args:
            widget: 要应用平滑滚动的控件
            gesture_type: 手势类型
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.4)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.9)
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 0.0)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 100)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def enable_vertical_only(widget):
        """
        只启用垂直方向的平滑滚动（锁定水平）
        
        Args:
            widget: 要配置的控件
        """
        if isinstance(widget, QScrollArea):
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    
    @staticmethod
    def enable_mouse_drag(widget):
        """
        启用鼠标左键拖动滚动（可选功能）
        
        Args:
            widget: 要启用鼠标拖动的控件
        """
        SmoothScroller.apply(widget, QScroller.LeftMouseButtonGesture)

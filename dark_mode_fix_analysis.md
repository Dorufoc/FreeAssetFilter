# 深色模式开关不生效问题分析与修复方案

## 问题分析

通过分析代码，我发现深色模式开关不生效的根本原因是：

1. **SettingsManager实例创建问题**：
   - 在`button_widgets.py`、`input_widgets.py`等组件的`update_style`方法中，每次都会创建一个新的`SettingsManager`实例
   ```python
   from freeassetfilter.core.settings_manager import SettingsManager
   settings_manager = SettingsManager()  # 每次都创建新实例
   current_colors = settings_manager.get_setting("appearance.colors", {})
   ```
   - 这导致组件无法获取到应用中最新的设置值，而是重新从文件加载设置

2. **设置更新不及时**：
   - 虽然`modern_settings_window.py`中的`on_theme_toggled`函数正确地更新了设置
   - 但由于组件使用了新的SettingsManager实例，无法立即看到这些更新

## 修复方案

### 1. 修复组件的update_style方法

修改所有组件（如`button_widgets.py`、`input_widgets.py`、`list_widgets.py`、`progress_widgets.py`）中的`update_style`方法，使其从应用实例中获取SettingsManager，而不是创建新实例。

### 2. 修改示例

以`button_widgets.py`为例，修改`update_style`方法：

```python
def update_style(self):
    """
    更新按钮样式
    """
    # 获取应用实例和最新的DPI缩放因子
    app = QApplication.instance()
    self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
    
    # 从应用实例获取设置管理器，而不是创建新实例
    if hasattr(app, 'settings_manager'):
        settings_manager = app.settings_manager
    else:
        # 回退方案：如果应用实例中没有settings_manager，再创建新实例
        from freeassetfilter.core.settings_manager import SettingsManager
        settings_manager = SettingsManager()
    
    current_colors = settings_manager.get_setting("appearance.colors", {})
    
    # 后续代码保持不变...
```

### 3. 修复其他组件

对`input_widgets.py`、`list_widgets.py`、`progress_widgets.py`等其他组件进行类似的修改。

### 4. 确保主题切换时所有颜色正确更新

在`modern_settings_window.py`的`on_theme_toggled`函数中，确保在切换主题时不仅更新base_color，还要更新其他相关颜色：

```python
def on_theme_toggled(value):
    # 更新主题模式设置
    self.current_settings.update({"appearance.theme": "dark" if value else "default"})
    
    # 根据主题模式更新所有基础颜色
    if value:  # 深色主题
        self.current_settings.update({
            "appearance.colors.base_color": "#2A2A2A",
            "appearance.colors.secondary_color": "#FFFFFF",  # 文字颜色改为白色
            "appearance.colors.normal_color": "#3A3A3A",
            "appearance.colors.auxiliary_color": "#1E1E1E"
        })
    else:  # 浅色主题
        self.current_settings.update({
            "appearance.colors.base_color": "#FFFFFF",
            "appearance.colors.secondary_color": "#333333",
            "appearance.colors.normal_color": "#e0e0e0",
            "appearance.colors.auxiliary_color": "#f1f3f5"
        })
    
    # 更新设置管理器中的颜色设置
    for key, value in self.current_settings["appearance.colors"].items():
        self.settings_manager.set_setting(f"appearance.colors.{key}", value)
    
    # 应用主题更新到UI
    app = self.parent() if hasattr(self, 'parent') and self.parent() else None
    if hasattr(app, 'update_theme'):
        app.update_theme()
    
    # 发出设置保存信号
    self.settings_saved.emit(self.current_settings)
```

## 修复验证

修复后，深色模式开关应该能够正常工作：
1. 当切换到深色主题时，base_color应该变为"#2A2A2A"（或用户期望的深色值）
2. 当切换到浅色主题时，base_color应该变为"#FFFFFF"
3. 所有组件应该能够立即反映出这些颜色变化

## 代码优化建议

1. **统一SettingsManager使用方式**：
   - 在应用启动时创建唯一的SettingsManager实例，并将其附加到QApplication实例上
   - 所有组件都从应用实例中获取这个唯一实例

2. **颜色计算逻辑集中化**：
   - 将颜色计算逻辑从各个组件中提取出来，集中到一个地方
   - 当基础颜色变化时，自动重新计算所有派生颜色

3. **主题切换时的全局通知机制**：
   - 实现一个全局的主题变化信号
   - 所有组件都监听这个信号，当主题变化时自动更新样式
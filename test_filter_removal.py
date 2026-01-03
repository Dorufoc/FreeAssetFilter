# 测试筛选移除功能的脚本
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from freeassetfilter.app.main import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    # 测试筛选移除功能
    def test_filter_removal():
        # 获取文件选择器组件
        file_selector = window.file_selector
        
        # 首先设置一个筛选条件
        file_selector.filter_pattern = "*.mp4"
        file_selector._update_filter_button_style()
        file_selector.refresh_files()
        
        print("\n=== 测试筛选移除功能 ===")
        print(f"设置筛选条件后，筛选模式: {file_selector.filter_pattern}")
        print(f"筛选按钮样式: {file_selector.filter_btn.button_type}")
        
        # 模拟移除筛选
        file_selector.filter_pattern = "*"
        file_selector._update_filter_button_style()
        file_selector.refresh_files()
        
        print(f"移除筛选条件后，筛选模式: {file_selector.filter_pattern}")
        print(f"筛选按钮样式: {file_selector.filter_btn.button_type}")
        print("筛选移除功能测试完成！")
    
    # 延迟执行测试，确保UI已初始化
    QTimer.singleShot(2000, test_filter_removal)
    
    sys.exit(app.exec_())
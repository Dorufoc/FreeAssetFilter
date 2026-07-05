"""
FreeAssetFilter 后台工作线程模块

包含从 UI 组件中提取的所有 QThread/QRunnable 子类：
- file_list_loader: 文件列表异步加载
- drive_list_loader: 盘符异步扫描
- staging_tasks: 暂存池 MD5 计算等后台任务

与 services/ 层的服务协作，通过 Qt 信号传递结果。
"""

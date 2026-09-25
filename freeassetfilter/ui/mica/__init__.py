"""``ui.mica`` —— 无 DWM 依赖、纯自主渲染的 Mica 实现。

包结构：
* ``config``   —— 参数模型（用户参数 ↔ 引擎参数映射）。纯数据，可无 GUI 测试。
* ``tint``     —— Oklab 色彩科学内核（去明度 / 色度低通 / 等亮度重建 / 颜色混合）。
* ``resample`` —— 抗锯齿重采样与 mip 缓存。
* ``source``   —— 壁纸源采集后端链（IDesktopWallpaper / DXGI / GDI / SPI 注册表）。
* ``engine``   —— 烘焙编排（采样几何 + 分辨率决策 + 调度 tint）。
* ``material`` —— Qt 门面（后台线程烘焙、QPixmap 转换、淡入淡出、焦点、绘制）。

为避免无 GUI 环境下导入数据层也连带拉起 Qt，本 ``__init__`` 只导出纯数据 / 数值
模块；需要 Qt 门面时请显式 ``from freeassetfilter.ui.mica.material import MicaMaterial``。

导入成本约定（首屏关键路径）：本 ``__init__`` **只主动导入 ``config``**（纯数据，
零第三方依赖）。``tint`` / ``resample`` / ``source`` / ``engine`` 均依赖 numpy
（约 0.13s），改由调用方按需触发 —— ``from freeassetfilter.ui.mica import engine``
这类写法无需 ``__init__`` 预导入（Python 会自动加载子模块）。主窗口在窗口显示前
只需 ``config.DEFAULT_MICA_CONFIG`` 与 ``winapi``（ctypes 薄封装），因此这两者
之外的重型子模块不得在此预导入，否则 numpy 会被拽进「窗口出现前」的关键路径。
"""

from . import config

__all__ = ["config"]

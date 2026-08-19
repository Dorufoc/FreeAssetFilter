# FreeAssetFilter 测试套件指南

本文档介绍仓库 `tests/` 目录的结构、各测试文件覆盖的对象，以及如何运行测试。面向维护者与贡献者，全部示例命令均在 Windows 环境下以 PowerShell 执行为准。

## 目录总览

```
tests/
├── conftest.py              # 顶层 fixture 工厂（QApplication、单例重置、原生可用性探测等）
├── run_tests.py             # 官方测试运行器（子命令式封装 pytest）
├── __init__.py
├── benchmark/               # 性能基准测试与回归检查（默认排除，需显式指定范围）
├── components/              # 上层业务组件的集成级测试（文件选择器、暂存池、预览器等）
├── gui/                     # 可视化 GUI 测试（需要真实显示器）
├── integration/             # 跨模块联动、全生命周期与真实二进制集成的测试
├── support/                 # 测试基础设施（fixture 辅助、日志、超时策略、覆盖清单等）
├── unit/                    # 单体测试（core / services / ui / utils / workers 五块）
└── widgets/                 # 自定义 QWidget 与模型/委派测试
```

各目录定位：

| 目录 | 定位 |
| --- | --- |
| `benchmark/` | 缩略图、缓存、SVG 等性能基准与回归对比，耗时较长，默认排除 |
| `components/` | 面向 `freeassetfilter/components/` 业务组件的测试，偏 UI 交互 |
| `gui/` | 渲染矩阵与主题视觉测试，必须真实显示器 |
| `integration/` | 跨组件流程、线程安全、设置持久化、真实二进制（MPV / FFmpeg）集成 |
| `support/` | 非测试代码的基础设施模块，被 conftest 与运行器引用 |
| `unit/` | 按模块划分的细粒度单体测试，数量最多 |
| `widgets/` | 自定义控件与其配套的模型、委托渲染测试 |

## 各测试文件职责

### benchmark/（性能基准）

| 文件 | 职责 |
| --- | --- |
| `perf_benchmark_utils.py` | 性能基准测试的通用辅助工具 |
| `perf_regression.py` | 基线文件对比，检查性能是否发生回归 |
| `test_batch_thumbnail_perf.py` | 批量缩略图生成的性能基准 |
| `test_cache_perf.py` | 缩略图缓存的读写性能基准 |
| `test_perf_metrics_pipeline.py` | 性能指标采集流水线测试 |
| `test_svg_perf.py` | SVG 渲染性能基准 |
| `test_thumbnail_perf.py` | 单张缩略图生成性能基准 |

### components/（业务组件）

| 文件 | 职责 |
| --- | --- |
| `test_file_selector.py` | 文件选择器组件核心行为（当前维护基准） |
| `test_file_staging_pool.py` | 文件暂存池组件 |
| `test_previewers.py` | 预览器全家桶，覆盖统一预览器、照片查看器、视频播放、PDF、文本、字体、压缩包浏览、目录内容列表、文件信息预览等 10 个模块 |
| `test_settings_window.py` | 设置窗口、主题编辑器与更新控制器联动 |
| `test_update_controller.py` | 更新控制器补强测试（检查与下载状态机） |

### gui/（可视化测试，需真实显示器）

| 文件 | 职责 |
| --- | --- |
| `test_render_matrix.py` | GUI 渲染矩阵验证 |
| `test_theme_visual.py` | 主题切换的视觉验证 |

### integration/（集成测试）

| 文件 | 职责 |
| --- | --- |
| `test_main_app.py` | 应用入口集成 |
| `test_module_imports.py` | 全量模块导入冒烟 |
| `test_mpv_integration.py` | MPV 模块集成（真实 libmpv 分支按可用性跳过） |
| `test_selector_preview_pool_flow.py` | 选择器到预览到暂存池的联动流程 |
| `test_settings_persistence.py` | 设置持久化往返 |
| `test_thread_safety.py` | 跨线程安全与并发写入 |
| `test_thumbnail_lifecycle.py` | 缩略图从生成到缓存到清理的全生命周期 |
| `test_ffmpeg_minimal_binaries.py` | FFmpeg 精简二进制可用性验证 |

### unit/core/（核心模块）

| 文件 | 职责 |
| --- | --- |
| `test_color_extractor.py` | 颜色提取核心逻辑 |
| `test_image_color_utils.py` | 图像颜色工具函数 |
| `test_heartbeat_manager.py` | 心跳管理器调度与注册/注销 |
| `test_lut_preview_generator.py` | LUT 预览生成器（C++ 与 Python 双实现） |
| `test_media_probe.py` | 媒体信息探测 |
| `test_mpv_manager.py` | MPV 管理器（全局队列锁、生命周期） |
| `test_mpv_player_core.py` | MPV 播放核心（信号、命令、错误码） |
| `test_paths.py` | `core/_paths.py` 资源路径解析 |
| `test_py7z_core.py` | 7z 压缩核心 |
| `test_rust_color_extractor.py` | Rust 颜色提取 DLL 的 ctypes 桥 |
| `test_rust_thumbnail_bridge.py` | Rust 缩略图生成桥 |
| `test_settings_manager.py` | 设置管理器读写与防抖保存 |
| `test_svg_renderer.py` | SVG 渲染器 |
| `test_theme_manager.py` | 主题管理器 |
| `test_thumbnail_manager.py` | 缩略图管理器缓存与生成 |
| `test_update_manager.py` | 更新检查与版本比较 |

### unit/services/（业务服务层）

| 文件 | 职责 |
| --- | --- |
| `test_base.py` | BaseService 基类 |
| `test_drive_service.py` | 磁盘驱动器枚举服务 |
| `test_favorites_service.py` | 收藏服务 |
| `test_file_icon_manager.py` | 文件图标管理器 |
| `test_file_service.py` | 文件服务 |
| `test_image_services.py` | ImageDecoderService 及其工作线程 |
| `test_media_metadata_service.py` | 媒体文件元数据服务 |
| `test_office_converter.py` | Office 转换服务及其工作线程与缓存 |
| `test_pdf_services.py` | PDF 文档、视图与后台渲染 |
| `test_previewer_registry.py` | 预览器注册表 |
| `test_repositories.py` | settings / favorites / office_cache 三类数据仓库 |
| `test_staging_pool_service.py` | 暂存池服务 |

### unit/ui/（界面层）

| 文件 | 职责 |
| --- | --- |
| `test_main_window.py` | 主窗口结构与延迟面板构建 |
| `components/test_styled_basic.py` | ui/components 下全部 26 个 `styled_*` 基础组件 |
| `components/test_styled_complex.py` | 手风琴、轮播、表格、时间线等复杂 styled 组件 |
| `components/test_styled_fluid.py` | fluid 数学与背景动效组件 |
| `layout/test_layouts.py` | 各主界面布局（文件池、选择器、设置、预览器各布局） |
| `theme/test_ui_theme.py` | 界面主题与适配中心 |

### unit/utils/（工具模块）

| 文件 | 职责 |
| --- | --- |
| `test_animation_settings.py` | 动画设置工具 |
| `test_app_logger.py` | 应用日志器 |
| `test_async_icon_loader.py` | 异步图标加载器 |
| `test_file_icon_helper.py` | 文件图标辅助 |
| `test_global_mouse_monitor.py` | 全局鼠标监听 |
| `test_icon_utils.py` | 图标处理工具 |
| `test_lut_utils.py` | LUT 工具 |
| `test_markdown_renderer.py` | Markdown 渲染 |
| `test_path_utils.py` | 路径处理工具 |
| `test_perf_metrics.py` | 性能指标统计 |
| `test_subprocess_utils.py` | 子进程工具 |
| `test_syntax_highlighter.py` | 语法高亮引擎 |

### unit/workers/（后台线程）

| 文件 | 职责 |
| --- | --- |
| `test_drive_list_loader.py` | DriveListLoaderThread 磁盘枚举线程 |
| `test_file_list_loader.py` | FileListLoaderThread 文件列表加载线程 |
| `test_staging_tasks.py` | MD5CalculationTask 等暂存池后台任务 |

### widgets/（自定义控件）

| 文件 | 职责 |
| --- | --- |
| `test_basic_widgets.py` | 18 个基础控件（按钮、滑块、进度条、弹窗、开关等） |
| `test_card_delegates.py` | 文件卡片委派渲染 |
| `test_D_widgets.py` | D 系列特效控件（悬浮菜单、音量控件、播放控制条、LUT 对话框等） |
| `test_file_models.py` | 选择器与暂存池的列表模型和委派 |

## 如何运行测试

### 官方运行器（推荐）

```bash
# 运行一个范围（子命令对应目录）：unit / widgets / components / integration / gui / benchmark
python tests/run_tests.py unit

# 所有非 GUI / 非基准测试
python tests/run_tests.py all

# 收集模式（只收集不执行，验证收集是否正常）
python tests/run_tests.py unit --co

# 覆盖率（等同 all 范围 + --cov=freeassetfilter --cov-report=term）
python tests/run_tests.py coverage --strict
```

运行器要点：

- 范围子命令：`all` / `unit` / `widgets` / `components` / `integration` / `gui` / `benchmark` / `coverage` / `regression`。
- 默认 `QT_QPA_PLATFORM=offscreen`（无头模式）；`--visual` 时取消 offscreen 并置 `FAF_VISUAL=1`，用于 gui 目录。
- 默认 `--timeout 30`（benchmark / regression 默认 300）；可用 `--timeout N` 覆盖。
- 支持透传 `-k`、`-x`、`--tb`、`--co`（`--collect-only`）等 pytest 参数。
- `coverage --strict` 会额外启用 `tests/support/coverage_manifest` 覆盖清单检查。

### 原生 pytest 用法

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行单个文件
python -m pytest tests/unit/test_file_selector.py -v

# 按关键词过滤
python -m pytest tests/ -k "thumbnail" -v

# GUI 测试（需要真实显示器）
python -m pytest tests/gui/ -v

# 性能基准测试
python -m pytest tests/benchmark/ -v

# 覆盖率报告
python -m pytest tests/ --cov=freeassetfilter --cov-report=term
```

### 覆盖度量

```bash
# 先度量，再出报告（--timeout 120 防止个别用例悬挂）
python -m coverage run -m pytest <target> -q --timeout 120
python -m coverage report
```

其中 `<target>` 可以是 `tests/unit/`、`tests/components/test_previewers.py` 等任意收集目标。内存中的 `freeassetfilter` 包与测试本身均可被度量。

## conftest 关键 Fixtures

`tests/conftest.py` 提供两类基础设施：会话级可用性探测（决定跳过还是执行）与函数级单例隔离。主要 fixture 一览：

| Fixture | 作用域 | 用途 |
| --- | --- | --- |
| `qapp` | session | 全局唯一 QApplication，附带 `dpi_scale_factor`、`global_font` 及应用级 `settings_manager` / `theme_manager` |
| `qt_app` | function | `qapp` 的别名，兼容旧式引用 |
| `reset_singletons` | function（autouse） | 每个测试前后重置 SettingsManager / HeartbeatManager / ThumbnailManager / MPVManager / AppLogger / AsyncIconLoader 等单例，保证隔离 |
| `settings_manager` | function | 绑定临时 `settings.json` 的全新 SettingsManager 实例 |
| `heartbeat_manager` | function | 创建并启动新 HeartbeatManager，teardown 时 `stop_all()` |
| `mpv_available` | session | 探测 `libmpv-2.dll` 可加载性（系统路径加捆绑 bin 目录） |
| `rust_available` | session | 探测 Rust 原生 DLL（`rust_color_extractor_native.dll` / `thumbnail_generator.dll`） |
| `cpp_lut_available` | session | 探测 C++ LUT 预览 .pyd 扩展可用性 |
| `py7z_available` | session | 探测 py7zr 可导入或捆绑 `7z.exe` 存在 |
| `soffice_available` | session | 探测 LibreOffice `soffice` 可执行文件 |
| `com_available` | session | 探测 MS Office / WPS COM ProgID |
| `ffmpeg_available` | session | 探测捆绑 `ffmpeg.exe` 且 `-version` 返回 0 |

另有数据生成 fixture 全部基于 `tests/support/data_factories`：`sample_image_file`、`sample_pdf_file`、`sample_text_file`、`sample_zip_file`、`sample_svg_file`、`sample_font_file`、`sample_dir`、`sample_dir_info`、`sample_file_info`（可经 parametrize 指定扩展名）、`sample_image_data`、`temp_file`、`temp_settings_file`、`settings_file`，以及基准用 `benchmark_dataset`、`video_sample_paths` 与 GUI 开关 `visual_mode`。`_reset_all_singletons` 是普通辅助函数（非 fixture），供 `reset_singletons` 两阶段复用。

## 测试注意事项

- **GUI 测试需要真实显示器**：`tests/gui/` 走真实渲染断言，无头环境（CI）需设置 `QT_QPA_PLATFORM=offscreen`，或在无显示器的机器上跳过该目录。
- **单例在测试间持久**：SettingsManager / HeartbeatManager 等单例跨测试存活，`reset_singletons` autouse fixture 会在每个测试函数前后归零。若引入新的单例管理器，记得同步到 `_reset_all_singletons` 重置清单。
- **依赖原生二进制的测试自动跳过**：libmpv-2.dll、Rust DLL、7z.exe、soffice、ffmpeg.exe 等均通过对应的 `*_available` fixture 作 session 级探测，缺失时相关测试 `pytest.skip`，不影响其余用例。
- **support/ 模块用途**：
  - `qt_helpers.py`：Qt 辅助，提供事件泵（`flush_widget_queue`）、信号等待（`wait_for_signal`）与安全清理（`safe_teardown`）。
  - `data_factories.py`：测试数据工厂，按需生成图片、PDF、文本、压缩包、音频、字体与文件信息字典。
  - `log_setup.py`：接管 pytest 日志，将输出双写到 `tests/log/`。
  - `progress.py`：运行进度条报告插件。
  - `timeout_policy.py`：目录级超时策略，统一显式 marker、自动打标与 CLI `--timeout` 的优先级。
  - `coverage_manifest.py`：覆盖清单扫描，检测缺测模块并告警。
- **已知注意点**：
  - 测试全局日志为双写（stdout/stderr 与日志文件同时记录）。
  - `--cov-branch` 分支覆盖因触发原生崩溃而禁用，只用行覆盖。
  - `rg` 命令行在本机不可用，搜索请用 `Select-String` 或 `findstr`。
  - 组合运行曾偶发 access violation 与心跳时序问题，已通过将事件泵浦超时从 5s 提升到 15s 修复；若再遇"回调未在超时前触发"的失败，建议继续增大 `_pump_until` 的超时值。

## 覆盖成果（参考）

| 目标 | 行覆盖 |
| --- | --- |
| previewers 预览器链 | 84% ~ 99% |
| file_selector 文件选择器 | 88% |
| mpv_player_core | 54% |
| mpv_manager | 66% |
| update_controller | 99% |
| app/main | 62% |
# FreeAssetFilter 测试套件指南

本文档介绍仓库 `tests/` 目录的结构、各测试文件覆盖的对象，以及如何运行测试。面向维护者与贡献者，全部示例命令均在 Windows 环境下以 PowerShell 执行为准。

## 目录总览

```
tests/
├── conftest.py              # 顶层 fixture 工厂（QApplication、单例重置、原生可用性探测等）
├── run_tests.py             # 官方测试运行器（子命令式封装 pytest，共 5 个子命令）
├── __init__.py
├── gui/                     # 可视化 GUI 测试（需要真实显示器）
├── integration/             # 跨模块联动、全生命周期与真实二进制集成的测试
├── log/                     # 测试运行日志（运行时生成，gitignore）
├── support/                 # 测试基础设施（fixture 辅助、日志、超时策略、覆盖清单、parity 工具等）
└── unit/                    # 单体测试（core / services / ui / utils / workers 五块）
```

各目录定位：

| 目录 | 定位 |
| --- | --- |
| `gui/` | 主题切换视觉一致性测试，必须真实显示器（`QT_QPA_PLATFORM` 取消 offscreen） |
| `integration/` | 跨组件流程、线程安全、模块导入冒烟、真实二进制（MPV / FFmpeg / Rust DLL）集成 |
| `support/` | 非测试代码的基础设施模块，被 conftest 与运行器引用 |
| `unit/` | 按模块划分的细粒度单体测试，数量最多 |
| `unit/ui/` | UI 层测试（组件 / 布局 / Mica / 主题 / 主窗口与无边框窗口） |

## 各测试文件职责

### gui/（可视化测试，需真实显示器）

| 文件 | 职责 |
| --- | --- |
| `conftest.py` | GUI 视觉测试配置（截图目录、事件冲刷、视觉模式开关） |
| `test_theme_visual.py` | 主题切换视觉一致性测试（产出 `screenshots/` 基线截图） |

### integration/（集成测试）

| 文件 | 职责 |
| --- | --- |
| `test_bootstrap.py` | 应用引导层（`app/main`、`instance_guard`、`startup`）集成测试 |
| `test_ffmpeg_minimal_binaries.py` | 精简 ffmpeg / ffprobe 二进制契约验证 |
| `test_module_imports.py` | 全量模块导入冒烟（覆盖清单 AST 清单驱动） |
| `test_mpv_integration.py` | MPV 管理器集成（mock + 真实 DLL 门控分支） |
| `test_rust_thumbnail_comprehensive.py` | Rust 缩略图综合验证（图像精度 + 视频功能） |
| `test_rust_thumbnail_concurrency.py` | Rust 缩略图并发加速比与线程池预算 |
| `test_selector_thumbnail_flow.py` | 文件选择器缩略图端到端流程（生成 → 回填 → 清除全链路） |
| `test_thread_safety.py` | 管理器 50 线程并发安全 |
| `test_thumbnail_lifecycle.py` | 缩略图批量生成 / 缓存 / 清理生命周期 |

### support/（测试基础设施）

| 文件 | 职责 |
| --- | --- |
| `coverage_manifest.py` | 覆盖清单扫描：源公开符号 × 测试目标缺失矩阵与孤儿告警（`coverage --strict` 门禁） |
| `data_factories.py` | 测试数据工厂（图片 / PDF / 文本 / 压缩包 / 音频 / 字体 / 文件信息字典） |
| `log_setup.py` | pytest 日志环境：日志目录准备、双写流与根 logger 接管 |
| `progress.py` | 运行进度条与周期小结、最慢测试统计插件 |
| `qt_helpers.py` | Qt 测试辅助（事件泵、DeferredDelete 派发、信号等待、安全清理、非空断言） |
| `timeout_policy.py` | 目录级超时策略：marker→超时映射、自动打标与 CLI 兜底优先级 |
| `test_parity_helper.py` | parity 辅助工具自测（相等 PASS / 不等 FAIL / 清单豁免 / 像素 hash） |
| `parity/comparator.py` | 逐字段 parity 断言：python 实现输出 vs native 输出 |
| `parity/normalize_html.py` | HTML 归一化器（Markdown 渲染对拍用） |
| `parity/pixels.py` | 像素 parity 断言：多源图像归一化 RGBA + 确定性 hash + 逐像素差异诊断 |
| `faf_core_fixtures/` | 夹具集（code_samples / dir_samples / encoding_samples / exif_samples / fluid_samples / font_samples / markdown_samples / pdf_samples / psd_samples / seven_zip_samples / svg_samples）；`generate_fixtures.py` 为固定 seed 生成脚本 |

### unit/core/（核心模块，24 个测试文件）

| 文件 | 职责 |
| --- | --- |
| `test_faf_core_bridge.py` | faf_core DLL ctypes 桥（扫描/排序/哈希/EXIF/SVG/7z 等） |
| `test_heartbeat_manager.py` | HeartbeatManager 调度、注册/注销与跨线程 FutureHandle |
| `test_image_color_utils.py` | 预览层图像色彩工具（RAW 解码 / ICC / EXIF 方向） |
| `test_lut_preview_generator.py` | LUT 预览生成器（C++ 与 Python 双实现） |
| `test_lut_preview_native.py` | C++ LUT 扩展加载缓存与重试策略 |
| `test_manager_matrix.py` | 三级格式矩阵分类函数、分桶路由与回退样本 |
| `test_media_probe.py` | ffprobe/ffmpeg 媒体信息探测 |
| `test_mpv_manager.py` | MPVManager（队列锁、崩溃健康检测、生命周期） |
| `test_mpv_player_core.py` | MPV 播放核心（信号、命令、错误码） |
| `test_paths.py` | `core/_paths.py` 资源路径解析 |
| `test_platform_gpu.py` | PE 导出表解析与独显路由档位校验 |
| `test_platform_monitor.py` | W9/W10 DWM 探测与 USER/GDI 句柄预算采样 |
| `test_platform_threads.py` | Windows 线程电源节流 / CPU 亲和 / MMCSS / 优先级封装 |
| `test_platform_timing.py` | W5 高精度定时器与 W6 交换链延迟探测 |
| `test_py7z_core.py` | 7z 压缩包处理核心（列表/加密检测/完整性测试） |
| `test_rust_batch_concurrency.py` | Rust 批量缩略图并发压测 |
| `test_rust_bridge_new_exports.py` | Rust 桥新导出接线 |
| `test_rust_thumbnail_bridge.py` | Rust 缩略图生成桥 |
| `test_settings_manager.py` | `SettingsManagerV2` 单元测试 |
| `test_settings_manager_v2.py` | SettingsManagerV2 专项补充（点号路径/迁移/原子写） |
| `test_status_channel.py` | 缩略图状态通道（桥层直测 + ThumbnailManager 路由） |
| `test_svg_renderer.py` | SVG 渲染器（native 换色 + Python 回退） |
| `test_thumbnail_fixtures.py` | 全格式夹具经桥命中 T1 原生路径回归 |
| `test_thumbnail_manager.py` | ThumbnailManager 缓存与生成、四队列调度 |

### unit/services/（业务服务层，13 个测试文件）

| 文件 | 职责 |
| --- | --- |
| `test_base.py` | `BaseService` 生命周期模板 |
| `test_encoding_native_parity.py` | 编码探测 native（faf_core）vs chardet 对拍 |
| `test_favorites_service.py` | 收藏夹 CRUD 与 JSON 持久化 |
| `test_file_icon_manager.py` | 文件类型图标管线（SVG/缩略图/系统图标 + 缓存） |
| `test_file_info_service.py` | 文件信息采集（stat/EXIF/字体/编码/压缩包/哈希 + 缓存） |
| `test_font_native_parity.py` | 字体 native vs fontTools 对拍 |
| `test_image_services.py` | `ImageDecoderService` 与 `ImageDecodeWorker` |
| `test_media_metadata_service.py` | 音频标签 / 封面 / 编码参数提取 |
| `test_office_converter.py` | Office 转换器、异步 worker 与磁盘缓存联动 |
| `test_pdf_services.py` | `PdfDocument` / `PdfDocumentView` / 后台 PDF 渲染器 |
| `test_previewer_registry.py` | 预览器注册表（扩展名→类惰性映射） |
| `test_repositories.py` | `office_cache` 仓库行为 |
| `test_staging_pool_service.py` | 存储池服务（增删查清、磁盘空间、备份序列化） |

### unit/ui/（界面层）

| 文件 | 职责 |
| --- | --- |
| `test_frameless_window.py` | 自研无边框基类（ExpandedClientAreaHint、NCHITTEST 命中） |
| `test_import_compat.py` | `theme` / `components` 短路径与规范路径导入别名收敛 |
| `test_main_window.py` | 主窗口结构与延迟面板构建 |
| `test_main_window_settings_close.py` | 设置窗口关闭引用清理与 closeEvent 纵深防御 |
| `components/test_custom_background.py` | 自定义窗口背景（cover / 快缩 / 持久化） |
| `components/test_styled_basic.py` | 基础 styled 组件（按钮、输入、开关等） |
| `components/test_styled_button_progress.py` | StyledButton 运行时进度模式 |
| `components/test_styled_complex.py` | 手风琴、轮播、表格、时间线等复杂组件 |
| `components/test_styled_fluid.py` | 流体数学与背景动效、文件列表组件 |
| `components/test_styled_loading.py` | StyledLoading 加载动画 |
| `layout/test_box_selection.py` | 框选手势共享组件 |
| `layout/test_file_selector_native_wiring.py` | 文件选择器 faf_core native 接线 |
| `layout/test_layouts.py` | 各主界面布局（文件池、选择器、设置、统一预览与各预览器、调色板对拍等） |
| `layout/test_main_layout.py` | MainLayout 两种装配（classic / workspace）与比例规则 |
| `layout/test_perf_profile_staging.py` | 性能档位三段选择器暂存隔离 |
| `layout/test_settings_staging_cache.py` | 设置暂存缓存与底部按钮组 |
| `layout/preview/test_archive_previewer_layout.py` | 压缩包预览器 |
| `layout/preview/test_file_info_panel.py` | 文件信息面板异步采集 |
| `layout/preview/test_folder_previewer_layout.py` | 文件夹预览器 |
| `layout/preview/test_native_pdf_renderer.py` | QPainter 交互式 PDF 渲染控件 |
| `layout/preview/test_pdf_drawer_async.py` | PDF 缩略图抽屉异步批处理 |
| `layout/preview/test_preview_loading_states.py` | 各预览器加载圆环显隐与主线程非阻塞行为 |
| `layout/preview/test_preview_toolbar.py` | 共享预览顶栏框架 |
| `layout/preview/test_zoom_popups.py` | 缩放 / 字重弹窗生命周期与随动 |
| `mica/test_compositor_present.py` | 合成器呈现调度 |
| `mica/test_drag_perf.py` | 拖动期快速路径性能回归门禁 |
| `mica/test_engine_display_banding.py` | 引擎显示分辨率 / 抖动 / 预合成纯函数 |
| `mica/test_mica_drag.py` | 拖动纯几何 / 视口层 |
| `mica/test_mica_layer.py` | 视口层 + material 层拖动层级验收 |
| `mica/test_mica_material_drag.py` | material 视口层拖动行为 |
| `mica/test_mica_tint.py` | 色彩混合与量化回归 |
| `mica/test_winapi_dwm.py` | 原生 DWM 云母桥接 |
| `theme/test_app_stylesheet.py` | 应用级 QSS 注册表单例与作用域改写 |
| `theme/test_ui_theme.py` | 系统强调色读取与 ThemeManager 单例 |

### unit/utils/（工具模块）

| 文件 | 职责 |
| --- | --- |
| `test_animation_settings.py` | 动画开关读取辅助 |
| `test_app_logger.py` | 应用日志器（双写 / 脱敏 / 去重压缩） |
| `test_async_icon_loader.py` | 系统图标异步加载器 |
| `test_fd_capture.py` | fd 1/2 重定向捕获原生输出 |
| `test_file_icon_helper.py` | 文件类型图标路径解析 |
| `test_icon_utils.py` | 系统图标提取（HICON→QPixmap、exe 图标枚举） |
| `test_lut_utils.py` | CUBE LUT 解析 / 验证 / 管理 |
| `test_markdown_renderer.py` | Markdown → 自包含主题 HTML |
| `test_path_utils.py` | 路径解析与文件系统访问控制 |
| `test_perf_metrics.py` | 统一性能埋点（计数 / 分位 / 快照） |
| `test_qt_message_handler.py` | qInstallMessageHandler 桥接与防回环 |
| `test_subprocess_utils.py` | 受限输出捕获 subprocess 辅助 |
| `test_syntax_highlighter.py` | 语法高亮引擎（native / pygments 双链） |

### unit/workers/（后台线程）

| 文件 | 职责 |
| --- | --- |
| `test_drive_list_loader.py` | DriveListLoaderThread 盘符枚举与可用性检查任务 |
| `test_file_list_loader.py` | FileListLoaderThread 目录扫描任务 |
| `test_staging_tasks.py` | MD5CalculationTask 等暂存池后台任务 |
| `test_thumbnail_controller.py` | ThumbnailController 生成 / 清除后台编排（世代 token） |

## 如何运行测试

### 官方运行器（推荐）

```powershell
# 运行一个范围（子命令对应目录）：unit / integration / gui
python tests/run_tests.py unit

# 所有非 GUI 测试
python tests/run_tests.py all

# 收集模式（只收集不执行，验证收集是否正常）
python tests/run_tests.py unit --co

# 覆盖率（等同 all 范围 + --cov=freeassetfilter --cov-report=term）
python tests/run_tests.py coverage --strict
```

运行器要点：

- 子命令共 5 个：`all` / `unit` / `integration` / `gui` / `coverage`。
- 默认 `QT_QPA_PLATFORM=offscreen`（无头模式）；`--visual` 时取消 offscreen 并置 `FAF_VISUAL=1`，用于 gui 目录。
- 默认 `--timeout 30`；可用 `--timeout N` 覆盖，但**不覆盖**显式 timeout marker（见 `support/timeout_policy.py`）。
- 支持透传 `-k`、`-x`、`--tb`、`--co`（`--collect-only`）等 pytest 参数。
- `coverage --strict` 会额外启用 `tests/support/coverage_manifest` 覆盖清单检查。

### 原生 pytest 用法

```powershell
# 运行全部测试
python -m pytest tests/ -v

# 运行单个文件
python -m pytest tests/unit/services/test_file_info_service.py -v

# 按关键词过滤
python -m pytest tests/ -k "thumbnail" -v

# GUI 测试（需要真实显示器）
python -m pytest tests/gui/ -v

# 覆盖率报告
python -m pytest tests/ --cov=freeassetfilter --cov-report=term
```

### 覆盖度量

```powershell
# 先度量，再出报告（--timeout 120 防止个别用例悬挂）
python -m coverage run -m pytest <target> -q --timeout 120
python -m coverage report
```

其中 `<target>` 可以是 `tests/unit/`、`tests/integration/` 等任意收集目标。内存中的 `freeassetfilter` 包与测试本身均可被度量。

## conftest 关键 Fixtures

`tests/conftest.py` 提供两类基础设施：会话级可用性探测（决定跳过还是执行）与函数级单例隔离。主要 fixture 一览：

| Fixture | 作用域 | 用途 |
| --- | --- | --- |
| `qapp` | session | 全局唯一 QApplication，附带 `global_font` 与 `settings_manager` 占位属性；主题/设置单例由需要的测试自行注入 |
| `qt_app` | function | `qapp` 的别名，兼容旧式引用 |
| `reset_singletons` | function（autouse） | 每个测试前后重置 ThumbnailManager / MPVManager / HeartbeatManager / AppLogger / AsyncIconLoader 等单例，保证隔离 |
| `scavenge_leaked_toplevel_widgets` | function（autouse） | 每个测试结束销毁本测试新建的顶层窗口（含 Mica 材质 dispose 与 DeferredDelete 派发） |
| `cleanup_qt_runtime` | session（autouse） | 会话结束回收 Mica GPU 渲染器常驻线程与全局线程池 |
| `settings_manager` | function | 绑定临时 `settings.json` 的全新 SettingsManager 实例 |
| `heartbeat_manager` | function | 创建并启动新 HeartbeatManager，teardown 时 `stop_all()` |
| `mpv_available` | session | 探测 `libmpv-2.dll` 可加载性（系统路径加捆绑 bin 目录） |
| `rust_available` | session | 探测 Rust 原生 DLL（`faf_core.dll` / `thumbnail_generator.dll`） |
| `cpp_lut_available` | session | 探测 C++ LUT 预览 .pyd 扩展可用性 |
| `py7z_available` | session | 探测 py7zr 可导入或捆绑 `7z.exe` 存在 |
| `soffice_available` | session | 探测 LibreOffice `soffice` 可执行文件 |
| `com_available` | session | 探测 MS Office / WPS COM ProgID（注册表不可用时回退 win32com） |
| `ffmpeg_available` | session | 探测捆绑 `ffmpeg.exe` 且 `-version` 返回 0 |

另有数据生成 fixture 全部基于 `tests/support/data_factories`：`sample_image_file`、`sample_pdf_file`、`sample_text_file`、`sample_zip_file`、`sample_svg_file`、`sample_font_file`、`sample_dir`、`sample_dir_info`、`sample_file_info`（可经 parametrize 指定扩展名）、`sample_image_data`、`temp_file`、`temp_settings_file`、`settings_file`，以及 `video_sample_paths` 与 GUI 开关 `visual_mode`。`_reset_all_singletons` 是普通辅助函数（非 fixture），供 `reset_singletons` 两阶段复用。

## 测试注意事项

- **GUI 测试需要真实显示器**：`tests/gui/` 走真实渲染断言，无头环境（CI）需设置 `QT_QPA_PLATFORM=offscreen`，或在无显示器的机器上跳过该目录。
- **单例与模块级缓存跨测试隔离**：类级单例（HeartbeatManager / ThumbnailManager / MPVManager / AppLogger）、模块级惰性缓存（thumbnail_manager / app_logger / async_icon_loader / faf_core 桥 / lut_preview_generator / lut_preview_native / mica_render / py7z_core）与 QSS 注册表均由 autouse fixture `reset_singletons` 在每个测试函数前后归零；清单与"明确不重置"的例外（`ui/theme` 主题单例，见原因）都以 `_reset_all_singletons` 的 docstring 为准。若引入新的单例/惰性缓存，记得同步到该清单。
- **依赖原生二进制的测试自动跳过**：libmpv-2.dll、Rust DLL、7z.exe、soffice、ffmpeg.exe 等均通过对应的 `*_available` fixture 作 session 级探测，缺失时相关测试 `pytest.skip`，不影响其余用例。
- **support/ 模块用途**：
  - `qt_helpers.py`：Qt 辅助，提供事件泵（`flush_widget_queue`）、DeferredDelete 派发（`drain_deferred_deletes`）、顶层窗口快照/清道夫（`toplevel_widget_snapshot` / `scavenge_toplevel_widgets`）、信号等待（`wait_for_signal`，默认 5s 有界）、条件等待（`wait_until`，可自定义有界超时）与安全清理（`safe_teardown`）。
  - `data_factories.py`：测试数据工厂，按需生成图片、PDF、文本、压缩包、音频、字体与文件信息字典。
  - `log_setup.py`：接管 pytest 日志，将输出双写到 `tests/log/`。
  - `progress.py`：运行进度条报告插件。
  - `timeout_policy.py`：目录级超时策略，统一显式 marker、自动打标与 CLI `--timeout` 的优先级。
  - `coverage_manifest.py`：覆盖清单扫描，检测缺测模块并告警。
- **可选/开发依赖**：`requirements-dev.txt` 的 `psutil` 供并发与内存探针测试使用；`requirements.txt` 的 `brotli` 供 `fontTools` 解码 WOFF/WOFF2（字体预览对拍依赖）。
- **已知注意点**：
  - 测试全局日志为双写（stdout/stderr 与日志文件同时记录）。
  - `--cov-branch` 分支覆盖因触发原生崩溃而禁用，只用行覆盖。
  - 组合运行曾偶发 access violation 与心跳时序问题，已通过将事件泵浦超时从 5s 提升到 15s 修复；若再遇"回调未在超时前触发"的失败，建议继续增大 `_pump_until` 的超时值。
  - UI 测试大量创建 `MainWindow`/预览布局；`scavenge_leaked_toplevel_widgets` 清道夫依赖显式派发 DeferredDelete + 先 dispose Mica 材质，**不要**把 `deleteLater` 后的控件在未清理材质时强制销毁（原生访问冲突签名见 `safe_teardown`）。
  - `tests/unit/ui/mica/` 单独运行需要 `freeassetfilter/ui` 在 `sys.path`（该目录测试模块自行 bootstrap 的约定，全量运行由其它 UI 测试模块先行完成）。

### 工作区隔离与确定性纪律（review 3.5 收口）

- **数据目录隔离**：`conftest` 在导入期设置 `FAF_DATA_DIR` 指向会话临时目录（`get_app_data_path()` 会优先使用，`utils/path_utils.py` 与 `core/_paths.py` 双实现均支持），任何模块都不会写到仓库真实 `data/`；`redirect_layout_app_data_writes` 仍为布局层提供逐测试临时目录。**新增写盘模块时，一律经 `get_app_data_path()` 取路径**，不要硬编码仓库相对路径。
- **等待纪律**：`wait_for_signal` 只适合"信号预期很快到达"的场景；异步扫描/线程池任务等受负载影响的等待，用 `wait_until(app, predicate, timeout_ms=...)` 或"**先连接信号、再触发动作**"的计数器模式（参考 `test_file_selector_native_wiring.py` 的重扫等待），不要用固定 `time.sleep` 替代等待。刻意模拟延迟/防抖语义的 sleep 保留，但需有注释说明用途。
- **原生资源会话纪律**：Mica GPU 渲染线程与全局 QThreadPool 由 session 级 `cleanup_qt_runtime` 统一回收；`safe_teardown`/清道夫保证 DeferredDelete 落地。不要绕过这些设施强杀控件或线程。
- **超时策略单一事实源**：`support/timeout_policy.py` 定义目录级超时与显式 marker 的优先级；单个用例若需更长超时，用 `@pytest.mark.timeout(N)` 显式声明，不要改全局值。
- **异常卫生门禁**：`tests/unit/test_exception_policy.py` 扫描全仓，宽泛 `except Exception/BaseException:`（含裸 `except:`）且处理体仅 `pass` 时必须就地写明理由注释；新代码请补 `debug/warning` 留痕或理由注释。

## 覆盖成果（历史参考）

以下为 tests-comprehensive-refactor 计划收口时的覆盖快照，仅作参考、不构成门禁（`coverage --strict` 的 manifest 检查才是门禁）：

| 目标 | 行覆盖 |
| --- | --- |
| previewers 预览器链 | 84% ~ 99% |
| file_selector 文件选择器 | 88% |
| mpv_player_core | 54% |
| mpv_manager | 66% |
| app/main | 62% |

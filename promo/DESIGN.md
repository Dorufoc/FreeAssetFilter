# Sopeek 宣传站点设计说明

> 这份文档说明 `promo/` 里四种页面的视觉决策从哪来、为什么这么定，以及改动时该动哪些令牌。
> 机器可读版本见 [`design-tokens.json`](design-tokens.json)，唯一实现来源是 [`assets/tokens.css`](assets/tokens.css)。

---

## 1. 美学方向

**一句话**：像一台仪器，不像一张海报。

Sopeek 本身是个高密度、冷色调、以数据为中心的 Windows 桌面工具。所以宣传页不采用「居中大标题 + 紫蓝渐变 + 玻璃卡片」的通用科技落地页语言，而是借用三样东西：

| 取向 | 具体做法 |
|---|---|
| **工程文体** | 栏目编号（01–07）、等宽小字标签、坐标式标注引线、终端代码块。像产品手册而不是广告。 |
| **排版驱动** | 标题用 Bahnschrift（Windows 自带窄体），中文大字走重字重 + 负字距；页面靠字号与留白建立层级，而不是靠插图。 |
| **非对称留白** | 每个栏目左侧固定 116px 索引槽、正文右倾；预览器以单列列表逐条呈现。刻意不居中。 |

**两套语境并存，但共用同一套令牌**：

1. **站点语境**（`index.html` / `video.html`）——暗青近黑底 `#070b0b`，细绿相描边，accent 蓝只出现在关键动作与数据上；浅色主题是同一套令牌的镜像，不是另写一份。
2. **产品语境**（演示片每一帧）——直接呈现真机：`panel_fill = alpha(text,5%)`、`panel_border = alpha(mid,50%)`、8px 面板圆角、4px 卡片间隙、72×102 卡片、48px 标题栏。它是真机渲染结果，不是「网站里的一段 UI 插画」。

---

## 2. 令牌决策与依据

### 色彩

- **`--accent: #3a9dcb`** 直接取自 `src/sopeek/ui/theme/colors.json` 的 `accent.primary`，也和 `assets/example1.png` 里主按钮、环形进度、选中态的实测值一致。出厂默认就是这一项（`colors.json` 只定义 accent.primary，用户可在设置页改色）；宣传页统一展示出厂蓝，并在文案里说明 accent 可变。
- **accent 状态色与 ThemeManager 同构**：`hover = _darken(accent, 0.9)` → `#348eb6`，`press = _darken(accent, 0.8)` → `#2e7da2`（HSV 明度缩放，不是提亮）；实底上的文字 = `tm.white`（`readable_on(#3a9dcb)` 亮度 0.29 < 0.35 也判白）。浅色主题不再整体压深 accent——产品浅色下按钮仍用原 accent 实底，只有文字/图标类强调走 `accent_text = _darken(accent, 0.72) ≈ #2a7192`。
- **所有中间灰都从 `--spk-mid: #888` 派生**（`rgba(136,136,136,α)`），这和 `ThemeManager` 的 `alpha_of(mid, n)` 完全同构。好处是只要改 `mid` 与 `surface`，产品语境的标注与实拍图配色就能保持一致，不会出现「有的描边偏蓝、有的偏灰」。
- **透明度一律取 ThemeManager 定义值**（不再用截图反解的近似）：`panel/bar_fill = α5%`、`card_fill = α85%`、`card_border/control_border/divider = α30%`、`panel_border = α50%`（浅色 36%）、`hover_veil = α25%`、`subtle = α20%`、`track = α40%`；`text_secondary` 深色 = mid 实色、浅色 = α(text,60%)，`text_hint` = α(mid,60%)/α(text,55%)。卡片 hover 不再用「换底色」近似，而是按 `file_card_delegate` 的做法在 `card_fill` 上叠一层 `hover_veil`。
- **面板描边定为 50%**：真机 `panel_border = alpha(mid,50%)`；对截图采样得到 (72,82,81)，在 `#102523` 底上反解约 47%——差异来自 Mica 混色，取 50% 更接近定义值。
- **站点底色偏青**：`#070b0b` / `#0b1211` 比纯黑多一点点绿相，正好呼应 Mica 被壁纸染色后的深青；同时让蓝色 accent 不显脏。
- **第二强调 `--amber: #e9a94b`** 只用在对勾、少数标注与代码注释，占比 < 3%，避免出现第二个主色。

### 字体

- Display 用 **Bahnschrift**：Windows 10/11 自带，窄体、机械感强，和 PySide6 应用的几何 UI 同源；不引入任何网络字体（离线可开、无 FOUT）。
- 正文用 **Segoe UI Variable → 微软雅黑**；产品语境的标注与演示片统一用 `--spk-font`（**Microsoft YaHei UI**），这是 `styled_*` 组件里硬编码的唯一 UI 字体族，读者不会感到「网站和应用不是一家」。
- 等宽用 **Cascadia Mono → Consolas**：真机哈希值列就是 Consolas。
- 中文大标题的实际档位是 `clamp(44px, 5.4vw, 84px)`：`--fs-display`（最大 176px）对中文会炸行，只在英文/数字大字（如 `100+`）里使用。

### 尺寸与间距

- 间距是 4 的倍数阶梯（4/8/12/16/24/32/48/64/96/136），但**卡片间隙 4px、面板间隙 10px、面板圆角 8px、卡片 72×102 是产品事实，不参与阶梯**——文档与演示必须服从真机，不能为了「整齐」把卡片放大或改成 8/12 的圆角。
- 控件几何直接引用 styled_* 的 SIZE_CONFIG：按钮高 28/32/40、圆角 4/5/8（字号 10/10/12pt）；输入框高 30/36/44、圆角 6（字号 12/13/15px）；开关 36×20/44×24/52×28（旋钮绘制为 0.8×）；复选框 14/18/22、圆角 3/4/5；滚动条手柄 4px（hover/按下 6px、边缘留白 2px、三档 alpha 40/80/100%，浅色 55/75/95%）。
- 三栏内部是**三张独立卡片**（顶栏卡 / 内容卡 / 底栏卡），不是一张卡加两条分割线。这一点最初做错过，靠对截图 y 轴采样（1144 描边 → 1148–1160 背景 → 1164 面板底）确认后重写。
- 窗口圆角在站点里给 12px，是因为浏览器没有 DWM；真机圆角由 DWM 画（Win11 约 8px），所以不要把 12px 写进 `--spk-*` 的产品语义里。

### 动效

- 只用三种缓动：`out`（`cubic-bezier(.16,1,.3,1)`，绝大多数入场）、`in-out`（重排/位移）、`spring`（仅按压回弹）。产品内部**禁用弹簧**，站点也不使用。
- 时长四档：120 / 190 / 280 / 460 / 760ms。滚动入场统一 820ms + 最多 90ms 阶梯延迟，超过这个量就开始拖沓。

---

## 3. 页面结构与职责

| 文件 | 职责 | 主要样式表 |
|---|---|---|
| `index.html` | 落地页：工作流、7 类预览器列表、格式矩阵、界面说明、快捷键、架构、开始 | `site.css` |
| `video.html` | 42 秒演示片：`<canvas>` 逐帧渲染，可拖时间轴、切分镜、定格秒数 | `site.css` + `showreel.js` |
| `video.html?t=19` | 任意时刻定格成海报，供无头截图/封面使用 | — |

两个页面共用 `site.js` 的顶栏、主题切换与滚动入场；演示片只额外加载 `showreel.js`。

---

## 4. 十维视觉审查

| 维度 | 结论 | 依据 |
|---|---|---|
| 色彩一致性 | ✅ | 全站颜色只来自 `tokens.css`；产品语境的标注由 `--spk-*` 派生，页面取色与真机逐区比对（灰度差 ≤3），无散落硬编码 |
| 排版层级 | ✅ | 四级：eyebrow(11px/0.18em) → 标题(clamp) → lead(15–17px) → 正文(13–15px)；数字与代码一律等宽 |
| 间距节奏 | ✅ | 栏目 `clamp(72px,11vh,140px)` 垂直留白 + 116px 索引槽；卡片内 8/12/16 三档；产品层严格 10px |
| 组件一致性 | ✅ | 标注里引用的按钮/输入/开关尺寸全部抄自 styled_*.py 的 SIZE_CONFIG，与真机同圆角、同高度 |
| 响应式 | ✅ | 断点 1240/1100/980/860/620；各栏栅格按断点重排；< 900px 时三栏退化为单列 |
| 深色模式 | ✅ | 深浅两套令牌同构；`prefers-color-scheme` 初始化 + 手动切换记忆；浅色下 accent 实底不变，文字/图标强调走 `accent_text`（`#2a7192`），与 ThemeManager 一致 |
| 动效 | ✅ | 入场 820ms 编排、悬停 120ms、重排 280ms；全部可被 `prefers-reduced-motion` 关闭；演示片走确定性 `render(t)` |
| 无障碍 | ⚠️ 基本达标 | 焦点可见（2px accent 内缩环）、`skip-link`、`aria-current`、对话框焦点回退、Esc 关闭。**未做**完整屏幕阅读器走查 |
| 信息密度 | ✅ | 首屏 4 个数字、格式 100+ 分四组、快捷键分五组；没有为了好看而删功能项 |
| 细节打磨 | ✅ | 卡片文件名两行断行与 Qt `WrapAtWordBoundaryOrAnywhere` 一致（`Sopeek.p / ng`、`ACE COL / LECTI…` 与真机同款）；New 布局下选择器底栏与窗口底部的 10px 余量等于面板内边距 |

---

## 5. 改动指引

- **改颜色/字号/间距**：只改 `assets/tokens.css`，再同步 `design-tokens.json`。不要直接改页面里的值。
- **改演示片**：所有绘制都必须在 `showreel.js` 的 `render(t)` 路径内，**禁止** `Math.random` / `Date.now` / `requestAnimationFrame` 参与画面计算（rAF 只负责推进时间轴）。新增分镜记得同步 `video.html` 的 `.reel-chapter[data-at]` 与 `DURATION`。
- **新增页面**：复用 `site.css` 的 `.section` / `.section-head` / `.mono` / `.btn` 骨架，页头页脚直接照抄 `index.html`，保证导航项齐全（介绍 / 演示片）。

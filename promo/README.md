# Sopeek 宣传资料

面向 Sopeek v2.0.0 的静态宣传站点：一个介绍页与一个 42 秒演示片。
全部是纯 HTML / CSS / JS——**无框架、无构建步骤、无第三方 CDN、无追踪**，双击一个静态服务器就能看。

```
promo/
├─ index.html              介绍页（首屏 / 工作流 / 8 类预览器 / 格式 / 界面 / 快捷键 / 架构 / 开始）
├─ video.html              演示片（canvas 逐帧渲染，可拖时间轴 / 切分镜 / 定格）
├─ DESIGN.md               设计说明：美学方向、令牌决策、十维视觉审查
├─ design-tokens.json      设计令牌的机器可读快照（与 assets/tokens.css 同步）
├─ media/                  演示片 MP4、配乐等大文件的落点（默认只放 .gitkeep）
└─ assets/
   ├─ tokens.css           唯一的令牌来源（颜色 / 字体 / 间距 / 圆角 / 动效 / 产品窗口变量）
   ├─ site.css             站点骨架：顶栏、首屏、栏目、机架、格式墙、快捷键、页脚
   ├─ site.js              主题切换、滚动入场、快捷键联动
   ├─ showreel.js          演示片：确定性 render(t) 逐帧绘制
   ├─ icons.svg            56 个内联 symbol 图标（id 全部带 i- 前缀）
   └─ Sopeek.png           应用图标
```

---

## 本地预览

浏览器对 `file://` 下的 `<use href="...svg#id">`、`fetch` 与相对路径处理不一致，**请用静态服务器**：

```bash
# 在仓库根目录
python -m http.server 8611 --bind 127.0.0.1
# 打开 http://127.0.0.1:8611/promo/
```

也可以用 `npx serve promo`、VS Code Live Server 等任意静态服务器替代。

---

## 两个页面各自的看点

### `index.html` — 介绍页

按原始 `README.md` 的功能清单逐项落地，栏目与内容一一对应：

| 栏目 | 覆盖的 README 内容 |
|---|---|
| 01 工作流 | 选择器 / 储存池 / 预览器三件事；智能浏览、框选多选、导航收藏、筛选排序 8 模式、隐藏项两级、缩略图管理、储存池的增删改与导入导出、自动备份 |
| 02 预览器 | 七类预览器逐条说明（图像 / 音频 / PDF / 代码 / 压缩包 / 字体 / 文件夹）+ 图像（50–500%、翻转旋转、取色、GIF）、音视频（libmpv、倍速、音轨字幕、流体背景）、PDF（缩放、缩略图索引、文本选择）、Office（三级降级）、文本代码（Markdown、50+ 语法、源码/渲染切换）、压缩包（不解压浏览、全包搜索、按需密码）、字体（可变字体）、文件夹（自动监听） |
| 03 格式 | 图像 / 视频音频 / 文档文本 / 压缩包字体 四组，覆盖 README 支持格式表里的全部扩展名 |
| 04 界面 | 经典与 New 两种布局、分隔条拖拽与双击重置、桌面浮窗、三栏区域说明 |
| 05 快捷键 | 全局、选择器、播放、图像/PDF、文本/压缩包 五组，悬停高亮对应按键 |
| 06 架构 | Rust `spk_core` 20 个导出、8 类预览器、5 个命名线程池 + rayon、三档性能与独显启动器 |
| 07 开始 | 安装包、源码运行、`--open-path`、数据目录、许可证 |

深浅色可在顶栏切换（记忆在 `localStorage: sopeek.promo.theme`）。

### `video.html` — 演示片

42 秒 / 1280×720 / 30fps 的分镜：片头 → 三栏窗口 → 卡片飞入储存池 → 预览器切换 → 格式墙 → 原生加速 → 收尾。
画面由 `showreel.js` 的**纯函数** `render(t)` 绘制：给同一个 `t` 永远出同一帧，不含 `Math.random` / `Date.now` / CSS 动画（rAF 只推进时间轴），因此可以直接抽帧导出视频。

- 播放 / 暂停：按钮、空格键或点击画布
- 拖动时间轴、点右侧分镜跳转、`0.5× / 1× / 2×` 变速
- `video.html?t=19` 会在 19 秒处定格，方便做封面或截图核对

---

## 把演示片导出成 MP4

`showreel.js` 暴露了全局对象：

```js
window.SopeekReel = { duration: 42, render(t), seek(t), play(), pause(), get time() }
```

画布固定 1280×720，所以导出的帧天然就是 720p。推荐**逐帧截图 + ffmpeg 合成**（帧数精确、不受实时编码码率影响）：

```js
// capture.mjs —— 需要 puppeteer：npm i puppeteer
import fs from 'node:fs';
import puppeteer from 'puppeteer';

const FPS = 30;
const browser = await puppeteer.launch();
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
await page.goto('http://127.0.0.1:8611/promo/video.html');
await page.waitForFunction(() => window.SopeekReel);
await page.evaluate(() => window.SopeekReel.pause());

fs.mkdirSync('frames', { recursive: true });
const total = Math.round(42 * FPS);
for (let i = 0; i < total; i++) {
  const png = await page.evaluate((t) => {
    window.SopeekReel.render(t);
    return document.getElementById('reelCanvas').toDataURL('image/png');
  }, i / FPS);
  fs.writeFileSync(`frames/f_${String(i).padStart(5, '0')}.png`, Buffer.from(png.split(',')[1], 'base64'));
}
await browser.close();
```

```bash
node capture.mjs
ffmpeg -framerate 30 -i frames/f_%05d.png -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart sopeek-reel.mp4
```

需要 BGM 或口播时，在上面的 `ffmpeg` 里加 `-i audio.m4a -c:a aac -b:a 160k -shortest` 即可（画面不含音轨，音源请自行确认授权）。

导出的成片建议放在 `media/`（例如 `media/sopeek-reel.mp4`），该目录默认只有 `.gitkeep`，避免把几十兆视频塞进仓库；如果要长期托管，请用 Releases 或对象存储。

---

## 部署

整目录是纯静态资源，直接上传即可（GitHub Pages、Cloudflare Pages、Nginx、对象存储都行）。若要放在站点子路径下，页面里的相对路径（`assets/...`、`video.html`）本身就是相对的，无需改配置；只有 `index.html` 里指向 GitHub 的外链是绝对地址。

`DESIGN.md` 与 `design-tokens.json` 也能直接被浏览器打开，页脚已链接，方便评审时对照。

---

## 内容口径与事实来源

- 产品事实来自仓库根 `README.md`（744 行）与 `SPKVERSION`（`v2.0.0` / `2026-11-22`），未使用任何虚构指标。
- 界面几何取自 `src/sopeek/ui/` 的真实实现与离屏实测（48px 标题栏、8px 面板圆角、面板间隙 10px、卡片间隙 4px、50% 面板描边、72×102 卡片、44px 卡片图标、28px 底栏按钮、17pt≈22.7px 信息面板标题、预览画布 9:16 + 48px 顶栏等）。
- 颜色取自 `src/sopeek/ui/theme/colors.json`、`src/sopeek/ui/theme/theme_manager.py` 与 `settings_manager_v2.py` 的默认配色；页面取色与真机逐区比对（深/浅主题灰度差均 ≤3）。
- 站点只保留文案与令牌，不再包含任何界面截图或手写界面复刻。

## 已知限制

- 站点不连接任何后端，也不读取真实文件；演示片里的哈希、进度条等是演示数据。
- 桌面浮窗（常驻托盘圆形入口、贴边吸附）只在文案与演示片中呈现，未做可交互复刻。
- 演示片无音轨；导出时如需 BGM 请自行提供。

## 许可

页面内容随 Sopeek 项目一起以 **AGPL-3.0** 发布。Sopeek 名称与应用图标归项目所有；引用的第三方名称（Windows、Rust、Qt 等）仅作事实描述。

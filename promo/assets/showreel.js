/* Sopeek promo — 42 秒演示片
   纯 Canvas 逐帧绘制：window.SopeekReel.render(t) 是纯函数，
   同一个 t 永远得到同一帧（无 Math.random、无 Date.now、无 CSS 动画）。
   播放器只负责推进时钟。 */
(function () {
  'use strict';

  var canvas = document.getElementById('reelCanvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var W = canvas.width;
  var H = canvas.height;
  var DURATION = 42;

  /* ---------- 常量 ---------- */
  var C = {
    ink: '#eef4f2',
    soft: 'rgba(238,244,242,.66)',
    mute: 'rgba(222,236,232,.42)',
    faint: 'rgba(222,236,232,.20)',
    accent: '#3a9dcb',
    accentSoft: 'rgba(58,157,203,.22)',
    amber: '#e9a94b',
    teal: '#102523',
    panel: 'rgba(255,255,255,.05)',
    border: 'rgba(136,136,136,.5)',
    bg: '#070b0b'
  };
  var F = {
    display: '"Bahnschrift","Segoe UI Variable Display","Microsoft YaHei UI",sans-serif',
    body: '"Segoe UI Variable Text","Microsoft YaHei UI",sans-serif',
    mono: '"Cascadia Mono",Consolas,"Microsoft YaHei UI",monospace'
  };

  /* ---------- 数学 ---------- */
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function lerp(a, b, p) { return a + (b - a) * p; }
  function easeOut(p) { return 1 - Math.pow(1 - clamp(p, 0, 1), 3); }
  function easeInOut(p) { p = clamp(p, 0, 1); return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; }
  function easeOutBack(p) { p = clamp(p, 0, 1); var c = 1.70158; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); }
  function seg(t, a, b) { return clamp((t - a) / (b - a), 0, 1); }
  /* 入场 0→1、出场 1→0 的包络 */
  function env(t, a, b, fadeIn, fadeOut) {
    fadeIn = fadeIn || 0.5;
    fadeOut = fadeOut || 0.5;
    var i = clamp((t - a) / fadeIn, 0, 1);
    var o = clamp((b - t) / fadeOut, 0, 1);
    return Math.min(easeOut(i), easeOut(o));
  }

  /* 固定种子伪随机：初始化时一次性生成，渲染过程不再调用 */
  var seed = 20261126;
  var noise = [];
  (function () {
    var s = seed >>> 0;
    for (var i = 0; i < 256; i++) {
      s = (s + 0x6D2B79F5) >>> 0;
      var x = Math.imul(s ^ (s >>> 15), 1 | s);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      noise.push(((x ^ (x >>> 14)) >>> 0) / 4294967296);
    }
  })();
  function rnd(i) { return noise[i % noise.length]; }

  /* ---------- 绘制原语 ---------- */
  function rr(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function fillRR(x, y, w, h, r, fill) { rr(x, y, w, h, r); ctx.fillStyle = fill; ctx.fill(); }
  function strokeRR(x, y, w, h, r, stroke, lw) {
    rr(x, y, w, h, r); ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1; ctx.stroke();
  }
  function text(str, x, y, opts) {
    opts = opts || {};
    ctx.save();
    ctx.font = (opts.weight || 400) + ' ' + (opts.size || 16) + 'px ' + (opts.font || F.body);
    ctx.fillStyle = opts.color || C.ink;
    ctx.textAlign = opts.align || 'left';
    ctx.textBaseline = opts.baseline || 'alphabetic';
    if (opts.spacing && 'letterSpacing' in ctx) ctx.letterSpacing = opts.spacing + 'px';
    if (opts.alpha !== undefined) ctx.globalAlpha = opts.alpha;
    ctx.fillText(str, x, y);
    ctx.restore();
  }

  var logo = new Image();
  var logoReady = false;
  logo.onload = function () { logoReady = true; draw(currentT); };
  logo.src = 'assets/Sopeek.png';

  /* ---------- 背景 ---------- */
  function backdrop(t) {
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    var drift = Math.sin(t * 0.22) * 60;
    var g = ctx.createRadialGradient(W * 0.28 + drift, H * 0.18, 0, W * 0.28 + drift, H * 0.18, W * 0.9);
    g.addColorStop(0, 'rgba(58,157,203,.16)');
    g.addColorStop(0.45, 'rgba(16,37,35,.5)');
    g.addColorStop(1, 'rgba(7,11,11,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    ctx.strokeStyle = 'rgba(160,205,194,.055)';
    ctx.lineWidth = 1;
    var step = 80;
    for (var x = (t * 6) % step; x < W; x += step) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (var y = 0; y < H; y += step) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    var v = ctx.createRadialGradient(W / 2, H / 2, H * 0.32, W / 2, H / 2, H * 0.95);
    v.addColorStop(0, 'rgba(0,0,0,0)');
    v.addColorStop(1, 'rgba(0,0,0,.62)');
    ctx.fillStyle = v;
    ctx.fillRect(0, 0, W, H);
  }

  /* ---------- 场景 1：片头 0 → 4.6 ---------- */
  function sceneIntro(t) {
    var p = env(t, 0, 4.6, 0.8, 0.7);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;

    var cx = W / 2;
    var cy = H / 2 - 26;
    var pop = easeOutBack(seg(t, 0.15, 1.25));

    /* 光环 */
    for (var i = 0; i < 3; i++) {
      var rp = ((t * 0.35 + i / 3) % 1);
      ctx.beginPath();
      ctx.arc(cx, cy - 14, 74 + rp * 150, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(58,157,203,' + (0.30 * (1 - rp)).toFixed(3) + ')';
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }

    /* 徽标 */
    var size = 116 * pop;
    ctx.save();
    ctx.shadowColor = 'rgba(58,157,203,.55)';
    ctx.shadowBlur = 46;
    if (logoReady) {
      ctx.drawImage(logo, cx - size / 2, cy - size / 2 - 14, size, size);
    } else {
      fillRR(cx - size / 2, cy - size / 2 - 14, size, size, size * 0.22, C.accent);
    }
    ctx.restore();

    /* 字标 */
    var lp = easeOut(seg(t, 0.55, 1.5));
    text('SOPEEK', cx, cy + 96, {
      font: F.display, size: 62, weight: 600, align: 'center',
      spacing: lerp(30, 12, lp), color: C.ink, alpha: lp
    });
    var sp = easeOut(seg(t, 1.0, 1.9));
    text('文件预览与管理，一次看完', cx, cy + 142, {
      font: F.body, size: 20, align: 'center', color: C.soft, alpha: sp, spacing: 1.5
    });

    var bp = easeOut(seg(t, 1.4, 2.3));
    if (bp > 0) {
      var bw = 216;
      ctx.save();
      ctx.globalAlpha = p * bp;
      strokeRR(cx - bw / 2, cy + 178, bw, 40, 20, 'rgba(160,205,194,.28)');
      text('WINDOWS 10 / 11 · X64', cx, cy + 204, {
        font: F.mono, size: 11, align: 'center', color: C.mute, spacing: 2.2
      });
      ctx.restore();
    }
    ctx.restore();
  }

  /* ---------- 窗口骨架（多场景复用） ---------- */
  function windowFrame(t, x, y, w, h, build, opts) {
    opts = opts || {};
    /* build: 0..1 建造进度 */
    var barH = 44;
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.55)';
    ctx.shadowBlur = 60;
    ctx.shadowOffsetY = 26;
    fillRR(x, y, w, h, 12, '#0c1413');
    ctx.restore();

    /* Mica 底 */
    var mg = ctx.createLinearGradient(x, y, x + w, y + h);
    mg.addColorStop(0, 'rgba(16,37,35,.96)');
    mg.addColorStop(0.55, 'rgba(12,26,26,.96)');
    mg.addColorStop(1, 'rgba(9,19,20,.98)');
    fillRR(x + 1, y + 1, w - 2, h - 2, 11, mg);
    strokeRR(x + 0.5, y + 0.5, w - 1, h - 1, 12, 'rgba(136,136,136,.28)');

    ctx.save();
    rr(x, y, w, h, 12);
    ctx.clip();

    /* 标题栏 */
    var tb = easeOut(seg(build, 0, 0.35));
    if (tb > 0) {
      ctx.globalAlpha = tb;
      if (logoReady) ctx.drawImage(logo, x + 16, y + 12, 20, 20);
      text('Sopeek', x + 44, y + barH / 2 + 5, { size: 13, weight: 600, color: C.ink });
      var bx = x + w - 16 - 5 * 30;
      for (var i = 0; i < 5; i++) {
        fillRR(bx + i * 30, y + 9, 26, 26, 4, 'rgba(255,255,255,.04)');
        ctx.strokeStyle = 'rgba(238,244,242,.5)';
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        var cx0 = bx + i * 30 + 13;
        var cy0 = y + 22;
        if (i === 0) { ctx.arc(cx0, cy0, 4.4, 0, Math.PI * 2); ctx.stroke(); }
        else if (i === 1) { ctx.arc(cx0, cy0, 4.4, -0.6, 2.2); ctx.stroke(); }
        else if (i === 2) { ctx.moveTo(cx0 - 4, cy0); ctx.lineTo(cx0 + 4, cy0); ctx.stroke(); }
        else if (i === 3) { ctx.strokeRect(cx0 - 4, cy0 - 4, 8, 8); }
        else { ctx.moveTo(cx0 - 4, cy0 - 4); ctx.lineTo(cx0 + 4, cy0 + 4); ctx.moveTo(cx0 + 4, cy0 - 4); ctx.lineTo(cx0 - 4, cy0 + 4); ctx.stroke(); }
      }
      ctx.globalAlpha = 1;
    }

    /* 三栏 */
    var bodyY = y + barH + 8;
    var bodyH = h - barH - 18;
    var gap = 10;
    var padX = 10;
    var colW = (w - padX * 2 - gap * 2) / 3;
    var cols = [x + padX, x + padX + colW + gap, x + padX + (colW + gap) * 2];
    var st = [
      easeOut(seg(build, 0.18, 0.55)),
      easeOut(seg(build, 0.32, 0.7)),
      easeOut(seg(build, 0.46, 0.85))
    ];

    for (var c = 0; c < 3; c++) {
      if (st[c] <= 0) continue;
      ctx.save();
      var off = (1 - st[c]) * 26;
      ctx.globalAlpha = st[c];
      ctx.translate(0, off);
      drawColumn(cols[c], bodyY, colW, bodyH, c, st[c], t, opts);
      ctx.restore();
    }
    ctx.restore();
  }

  function panel(x, y, w, h, r) {
    fillRR(x, y, w, h, r || 8, C.panel);
    strokeRR(x + 0.5, y + 0.5, w - 1, h - 1, r || 8, 'rgba(136,136,136,.42)');
  }

  /* 三栏内部：0=选择器 1=储存池 2=预览+信息 */
  function drawColumn(x, y, w, h, kind, p, t, opts) {
    opts = opts || {};
    if (kind === 0) {
      var headH = 78;
      panel(x, y, w, headH);
      fillRR(x + 9, y + 8, w - 18, 26, 6, 'rgba(0,0,0,.32)');
      strokeRR(x + 9.5, y + 8.5, w - 19, 25, 6, 'rgba(136,136,136,.32)');
      text('D:\\素材库', x + 18, y + 25, { size: 10.5, color: C.soft });
      for (var i = 0; i < 6; i++) {
        fillRR(x + 10 + i * 24, y + 44, 20, 20, 4, 'rgba(255,255,255,.05)');
      }
      /* 驱动器环 */
      var ringY = y + headH + 10;
      panel(x, ringY, w, 74);
      for (var d = 0; d < 2; d++) {
        var cx = x + 32 + d * 54;
        var cy = ringY + 36;
        ctx.beginPath(); ctx.arc(cx, cy, 20, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(136,136,136,.3)'; ctx.lineWidth = 3.4; ctx.stroke();
        ctx.beginPath();
        ctx.arc(cx, cy, 20, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (d === 0 ? 0.41 : 0.28));
        ctx.strokeStyle = C.accent; ctx.lineWidth = 3.4; ctx.lineCap = 'round'; ctx.stroke();
        text(d === 0 ? '41%' : '28%', cx, cy + 3.4, { size: 9.5, align: 'center', font: F.mono, color: C.ink });
        text(d === 0 ? 'C:' : 'D:', cx, ringY + 66, { size: 9.5, align: 'center', font: F.mono, color: C.mute });
      }
      /* 文件网格 */
      var gy = ringY + 84;
      var gh = h - (gy - y) - 56;
      panel(x, gy, w, gh);
      var cw = 46, chh = 46, gx = 12, ggap = 8;
      var perRow = Math.floor((w - 20 + ggap) / (cw + ggap));
      var cols2 = [C.accent, '#7fb7d9', '#8b5cf6', '#3b82f6', '#e9a94b', '#22b8a6', '#ef6d7d', '#9fd3c7', '#c9c3f0'];
      for (var k = 0; k < 14; k++) {
        var r0 = Math.floor(k / perRow), c0 = k % perRow;
        var bx2 = x + 10 + c0 * (cw + ggap);
        var by2 = gy + 10 + r0 * (chh + ggap);
        if (by2 + chh > gy + gh - 8) break;
        fillRR(bx2, by2, cw, chh, 6, 'rgba(26,26,26,.85)');
        strokeRR(bx2 + 0.5, by2 + 0.5, cw - 1, chh - 1, 6, 'rgba(136,136,136,.34)');
        fillRR(bx2 + 12, by2 + 9, 22, 20, 4, cols2[k % cols2.length]);
        fillRR(bx2 + 9, by2 + 34, cw - 18, 3, 1.5, 'rgba(238,244,242,.55)');
        fillRR(bx2 + 9, by2 + 40, cw - 26, 3, 1.5, 'rgba(238,244,242,.30)');
      }
      /* 底栏 */
      var barY = y + h - 44;
      panel(x, barY, w, 44);
      text('12 个条目', x + 14, barY + 26, { size: 10, color: C.mute });
      fillRR(x + w - 106, barY + 8, 96, 28, 5, C.accent);
      text('生成缩略图', x + w - 58, barY + 26, { size: 10.5, align: 'center', color: '#ffffff', weight: 400 });
    } else if (kind === 1) {
      var ph = h - 54;
      panel(x, y, w, ph);
      var rows = (opts.poolRows == null) ? 3 : opts.poolRows;
      for (var q = 0; q < rows; q++) {
        var iy = y + 12 + q * 62;
        fillRR(x + 12, iy, w - 24, 54, 6, 'rgba(26,26,26,.8)');
        strokeRR(x + 12.5, iy + 0.5, w - 25, 53, 6, 'rgba(136,136,136,.3)');
        fillRR(x + 20, iy + 9, 22, 24, 4, ['#7fb7d9', '#ef6d7d', '#e9a94b'][q]);
        fillRR(x + 50, iy + 14, w - 80, 4, 2, 'rgba(238,244,242,.5)');
        fillRR(x + 50, iy + 23, w - 110, 3, 1.5, 'rgba(238,244,242,.24)');
        text(['Sopeek.png', '产品介绍.mp4', 'Archive.zip'][q], x + 50, iy + 43, { size: 9.5, color: C.mute });
      }
      var pbar = y + h - 44;
      panel(x, pbar, w, 44);
      var poolN = (opts.poolCount == null) ? 3 : opts.poolCount;
      text(poolN + '个条目', x + 14, pbar + 26, { size: 10, color: C.mute });
      fillRR(x + w - 74, pbar + 8, 62, 28, 5, C.accent);
      text('导出文件', x + w - 43, pbar + 26, { size: 10.5, align: 'center', color: '#ffffff', weight: 400 });
    } else {
      var cw2 = w;
      var ch2 = h * 0.56;
      panel(x, y, cw2, ch2);
      var ih = h - ch2 - 10;
      panel(x, y + ch2 + 10, cw2, ih - 44);
      panel(x, y + h - 44, cw2, 44);
      /* 统一操作行：4 个等宽按钮 */
      var bw2 = (cw2 - 20 - 18) / 4;
      for (var a = 0; a < 4; a++) {
        fillRR(x + 10 + a * (bw2 + 6), y + h - 35, bw2, 26, 5,
          a === 2 ? C.accent : 'rgba(136,136,136,.18)');
      }
      drawPreviewCanvas(x + 1, y + 1, cw2 - 2, ch2 - 2, t, true);
      text('Sopeek.png', x + 14, y + ch2 + 32, { size: 15, weight: 600, color: C.ink });
      text('D:\\素材库\\Sopeek.png', x + 14, y + ch2 + 52, { size: 9.5, color: C.mute });
      var rows = ['类别  PNG 图像', '大小  31.0 KB (31,708 字节)', '修改  2026-11-24 18:22', '尺寸  256 × 256'];
      for (var r = 0; r < rows.length; r++) {
        text(rows[r], x + 14, y + ch2 + 76 + r * 19, { size: 9.5, color: C.mute, font: F.mono });
      }
    }
  }

  /* ---------- 预览画布内容（可在场景 4 单独放大） ---------- */
  function drawPreviewCanvas(x, y, w, h, t, mini) {
    ctx.save();
    rr(x, y, w, h, mini ? 7 : 10);
    ctx.clip();
    fillRR(x, y, w, h, mini ? 7 : 10, '#0a1110');

    /* 场景 4 有独立的时间线，这里按 mode 混合 */
    var modes = ['image', 'video', 'pdf', 'code'];
    var local = t - 16.4;
    var idx = 0, mix = 0;
    if (!mini || local > 0) {
      var slot = local / 1.7;
      idx = clamp(Math.floor(slot), 0, 3);
      mix = easeInOut(clamp((slot - Math.floor(slot)) / 0.55, 0, 1));
    }
    var mode = modes[idx];

    if (mode === 'image') {
      var pw = w * 0.62, phh = h * 0.72;
      var px = x + (w - pw) / 2, py = y + (h - phh) / 2;
      var grad = ctx.createLinearGradient(px, py, px + pw, py + phh);
      grad.addColorStop(0, '#1d3d55');
      grad.addColorStop(0.55, '#245a63');
      grad.addColorStop(1, '#123028');
      fillRR(px, py, pw, phh, 8, grad);
      ctx.beginPath();
      ctx.arc(px + pw * 0.46, py + phh * 0.5, Math.min(pw, phh) * 0.24, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(94,214,190,.5)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px + pw * 0.58, py + phh * 0.5, Math.min(pw, phh) * 0.24, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(120,170,220,.45)';
      ctx.fill();
      text('256 × 256 · PNG', x + w - 14, y + h - 12, { size: 9, align: 'right', font: F.mono, color: C.mute });
    } else if (mode === 'video') {
      var vw = w * 0.78, vh = vw * 9 / 16;
      var vx = x + (w - vw) / 2, vy = y + (h - vh) / 2;
      fillRR(vx, vy, vw, vh, 8, '#0d1b1e');
      strokeRR(vx + 0.5, vy + 0.5, vw - 1, vh - 1, 8, 'rgba(136,136,136,.3)');
      ctx.beginPath();
      ctx.arc(vx + vw / 2, vy + vh / 2, 26, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,.12)'; ctx.fill();
      ctx.beginPath();
      ctx.moveTo(vx + vw / 2 - 6, vy + vh / 2 - 9);
      ctx.lineTo(vx + vw / 2 + 10, vy + vh / 2);
      ctx.lineTo(vx + vw / 2 - 6, vy + vh / 2 + 9);
      ctx.closePath();
      ctx.fillStyle = C.ink; ctx.fill();
      fillRR(vx, vy + vh - 20, vw, 20, 0, 'rgba(0,0,0,.55)');
      fillRR(vx + 8, vy + vh - 11, vw * 0.42, 2.5, 1.2, C.accent);
      text('1.5×  ·  AAC  ·  02:14', vx + vw - 10, vy + vh - 6, { size: 8.5, align: 'right', font: F.mono, color: C.soft });
    } else if (mode === 'pdf') {
      var dw = w * 0.56, dh = h * 0.84;
      var dx = x + (w - dw) / 2, dy = y + (h - dh) / 2;
      fillRR(dx, dy, dw, dh, 4, '#f3f2ee');
      for (var l = 0; l < 12; l++) {
        var lw = l === 0 ? dw * 0.5 : dw * (0.9 - (l % 3) * 0.14);
        fillRR(dx + 16, dy + 22 + l * 15, lw, l === 0 ? 7 : 3, 1.5, l === 0 ? 'rgba(20,30,28,.72)' : 'rgba(20,30,28,.24)');
      }
      text('PDF · 1 / 24', x + w - 14, y + h - 12, { size: 9, align: 'right', font: F.mono, color: C.mute });
    } else {
      var codeLines = [
        ['def', ' scan ', 'path', ':'],
        ['    ', 'entries', ' = spk_scan(', 'path', ')'],
        ['    ', 'return', ' sorted(', 'entries', ')'],
        ['', ''],
        ['class', ' Previewer', ':'],
        ['    ', 'def', ' render(', 'self', ', file', '):'],
        ['        ', 'if', ' file.kind == ', '"image"', ':']
      ];
      var cxs = x + w * 0.10, cys = y + h * 0.16;
      for (var cl = 0; cl < codeLines.length; cl++) {
        var segs = codeLines[cl];
        var ox = cxs;
        for (var sg = 0; sg < segs.length; sg++) {
          var s = segs[sg];
          if (!s) continue;
          var col = C.soft;
          if (sg === 0 && /def|class|return|if/.test(s)) col = C.accent;
          else if (/^"/.test(s)) col = '#8fd6a8';
          else if (sg === 0) col = 'rgba(238,244,242,.3)';
          ctx.font = '13px ' + F.mono;
          ctx.fillStyle = col;
          ctx.fillText(s, ox, cys + cl * 22);
          ox += ctx.measureText(s).width;
        }
      }
      text('main.py', x + w - 14, y + h - 12, { size: 9, align: 'right', font: F.mono, color: C.mute });
    }
    ctx.restore();
    if (!mini) {
      ctx.save();
      var fade = Math.min(1, mix * 1.4);
      ctx.globalAlpha = 1 - fade;
      ctx.restore();
    }
  }

  /* ---------- 场景 2：三栏立起来 4.6 → 10.2 ---------- */
  function sceneWindow(t) {
    var p = env(t, 4.4, 10.5, 0.7, 0.55);
    if (p <= 0) return;
    var build = easeInOut(seg(t, 4.7, 8.6));
    var w = 1000, h = 604;
    var x = (W - w) / 2;
    var y = 58 + (1 - p) * 22;
    ctx.save();
    ctx.globalAlpha = p;
    windowFrame(t, x, y, w, h, build);
    ctx.restore();

    var cap = easeOut(seg(t, 7.2, 8.4));
    if (cap > 0) {
      text('选择器  ·  储存池  ·  预览器 / 信息面板', W / 2, y + h + 46, {
        align: 'center', size: 14, color: C.mute, alpha: cap, font: F.mono, spacing: 1.6
      });
    }
    var cap2 = easeOut(seg(t, 8.0, 9.2));
    if (cap2 > 0) {
      text('三栏都是卡片，间距 10px，圆角 8px', W / 2, y + h + 74, {
        align: 'center', size: 12, color: 'rgba(222,236,232,.3)', alpha: cap2
      });
    }
  }

  /* ---------- 场景 3：卡片飞进储存池 10.2 → 16.4 ---------- */
  function sceneFlow(t) {
    var p = env(t, 10.2, 16.5, 0.6, 0.5);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;

    var w = 900, h = 520;
    var x = (W - w) / 2, y = 92;

    /* 与三栏几何保持一致，卡片落到池里对应的行上 */
    var colW = (w - 20 - 20) / 3;
    var poolX = x + 10 + colW + 10;
    var bodyY = y + 44 + 8;
    var rowCy = function (i) { return bodyY + 12 + 27 + i * 62; };
    var rowCx = poolX + 12 + (colW - 24) / 2;

    var flies = [
      { a: 0.15, from: [x + 130, y + 250] },
      { a: 0.42, from: [x + 190, y + 300] },
      { a: 0.69, from: [x + 130, y + 360] }
    ];
    var ks = flies.map(function (f) { return easeInOut(seg(t, 11.0 + f.a, 12.4 + f.a)); });
    var landed = ks.filter(function (k) { return k > 0.9; }).length;
    var n = Math.round(lerp(0, 3, easeOut(seg(t, 11.4, 13.4))));

    windowFrame(t, x, y, w, h, 1, { poolRows: landed, poolCount: n });

    for (var i = 0; i < flies.length; i++) {
      var f = flies[i];
      var k = ks[i];
      if (k <= 0) continue;
      var to = [rowCx, rowCy(i)];
      var cx1 = (f.from[0] + to[0]) / 2, cy1 = f.from[1] - 90;
      var bx = (1 - k) * (1 - k) * f.from[0] + 2 * (1 - k) * k * cx1 + k * k * to[0];
      var by = (1 - k) * (1 - k) * f.from[1] + 2 * (1 - k) * k * cy1 + k * k * to[1];
      var sc = lerp(1, 0.86, k);
      var alpha = k > 0.9 ? (1 - (k - 0.9) / 0.1) : 1;
      ctx.save();
      ctx.globalAlpha = p * clamp(alpha, 0, 1);
      ctx.translate(bx, by);
      ctx.scale(sc, sc);
      ctx.shadowColor = 'rgba(58,157,203,.5)';
      ctx.shadowBlur = 26 * k;
      fillRR(-24, -27, 48, 54, 6, '#1a1a1a');
      strokeRR(-24, -27, 48, 54, 6, k > 0.15 ? C.accent : 'rgba(136,136,136,.32)', 1.4);
      fillRR(-14, -18, 26, 22, 4, ['#7fb7d9', '#ef6d7d', '#e9a94b'][i]);
      ctx.restore();
    }

    /* 体积 + 文案 */
    var vol = lerp(0, 378.4, easeOut(seg(t, 11.4, 13.6)));
    text(vol.toFixed(1) + ' MB', poolX + 74, y + h - 28, { size: 9.5, color: C.mute, font: F.mono });

    var c1 = easeOut(seg(t, 12.6, 13.8));
    text('右键 → 加入储存池', x - 46, y - 34, { size: 13, color: C.soft, alpha: c1, font: F.mono });
    var c2 = easeOut(seg(t, 13.6, 14.8));
    text('跨目录累积，一次导出', x + w * 0.42, y + h + 52, { size: 13, color: C.soft, alpha: c2 });
    var c3 = easeOut(seg(t, 14.4, 15.6));
    text('Tab 键入池 / 移出', x + w * 0.42 + 190, y + h + 52, { size: 13, color: C.mute, alpha: c3 });
    ctx.restore();
  }

  /* ---------- 场景 4：预览器切换 16.4 → 23.4 ---------- */
  function scenePreview(t) {
    var p = env(t, 16.3, 23.6, 0.6, 0.6);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;

    var w = 860, h = 452;
    var x = (W - w) / 2, y = 132;
    var names = ['图像预览器', '视频音频预览器', 'PDF 预览器', '文本代码预览器'];
    var local = t - 16.4;
    var slot = local / 1.7;
    var idx = clamp(Math.floor(slot), 0, 3);
    panel(x, y, w, h);

    /* 预览器顶栏：文件名 + 统一操作按钮 */
    ctx.save();
    rr(x, y, w, 38, 8);
    ctx.clip();
    fillRR(x, y, w, 38, 0, 'rgba(255,255,255,.028)');
    ctx.restore();
    ctx.strokeStyle = 'rgba(136,136,136,.30)';
    ctx.beginPath();
    ctx.moveTo(x + 1, y + 38);
    ctx.lineTo(x + w - 1, y + 38);
    ctx.stroke();
    text(names[idx], x + 16, y + 24, { size: 11.5, color: C.soft });
    for (var ib = 0; ib < 4; ib++) {
      fillRR(x + w - 16 - (4 - ib) * 26 + 4, y + 9, 20, 20, 4, 'rgba(255,255,255,.045)');
      ctx.strokeStyle = 'rgba(238,244,242,.42)';
      ctx.lineWidth = 1.1;
      ctx.strokeRect(x + w - 16 - (4 - ib) * 26 + 10, y + 15, 8, 8);
    }

    ctx.save();
    rr(x + 1, y + 39, w - 2, h - 40, 0);
    ctx.clip();
    drawPreviewCanvas(x + 1, y + 39, w - 2, h - 40, t, false);
    ctx.restore();

    var namesX = x;
    var labels = [
      ['缩放 50%–500%', '翻转 / 旋转 / 取色器 / GIF 播放'],
      ['libmpv 直连', '倍速 / 音轨字幕 / 全屏浮动栏'],
      ['原生渲染 + 选区', '缩略图索引抽屉 / 页码跳转'],
      ['50+ TextMate 语法', '源码与渲染切换 / 站内搜索']
    ];
    var lp = easeOut(seg(t, 17.0, 17.8));
    text(names[idx], namesX, y - 54, { size: 26, weight: 600, color: C.ink, alpha: lp, font: F.display });
    text(labels[idx][0] + '　·　' + labels[idx][1], namesX, y - 24, { size: 12, color: C.mute, alpha: lp });

    /* 进度条：4 段 */
    for (var d = 0; d < 4; d++) {
      var dw = (w - 24) / 4;
      var dx = x + d * (dw + 8);
      fillRR(dx, y + h + 22, dw, 3, 1.5, 'rgba(136,136,136,.22)');
      if (d < idx) fillRR(dx, y + h + 22, dw, 3, 1.5, 'rgba(58,157,203,.55)');
      if (d === idx) fillRR(dx, y + h + 22, dw * (0.3 + 0.7 * clamp((slot - idx) / 1, 0, 1)), 3, 1.5, C.accent);
    }
    ctx.restore();
  }

  /* ---------- 场景 5：格式墙 23.4 → 29.2 ---------- */
  var FORMATS = [
    'JPG', 'PNG', 'GIF', 'WEBP', 'AVIF', 'HEIC', 'PSD', 'RAW', 'CR2', 'NEF', 'ARW', 'DNG',
    'MP4', 'MOV', 'MKV', 'AVI', 'WEBM', 'M2TS', 'MP3', 'FLAC', 'WAV', 'APE', 'OPUS',
    'PDF', 'DOCX', 'XLSX', 'PPTX', 'MD', 'RST', 'PY', 'JS', 'TS', 'GO', 'RS',
    'ZIP', 'RAR', '7Z', 'TAR', 'GZ', 'ISO', 'TTF', 'OTF', 'WOFF2', 'EOT'
  ];
  function sceneFormats(t) {
    var p = env(t, 23.3, 29.4, 0.6, 0.6);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    var cols = 9;
    var colW = W / cols;
    for (var c = 0; c < cols; c++) {
      var speed = 26 + (c % 4) * 9;
      var dir = c % 2 === 0 ? 1 : -1;
      var offset = (t * speed * dir) % 74;
      for (var r = -1; r < 11; r++) {
        var yy = r * 74 + offset;
        var idx = (c * 5 + r + 40) % FORMATS.length;
        var alpha = 0.18 + 0.62 * (0.5 + 0.5 * Math.sin((yy / H) * Math.PI));
        text(FORMATS[(idx + FORMATS.length) % FORMATS.length], c * colW + colW / 2, yy, {
          size: 26, align: 'center', font: F.display, weight: 600,
          color: 'rgba(238,244,242,' + alpha.toFixed(2) + ')'
        });
      }
    }
    var g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, 'rgba(7,11,11,.94)');
    g.addColorStop(0.34, 'rgba(7,11,11,0)');
    g.addColorStop(0.68, 'rgba(7,11,11,0)');
    g.addColorStop(1, 'rgba(7,11,11,.94)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    /* 中心暗场，保证大字压得住格式墙 */
    var halo = ctx.createRadialGradient(W / 2, H / 2 + 10, 40, W / 2, H / 2 + 10, 430);
    halo.addColorStop(0, 'rgba(7,11,11,.94)');
    halo.addColorStop(0.55, 'rgba(7,11,11,.82)');
    halo.addColorStop(1, 'rgba(7,11,11,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, W, H);

    var cp = easeOut(seg(t, 23.8, 25.0));
    text('100+', W / 2, H / 2 + 4, { align: 'center', size: 132, weight: 600, font: F.display, color: C.ink, alpha: cp });
    text('种扩展名，8 类预览器', W / 2, H / 2 + 58, { align: 'center', size: 18, color: C.soft, alpha: cp, spacing: 1 });
    ctx.restore();
  }

  /* ---------- 场景 6：原生加速 29.2 → 35.4 ---------- */
  function scenePerf(t) {
    var p = env(t, 29.1, 35.6, 0.6, 0.6);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;

    var title = easeOut(seg(t, 29.4, 30.4));
    text('重活交给 Rust', W / 2, 190, { align: 'center', size: 44, weight: 600, font: F.display, color: C.ink, alpha: title });

    var sub = easeOut(seg(t, 29.9, 30.9));
    text('spk_core.dll · 扫描 / 排序 / 高亮 / 哈希 / 编码探测 / EXIF / 7z 列表', W / 2, 228, {
      align: 'center', size: 13, color: C.mute, alpha: sub, font: F.mono
    });

    var stats = [
      { n: 20, suf: '', label: 'spk_* 原生导出' },
      { n: 32, suf: '', label: '线程预算上限' },
      { n: 3, suf: '', label: '性能档位' },
      { n: 1, suf: '', label: 'MiB / 块 哈希' }
    ];
    var baseY = 366;
    var colW = W / (stats.length + 1);
    for (var i = 0; i < stats.length; i++) {
      var k = easeOut(seg(t, 30.0 + i * 0.14, 31.1 + i * 0.14));
      var val = (stats[i].n * k);
      var cx = colW * (i + 1);
      text(val.toFixed(0) + stats[i].suf, cx, baseY, {
        align: 'center', size: 62, weight: 600, font: F.display, color: C.ink, alpha: k
      });
      text(stats[i].label, cx, baseY + 28, { align: 'center', size: 11.5, color: C.mute, alpha: k, spacing: 1.2 });
      if (i < stats.length - 1) {
        ctx.strokeStyle = 'rgba(160,205,194,.16)';
        ctx.beginPath();
        ctx.moveTo(colW * (i + 1.5), baseY - 54);
        ctx.lineTo(colW * (i + 1.5), baseY + 34);
        ctx.stroke();
      }
    }

    /* 三档条 */
    var bars = ['性能', '均衡', '省电'];
    var by = 486;
    var bw = 520, bh = 40;
    var bx = (W - bw) / 2;
    for (var b = 0; b < 3; b++) {
      var bp = easeOut(seg(t, 31.0 + b * 0.14, 32.0 + b * 0.14));
      strokeRR(bx, by + b * (bh + 10), bw, bh, 8, 'rgba(136,136,136,.24)');
      var fillW = (bw - 8) * (b === 0 ? 1 : b === 1 ? 0.78 : 0.54) * bp;
      if (fillW > 1) fillRR(bx + 4, by + b * (bh + 10) + 4, fillW, bh - 8, 6,
        b === 0 ? 'rgba(58,157,203,.92)' : b === 1 ? 'rgba(58,157,203,.4)' : 'rgba(58,157,203,.18)');
      text(bars[b], bx + 18, by + b * (bh + 10) + 26, { size: 12, color: b === 0 ? '#ffffff' : C.soft, weight: 500 });
      text(b === 0 ? '全速解码' : b === 1 ? '默认' : '笔记本省电', bx + bw - 18, by + b * (bh + 10) + 26, {
        size: 11, align: 'right', color: b === 0 ? 'rgba(255,255,255,.86)' : C.mute
      });
    }
    ctx.restore();
  }

  /* ---------- 场景 7：收尾 35.4 → 42 ---------- */
  function sceneOutro(t) {
    var p = env(t, 35.3, 42, 0.7, 0.001);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;

    var pop = easeOutBack(seg(t, 35.5, 36.6));
    var size = 96 * clamp(pop, 0.001, 1.2);
    if (logoReady) {
      ctx.save();
      ctx.shadowColor = 'rgba(58,157,203,.5)';
      ctx.shadowBlur = 40;
      ctx.drawImage(logo, W / 2 - size / 2, H / 2 - size / 2 - 84, size, size);
      ctx.restore();
    }
    var lp = easeOut(seg(t, 35.9, 36.9));
    text('SOPEEK', W / 2, H / 2 + 26, { align: 'center', size: 54, weight: 600, font: F.display, spacing: lerp(26, 10, lp), alpha: lp });
    var sp = easeOut(seg(t, 36.3, 37.3));
    text('把「找文件 → 挑文件 → 看文件」压进一个窗口', W / 2, H / 2 + 66, {
      align: 'center', size: 17, color: C.soft, alpha: sp
    });

    var bp = easeOut(seg(t, 36.9, 37.9));
    if (bp > 0) {
      var bw = 208;
      fillRR(W / 2 - bw / 2, H / 2 + 100, bw, 44, 8, 'rgba(58,157,203,' + (0.9 * bp).toFixed(2) + ')');
      text('下载安装包', W / 2, H / 2 + 128, { align: 'center', size: 14, weight: 600, color: 'rgba(255,255,255,' + bp.toFixed(2) + ')' });
      text('AGPL-3.0　·　Windows 10 / 11 x64　·　v2.0.0', W / 2, H / 2 + 176, {
        align: 'center', size: 11, color: C.mute, alpha: bp, font: F.mono, spacing: 1.2
      });
      text('github.com/Dorufoc/Sopeek', W / 2, H / 2 + 200, {
        align: 'center', size: 11, color: 'rgba(222,236,232,.3)', alpha: bp, font: F.mono
      });
    }
    ctx.restore();
  }

  /* ---------- 帧合成 ---------- */
  function render(t) {
    t = clamp(t, 0, DURATION);
    ctx.clearRect(0, 0, W, H);
    backdrop(t);
    sceneIntro(t);
    sceneWindow(t);
    sceneFlow(t);
    scenePreview(t);
    sceneFormats(t);
    scenePerf(t);
    sceneOutro(t);
  }

  /* ---------- 播放器 ---------- */
  var currentT = 0;
  var playing = false;
  var rate = 1;
  var last = 0;
  var raf = 0;

  var btn = document.getElementById('reelPlay');
  var icon = document.getElementById('reelPlayIcon');
  var seek = document.getElementById('reelSeek');
  var prog = document.getElementById('reelProg');
  var head = document.getElementById('reelHeadBar');
  var nowEl = document.getElementById('reelNow');
  var chapters = Array.prototype.slice.call(document.querySelectorAll('.reel-chapter'));
  var marks = chapters.map(function (c) { return parseFloat(c.getAttribute('data-at')); });

  function fmt(t) {
    var m = Math.floor(t / 60);
    var s = t - m * 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s.toFixed(1);
  }

  function syncUI() {
    var p = currentT / DURATION;
    if (prog) prog.style.width = (p * 100).toFixed(3) + '%';
    if (head) head.style.left = (p * 100).toFixed(3) + '%';
    if (seek && document.activeElement !== seek) seek.value = currentT.toFixed(2);
    if (nowEl) nowEl.textContent = fmt(currentT);
    var active = 0;
    for (var i = 0; i < marks.length; i++) if (currentT >= marks[i] - 0.001) active = i;
    chapters.forEach(function (c, i) { c.classList.toggle('is-current', i === active); });
  }

  function draw(t) {
    currentT = clamp(t, 0, DURATION);
    render(currentT);
    syncUI();
  }

  function tick(ts) {
    if (!playing) return;
    if (!last) last = ts;
    var dt = Math.min((ts - last) / 1000, 0.12);
    last = ts;
    currentT += dt * rate;
    if (currentT >= DURATION) {
      currentT = DURATION;
      render(currentT); syncUI();
      pause();
      return;
    }
    render(currentT);
    syncUI();
    raf = window.requestAnimationFrame(tick);
  }

  function play() {
    if (playing) return;
    if (currentT >= DURATION - 0.01) currentT = 0;
    playing = true;
    last = 0;
    if (icon) icon.querySelector('use').setAttribute('href', 'assets/icons.svg#i-pause');
    if (btn) btn.setAttribute('aria-label', '暂停');
    raf = window.requestAnimationFrame(tick);
  }
  function pause() {
    playing = false;
    window.cancelAnimationFrame(raf);
    if (icon) icon.querySelector('use').setAttribute('href', 'assets/icons.svg#i-play');
    if (btn) btn.setAttribute('aria-label', '播放');
  }

  if (btn) btn.addEventListener('click', function () { playing ? pause() : play(); });
  if (seek) {
    seek.max = String(DURATION);
    seek.addEventListener('input', function () {
      pause();
      draw(parseFloat(seek.value));
    });
  }
  chapters.forEach(function (c) {
    c.addEventListener('click', function () {
      pause();
      draw(parseFloat(c.getAttribute('data-at')));
    });
  });
  Array.prototype.slice.call(document.querySelectorAll('[data-rate]')).forEach(function (b) {
    b.addEventListener('click', function () {
      rate = parseFloat(b.getAttribute('data-rate')) || 1;
      document.querySelectorAll('[data-rate]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o === b));
      });
    });
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== ' ' || /INPUT|TEXTAREA|SELECT/.test((ev.target.tagName || ''))) return;
    if (ev.target.closest && ev.target.closest('button, a')) return;
    ev.preventDefault();
    playing ? pause() : play();
  });

  /* 画布点击播放/暂停 */
  canvas.addEventListener('click', function () { playing ? pause() : play(); });
  canvas.style.cursor = 'pointer';

  /* 暴露确定性入口 */
  window.SopeekReel = {
    duration: DURATION,
    render: render,
    seek: function (t) { pause(); draw(t); },
    play: play,
    pause: pause,
    get time() { return currentT; }
  };

  /* 首帧：默认停在片头的海报帧，?t=18.4 可指定任意定格 */
  if (logo.complete) { logoReady = true; }
  var query = new URLSearchParams(window.location.search);
  var poster = parseFloat(query.get('t'));
  draw(isNaN(poster) ? 2.6 : clamp(poster, 0, DURATION));

  /* 字体就绪后再画一次，避免首帧回退字重 */
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { render(currentT); });
  }
})();

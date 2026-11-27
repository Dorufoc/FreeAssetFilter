/* ==========================================================================
   Sopeek Promo — 展示站交互
   --------------------------------------------------------------------------
   只做四件事：主题、顶栏状态、首屏窗口缩放适配、滚动入场、快捷键联动。
   无依赖、无框架、无追踪。
   ========================================================================== */
(() => {
  "use strict";

  const root = document.documentElement;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 1. 主题：跟随系统，可手动覆盖 ---------- */
  const THEME_KEY = "sopeek.promo.theme";

  const readStoredTheme = () => {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch {
      return null;
    }
  };

  const systemTheme = () =>
    window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";

  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    const btn = document.getElementById("themeToggle");
    if (btn) {
      const use = btn.querySelector("use");
      if (use) {
        use.setAttribute("href", `assets/icons.svg#i-${theme === "dark" ? "moon" : "sun"}`);
      }
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "切换到浅色主题" : "切换到深色主题"
      );
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#070b0b" : "#eef1ef");
  };

  applyTheme(readStoredTheme() ?? systemTheme());

  document.getElementById("themeToggle")?.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* 隐私模式下忽略 */
    }
  });

  window
    .matchMedia("(prefers-color-scheme: light)")
    .addEventListener("change", () => {
      if (!readStoredTheme()) applyTheme(systemTheme());
    });

  /* ---------- 2. 顶栏吸附与锚点高亮 ---------- */
  const topbar = document.getElementById("topbar");
  const onScroll = () => {
    if (topbar) topbar.classList.toggle("is-stuck", window.scrollY > 8);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const navLinks = new Map(
    [...document.querySelectorAll(".nav a[href^='#']")].map((a) => [
      a.getAttribute("href").slice(1),
      a,
    ])
  );

  if (navLinks.size && "IntersectionObserver" in window) {
    const spy = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          navLinks.forEach((link, id) => {
            link.toggleAttribute(
              "aria-current",
              id === entry.target.id && entry.intersectionRatio > 0
            );
            if (id === entry.target.id) link.setAttribute("aria-current", "true");
            else link.removeAttribute("aria-current");
          });
        });
      },
      { rootMargin: "-45% 0px -50% 0px", threshold: 0 }
    );
    navLinks.forEach((_, id) => {
      const section = document.getElementById(id);
      if (section) spy.observe(section);
    });
  }

  /* ---------- 3. 首屏窗口：把 1240 宽的真实布局缩放进容器 ---------- */
  const heroWindow = document.querySelector(".fs-window");
  const fitHeroWindow = () => {
    if (!heroWindow) return;
    const width = heroWindow.clientWidth;
    if (width > 0) heroWindow.style.setProperty("--fit", (width / 1240).toFixed(4));
  };

  fitHeroWindow();
  if ("ResizeObserver" in window && heroWindow) {
    new ResizeObserver(fitHeroWindow).observe(heroWindow);
  } else {
    window.addEventListener("resize", fitHeroWindow);
  }

  /* ---------- 4. 滚动入场（JS 添加才生效，禁用 JS 时内容可见） ----------
     用 scroll + getBoundingClientRect 判定，而不是 IntersectionObserver：
     IO 依赖合成帧，在某些无头/嵌入环境下不投递回调，内容会停在 opacity:0。 */
  if (!reduceMotion) {
    const targets = [
      ...document.querySelectorAll(
        ".section-head > div:last-child, .flow-step, .rack-list, .format-group, .notes3 > div, .metric, .stack-layer, .terminal, .note-card, .footer-top"
      ),
    ];
    targets.forEach((el, index) => {
      el.classList.add("reveal");
      el.style.setProperty("--delay", `${Math.min(index % 6, 5) * 55}ms`);
    });

    let queued = false;
    const reveal = () => {
      queued = false;
      const limit = window.innerHeight * 0.94;
      let pending = 0;
      targets.forEach((el) => {
        if (el.classList.contains("is-in")) return;
        if (el.getBoundingClientRect().top <= limit) el.classList.add("is-in");
        else pending += 1;
      });
      // 全部入场后停止监听，避免长页面滚动时的无效计算
      if (!pending) window.removeEventListener("scroll", onScroll);
    };
    const onScroll = () => {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(reveal);
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    reveal();
    // 兜底：若布局在字体加载后发生变化而没触发滚动，1.2s 后再判一次
    window.setTimeout(reveal, 1200);
  }

  /* ---------- 5. 键盘：悬停条目点亮按键，空闲时自动巡演 ---------- */
  const shortcutRows = [...document.querySelectorAll(".sc-row[data-keys]")];
  const keyEls = [...document.querySelectorAll(".keyboard .key")];

  const lightKeys = (row) => {
    const wanted = new Set((row?.dataset.keys ?? "").split(/\s+/).filter(Boolean));
    keyEls.forEach((key) => key.classList.toggle("lit", wanted.has(key.dataset.key)));
  };

  let hoverLock = false;
  shortcutRows.forEach((row) => {
    row.addEventListener("mouseenter", () => {
      hoverLock = true;
      lightKeys(row);
    });
    row.addEventListener("mouseleave", () => {
      hoverLock = false;
      lightKeys(null);
    });
  });

  const shortcutsSection = document.getElementById("shortcuts");
  if (!reduceMotion && shortcutsSection && shortcutRows.length) {
    let cursor = 0;
    let inView = false;
    let timer = 0;

    const tick = () => {
      if (!inView || hoverLock) return;
      lightKeys(shortcutRows[cursor % shortcutRows.length]);
      cursor += 1;
    };

    new IntersectionObserver((entries) => {
      inView = entries.some((entry) => entry.isIntersecting);
      if (inView && !timer) {
        tick();
        timer = window.setInterval(tick, 2600);
      }
      if (!inView && timer) {
        window.clearInterval(timer);
        timer = 0;
        lightKeys(null);
      }
    }).observe(shortcutsSection);
  }
})();

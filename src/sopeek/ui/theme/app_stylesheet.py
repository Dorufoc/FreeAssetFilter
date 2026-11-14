"""App-level stylesheet registry (QSS single-tonification, A1/R2).

Consolidates per-widget ``setStyleSheet`` calls behind one registry so a
theme switch re-applies every fragment exactly once, with two delivery
modes selected by the ``SPK_QSS_MODE`` environment variable:

* ``widget`` (default, performance-first): each fragment is delivered to
  its own registered widget via ``QWidget.setStyleSheet``.  A theme
  switch only re-polishes the widgets whose fragment text actually
  changed — never the whole application tree.  Measured on the real
  main window + settings window (92 fragments, 1600×900, offscreen):
  ~50 ms per switch versus ~206 ms for the app-level sheet, because
  ``QApplication.setStyleSheet`` also re-polishes every *unregistered*
  widget (file cards, preview toolbars, …).  Native ``setStyleSheet``
  semantics also give the exact "nearest rule wins" cascade that the
  legacy scoping emulated.
* ``app`` (fallback / diagnostics): the legacy single application-wide
  sheet via ``QApplication.setStyleSheet`` (one full-tree repolish per
  switch where the widget carrying the fragment is irrelevant).

Migration pattern (triage categories a/b)::

    # before (per-widget, N call sites, re-polish per widget on switch)
    widget.setStyleSheet(f"color: {tm.text.name()}; ...")

    # after (registered fragment, re-applied centrally on switch)
    register_widget_qss(widget, f"color: {tm.text.name()}; ...")

Scoping (``app`` mode only): each registered widget gets a unique
``spkQssId`` dynamic property; its fragment is rewritten with
``[spkQssId="<id>"]`` selectors so subtree semantics are preserved
exactly (self rules via ``Type[spkQssId="<id>"]<pseudo>``, descendant
rules via ``[spkQssId="<id>"] <selector>``, bare declarations via
``*[spkQssId="<id>"]``). ``objectName``/``findChild`` are untouched.

Category (c) sites (genuinely per-instance runtime feedback) keep direct
``setStyleSheet`` and each carry an inline justification comment; the
allowed set is pinned in :data:`DIRECT_SETSTYLESHEET_SITES` and enforced
by a fail-closed unit test that scans the whole package, so any new
direct call site must be registered there first.

``ThemeManager.render_qss`` / signals are preserved untouched; this
module only *reads* the global template and re-applies it when non-empty.
"""

from __future__ import annotations

import os
import re
import threading
import weakref
from typing import Optional

#: Delivery mode selector: ``widget`` (default) or ``app`` (legacy).
QSS_MODE_ENV = "SPK_QSS_MODE"

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
_SIMPLE_SELECTOR_RE = re.compile(r"^([A-Za-z_][\w]*)(.*)$", re.DOTALL)


def _resolve_mode() -> str:
    """Return the delivery mode from ``SPK_QSS_MODE`` (default ``widget``).

    Returns:
        ``"widget"`` (per-widget delivery, performance-first) or
        ``"app"`` (legacy single application-wide sheet).
    """
    raw = os.environ.get(QSS_MODE_ENV, "").strip().lower()
    return "app" if raw == "app" else "widget"


def _looks_like_declarations(text: str) -> bool:
    """Check whether *text* is a plain QSS declaration sequence.

    Used to split a fragment shaped ``prop: value; ... selector { ... }``
    (bare declarations glued in front of a rule). Square/curly brackets
    only occur in selectors, and unbalanced quotes mark attribute values
    that may legitimately contain ``;`` — in both cases the text must not
    be split, because skipping the rule is safer than emitting an
    unparsable selector (see :func:`scope_qss`).

    Args:
        text: Candidate declaration text (without trailing ``;``).

    Returns:
        True when every ``;``-separated segment carries a ``prop: value``
        pair (or is blank), so the text can safely be treated as
        declarations.
    """
    if not text.strip():
        return True
    if any(ch in text for ch in "[]{}"):
        return False
    if text.count('"') % 2 or text.count("'") % 2:
        return False
    return all(":" in seg for seg in text.split(";") if seg.strip())


def _warn_unparsable_fragment(selector: str) -> None:
    """Best-effort warning for a fragment chunk that cannot be scoped.

    Logging must never break style registration, so any logging failure is
    ignored. Imported lazily: ``app_logger`` initializes a session logger
    on import and this module loads during early UI startup.

    Args:
        selector: Offending selector text (truncated for the message).
    """
    try:
        from sopeek.utils.app_logger import warning

        warning(f"scope_qss: 跳过无法解析的样式片段选择器: {selector[:80]!r}")
    except Exception:
        pass  # 日志系统自身失败（预期兜底）：不递归、不抛出


def _debug_log(message: str) -> None:
    """Early-startup-safe debug logging: imports app_logger on demand.

    ``app_logger`` initializes a session logger on import while this module
    loads during early UI startup; importing lazily inside the failure path
    keeps startup cost unchanged. Logging failures never propagate.

    Args:
        message: Preformatted debug message.
    """
    try:
        from sopeek.utils.app_logger import debug

        debug(message)
    except Exception:
        pass  # 日志系统不可用时静默（不得影响样式注册）


def _repaint_all_widgets() -> None:
    """标脏应用内所有控件（配色变化后自绘组件即时换色的兜底）。

    不依赖 ``theme_changed`` 的组件（分段控件 / 开关 / 滑块 / 卡片委托 /
    框选覆层等）只在 paint 时读取 ``tm``；配色单独变化时必须统一标脏，
    否则要等鼠标扫过等外部失效才换色。``update()`` 仅登记脏区，
    成本与控件数量同阶；等待 ``deleteLater`` 析构的控件包 RuntimeError
    跳过（其底层 C++ 对象已销毁）。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.allWidgets():
        try:
            widget.update()
        except (RuntimeError, AttributeError):
            continue


#: Dynamic property used to scope registered fragments. Chosen over
#: ``objectName`` so ``findChild`` lookups and existing ``#id`` selectors
#: keep working untouched. Also used in ``widget`` mode as a cheap
#: registration marker (value stays stable per widget, so re-registering
#: does not emit a property-change event).
SPK_QSS_PROP = "spkQssId"

#: 直接 ``setStyleSheet`` 白名单（category (c)）：(包内相对路径, 所在函数名)。
#: 仅限"运行时逐实例反馈、注册片段表达不了"的调用点；每处必须带内联理由
#: 注释。``tests/unit/ui/theme/test_app_stylesheet.py`` 的 fail-closed 单测
#: 扫描全包比对，新增/移除调用点都必须先同步这里。
DIRECT_SETSTYLESHEET_SITES: frozenset[tuple[str, str]] = frozenset(
    {
        ("ui/layout/file_pool_layout.py", "_animate_card_exit"),
        ("ui/layout/preview/file_info_panel.py", "_apply_toast_style"),
        ("ui/components/styled_sidebar.py", "_apply_label_fade"),
        ("ui/theme/app_stylesheet.py", "rebuild"),
        # widget 模式下注册表自身的逐控件下发/清除与全局模板下发入口
        # （片段内容来自 ``register_widget_qss`` 调用方，非逐实例反馈）。
        ("ui/theme/app_stylesheet.py", "_set_widget_sheet"),
        ("ui/theme/app_stylesheet.py", "_apply_template"),
    }
)


def scope_qss(scope_id: str, qss: str, weight: int = 1) -> str:
    """Rewrite *qss* so it only matches the widget carrying *scope_id*.

    Handles the Qt ``setStyleSheet`` semantics for a whole fragment:
    selector-less declarations cascade to the widget and its subtree,
    rule blocks keep their relative selectors, and a fragment that glues
    bare declarations in front of a rule block (``prop: value; ... Sel {
    ... }``) has the two parts split before scoping. Chunks that cannot
    be parsed reliably are skipped with a warning — never emitted
    malformed, because Qt's parser drops the remainder of the sheet
    after a malformed rule.

    Args:
        scope_id: Unique id stored in the widget's ``spkQssId`` property.
        qss: Original per-widget stylesheet fragment.
        weight: Depth weight (widget tree depth + 1, capped at 3 by
            the caller). The scope attribute is repeated *weight*
            times on every emitted selector, so rules from nearer
            fragments outrank farther ones regardless of base
            specificity — emulating Qt's level precedence (own sheet
            > ancestor sheets), which dominates specificity across
            levels (see task-5 probe_levels.py: own bare beats
            ancestor type). Beyond the cap, depth-sorted document
            order breaks ties level-correctly. Within one fragment
            the relative order is preserved, so same-level
            specificity semantics are unchanged.

    Returns:
        App-level equivalent stylesheet text with identical subtree
        semantics (self + descendants of the scoped widget).
    """
    if not qss or not qss.strip():
        return ""
    weight = max(1, int(weight))
    text = _CSS_COMMENT_RE.sub("", qss)
    prop = f'{SPK_QSS_PROP}="{scope_id}"'
    scope_chain = "".join(f"[{prop}]" for _ in range(weight))

    def _bare(declarations: str) -> list[str]:
        """Scope selector-less declarations (cascade to subtree).

        A bare ``background: transparent;`` set on a widget applies to
        the widget AND all descendants (which is how e.g. a graphics
        view's transparency reached its viewport); closer-level rules
        still win by document order (children register after parents).

        Returns two parse-independent rules (self + subtree) — never
        comma-joined (see the comma note below).
        """
        return [
            f"*{scope_chain} {{ {declarations} }}",
            f"{scope_chain} * {{ {declarations} }}",
        ]

    chunks: list[str] = []
    pos = 0
    for match in _RULE_RE.finditer(text):
        stray = text[pos : match.start()].strip().strip(";").strip()
        if stray:
            chunks.extend(_bare(stray + ";"))
        selector = match.group(1).strip()
        declarations = match.group(2)
        # Fragment shaped ``bare declarations; selector { ... }``: the
        # ``[^{}]+`` group swallows the leading declarations into the
        # selector text (commas inside values such as ``rgba(255,255,255,.5)``
        # then shred the selector list), which emits a malformed rule — and
        # Qt's parser drops the remainder of the sheet after such a rule
        # (regression: the pool panel lost its styles). Split at the last
        # top-level ``;``; the left side keeps bare-declaration semantics.
        if ";" in selector:
            decls_text, _, selector = selector.rpartition(";")
            selector = selector.strip()
            if not _looks_like_declarations(decls_text):
                _warn_unparsable_fragment(match.group(1).strip())
                pos = match.end()
                continue
            if decls_text.strip():
                chunks.extend(_bare(decls_text.strip() + ";"))
        if not selector:
            pos = match.end()
            continue
        if ";" in selector:
            # A valid QSS selector never contains ``;``: a leftover here
            # means the split above was not reliable. Skip the rule instead
            # of emitting text that would poison the sheet's remainder.
            _warn_unparsable_fragment(selector)
            pos = match.end()
            continue
        scoped_parts: list[str] = []
        for part in selector.split(","):
            part = part.strip()
            if not part:
                continue
            if SPK_QSS_PROP in part:
                scoped_parts.append(part)
                continue
            # Descendant form: matches widgets under the scoped root,
            # exactly like the original subtree-relative rule.
            scoped_parts.append(f"{scope_chain} {part}")
            # Self form: the original rule also matched the widget
            # itself when it fit the selector. Type selectors anchor
            # as ``Type[scope]``; id/class selectors (``#id``/``.cls``,
            # which never match the plain type regex) anchor by
            # appending the scope attributes (``#id[scope]``).
            if (" " not in part and ">" not in part
                    and "+" not in part and "~" not in part):
                simple = _SIMPLE_SELECTOR_RE.match(part)
                if simple:
                    base, rest = simple.group(1), simple.group(2)
                    scoped_parts.append(f"{base}{scope_chain}{rest}")
                elif part.startswith(("#", ".", "*")):
                    scoped_parts.append(f"{part}{scope_chain}")
        if scoped_parts:
            # NOTE (task-5 probe_comma/probe_combos): Qt's parser drops
            # the remainder of the sheet after a comma-separated rule
            # that involves a bare-universal part (``*[scope]`` or
            # ``[scope] *``) — even ``self-bare + type`` poisons, while
            # comma lists of only type/#id parts are safe. A comma is
            # pure OR, so such rules are emitted one-selector-per-rule
            # (parse-independent); everything else stays comma-joined
            # to keep the sheet compact.
            def _is_universal(part: str) -> bool:
                """Check whether *part* matches universally."""
                return part.startswith("*") or part.endswith(" *")

            if len(scoped_parts) > 1 and any(
                _is_universal(p) for p in scoped_parts
            ):
                for scoped in scoped_parts:
                    chunks.append(scoped + " {" + declarations + "}")
            else:
                chunks.append(
                    ", ".join(scoped_parts) + " {" + declarations + "}"
                )
        pos = match.end()
    tail = text[pos:].strip().strip(";").strip()
    if tail:
        chunks.extend(_bare(tail + ";"))
    return "\n".join(chunks)


class _AppStylesheetRegistry:
    """Holds per-widget fragments and delivers them to their widgets.

    Delivery modes (see :func:`_resolve_mode`):

    - ``widget`` (default): fragments are pushed straight to the owning
      widget. Only widgets whose fragment text changed are re-polished.
    - ``app`` (fallback): ``build_combined`` renders one scoped sheet
      re-applied through ``QApplication.setStyleSheet``.
    """

    def __init__(self) -> None:
        """Initialize empty registry state."""
        self._lock = threading.Lock()
        # entry := [scope_id, qss, seq, applied_qss_or_None]
        self._fragments: "weakref.WeakKeyDictionary[object, list]" = (
            weakref.WeakKeyDictionary()
        )
        self._counter = 0
        self._dirty = False
        self._signal_connected = False
        self._last_combined = ""
        self._last_template: Optional[str] = None
        self._generation = 0
        self._rebuilding = False
        self._teardown_depth = 0
        self._defer_reschedule = False
        self._frag_version = 0
        self._mode = _resolve_mode()
        self._rebuild_timer = None  # 单例合并定时器（app 模式）
        self._pending_generation = 0
        self._last_prune_logged = -1
        self._first_apply_done = False

    # ── 模式 ──────────────────────────────────────────────────────

    def mode(self) -> str:
        """Return the active delivery mode (``"widget"`` / ``"app"``).

        Returns:
            Current mode string, fixed for the registry lifetime.
        """
        return self._mode

    # ── 注册 / 注销 ───────────────────────────────────────────────

    def register(self, widget: object, qss: str) -> str:
        """Store *qss* for *widget* and deliver it (widget mode: inline).

        Re-registering the identical fragment text is a no-op: the widget
        is not re-polished and no rebuild is scheduled. This matters on
        theme switches, where each widget is typically registered twice
        (once from ``theme_changed`` handlers, once from
        ``colors_updated`` handlers) with the same or only partly
        different text.

        Args:
            widget: Target ``QWidget`` (must support setProperty).
            qss: Stylesheet fragment (evaluated by the caller, so theme
                re-registration paths keep working unchanged).

        Returns:
            The stable scope id assigned to *widget*.
        """
        if not isinstance(qss, str) or not qss.strip():
            self.unregister(widget)
            return ""
        with self._lock:
            entry = self._fragments.get(widget)
            if entry is None:
                self._counter += 1
                scope_id = f"spk-{self._counter}"
                entry = [scope_id, qss, self._counter, None]
                self._fragments[widget] = entry
            else:
                scope_id = entry[0]
                if entry[1] == qss:
                    self._ensure_theme_hook()
                    return scope_id
                entry[1] = qss
            self._dirty = True
            self._frag_version += 1
        try:
            # 值稳定（同控件恒为同一 id）：重复注册不触发属性变更事件。
            widget.setProperty(SPK_QSS_PROP, scope_id)  # type: ignore[attr-defined]
        except Exception as exc:
            _debug_log(f"设置 QSS 作用域属性失败：{exc}")
        self._ensure_theme_hook()
        if self._mode == "widget":
            self._apply_entry(widget)
        else:
            self._schedule_rebuild()
        return scope_id

    def unregister(self, widget: object) -> None:
        """Drop *widget*'s fragment (``setStyleSheet("")`` equivalent).

        Args:
            widget: Previously registered widget.
        """
        with self._lock:
            had = widget in self._fragments
            if had:
                del self._fragments[widget]
                self._dirty = True
                self._frag_version += 1
        try:
            widget.setProperty(SPK_QSS_PROP, "")  # type: ignore[attr-defined]
        except Exception as exc:
            _debug_log(f"清除 QSS 作用域属性失败：{exc}")
        if had and self._mode == "widget":
            self._set_widget_sheet(widget, "")
            return
        self._schedule_rebuild()

    def registered_count(self) -> int:
        """Return the number of live registered widgets.

        Returns:
            Count of currently tracked widgets.
        """
        with self._lock:
            return len(self._fragments)

    def reset(self) -> None:
        """Drop all fragments and clear pending state (test isolation).

        Widgets constructed afterwards re-register from their own
        constructors, so per-test styling is unaffected; only
        cross-test accumulation is discarded.

        Deliberately does NOT call ``app.setStyleSheet("")`` here: this
        runs on every test teardown (via ``reset_qss_registry``), when
        the just-finished test's widgets typically have ``deleteLater``
        pending — a full-tree repolish at that moment wedges natively
        (task-5 rebuild-hang fix). Skipping the blanket clear is safe:
        scope ids are monotonic and never reused, so rules from the
        previous sheet cannot match any new widget; the next rebuild
        overwrites the sheet from the (now empty) registry anyway.

        Bumps the coalescing generation so ticks scheduled before this
        reset die silently instead of polishing a torn-down tree.
        """
        with self._lock:
            self._fragments.clear()
            self._dirty = False
            self._generation += 1
            self._frag_version += 1
            self._first_apply_done = False
        timer = self._rebuild_timer
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass  # 定时器已随宿主销毁：重置时无需再停

    def is_dirty(self) -> bool:
        """Return whether a rebuild is pending.

        Returns:
            True when fragments changed since the last rebuild.
        """
        with self._lock:
            return self._dirty

    # ── widget 模式：逐控件下发 ───────────────────────────────────

    def _apply_entry(self, widget: object) -> bool:
        """Deliver the entry's current fragment to *widget*.

        Skips when the fragment was already delivered, defers while a
        teardown window is open, and prunes the entry when the widget is
        gone (see :meth:`_set_widget_sheet`).

        Args:
            widget: Registered widget.

        Returns:
            True when a sheet was actually applied.
        """
        with self._lock:
            entry = self._fragments.get(widget)
            if entry is None:
                return False
            qss = entry[1]
            if entry[3] == qss:
                return False
        if self._teardown_depth > 0:
            # 清理窗口内不下发：resume 后由 sweep 合并补发。
            with self._lock:
                self._defer_reschedule = True
            return False
        if not self._set_widget_sheet(widget, qss):
            with self._lock:
                if self._fragments.get(widget) is entry:
                    self._fragments.pop(widget, None)
                    self._frag_version += 1
            return False
        with self._lock:
            if self._fragments.get(widget) is entry:
                entry[3] = qss
        return True

    @staticmethod
    def _set_widget_sheet(widget: object, qss: str) -> bool:
        """Apply *qss* to *widget* (single direct-call site for widget mode).

        控件已销毁（C++ 对象不存在）时静默失败，由调用方剪枝：历史实现
        每次重刷都会为数百个已销毁控件逐条抛异常 + 写日志（单次
        300~400 行），这里改为返回 False 由注册表一次性清理。

        Args:
            widget: Target widget (possibly already destroyed).
            qss: Fragment text (``""`` clears the widget's own sheet).

        Returns:
            True when the sheet was applied, False when the widget is
            gone or refused the call.
        """
        try:
            from shiboken6 import isValid
        except Exception:
            isValid = None  # type: ignore[assignment]
        try:
            if isValid is not None and not isValid(widget):
                return False
            widget.setStyleSheet(qss)  # type: ignore[attr-defined]
            return True
        except (RuntimeError, TypeError):
            return False
        except Exception as exc:  # noqa: BLE001 - 下发失败按条目剪枝处理
            _debug_log(f"控件样式下发失败（已剪枝）：{exc}")
            return False

    def apply_widget_sheets(self, force: bool = False) -> bool:
        """Deliver every pending fragment, then prune gone widgets.

        Cheap and idempotent: entries whose text was already delivered are
        skipped. ``force=True`` re-delivers every entry (each widget then
        sees a style change, letting Qt recompute cached layout metrics —
        the guarantee the historical app-wide apply provided once at
        startup).

        Args:
            force: Re-deliver every registered fragment, even unchanged.

        Returns:
            True when a QApplication exists (delivery attempted),
            False when no application exists yet.
        """
        try:
            from PySide6.QtWidgets import QApplication
        except Exception:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        self._prune_dead()
        with self._lock:
            items = list(self._fragments.items())
            if force:
                for entry in self._fragments.values():
                    entry[3] = None
        for widget, entry in items:
            if force or entry[3] != entry[1]:
                self._apply_entry(widget)
        self._apply_template()
        with self._lock:
            if self._teardown_depth == 0:
                self._dirty = False
        return True

    def take_first_apply(self) -> bool:
        """Return True exactly once per registry lifetime (startup pass).

        Mirrors the historical ``apply_app_stylesheet()`` start-up
        app-wide apply: the first call performs a full re-delivery so
        every registered widget receives one style change after the UI
        is built.

        Returns:
            True on the first call, False afterwards (until :meth:`reset`).
        """
        with self._lock:
            if self._first_apply_done:
                return False
            self._first_apply_done = True
            return True

    def _prune_dead(self) -> int:
        """Drop entries whose C++ object is destroyed.

        ``WeakKeyDictionary`` only tracks the Python wrappers; a wrapper
        often outlives its C++ object (Qt keeps signal connections alive
        until the receiver is destroyed, and the wrapper until the next
        GC), so dead entries linger and would otherwise be walked on every
        pass. Logs at most one summary line per distinct count.

        Returns:
            Number of pruned entries.
        """
        try:
            from shiboken6 import isValid
        except Exception:
            return 0
        with self._lock:
            items = list(self._fragments.keys())
        dead: list[object] = []
        for widget in items:
            try:
                alive = isValid(widget)
            except Exception:
                alive = False
            if not alive:
                dead.append(widget)
        if not dead:
            return 0
        with self._lock:
            for widget in dead:
                self._fragments.pop(widget, None)
            self._frag_version += len(dead)
        count = len(dead)
        if count != self._last_prune_logged:
            self._last_prune_logged = count
            _debug_log(f"QSS 注册表剪枝已销毁控件 {count} 个")
        return count

    # ── app 模式：合并为一张应用级样式表 ──────────────────────────

    def build_combined(self) -> str:
        """Render the full app-level stylesheet without applying it.

        Fragments are emitted shallow-first (stable by registration
        sequence within one depth) so document order mirrors Qt's
        ancestor-before-descendant level order; combined with
        depth-weighted specificity in :func:`scope_qss` this reproduces
        per-widget cascade precedence in a single sheet.

        Returns:
            Global template output + all scoped fragments concatenated.
        """
        self._prune_dead()
        try:
            from sopeek.ui.theme.theme_manager import ThemeManager

            global_qss = ThemeManager().render_qss()
        except Exception:
            global_qss = ""
        with self._lock:
            items = list(self._fragments.items())
        ranked = []
        for widget, entry in items:
            scope_id, qss = entry[0], entry[1]
            seq = entry[2] if len(entry) > 2 else 0
            ranked.append((self._widget_depth(widget), seq, scope_id, qss))
        ranked.sort(key=lambda row: (row[0], row[1]))
        parts: list[str] = []
        if global_qss and global_qss.strip():
            parts.append(global_qss)
        for depth, _seq, scope_id, qss in ranked:
            try:
                # Depth weight capped at 3 (levels 0-2 exact; deeper
                # conflicts fall back to depth-sorted document order,
                # which is also level-correct for ties). Full
                # depth+1 weights bloat selectors and make Qt's
                # matcher superlinear (task-5 probe_profile: 1.5-3s
                # per repolish at 8 windows); A/B parity holds at
                # cap 3 with strict=0.0000% on all subjects.
                scoped = scope_qss(scope_id, qss, weight=min(depth + 1, 3))
            except Exception:
                continue
            if scoped:
                parts.append(f"/* spk:{scope_id} */\n" + scoped)
        combined = "\n".join(parts)
        self._last_combined = combined
        return combined

    def rebuild(self, force: bool = False) -> bool:
        """Apply the combined sheet via the single app-level call.

        This is the ONLY ``QApplication.setStyleSheet`` call in the app
        delivery mode (R2: theme switch collapses N re-polishes into one).

        Coalesced timer ticks call with ``force=False`` and return
        immediately when nothing changed since the last apply, so
        event-loop pumps never trigger redundant full-tree re-polishes.

        Safe-application guards (task-5 rebuild-hang fix): a coalesced
        tick can land inside a teardown ``processEvents`` pump. The
        guards below make such a tick a harmless no-op whenever the
        application object is missing, invalid, or closing down, and
        the dirty flag is intentionally left set so the next safe tick
        still applies the pending update instead of silently dropping
        it. Deliberately, no pending widget destruction is forced here:
        completing foreign ``deleteLater`` items synchronously perturbs
        destruction order (native destructors may rely on pump-time
        interleaving) and was observed to trade the teardown wedge for
        an access violation. Cleanup of dead widgets happens naturally
        at event-loop pumps; the registry itself only holds weak
        references, so dead widgets simply stop matching.

        Re-entrancy guard: ``app.setStyleSheet`` dispatches style
        change events synchronously; a widget handler that registers a
        new fragment can therefore re-enter this method while the
        outer polish is still running. A nested rebuild is deferred to
        the next event-loop turn (generation bump + reschedule) instead
        of nesting another full-tree polish, keeping the cost bounded
        and the application responsive.

        Args:
            force: Re-apply even when no fragment changed (theme
                switch path: same fragments, new colors).

        Returns:
            True when the sheet was applied, False when there was
            nothing to do, no valid QApplication exists yet (fragments
            stay pending for the next safe tick), or the application
            is closing down.
        """
        if not force and not self.is_dirty():
            return False
        try:
            from PySide6.QtCore import QCoreApplication
            from PySide6.QtWidgets import QApplication
        except Exception:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        try:
            from shiboken6 import isValid

            if not isValid(app):
                return False
        except Exception as exc:
            _debug_log(f"app 有效性检查失败（按有效继续）：{exc}")
        try:
            if QCoreApplication.closingDown():
                return False
        except Exception as exc:
            _debug_log(f"应用关闭状态检查失败（按未关闭处理）：{exc}")
        with self._lock:
            if self._teardown_depth > 0:
                # teardown 清理窗口：当时树上仍有大量 deleteLater 待销毁控件，
                # 任何全树 setStyleSheet 都会按存活规模线性放大（历史数千控件
                # 时单次数十秒）。只记脏并延后重排，清理完成后合并下发一次；
                # force（主题切换）同样延后，dirty 标志保留，恢复后必被重排。
                self._dirty = True
                self._defer_reschedule = True
                return False
        with self._lock:
            if self._rebuilding:
                # 嵌套重刷：不叠第二轮全树 polish，改到下一轮事件循环。
                self._dirty = True
                pending = True
            else:
                self._rebuilding = True
                pending = False
                version = self._frag_version
        if pending:
            self._schedule_rebuild()
            return False
        try:
            combined = self.build_combined()
            try:
                app.setStyleSheet(combined)
            except Exception:
                return False
            with self._lock:
                # 只在期间没有新注册/注销时清脏，避免静默丢掉本轮更新
                # （历史缺陷：失败/竞态下 dirty 已清 → 界面停在半旧态）。
                if self._frag_version == version:
                    self._dirty = False
            return True
        finally:
            with self._lock:
                self._rebuilding = False

    # ── 合并调度 / 全局模板 ───────────────────────────────────────

    def _schedule_rebuild(self) -> None:
        """Coalesce pending rebuilds into one event-loop tick.

        Uses a single persistent timer instead of one
        ``QTimer.singleShot`` per registration: a theme switch
        re-registers every fragment (~100+ calls), and the historical
        one-shot-per-call approach created ~124 throwaway timers per
        switch, each firing an empty callback.

        The tick carries the current coalescing generation; if a
        :meth:`reset` bumps the generation before the tick fires (e.g.
        a test teardown ran in between), the stale tick becomes a
        no-op instead of repolishing a torn-down tree.
        """
        if self._mode != "app":
            return
        try:
            from PySide6.QtCore import QCoreApplication, QTimer

            if QCoreApplication.instance() is None:
                return
            if QCoreApplication.closingDown():
                return
            with self._lock:
                generation = self._generation
            timer = self._rebuild_timer
            if timer is None:
                timer = QTimer()
                timer.setSingleShot(True)
                timer.setInterval(0)
                timer.timeout.connect(self._on_rebuild_timer)
                self._rebuild_timer = timer
            self._pending_generation = generation
            timer.start()
        except Exception as exc:
            _debug_log(f"样式表重建调度失败：{exc}")

    def _on_rebuild_timer(self) -> None:
        """Persistent-timer slot: run a coalesced rebuild if still current."""
        generation = self._pending_generation
        self._rebuild_if_current(generation)

    def _apply_template(self) -> bool:
        """Deliver the global template (``render_qss``) when it changed.

        The template is empty in this repo (no ``global.qss.tpl``), in
        which case this is a zero-cost no-op. When a template does
        exist it is applied once at the application level on change —
        never on every theme switch.

        Returns:
            True when a template sheet was applied.
        """
        try:
            from sopeek.ui.theme.theme_manager import ThemeManager

            template = ThemeManager().render_qss()
        except Exception:
            template = ""
        if not template or not template.strip():
            return False
        with self._lock:
            if template == self._last_template:
                return False
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return False
            app.setStyleSheet(template)
        except Exception as exc:
            _debug_log(f"全局模板下发失败：{exc}")
            return False
        with self._lock:
            self._last_template = template
        return True

    def suspend_apply(self) -> None:
        """暂停样式下发（进入 teardown 清理窗口）。

        清理窗口里 ``deleteLater`` 的控件仍挂在应用树上，此时全树
        ``setStyleSheet`` 的成本与存活控件规模成正比（历史上数千控件时
        单次可达数十秒，把 teardown 事件泵变成超时点）；widget 模式下
        逐控件下发同样应暂停，避免向待销毁控件下发。暂停期间
        :meth:`rebuild` / :meth:`_apply_entry` 只记脏并延后，由
        :meth:`resume_apply` 在清理完成后触发一次合并下发。可重入
        （按计数配对）。
        """
        with self._lock:
            self._teardown_depth += 1

    def resume_apply(self) -> None:
        """恢复样式下发；若暂停期间有积压变更则重排一次合并下发。"""
        with self._lock:
            if self._teardown_depth > 0:
                self._teardown_depth -= 1
            pending = self._defer_reschedule and self._teardown_depth == 0
            if pending:
                self._defer_reschedule = False
        if not pending:
            return
        if self._mode == "widget":
            self.apply_widget_sheets()
        else:
            self._schedule_rebuild()

    def _rebuild_if_current(self, generation: int) -> bool:
        """Run :meth:`rebuild` only when *generation* is still current.

        Args:
            generation: Coalescing generation captured when the tick
                was scheduled.

        Returns:
            The :meth:`rebuild` result, or False for a stale tick that
            was superseded by a :meth:`reset`.
        """
        try:
            with self._lock:
                current = self._generation
            if generation != current:
                return False
            return self.rebuild()
        except Exception:
            return False

    def _ensure_theme_hook(self) -> None:
        """Connect ``ThemeManager`` theme/color signals to the hooks.

        ``app`` 模式下主题回调**同步**执行一次全树重刷（实测 1600×900
        主窗 ~50ms，含设置窗口 ~206ms）——这是历史视觉同步的必要代价。
        ``widget`` 模式下各控件片段由其订阅者重新注册时逐控件下发，
        回调本身零成本（仅当全局模板非空时下发模板）。

        ``colors_updated`` 只有强调色变化时也会发射（不发
        ``theme_changed``）；此时样式片段需由各自订阅者重新注册，
        自绘组件则靠 :meth:`_on_colors_updated` 的全树标脏即时换色。
        """
        if self._signal_connected:
            return
        try:
            from sopeek.ui.theme.theme_manager import ThemeManager

            ThemeManager().theme_changed.connect(self._on_theme_changed)
            ThemeManager().colors_updated.connect(self._on_colors_updated)
            self._signal_connected = True
        except Exception as exc:
            _debug_log(f"主题信号连接失败（样式表退化为手动触发重建）：{exc}")

    def _on_colors_updated(self, _colors: dict) -> None:
        """配色变化回调：标脏全应用控件，保证自绘组件即时换色。

        强调色（主题色）单独变化时不发 ``theme_changed``，而自绘组件
        （分段控件 / 开关 / 滑块 / 卡片委托 / 框选覆层等）只在 paint 时
        读取 ``tm``，没有订阅者主动标脏就要等鼠标扫过等外部失效才换色
        （历史缺陷：「换主题色后部分控件卡住旧色」）。

        ``update()`` 只登记脏区，成本与控件数量同阶，远低于重绘本身；
        主题色改动已由设置页去抖合并，不会逐帧触发。

        Args:
            _colors: 更新后的配色字典（未使用）。
        """
        _repaint_all_widgets()

    def _on_theme_changed(self, _theme: str) -> None:
        """Theme-switch callback: app mode rebuilds, widget mode is free.

        Args:
            _theme: New effective theme name (unused).
        """
        if self._mode == "app":
            self.rebuild(force=True)
            return
        # widget 模式：片段在各自订阅者重新注册时逐控件下发；
        # 模板非空时补一次模板下发（本仓库为空 → 零成本）。
        self._prune_dead()
        self._apply_template()

    @staticmethod
    def _widget_depth(widget: object) -> int:
        """Return the QWidget ancestor depth of *widget* (top-level = 0).

        Failures are silent: dead wrappers must not generate one log line
        each (historical defect: 300~400 lines per rebuild after the
        settings window was destroyed) — :meth:`_prune_dead` removes them.

        Args:
            widget: Widget whose depth to measure.

        Returns:
            Number of strict QWidget ancestors (0 on any error).
        """
        depth = 0
        try:
            parent = widget.parent()  # type: ignore[attr-defined]
            while parent is not None:
                depth += 1
                parent = parent.parent()
        except Exception:
            return 0
        return depth


_REGISTRY = _AppStylesheetRegistry()


def suspend_qss_apply() -> None:
    """暂停样式下发（进入 teardown 清理窗口；可重入计数）。"""
    _REGISTRY.suspend_apply()


def resume_qss_apply() -> None:
    """恢复样式下发；暂停期间积压的变更会合并重排一次。"""
    _REGISTRY.resume_apply()


def register_widget_qss(widget: object, qss: str) -> str:
    """Register a per-widget QSS fragment and deliver it.

    Drop-in replacement for ``widget.setStyleSheet(qss)`` (triage
    categories a/b). The fragment is re-delivered on theme switch;
    callers keep re-invoking this from their existing
    ``_on_theme_changed`` handlers exactly as before (identical text is
    skipped).

    Args:
        widget: Target widget.
        qss: Stylesheet text (empty/blank unregisters).

    Returns:
        Stable scope id for *widget* ("" when unregistered).
    """
    return _REGISTRY.register(widget, qss)


def unregister_widget_qss(widget: object) -> None:
    """Remove *widget*'s fragment (``setStyleSheet("")`` equivalent).

    Args:
        widget: Previously registered widget.
    """
    _REGISTRY.unregister(widget)


def apply_app_stylesheet() -> bool:
    """Force-apply the pending stylesheet state now.

    Called once at startup after the main window is built, and
    automatically on every ``ThemeManager.theme_changed`` afterwards.
    In widget mode (default) the **first** call re-delivers every
    registered fragment (each widget gets one style change after the UI
    is built — the guarantee the historical app-wide apply provided, and
    the trigger Qt needs to recompute cached layout metrics); later calls
    only deliver fragments that could not be delivered inline (e.g. while
    a teardown window was open). In app mode it applies the combined
    sheet.

    Returns:
        True when applied (or nothing was pending), False when no
        QApplication exists yet.
    """
    _REGISTRY._ensure_theme_hook()
    if _REGISTRY.mode() == "widget":
        return _REGISTRY.apply_widget_sheets(force=_REGISTRY.take_first_apply())
    return _REGISTRY.rebuild()


def reset_qss_registry() -> None:
    """Clear the app-stylesheet registry (test isolation hook).

    Called from ``tests/conftest.py::_reset_all_singletons`` between
    tests so the central sheet never accumulates session-wide.
    """
    _REGISTRY.reset()


def registered_widget_count() -> int:
    """Return the number of live registered widgets (diagnostics).

    Returns:
        Count of currently tracked widgets.
    """
    return _REGISTRY.registered_count()


def prune_dead_registrations() -> int:
    """Drop registry entries whose C++ widget is already destroyed.

    Called after a window subtree is destroyed (e.g. the settings window
    with ``WA_DeleteOnClose``) so the registry does not accumulate dead
    entries between theme switches.

    Returns:
        Number of pruned entries.
    """
    return _REGISTRY._prune_dead()


def stylesheet_mode() -> str:
    """Return the active QSS delivery mode (diagnostics / tests).

    Returns:
        ``"widget"`` or ``"app"``.
    """
    return _REGISTRY.mode()


def scope_stylesheet_for_test(scope_id: str, qss: str) -> str:
    """Test hook exposing :func:`scope_qss`.

    Args:
        scope_id: Scope id to use.
        qss: Fragment to scope.

    Returns:
        App-level equivalent stylesheet text.
    """
    return scope_qss(scope_id, qss)

"""App-level stylesheet singleton (QSS single-tonification, A1/R2).

Consolidates per-widget ``setStyleSheet`` calls into one application
stylesheet applied via ``QApplication.setStyleSheet`` exactly once per
theme switch (plus one initial apply at startup).

Migration pattern (triage categories a/b)::

    # before (per-widget, N call sites, re-polish per widget on switch)
    widget.setStyleSheet(f"color: {tm.text.name()}; ...")

    # after (registered fragment, re-rendered centrally on switch)
    register_widget_qss(widget, f"color: {tm.text.name()}; ...")

Scoping: each registered widget gets a unique ``fafQssId`` dynamic
property; its fragment is rewritten with ``[fafQssId="<id>"]`` selectors
so subtree semantics are preserved exactly (self rules via
``Type[fafQssId="<id>"]<pseudo>``, descendant rules via
``[fafQssId="<id>"] <selector>``, bare declarations via
``*[fafQssId="<id>"]``). ``objectName``/``findChild`` are untouched.

Category (c) sites (genuinely per-instance runtime feedback such as drag
borders) keep direct ``setStyleSheet`` and are each justified in the
task-5 report.

``ThemeManager.render_qss`` / signals are preserved untouched; this
module only *reads* the global template and re-applies on
``theme_changed``.
"""

from __future__ import annotations

import re
import threading
import weakref
from typing import Callable, Dict, Optional

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
_SIMPLE_SELECTOR_RE = re.compile(r"^([A-Za-z_][\w]*)(.*)$", re.DOTALL)

#: Dynamic property used to scope registered fragments. Chosen over
#: ``objectName`` so ``findChild`` lookups and existing ``#id`` selectors
#: keep working untouched.
FAF_QSS_PROP = "fafQssId"


def scope_qss(scope_id: str, qss: str, weight: int = 1) -> str:
    """Rewrite *qss* so it only matches the widget carrying *scope_id*.

    Args:
        scope_id: Unique id stored in the widget's ``fafQssId`` property.
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
    prop = f'{FAF_QSS_PROP}="{scope_id}"'
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
        scoped_parts: list[str] = []
        for part in selector.split(","):
            part = part.strip()
            if not part:
                continue
            if FAF_QSS_PROP in part:
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
    """Holds per-widget fragments and rebuilds the single app sheet."""

    def __init__(self) -> None:
        """Initialize empty registry state."""
        self._lock = threading.Lock()
        self._fragments: "weakref.WeakKeyDictionary[object, list[str]]" = (
            weakref.WeakKeyDictionary()
        )
        self._counter = 0
        self._dirty = False
        self._signal_connected = False
        self._last_combined = ""
        self._generation = 0

    def register(self, widget: object, qss: str) -> str:
        """Store *qss* for *widget*, assigning a stable scope id.

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
                scope_id = f"faf-{self._counter}"
                self._fragments[widget] = [scope_id, qss, self._counter]
            else:
                scope_id = entry[0]
                entry[1] = qss
            self._dirty = True
        try:
            widget.setProperty(FAF_QSS_PROP, scope_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._ensure_theme_hook()
        self._schedule_rebuild()
        return scope_id

    def unregister(self, widget: object) -> None:
        """Drop *widget*'s fragment (``setStyleSheet("")`` equivalent).

        Args:
            widget: Previously registered widget.
        """
        with self._lock:
            if widget in self._fragments:
                del self._fragments[widget]
                self._dirty = True
        try:
            widget.setProperty(FAF_QSS_PROP, "")  # type: ignore[attr-defined]
        except Exception:
            pass
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

    def is_dirty(self) -> bool:
        """Return whether a rebuild is pending.

        Returns:
            True when fragments changed since the last rebuild.
        """
        with self._lock:
            return self._dirty

    def _ensure_theme_hook(self) -> None:
        """Connect ``ThemeManager.theme_changed`` to rebuild (once)."""
        if self._signal_connected:
            return
        try:
            from freeassetfilter.ui.theme.theme_manager import ThemeManager

            ThemeManager().theme_changed.connect(
                lambda _t: self.rebuild(force=True)
            )
            self._signal_connected = True
        except Exception:
            pass

    def _schedule_rebuild(self) -> None:
        """Coalesce pending rebuilds into one event-loop tick.

        The tick carries the current coalescing generation; if a
        :meth:`reset` bumps the generation before the tick fires (e.g.
        a test teardown ran in between), the stale tick becomes a
        no-op instead of repolishing a torn-down tree.
        """
        try:
            from PySide6.QtCore import QCoreApplication
            from PySide6.QtCore import QTimer

            if QCoreApplication.instance() is None:
                return
            if QCoreApplication.closingDown():
                return
            with self._lock:
                generation = self._generation
            QTimer.singleShot(
                0, lambda: self._rebuild_if_current(generation)
            )
        except Exception:
            pass

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

    @staticmethod
    def _widget_depth(widget: object) -> int:
        """Return the QWidget ancestor depth of *widget* (top-level = 0).

        Args:
            widget: Widget whose depth to measure.

        Returns:
            Number of strict QWidget ancestors (0 on any error, e.g.
            Tk-deleted wrappers — their rules match nothing anyway).
        """
        depth = 0
        try:
            parent = widget.parent()  # type: ignore[attr-defined]
            while parent is not None:
                depth += 1
                parent = parent.parent()
        except Exception:
            pass
        return depth

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
        try:
            from freeassetfilter.ui.theme.theme_manager import ThemeManager

            global_qss = ThemeManager().render_qss()
        except Exception:
            global_qss = ""
        with self._lock:
            items = list(self._fragments.items())
            self._dirty = False
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
                parts.append(f"/* faf:{scope_id} */\n" + scoped)
        combined = "\n".join(parts)
        self._last_combined = combined
        return combined

    def rebuild(self, force: bool = False) -> bool:
        """Apply the combined sheet via the single app-level call.

        This is the ONLY ``QApplication.setStyleSheet`` call in the
        product (R2: theme switch collapses N re-polishes into one).

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
        except Exception:
            pass
        try:
            if QCoreApplication.closingDown():
                return False
        except Exception:
            pass
        combined = self.build_combined()
        try:
            app.setStyleSheet(combined)
        except Exception:
            return False
        return True


_REGISTRY = _AppStylesheetRegistry()


def register_widget_qss(widget: object, qss: str) -> str:
    """Register a per-widget QSS fragment into the app-level sheet.

    Drop-in replacement for ``widget.setStyleSheet(qss)`` (triage
    categories a/b). The fragment is scoped to *widget*'s subtree and
    re-applied centrally on theme switch; callers keep re-invoking this
    from their existing ``_on_theme_changed`` handlers exactly as before.

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
    """Force-apply the combined app stylesheet now.

    Called once at startup after the main window is built, and
    automatically on every ``ThemeManager.theme_changed`` afterwards.

    Returns:
        True when applied, False when no QApplication exists yet.
    """
    _REGISTRY._ensure_theme_hook()
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


def scope_stylesheet_for_test(scope_id: str, qss: str) -> str:
    """Test hook exposing :func:`scope_qss`.

    Args:
        scope_id: Scope id to use.
        qss: Fragment to scope.

    Returns:
        Scoped stylesheet text.
    """
    return scope_qss(scope_id, qss)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Background PDF page renderer — ports sioyek's PdfRenderer (pdf_renderer.h/cpp)
to Python using QThreadPool + QRunnable for thread-safe background rendering
with an LRU cache and closest-zoom fallback.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, List, Optional

import fitz

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage


# ── Data classes (sioyek RenderRequest / RenderResponse) ──────────────


@dataclass
class RenderRequest:
    """Render request matching sioyek's ``RenderRequest`` struct.

    Attributes
    ----------
    path : str
        Absolute or relative path to the PDF file.
    page : int
        Zero-based page number to render.
    zoom : float
        Zoom level (1.0 = 72 DPI / screen resolution).
    dpr : float
        Device-pixel ratio for HiDPI displays (default 1.0).
    request_id : int
        Unique identifier for tracking and cancellation.
    """

    path: str
    page: int
    zoom: float
    dpr: float = 1.0
    request_id: int = 0


@dataclass
class RenderResponse:
    """Render response matching sioyek's ``RenderResponse`` struct.

    Attributes
    ----------
    request : RenderRequest
        The original request this response corresponds to.
    image : QImage | None
        The rendered page image, or ``None`` if rendering failed
        or has not yet completed.
    timestamp : int
        Monotonic access timestamp (``time.monotonic_ns()``)
        for LRU cache eviction ordering.
    pending : bool
        ``True`` while the render task is still queued or in progress;
        ``False`` once rendering has completed (success or failure).
    invalid : bool
        ``True`` if this response has been invalidated (cancelled or
        superseded by a newer request).  Matches sioyek's ``invalid``
        field.
    """

    request: RenderRequest
    image: Optional[QImage] = None
    timestamp: int = 0
    pending: bool = True
    invalid: bool = False


# ── Worker task (sioyek PdfRenderer::run() pattern) ───────────────────


class _RenderTask(QRunnable):
    """QRunnable worker that renders a single PDF page.

    Ported from sioyek's ``PdfRenderer::run()`` worker-thread pattern.
    Each task opens its own ``fitz.open(path)`` — PyMuPDF ``Document``
    objects are **not** thread-safe, so sharing across threads would
    require a lock that serialises all access.  Opening a fresh
    document per task is the recommended pattern; MuPDF shares its
    underlying file-data internally, so the memory overhead is
    acceptable.

    Parameters
    ----------
    request : RenderRequest
        The render parameters (path, page, zoom, dpr, id).
    callback : Callable[[RenderRequest, Optional[QImage]], None]
        Invoked on completion (from the pool thread).  The caller is
        responsible for dispatching the result back to the main thread
        via a Qt signal.
    """

    def __init__(
        self,
        request: RenderRequest,
        callback: Callable[[RenderRequest, Optional[QImage]], None],
    ) -> None:
        super().__init__()
        self._request: RenderRequest = request
        self._callback: Callable[[RenderRequest, Optional[QImage]], None] = callback
        self._cancelled: bool = False

    # ── Public ─────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Mark this task as cancelled.

        The ``run()`` method checks this flag before and after
        rendering and will skip storing the result if cancelled.
        """
        self._cancelled = True

    # ── QRunnable ──────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute the render.

        1. Opens ``fitz.open(self._request.path)`` (per-thread document).
        2. Loads the target page and calls ``get_pixmap()`` with
           ``zoom * dpr``.
        3. Converts the pixmap to a ``QImage``.
        4. Invokes ``self._callback(request, image)``.

        If the file cannot be opened, the page index is out of range,
        or the task was cancelled, the callback is invoked with
        ``image=None``.
        """
        if self._cancelled:
            self._callback(self._request, None)
            return

        # Open a fresh document per task (thread-safe pattern)
        try:
            doc: fitz.Document = fitz.open(self._request.path)
        except Exception:
            self._callback(self._request, None)
            return

        try:
            page: fitz.Page = doc.load_page(self._request.page)
            mat: fitz.Matrix = fitz.Matrix(
                self._request.zoom * self._request.dpr,
                self._request.zoom * self._request.dpr,
            )
            pix: fitz.Pixmap = page.get_pixmap(matrix=mat, alpha=False)

            # Copy samples out of the pixmap before it goes out of scope
            samples: bytes = bytes(pix.samples)
            w: int = pix.width
            h: int = pix.height
            stride: int = pix.stride
            fmt: QImage.Format = (
                QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
            )
            image: QImage = QImage(samples, w, h, stride, fmt)
        except Exception:
            image = None
        finally:
            try:
                doc.close()
            except Exception:
                pass

        # If the task was cancelled while rendering, discard the result
        if self._cancelled:
            image = None

        self._callback(self._request, image)


# ── Main renderer class (sioyek PdfRenderer) ─────────────────────────


class PdfBackgroundRenderer(QObject):
    """Background PDF page renderer with LRU cache and thread pool.

    Ported from sioyek's ``PdfRenderer`` (see ``pdf_renderer.h`` / ``.cpp``).

    Key design:

    * Uses ``QThreadPool`` (not raw ``std::thread``) for worker
      management, matching Qt's recommended threading pattern.
    * Each ``_RenderTask`` opens its own ``fitz.Document`` to avoid
      thread-safety issues with PyMuPDF.
    * Cache access is guarded by ``threading.Lock()``.
    * LRU eviction: when the cache exceeds ``max_cache`` entries, the
      entry with the oldest access timestamp is removed.
    * Closest-zoom fallback: if an exact ``(page, zoom)`` match is not
      found, the nearest zoom level for the same page is returned
      (matching sioyek's ``try_closest_rendered_page()``).

    Signals
    -------
    render_ready : Signal(int, int)
        Emitted when a page has finished rendering.
        Arguments: ``page_number``, ``request_id``.

    Usage::

        renderer = PdfBackgroundRenderer(max_cache=10)
        rid = renderer.submit("doc.pdf", 0, zoom=1.0, dpr=2.0)
        renderer.render_ready.connect(on_page_rendered)
        ...
        resp = renderer.find_cached(0, zoom=1.0)
        if resp is not None and resp.image is not None:
            # use resp.image
            pass
    """

    render_ready = Signal(int, int)  # page_num, request_id

    def __init__(self, max_cache: int = 10) -> None:
        """Initialise the background renderer.

        Parameters
        ----------
        max_cache : int
            Maximum number of ``RenderResponse`` entries to keep in the
            LRU cache.  Sioyek's ``NUM_CACHED_PAGES`` defaults to 5; we
            use 10 as a sensible default for modern workstations.
        """
        super().__init__()
        self._max_cache: int = max_cache
        self._lock: threading.Lock = threading.Lock()
        self._request_id_counter: int = 0

        # LRU cache: OrderedDict preserves insertion order.  When an
        # entry is accessed we ``move_to_end()`` it; eviction pops from
        # the front (FIFO = least-recently-used).
        self._cache: OrderedDict[int, RenderResponse] = OrderedDict()

        # Tasks that have been submitted but have not yet completed.
        self._pending: List[_RenderTask] = []

        self._pool: QThreadPool = QThreadPool.globalInstance()

    # ── Public API ─────────────────────────────────────────────────────

    def submit(
        self,
        path: str,
        page: int,
        zoom: float,
        dpr: float = 1.0,
    ) -> int:
        """Submit a page-render request to the background thread pool.

        Behaviour matches sioyek's ``PdfRenderer::add_request()``:

        1. Creates a ``RenderRequest`` with a unique ID.
        2. Cancels any stale (previously-submitted) tasks for the same
           ``(path, page)`` — only the latest request matters (latest
           request wins).
        3. Adds the new task to the pending queue.
        4. Starts the task via ``QThreadPool``.

        Parameters
        ----------
        path : str
            PDF file path.
        page : int
            Zero-based page index.
        zoom : float
            Zoom factor (1.0 = 72 DPI).
        dpr : float
            Device-pixel ratio (default 1.0).  Pass
            ``widget.devicePixelRatio()`` for HiDPI displays.

        Returns
        -------
        int
            The unique ``request_id`` assigned to this request.
        """
        with self._lock:
            self._request_id_counter += 1
            request = RenderRequest(
                path=path,
                page=page,
                zoom=zoom,
                dpr=dpr,
                request_id=self._request_id_counter,
            )

            # Cancel stale tasks for the same (path, page) — only the
            # latest request wins, regardless of zoom level.
            stale: List[_RenderTask] = [
                t
                for t in self._pending
                if t._request.path == path and t._request.page == page
            ]
            for task in stale:
                task.cancel()
            self._pending = [t for t in self._pending if t not in stale]

            task = _RenderTask(request, self._on_render_complete)
            self._pending.append(task)

        self._pool.start(task)
        return request.request_id

    def find_cached(self, page: int, zoom: float) -> Optional[RenderResponse]:
        """Look up a cached render response.

        Behaviour matches sioyek's ``PdfRenderer::find_rendered_page()``:

        1. First, try an exact ``(page, zoom)`` match (zoom within
           1e-6 tolerance).
        2. If no exact match is found, fall back to the closest zoom
           level for the same page *only if the zoom difference is
           within 20 %* (sioyek's ``try_closest_rendered_page()``).

           **Zoom-gate**: a fallback image whose zoom differs by more
           than 20 % is rejected — rendering it would stretch a
           low-resolution pixmap across a much larger display area,
           producing extreme pixelation.  The caller will instead see
           a "rendering..." placeholder until the exact-zoom render
           completes.

        Parameters
        ----------
        page : int
            Zero-based page index.
        zoom : float
            Target zoom level.

        Returns
        -------
        RenderResponse | None
            The cached response if a match (exact or closest-zoom) was
            found, or ``None`` if nothing could be served.  When
            ``None`` is returned, the caller should call ``submit()``
            and wait for the ``render_ready`` signal.
        """
        with self._lock:
            # 1. Exact (page, zoom) match
            for req_id, resp in reversed(self._cache.items()):
                if resp.request.page == page and abs(resp.request.zoom - zoom) < 1e-6:
                    resp.timestamp = time.monotonic_ns()
                    self._cache.move_to_end(req_id)
                    return resp

            # 2. Closest-zoom fallback with zoom-gate
            #    (sioyek try_closest_rendered_page, but limited to
            #     avoid stretching a tiny pixmap across the viewport)
            best_key: Optional[int] = None
            best_resp: Optional[RenderResponse] = None
            best_diff: float = float("inf")

            for req_id, resp in self._cache.items():
                if resp.request.page == page and resp.image is not None:
                    diff: float = abs(resp.request.zoom - zoom)
                    if diff < best_diff:
                        best_diff = diff
                        best_key = req_id
                        best_resp = resp

            # Zoom-gate: reject if the closest zoom differs by >20 %
            if best_resp is not None and best_key is not None:
                MAX_ZOOM_DIFF_RATIO: float = 0.20
                if best_diff / max(zoom, 0.01) > MAX_ZOOM_DIFF_RATIO:
                    return None
                best_resp.timestamp = time.monotonic_ns()
                self._cache.move_to_end(best_key)

            return best_resp

    def cancel_all(self) -> None:
        """Cancel all pending requests and clear the cache.

        Equivalent to sioyek's ``delete_old_pages(true)`` with the
        force-all flag set.

        All queued ``_RenderTask`` instances are marked as cancelled;
        any that have already started rendering will skip storing
        their result.  The LRU cache is emptied.
        """
        with self._lock:
            for task in self._pending:
                task.cancel()
            self._pending.clear()
            self._cache.clear()

    def clear_cache(self) -> None:
        """Clear the LRU cache without cancelling pending requests.

        Equivalent to sioyek's ``delete_old_pages()`` with
        ``force_all=true`` but without affecting the pending queue.

        Render tasks that are already running will still store their
        results in the cache when they complete.
        """
        with self._lock:
            self._cache.clear()

    def is_busy(self) -> bool:
        """Check whether the renderer has pending work.

        Returns
        -------
        bool
            ``True`` if there are queued requests or active pool
            threads.
        """
        with self._lock:
            if self._pending:
                return True
        return self._pool.activeThreadCount() > 0

    def pending_count(self) -> int:
        """Return the number of not-yet-completed render tasks.

        Returns
        -------
        int
            Number of tasks that have been submitted but have not yet
            finished rendering (includes both queued and currently
            running tasks).
        """
        with self._lock:
            return len(self._pending)

    # ── Internal helpers ───────────────────────────────────────────────

    def _on_render_complete(
        self,
        request: RenderRequest,
        image: Optional[QImage],
    ) -> None:
        """Callback invoked by ``_RenderTask`` when rendering finishes.

        Stores the result in the LRU cache (only if rendering
        succeeded), removes the task from the pending list, evicts old
        entries if the cache exceeds capacity, and emits
        ``render_ready``.

        Parameters
        ----------
        request : RenderRequest
            The original request that has finished.
        image : QImage | None
            The rendered image, or ``None`` on failure or cancellation.
        """
        now: int = time.monotonic_ns()

        with self._lock:
            # Remove the task from the pending list.
            self._pending = [
                t
                for t in self._pending
                if t._request.request_id != request.request_id
            ]

            # Only cache successful renders.
            if image is not None:
                response = RenderResponse(
                    request=request,
                    image=image,
                    timestamp=now,
                    pending=False,
                    invalid=False,
                )
                self._cache[request.request_id] = response
                self._evict_lru()

        # Emit the signal *outside* the lock to avoid potential
        # deadlocks if a connected slot calls back into us.
        #
        # Because ``PdfBackgroundRenderer`` is a ``QObject`` created on
        # the main thread, and this callback runs on a pool thread,
        # Qt's auto-connection mechanism delivers the signal as a
        # queued connection (slot executes on the main thread's event
        # loop).
        self.render_ready.emit(request.page, request.request_id)

    def _evict_lru(self) -> None:
        """Evict the oldest entries when the cache exceeds ``_max_cache``.

        Must be called with ``self._lock`` held.  Removes entries with
        the smallest access timestamp until the cache is within the
        capacity limit.  ``OrderedDict`` preserves insertion order —
        ``popitem(last=False)`` removes the first (oldest) entry.
        """
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)

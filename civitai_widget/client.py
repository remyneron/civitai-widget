"""Asynchronous Civitai client built on QNetworkAccessManager (no threads)."""

from __future__ import annotations

import json
import logging
from collections import deque
from functools import partial

from PySide6.QtCore import QIODevice, QObject, QSaveFile, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from civitai_widget import config
from civitai_widget.cache import DiskCache
from civitai_widget.feed import FeedQuery, clean_items, thumbnail_url
from civitai_widget.i18n import tr

log = logging.getLogger(__name__)


class CivitaiClient(QObject):
    feed_loaded = Signal(list, str, bool)   # items, next_cursor, is_stale_cache
    feed_failed = Signal(str)               # human readable message
    image_ready = Signal(str, str)          # image_id, local path
    image_failed = Signal(str)              # image_id

    def __init__(self, cache: DiskCache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self._nam = QNetworkAccessManager(self)
        self._generation = 0
        self._feed_reply: QNetworkReply | None = None
        self._queue: deque[tuple[str, str]] = deque()
        self._queued: set[str] = set()
        self._active: dict[str, QNetworkReply] = {}
        self._attempts: dict[str, int] = {}
        self._closed = False

    # ---- feed -------------------------------------------------------------
    def fetch_feed(self, query: FeedQuery, cursor: str = "", force: bool = False) -> None:
        """Load a batch. Any request still in flight is cancelled and its answer ignored."""
        self._generation += 1
        self._abort_feed()

        if not cursor and not force:
            cached = self.cache.load_feed(query.key())
            if cached and cached[0] and cached[2] < config.FEED_TTL_S:
                items = clean_items(cached[0], query.nsfw)
                if items:
                    self.feed_loaded.emit(items, cached[1], False)
                    return

        url = QUrl(config.API_URL)
        url_query = QUrlQuery()
        for name, value in query.params(cursor).items():
            url_query.addQueryItem(name, QUrl.toPercentEncoding(value).data().decode())
        url.setQuery(url_query)

        reply = self._nam.get(self._request(url))
        self._feed_reply = reply
        reply.finished.connect(partial(self._on_feed_finished, reply, self._generation, query, cursor))

    def _abort_feed(self) -> None:
        reply, self._feed_reply = self._feed_reply, None
        if reply is not None and reply.isRunning():
            reply.abort()

    def _on_feed_finished(self, reply: QNetworkReply, generation: int, query: FeedQuery, cursor: str) -> None:
        reply.deleteLater()
        if generation != self._generation or self._closed:
            return  # superseded by a newer request (e.g. the NSFW switch was flipped back)
        self._feed_reply = None

        error = self._reply_error(reply)
        items: list[dict] = []
        next_cursor = ""
        if error is None:
            try:
                data = json.loads(bytes(reply.readAll().data()))
                items = clean_items(data.get("items"), query.nsfw)
                next_cursor = str((data.get("metadata") or {}).get("nextCursor") or "")
            except (ValueError, AttributeError, TypeError):
                error = tr("err_bad_response")

        if error is None:
            if not cursor:
                self.cache.save_feed(query.key(), items, next_cursor)
            self.feed_loaded.emit(items, next_cursor, False)
            return

        log.warning("Feed request failed: %s", error)
        if not cursor:
            cached = self.cache.load_feed(query.key())
            if cached:
                stale = clean_items(cached[0], query.nsfw)
                if stale:
                    self.feed_loaded.emit(stale, cached[1], True)
                    return
        self.feed_failed.emit(error)

    # ---- thumbnails -------------------------------------------------------
    def cached_image(self, image_id: str) -> str | None:
        """Path of a usable cached thumbnail, or None. Damaged files are removed."""
        if not self.cache.has_image(image_id):
            return None
        path = str(self.cache.image_path(image_id))
        if QImageReader(path).canRead():
            self.cache.touch(image_id)
            return path
        self.cache.drop_image(image_id)
        return None

    def invalidate_image(self, image_id: str) -> None:
        self.cache.drop_image(image_id)

    def request_image(self, image_id: str, url: str, priority: bool = True) -> None:
        if not image_id or not url or self._closed:
            return
        path = self.cached_image(image_id)
        if path:
            self.image_ready.emit(image_id, path)
            return
        if image_id in self._active:
            return
        if image_id in self._queued:
            if priority:  # move to the front of the queue
                self._queue = deque(entry for entry in self._queue if entry[0] != image_id)
                self._queue.appendleft((image_id, url))
            return
        self._attempts[image_id] = 0
        self._enqueue(image_id, url, priority)

    def prefetch(self, items: list[dict]) -> None:
        for item in items:
            self.request_image(str(item.get("id")), item.get("url") or "", priority=False)

    def clear_queue(self) -> None:
        """Forget downloads that have not started yet (the feed has changed)."""
        self._queue.clear()
        self._queued.clear()

    def _enqueue(self, image_id: str, url: str, priority: bool) -> None:
        if image_id in self._queued or image_id in self._active:
            return
        self._queued.add(image_id)
        if priority:
            self._queue.appendleft((image_id, url))
        else:
            self._queue.append((image_id, url))
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._active) < config.MAX_PARALLEL_DOWNLOADS and not self._closed:
            image_id, url = self._queue.popleft()
            self._queued.discard(image_id)
            reply = self._nam.get(self._request(QUrl(thumbnail_url(url))))
            self._active[image_id] = reply
            reply.finished.connect(partial(self._on_image_finished, reply, image_id, url))

    def _on_image_finished(self, reply: QNetworkReply, image_id: str, url: str) -> None:
        reply.deleteLater()
        self._active.pop(image_id, None)
        if self._closed:
            return

        error = self._reply_error(reply)
        if error is None:
            data = reply.readAll()
            if QImage.fromData(data).isNull():
                error = "not an image"
            elif not self._save(image_id, data):
                error = "cannot write cache file"

        if error is None:
            self._attempts.pop(image_id, None)
            self.image_ready.emit(image_id, str(self.cache.image_path(image_id)))
        else:
            attempt = self._attempts.get(image_id, 0) + 1
            self._attempts[image_id] = attempt
            if attempt <= config.MAX_DOWNLOAD_RETRIES:
                log.info("Retrying image %s (%s), attempt %d", image_id, error, attempt)
                QTimer.singleShot(1000 * 2 ** (attempt - 1), self, partial(self._enqueue, image_id, url, False))
            else:
                log.warning("Giving up on image %s: %s", image_id, error)
                self._attempts.pop(image_id, None)
                self.image_failed.emit(image_id)
        self._pump()

    def _save(self, image_id: str, data) -> bool:
        target = QSaveFile(str(self.cache.image_path(image_id)))  # atomic: temp file + rename
        if not target.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        target.write(data)
        return target.commit()

    # ---- helpers ----------------------------------------------------------
    def _request(self, url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", config.USER_AGENT.encode())
        request.setTransferTimeout(config.REQUEST_TIMEOUT_MS)
        return request

    @staticmethod
    def _reply_error(reply: QNetworkReply) -> str | None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if reply.error() == QNetworkReply.NetworkError.NoError and status in (None, 200):
            return None
        if status == 429:
            return tr("err_rate_limited")
        if isinstance(status, int) and status >= 400:
            return tr("err_http", code=status)
        return tr("err_network")

    def shutdown(self) -> None:
        """Cancel everything immediately; nothing here can block the UI on exit."""
        self._closed = True
        self._generation += 1
        self._abort_feed()
        self.clear_queue()
        for reply in list(self._active.values()):
            reply.abort()
        self._active.clear()

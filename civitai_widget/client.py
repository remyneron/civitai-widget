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
from civitai_widget.feed import FeedQuery, clean_items, is_video, poster_url, video_url
from civitai_widget.i18n import tr

log = logging.getLogger(__name__)

Job = tuple[str, str, str]  # kind ("image" | "video"), media id, url


class CivitaiClient(QObject):
    feed_loaded = Signal(list, str, bool)   # items, next_cursor, is_stale_cache
    feed_failed = Signal(str)               # human readable message
    image_ready = Signal(str, str)          # item id, local path of the still picture
    image_failed = Signal(str)
    video_ready = Signal(str, str)          # item id, local path of the MP4
    video_failed = Signal(str)

    def __init__(self, cache: DiskCache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.autoplay_video = True
        self._nam = QNetworkAccessManager(self)
        self._generation = 0
        self._feed_reply: QNetworkReply | None = None
        self._queue: deque[Job] = deque()
        self._queued: set[tuple[str, str]] = set()
        self._active: dict[tuple[str, str], QNetworkReply] = {}
        self._attempts: dict[tuple[str, str], int] = {}
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

        reply = self._nam.get(self._request_for(url))
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

    # ---- media ------------------------------------------------------------
    def cached_image(self, item_id: str) -> str | None:
        """Path of a usable cached still picture, or None. Damaged files are removed."""
        if not self.cache.has_media(item_id, "image"):
            return None
        path = str(self.cache.media_path(item_id, "image"))
        if QImageReader(path).canRead():
            self.cache.touch(item_id, "image")
            return path
        self.cache.drop_media(item_id, "image")
        return None

    def cached_video(self, item_id: str) -> str | None:
        if not self.cache.has_media(item_id, "video"):
            return None
        self.cache.touch(item_id, "video")
        return str(self.cache.media_path(item_id, "video"))

    def invalidate(self, item_id: str, kind: str = "image") -> None:
        self.cache.drop_media(item_id, kind)

    def request_image(self, item: dict, priority: bool = True) -> None:
        """Make sure the still picture of `item` is on disk; answers with image_ready/failed."""
        item_id = str(item.get("id"))
        path = self.cached_image(item_id)
        if path:
            self.image_ready.emit(item_id, path)
        else:
            self._request("image", item_id, poster_url(item), priority)

    def request_video(self, item: dict, priority: bool = True) -> None:
        item_id = str(item.get("id"))
        path = self.cached_video(item_id)
        if path:
            self.video_ready.emit(item_id, path)
        else:
            self._request("video", item_id, video_url(item), priority)

    def prefetch(self, items: list[dict]) -> None:
        """Quietly warm the cache for a page that is about to be shown."""
        for item in items:
            item_id = str(item.get("id"))
            if not self.cached_image(item_id):
                self._request("image", item_id, poster_url(item), False)
            if is_video(item) and self.autoplay_video and not self.cache.has_media(item_id, "video"):
                self._request("video", item_id, video_url(item), False)

    def clear_queue(self) -> None:
        """Forget downloads that have not started yet (the feed has changed)."""
        self._queue.clear()
        self._queued.clear()

    def _request(self, kind: str, item_id: str, url: str, priority: bool) -> None:
        key = (kind, item_id)
        if not item_id or not url or self._closed or key in self._active:
            return
        if key in self._queued:
            if priority:  # move to the front of the queue
                self._queue = deque(job for job in self._queue if (job[0], job[1]) != key)
                self._queue.appendleft((kind, item_id, url))
            return
        self._attempts[key] = 0
        self._enqueue(kind, item_id, url, priority)

    def _enqueue(self, kind: str, item_id: str, url: str, priority: bool) -> None:
        key = (kind, item_id)
        if key in self._queued or key in self._active or self._closed:
            return
        self._queued.add(key)
        if priority:
            self._queue.appendleft((kind, item_id, url))
        else:
            self._queue.append((kind, item_id, url))
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._active) < config.MAX_PARALLEL_DOWNLOADS and not self._closed:
            kind, item_id, url = self._queue.popleft()
            key = (kind, item_id)
            self._queued.discard(key)
            reply = self._nam.get(self._request_for(QUrl(url)))
            self._active[key] = reply
            reply.finished.connect(partial(self._on_media_finished, reply, kind, item_id, url))

    def _on_media_finished(self, reply: QNetworkReply, kind: str, item_id: str, url: str) -> None:
        reply.deleteLater()
        key = (kind, item_id)
        self._active.pop(key, None)
        if self._closed:
            return

        error = self._reply_error(reply)
        if error is None:
            data = reply.readAll()
            if kind == "image" and QImage.fromData(data).isNull():
                error = "not an image"
            elif kind == "video" and data.size() < 1024:
                error = "not a video"
            elif not self._save(kind, item_id, data):
                error = "cannot write cache file"

        ready, failed = (self.image_ready, self.image_failed) if kind == "image" else (self.video_ready, self.video_failed)
        if error is None:
            self._attempts.pop(key, None)
            ready.emit(item_id, str(self.cache.media_path(item_id, kind)))
        else:
            attempt = self._attempts.get(key, 0) + 1
            self._attempts[key] = attempt
            if attempt <= config.MAX_DOWNLOAD_RETRIES:
                log.info("Retrying %s %s (%s), attempt %d", kind, item_id, error, attempt)
                QTimer.singleShot(1000 * 2 ** (attempt - 1), self, partial(self._enqueue, kind, item_id, url, False))
            else:
                log.warning("Giving up on %s %s: %s", kind, item_id, error)
                self._attempts.pop(key, None)
                failed.emit(item_id)
        self._pump()

    def _save(self, kind: str, item_id: str, data) -> bool:
        target = QSaveFile(str(self.cache.media_path(item_id, kind)))  # atomic: temp file + rename
        if not target.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        target.write(data)
        return target.commit()

    # ---- helpers ----------------------------------------------------------
    def _request_for(self, url: QUrl) -> QNetworkRequest:
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

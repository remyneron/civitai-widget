"""A single gallery tile: blurhash placeholder, picture or looping video, hover caption.

Content changes are cross-faded: the previous picture stays in place while the new one,
already downloaded, gently appears on top of it. Mouse presses are deliberately not handled
here: they bubble up to the window, which tells clicks, double clicks and drags apart.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QUrl, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from civitai_widget import blurhash, icons
from civitai_widget.client import CivitaiClient
from civitai_widget.feed import format_count, is_video, reaction_count

try:  # QtMultimedia lives in PySide6-Addons; without it videos stay as still posters
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
except ImportError:  # pragma: no cover - depends on the installation
    QMediaPlayer = QVideoSink = None

log = logging.getLogger(__name__)

RADIUS = 12.0
READY_POLL_MS = 120
READY_TIMEOUT_MS = 2500


def _cover_source(source_w: float, source_h: float, target_w: float, target_h: float) -> QRectF:
    """Largest centred part of the source with the target's aspect ratio (object-fit: cover)."""
    if source_w <= 0 or source_h <= 0 or target_w <= 0 or target_h <= 0:
        return QRectF(0, 0, source_w, source_h)
    scale = max(target_w / source_w, target_h / source_h)
    crop_w, crop_h = target_w / scale, target_h / scale
    return QRectF((source_w - crop_w) / 2, (source_h - crop_h) / 2, crop_w, crop_h)


class ImageCard(QWidget):
    def __init__(self, client: CivitaiClient, parent=None):
        super().__init__(parent)
        self.client = client
        self.item: dict | None = None
        self.image_id = ""

        self._pixmap: QPixmap | None = None
        self._placeholder: QImage | None = None
        self._scaled: QPixmap | None = None
        self._scaled_key = None
        self._frame: QImage | None = None
        self._failed = False
        self._reloaded = False
        self._player = None
        self._sink = None
        self._playing_allowed = True

        self._hover = 0.0
        self._pending: dict | None = None
        self._has_pending = False
        self._waited = 0
        self._fade_ms = 800
        self._old: QPixmap | None = None
        self._blend = 1.0

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(60, 60)

        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self._try_transition)

        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.valueChanged.connect(self._set_blend)
        self._fade.finished.connect(self._on_fade_finished)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)

        client.image_ready.connect(self._on_image_ready)
        client.image_failed.connect(self._on_image_failed)
        client.video_ready.connect(self._on_video_ready)

    # ---- content ----------------------------------------------------------
    def set_item(self, item: dict | None, delay_ms: int = 0, fade_ms: int = 800) -> None:
        """Show `item` (None clears the tile), optionally after a delay and with a cross-fade."""
        new_id = str(item.get("id")) if item else ""
        if not self._has_pending and new_id == self.image_id:
            return
        if self._has_pending and self._pending is not None and str(self._pending.get("id")) == new_id:
            return
        self._pending = item
        self._has_pending = True
        self._fade_ms = fade_ms
        self._waited = 0
        self._delay.stop()
        if item and not self.client.cached_image(new_id):
            self.client.request_image(item)  # start downloading during the delay
        if fade_ms <= 0 or not self.isVisible():
            self._fade.stop()
            self._old = None
            self._blend = 1.0
            self._swap()
        else:
            self._delay.start(max(1, delay_ms))

    def _try_transition(self) -> None:
        """Begin the cross-fade once the new picture is on disk (or we have waited long enough)."""
        item = self._pending
        if item and self._waited < READY_TIMEOUT_MS and not self.client.cached_image(str(item.get("id"))):
            self._waited += READY_POLL_MS
            self._delay.start(READY_POLL_MS)
            return
        self._fade.stop()
        self._old = self._snapshot()
        self._blend = 0.0
        self._swap()
        self._fade.setDuration(self._fade_ms)
        self._fade.start()

    def _snapshot(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        snapshot = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        snapshot.setDevicePixelRatio(dpr)
        snapshot.fill(Qt.GlobalColor.transparent)
        painter = QPainter(snapshot)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._old is not None and self._blend < 1.0:  # interrupted mid-fade: keep what was visible
            painter.drawPixmap(QRectF(self.rect()), self._old, QRectF(self._old.rect()))
            painter.setOpacity(self._blend)
        self._paint_content(painter, QRectF(self.rect()))
        painter.end()
        return snapshot

    def _on_fade_finished(self) -> None:
        self._old = None
        self._blend = 1.0
        self.update()

    def _swap(self) -> None:
        item, self._pending, self._has_pending = self._pending, None, False
        self._stop_video()
        self.item = item
        self.image_id = str(item.get("id")) if item else ""
        self._pixmap = None
        self._scaled = None
        self._placeholder = None
        self._failed = False
        self._reloaded = False
        self.setCursor(Qt.CursorShape.PointingHandCursor if item else Qt.CursorShape.ArrowCursor)
        if item:
            data = blurhash.decode(item.get("hash") or "")
            if data:
                self._placeholder = QImage(data, 20, 20, 60, QImage.Format.Format_RGB888).copy()
            path = self.client.cached_image(self.image_id)
            if not path or not self._load(path):
                self.client.request_image(item)
            self._request_video()
        self.update()

    def _load(self, path: str) -> bool:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        self._pixmap = pixmap
        self._scaled = None
        self._failed = False
        self.update()
        return True

    def _on_image_ready(self, item_id: str, path: str) -> None:
        if item_id != self.image_id or self._pixmap is not None:
            return
        if self._load(path):
            return
        # The cached file cannot be decoded: drop it and download once more.
        self.client.invalidate(item_id, "image")
        if not self._reloaded and self.item:
            self._reloaded = True
            self.client.request_image(self.item)
        else:
            self._failed = True
            self.update()

    def _on_image_failed(self, item_id: str) -> None:
        if item_id == self.image_id and self._pixmap is None:
            self._failed = True
            self.update()

    # ---- video ------------------------------------------------------------
    def _wants_video(self) -> bool:
        return QMediaPlayer is not None and is_video(self.item) and self.client.autoplay_video

    def _request_video(self) -> None:
        if self._wants_video() and self._player is None:
            self.client.request_video(self.item)

    def refresh_video(self) -> None:
        """Re-evaluate playback after the autoplay setting has changed."""
        if self._wants_video():
            self._request_video()
        else:
            self._stop_video()
            self.update()

    def set_playing(self, playing: bool) -> None:
        """Pause decoding while the widget is hidden."""
        self._playing_allowed = playing
        if self._player is not None:
            if playing:
                self._player.play()
            else:
                self._player.pause()

    def _on_video_ready(self, item_id: str, path: str) -> None:
        if item_id != self.image_id or self._player is not None or not self._wants_video():
            return
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player = QMediaPlayer(self)  # no audio output attached: playback is silent
        self._player.setVideoSink(self._sink)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.errorOccurred.connect(self._on_video_error)
        self._player.setSource(QUrl.fromLocalFile(path))
        if self._playing_allowed:
            self._player.play()

    def _on_frame(self, frame) -> None:
        # Frames are delivered through the event queue and may arrive after the player was
        # stopped or the tile moved on to another item; such late frames must be dropped.
        if self._sink is None or self.sender() is not self._sink or not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._frame = image
            self.update()

    def _on_video_error(self, error, message: str = "") -> None:
        log.warning("Video %s cannot be played: %s", self.image_id, message)
        self.client.invalidate(self.image_id, "video")
        self._stop_video()
        self.update()

    def _stop_video(self) -> None:
        player, sink = self._player, self._sink
        self._player = self._sink = None
        self._frame = None
        if player is not None:
            player.stop()
            player.setVideoSink(None)
            player.deleteLater()
        if sink is not None:
            sink.deleteLater()

    # ---- hover ------------------------------------------------------------
    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def _animate_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(float(self._hover))
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def _set_hover(self, value) -> None:
        self._hover = float(value)
        self.update()

    def _set_blend(self, value) -> None:
        self._blend = float(value)
        self.update()

    # ---- painting ---------------------------------------------------------
    def resizeEvent(self, event):
        self._scaled = None
        super().resizeEvent(event)

    def _cover(self) -> QPixmap | None:
        """Thumbnail cropped and scaled to the tile once per size, not on every repaint."""
        if self._pixmap is None:
            return None
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._scaled is None or self._scaled_key != key:
            target_w = max(1, round(self.width() * dpr))
            target_h = max(1, round(self.height() * dpr))
            scaled = self._pixmap.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - target_w) // 2
            y = (scaled.height() - target_h) // 2
            scaled = scaled.copy(x, y, target_w, target_h)
            scaled.setDevicePixelRatio(dpr)
            self._scaled = scaled
            self._scaled_key = key
        return self._scaled

    def _paint_content(self, painter: QPainter, rect: QRectF) -> None:
        cover = self._cover()
        if self._frame is not None:
            source = _cover_source(self._frame.width(), self._frame.height(), rect.width(), rect.height())
            painter.drawImage(rect, self._frame, source)
        elif cover is not None:
            painter.drawPixmap(0, 0, cover)
        elif self._placeholder is not None:
            painter.drawImage(rect, self._placeholder)
        elif self.item:
            painter.fillRect(rect, QColor(255, 255, 255, 14))

        if self._failed:
            painter.fillRect(rect, QColor(0, 0, 0, 90))
            painter.drawPixmap(int(rect.center().x() - 11), int(rect.center().y() - 11), icons.pixmap("alert", "#e2e8f0", 22))
        elif is_video(self.item) and self._frame is None:
            # A still poster of a video: mark it so it is not mistaken for a picture.
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 120))
            painter.drawEllipse(QRectF(rect.right() - 34, rect.top() + 8, 26, 26))
            painter.drawPixmap(int(rect.right() - 28), int(rect.top() + 14), icons.pixmap("play", "#ffffff", 14))
            painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.setClipPath(path)

        if self._old is not None and self._blend < 1.0:
            if self.item:
                painter.drawPixmap(rect, self._old, QRectF(self._old.rect()))
                painter.setOpacity(self._blend)
                self._paint_content(painter, rect)
            else:  # the tile is being cleared: just let the old picture fade away
                painter.setOpacity(1.0 - self._blend)
                painter.drawPixmap(rect, self._old, QRectF(self._old.rect()))
            painter.setOpacity(1.0)
        else:
            self._paint_content(painter, rect)

        if self.item and self._hover > 0.01:
            self._paint_caption(painter, rect)

        if self.item or self._old is not None:
            painter.setClipping(False)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(255, 255, 255, int(18 + 55 * self._hover)))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.end()

    def _paint_caption(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setOpacity(self._hover)
        gradient = QLinearGradient(0, rect.height() * 0.45, 0, rect.height())
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 205))
        painter.fillRect(rect, gradient)

        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        margin = 11
        baseline = int(rect.height() - margin - metrics.descent())

        reactions = "♥ " + format_count(reaction_count(self.item))
        reactions_w = metrics.horizontalAdvance(reactions)
        painter.setPen(QColor("#fda4af"))
        painter.drawText(int(rect.width() - margin - reactions_w), baseline, reactions)

        available = int(rect.width() - 3 * margin - reactions_w)
        if available > 30:
            author = "@" + str(self.item.get("username") or "unknown")
            painter.setPen(QColor("#ffffff"))
            painter.drawText(margin, baseline, metrics.elidedText(author, Qt.TextElideMode.ElideRight, available))
        painter.restore()

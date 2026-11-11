"""A single gallery tile: blurhash placeholder, thumbnail, hover caption, fade transitions.

Mouse presses are deliberately not handled here: they bubble up to the window, which
tells clicks, double clicks and drags apart in one place.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from civitai_widget import blurhash, icons
from civitai_widget.client import CivitaiClient
from civitai_widget.feed import format_count, reaction_count

RADIUS = 12.0


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
        self._failed = False
        self._reloaded = False

        self._opacity = 1.0
        self._hover = 0.0
        self._pending: dict | None = None
        self._has_pending = False
        self._phase: str | None = None
        self._fade_ms = 350

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(60, 60)

        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self._begin_fade_out)

        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self._on_fade_finished)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)

        client.image_ready.connect(self._on_image_ready)
        client.image_failed.connect(self._on_image_failed)

    # ---- content ----------------------------------------------------------
    def set_item(self, item: dict | None, delay_ms: int = 0, fade_ms: int = 350) -> None:
        """Show `item` (or an empty tile for None), optionally after a delay and with a fade."""
        new_id = str(item.get("id")) if item else ""
        if new_id == self.image_id and not self._has_pending:
            return
        self._pending = item
        self._has_pending = True
        self._fade_ms = fade_ms
        self._delay.stop()
        if fade_ms <= 0 or not self.isVisible():
            self._fade.stop()
            self._phase = None
            self._swap()
            self._set_opacity(1.0)
        elif delay_ms > 0:
            self._delay.start(delay_ms)
        else:
            self._begin_fade_out()

    def _begin_fade_out(self) -> None:
        self._fade.stop()
        self._phase = "out"
        self._fade.setDuration(max(1, int(self._fade_ms * self._opacity)))
        self._fade.setStartValue(float(self._opacity))
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._phase == "out":
            self._swap()
            self._phase = "in"
            self._fade.setDuration(self._fade_ms)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._phase = None

    def _swap(self) -> None:
        item, self._pending, self._has_pending = self._pending, None, False
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
                self.client.request_image(self.image_id, item.get("url") or "")
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

    def _on_image_ready(self, image_id: str, path: str) -> None:
        if image_id != self.image_id or self._pixmap is not None:
            return
        if self._load(path):
            return
        # The cached file cannot be decoded: drop it and download once more.
        self.client.invalidate_image(image_id)
        if not self._reloaded and self.item:
            self._reloaded = True
            self.client.request_image(image_id, self.item.get("url") or "")
        else:
            self._failed = True
            self.update()

    def _on_image_failed(self, image_id: str) -> None:
        if image_id == self.image_id and self._pixmap is None:
            self._failed = True
            self.update()

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

    def _set_opacity(self, value) -> None:
        self._opacity = float(value)
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self._opacity)

        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.setClipPath(path)

        cover = self._cover()
        if cover is not None:
            painter.drawPixmap(0, 0, cover)
        elif self._placeholder is not None:
            painter.drawImage(rect, self._placeholder)
        else:
            painter.fillPath(path, QColor(255, 255, 255, 14))

        if self._failed:
            painter.fillPath(path, QColor(0, 0, 0, 90))
            mark = icons.pixmap("alert", "#e2e8f0", 22)
            painter.drawPixmap(int(rect.center().x() - 11), int(rect.center().y() - 11), mark)

        if self.item and self._hover > 0.01:
            self._paint_caption(painter, rect)

        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(255, 255, 255, int(18 + 55 * self._hover)))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.end()

    def _paint_caption(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setOpacity(self._opacity * self._hover)
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

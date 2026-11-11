"""Small custom-painted controls: page dots, progress line, resize-aware stack."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QWidget

from civitai_widget import styles


class PageDots(QWidget):
    """Pagination dots with comfortably large click targets."""

    clicked = Signal(int)

    CELL = 16
    HEIGHT = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._current = 0
        self._hovered = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self.CELL * max(1, self._count), self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, self.HEIGHT)

    def set_count(self, count: int) -> None:
        self._count = max(0, count)
        self._current = min(self._current, max(0, self._count - 1))
        self.setVisible(self._count > 1)
        self.updateGeometry()
        self.update()

    def set_current(self, index: int) -> None:
        self._current = index
        self.update()

    def _cell(self) -> float:
        return min(float(self.CELL), self.width() / max(1, self._count))

    def _index_at(self, x: float) -> int:
        cell = self._cell()
        start = (self.width() - cell * self._count) / 2
        index = int((x - start) // cell)
        return index if 0 <= index < self._count else -1

    def mouseMoveEvent(self, event):
        hovered = self._index_at(event.position().x())
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()

    def leaveEvent(self, event):
        self._hovered = -1
        self.update()

    def mousePressEvent(self, event):
        index = self._index_at(event.position().x())
        if event.button() == Qt.MouseButton.LeftButton and index >= 0:
            self.clicked.emit(index)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()  # do not toggle Zen mode when paging quickly

    def paintEvent(self, event):
        if not self._count:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        cell = self._cell()
        start = (self.width() - cell * self._count) / 2
        middle = self.height() / 2
        dot = min(6.0, cell * 0.55)
        for i in range(self._count):
            center = start + cell * i + cell / 2
            if i == self._current:
                width = min(cell * 0.9, dot * 2.2)
                painter.setBrush(QColor(styles.ACCENT))
                painter.drawRoundedRect(QRectF(center - width / 2, middle - dot / 2, width, dot), dot / 2, dot / 2)
            else:
                painter.setBrush(QColor(255, 255, 255, 120 if i == self._hovered else 46))
                painter.drawEllipse(QRectF(center - dot / 2, middle - dot / 2, dot, dot))
        painter.end()


class ProgressLine(QWidget):
    """Hair-thin countdown to the next page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self.setFixedHeight(2)

    def set_fraction(self, fraction: float) -> None:
        if abs(fraction - self._fraction) > 0.001:
            self._fraction = fraction
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 14))
        painter.drawRect(self.rect())
        painter.setBrush(QColor(styles.ACCENT))
        painter.drawRect(0, 0, int(self.width() * self._fraction), self.height())
        painter.end()


class ResizeAwareStack(QStackedWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

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
    MAX_DOTS = 15
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
        return QSize(self.CELL * max(1, min(self._count, self.MAX_DOTS)), self.HEIGHT)

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

    def _window(self) -> tuple[int, int]:
        """First shown page and number of dots: long feeds get a sliding window of dots."""
        shown = min(self._count, self.MAX_DOTS)
        start = min(max(0, self._current - shown // 2), self._count - shown)
        return start, shown

    def _cell(self) -> float:
        return min(float(self.CELL), self.width() / max(1, self._window()[1]))

    def _index_at(self, x: float) -> int:
        start_index, shown = self._window()
        cell = self._cell()
        left = (self.width() - cell * shown) / 2
        slot = int((x - left) // cell)
        return start_index + slot if 0 <= slot < shown else -1

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
        first, shown = self._window()
        cell = self._cell()
        left = (self.width() - cell * shown) / 2
        middle = self.height() / 2
        base = min(6.0, cell * 0.55)
        for slot in range(shown):
            index = first + slot
            center = left + cell * slot + cell / 2
            dot = base
            # Shrinking edge dots hint that there are more pages in that direction.
            if (slot == 0 and first > 0) or (slot == shown - 1 and index < self._count - 1):
                dot = base * 0.45
            elif (slot == 1 and first > 0) or (slot == shown - 2 and index < self._count - 2):
                dot = base * 0.7
            if index == self._current:
                width = min(cell * 0.9, dot * 2.2)
                painter.setBrush(QColor(styles.ACCENT))
                painter.drawRoundedRect(QRectF(center - width / 2, middle - dot / 2, width, dot), dot / 2, dot / 2)
            else:
                painter.setBrush(QColor(255, 255, 255, 120 if index == self._hovered else 46))
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

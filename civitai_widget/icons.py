"""Small vector icon set, rendered from inline SVG so it does not depend on emoji fonts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).parent / "assets"

_STROKE = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
_FILL = 'fill="{c}" stroke="none"'

_ICONS: dict[str, tuple[str, str]] = {
    "pause": (_FILL, '<rect x="6" y="5" width="4.2" height="14" rx="1.4"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.4"/>'),
    "play": (_FILL, '<path d="M8 5.2a1 1 0 0 1 1.5-.86l11 6.8a1 1 0 0 1 0 1.72l-11 6.8A1 1 0 0 1 8 18.8z"/>'),
    "pin": (_STROKE, '<path d="M12 16v5.5"/><path d="M8.5 3h7l-1 6.2 3.2 3.6a.7.7 0 0 1-.5 1.2H6.800a.7.7 0 0 1-.5-1.2l3.200-3.600z"/>'),
    "menu": (_STROKE, '<path d="M4.500 7h15M4.500 12h15M4.500 17h15"/>'),
    "close": (_STROKE, '<path d="M6.500 6.500l11 11M17.500 6.500l-11 11"/>'),
    "refresh": (_STROKE, '<path d="M20 12a8 8 0 1 1-2.6-5.900"/><path d="M20 4.500V9h-4.500"/>'),
    "expand": (_STROKE, '<path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/>'),
    "alert": (_STROKE, '<path d="M12 4.200l8.300 14.300H3.700z"/><path d="M12 10v4M12 16.700v.100"/>'),
}


@lru_cache(maxsize=64)
def pixmap(name: str, color: str = "#cbd5e1", size: int = 18, dpr: float = 2.0) -> QPixmap:
    attrs, body = _ICONS[name]
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g {attrs.format(c=color)}>{body}</g></svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QPixmap(int(size * dpr), int(size * dpr))
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    result.setDevicePixelRatio(dpr)
    return result


def icon(name: str, color: str = "#cbd5e1", active_color: str | None = None) -> QIcon:
    result = QIcon(pixmap(name, color))
    if active_color:
        result.addPixmap(pixmap(name, active_color), QIcon.Mode.Normal, QIcon.State.On)
    return result


def app_icon() -> QIcon:
    return QIcon(str(ASSETS / "icon.svg"))

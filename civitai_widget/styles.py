"""Colours and Qt style sheets shared by the whole UI."""

ACCENT = "#8b5cf6"
ACCENT_SOFT = "rgba(139, 92, 246, 0.22)"
TEXT = "#e2e8f0"
TEXT_MUTED = "#94a3b8"
DANGER = "#f87171"

FONT_FAMILIES = ["Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"]

WINDOW_QSS = f"""
#MainContainer {{
    background-color: rgba(17, 17, 21, 0.86);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
}}
QLabel#TitleLabel {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
QLabel#SubtitleLabel, QLabel#FooterStatus {{ color: {TEXT_MUTED}; font-size: 11px; }}
QLabel#StatusLabel {{ color: {TEXT_MUTED}; font-size: 12px; }}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px;
}}
QToolButton:hover {{
    background-color: rgba(255, 255, 255, 0.10);
    border-color: rgba(255, 255, 255, 0.10);
}}
QToolButton:pressed {{ background-color: rgba(255, 255, 255, 0.05); }}
QToolButton:checked {{ background-color: {ACCENT_SOFT}; border-color: rgba(139, 92, 246, 0.45); }}
QToolButton::menu-indicator {{ image: none; }}
QToolButton#CloseButton:hover {{
    background-color: rgba(248, 113, 113, 0.18);
    border-color: rgba(248, 113, 113, 0.30);
}}
QToolButton#ZenButton {{
    background-color: rgba(17, 17, 21, 0.72);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 10px;
    padding: 6px;
}}
QToolButton#ZenButton:hover {{ background-color: rgba(60, 60, 70, 0.85); }}
QPushButton#RetryButton {{
    background-color: {ACCENT_SOFT};
    border: 1px solid rgba(139, 92, 246, 0.45);
    border-radius: 8px;
    color: {TEXT};
    font-size: 12px;
    font-weight: 600;
    padding: 6px 16px;
}}
QPushButton#RetryButton:hover {{ background-color: rgba(139, 92, 246, 0.35); }}
QToolTip {{
    background-color: #1c1c22;
    color: {TEXT};
    border: 1px solid rgba(255, 255, 255, 0.12);
    padding: 4px 6px;
}}
"""

MENU_QSS = f"""
QMenu {{
    background-color: #1c1c22;
    color: {TEXT};
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 5px;
    font-size: 12px;
}}
QMenu::item {{ padding: 6px 22px 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: rgba(255, 255, 255, 0.10); }}
QMenu::item:disabled {{ color: #64748b; }}
QMenu::separator {{ height: 1px; background: rgba(255, 255, 255, 0.08); margin: 5px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 6px; }}
QMenu::indicator:checked {{ background-color: {ACCENT}; border-radius: 6px; }}
QMenu::indicator:unchecked {{ background-color: transparent; }}
"""

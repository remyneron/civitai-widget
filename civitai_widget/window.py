"""Main widget window: layout, gestures, menu and wiring between feed, cards and slideshow."""

from __future__ import annotations

import logging
import random

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from civitai_widget import autostart, config, feed, icons, styles
from civitai_widget.cache import DiskCache
from civitai_widget.card import ImageCard
from civitai_widget.client import CivitaiClient
from civitai_widget.config import Settings
from civitai_widget.i18n import tr
from civitai_widget.slideshow import Slideshow
from civitai_widget.widgets import PageDots, ProgressLine, ResizeAwareStack

log = logging.getLogger(__name__)

OUTER_MARGIN = 8     # transparent rim around the glass panel
EDGE_ZONE = 12       # px from the window edge that start a resize
GRID_SPACING = 10
WHEEL_COOLDOWN_MS = 180


class CivitaiWindow(QWidget):
    def __init__(self, settings: Settings | None = None, cache: DiskCache | None = None, tray: bool = True):
        super().__init__()
        self.settings = settings or Settings()
        self.cache = cache or DiskCache()
        self.client = CivitaiClient(self.cache, self)
        self.slideshow = Slideshow(self.settings.get("interval_s") * 1000, self)

        self._all_items: list[dict] = []
        self._items: list[dict] = []
        self._pages: list[list[dict]] = []
        self._page = 0
        self._batch = 1
        self._next_cursor = ""
        self._pending_cursor = ""
        self._model_filter: str | None = None
        self._zen = bool(self.settings.get("zen"))
        self._quitting = False

        self._cards: list[ImageCard] = []
        self._press_pos: QPoint | None = None
        self._press_card: ImageCard | None = None
        self._press_edges = Qt.Edge(0)
        self._manual_drag: QPoint | None = None
        self._wheel_clock = QElapsedTimer()
        self._wheel_clock.start()

        self._init_window()
        self._init_ui()
        self._init_timers()
        self._init_tray(tray)

        self.client.feed_loaded.connect(self._on_feed_loaded)
        self.client.feed_failed.connect(self._on_feed_failed)
        self.slideshow.advance.connect(self._on_advance)
        self.slideshow.progress.connect(self.progress_line.set_fraction)

        self._apply_zen()
        self._update_title()
        QTimer.singleShot(0, self.load)
        QTimer.singleShot(5000, self.cache.cleanup)

    # ---- construction -----------------------------------------------------
    def query(self) -> feed.FeedQuery:
        return feed.FeedQuery(
            nsfw=bool(self.settings.get("nsfw")),
            period=self.settings.get("period"),
            sort=self.settings.get("sort"),
        )

    def _window_flags(self) -> Qt.WindowType:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.settings.get("always_on_top"):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def _init_window(self) -> None:
        self.setWindowTitle(tr("app_name"))
        self.setWindowIcon(icons.app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(self._window_flags())
        self.setMinimumSize(*config.MIN_SIZE)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(self._initial_geometry())

    def _initial_geometry(self) -> QRect:
        saved = self.settings.get("geometry")
        try:
            x, y, w, h = (int(part) for part in str(saved).split(","))
            rect = QRect(x, y, max(w, config.MIN_SIZE[0]), max(h, config.MIN_SIZE[1]))
            for screen in QGuiApplication.screens():
                visible = screen.availableGeometry().intersected(rect)
                if visible.width() >= 80 and visible.height() >= 80:
                    return rect
        except (TypeError, ValueError):
            pass
        area = QGuiApplication.primaryScreen().availableGeometry()
        width = min(config.DEFAULT_SIZE[0], area.width() - 40)
        height = min(config.DEFAULT_SIZE[1], area.height() - 60)
        return QRect(area.right() - width - 24, area.top() + (area.height() - height) // 2, width, height)

    def _tool_button(self, icon_name: str, tooltip: str, slot, checkable: bool = False) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(icons.icon(icon_name, active_color="#c4b5fd" if checkable else None))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        return button

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(OUTER_MARGIN, OUTER_MARGIN, OUTER_MARGIN, OUTER_MARGIN)

        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container.setMouseTracking(True)
        self.setStyleSheet(styles.WINDOW_QSS)
        outer.addWidget(self.container)

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setSpacing(10)

        # Header: what is shown on the left, a few essential controls on the right.
        self.header = QWidget(self.container)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(2, 0, 0, 0)
        header_layout.setSpacing(4)
        self.title_label = QLabel(self.header)
        self.title_label.setObjectName("TitleLabel")
        self.subtitle_label = QLabel(self.header)
        self.subtitle_label.setObjectName("SubtitleLabel")
        self.pause_button = self._tool_button("pause", tr("pause"), self.toggle_pause)
        self.pin_button = self._tool_button("pin", tr("always_on_top"), self.toggle_always_on_top, checkable=True)
        self.pin_button.setChecked(bool(self.settings.get("always_on_top")))
        self.menu_button = self._tool_button("menu", tr("menu"), self._show_button_menu)
        self.close_button = self._tool_button("close", tr("quit"), self.quit)
        self.close_button.setObjectName("CloseButton")
        self.close_button.setIcon(icons.icon("close", styles.DANGER))
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label, 1)
        for button in (self.pause_button, self.pin_button, self.menu_button, self.close_button):
            header_layout.addWidget(button)

        # Content: the gallery and a status page share the same slot.
        self.stack = ResizeAwareStack(self.container)
        self.grid_page = QWidget(self.stack)
        self.grid = QGridLayout(self.grid_page)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GRID_SPACING)
        self.status_page = QWidget(self.stack)
        status_layout = QVBoxLayout(self.status_page)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.setSpacing(14)
        self.status_label = QLabel(tr("loading"), self.status_page)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_button = QPushButton(tr("retry"), self.status_page)
        self.retry_button.setObjectName("RetryButton")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(lambda: self.load(force=True))
        self.retry_button.hide()
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.stack.addWidget(self.grid_page)
        self.stack.addWidget(self.status_page)
        self.stack.setCurrentWidget(self.status_page)
        self.stack.resized.connect(self._schedule_relayout)

        # Footer: countdown, page dots and a quiet status line.
        self.footer = QWidget(self.container)
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        self.progress_line = ProgressLine(self.footer)
        self.dots = PageDots(self.footer)
        self.dots.clicked.connect(lambda index: self.go_to_page(index))
        self.footer_status = QLabel(self.footer)
        self.footer_status.setObjectName("FooterStatus")
        self.footer_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer_status.setWordWrap(True)
        self.footer_status.hide()
        footer_layout.addWidget(self.progress_line)
        footer_layout.addWidget(self.dots)
        footer_layout.addWidget(self.footer_status)

        self.container_layout.addWidget(self.header)
        self.container_layout.addWidget(self.stack, 1)
        self.container_layout.addWidget(self.footer)

        # Floating way out of Zen mode, shown only while the pointer is over the widget.
        self.zen_button = self._tool_button("expand", tr("exit_zen"), lambda: self.set_zen(False))
        self.zen_button.setObjectName("ZenButton")
        self.zen_button.hide()

    def _init_timers(self) -> None:
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(60)
        self._relayout_timer.timeout.connect(self._relayout)

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._open_clicked_item)
        self._clicked_id = ""

        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(800)
        self._geometry_timer.timeout.connect(self._save_geometry)

        self._footer_status_timer = QTimer(self)
        self._footer_status_timer.setSingleShot(True)
        self._footer_status_timer.timeout.connect(lambda: self._set_footer_status(""))

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.AUTO_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start()

        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(config.CACHE_CLEANUP_MS)
        self._cleanup_timer.timeout.connect(self.cache.cleanup)
        self._cleanup_timer.start()

    def _init_tray(self, enabled: bool) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not enabled or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(tr("app_name"))
        menu = QMenu()
        menu.setStyleSheet(styles.MENU_QSS)
        self._tray_toggle = menu.addAction(tr("hide_widget"), self.toggle_visible)
        self._tray_pause = menu.addAction(tr("pause"), self.toggle_pause)
        menu.addSeparator()
        menu.addAction(tr("quit"), self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ---- data -------------------------------------------------------------
    def load(self, cursor: str = "", force: bool = False, silent: bool = False) -> None:
        self._pending_cursor = cursor
        if self._all_items:
            if not silent:
                self._set_footer_status(tr("updating"))
        else:
            self._show_status(tr("loading"), retry=False)
        self.client.fetch_feed(self.query(), cursor=cursor, force=force)

    def refresh(self) -> None:
        self.load(force=True)

    def load_next_batch(self) -> None:
        if self._next_cursor:
            self.load(cursor=self._next_cursor, force=True)
        else:
            self._set_footer_status(tr("no_more"), timeout_ms=6000)

    def _auto_refresh(self) -> None:
        # Only the first batch is "live"; do not yank the user out of a deeper one.
        if self._batch == 1:
            self.load(force=True, silent=True)

    def _on_feed_loaded(self, items: list, next_cursor: str, stale: bool) -> None:
        was_next_batch = bool(self._pending_cursor)
        self._pending_cursor = ""
        if not items:
            if self._all_items and was_next_batch:
                self._set_footer_status(tr("no_more"), timeout_ms=6000)
            else:
                self._all_items, self._items, self._pages = [], [], []
                self.dots.set_count(0)
                self._show_status(tr("empty"), retry=True)
            return

        unchanged = feed.item_ids(items) == feed.item_ids(self._all_items)
        had_items = bool(self._all_items)
        self._all_items = items
        self._next_cursor = next_cursor
        self._batch = self._batch + 1 if was_next_batch else 1
        if not unchanged:
            self.client.clear_queue()
        self._apply_filter(reset_page=not unchanged, mode="fast" if had_items else "instant")
        self._update_title()
        self.stack.setCurrentWidget(self.grid_page)
        self.slideshow.hold("empty", False)
        self._set_footer_status(tr("offline_cache") if stale else "")

    def _on_feed_failed(self, message: str) -> None:
        self._pending_cursor = ""
        if self._all_items:
            self._set_footer_status(message, timeout_ms=12000)
        else:
            self._show_status(message, retry=True)

    def _apply_filter(self, reset_page: bool, mode: str = "fast") -> None:
        if self._model_filter and not feed.filter_by_model(self._all_items, self._model_filter):
            self._model_filter = None
        self._items = feed.filter_by_model(self._all_items, self._model_filter)
        first_index = 0 if reset_page else self._page * max(1, len(self._cards))
        self._ensure_cards()
        self._rebuild_pages(first_index, mode)
        if reset_page:
            self.slideshow.restart()

    def _rebuild_pages(self, first_index: int, mode: str) -> None:
        per_page = max(1, len(self._cards))
        self._pages = feed.paginate(self._items, per_page)
        self.dots.set_count(len(self._pages))
        page = min(first_index // per_page, max(0, len(self._pages) - 1))
        self._show_page(page, mode)

    # ---- pages ------------------------------------------------------------
    def _show_page(self, index: int, mode: str) -> None:
        if not self._pages:
            for card in self._cards:
                card.set_item(None, fade_ms=0)
            return
        index %= len(self._pages)
        self._page = index
        page = self._pages[index]
        order = list(range(len(self._cards)))
        if mode == "cascade":
            random.shuffle(order)
            step, fade = min(450, 1500 // max(1, len(order) - 1)), 350
        elif mode == "fast":
            step, fade = 0, 140
        else:
            step, fade = 0, 0
        for rank, card_index in enumerate(order):
            item = page[card_index] if card_index < len(page) else None
            self._cards[card_index].set_item(item, delay_ms=rank * step, fade_ms=fade)
        self.dots.set_current(index)
        if len(self._pages) > 1:
            self.client.prefetch(self._pages[(index + 1) % len(self._pages)])

    def go_to_page(self, index: int, restart: bool = True) -> None:
        if len(self._pages) < 2:
            return
        self._show_page(index, "fast")
        if restart:
            self.slideshow.restart()

    def next_page(self) -> None:
        self.go_to_page(self._page + 1)

    def prev_page(self) -> None:
        self.go_to_page(self._page - 1)

    def _on_advance(self) -> None:
        if len(self._pages) > 1 and self.stack.currentWidget() is self.grid_page:
            self._show_page(self._page + 1, "cascade")

    # ---- layout -----------------------------------------------------------
    def _rows_for_height(self) -> int:
        width, height = self.stack.width(), self.stack.height()
        column = (width - GRID_SPACING * (config.COLUMNS - 1)) / config.COLUMNS
        card_height = max(60.0, column * config.CARD_ASPECT)
        return max(1, round((height + GRID_SPACING) / (card_height + GRID_SPACING)))

    def _ensure_cards(self) -> bool:
        """Make the number of tiles match the window height. Returns True if it changed."""
        wanted = self._rows_for_height() * config.COLUMNS
        if wanted == len(self._cards):
            return False
        for card in self._cards:
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = []
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 0)
        for index in range(wanted):
            card = ImageCard(self.client, self.grid_page)
            self.grid.addWidget(card, index // config.COLUMNS, index % config.COLUMNS)
            self._cards.append(card)
        for row in range(wanted // config.COLUMNS):
            self.grid.setRowStretch(row, 1)
        return True

    def _schedule_relayout(self) -> None:
        self._relayout_timer.start()

    def _relayout(self) -> None:
        if not self._items:
            return
        first_index = self._page * max(1, len(self._cards))
        if self._ensure_cards():
            self._rebuild_pages(first_index, "instant")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_zen_button()
        self._geometry_timer.start()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._geometry_timer.start()

    def _place_zen_button(self) -> None:
        size = self.zen_button.sizeHint()
        self.zen_button.setGeometry(self.width() - OUTER_MARGIN - size.width() - 12, OUTER_MARGIN + 12, size.width(), size.height())
        self.zen_button.raise_()

    # ---- status -----------------------------------------------------------
    def _show_status(self, text: str, retry: bool) -> None:
        self.status_label.setText(text)
        self.retry_button.setVisible(retry)
        self.stack.setCurrentWidget(self.status_page)
        self._set_footer_status("")
        self.dots.set_count(0)
        self.slideshow.hold("empty", True)

    def _set_footer_status(self, text: str, timeout_ms: int = 0) -> None:
        self._footer_status_timer.stop()
        self.footer_status.setText(text)
        self.footer_status.setVisible(bool(text))
        if text and timeout_ms:
            self._footer_status_timer.start(timeout_ms)

    def _update_title(self) -> None:
        query = self.query()
        self.title_label.setText(tr(f"title_{query.period}"))
        details = []
        if query.sort != config.DEFAULT_SORT:
            details.append(tr(f"sort_{query.sort}").lower())
        if self._model_filter:
            details.append(self._model_filter)
        if self._batch > 1:
            details.append(tr("batch", n=self._batch))
        if query.nsfw:
            details.append("NSFW")
        self.subtitle_label.setText(("· " + " · ".join(details)) if details else "")

    # ---- actions ----------------------------------------------------------
    def toggle_pause(self) -> None:
        paused = not self.slideshow.is_held("user")
        self.slideshow.hold("user", paused)
        self.pause_button.setIcon(icons.icon("play" if paused else "pause"))
        self.pause_button.setToolTip(tr("resume") if paused else tr("pause"))
        if self.tray:
            self._tray_pause.setText(tr("resume") if paused else tr("pause"))

    def toggle_always_on_top(self) -> None:
        enabled = not self.settings.get("always_on_top")
        self.settings.set("always_on_top", enabled)
        self.pin_button.setChecked(enabled)
        geometry = self.geometry()
        was_visible = self.isVisible()
        self.setWindowFlags(self._window_flags())
        self.setGeometry(geometry)
        if was_visible:
            self.show()

    def set_zen(self, enabled: bool) -> None:
        self._zen = enabled
        self.settings.set("zen", enabled)
        self._apply_zen()

    def toggle_zen(self) -> None:
        self.set_zen(not self._zen)

    def _apply_zen(self) -> None:
        self.header.setVisible(not self._zen)
        self.footer.setVisible(not self._zen)
        margin = 6 if self._zen else 14
        self.container_layout.setContentsMargins(margin, margin, margin, margin)
        self.zen_button.setVisible(self._zen and self.underMouse())
        self._place_zen_button()
        self.slideshow.set_progress_visible(not self._zen and self.isVisible())

    def set_interval(self, seconds: int) -> None:
        self.settings.set("interval_s", seconds)
        self.slideshow.set_interval(seconds * 1000)

    def set_period(self, period: str) -> None:
        self.settings.set("period", period)
        self._reload_for_new_query()

    def set_sort(self, sort: str) -> None:
        self.settings.set("sort", sort)
        self._reload_for_new_query()

    def set_model_filter(self, model: str | None) -> None:
        self._model_filter = model
        self._apply_filter(reset_page=True)
        self._update_title()

    def set_nsfw(self, enabled: bool) -> None:
        if enabled and not self._confirm_nsfw():
            return
        self.settings.set("nsfw", enabled)
        self._reload_for_new_query()

    def _confirm_nsfw(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("nsfw_confirm_title"))
        box.setText(tr("nsfw_confirm_title"))
        box.setInformativeText(tr("nsfw_confirm_text"))
        accept = box.addButton(tr("enable"), QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(tr("cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is accept

    def _reload_for_new_query(self) -> None:
        self._model_filter = None
        self._batch = 1
        self._update_title()
        self.load()

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.bring_to_front()

    def bring_to_front(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._save_geometry()
        self.settings.sync()
        self.client.shutdown()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.accept()
        self.quit()

    def _save_geometry(self) -> None:
        g = self.geometry()
        self.settings.set("geometry", f"{g.x()},{g.y()},{g.width()},{g.height()}")

    # ---- menu -------------------------------------------------------------
    def build_menu(self) -> QMenu:
        """One menu for the ☰ button and the right click, so they can never drift apart."""
        menu = QMenu(self)
        menu.setStyleSheet(styles.MENU_QSS)
        paused = self.slideshow.is_held("user")
        menu.addAction((tr("resume") if paused else tr("pause")) + "\tSpace", self.toggle_pause)
        paging = len(self._pages) > 1
        menu.addAction(tr("next_page") + "\t→", self.next_page).setEnabled(paging)
        menu.addAction(tr("prev_page") + "\t←", self.prev_page).setEnabled(paging)
        menu.addSeparator()

        query = self.query()
        self._add_choices(
            menu.addMenu(tr("interval")),
            [(tr("seconds", n=s), s) for s in config.INTERVALS_S],
            self.settings.get("interval_s"),
            self.set_interval,
        )
        self._add_choices(
            menu.addMenu(tr("period")), [(tr(f"period_{p}"), p) for p in config.PERIODS], query.period, self.set_period
        )
        self._add_choices(
            menu.addMenu(tr("sort")), [(tr(f"sort_{s}"), s) for s in config.SORTS], query.sort, self.set_sort
        )
        models = feed.base_models(self._all_items)[:14]
        model_menu = menu.addMenu(tr("base_model"))
        model_menu.setEnabled(bool(models))
        self._add_choices(
            model_menu,
            [(tr("all_models"), None)] + [(f"{name}  ({count})", name) for name, count in models],
            self._model_filter,
            self.set_model_filter,
        )
        menu.addSeparator()

        menu.addAction(tr("next_batch") + "\tN", self.load_next_batch).setEnabled(bool(self._next_cursor))
        menu.addAction(tr("refresh") + "\tR", self.refresh)
        menu.addSeparator()

        self._add_toggle(menu, tr("always_on_top") + "\tP", self.settings.get("always_on_top"), lambda _: self.toggle_always_on_top())
        self._add_toggle(menu, tr("zen") + "\tEsc", self._zen, self.set_zen)
        self._add_toggle(menu, tr("autostart"), autostart.is_enabled(), self._set_autostart)
        self._add_toggle(menu, tr("nsfw"), query.nsfw, self.set_nsfw)
        menu.addSeparator()
        menu.addAction(tr("quit") + "\tCtrl+Q", self.quit)
        return menu

    @staticmethod
    def _add_choices(menu: QMenu, choices, current, callback) -> None:
        menu.setStyleSheet(styles.MENU_QSS)
        group = QActionGroup(menu)
        for label, value in choices:
            action = QAction(label, menu, checkable=True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _checked=False, v=value: callback(v))
            group.addAction(action)
            menu.addAction(action)

    @staticmethod
    def _add_toggle(menu: QMenu, label: str, checked: bool, callback) -> None:
        action = QAction(label, menu, checkable=True)
        action.setChecked(bool(checked))
        action.triggered.connect(callback)
        menu.addAction(action)

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            log.warning("Cannot change autostart: %s", exc)

    def _show_button_menu(self) -> None:
        menu = self.build_menu()
        menu.exec(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height() + 4)))
        menu.deleteLater()

    def contextMenuEvent(self, event):
        menu = self.build_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    # ---- gestures ---------------------------------------------------------
    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if pos.x() <= EDGE_ZONE:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - EDGE_ZONE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE_ZONE:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - EDGE_ZONE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _card_at(self, pos: QPoint) -> ImageCard | None:
        widget = self.childAt(pos)
        while widget is not None and widget is not self:
            if isinstance(widget, ImageCard):
                return widget
            widget = widget.parentWidget()
        return None

    def _update_cursor(self, edges: Qt.Edge) -> None:
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            same_diagonal = edges in (
                Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            )
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if same_diagonal else Qt.CursorShape.SizeBDiagCursor)
        elif horizontal:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif vertical:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        self._press_pos = event.globalPosition().toPoint()
        self._press_edges = self._edges_at(pos)
        self._press_card = None if self._press_edges else self._card_at(pos)
        self._manual_drag = None
        event.accept()

    def mouseMoveEvent(self, event):
        global_pos = event.globalPosition().toPoint()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._update_cursor(self._edges_at(event.position().toPoint()))
            return
        if self._manual_drag is not None:
            self.move(global_pos - self._manual_drag)
            return
        if self._press_pos is None:
            return
        if (global_pos - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        # The gesture is a drag: hand it over to the window manager (works on X11 and Wayland).
        handle = self.windowHandle()
        edges, self._press_pos, self._press_card = self._press_edges, None, None
        if edges:
            if handle:
                handle.startSystemResize(edges)
        elif not (handle and handle.startSystemMove()):
            self._manual_drag = global_pos - self.frameGeometry().topLeft()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        card, pressed = self._press_card, self._press_pos is not None
        self._press_pos, self._press_card, self._manual_drag = None, None, None
        if pressed and card is not None and card.item:
            # A plain click. Wait a moment in case it is the first half of a double click.
            self._clicked_id = card.image_id
            self._click_timer.start(QApplication.doubleClickInterval())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.toggle_zen()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _open_clicked_item(self) -> None:
        if self._clicked_id:
            QDesktopServices.openUrl(QUrl(config.IMAGE_PAGE_URL.format(id=self._clicked_id)))

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta and self._wheel_clock.elapsed() >= WHEEL_COOLDOWN_MS:
            self._wheel_clock.restart()
            if delta < 0:
                self.next_page()
            else:
                self.prev_page()
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Space:
            self.toggle_pause()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.next_page()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.prev_page()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Z):
            self.toggle_zen()
        elif key in (Qt.Key.Key_R, Qt.Key.Key_F5):
            self.refresh()
        elif key == Qt.Key.Key_N:
            self.load_next_batch()
        elif key == Qt.Key.Key_P:
            self.toggle_always_on_top()
        elif key == Qt.Key.Key_Q and ctrl:
            self.quit()
        else:
            return super().keyPressEvent(event)
        event.accept()

    # ---- hover / visibility ----------------------------------------------
    def enterEvent(self, event):
        self.slideshow.hold("hover", True)   # never swap an image under the cursor
        self.zen_button.setVisible(self._zen)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.slideshow.hold("hover", False)
        self.zen_button.hide()
        self.unsetCursor()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.slideshow.hold("hidden", False)
        self.slideshow.set_progress_visible(not self._zen)
        if self.tray:
            self._tray_toggle.setText(tr("hide_widget"))

    def hideEvent(self, event):
        super().hideEvent(event)
        self.slideshow.hold("hidden", True)
        self.slideshow.set_progress_visible(False)
        if self.tray:
            self._tray_toggle.setText(tr("show_widget"))

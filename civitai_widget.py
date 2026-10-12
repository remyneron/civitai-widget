import os
import sys
import math
import random
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Slot
from PySide6.QtGui import QFont, QIcon, QColor, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QStackedWidget, QProgressBar, QFrame, QGraphicsOpacityEffect, QSizePolicy, QMenu
)

# Force XWayland compatibility to enable dragging, positioning, and stays-on-top in GNOME Wayland
os.environ["QT_QPA_PLATFORM"] = "xcb"

# Set path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from civitai_api import CivitaiManager
from image_card import ImageCard

SLIDESHOW_INTERVAL_MS = 15000  # 15 seconds per page
PROGRESS_TICK_MS = 100         # Update progress bar every 100ms

class DraggableFrame(QFrame):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setMouseTracking(True)
        self.resize_mode = None
        self.drag_start_geometry = None
        self.drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            w, h = self.width(), self.height()
            margin = 12
            
            # Check resizing (only if controls are visible)
            if self.main_window.controls_visible:
                if pos.x() >= w - margin and pos.y() >= h - margin:
                    self.resize_mode = "both"
                elif pos.x() >= w - margin:
                    self.resize_mode = "width"
                elif pos.y() >= h - margin:
                    self.resize_mode = "height"
                else:
                    self.resize_mode = None
            else:
                self.resize_mode = None
                
            if self.resize_mode:
                self.drag_start_geometry = self.main_window.geometry()
                self.drag_start_pos = event.globalPosition().toPoint()
                event.accept()
            else:
                # Normal window drag
                self.main_window.drag_position = event.globalPosition().toPoint() - self.main_window.frameGeometry().topLeft()
                event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        w, h = self.width(), self.height()
        margin = 12
        
        # Update cursor shape on hover (when not dragging)
        if event.buttons() == Qt.MouseButton.NoButton:
            if self.main_window.controls_visible:
                if pos.x() >= w - margin and pos.y() >= h - margin:
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif pos.x() >= w - margin:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif pos.y() >= h - margin:
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)
            return

        # Handle resizing or dragging
        if event.buttons() == Qt.MouseButton.LeftButton:
            if self.resize_mode:
                delta = event.globalPosition().toPoint() - self.drag_start_pos
                geom = self.drag_start_geometry
                new_w = max(280, geom.width() + delta.x())
                new_h = max(400, geom.height() + delta.y())
                
                # Limit maximum width to 1/3 of screen
                screen = QApplication.primaryScreen().geometry()
                max_w = screen.width() // 3
                new_w = min(max_w, new_w)
                
                self.main_window.setGeometry(geom.x(), geom.y(), new_w, new_h)
                event.accept()
            elif self.main_window.drag_position is not None:
                # Drag window
                self.main_window.move(event.globalPosition().toPoint() - self.main_window.drag_position)
                event.accept()
            else:
                super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.resize_mode = None
        self.main_window.drag_position = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.main_window.toggle_controls()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class CivitaiWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # Initialize Civitai API Manager
        self.manager = CivitaiManager()
        
        # States
        self.nsfw_enabled = False
        self.always_on_top = False
        self.is_paused = False
        self.controls_visible = True
        self.slideshow_interval_ms = SLIDESHOW_INTERVAL_MS
        self.current_page_idx = 0
        self.next_cursor = ""
        self.items = []
        self.cards = []
        
        # Slideshow timer setup
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_page)
        
        # Progress timer setup (for smooth progress bar animation)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.elapsed_time_ms = 0
        
        # Dragging / Resizing support
        self.drag_position = None
        self.target_page_idx = 0
        
        # Setup Window Properties
        self.setup_window_properties()
        
        # Setup UI
        self.init_ui()
        
        # Connect Manager Signals
        self.manager.metadata_loaded.connect(self.on_metadata_loaded)
        self.manager.load_failed.connect(self.on_load_failed)
        
        # Fetch initial SFW data asynchronously after window is mapped/shown
        QTimer.singleShot(100, self.refresh_data)
        
        # Clean cache older than 1 week (run once on start in background)
        QTimer.singleShot(5000, self.manager.clean_old_cache)

    def setup_window_properties(self):
        # Translucent background setup
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # Frameless window flags
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.Tool
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        
        # Responsive Sizing: Occupies no more than 1/3 of the screen width, Centered vertically
        screen = QApplication.primaryScreen().geometry()
        screen_w = screen.width()
        screen_h = screen.height()
        
        self.widget_width = 360
        self.widget_height = min(880, screen_h - 100)
        
        # Default position: Top right with padding
        x_pos = screen_w - self.widget_width - 30
        y_pos = (screen_h - self.widget_height) // 2
        
        self.setGeometry(x_pos, y_pos, self.widget_width, self.widget_height)
        self.setMinimumSize(280, 400)
        self.setMaximumSize(screen_w // 3, screen_h)
        self.setMouseTracking(True)

    def init_ui(self):
        # Outer layout to support transparent edges
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        
        # Main Glassmorphism container
        self.main_container = DraggableFrame(self, self)
        self.main_container.setObjectName("MainContainer")
        self.main_container.setMouseTracking(True)
        
        # Global stylesheet (minimalist dark glass theme)
        self.main_container.setStyleSheet("""
            #MainContainer {
                background-color: rgba(20, 20, 20, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 6px;
                color: #a0aec0;
                font-family: "Inter", sans-serif;
                font-size: 11px;
                font-weight: 600;
                min-width: 28px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.06);
            }
            QPushButton#CloseBtn {
                color: #e53e3e;
            }
            QPushButton#CloseBtn:hover {
                background-color: rgba(229, 62, 62, 0.15);
                border-color: rgba(229, 62, 62, 0.3);
                color: #fc8181;
            }
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.03);
                border: none;
                border-radius: 0px;
                max-height: 2px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6; /* Blue indicator */
            }
            QLabel.StatusMsg {
                color: #a0aec0;
                font-family: "Inter", sans-serif;
                font-size: 12px;
                background-color: transparent;
            }
        """)
        
        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(12)
        
        # 1. Header Widget
        self.header_widget = QWidget(self.main_container)
        self.header_widget.setObjectName("HeaderWidget")
        self.header_widget.setStyleSheet("background-color: transparent;")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Control Buttons
        self.play_btn = QPushButton("⏸", self.header_widget) # U+23F8
        self.play_btn.setToolTip("Pause/Play Slideshow")
        self.play_btn.clicked.connect(self.toggle_play_pause)
        
        self.speed_up_btn = QPushButton("+", self.header_widget)
        self.speed_up_btn.setToolTip("Scroll Faster (-5s)")
        self.speed_up_btn.clicked.connect(self.speed_up)
        
        self.speed_down_btn = QPushButton("-", self.header_widget)
        self.speed_down_btn.setToolTip("Scroll Slower (+5s)")
        self.speed_down_btn.clicked.connect(self.speed_down)
        
        self.pin_btn = QPushButton("📌", self.header_widget) # U+1F4CC
        self.pin_btn.setToolTip("Always on Top")
        self.pin_btn.clicked.connect(self.toggle_always_on_top)
        self.update_pin_button_style()
        
        self.nsfw_btn = QPushButton("🔞", self.header_widget) # U+1F51E (NSFW Icon)
        self.nsfw_btn.setToolTip("Toggle NSFW Content")
        self.nsfw_btn.clicked.connect(self.toggle_nsfw)
        self.update_nsfw_button_style()
        
        self.next_60_btn = QPushButton("⏭", self.header_widget) # U+23ED (Load next 60 images)
        self.next_60_btn.setToolTip("Load Next 60 Images")
        self.next_60_btn.clicked.connect(self.load_next_60)
        
        self.refresh_btn = QPushButton("↻", self.header_widget) # U+21BB
        self.refresh_btn.setToolTip("Refresh Current Batch")
        self.refresh_btn.clicked.connect(lambda: self.refresh_data(force=True))
        
        close_btn = QPushButton("×", self.header_widget) # U+00D7
        close_btn.setObjectName("CloseBtn")
        close_btn.setToolTip("Exit Widget")
        close_btn.clicked.connect(self.close_application)
        
        header_layout.addStretch() # Push everything to the right
        header_layout.addWidget(self.play_btn)
        header_layout.addWidget(self.speed_up_btn)
        header_layout.addWidget(self.speed_down_btn)
        header_layout.addWidget(self.pin_btn)
        header_layout.addWidget(self.nsfw_btn)
        header_layout.addWidget(self.next_60_btn)
        header_layout.addWidget(self.refresh_btn)
        header_layout.addWidget(close_btn)
        
        # 2. Main content area containing loader / grid / error views
        self.image_grid_widget = QWidget(self.main_container)
        self.image_grid_widget.setObjectName("ImageGridWidget")
        self.image_grid_widget.setStyleSheet("background-color: transparent;")
        
        self.grid_layout = QHBoxLayout(self.image_grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(12)
        
        self.left_col = QVBoxLayout()
        self.left_col.setContentsMargins(0, 0, 0, 0)
        self.left_col.setSpacing(12)
        
        self.right_col = QVBoxLayout()
        self.right_col.setContentsMargins(0, 0, 0, 0)
        self.right_col.setSpacing(12)
        
        self.grid_layout.addLayout(self.left_col, 1)
        self.grid_layout.addLayout(self.right_col, 1)
        
        self.left_col.addStretch()
        self.right_col.addStretch()
        
        # Central Loading / Error container inside container_layout
        self.status_container = QFrame(self.main_container)
        self.status_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_layout = QVBoxLayout(self.status_container)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.status_label = QLabel("Loading Civitai Top 60...", self.status_container)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #a0aec0; font-family: 'Inter', sans-serif; font-size: 12px;")
        
        status_layout.addWidget(self.status_label)
        
        container_layout.addWidget(self.header_widget)
        container_layout.addWidget(self.image_grid_widget, 1)
        container_layout.addWidget(self.status_container, 1)
        
        # Hide grid widget initially while loading
        self.image_grid_widget.hide()
        self.status_container.show()
        
        # 3. Footer Widget
        self.footer_widget = QWidget(self.main_container)
        self.footer_widget.setObjectName("FooterWidget")
        self.footer_widget.setStyleSheet("background-color: transparent;")
        footer_layout = QVBoxLayout(self.footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        
        # Thin Progress Bar
        self.progress_bar = QProgressBar(self.footer_widget)
        self.progress_bar.setRange(0, self.slideshow_interval_ms)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        
        # Page Indicator Dots Layout
        self.dots_layout = QHBoxLayout()
        self.dots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dots_layout.setSpacing(6)
        
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addLayout(self.dots_layout)
        container_layout.addWidget(self.footer_widget)
        
        outer_layout.addWidget(self.main_container)

    def contextMenuEvent(self, event):
        """
        Right-click desktop context menu for extremely minimalist controls
        """
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a1a;
                color: #a0aec0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
        """)
        
        toggle_controls_action = menu.addAction("Show Controls" if not self.controls_visible else "Hide Controls")
        menu.addSeparator()
        
        nsfw_text = "🔞 Disable NSFW" if self.nsfw_enabled else "🔞 Enable NSFW"
        nsfw_action = menu.addAction(nsfw_text)
        
        pin_text = "📌 Disable Always on Top" if self.always_on_top else "📌 Always on Top"
        pin_action = menu.addAction(pin_text)
        
        menu.addSeparator()
        faster_action = menu.addAction(f"➕ Faster (Current: {self.slideshow_interval_ms//1000}s)")
        slower_action = menu.addAction(f"➖ Slower (Current: {self.slideshow_interval_ms//1000}s)")
        
        menu.addSeparator()
        next_60_action = menu.addAction("⏭ Load Next 60 Images")
        refresh_action = menu.addAction("↻ Refresh Current Batch")
        exit_action = menu.addAction("× Exit Widget")
        
        action = menu.exec(event.globalPos())
        if action == toggle_controls_action:
            self.toggle_controls()
        elif action == nsfw_action:
            self.toggle_nsfw()
        elif action == pin_action:
            self.toggle_always_on_top()
        elif action == faster_action:
            self.speed_up()
        elif action == slower_action:
            self.speed_down()
        elif action == next_60_action:
            self.load_next_60()
        elif action == refresh_action:
            self.refresh_data(force=True)
        elif action == exit_action:
            self.close_application()

    def mouseDoubleClickEvent(self, event):
        """
        Double-clicking background toggles the controls interface
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_controls()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def toggle_controls(self, visible=None):
        """
        Hides or shows the header controls and footer bar
        """
        if visible is not None:
            self.controls_visible = visible
        else:
            self.controls_visible = not self.controls_visible
            
        self.header_widget.setVisible(self.controls_visible)
        self.footer_widget.setVisible(self.controls_visible)
        
        # Trim margins to maximize display when controls are hidden
        if self.controls_visible:
            self.main_container.layout().setContentsMargins(15, 15, 15, 15)
        else:
            self.main_container.layout().setContentsMargins(5, 5, 5, 5)
            
        self.recalculate_card_heights()

    def recalculate_card_heights(self):
        """
        Calculates card heights dynamically to create a uniform grid layout.
        All cards have the exact same height, based on the column width,
        to keep the columns aligned and prevent empty gaps.
        """
        if not self.cards:
            return
            
        # Calculate available width for each of the 2 columns
        margin_overhead = 30 if self.controls_visible else 10
        available_width = self.width() - margin_overhead - 12  # 12px column spacing
        column_width = max(100, available_width // 2)
        card_height = int(column_width * 1.35)  # 3:4 aspect ratio for uniform grid
        
        for card in self.cards:
            card.setFixedHeight(card_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recalculate_card_heights()

    def refresh_data(self, force=False):
        """
        Triggers data refresh from CivitaiManager (loads first page)
        """
        print("[DEBUG] refresh_data called, force:", force)
        self.stop_timers()
        self.status_label.setText("Fetching trending images...")
        self.image_grid_widget.hide()
        self.status_container.show()
        self.update()
        self.next_cursor = "" # Reset cursor
        self.manager.fetch_top_images(nsfw=self.nsfw_enabled, force_refresh=force)

    def load_next_60(self):
        """
        Fetches the next 60 images based on the pagination cursor
        """
        self.stop_timers()
        self.status_label.setText("Fetching next batch of images...")
        self.image_grid_widget.hide()
        self.status_container.show()
        self.update()
        self.manager.fetch_top_images(nsfw=self.nsfw_enabled, force_refresh=True, cursor=self.next_cursor)

    def on_load_failed(self, error_msg):
        print("[DEBUG] on_load_failed called, error:", error_msg)
        self.status_label.setText(f"Failed to load images:\n{error_msg}\n\nClick ↻ to retry.")

    def on_metadata_loaded(self, items, next_cursor=""):
        """
        Callback when API metadata is loaded.
        """
        print("[DEBUG] on_metadata_loaded called, items:", len(items), "next_cursor:", next_cursor)
        self.items = items
        self.next_cursor = next_cursor
        
        if not items:
            self.status_label.setText("No images found.\nClick ↻ to retry.")
            return

        # Instantiate cards if they don't exist yet
        if not self.cards:
            for i in range(6):
                item = self.items[i] if i < len(self.items) else {}
                card = ImageCard(item, self.manager, self.image_grid_widget)
                self.cards.append(card)
                if i % 2 == 0:
                    self.left_col.insertWidget(self.left_col.count() - 1, card)
                else:
                    self.right_col.insertWidget(self.right_col.count() - 1, card)
        else:
            # If cards already exist, swap them immediately to the first page's images
            cards_per_page = 6
            page_items = self.items[0 : cards_per_page]
            for i, card in enumerate(self.cards):
                if i < len(page_items):
                    card.transition_to_item(page_items[i], 0)

        # Show Grid widget, hide status loader
        print("[DEBUG] Showing image_grid_widget and hiding status_container")
        self.status_container.hide()
        self.image_grid_widget.show()
        self.update()

        # Recalculate heights based on current sizes
        self.recalculate_card_heights()
        
        # Re-build page indicator dots (60 images total / 6 per page = 10 pages)
        cards_per_page = 6
        num_pages = math.ceil(len(self.items) / cards_per_page)
        self.setup_page_dots(num_pages)
        
        # Set page index and restart slideshow
        self.current_page_idx = 0
        self.update_dots_state()
        
        # Start slideshow timers
        self.reset_and_start_timers()
        print("[DEBUG] on_metadata_loaded finished")

    def setup_page_dots(self, count):
        while self.dots_layout.count() > 0:
            item = self.dots_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        for i in range(count):
            dot = QPushButton(self.main_container)
            dot.setProperty("class", "PageDot")
            dot.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            dot.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.15);
                    border: none;
                    border-radius: 3px;
                    min-width: 6px;
                    max-width: 6px;
                    min-height: 6px;
                    max-height: 6px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.4);
                }
            """)
            dot.clicked.connect(lambda _, idx=i: self.fade_to_page(idx))
            self.dots_layout.addWidget(dot)

    def update_dots_state(self):
        for i in range(self.dots_layout.count()):
            dot = self.dots_layout.itemAt(i).widget()
            if dot:
                if i == self.current_page_idx:
                    dot.setStyleSheet("""
                        QPushButton {
                            background-color: #3b82f6;
                            border: none;
                            border-radius: 3px;
                            min-width: 8px;
                            max-width: 8px;
                            min-height: 6px;
                            max-height: 6px;
                        }
                    """)
                else:
                    dot.setStyleSheet("""
                        QPushButton {
                            background-color: rgba(255, 255, 255, 0.15);
                            border: none;
                            border-radius: 3px;
                            min-width: 6px;
                            max-width: 6px;
                            min-height: 6px;
                            max-height: 6px;
                        }
                        QPushButton:hover {
                            background-color: rgba(255, 255, 255, 0.4);
                        }
                    """)

    def next_page(self):
        num_pages = math.ceil(len(self.items) / 6)
        if num_pages <= 1:
            return
        # Choose a random page index different from the current one to avoid showing the same page twice
        candidates = [i for i in range(num_pages) if i != self.current_page_idx]
        next_idx = random.choice(candidates) if candidates else 0
        self.fade_to_page(next_idx)

    def fade_to_page(self, index):
        """
        Executes a staggered individual card transition to switch pages.
        """
        print("[DEBUG] fade_to_page called, target index:", index, "current:", self.current_page_idx)
        cards_per_page = 6
        num_pages = math.ceil(len(self.items) / cards_per_page)
        if num_pages <= 1:
            return
            
        self.timer.stop()
        self.progress_timer.stop()
        self.target_page_idx = index
        
        page_items = self.items[index * cards_per_page : (index + 1) * cards_per_page]
        
        # Stop any existing transition completed timer
        if hasattr(self, "_completion_timer") and self._completion_timer:
            try:
                self._completion_timer.stop()
                self._completion_timer.deleteLater()
            except Exception:
                pass
            self._completion_timer = None
            
        # Transition cards with randomized staggered delays
        indices = list(range(len(self.cards)))
        random.shuffle(indices)
        
        for delay_order, card_idx in enumerate(indices):
            if card_idx < len(page_items):
                card = self.cards[card_idx]
                card.transition_to_item(page_items[card_idx], delay_order * 600)
                
        # Card 5 starts transition at 3000ms, takes 500ms to fade out, updates, takes 500ms to fade in (total 4000ms).
        # We schedule a timer to reset and restart slideshow timers at 4100ms.
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.timeout.connect(self._on_transition_completed)
        self._completion_timer.start(4100)

    def _on_transition_completed(self):
        self._completion_timer = None
        self.current_page_idx = self.target_page_idx
        self.update_dots_state()
        self.reset_and_start_timers()
        self.update()

    def reset_and_start_timers(self):
        self.elapsed_time_ms = 0
        self.progress_bar.setValue(0)
        
        if not self.is_paused:
            self.timer.start(self.slideshow_interval_ms)
            self.progress_timer.start(PROGRESS_TICK_MS)
        else:
            self.progress_timer.stop()
            self.timer.stop()

    def stop_timers(self):
        self.timer.stop()
        self.progress_timer.stop()
        self.progress_bar.setValue(0)
        self.elapsed_time_ms = 0

    def update_progress(self):
        if self.is_paused:
            return
            
        self.elapsed_time_ms += PROGRESS_TICK_MS
        self.progress_bar.setValue(self.elapsed_time_ms)
        
        if self.elapsed_time_ms >= self.slideshow_interval_ms:
            self.progress_timer.stop()

    def speed_up(self):
        """
        Scroll faster (decrease timer interval by 5 seconds).
        Minimum interval is 5 seconds.
        """
        self.slideshow_interval_ms = max(5000, self.slideshow_interval_ms - 5000)
        self.progress_bar.setRange(0, self.slideshow_interval_ms)
        self.reset_and_start_timers()
        self.show_speed_tooltip()

    def speed_down(self):
        """
        Scroll slower (increase timer interval by 5 seconds).
        Maximum interval is 120 seconds.
        """
        self.slideshow_interval_ms = min(120000, self.slideshow_interval_ms + 5000)
        self.progress_bar.setRange(0, self.slideshow_interval_ms)
        self.reset_and_start_timers()
        self.show_speed_tooltip()

    def show_speed_tooltip(self):
        seconds = self.slideshow_interval_ms // 1000
        self.speed_up_btn.setToolTip(f"Scroll Faster (Current: {seconds}s)")
        self.speed_down_btn.setToolTip(f"Scroll Slower (Current: {seconds}s)")

    # Toolbar Toggle Actions
    def toggle_play_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.play_btn.setText("▶")
            self.stop_timers()
        else:
            self.play_btn.setText("⏸")
            self.reset_and_start_timers()
        self.update_button_active_property(self.play_btn, self.is_paused)

    def toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top
        
        # Save geometry to avoid window shifting
        geom = self.geometry()
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.Tool
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
            
        self.setWindowFlags(flags)
        self.setGeometry(geom)
        self.show()
        self.update_pin_button_style()

    def toggle_nsfw(self):
        self.nsfw_enabled = not self.nsfw_enabled
        self.update_nsfw_button_style()
        self.refresh_data()

    def update_pin_button_style(self):
        self.update_button_active_property(self.pin_btn, self.always_on_top)
        if self.always_on_top:
            self.pin_btn.setStyleSheet("QPushButton { color: #3b82f6; border-color: rgba(59, 130, 246, 0.4); background-color: rgba(59, 130, 246, 0.15); }")
        else:
            self.pin_btn.setStyleSheet("")

    def update_nsfw_button_style(self):
        self.update_button_active_property(self.nsfw_btn, self.nsfw_enabled)
        if self.nsfw_enabled:
            self.nsfw_btn.setStyleSheet("QPushButton { color: #f43f5e; border-color: rgba(244, 63, 94, 0.4); background-color: rgba(244, 63, 94, 0.15); }")
        else:
            self.nsfw_btn.setStyleSheet("")

    def update_button_active_property(self, button, active):
        button.setProperty("active", "true" if active else "false")
        button.style().unpolish(button)
        button.style().polish(button)

    def close_application(self):
        self.stop_timers()
        self.manager.stop_worker()
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        self.close_application()
        event.accept()

def main():
    app = QApplication(sys.argv)
    widget = CivitaiWidget()
    widget.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

import os
from PySide6.QtCore import Qt, QRect, QUrl, QPropertyAnimation, QEasingCurve, QTimer, Property
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QFont, QDesktopServices, QCursor
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect

class ImageCard(QWidget):
    def __init__(self, item, manager, parent=None):
        super().__init__(parent)
        self.item = item
        self.image_id = str(item.get("id"))
        self.image_url = item.get("url")
        self.username = item.get("username", "Unknown")
        self.manager = manager
        
        # Calculate reactions count
        stats = item.get("stats", {})
        likes = stats.get("likeCount", 0)
        hearts = stats.get("heartCount", 0)
        laughs = stats.get("laughCount", 0)
        cries = stats.get("cryCount", 0)
        self.reaction_count = likes + hearts + laughs + cries
        
        # UI State
        self.pixmap = None
        self.loading = True
        self.hovered = False
        self._card_opacity = 1.0
        
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setObjectName("ImageCard")
        self.setMinimumHeight(150)
        
        # Overlay Widget for hover details
        self.overlay = QFrame(self)
        self.overlay.setObjectName("Overlay")
        self.overlay.setStyleSheet("""
            #Overlay {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 0, 0, 0.0),
                    stop:0.5 rgba(0, 0, 0, 0.3),
                    stop:1 rgba(0, 0, 0, 0.8)
                );
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
        """)
        
        # Overlay Layout
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(15, 15, 15, 15)
        overlay_layout.addStretch()
        
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)
        
        self.author_label = QLabel(f"@{self.username}", self.overlay)
        self.author_label.setFont(QFont("Inter", 10, QFont.Weight.Medium))
        
        self.reactions_label = QLabel(f"❤️ {self.reaction_count}", self.overlay)
        self.reactions_label.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.reactions_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        info_layout.addWidget(self.author_label, 1)
        info_layout.addWidget(self.reactions_label, 0)
        overlay_layout.addLayout(info_layout)
        
        # Opacity effect for fade transition
        self.opacity_effect = QGraphicsOpacityEffect(self.overlay)
        self.overlay.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)
        
        # Queue image download
        self.manager.image_ready.connect(self._on_image_ready)
        if self.image_url:
            self.manager.queue_image_download(self.image_id, self.image_url)
        
        # Animation
        self.hover_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.hover_anim.setDuration(250)
        self.hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_card_opacity(self):
        return self._card_opacity

    def set_card_opacity(self, opacity):
        self._card_opacity = opacity
        self.update()

    card_opacity = Property(float, get_card_opacity, set_card_opacity)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep overlay sized to match the card
        self.overlay.setGeometry(self.rect())

    def enterEvent(self, event):
        self.hovered = True
        if hasattr(self, "fade_anim") and self.fade_anim:
            self.update()
            return
        self.hover_anim.stop()
        self.hover_anim.setStartValue(self.opacity_effect.opacity())
        self.hover_anim.setEndValue(0.95)
        self.hover_anim.start()
        self.update() # Triggers repaint for border outline

    def leaveEvent(self, event):
        self.hovered = False
        if hasattr(self, "fade_anim") and self.fade_anim:
            self.update()
            return
        self.hover_anim.stop()
        self.hover_anim.setStartValue(self.opacity_effect.opacity())
        self.hover_anim.setEndValue(0.0)
        self.hover_anim.start()
        self.update() # Triggers repaint for border outline

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Open the post URL on Civitai
            civitai_url = f"https://civitai.com/images/{self.image_id}"
            QDesktopServices.openUrl(QUrl(civitai_url))
            event.accept()
        else:
            super().mousePressEvent(event)

    def _on_image_ready(self, image_id, filepath):
        if image_id == self.image_id:
            # Load the image in a pixmap
            pixmap = QPixmap()
            if pixmap.load(filepath):
                self.pixmap = pixmap
                self.loading = False
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(self._card_opacity)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        rect = self.rect()
        radius = 12.0
        
        # 1. Draw Background / Placeholder (Pulsing style look but static for low energy)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        
        if self.loading or not self.pixmap:
            # Draw loader background
            painter.fillPath(path, QColor(30, 30, 30, 100))
            
            # Draw Loading Text
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont("Inter", 10))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Loading...")
        else:
            # 2. Draw image with AspectRatio-crop (object-fit: cover)
            painter.setClipPath(path)
            
            pm_w = self.pixmap.width()
            pm_h = self.pixmap.height()
            target_w = rect.width()
            target_h = rect.height()
            
            pm_ratio = pm_w / pm_h
            target_ratio = target_w / target_h
            
            if pm_ratio > target_ratio:
                crop_w = int(pm_h * target_ratio)
                crop_h = pm_h
                x = (pm_w - crop_w) // 2
                y = 0
            else:
                crop_w = pm_w
                crop_h = int(pm_w / target_ratio)
                x = 0
                y = (pm_h - crop_h) // 2
                
            source_rect = QRect(x, y, crop_w, crop_h)
            painter.drawPixmap(rect, self.pixmap, source_rect)
            
        # 3. Draw border highlight on hover
        painter.setClipping(False) # Stop clipping
        if self.hovered:
            painter.setPen(QColor(255, 255, 255, 60)) # subtle light border
        else:
            painter.setPen(QColor(255, 255, 255, 15)) # very dark/translucent border
        
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), radius, radius)
        painter.end()

    def transition_to_item(self, new_item, delay_ms):
        # Cancel any pending transition timer
        if hasattr(self, "_transition_timer") and self._transition_timer:
            try:
                self._transition_timer.stop()
                self._transition_timer.deleteLater()
            except Exception:
                pass
            self._transition_timer = None
            
        self._pending_item = new_item
        
        if delay_ms == 0:
            self._start_fade_out()
        else:
            self._transition_timer = QTimer(self)
            self._transition_timer.setSingleShot(True)
            self._transition_timer.timeout.connect(self._start_fade_out)
            self._transition_timer.start(delay_ms)
            
    def _start_fade_out(self):
        self._transition_timer = None
        
        # Stop hover animation and hide overlay
        self.hovered = False
        if hasattr(self, "hover_anim") and self.hover_anim:
            self.hover_anim.stop()
        self.opacity_effect.setOpacity(0.0)
        
        # Stop any active fade animation
        if hasattr(self, "fade_anim") and self.fade_anim:
            try:
                self.fade_anim.stop()
                self.fade_anim.finished.disconnect()
            except Exception:
                pass
                
        # Animation setup
        self.fade_anim = QPropertyAnimation(self, b"card_opacity")
        self.fade_anim.setDuration(500)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_anim.finished.connect(self._on_fade_out_completed)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()
        
    def _on_fade_out_completed(self):
        if hasattr(self, "fade_anim") and self.fade_anim:
            try:
                self.fade_anim.finished.disconnect()
            except Exception:
                pass
                
        # Swap metadata
        self.item = self._pending_item
        self.image_id = str(self.item.get("id"))
        self.image_url = self.item.get("url")
        self.username = self.item.get("username", "Unknown")
        
        # Recalculate stats
        stats = self.item.get("stats", {})
        likes = stats.get("likeCount", 0)
        hearts = stats.get("heartCount", 0)
        laughs = stats.get("laughCount", 0)
        cries = stats.get("cryCount", 0)
        self.reaction_count = likes + hearts + laughs + cries
        
        # Update text labels
        self.author_label.setText(f"@{self.username}")
        self.reactions_label.setText(f"❤️ {self.reaction_count}")
        
        # Clean up old connection to avoid double triggers
        try:
            self.manager.image_ready.disconnect(self._on_image_ready)
        except Exception:
            pass
            
        # Register new connection
        self.manager.image_ready.connect(self._on_image_ready)
        
        # Check cache / queue download
        if self.image_url:
            local_path = os.path.join(self.manager.cache_dir, f"{self.image_id}_450.jpg")
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                pixmap = QPixmap()
                if pixmap.load(local_path):
                    self.pixmap = pixmap
                    self.loading = False
                else:
                    self.pixmap = None
                    self.loading = True
                    self.manager.queue_image_download(self.image_id, self.image_url)
            else:
                self.pixmap = None
                self.loading = True
                self.manager.queue_image_download(self.image_id, self.image_url)
        else:
            self.pixmap = None
            self.loading = False
            
        self.update()
        
        # Play fade in
        self.fade_anim = QPropertyAnimation(self, b"card_opacity")
        self.fade_anim.setDuration(500)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_anim.finished.connect(self._on_fade_in_completed)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()
        
    def _on_fade_in_completed(self):
        if hasattr(self, "fade_anim") and self.fade_anim:
            try:
                self.fade_anim.finished.disconnect()
            except Exception:
                pass
                
        self.fade_anim = None

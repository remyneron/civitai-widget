"""Slideshow clock: a pausable countdown that knows how much time is left."""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

PROGRESS_TICK_MS = 250


class Slideshow(QObject):
    """Emits `advance` every `interval`; can be held for several independent reasons.

    Holding (user pause, mouse hover, hidden window, loading) freezes the countdown
    instead of resetting it, so resuming continues from the same point.
    """

    advance = Signal()
    progress = Signal(float)        # 0..1 share of the interval that has elapsed
    running_changed = Signal(bool)

    def __init__(self, interval_ms: int, parent=None):
        super().__init__(parent)
        self._interval = max(1000, int(interval_ms))
        self._remaining = self._interval
        self._holds: set[str] = set()
        self._progress_visible = True
        self._clock = QElapsedTimer()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

        self._tick = QTimer(self)
        self._tick.setInterval(PROGRESS_TICK_MS)
        self._tick.timeout.connect(self._emit_progress)

    # ---- public API -------------------------------------------------------
    @property
    def interval_ms(self) -> int:
        return self._interval

    def is_running(self) -> bool:
        return self._timer.isActive()

    def is_held(self, reason: str) -> bool:
        return reason in self._holds

    def set_interval(self, interval_ms: int) -> None:
        self._interval = max(1000, int(interval_ms))
        self.restart()

    def restart(self) -> None:
        """Start a full interval from scratch (after a manual page change, new data…)."""
        self._timer.stop()
        self._remaining = self._interval
        self._apply()

    def hold(self, reason: str, on: bool) -> None:
        if (reason in self._holds) == on:
            return
        self._freeze()
        if on:
            self._holds.add(reason)
        else:
            self._holds.discard(reason)
        self._apply()

    def set_progress_visible(self, visible: bool) -> None:
        """Progress ticks are only produced while something is there to draw them."""
        self._progress_visible = visible
        if visible and self._timer.isActive():
            self._tick.start()
            self._emit_progress()
        else:
            self._tick.stop()

    def fraction(self) -> float:
        elapsed = self._interval - self._remaining
        if self._timer.isActive():
            elapsed += self._clock.elapsed()
        return min(1.0, max(0.0, elapsed / self._interval))

    # ---- internals --------------------------------------------------------
    def _freeze(self) -> None:
        if self._timer.isActive():
            self._remaining = max(0, self._remaining - self._clock.elapsed())
            self._timer.stop()
        self._tick.stop()

    def _apply(self) -> None:
        was_running = self._timer.isActive()
        if self._holds:
            self._timer.stop()
            self._tick.stop()
        else:
            self._clock.start()
            self._timer.start(max(1, self._remaining))
            if self._progress_visible:
                self._tick.start()
        self._emit_progress()
        if was_running != self._timer.isActive():
            self.running_changed.emit(self._timer.isActive())

    def _fire(self) -> None:
        self._remaining = self._interval
        self.advance.emit()
        if not self._timer.isActive():  # a slot may already have restarted us
            self._apply()

    def _emit_progress(self) -> None:
        self.progress.emit(self.fraction())

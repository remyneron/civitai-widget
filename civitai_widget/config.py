"""Constants, XDG paths and persistent settings."""

from __future__ import annotations

import os
from pathlib import Path

APP_ID = "civitai-widget"
USER_AGENT = "civitai-widget/2.0"

API_URL = "https://civitai.com/api/v1/images"
IMAGE_PAGE_URL = "https://civitai.com/images/{id}"

FEED_LIMIT = 100                # items requested per API call
FEED_TTL_S = 3600               # cached feed is considered fresh for an hour
AUTO_REFRESH_MS = 3600 * 1000   # background refresh of the first batch
REQUEST_TIMEOUT_MS = 15000

THUMB_WIDTH = 450
MAX_PARALLEL_DOWNLOADS = 4
MAX_DOWNLOAD_RETRIES = 2

CACHE_MAX_AGE_S = 7 * 86400
CACHE_MAX_BYTES = 300 * 1024 * 1024
CACHE_CLEANUP_MS = 6 * 3600 * 1000

INTERVALS_S = (5, 10, 15, 30, 60, 120)
DEFAULT_INTERVAL_S = 15

PERIODS = ("Day", "Week", "Month", "Year", "AllTime")
DEFAULT_PERIOD = "Week"
SORTS = ("Most Reactions", "Most Comments", "Most Collected", "Newest")
DEFAULT_SORT = "Most Reactions"

COLUMNS = 2
CARD_ASPECT = 1.4               # preferred height / width of a card
DEFAULT_SIZE = (360, 880)
MIN_SIZE = (240, 260)


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "")
    return Path(value) if os.path.isabs(value) else Path.home() / fallback


def cache_dir() -> Path:
    # Directory name is kept from v1 so the existing thumbnail cache is reused.
    return _xdg("XDG_CACHE_HOME", ".cache") / "civitai_widget"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP_ID


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


class Settings:
    """Typed wrapper around QSettings (~/.config/civitai-widget/civitai-widget.conf)."""

    DEFAULTS = {
        "interval_s": DEFAULT_INTERVAL_S,
        "period": DEFAULT_PERIOD,
        "sort": DEFAULT_SORT,
        "nsfw": False,
        "always_on_top": False,
        "zen": False,
        "geometry": None,
    }

    def __init__(self, qsettings=None):
        if qsettings is None:
            from PySide6.QtCore import QSettings

            qsettings = QSettings(APP_ID, APP_ID)
        self._s = qsettings

    def get(self, key: str):
        default = self.DEFAULTS[key]
        value = self._s.value(key, default)
        if isinstance(default, bool):
            # INI files store booleans as strings.
            return value in (True, "true", "1", 1)
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def set(self, key: str, value) -> None:
        if key not in self.DEFAULTS:
            raise KeyError(key)
        self._s.setValue(key, value)

    def sync(self) -> None:
        self._s.sync()

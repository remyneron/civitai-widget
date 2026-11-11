"""On-disk cache for thumbnails and feed metadata. No Qt here."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from civitai_widget import config

log = logging.getLogger(__name__)

_IMAGE_SUFFIX = f"_{config.THUMB_WIDTH}.jpg"
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_STALE_TEMP_S = 3600


class DiskCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.cache_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- thumbnails -------------------------------------------------------
    def image_path(self, image_id: str) -> Path:
        safe = _UNSAFE.sub("", str(image_id)) or "unknown"
        return self.root / f"{safe}{_IMAGE_SUFFIX}"

    def has_image(self, image_id: str) -> bool:
        path = self.image_path(image_id)
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    def touch(self, image_id: str) -> None:
        """Mark a thumbnail as recently used so cleanup keeps what is still on screen."""
        try:
            os.utime(self.image_path(image_id))
        except OSError:
            pass

    def drop_image(self, image_id: str) -> None:
        try:
            self.image_path(image_id).unlink()
        except OSError:
            pass

    # ---- feed metadata ----------------------------------------------------
    def feed_path(self, key: str) -> Path:
        return self.root / f"feed_{_UNSAFE.sub('', key)}.json"

    def save_feed(self, key: str, items: list[dict], next_cursor: str) -> None:
        path = self.feed_path(key)
        temp = path.with_suffix(".json.tmp")
        payload = {"saved_at": time.time(), "next_cursor": next_cursor, "items": items}
        try:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(temp, path)
        except OSError as exc:
            log.warning("Cannot save feed cache: %s", exc)

    def load_feed(self, key: str) -> tuple[list[dict], str, float] | None:
        """Return (items, next_cursor, age_seconds) or None when missing or damaged."""
        try:
            with open(self.feed_path(key), encoding="utf-8") as handle:
                payload = json.load(handle)
            items = payload["items"]
            if not isinstance(items, list):
                return None
            age = max(0.0, time.time() - float(payload.get("saved_at", 0)))
            return items, str(payload.get("next_cursor") or ""), age
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # ---- housekeeping -----------------------------------------------------
    def cleanup(
        self,
        max_age_s: float = config.CACHE_MAX_AGE_S,
        max_bytes: int = config.CACHE_MAX_BYTES,
        now: float | None = None,
    ) -> int:
        """Delete old files, leftovers and, if needed, least recently used thumbnails."""
        now = time.time() if now is None else now
        removed = 0
        images: list[tuple[float, int, Path]] = []
        try:
            entries = list(os.scandir(self.root))
        except OSError:
            return 0
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            path = Path(entry.path)
            age = now - stat.st_mtime
            name = entry.name
            if name.endswith(_IMAGE_SUFFIX):
                if age > max_age_s:
                    removed += _unlink(path)
                else:
                    images.append((stat.st_mtime, stat.st_size, path))
            elif name.startswith("feed_") and name.endswith(".json"):
                if age > max_age_s:
                    removed += _unlink(path)
            elif name.startswith("metadata_") and name.endswith(".json"):
                removed += _unlink(path)  # v1 metadata format
            elif age > _STALE_TEMP_S:
                removed += _unlink(path)  # interrupted downloads and other leftovers

        total = sum(size for _, size, _ in images)
        for _, size, path in sorted(images):
            if total <= max_bytes:
                break
            if _unlink(path):
                removed += 1
                total -= size
        return removed


def _unlink(path: Path) -> int:
    try:
        path.unlink()
        return 1
    except OSError:
        return 0

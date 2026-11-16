"""Pure feed logic: query description, item filtering, pagination. No Qt here."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from civitai_widget import config


@dataclass(frozen=True)
class FeedQuery:
    nsfw: bool = False
    period: str = config.DEFAULT_PERIOD
    sort: str = config.DEFAULT_SORT

    def params(self, cursor: str = "") -> dict[str, str]:
        params = {
            "sort": self.sort,
            "period": self.period,
            "limit": str(config.FEED_LIMIT),
            "nsfw": "true" if self.nsfw else "false",
        }
        if cursor:
            params["cursor"] = cursor
        return params

    def key(self) -> str:
        """Stable identifier used for the on-disk feed cache."""
        raw = f"{int(self.nsfw)}|{self.period}|{self.sort}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _with_transform(url: str, transform: str, extension: str | None = None) -> str:
    """Replace the CDN transform segment (the one right before the file name)."""
    parts = urlsplit(url)
    segments = parts.path.split("/")
    if len(segments) < 2 or "=" not in segments[-2]:
        return url
    segments[-2] = transform
    if extension:
        segments[-1] = segments[-1].rsplit(".", 1)[0] + extension
    return urlunsplit(parts._replace(path="/".join(segments)))


def thumbnail_url(url: str, width: int = config.THUMB_WIDTH) -> str:
    """Rewrite a Civitai image URL so the CDN returns a `width`-px thumbnail.

    URLs look like `.../<uuid>/original=true/<name>.jpeg` or `.../<uuid>/width=1024/<name>.jpeg`.
    """
    return _with_transform(url, f"width={width}")


def is_video(item: dict | None) -> bool:
    return bool(item) and item.get("type") == "video"


def poster_url(item: dict, width: int = config.THUMB_WIDTH) -> str:
    """Still picture for a tile: a thumbnail for images, the first frame for videos."""
    url = item.get("url") or ""
    if is_video(item):
        return _with_transform(url, f"anim=false,transcode=true,width={width}", ".jpeg")
    return thumbnail_url(url, width)


def video_url(item: dict, width: int = config.THUMB_WIDTH) -> str:
    """Down-scaled MP4 for in-tile playback (a few MB instead of the original)."""
    return _with_transform(item.get("url") or "", f"transcode=true,width={width}", ".mp4")


def reaction_count(item: dict) -> int:
    stats = item.get("stats") or {}
    total = 0
    for key in ("likeCount", "heartCount", "laughCount", "cryCount"):
        value = stats.get(key) or 0
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def format_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1000:.0f}k"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def is_sfw(item: dict) -> bool:
    """Client-side safety net on top of the `nsfw=false` request parameter."""
    if item.get("nsfw") not in (None, False):
        return False
    level = item.get("nsfwLevel")
    if level is None:
        return True
    if isinstance(level, str):
        return level.strip().lower() in ("", "none")
    if isinstance(level, (int, float)):
        return level <= 1
    return False


def clean_items(raw_items, allow_nsfw: bool) -> list[dict]:
    """Keep displayable images and videos, drop duplicates and (optionally) anything not SFW."""
    seen: set[str] = set()
    result: list[dict] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in ("image", "video") or not item.get("url") or item.get("id") is None:
            continue
        if not allow_nsfw and not is_sfw(item):
            continue
        item_id = str(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def base_models(items: list[dict]) -> list[tuple[str, int]]:
    """Base models present in the feed, most frequent first."""
    counts = Counter(item.get("baseModel") for item in items if item.get("baseModel"))
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def filter_by_model(items: list[dict], model: str | None) -> list[dict]:
    if not model:
        return list(items)
    return [item for item in items if item.get("baseModel") == model]


def paginate(items: list[dict], per_page: int) -> list[list[dict]]:
    per_page = max(1, per_page)
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def page_count(total: int, per_page: int) -> int:
    return -(-total // max(1, per_page))


def page_slice(items: list[dict], page: int, per_page: int) -> list[dict]:
    """Items of one page. A short last page is topped up from the start, so no tile stays empty."""
    per_page = max(1, per_page)
    start = page * per_page
    chunk = items[start : start + per_page]
    if chunk and len(chunk) < per_page and len(items) >= per_page:
        chunk = chunk + items[: per_page - len(chunk)]
    return chunk


def merge_new(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Items from `incoming` that are not in `existing` yet (batches may overlap)."""
    known = set(item_ids(existing))
    return [item for item in incoming if str(item.get("id")) not in known]


def item_ids(items: list[dict]) -> list[str]:
    return [str(item.get("id")) for item in items]

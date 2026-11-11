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


def thumbnail_url(url: str, width: int = config.THUMB_WIDTH) -> str:
    """Rewrite a Civitai image URL so the CDN returns a `width`-px thumbnail.

    URLs look like `.../<uuid>/original=true/<name>.jpeg` or `.../<uuid>/width=1024/<name>.jpeg`;
    the transform segment is always the one right before the file name.
    """
    parts = urlsplit(url)
    segments = parts.path.split("/")
    if len(segments) >= 2 and "=" in segments[-2]:
        segments[-2] = f"width={width}"
        return urlunsplit(parts._replace(path="/".join(segments)))
    return url


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
    """Keep displayable still images, drop duplicates and (optionally) anything not SFW."""
    seen: set[str] = set()
    result: list[dict] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image" or not item.get("url") or item.get("id") is None:
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


def item_ids(items: list[dict]) -> list[str]:
    return [str(item.get("id")) for item in items]

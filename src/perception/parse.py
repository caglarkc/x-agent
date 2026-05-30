"""Parsing helpers for X UI text."""

from __future__ import annotations

import re


METRIC_ALIASES = {
    "views": ("view", "views", "görüntülenme"),
    "likes": ("like", "likes", "beğeni"),
    "retweets": ("repost", "reposts", "retweet", "retweets", "yeniden gönderi"),
    "replies": ("reply", "replies", "yanıt"),
    "quotes": ("quote", "quotes", "alıntı"),
    "bookmarks": ("bookmark", "bookmarks", "yer işareti"),
}


def parse_compact_number(value: str) -> int:
    """Parse compact counts such as `1.2K`, `4 B`, or `3,1 Mn`."""
    cleaned = value.strip().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KkMmBb]|Mn|mn|B|bin|milyon)?", cleaned)
    if not match:
        return 0
    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = 1
    if suffix in {"k", "b", "bin"}:
        multiplier = 1_000
    elif suffix in {"m", "mn", "milyon"}:
        multiplier = 1_000_000
    return int(number * multiplier)


def parse_metrics_blob(blob: str) -> dict[str, int]:
    """Extract engagement metrics from aria-label or visible text blobs."""
    result = {key: 0 for key in METRIC_ALIASES}
    normalized = " ".join(blob.replace("\n", " ").split())
    for key, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            patterns = [
                rf"(\d+(?:[\.,]\d+)?\s*(?:[KkMmBb]|Mn|mn|bin|milyon)?)\s+{re.escape(alias)}",
                rf"{re.escape(alias)}\s+(\d+(?:[\.,]\d+)?\s*(?:[KkMmBb]|Mn|mn|bin|milyon)?)",
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match:
                    result[key] = parse_compact_number(match.group(1))
                    break
            if result[key]:
                break
    return result

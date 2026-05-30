"""Trend radar observation from X Explore."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.config import BrandBible
from src.db import XAgentDB
from src.perception import selectors
from src.perception.browser import BrowserAgent


@dataclass(frozen=True)
class Trend:
    """Normalized trend item."""

    name: str
    volume: str | None
    niche_fit: float


def score_niche_fit(name: str, brand_bible: BrandBible) -> float:
    """Score a trend by simple theme/name overlap for the cold-start radar."""
    haystack = name.casefold()
    needles = [brand_bible.niche, *brand_bible.themes]
    score = 0.0
    for needle in needles:
        terms = [term for term in needle.casefold().replace(",", " ").split() if len(term) >= 3]
        if any(term in haystack for term in terms):
            score += 0.25
    return min(score, 1.0)


def _split_trend_text(text: str) -> tuple[str, str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", None
    name = lines[0]
    volume = next((line for line in lines[1:] if "post" in line.lower() or "gönderi" in line.lower()), None)
    return name, volume


async def observe_trends(
    *,
    db: XAgentDB,
    browser: BrowserAgent,
    brand_bible: BrandBible,
    limit: int,
) -> list[Trend]:
    """Capture current X Explore trends and store niche-fit scores."""
    observed: list[Trend] = []
    async with browser.session("https://x.com/explore/tabs/trending") as page:
        await page.wait_for_timeout(2000)
        trend_locator = page.locator(selectors.TREND_ITEM)
        if not await trend_locator.count():
            trend_locator = page.locator("[role='link']").filter(has_text="posts")

        for index in range(min(await trend_locator.count(), limit)):
            text = (await trend_locator.nth(index).inner_text()).strip()
            name, volume = _split_trend_text(text)
            if not name:
                continue
            observed.append(Trend(name=name[:200], volume=volume, niche_fit=score_niche_fit(name, brand_bible)))

    for trend in observed:
        db.add_trend(trend.name, trend.volume, trend.niche_fit)
    db.add_observation(
        "trends",
        {"count": len(observed), "trends": [asdict(trend) for trend in observed]},
    )
    return observed

"""Observe niche search results and store lightweight engagement snapshots."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import quote_plus

from src.db import XAgentDB
from src.perception import selectors
from src.perception.browser import BrowserAgent
from src.perception.parse import parse_metrics_blob


@dataclass(frozen=True)
class NicheTweet:
    """A niche tweet captured from search or timeline context."""

    x_post_id: str | None
    text: str
    metrics: dict[str, int]


def _extract_tweet_id(hrefs: list[str]) -> str | None:
    for href in hrefs:
        match = re.search(r"/status/(\d+)", href)
        if match:
            return match.group(1)
    return None


async def observe_niche(
    *,
    db: XAgentDB,
    browser: BrowserAgent,
    query: str,
    limit: int,
) -> list[NicheTweet]:
    """Capture recent niche tweets for strategy and feedback context."""
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("A search query is required for observe-niche")

    url = f"https://x.com/search?q={quote_plus(clean_query)}&src=typed_query&f=live"
    observed: list[NicheTweet] = []
    async with browser.session(url) as page:
        await page.wait_for_timeout(2000)
        articles = page.locator(selectors.TWEET_ARTICLE)
        for index in range(min(await articles.count(), limit)):
            article = articles.nth(index)
            text_locator = article.locator(selectors.TWEET_TEXT)
            if await text_locator.count():
                text = (await text_locator.first().inner_text()).strip()
            else:
                text = (await article.inner_text()).strip()
            hrefs = await article.locator("a[href*='/status/']").evaluate_all(
                "(els) => els.map((el) => el.getAttribute('href')).filter(Boolean)"
            )
            x_post_id = _extract_tweet_id(hrefs)
            metrics = parse_metrics_blob(await article.inner_text())
            observed.append(NicheTweet(x_post_id=x_post_id, text=text[:1000], metrics=metrics))

    for tweet in observed:
        post_id = db.get_or_create_observed_post(x_post_id=tweet.x_post_id, text=tweet.text)
        db.add_metrics(post_id, **tweet.metrics)
    db.add_observation(
        "niche_tweets",
        {"query": clean_query, "count": len(observed), "tweets": [asdict(tweet) for tweet in observed]},
    )
    return observed

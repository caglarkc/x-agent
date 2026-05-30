"""Observe the user's own recent X posts and store metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from src.db import XAgentDB
from src.perception import selectors
from src.perception.browser import BrowserAgent
from src.perception.parse import parse_metrics_blob


@dataclass(frozen=True)
class ObservedTweet:
    """Normalized tweet data extracted from the X UI."""

    x_post_id: str | None
    text: str
    metrics: dict[str, int]


def _extract_tweet_id(text: str) -> str | None:
    match = re.search(r"/status/(\d+)", text)
    return match.group(1) if match else None


async def observe_self(
    *,
    db: XAgentDB,
    browser: BrowserAgent,
    username: str,
    limit: int,
) -> list[ObservedTweet]:
    """Capture recent posts from the configured account profile."""
    clean_username = username.strip().lstrip("@")
    if not clean_username:
        raise ValueError("A username is required for observe-self")

    profile_url = f"https://x.com/{clean_username}"
    observed: list[ObservedTweet] = []
    async with browser.session(profile_url) as page:
        await page.wait_for_timeout(1500)
        articles = page.locator(selectors.TWEET_ARTICLE)
        for index in range(min(await articles.count(), limit)):
            article = articles.nth(index)
            text = ""
            text_locator = article.locator(selectors.TWEET_TEXT)
            if await text_locator.count():
                text = (await text_locator.first().inner_text()).strip()
            if not text:
                text = (await article.inner_text()).strip()

            links = await article.locator("a[href*='/status/']").evaluate_all(
                "(els) => els.map((el) => el.getAttribute('href')).filter(Boolean)"
            )
            x_post_id = _extract_tweet_id(" ".join(links))
            aria_blob = await article.locator("[role='group']").evaluate_all(
                "(els) => els.map((el) => el.getAttribute('aria-label') || el.innerText || '').join(' ')"
            )
            metrics = parse_metrics_blob(f"{aria_blob} {await article.inner_text()}")
            observed.append(ObservedTweet(x_post_id=x_post_id, text=text[:1000], metrics=metrics))

    for tweet in observed:
        post_id = db.get_or_create_observed_post(x_post_id=tweet.x_post_id, text=tweet.text)
        db.add_metrics(post_id, **tweet.metrics)
    db.add_observation(
        "self_tweets",
        {"username": clean_username, "count": len(observed), "tweets": [asdict(tweet) for tweet in observed]},
    )
    return observed

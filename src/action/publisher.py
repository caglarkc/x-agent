"""X API publisher with shadow mode and non-bypassable safety gates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.config import SafetySettings
from src.db import XAgentDB


class PublishBlockedError(RuntimeError):
    """Raised when a safety gate blocks publishing."""


@dataclass(frozen=True)
class PublishResult:
    """Result of a live or shadow publishing attempt."""

    draft_id: int
    post_id: int | None
    x_post_id: str | None
    shadow: bool
    status: str


@dataclass
class Publisher:
    """Publishes through X API v2, or records the action in shadow mode."""

    db: XAgentDB
    shadow_mode: bool
    safety: SafetySettings
    kill_switch_file: Path

    def publish_text(self, text: str, *, fmt: str = "single", topic: str | None = None) -> PublishResult:
        """Publish text or record a shadow publish, enforcing safety gates first."""
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Cannot publish empty text")
        if len(cleaned) > 280:
            raise ValueError("P0 publisher only supports single posts up to 280 characters")

        self._enforce_safety_gates()
        if self.shadow_mode:
            draft_id = self.db.create_draft(
                cleaned,
                fmt=fmt,
                topic=topic,
                status="shadow_post_planned",
                safety_ok=True,
                reason="shadow_mode=true; no X API call made",
            )
            post_id = self.db.create_post(
                cleaned,
                draft_id=draft_id,
                x_post_id=None,
                status="shadow",
            )
            return PublishResult(
                draft_id=draft_id,
                post_id=post_id,
                x_post_id=None,
                shadow=True,
                status="shadow_post_planned",
            )

        draft_id = self.db.create_draft(cleaned, fmt=fmt, topic=topic, status="publishing", safety_ok=True)
        x_post_id = self._post_to_x(cleaned)
        post_id = self.db.create_post(cleaned, draft_id=draft_id, x_post_id=x_post_id, status="published")
        self.db.update_draft_status(draft_id, "published", reason=f"published via X API as {x_post_id}")
        return PublishResult(
            draft_id=draft_id,
            post_id=post_id,
            x_post_id=x_post_id,
            shadow=False,
            status="published",
        )

    def _enforce_safety_gates(self) -> None:
        if self.kill_switch_file.exists():
            raise PublishBlockedError(f"Kill switch is active: {self.kill_switch_file}")
        if not self.shadow_mode:
            self._enforce_live_caps()

    def _enforce_live_caps(self) -> None:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        min_time = (now - timedelta(minutes=self.safety.min_post_interval_minutes)).isoformat(timespec="seconds")
        with self.db.connect() as conn:
            daily_count = conn.execute(
                "SELECT COUNT(*) AS count FROM posts WHERE status = 'published' AND published_at >= ?",
                (day_start,),
            ).fetchone()["count"]
            if int(daily_count) >= self.safety.daily_post_cap:
                raise PublishBlockedError("Daily live post cap reached")

            recent = conn.execute(
                "SELECT published_at FROM posts WHERE status = 'published' AND published_at >= ? LIMIT 1",
                (min_time,),
            ).fetchone()
            if recent:
                raise PublishBlockedError("Minimum live post interval has not elapsed")

    def _post_to_x(self, text: str) -> str:
        keys = {
            "consumer_key": os.getenv("X_API_KEY"),
            "consumer_secret": os.getenv("X_API_SECRET"),
            "access_token": os.getenv("X_ACCESS_TOKEN"),
            "access_token_secret": os.getenv("X_ACCESS_SECRET"),
        }
        missing = [name for name, value in keys.items() if not value]
        if missing:
            raise PublishBlockedError(f"Missing X API credentials: {', '.join(missing)}")

        try:
            import tweepy
        except ImportError as exc:
            raise PublishBlockedError("Install tweepy before live publishing") from exc

        client = tweepy.Client(**keys)
        response = client.create_tweet(text=text)
        data = getattr(response, "data", None) or {}
        x_post_id = data.get("id")
        if not x_post_id:
            raise RuntimeError(f"X API did not return a tweet id: {response!r}")
        return str(x_post_id)

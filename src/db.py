"""SQLite persistence layer for X-Agent audit data."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class XAgentDB:
    """Small SQLite repository with idempotent schema initialization."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction-enabled SQLite connection."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create or migrate the local database schema."""
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    format TEXT NOT NULL,
                    topic TEXT,
                    text TEXT NOT NULL,
                    oracle_score REAL,
                    predicted_views INTEGER,
                    confidence REAL,
                    safety_ok INTEGER,
                    status TEXT NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    x_post_id TEXT UNIQUE,
                    draft_id INTEGER,
                    published_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'published',
                    FOREIGN KEY (draft_id) REFERENCES drafts(id)
                );

                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    retweets INTEGER DEFAULT 0,
                    replies INTEGER DEFAULT 0,
                    quotes INTEGER DEFAULT 0,
                    bookmarks INTEGER DEFAULT 0,
                    profile_clicks INTEGER DEFAULT 0,
                    link_clicks INTEGER DEFAULT 0,
                    follows INTEGER DEFAULT 0,
                    oon_impressions INTEGER DEFAULT 0,
                    FOREIGN KEY (post_id) REFERENCES posts(id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    volume TEXT,
                    niche_fit REAL
                );

                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at TEXT NOT NULL,
                    key TEXT NOT NULL UNIQUE,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
                CREATE INDEX IF NOT EXISTS idx_posts_draft_id ON posts(draft_id);
                CREATE INDEX IF NOT EXISTS idx_metrics_post_id ON metrics(post_id);
                CREATE INDEX IF NOT EXISTS idx_observations_kind_time ON observations(kind, captured_at);
                CREATE INDEX IF NOT EXISTS idx_trends_time ON trends(captured_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_type_time ON sessions(type, started_at);
                """
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def create_session(self, session_type: str, status: str = "started", notes: str | None = None) -> int:
        """Record a session start and return its id."""
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (started_at, type, status, notes) VALUES (?, ?, ?, ?)",
                (utc_now(), session_type, status, notes),
            )
            return int(cursor.lastrowid)

    def finish_session(self, session_id: int, status: str, notes: str | None = None) -> None:
        """Mark a session as finished."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, status = ?, notes = ? WHERE id = ?",
                (utc_now(), status, notes, session_id),
            )

    def create_draft(
        self,
        text: str,
        *,
        fmt: str = "single",
        topic: str | None = None,
        status: str = "draft",
        oracle_score: float | None = None,
        predicted_views: int | None = None,
        confidence: float | None = None,
        safety_ok: bool | None = None,
        reason: str | None = None,
    ) -> int:
        """Create a draft with optional Oracle and Safety Guard audit fields."""
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO drafts (
                    created_at, format, topic, text, oracle_score, predicted_views,
                    confidence, safety_ok, status, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    fmt,
                    topic,
                    text,
                    oracle_score,
                    predicted_views,
                    confidence,
                    None if safety_ok is None else int(safety_ok),
                    status,
                    reason,
                ),
            )
            return int(cursor.lastrowid)

    def update_draft_status(self, draft_id: int, status: str, reason: str | None = None) -> None:
        """Update draft status while keeping an audit reason."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE drafts SET status = ?, reason = COALESCE(?, reason) WHERE id = ?",
                (status, reason, draft_id),
            )

    def create_post(
        self,
        text: str,
        *,
        draft_id: int | None = None,
        x_post_id: str | None = None,
        status: str = "published",
    ) -> int:
        """Record a live or shadow post action."""
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO posts (x_post_id, draft_id, published_at, text, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (x_post_id, draft_id, utc_now(), text, status),
            )
            return int(cursor.lastrowid)

    def get_or_create_observed_post(
        self,
        *,
        x_post_id: str | None,
        text: str,
        status: str = "observed",
    ) -> int:
        """Return an existing observed post id or create one for metric captures."""
        external_id = x_post_id or f"observed:{sha256(text.encode('utf-8')).hexdigest()[:24]}"
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM posts WHERE x_post_id = ?",
                (external_id,),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO posts (x_post_id, draft_id, published_at, text, status)
                VALUES (?, NULL, ?, ?, ?)
                """,
                (external_id, utc_now(), text, status),
            )
            return int(cursor.lastrowid)

    def add_metrics(self, post_id: int, **metrics: int) -> int:
        """Insert a metrics capture for a post."""
        allowed = {
            "views",
            "likes",
            "retweets",
            "replies",
            "quotes",
            "bookmarks",
            "profile_clicks",
            "link_clicks",
            "follows",
            "oon_impressions",
        }
        values = {key: int(metrics.get(key, 0)) for key in allowed}
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO metrics (
                    post_id, captured_at, views, likes, retweets, replies, quotes,
                    bookmarks, profile_clicks, link_clicks, follows, oon_impressions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    utc_now(),
                    values["views"],
                    values["likes"],
                    values["retweets"],
                    values["replies"],
                    values["quotes"],
                    values["bookmarks"],
                    values["profile_clicks"],
                    values["link_clicks"],
                    values["follows"],
                    values["oon_impressions"],
                ),
            )
            return int(cursor.lastrowid)

    def add_observation(self, kind: str, payload: dict[str, Any]) -> int:
        """Insert a browser or LLM observation payload."""
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO observations (captured_at, kind, payload_json) VALUES (?, ?, ?)",
                (utc_now(), kind, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            return int(cursor.lastrowid)

    def add_trend(self, name: str, volume: str | None = None, niche_fit: float | None = None) -> int:
        """Insert a trend radar item."""
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO trends (captured_at, name, volume, niche_fit) VALUES (?, ?, ?, ?)",
                (utc_now(), name, volume, niche_fit),
            )
            return int(cursor.lastrowid)

    def upsert_learning(self, key: str, value: dict[str, Any]) -> None:
        """Store calibration or strategy learning state by key."""
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO learnings (updated_at, key, value_json)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    value_json = excluded.value_json
                """,
                (utc_now(), key, payload),
            )

    def count_rows(self, table: str) -> int:
        """Return row count for a known table, used by CLI smoke checks."""
        allowed = {"drafts", "posts", "metrics", "observations", "trends", "learnings", "sessions"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])

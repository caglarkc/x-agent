"""X-Agent command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.action.publisher import Publisher
from src.config import AppConfig, load_config
from src.db import XAgentDB
from src.perception.browser import BrowserAgent
from src.perception.observe_niche import observe_niche
from src.perception.observe_self import observe_self
from src.perception.trends import observe_trends


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="X-Agent autonomous X manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("db-init", help="Initialize or migrate the SQLite database")
    subparsers.add_parser("login", help="Open persistent Chrome profile for one-time X login")

    test_post = subparsers.add_parser("test-post", help="Publish or shadow-record a hello-world post")
    test_post.add_argument("--text", default=None, help="Post text; defaults to config.posting.test_post_text")

    observe_self_parser = subparsers.add_parser("observe-self", help="Capture own recent posts and metrics")
    observe_self_parser.add_argument("--username", default=None, help="X username; defaults to config or X_USERNAME")
    observe_self_parser.add_argument("--limit", type=int, default=None, help="Number of recent posts to inspect")

    observe_niche_parser = subparsers.add_parser("observe-niche", help="Capture recent niche search results")
    observe_niche_parser.add_argument("query", help="X search query for the niche")
    observe_niche_parser.add_argument("--limit", type=int, default=None, help="Number of posts to inspect")

    observe_trends_parser = subparsers.add_parser("observe-trends", help="Capture X Explore trends")
    observe_trends_parser.add_argument("--limit", type=int, default=None, help="Number of trends to inspect")

    subparsers.add_parser("observe", help="Run self, trends, and niche observation in one session")

    subparsers.add_parser("run", help="Future autonomous scheduler entrypoint")
    return parser


def load_runtime() -> tuple[XAgentDB, AppConfig]:
    """Load config and initialize the database handle."""
    config = load_config()
    db = XAgentDB(config.settings.database_file)
    return db, config


def command_db_init() -> int:
    db, config = load_runtime()
    db.init_schema()
    print(f"Database ready: {config.settings.database_file}")
    return 0


def command_login() -> int:
    db, config = load_runtime()
    db.init_schema()
    session_id = db.create_session("login", notes="manual persistent-profile login")
    try:
        agent = BrowserAgent(config.settings.chrome_profile_path, config.settings.browser)
        asyncio.run(agent.login())
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise
    db.finish_session(session_id, "completed", "manual login flow closed")
    print(f"Chrome profile stored under: {config.settings.chrome_profile_path}")
    return 0


def command_test_post(text: str | None) -> int:
    db, config = load_runtime()
    db.init_schema()
    session_id = db.create_session("test-post", notes="CLI smoke post")
    try:
        publisher = Publisher(
            db=db,
            shadow_mode=config.settings.shadow_mode,
            safety=config.settings.safety,
            kill_switch_file=config.settings.kill_switch_path,
        )
        result = publisher.publish_text(text or config.settings.posting.test_post_text)
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise

    db.finish_session(
        session_id,
        "completed",
        f"status={result.status}; draft_id={result.draft_id}; post_id={result.post_id}; shadow={result.shadow}",
    )
    if result.shadow:
        print(f"Shadow post recorded: draft_id={result.draft_id}, post_id={result.post_id}")
    else:
        print(f"Live post published: x_post_id={result.x_post_id}, draft_id={result.draft_id}")
    return 0


def _browser(config: AppConfig) -> BrowserAgent:
    return BrowserAgent(config.settings.chrome_profile_path, config.settings.browser)


def command_observe_self(username: str | None, limit: int | None) -> int:
    db, config = load_runtime()
    db.init_schema()
    selected_username = username or config.settings.account.x_username or os.getenv("X_USERNAME")
    selected_limit = limit or config.settings.observation.self_tweet_limit
    session_id = db.create_session("observe-self", notes=f"username={selected_username}; limit={selected_limit}")
    try:
        tweets = asyncio.run(
            observe_self(
                db=db,
                browser=_browser(config),
                username=selected_username or "",
                limit=selected_limit,
            )
        )
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise
    db.finish_session(session_id, "completed", f"captured={len(tweets)}")
    print(f"Self observation captured {len(tweets)} tweets")
    return 0


def command_observe_niche(query: str, limit: int | None) -> int:
    db, config = load_runtime()
    db.init_schema()
    selected_limit = limit or config.settings.observation.niche_tweet_limit
    session_id = db.create_session("observe-niche", notes=f"query={query}; limit={selected_limit}")
    try:
        tweets = asyncio.run(
            observe_niche(
                db=db,
                browser=_browser(config),
                query=query,
                limit=selected_limit,
            )
        )
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise
    db.finish_session(session_id, "completed", f"captured={len(tweets)}")
    print(f"Niche observation captured {len(tweets)} tweets")
    return 0


def command_observe_trends(limit: int | None) -> int:
    db, config = load_runtime()
    db.init_schema()
    selected_limit = limit or config.settings.observation.trend_limit
    session_id = db.create_session("observe-trends", notes=f"limit={selected_limit}")
    try:
        trends = asyncio.run(
            observe_trends(
                db=db,
                browser=_browser(config),
                brand_bible=config.brand_bible,
                limit=selected_limit,
            )
        )
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise
    db.finish_session(session_id, "completed", f"captured={len(trends)}")
    print(f"Trend observation captured {len(trends)} trends")
    return 0


def command_observe() -> int:
    db, config = load_runtime()
    db.init_schema()
    username = config.settings.account.x_username or os.getenv("X_USERNAME")
    if not username:
        raise ValueError("Set account.x_username in config/settings.yaml or X_USERNAME in .env")
    session_id = db.create_session("observe", notes="combined P1 observation")
    try:
        tweets = asyncio.run(
            observe_self(
                db=db,
                browser=_browser(config),
                username=username,
                limit=config.settings.observation.self_tweet_limit,
            )
        )
        trends = asyncio.run(
            observe_trends(
                db=db,
                browser=_browser(config),
                brand_bible=config.brand_bible,
                limit=config.settings.observation.trend_limit,
            )
        )
        niche = asyncio.run(
            observe_niche(
                db=db,
                browser=_browser(config),
                query=config.brand_bible.niche,
                limit=config.settings.observation.niche_tweet_limit,
            )
        )
    except Exception as exc:
        db.finish_session(session_id, "failed", str(exc))
        raise
    db.finish_session(
        session_id,
        "completed",
        f"self={len(tweets)}; trends={len(trends)}; niche={len(niche)}",
    )
    print(f"Observation captured self={len(tweets)}, trends={len(trends)}, niche={len(niche)}")
    return 0


def command_run() -> int:
    print("The autonomous scheduler is introduced in later phases.")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "db-init":
        return command_db_init()
    if args.command == "login":
        return command_login()
    if args.command == "test-post":
        return command_test_post(args.text)
    if args.command == "observe-self":
        return command_observe_self(args.username, args.limit)
    if args.command == "observe-niche":
        return command_observe_niche(args.query, args.limit)
    if args.command == "observe-trends":
        return command_observe_trends(args.limit)
    if args.command == "observe":
        return command_observe()
    if args.command == "run":
        return command_run()
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

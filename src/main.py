"""X-Agent command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.action.publisher import Publisher
from src.config import load_config
from src.db import XAgentDB
from src.perception.browser import BrowserAgent


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="X-Agent autonomous X manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("db-init", help="Initialize or migrate the SQLite database")
    subparsers.add_parser("login", help="Open persistent Chrome profile for one-time X login")

    test_post = subparsers.add_parser("test-post", help="Publish or shadow-record a hello-world post")
    test_post.add_argument("--text", default=None, help="Post text; defaults to config.posting.test_post_text")

    subparsers.add_parser("run", help="Future autonomous scheduler entrypoint")
    return parser


def load_runtime() -> tuple[XAgentDB, object]:
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
    if args.command == "run":
        return command_run()
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

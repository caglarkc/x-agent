"""Playwright browser adapter for persistent-profile X sessions."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from pathlib import Path

from src.config import BrowserSettings
from src.perception import selectors


class BrowserConfigurationError(RuntimeError):
    """Raised when Playwright is unavailable or misconfigured."""


@dataclass
class BrowserAgent:
    """Human-paced browser session manager using a persistent Chrome profile."""

    profile_dir: Path
    settings: BrowserSettings

    async def _sleep_jitter(self) -> None:
        delay = random.uniform(
            self.settings.action_jitter_min_seconds,
            self.settings.action_jitter_max_seconds,
        )
        await asyncio.sleep(delay)

    async def login(self) -> None:
        """Open X for one-time manual login and keep the profile on disk."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserConfigurationError("Install playwright and run `playwright install chromium`") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.settings.headless,
                viewport={"width": 1280, "height": 900},
                channel="chrome",
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(selectors.X_HOME_URL, wait_until="domcontentloaded")
            await self._sleep_jitter()
            if "login" in page.url or "flow/login" in page.url:
                await page.goto(selectors.X_LOGIN_URL, wait_until="domcontentloaded")

            print("Browser opened. Complete X login/2FA, then return here and press Enter.")
            await asyncio.to_thread(input)
            await context.storage_state(path=str(self.profile_dir / "storage_state.json"))
            await context.close()

    async def open_home_once(self) -> str:
        """Open the home timeline briefly and return the final URL."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserConfigurationError("Install playwright and run `playwright install chromium`") from exc

        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.settings.headless,
                viewport={"width": 1280, "height": 900},
                channel="chrome",
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(selectors.X_HOME_URL, wait_until="domcontentloaded")
            await self._sleep_jitter()
            final_url = page.url
            await context.close()
            return final_url

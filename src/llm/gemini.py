"""Gemini API adapter with local throttle and retry controls."""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from src.config import GeminiSettings, ModelSettings


class GeminiConfigurationError(RuntimeError):
    """Raised when Gemini is called without required configuration."""


@dataclass
class GeminiClient:
    """Thin wrapper around `google-genai` for Flash, Pro, and vision calls."""

    models: ModelSettings
    settings: GeminiSettings
    api_key: str | None = None
    _client: Any | None = field(default=None, init=False, repr=False)
    _minute_calls: deque[float] = field(default_factory=deque, init=False, repr=False)
    _day: date = field(default_factory=lambda: datetime.now(UTC).date(), init=False)
    _day_calls: int = field(default=0, init=False)

    def _get_client(self) -> Any:
        if self._client is None:
            key = self.api_key or os.getenv("GEMINI_API_KEY")
            if not key:
                raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini calls")
            try:
                from google import genai
            except ImportError as exc:
                raise GeminiConfigurationError("Install google-genai before calling Gemini") from exc
            self._client = genai.Client(api_key=key)
        return self._client

    def _throttle(self) -> None:
        now = time.monotonic()
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day = today
            self._day_calls = 0

        while self._minute_calls and now - self._minute_calls[0] >= 60:
            self._minute_calls.popleft()

        if self._day_calls >= self.settings.rpd_limit:
            raise GeminiConfigurationError("Gemini daily request limit reached")

        if len(self._minute_calls) >= self.settings.rpm_limit:
            sleep_for = 60 - (now - self._minute_calls[0])
            time.sleep(max(0.0, sleep_for))

        self._minute_calls.append(time.monotonic())
        self._day_calls += 1

    def generate(self, prompt: str, *, model: str | None = None) -> str:
        """Generate text with retry and quota pacing."""
        selected_model = model or self.models.flash
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                self._throttle()
                response = self._get_client().models.generate_content(
                    model=selected_model,
                    contents=prompt,
                )
                return getattr(response, "text", "") or ""
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(self.settings.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"Gemini request failed after retries: {last_error}") from last_error

    def generate_flash(self, prompt: str) -> str:
        """Generate with the high-volume Flash model."""
        return self.generate(prompt, model=self.models.flash)

    def generate_pro(self, prompt: str) -> str:
        """Generate with the deeper weekly-analysis Pro model."""
        return self.generate(prompt, model=self.models.pro)

    def generate_vision(self, prompt: str, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Generate from a prompt plus screenshot bytes using the vision-capable Flash model."""
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                self._throttle()
                try:
                    from google.genai import types
                except ImportError as exc:
                    raise GeminiConfigurationError("Install google-genai before vision calls") from exc
                response = self._get_client().models.generate_content(
                    model=self.models.vision,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    ],
                )
                return getattr(response, "text", "") or ""
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(self.settings.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"Gemini vision request failed after retries: {last_error}") from last_error

"""Runtime settings, read from environment variables only.

API keys and the app password never live in the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")
CUP_DAY = date(2026, 11, 3)
CUP_VENUE = "Flemington"

MIN_POLL_SECONDS = 30


class ConfigError(ValueError):
    """Raised when an environment variable holds an unusable value."""


@dataclass(frozen=True)
class Settings:
    formfav_api_key: str | None
    puntersedge_api_key: str | None
    app_password: str | None
    race_date: date
    venue: str
    poll_seconds: int
    auto_refresh: bool = False

    @property
    def has_form_source(self) -> bool:
        return bool(self.formfav_api_key or self.puntersedge_api_key)

    @property
    def has_price_source(self) -> bool:
        return bool(self.puntersedge_api_key)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    raw_date = _clean(env.get("RACE_DATE"))
    try:
        race_date = date.fromisoformat(raw_date) if raw_date else CUP_DAY
    except ValueError as exc:
        raise ConfigError(f"RACE_DATE must be YYYY-MM-DD, got {raw_date!r}") from exc

    raw_poll = _clean(env.get("POLL_SECONDS"))
    try:
        poll_seconds = int(raw_poll) if raw_poll else 60
    except ValueError as exc:
        raise ConfigError(f"POLL_SECONDS must be a whole number, got {raw_poll!r}") from exc
    if poll_seconds < MIN_POLL_SECONDS:
        raise ConfigError(f"POLL_SECONDS must be at least {MIN_POLL_SECONDS}")

    return Settings(
        formfav_api_key=_clean(env.get("FORMFAV_API_KEY")),
        puntersedge_api_key=_clean(env.get("PUNTERSEDGE_API_KEY")),
        app_password=_clean(env.get("APP_PASSWORD")),
        race_date=race_date,
        venue=_clean(env.get("VENUE")) or CUP_VENUE,
        poll_seconds=poll_seconds,
        auto_refresh=(_clean(env.get("PRICE_MODE")) or "manual").lower() == "auto",
    )

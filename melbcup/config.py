"""Runtime settings, read from environment variables only.

API keys and the app password never live in the repository. racing.com needs no key. The
retired PUNTERSEDGE_API_KEY, if still set on a host, is ignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")
CUP_DAY = date(2026, 11, 3)
CUP_VENUE = "Flemington"


class ConfigError(ValueError):
    """Raised when an environment variable holds an unusable value."""


@dataclass(frozen=True)
class Settings:
    formfav_api_key: str | None
    app_password: str | None
    race_date: date
    venue: str
    auto_refresh: bool = False
    public: bool = False  # PUBLIC_ACCESS=1: no password prompt (owner choice, Azure app)


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

    return Settings(
        formfav_api_key=_clean(env.get("FORMFAV_API_KEY")),
        app_password=_clean(env.get("APP_PASSWORD")),
        race_date=race_date,
        venue=_clean(env.get("VENUE")) or CUP_VENUE,
        auto_refresh=(_clean(env.get("PRICE_MODE")) or "manual").lower() == "auto",
        public=_clean(env.get("PUBLIC_ACCESS")) == "1",
    )

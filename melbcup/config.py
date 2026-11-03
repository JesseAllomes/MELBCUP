"""Runtime settings, read from environment variables only.

API keys and the app password never live in the repository. racing.com needs no key. The
retired PUNTERSEDGE_API_KEY, if still set on a host, is ignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    auto_refresh: bool = True  # PRICE_MODE=manual turns the live loop off
    public: bool = False  # PUBLIC_ACCESS=1: no password prompt (owner choice, Azure app)
    betfair_username: str | None = field(default=None, repr=False)
    betfair_password: str | None = field(default=None, repr=False)
    betfair_app_key: str | None = field(default=None, repr=False)
    bet_pin: str | None = field(default=None, repr=False)  # BET_PIN: every betting action
    bet_live: bool = False  # BET_MODE=live: real Betfair bets (needs the live app key)
    auto_limit: float = 20.0  # AUTO_LIMIT: auto's default daily limit in dollars
    pointsbet: bool = False  # POINTSBET=1: PointsBet as a third betting account (off by default)
    promos: bool = False  # PROMOS=1: bookmaker promos (melbcup/bets/promos.py) become Win bets
    asynym: bool = False  # ASYNYM=1: the AsynymBet redesign (melbcup/web/templates/asynym/)


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
        auto_refresh=(_clean(env.get("PRICE_MODE")) or "auto").lower() != "manual",
        public=_clean(env.get("PUBLIC_ACCESS")) == "1",
        betfair_username=_clean(env.get("BETFAIR_USERNAME")),
        betfair_password=_clean(env.get("BETFAIR_PASSWORD")),
        betfair_app_key=_clean(env.get("BETFAIR_APP_KEY")),
        bet_pin=_clean(env.get("BET_PIN")),
        bet_live=(_clean(env.get("BET_MODE")) or "").lower() == "live",
        auto_limit=_money(env.get("AUTO_LIMIT"), 20.0),
        pointsbet=_clean(env.get("POINTSBET")) == "1",
        promos=_clean(env.get("PROMOS")) == "1",
        asynym=_clean(env.get("ASYNYM")) == "1",
    )


def _money(raw: str | None, default: float) -> float:
    raw = _clean(raw)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"AUTO_LIMIT must be a dollar amount, got {raw!r}") from exc
    if value < 0:
        raise ConfigError("AUTO_LIMIT cannot be negative")
    return value

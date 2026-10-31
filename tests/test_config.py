from datetime import date

import pytest

from melbcup.config import CUP_DAY, ConfigError, load_settings


def test_defaults_target_cup_day_at_flemington():
    s = load_settings({})
    assert s.race_date == CUP_DAY == date(2026, 11, 3)
    assert s.venue == "Flemington"
    assert s.formfav_api_key is None


def test_keys_are_trimmed_and_blank_means_missing():
    s = load_settings({"FORMFAV_API_KEY": "  abc ", "APP_PASSWORD": "   "})
    assert s.formfav_api_key == "abc"
    assert s.app_password is None


def test_the_retired_puntersedge_key_is_ignored():
    s = load_settings({"PUNTERSEDGE_API_KEY": "old-key"})
    assert not hasattr(s, "puntersedge_api_key")
    assert "old-key" not in repr(s)


def test_overrides():
    s = load_settings({"RACE_DATE": "2026-10-31", "VENUE": "Caulfield"})
    assert s.race_date == date(2026, 10, 31)
    assert s.venue == "Caulfield"


@pytest.mark.parametrize(
    "env",
    [{"RACE_DATE": "3/11/2026"}, {"RACE_DATE": "2026-13-01"}],
)
def test_bad_values_raise(env):
    with pytest.raises(ConfigError):
        load_settings(env)

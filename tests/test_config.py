from datetime import date

import pytest

from melbcup.config import CUP_DAY, ConfigError, load_settings


def test_defaults_target_cup_day_at_flemington():
    s = load_settings({})
    assert s.race_date == CUP_DAY == date(2026, 11, 3)
    assert s.venue == "Flemington"
    assert not s.has_form_source
    assert not s.has_price_source


def test_keys_are_trimmed_and_blank_means_missing():
    s = load_settings({"FORMFAV_API_KEY": "  abc ", "PUNTERSEDGE_API_KEY": "   "})
    assert s.formfav_api_key == "abc"
    assert s.puntersedge_api_key is None
    assert s.has_form_source
    assert not s.has_price_source


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

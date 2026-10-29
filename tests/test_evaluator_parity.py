"""Compare the standalone evaluator with the committed v1 evaluator on synthetic races."""

import importlib.util
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.evaluator import Rules, evaluate


@unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("numpy"),
                     "Comparing the v1 implementation requires pandas and NumPy")
class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / "research" / "analysis"
        with tempfile.TemporaryDirectory(prefix="melbcup-parity-") as scratch:
            with patch.dict(os.environ, MELBCUP_DATA=scratch, MELBCUP_RESULTS=scratch):
                spec = importlib.util.spec_from_file_location("parity_screen", root / "screen.py")
                screen = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(screen)
            with patch.dict(sys.modules, screen=screen):
                spec = importlib.util.spec_from_file_location("parity_evaluate", root / "evaluate.py")
                cls.legacy = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cls.legacy)
            with patch.dict(sys.modules, evaluate=cls.legacy):
                spec = importlib.util.spec_from_file_location("parity_git_tests",
                                                              root / "test_evaluate.py")
                cls.git_tests = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cls.git_tests)
        # Smoke comparisons need no more than 500 resamples; no published output is changed.
        cls.legacy.NBOOT = 500

    def both(self, scenarios):
        import numpy as np
        import pandas as pd

        predictions, outcomes, frames = [], [], []
        for i, (probs, market, prices, winners, scratches, barriers) in enumerate(scenarios):
            rid, day = f"r{i}", f"2024-01-{i + 1:02d}"
            for j, (p, m, q, barrier) in enumerate(zip(probs, market, prices, barriers, strict=True), 1):
                runner = str(j)
                starter, won = runner not in scratches, runner in winners
                predictions.append(dict(race_id=rid, runner_id=runner, day=day, block="train",
                                        model_prob=p, market_prob=m, win_price=q, bookmaker="sb"))
                outcomes.append(dict(race_id=rid, runner_id=runner, starter=starter, won=won))
                status = "late_scratching" if scratches else (
                    "dead_heat" if len(winners) > 1 else "ok"
                )
                frames.append(dict(race_id=rid, date=day, mel_date=day, block="train",
                                   starter=starter, won=won, M_t30=m, barrier=barrier,
                                   fav_M_t30=abs(m - max(market)) <= 1e-9,
                                   sb_t30=q, lb_t30=q, scoring_status_t30=status))
        frame = pd.DataFrame(frames)
        p = np.array([row["model_prob"] for row in predictions])
        m = frame.M_t30.to_numpy()
        legacy = self.legacy.claims(frame, p, m, m, 0.9833)
        standalone = evaluate(predictions, outcomes, Rules(alpha=1, resamples=500))
        return legacy, standalone

    def test_committed_git_settlement_tests(self):
        self.git_tests.test_win_returns()
        self.git_tests.test_claims_dead_heat()

    def test_point_estimates_match_across_eleven_scenarios(self):
        p, m, q = (.6, .3, .1), (.5, .3, .2), (2, 3, 5)
        upset = (.45, .25, .3)
        cases = [
            (p, m, q, ("1",), ()), (p, m, q, ("2",), ()),
            (upset, m, q, ("3",), ()), (upset, m, q, ("2",), ()),
            (p, m, q, ("1", "2"), ()),
            (p, m, (2, 4, 12), ("1", "2", "3"), ()),
            (p, m, q, ("1",), ("3",)), (upset, m, q, ("1",), ("2",)),
            ((.4, .4, .2), m, q, ("2",), ()),
            (p, (.4, .4, .2), q, ("1",), ()),
            ((.5, .3, .2), m, (1.1, 1.1, 1.1), ("1",), ()),
        ]
        git, new = self.both([(*case, (1, 2, 3)) for case in cases])
        pairs = [
            (git["A"]["mean_ll_gain"], new["claims"]["A"]["estimate"]),
            (git["A"]["races"], new["claims"]["A"]["events"]),
            (git["A"]["logloss_P"], new["metrics"]["model"]["logloss"]),
            (git["A"]["logloss_Malpha"], new["metrics"]["corrected_market"]["logloss"]),
            (git["A"]["brier_P"], new["metrics"]["model"]["brier"]),
            (git["A"]["brier_Malpha"], new["metrics"]["corrected_market"]["brier"]),
            (git["B"]["bets"], new["claims"]["B"]["events"]),
            (git["B"]["roi"], new["claims"]["B"]["estimate"]),
            (git["B"]["excluded_late_scratch_bets"],
             new["counts"]["excluded_late_scratch_bets"]),
            (git["C"]["nominations"], new["claims"]["C"]["events"]),
            (git["C"]["mean_diff"], new["claims"]["C"]["estimate"]),
        ]
        for old, current in pairs:
            self.assertTrue(math.isclose(old, current, rel_tol=1e-12, abs_tol=1e-12),
                            (old, current))
        self.assertEqual(git["B"]["days"], 8)
        self.assertEqual(new["claims"]["B"]["eligible_days"], 11)

    def test_benchmark_tie_policy_is_an_explicit_difference(self):
        git, new = self.both([((.35, .2, .3, .15), (.5, .2, .2, .1),
                              (2, 3, 4, 5), ("3",), (), (4, 3, 1, 2))])
        self.assertEqual(git["C"]["mean_diff"], 0)
        self.assertEqual(new["claims"]["C"]["estimate"], 1)


if __name__ == "__main__":
    unittest.main()

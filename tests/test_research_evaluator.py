"""Synthetic-only checks; never load any research block or frozen result."""

import contextlib
import csv
import importlib.util
import io
import json
import math
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from research.evaluator import Rules, evaluate, interval, main


def race(rid="r1", day="2024-01-01", p=(0.6, 0.3, 0.1), m=(0.5, 0.3, 0.2),
         prices=(2.0, 3.0, 5.0), winners=("1",), scratches=()):
    predictions, outcomes = [], []
    for i, (prob, market, price) in enumerate(zip(p, m, prices, strict=True), 1):
        runner = str(i)
        predictions.append(dict(race_id=rid, runner_id=runner, day=day, block="train",
                                model_prob=prob, market_prob=market, win_price=price,
                                bookmaker="test"))
        outcomes.append(dict(race_id=rid, runner_id=runner,
                             starter=runner not in scratches, won=runner in winners))
    return predictions, outcomes


class EvaluatorTests(unittest.TestCase):
    rules = Rules(alpha=1, resamples=100)

    def score(self, predictions, outcomes, **changes):
        return evaluate(predictions, outcomes, replace(self.rules, **changes))

    def test_hand_calculated_logloss_brier_and_improvement(self):
        report = self.score(*race())
        self.assertAlmostEqual(report["metrics"]["model"]["logloss"], -math.log(0.6))
        self.assertAlmostEqual(report["metrics"]["model"]["brier"], 0.26)
        self.assertAlmostEqual(report["claims"]["A"]["estimate"], math.log(0.6 / 0.5))
        self.assertAlmostEqual(report["comparisons"]["corrected_vs_raw_logloss"]["estimate"], 0)

    def test_frozen_exponent_and_supplied_corrected_probabilities_agree(self):
        p, o = race()
        total = sum(float(r["market_prob"]) ** 1.13 for r in p)
        for row in p:
            row["corrected_prob"] = row["market_prob"] ** 1.13 / total
        a = self.score(p, o, alpha=1.13)
        b = self.score(p, o, alpha=None)
        self.assertEqual(a["metrics"], b["metrics"])

    def test_dead_heat_counts_unbacked_winner(self):
        p, o = race(winners=("1", "2"))
        report = self.score(p, o)
        self.assertEqual(report["counts"]["selected_bets"], 1)
        self.assertEqual(report["race_audit"][0]["bets"][0]["returned"], 1.0)
        self.assertEqual(report["claims"]["B"]["estimate"], 0)
        self.assertIsNone(report["claims"]["A"]["estimate"])

    def test_dead_heat_multiple_bets_and_three_way_split(self):
        for prices, winners, expected in (
            ((2, 4, 5), ("1", "2"), [1, 2]),
            ((2, 4, 12), ("1", "2", "3"), [2 / 3, 4 / 3, 4]),
        ):
            report = self.score(*race(prices=prices, winners=winners))
            returns = [b["returned"] for b in report["race_audit"][0]["bets"]]
            self.assertEqual(returns, expected)

    def test_late_scratches_renormalise_both_models_but_not_selection(self):
        report = self.score(*race(scratches=("3",)))
        self.assertAlmostEqual(report["metrics"]["model"]["logloss"], -math.log(0.6 / 0.9))
        self.assertAlmostEqual(report["metrics"]["raw_market"]["logloss"], -math.log(0.5 / 0.8))
        self.assertEqual(report["counts"]["excluded_late_scratch_bets"], 1)
        self.assertEqual(report["counts"]["excluded_notional_return"], 2)
        self.assertIsNone(report["claims"]["B"]["estimate"])

    def test_recorded_settlement_handles_refunds_and_deductions(self):
        p, o = race(scratches=("3",))
        o[0]["return_per_unit"] = 1.8
        report = self.score(p, o, settlement="recorded")
        self.assertAlmostEqual(report["claims"]["B"]["estimate"], 0.8)
        p, o = race(scratches=("1",), winners=("2",))
        o[0]["return_per_unit"] = 1
        report = self.score(p, o, settlement="recorded")
        self.assertEqual(report["claims"]["B"]["estimate"], 0)

    def test_recorded_settlement_requires_payout_for_every_selected_bet(self):
        with self.assertRaisesRegex(ValueError, "return_per_unit"):
            self.score(*race(), settlement="recorded")

    def test_recorded_refunds_include_cancelled_races_without_results(self):
        p, o = race()
        for result in o:
            result.update(result_available=False, return_per_unit=1)
        report = self.score(p, o, settlement="recorded")
        self.assertEqual(report["counts"]["selected_bets"], 1)
        self.assertEqual(report["counts"]["settled_bets"], 1)
        self.assertEqual(report["claims"]["B"]["estimate"], 0)
        self.assertIsNone(report["claims"]["A"]["estimate"])

    def test_missing_results_preserve_predecision_exposure(self):
        p, _ = race()
        report = self.score(p, [])
        self.assertEqual(report["counts"]["selected_bets"], 1)
        self.assertEqual(report["counts"]["unsettled_bets"], 1)
        self.assertEqual(report["race_audit"][0]["bets"][0]["status"], "unsettled")
        self.assertIsNone(report["claims"]["A"]["estimate"])

    def test_partial_results_are_not_silently_dropped(self):
        p, o = race()
        with self.assertRaisesRegex(ValueError, "partial result"):
            self.score(p, o[:-1])

    def test_three_losses_are_flagged_without_rewriting_frozen_rule(self):
        p, o = [], []
        for i in range(3):
            a, b = race(f"r{i}", f"2024-01-0{i + 1}", winners=("2",))
            p.extend(a)
            o.extend(b)
        result = self.score(p, o)["claims"]["B"]
        self.assertEqual((result["lo"], result["hi"]), (-1, -1))
        self.assertEqual(result["rule_verdict"], "fail")
        self.assertEqual(result["evidence_verdict"], "inconclusive")
        self.assertTrue(any("Degenerate" in w for w in result["warnings"]))

    def test_bootstrap_ratio_of_sums_and_zero_event_days(self):
        parts = {"d1": (9, 9), "d2": (-1, 1)}
        result = interval(parts, {"d1", "d2", "d3"}, self.rules)
        self.assertEqual(result["estimate"], 0.8)
        self.assertEqual(result["eligible_days"], 3)
        self.assertEqual(result["event_days"], 2)
        self.assertGreater(result["zero_denominator_resamples"], 0)
        self.assertEqual(result, interval(parts, {"d3", "d2", "d1"}, self.rules))

    def test_no_events_and_minimums(self):
        self.assertIsNone(interval({}, {"d1"}, self.rules)["estimate"])
        result = interval({"d1": (1, 1), "d2": (2, 1)}, {"d1", "d2"}, self.rules, 3)
        self.assertEqual(result["rule_verdict"], "inconclusive")

    def test_nomination_and_benchmark_fixed_before_scratches(self):
        p, o = race(p=(0.45, 0.25, 0.30), scratches=("2",))
        report = self.score(p, o)
        audit = report["race_audit"][0]
        self.assertEqual((audit["nominee"], audit["benchmark"]), ("3", "2"))
        self.assertEqual(audit["nomination_status"], "void")
        self.assertEqual(report["counts"]["void_benchmark"], 1)
        self.assertIsNone(report["claims"]["C"]["estimate"])

    def test_missing_outcomes_do_not_erase_nomination(self):
        p, _ = race(p=(0.45, 0.25, 0.30))
        report = self.score(p, [])
        self.assertEqual(report["counts"]["selected_nominations"], 1)
        self.assertEqual(report["race_audit"][0]["nomination_status"], "unscored")

    def test_nominee_equal_benchmark_counts_as_zero(self):
        report = self.score(*race(p=(0.4, 0.4, 0.2)))
        self.assertEqual(report["claims"]["C"]["estimate"], 0)

    def test_cofavourites_cannot_be_upset_nominees(self):
        report = self.score(*race(p=(0.6, 0.3, 0.1), m=(0.4, 0.4, 0.2)))
        self.assertIsNone(report["race_audit"][0]["nominee"])

    def test_input_permutation_does_not_change_report(self):
        p, o = race(p=(0.4, 0.4, 0.2))
        self.assertEqual(self.score(p, o), self.score(p[::-1], o[::-1]))

    def test_rejects_invalid_probabilities_and_duplicate_predictions(self):
        for value in (float("nan"), -1, 1.1, 0):
            p, o = race()
            p[0]["model_prob"] = value
            with self.assertRaises(ValueError):
                self.score(p, o)
        p, o = race()
        with self.assertRaisesRegex(ValueError, "duplicate prediction"):
            self.score(p + [p[0]], o)
        p[0]["model_prob"] = 0.7
        with self.assertRaisesRegex(ValueError, "probabilities sum"):
            self.score(p, o)

    def test_rejects_invalid_results_mixed_blocks_and_extra_starters(self):
        p, o = race()
        with self.assertRaisesRegex(ValueError, "duplicate outcome"):
            self.score(p, o + [o[0]])
        with self.assertRaisesRegex(ValueError, "actual starter missing"):
            self.score(p, o + [dict(race_id="r1", runner_id="4", starter=True, won=False)])
        o[0]["starter"] = False
        with self.assertRaisesRegex(ValueError, "scratched runner cannot win"):
            self.score(p, o)
        p[1]["block"] = "tune1"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.score(p, [])

    def test_cli_writes_strict_json_and_never_overwrites(self):
        p, o = race()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, rows in (("pred.csv", p), ("out.csv", o)):
                with (root / name).open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            (root / "rules.json").write_text('{"resamples": 100}')
            args = ["--predictions", str(root / "pred.csv"), "--outcomes", str(root / "out.csv"),
                    "--output", str(root / "report.json"), "--alpha", "1",
                    "--rules", str(root / "rules.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                main(args)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["counts"]["eligible_races"], 1)
            self.assertEqual(len(report["provenance"]["inputs"]["predictions"]["sha256"]), 64)
            before = (root / "report.json").read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)
            self.assertEqual(before, (root / "report.json").read_bytes())

    def test_protected_block_rejected_before_any_input_is_opened(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--predictions", "/missing/p", "--outcomes", "/missing/o",
                  "--output", "/missing/report", "--block", "final"])


@unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("numpy"),
                     "The pinned-model adapter requires pandas and NumPy")
class PinnedExportTests(unittest.TestCase):
    def fixture(self, root):
        import pandas as pd

        from research.evaluator import file_hash

        out = root / "dataset" / "out"
        out.mkdir(parents=True)
        predictions, outcomes = race()
        rows = []
        for p, o in zip(predictions, outcomes, strict=True):
            rows.append(dict(race_id=p["race_id"], entry_no=p["runner_id"], date=p["day"],
                             mel_date=p["day"], block="train", inU_t30=True,
                             M_t30=p["market_prob"], sb_t30=p["win_price"],
                             lb_t30=p["win_price"], starter=o["starter"], won=o["won"]))
        # A synthetic protected row cannot be used for prediction (invalid M). No real data.
        rows.append(dict(rows[0], race_id="protected", block="final", M_t30=-1))
        pd.DataFrame(rows).to_pickle(out / "runners.pkl.gz")
        pd.DataFrame([dict(race_id="r1", race_resulted=True, in_sample=True),
                      dict(race_id="protected", race_resulted=True, in_sample=True)]).to_pickle(
                          out / "races.pkl.gz")
        manifest = dict(files={f"out/{name}.pkl.gz": dict(sha256=file_hash(out / f"{name}.pkl.gz"))
                               for name in ("runners", "races")})
        (out.parent / "manifest.json").write_text(json.dumps(manifest))
        model = dict(alpha=1.13, fams=[], names=[], w=[], scalers={},
                     dataset_manifest_sha256=file_hash(out.parent / "manifest.json"))
        (root / "model.json").write_text(json.dumps(model))
        return out.parent, root / "model.json"

    def test_export_predicts_without_fitting_and_filters_protected_rows(self):
        from research.analysis.export_predictions import export

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, model = self.fixture(root)
            before = model.read_bytes()
            environment_before = {k: os.environ.get(k)
                                  for k in ("MELBCUP_DATA", "MELBCUP_RESULTS")}
            record = export(data, model, root / "export", "train")
            self.assertEqual(record["prediction_rows"], 3)
            self.assertEqual(before, model.read_bytes())
            self.assertEqual(environment_before, {k: os.environ.get(k)
                                                  for k in environment_before})
            with (root / "export" / "predictions.csv").open() as stream:
                p = list(csv.DictReader(stream))
            with (root / "export" / "outcomes.csv").open() as stream:
                o = list(csv.DictReader(stream))
            report = evaluate(p, o, Rules(resamples=100))
            self.assertAlmostEqual(report["claims"]["A"]["estimate"], 0)
            self.assertEqual(report["counts"]["eligible_races"], 1)
            with self.assertRaisesRegex(ValueError, "already exists"):
                export(data, model, root / "export", "train")

    def test_export_refuses_protected_blocks_and_modified_dataset(self):
        from research.analysis.export_predictions import export

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, model = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "development blocks only"):
                export(data, model, root / "export", "final")
            with (data / "out" / "runners.pkl.gz").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "does not match"):
                export(data, model, root / "export", "train")
            self.assertFalse((root / "export").exists())


if __name__ == "__main__":
    unittest.main()

"""Evaluate saved runner probabilities without fitting a model or selecting features.

Standard-library-only CLI: python -m research.evaluator --help.
Input/output contracts and examples are in research/EVALUATOR.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

DEVELOPMENT = {"train", "tune1"}
BLOCKS = DEVELOPMENT | {"tune2", "final", "forward"}
VIEWS = ("model", "corrected_market", "raw_market")


@dataclass(frozen=True)
class Rules:
    alpha: float | None = None
    level: float = 0.9833
    resamples: int = 10_000
    seed: int = 20261031
    min_edge: float = 0.05
    min_win_prob: float = 0.04
    max_price: float = 21.0
    upset_min_prob: float = 0.10
    upset_ratio: float = 1.25
    min_bets: int = 0
    min_nominations: int = 0
    settlement: str = "conditional"

    def validate(self):
        if self.alpha is not None and (not math.isfinite(self.alpha) or self.alpha <= 0):
            raise ValueError("alpha must be finite and positive")
        if not 0 < self.level < 1 or self.resamples < 100:
            raise ValueError("interval level must be in (0,1), with at least 100 resamples")
        if not 0 <= self.min_win_prob <= 1 or not 0 <= self.upset_min_prob <= 1:
            raise ValueError("probability thresholds must be in [0,1]")
        if not math.isfinite(self.min_edge) or self.min_edge < 0:
            raise ValueError("minimum edge must be finite and nonnegative")
        if not math.isfinite(self.max_price) or self.max_price <= 1:
            raise ValueError("maximum price must exceed 1")
        if not math.isfinite(self.upset_ratio) or self.upset_ratio < 1:
            raise ValueError("upset ratio must be finite and at least 1")
        if self.min_bets < 0 or self.min_nominations < 0:
            raise ValueError("event minimums cannot be negative")
        if self.settlement not in {"conditional", "recorded"}:
            raise ValueError("settlement must be conditional or recorded")


def number(value, name, *, low=0.0, high=math.inf):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: expected a number, got {value!r}") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name}: outside [{low}, {high}]")
    return result


def flag(value, name):
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"{name}: expected true/false or 1/0")


def identity(row):
    key = (str(row.get("race_id", "")).strip(), str(row.get("runner_id", "")).strip())
    if not all(key):
        raise ValueError("race_id and runner_id are required")
    return key


def quantile(values, q):
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def interval(parts, days, rules, minimum=0):
    """Paired ratio-of-sums bootstrap; include eligible days with zero events."""
    pairs = [parts.get(day, (0.0, 0.0)) for day in sorted(days)]
    total_num = sum(p[0] for p in pairs)
    total_den = sum(p[1] for p in pairs)
    result = dict(estimate=None, lo=None, hi=None, events=total_den,
                  eligible_days=len(pairs), event_days=sum(p[1] > 0 for p in pairs),
                  valid_resamples=0, zero_denominator_resamples=0,
                  rule_verdict="inconclusive", evidence_verdict="inconclusive", warnings=[])
    if total_den <= 0:
        result["warnings"].append("No scored events; the rule was not tested.")
        return result
    result["estimate"] = total_num / total_den
    rng = random.Random(rules.seed)
    samples = []
    for _ in range(rules.resamples):
        n = d = 0.0
        for _ in pairs:
            pn, pd = pairs[rng.randrange(len(pairs))]
            n += pn
            d += pd
        if d > 0:
            samples.append(n / d)
    result["valid_resamples"] = len(samples)
    result["zero_denominator_resamples"] = rules.resamples - len(samples)
    if not samples:
        return result
    samples.sort()
    tail = (1 - rules.level) / 2
    lo, hi = quantile(samples, tail), quantile(samples, 1 - tail)
    result.update(lo=lo, hi=hi)
    verdict = "pass" if lo > 0 else "fail" if hi <= 0 else "inconclusive"
    result["rule_verdict"] = verdict
    if total_den < minimum:
        result["warnings"].append(f"Below the declared minimum of {minimum} events.")
        result["rule_verdict"] = "inconclusive"
    if result["event_days"] < 2:
        result["warnings"].append("Fewer than two days with events; uncertainty is not estimable.")
    if math.isclose(samples[0], samples[-1], rel_tol=1e-12, abs_tol=1e-15):
        result["warnings"].append(
            "Degenerate empirical bootstrap; a zero-width interval does not establish certainty."
        )
    if not result["warnings"]:
        result["evidence_verdict"] = result["rule_verdict"]
    return result


def add(parts, day, numerator, denominator=1.0):
    old_n, old_d = parts.get(day, (0.0, 0.0))
    parts[day] = (old_n + numerator, old_d + denominator)


def evaluate(predictions, outcomes, rules=None):
    """Score one block. Predictions cover U at decision time, including later scratches.

    No model fitting, probability calibration, or threshold search happens here.
    """
    rules = rules or Rules()
    rules.validate()
    races = defaultdict(list)
    keys = set()
    blocks = set()
    for source in predictions:
        row = dict(source)
        race_id, runner_id = identity(row)
        if (race_id, runner_id) in keys:
            raise ValueError(f"duplicate prediction: {race_id}/{runner_id}")
        keys.add((race_id, runner_id))
        day = date.fromisoformat(str(row["day"])).isoformat()
        block = str(row["block"])
        if block not in BLOCKS:
            raise ValueError(f"unknown block: {block}")
        blocks.add(block)
        p = number(row["model_prob"], "model_prob", low=1e-300, high=1)
        m = number(row["market_prob"], "market_prob", low=1e-300, high=1)
        corrected = None
        if rules.alpha is None:
            corrected = number(row.get("corrected_prob"), "corrected_prob", low=1e-300, high=1)
        price = None
        if row.get("win_price") not in (None, ""):
            price = number(row["win_price"], "win_price", low=1.0000001)
            if not str(row.get("bookmaker", "")).strip():
                raise ValueError("bookmaker is required when win_price is supplied")
        row.update(race_id=race_id, runner_id=runner_id, day=day, block=block,
                   model=p, raw_market=m, corrected_market=corrected, price=price)
        races[race_id].append(row)
    if len(blocks) != 1:
        raise ValueError("evaluate exactly one nonempty block per report")
    for rid, rows in races.items():
        if len(rows) < 2 or len({r["day"] for r in rows}) != 1:
            raise ValueError(f"{rid}: need at least two runners and one consistent day")
        for view in VIEWS:
            if view == "corrected_market" and rules.alpha is not None:
                logs = [rules.alpha * math.log(r["raw_market"]) for r in rows]
                top = max(logs)
                weights = [math.exp(x - top) for x in logs]
                total = sum(weights)
                for row, weight in zip(rows, weights, strict=True):
                    row[view] = weight / total
            total = sum(r[view] for r in rows)
            if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-6):
                raise ValueError(f"{rid}: {view} probabilities sum to {total}, not 1")
            for row in rows:
                row[view] /= total

    results = {}
    for source in outcomes:
        key = identity(source)
        if key in results:
            raise ValueError(f"duplicate outcome: {key}")
        if key[0] not in races:
            continue
        row = dict(source)
        if not flag(row.get("result_available", True), "result_available"):
            row.update(available=False)
        else:
            starter = flag(row["starter"], "starter")
            won = flag(row["won"], "won")
            if won and not starter:
                raise ValueError(f"{key}: a scratched runner cannot win")
            if key not in keys and starter:
                raise ValueError(f"{key}: actual starter missing from decision-time predictions")
            row.update(available=True, starter=starter, won=won)
        results[key] = row

    parts = {name: {} for name in ("A", "B", "C", "market_logloss", "market_brier", "model_brier")}
    totals = {view: dict(logloss=0.0, brier=0.0, top_pick_strike=0.0) for view in VIEWS}
    calibration = {view: {} for view in VIEWS}
    counts = defaultdict(int)
    audit = []
    days = {rows[0]["day"] for rows in races.values()}
    for rid in sorted(races):
        rows = sorted(races[rid], key=lambda r: r["runner_id"])
        day = rows[0]["day"]
        record = dict(race_id=rid, day=day, scoring="", bets=[], nominee=None, benchmark=None)
        audit.append(record)
        selected_bets = [r for r in rows if r["price"] is not None
                         and r["model"] * r["price"] - 1 >= rules.min_edge
                         and r["model"] >= rules.min_win_prob
                         and r["price"] <= rules.max_price]
        counts["unpriced_runners"] += sum(r["price"] is None for r in rows)
        for row in selected_bets:
            record["bets"].append(dict(runner_id=row["runner_id"], price=row["price"],
                                       bookmaker=row["bookmaker"], probability=row["model"],
                                       stake=1.0, status="unsettled"))
        counts["selected_bets"] += len(selected_bets)
        highest = max(r["raw_market"] for r in rows)
        nonfav = [r for r in rows if highest - r["raw_market"] > 1e-9]
        candidates = [r for r in nonfav if r["model"] >= rules.upset_min_prob]
        nominee = benchmark = None
        if candidates:
            candidate = min(candidates, key=lambda r: (
                -r["model"] / r["corrected_market"], r["runner_id"]
            ))
            if candidate["model"] / candidate["corrected_market"] >= rules.upset_ratio:
                nominee = candidate
                benchmark = min(nonfav, key=lambda r: (-r["raw_market"], r["runner_id"]))
                record.update(nominee=nominee["runner_id"], benchmark=benchmark["runner_id"],
                              nomination_status="unscored")
                counts["selected_nominations"] += 1
        rr = [results.get((rid, r["runner_id"])) for r in rows]
        if any(r is None for r in rr) and any(r is not None for r in rr):
            raise ValueError(f"{rid}: partial result; supply every runner or mark unavailable")
        # Actual recorded settlements also cover cancelled races with no winning result.
        if rules.settlement == "recorded":
            for row, bet in zip(selected_bets, record["bets"], strict=True):
                outcome = results.get((rid, row["runner_id"]), {})
                returned = number(outcome.get("return_per_unit"), "return_per_unit")
                bet.update(status="settled", returned=returned, profit=returned - 1)
                counts["settled_bets"] += 1
                counts["stakes"] += 1
                counts["returned"] += returned
                add(parts["B"], day, returned - 1)
        if any(r is None or not r["available"] for r in rr):
            counts["missing_result_races"] += 1
            if rules.settlement == "conditional":
                counts["unsettled_bets"] += len(selected_bets)
            record["scoring"] = "missing_result"
            continue
        for row, result in zip(rows, rr, strict=True):
            row.update(starter=result["starter"], won=result["won"], outcome=result)
        starters = [r for r in rows if r["starter"]]
        winners = [r for r in starters if r["won"]]
        late = len(starters) != len(rows)
        counts["late_scratching_races"] += late
        if not winners:
            counts["no_winner_races"] += 1
            if rules.settlement == "conditional":
                counts["unsettled_bets"] += len(selected_bets)
            record["scoring"] = "no_winner"
            continue
        dead = len(winners) > 1
        counts["dead_heat_races"] += dead
        record["scoring"] = "dead_heat" if dead else "late_scratching" if late else "ok"
        if not dead:
            counts["probability_scored_races"] += 1
            losses, briers = {}, {}
            for view in VIEWS:
                total = sum(r[view] for r in starters)
                probs = [r[view] / total for r in starters]
                losses[view] = -math.log(probs[starters.index(winners[0])])
                briers[view] = sum((p - float(r["won"])) ** 2
                                   for p, r in zip(probs, starters, strict=True))
                best_p = max(probs)
                top = [r for p, r in zip(probs, starters, strict=True)
                       if abs(p - best_p) <= 1e-9]
                totals[view]["logloss"] += losses[view]
                totals[view]["brier"] += briers[view]
                totals[view]["top_pick_strike"] += sum(r["won"] for r in top) / len(top)
                for p, row in zip(probs, starters, strict=True):
                    band = min(int(p * 10), 9)
                    cell = calibration[view].setdefault(band, [0, 0.0, 0])
                    cell[0] += 1
                    cell[1] += p
                    cell[2] += row["won"]
            add(parts["A"], day, losses["corrected_market"] - losses["model"])
            add(parts["market_logloss"], day, losses["raw_market"] - losses["corrected_market"])
            add(parts["market_brier"], day, briers["raw_market"] - briers["corrected_market"])
            add(parts["model_brier"], day, briers["corrected_market"] - briers["model"])
            record["logloss"] = losses
            record["brier"] = briers

        for row, bet in zip(selected_bets, record["bets"], strict=True):
            if rules.settlement == "recorded":
                continue
            q = row["price"]
            notional = q / len(winners) if row["won"] else 0.0
            if late and rules.settlement == "conditional":
                counts["excluded_late_scratch_bets"] += 1
                counts["excluded_stakes"] += 1
                counts["excluded_notional_return"] += notional
                bet.update(status="excluded_late_scratching", notional_return=notional)
                continue
            returned = notional
            bet.update(status="settled", returned=returned, profit=returned - 1)
            counts["settled_bets"] += 1
            counts["stakes"] += 1
            counts["returned"] += returned
            add(parts["B"], day, returned - 1)

        if nominee is None:
            continue
        if not nominee["starter"] or not benchmark["starter"]:
            counts["void_nominee"] += not nominee["starter"]
            counts["void_benchmark"] += not benchmark["starter"]
            record["nomination_status"] = "void"
        elif dead:
            counts["dead_heat_nominations"] += 1
            record["nomination_status"] = "excluded_dead_heat"
        else:
            counts["scored_nominations"] += 1
            counts["nominee_wins"] += nominee["won"]
            counts["benchmark_wins"] += benchmark["won"]
            record["nomination_status"] = "scored"
            add(parts["C"], day, float(nominee["won"]) - float(benchmark["won"]))

    n = counts["probability_scored_races"]
    metrics = {view: {key: value / n if n else None for key, value in vals.items()}
               for view, vals in totals.items()}
    bands = {view: [dict(lower=b / 10, upper=(b + 1) / 10, runners=cell[0],
                         mean_probability=cell[1] / cell[0], win_rate=cell[2] / cell[0])
                    for b, cell in sorted(cells.items())] for view, cells in calibration.items()}
    return dict(schema_version=1, block=next(iter(blocks)), rules=asdict(rules),
                interpretation="Positive paired differences favour the model named first.",
                metrics=metrics, calibration=bands,
                claims={name: interval(parts[name], days, rules, minimum)
                        for name, minimum in (("A", 0), ("B", rules.min_bets),
                                              ("C", rules.min_nominations))},
                comparisons={name: interval(parts[key], days, rules) for name, key in (
                    ("corrected_vs_raw_logloss", "market_logloss"),
                    ("corrected_vs_raw_brier", "market_brier"),
                    ("model_vs_corrected_brier", "model_brier"))},
                counts=dict(eligible_races=len(races), eligible_days=len(days), **counts),
                race_audit=audit)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--block", choices=sorted(BLOCKS), default="train")
    parser.add_argument("--alpha", type=float,
                        help="Frozen exponent; otherwise corrected_prob required")
    parser.add_argument("--rules", type=Path, help="JSON Rules fields; no search or fitting")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--confirmatory", action="store_true")
    args = parser.parse_args(argv)
    if args.block not in DEVELOPMENT and not (
        args.confirmatory and args.protocol and args.model
    ):
        parser.error("protected block: requires --confirmatory, --protocol and --model")
    if args.output.exists():
        parser.error("output already exists; use a new report filename")
    try:
        settings = json.loads(args.rules.read_text()) if args.rules else {}
        if args.alpha is not None:
            settings["alpha"] = args.alpha
        rules = Rules(**settings)
        rules.validate()
        with args.predictions.open(newline="") as stream:
            predictions = [r for r in csv.DictReader(stream) if r.get("block") == args.block]
        selected = {r["race_id"] for r in predictions}
        with args.outcomes.open(newline="") as stream:
            outcomes = [r for r in csv.DictReader(stream) if r.get("race_id") in selected]
        report = evaluate(predictions, outcomes, rules)
        inputs = {name: dict(path=str(path.resolve()), sha256=file_hash(path))
                  for name, path in (("predictions", args.predictions), ("outcomes", args.outcomes),
                                     ("rules", args.rules), ("protocol", args.protocol),
                                     ("model", args.model)) if path is not None}
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                cwd=Path(__file__).parent, check=False).stdout.strip()
        report["provenance"] = dict(inputs=inputs, git_commit=commit,
                                    evaluator_sha256=file_hash(__file__),
                                    created_utc=datetime.now(UTC).isoformat())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(f"Wrote {args.output}: {report['counts']['eligible_races']} races ({args.block})")


if __name__ == "__main__":
    main()

"""Export development predictions from a pinned v1 model; never refit it.

Run from the repo root: python -m research.analysis.export_predictions --help.
NumPy and pandas are needed only for this adapter, not for the evaluator.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import tempfile
from pathlib import Path

from research.evaluator import file_hash


def screen_helpers(data_root):
    """Load prediction helpers without directing legacy output into frozen result folders."""
    names = ("MELBCUP_DATA", "MELBCUP_RESULTS")
    previous = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory(prefix="melbcup-prediction-import-") as scratch:
        os.environ["MELBCUP_DATA"] = str(data_root)
        os.environ["MELBCUP_RESULTS"] = scratch
        try:
            return importlib.import_module("research.analysis.screen")
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def export(data_root, model_path, output_dir, block):
    if block not in {"train", "tune1"}:
        raise ValueError("The v1 adapter exports development blocks only: train or tune1")
    if output_dir.exists():
        raise ValueError("output directory already exists; choose a new directory")
    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    model = json.loads(model_path.read_text())
    manifest_hash = file_hash(manifest_path)
    if model.get("dataset_manifest_sha256") != manifest_hash:
        raise ValueError("dataset manifest differs from the pinned model's manifest")
    paths = {name: data_root / "out" / f"{name}.pkl.gz" for name in ("runners", "races")}
    for name, path in paths.items():
        expected = manifest["files"][f"out/{name}.pkl.gz"]["sha256"]
        if file_hash(path) != expected:
            raise ValueError(f"{name} table does not match its manifest")

    # Import only after validating paths and the block. These are trusted local dataset pickles.
    import numpy as np
    import pandas as pd

    screen = screen_helpers(data_root)
    raw = pd.read_pickle(paths["runners"])
    raw = raw[raw["block"].astype(str) == block].copy()
    race_rows = pd.read_pickle(paths["races"])
    race_rows = race_rows[race_rows["race_id"].isin(raw["race_id"])].copy()
    if "in_sample" in race_rows:
        race_rows = race_rows[race_rows["in_sample"].astype(bool)]
    raw = raw[raw["race_id"].isin(race_rows["race_id"])].copy()
    d = raw[raw["inU_t30"].astype(bool)].copy()
    if d.empty:
        raise ValueError(f"no eligible runners in {block}")
    d = d.sort_values(["date", "race_id", "entry_no"]).reset_index(drop=True)
    if not np.isfinite(d["M_t30"]).all() or (d["M_t30"] <= 0).any():
        raise ValueError("invalid decision-time market probabilities")
    d["logM"] = np.log(d["M_t30"])
    # Probability generation has no access to labels through Races.y.
    d["won"] = False
    rc = screen.Races(d)
    scalers = {key: tuple(value) for key, value in model["scalers"].items()}
    X, names = screen.design(d, model["fams"], scalers)
    if names != model["names"] or len(model["w"]) != len(names):
        raise ValueError("pinned feature names/coefficients differ from the design matrix")
    offset = model["alpha"] * d["logM"].to_numpy()
    p = rc.probs(offset + X @ np.asarray(model["w"]))
    corrected = rc.probs(offset)
    predictions = []
    for i, row in enumerate(d.to_dict("records")):
        sb, lb = float(row["sb_t30"]), float(row["lb_t30"])
        if not all(np.isfinite(q) and q > 1 for q in (sb, lb)):
            raise ValueError("both decision-time bookmaker quotes are required")
        predictions.append(dict(race_id=str(row["race_id"]), runner_id=str(row["entry_no"]),
                                day=str(row["mel_date"])[:10], block=block,
                                model_prob=float(p[i]), market_prob=float(row["M_t30"]),
                                corrected_prob=float(corrected[i]), win_price=max(sb, lb),
                                bookmaker="sb" if sb >= lb else "lb"))
    available = race_rows.set_index("race_id")["race_resulted"].to_dict()
    outcomes = [dict(race_id=str(r["race_id"]), runner_id=str(r["entry_no"]),
                     starter=bool(r["starter"]),
                     won=bool(r["won"]) if pd.notna(r["won"]) else False,
                     result_available=bool(available[r["race_id"]]))
                for r in raw.to_dict("records")]
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, rows in (("predictions", predictions), ("outcomes", outcomes)):
        with (output_dir / f"{name}.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    record = dict(block=block, model_sha256=file_hash(model_path),
                  dataset_manifest_sha256=manifest_hash,
                  source_sha256={name: file_hash(path) for name, path in paths.items()},
                  output_sha256={name: file_hash(output_dir / f"{name}.csv")
                                 for name in ("predictions", "outcomes")},
                  prediction_rows=len(predictions), outcome_rows=len(outcomes))
    with (output_dir / "export.json").open("x") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Trusted dataset directory containing manifest.json and out/")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--block", choices=("train", "tune1"), default="train")
    args = parser.parse_args(argv)
    try:
        record = export(args.data_root, args.model, args.output_dir, args.block)
    except (OSError, ValueError, KeyError, ImportError) as exc:
        parser.error(str(exc))
    print(f"Exported {record['prediction_rows']} runner predictions to {args.output_dir}")


if __name__ == "__main__":
    main()

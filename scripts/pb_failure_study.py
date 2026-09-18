"""Pre-registered PB-family failure-classifier promotion study.

The rule is fitted once on the chronological training segment, then evaluated
without refitting on the untouched holdout at the measured spread and at 1.5x
spread.  It is intentionally research-only: a passing result would still need
an explicit production review before an EA input/guard is changed.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pb_failure_classifier import FailureRule, derive_rule  # noqa: E402

DEFAULT_DATA_DIR = ROOT / "artifacts" / "v75_blind90_fresh"
TRAIN_START = datetime.fromisoformat("2026-06-07T23:00:00+00:00")
HOLDOUT_START = datetime.fromisoformat("2026-08-06T23:00:00+00:00")
HOLDOUT_END = datetime.fromisoformat("2026-09-05T23:00:00+00:00")
BASE_SPREAD = 18.5
STRESS_MULT = 1.5
STARTING_EQUITY = 50.0
TP_MULT = 1.8
MIN_HOLDOUT_TRADES = 30


def _certifier(data_dir: Path, spread: float):
    """Load certification constants for one spread in an isolated module state."""
    os.environ.update({
        "CERT_DATA_DIR": str(data_dir.resolve()),
        "CERT_SPREAD": str(spread),
        "CERT_SPREAD_GATE_FRAC": "0.18",
        "CERT_USD_PER_UNIT_PER_LOT": "1.009",
        "CERT_MIN_LOT": "0.01",
        "CERT_LOT_STEP": "0.001",
        "CERT_MICRO_FIT_PCT": "1.5",
        "CERT_MIN_STOP": "107.70",
    })
    import certify_v75

    return importlib.reload(certify_v75)


def _metrics(report: dict) -> dict:
    return {
        key: report[key]
        for key in (
            "n", "wins", "win_rate", "total_r", "total_pnl",
            "max_drawdown_pct", "worst_loss_streak", "max_risk_pct",
        )
    }


def _run_pair(certifier, rule: FailureRule | None) -> dict:
    return _metrics(certifier.certify(
        STARTING_EQUITY,
        start=HOLDOUT_START,
        end=HOLDOUT_END,
        tp_mult=TP_MULT,
        failure_classifier=rule,
    ))


def run_study(data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    """Fit on training, then run one base and one stress comparison per arm."""
    base = _certifier(data_dir, BASE_SPREAD)
    training = base.certify(
        STARTING_EQUITY,
        start=TRAIN_START,
        end=HOLDOUT_START,
        tp_mult=TP_MULT,
    )
    rule, fit = derive_rule(training["trades"])
    baseline = _run_pair(base, None)
    filtered = _run_pair(base, rule)

    stress = _certifier(data_dir, BASE_SPREAD * STRESS_MULT)
    stressed_baseline = _run_pair(stress, None)
    stressed_filtered = _run_pair(stress, rule)

    gate = {
        "trade_count": filtered["n"] >= MIN_HOLDOUT_TRADES,
        "holdout_return": filtered["total_r"] > baseline["total_r"],
        "holdout_pnl": filtered["total_pnl"] > baseline["total_pnl"],
        "holdout_max_drawdown_not_worse": (
            filtered["max_drawdown_pct"] <= baseline["max_drawdown_pct"]
        ),
        "stress_return_not_worse": (
            stressed_filtered["total_r"] >= stressed_baseline["total_r"]
        ),
        "stress_pnl_not_worse": (
            stressed_filtered["total_pnl"] >= stressed_baseline["total_pnl"]
        ),
        "stress_max_drawdown_not_worse": (
            stressed_filtered["max_drawdown_pct"] <= stressed_baseline["max_drawdown_pct"]
        ),
    }
    return {
        "schema": "mitemshub.v75.pb-failure-classifier-study.v1",
        "protocol": {
            "data_dir": str(data_dir.resolve()),
            "training_window": [TRAIN_START.isoformat(), HOLDOUT_START.isoformat()],
            "holdout_window": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "base_spread": BASE_SPREAD,
            "stress_spread": BASE_SPREAD * STRESS_MULT,
            "spread_gate_frac": 0.18,
            "starting_equity": STARTING_EQUITY,
            "tp_mult": TP_MULT,
            "min_holdout_trades": MIN_HOLDOUT_TRADES,
            "fit_once_on_training": True,
        },
        "frozen_rule": rule.to_dict(),
        "training_fit": fit,
        "holdout": {"baseline": baseline, "classifier": filtered},
        "stress_1p5x": {"baseline": stressed_baseline, "classifier": stressed_filtered},
        "gate": gate,
        "promote": all(gate.values()),
        "production_change": "none unless promote is true",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "v75_replay" / "pb_failure_classifier_study.json",
    )
    args = parser.parse_args()
    result = run_study(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")

    print(f"frozen rule: {result['frozen_rule']['name']}")
    for label in ("holdout", "stress_1p5x"):
        row = result[label]
        print(
            f"{label}: baseline R={row['baseline']['total_r']:+.2f} "
            f"DD={row['baseline']['max_drawdown_pct']:.1f}% n={row['baseline']['n']} | "
            f"classifier R={row['classifier']['total_r']:+.2f} "
            f"DD={row['classifier']['max_drawdown_pct']:.1f}% n={row['classifier']['n']}"
        )
    print("gate:", "PASS" if result["promote"] else "FAIL")
    for name, passed in result["gate"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    print(f"report: {args.output}")
    return 0 if result["promote"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

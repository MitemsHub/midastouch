"""Two-sample train/test (walk-forward) protocol for V75MacroEngine tester runs.

Why this exists: every config comparison in this repo so far has been a
single-window A/B, which cannot separate *selection* from *validation*. The
standing example is the 6-month "best" springboard cell that collapsed on the
full window. This harness makes the discipline mechanical: parameters are
chosen on a TRAIN segment of the tick cache and then judged, untouched, on a
TEST segment, with the transfer reported rather than assumed.

Tick cache on the tester terminal: V75 real ticks 2024.01 -> 2026.09
(33 months). The broker's usable history starts at 2024.01 -- 2024.01/02 run
complete (2,832 M30 bars over 2 months) whereas 2023 Q4 delivers only 384 bars
at 60% history quality, so 2024.01 is the floor worth building on. Both presets
below are fully local, so a split costs no download time.

Presets
    legacy   train 2024.03-2024.05 / test 2024.06-2024.08
             (cache months 1-3 vs 4-6; ~18 / ~14 fills -- underpowered for
             per-cell selection, kept for continuity with the first split run)
    powered  train 2024.01-2025.08 / test 2025.09-2026.09
             (~20 / ~12 months, ~175 / ~105 fills -- the split the cache
             actually supports, clearing the 30-trade gate on both sides)

Usage
    python tests/v75_walkforward.py --preset legacy
    python tests/v75_walkforward.py --preset powered --configs spec,trail6h
    python tests/v75_walkforward.py --train 2024.03.01 2024.05.31 \
                                    --test 2024.06.01 2024.08.31 --configs spec

Each pass uses a complete explicit [TesterInputs] set (the INI otherwise merges
with the agent's cached inputs) and is verified against the report's own input
dump afterwards. Results persist to
artifacts/v75_macro_engine_tester/walkforward_<name>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v75_tester_runner import report_inputs, run_pass          # noqa: E402

ARTIFACTS = Path("artifacts/v75_macro_engine_tester")
MIN_FILLS = 30          # house protocol sample gate (per segment)
PASS_TIMEOUT_S = 900

PRESETS: dict[str, dict[str, tuple[str, str]]] = {
    "legacy": {"train": ("2024.03.01", "2024.05.31"),
               "test": ("2024.06.01", "2024.08.31")},
    "powered": {"train": ("2024.01.01", "2025.08.31"),
                "test": ("2025.09.01", "2026.09.10")},
}

# Spec contract defaults. Every pass sends the whole set.
BASE_INPUTS: dict[str, str] = {
    "InpMagicNumber": "7500", "InpMaxPositionCount": "1",
    "InpH4EMAPeriod": "20", "InpH1EMAPeriod": "20",
    "InpBBPeriod": "20", "InpBBDeviation": "2.0",
    "InpRSIPeriod": "14", "InpRSIBuyLevel": "35.0", "InpRSISellLevel": "65.0",
    "InpATRPeriod": "14", "InpRiskPercent": "1.0", "InpRRMultiplier": "2.0",
    "InpEnableTickSafety": "true",
    "InpBETriggerR": "0.2", "InpBEOffsetPoints": "10", "InpTrailATRMult": "1.0",
    "InpAuditCsv": "false",
}

# The dimension that has actually moved results: exit geometry.
CONFIGS: dict[str, dict[str, str]] = {
    "spec":          {"InpExitManager": "0", "InpTPMode": "0",
                      "InpTradeTimeoutHours": "3"},
    "tp060":         {"InpExitManager": "0", "InpTPMode": "1",
                      "InpTPRMultiple": "0.60", "InpTradeTimeoutHours": "3"},
    "tp090":         {"InpExitManager": "0", "InpTPMode": "1",
                      "InpTPRMultiple": "0.90", "InpTradeTimeoutHours": "3"},
    "trail6h":       {"InpExitManager": "2", "InpTPMode": "0",
                      "InpTradeTimeoutHours": "6"},
    "trail6h_tp060": {"InpExitManager": "2", "InpTPMode": "1",
                      "InpTPRMultiple": "0.60", "InpTradeTimeoutHours": "6"},
}

VERIFY_KEYS = ("InpExitManager", "InpTPMode", "InpTPRMultiple",
               "InpTradeTimeoutHours")


def segment_inputs(config: str) -> dict[str, str]:
    """Complete explicit input set for one config cell."""
    return {**BASE_INPUTS, "InpTPRMultiple": "0.3", **CONFIGS[config]}


def spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rank correlation, no scipy. None when undefined (n < 2 or flat)."""
    n = len(a)
    if n < 2:
        return None

    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: xs[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    da = [x - sum(ra) / n for x in ra]
    db = [x - sum(rb) / n for x in rb]
    denom = (sum(x * x for x in da) * sum(x * x for x in db)) ** 0.5
    return sum(x * y for x, y in zip(da, db)) / denom if denom else None


def select_winner(cells: dict[str, dict], segment: str = "train") -> str:
    """Chosen on the selection segment's expectancy alone (PF breaks ties)."""
    pool = {n: c for n, c in cells[segment].items()
            if n in cells.get("test", cells[segment])}
    if not pool:
        raise ValueError("no config completed in both segments yet")
    ranked = sorted(pool.items(),
                    key=lambda kv: (-kv[1]["expectancy_r"], -kv[1]["pf"]))
    return ranked[0][0]


def transfer_summary(cells: dict[str, dict]) -> dict:
    """Train-selected winner vs the same config on untouched test data.

    Ranked over the configs present in BOTH segments (a partially completed run
    can have unequal sides), so this is safe to call mid-flight.
    """
    names = [n for n in cells["train"] if n in cells["test"]]
    if not names:
        raise ValueError("transfer needs at least one config present in both segments")
    winner = select_winner(cells, "train")

    def ranked(segment: str) -> list[str]:
        return sorted(names, key=lambda n: (-cells[segment][n]["expectancy_r"],
                                            -cells[segment][n]["pf"]))


    tr_rank = ranked("train").index(winner) + 1
    te_rank = ranked("test").index(winner) + 1
    return {
        "winner": winner,
        "winner_train_rank": tr_rank,
        "winner_test_rank": te_rank,
        "n_configs": len(names),
        "spearman_expectancy": spearman(
            [cells["train"][n]["expectancy_r"] for n in names],
            [cells["test"][n]["expectancy_r"] for n in names]),
        "train_fills": sum(c["fills"] for c in cells["train"].values()) // len(names),
        "test_fills": sum(c["fills"] for c in cells["test"].values()) // len(names),
        "sample_gate": (cells["train"][winner]["fills"] >= MIN_FILLS
                        and cells["test"][winner]["fills"] >= MIN_FILLS),
    }


def run_split(preset: str, segments: dict[str, tuple[str, str]],
              configs: list[str], out: Path) -> dict:
    cells: dict[str, dict] = {"train": {}, "test": {}}
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():                      # resume: keep cells already banked
        try:
            for seg in ("train", "test"):
                for name, cell in json.loads(out.read_text()).get("cells", {}).get(seg, {}).items():
                    if cell.get("config_verified"):
                        cells[seg][name] = cell
        except (OSError, ValueError):
            pass
        banked = sum(len(c) for c in cells.values())
        if banked:
            print(f"resume: {banked} cell(s) already banked in {out.name}", flush=True)

    def persist() -> None:
        """Cells land on disk as they arrive, so a long split survives a kill."""
        shared = [n for n in cells["train"] if n in cells["test"]]
        out.write_text(json.dumps({"preset": preset,
                                   "segments": {k: list(v) for k, v in segments.items()},
                                   "cells": cells,
                                   "summary": (transfer_summary(cells)
                                               if shared else None)},
                                  indent=1))

    for segment, (frm, to) in segments.items():
        for name in configs:
            if name in cells[segment]:
                print(f"{segment:5s} {name:15s} (banked, skipped)", flush=True)
                continue
            tag = f"wf{preset}_{segment}_{name}"
            r = run_pass(tag, segment_inputs(name),
                         dates=(frm, to), timeout_s=PASS_TIMEOUT_S)
            rep, j = r["report"], r["journal"]
            seen = report_inputs(tag, VERIFY_KEYS)
            expect = segment_inputs(name)
            cells[segment][name] = {
                "fills": rep["fills"], "pnl": round(rep["pnl"], 2),
                "pf": round(min(rep["pf"], 99), 3),
                "sl_hits": rep["sl_hits"], "tp_hits": rep["tp_hits"],
                "timeouts": j["timeouts"], "r_sum": j["r_sum"],
                "expectancy_r": round(j["r_sum"] / rep["fills"], 4) if rep["fills"] else 0.0,
                "seen": seen,
                "config_verified": all(seen.get(k) == expect.get(k)
                                       for k in VERIFY_KEYS if k in expect),
            }
            c = cells[segment][name]
            print(f"{segment:5s} {name:15s} fills {c['fills']:3d} "
                  f"pnl {c['pnl']:+9.2f} PF {c['pf']:5.2f} "
                  f"E {c['expectancy_r']:+.4f}R "
                  f"sl {c['sl_hits']:3d} tp {c['tp_hits']:2d} to {c['timeouts']:3d} "
                  f"| cfg_ok {c['config_verified']}", flush=True)
            persist()

    summary = transfer_summary(cells)
    payload = {"preset": preset, "segments": {k: list(v) for k, v in segments.items()},
               "cells": cells, "summary": summary}
    out.write_text(json.dumps(payload, indent=1))
    return payload


def render(payload: dict) -> str:
    s = payload["summary"]
    names = list(payload["cells"]["train"])
    lines = [f"preset {payload['preset']}  "
             f"train {payload['segments']['train'][0]}..{payload['segments']['train'][1]}  "
             f"test {payload['segments']['test'][0]}..{payload['segments']['test'][1]}",
             "",
             f"{'config':16s} {'train E':>9s} {'train PF':>9s} {'test E':>9s} {'test PF':>8s}"]
    for n in names:
        t, e = payload["cells"]["train"][n], payload["cells"]["test"][n]
        lines.append(f"{n:16s} {t['expectancy_r']:+9.4f} {t['pf']:9.2f} "
                     f"{e['expectancy_r']:+9.4f} {e['pf']:8.2f}")
    lines += ["",
              f"train-selected winner: {s['winner']} "
              f"(train rank {s['winner_train_rank']}/{s['n_configs']}, "
              f"test rank {s['winner_test_rank']}/{s['n_configs']})",
              f"spearman(train E, test E) = "
              f"{s['spearman_expectancy'] if s['spearman_expectancy'] is None else round(s['spearman_expectancy'], 3)}",
              f"fills: train ~{s['train_fills']}, test ~{s['test_fills']} "
              f"(gate {MIN_FILLS}) -> sample_gate {s['sample_gate']}"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="legacy")
    ap.add_argument("--train", nargs=2, metavar=("FROM", "TO"))
    ap.add_argument("--test", nargs=2, metavar=("FROM", "TO"))
    ap.add_argument("--configs", default=",".join(CONFIGS))
    args = ap.parse_args()

    name = args.preset
    segments = PRESETS[args.preset]
    if args.train and args.test:
        segments = {"train": tuple(args.train), "test": tuple(args.test)}
        name = "custom"
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in configs if c not in CONFIGS]
    if unknown:
        raise SystemExit(f"unknown config(s): {unknown}; known: {list(CONFIGS)}")

    payload = run_split(name, segments, configs, ARTIFACTS / f"walkforward_{name}.json")
    print()
    print(render(payload))


if __name__ == "__main__":
    main()

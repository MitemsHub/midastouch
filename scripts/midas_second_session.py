#!/usr/bin/env python3
"""The 24-hour study (`docs/SESSION24_PREREG_20260923.md`): the armed rule, all 24 hours.

The operator asked whether the EA can trade the full session intelligently. The session
gate is two preset inputs, so the question is empirical: does the ARMED RULE's own trigger
earn anything in the hours the certified window refuses to look at? The pass rule was
fixed in the pre-registration BEFORE any number below existed; this harness implements
that rule and cannot move it. `EVE-ADD` (the 18-04Z complement) is attribution only.

Structure mirrors `midas_sweep_shadow.py`: a pinned corpus law as self-check, then the
study, then the artifact.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402

ARTIFACT = Path("artifacts/midas_session24_20260923.json")
WINDOWS = ("wfv", "oos")


def _hour(book: list[dict]) -> int:
    """Entry hour, UTC — engine frame (the corpus is normalized by the window offset)."""
    return datetime.fromtimestamp(book["open_ct"], tz=timezone.utc).hour


def in_evening(hour: int) -> bool:
    """The 18:00-04:00Z complement, one definition, used everywhere."""
    return hour >= 18 or hour < 4


def window_fills(trades: list[dict], *, evening: bool) -> list[dict]:
    return [t for t in trades if in_evening(_hour(t)) == evening]


def t_stat(rs: list[float]) -> float:
    if len(rs) < 2:
        return 0.0
    m = sum(rs) / len(rs)
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (len(rs) - 1))
    if sd == 0:
        return 0.0
    return m / (sd / math.sqrt(len(rs)))


def summarize(trades: list[dict], t0: int, t1: int) -> dict:
    if not trades:
        return {"n": 0}
    rs = [t["r"] for t in trades]
    m = M.metrics(trades)
    days = max((t1 - t0) / 86400.0, 1e-9)
    return {"n": m["n"], "net_r": round(m["net_r"], 4),
            "mean_r": round(sum(rs) / len(rs), 4), "pf": round(m["pf"], 4),
            "max_dd_r": round(m["max_dd_r"], 3), "t": round(t_stat(rs), 3),
            "fills_per_day": round(len(rs) / days, 3)}


def law_ok(n: int, total: float) -> bool:
    """The pinned venue-corpus law: wfv defaults = 56 fills, +15.9352R."""
    return n == 56 and abs(total - 15.9352) < 5e-4


def self_check() -> None:
    """The pinned corpus law must reproduce, or nothing below means anything."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    n, total = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']} defaults: n={n} totalR={total:+.4f}")
    if not law_ok(n, total):
        raise SystemExit(f"REFUSED: corpus law moved (n={n} totalR={total:+.4f}); "
                         "the study would be measuring a different engine.")


def run() -> dict:
    out: dict = {"candidates": {}}
    for wname in WINDOWS:
        spec = P._window_spec(wname)
        corpus = spec.get("corpus", "frozen")
        data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus=corpus)
        t0, t1 = spec["t0"], spec["t1"]

        inc = M.run_mode(spec["mode"], t0, t1, data)                         # 04-18Z
        free = M.run_mode(spec["mode"], t0, t1, data, win_lo=0, win_hi=24)   # 24H

        # the 24H book, partitioned: the incumbent hours vs the evening complement.
        # Partition identity (pinned): day entries == incumbent book exactly; evening
        # entries == the complement the incumbent never saw.
        day, eve = window_fills(free.trades, evening=False), window_fills(free.trades, evening=True)
        inc_hours = {(t["open_ct"], t["side"]) for t in inc.trades}
        day_hours = {(t["open_ct"], t["side"]) for t in day}

        out["candidates"][wname] = {
            "window": {"t0": t0, "t1": t1, "corpus": corpus,
                       "iso": [datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
                               datetime.fromtimestamp(t1, tz=timezone.utc).isoformat()]},
            "incumbent": summarize(inc.trades, t0, t1),
            "h24": summarize(free.trades, t0, t1),
            "h24_day_part": summarize(day, t0, t1),
            "eve_complement": summarize(eve, t0, t1),
        # The engine holds ONE position: an evening fill occupies the slot and can
        # DISPLACE a certified day fill. This measures that displacement, not an
        # identity: day entries of the 24H book vs the incumbent book's fills.
        "slot_displacement": {"day_entries_match_incumbent":
                              day_hours == inc_hours,
                              "day_n": len(day_hours), "incumbent_n": len(inc_hours),
                              "displaced": len(inc_hours - day_hours)},
        }
    return out


def verdict(runs: dict) -> dict:
    """The pre-registered rule, implemented literally. Read from `oos` (held out)."""
    oos = runs["candidates"]["oos"]
    inc, h24 = oos["incumbent"], oos["h24"]
    wfv = runs["candidates"]["wfv"]

    checks = {
        "c1_net_r_not_lower": h24["net_r"] >= inc["net_r"],
        # pre-reg condition 2, dual reading exactly as written: met by margin
        # (mean >= +0.0155R AND t >= 1.96) OR by incumbent-parity (mean within
        # 0.02R of the incumbent's).
        "c2_mean_r_survives": ((h24["mean_r"] >= 0.0155 and h24["t"] >= 1.96)
                               or h24["mean_r"] >= inc["mean_r"] - 0.02),
        "c3_dd_within_3r": h24["max_dd_r"] <= inc["max_dd_r"] + 3.0,
        "c4_direction_agrees_wfv": wfv["h24"]["net_r"] >= wfv["incumbent"]["net_r"],
        "c5_activity_real": h24["fills_per_day"] >= 0.50,
    }
    eve = oos["eve_complement"]
    eve_clears = (eve.get("n", 0) >= 2 and eve["mean_r"] >= 0.0355 and eve["t"] >= 1.96)
    passed = all(checks.values())
    return {"passed": passed, "checks": checks,
            "eve_complement_clears_bar": eve_clears,
            "eve_complement": eve,
            "statement": ("PASS: the 24H preset earns an arming-record change"
                          if passed else
                          "FAIL: the incumbent window stays; retired until the evidence "
                          "base changes (forward shadow verdict or a new corpus era)")}


def main() -> int:
    self_check()
    runs = run()
    v = verdict(runs)
    art = {"study": "SESSION24_PREREG_20260923",
           "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
           "engine_law_self_check": {"window": "wfv", "n": 56, "net_r": 15.9352},
           "runs": runs, "verdict": v}
    ARTIFACT.write_text(json.dumps(art, indent=1))
    print(f"\nartifact: {ARTIFACT}")

    for wname in WINDOWS:
        c = runs["candidates"][wname]
        print(f"\n[{wname}]  incumbent n={c['incumbent'].get('n')} "
              f"netR={c['incumbent'].get('net_r', 0):+.3f} meanR={c['incumbent'].get('mean_r', 0):+.4f} "
              f"pf={c['incumbent'].get('pf', 0):.3f} dd={c['incumbent'].get('max_dd_r', 0):.2f}R")
        print(f"     24H      n={c['h24'].get('n')} "
              f"netR={c['h24'].get('net_r', 0):+.3f} meanR={c['h24'].get('mean_r', 0):+.4f} "
              f"pf={c['h24'].get('pf', 0):.3f} dd={c['h24'].get('max_dd_r', 0):.2f}R "
              f"fpd={c['h24'].get('fills_per_day', 0):.2f}")
        print(f"     eve complement: {c['eve_complement']}")
        print(f"     slot displacement: {c['slot_displacement']}")

    print(f"\nVERDICT: {'PASS' if v['passed'] else 'FAIL'}  ({v['statement']})")
    for k, ok in v["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k}")
    print(f"  eve complement clears the family bar (t>=1.96, mean>=+0.0355R): "
          f"{v['eve_complement_clears_bar']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Is the venue's spread actually flat across the day? The corpus says so; the arm measures.

WHY THIS FILE EXISTS. The session-hours finding (`docs/FREQUENCY_AXES_PREREG_20260922.md`,
and the session gate the EA has run since) rests on the venue's spread being FLAT across
UTC hours at ~0.2 pts — and that flatness was read off the CORPUS (the data of record),
never off the live feed. v1.27 gave the arm its own measurement
(`SPREADHOUR,<epoch>,<day>,` + 24 x `<hour>,<n>,<mean>,<max_x100>`, one row per UTC day).
This harness puts the two side by side and lets the live measurement falsify the premise
if it can — that is the only direction a comparison like this is worth anything in.

TWO SOURCES, TWO TRUTHS:
  * the corpus (`data/forex/xauusd/XAUUSD_M15_upcomers.csv`) carries each bar's spread in
    venue POINTS (an integer column) and each bar's true UTC stamp in its own `iso` field,
    so the hour classification uses the file's own declaration and NO server-offset era
    logic — a mis-pinned era would otherwise mis-date every hour silently;
  * the live rows come from the arm's ledger through `morning_status.spread_hours` (the one
    parser; it keeps zero-sample hours absent rather than reporting them as 0.0, which
    would read as the tightest hour of the day), whose `mean` is in PRICE units — divided
    by `midas_sweep.POINT` here so both sides speak POINTS.

VERDICTS, each stated before it was measured (the tolerance values are judgement, the
rule is not):
  PENDING              — the live side has no rows yet, or fewer than MIN_LIVE_HOURS hours
                         carrying MIN_LIVE_SAMPLES samples; nothing is claimed.
  FLATNESS HOLDS       — live max-hour/min-hour mean ratio <= LIVE_FLAT_RATIO (3.0: the
                         premise does not need perfect flatness, it needs no hour an
                         order of magnitude wider than another).
  FLATNESS VIOLATED    — that ratio exceeded: the session finding's cost premise is
                         false on the live venue, and the gate the finding produced is
                         measuring the wrong thing.
  PREMISE MISALIGNED   — flatness holds but the live tightest-hour mean exceeds
                         CORPUS_LIVE_TOLERANCE (2.0) x the corpus's own mean: the venue
                         is flat but at a different level than the corpus describes, so
                         every spread-derived cost model built on the corpus understates
                         the live venue.
The artifact records every per-hour number on both sides so a later reader can re-judge
with their own tolerance without re-measuring.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "tests"), os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import midas_sweep as M          # noqa: E402  POINT: price-unit -> point conversion
from morning_status import spread_hours   # noqa: E402  the ONE SPREADHOUR parser

# --- the rule, stated before the numbers exist ----------------------------------------
MIN_LIVE_HOURS = 6        # hours with samples needed before the live side may speak
MIN_LIVE_SAMPLES = 10     # samples per hour needed before that hour's mean may speak
LIVE_FLAT_RATIO = 3.0     # live max/min hour-mean ratio consistent with "flat"
CORPUS_LIVE_TOLERANCE = 2.0   # live-vs-corpus level drift consistent with the corpus model


def corpus_hourly_spread(path: str) -> dict:
    """Per-UTC-hour n / mean / max of the corpus's spread column, in POINTS.

    Hours are taken from each row's own `iso` field (true UTC), not from the
    server-stamped `time` epoch — the file declares its own clock, and reading the
    declaration costs nothing and cannot inherit a wrong era pin.
    """
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    maxima: dict[int, float] = defaultdict(float)
    with open(path) as fh:
        for r in csv.DictReader(fh):
            hour = dt.datetime.fromisoformat(r["iso"]).hour
            s = float(r["spread"])
            counts[hour] += 1
            sums[hour] += s
            maxima[hour] = max(maxima[hour], s)
    hours = {}
    for h, n in counts.items():
        hours[h] = {"n": n, "mean": sums[h] / n, "max": maxima[h]}
    return {"source": path, "hours": hours}


def session_slice(hours: dict, lo: int, hi: int) -> dict:
    """The hours the premise is about. The session finding's claim is that the venue
    is flat DURING the trading window — 21-23Z rollover hours at five-figure samples
    are the REASON a session gate exists, and letting them drive the verdict would
    test a claim nobody made."""
    return {h: v for h, v in hours.items() if lo <= h < hi}


def flatness(hours: dict) -> dict | None:
    """Ratio of widest to tightest sampled hour (n-weighted nothing: plain means)."""
    means = [v["mean"] for v in hours.values() if v["n"] > 0]
    if len(means) < 2:
        return None
    lo, hi = min(means), max(means)
    if lo <= 0:
        return None
    return {"min_hour_mean": lo, "max_hour_mean": hi, "ratio": hi / lo}


def verdict_for(live: dict | None, corpus: dict, *, lo: int = 4, hi: int = 18) -> dict:
    """The pre-stated rule, applied to the SESSION hours the gate trades. Both sides'
    full per-hour numbers ride the artifact either way."""
    out: dict = {"verdict": "PENDING", "session_utc": [lo, hi], "rule": {
        "min_live_hours": MIN_LIVE_HOURS, "min_live_samples": MIN_LIVE_SAMPLES,
        "live_flat_ratio": LIVE_FLAT_RATIO, "corpus_live_tolerance": CORPUS_LIVE_TOLERANCE}}
    c_hours = session_slice(corpus["hours"], lo, hi)
    out["corpus"] = {**corpus, "session_hours": c_hours,
                     "flatness": flatness(c_hours),
                     "flatness_all_hours": flatness(corpus["hours"])}
    if not live or not live.get("hours"):
        out["live"] = {"hours": {}, "note": "no SPREADHOUR rows yet"}
        return out
    speak = {h: v for h, v in live["hours"].items()
             if v["n"] >= MIN_LIVE_SAMPLES and lo <= h < hi}
    out["live"] = {**live, "hours_speaking": speak}
    if len(speak) < MIN_LIVE_HOURS:
        out["verdict"] = "PENDING"
        out["note"] = (f"only {len(speak)} in-session hour(s) carry >= {MIN_LIVE_SAMPLES} "
                       f"samples; the live side says nothing yet")
        return out
    live_flat = flatness(speak)
    out["live"]["flatness"] = live_flat
    if live_flat["ratio"] > LIVE_FLAT_RATIO:
        out["verdict"] = "FLATNESS VIOLATED"
        out["note"] = (f"widest live in-session hour {live_flat['max_hour_mean']:.2f} pts is "
                       f"{live_flat['ratio']:.1f}x the tightest "
                       f"({live_flat['min_hour_mean']:.2f} pts) — the flatness premise is "
                       f"false on the live venue")
        return out
    corpus_mean = sum(v["mean"] * v["n"] for v in c_hours.values()) / \
        sum(v["n"] for v in c_hours.values())
    out["corpus_mean_points"] = corpus_mean
    if live_flat["min_hour_mean"] > CORPUS_LIVE_TOLERANCE * corpus_mean:
        out["verdict"] = "PREMISE MISALIGNED"
        out["note"] = (f"live spread is flat but at {live_flat['min_hour_mean']:.2f} pts vs "
                       f"the corpus session mean's {corpus_mean:.2f} pts — corpus-derived "
                       f"cost models understate the live venue")
        return out
    out["verdict"] = "FLATNESS HOLDS"
    out["note"] = (f"live max/min in-session hour ratio {live_flat['ratio']:.2f} <= "
                   f"{LIVE_FLAT_RATIO} and the live level matches the corpus within "
                   f"tolerance")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", help="the arm's ledger CSV (default: resolved from the "
                                     "arming record's terminal, if any)")
    ap.add_argument("--corpus", default=os.path.join(ROOT, "data", "forex",
                                                     "xauusd", "XAUUSD_M15_upcomers.csv"))
    ap.add_argument("--session-lo", type=int, default=4, help="session window open, UTC hour")
    ap.add_argument("--session-hi", type=int, default=18, help="session window close, UTC hour")
    ap.add_argument("--out", help="artifact path (default artifacts/midas_spread_flatness_<ts>.json)")
    args = ap.parse_args()

    ledger = args.ledger
    if not ledger:
        import mt5_ops as R
        rec = R.arming_record() or {}
        tag = rec.get("arm")
        sym = rec.get("symbol") or "XAUUSD"
        df = R.data_folder_for_terminal()
        if df and tag:
            ledger = os.path.join(df, "MQL5", "Files", f"MIDASTOUCH_paper_{sym}_{tag}.csv")
    if not ledger or not os.path.isfile(ledger):
        print("no ledger to read (pass --ledger); reporting the corpus side only")
        live = None
    else:
        live = spread_hours(ledger)

    corpus = corpus_hourly_spread(args.corpus)
    result = verdict_for(live, corpus, lo=args.session_lo, hi=args.session_hi)
    result["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["ledger"] = ledger
    out = args.out or os.path.join(ROOT, "artifacts",
                                   f"midas_spread_flatness_{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(result, fh, indent=1)

    print(f"=== spread flatness: the corpus premise vs the arm's own measurement ===")
    ch = corpus["hours"]
    if ch:
        sh = session_slice(ch, args.session_lo, args.session_hi)
        s_means = {h: v["mean"] for h, v in sh.items()}
        a_means = {h: v["mean"] for h, v in ch.items()}
        print(f"corpus ({os.path.basename(args.corpus)}), in-session "
              f"{args.session_lo:02d}-{args.session_hi:02d}Z: "
              f"{min(s_means.values()):.2f}-{max(s_means.values()):.2f} pts, "
              f"ratio {max(s_means.values())/min(s_means.values()):.2f}")
        print(f"  (all 24 h for context: {min(a_means.values()):.2f}-"
              f"{max(a_means.values()):.2f} pts, ratio "
              f"{max(a_means.values())/min(a_means.values()):.2f} — the rollover hours "
              f"are why a session gate exists)")
    lh = (live or {}).get("hours") or {}
    if lh:
        print("live (ledger SPREADHOUR, points):")
        for h in sorted(lh):
            v = lh[h]
            print(f"  {h:02d}:00Z  n={v['n']:5d}  mean {v['mean']:.2f}  max {v['max_x100']}")
    else:
        print("live: no SPREADHOUR rows yet (they roll at each UTC day boundary)")
    print(f"VERDICT: {result['verdict']}")
    if result.get("note"):
        print(f"  {result['note']}")
    print(f"artifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

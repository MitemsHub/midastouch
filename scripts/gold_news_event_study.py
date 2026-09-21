#!/usr/bin/env python3
"""Which releases gold actually moves on, and how wide the blackout should be.

THE QUESTION. The playbook's policy is "no entries within +/-15 minutes of a top-tier USD
release", and V1.19c enforces it as `InpUseNewsFilter`. The width (15 minutes) and the
scope (every HIGH event the probe collected) were both inherited from policy text. Neither
has been measured, and the news sensitivity study showed the rule is not free: switching it
on re-selected a configuration in one fold, so it changes the strategy rather than sitting
on top of it. A rule with a cost has to earn its width.

WHY THE BASELINE IS HORIZON-MATCHED, WHICH IS THE WHOLE POINT OF THIS FILE. Gold's move
from a release is never compared to the average move of the day: it is compared to what
gold does over the SAME number of bars at the SAME UTC hour across the whole corpus. The
first version of this measurement used a fixed 15-minute baseline and reported "2.40x at
+/-60 min" — which is almost exactly the square-root-of-time scaling a random walk produces
(|60m| ~ 2 x |15m|), i.e. it measured the horizon, not the release. A horizon-matched
baseline makes the number say one thing: 1.00x is "indistinguishable from an ordinary
window of that length at that time of day", and anything above it is the release.

Only `close` is used, because the engine fills at closes: a move that no bar's close
records is a move this strategy could not have taken.

THE PRE-WINDOW COLUMN IS A CLOCK CHECK. A scheduled release should not move gold before it
is published. If pre-window moves were large, the calendar's epochs would sit off the
venue's bars — the same defect a timezone offset produces. The lag sweep makes that
visible rather than assumed: if the response peaks at a non-zero lag, the epochs are
misaligned by that much, and every blackout window would miss the move it exists to avoid.

WHAT IS NOT CLAIMED. MetaQuotes serves calendar HISTORY, so these are events as they are
known now: exact for exposure (which bars the rule suppresses), approximate for a live day
where a release can land at a revised time. This file does not decide the rule. It produces
the two numbers the decision needs — how much of a release's move a given half-width
captures, and how many entry opportunities that half-width costs — and the walk-forward,
not this file, says whether a width pays.

    python scripts/gold_news_event_study.py --calendar "<terminal>\\MQL5\\Files\\MIDASTOUCH_news_calendar.csv"
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_walkforward as W  # noqa: E402
import gold_news_sensitivity as NS  # noqa: E402
from mt5_data import load_m5  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

M15_SEC = 900
REF_MIN = 60
#: The reference horizon a release's two-sided move is measured against.
WIDTHS = (5, 10, 15, 30, 45, 60)
#: Widths whose close-to-close capture can be measured at M15 granularity. Below one bar
#: there are no two closes to difference, so capture there is 0 by construction, not by
#: measurement. Those widths still appear in the suppression columns: the mask does judge a
#: real bar close.
WIDTHS_CAPTURE = (15, 30, 45, 60)
LAGS_MIN = (-60, -45, -30, -15, 0, 15, 30, 45, 60)
#: Horizons, in bars, the per-hour baselines are built for. The binding case is not the lag
#: sweep but the widest window's own footprint for a release landing exactly on a bar close:
#: `blackout_footprint` then spans 2*REF_MIN/15 + 2 bars (60 minutes either side, rounded out
#: to the closes that bound them). Stating it as a formula rather than a literal is what
#: `test_the_baseline_covers_the_widest_footprint` checks, because a table one horizon short
#: does not misreport -- it silently returns None and the event disappears with no reason.
MAX_K = 2 * REF_MIN // 15 + 2
MIN_EVENTS_FOR_GROUP = 5


def load_corpus(symbol: str) -> dict:
    m15 = load_m5(symbol, timeframe=W.EXEC_TF, bars=60000)
    B = {k: m15.array[k].astype(float) for k in
         ("epoch", "open", "high", "low", "close", "spread", "volume")}
    B["atr"] = W.wilder_atr(B["high"], B["low"], B["close"], W.ATR_PERIOD)
    return B


def close_at(B: dict, t: float) -> int:
    """Index of the last bar whose CLOSE is at or before `t`, or -1."""
    i = int(np.searchsorted(B["epoch"] + M15_SEC, t, side="right")) - 1
    return i if 0 <= i < len(B["epoch"]) else -1


def hour_move_stats(B: dict) -> dict[int, list[np.ndarray]]:
    """Per UTC hour, per horizon in bars, the corpus's own |close(i+k) - close(i)| moves.

    This is the baseline the whole study rests on. Building it per hour means the ordinary
    volatility of that time of day is not mistaken for a release's effect; building it per
    horizon means the square-root-of-time scaling of a longer window is not mistaken for
    one either.
    """
    c = B["close"]
    n = len(c)
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in B["epoch"]], dtype=int)
    out: dict[int, list[np.ndarray]] = {}
    for h in range(24):
        idx = np.nonzero(hours == h)[0]
        out[h] = [np.abs(c[j + k] - c[j]) for k in range(MAX_K + 1)
                  for j in (idx[idx + k < n],)]
    return out


def abnormal(B: dict, stats: dict[int, list[np.ndarray]], hour: int,
             ri: int, ki: int) -> dict | None:
    """A move from close `ri` to close `ki`, in units of the same-hour same-length move."""
    k = ki - ri
    if k <= 0 or not (0 <= ri < len(B["epoch"])) or not (0 <= ki < len(B["epoch"])):
        return None
    arr = stats.get(hour, [])
    if k >= len(arr) or len(arr[k]) < 100:
        return None
    base = float(np.median(arr[k]))
    if base <= 0:
        return None
    d = abs(float(B["close"][ki]) - float(B["close"][ri]))
    return {"bars": k, "move": d, "baseline": base, "ratio": d / base,
            "pctile": float((arr[k] < d).mean()), "p90": float(np.percentile(arr[k], 90))}


def blackout_footprint(B: dict, epoch: float, w_min: int) -> tuple[int, int] | None:
    """The move a +/-w minute blackout sits across: last allowed entry before, first after.

    THE DEFINITION THAT MAKES THIS COMPARABLE ACROSS WIDTHS. The rule forbids entries at
    closes inside the window. The exposure it removes is therefore the path from the last
    close it would have allowed BEFORE the window to the first close it allows AFTER it --
    not from an arbitrary reference close, and not the move inside the window, which no
    position could ever have been opened into. This also makes the horizon a measured
    quantity rather than an assumed one, which is what the horizon-matched baseline needs.
    """
    lo = close_at(B, epoch - w_min * 60 - 1)
    hi = close_at(B, epoch + w_min * 60) + 1
    if lo < 0 or hi >= len(B["epoch"]) or hi <= lo:
        return None
    return lo, hi


def drop_reason(B: dict, stats: dict[int, list[np.ndarray]], ev: NC.Event) -> str:
    """Why this event cannot be measured; "" when it can.

    A drop reported as "unmeasurable" without saying why is indistinguishable from a bug
    that discarded the event, and this study's whole argument is that a refusal has to be
    legible. Three causes, in the order they are hit: the footprint runs off the corpus, the
    release's own UTC hour holds too little history to compare against (this venue's hour 23
    has one bar in the whole corpus, so its releases cannot be judged there at all), and --
    unreachable in practice, which is why it is named rather than assumed -- a reference
    window that measured while the footprint did not.
    """
    if measure(B, stats, ev) is not None:
        return ""
    hour = datetime.fromtimestamp(float(ev.epoch), timezone.utc).hour
    for w in WIDTHS:
        foot = blackout_footprint(B, ev.epoch, w)
        if foot is None:
            return "no bars"
        lo, hi = foot
        if abnormal(B, stats, hour, lo, hi) is None:
            return "no baseline"
    return "no reference window"


def measure(B: dict, stats: dict[int, list[np.ndarray]], ev: NC.Event) -> dict | None:
    """One release: the move across each width's blackout, and its capture of the widest."""
    hour = datetime.fromtimestamp(float(ev.epoch), timezone.utc).hour
    row = {"epoch": int(ev.epoch), "name": ev.name, "currency": ev.currency,
           "hour_utc": hour}
    raw: dict[int, float] = {}
    for w in WIDTHS:
        foot = blackout_footprint(B, ev.epoch, w)
        if foot is None:
            continue
        lo, hi = foot
        a = abnormal(B, stats, hour, lo, hi)
        if a is None:
            continue
        raw[w] = a["move"]
        row[f"bars_{w}"] = a["bars"]
        row[f"ratio_{w}"] = a["ratio"]
        row[f"pctile_{w}"] = a["pctile"]
        row[f"over_p90_{w}"] = a["move"] > a["p90"]
        row[f"move_{w}"] = a["move"]
    if REF_MIN not in raw or not raw[REF_MIN]:
        return None
    row["move_ref"] = raw[REF_MIN]
    for w in WIDTHS_CAPTURE:
        if w in raw:
            row[f"capture_{w}"] = min(1.0, raw[w] / raw[REF_MIN])
    # the clock check: the last bar of move BEFORE the release's own bar, same hour
    r0 = close_at(B, ev.epoch - 1)
    pre = abnormal(B, stats, hour, r0 - 1, r0) if r0 >= 1 else None
    row["pre_ratio"] = pre["ratio"] if pre else float("nan")
    return row


def lag_profile(B: dict, stats: dict[int, list[np.ndarray]], events, lags, w: int):
    """Where in time the response lands, swept in both directions at one window width."""
    out = []
    for lag in lags:
        ratios, over = [], 0
        for ev in events:
            hour = datetime.fromtimestamp(float(ev.epoch), timezone.utc).hour
            ri = close_at(B, ev.epoch + lag * 60 - 1)
            ki = close_at(B, ev.epoch + (lag + w) * 60)
            a = abnormal(B, stats, hour, ri, ki)
            if a is None:
                continue
            ratios.append(a["ratio"])
            over += a["move"] > a["p90"]
        if ratios:
            out.append({"lag_min": lag, "window_min": w, "n": len(ratios),
                        "median_ratio": float(statistics.median(ratios)),
                        "p75_ratio": float(np.percentile(ratios, 75)),
                        "over_p90_share": over / len(ratios)})
    return out


def width_table(rows: list[dict]) -> list[dict]:
    """Capture (what a width protects) beside suppression cost for the same width."""
    out = []
    for w in WIDTHS:
        hits = [r for r in rows if f"ratio_{w}" in r]
        if not hits:
            continue
        caps = [r[f"capture_{w}"] for r in hits if f"capture_{w}" in r]
        out.append({
            "width_min": w,
            "median_ratio": float(statistics.median([r[f"ratio_{w}"] for r in hits])),
            "median_bars": float(statistics.median([r[f"bars_{w}"] for r in hits])),
            "over_p90_share": sum(1 for r in hits if r[f"over_p90_{w}"]) / len(hits),
            "median_capture_of_release_move": (
                float(statistics.median(caps)) if caps else None),
            "n": len(hits),
        })
    return out


def exposure(B: dict, events: tuple[NC.Event, ...], currency: str | None) -> list[dict]:
    """Bars suppressed per width, and the entry-condition bars among them.

    The entry-condition count is the cost side: a suppressed bar where no entry was
    possible cost nothing. The conditions are the engine of record's own, restricted to the
    session window the strategy trades.
    """
    epoch = B["epoch"]
    n = len(epoch)
    atr = B["atr"]
    atr_lo = W.trailing_percentile(atr, W.ATR_LOOKBACK, W.ATR_LOW_PCT)
    atr_hi = W.trailing_percentile(atr, W.ATR_LOOKBACK, W.ATR_HIGH_PCT)
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)
    trend = np.zeros(n, dtype=bool)
    for emas in W.EMA_SETS:
        e_f, e_m, e_s = (W.ema(B["close"], p) for p in emas)
        trend |= ((e_f > e_m) & (e_m > e_s)) | ((e_f < e_m) & (e_m < e_s))
    band = np.array([not (np.isnan(atr[i]) or np.isnan(atr_lo[i]) or np.isnan(atr_hi[i]))
                     and atr_lo[i] < atr[i] <= atr_hi[i] and atr[i] > 0
                     for i in range(n)], dtype=bool)
    in_win = np.array([7 <= h <= 20 and h < W.FLAT_BY_UTC_HOUR for h in hours], dtype=bool)
    entry_ok = trend & band & in_win
    entry_ok[:W.WARMUP_BARS] = False

    sel = tuple(e for e in events if currency is None or e.currency == currency)
    out = []
    for w in WIDTHS:
        mask = NS.blackout_mask(epoch, sel, w)
        out.append({"width_min": w, "currency": currency or "ALL",
                    "bars": int(mask.sum()), "share": float(mask.mean()),
                    "entry_bars": int((mask & entry_ok).sum()),
                    "entry_bars_after_warmup": int((mask & entry_ok).sum())})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=W.SYMBOL)
    ap.add_argument("--calendar", help="the probe's calendar file (default: the running "
                                       "terminal's MQL5\\Files copy)")
    ap.add_argument("--out", default="artifacts/gold_news_event_study.json")
    a = ap.parse_args(argv)

    cal_path = Path(a.calendar) if a.calendar else NS.default_calendar()
    if cal_path is None or not cal_path.is_file():
        raise SystemExit(f"no calendar at {cal_path or '<unresolved>'} — attach "
                         f"mql5/MIDASTOUCH/MidasNewsProbe.mq5 once to write the venue's "
                         f"own feed")
    cal = NC.read_calendar(cal_path)
    highs = NC.top_tier_events(cal)

    B = load_corpus(a.symbol)
    epoch = B["epoch"]
    first, last = float(epoch[0]), float(epoch[-1])
    stats = hour_move_stats(B)
    currencies = sorted({e.currency for e in highs})
    print(f"calendar : {cal_path}")
    print(f"           {len(cal.events)} events, {len(highs)} HIGH "
          f"(currencies: {', '.join(currencies)})")
    print(f"corpus   : {len(epoch)} bars  "
          f"{datetime.fromtimestamp(first, timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(last, timezone.utc):%Y-%m-%d}  at {W.EXEC_TF}")
    print(f"baseline : |close-to-close| of the SAME length at the SAME UTC hour, "
          f"over the whole corpus (horizon-matched)")

    in_range = tuple(e for e in highs if first + 7200 < e.epoch < last - 7200)
    rows, dropped = [], {}
    for e in in_range:
        r = measure(B, stats, e)
        if r is not None:
            rows.append(r)
        else:
            why = drop_reason(B, stats, e)
            dropped[why] = dropped.get(why, 0) + 1
    if not rows:
        raise SystemExit("REFUSING: no HIGH event in the corpus could be measured")
    tail = "" if not dropped else " — " + ", ".join(
        f"{n} dropped for {why}" for why, n in sorted(dropped.items()))
    print(f"           {len(rows)} of {len(in_range)} HIGH events measurable{tail}\n")

    pre = [r["pre_ratio"] for r in rows if r["pre_ratio"] == r["pre_ratio"]]
    pre_ratio = float(statistics.median(pre))
    print("== clock check: does gold move BEFORE the release? ==")
    print(f"   one bar before the release, in units of that hour's ordinary bar: "
          f"{pre_ratio:.2f}x  (n={len(pre)})")
    print(f"   a scheduled release should be near 1.00x; materially above it would mean the "
          f"epochs sit off the bars\n")

    print("== does gold move on a HIGH release at all? (per half-width, horizon-matched) ==")
    print(f"   {'width':>6s} {'median':>8s} {'bars':>5s} {'over p90':>9s} {'n':>4s}   "
          f"(under the null, 10% of ordinary windows exceed the same p90)")
    wt = width_table(rows)
    for d in wt:
        cap = "   n/a" if d["median_capture_of_release_move"] is None \
            else f"{d['median_capture_of_release_move']:5.0%}"
        print(f"   {d['width_min']:4d}m {d['median_ratio']:7.2f}x {d['median_bars']:5.1f} "
              f"{d['over_p90_share']:8.0%} {d['n']:4d}   capture {cap}")

    print(f"\n== where in time the move lands (swept by lag) ==")
    prof = {w: lag_profile(B, stats, in_range, LAGS_MIN, w) for w in (15, 30)}
    print(f"   {'lag':>5s} {'15m window':>11s} {'over p90':>9s}   "
          f"{'30m window':>11s} {'over p90':>9s}")
    by_lag30 = {d["lag_min"]: d for d in prof[30]}
    for d in prof[15]:
        e = by_lag30.get(d["lag_min"])
        right = f"   {e['median_ratio']:10.2f}x {e['over_p90_share']:8.0%}" if e else ""
        print(f"   {d['lag_min']:+4d}m {d['median_ratio']:10.2f}x "
              f"{d['over_p90_share']:8.0%}{right}")
    for w in (15, 30):
        p = max(prof[w], key=lambda d: d["median_ratio"]) if prof[w] else None
        if p:
            print(f"   peak at width {w}m: lag {p['lag_min']:+d}m "
                  f"({p['median_ratio']:.2f}x)")

    by_name: dict[str, list[dict]] = {}
    by_ccy: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)
        by_ccy.setdefault(r["currency"], []).append(r)
    ccy_summary = [{"currency": c, "n": len(rs),
                    "median_ratio_15": float(statistics.median([r["ratio_15"] for r in rs])),
                    "over_p90_share_15": sum(1 for r in rs if r["over_p90_15"]) / len(rs)}
                   for c, rs in sorted(by_ccy.items(), key=lambda kv: -len(kv[1]))]
    named = [{"event": n_, "currency": rs[0]["currency"], "n": len(rs),
              "median_ratio_15": float(statistics.median([r["ratio_15"] for r in rs])),
              "median_ratio_60": float(statistics.median([r["ratio_60"] for r in rs])),
              "over_p90_share_15": sum(1 for r in rs if r["over_p90_15"]) / len(rs)}
             for n_, rs in by_name.items() if len(rs) >= MIN_EVENTS_FOR_GROUP]
    named.sort(key=lambda d: -d["median_ratio_15"])
    print(f"\n== releases with >={MIN_EVENTS_FOR_GROUP} occurrences, by 15-minute response ==")
    print(f"   {'event':34s} {'ccy':4s} {'n':>3s} {'15m':>7s} {'60m':>7s} {'over p90':>9s}")
    for d in named[:12]:
        print(f"   {d['event'][:33]:34s} {d['currency']:4s} {d['n']:3d} "
              f"{d['median_ratio_15']:6.2f}x {d['median_ratio_60']:6.2f}x "
              f"{d['over_p90_share_15']:8.0%}")
    quiet = [d for d in named if d["over_p90_share_15"] <= 0.10]
    print(f"   {len(quiet)} of {len(named)} named releases sit at or below the 10% rate a "
          f"no-effect window would show")

    exp_all = exposure(B, highs, None)
    exp_usd = exposure(B, highs, "USD")
    print(f"\n== the cost side: what each half-width suppresses ==")
    print(f"   {'width':>6s} {'capture':>9s} {'bars':>7s} {'entry bars':>11s} "
          f"{'entry bars USD-only':>19s}")
    cap_by_w = {d["width_min"]: d for d in wt}
    for ea, eu in zip(exp_all, exp_usd):
        c = cap_by_w[ea["width_min"]]
        cap = "      n/a" if c["median_capture_of_release_move"] is None \
            else f"{c['median_capture_of_release_move']:8.0%}"
        print(f"   {ea['width_min']:4d}m {cap} {ea['bars']:7d} {ea['entry_bars']:11d} "
              f"{eu['entry_bars']:19d}")
    print("   capture = share of the release's own +/-60 min move inside +/-w; it is n/a "
          "below 15 min because no two closes exist inside one bar.")
    print("   entry bars = suppressed bars where the engine of record's entry conditions "
          "held inside the trading session — the only cost that is real.")

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(json.dumps({
        "spec": {"symbol": a.symbol, "calendar": str(cal_path),
                 "calendar_generated_utc": cal.generated_utc,
                 "calendar_currencies": currencies,
                 "exec_tf": W.EXEC_TF, "ref_min": REF_MIN,
                 "widths": list(WIDTHS), "lags_min": list(LAGS_MIN),
                 "baseline": "per UTC hour, per horizon in bars: |close(i+k)-close(i)| "
                             "over the whole corpus (horizon- and hour-matched)",
                 "measured_from": "the close of the last bar at or before the release",
                 "caveat": "MetaQuotes serves calendar history: events as known now, exact "
                           "for exposure, approximate for a single live day"},
        "clock_check": {"median_pre_ratio": pre_ratio, "n": len(pre)},
        "events_measured": len(rows),
        "events_in_range": len(in_range),
        "events_dropped": dropped,
        "by_currency": ccy_summary,
        "by_event": named,
        "widths": wt,
        "lag_profile": {str(w): prof[w] for w in prof},
        "exposure_all": exp_all,
        "exposure_usd": exp_usd,
        "rows": rows,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

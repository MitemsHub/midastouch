"""Spike-continuation study (docs/SPIKE_CONTINUATION_STUDY.md, frozen 2026-09-15).

Position-free test of the cascade-correlation claim behind spike-path stop
overshoots: do fast/extreme bars that cross a 1R-away level CONTINUE after the
crossing tick more than slow controls do? Pure market mechanics on the tick
corpus -- no positions, no strategy.

Usage: python scripts/spike_continuation_study.py [--ticks TICKS_CSV]
Writes artifacts/v75_replay/spike_continuation_20260915.json and prints a summary.
"""
import argparse
import bisect
import csv
import json
import os
import random
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
DEFAULT_TICKS = os.path.join(HERE, "..", "artifacts", "data",
                             "volatility_75_index_ticks_fresh90.csv")
BAR_MS = 900_000
HORIZONS_MS = [5_000, 30_000, 120_000, 480_000]
SPEED_CUTOFF_MS = 600_000          # crossing within first 10 min of the bar
TRAIL_BARS = 96                    # 24h of M15 for the trailing range percentile


def load_bars(path):
    bars = []  # {key, o, h, l, c} mid-based; key = epoch//BAR_MS bucket
    cur = None
    cur_key = None
    with open(path) as f:
        rd = csv.reader(f)
        next(rd)
        for epoch_s, bid, ask in rd:
            t = int(epoch_s)
            key = t // BAR_MS
            mid = (float(bid) + float(ask)) / 2.0
            if key != cur_key:
                if cur is not None:
                    bars.append(cur)
                cur = {"key": key, "o": mid, "h": mid, "l": mid, "c": mid}
                cur_key = key
            else:
                cur["h"] = max(cur["h"], mid)
                cur["l"] = min(cur["l"], mid)
                cur["c"] = mid
    if cur is not None:
        bars.append(cur)
    return bars


def classify_crossings(bars):
    """Flag bars whose high/low crosses 1R (window-median M15 true range) beyond
    the prior close; assign frozen group labels."""
    trs = [max(b["h"] - b["l"], abs(b["h"] - bars[i - 1]["c"]),
               abs(bars[i - 1]["c"] - b["l"])) for i, b in enumerate(bars)]
    R = st.median(trs)
    events = []  # (bar_idx, dir, level)
    for i in range(1, len(bars)):
        if i < TRAIL_BARS:
            continue
        pc = bars[i - 1]["c"]
        window = sorted(trs[i - TRAIL_BARS:i])
        p90 = window[int(0.90 * (len(window) - 1))]
        p70 = window[int(0.70 * (len(window) - 1))]
        rng = bars[i]["h"] - bars[i]["l"]
        extreme = rng > p90
        small = rng < p70
        if bars[i]["l"] <= pc - R:
            events.append({"bar": i, "dir": -1, "level": pc - R,
                           "extreme": extreme, "small": small})
        if bars[i]["h"] >= pc + R:
            events.append({"bar": i, "dir": +1, "level": pc + R,
                           "extreme": extreme, "small": small})
    return events, R


def collect_tick_buffers(path, buffer_bars):
    """Second pass: keep ticks only for bars in buffer_bars (a set of indices)."""
    bufs = {}
    cur_key = None
    idx = -1
    with open(path) as f:
        rd = csv.reader(f)
        next(rd)
        for epoch_s, bid, ask in rd:
            t = int(epoch_s)
            key = t // BAR_MS
            if key != cur_key:
                cur_key = key
                idx += 1
            if idx in buffer_bars:
                bufs.setdefault(idx, []).append((t, (float(bid) + float(ask)) / 2.0))
    return bufs


def continuations(bufs, events, bars, R):
    """For each event find the crossing tick, then mid at ts+d for each horizon."""
    out = []
    for ev in events:
        k = ev["bar"]
        key = bars[k]["key"]
        ticks = bufs.get(k)
        if not ticks:
            continue
        ts_lo, ts_hi = key * BAR_MS, (key + 1) * BAR_MS
        fut = []
        for kk in (k, k + 1, k + 2):
            fut.extend(bufs.get(kk, []))
        fut.sort()
        fts = [t for t, _ in fut]
        # crossing tick: first tick in the bar at/beyond the level
        cross_ts = cross_mid = None
        for t, m in ticks:
            if t < ts_lo:
                continue
            if (ev["dir"] < 0 and m <= ev["level"]) or (ev["dir"] > 0 and m >= ev["level"]):
                cross_ts, cross_mid = t, m
                break
        if cross_ts is None:
            continue
        speed_fast = (cross_ts - ts_lo) <= SPEED_CUTOFF_MS
        if speed_fast and ev["extreme"]:
            grp = "spike"
        elif (not speed_fast) or ev["small"]:
            grp = "slow"
        else:
            grp = "fast"
        rec = {"grp": grp, "dir": ev["dir"], "cross_s": (cross_ts - ts_lo) / 1000.0,
               "cont": {}}
        for d in HORIZONS_MS:
            j = bisect.bisect_right(fts, cross_ts + d) - 1
            if j < 0:
                continue
            rec["cont"][d] = ev["dir"] * (fut[j][1] - cross_mid) / R
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", default=DEFAULT_TICKS)
    args = ap.parse_args()

    bars = load_bars(args.ticks)
    events, R = classify_crossings(bars)
    need = set()
    for ev in events:
        need.update((ev["bar"], ev["bar"] + 1, ev["bar"] + 2))
    bufs = collect_tick_buffers(args.ticks, need)
    recs = continuations(bufs, events, bars, R)

    groups = ("spike", "fast", "slow")
    summary = {g: {"n": 0} for g in groups}
    for g in groups:
        sel = [r for r in recs if r["grp"] == g]
        summary[g]["n"] = len(sel)
        for d in HORIZONS_MS:
            vals = [r["cont"][d] for r in sel if d in r["cont"]]
            if vals:
                summary[g][f"mean_{d//1000}s"] = round(st.mean(vals), 4)
                summary[g][f"med_{d//1000}s"] = round(st.median(vals), 4)
                summary[g][f"p_pos_{d//1000}s"] = round(sum(v > 0 for v in vals) / len(vals), 3)
                summary[g][f"n_{d//1000}s"] = len(vals)
                adv = [-v for v in vals if v < 0]
                summary[g][f"med_adverse_{d//1000}s"] = round(st.median(adv), 4) if adv else 0.0

    # frozen primary statistic: d2min = mean(spike@2min) - mean(slow@2min)
    sp = [r["cont"][120_000] for r in recs if r["grp"] == "spike" and 120_000 in r["cont"]]
    sl = [r["cont"][120_000] for r in recs if r["grp"] == "slow" and 120_000 in r["cont"]]
    labels = ["spike"] * len(sp) + ["slow"] * len(sl)
    pooled = sp + sl
    obs = st.mean(sp) - st.mean(sl) if sp and sl else None
    rng = random.Random(20260915)
    if obs is not None:
        ge = 0
        for _ in range(10_000):
            rng.shuffle(labels)
            a = [v for v, l in zip(pooled, labels) if l == "spike"]
            b = [v for v, l in zip(pooled, labels) if l == "slow"]
            if st.mean(a) - st.mean(b) >= obs:
                ge += 1
        perm_p = ge / 10_000
        boot = []
        for _ in range(20_000):
            a = [rng.choice(sp) for _ in sp]
            b = [rng.choice(sl) for _ in sl]
            boot.append(st.mean(a) - st.mean(b))
        boot.sort()
        ci = (boot[500], boot[19500])
    else:
        perm_p, ci = None, None

    out = {
        "schema": "mitemshub.artifact-spec.v1",
        "artifact": "spike_continuation",
        "generated": "2026-09-15",
        "design": "docs/SPIKE_CONTINUATION_STUDY.md (frozen before run)",
        "ticks_file": os.path.basename(args.ticks),
        "bars": len(bars),
        "R_median_m15_tr": round(R, 2),
        "crossing_events_raw": len(events),
        "events_with_continuation": len(recs),
        "groups": summary,
        "primary": {
            "stat": "mean(cont 2min | spike) - mean(cont 2min | slow), R units",
            "delta_2min": round(obs, 4) if obs is not None else None,
            "permutation_p_10k": perm_p,
            "bootstrap_ci95_20k": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "claim_holds": bool(obs is not None and obs > 0 and perm_p < 0.05
                                and summary["spike"].get("mean_30s", 0) > summary["slow"].get("mean_30s", 0)
                                and summary["spike"].get("mean_480s", 0) > summary["slow"].get("mean_480s", 0)),
        },
    }
    path = os.path.join(DATA, "spike_continuation_20260915.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out["groups"], indent=1))
    print("\nPRIMARY delta2min =", out["primary"]["delta_2min"],
          " perm p =", perm_p, " CI =", out["primary"]["bootstrap_ci95_20k"],
          "\nCLAIM:", out["primary"]["claim_holds"])
    print("artifact:", path)


if __name__ == "__main__":
    main()

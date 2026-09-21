#!/usr/bin/env python3
"""How much of the measured drift do the exits give back? (exit-side, not entry-side)

THE MEASUREMENT THAT MOTIVATES THIS. `scripts/gold_trigger_edge.py` measured forward drift
after every signal bar at **+0.113 ATR (2h, t=+3.5)** and **+0.177 ATR (4h, t=+4.0)** with
no exit rule attached — while the same entries through the strategy's own exits average
about zero. The trigger is therefore not the binding constraint; the exit is. This study
measures the gap three ways:

  1. **Excursion.** For each entry, the maximum favourable and adverse excursion in R over
     4/8/16/32/48 bars — i.e. what the market actually offered after the signal.
  2. **Policy sweep.** A grid of exit policies applied to those SAME entries through the
     frozen engine's cost model: fixed stop/target pairs, trailing stops with declared
     activation/trail distances, and pure time exits.
  3. **Capture.** For each policy, mean net R as a fraction of the mean favourable
     excursion at the matching horizon — "how much of the move this exit actually keeps",
     after the spread and the commission are paid.

Exit marks are the same pessimistic convention as the frozen engine: a stop or target
touched inside one bar assumes the STOP first, a bar that gaps through the stop fills at
its open, and every position is flat by 22:00 UTC. Trailing marks use bar CLOSES, which is
the conservative reading for a trail (a tick-level trail would exit earlier and better).

Everything here is exploration on the gate's own window — the report says so, and the
artifact records it. Nothing in this file can pass the gate.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg  # noqa: E402
import gold_walkforward as gw  # noqa: E402

#: Entries come from the widest declared config so the exit study is not pre-filtered by a
#: session window; the exits are then varied while the entries are held FIXED.
ENTRY_CFG = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 3.0, "win_lo": 0, "win_hi": 24}
HORIZONS = (4, 8, 16, 32, 48)
FIXED_TPS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0)
TRAILS = ((1.0, 1.0), (1.0, 0.5), (0.5, 0.5))   # (activation R, trail distance R)
TIMES = (4, 8, 16)


def excursions(bars: dict, entry_i: int, dir_: int, entry: float, risk: float,
               max_bars: int) -> tuple[float, float, int]:
    """(MFE, MAE) in R and the bar count actually available (flat by 22:00 UTC)."""
    high, low, epoch = bars["high"], bars["low"], bars["epoch"]
    mfe = mae = 0.0
    k = 0
    i = entry_i + 1
    end = min(len(high), entry_i + 1 + max_bars)
    while i < end:
        if datetime.fromtimestamp(float(epoch[i]), timezone.utc).hour >= gw.FLAT_BY_UTC_HOUR:
            break
        up = dir_ * (float(high[i]) - entry) / risk
        dn = dir_ * (float(low[i]) - entry) / risk
        mfe, mae = max(mfe, up), min(mae, dn)
        k += 1
        i += 1
    return mfe, mae, k


def simulate_policy(bars: dict, entries: list[dict], atr: np.ndarray, *, tp: float | None,
                    trail: tuple[float, float] | None, time_bars: int | None) -> list[dict]:
    """Apply one exit policy to the FIXED entry set, with the frozen cost model.

    Stop = 1.0 x ATR (the certified family's stop), so every policy shares one risk unit and
    the comparison is about exits, not about sizing.
    """
    o, h, l, c, epoch = (bars["open"], bars["high"], bars["low"], bars["close"],
                         bars["epoch"])
    out: list[dict] = []
    for e in entries:
        i0, dir_, entry = e["entry_i"], e["dir"], e["entry"]
        risk = float(atr[i0])
        if risk <= 0:
            continue
        stop = entry - dir_ * risk
        peak = entry
        target = entry + dir_ * tp * risk if tp is not None else None
        limit = i0 + (time_bars if time_bars is not None else 48)
        px = None
        j = i0
        while True:
            j += 1
            if j >= len(c) or j > limit:
                px = float(c[min(j, len(c) - 1)])
                break
            if datetime.fromtimestamp(float(epoch[j]), timezone.utc).hour >= gw.FLAT_BY_UTC_HOUR:
                px = float(o[j])
                break
            if trail is not None:
                # Trail on the previous bar's CLOSE: activation, then a stop that follows
                # the best close, never loosening.
                run = dir_ * (float(c[j - 1]) - entry) / risk
                if run >= trail[0]:
                    peak = max(peak, float(c[j - 1]))
                    stop = max(stop, peak - dir_ * trail[1] * risk) if dir_ > 0 else \
                        min(stop, peak + abs(trail[1]) * risk)
            if dir_ > 0:
                if float(o[j]) <= stop:
                    px = float(o[j])
                elif float(l[j]) <= stop:
                    px = stop
                elif target is not None and float(h[j]) >= target:
                    px = target
            else:
                if float(o[j]) >= stop:
                    px = float(o[j])
                elif float(h[j]) >= stop:
                    px = stop
                elif target is not None and float(l[j]) <= target:
                    px = target
            if px is not None:
                break
        gross = dir_ * (px - entry) / risk
        spread_r = (gw.SPREAD_BPS / 1e4 * entry) / risk
        comm_r = gw.COMMISSION_PER_LOT_RT / (risk * gw.USD_PER_UNIT_PER_LOT)
        out.append({"entry_i": i0, "exit_i": j, "dir": dir_, "gross_r": gross,
                    "net_r": gross - spread_r - comm_r, "bars": j - i0})
    return out


def stats(rs: list[float]) -> dict:
    n = len(rs)
    if n < 2:
        return {"n": n, "mean_r": None, "t": None}
    mean = sum(rs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1))
    return {"n": n, "mean_r": round(mean, 4), "sd": round(sd, 4),
            "t": round(mean / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0,
            "total_r": round(sum(rs), 3)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_exit_capture.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    entries = gg.run_grid(B, hours, ok, atr, ENTRY_CFG, n)
    print(f"entries held FIXED at {len(entries)} (session 0-24, stop 1.0xATR); "
          f"only the exit varies\n")

    # ---- 1. what the market offered --------------------------------------- #
    print("== excursion after the signal, in R (risk = 1.0 x ATR at the entry bar) ==")
    print(f"{'horizon':>8} {'n':>6} {'MFE':>8} {'MAE':>8} {'MFE in ATR':>11} {'t(MFE)':>8}")
    exc: dict[int, list[dict]] = {}
    atr_ratio = []
    for hz in HORIZONS:
        rows = []
        for e in entries:
            i0 = e["entry_i"]
            risk = float(atr[i0])
            if risk <= 0:
                continue
            mfe, mae, k = excursions(B, i0, e["dir"], e["entry"], risk, hz)
            if k == 0:
                continue
            rows.append({"mfe": mfe, "mae": mae, "mfe_atr": mfe * risk / float(atr[i0])})
        mfes = [r["mfe"] for r in rows]
        st = stats(mfes)
        mean_atr = sum(r["mfe_atr"] for r in rows) / len(rows)
        exc[hz] = rows
        print(f"{hz:>8} {len(rows):>6} {st['mean_r']:>8.3f} "
              f"{sum(r['mae'] for r in rows) / len(rows):>8.3f} {mean_atr:>11.3f} "
              f"{st['t']:>8.2f}")

    # ---- 2/3. the policy sweep and its capture ---------------------------- #
    print("\n== exit policies applied to the SAME entries (costs included) ==")
    print(f"{'policy':<22} {'n':>5} {'mean netR':>10} {'t':>6} {'total':>9} "
          f"{'capture of MFE@8':>16}")
    mfe8 = [r["mfe"] for r in exc[8]]
    mfe8_mean = sum(mfe8) / len(mfe8) if mfe8 else 0.0
    policies: list[dict] = []
    for tp in (None, *FIXED_TPS):
        label = "fixed stop 1.0 only" if tp is None else f"fixed stop1.0 tp{tp}"
        tr = simulate_policy(B, entries, atr, tp=tp, trail=None, time_bars=None)
        st = stats([t["net_r"] for t in tr])
        cap = (st["mean_r"] / mfe8_mean) if mfe8_mean else 0.0
        policies.append({"policy": label, **st, "capture_of_mfe8": round(cap, 3)})
        print(f"{label:<22} {st['n']:>5} {st['mean_r']:>10.4f} {st['t']:>6.2f} "
              f"{st['total_r']:>9.1f} {cap:>16.1%}")
    for act, dist in TRAILS:
        label = f"trail act{act} dist{dist}"
        tr = simulate_policy(B, entries, atr, tp=None, trail=(act, dist), time_bars=None)
        st = stats([t["net_r"] for t in tr])
        cap = (st["mean_r"] / mfe8_mean) if mfe8_mean else 0.0
        policies.append({"policy": label, **st, "capture_of_mfe8": round(cap, 3)})
        print(f"{label:<22} {st['n']:>5} {st['mean_r']:>10.4f} {st['t']:>6.2f} "
              f"{st['total_r']:>9.1f} {cap:>16.1%}")
    for tb in TIMES:
        label = f"time exit {tb} bars"
        tr = simulate_policy(B, entries, atr, tp=None, trail=None, time_bars=tb)
        st = stats([t["net_r"] for t in tr])
        cap = (st["mean_r"] / mfe8_mean) if mfe8_mean else 0.0
        policies.append({"policy": label, **st, "capture_of_mfe8": round(cap, 3)})
        print(f"{label:<22} {st['n']:>5} {st['mean_r']:>10.4f} {st['t']:>6.2f} "
              f"{st['total_r']:>9.1f} {cap:>16.1%}")

    best = max(policies, key=lambda p: (p["mean_r"] or -9))
    print(f"\nbest policy: {best['policy']} -> {best['mean_r']:+.4f}R/trade "
          f"(t={best['t']}, n={best['n']}), capturing {best['capture_of_mfe8']:.1%} of the "
          f"mean 8-bar favourable excursion ({mfe8_mean:.3f}R)")
    print(f"the trigger's raw drift was +0.113 ATR at 8 bars and +0.177 ATR at 16; "
          f"the certified exit captures {policies[1]['capture_of_mfe8']:.1%} of the 8-bar one")
    print("\nEXPLORATION on the gate's own window: a hypothesis, never a pass.")

    out = {"spec": {"symbol": a.symbol, "bars": n, "entry_config": ENTRY_CFG,
                    "entry_count": len(entries),
                    "window": [str(datetime.fromtimestamp(epoch[0], timezone.utc)),
                               str(datetime.fromtimestamp(epoch[-1], timezone.utc))],
                    "note": "exploration on the gate's window — nothing here is a pass"},
           "excursions": {str(hz): stats([r["mfe"] for r in rows])
                          for hz, rows in exc.items()},
           "mfe8_mean_r": round(mfe8_mean, 4),
           "policies": policies, "best": best}
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

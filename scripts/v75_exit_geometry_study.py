"""V75 exit-geometry forensics: why does the spec engine lose on exits?

Path-traces the real trades of a Strategy Tester pass (deals from the tester
report, price paths from the cached M5 series) and measures each trade's
favourable/adverse excursion in H1-ATR(14) units within its lifecycle.

Finding this study established (71-day v2.00 window): typical MFE is ~0.6
H1-ATR while the spec TP sits at 4.0 ATR and the SL at 2.0 ATR — neither rail
is ever touched, so ~91% of trades are 3h timeout coin flips net of spread.

Usage:  python scripts/v75_exit_geometry_study.py [report_tag]
        (default tag: v200_verify)
"""
from __future__ import annotations

import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from mt5_data import load_m5  # noqa: E402
from v75_tester_runner import TERMINAL_DATA, pair_trades, parse_report  # noqa: E402

WINDOW = ("2026.07.01", "2026.09.10")
TIMEOUT_H = 3.0
ATR_PERIOD = 14
SL_ATR, TP_ATR = 2.0, 4.0


def h1_bars(m5: list[dict]) -> list[dict]:
    out, cur = [], None
    for b in m5:
        hour = int(b["epoch"] // 3600) * 3600
        if cur is None or hour != cur["epoch"]:
            if cur:
                out.append(cur)
            cur = {"epoch": hour, "open": b["open"], "high": b["high"],
                   "low": b["low"], "close": b["close"]}
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
    if cur:
        out.append(cur)
    return out


def atr_at(h1: list[dict], t: float) -> float:
    """ATR(ATR_PERIOD) over the ATR_PERIOD TRs ending at the last H1 bar
    fully closed at time t (same window as the EA's Wilder seed)."""
    idx = max(i for i, b in enumerate(h1) if b["epoch"] + 3600 <= t + 1)
    if idx < ATR_PERIOD:
        return 0.0
    trs = []
    for j in range(idx - ATR_PERIOD + 1, idx + 1):
        h, l, pc = h1[j]["high"], h1[j]["low"], h1[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / ATR_PERIOD


def m5_series() -> list[dict]:
    bars = load_m5("Volatility 75 Index", "M5", prefer_cache=True)
    lo = datetime.strptime(WINDOW[0], "%Y.%m.%d").replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.strptime(WINDOW[1], "%Y.%m.%d").replace(tzinfo=timezone.utc).timestamp()
    return [b for b in bars if lo <= b["epoch"] <= hi]


def main() -> None:
    tag = sys.argv[1] if len(sys.argv) > 1 else "v200_verify"
    assert (TERMINAL_DATA / f"V75_regress_{tag}.htm").exists(), f"no report for {tag}"
    deals = parse_report(tag)["deals"]
    trades = pair_trades(deals)
    m5 = m5_series()
    h1 = h1_bars(m5)

    def ts(s: str) -> float:
        return datetime.strptime(s, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()

    # The npz M5 cache slides forward (20k bars); trades older than cache start
    # plus an ATR warmup cannot be path-traced and are excluded.
    first_usable = h1[ATR_PERIOD - 1]["epoch"] if len(h1) > ATR_PERIOD else 0
    traceable = [t for t in trades if ts(t["entry_time"]) >= first_usable]
    print(f"deals={len(trades)}  path-traceable={len(traceable)}  "
          f"(cache starts {datetime.fromtimestamp(m5[0]['epoch'], timezone.utc):%m-%d %H:%M}, "
          f"excluded {len(trades) - len(traceable)} early trade[s])")
    print(f"{'#':>2} {'dir':<4} {'entry':<17} {'ATR':>8} {'SLdist':>8} {'TPdist':>8} "
          f"{'MFE_atr':>8} {'MAE_atr':>8} {'TTP_h':>6} {'exitR':>7}")

    rows = []
    for k, t in enumerate(traceable, 1):
        atr = atr_at(h1, ts(t["entry_time"]))
        if atr <= 0:
            continue
        sl_d = SL_ATR * atr
        sign = 1 if t["side"] == "buy" else -1
        entry = t["entry_price"]
        end = min(ts(t["entry_time"]) + TIMEOUT_H * 3600, m5[-1]["epoch"])
        mfe = mae = 0.0
        ttp = TIMEOUT_H
        for b in m5:
            eb = b["epoch"]
            if eb < ts(t["entry_time"]):
                continue
            if eb > end:
                break
            fav = sign * (b["high"] - entry)
            adv = sign * (entry - b["low"])
            if fav > mfe:
                mfe, ttp = fav, (eb - ts(t["entry_time"])) / 3600
            mae = max(mae, adv)
        r = sign * (t["exit_price"] - entry) / sl_d if t["exit_price"] else 0.0
        rows.append({"atr": atr, "mfe": mfe, "mae": mae})
        print(f"{k:>2} {t['side']:<4} {t['entry_time'][5:16]:<17} {atr:>8.1f} "
              f"{sl_d:>8.1f} {TP_ATR * atr:>8.1f} {mfe/atr:>8.2f} {mae/atr:>8.2f} "
              f"{ttp:>6.2f} {r:>+7.2f}")

    if not rows:
        print("no trades to analyze")
        return
    mfes = [x["mfe"] / x["atr"] for x in rows]
    maes = [x["mae"] / x["atr"] for x in rows]
    print(f"\nMFE (ATR units): mean={st.mean(mfes):.2f} median={st.median(mfes):.2f} "
          f"max={max(mfes):.2f}  | >=1.0R: {sum(1 for x in mfes if x >= 1.0)}/{len(mfes)}"
          f"  >=1.5R: {sum(1 for x in mfes if x >= 1.5)}/{len(mfes)}"
          f"  >=2.0R: {sum(1 for x in mfes if x >= 2.0)}/{len(mfes)}")
    print(f"MAE (ATR units): mean={st.mean(maes):.2f} median={st.median(maes):.2f} "
          f"max={max(maes):.2f}  | reaching -1.0R: {sum(1 for x in maes if x >= 1.0)}/{len(maes)}")


if __name__ == "__main__":
    main()

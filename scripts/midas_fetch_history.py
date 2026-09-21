#!/usr/bin/env python3
"""MIDASTOUCH Step 2b — XAUUSD history download + validation (fail-closed).

Pulls the full bar depth the terminal offers for XAUUSD (and XAUUSD for
reference) at M15/H1/D1, writes CSVs under data/forex/xauusd/, and runs the
ANCIENT_WINDOW validation pattern:
  V1  bar count vs calendar (24/5 market: D1 5 bars/week, H1 ~120/wk)
  V2  gap scan — no bar older than the previous + a tolerance
  V3  OHLC sanity — high>=max(open,close), low<=min(open,close), all > 0
  V4  day-of-week calendar — trades Mon..Fri only (Sat should be ~absent)
Validation failures are reported loudly; the artifact records every check.

PROVENANCE IS PART OF THE OUTPUT. The artifact records which terminal, data folder and
account the bars came from, because the corpus in data/forex/xauusd/ was fetched (from
the DERIV install, 2026-09-17) for an account that now trades Upcomers — whose own
XAUUSD history begins 2026-01-12 13:15, i.e. 60% of the walk-forward window does not
exist at the venue the strategy is certified for. An unlabelled corpus is how that
stays invisible.

Output: data/forex/xauusd/<SYMBOL>_<TF><suffix>.csv + artifacts/midas_history_<date>.json
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

#: The install is resolved at run time from the account registry (mt5_ops), NEVER
#: hardcoded. It used to be `C:\Program Files\MetaTrader 5 Terminal\terminal64.exe` —
#: the DERIV install, which no longer exists on this machine. That is how the corpus in
#: data/forex/xauusd/ came to be another venue's gold series while the funded account
#: trades Upcomers, whose own XAUUSD history begins 2026-01-12 13:15. Every run now
#: records the terminal, data folder and account it actually read, so a corpus can never
#: again be mistaken for the venue it did not come from.
TERMINAL_EXE = ""          # set in main() from mt5_ops.terminal_exe()
OUT_DIR = os.path.join("data", "forex", "xauusd")
ART = "artifacts"
SYMBOLS = ["XAUUSD"]       # was ["XAUUSD", "XAUUSD"]: the same symbol twice, so the
#                            second pass rewrote the first's CSVs for no reason.
TFS = {"H1": 16385, "M15": 15, "D1": 16408}
# (MetaTrader5.TIMEFRAME_* constants inlined to keep the module import-free
# of a hard dependency at module import time; values are stable ABI constants.)
TF_LADDER = (1000, 5000, 20000, 50000, 100000, 200000)


def rates_with_retry(mt5, name: str, tf: int, count: int,
                     attempts: int = 4, sleep_s: float = 3.0):
    """copy_rates_from_pos can return None on a transient IPC miss (cold
    history, busy terminal). Bounded retry, honest None afterwards."""
    for k in range(attempts):
        bars = mt5.copy_rates_from_pos(name, tf, 0, count)
        if bars is not None and len(bars):
            return bars
        if k < attempts - 1:
            time.sleep(sleep_s)
    return None


def warm_up(mt5, name: str, tf: int) -> bool:
    """The first history request after attach often misses while the terminal
    builds the cache. Ping a tiny slice until it answers (bounded), so the
    real pulls never race the cache build."""
    for _ in range(8):
        bars = mt5.copy_rates_from_pos(name, tf, 0, 10)
        if bars is not None and len(bars):
            return True
        time.sleep(3.0)
    return False


def max_depth(mt5, name: str, tf: int) -> int:
    best = 0
    for want in TF_LADDER:
        bars = rates_with_retry(mt5, name, tf, want)
        if bars is None or len(bars) == 0:
            break
        best = len(bars)
        if len(bars) < want:
            break
    return best


def validate(bars: list[dict], tf_name: str) -> dict:
    """V1..V4 checks; each returns (ok, detail)."""
    res: dict = {}
    if not bars:
        return {"empty": (False, "no bars")}

    first = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
    last = datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc)
    days = (last - first).total_seconds() / 86400
    res["span_days"] = (True, round(days, 1))

    # V1 bar count vs calendar — 24/5 market. M15/H1: weekdays only (the
    # Sunday reopen adds only small intraday bars). D1: Deriv stamps a bar at
    # every Sunday reopen, so a week carries 6 daily bars — measured over
    # CALENDAR weeks (Sun..Fri), not weekdays.
    if tf_name == "D1":
        expect = days / 7 * 6
    else:
        weekdays = sum(1 for i in range(int(days) + 1)
                       if (first.fromtimestamp(first.timestamp() + i * 86400,
                                               tz=timezone.utc).weekday() < 5))
        expect = weekdays * {"H1": 23.0, "M15": 92.0}.get(tf_name, 0)
    if expect:
        ratio = len(bars) / expect
        truncated = len(bars) >= TF_LADDER[-1]  # terminal max-bars cap hit
        ok = (0.85 <= ratio <= 1.15) or truncated
        note = f"{len(bars)} bars, expected ~{expect:.0f}, ratio {ratio:.2f}"
        res["V1_count_vs_calendar"] = (ok, note + " [TRUNCATED AT CAP]" if truncated else note)

    # V2 gap scan — flag only breaks > 4 days on intraday TFs. On D1 the
    # Easter holiday spans Thu-bar -> Tue-bar = 5 calendar days (Good Friday
    # + Easter Monday: both legal), so D1 tolerates 6 days.
    dts = sorted(b2["time"] - b1["time"] for b1, b2 in zip(bars, bars[1:]))
    med = dts[len(dts) // 2] if dts else 0
    tol_days = 6 if tf_name == "D1" else 4
    broken = [(i, d) for i, d in enumerate(dts) if d <= 0 or d > tol_days * 86400]
    res["V2_gaps"] = (not broken,
                      f"{len(broken)} broken gaps (>{tol_days}d or non-monotonic); median dt {med}s")

    # V3 OHLC sanity
    bad3 = 0
    for b in bars:
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        if not (h >= max(o, c) and l <= min(o, c) and 0 < l <= h):
            bad3 += 1
    res["V3_ohlc_sanity"] = (bad3 == 0, f"{bad3} malformed bars")

    # V4 day-of-week — Saturday ~absent everywhere. Sunday: small minority of
    # intraday bars (the legal reopen) but ~1/6 of D1 bars (weekly reopen bar).
    dows = [datetime.fromtimestamp(b["time"], tz=timezone.utc).weekday() for b in bars]
    sat = dows.count(5)
    sun = dows.count(6)
    sun_cap = 0.25 if tf_name == "D1" else 0.05
    res["V4_dow"] = (sat <= 0.005 * len(bars) and sun <= sun_cap * len(bars),
                     f"Saturday {sat}/{len(bars)}, Sunday {sun}/{len(bars)}")
    return res


def _resolve_install() -> str:
    """The live install's executable, by account identity, or refuse.

    Refusing is the point: a fetch that cannot identify the install must not fall back
    to a path, because the fallback is what produced a Deriv-sourced corpus for an
    Upcomers account. `mt5_ops.terminal_exe()` reads `origin.txt` of the data folder
    whose journals name the active account.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mt5_ops                                   # noqa: PLC0415
    try:
        return mt5_ops.terminal_exe()
    except mt5_ops.MT5OpsUnavailable as exc:
        print(f"FAIL: no live install to fetch from — {exc}")
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MIDASTOUCH XAUUSD history download")
    ap.add_argument("--suffix", default="",
                    help="appended to each CSV name, so a differently-sourced corpus can "
                         "be written alongside the existing one instead of over it "
                         "(e.g. --suffix _upcomers)")
    ap.add_argument("--terminal", default=None,
                    help="explicit terminal64.exe (default: resolve the live install)")
    args = ap.parse_args(argv)

    global TERMINAL_EXE
    TERMINAL_EXE = args.terminal or _resolve_install()
    if not os.path.isfile(TERMINAL_EXE):
        print(f"FAIL: terminal not found at {TERMINAL_EXE}")
        return 2
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("FAIL: MetaTrader5 package unavailable")
        return 2
    if not mt5.initialize(path=TERMINAL_EXE, timeout=60000):
        print(f"FAIL: mt5.initialize: {mt5.last_error()}")
        return 2
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        os.makedirs(ART, exist_ok=True)
        ti, ai = mt5.terminal_info(), mt5.account_info()
        provenance = {
            "terminal_exe": TERMINAL_EXE,
            "terminal_path": getattr(ti, "path", None),
            "terminal_data_path": getattr(ti, "data_path", None),
            "terminal_build": getattr(ti, "build", None),
            "account": getattr(ai, "login", None),
            "server": getattr(ai, "server", None),
            "currency": getattr(ai, "currency", None),
            "balance": getattr(ai, "balance", None),
            "suffix": args.suffix,
            "resolution": "mt5_ops.terminal_exe() by account identity",
        }
        print(f"install   : {provenance['terminal_path']}  (build {provenance['terminal_build']})")
        print(f"account   : {provenance['account']} @ {provenance['server']}  "
              f"{provenance['balance']} {provenance['currency']}")
        report: dict = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "provenance": provenance,
                        "symbols": {}}
        # D1 on this broker is reference-only: Deriv's D1 backfill carries a
        # disclosed hole (2023-12-20 -> 2024-04-10 on XAUUSD) that H1 does not
        # share. Research runs on M15/H1; D1 never gates the verdict.
        REFERENCE_ONLY = {"D1"}
        ok_all = True
        for sym in SYMBOLS:
            report["symbols"][sym] = {}
            for tf_name, tf in TFS.items():
                if not warm_up(mt5, sym, tf):
                    report["symbols"][sym][tf_name] = {"error": "warm-up failed"}
                    if tf_name not in REFERENCE_ONLY:
                        print(f"{sym:<12}{tf_name:<5}ERROR: warm-up failed")
                        ok_all = False
                    continue
                n = max_depth(mt5, sym, tf)
                if not n:
                    report["symbols"][sym][tf_name] = {"error": "no bars after retries"}
                    if tf_name not in REFERENCE_ONLY:
                        print(f"{sym:<12}{tf_name:<5}ERROR: no bars after retries")
                        ok_all = False
                    continue
                bars = rates_with_retry(mt5, sym, tf, n)
                if bars is None:
                    report["symbols"][sym][tf_name] = {"error": "fetch failed after retries"}
                    if tf_name not in REFERENCE_ONLY:
                        ok_all = False
                    continue
                rows = [{"time": b["time"],
                         "iso": datetime.fromtimestamp(b["time"], tz=timezone.utc).isoformat(),
                         "open": b["open"], "high": b["high"], "low": b["low"],
                         "close": b["close"], "tick_volume": b["tick_volume"],
                         "spread": b["spread"]}
                        for b in bars]
                checks = validate(rows, tf_name)
                # Research-span definition: if the feed carries a coverage
                # hole (the retired Deriv gold backfill had a 112-day hole
                # Dec-2023 -> Apr-2024), everything after the LAST broken gap is the
                # continuous, research-grade span. Gate on that span; record
                # the discarded prefix loudly. D1 stays reference-only.
                research_note = None
                dropped = 0
                if tf_name not in REFERENCE_ONLY and not checks["V2_gaps"][0]:
                    tol = 6 if tf_name == "D1" else 4
                    ts_all = [b["time"] for b in rows]
                    cut = None
                    for a, b in zip(ts_all, ts_all[1:]):
                        if b - a <= 0 or b - a > tol * 86400:
                            cut = b
                    if cut:
                        dropped = sum(1 for t in ts_all if t < cut)
                        rows = [b for b in rows if b["time"] >= cut]
                        research_note = (
                            "research span starts "
                            + datetime.fromtimestamp(cut, tz=timezone.utc).isoformat()
                            + f"; dropped {dropped}-bar prefix before the broker feed hole")
                        checks = validate(rows, tf_name)
                fn = os.path.join(OUT_DIR,
                                  f"{sym.replace('/', '')}_{tf_name}{args.suffix}.csv")
                with open(fn, "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                ok = all(v[0] for v in checks.values())
                if tf_name not in REFERENCE_ONLY:
                    ok_all &= ok
                report["symbols"][sym][tf_name] = {
                    "file": fn, "bars": len(rows), "dropped_prefix": dropped,
                    "first": rows[0]["iso"], "last": rows[-1]["iso"],
                    "reference_only": tf_name in REFERENCE_ONLY,
                    "research_note": research_note,
                    "checks": {k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()},
                    "all_ok": ok}
                first = rows[0]["iso"][:10]
                tag = "REF" if tf_name in REFERENCE_ONLY else ("OK" if ok else "CHECK-FAILURES")
                extra = f"  [{dropped} bars dropped as pre-hole]" if dropped else ""
                print(f"{sym:<12}{tf_name:<5}{len(rows):>7} bars  {first} -> {rows[-1]['iso'][:10]}  {tag}{extra}")
                for k, v in checks.items():
                    if not v[0]:
                        print(f"    {k}: {v[1]}")
        out = os.path.join(ART,
                           f"midas_history_{datetime.now():%Y%m%d}"
                           f"{args.suffix.replace('_', '-')}.json")
        with open(out, "w") as fh:
            json.dump(report, fh, indent=1)
        print(f"\nartifact: {out}")
        print("HISTORY (M15/H1 = research timeframes):",
              "ALL CHECKS PASS" if ok_all else "VALIDATION FAILURES — see above")
        return 0 if ok_all else 2
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())

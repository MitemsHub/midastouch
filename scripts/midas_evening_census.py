#!/usr/bin/env python3
"""Day census (rerunnable): what the tape did on a UTC day, why the book is flat.

Runs the arm's own series (venue corpus extended by the terminal's live bars, one UTC frame)
and reports the requested UTC day (default: today): the day's range, the move off its low,
how much of it sat inside the 04-18Z session gate, and the ledger's own counters for that
day. No decision is made here; this is the number behind "why didn't it trade".

Usage: python scripts/midas_evening_census.py [YYYY-MM-DD]
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midas_sweep_shadow as sh  # noqa: E402

UTC = dt.timezone.utc
LEDGER = Path(r"C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal"
              r"\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Files"
              r"\MIDASTOUCH_paper_XAUUSD_U25.csv")


def f(t: int) -> str:
    return dt.datetime.fromtimestamp(t, tz=UTC).strftime("%H:%M") + "Z"


def main() -> int:
    day_str = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(UTC).strftime("%Y-%m-%d")
    y, m, d = (int(x) for x in day_str.split("-"))
    day0 = int(dt.datetime(y, m, d, tzinfo=UTC).timestamp())
    day_no = day0 // 86400

    m15, _h1, prov = sh.build_series(120)
    last = dt.datetime.fromtimestamp(m15[-1]["time"], tz=UTC)
    print(f"series: {len(m15)} m15 bars (corpus {prov['corpus_m15_rows']} + terminal "
          f"{prov['appended_m15_rows']}), last bar {last:%Y-%m-%d %H:%M}Z")

    td = [b for b in m15 if day0 <= b["time"] < day0 + 86400]
    if not td:
        print(f"no bars for {day_str} in the series")
        return 1
    gate = lambda b: 4 <= dt.datetime.fromtimestamp(b["time"], tz=UTC).hour < 18  # noqa: E731
    ing = [b for b in td if gate(b)]
    d0, d1 = td[0], td[-1]
    hi = max(td, key=lambda b: b["high"])
    lo = min(td, key=lambda b: b["low"])
    print(f"\nDAY {day_str}: {len(td)} bars ({len(ing)} in-gate), open {d0['open']:.2f} -> "
          f"{d1['close']:.2f} ({d1['close'] - d0['open']:+.2f})")
    print(f"     high {hi['high']:.2f} @{f(hi['time'])}   low {lo['low']:.2f} @{f(lo['time'])}")

    # the move off the day's low, and how much of it the gate could see
    off_lo = [b for b in td if b["time"] >= lo["time"]]
    off_g = [b for b in off_lo if gate(b)]
    run = d1["close"] - lo["low"]
    if run > 0 and len(off_lo) > 1:
        in_part = (off_g[-1]["close"] - lo["low"]) if off_g else 0.0
        out_part = d1["close"] - (off_g[-1]["close"] if off_g else lo["low"])
        print(f"\nMOVE OFF LOW: {run:+.2f} pts since {f(lo['time'])} "
              f"({len(off_lo)} bars, {len(off_g)} in-gate)")
        print(f"  in-gate  part: {in_part:+.2f}   after-gate part: {out_part:+.2f}")

    # last four hours, wherever they sit relative to the gate
    h4 = [b for b in td if b["time"] >= td[-1]["time"] - 4 * 3600]
    h4g = [b for b in h4 if gate(b)]
    print(f"\nLAST 4H: {len(h4)} bars, net {h4[-1]['close'] - h4[0]['open']:+.2f} "
          f"({len(h4g)} in-gate)")

    # what the armed rule itself did that day, from the ledger's own counters
    print(f"\nLEDGER (day {day_no}, UTC {day_str}):")
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split(",")
        if p[0] == "NOFILLSUM" and len(p) > 2 and p[2] == str(day_no):
            print("  " + line[:130])
        elif p[0] in ("LOPEN", "LCLOSE", "SWEEPSHADOW") and p[1].isdigit() \
                and day0 <= int(p[1]) < day0 + 86400:
            print("  " + line[:130])
    st = [ln for ln in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
          if ln.startswith("STATE,") and ln.split(",")[1].isdigit()
          and day0 <= int(ln.split(",")[1]) < day0 + 86400]
    if st:
        print(f"  ... {len(st)} STATE rows, last:")
        print("  " + st[-1][:130])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Long-only build validation: two real-tick Strategy Tester passes.

Pass 1 (fast gate, ~3 min): the pinned 71-day regression window. The v2.00
baseline's 13 trades split into 8 buys (-45.92) and 5 sells (-130.58); with the
sell leg removed and entries untouched, the long-only build must reproduce
exactly the 8-buy entry stream. Any deviation means entry paths moved.

Pass 2 (the money question, 31 months): the full broker-served window
(2024.03 = tick-cache floor, per the Sep 12 probe). Reference arms:
v2.00 spec both-arm -333.31/PF 0.920; v2.10 long-only +730.66/PF 1.529
(tpA2 buy arm +747.55/PF 1.56).

Usage: python v210_longonly_validate.py [tag_prefix]   (default: v210)
Tag prefix selects the report names; PnL pins apply only to v2.10 (2h-timeout
variants change exit paths by design, so only entry-stream invariants are
asserted for them).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from v75_tester_runner import run_pass, split_sides  # noqa: E402

INPUTS = {
    "InpMagicNumber": "7500",
    "InpRiskPercent": "1.0",
    "InpRRMultiplier": "2.0",
    "InpEnableTickSafety": "true",
    "InpRSIBuyLevel": "35.0",
}

def _summarize(tag: str, res: dict) -> dict:
    """Per-side PnL summary via the runner's shared deals-pairing helper."""
    sides = split_sides(res["report"]["deals"])
    return {"n": len(sides["all"]), "buys": sides["buy"], "sells": sides["sell"],
            "all": sides["all"], "pnl": sum(t["pnl"] for t in sides["all"])}

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "v210"
PINNED = PREFIX == "v210"   # v2.10-specific PnL/R pins; other builds: entry-stream only
VERSION = "2.20"            # expected engine identity in the tester journal

# ---------------- Pass 1: 71-day fast gate ----------------
print(f"=== PASS 1: 71-day window (fast gate, prefix={PREFIX}) ===", flush=True)
r1 = (None if os.environ.get("V210_PASS2_ONLY")
      else run_pass(f"{PREFIX}_71d", INPUTS))
if r1 is None:
    s1 = None
    print("(skipped by V210_PASS2_ONLY)")
else:
    s1 = _summarize(f"{PREFIX}_71d", r1)
if s1 is not None:
    print(f"fills={r1['report']['fills']} pnl={r1['report']['pnl']:+.2f} "
          f"pf={r1['report']['pf']:.3f} sl={r1['report']['sl_hits']} tp={r1['report']['tp_hits']}")
    print(f"buy pnls={[round(x, 2) for x in s1['buys']]}")
    print(f"journal: r_values={r1['journal']['r_values']} r_sum={r1['journal']['r_sum']} "
          f"closed={r1['journal']['closed_marks']} timeouts={r1['journal']['timeouts']}")

    assert s1["sells"] == [], "long-only gate violated: a SELL was taken"
    assert r1["report"]["fills"] == 8, f"expected 8 fills (buys only), got {r1['report']['fills']}"
    if PINNED:
        assert abs(r1["report"]["pnl"] - (-45.92)) <= 1.0, \
            f"buy-arm PnL moved: {r1['report']['pnl']:+.2f} vs pinned -45.92"
        expected = [-57.73, 32.25, 20.74, 27.32, -38.72, -5.56, 13.27, -37.49]
        got = [round(x, 2) for x in s1["buys"]]
        # R-values already pinned identical; timeout exits fill at the next real
        # tick, so cent-level drift (~1 tick) is fill noise, not a path change.
        assert all(abs(g - e) <= 0.50 for g, e in zip(got, expected)) and len(got) == len(expected), \
            f"buy sequence moved beyond tick noise: {got} vs {expected}"
    assert r1["report"]["entries_on_bar_open"], "entries no longer on M30 bar opens"
    assert r1["journal"]["closed_marks"] == 8, "reconciliation count != fills"
    ident1 = r1["journal"]["identity"]
    assert f"v{VERSION} initialized" in ident1, (
        f"wrong binary ran: identity '{ident1}' does not match expected v{VERSION}"
    )
    print("PASS 1 GATE: entry-stream invariants hold (8 buys, zero sells)\n", flush=True)

# ---------------- Pass 2: 31-month window ----------------
print(f"=== PASS 2: 31-month window 2024.03.01 - 2026.09.10 (prefix={PREFIX}) ===", flush=True)
r2 = run_pass(f"{PREFIX}_31m", INPUTS, timeout_s=10800,
              dates=("2024.03.01", "2026.09.10"))
s2 = _summarize(f"{PREFIX}_31m", r2)
print(f"fills={r2['report']['fills']} pnl={r2['report']['pnl']:+.2f} "
      f"pf={r2['report']['pf']:.3f} sl={r2['report']['sl_hits']} tp={r2['report']['tp_hits']}")
print(f"journal: r_sum={r2['journal']['r_sum']} closed={r2['journal']['closed_marks']} "
      f"final_balance={r2['journal']['final_balance']}")
assert s2["sells"] == [], "long-only gate violated: a SELL was taken in the 31-month pass"
ident2 = r2["journal"]["identity"]
assert f"v{VERSION} initialized" in ident2, (
    f"wrong binary ran: identity '{ident2}' does not match expected v{VERSION}"
)
print(f"run identity: {ident2}")
print(f"buys n={len(s2['buys'])} pnl={sum(s2['buys']):+.2f}")

# per-year and per-month breakdown of the long-only profile
from collections import defaultdict
per_year, per_month = defaultdict(float), defaultdict(float)
for t in s2["all"]:
    per_year[t["exit_time"][:4]] += t["pnl"]
    per_month[t["exit_time"][:7]] += t["pnl"]
print("per-year:  " + "  ".join(f"{y}:{v:+.0f}" for y, v in sorted(per_year.items())))
neg = sum(1 for v in per_month.values() if v < 0)
print(f"months: {len(per_month)} total, {neg} negative")

print("\n=== LONG-ONLY 31-MONTH RESULT vs REFERENCE ARMS ===")
print("v2.00 spec (both arms): 167 fills  -333.31  PF 0.920")
print("v2.10 long-only 3h:     75 buys  +730.66  PF 1.529  R-sum +7.15")
print(f"{PREFIX} build:           {len(s2['buys'])} buys  {sum(s2['buys']):+.2f}  "
      f"(report PF {r2['report']['pf']:.3f}, R-sum {r2['journal']['r_sum']:+.2f})")

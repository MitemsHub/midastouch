#!/usr/bin/env python3
"""The no-target exit as ONE declared hypothesis: stop 1.0R, no target, flat by 22:00 UTC.

THE DECLARATION CAME FIRST and is `docs/GOLD_PREREG_NO_TARGET_20260921.md`. It fixes, before
any number below was produced: the rule; the primary entry set; the comparators; the required
sample (**375** trades to reach t=1.96 at the discovered effect, **766** for 80% power); and
the decision rule, including a kill. This file must not be able to compute a result the
declaration did not foresee, so the constants below are read from that document's terms
rather than tuned here.

WHY N=1 IS THE WHOLE POINT. Every other study in this program reports the best of a search,
so its t must clear `selection_threshold(N)` (3.07 at 24 trials, 3.61 at 168 — see
`docs/GOLD_DECIDABILITY_AUDIT_20260921.md`). Nothing is selected here: one rule, declared,
applied. The comparison is therefore the ordinary 1.96, and it is *legitimate* to use it.

WHAT IS CONTAMINATED, STATED IN THE ARTIFACT. The rule was discovered by a 14-policy
comparison on the widest-session entry set (`artifacts/gold_exit_capture.json`), so the
discovery half of this run is in-sample by construction. The primary set restricts to the
arm's session (06-20 UTC) — entries the rule was not selected on — which is the strongest
separation the venue's 8 months allow. It is not a clean time holdout, and nothing here is a
validation: the forward record is the only instrument that can validate.

WHY THE STOP IS 1.0 x ATR AND NOT THE ARM'S 2.0 x ATR. The exit-capture study priced every
policy against one risk unit so the comparison is about *exits*, not sizing. That convention
is kept, so this test asks the question the discovery asked, on a fresh entry set. Sizing is
handled separately, by the declared deployability leg at the end.
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

import gold_exit_capture as ge  # noqa: E402
import gold_governed_wfo as gg  # noqa: E402
import gold_walkforward as gw  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

#: The declared threshold. N=1, so this is `selection_threshold(1)`, which happens to be the
#: familiar number -- the point is that it is DERIVED from the search size and not assumed.
T_REQ = gw.selection_threshold(1)
#: The rule, exactly as declared: no take-profit, no trail, at most 48 bars, flat by 22:00.
RULE = {"tp": None, "trail": None, "time_bars": None}

#: Entry sets. Only the SESSION differs; the trigger configuration is the frozen one, so a
#: difference between the two halves is the session and not the trigger.
FROZEN_TRIGGER = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 3.0}
PRIMARY_SESSION = (6, 20)          # the arm's own session, UTC
DISCOVERY_SESSION = (0, 24)        # the widest declared config: what the discovery used

#: Comparators, declared in the document. Both priced on the same entries as the rule.
COMPARATORS = (2.0, 3.0)

#: Sample requirements from the declaration (the discovery's effect: +0.3221R, sd 3.1838).
N_FOR_T195 = 375
N_FOR_POWER = 766


def entry_config(session: tuple[int, int]) -> dict:
    return {**FROZEN_TRIGGER, "win_lo": session[0], "win_hi": session[1]}


def decide(st: dict, *, t_req: float = T_REQ, n_for_t: int = N_FOR_T195,
           n_for_power: int = N_FOR_POWER) -> tuple[str, str]:
    """The declared decision rule, in one place so the artifact can be re-checked against it.

    Extracted from `main()` for exactly that reason: the verdict written into the artifact
    must be reproducible from the artifact's own stored statistics, or the record and its
    declaration could drift apart unnoticed. `tests/test_gold_pbo_and_prereg.py` re-applies
    this to the committed artifact.
    """
    mean, n, t = st.get("mean_r"), st.get("n") or 0, st.get("t")
    if mean is not None and mean <= 0:
        return "KILL", "primary mean <= 0 - the no-target family is retired"
    if n < n_for_t:
        return "INSUFFICIENT", f"n={n} < the declared {n_for_t}"
    if t is not None and t >= t_req and n < n_for_power:
        return ("POSITIVE, UNDERPOWERED",
                f"t={t:+.2f} >= {t_req:.2f} at n={n} < {n_for_power}: positive, explicitly "
                f"not validated")
    if t is not None and t >= t_req:
        return "PASS", f"t={t:+.2f} >= {t_req:.2f} at n={n}"
    return ("FAIL", f"t={t:+.2f} < {t_req:.2f} at n={n} - the exit effect does not survive "
            f"the session restriction")


def halves(rs: list[float]) -> dict:
    """First/second half of the trade sequence, in entry order (a stability check, declared)."""
    if not rs:
        return {}
    mid = len(rs) // 2
    return {"first_half": ge.stats(rs[:mid]), "second_half": ge.stats(rs[mid:])}


def deployability(trades: list[dict], epoch: np.ndarray, rules, risk_usd: float) -> dict:
    """The declared second leg: can the rule be DEPLOYED at the arm's own risk?

    A significant rule that still breaks the venue's daily line is not deployable at 1% risk
    (the line is 3R at that size). Reported, never traded away.
    """
    kept, vetoes = gg.govern(trades, epoch, rules=rules, risk_usd=risk_usd)
    pc = gw.prop_compat(kept, epoch, rules, risk_usd) if kept else {}
    days: dict[str, float] = {}
    for t in kept:
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).strftime("%Y-%m-%d")
        days[d] = days.get(d, 0.0) + float(t["net_r"])
    worst_day_r = min(days.values()) if days else 0.0
    return {
        "trades_kept": len(kept),
        "trades_vetoed": len(trades) - len(kept),
        "vetoes": vetoes,
        "days": len(days),
        "worst_day_r": round(worst_day_r, 3),
        "worst_day_usd": round(worst_day_r * risk_usd, 2),
        "daily_limit_usd": round(rules.daily_loss_limit_usd, 2),
        "days_beyond_daily_limit": sum(
            1 for v in days.values() if v * risk_usd < -rules.daily_loss_limit_usd),
        "prop_compat": pc,
    }


#: Post-hoc SIZING scan, declared as such. The rule is frozen and unchanged; only the
#: dollars-per-R moves, so this cannot rescue or damage the statistical verdict. It answers
#: the declaration's own follow-on: "if it passes and still breaches, cut risk" -- by how much?
RISK_SCAN = (250.0, 187.5, 125.0, 62.5)   # 1.00%, 0.75%, 0.50%, 0.25% of 25,000


def sizing_scan(trades: list[dict], epoch: np.ndarray, rules) -> list[dict]:
    out = []
    for r in RISK_SCAN:
        d = deployability(trades, epoch, rules, r)
        out.append({"risk_usd_per_r": r, "risk_pct": round(100.0 * r / rules.account_size, 2),
                    "trades_kept": d["trades_kept"], "worst_day_r": d["worst_day_r"],
                    "worst_day_usd": d["worst_day_usd"],
                    "daily_limit_usd": d["daily_limit_usd"],
                    "days_beyond_daily_limit": d["days_beyond_daily_limit"]})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--risk-usd", type=float, default=gg.RISK_USD)
    ap.add_argument("--out", default="artifacts/gold_prereg_no_target.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    rules = ThunderboltClassicRules(account_size=gg.ACCOUNT_SIZE)
    window = [str(datetime.fromtimestamp(epoch[0], timezone.utc)),
              str(datetime.fromtimestamp(epoch[-1], timezone.utc))]
    print(f"venue window: {window[0]} .. {window[1]}  ({n} bars)")
    print(f"declared rule: stop 1.0xATR(H1), NO target, <=48 bars, flat by "
          f"{gw.FLAT_BY_UTC_HOUR}:00 UTC   |   threshold t >= {T_REQ:.2f} (N=1)")

    out: dict = {
        "declared": {
            "document": "docs/GOLD_PREREG_NO_TARGET_20260921.md",
            "rule": {"stop": "1.0 x ATR(H1) at the entry bar", "take_profit": None,
                     "max_bars": 48, "flat_by_utc_hour": gw.FLAT_BY_UTC_HOUR},
            "t_required": round(T_REQ, 4),
            "n_required_for_t": N_FOR_T195, "n_required_for_power": N_FOR_POWER,
            "primary_session_utc": list(PRIMARY_SESSION),
            "comparators_tp": list(COMPARATORS),
            "kill_rule": "primary mean <= 0 retires the no-target family; no variant follows",
            "contamination": ("the rule was selected by a 14-policy comparison on the "
                              "discovery entry set; the primary set differs by SESSION only, "
                              "and there is no uncontaminated holdout inside the venue window"),
        },
        "window": window, "bars": n,
    }

    sets: dict[str, list[dict]] = {}
    for label, session in (("primary", PRIMARY_SESSION), ("discovery", DISCOVERY_SESSION)):
        cfg = entry_config(session)
        sets[label] = gg.run_grid(B, hours, ok, atr, cfg, n)
        print(f"{label:<10} entries (session {session[0]:02d}-{session[1]:02d} UTC, "
              f"trigger {FROZEN_TRIGGER['emas']}): {len(sets[label])}")

    verdicts: dict[str, dict] = {}
    for label, entries in sets.items():
        print(f"\n== {label.upper()} entry set — one declared rule, no selection ==")
        rule_trades = ge.simulate_policy(B, entries, atr, **RULE)
        rs = [t["net_r"] for t in rule_trades]
        st = ge.stats(rs)
        t = st["t"]
        print(f"  {'rule':<28} n={st['n']:>4}  mean={st['mean_r']:+.4f}R  sd={st['sd']:.4f}  "
              f"t={t:+.2f}  total={st['total_r']:+.1f}R")
        comps = {}
        for tp in COMPARATORS:
            ctr = ge.simulate_policy(B, entries, atr, tp=tp, trail=None, time_bars=None)
            cst = ge.stats([x["net_r"] for x in ctr])
            comps[f"tp{tp}"] = cst
            print(f"  {'comparator tp'+str(tp)+' (arm-style)':<28} n={cst['n']:>4}  "
                  f"mean={cst['mean_r']:+.4f}R  t={cst['t']:+.2f}")
        h = halves(rs)
        print(f"  halves: first {h['first_half']['mean_r']:+.4f}R (n={h['first_half']['n']}, "
              f"t={h['first_half']['t']}) | second {h['second_half']['mean_r']:+.4f}R "
              f"(n={h['second_half']['n']}, t={h['second_half']['t']})")
        dep = deployability(rule_trades, epoch, rules, a.risk_usd)
        print(f"  deployability at {a.risk_usd:.0f}$/R: kept {dep['trades_kept']} of "
              f"{len(rule_trades)} (vetoes {dep['vetoes']}), worst day "
              f"{dep['worst_day_r']:+.2f}R = {dep['worst_day_usd']:+.0f}$ vs the "
              f"{dep['daily_limit_usd']:.0f}$ line, days beyond it "
              f"{dep['days_beyond_daily_limit']}")

        if label == "primary":
            v, why = decide(st)
        else:
            v, why = ("REPLICATION", "in-sample by construction; must reproduce the discovery")
        print(f"  -> {v}: {why}")
        verdicts[label] = {"stats": st, **{k: comps[k] for k in comps}, "halves": h,
                           "deployability": dep, "verdict": v, "reason": why}

    print("\n== post-hoc SIZING scan on the primary rule (rule unchanged; only $/R moves) ==")
    scan = sizing_scan([t for t in ge.simulate_policy(B, sets["primary"], atr, **RULE)],
                       epoch, rules)
    print(f"  {'risk/R':>8} {'%':>6} {'kept':>6} {'worst day':>11} {'line':>8} "
          f"{'days beyond it':>15}")
    for s in scan:
        print(f"  {s['risk_usd_per_r']:>8.1f} {s['risk_pct']:>6.2f} {s['trades_kept']:>6} "
              f"{s['worst_day_usd']:>11.0f} {s['daily_limit_usd']:>8.0f} "
              f"{s['days_beyond_daily_limit']:>15}")
    usable = [s for s in scan if s["days_beyond_daily_limit"] == 0]
    print(f"  largest scanned size with NO day beyond the venue's line: "
          f"{usable[0]['risk_pct']:.2f}% ({usable[0]['risk_usd_per_r']:.1f}$/R)"
          if usable else "  no scanned size keeps every day inside the line")
    out["sizing_scan_post_hoc"] = scan

    out["results"] = verdicts
    out["verdict"] = verdicts["primary"]["verdict"]
    out["reason"] = verdicts["primary"]["reason"]

    rep = verdicts["discovery"]["stats"]
    print(f"\nreplication check: discovery set gives {rep['mean_r']:+.4f}R over n={rep['n']} "
          f"(artifact of record for that comparison: +0.3221R over 912)")
    print(f"\nPRIMARY VERDICT: {out['verdict']} — {out['reason']}")
    print("Nothing here is a validation. The forward record is the only instrument that can "
          "validate a rule.")

    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

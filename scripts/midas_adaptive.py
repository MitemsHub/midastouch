#!/usr/bin/env python3
"""P5 adaptive-trigger proposal engine — REGISTERED SPEC, NOT DEPLOYED.

Register row P5 (docs/MIDASTOUCH_V2_REGISTER.md §2b, 2026-09-18) defines
the only lawful "self-adjusting" mechanism for the MIDASTOUCH program:
an offline hill-climb that proposes each era's trigger threshold θ from
trailing realized expectancy. The EA NEVER mutates its own parameters
mid-era; every proposal deploys through the existing era machinery
(re-splice + watchdog pin verification) as a registered amendment.

This module is deliberately PURE: no MetaTrader5 import, no ledger
writes, no watchdog interaction. It consumes closed-trade records and
emits a proposal artifact. Deployment is a separate, separately-
registered step queued behind the 2026-10-01 §13 reading and the
P-series (P5 runs after P4, or directly after P3 if P4 voids).

Frozen constants (register-locked; changing any of them is a
re-registration, not an edit):
  CADENCE        one adaptation step per 20 closed trades
  BOUNDS         θ ∈ [1.0, 4.0] — a raw proposal outside is VOID
  STEP           δ = 0.25 per adaptation step
  TIE            toward θmax (the conservative, rarer-signal end)
  FREEZE         trailing-20 expectancy < −0.30R freezes at θmax
  REVERT         two consecutive full-loss (−1R) days revert to θmax
                 and stop adaptation for the window
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CADENCE = 20
THETA_MIN = 1.0
THETA_MAX = 4.0
STEP = 0.25
FREEZE_EXPECTANCY = -0.30
FULL_LOSS_R = -0.999          # a trade at/below this counts as a full loss


def trailing_expectancy(trades: list[float]) -> float:
    if not trades:
        return 0.0
    return sum(trades) / len(trades)


def _full_loss_days(trades: list[dict]) -> int:
    """Consecutive trailing days (UTC, from trade close epoch) that end
    with at least one full-loss trade and no positive trade."""
    if not trades:
        return 0
    by_day: dict[str, float] = {}
    for t in trades[-60:]:
        day = datetime.fromtimestamp(t["close_epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[day] = min(by_day.get(day, 0.0), t["r"])
    days = sorted(by_day, reverse=True)
    n = 0
    for d in days:
        if by_day[d] <= FULL_LOSS_R:
            n += 1
        else:
            break
    return n


def propose(state: dict, trades: list[dict]) -> dict:
    """Pure proposal function. `trades` are closed trades since the last
    adaptation step, each {"r": float, "close_epoch": int}. `state`
    carries {"theta", "last_direction", "frozen", "reverted"}.

    Direction convention: +1 steps toward THETA_MAX (the conservative,
    rarer-signal end), −1 steps toward THETA_MIN (looser, more frequent —
    the direction this experiment exists to explore). A non-positive
    block reverses toward THETA_MAX; an exact-zero expectancy ties toward
    THETA_MAX per the register row.

    Bound law: the engine NEVER proposes outside [THETA_MIN, THETA_MAX] —
    a desired step past a bound is a HOLD at the bound (the envelope was
    frozen precisely to cap adaptation; wanting more is a steady state,
    not a violation). VOID is reserved for envelope-violating STATE
    (theta out of bounds, direction not ±1): the pipeline itself broke
    the registration, which voids the experiment outright.

    Returns a proposal dict: {"action": HOLD|PROPOSE|FREEZE|REVERT|VOID,
    "theta": float, "reason": str, "expectancy": float, "n": int}.
    """
    theta = float(state.get("theta", THETA_MAX))
    direction = int(state.get("last_direction", -1))   # default: explore toward θmin
    if theta < THETA_MIN or theta > THETA_MAX or direction not in (-1, 1):
        return {"action": "VOID", "theta": theta,
                "reason": (f"state violates the frozen envelope "
                           f"(theta={theta}, direction={direction}) "
                           f"— experiment VOID, operator re-registration required"),
                "expectancy": 0.0, "n": len(trades)}
    if state.get("reverted") or state.get("frozen"):
        return {"action": "HOLD", "theta": theta,
                "reason": "adaptation stopped by kill rule", "expectancy": 0.0,
                "n": len(trades)}
    if len(trades) < CADENCE:
        return {"action": "HOLD", "theta": theta,
                "reason": f"cadence not reached ({len(trades)}/{CADENCE})",
                "expectancy": trailing_expectancy([t["r"] for t in trades]),
                "n": len(trades)}

    rs = [t["r"] for t in trades[-CADENCE:]]
    exp = trailing_expectancy(rs)

    if _full_loss_days(trades) >= 2:
        return {"action": "REVERT", "theta": THETA_MAX,
                "reason": "two consecutive full-loss days",
                "expectancy": exp, "n": len(rs)}
    if exp < FREEZE_EXPECTANCY:
        return {"action": "FREEZE", "theta": THETA_MAX,
                "reason": f"trailing-{CADENCE} expectancy {exp:.3f} < {FREEZE_EXPECTANCY:.2f}",
                "expectancy": exp, "n": len(rs)}

    # hill-climb: keep direction while expectancy positive, reverse toward
    # the conservative end otherwise (ties included).
    new_direction = direction if exp > 0 else 1
    raw = theta + new_direction * STEP
    if raw < THETA_MIN or raw > THETA_MAX:
        return {"action": "HOLD", "theta": theta,
                "reason": (f"bound reached ({'THETA_MAX' if new_direction > 0 else 'THETA_MIN'}); "
                           f"crossing is never proposed — envelope is the cap"),
                "expectancy": exp, "n": len(rs), "last_direction": new_direction}
    return {"action": "PROPOSE", "theta": round(raw, 4),
            "reason": ("positive block, continuing direction" if exp > 0
                       else "non-positive block, reversing toward conservative end"),
            "expectancy": exp, "n": len(rs), "last_direction": new_direction}


def emit(proposal: dict, era_note: str, out_dir: str | Path = "artifacts") -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = Path(out_dir) / f"midas_adaptive_proposal_{ts}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "proposal": proposal, "era_note": era_note,
                             "constants": {"CADENCE": CADENCE, "THETA_MIN": THETA_MIN,
                                           "THETA_MAX": THETA_MAX, "STEP": STEP,
                                           "FREEZE_EXPECTANCY": FREEZE_EXPECTANCY}},
                            indent=1), encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="P5 adaptive-threshold proposal engine (registered spec)")
    ap.add_argument("--state", default="artifacts/midas_adaptive_state.json")
    ap.add_argument("--trades-json",
                    help='[{"r": float, "close_epoch": int}, ...] closed trades since last step '
                         '(required unless --selftest)')
    ap.add_argument("--era-note", default="P5-proposal")
    ap.add_argument("--emit", action="store_true", help="write the proposal artifact")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        two_full_loss_days = ([{"r": -1.0, "close_epoch": i * 900} for i in range(10)]
                              + [{"r": -1.0, "close_epoch": 86400 + i * 900} for i in range(10)])
        ok = (propose({}, [])["action"] == "HOLD"                                   # cadence
              and propose({"theta": 2.0}, [{"r": 0.5, "close_epoch": 0}] * CADENCE)["action"] == "PROPOSE"
              and propose({"theta": THETA_MIN, "last_direction": -1},
                          [{"r": 0.5, "close_epoch": 0}] * CADENCE)["action"] == "HOLD"   # bound-reach
              and propose({"theta": 7.5}, [{"r": 0.5, "close_epoch": 0}] * CADENCE)["action"] == "VOID"  # corrupt state
              and propose({"theta": THETA_MAX, "last_direction": -1},
                          two_full_loss_days)["action"] == "REVERT"              # kill rule
              and propose({"theta": THETA_MAX, "last_direction": -1},
                          [{"r": -0.5, "close_epoch": 0}] * CADENCE)["action"] == "FREEZE")
        print("selftest:", "OK" if ok else "FAIL")
        return 0 if ok else 1
    if not args.trades_json:
        ap.error("--trades-json is required unless --selftest")
    state = json.loads(Path(args.state).read_text(encoding="utf-8")) if Path(args.state).exists() else {}
    trades = json.loads(Path(args.trades_json).read_text(encoding="utf-8"))
    proposal = propose(state, trades)
    print(json.dumps(proposal, indent=1))
    if args.emit and proposal["action"] in ("PROPOSE", "FREEZE", "REVERT", "VOID"):
        out = emit(proposal, args.era_note)
        print("artifact:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

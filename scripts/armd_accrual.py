"""Forward-test accrual tracker (all arms) — scripts/armd_accrual.py

Appends one JSONL row per calendar day per arm summarizing the arm's paper
ledger (n, totalR, meanR, maxDD, wins) and reports the standing against that
arm's PRE-REGISTERED gates:
  VALIDATED : n>=MIN_N and totalR>0 and DD<=DD_MAX and meanR>=MEAN_R_MIN
  REJECTED  : n>=MIN_N and (totalR<0 or DD>DD_ABORT or meanR<=0)
  CONTINUE  : otherwise (n<MIN_N, or positive-but-unproven bands)

Arms are declared in ARMS (frozen citations; do not edit without an
amendment):
  D  — docs/ARM_D_FORWARD_TEST.md   (window opened 2026-09-16)
  A2 — docs/ARM_A2_RESTART.md       (pre-start; REVERSE_BOTH tp2.0 at a
       $1,000 basis — supersedes the arm-E pre-draft per the user decision
       of 2026-09-16; arm E is retired from the registry, never started)

Generalized from arm-D-only (2026-09-16) per the arm-E pre-draft §6 so arm E
inherits the tracker and the Sunday pipeline leg the moment its ledger
exists. `accrue(arm="D")` is byte-compatible with the old arm-D contract.

Artifacts: artifacts/ARMD_ACCRUAL.jsonl, artifacts/ARMA2_ACCRUAL.jsonl
(one per arm — the arms' windows are independent and must never blend).

Window clock: an arm with `start: None` has not opened its window; its first
accrual row records `window_start=<today>` and the clock runs from that day
until the registry's start date is confirmed to the true init date (one-line
registry edit + changelog row, per the arm-E §8 start checklist).

Idempotent: one row per arm per day unless --force.

Pipeline entry point: accrue(append=True, arm=...) -> dict (paper_weekly [6]).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timezone

APPDATA = os.environ.get("APPDATA", "")
_FILES = os.path.join(APPDATA, "MetaQuotes", "Terminal", "{term}",
                      "MQL5", "Files", "{ledger}")


def _glob(term: str, ledger: str) -> str:
    return _FILES.format(term=term, ledger=ledger)


# Pre-registered gates, frozen per arm. The VALUES below are identical for D
# and E by design (arm-E pre-draft §4 freezes arm-D's gates verbatim); each
# arm's doc is its own amendment surface.
_GATES_D = {"MIN_N": 60, "DD_MAX": 25.0, "MEAN_R_MIN": 0.05, "DD_ABORT": 30.0}

ARMS: dict[str, dict] = {
    "D": {
        "doc": "docs/ARM_D_FORWARD_TEST.md",
        "gates": _GATES_D,
        "start": "2026-09-16",          # arm D init date (banner 00:38 UTC)
        "ledger_glob": _glob("49E0*",
                             "MitemshubAI_paper_Volatility_75_Index_D.csv"),
        "artifact": os.path.join("artifacts", "ARMD_ACCRUAL.jsonl"),
    },
    # PRE-START (user-authorized 2026-09-16, docs/ARM_A2_RESTART.md): the
    # terminal id is a placeholder — the forward build does not exist yet, so
    # the ledger lookup fails closed (SystemExit) until start day. Supersedes
    # the arm-E registry entry (same candidate, amended start gate); arm E is
    # retired from this registry — it never opened a window.
    "A2": {
        "doc": "docs/ARM_A2_RESTART.md",
        "gates": dict(_GATES_D),        # frozen values, A2 §3 citation
        "start": None,
        "ledger_glob": _glob("SET-ON-START-DAY*",
                             "MitemshubAI_paper_Volatility_75_Index_A2.csv"),
        "artifact": os.path.join("artifacts", "ARMA2_ACCRUAL.jsonl"),
    },
}


def ledger_path(arm: str = "D") -> str:
    cfg = ARMS[arm]
    hits = sorted(glob.glob(cfg["ledger_glob"]))
    if not hits:
        raise SystemExit(f"no arm-{arm} ledger found: {cfg['ledger_glob']} "
                         f"(arm E pre-start is expected to fail here)")
    return hits[-1]


def parse(path: str) -> dict:
    closes: list[dict] = []
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if p and p[0] == "CLOSE" and len(p) >= 8:
                closes.append({"epoch": int(p[1]), "r": float(p[5]),
                               "veq": float(p[7])})
    n = len(closes)
    total_r = sum(c["r"] for c in closes)
    wins = sum(1 for c in closes if c["r"] > 0)
    dd = 0.0
    peak = None
    for c in closes:  # drawdown on the virtual-equity path, peak-to-trough
        peak = c["veq"] if peak is None else max(peak, c["veq"])
        if peak > 0:
            dd = max(dd, (peak - c["veq"]) / peak * 100.0)
    return {"n": n, "total_r": round(total_r, 4),
            "mean_r": round(total_r / n, 4) if n else 0.0,
            "wins": wins, "max_dd_pct": round(dd, 2),
            "last_close_epoch": closes[-1]["epoch"] if closes else None}


def verdict(m: dict, gates: dict | None = None) -> str:
    g = gates or _GATES_D
    if m["n"] < g["MIN_N"]:
        return "CONTINUE"
    if m["total_r"] > 0 and m["max_dd_pct"] <= g["DD_MAX"] \
            and m["mean_r"] >= g["MEAN_R_MIN"]:
        return "VALIDATED"
    if m["total_r"] < 0 or m["max_dd_pct"] > g["DD_ABORT"] \
            or m["mean_r"] <= 0:
        return "REJECTED"
    return "CONTINUE"


def accrue(append: bool = True, force: bool = False, arm: str = "D") -> dict:
    """One accrual read for `arm`: parse the ledger, stamp today's row
    (idempotent per day unless `force`), and return
    {arm, row, appended, days, rate, eta_days}.

    Rows carry the arm tag. A pre-start arm (start: None) whose ledger does
    not exist raises SystemExit — the weekly leg catches it and records why;
    this must stay exception-transparent otherwise.
    """
    cfg = ARMS[arm]
    m = parse(ledger_path(arm))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows: list[dict] = []
    if os.path.exists(cfg["artifact"]):
        rows = [json.loads(l) for l in open(cfg["artifact"]) if l.strip()]
    prior = {r["date"]: r for r in rows}
    row = {"date": today, "arm": arm, **m, "verdict": verdict(m, cfg["gates"])}
    appended = False
    if prior.get(today) and not force:
        row = prior[today]           # the day's first reading is the day's row
    elif append:
        rows = [r for r in rows if r["date"] != today] + [row]
        with open(cfg["artifact"], "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        appended = True
    # Window clock: fixed start date, else the first appended row's date
    # (recorded in-row as window_start so the derivation is auditable).
    start = cfg["start"]
    if start is None:
        starts = [r.get("window_start") for r in rows if r.get("window_start")]
        start = starts[0] if starts else row.get("window_start")
    if start is None:                # append=False and no history yet
        start = today
    if row.get("window_start") is None and cfg["start"] is None and appended:
        row["window_start"] = today
        rows = [r for r in rows if r["date"] != today] + [row]
        with open(cfg["artifact"], "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    days = max((datetime.strptime(today, "%Y-%m-%d")
                - datetime.strptime(start, "%Y-%m-%d")).days, 1)
    rate = row["n"] / days
    eta = ((cfg["gates"]["MIN_N"] - row["n"]) / rate
           if rate > 0 and row["n"] < cfg["gates"]["MIN_N"] else 0)
    return {"arm": arm, "row": row, "appended": appended, "days": days,
            "rate": round(rate, 3), "eta_days": round(eta, 1) if eta else 0.0}


def _print(acc: dict) -> None:
    arm = acc.get("arm", "D")
    cfg = ARMS[arm]
    m = acc["row"]
    print(f"ARM {arm} ACCRUAL {m['date']}: n={m['n']} totalR={m['total_r']:+.2f} "
          f"meanR={m['mean_r']:+.3f} DD={m['max_dd_pct']:.1f}% wins={m['wins']}")
    if m["n"] >= cfg["gates"]["MIN_N"]:
        print(f"day {acc['days']}, rate {acc['rate']:.2f} trades/day, n-gate reached")
    elif acc["eta_days"]:
        print(f"day {acc['days']} of the window, rate {acc['rate']:.2f} trades/day -> "
              f"n={cfg['gates']['MIN_N']} in ~{acc['eta_days']:.0f} days")
    else:
        print(f"day {acc['days']} of the window, 0 trades yet — no rate to project from")
    print(f"PRE-REGISTERED VERDICT: {m['verdict']}  (gates frozen in "
          f"{cfg['doc']}: n>={cfg['gates']['MIN_N']}, totalR>0, "
          f"DD<={cfg['gates']['DD_MAX']}%, meanR>={cfg['gates']['MEAN_R_MIN']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="D", choices=sorted(ARMS),
                    help="forward-test arm to accrue (default: D)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite today's row instead of skipping")
    args = ap.parse_args()
    _print(accrue(force=args.force, arm=args.arm))


if __name__ == "__main__":
    main()

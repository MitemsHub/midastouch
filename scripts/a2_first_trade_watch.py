"""A2 first-trade watch — alerts the moment arm A2's first OPEN lands and
verifies the consult trail around it.

What "right" looks like (the EA contract, MitemshubAI_v28_fwd.mq5):
  * A ledger row  FCONSULT,side,tod,p,src,decision  precedes every OPEN.
    In PASSIVE/ABSENT activation the decision is OBSERVE and the consult
    can never veto (p=0.50 "no opinion"; muted buckets ship exactly 0.50).
  * The Experts journal prints FILTER CONSULT with the same fields, and
    OPEN <side> volume=... risk=$... with trigger=<name>.
  * The OPEN's risk must respect the account-budget guard (<= 15% of the
    $1,000 basis) and, under the materiality amendment, a plain
    *_EXTREME trigger must NOT be stood down at A2's ~1.28% overage —
    if the first trade carries a plain trigger at min-lot risk, that is
    the amendment working in vivo (it would have been vetoed before).

Modes:
  python scripts/a2_first_trade_watch.py            # one poll, exit
  python scripts/a2_first_trade_watch.py --loop 60  # poll every 60s
Alert surface: stdout ALERT line + artifacts/paper_ledgers/a2_first_trade_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from v28_sweep_runner import (  # noqa: E402
    data_folder_for_terminal, inventory_arms)

ART = REPO / "artifacts" / "paper_ledgers"
STATE = ART / "a2_watch_state.json"
REPORT = ART / "a2_first_trade_report.json"

RE_FCONSULT = re.compile(
    r"^FCONSULT,(BUY|SELL),(\d+),(0\.\d+),(BUCKET|GLOBAL),(OBSERVE|TAKE|VETO)")
# Ledger OPEN row (fwd PaperOpen): OPEN,ticket,time,side(1|-1),entry,sl,tp,
# volume,risk,balance,magic,tag  — side is an INT, not BUY/SELL.
LEDGER_OPEN_SIDES = {"1": "BUY", "-1": "SELL"}


def a2_ledger() -> Path:
    df = data_folder_for_terminal()
    arms = inventory_arms(df)
    for a in arms:
        if a.get("tag") == "A2":
            return Path(a["ledger"])
    raise SystemExit("A2 arm not found on the paper terminal — is it attached?")


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"first_trade_reported": False}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def verify_first_trade(ledger_rows: list[list[str]], journal_text: str) -> dict:
    """Full verification of the first OPEN and its consult trail."""
    problems: list[str] = []
    open_idx = next(i for i, r in enumerate(ledger_rows)
                    if r and r[0] == "OPEN")
    consults = [(i, r) for i, r in enumerate(ledger_rows[:open_idx])
                if r and r[0] == "FCONSULT"]
    open_row = ledger_rows[open_idx]

    # --- ledger-side checks -------------------------------------------------
    if not consults:
        problems.append("no FCONSULT row precedes the first OPEN — the consult "
                        "leg did not run before entry")
        consult = None
    else:
        ci, c = consults[-1]
        m = RE_FCONSULT.match(",".join(c))
        if not m:
            problems.append(f"FCONSULT row {ci} malformed: {c}")
            consult = None
        else:
            side, tod, p, src, decision = m.groups()
            if decision != "OBSERVE":
                problems.append(f"consult decision {decision!r} under PASSIVE/ABSENT "
                                "— a passive table must only OBSERVE")
            open_side = LEDGER_OPEN_SIDES.get(open_row[3], f"?{open_row[3]}")
            if side != open_side:
                problems.append(f"consult side {side} != OPEN side {open_side}")
            consult = {"side": side, "tod": int(tod), "p": float(p),
                       "src": src, "decision": decision}

    # --- journal-side checks ------------------------------------------------
    j_open = None
    m = re.search(r"\[v28\.10\] OPEN (BUY|SELL) volume=([\d.]+) entry=([\d.]+) "
                  r"SL=([\d.]+) TP=([\d.]+) risk=\$([\d.]+).*?trigger=(\S+)",
                  journal_text)
    if m:
        j_open = {"side": m.group(1), "volume": float(m.group(2)),
                  "entry": float(m.group(3)), "risk": float(m.group(6)),
                  "trigger": m.group(7)}
        if j_open["risk"] > 150.0:
            problems.append(f"OPEN risk ${j_open['risk']:.2f} busts the 15% "
                            "budget cap ($150) — guard failed to fire")
        # in-vivo evidence of the materiality amendment: a plain *_EXTREME
        # trigger trading at min-lot risk (~$12.75 ≈ 1.28% of basis)
        if (j_open["trigger"].endswith("_EXTREME")
                and j_open["risk"] <= 150.0):
            j_open["materiality_amendment_in_vivo"] = True
    else:
        problems.append("no [v28.10] OPEN print found in today's journal")

    return {"open_row": open_row, "consult": consult, "journal": j_open,
            "problems": problems,
            "verified_at": datetime.now(timezone.utc).isoformat()}


def poll(ledger: Path) -> dict:
    state = load_state()
    raw = [r for r in
           (ln.strip().split(",") for ln in
            ledger.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip())]
    opens = [r for r in raw if r and r[0] == "OPEN"]
    consults = [r for r in raw if r and r[0] == "FCONSULT"]
    status = {"ts": datetime.now(timezone.utc).isoformat(),
              "ledger_rows": len(raw), "opens": len(opens),
              "fconsults": len(consults),
              "first_trade_reported": state["first_trade_reported"]}

    if opens and not state["first_trade_reported"]:
        df = data_folder_for_terminal()
        journal = ""
        if df:
            logs = sorted(Path(df, "MQL5", "Logs").glob("*.log"))
            if logs:
                data = logs[-1].read_bytes()
                journal = (data.decode("utf-16-le", errors="ignore")
                           if data[:2] == b"\xff\xfe"
                           else data.decode("utf-8", errors="ignore"))
        verdict = verify_first_trade(raw, journal)
        verdict["first_trade_row"] = raw.index(opens[0])
        REPORT.write_text(json.dumps(verdict, indent=1), encoding="utf-8")
        state["first_trade_reported"] = True
        save_state(state)
        status["first_trade_reported"] = True
        status["problems"] = verdict["problems"]
        print("=" * 60)
        print("ALERT: ARM A2 FIRST TRADE LANDED")
        print(f"  OPEN row : {','.join(opens[0])}")
        if verdict["consult"]:
            print(f"  consult  : {verdict['consult']}")
        if verdict["journal"]:
            print(f"  journal  : {verdict['journal']}")
        for p in verdict["problems"]:
            print(f"  PROBLEM  : {p}")
        if not verdict["problems"]:
            print("  trail verified: consult -> OPEN all checks green")
        print(f"  report   : {REPORT}")
        print("=" * 60)
    return status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0,
                    help="poll every N seconds instead of once")
    args = ap.parse_args()
    ledger = a2_ledger()
    if args.loop:
        print(f"watching {ledger.name} every {args.loop}s — Ctrl+C to stop")
        while True:
            poll(ledger)
            time.sleep(args.loop)
    else:
        s = poll(ledger)
        print(json.dumps(s))


if __name__ == "__main__":
    main()

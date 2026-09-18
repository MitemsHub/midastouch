"""V28 §11 regime-test data collection driver.

Runs the RESEARCH build (MitemshubAI_v28) on the REVERSE_TRIGGER cell for the
frozen windows (wf, oos) as tagged passes — exactly like a parity pass but
single-sided and without touching the registry — then restores the paper
terminal and harvests per-trade OPEN/CLOSE segments with sim timestamps.

The harvest output (JSON) feeds the §11 conditional analysis.
Discipline: refuses if a hosted paper arm holds an OPEN virtual position
(same fail-closed ledger check as the sweep runner); always relaunches the
terminal, even on failure, so arm A2's forward clock never silently stops.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from v28_research import (  # noqa: E402
    DEFAULT_GEOMETRY, EA_V28, PASS_TIMEOUT_S, WINDOWS, candidate_inputs)
from v28_sweep_runner import (  # noqa: E402
    data_folder_for_terminal, inventory_arms, relaunch_terminal,
    stop_terminal, terminal_pids_exact, verify_all_flat)
from v75_tester_runner import run_pass  # noqa: E402
import build_parity as bp  # noqa: E402  (for pass_segment)

ART = REPO / "artifacts" / "v28_research"
MODE = "V28_REVERSE_TRIGGER"
# Frozen §11 design: wf + oos are the test windows; is180 is the honesty
# check (the regime split must classify the is-window losses into R=off).
WINS = tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else ("wf", "oos")


def flat_or_die() -> None:
    df = data_folder_for_terminal()
    arms = inventory_arms(df)
    if not arms:
        raise SystemExit("no paper arms discovered — refusing without evidence")
    all_flat, evidence = verify_all_flat(arms)
    for e in evidence:
        print(f"flat ok: {e['name']} ({Path(e['ledger']).name}) "
              if e["flat"] else
              f"REFUSED: {e['name']} holds OPEN ticket(s) "
              f"{[o['ticket'] for o in e['open_positions']]}")
    if not all_flat:
        raise SystemExit(2)


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    flat_or_die()

    pids = terminal_pids_exact()
    if pids:
        print(f"stopping paper terminal (pids {pids}) …", flush=True)
        if not stop_terminal(pids):
            raise SystemExit("ERROR: terminal did not stop; refusing to run.")

    out: dict = {"ts": ts, "mode": MODE, "windows": {}, "restored": False}
    try:
        for win in WINS:
            frm, to, _role = WINDOWS[win]
            tag = f"regime_{win}_{ts}"
            print(f"pass [{win}]: {MODE} {frm} -> {to} …", flush=True)
            result = run_pass(tag, candidate_inputs(MODE, DEFAULT_GEOMETRY, tag),
                              dates=(frm, to), timeout_s=PASS_TIMEOUT_S,
                              expert=EA_V28, wait_for_research_line=True)
            seg = bp.pass_segment(tag)
            rep = result["report"]
            out["windows"][win] = {
                "run_tag": tag,
                "identity": seg["identity"],
                "segment_lines": seg["segment_lines"],
                "journal_r_count": len(seg["r_values"]),
                "fills": rep["fills"],
                "exits": rep["exits"],
                "pnl": rep["pnl"],
                "window": [frm, to],
            }
            print(f"  [{win}] fills={rep['fills']} pnl={rep['pnl']:+.2f} "
                  f"segment_lines={seg['segment_lines']}", flush=True)
        out["restored"] = True
    finally:
        relaunch_terminal()
        print("terminal relaunched — A2 keeps accruing.")

    path = ART / f"regime_rerun_{ts}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"artifact: {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rehearse the news stand-down on the REAL EA, one calendar state at a time.

WHY THIS EXISTS, AND WHY IT IS NOT A UNIT TEST. The gate's refusals are pinned by
`tests/test_news_calendar.py` against the Python mirror and against the EA's source text,
and neither of those proves the COMPILED Expert behaves. That gap is not academic: the
mirror and the EA once disagreed about the same file, because the EA's row counter matched
the column header and so counted an empty calendar as a one-event one — the python side
refused the file while the EA traded straight through it. Source-level agreement did not
catch it; running the thing would have.

So this drives a strategy-tester pass per calendar state and prints the EA's own journal
lines. It is a rehearsal, not a certification: the pass is a bar-replay of a real window,
the calendar is a synthetic one, and the point is only that the EA says what the source
actually is — usable, missing, stale, truncated, empty — and vetoes entries when it is not.

WHAT IT TOUCHES. One file, `MIDASTOUCH_news_calendar.csv` in the live terminal's
`MQL5\\Files`, plus tester configs and pass reports the house driver already owns. The
calendar file is REMOVED afterwards (and its prior contents restored if it existed), because
leaving a synthetic calendar on a machine that may later run the gate for real would be a
disaster of exactly the kind this gate exists to prevent.

    python scripts/news_gate_rehearsal.py                 # all states
    python scripts/news_gate_rehearsal.py --state empty   # just one
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import mt5_ops as ops  # noqa: E402
import mt5_terminals as registry  # noqa: E402
import mt5_tester_driver as T  # noqa: E402

CAL_NAME = "MIDASTOUCH_news_calendar.csv"
EXPERT = r"MIDASTOUCH\MidastouchAI"
#: Short and inside the venue's real-tick window (ticks begin 2026.09.04): the pass is
#: read for the EA's words, not for edge, so a day is enough and Model=4 stays honest.
DATES = ("2026.09.08", "2026.09.09")

#: The moment the fixtures are stated relative to: six hours into the pass's own day, in
#: the pass's own (simulated) clock. See `states()`.
WINDOW_ANCHOR = datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc).timestamp()

def inputs() -> dict[str, str]:
    """The certified strategy at its defaults, PERTICK, gate ON, on THIS account's basis.

    The basis comes from the registry (`mt5_terminals.active_account_size`, which refuses
    rather than defaulting) — a sizing basis may only enter a module that way, and
    `tests/test_parity_basis.py` fails any script that writes one as a literal.
    """
    basis = f"{registry.active_account_size():.1f}"
    return {
        "InpMode": "1",
        "InpArmTag": "NEWS",
        "InpMagic": "7825099",
        "InpBarModel": "false",
        "InpLiveExecution": "false",
        "InpPaperEquity": basis,
        "InpPropGuard": "true",
        "InpPropAccountSize": basis,
        "InpUseNewsFilter": "true",
        "InpNewsFile": CAL_NAME,
        "InpNewsWindowMin": "15",
        "InpNewsMaxAgeHours": "24",
        "InpNewsCoverHours": "24",
        "InpNewsRefreshHours": "6",
    }

COLUMNS = "epoch_utc;time_utc;time_server;currency;country;importance;event"


def write_calendar(path: Path, *, generated: int, window_to: int, declared: int | None,
                   rows: list[str], importance: str = "HIGH") -> None:
    """A calendar in the writers' wire format (see MidasNewsProbe.mq5)."""
    import datetime as _dt

    def iso(ts: int) -> str:
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y.%m.%d %H:%M:%S")

    n = len(rows) if declared is None else declared
    # ASCII on purpose: both real producers open the file FILE_ANSI (single-byte), so a
    # fixture carrying anything wider would not be testing the file they actually write.
    lines = [
        "# MIDASTOUCH news calendar - REHEARSAL fixture (scripts/news_gate_rehearsal.py)",
        f"# epoch_generated_utc={generated}",
        f"# generated_at_server={iso(generated)}",
        f"# epoch_window_to_utc={window_to}",
        f"# source=rehearsal",
        f"# events={n}",
        COLUMNS,
    ]
    for row in rows:
        stamp = _dt.datetime.strptime(row, "%Y.%m.%d %H:%M:%S").replace(
            tzinfo=_dt.timezone.utc).timestamp()
        lines.append(f"{int(stamp)};{row};{row};USD;US;{importance};Rehearsal release")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def states(anchor: int, day: str) -> dict[str, dict]:
    """Each calendar state the gate must name, and the phrase we expect back.

    `anchor` is a moment on the PASS'S OWN CLOCK, not the host's. That distinction is not
    cosmetic and it cost a run: inside the tester `TimeGMT()` returns the simulated window
    time, so a fixture stamped from the host clock (2026-09-20) looks like the FUTURE to
    the EA reading bar times on 2026-09-08 — the freshness test then passes for the wrong
    reason and a 'stale' fixture is judged usable. A fixture's provenance must be stated
    in the frame the reader lives in.
    """
    hard = [8, 10, 12, 14, 16, 18, 20, 22]
    return {
        # Six hours into the window: age runs 0h -> 18h across the pass, never crossing the
        # 24 h budget, and coverage reaches 21 days past it.
        "usable": dict(
            generated=anchor, window_to=anchor + 21 * 86400, declared=None,
            rows=[f"{day} {h:02d}:05:00" for h in hard],
            expect="usable"),
        "stale": dict(
            generated=anchor - 30 * 3600, window_to=anchor + 21 * 86400, declared=None,
            rows=[f"{day} {h:02d}:05:00" for h in hard],
            expect="calendar stale"),
        "truncated": dict(
            generated=anchor, window_to=anchor + 21 * 86400, declared=3,
            rows=[f"{day} 14:05:00"],
            expect="calendar truncated"),
        "empty": dict(
            generated=anchor, window_to=anchor + 21 * 86400, declared=0, rows=[],
            expect="calendar empty"),
        "missing": None,   # nothing on disk at all
    }


@contextlib.contextmanager
def tester_session():
    """The house tester-session discipline, borrowed rather than reinvented.

    A /config launch against a running terminal is a silent single-instance no-op, so the
    terminal must be stopped first — and stopping it means (a) pausing the watchdog, or it
    restarts the host mid-pass, and (b) verifying every paper book is flat, because the EA
    adopts a dangling OPEN as a live virtual position on init. `scripts/midas_parity.py`
    learned both; this reuses its steps instead of approximating them.
    """
    marker = REPO / "scripts" / ".midas_watchdog_paused"
    paused_by_us = not marker.exists()
    if paused_by_us:
        marker.write_text(datetime.now(timezone.utc).isoformat() + "\n")
        print("watchdog paused for this rehearsal session")
    data_folder = ops.data_folder_for_terminal()
    arms = ops.inventory_arms(data_folder)
    flat, bad = ops.verify_all_flat(arms)
    for b in bad:
        print(f"  book problem: {b}")
    if not flat:
        if paused_by_us:
            marker.unlink(missing_ok=True)
        raise SystemExit("ABORT: a paper book is not flat — refusing to stop the terminal")
    pids = ops.terminal_pids_exact()
    print(f"stopping terminal (pids {pids})")
    ops.stop_terminal(pids)
    try:
        yield
    finally:
        print("relaunching the terminal")
        ops.relaunch_terminal()
        if paused_by_us:
            marker.unlink(missing_ok=True)
            print("watchdog unpaused")


def one(state: str, spec: dict | None, cal_path: Path, day: str) -> dict:
    if spec is None:
        cal_path.unlink(missing_ok=True)
    else:
        write_calendar(cal_path, generated=spec["generated"], window_to=spec["window_to"],
                       declared=spec["declared"], rows=spec["rows"])
    tag = f"newsgate_{state}"
    snaps = T.journal_snapshots()      # BEFORE the pass: only the EA's own new lines
    t0 = time.monotonic()
    try:
        T.run_pass(tag, inputs(), dates=DATES, expert=EXPERT)
        err = ""
    except Exception as exc:  # the pass itself can refuse (tick model, timeout)
        err = f"{type(exc).__name__}: {exc}"
    journal = T.appended_text(snaps)
    return {"state": state, "seconds": round(time.monotonic() - t0, 1), "error": err,
            "journal": journal}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", action="append", choices=list(states(WINDOW_ANCHOR, "x")),
                    help="rehearse only this state (repeatable)")
    ap.add_argument("--keep", action="store_true",
                    help="leave the fixture calendar on disk (NOT for a machine that may "
                         "later run the gate for real)")
    a = ap.parse_args(argv)

    T.assert_live_terminal()
    # Preflight the DRIVER, not just the terminal. A pass configured for a symbol this
    # venue does not offer never starts and never reports: the first rehearsal run of this
    # script burned its whole 420 s timeout that way, because the driver's defaults still
    # named the closed V75/Deriv program. Fail in a second instead.
    base = T._BASE_TESTER_INI
    if not str(base.get("Symbol", "")).upper().startswith("XAU"):
        raise SystemExit(f"ABORT: the tester driver's default symbol is {base.get('Symbol')!r} "
                         f"— not the gold symbol this EA trades. Fix the driver defaults; "
                         f"a pass on an unoffered symbol never reports.")
    if str(base.get("FromDate", "")) < T.TICK_COVERAGE_START:
        raise SystemExit(f"ABORT: the default window starts {base.get('FromDate')} but this "
                         f"venue's real ticks begin {T.TICK_COVERAGE_START} — a Model=4 "
                         f"default outside coverage is a generated-tick pass")
    os.makedirs(REPO / "scripts", exist_ok=True)
    cal_path = Path(str(T.TERMINAL_DATA)) / "MQL5" / "Files" / CAL_NAME
    saved = cal_path.read_bytes() if cal_path.is_file() else None
    print(f"terminal data : {T.TERMINAL_DATA}")
    print(f"calendar      : {cal_path}  ({'existing, will be restored' if saved else 'absent'})")
    day = DATES[0]
    want = a.state or list(states(WINDOW_ANCHOR, day))
    results = []
    try:
        with tester_session():
            for state in want:
                spec = states(WINDOW_ANCHOR, day)[state]
                print(f"\n=== {state} ===", flush=True)
                res = one(state, spec, cal_path, day)
                results.append(res)
                if res["error"]:
                    print(f"  pass refused: {res['error']}")
                    continue
                for line in res["journal"].splitlines():
                    if any(k in line for k in ("NEWS FILTER ON", "NEWS SOURCE", "NEWS VETO",
                                               "PAPER FILL", "started | mode=")):
                        print("  " + line.strip()[:160])
                print(f"  ({res['seconds']}s)")
    finally:
        if a.keep:
            print(f"\nfixture left in place: {cal_path}")
        else:
            cal_path.unlink(missing_ok=True)
            if saved is not None:
                cal_path.write_bytes(saved)
                print(f"\nrestored the previous calendar at {cal_path}")
            else:
                print("\nremoved the fixture calendar (no calendar on this machine, as before)")

    print("\n--- verdict per state ---")
    ok = True
    for res, state in zip(results, want):
        spec = states(WINDOW_ANCHOR, day)[state]
        expect = "missing" if spec is None else spec["expect"]
        if res["error"]:
            print(f"  {state:10s} PASS REFUSED ({expect} not exercised): {res['error'][:90]}")
            ok = False
            continue
        hit = expect in res["journal"]
        print(f"  {state:10s} EA said {expect!r}: {'YES' if hit else 'NO'}")
        ok &= hit
    if "usable" in want and not any(r["error"] for r in results):
        vetoed = any("NEWS VETO" in r["journal"] for r in results)
        print(f"  window evaluated at runtime (a NEWS VETO appeared): "
              f"{'YES' if vetoed else 'no signal fell inside a window this pass'}")
    print("\nREHEARSAL " + ("COMPLETE — every state produced the EA's own phrase"
                            if ok else "INCOMPLETE — see the states above"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

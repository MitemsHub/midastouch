"""The flat-gate can no longer pass vacuously on an armed arm.

WHY THIS FILE EXISTS. Measured 2026-09-22 (`docs/LIVE_EXIT_AUDIT_20260922.md` §5): the
parity harness's flat gate discovered arms from chart profiles only, and the live arm is
**start-up-attached** — MT5 never saves a start-up chart to `Profiles`, so the inventory
came up empty, `verify_all_flat([])` returned vacuous truth, and TWO certification runs
stopped the live terminal while the venue held the arm's OPEN position. The position
survived only because its SL/TP live at the venue and the EA re-adopts state on re-init —
a rescue the arm's own design paid for, not one the gate provided.

The fix, pinned here, has three parts:
  1. discovery merges the attach-config arms the watchdog already reads into the
     profile inventory (deduped by ledger), so the one arm that matters has a book
     in the list;
  2. an armed record with zero discovered books REFUSES — "no books" is not "flat";
  3. the venue itself is the second witness: if the ledgers read flat while the venue
     holds a position with the armed arm's magic, the gate refuses — and an
     unanswerable venue refuses too, because silence is exactly what the old gate
     passed on.

The gate block is exercised as written (`exec` against stand-in terminal ops, with the
module's own `R` binding replaced), so these pins fail when the gate's structure drifts,
not merely when a copy of it drifts.
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

GATE_SRC = (REPO / "scripts" / "midas_parity.py").read_text(encoding="utf-8")


class GateReturn(Exception):
    """Stands in for the gate block's `return 4` at exec scope."""

    def __init__(self, code: int):
        self.code = code


class FakeOps:
    """The `R` (mt5_ops) surface the flat gate touches, with answers injected."""

    def __init__(self, *, data_folder, profile_arms=(), startup_arms=(),
                 armed_record=None, armed=True, verify=(True, []),
                 gold_flat=True, venue_count=0, venue_unavailable=False):
        self.data_folder = data_folder
        self.profile_arms = list(profile_arms)
        self.startup_arms = list(startup_arms)
        self.armed_record = armed_record
        self.armed = armed
        self.verify = verify
        self.gold_flat = gold_flat
        self.venue_count = venue_count
        self.venue_unavailable = venue_unavailable
        self.venue_asked_with = None

    ATTACH_INI = "midas_attach.ini"      # mt5_ops.ATTACH_INI, as the gate reads it

    def data_folder_for_terminal(self):
        return self.data_folder

    def inventory_arms(self, df):
        return list(self.profile_arms)

    def startup_attached_arms(self, df):
        return list(self.startup_arms)

    def arming_record(self):
        return self.armed_record

    def arming_state(self):
        if not self.armed:
            return {"armed": False, "override": False, "arm": "",
                    "summary": "no arming record — execution is OFF"}
        return {"armed": True, "override": True, "arm": "U25",
                "summary": "ARMED BY OPERATOR OVERRIDE (test)"}

    def verify_all_flat(self, arms):
        return self.verify

    def ledger_flatness(self, path):
        return {"flat": self.gold_flat, "rows": 12, "open_positions": []}

    def venue_open_position_count(self, symbol, magic):
        self.venue_asked_with = (symbol, magic)
        if self.venue_unavailable:
            return None
        return self.venue_count


def run_gate(tmp: Path, *, fake: FakeOps) -> tuple[int, list[str]]:
    """Extract the gate block from the harness source and run it as written."""
    start = GATE_SRC.index("# flat-check gate")
    start = GATE_SRC.index("data_folder = R.data_folder_for_terminal()", start)
    start = GATE_SRC.rfind("\n", 0, start) + 1          # the LINE start, so dedent works
    end = GATE_SRC.index("pids = R.terminal_pids_exact()", start)
    end = GATE_SRC.rfind("\n", 0, end) + 1
    block = textwrap.dedent(GATE_SRC[start:end]).replace("return 4", "raise GateReturn(4)")

    ns: dict = {"R": fake, "os": os, "GateReturn": GateReturn,
                "GOLD_LEDGER": "MIDASTOUCH_paper_XAUUSD_M1.csv"}
    log: list[str] = []
    ns["print"] = lambda *a, **k: log.append(" ".join(str(x) for x in a))
    try:
        exec(block, ns)  # noqa: S102 - the point: run the gate AS WRITTEN
        return 0, log
    except GateReturn as g:
        return g.code, log


def startup_arm(tmp: Path) -> dict:
    return {"data_folder": str(tmp), "tag": "U25",
            "ledger": str(tmp / "MIDASTOUCH_paper_XAUUSD_U25.csv")}


def armed_record() -> dict:
    return {"arm": "U25", "symbol": "XAUUSD", "magic": "7825001",
            "record_type": "operator_override"}


# --- 1. discovery ---------------------------------------------------------------------

def test_the_start_up_attached_arm_is_discovered(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), venue_count=0)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 0, log
    assert "flat-check OK (1 gold arm book(s)" in log[-1]


def test_profile_and_startup_arms_dedupe_by_ledger(tmp_path):
    arm = startup_arm(tmp_path)
    profile = {"magic": "7825001", "name": "U25", "tag": "U25",
               "chart": "chart01.chr", "ledger": arm["ledger"]}
    fake = FakeOps(data_folder=str(tmp_path), profile_arms=[profile],
                   startup_arms=[arm], armed_record=armed_record(), venue_count=0)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 0, log
    assert "flat-check OK (1 gold arm book(s)" in log[-1], "same ledger must be one arm"


# --- 2. the vacuous pass is gone ------------------------------------------------------

def test_armed_with_zero_discovered_books_refuses(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), armed_record=armed_record(), armed=True)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 4
    assert any("no gold arm book was discovered" in line for line in log), log
    assert any("'no books' is not 'flat'" in line for line in log), log


def test_disarmed_with_zero_books_is_vacuously_flat(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), armed_record=None, armed=False)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 0, log
    assert any("vacuously flat" in line for line in log), log


def test_a_flat_still_refuses(tmp_path):
    """The original gate's refusal path survives the fix."""
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), verify=(False, [{"name": "x", "problem": "open"}]))
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 4
    assert any("not flat" in line for line in log), log


# --- 3. the venue is the second witness ----------------------------------------------

def test_the_venue_is_asked_with_the_record_s_identity(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), venue_count=0)
    run_gate(tmp_path, fake=fake)
    assert fake.venue_asked_with == ("XAUUSD", 7825001), \
        "the question must carry the arming record's own symbol and magic"


def test_venue_holding_a_position_while_ledgers_read_flat_refuses(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), venue_count=1)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 4, log
    assert any("the venue holds 1 open position(s) with magic 7825001" in line
               for line in log), log


def test_an_unanswerable_venue_refuses(tmp_path):
    """None is 'could not ask', not 'zero' — the exact silence the old gate passed on."""
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), venue_unavailable=True)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 4, log
    assert any("could not be asked" in line for line in log), log


def test_an_agreeing_venue_is_said_out_loud(tmp_path):
    fake = FakeOps(data_folder=str(tmp_path), startup_arms=[startup_arm(tmp_path)],
                   armed_record=armed_record(), venue_count=0)
    code, log = run_gate(tmp_path, fake=fake)
    assert code == 0
    assert any("venue cross-check: 0 open position(s)" in line for line in log), log


# --- 4. the pieces the gate leans on --------------------------------------------------

def test_the_reader_exists_and_fails_closed_by_contract():
    import mt5_ops as ops
    assert hasattr(ops, "venue_open_position_count")
    doc = ops.venue_open_position_count.__doc__ or ""
    assert "None" in doc and "fail-closed" in doc, \
        "the reader must document that None means 'could not ask', not 0"
    assert "IN deal bearing our magic" in doc, \
        "attribution is by position, not POSITION_MAGIC — the venue stamps closes magic 0"


def test_verify_all_flat_still_warns_its_callers():
    """The vacuous-truth contract is unchanged; the CALLERS are what were fixed."""
    import mt5_ops as ops
    src_txt = open(ops.__file__, encoding="utf-8").read()
    fn = src_txt.split("def verify_all_flat", 1)[1].split("\ndef ", 1)[0]
    assert "vacuous truth" in fn, "the documented trap must stay documented"


def test_the_gate_merges_attach_config_arms():
    assert "R.startup_attached_arms(data_folder)" in GATE_SRC, \
        "discovery must include the arms no profile will ever hold"
    assert "venue_open_position_count" in GATE_SRC, \
        "the gate must consult the venue's own book"
    assert "R.arming_record()" in GATE_SRC, \
        "the magic and symbol must come from the arming record, not a glob"

"""The sizing tool's two verdicts, and the `$0.00` an operator read as a refusal.

WHY THIS FILE EXISTS. On 2026-09-21 `scripts/verify_sizing_live.py` printed
`BLOCK` next to `$0.00 allowance` on a funded account that had no profit yet and
an arming switch that was off. Nothing had blocked anything:

* the `$0.00` was the Best Day *share* at zero total profit -- undefined at zero,
  not a refusal, and the rule cannot bind on an entry at all; and
* the `BLOCK` was `BlockCode.NOT_ARMED`, folded into the legality check so a legal
  trade on an unarmed system was reported with the same word as a rule refusal.

Both were reporting defects in this repository's own tooling, and a tool that
prints `BLOCK` when nothing is blocked trains its reader to ignore it. So the two
questions are now answered separately and the zero allowance carries its reason.
The tests below are the invariants that make that true rather than promised.

They are pure: no terminal, no MT5, no network. `evaluate_trade` is arithmetic and
`best_day_line` / `verdict_lines` are string builders.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import verify_sizing_live as vsl  # noqa: E402
from midas_prop.execution.prop_execution import (  # noqa: E402
    BEST_DAY_CAP_REACHED,
    BEST_DAY_NO_PROFIT_YET,
    AccountState,
    ArmingDecision,
    BlockCode,
    ContractSpec,
    TradeDecision,
    evaluate_trade,
    size_like_ea,
)
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

SCRIPT = ROOT / "scripts" / "verify_sizing_live.py"

RULES = ThunderboltClassicRules(account_size=25_000.0)

#: The venue's measured basis for XAUUSD ($100 per 1.0 move per lot, measured with
#: `order_calc_profit`), and the arm's own stop geometry.
SPEC = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=100.0,
                    digits=2, usd_per_unit_per_lot=100.0,
                    basis="order_calc_profit")
STOP = 31.84


def _state(today: float = 0.0, others: tuple[float, ...] = ()) -> AccountState:
    """A flat, funded account: equity == balance == peak, so no floor is touched."""
    return AccountState(equity=25_000.0, balance=25_000.0, peak_equity=25_000.0,
                        today_profit=today, other_days_profit=others)


def _decide(state: AccountState) -> TradeDecision:
    """Legality with NO arming decision — exactly how the tool asks the question."""
    return evaluate_trade(RULES, SPEC, state, stop_distance_price=STOP,
                          safety_fraction=0.5, arming=None)


# --------------------------------------------------------------------------- #
# The $0.00: two states, one number
# --------------------------------------------------------------------------- #


def test_the_first_trade_of_a_flat_account_is_legal():
    """The premise of the whole defect: nothing refuses this trade."""
    d = _decide(_state())
    assert d.allowed, d.explain()
    assert d.block_codes == ()
    assert d.sizing is not None and d.sizing.ok


def test_a_zero_allowance_with_no_profit_never_prints_bare():
    """`$0.00` must carry its reason in the same breath — that is the invariant."""
    d = _decide(_state())
    assert d.best_day_allowance_usd == 0.0
    assert d.best_day_basis == BEST_DAY_NO_PROFIT_YET

    line = vsl.best_day_line(d)
    # The number is *immediately* qualified: no reader can lift it out of context.
    assert "$0.00 — NOT a refusal" in line
    assert "no profit is banked yet" in line
    # and it says where the rule actually binds, since that is what was misread
    assert "first profitable CLOSE" in line


def test_a_reached_cap_is_labelled_as_the_refusal_it_is():
    """The other `$0.00` — same number, opposite meaning, and it must say so."""
    d = _decide(_state(today=120.0))
    assert not d.allowed
    assert BlockCode.BEST_DAY_EXHAUSTED in d.block_codes
    assert d.best_day_allowance_usd == 0.0
    assert d.best_day_basis == BEST_DAY_CAP_REACHED

    line = vsl.best_day_line(d)
    assert "$0.00 — today has reached" in line
    assert "IS a refusal" in line


def test_real_headroom_prints_the_number_without_the_word_refusal():
    d = _decide(_state(others=(400.0,)))
    assert d.best_day_allowance_usd == pytest.approx(100.0)
    assert d.best_day_allowance_usd > 0 and d.allowed

    line = vsl.best_day_line(d)
    assert "$100.00" in line
    assert "refusal" not in line.lower()


def test_an_unknown_basis_refuses_to_render():
    """A basis the renderer does not know is a bug, not something to guess at."""
    d = TradeDecision(allowed=True, sizing=None, best_day_basis="invented")
    with pytest.raises(ValueError, match="unknown Best Day basis"):
        vsl.best_day_line(d)


def test_the_engine_always_states_a_basis_it_can_be_read():
    """Every decision carries both a known basis and a sentence explaining it."""
    known = {BEST_DAY_NO_PROFIT_YET, BEST_DAY_CAP_REACHED, vsl.BEST_DAY_HEADROOM}
    for state in (_state(), _state(today=120.0), _state(others=(400.0,)),
                  _state(today=-50.0), _state(today=10.0, others=(900.0,))):
        d = _decide(state)
        assert d.best_day_basis in known, d.explain()
        assert d.best_day_note, d.explain()
        assert vsl.best_day_line(d)  # renders rather than raising


# --------------------------------------------------------------------------- #
# One word `BLOCK` for two different facts
# --------------------------------------------------------------------------- #


def test_a_legal_unarmed_system_is_not_reported_as_blocked():
    """The regression: this output must contain no `BLOCK` at all."""
    d = _decide(_state())
    arming = ArmingDecision(armed=False, reasons=("no arming record at "
                                                  "artifacts/live/armed.json",))
    lines = vsl.verdict_lines(d, arming)
    text = "\n".join(lines)

    assert "LEGAL_BUT_NOT_ARMED" in text
    assert "NOTHING refuses this trade" in text
    assert "BLOCK" not in text, text
    for line in lines:
        assert not line.startswith("VERDICT: BLOCKED"), line


def test_a_rule_refusal_names_what_refused_it():
    """A refusal has to be actionable: the codes, not just the word."""
    d = _decide(_state(today=120.0))
    arming = ArmingDecision(armed=True)
    text = "\n".join(vsl.verdict_lines(d, arming))

    assert "VERDICT: BLOCKED" in text
    assert BlockCode.BEST_DAY_EXHAUSTED in text
    assert "the rules refuse this trade" in text


def test_the_arming_switch_gets_its_own_labelled_line():
    d = _decide(_state())
    for armed, word in ((False, "OFF"), (True, "ARMED")):
        lines = vsl.verdict_lines(d, ArmingDecision(armed=armed))
        labelled = [ln for ln in lines if ln.startswith("arming switch")]
        assert len(labelled) == 1, lines
        assert word in labelled[0]


def test_legality_is_decided_without_the_arming_switch():
    """AST pin, not a text match: the CALL must not be handed an arming decision.

    Prose about arming is fine; an argument that would let an unarmed switch turn a
    legal trade into `BLOCKED` is not. Only `None` is acceptable there.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "evaluate_trade"]
    assert calls, "the tool must actually ask the execution layer"
    for call in calls:
        for kw in call.keywords:
            if kw.arg == "arming":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is None, (
                    "evaluate_trade is handed an arming decision: an unarmed switch "
                    "would then be reported as a rule refusal")


# --------------------------------------------------------------------------- #
# Exit codes
# --------------------------------------------------------------------------- #


def test_exit_codes_separate_a_rule_refusal_from_an_unarmed_switch():
    assert vsl.verdict(True, True) == "LEGAL_AND_ARMED"
    assert vsl.exit_code(True, True) == 0

    assert vsl.verdict(False, True) == "BLOCKED"
    assert vsl.exit_code(False, True) == vsl.EXIT_RULES_REFUSE

    assert vsl.verdict(True, False) == "LEGAL_BUT_NOT_ARMED"
    assert vsl.exit_code(True, False) == vsl.EXIT_NOT_ARMED

    # The whole point, asserted directly: a pipeline can tell these apart.
    assert vsl.EXIT_NOT_ARMED != vsl.EXIT_RULES_REFUSE
    assert vsl.EXIT_NOT_ARMED != 0


def test_the_rendered_verdict_line_carries_its_exit_code():
    d = _decide(_state())
    text = "\n".join(vsl.verdict_lines(d, ArmingDecision(armed=False)))
    assert f"({vsl.EXIT_NOT_ARMED})" in text


# --------------------------------------------------------------------------- #
# The arm's own configured risk, read from the preset the record names
# --------------------------------------------------------------------------- #

PRESET_DIR = ROOT / "mql5" / "MIDASTOUCH"
LIVE_PRESET = "MidastouchAI_upcomers_gold_LIVE.set"


def _record(tmp_path: Path, payload) -> Path:
    p = tmp_path / "armed.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                 encoding="utf-8")
    return p


def test_the_preset_the_arming_record_names_is_the_one_used(tmp_path):
    """Authority is the record, not a filename convention: the U25 arm's preset is
    `..._upcomers_gold_LIVE.set` while its tag is U25 and its paper twin has no `_LIVE`."""
    rec = _record(tmp_path, {"arm": "U25", "preset": LIVE_PRESET})
    path, where = vsl.resolve_arm_preset(record=rec, preset_dir=PRESET_DIR)
    assert path is not None and path.name == LIVE_PRESET
    assert "armed.json" in where


def test_no_arming_record_reports_rather_than_guessing_a_preset(tmp_path):
    """Without a record the arm's configuration is unknown, and the paper preset is
    NOT a fallback — that would answer a question about a different configuration."""
    path, where = vsl.resolve_arm_preset(record=tmp_path / "absent.json",
                                         preset_dir=PRESET_DIR)
    assert path is None
    assert "no arming record" in where and "--preset" in where


def test_a_malformed_or_presetless_record_is_reported_not_swallowed(tmp_path):
    path, where = vsl.resolve_arm_preset(
        record=_record(tmp_path, "{not json"), preset_dir=PRESET_DIR)
    assert path is None and "unreadable" in where

    path, where = vsl.resolve_arm_preset(
        record=_record(tmp_path, {"arm": "U25"}), preset_dir=PRESET_DIR)
    assert path is None and "names no preset" in where


def test_a_named_preset_that_is_not_on_disk_is_reported(tmp_path):
    path, where = vsl.resolve_arm_preset(
        record=_record(tmp_path, {"preset": "MidastouchAI_nope.set"}),
        preset_dir=PRESET_DIR)
    assert path is None and "which is not in" in where


def test_an_explicit_preset_override_wins_and_must_exist(tmp_path):
    path, where = vsl.resolve_arm_preset(record=tmp_path / "absent.json",
                                         preset_dir=PRESET_DIR,
                                         override=str(PRESET_DIR / LIVE_PRESET))
    assert path is not None and where == "--preset"

    path, where = vsl.resolve_arm_preset(record=tmp_path / "absent.json",
                                         preset_dir=PRESET_DIR,
                                         override="does/not/exist.set")
    assert path is None and "does not exist" in where


def test_the_configured_risk_is_read_from_the_preset():
    vals = vsl.parse_preset(str(PRESET_DIR / LIVE_PRESET))
    pair, why = vsl.arm_risk_from_preset(vals)
    assert pair is not None, why
    assert pair == (0.25, 15.0), pair


def test_unreadable_risk_inputs_are_refused_not_defaulted():
    """The EA's repo defaults are not what the arm runs, so a preset missing them is
    unreadable rather than defaulted."""
    for vals, frag in (({"InpRiskPercent": "abc", "InpMaxRiskPct": "15"}, "not a number"),
                       ({"InpRiskPercent": "0.25"}, "InpMaxRiskPct is not in the preset"),
                       ({"InpRiskPercent": "0", "InpMaxRiskPct": "15"}, "not positive"),
                       ({}, "InpRiskPercent is not in the preset")):
        pair, why = vsl.arm_risk_from_preset(vals)
        assert pair is None and frag in why, (pair, why)


# --------------------------------------------------------------------------- #
# Two sizes, both labelled
# --------------------------------------------------------------------------- #


def test_the_two_sizes_are_printed_under_different_labels():
    """The regression this was built for: one unlabelled number read as the other.

    This tool sizes to the venue's daily limit (0.11 lots here); the arm sizes to
    InpRiskPercent of equity (0.01 lots). Both must appear, labelled, and the arm's
    must name the preset it came from.
    """
    d = _decide(_state())
    ea = size_like_ea(SPEC, equity=25_000.0, risk_percent=0.25, max_risk_pct=15.0,
                      stop_distance_price=STOP)
    text = "\n".join(vsl.sizing_lines(d, ea, ea_source=LIVE_PRESET))

    assert "size (this tool)" in text and "size (the ARM)" in text
    tool_line = [ln for ln in text.splitlines() if ln.startswith("size (this tool)")][0]
    arm_line = [ln for ln in text.splitlines() if ln.startswith("size (the ARM)")][0]
    assert tool_line != arm_line
    assert f"{d.sizing.lots:g} lots" in tool_line
    assert f"{ea.lots:g} lots" in arm_line
    assert LIVE_PRESET in arm_line
    assert "InpRiskPercent" in text, "the arm's line must name the input it used"


def test_an_unavailable_arm_size_prints_no_size_at_all():
    """An unreadable preset must not leave a lot figure standing in for the arm's."""
    d = _decide(_state())
    text = "\n".join(vsl.sizing_lines(d, None, ea_unavailable="no arming record"))
    arm_line = [ln for ln in text.splitlines() if ln.startswith("size (the ARM)")][0]
    assert "UNAVAILABLE" in arm_line and "no arming record" in arm_line
    assert "lots" not in arm_line


def test_a_vetoed_arm_size_says_the_ea_refused_it():
    d = _decide(_state())
    ea = size_like_ea(SPEC, equity=150.0, risk_percent=0.25, max_risk_pct=15.0,
                      stop_distance_price=STOP)
    text = "\n".join(vsl.sizing_lines(d, ea, ea_source=LIVE_PRESET))
    arm_line = [ln for ln in text.splitlines() if ln.startswith("size (the ARM)")][0]
    assert "REFUSED by the EA" in arm_line
    assert "lots" not in arm_line.split("REFUSED")[0]


def test_the_decision_block_never_re_emits_a_size():
    """The size is printed once, labelled. `TradeDecision.explain()` prints it too (for
    its own callers), and reprinting that here is how the dollars appeared twice with
    only one copy labelled."""
    for state in (_state(), _state(today=120.0), _state(others=(400.0,))):
        text = "\n".join(vsl.decision_lines(_decide(state)))
        assert "lots" not in text, text


def test_the_decision_block_still_carries_the_reasons_and_codes():
    text = "\n".join(vsl.decision_lines(_decide(_state(today=120.0))))
    assert "REFUSED" in text and "best_day_exhausted" in text

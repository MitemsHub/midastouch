"""Pins for the prop-account execution layer.

The load-bearing tests here are the *refusals*, not the happy path:

* ``test_minimum_lot_that_exceeds_budget_is_refused`` -- MIDASTOUCH went live on a
  $39.58 account where the broker's minimum lot risked more than the whole
  allowable budget, and lost its only trade. Sizing must return an explicit
  refusal there, never a smaller-but-still-wrong lot.
* ``test_unverified_dollar_basis_is_refused_for_live_sizing`` -- the XAUUSD spec
  fields disagreed with the broker by 10x. Sizing off a convention is the error
  this whole module exists to prevent.
* ``test_best_day_allowance_is_zero_on_the_first_profitable_day`` -- the Best Day
  rule is a profit *ceiling*, and on day one that ceiling is $0.00 because any
  profit is 100% of total. It is the least understood rule on the account and the
  one that breaches regardless of whether the strategy has an edge.
* ``test_arming_defaults_off_and_requires_all_three_things`` -- the switch is
  fail-closed on evidence, thresholds and an agreeing operator file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from midas_prop.execution.prop_execution import (  # noqa: E402
    MIN_HOLD_SECONDS,
    AccountState,
    ArmingGate,
    BlockCode,
    ContractSpec,
    GateCriteria,
    ValidationRecord,
    best_day_budget_usd,
    best_day_days_required,
    evaluate_trade,
    order_calc_profit_lots,
    size_position,
    verify_against_broker,
)
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402


RULES = ThunderboltClassicRules(account_size=25_000.0)

#: XAUUSD as MEASURED on the Upcomers terminal 2026-09-19: $100 per $1.00 move
#: per 1.0 lot. The spec's `trade_tick_value` implied ~$10 for the same thing.
GOLD = ContractSpec(
    symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=50.0, digits=2,
    usd_per_unit_per_lot=100.0, basis="order_calc_profit",
    tick_value_field=0.1)


def _unverified(**kw) -> ContractSpec:
    base = dict(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=50.0,
                digits=2, usd_per_unit_per_lot=100.0, basis="assumed")
    base.update(kw)
    return ContractSpec(**base)


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


def test_gold_sizes_to_a_sane_lot_on_a_25000_account():
    """$12,500 daily allowance x 0.5 safety = $6,250... but the daily limit binds first.

    The daily limit is 3% of $25,000 = $750, halved to $375. With a $9.89 stop
    that is 375 / (9.89 x 100) = 0.379 lots -> floored to 0.37.
    """
    s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                      stop_distance_price=9.89)
    assert s.ok
    assert s.lots == pytest.approx(0.37)
    assert s.risk_usd == pytest.approx(0.37 * 9.89 * 100.0)
    assert s.risk_usd <= s.budget_usd + 1e-6
    assert s.budget_usd == pytest.approx(375.0)
    assert "daily 3% limit" in s.budget_note


def test_sizing_never_exceeds_the_budget():
    """Flooring to lot step must never overshoot; overshooting is the failure mode."""
    for stop in (1.0, 3.7, 9.89, 27.5, 100.0):
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=stop)
        assert s.ok, stop
        assert s.risk_usd <= s.budget_usd + 1e-9, stop


def test_lot_step_floors_and_does_not_round_up():
    """0.379 must become 0.37: rounding up would breach the budget it was given."""
    assert GOLD.floor_lots(0.379) == pytest.approx(0.37)
    assert GOLD.floor_lots(0.3) == pytest.approx(0.30)   # no 0.29 float slip
    assert GOLD.floor_lots(0.0) == 0.0
    assert GOLD.floor_lots(-1.0) == 0.0


def test_minimum_lot_that_exceeds_budget_is_refused():
    """The MIDASTOUCH condition: the smallest tradeable size is already too big.

    A $39.58 account, which is the size MIDASTOUCH actually went live on. 3% of
    $39.58 is $1.19, halved to $0.59, while the minimum 0.01 lot risks
    $0.01 x 9.89 x 100 = $9.89 -- about 17x the whole budget.
    """
    tiny_rules = ThunderboltClassicRules(account_size=39.58)
    s = size_position(tiny_rules, GOLD, equity=39.58, balance=39.58,
                      stop_distance_price=9.89)
    assert s.refused
    assert s.lots == 0.0
    assert any("minimum lot" in r and "impossible" in r for r in s.reasons)
    assert "17" in s.reasons[0] or "16" in s.reasons[0]


def test_budget_uses_the_reference_equity_not_the_nominal_account_size():
    """The bug this layer found: sizing off account_size alone ignores reality.

    On a $25,000 account whose equity has fallen to $4,000, the 00:00 reference
    was at least $4,000 and at most the nominal size, so the allowance must be
    3% of $4,000 -- not 3% of $25,000.
    """
    shrunk = size_position(RULES, GOLD, equity=4_000.0, balance=4_000.0,
                           stop_distance_price=9.89)
    nominal = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                            stop_distance_price=9.89)
    assert shrunk.budget_usd == pytest.approx(4_000.0 * 0.03 * 0.5)
    assert shrunk.budget_usd < nominal.budget_usd
    assert "reference equity" in shrunk.budget_note


def test_unverified_dollar_basis_is_refused_for_live_sizing():
    s = size_position(RULES, _unverified(), equity=25_000.0, balance=25_000.0,
                      stop_distance_price=9.89)
    assert s.refused
    assert any("order_calc_profit" in r for r in s.reasons)


def test_unverified_basis_allowed_only_when_explicitly_opted_in():
    s = size_position(RULES, _unverified(), equity=25_000.0, balance=25_000.0,
                      stop_distance_price=9.89, allow_unverified_basis=True)
    assert s.ok
    assert any("UNVERIFIED" in w for w in s.warnings), \
        "an assumed basis must be loud even when permitted"


def test_safety_fraction_default_gives_two_attempts_not_one():
    """At 1.0 a single loss ends the day; at the 0.5 default, two do."""
    full = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                         stop_distance_price=9.89, safety_fraction=1.0)
    half = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                         stop_distance_price=9.89, safety_fraction=0.5)
    assert full.risk_usd == pytest.approx(750.0, rel=0.02)
    # lot-step quantisation costs a couple of percent; that is the floor working
    assert half.risk_usd == pytest.approx(375.0, rel=0.04)
    assert full.risk_usd / RULES.daily_loss_limit_usd == pytest.approx(1.0, rel=0.04)


def test_zero_or_negative_stop_is_refused():
    for bad in (0.0, -1.0):
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=bad)
        assert s.refused
        assert any("must be positive" in r for r in s.reasons)


def test_capping_at_max_lot_warns_rather_than_silently_truncating():
    micro = ContractSpec(symbol="XX", min_lot=1.0, lot_step=1.0, max_lot=2.0,
                         usd_per_unit_per_lot=1.0, basis="order_calc_profit")
    s = size_position(RULES, micro, equity=25_000.0, balance=25_000.0,
                      stop_distance_price=1.0, allow_unverified_basis=False)
    assert s.ok
    assert s.lots == pytest.approx(2.0)
    assert any("capped at max_lot" in w for w in s.warnings)


def test_contract_spec_rejects_incoherent_volumes():
    for kw in ({"min_lot": 0.0}, {"lot_step": 0.0},
               {"min_lot": 1.0, "max_lot": 0.5},
               {"usd_per_unit_per_lot": 0.0}):
        with pytest.raises(ValueError):
            ContractSpec(symbol="X", **kw)


# --------------------------------------------------------------------------- #
# Best Day: a profit ceiling
# --------------------------------------------------------------------------- #


def test_best_day_allowance_is_zero_on_the_first_profitable_day():
    """Any profit on day one is 100% of total profit, so the ceiling is $0.00.

    This is the rule as written, not a modelling artefact, and it is why the
    target cannot be banked in one good day.
    """
    assert best_day_budget_usd(RULES, today_profit=0.0, other_days_profit=[]) == 0.0
    # even a dollar of profit is a breach, so there is no allowance to spend
    assert best_day_budget_usd(RULES, today_profit=1.0, other_days_profit=[]) == 0.0


def test_best_day_ceiling_is_one_quarter_of_other_days_at_twenty_percent():
    """f*R/(1-f) at f=0.20 is R/4."""
    assert best_day_budget_usd(RULES, today_profit=0.0,
                               other_days_profit=[400.0]) == pytest.approx(100.0)


def test_best_day_allowance_shrinks_as_the_day_earns():
    a = best_day_budget_usd(RULES, today_profit=0.0, other_days_profit=[1000.0])
    b = best_day_budget_usd(RULES, today_profit=150.0, other_days_profit=[1000.0])
    assert a == pytest.approx(250.0)
    assert b == pytest.approx(100.0)


def test_best_day_never_returns_a_negative_allowance():
    assert best_day_budget_usd(RULES, today_profit=9e9,
                               other_days_profit=[1.0]) == 0.0


def test_losing_days_do_not_buy_headroom():
    """A losing day adds nothing to the profit denominator."""
    with_loss = best_day_budget_usd(RULES, today_profit=0.0,
                                    other_days_profit=[400.0, -900.0])
    without = best_day_budget_usd(RULES, today_profit=0.0,
                                  other_days_profit=[400.0])
    assert with_loss == without == pytest.approx(100.0)


def test_the_allowance_it_grants_actually_satisfies_the_rule():
    """Round-trip: spending exactly the allowance holds the share AT the cap.

    The fixture has to be a compliant history -- five equal days -- because an
    already-breaching history (e.g. one day at 70% of total) cannot be repaired by
    capping today, and asserting on it would test the wrong thing.
    """
    others = [100.0] * 5
    banked = sum(others)
    assert RULES.best_day_ok(others), "fixture must start compliant"

    allowance = best_day_budget_usd(RULES, today_profit=0.0, other_days_profit=others)
    assert allowance == pytest.approx(banked * 0.2 / 0.8)   # R/4 at f=0.20

    share = allowance / (banked + allowance)
    assert share == pytest.approx(RULES.best_day_pct / 100.0, abs=1e-9)
    assert RULES.best_day_ok(others + [allowance])
    # one cent more today breaks it
    assert not RULES.best_day_ok([*others, allowance + 0.01])


def test_best_day_requires_at_least_five_profitable_days():
    assert best_day_days_required(RULES) == 5
    tight = ThunderboltClassicRules(best_day_pct=50.0)
    assert best_day_days_required(tight) == 2


def test_best_day_rejects_a_degenerate_percentage():
    for bad in (0.0, 100.0, 150.0):
        with pytest.raises(ValueError):
            best_day_budget_usd(ThunderboltClassicRules(best_day_pct=bad),
                                today_profit=0.0, other_days_profit=[1.0])


# --------------------------------------------------------------------------- #
# Pre-trade legality
# --------------------------------------------------------------------------- #


def _state(**kw) -> AccountState:
    base = dict(equity=25_000.0, balance=25_000.0, peak_equity=25_000.0)
    base.update(kw)
    return AccountState(**base)


def test_a_clean_trade_is_allowed_when_armed_elsewhere():
    d = evaluate_trade(RULES, GOLD, _state(), stop_distance_price=9.89,
                       arming=None)
    assert d.allowed, d.explain()
    assert d.block_codes == ()


def test_daily_loss_floor_blocks_a_trade():
    """3% of $25,000 = $750, so the floor sits at $24,250."""
    d = evaluate_trade(RULES, GOLD, _state(equity=24_200.0, balance=25_000.0),
                       stop_distance_price=9.89, arming=None)
    assert not d.allowed
    assert BlockCode.DAILY_LOSS_FLOOR in d.block_codes
    assert any("daily floor" in r for r in d.reasons)


def test_shield_floor_blocks_a_trade():
    """6% of the initial balance = $1,500 below $25,000 -> floor $23,500."""
    d = evaluate_trade(RULES, GOLD,
                       _state(equity=23_400.0, balance=25_000.0,
                              peak_equity=25_000.0),
                       stop_distance_price=9.89, arming=None)
    assert not d.allowed
    assert BlockCode.SHIELD_FLOOR in d.block_codes


def test_shield_floor_trails_the_peak_but_locks_at_initial_balance():
    """Once 6% up the floor stops rising, so the initial balance is safe."""
    assert RULES.drawdown_floor_usd(25_000.0) == pytest.approx(23_500.0)
    assert RULES.drawdown_floor_usd(30_000.0) == pytest.approx(25_000.0)  # locked
    assert RULES.drawdown_floor_usd(26_000.0) == pytest.approx(24_500.0)  # trailing


def test_best_day_exhaustion_blocks_further_trading():
    """Today at $500 against $400 banked: today is 56% of total, so cap is reached."""
    d = evaluate_trade(RULES, GOLD,
                       _state(today_profit=500.0,
                              other_days_profit=(400.0,)),
                       stop_distance_price=9.89, arming=None)
    assert not d.allowed
    assert BlockCode.BEST_DAY_EXHAUSTED in d.block_codes
    assert d.best_day_allowance_usd == 0.0
    assert d.day_profit_cap_usd == pytest.approx(500.0)


def test_the_first_trade_of_a_day_is_never_blocked_by_best_day():
    """A rule that forbids starting is a deadlock, not a constraint."""
    d = evaluate_trade(RULES, GOLD, _state(today_profit=0.0, other_days_profit=()),
                       stop_distance_price=9.89, arming=None)
    assert d.allowed, d.explain()
    assert BlockCode.BEST_DAY_EXHAUSTED not in d.block_codes
    assert any("100% of total profit" in w for w in d.warnings)


def test_best_day_advise_mode_reports_without_blocking():
    d = evaluate_trade(RULES, GOLD,
                       _state(today_profit=500.0, other_days_profit=(400.0,)),
                       stop_distance_price=9.89, arming=None,
                       best_day_mode="advise")
    assert d.allowed
    assert any("advise" in w for w in d.warnings)


def test_best_day_mode_is_validated():
    with pytest.raises(ValueError):
        evaluate_trade(RULES, GOLD, _state(), stop_distance_price=9.89,
                       arming=None, best_day_mode="ignore")


def test_min_hold_blocks_a_close_just_after_the_last_one():
    fresh = evaluate_trade(RULES, GOLD,
                           _state(seconds_since_last_close=MIN_HOLD_SECONDS - 1),
                           stop_distance_price=9.89, arming=None)
    assert not fresh.allowed
    assert BlockCode.MIN_HOLD in fresh.block_codes
    settled = evaluate_trade(RULES, GOLD,
                             _state(seconds_since_last_close=MIN_HOLD_SECONDS + 1),
                             stop_distance_price=9.89, arming=None)
    assert settled.allowed


def test_every_tripped_limit_is_reported_not_just_the_first():
    d = evaluate_trade(RULES, GOLD,
                       _state(equity=23_400.0, balance=25_000.0,
                              peak_equity=25_000.0, today_profit=500.0,
                              other_days_profit=(400.0,),
                              seconds_since_last_close=10.0),
                       stop_distance_price=9.89, arming=None)
    assert not d.allowed
    for code in (BlockCode.DAILY_LOSS_FLOOR, BlockCode.SHIELD_FLOOR,
                 BlockCode.BEST_DAY_EXHAUSTED, BlockCode.MIN_HOLD):
        assert code in d.block_codes, code


def test_sizing_refusal_reaches_the_decision():
    """On a $39.58 account everything is wrong at once; sizing must be among them."""
    tiny_rules = ThunderboltClassicRules(account_size=39.58)
    d = evaluate_trade(tiny_rules, GOLD, AccountState(equity=39.58, balance=39.58,
                                                      peak_equity=39.58),
                       stop_distance_price=9.89, arming=None)
    assert not d.allowed
    assert BlockCode.SIZING_REFUSED in d.block_codes


def test_account_state_rejects_a_peak_below_current_equity():
    with pytest.raises(ValueError):
        _state(equity=26_000.0, peak_equity=25_000.0)


# --------------------------------------------------------------------------- #
# Broker arithmetic
# --------------------------------------------------------------------------- #


def test_order_calc_profit_inversion_gold():
    """The terminal's own answer for XAUUSD: $100 on 1.0 lot over $1.00."""
    assert order_calc_profit_lots(100.0, price_move=1.0, lot_basis=1.0) == 100.0
    # and it is defensive about the inputs
    for kw in ({"price_move": 0.0}, {"lot_basis": 0.0}):
        with pytest.raises(ValueError):
            order_calc_profit_lots(100.0, **{"price_move": 1.0, "lot_basis": 1.0, **kw})


def test_verify_against_broker_catches_the_ten_x_disagreement():
    """The real 2026-09-19 case: the spec implied $10 where the broker said $100."""
    spec = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01,
                        usd_per_unit_per_lot=10.0, basis="spec_tick_value")
    check = verify_against_broker(spec, broker_usd_per_unit_per_lot=100.0)
    assert not check.agrees
    assert check.disagreement_factor == pytest.approx(10.0)
    assert "off by 10.00x" in check.detail


def test_verify_against_broker_accepts_a_one_percent_agreement():
    spec = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01,
                        usd_per_unit_per_lot=100.5, basis="order_calc_profit")
    assert verify_against_broker(spec, broker_usd_per_unit_per_lot=100.0).agrees


# --------------------------------------------------------------------------- #
# The arming switch: fail-closed on every axis
# --------------------------------------------------------------------------- #

GOOD_RECORD = {
    "symbol": "XAUUSD",
    "config_id": "gold_cfg_0001",
    "verdict": "PASS",
    "t_stat": 2.4,
    "positive_fold_pct": 72.0,
    "oos_trades": 640,
    "beats_null": True,
    "cost_included": True,
    "artifact_path": "",       # filled per-test
    "sha256": "",              # filled per-test
    "recorded_utc": "2026-09-19T12:00:00Z",
}


def _write_evidence(tmp_path, **overrides):
    """Write an artifact + validation record + arming file; return the paths."""
    art = tmp_path / "wfo.json"
    art.write_text(json.dumps({"oos_total_r": 20.0}), encoding="utf-8")
    import hashlib
    record = dict(GOOD_RECORD)
    record["artifact_path"] = str(art)
    record["sha256"] = hashlib.sha256(art.read_bytes()).hexdigest()
    record.update(overrides.pop("record", {}))
    val = tmp_path / "validation_record.json"
    val.write_text(json.dumps(record), encoding="utf-8")
    arm = tmp_path / "armed.json"
    arm.write_text(json.dumps({"armed": True, "config_id": "gold_cfg_0001",
                               "symbol": "XAUUSD"}), encoding="utf-8")
    return arm, val


def _gate(tmp_path, arm, val, **kw):
    return ArmingGate(arm_path=arm, validation_path=val, **kw)


def test_arming_is_off_when_no_files_exist(tmp_path):
    d = ArmingGate(arm_path=tmp_path / "nope.json",
                   validation_path=tmp_path / "nope2.json").evaluate()
    assert not d.armed
    assert not d                      # __bool__
    assert any("defaults to OFF" in r for r in d.reasons)


def test_arming_off_when_switch_is_present_but_false(tmp_path):
    arm = tmp_path / "armed.json"
    arm.write_text(json.dumps({"armed": False, "config_id": "x"}), encoding="utf-8")
    d = _gate(tmp_path, arm, tmp_path / "missing.json").evaluate()
    assert not d.armed
    assert any('"armed": true' in r for r in d.reasons)


def test_arming_off_when_switch_names_no_config(tmp_path):
    arm = tmp_path / "armed.json"
    arm.write_text(json.dumps({"armed": True}), encoding="utf-8")
    d = _gate(tmp_path, arm, tmp_path / "missing.json").evaluate()
    assert not d.armed
    assert any("names no config_id" in r for r in d.reasons)


def test_arming_off_when_there_is_no_validation_record(tmp_path):
    arm, _val = _write_evidence(tmp_path)
    d = _gate(tmp_path, arm, tmp_path / "absent.json").evaluate()
    assert not d.armed
    assert any("cleared the walk-forward gate" in r for r in d.reasons)


def test_arming_off_when_switch_and_record_name_different_configs(tmp_path):
    art = tmp_path / "wfo.json"
    art.write_text("{}", encoding="utf-8")
    import hashlib
    record = dict(GOOD_RECORD, artifact_path=str(art),
                  sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
                  config_id="OTHER_cfg")
    val = tmp_path / "validation_record.json"
    val.write_text(json.dumps(record), encoding="utf-8")
    arm = tmp_path / "armed.json"
    arm.write_text(json.dumps({"armed": True, "config_id": "gold_cfg_0001"}),
                   encoding="utf-8")
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("config mismatch" in r for r in d.reasons)


def test_a_failing_t_stat_keeps_the_switch_off(tmp_path):
    """The gold case: t=+0.52 must NOT arm, however good the total looks."""
    arm, val = _write_evidence(tmp_path, record={"t_stat": 0.52})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("below the required 1.5" in r for r in d.reasons)


def test_too_few_positive_folds_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path, record={"positive_fold_pct": 40.0})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("40% of folds positive" in r for r in d.reasons)


def test_a_non_pass_verdict_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path, record={"verdict": "NOT VALIDATED",
                                                 "t_stat": 3.0})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("not PASS" in r for r in d.reasons)


def test_too_few_oos_trades_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path, record={"oos_trades": 12})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("below the required 100" in r for r in d.reasons)


def test_missing_cost_model_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path, record={"cost_included": False})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("cost was not included" in r for r in d.reasons)


def test_a_tampered_artifact_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path)
    import json as _json
    record = _json.loads(Path(val).read_text(encoding="utf-8"))
    Path(record["artifact_path"]).write_text('{"oos_total_r": 999.0}',
                                            encoding="utf-8")
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("has changed since it was certified" in r for r in d.reasons)


def test_a_record_citing_a_missing_artifact_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path, record={"artifact_path": str(tmp_path / "gone.json")})
    d = _gate(tmp_path, arm, val).evaluate()
    assert not d.armed
    assert any("does not exist" in r for r in d.reasons)


def test_a_stale_validation_keeps_the_switch_off(tmp_path):
    arm, val = _write_evidence(tmp_path)
    d = _gate(tmp_path, arm, val, max_age_days=30.0,
              now_utc="2027-09-19T12:00:00Z").evaluate()
    assert not d.armed
    assert any("stale certificate" in r for r in d.reasons)


def test_arming_succeeds_only_when_all_three_conditions_hold(tmp_path):
    """One positive control, so the refusals above are not just a broken gate."""
    arm, val = _write_evidence(tmp_path)
    d = _gate(tmp_path, arm, val).evaluate()
    assert d.armed
    assert d.config_id == "gold_cfg_0001"
    assert any("cleared the gate" in r for r in d.reasons)


def test_an_unarmed_decision_blocks_an_otherwise_legal_trade(tmp_path):
    """The switch outranks the trade: a legal trade on an unarmed system is a block."""
    arm, val = _write_evidence(tmp_path, record={"t_stat": 0.52})
    arming = _gate(tmp_path, arm, val).evaluate()
    d = evaluate_trade(RULES, GOLD, _state(), stop_distance_price=9.89,
                       arming=arming)
    assert not d.allowed
    assert BlockCode.NOT_ARMED in d.block_codes
    assert d.sizing is not None and d.sizing.ok, \
        "the size is still computed and reported; it just may not be placed"


def test_a_partial_validation_record_is_not_evidence(tmp_path):
    val = tmp_path / "validation_record.json"
    val.write_text(json.dumps({"symbol": "XAUUSD", "verdict": "PASS"}),
                   encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        ValidationRecord.load(val)
    assert "is not evidence" in str(exc.value)


def test_gate_criteria_are_pinned_to_the_frozen_document():
    """Changing these changes what 'validated' means, so pin them."""
    c = GateCriteria()
    assert c.min_t_stat == 1.5
    assert c.min_positive_fold_pct == 60.0
    assert c.min_oos_trades == 100
    assert c.require_beats_null and c.require_cost_included

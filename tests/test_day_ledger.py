"""Pins for the persisted day ledger: the stops that a restart must not clear.

THE CLAIM BEING TESTED. "The state is written to disk so a restart cannot silently
resume trading." That is a claim about a *specific* sequence — process stops, process
starts again, and the day that was stopped must still be stopped — and it is the one
behaviour an in-memory stop cannot provide. So the tests below are written as
sequences (write, re-read in a fresh call) rather than as assertions about a live
object.

The second class of test is the refusal: an absent ledger with no broker figure must
NOT be read as "a fresh day with nothing lost". Fail-closed means the unknowable case
is the one that stops trading, and that is easy to get backwards.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synthetic_trader.execution.prop_execution import (  # noqa: E402
    AccountState,
    ContractSpec,
    DailyStopConfig,
    DayLedger,
    HaltReason,
    evaluate_trade,
    reconcile_realised,
    resolve_day_ledger,
    trade_would_breach_day_stop,
)
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

TODAY = "2026-09-19"
RULES = ThunderboltClassicRules(account_size=25_000.0)


def spec(basis: str = "order_calc_profit") -> ContractSpec:
    return ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01,
                        usd_per_unit_per_lot=100.0, basis=basis)


class TestStopLevelsDeriveFromTheVenueRules:
    """The stops are fractions of limits the venue imposes, not invented numbers."""

    def test_loss_stop_is_half_the_venue_limit_by_default(self):
        assert DailyStopConfig().loss_stop_usd(RULES) == pytest.approx(375.0)
        assert RULES.daily_loss_limit_usd == pytest.approx(750.0)

    def test_profit_stop_defaults_to_the_best_day_ceiling(self):
        """20% of the target: the same number the study proved is sufficient."""
        stop = DailyStopConfig().profit_stop_for(RULES)
        assert stop == pytest.approx(250.0)
        assert stop == pytest.approx(RULES.profit_target_usd * 0.20)

    def test_an_explicit_profit_stop_overrides(self):
        assert DailyStopConfig(profit_stop_usd=99.0).profit_stop_for(RULES) == 99.0

    def test_a_nonsense_fraction_is_rejected(self):
        for bad in (0.0, -0.5, 1.5):
            with pytest.raises(ValueError):
                DailyStopConfig(loss_stop_fraction=bad).loss_stop_usd(RULES)


class TestReconciliationTakesTheWorseNumber:
    """A deal closed while the EA was off is still a deal."""

    def test_lower_of_the_two_sources_wins(self):
        assert reconcile_realised(-100.0, -400.0)[0] == -400.0
        assert reconcile_realised(-400.0, -100.0)[0] == -400.0

    def test_disagreement_is_reported_not_hidden(self):
        v, note = reconcile_realised(50.0, -300.0)
        assert v == -300.0
        assert "worse of the two" in note

    def test_agreement_is_silent(self):
        assert reconcile_realised(-10.0, -10.0)[1] == ""

    def test_a_missing_broker_figure_leaves_the_disk_number_alone(self):
        assert reconcile_realised(-10.0, None) == (-10.0, "")


class TestRestartCannotResumeAStoppedDay:
    """The sequence that matters: write, then re-resolve from scratch."""

    def test_a_halted_ledger_is_still_halted_on_the_next_start(self, tmp_path):
        p = tmp_path / "day_ledger.json"
        DayLedger(utc_date=TODAY, realised_usd=-400.0, halted=True,
                  halt_reason=HaltReason.DAILY_LOSS_STOP,
                  halted_at_utc="2026-09-19T10:00:00+00:00").save(p)

        # fresh process: nothing in memory, and the broker reports a *better*
        # number than the file, which must not be grounds to resume.
        ledger, notes = resolve_day_ledger(RULES, ledger_path=p, today=TODAY,
                                           broker_realised_usd=-50.0)
        assert ledger.halted is True
        assert ledger.halted_by_disk is True, "the file's decision, not this run's"
        assert ledger.halt_reason == HaltReason.DAILY_LOSS_STOP
        assert any("restart does not resume" in n for n in notes)

    def test_the_loss_stop_halts_without_any_prior_file(self, tmp_path):
        ledger, _ = resolve_day_ledger(
            RULES, ledger_path=tmp_path / "absent.json", today=TODAY,
            broker_realised_usd=-400.0)
        assert ledger.halted and ledger.halt_reason == HaltReason.DAILY_LOSS_STOP
        assert ledger.halted_by_disk is False

    def test_just_inside_the_stop_does_not_halt(self, tmp_path):
        ledger, _ = resolve_day_ledger(
            RULES, ledger_path=tmp_path / "absent.json", today=TODAY,
            broker_realised_usd=-374.0)
        assert ledger.halted is False

    def test_the_profit_stop_halts_at_the_best_day_ceiling(self, tmp_path):
        ledger, _ = resolve_day_ledger(
            RULES, ledger_path=tmp_path / "absent.json", today=TODAY,
            broker_realised_usd=250.0)
        assert ledger.halted and ledger.halt_reason == HaltReason.DAY_PROFIT_STOP

    def test_a_previous_days_halt_does_not_carry_into_today(self, tmp_path):
        p = tmp_path / "day_ledger.json"
        DayLedger(utc_date="2026-09-18", realised_usd=-900.0, halted=True,
                  halt_reason=HaltReason.DAILY_LOSS_STOP).save(p)
        ledger, notes = resolve_day_ledger(RULES, ledger_path=p, today=TODAY,
                                           broker_realised_usd=0.0)
        assert ledger.halted is False
        assert any("today is" in n for n in notes)


class TestUnknownStateIsARefusalNotAFreshDay:
    """The case a naive restart falls into."""

    def test_no_file_and_no_broker_figure_refuses(self, tmp_path):
        ledger, notes = resolve_day_ledger(RULES, ledger_path=tmp_path / "nope.json",
                                           today=TODAY, broker_realised_usd=None)
        assert ledger.halted is True
        assert ledger.halt_reason == HaltReason.UNKNOWN_STATE
        assert any("cannot tell whether this day was already stopped" in n
                   for n in notes)

    def test_a_corrupt_ledger_is_treated_as_unknown_not_as_empty(self, tmp_path):
        p = tmp_path / "day_ledger.json"
        p.write_text("{ not json", encoding="utf-8")
        ledger, notes = resolve_day_ledger(RULES, ledger_path=p, today=TODAY,
                                           broker_realised_usd=None)
        assert ledger.halted is True
        assert ledger.halt_reason == HaltReason.UNKNOWN_STATE

    def test_a_truncated_ledger_is_refused_rather_than_defaulted(self, tmp_path):
        p = tmp_path / "day_ledger.json"
        p.write_text(json.dumps({"utc_date": TODAY}), encoding="utf-8")
        ledger, _ = resolve_day_ledger(RULES, ledger_path=p, today=TODAY,
                                       broker_realised_usd=None)
        assert ledger.halt_reason == HaltReason.UNKNOWN_STATE

    def test_a_corrupt_ledger_is_still_survivable_with_broker_truth(self, tmp_path):
        """Unreadable state plus an authoritative figure is not unknowable."""
        p = tmp_path / "day_ledger.json"
        p.write_text("{ not json", encoding="utf-8")
        ledger, _ = resolve_day_ledger(RULES, ledger_path=p, today=TODAY,
                                       broker_realised_usd=-100.0)
        assert ledger.halted is False and ledger.realised_usd == -100.0


class TestTheStopBindsBeforeTheTradeNotAfter:
    """A stop that acts after the crossing trade has already failed."""

    def test_a_trade_that_would_cross_the_stop_is_refused(self):
        led = DayLedger(utc_date=TODAY, realised_usd=-200.0)
        msg = trade_would_breach_day_stop(RULES, led, prospective_risk_usd=200.0)
        assert "would cross the day's loss stop" in msg

    def test_a_trade_that_stays_inside_is_allowed(self):
        led = DayLedger(utc_date=TODAY, realised_usd=-100.0)
        assert trade_would_breach_day_stop(RULES, led,
                                           prospective_risk_usd=200.0) == ""

    def test_evaluate_trade_blocks_it_and_names_the_stop(self):
        led = DayLedger(utc_date=TODAY, realised_usd=-200.0)
        d = evaluate_trade(RULES, spec(), AccountState(
            equity=24_800.0, balance=24_800.0, peak_equity=25_000.0),
            stop_distance_price=9.89, ledger=led)
        assert d.allowed is False
        assert HaltReason.DAILY_LOSS_STOP in d.block_codes

    def test_a_halted_ledger_blocks_even_a_perfectly_legal_trade(self):
        led = DayLedger(utc_date=TODAY, realised_usd=-400.0, halted=True,
                        halt_reason=HaltReason.DAILY_LOSS_STOP, halted_by_disk=True)
        d = evaluate_trade(RULES, spec(), AccountState(
            equity=25_000.0, balance=25_000.0, peak_equity=25_000.0),
            stop_distance_price=9.89, ledger=led)
        assert d.allowed is False
        assert HaltReason.DAILY_LOSS_STOP in d.block_codes
        assert any("restart did not clear it" in r for r in d.reasons)

    def test_without_a_ledger_behaviour_is_unchanged(self):
        """Backward compatibility: no ledger means no new blocks."""
        d = evaluate_trade(RULES, spec(), AccountState(
            equity=25_000.0, balance=25_000.0, peak_equity=25_000.0),
            stop_distance_price=9.89)
        assert HaltReason.DAILY_LOSS_STOP not in d.block_codes


class TestLedgerPersistence:
    def test_save_then_load_round_trips(self, tmp_path):
        p = tmp_path / "l.json"
        led = DayLedger(utc_date=TODAY, realised_usd=-12.5, entries=3,
                        risk_per_r_usd=250.0)
        led.save(p)
        back = DayLedger.load(p)
        assert back.realised_usd == -12.5 and back.entries == 3
        assert back.realised_r == pytest.approx(-12.5 / 250.0)

    def test_save_leaves_no_tmp_file_behind(self, tmp_path):
        """Atomic write: the temp file must not survive as a decoy ledger."""
        p = tmp_path / "l.json"
        DayLedger(utc_date=TODAY).save(p)
        assert p.is_file()
        assert not list(tmp_path.glob("*.tmp"))

    def test_save_records_when_it_was_written(self, tmp_path):
        p = tmp_path / "l.json"
        led = DayLedger(utc_date=TODAY)
        assert led.written_utc == ""
        led.save(p)
        assert led.written_utc, "an undated ledger cannot be judged stale"

    def test_zero_risk_does_not_divide_by_zero(self):
        assert DayLedger(utc_date=TODAY, realised_usd=10.0).realised_r == 0.0

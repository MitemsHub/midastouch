"""Pins for the Best Day concentration study's arithmetic and its entry rules.

WHY THESE TESTS EXIST. `scripts/gold_wfo_v2.simulate` gained two optional entry rules
(`day_cap_r`, `max_per_day`) that a funded account's survival depends on, and the study
that concludes "no cap preserves this edge" rests on those rules being what they claim.
Two failure modes are worth guarding specifically:

1. **A cap that silently does nothing.** If `day_cap_r` were ignored, or applied as a
   post-hoc filter, the study would report that capping is harmless — the opposite of
   what it measured. So the cap is tested against a hand-built window where the correct
   answer is known by construction, not against the market.
2. **A share computed where no profit exists.** The first draft reported a losing
   variant as `best_day_share = nan -> BREACH`. A window with no profit has no
   concentration to breach, and reporting one is a verdict about a quantity that does
   not exist. `best_day_ok` must be `None` there, and that is pinned.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_best_day_study as study  # noqa: E402
from midas_prop.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

DAY = 86400


def trade(entry_i: int, exit_i: int, net_r: float) -> dict:
    return {"entry_i": entry_i, "exit_i": exit_i, "net_r": net_r,
            "direction": 1, "exit_reason": "target"}


class TestDayTable:
    """Day aggregation is the measurement the whole study rests on."""

    def test_groups_by_utc_day_of_entry(self):
        epoch = [0.0, 100.0, DAY + 100.0, 2 * DAY + 100.0]
        trades = [trade(0, 0, 1.0), trade(1, 1, 2.0), trade(2, 2, -3.0),
                  trade(3, 3, 4.0)]
        d1, d2, d3 = (date(1970, 1, 1), date(1970, 1, 2), date(1970, 1, 3))
        t = study.day_table(trades, epoch)
        assert t["n"][d1] == 2 and t["n"][d2] == 1 and t["n"][d3] == 1
        assert t["r"][d1] == pytest.approx(3.0), "two trades on day one sum"
        assert t["r"][d2] == pytest.approx(-3.0)

    def test_counts_trades_whose_exit_day_differs(self):
        """The entry/exit convention must be MEASURED, not assumed identical."""
        epoch = [22 * 3600.0, DAY + 3600.0]
        # exits just after midnight: a different UTC day from the entry
        t = study.day_table([trade(0, 1, 1.0), trade(1, 1, 1.0)], epoch)
        assert t["exit_day_differs"] == 1


class TestConcentration:
    """The claim 'not a few lucky trades' is read off this function."""

    def test_top_share_is_over_positive_values_only(self):
        trades = [trade(0, 0, r) for r in (10.0, 1.0, 1.0, 1.0, -50.0)]
        c = study.concentration({"r": {1: 13.0, 2: -50.0}, "n": {1: 4, 2: 1}},
                                trades)
        # top 1% of 4 positive trades = 1 trade = 10 of 13
        assert c["top_1pct_trades_share_of_gross_profit"] == pytest.approx(10 / 13,
                                                                         abs=1e-4)
        assert c["winning_trades"] == 4

    def test_correlation_sign_tracks_which_days_are_busy(self):
        """The sign of this correlation is the study's whole mechanism claim.

        Busy days profitable -> positive, and a per-day cap cuts the profitable
        days. Busy days losing -> negative, and the cap is harmless (or helps).
        """
        epoch = [float(i * DAY) for i in range(4)]
        up = ([trade(0, 0, 1.0)] * 3 + [trade(1, 1, 1.0)] * 2
              + [trade(2, 2, 1.0)] + [trade(3, 3, -1.0)])
        c = study.concentration(study.day_table(up, epoch), up)
        assert c["corr_trades_per_day__day_r"] > 0
        down = ([trade(0, 0, -1.0)] * 3 + [trade(1, 1, -1.0)] * 2
                + [trade(2, 2, -1.0)] + [trade(3, 3, 5.0)])
        c = study.concentration(study.day_table(down, epoch), down)
        assert c["corr_trades_per_day__day_r"] < 0


class TestUnprofitableWindowReporting:
    """Regression pin for the `nan -> BREACH` verdict bug."""

    def _summarise(self, day_r: dict):
        rules = ThunderboltClassicRules(account_size=25000.0)
        day = {"r": day_r, "n": {d: 1 for d in day_r}, "exit_day_differs": 0}
        variant = {"label": "t", "_oos_trades": [], "_epoch": [0.0]}
        return study.summarise(variant, day, [0.0, 0.0], [], rules)

    def test_losing_window_has_no_share_and_no_breach(self):
        s = self._summarise({1: -5.0, 2: -3.0})
        assert s["best_day_share"] is None
        assert s["best_day_ok"] is None, "no profit exists, so nothing is breached"
        assert s["risk_window_open"] is False

    def test_profitable_window_reports_scale_free_share(self):
        s = self._summarise({1: 40.0, 2: 10.0})
        assert s["best_day_share"] == pytest.approx(0.8)
        assert s["best_day_ok"] is False

    def test_resizing_does_not_move_the_share(self):
        """Best Day has no `r` in it -- the study's central structural claim."""
        for mult in (0.01, 1.0, 100.0):
            s = self._summarise({1: 40.0 * mult, 2: 10.0 * mult})
            assert s["best_day_share"] == pytest.approx(0.8)


ARTIFACT = ROOT / "artifacts" / "gold_wfo_v2.json"


@pytest.mark.skipif(not ARTIFACT.is_file(), reason="walk-forward v2 artifact absent")
class TestRefactorIsFaithful:
    """`prepare()` extraction and the `atr_lo/atr_hi` hoist must not move a number.

    The uncapped variant re-runs the whole grid and the walk-forward, so it is
    allowed to be slow; it is skipped rather than failed when the market data is
    not on this machine, because a missing data file is not a broken refactor.
    """

    def test_uncapped_reproduces_published_v2_numbers(self):
        d = json.loads(ARTIFACT.read_text())
        rules = ThunderboltClassicRules(account_size=25000.0)
        import gold_wfo_v2 as w2
        try:
            P = w2.prepare(d["symbol"], bars=60000)
        except (FileNotFoundError, OSError) as exc:
            pytest.skip(f"market data unavailable: {exc}")
        run = study.run_variant({"label": "uncapped"}, P, w2.configs(),
                                P["folds"], rules)
        assert len(run["_oos_trades"]) == d["oos_trades"]
        assert sum(run["_oos_rs"]) == pytest.approx(d["oos_total_r"], abs=1e-6)
        assert len(run["_oos_rs"]) == d["oos_folds"]

    def test_the_atr_band_argument_changes_nothing(self):
        """The profiling hoist must be exact, not merely close."""
        import gold_wfo_v2 as w2
        try:
            P = w2.prepare("XAUUSD", bars=8000)
        except (FileNotFoundError, OSError) as exc:
            pytest.skip(f"market data unavailable: {exc}")
        cfg = w2.configs()[0]
        kw = dict(start=w2.WARMUP_BARS, end=P["holdout_start"])
        args = (P["B"], P["hours"], P["h1_ok_long"], P["h1_ok_short"],
                P["h4_ok_long"], P["h4_ok_short"], P["atr"], cfg)
        computed = w2.simulate(*args, **kw)
        hoisted = w2.simulate(*args, atr_lo=P["atr_lo"], atr_hi=P["atr_hi"], **kw)
        assert [t["net_r"] for t in hoisted] == [t["net_r"] for t in computed]
        assert [t["entry_i"] for t in hoisted] == [t["entry_i"] for t in computed]

"""Is the blackout rule measuring anything, and is +/-15 minutes the right width?

WHY THIS FILE EXISTS. `scripts/gold_news_event_study.py` produces the two numbers a width
decision needs — how much of a release's own move a given half-width captures, and how many
entry opportunities that half-width suppresses. Both are easy to produce wrong in ways that
look confident, and the first version of the script did exactly that:

  * THE BASELINE. Comparing a 60-minute move to a fixed 15-minute baseline reported "2.40x",
    which is the square-root-of-time scaling of a random walk (|60m| ~ 2 x |15m|), not a
    release effect. The baseline must be the corpus's own move over the SAME number of bars
    at the SAME UTC hour, or the statistic is measuring the horizon.
  * THE FOOTPRINT. The exposure a blackout removes is the path from the last close it would
    have allowed before the window to the first close it allows after it — not the move
    inside the window, which no position could have been opened into. That also makes the
    horizon a measured quantity, which the matched baseline needs.

Both are pinned here against corpora whose answer is known exactly (a $1-per-bar ramp makes
every k-bar move exactly k), so a regression cannot hide inside the real data's noise.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import gold_news_event_study as E  # noqa: E402
import gold_news_sensitivity as NS  # noqa: E402
import gold_walkforward as W  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

M15 = 900
#: A UTC midnight, so a bar's hour is arithmetic rather than a timezone question.
BASE = (1_770_000_000 // 86400) * 86400


def _ramp(n: int, start: int = BASE) -> dict:
    """A corpus where every k-bar move is exactly $k — the degenerate case that makes the
    baseline and footprint answers checkable by hand."""
    epoch = np.array([start + i * M15 for i in range(n)], dtype=float)
    return {"epoch": epoch, "close": np.arange(1.0, n + 1.0), "open": np.arange(1.0, n + 1.0),
            "high": np.arange(1.0, n + 1.0), "low": np.arange(1.0, n + 1.0),
            "spread": np.full(n, 20.0), "volume": np.full(n, 100.0)}


def _random_walk(n: int = 4000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    epoch = np.array([BASE + i * M15 for i in range(n)], dtype=float)
    close = 2000.0 + np.cumsum(rng.normal(0.0, 0.6, n))
    B = {"epoch": epoch, "open": close, "high": close + 0.3, "low": close - 0.3,
         "close": close, "spread": np.full(n, 20.0), "volume": np.full(n, 100.0)}
    B["atr"] = W.wilder_atr(B["high"], B["low"], B["close"], W.ATR_PERIOD)
    return B


def _flat_stats(scale_by_hour: dict[int, float] | None = None) -> dict:
    """Hand-built per-hour baselines: horizon k for hour 10, 5k for hour 14."""
    mult = {h: 5.0 if h == 14 else 1.0 for h in range(24)}
    mult.update(scale_by_hour or {})
    return {h: [np.full(200, m * k, dtype=float) for k in range(E.MAX_K + 1)]
            for h, m in mult.items()}


def _ev(epoch: int, name: str = "Nonfarm Payrolls") -> NC.Event:
    return NC.Event(epoch=int(epoch), currency="USD", importance="HIGH", name=name)


# --- the close index --------------------------------------------------------------------

def test_close_at_is_the_last_close_at_or_before_the_instant():
    """Everything downstream is indexed by the close the engine could have filled at, so
    one bar of slack here moves every measurement."""
    B = _ramp(10)
    assert E.close_at(B, B["epoch"][3] + M15) == 3
    assert E.close_at(B, B["epoch"][3] + M15 + 1) == 3
    assert E.close_at(B, B["epoch"][0] + M15 - 1) == -1, "before the first close"
    assert E.close_at(B, B["epoch"][-1] + 10 * M15) == 9, "a later instant still closes at bar 9"


# --- the baseline ------------------------------------------------------------------------

def test_the_baseline_is_horizon_matched_not_a_fixed_window():
    """A $1-per-bar ramp makes the correct answer exact: a k-bar move is $k and the
    corpus's own k-bar median is $k, so the ratio is 1.00 at every horizon."""
    B = _ramp(4000)
    stats = E.hour_move_stats(B)
    for k in range(1, E.MAX_K + 1):
        assert float(np.median(stats[12][k])) == pytest.approx(float(k))
    a = E.abnormal(B, stats, 12, 1000, 1004)
    assert a["bars"] == 4 and a["move"] == pytest.approx(4.0)
    assert a["ratio"] == pytest.approx(1.0)
    # The defect this replaced: against a fixed 15-minute baseline the same ordinary
    # 60-minute move reads 4.00x, which is the horizon and nothing else.
    assert a["move"] / float(np.median(stats[12][1])) == pytest.approx(4.0)


def test_the_baseline_is_hour_matched_or_the_time_of_day_is_read_as_a_release():
    """The same $4 move over the same 4 bars, judged in two hours whose ordinary
    volatility differs: the number must move with the hour, not only with the move."""
    B = _ramp(400)
    stats = _flat_stats()
    assert E.abnormal(B, stats, 10, 10, 14)["ratio"] == pytest.approx(1.0)
    assert E.abnormal(B, stats, 14, 10, 14)["ratio"] == pytest.approx(0.2)


def test_the_baseline_covers_the_widest_footprint_a_release_can_produce():
    """A release landing exactly on a bar close gives the widest footprint its window can
    produce, and the baseline table must reach that far. One horizon short does not
    misreport: `abnormal` returns None and the event leaves the study with no reason."""
    B = _ramp(200)
    at = B["epoch"][100] + M15
    for w in E.WIDTHS:
        lo, hi = E.blackout_footprint(B, at, w)
        assert hi - lo <= E.MAX_K, f"width {w} spans {hi - lo} bars, table holds {E.MAX_K}"
    assert E.MAX_K >= 2 * E.REF_MIN // 15 + 2


def test_a_dropped_event_says_why_it_was_dropped():
    """Two of this calendar's in-range events sit in a UTC hour the corpus holds a single
    bar of. Refusing them is right; refusing them silently is how a study loses events and
    still reports a count."""
    B = _ramp(400)
    thin = {h: [np.full(1, float(k)) for k in range(E.MAX_K + 1)] for h in range(24)}
    ev = _ev(B["epoch"][200] + M15)
    assert E.drop_reason(B, _flat_stats(), ev) == "", "measurable events have no reason"
    assert E.measure(B, _flat_stats(), ev) is not None
    assert E.drop_reason(B, thin, ev) == "no baseline"
    assert E.drop_reason(B, _flat_stats(), _ev(B["epoch"][-1] + M15)) == "no bars"


def test_a_thin_baseline_refuses_rather_than_reporting_a_ratio():
    """A ratio computed off a handful of windows is a number, not a measurement."""
    B = _ramp(400)
    thin = {12: [np.full(50, float(k)) for k in range(E.MAX_K + 1)]}
    assert E.abnormal(B, thin, 12, 10, 14) is None, "50 ordinary windows is not a baseline"
    assert E.abnormal(B, {}, 12, 10, 14) is None, "no data for that hour at all"
    assert E.abnormal(B, thin, 12, 14, 10) is None, "a non-positive horizon"
    assert E.abnormal(B, thin, 12, 400, 420) is None, "beyond the corpus"


def test_ten_percent_of_ordinary_windows_beat_their_own_p90():
    """The null the width table is read against, measured rather than asserted: if a move is
    compared to the corpus's own p90 for its horizon and hour, ~10% of ordinary windows
    exceed it. A release response of 1.02x therefore means nothing at all."""
    B = _random_walk()
    stats = E.hour_move_stats(B)
    hits = total = 0
    for j in range(1000, 3000, 17):
        hour = datetime.fromtimestamp(float(B["epoch"][j]), timezone.utc).hour
        a = E.abnormal(B, stats, hour, j - 1, j + 3)
        if a is None:
            continue
        total += 1
        hits += a["move"] > a["p90"]
    assert total > 100
    assert 0.04 <= hits / total <= 0.20, f"{hits}/{total} of ordinary windows beat their p90"


# --- the footprint -----------------------------------------------------------------------

@pytest.mark.parametrize("offset_min,width_min,want", [
    (0, 15, 4),      # the release lands exactly on a close: the edge bars are vetoed too
    (7.5, 15, 3),    # mid-bar, which is why the measured median over real events is 3
    (0, 45, 8),
])
def test_the_footprint_brackets_exactly_the_bars_the_rule_vetoes(offset_min, width_min, want):
    """The definition, checked against the live rule's own mask rather than restated: the
    footprint runs from the last close the blackout ALLOWS to the first one it allows after,
    so the bars it spans are precisely the barred closes plus the two allowed endpoints."""
    B = _ramp(120)
    at = B["epoch"][60] + M15 + int(offset_min * 60)
    lo, hi = E.blackout_footprint(B, at, width_min)
    assert hi - lo == want
    mask = NS.blackout_mask(B["epoch"], (_ev(at),), window_min=width_min)
    assert list(np.nonzero(mask)[0]) == list(range(lo + 1, hi))
    assert not mask[lo] and not mask[hi]
    # the endpoints really are outside the window, which is what makes the horizon "allowed
    # entry to allowed entry" rather than "whatever the window happened to span"
    assert B["epoch"][lo] + M15 < at - width_min * 60
    assert B["epoch"][hi] + M15 > at + width_min * 60


def test_a_footprint_that_would_run_off_the_corpus_is_refused():
    B = _ramp(60)
    assert E.blackout_footprint(B, B["epoch"][0] + M15, 60) is None
    assert E.blackout_footprint(B, B["epoch"][-1] + M15, 15) is None


# --- the release's own measurement ---------------------------------------------------------

def test_capture_is_bounded_and_a_real_release_moves_the_ratio():
    """A $1-per-bar ramp has no release in it: every width reads ordinary, and the capture
    of the widest window is 1.00 by definition. A jump inside the window has to show."""
    B = _ramp(1000)
    stats = _flat_stats()
    row = E.measure(B, stats, _ev(B["epoch"][500] + M15))
    assert row is not None
    assert row["ratio_60"] == pytest.approx(1.0)
    assert row["pre_ratio"] == pytest.approx(1.0), "nothing moves before a scheduled release"
    assert row["capture_60"] == pytest.approx(1.0)
    assert 0.0 < row["capture_15"] < 1.0, "a narrower window captures less of the move"

    B2 = _ramp(1000)
    B2["close"] = B2["close"].copy()
    B2["close"][502:] += 25.0        # a $25 release, inside the +/-60 min footprint
    hot = E.measure(B2, _flat_stats(), _ev(B2["epoch"][500] + M15))
    assert hot["ratio_15"] > 5.0
    assert hot["over_p90_15"] is True
    assert hot["pre_ratio"] == pytest.approx(1.0), "the clock check still reads clean"


def test_an_event_without_a_full_reference_window_is_skipped_not_approximated():
    B = _ramp(400)
    last = B["epoch"][-1] + M15
    assert E.measure(B, _flat_stats(), _ev(last)) is None


# --- the cost side --------------------------------------------------------------------------

def _events(B: dict, every: int = 40, count: int = 38) -> tuple[NC.Event, ...]:
    return tuple(_ev(B["epoch"][i * every + 10] + M15) for i in range(1, count + 1))


def test_the_exposure_table_is_the_cost_side_and_is_monotone_in_width():
    """Widening the window can only suppress more, and it can never suppress more entry
    bars than bars. The last column is the only cost that is real."""
    B = _random_walk(1600)
    events = _events(B)
    rows = E.exposure(B, events, None)
    assert [r["width_min"] for r in rows] == list(E.WIDTHS)
    assert all(r["entry_bars"] <= r["bars"] for r in rows)
    bars = [r["bars"] for r in rows]
    assert bars == sorted(bars), "a wider blackout cannot suppress fewer bars"
    assert rows[-1]["bars"] > rows[0]["bars"]


def test_the_currency_scope_is_a_filter_not_a_decoration():
    """The EA's gate blocks any HIGH row it reads; the study's counts are per currency. That
    gap is why the probe declares `InpCurrency` — regenerating it with an empty currency
    would silently widen the rule to every currency without touching a preset."""
    B = _random_walk(1600)
    events = _events(B)
    all_ccy = E.exposure(B, events, None)
    usd = E.exposure(B, events, "USD")
    eur = E.exposure(B, events, "EUR")
    assert all(u["entry_bars"] <= a["entry_bars"] for u, a in zip(usd, all_ccy))
    assert any(u["bars"] > 0 for u in usd)
    assert all(r["bars"] == 0 for r in eur), "an all-USD calendar must suppress nothing for EUR"


def test_the_study_states_the_conventions_it_measures_under():
    """A number without its baseline, its horizon and its currency scope is not evidence."""
    src = (REPO / "scripts" / "gold_news_event_study.py").read_text(encoding="utf-8")
    assert "horizon- and hour-matched" in src
    assert "horizon-matched" in src and "measured_from" in src
    assert "WIDTHS_CAPTURE" in src, "widths below one bar cannot be measured close-to-close"
    assert "MIN_EVENTS_FOR_GROUP" in src
    assert "MetaQuotes serves calendar history" in src, "the history caveat is stated"

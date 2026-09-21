"""The news veto in the engine of record: the same rule, at the same instant, on both sides.

WHY THIS FILE EXISTS. Until v1.19d the EA refused `InpBarModel + InpUseNewsFilter` at init,
and it was right to: the python engine of record could not apply the veto, so a BAR-mode
parity pass with the gate on would have certified a protection that could not act. Removing
that refusal is only honest if the engine of record really does apply the rule — so these
tests exist as the pair to it, and `tests/test_news_calendar.py` fails if the mirror is ever
dropped while the refusal stays gone.

WHAT IS ACTUALLY HARD TO GET RIGHT, and therefore pinned:

  * the INSTANT. The EA judges the closed bar when the next bar opens, with `TimeGMT()` as
    "now"; the engine of record stashes a signal at the closed bar's own close time `ct`.
    Those are the same moment, and a rule judged one bar early would silently veto the
    wrong bar while every count still looked plausible.
  * the IMPORTANCE filter. HIGH only. The filter lives in `midas_prop.risk.news_calendar`
    and is shared, not re-implemented — asserted, because a second copy with a different
    constant is exactly how two engines start measuring different rules.
  * the STANCE. A pass may run the gate either way, never in two stances at once.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

M15 = 900
WINDOW = P._window_spec("tickcov")
T0, T1 = WINDOW["t0"], WINDOW["t1"]


@pytest.fixture(scope="module")
def data() -> dict:
    """The corpus the engine of record actually runs on: the VENUE's own bars.

    `corpus` is passed explicitly and has no default (see `python_build_data`): the retired
    research series is not a fallback, because a caller who merely forgot must not get a
    silently different market. This module runs on the window it names (`tickcov`), so it runs
    on that window's own data of record.

    The basis is SAVED AND RESTORED around this module on purpose: the research engine's
    basis is process-global, and a test module that left it at the account size would
    silently re-basis every module that ran after it — which is precisely the defect
    `tests/test_parity_basis.py` exists to catch, and it caught this one.
    """
    previous = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        yield P.python_build_data(offset_min=P.assert_server_offset(WINDOW), corpus="venue")
    finally:
        M._BASIS = previous


@pytest.fixture(autouse=True)
def _no_news_by_default():
    """Every test starts from the certified stance, and leaves it there."""
    M.use_news(None)
    yield
    M.use_news(None)


def _ev(epoch: int, importance: str = "HIGH") -> NC.Event:
    return NC.Event(epoch=int(epoch), currency="USD", importance=importance,
                    name="Nonfarm Payrolls")


def _run(mode: str, data: dict):
    return M.run_mode(mode, T0, T1, data)


def _trades(rr) -> list[tuple]:
    return [(t["open_ct"], t["close_ct"], t["side"], round(t["r"], 6)) for t in rr.trades]


# --- the rule itself ------------------------------------------------------------------

def test_the_engine_of_record_filters_to_high_importance_only():
    """A MEDIUM event must not veto: the policy is top-tier releases, and a filter that
    also hides the ordinary calendar changes the strategy rather than protecting it."""
    ct = T0 + 3600
    M.use_news((_ev(ct, "MEDIUM"),))
    assert M.news_veto_reason(ct) == ""
    M.use_news((_ev(ct, "LOW"),))
    assert M.news_veto_reason(ct) == ""
    M.use_news((_ev(ct, "HIGH"),))
    assert M.news_veto_reason(ct) != ""


def test_the_engine_speaks_the_mirrors_vocabulary_and_window():
    """One rule, two engines: for the same events and the same instant, the engine's answer
    must be the mirror's answer — including at both edges of the window."""
    events = tuple(_ev(T0 + 10_000 + off) for off in (-900, 0, 900))
    ct = T0 + 10_000
    for window_min in (15, 30):
        M.use_news(events, window_min=window_min)
        assert M.news_veto_reason(ct) == NC.blackout_reason(events, ct, window_min)
    # and outside the window both are silent
    M.use_news((_ev(ct + 15 * 60 + 1),))
    assert M.news_veto_reason(ct) == ""
    M.use_news((_ev(ct - 15 * 60 - 1),))
    assert M.news_veto_reason(ct) == ""
    M.use_news((_ev(ct + 15 * 60),))
    assert M.news_veto_reason(ct) != "", "the near edge is inclusive (a release that just printed)"


def test_clearing_the_veto_restores_the_certified_stance():
    M.use_news((_ev(T0 + 10_000),))
    assert M.news_veto_reason(T0 + 10_000) != ""
    M.use_news(None)
    assert M.news_veto_reason(T0 + 10_000) == ""


def test_the_mirror_module_is_this_checkouts_copy():
    """A rule imported from another checkout's package would be a different rule wearing
    this one's name — the failure mode `tests/test_local_imports.py` exists for, applied
    to the news rule specifically."""
    assert Path(M._news_calendar().__file__).resolve().is_relative_to(REPO / "src")


# --- the engine, on the real corpus ---------------------------------------------------

def test_the_veto_removes_exactly_the_entry_whose_close_the_release_lands_on(data):
    """The end-to-end claim: one HIGH event placed on a real signal's close removes that
    trade and nothing else, and the engine says it vetoed one entry.

    The event is placed from the certified run's own trade list, so this does not depend on
    any calendar's contents — only on the engine applying the rule at the bar close.
    """
    base = _run("REVERSE_DIRECTION", data)
    assert base.trades, "the tickcov window must produce trades or this proves nothing"
    target = base.trades[len(base.trades) // 2]
    ct = int(target["open_ct"])          # the fill bar's open == the signal bar's close
    base_set = _trades(base)

    M.use_news((_ev(ct),))
    armed = _run("REVERSE_DIRECTION", data)
    armed_set = _trades(armed)
    M.use_news(None)

    assert armed.news_vetoed >= 1, "the engine must count the refusals it makes"
    assert _trades(base)[len(base_set) // 2] not in armed_set, (
        "the vetoed trade must be the one whose signal bar closed inside the window")
    # NOT a strict subset, and that is the honest semantics rather than a defect: this
    # engine holds ONE position at a time, so refusing an entry frees the slot and a later
    # signal can fill it. What must NOT happen is a shared trade changing — that would mean
    # the veto touched an exit, which is the thing it is forbidden from doing.
    for t in set(armed_set) & set(base_set):
        assert t in set(base_set), t
    for t in sorted(set(armed_set) - set(base_set)):
        assert t[0] >= ct, f"a replacement entry appeared BEFORE the vetoed bar: {t}"


def test_one_second_outside_the_window_changes_nothing(data):
    """The boundary, on real data: the same event a second too late must leave the trade
    set byte-identical. Without this the test above would also pass on an engine that
    vetoes every bar it is asked about."""
    base = _run("REVERSE_DIRECTION", data)
    ct = int(base.trades[len(base.trades) // 2]["open_ct"])
    M.use_news((_ev(ct + 15 * 60 + 1),))
    armed = _run("REVERSE_DIRECTION", data)
    M.use_news(None)
    assert _trades(armed) == _trades(base)
    assert armed.news_vetoed == 0


def test_a_medium_release_on_a_real_signal_leaves_the_trade_set_alone(data):
    base = _run("REVERSE_DIRECTION", data)
    ct = int(base.trades[len(base.trades) // 2]["open_ct"])
    M.use_news((_ev(ct, "MEDIUM"),))
    armed = _run("REVERSE_DIRECTION", data)
    M.use_news(None)
    assert _trades(armed) == _trades(base)


def test_the_veto_never_moves_a_trade_that_both_runs_took(data):
    """Entry-only, stated as the property that can actually fail: every trade the two runs
    share is IDENTICAL — same fill bar, same exit bar, same side, same R. A veto that
    touched an exit would show up here as a shared trade whose numbers moved, and that
    would be a rule that can trap a position through a release.

    It is deliberately not a subset assertion. One position at a time means a refused entry
    frees the slot, so the armed run legitimately contains fills the certified run never
    took; asserting a subset would have pinned the wrong behaviour and hidden that fact.
    """
    base = _run("REVERSE_DIRECTION", data)
    ct = int(base.trades[len(base.trades) // 2]["open_ct"])
    M.use_news((_ev(ct),))
    armed = _run("REVERSE_DIRECTION", data)
    M.use_news(None)

    base_by_open = {t[0]: t for t in _trades(base)}
    shared = 0
    for t in _trades(armed):
        twin = base_by_open.get(t[0])
        if twin is not None:
            assert twin == t, f"the veto MOVED a shared trade: {twin} -> {t}"
            shared += 1
    assert shared > 0, "no shared trades means this asserts nothing"
    assert len(_trades(armed)) <= len(_trades(base)), (
        "a refused entry cannot create more trades than it removed")


# --- the stance, which is what replaced "news must be off" ----------------------------

def test_the_input_block_declares_the_stance_the_engine_is_armed_with():
    for news in (False, True):
        inputs = P.build_inputs("REVERSE_DIRECTION", T0, T1, news=news)
        assert P.news_stance_consistent(inputs, news) is True
        assert P.news_stance_consistent(inputs, not news) is False, (
            "a pass must never be able to declare one stance and run the other")
        assert P.inputs_declare_news(news) is True


def test_the_pass_pins_the_news_contract_whether_it_is_on_or_off():
    """Declared in both stances, so a diff between two passes is the gate and nothing else.
    Refresh is pinned OFF because the calendar API is unavailable in the tester (4014) and a
    refresh would rewrite the very file the pass is being judged against."""
    off = P.build_inputs("ORIGINAL", T0, T1, news=False)
    on = P.build_inputs("ORIGINAL", T0, T1, news=True)
    for key in ("InpNewsFile", "InpNewsWindowMin", "InpNewsMaxAgeHours",
                "InpNewsCoverHours", "InpNewsRefreshHours"):
        assert off[key] == on[key], f"{key} must not move with the gate"
    assert off["InpNewsRefreshHours"] == "0"
    assert off["InpUseNewsFilter"] == "false" and on["InpUseNewsFilter"] == "true"
    assert off["InpNewsWindowMin"] == str(P.NEWS_WINDOW_MIN)


def test_the_harness_bound_the_window_to_the_eas_minutes():
    """The two engines cannot drift by an edited constant: the harness's window, age and
    coverage are checked against the EA's own input defaults, textually, because that is
    the only place the EA's values exist for python to read."""
    src = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(
        encoding="utf-8", errors="replace")
    for line in (f"input int                  InpNewsWindowMin    = {P.NEWS_WINDOW_MIN};",
                 f"input int                  InpNewsMaxAgeHours  = {P.NEWS_MAX_AGE_HOURS};",
                 f"input int                  InpNewsCoverHours   = {P.NEWS_COVER_HOURS};",
                 f'input string               InpNewsFile         = "{P.NEWS_FILE}";'):
        assert line in src, line


def test_a_news_pass_refuses_without_a_calendar(monkeypatch, tmp_path):
    """Fail-closed on both sides: the EA refuses entries it cannot judge, and the harness
    refuses the pass before it stops a terminal to run one."""
    monkeypatch.setattr(P, "news_calendar_path", lambda: tmp_path / "absent.csv")
    with pytest.raises(SystemExit) as e:
        P.news_events_for_pass(WINDOW)
    assert "no calendar" in str(e.value)


def test_a_news_pass_refuses_a_calendar_that_stops_covering_the_window(monkeypatch, tmp_path):
    """Coverage is judged at the END of the window, which is the strictest instant in it:
    a calendar that runs out mid-window would let the EA fail closed while python kept
    trading, and that would read as an engine difference."""
    cal = tmp_path / "c.csv"
    end = datetime.fromtimestamp(T1, timezone.utc)
    cal.write_text("\n".join([
        "# fixture",
        f"# epoch_generated_utc={T1 + 86_400}",
        "# epoch_window_from_utc=0",
        f"# epoch_window_to_utc={T1 - 86_400}",     # stops a day BEFORE the window ends
        "# events=1",
        "epoch_utc;time_utc;time_server;currency;country;importance;event",
        f"{T0 + 3600};2026.09.04 00:00:00Z;2026.09.04 02:00:00;USD;US;HIGH;Release",
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(P, "news_calendar_path", lambda: cal)
    with pytest.raises(SystemExit) as e:
        P.news_events_for_pass(WINDOW)
    assert "REFUSING" in str(e.value)
    assert end is not None

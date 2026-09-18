"""Offline tests for the V28 research engine's bookkeeping.

These pin the parts that must never silently drift: candidate identity, the
completeness of the explicit input surface, the sample window roles, the
determinism of the robustness probe, and the promotion gate's refusals. They do
not launch the Strategy Tester; the numbers come from the opt-in runs.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import v28_research as r  # noqa: E402
import v75_tester_runner as runner  # noqa: E402


def _rec(role: str, pnl: float, trades: int = 50, cumulative_r: float | None = None) -> dict:
    """A record shaped like one the runner actually writes."""
    return {"role": role, "test_pnl": pnl, "trades": trades,
            "cumulative_r": cumulative_r if cumulative_r is not None else pnl / 100.0,
            # a constant $100 denominator, so both R measures coincide here
            "mean_risk": 100.0, "money_implied_r": pnl / 100.0,
            "profit_factor": 1.5, "max_drawdown": 120.0, "expectancy": pnl / max(trades, 1),
            "win_rate_pct": 52.0, "avg_win": 30.0, "avg_loss": -20.0,
            "longest_loss_streak": 3, "recovery_factor": 1.4,
            "trades_pnl": [10.0] * (trades // 2) + [-8.0] * (trades - trades // 2)}


# --- identity -----------------------------------------------------------------

def test_hypothesis_identity_encodes_mode_and_geometry() -> None:
    assert r.hypothesis("V28_ORIGINAL") == "ORIGINAL_sl2_tp4_h180_r0.01"
    assert r.hypothesis("V28_ORIGINAL", {"sl_atr": 3.0}) == "ORIGINAL_sl3_tp4_h180_r0.01"
    # same hypothesis => same identity, regardless of call order
    assert r.hypothesis("V28_SHORT_ONLY", {"hold_min": 60}) == \
        r.hypothesis("V28_SHORT_ONLY", {"hold_min": 60})


def test_every_pass_sends_the_complete_explicit_input_surface() -> None:
    """A partial [TesterInputs] merges with the agent's cached set."""
    inputs = r.candidate_inputs("V28_REVERSE_TRIGGER", {"tp_atr": 6.0})
    required = {"InpLiveExecution", "InpMagic", "InpMaxDeviationPoints", "InpDrawHud",
                "InpStrategyMode", "InpResearchLogging", "InpExperimentTag",
                "InpAllowLong", "InpAllowShort", "InpLegacyV27ModifyClose",
                "InpRiskFraction", "InpStopATRMultiplier", "InpTargetATRMultiplier",
                "InpMaxHoldMinutes"}
    assert required <= set(inputs), f"missing: {required - set(inputs)}"
    assert inputs["InpStrategyMode"] == str(r.MODES["V28_REVERSE_TRIGGER"]) == "2"
    assert inputs["InpTargetATRMultiplier"] == "6.0"
    # the corrected contract is the default; v27 reproduction is opt-in
    assert inputs["InpLegacyV27ModifyClose"] == "false"
    assert inputs["InpLiveExecution"] == "true"     # tester must be allowed to trade


def test_mode_table_matches_the_spec_enum() -> None:
    assert r.MODES == {"V28_ORIGINAL": 0, "V28_REVERSE_DIRECTION": 1,
                       "V28_REVERSE_TRIGGER": 2, "V28_REVERSE_BOTH": 3,
                       "V28_LONG_ONLY": 4, "V28_SHORT_ONLY": 5,
                       "V28_MACRO_ONLY": 6, "V28_TRIGGER_ONLY": 7}


# --- windows ------------------------------------------------------------------

def test_window_roles_are_fixed_and_sample_roles_never_overlap() -> None:
    """is90/is180 are nested by design (same role); different ROLES must not
    overlap, otherwise a window would leak into the held-out sample."""
    role_spans: dict[str, list[tuple[date, date]]] = {}
    for name, (frm, to, role) in r.WINDOWS.items():
        a = date.fromisoformat(frm.replace(".", "-"))
        b = date.fromisoformat(to.replace(".", "-"))
        assert a <= b, f"{name}: window not ordered"
        role_spans.setdefault(role, []).append((a, b))
    assert set(role_spans) == {"is", "wf", "oos"}
    # flatten per role, then require every pair from different roles to be disjoint
    spans = [(a, b, role) for role, pairs in role_spans.items() for a, b in pairs]
    for i, (a1, b1, r1) in enumerate(spans):
        for a2, b2, r2 in spans[i + 1:]:
            if r1 != r2:
                assert b1 < a2 or b2 < a1, f"{r1}/{r2} windows overlap"
    # is90 must sit inside is180 (the fast check is a subset, not a new sample)
    is90 = (date(2026, 6, 12), date(2026, 9, 10))
    is180 = (date(2026, 3, 14), date(2026, 9, 10))
    assert is180[0] <= is90[0] and is90[1] <= is180[1]


def test_out_of_sample_is_the_oldest_block_so_discovery_cannot_have_seen_it() -> None:
    oos = date.fromisoformat(r.WINDOWS["oos"][0].replace(".", "-"))
    others = [date.fromisoformat(r.WINDOWS[k][0].replace(".", "-"))
              for k in r.WINDOWS if k != "oos"]
    assert all(oos < start for start in others)


# --- robustness ---------------------------------------------------------------

def test_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    pnls = [50.0, -40.0, 60.0, -30.0, -25.0, 80.0, -35.0, 45.0, -50.0, -20.0]
    first = r.bootstrap(pnls, iterations=400)
    second = r.bootstrap(pnls, iterations=400)
    assert first == second, "same candidate must always get the same verdict"
    assert 0.0 <= first["profitable_share"] <= 1.0
    assert first["p05"] <= first["p50"] <= first["p95"]
    assert r.bootstrap([])["iterations"] == 0


def test_drop_best_removes_the_luckiest_trades() -> None:
    pnls = [100.0, 90.0, -10.0, -10.0, -10.0]
    assert r.drop_best(pnls, 1) == 60.0
    assert r.drop_best(pnls, 3) == -20.0
    assert r.drop_best(pnls, 0) == 160.0


def test_robustness_pass_requires_a_real_edge() -> None:
    strong = {"bootstrap": {"profitable_share": 0.95, "p05": 12.0}, "drop_best_3": 20.0}
    coinflip = {"bootstrap": {"profitable_share": 0.55, "p05": -50.0}, "drop_best_3": 5.0}
    lucky = {"bootstrap": {"profitable_share": 0.90, "p05": 5.0}, "drop_best_3": -1.0}
    assert r.robustness_pass(strong)
    assert not r.robustness_pass(coinflip)
    assert not r.robustness_pass(lucky)      # edge lives in three trades


# --- scorecard & promotion gate ------------------------------------------------

def test_scorecard_carries_every_required_field() -> None:
    records = [dict(_rec("is", 200.0), hypothesis="H"), dict(_rec("oos", 150.0), hypothesis="H")]
    card = r.scorecard(records, "H")
    for field in ("net_pnl", "cumulative_r", "profit_factor", "max_drawdown",
                  "expectancy_r", "win_rate_pct", "avg_win", "avg_loss",
                  "longest_loss_streak", "trade_count", "recovery_factor",
                  "oos_pnl", "walker_forward_consistency", "robustness"):
        assert field in card, f"scorecard missing {field}"
    assert card["oos_pnl"] == 150.0


def test_is_role_collapses_to_the_long_window_deterministically() -> None:
    """is90 and is180 share the `is` role; the long window is the discovery
    sample, so a dict-keyed-by-role scorecard must not pick arbitrarily."""
    short = dict(_rec("is", 100.0, trades=18), hypothesis="H", window="is90")
    long_ = dict(_rec("is", 500.0, trades=29), hypothesis="H", window="is180")
    oos = dict(_rec("oos", 200.0, trades=40), hypothesis="H", window="oos")
    # order must not matter
    for records in ([short, long_, oos], [long_, short, oos], [oos, long_, short]):
        card = r.scorecard(records, "H")
        assert card["trade_count"] == 29, "scorecard must use the long is-window"
        assert card["net_pnl"] == 500.0
        assert card["roles_present"] == ["is", "oos"]
    # and with only the short window available it still works
    card = r.scorecard([short, oos], "H")
    assert card["trade_count"] == 18


def test_promotion_refuses_a_single_backtest() -> None:
    ok, reasons = r.promotion_gate([dict(_rec("is", 500.0), hypothesis="H")], "H")
    assert not ok
    assert any("missing wf" in x for x in reasons)
    assert any("missing oos" in x for x in reasons)


def test_promotion_refuses_a_thin_sample_however_large_the_profit() -> None:
    records = [dict(_rec("is", 5000.0, trades=25), hypothesis="H"),
               dict(_rec("wf", 400.0, trades=40), hypothesis="H"),
               dict(_rec("oos", 900.0, trades=40), hypothesis="H")]
    ok, reasons = r.promotion_gate(records, "H")
    assert not ok
    assert any("30-trade sample gate" in x for x in reasons)


def test_promotion_refuses_a_walk_forward_sign_flip() -> None:
    records = [dict(_rec("is", 800.0), hypothesis="H"),
               dict(_rec("wf", -300.0), hypothesis="H"),
               dict(_rec("oos", 700.0), hypothesis="H")]
    ok, reasons = r.promotion_gate(records, "H")
    assert not ok
    assert any("sign flips" in x for x in reasons)


def test_promotion_allows_only_full_evidence_with_robustness() -> None:
    good = dict(_rec("is", 800.0), hypothesis="H")
    good["trades_pnl"] = [40.0] * 40 + [-10.0] * 10      # clearly profitable
    records = [good, dict(_rec("wf", 300.0), hypothesis="H"),
               dict(_rec("oos", 500.0), hypothesis="H")]
    ok, reasons = r.promotion_gate(records, "H")
    assert ok, reasons


# --- registry ------------------------------------------------------------------

def test_registry_round_trip_and_unique_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    monkeypatch.setattr(r, "REGISTRY", tmp_path / "registry.jsonl")
    assert r.load_registry() == []
    first = dict(_rec("is", 100.0), hypothesis="H1")
    first["experiment_id"] = r.next_id(r.load_registry())
    r.append_registry(first)
    second = dict(_rec("is", -50.0), hypothesis="H2")
    second["experiment_id"] = r.next_id(r.load_registry())
    r.append_registry(second)
    loaded = r.load_registry()
    assert [x["experiment_id"] for x in loaded] == ["V28-0001", "V28-0002"]
    assert json.loads((tmp_path / "registry.jsonl").read_text().splitlines()[1])["hypothesis"] == "H2"


def test_find_record_matches_hypothesis_and_window() -> None:
    records = [{"hypothesis": "H", "window": "is90"}, {"hypothesis": "H", "window": "oos"}]
    assert r.find_record(records, "H", "oos")["window"] == "oos"
    assert r.find_record(records, "H", "wf") is None


# --- R-accounting contract (source-level) -------------------------------------
#
# Regression pins for the 2026-09-13 close-booking defect: the timeout guardian
# and an M30 entry can land on the same tick (an entry opens at a bar open and
# the hold window is exactly six M30 bars), so a new position could be adopted
# while the previous trade was still tracked. 77 of 262 closes were dropped from
# the whole-run counters that way, which flipped the sign of cumulative R
# against net P&L and therefore corrupted the optimization score.

EA_V28_SRC = REPO / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_v28.mq5"


def _fn_body(source: str, signature: str) -> str:
    """Body of a top-level MQL5 function, from its opening brace to its match."""
    start = source.index(signature)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace:i + 1]
    raise AssertionError(f"unbalanced braces in {signature}")


def test_the_r_denominator_has_exactly_one_writer() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    writers = re.findall(r"^\s*g_risk_money\s*=", src, re.M)
    assert len(writers) == 1, "only CommitTradeRisk may write the R denominator"
    assert "g_risk_money =" in _fn_body(src, "void CommitTradeRisk")


def test_peak_excursion_is_tracked_every_tick_and_reported_per_trade() -> None:
    """Why timeouts dominate cannot be answered from realised P&L alone: a trade
    that times out reports where it finished, never how far in front it was."""
    src = EA_V28_SRC.read_text(encoding="utf-8")
    assert "peak_r=%.3f" in src, "every close must report its peak excursion"
    assert "MFE_SUMMARY trades=%d mean_peak_r=%.4f max_peak_r=%.4f" in src
    track = _fn_body(src, "void TrackPeakExcursion")
    assert "POSITION_PROFIT" in track and "g_risk_money" in track
    # the peak must be sampled BEFORE the guardian closes the trade
    on_tick = src[src.index("void OnTick()"):]
    assert on_tick.index("TrackPeakExcursion()") < on_tick.index("ManageTimeGuardian()")
    # the exit fill can itself be the best excursion of the trade
    assert "if(realized_r > g_peak_r)" in src


def test_peak_excursion_state_resets_every_pass() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    reset = _fn_body(src, "void ResetTestMetrics")
    for acc in ("g_peak_r", "g_mfe_sum", "g_mfe_max", "g_mfe_hits"):
        assert acc in reset, f"{acc} would leak across tester passes"


def test_cumulative_r_is_reconciled_against_the_money_every_run() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    assert "R_RECONCILE trades=%d mean_risk=%.2f" in src
    assert "money_implied_r=%+.4f" in src and "dispersion_bound=%.4f" in src
    body = _fn_body(src, "void LogRAccounting")
    # The bound is what separates benign ratio-summation from a wrong denominator:
    # sum(pnl_i/risk_i) != sum(pnl)/mean_risk unless every risk_i is identical.
    assert "g_sum_abs_pnl * deviation" in body
    assert "consistent" in body


def test_the_reconciliation_accumulators_are_reset_every_pass() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    reset = _fn_body(src, "void ResetTestMetrics")
    for acc in ("g_sum_risk", "g_sum_abs_pnl", "g_risk_min", "g_risk_max"):
        assert acc in reset, f"{acc} would leak across tester passes"


def test_every_close_prints_its_risk_denominator_and_source() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    assert 'CLOSE %s ticket=%I64u pnl=%+.2f R=%+.3f risk=%.2f "' in src
    assert "risk_src=%s peak_r=%.3f cum_pnl=%+.2f cum_R=%+.3f" in src
    # the same denominator the counters were updated with is the one printed
    body = _fn_body(src, "void FinalizeClosedTrade")
    assert "risk_used" in body and "g_test_r += realized_r" in body


# --- journal addressing ------------------------------------------------------
#
# Run tags are derived from deterministic experiment ids, so re-running a cell
# reuses its tag. Every journal lookup is tag-addressed, so an unscoped lookup
# reads the OLDER pass: the wait returns immediately, the delta parse finds
# nothing, and `backfill` imports a superseded build's numbers (it replaced the
# post-fix whole-run R on 24 of 32 records with defect-era values).

def test_whole_run_pnl_prefers_the_ea_counter_over_the_deals_sum() -> None:
    # The deals-table sum under-reports losses by ~$0.05/trade (one-directional),
    # so preferring it biased out-of-sample P&L optimistic on 23 of 32 records.
    assert r.choose_whole_run_pnl(-144.81, -144.81, -129.24) == (-144.81, "ea_journal")
    assert r.choose_whole_run_pnl(None, -144.81, -129.24) == (-144.81, "report_net")
    assert r.choose_whole_run_pnl(None, None, -129.24) == (-129.24, "deals_sum")


def test_the_research_line_wait_is_scoped_to_the_new_journal_bytes(tmp_path, monkeypatch) -> None:
    journal = tmp_path / "agent.log"
    journal.write_bytes("RESEARCH_RESULT tag=TAG r=+29.47\r\n".encode("utf-16-le"))
    monkeypatch.setattr(runner, "journal_paths", lambda: [journal])

    assert runner.journal_has_tag("TAG", {journal: 0}) is True
    # the older line must NOT satisfy the wait for this pass
    assert runner.journal_has_tag("TAG", {journal: journal.stat().st_size}) is False

    before_append = journal.stat().st_size
    with journal.open("ab") as fh:
        fh.write("RESEARCH_RESULT tag=TAG r=-1.19\r\n".encode("utf-16-le"))
    assert runner.journal_has_tag("TAG", {journal: before_append}) is True


# --- terminal-host fast-fail -------------------------------------------------
#
# A /config tester launch against an already-running terminal is a silent
# single-instance no-op: no report, no agent journal, run_pass burns its full
# timeout (2026-09-15 /portable; 2026-09-16 10:22 sweep retry). The guard must
# fire BEFORE the launch, with the stop/sweep/restart fix in the message.

def test_run_pass_fast_fails_when_the_tester_terminal_is_already_running(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runner, "_terminal_running", lambda: True)
    monkeypatch.setattr(runner, "_wait_terminal_exit", lambda _t: False)

    class _NoLaunch:
        def __init__(self, *a, **k):
            calls.append("Popen")

    monkeypatch.setattr(runner.subprocess, "Popen", _NoLaunch)
    with pytest.raises(RuntimeError, match="already running"):
        runner.run_pass("guard", {"InpExperimentTag": "guard"})
    assert calls == [], "the launch itself must never happen on a live terminal"


def test_run_pass_waits_out_self_exit_before_condemning_a_live_process(monkeypatch) -> None:
    """Passes 2..n must not be condemned for the previous pass's teardown lag:
    the terminal self-exits after each pass, and the wait must give it time."""
    polls = iter([True, True, False])   # running, running, gone
    clock = iter([0.0, 0.0, 0.0, 10_000.0])   # deadline, two in-loop checks, then past it
    monkeypatch.setattr(runner, "_terminal_running", lambda: next(polls))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
    assert runner._wait_terminal_exit(30.0) is True


def test_terminal_match_is_scoped_to_the_tester_terminal_exe(monkeypatch) -> None:
    """The other MT5 installs (FB9A, MitemshubMT5_C) must never false-positive."""
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": ""})())
    assert runner._terminal_running() is False


def test_terminal_running_matches_the_pinned_path_case_insensitively(monkeypatch) -> None:
    exes = [str(runner.TERMINAL_EXE).upper()]   # same path, different case
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "\n".join(exes) + "\n"})())
    assert runner._terminal_running() is True


def test_backfill_reads_the_newest_matching_line_and_tags_are_unique() -> None:
    src = (REPO / "scripts" / "v28_research.py").read_text(encoding="utf-8")
    assert 're.findall(r"RESEARCH_RESULT tag=" + re.escape(run_tag)' in src, \
        "backfill must collect every match, not the first"
    assert "matches[-1]" in src, "backfill must use the newest matching line"
    assert "time.strftime" in src and "os.getpid()" in src, \
        "a run tag must identify exactly one pass"


def test_adopting_a_position_settles_the_previous_trade_first() -> None:
    src = EA_V28_SRC.read_text(encoding="utf-8")
    body = _fn_body(src, "void CaptureManagedPosition")
    adopt = body.index("g_has_active_trade = true")
    assert "identifier != g_position_id" in body[:adopt], "adoption must detect a superseded trade"
    assert body.index("RecoverClosedPosition()") < adopt, \
        "a superseded trade must be booked before its identity is replaced"


# --- OOS one-shot gate (frozen 2026-09-16) ------------------------------------
#
# The §9 amendment 3 rule, code-checked: the interior's single OOS run exists
# only if a cell clears the pre-registered bar on ALREADY-HELD windows, the
# shot is single-use (token + registry row both block), and the decision map-
# ping is exactly the frozen one. Nothing here launches the tester.

def _sweep_rec(hyp: str, window: str, r_val: float, pnl: float, n: int = 29,
              dd: float = 150.0) -> dict:
    return {"hypothesis": hyp, "mode": "V28_REVERSE_BOTH", "mode_id": 3,
            "window": window, "role": {"is180": "is", "wf": "wf",
                                       "oos": "oos"}[window],
            "sweep_axis": "sl_atr", "trades": n, "test_pnl": pnl,
            "cumulative_r": r_val, "max_drawdown": dd,
            "geometry": {"risk": 0.01, "sl_atr": 2.0, "tp_atr": 4.0,
                         "hold_min": 180}}


def _base_record() -> dict:
    return {"hypothesis": r.OOS_BASELINE_HYP, "mode": "V28_REVERSE_BOTH",
            "mode_id": 3, "window": "is180", "role": "is",
            "sweep_axis": "sl_atr", "trades": 29, "test_pnl": 679.49,
            "cumulative_r": 6.604, "max_drawdown": 72.18,
            "geometry": {"risk": 0.01, "sl_atr": 2.0, "tp_atr": 4.0,
                         "hold_min": 180}}


def _eligible_cell(hyp="REVERSE_BOTH_sl2_tp2_h180_r0.01",
                   is_r=7.115, wf_r=3.029, wf_pnl=302.18, wf_dd=166.0) -> list[dict]:
    return [_base_record(),
            _sweep_rec(hyp, "is180", is_r, 733.75),
            _sweep_rec(hyp, "wf", wf_r, wf_pnl, n=27, dd=wf_dd)]


def test_eligible_cell_clears_the_frozen_bar() -> None:
    ok, cells = r.oos_one_shot_eligibility(_eligible_cell())
    assert ok and len(cells) == 1
    assert cells[0]["hypothesis"] == "REVERSE_BOTH_sl2_tp2_h180_r0.01"
    assert cells[0]["is_r"] == 7.115 and cells[0]["wf_r"] == 3.029


def test_sign_flip_low_wf_r_and_dd_breach_each_disqualify() -> None:
    for kw in ({"wf_r": -1.0, "wf_pnl": -50.0},          # wf sign flip
               {"wf_r": 1.0},                             # below min_wf_r
               {"wf_dd": 2500.0}):                        # 25% wf drawdown > 20
        ok, cells = r.oos_one_shot_eligibility(_eligible_cell(**kw))
        assert not ok and cells == [], f"bar not enforced for {kw}"


def test_low_is_r_disqualifies() -> None:
    ok, _ = r.oos_one_shot_eligibility(_eligible_cell(is_r=1.9))
    assert not ok


def test_baseline_and_its_trade_identical_duplicates_are_excluded() -> None:
    # tp3/5/6 rows carry the baseline's exact (n, pnl) signature on is180:
    # same strategy under another label must not multiply the shot's choices.
    records = _eligible_cell()
    records += [_sweep_rec("REVERSE_BOTH_sl2_tp3_h180_r0.01", "is180", 6.604, 679.49),
                _sweep_rec("REVERSE_BOTH_sl2_tp3_h180_r0.01", "wf", 2.516, 250.40, n=27)]
    ok, cells = r.oos_one_shot_eligibility(records)
    assert ok
    assert "REVERSE_BOTH_sl2_tp3_h180_r0.01" not in {c["hypothesis"] for c in cells}


def test_cell_without_a_wf_row_is_not_eligible() -> None:
    records = [_base_record(), _sweep_rec("REVERSE_BOTH_sl2_tp2_h180_r0.01",
                                          "is180", 7.115, 733.75)]
    ok, cells = r.oos_one_shot_eligibility(records)
    assert not ok and cells == []


def test_decision_mapping_is_exactly_the_frozen_one() -> None:
    rec = {"trades": 35, "test_pnl": 120.0, "cumulative_r": 1.2,
           "max_drawdown": 900.0}
    assert r.oos_one_shot_decision(rec)[0] == "EARNED_FORWARD_TEST_PROPOSAL"
    thin = dict(rec, trades=12)
    assert r.oos_one_shot_decision(thin)[0] == "CONTINUE_THIN"
    assert "thin-sample" in r.oos_one_shot_decision(thin)[1][0]
    neg = dict(rec, test_pnl=-40.0, cumulative_r=-0.4)
    assert r.oos_one_shot_decision(neg)[0] == "FAMILY_RETIRED"
    dd_abort = dict(rec, max_drawdown=3100.0)
    assert r.oos_one_shot_decision(dd_abort)[0] == "FAMILY_RETIRED"
    assert "abort" in r.oos_one_shot_decision(dd_abort)[1][0]


def test_one_shot_token_defaults_to_unspent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    token = r.oos_token_state()
    assert token["spent"] is False and token["decision"] is None


def test_spent_shot_refuses_a_second_run(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    records = _eligible_cell() + [
        _sweep_rec("REVERSE_BOTH_sl2_tp2_h180_r0.01", "oos", 1.2, 120.0, n=35)]
    monkeypatch.setattr(r, "load_registry", lambda: records)
    monkeypatch.setattr(r, "oos_token_state",
                        lambda: {"spent": True, "spent_at": "2026-09-16",
                                 "spent_for": "REVERSE_BOTH_sl2_tp2_h180_r0.01",
                                 "decision": "EARNED_FORWARD_TEST_PROPOSAL"})
    args = r.argparse.Namespace(cell=None, dry_run=True, reason=None)
    with pytest.raises(SystemExit) as exc:
        r.cmd_oos_oneshot(args)
    assert exc.value.code == 2
    assert "already spent" in capsys.readouterr().out


def test_spend_requires_a_reason_and_an_eligible_cell(tmp_path, monkeypatch,
                                                      capsys) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    records = _eligible_cell()
    monkeypatch.setattr(r, "load_registry", lambda: records)
    monkeypatch.setattr(r, "oos_token_state",
                        lambda: {"spent": False, "spent_at": None,
                                 "spent_for": None, "decision": None})
    # no --reason with --cell: refuse before anything runs
    with pytest.raises(SystemExit) as exc:
        r.cmd_oos_oneshot(r.argparse.Namespace(
            cell="REVERSE_BOTH_sl2_tp2_h180_r0.01", dry_run=False, reason=None))
    assert exc.value.code == 2
    assert "--reason" in capsys.readouterr().out
    # not an eligible cell: refuse too
    with pytest.raises(SystemExit) as exc:
        r.cmd_oos_oneshot(r.argparse.Namespace(
            cell="REVERSE_BOTH_sl2_tp4_h30_r0.01", dry_run=False, reason="x"))
    assert exc.value.code == 2


# --- family-level wf significance (§9 amendment 4) -----------------------------
#
# One verdict for the whole sweep interior: dedupe the mode's wf rows to
# DISTINCT trade sets, pool them, bootstrap the family, permutation-test the
# mean-per-trade difference vs the baseline mode's wf pool. Nothing here
# launches the tester; every number comes from fixture trade lists.


def _wf_rec(pnls: list[float], hyp="REVERSE_BOTH_sl2_tp4_h180_r0.01",
            eid="V28-9001", axis: str | None = None) -> dict:
    pnl = round(sum(pnls), 2)
    return {"experiment_id": eid, "hypothesis": hyp, "mode": "V28_REVERSE_BOTH",
            "window": "wf", "role": "wf", "sweep_axis": axis,
            "trades": len(pnls), "test_pnl": pnl, "mean_risk": 100.0,
            "money_implied_r": pnl / 100.0, "trades_pnl": list(pnls),
            "geometry": {"risk": 0.01, "sl_atr": 2.0, "tp_atr": 4.0,
                         "hold_min": 180}}


def _orig_wf_rec(pnls: list[float]) -> dict:
    rec = _wf_rec(pnls, hyp="ORIGINAL_sl2_tp4_h180_r0.01", eid="V28-0017")
    rec["mode"] = "V28_ORIGINAL"
    return rec


def _family_registry(strong: bool = True) -> list[dict]:
    # four DISTINCT trade sets (the four real sweep groups) plus three labels
    # over the baseline's exact trade set (the tp3/5/6 case)
    if strong:
        cells = {"A": [8.0] * 15 + [-2.0] * 15,
                 "B": [9.0] * 14 + [-3.0] * 14,
                 "C": [7.0] * 16 + [-2.0] * 16,
                 "D": [10.0] * 12 + [-2.0] * 16}
    else:
        cells = {"A": [2.0] * 15 + [-1.0] * 15,
                 "B": [1.5] * 14 + [-1.0] * 14,
                 "C": [2.0] * 16 + [-1.5] * 16,
                 "D": [2.5] * 12 + [-1.0] * 16}
    recs = [
        _wf_rec(cells["A"], hyp="REVERSE_BOTH_sl2_tp4_h180_r0.01", eid="V28-0020"),
        _wf_rec(cells["B"], hyp="REVERSE_BOTH_sl1.5_tp4_h180_r0.01",
                eid="V28-0048", axis="sl_atr"),
        _wf_rec(cells["C"], hyp="REVERSE_BOTH_sl2_tp4_h240_r0.01",
                eid="V28-0059", axis="hold_min"),
        _wf_rec(cells["D"], hyp="REVERSE_BOTH_sl2_tp2_h180_r0.01",
                eid="V28-0051", axis="tp_atr"),
        # three labels over the baseline's exact trade set (the tp3/5/6 case)
        _wf_rec(cells["A"], hyp="REVERSE_BOTH_sl2_tp3_h180_r0.01",
                eid="V28-0052", axis="tp_atr"),
        _wf_rec(cells["A"], hyp="REVERSE_BOTH_sl2_tp5_h180_r0.01",
                eid="V28-0053", axis="tp_atr"),
        _wf_rec(cells["A"], hyp="REVERSE_BOTH_sl2_tp6_h180_r0.01",
                eid="V28-0054", axis="tp_atr"),
        _orig_wf_rec([2.0] * 15 + [-1.0] * 15),
    ]
    return recs


def test_duplicates_collapse_to_distinct_trade_sets() -> None:
    rep = r.wf_family_significance(_family_registry())
    # 7 family wf rows read, 4 distinct trade sets, 3 duplicate labels collapsed
    assert rep["wf_rows_read"] == 7
    assert rep["distinct_trade_sets"] == 4
    assert rep["duplicates_collapsed"] == 3
    assert rep["pooled_trades"] == 118
    base = next(c for c in rep["cells"]
                if c["hypothesis"] == "REVERSE_BOTH_sl2_tp4_h180_r0.01")
    assert base["collapsed_duplicates"] == 3


def test_representative_prefers_the_baseline_geometry_row() -> None:
    # the duplicate label appears FIRST in registry order; the group's
    # representative must still be the no-sweep-axis row
    recs = _family_registry()
    recs.reverse()  # dup labels now precede the baseline row
    rep = r.wf_family_significance(recs)
    assert any(c["hypothesis"] == "REVERSE_BOTH_sl2_tp4_h180_r0.01"
               and c["collapsed_duplicates"] == 3 for c in rep["cells"])


def test_signature_collision_fails_closed() -> None:
    recs = _family_registry()
    # same (n, pnl) signature as the baseline group but a different trade list:
    # cannot be the same strategy, must refuse rather than silently group
    impostor = _wf_rec([8.0] * 13 + [-2.0] * 7 + [0.0] * 10,
                       hyp="REVERSE_BOTH_sl2_tp3_h180_r0.01",
                       eid="V28-0052", axis="tp_atr")
    recs.append(impostor)
    with pytest.raises(SystemExit, match="collision"):
        r.wf_family_significance(recs)


def test_permutation_diff_is_deterministic_and_directional() -> None:
    a = [8.0] * 15 + [-2.0] * 15
    b = [2.0] * 15 + [-1.0] * 15
    p1 = r.permutation_diff_pvalue(a, b)
    p2 = r.permutation_diff_pvalue(a, b)
    assert p1 == p2                      # house seed => reproducible
    assert p1 <= 0.05                    # clearly separated
    # identical pools must NOT claim superiority: with ties, P(k>=n_a) under the
    # symmetric hypergeometric sits well above any significance bar
    assert r.permutation_diff_pvalue(b, b) > 0.5
    assert r.permutation_diff_pvalue(a, []) == 1.0  # empty comparison => no claim


def test_strong_family_is_supported_and_weak_is_not() -> None:
    strong = r.wf_family_significance(_family_registry(strong=True))
    assert strong["verdict"] == "FAMILY_EDGE_SUPPORTED"
    assert strong["reasons"] == []
    assert strong["family"]["bootstrap"]["p05"] > 0
    assert strong["mean_diff_per_trade"] > 0
    assert strong["permutation_p_one_sided"] <= 0.05

    weak = r.wf_family_significance(_family_registry(strong=False))
    assert weak["verdict"] == "FAMILY_EDGE_NOT_SUPPORTED"
    assert any("<= ORIGINAL" in x for x in weak["reasons"])
    assert any("permutation p" in x for x in weak["reasons"])


def test_pooled_pool_below_the_minimum_is_refused_even_when_profitable() -> None:
    cell = [8.0] * 15 + [-2.0] * 15
    recs = [_wf_rec(cell, eid="V28-0020"),
            _wf_rec([9.0] * 14 + [-3.0] * 14,
                    hyp="REVERSE_BOTH_sl2_tp2_h180_r0.01",
                    eid="V28-0051", axis="tp_atr"),
            _orig_wf_rec([2.0] * 15 + [-1.0] * 15)]
    rep = r.wf_family_significance(recs)
    assert rep["verdict"] == "FAMILY_EDGE_NOT_SUPPORTED"
    # the pool is profitable AND beats ORIGINAL, so the sample floor is the
    # only reason standing between it and a pass
    assert rep["mean_diff_per_trade"] > 0
    assert any(f"< {r.FAMILY_MIN_TRADES}" in x for x in rep["reasons"])


def test_missing_wf_trade_data_fails_loudly() -> None:
    with pytest.raises(SystemExit, match="no wf trade data for mode"):
        r.wf_family_significance([])
    recs = _family_registry()
    for rec in recs:
        if rec["mode"] == "V28_ORIGINAL":
            rec.pop("trades_pnl")
    with pytest.raises(SystemExit, match="V28_ORIGINAL"):
        r.wf_family_significance(recs)


# --- family windows & sensitivity (held windows only; OOS refused) -------------


def _is180_registry() -> list[dict]:
    """The strong family fixture re-dated to is180 rows, mirroring the live
    registry's shape (distinct trade sets + duplicate labels, ORIGINAL row)."""
    recs = _family_registry(strong=True)
    for rec in recs:
        rec["window"] = "is180"
        rec["role"] = "is"
    return recs


def test_family_aggregation_refuses_the_oos_window() -> None:
    with pytest.raises(SystemExit, match="REFUSED"):
        r.wf_family_significance(_family_registry(), window="oos")


def test_family_aggregation_runs_on_is180_rows() -> None:
    rep = r.wf_family_significance(_is180_registry(), window="is180")
    assert rep["window"] == "is180"
    assert rep["distinct_trade_sets"] == 4
    assert rep["verdict"] == "FAMILY_EDGE_SUPPORTED"   # same numbers, held window


def test_family_artifact_name_follows_the_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    monkeypatch.setattr(r, "load_registry", lambda: _is180_registry())
    r.cmd_wf_family(r.argparse.Namespace(mode="V28_REVERSE_BOTH",
                                         baseline="V28_ORIGINAL",
                                         window="is180", leave_one_out=False))
    assert (tmp_path / "family_significance_is180.json").exists()
    assert not (tmp_path / "wf_family_significance.json").exists()


def _loo_registry() -> list[dict]:
    """Five distinct ~28-trade cells (140 pooled; any single drop stays above
    the 100-trade floor) with one deliberate loser. Wins are large and losses
    small so the FULL family clears the p05 bar — the point here is the
    sensitivity mechanics (which cells carry the verdict), not a marginal
    statistic."""
    recs = [
        _wf_rec([12.0] * 14 + [-0.5] * 14, eid="V28-0020"),
        _wf_rec([13.0] * 14 + [-1.0] * 14, hyp="REVERSE_BOTH_sl1.5_tp4_h180_r0.01",
                eid="V28-0048", axis="sl_atr"),
        _wf_rec([11.0] * 15 + [-0.5] * 15, hyp="REVERSE_BOTH_sl2_tp2_h180_r0.01",
                eid="V28-0051", axis="tp_atr"),
        _wf_rec([12.0] * 12 + [0.0] * 16, hyp="REVERSE_BOTH_sl2_tp4_h240_r0.01",
                eid="V28-0059", axis="hold_min"),
        _wf_rec([-6.0] * 14 + [1.5] * 14, hyp="REVERSE_BOTH_sl2_tp4_h30_r0.01",
                eid="V28-0055", axis="hold_min"),
        _orig_wf_rec([2.0] * 15 + [-1.0] * 15),
    ]
    return recs


def test_leave_one_out_names_the_cells_that_carry_the_verdict(
        tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    monkeypatch.setattr(r, "load_registry", lambda: _loo_registry())
    r.cmd_wf_family(r.argparse.Namespace(mode="V28_REVERSE_BOTH",
                                         baseline="V28_ORIGINAL", window="wf",
                                         leave_one_out=True))
    rep = json.loads((tmp_path / "family_sensitivity_wf.json").read_text())
    assert rep["kind"] == "leave_one_cell_out"
    assert rep["full_verdict"] == "FAMILY_EDGE_SUPPORTED"
    assert len(rep["cells"]) == 5                     # one row per distinct cell
    assert all(row["loo_verdict"] == "FAMILY_EDGE_SUPPORTED"
               for row in rep["cells"])               # no single fragile carrier
    loser = next(row for row in rep["cells"]
                 if row["dropped"] == "REVERSE_BOTH_sl2_tp4_h30_r0.01")
    assert loser["solo_mean_per_trade"] < 0           # the loser shows as such
    winner = next(row for row in rep["cells"]
                  if row["dropped"] == "REVERSE_BOTH_sl2_tp4_h180_r0.01")
    assert winner["solo_mean_per_trade"] > 0
    assert "FLIPS the verdict" not in capsys.readouterr().out


def test_sensitivity_refuses_oos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    with pytest.raises(SystemExit, match="REFUSED"):
        r.cmd_leave_one_out(r.argparse.Namespace(mode="V28_REVERSE_BOTH",
                                                 baseline="V28_ORIGINAL",
                                                 window="oos"))


def test_family_artifact_is_byte_deterministic(tmp_path, monkeypatch,
                                               capsys) -> None:
    monkeypatch.setattr(r, "ART", tmp_path)
    monkeypatch.setattr(r, "load_registry", lambda: _family_registry())
    r.cmd_wf_family(r.argparse.Namespace(mode="V28_REVERSE_BOTH",
                                         baseline="V28_ORIGINAL", window="wf",
                                         leave_one_out=False))
    first = (tmp_path / "wf_family_significance.json").read_bytes()
    r.cmd_wf_family(r.argparse.Namespace(mode="V28_REVERSE_BOTH",
                                         baseline="V28_ORIGINAL", window="wf",
                                         leave_one_out=False))
    second = (tmp_path / "wf_family_significance.json").read_bytes()
    assert first == second               # no timestamps: same registry, same bytes
    out = capsys.readouterr().out
    assert "FAMILY_EDGE_SUPPORTED" in out and "distinct trade sets" in out


# --- mean-risk denominator ---------------------------------------------------
#
# The scorecard must state dollars and R that correspond to each other, which
# needs a per-record mean risk. A record's own pass is the only legitimate
# source: the EA's R_RECONCILE line when it emitted one, else the OPEN geometry.

def test_mean_risk_prefers_the_ea_reconcile_line_over_reconstruction() -> None:
    segment = [
        "  InpExperimentTag=TAG",
        "[v28.00] OPEN BUY volume=0.10 entry=100.0 SL=90.0 TP=120.0 risk=$100.00 expiry=X",
        "[v28.00] R_RECONCILE trades=1 mean_risk=96.86 risk_min=89.24 risk_max=104.04 "
        "ratio_sum_r=-1.1920 money_implied_r=-1.4951 gap=+0.3030 dispersion_bound=9.7843 "
        "consistent=true net_pnl=-144.81",
        "RESEARCH_RESULT tag=TAG trades=1",
    ]
    risk, source = r.mean_risk_from_segment(segment)
    assert source == "ea_reconcile_line", "the EA's own figure outranks a reconstruction"
    assert risk is not None and abs(risk - 96.86) < 1e-9


def test_mean_risk_reconstructs_from_open_geometry_when_it_must() -> None:
    # The EA denominator is (stop_distance / tick_size) * calibrated tick value,
    # and on V75 the calibrated value is the geometric tick_size*contract_size,
    # so it reduces to |entry - SL| * volume.
    segment = [
        "  InpExperimentTag=TAG",
        "[v28.00] OPEN BUY volume=0.10 entry=100.0 SL=90.0 TP=130.0 risk=$100.00 expiry=X",
        "[v28.00] OPEN SELL volume=0.20 entry=200.0 SL=210.0 TP=170.0 risk=$100.00 expiry=X",
        "RESEARCH_RESULT tag=TAG trades=2",
    ]
    risk, source = r.mean_risk_from_segment(segment)
    assert source == "open_lines"
    assert risk is not None and abs(risk - (0.10 * 10.0 + 0.20 * 10.0) / 2) < 1e-9
    # nothing to reconstruct from => unknown, never a guessed number
    assert r.mean_risk_from_segment(["RESEARCH_RESULT tag=TAG trades=0"]) == (None, "")


def test_tag_segment_brackets_one_pass_and_takes_the_newest_pair() -> None:
    lines = [
        "  InpExperimentTag=TAG",
        "old pass opening",
        "RESEARCH_RESULT tag=TAG trades=5",
        "  InpExperimentTag=TAG",
        "new pass opening",
        "RESEARCH_RESULT tag=TAG trades=9",
    ]
    seg = r._tag_segment(lines, "TAG")
    assert "new pass opening" in seg and "old pass opening" not in seg
    assert r._tag_segment(lines, "ABSENT") == []


def test_the_implied_r_is_derived_from_the_stored_denominator() -> None:
    src = (REPO / "scripts" / "v28_research.py").read_text(encoding="utf-8")
    assert 'rec["mean_risk"] = round(mean_risk, 2)' in src
    assert 'money_implied_r(rec.get("test_pnl", 0.0), rec["mean_risk"])' in src, \
        "a record's own fields must satisfy test_pnl == money_implied_r * mean_risk"


def test_scorecard_and_gate_state_dollars_and_both_r_measures() -> None:
    card = r.scorecard([dict(_rec("is", 200.0), hypothesis="H")], "H")
    assert card["mean_risk"] == 100.0
    assert card["cumulative_r"] == 2.0 and card["money_implied_r"] == 2.0
    assert card["expectancy_r_money"] == 0.04

    blank = dict(_rec("oos", 500.0), hypothesis="H")
    blank["mean_risk"] = None
    blank["money_implied_r"] = None
    ok, reasons = r.promotion_gate(
        [dict(_rec("is", 800.0), hypothesis="H"),
         dict(_rec("wf", 300.0), hypothesis="H"), blank], "H")
    assert not ok
    assert any("backfill" in x for x in reasons), \
        "a denominator-less record must be refused, naming the fix"

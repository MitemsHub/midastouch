"""Go-live artifact contract tests — the two-engine reality since v26.38/v2.23.

These tests pin the certified state of both engines and the LIVE/FINAL
presets. They are intentionally structural: they catch the failure classes
that already bit this project (stale version pins that pass silently, the
bar-open paper fill cadence, a fleet guard blind to virtual positions,
paper paths that could submit real orders, ledger-schema regressions).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_go_live_artifacts import verify


ROOT = Path(__file__).resolve().parents[1]
M_SOURCE = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI.mq5"
V_SOURCE = ROOT / "V75MacroEngine.mq5"


def m_source() -> str:
    return M_SOURCE.read_text(encoding="utf-8", errors="replace")


def v_source() -> str:
    return V_SOURCE.read_text(encoding="utf-8", errors="replace")


def on_tick_body(text: str, terminator: str) -> str:
    """The OnTick body from its header to a recognizable later anchor."""
    start = text.index("void OnTick()")
    end = text.find(terminator, start)
    return text[start:end]


# ---------------------------------------------------------------------------
# Repository artifact integrity (manifest-driven)
# ---------------------------------------------------------------------------

def test_go_live_repository_artifacts_pass() -> None:
    result = verify()
    assert result["ok"], result["problems"]
    assert result["deployed_byte_identical"] is None
    assert result["repo_live_sha256"] is not None
    assert len(result["repo_live_sha256"]) == 64


def test_deploy_manifest_pins_both_engines_at_expected_versions() -> None:
    result = verify()
    assert result["manifest_pins_ok"], result["problems"]
    assert result["version"] == "26.40"
    assert result["v75_version"] == "2.24"


def test_engine_version_macros_match_pinned_versions() -> None:
    # A bump without a deliberate manifest re-pin must fail the suite —
    # this is the test that was missing while the v27.00 pin went stale.
    assert '#define APP_VERSION "26.40"' in m_source()
    assert '#define ENGINE_VERSION "2.24"' in v_source()


def test_both_engines_stamp_the_frozen_era_boundary() -> None:
    # The ledger-era provenance rows must carry the reader's frozen boundary
    # epoch (scripts/era.py): a writer/reader disagreement stamps rows the
    # consumers would silently ignore.
    from scripts import era
    m_stamp = [l for l in m_source().splitlines() if 'PaperLog("ERA,"' in l]
    v_stamp = [l for l in v_source().splitlines() if 'PaperAppendLedger("ERA,"' in l]
    assert len(m_stamp) == 1 and len(v_stamp) == 1
    assert str(era.ERA_EPOCH) in m_stamp[0]
    assert str(era.ERA_EPOCH) in v_stamp[0]


# ---------------------------------------------------------------------------
# MitemshubAI (paper A/B arms) — v26.38 contract
# ---------------------------------------------------------------------------

def test_mitemshubai_is_multi_strategy_with_modules() -> None:
    text = m_source()
    assert "#include <Trade\\Trade.mqh>" in text
    assert '#include "Microstructure/TickRecorder.mqh"' in text
    assert "is a Crash/Boom symbol" in text  # volatility-only mandate enforced


def test_mitemshubai_hard_exits_fill_per_tick_before_bar_guard() -> None:
    # The v26.38 fill-model parity fix: hard SL/TP evaluated on EVERY tick,
    # BEFORE the bar guard. Regression here silently re-prices the paper
    # book at bar-open cadence (-8.3R/window on the certified corpus).
    text = m_source()
    on_tick = text.index("void OnTick()")
    parity = text.index("if(PaperActive() && g_pp_open) PaperCheckHardExits();", on_tick)
    guard = text.index("static datetime last_bar=0;", on_tick)
    assert on_tick < parity < guard


def test_mitemshubai_hard_exit_semantics_mirror_resting_orders() -> None:
    text = m_source()
    body = text[text.index("void PaperCheckHardExits()"):text.index("void PaperClose(")]
    # STOP checked before TP when one tick spans both (conservative).
    assert body.index("bid<=g_pp_sl") < body.index("bid>=g_pp_tp")
    assert body.index("ask>=g_pp_sl") < body.index("ask<=g_pp_tp")
    # Resting-order fills: at the LEVEL, with an explicit price.
    assert 'PaperClose("STOP",g_pp_sl)' in body
    assert 'PaperClose("TARGET",g_pp_tp)' in body


def test_mitemshubai_management_exits_stay_bar_granular() -> None:
    # PLOCK/ECUT/TIME/BE/trail are decisions, not resting orders — they must
    # NOT have been moved into the per-tick hard-exit monitor.
    hard = m_source()[m_source().index("void PaperCheckHardExits()"):m_source().index("void PaperClose(")]
    for decision in ("PLOCK", "ECUT", '"TIME"'):
        assert decision not in hard


def test_mitemshubai_paper_close_takes_explicit_fill_price() -> None:
    text = m_source()
    assert "void PaperClose(string reason, double exit_price=0)" in text
    # Default falls back to the touch price (legacy call sites unchanged).
    assert "double exit=(exit_price>0)?exit_price:((g_pp_dir>0)?bid:ask);" in text


def test_mitemshubai_paper_open_never_submits_orders() -> None:
    text = m_source()
    body = text[text.index("bool PaperOpen("):text.index("void PaperCheckHardExits()")]
    for order_call in ("trade.Buy", "trade.Sell", "OrderSend", "PositionOpen"):
        assert order_call not in body


def test_mitemshubai_fleet_guard_sees_the_virtual_position() -> None:
    # v26.37 fix: in paper mode the real-positions loop sums $0.00, so the
    # fleet account guard must add the instance's own virtual position.
    text = m_source()
    assert "double FleetOpenRisk(int &no_sl_count)" in text
    assert "g_pp_open && g_pp_orig_risk>0 && g_pp_vol>0" in text


def test_mitemshubai_tick_recorder_defaults_off() -> None:
    # Opt-in per preset (arm hosts only) — the artifact test stays include-free
    # of recorder behavior; the default must stay off.
    assert "input bool   InpTickRecordEnabled = false;" in m_source()


# ---------------------------------------------------------------------------
# V75MacroEngine (arm C) — v2.23 contract
# ---------------------------------------------------------------------------

def test_v75_engine_is_self_contained() -> None:
    text = v_source()
    assert '#include <Trade\\Trade.mqh>' in text
    assert '#include "' not in text  # native includes only


def test_v75_version_macro_and_banner_identity() -> None:
    text = v_source()
    assert '#define ENGINE_VERSION "2.24"' in text
    assert 'Print("V75 Macro Engine v" + ENGINE_VERSION + " initialized' in text
    # Informational only: #property version may legitimately lag the macro.
    assert '#property version     "2.22"' in text


def test_v75_entries_only_behind_the_m30_gate() -> None:
    text = v_source()
    gate = text[text.index("if(!IsNewM30Candle())"):]
    assert "ExecuteTrade(signal);" in gate
    assert "PaperOpenTrade(signal);" in gate
    on_tick = text[text.index("void OnTick()"):text.index("bool IsNewM30Candle()")]
    assert "ExecuteTrade(" not in on_tick.split("if(!IsNewM30Candle())")[0]
    assert "PaperOpenTrade(" not in on_tick.split("if(!IsNewM30Candle())")[0]


def test_v75_paper_exits_run_per_tick_before_the_gate() -> None:
    # Arm C filled per tick from day one — the property arms A/B had to be
    # fixed to. If this moves behind the gate, arm C regresses to bar-open
    # fills and the A/B comparison breaks on machinery again.
    text = v_source()
    body = on_tick_body(text, "bool IsNewM30Candle()")
    exits = body.index("PaperCheckExits();")
    timeout = body.index("PaperCheckTimeout();")
    gate = body.index("if(!IsNewM30Candle())")
    assert exits < gate and timeout < gate


def test_v75_paper_ledger_schema_is_arms_exact() -> None:
    # v2.22 fix, caught by the tester-mode ledger validation: OPEN rows must
    # be the arms' exact 12-field schema with real numbers (no extra ATR
    # column, no zeroed geometry).
    text = v_source()
    assert '"OPEN,%I64d,%I64d,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.2f,%d,%s"' in text
    assert '"CLOSE,%I64d,%I64d,%s,%.5f,%.3f,%.2f,%.2f"' in text
    assert '"EQ,%.2f"' in text


def test_v75_is_long_only_with_macro_standdown() -> None:
    text = v_source()
    assert "MACROTREND_ALIGNED_DOWN" in text
    assert "LONG-ONLY" in text


def test_v75_risk_geometry_and_guards() -> None:
    text = v_source()
    assert "#define SL_ATR_MULTIPLE   2.0" in text
    assert "#define TIMEOUT_SECONDS   (2 * 3600)" in text
    assert "input double InpRiskPercent        = 1.0;" in text
    assert "input double InpRRMultiplier       = 2.0;" in text
    assert "void SyncPositionState()" in text
    assert "void CheckTradeTimeout()" in text
    assert "trade.PositionClose(g_ticket" in text


def test_v75_live_entries_carry_broker_side_resting_sltp() -> None:
    # The code fact that justified the v26.38 paper fix: live orders go out
    # WITH their SL/TP attached, so the broker fills them intrabar.
    assert "trade.Buy(volume, g_symbol, entryPrice, slPrice, tpPrice" in v_source()


def test_v75_tick_value_calibration_uses_five_percent_geometry_tolerance() -> None:
    text = v_source()
    body = text[text.index("double CalibratedTickValue()"):text.index("void ValidateTickValue()")]
    assert "MathAbs(tickValue - expected) / expected > 0.05" in body
    assert "return expected;" in body  # identity wins when the broker lies


def test_v75_paper_mode_defaults_to_live_disabled() -> None:
    # The input defaults LIVE; the preset (not the source) opts into paper.
    assert "input bool   InpPaperMode          = false;" in v_source()


# ---------------------------------------------------------------------------
# Presets — intent, magic agreement, and allowed drift
# ---------------------------------------------------------------------------

def test_live_preset_submits_and_final_preset_does_not() -> None:
    result = verify()
    assert result["ok"], result["problems"]


def test_both_presets_share_the_go_live_magic() -> None:
    from scripts.verify_go_live_artifacts import read_set
    live = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set")
    final = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_FINAL.set")
    assert live["InpMagic"] == final["InpMagic"] == "7788075"
    assert live["InpLiveExecution"] == "true"
    assert final["InpLiveExecution"] == "false"


def test_live_preset_carries_the_certified_geometry() -> None:
    # 2026-09-16 rehearsal finding: the LIVE set was a 7-line stub, so a fresh
    # attach + Load booted InpTpMult at the 2.4 default instead of the
    # certified tp18 geometry the truth table and certified chain are built
    # on. The executed surface's pins are mandatory now.
    from scripts.verify_go_live_artifacts import read_set
    live = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set")
    assert live["InpTpMult"] == "1.8"                 # certified tp18 geometry
    assert live["InpRiskPerTrade"] == "0.005"
    assert live["InpMaxEffectiveRiskPct"] == "20.0"
    assert live["InpPaperEquity"] == "50.0"
    assert "7788075" in live["InpFleetMagicsCSV"]     # A
    assert "7788100" in live["InpFleetMagicsCSV"]     # B stays guarded


def test_live_and_final_mirror_the_certified_surface() -> None:
    # Both presets carry the complete executed surface (arm A's chart); the
    # only legitimate difference is the execution switch (+ the per-arm tick
    # recorder). A one-sided completion is intent drift by definition.
    from scripts.verify_go_live_artifacts import read_set
    live = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set")
    final = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_FINAL.set")
    keys = set(live) | set(final)
    assert len(keys) >= 70, "preset regression to a stub"
    differing = {k for k in keys if live.get(k) != final.get(k)}
    assert differing <= {"InpLiveExecution", "InpTickRecordEnabled"}, differing


def test_arm_d_forward_test_preset_is_paper_safe_and_frozen() -> None:
    # Arm D carries the gated candidate (docs/OOS_AUTOPSY_20260915.md) into
    # forward testing. It must stay paper-only, carry its own magic + arm tag
    # (file-collision-free beside arm B), keep the tick recorder off (arm B
    # owns the terminal's shared tick file), and hold the frozen geometry.
    from scripts.verify_go_live_artifacts import read_set, verify_arm_d_preset
    arm_d = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_D_FWD.set")
    assert arm_d["InpLiveExecution"] == "false"
    assert arm_d["InpMagic"] == "7788150"
    assert arm_d["InpArmTag"] == "D"
    assert arm_d["InpTickRecordEnabled"] == "false"
    assert arm_d["InpSelfCorrect"] == "false"  # no lab counterpart: off for parity
    # frozen gated candidate: BOTH gates on, MR/BF/BO off, sprint geometry
    assert arm_d["InpNoMomGate"] == "true"
    assert arm_d["InpHtfSlopeGate"] == "true"
    assert arm_d["InpUseMeanRevert"] == "false"
    assert arm_d["InpUseBandFade"] == "false"
    assert arm_d["InpUseBreakout"] == "false"
    assert arm_d["InpPullbackMin"] == "0.60" and arm_d["InpPullbackMax"] == "0.70"
    assert arm_d["InpTpMult"] == "1.6"
    assert arm_d["InpPbEmaSideVeto"] == "true"
    # drift from any pin fails the suite (protocol amendment required first)
    assert not verify_arm_d_preset(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_D_FWD.set")


def test_arm_a2_restart_preset_is_paper_safe_and_frozen() -> None:
    # Arm A2's pre-drafted preset is a BUILD CONTRACT (the forward EA does not
    # exist yet): it must stay paper-only, carry arm A's ORIGINAL slot 7788075
    # + tag A2 (arm B keeps 7788100; the retired arm-E magic 7788175 must
    # never appear anywhere), $1,000 virtual basis, tick recorder off, and
    # the frozen tp2.0 strategy surface.
    from scripts.verify_go_live_artifacts import (
        EXPECTED_ARM_A2_FLEET, read_set, verify_arm_a2_preset)
    arm_a2 = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_A2.set")
    assert arm_a2["InpLiveExecution"] == "false"
    assert arm_a2["InpMagic"] == "7788075"
    assert arm_a2["InpArmTag"] == "A2"
    assert arm_a2["InpPaperEquity"] == "1000.0"
    assert arm_a2["InpTickRecordEnabled"] == "false"
    # frozen tp2.0 candidate (ARM_A2_RESTART.md §2):
    assert arm_a2["InpStrategyMode"] == "3"
    assert arm_a2["InpStopATRMultiplier"] == "2.0"
    assert arm_a2["InpTargetATRMultiplier"] == "2.0"
    assert arm_a2["InpMaxHoldMinutes"] == "180"
    assert arm_a2["InpRiskFraction"] == "0.01"
    # fleet guard visibility: A2's slot is IN the CSV (already there as arm
    # A's), arm D's still there, retired arm-E magic ABSENT everywhere
    assert arm_a2["InpFleetMagicsCSV"] == EXPECTED_ARM_A2_FLEET
    assert "7788150" in arm_a2["InpFleetMagicsCSV"]
    assert "7788175" not in arm_a2["InpFleetMagicsCSV"]
    # .set values must be bare: no inline ';' comment can pollute a value
    # (the failure mode the verifier caught in the first draft of this file)
    for k, v in arm_a2.items():
        assert ";" not in v, f"{k}={v!r} carries an inline comment"
    # drift from any pin fails the suite (protocol amendment required first)
    assert not verify_arm_a2_preset(
        ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_A2.set")


def test_arm_a2_floor_mode_policy_is_pinned() -> None:
    """§2 amendment (2026-09-16): the strangulation-zone contract is a pinned
    constant set, not an EA default. If any value drifts, verification must
    fail loudly — the policy exists so the account can always trade."""
    from scripts.verify_go_live_artifacts import (
        ARM_A2, EXPECTED_ARM_A2_FLEET, read_set, verify_arm_a2_preset)
    arm_a2 = read_set(ARM_A2)
    # frozen floor-mode policy: hard −30% drawdown stop, conviction bar ON,
    # and the guard cap made explicit (was implicit before the amendment)
    assert arm_a2["InpMaxTotalRiskPct"] == "15.0"
    assert arm_a2["InpFloorModeMaxDDPct"] == "30.0"
    assert arm_a2["InpFloorModeConviction"] == "true"
    # materiality-conditioned conviction bar (§2 amendment 2, 2026-09-16):
    # A2's ~1.28% min-lot overage must NOT be throttled by the strong-trigger
    # bar (0/800 observed confluences); only a material overage pays it
    assert arm_a2["InpFloorModeConvictionMinRiskPct"] == "2.5"
    # full fail-closed pin check still passes with the new keys
    assert verify_arm_a2_preset(ARM_A2) == []


def test_floor_mode_engine_contract_in_source() -> None:
    """The policy lives in the forward build's source, ordered exactly as the
    contract states: identity evidence print -> hard drawdown stop -> raised
    entry bar -> account-budget guard -> take the minimum lot."""
    from scripts.verify_go_live_artifacts import ROOT
    src = (ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_v28_fwd.mq5").read_text(
        encoding="utf-8", errors="replace")
    # inputs exist (tester-visible, so any future tester run proves its policy)
    import re as _re
    for key in ("InpFloorModeMaxDDPct", "InpFloorModeConviction",
                "InpFloorModeConvictionMinRiskPct"):
        assert _re.search(rf"input\s+\w+\s+{key}\s*=", src), key
    # the paper path sets the trigger BEFORE sizing so the policy reads the
    # real signal name
    paper_path = src.find("PAPER PATH (v26.40)")
    set_trigger = src.find("g_entry_trigger = trigger;", paper_path)
    calc = src.find("CalculateVolume(entry, atr, volume, risk_money)", paper_path)
    assert 0 < set_trigger < calc
    # policy order inside the floor-mode branch
    floor_branch = src.find("FLOOR MODE: min lot risks $")
    halt = src.find("FloorModePolicyAllows(min_lot_risk)", floor_branch)
    budget = src.find("AccountBudgetAllows(min_lot_risk)", floor_branch)
    volume_take = src.find("volume = min_volume;", floor_branch)
    assert 0 < floor_branch < halt < budget < volume_take
    # halt fires on the hard floor vs WINDOW-START equity (g_paper_start),
    # not current equity — no drawdown laundering across restarts
    policy = src.find("bool FloorModePolicyAllows")
    body = src[policy:policy + 1600]
    assert "g_paper_start" in body and "PaperEquity()" in body
    # the conviction bar is materiality-conditioned: the gate reads
    # min_lot_risk/veq against InpFloorModeConvictionMinRiskPct BEFORE
    # IsStrongTrigger — below the bar the strong class is not demanded
    gate = src.find("InpFloorModeConviction &&")
    gate_body = src[gate:gate + 400]
    assert "InpFloorModeConvictionMinRiskPct" in gate_body
    assert gate_body.index("InpFloorModeConvictionMinRiskPct")
    assert gate_body.index("IsStrongTrigger")
    # and the stand-down print discloses the bar it enforces
    assert "bar) — standing down" in src
    # tester path untouched: the research contract still blocks without the
    # policy (parity safety)
    assert "Research contract, byte-faithful" in src
    assert src.find("if(!PaperActive())") < src.find("else if(min_lot_risk > risk_money")


def test_arm_a2_cross_artifact_consistency_parity_and_accrual() -> None:
    # The preset's strategy surface must equal the parity harness's pins
    # exactly (the parity run and the forward preset test the SAME candidate
    # or the precondition is meaningless), and the accrual registry must hold
    # arm A2 pre-start (start=None, tag-A2 ledger glob).
    import sys
    from scripts.verify_go_live_artifacts import (
        read_set, verify_arm_a2_consistency)
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_parity import INPUT_PINS as PARITY_PINS
    from armd_accrual import ARMS
    problems = verify_arm_a2_consistency()
    assert problems == [], problems
    arm_a2 = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_A2.set")
    for key, want in PARITY_PINS.items():
        assert arm_a2[key] == want or (
            abs(float(arm_a2[key]) - float(want)) < 1e-9), \
            f"preset {key}={arm_a2[key]!r} != parity pin {want!r}"
    assert ARMS["A2"]["start"] is None
    assert str(ARMS["A2"]["ledger_glob"]).endswith("_A2.csv")


def test_participation_gates_are_inputs_inert_by_default_and_post_decision() -> None:
    # v26.40 port of the OOS-autopsy gates: inputs exist, default OFF (exact
    # v26.39 behaviour), and the veto applies AFTER the score decision with
    # the band-fade plan disarmed on veto (no armed-retry straddle).
    text = m_source()
    assert "input bool   InpNoMomGate        = false;" in text
    assert "input bool   InpHtfSlopeGate     = false;" in text
    decision = text.index("int min_score_eff = EffectiveMinScore();")
    gates = text.index("v26.40: OOS-autopsy participation gates")
    assert decision < gates, "gates must be applied after the score decision"
    block = text[gates:text.index("if(final_dir!=0)", text.index('"gate-htf-slope"', gates))]
    assert "g_sig_is_band=false; g_sig_sl_atr=0; g_sig_tp_atr=0;" in block
    assert '"gate-no-mom"' in text and '"gate-htf-slope"' in text


def test_htf_slope_gate_uses_completed_h1_bars_and_fails_open() -> None:
    # The gate must never read the FORMING H1 bar (the lab's completed-bar
    # rule) and must fail OPEN when H1 data is unavailable (warmup/history
    # gap) — a data outage must not silently change the strategy's exposure.
    text = m_source()
    body = text[text.index("bool HtfSlopeRebuild()"):text.index("//| 5 CORE STRATEGIES")]
    assert "if(!HtfSlopeRebuild()) return true;" in body  # fail-open in HtfSlopeOK
    assert "iTime(_Symbol, PERIOD_H1, 0)" in body        # H1-bar-keyed rebuild
    assert "copied < HTF_SLOPE_SERIES) return false" in body


def test_preset_drift_is_confined_to_declared_keys() -> None:
    # Only the execution switch and the per-arm tick recorder may differ;
    # anything else drifting between LIVE and FINAL is intent drift.
    from scripts.verify_go_live_artifacts import read_set
    live = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set")
    final = read_set(ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_FINAL.set")
    allowed = {"InpLiveExecution", "InpTickRecordEnabled"}
    drifted = {k for k in set(live) & set(final) if live[k] != final[k]} - allowed
    assert not drifted, drifted

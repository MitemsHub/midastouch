"""The account-layer stance: the sizing and the governor, certified instead of pinned off.

WHY THIS FILE EXISTS. Every pass of record pins `InpPropGuard=false`, `InpRiskPercent=1.0` and
`InpArmTag=M1`, because the python engine of record is a BAR model of the STRATEGY and the
governor is an account-level layer it does not model — comparing the two with the gate on would
report a rule difference as an engine difference. The cost of that honesty, MEASURED 2026-09-22
on the arm's own first fill, was that NOTHING certified the configuration the arm actually runs:
the sizing the venue allowed ($39.01 of a $62.50 configured budget) existed only in a read-only
probe against the live terminal, and the governor existed only in the preset.

So `midas_parity --live-stance` runs a SECOND pass over the same window in the arm's own stance
and certifies the two things the BAR pass cannot. These tests pin the parts that can be pinned
without a tester: the input derivation (only the account layer moves, and it comes from the
preset), the sizing audit (against the python mirror), the governor model (including the
vacuous case, in words), and the ledger parse (the arm's real netting row).

Pure: no terminal, no tester, no network — the tester pass itself is the script's job.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import midas_parity as P  # noqa: E402
from midas_prop.execution.prop_execution import ContractSpec  # noqa: E402

#: The instrument as the venue measures it ($100 per unit per 1.0 lot — `order_calc_profit`,
#: 2026-09-21; the symbol's own spec field claims $10 and is wrong).
SPEC = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=100.0, digits=2,
                    usd_per_unit_per_lot=100.0, basis="order_calc_profit")

#: THE ARM'S ONE REAL FILL, from its own ledger: SHORT 0.01 lots at 4333.07, stopped 41.20143
#: away, closed 4328.76 for +0.104R. `risk_usd` is what the venue's lot step ALLOWED, and the
#: `cfg` token is what the preset ASKED FOR — the gap is the whole reason the token exists.
REAL_FILL = {"key": "18874164", "open_ct": 1790092800, "close_ct": 1790093197, "dir": -1,
             "entry": 4333.07, "exit": 4328.76, "lots": 0.01, "risk_usd": 41.20,
             "stop_d": 41.20143, "r": 0.104,
             "cfg": {"cfg_risk_usd": 62.50, "cfg_risk_pct": 0.25}}


def _declared() -> dict:
    return P.read_preset_inputs()


# --------------------------------------------------------------------------- #
# The stance: only the account layer moves, and it comes from the preset
# --------------------------------------------------------------------------- #


def test_the_live_stance_moves_only_the_account_layer() -> None:
    """A live-stance pass is the SAME strategy contract wearing the arm's account layer.

    If it moved anything else, its sizing verdict would be about a strategy nobody runs — and
    the strategy certificate would be describing a different window than the one it printed.
    """
    t0, t1 = 1790000000, 1790100000
    base = P.build_inputs("REVERSE_DIRECTION", t0, t1, offset_min=120)
    live = P.live_stance_inputs("REVERSE_DIRECTION", t0, t1, offset_min=120)
    moved = {k for k in set(base) | set(live) if base.get(k) != live.get(k)}
    # NOTHING OUTSIDE THE LAYER MAY MOVE. Two of its keys (`InpPaperEquity`, `InpPropAccountSize`)
    # happen to already hold the same value in the strategy contract — it is the same account
    # basis — so this asserts a SUPERSET relation, and the values themselves are pinned by
    # `test_the_account_layer_is_read_from_the_arm_s_own_preset` below.
    assert moved <= set(P.ACCOUNT_LAYER_INPUTS) | {"InpBarModel"}, (
        f"the live stance moved {sorted(moved - set(P.ACCOUNT_LAYER_INPUTS) - {'InpBarModel'})}, "
        f"which is outside the account layer {sorted(P.ACCOUNT_LAYER_INPUTS)}")
    assert {"InpRiskPercent", "InpPropGuard", "InpArmTag", "InpMagic", "InpDailyLossCapPct",
            "InpBarModel"} <= moved, "the stance this leg certifies must be the one that moved"
    # the session/window/threshold contract is byte-identical
    for k in ("InpMode", "InpBBDev", "InpSessionStartHour", "InpSessionEndHour",
              "InpFridayCutoffHour", "InpWindowStart", "InpWindowEnd", "InpUseNewsFilter",
              "InpNewsFile", "InpRiskPercent"):
        if k in P.ACCOUNT_LAYER_INPUTS:
            continue
        assert base[k] == live[k], f"{k} must not move in the live stance"
    # and the live path is the point: BAR replay off, execution on (in the tester those orders
    # hit the SIMULATED account, which is what makes the real sizing measurable)
    assert live["InpBarModel"] == "false" and live["InpLiveExecution"] == "true"


def test_the_account_layer_is_read_from_the_arm_s_own_preset() -> None:
    """One declaration, not a copy. The values are the preset's, not the harness's."""
    declared = _declared()
    live = P.live_stance_inputs("REVERSE_DIRECTION", 1790000000, 1790100000, offset_min=120)
    for k in P.ACCOUNT_LAYER_INPUTS:
        assert live[k] == declared[k], f"{k} must come from the preset the arm is launched with"
    assert declared["InpArmTag"] == "U25" and declared["InpMagic"] == "7825001"
    assert declared["InpPropGuard"] == "true"
    assert float(declared["InpRiskPercent"]) == 0.25


def test_an_unarmed_preset_refuses_the_live_stance(tmp_path: Path) -> None:
    """An armed preset declares InpLiveExecution=true — that is what arming IS.

    Without this guard a live-stance pass over a paper preset would certify the PAPER arm's
    sizing while printing a verdict about the arm. The harness would be measuring the wrong
    engine and saying nothing about it.
    """
    p = tmp_path / "paper.set"
    p.write_text("\n".join(f"{k}=0" for k in P.ACCOUNT_LAYER_INPUTS) + "\nInpLiveExecution=false\n",
                 encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        P.live_stance_inputs("REVERSE_DIRECTION", 0, 1, preset=p)
    assert "InpLiveExecution" in str(exc.value)


def test_a_preset_that_does_not_declare_the_layer_refuses(tmp_path: Path) -> None:
    """A missing key is a REFUSAL, never a default: a harness default would be a second
    declaration of the arm's risk, and the second declaration is the failure mode."""
    p = tmp_path / "partial.set"
    p.write_text("InpMagic=1\nInpArmTag=X\nInpRiskPercent=0.25\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        P.live_stance_inputs("REVERSE_DIRECTION", 0, 1, preset=p)
    assert "does not declare" in str(exc.value)


def test_a_missing_preset_refuses(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        P.read_preset_inputs(tmp_path / "nope.set")
    assert "no preset" in str(exc.value)


# --------------------------------------------------------------------------- #
# The sizing audit: the fill, against the mirror, at the equity it had
# --------------------------------------------------------------------------- #


def test_the_sizing_audit_reproduces_the_arm_s_own_fill() -> None:
    """The real fill, graded by the python mirror at the arm's own basis.

    $25,000 x 0.25% = a $62.50 budget; a 41.20143 stop at $100/unit/lot wants 0.0152 lots; the
    venue's 0.01 step floors that to 0.01, which risks $41.20 — QUANTISED DOWN, deliberately, by
    the venue's granularity. The audit grades the two numbers the rule fixes (`lots`, and the
    row's own `risk_usd`) and DISCLOSES the budget it could not spend.
    """
    a = P.stance_sizing_audit([REAL_FILL], preset=_declared(), spec=SPEC, deposit=25_000.0)
    assert a["verdict"] == "PASS", a["why"]
    row = a["rows"][0]
    assert row["lots_python"] == 0.01 and row["lots_ea"] == 0.01
    assert abs(row["risk_usd_python"] - 41.20) < 0.005
    assert row["budget_usd_python"] == 62.50
    assert row["budget_usd_ea"] == 62.50 and row["cfg_risk_pct_ea"] == 0.25
    assert row["floored_to_min_lot"] is True and row["agrees"] is True
    assert a["floored_to_min_lot"] == 1 and a["fills"] == 1
    # the equity path moves with the realized R x risk of the fills it has walked
    assert a["end_equity"] == pytest.approx(25_004.2848, abs=0.01)


def test_a_wrong_size_is_a_failure_and_it_says_which_fill() -> None:
    a = P.stance_sizing_audit([{**REAL_FILL, "lots": 0.02}], preset=_declared(), spec=SPEC,
                              deposit=25_000.0)
    assert a["verdict"] == "FAIL"
    assert "lots" in a["why"] and "18874164" in a["why"]


def test_a_risk_that_does_not_match_the_geometry_is_a_failure() -> None:
    """`risk_usd` is equity-independent (stop x lots x $/unit), so it catches a wrong basis that
    a floored lot size would otherwise hide behind."""
    a = P.stance_sizing_audit([{**REAL_FILL, "risk_usd": 12.00}], preset=_declared(), spec=SPEC,
                              deposit=25_000.0)
    assert a["verdict"] == "FAIL" and "risk" in a["why"]


def test_a_row_whose_configured_percent_is_not_the_preset_s_is_a_failure() -> None:
    a = P.stance_sizing_audit([{**REAL_FILL, "cfg": {"cfg_risk_usd": 62.50, "cfg_risk_pct": 1.0}}],
                              preset=_declared(), spec=SPEC, deposit=25_000.0)
    assert a["verdict"] == "FAIL" and "configured percent" in a["why"]


def test_no_fills_is_not_a_pass() -> None:
    a = P.stance_sizing_audit([], preset=_declared(), spec=SPEC, deposit=25_000.0)
    assert a["verdict"] == "NO-FILLS" and "no sizing to certify" in a["why"]


# --------------------------------------------------------------------------- #
# The governor: modelled on the pass's own equity path, and VACUOUS in words
# --------------------------------------------------------------------------- #


def test_the_governor_leg_is_vacuous_when_no_rule_binds() -> None:
    """The arm's one fill did not come near a 3% daily cap, and the verdict SAYS so.

    "The governor behaved" and "the governor was never asked" are different claims; only one of
    them is evidence, and a pass that blurred them would be naming a protection it had not
    exercised.
    """
    g = P.stance_governor_audit([REAL_FILL], preset=_declared(), deposit=25_000.0, offset_min=120)
    assert g["verdict"] == "VACUOUS"
    assert "never asked" in g["why"]
    assert g["blocks_modelled"] == 0 and g["coincident_entries"] == []
    assert g["days"][0]["headroom_pct"] == pytest.approx(3.0, abs=1e-6)
    # what the model covers, and what it does not, is on the record rather than inferred
    assert any("trailing shield" in r for r in g["not_modelled"])


def test_the_governor_leg_fails_when_a_cap_binds_before_an_entry() -> None:
    """20 stop-outs at $41.20 is a 3.3% day on a $25,000 account: the cap binds, the EA latches
    it for the rest of the UTC day, and an entry after that instant is a DISAGREEMENT."""
    losing = [{**REAL_FILL, "key": f"k{i}", "open_ct": 1790092800 + 600 * i,
               "close_ct": 1790092900 + 600 * i, "r": -1.0} for i in range(20)]
    losing.append({**REAL_FILL, "key": "late", "open_ct": 1790092800 + 600 * 20,
                   "close_ct": 1790092900 + 600 * 21, "r": 0.1})
    g = P.stance_governor_audit(losing, preset=_declared(), deposit=25_000.0, offset_min=120)
    assert g["verdict"] == "FAIL", g["why"]
    assert g["blocks_modelled"] == 1
    # BOTH later entries: the cap is reached on the 19th stop-out ($782.80 of a $750 cap) and the
    # breaker latches for the rest of the UTC day, so the 20th fill (k19) is refused too. A model
    # that flagged only the last one would be modelling a per-trade rule, not this one.
    assert {c["key"] for c in g["coincident_entries"]} == {"k19", "late"}, g["coincident_entries"]
    assert "daily loss cap" in g["why"]


def test_the_best_day_cap_is_the_eas_own_formula_not_a_fifth_of_the_account() -> None:
    """MEASURED 2026-09-22: this model read the best-day cap as `account x InpPropBestDayPct` =
    **$5,000/day**, while the EA's `PropDayProfitCapUsd()` is `size x InpPropTargetPct/100 x
    InpPropBestDayPct/100` = 5% x 20% = **$250/day** — twenty times smaller. Read as $5,000 the
    model needed a day twenty times bigger before the rule could be seen to bind, so its VACUOUS
    verdict would have been a false negative dressed as evidence. The research mirror
    (`scripts/gold_governed_wfo.py`) had the product right all along.

    A day gaining more than $250 must therefore TRIP it, and an entry after that instant is a
    disagreement — which the old number could never have produced.
    """
    declared = _declared()
    assert declared["InpPropTargetPct"] == "5.0" and declared["InpPropBestDayPct"] == "20.0"
    assert declared["InpPropAccountSize"] == "25000.0"
    winners = [{**REAL_FILL, "key": f"w{i}", "open_ct": 1790092800 + 600 * i,
                "close_ct": 1790092900 + 600 * i, "r": 1.0} for i in range(7)]
    after = {**REAL_FILL, "key": "after", "open_ct": 1790092800 + 600 * 7 + 300,
             "close_ct": 1790092900 + 600 * 8, "r": 0.1}
    g = P.stance_governor_audit(winners + [after], preset=declared, deposit=25_000.0, offset_min=120)
    row = g["days"][0]
    assert g["best_cap_usd"] == pytest.approx(250.0, abs=0.01), g["best_cap_basis"]
    assert row["best_cap_usd"] == pytest.approx(250.0, abs=0.01)
    # 7 x +1R at $41.20 = +$288.40, past the $250 cap on the 7th close
    assert row["best_cap_hit_at"] is not None
    assert g["verdict"] == "FAIL" and "best-day cap" in g["why"]
    assert "after" in {c["key"] for c in g["coincident_entries"]}
    # and the basis is stated, so a reader never has to infer which rule produced the number
    assert "PropDayProfitCapUsd" in g["best_cap_basis"] and "250" in g["best_cap_basis"]


def test_the_mirror_and_the_ea_state_the_same_best_day_rule() -> None:
    """The python and the MQL5 are one contract: if the EA's formula moves, this fails rather than
    letting the stance certify a rule the chart no longer implements."""
    ea = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(encoding="utf-8",
                                                                        errors="replace")
    body = ea.split("double PropDayProfitCapUsd()", 1)[1].split("}", 1)[0]
    assert "InpPropTargetPct" in body and "InpPropBestDayPct" in body, body
    assert "PropGovernorSize()" in body, "the rule is a share of the SIZED account, not a constant"
    declared = _declared()
    expected = (float(declared["InpPropAccountSize"]) * float(declared["InpPropTargetPct"]) / 100.0
                * float(declared["InpPropBestDayPct"]) / 100.0)
    g = P.stance_governor_audit([REAL_FILL], preset=declared, deposit=25_000.0, offset_min=120)
    assert g["best_cap_usd"] == pytest.approx(expected, abs=0.01)
    assert "best-day" in " ".join(g["modelled_rules"])


def test_a_best_day_share_with_no_target_is_refused_not_guessed() -> None:
    """The cap is a SHARE OF THE TARGET: with no target it cannot be computed, and a guess here is
    a risk number invented by the harness."""
    declared = {**_declared(), "InpPropTargetPct": "0"}
    g = P.stance_governor_audit([REAL_FILL], preset=declared, deposit=25_000.0, offset_min=120)
    assert g["best_cap_usd"] == 0.0
    assert not any(r.startswith("best-day") for r in g["modelled_rules"])
    assert any("cannot be computed" in r for r in g["not_modelled"])


def test_a_governor_with_no_rule_is_not_armed() -> None:
    """A preset with the gate on and no caps declares nothing to exercise."""
    declared = {**_declared(), "InpDailyLossCapPct": "0", "InpPropBestDayPct": "0"}
    g = P.stance_governor_audit([REAL_FILL], preset=declared, deposit=25_000.0, offset_min=120)
    assert g["verdict"] == "NOT-ARMED" and "no rule to exercise" in g["why"]


# --------------------------------------------------------------------------- #
# The parse: the arm's own netting row, and the fail-closed directions
# --------------------------------------------------------------------------- #

#: The arm's ledger as written, unedited (account 1428765, magic 7825001, server 16:00 = 14:00Z).
REAL_ROWS = (
    "ERA,MIDAS1.25,1790091000,pertick-fills+cfg-risk\n"
    "EQ,25000.00\n"
    "LOPEN,1790092800,0,18874164,0,-1,4333.07000,4374.38000,4250.77000,0.01,41.20,41.20143,"
    "43200,U25,1790091900,13,1.39453,out,120,cfg=62.50@0.25\n"
    "LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104\n"
)


def _ledger(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_parse_joins_the_netting_fill_by_the_one_identity_rule(tmp_path: Path) -> None:
    """posid is 0 at write time and the ORDER ticket is the position id (netting) — the same
    rule the four ledger readers were fixed to use, so one fill comes back, not zero."""
    fills, problems = P.parse_stance_fills(_ledger(tmp_path, REAL_ROWS))
    assert problems == [], problems
    assert len(fills) == 1
    f = fills[0]
    assert f["key"] == "18874164" and f["dir"] == -1 and f["r"] == 0.104
    assert f["lots"] == 0.01 and f["stop_d"] == 41.20143
    assert f["cfg"] == {"cfg_risk_usd": 62.50, "cfg_risk_pct": 0.25}


def test_an_open_live_fill_is_a_problem_not_a_silent_drop(tmp_path: Path) -> None:
    """A dangling LOPEN is a real-money position: it cannot be graded by a closed-trade audit,
    and dropping it quietly would certify fewer trades than the arm took."""
    rows = REAL_ROWS.replace("LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104\n", "")
    fills, problems = P.parse_stance_fills(_ledger(tmp_path, rows))
    assert fills == [] and any("still OPEN" in p for p in problems)


def test_a_close_with_no_open_is_a_problem(tmp_path: Path) -> None:
    rows = ("LOPEN,1790092800,18874164,0,0,-1,4333.07000,4374.38000,4250.77000,0.01,41.20,"
            "41.20143,43200,U25\n"
            "LCLOSE,1790093197,99999,EXTERNAL,4328.76000,0.104\n")
    fills, problems = P.parse_stance_fills(_ledger(tmp_path, rows))
    assert fills == [] and any("closes no LOPEN" in p for p in problems)


# --------------------------------------------------------------------------- #
# The governor EXERCISED (--governor-stress): a threshold derived to bind,
# read off the ungoverned path and verified against the governed one
# --------------------------------------------------------------------------- #

#: A day on the arm's own basis: a small win, a 0.3% loss (a 41.20 stop is 0.16% of $25,000, so
#: this is two min-lot stop-outs), then one more entry that only exists if nothing refused it.
STRESS_DAY = [
    {"key": "a", "open_ct": 1790092800, "close_ct": 1790096400, "dir": 1, "r": 0.10,
     "risk_usd": 41.20},
    {"key": "b", "open_ct": 1790097000, "close_ct": 1790100600, "dir": -1, "r": -1.40,
     "risk_usd": 41.20},
    {"key": "c", "open_ct": 1790101200, "close_ct": 1790104800, "dir": -1, "r": 0.50,
     "risk_usd": 41.20},
]

def test_the_prediction_is_read_off_the_ungoverned_path(tmp_path: Path) -> None:
    """THE SEPARATION, which is what makes this a test rather than a tautology.

    The mirror is handed the fills of a pass run with the governor OFF, so its equity path is the
    strategy's own. If it were handed the GOVERNED pass's fills, `must_be_present` would be empty
    by construction — the refused entries would simply not be there — and an over-refusal could
    never be detected. Asserting that `must_be_present` is NOT empty is therefore asserting that
    the audit can still see the entries it is checking survived.
    """
    pred = P.governor_prediction(STRESS_DAY, cap_pct=0.2, deposit=25_000.0, offset_min=0)
    assert pred["breach"] is not None
    # the day's LOW is +0.10R then -1.40R at $41.20/R: +$4.12 then -$57.68, so the drawdown from
    # the day's anchor is $53.56 = 0.2142% of $25,000. The win is why the number is not 1.4R.
    assert pred["breach"]["loss_pct"] == pytest.approx(0.2142, abs=0.001)
    assert [r["open_ct"] for r in pred["must_be_absent"]] == [1790101200]
    assert [r["open_ct"] for r in pred["must_be_present"]] == [1790092800, 1790097000]
    assert pred["must_be_present"], "entries before the breach must remain graded"
    # the breach is on the path's own day, and it names the instant the EA latches at
    assert pred["breach"]["day"] == "2026-09-22"
    assert pred["breach"]["from_utc"].startswith("2026-09-22")


def test_the_boundary_entry_is_named_not_scored() -> None:
    """An entry tapped on the breaching bar itself may be taken just before the tick that latches
    the breaker or just after, and neither ordering is a disagreement to report as one."""
    with_boundary = STRESS_DAY + [{"key": "x", "open_ct": 1790100600, "close_ct": 1790101800,
                                   "dir": 1, "r": 0.0, "risk_usd": 41.20}]
    pred = P.governor_prediction(with_boundary, cap_pct=0.2, deposit=25_000.0, offset_min=0)
    assert [r["open_ct"] for r in pred["boundary"]] == [1790100600]
    assert 1790100600 not in [r["open_ct"] for r in pred["must_be_absent"]]
    assert 1790100600 not in [r["open_ct"] for r in pred["must_be_present"]]


def test_a_cap_above_every_day_predicts_nothing() -> None:
    """The `inf` probe is how the stress DERIVES its threshold, and on a path no cap can reach it
    must return the day measurements with no breach — never a guess."""
    probe = P.governor_prediction(STRESS_DAY, cap_pct=float("inf"), deposit=25_000.0,
                                  offset_min=0)
    assert probe["breach"] is None and probe["must_be_absent"] == []
    assert probe["largest_day_loss_pct"] == pytest.approx(0.2142, abs=0.001)
    assert len(probe["days"]) == 1 and probe["days"][0]["day"] == "2026-09-22"


@pytest.mark.parametrize("governed,verdict,clause", [
    ([1790092800, 1790097000], "GOVERNED-PASS", "none of them"),
    ([1790092800, 1790097000, 1790101200], "GOVERNED-FAIL", "TOOK anyway"),
    ([1790092800], "GOVERNED-FAIL", "does NOT hold"),
    ([1790092800, 1790097000, 1790109999], "GOVERNED-FAIL", "never on the ungoverned path"),
])
def test_the_stress_verdict_names_the_disagreement(governed: list[int], verdict: str,
                                                   clause: str) -> None:
    """Four directions, each naming its own failure: the entry the mirror refused and the EA
    took, the entry the mirror kept and the EA lost (an OVER-refusal), and the entry that appears
    in the governed pass and was never on the ungoverned one — which a governor that can only
    refuse can never produce, and which is therefore the quietest of the three."""
    pred = P.governor_prediction(STRESS_DAY, cap_pct=0.2, deposit=25_000.0, offset_min=0)
    ungoverned = [r["open_ct"] for r in pred["must_be_absent"] + pred["must_be_present"]]
    got, why, counts = P.governor_stress_compare(pred, ungoverned, governed, cap=0.2, dd=0.297)
    assert got == verdict, why
    assert clause in why
    assert counts["unexpected_entries"] == (1 if verdict == "GOVERNED-FAIL"
                                            and clause.startswith("never") else 0)


def test_a_refusal_that_never_happened_cannot_be_a_pass() -> None:
    """A stress run where the governor refused nothing at all is not a certificate: `refused_ok`
    empty means the prediction was never exercised, and the verdict says FAIL rather than
    quietly counting zero agreements as agreement."""
    pred = P.governor_prediction(STRESS_DAY, cap_pct=0.2, deposit=25_000.0, offset_min=0)
    ungoverned = [r["open_ct"] for r in pred["must_be_absent"] + pred["must_be_present"]]
    got, why, _ = P.governor_stress_compare(pred, ungoverned, ungoverned, cap=0.2, dd=0.297)
    assert got == "GOVERNED-FAIL" and "TOOK anyway" in why


#: A day where the LARGEST drawdown belongs to the LAST fill — MEASURED 2026-09-22 as the actual
#: shape of the arm's own window, where half of 0.318% (0.15%) breached on a close with nothing
#: after it and the whole leg came back NO-BIND. The derivation must pick an earlier close.
LAST_FILL_DAY = [
    {"key": "a", "open_ct": 1000, "close_ct": 2000, "dir": 1, "r": -1.0, "risk_usd": 41.20},
    {"key": "b", "open_ct": 3000, "close_ct": 4000, "dir": 1, "r": 1.0, "risk_usd": 41.20},
    {"key": "c", "open_ct": 5000, "close_ct": 6000, "dir": -1, "r": -2.0, "risk_usd": 41.20},
    {"key": "d", "open_ct": 7000, "close_ct": 8000, "dir": -1, "r": -1.0, "risk_usd": 41.20},
]


def test_the_derivation_picks_a_threshold_with_an_entry_left_to_refuse() -> None:
    """The threshold is derived from where an ENTRY still exists after the breach, not from the
    largest drawdown — those are different closes, and the difference is the whole leg.

    The last fill carries the day's largest drawdown (0.4944%) and nothing follows it on that day,
    so a cap derived from it can only ever come back NO-BIND (that is exactly what happened on the
    arm's own window at 0.15%). The derivation therefore takes the largest drawdown that still has
    an entry after it: 0.3296% after the third fill, from which the fourth fill must be refused.
    The unusable close is NAMED rather than silently dropped.
    """
    d = P.derive_binding_threshold(LAST_FILL_DAY, deposit=25_000.0, offset_min=0)
    assert d["cap_pct"] == 0.32
    assert d["chosen"]["day"] == "1970-01-01" and d["chosen"]["entries_after"] == 1
    assert [s["drawdown_pct"] for s in d["skipped"]] == [0.4944]
    assert "refuse nothing" in d["skipped"][0]["why"]
    pred = P.governor_prediction(LAST_FILL_DAY, cap_pct=d["cap_pct"], deposit=25_000.0,
                                 offset_min=0)
    assert [r["open_ct"] for r in pred["must_be_absent"]] == [7000]
    assert [r["open_ct"] for r in pred["must_be_present"]] == [1000, 3000, 5000]


def test_a_path_with_nothing_to_refuse_derives_no_cap() -> None:
    """A day whose only loss is its last fill cannot be asked the question, and the derivation says
    so instead of inventing a threshold that binds nothing."""
    # -2.0R, not -1.0R: a single min-lot loss is offset by the win before it and the day never
    # goes below its own anchor, which is a different reason for the same NO-BIND
    win_then_last_loss = [{**LAST_FILL_DAY[1], "r": 1.0}, {**LAST_FILL_DAY[2], "r": -2.0}]
    d = P.derive_binding_threshold(win_then_last_loss, deposit=25_000.0, offset_min=0)
    assert d["cap_pct"] is None
    assert "no cap can be derived" in d["why"]
    assert d["skipped"] and "refuse nothing" in d["skipped"][0]["why"]


def test_a_stale_ledger_is_never_graded(tmp_path: Path, monkeypatch) -> None:
    """ONE FILE PER ARM TAG. A pass that writes nothing leaves the previous pass's ledger in place,
    and a newest-by-mtime lookup would then grade a pass against itself and call it a certificate.
    """
    p = _ledger(tmp_path, REAL_ROWS)
    monkeypatch.setattr(P, "stance_ledger_candidates", lambda tag: [p])
    fresh = P.stance_ledger_snapshot("U25")
    assert "stale" not in fresh and fresh["bytes"] == p.stat().st_size
    stale = P.stance_ledger_snapshot("U25", not_before=p.stat().st_mtime + 60)
    assert stale["stale"] and "belong to an earlier pass" in stale["stale"]
    # and the grace window is real: a ledger written a couple of seconds BEFORE the pass is
    # reported began is still this pass's (the agent flushes as the run ends)
    assert "stale" not in P.stance_ledger_snapshot("U25", not_before=p.stat().st_mtime - 5)


def test_the_stress_reads_its_prediction_off_the_ungoverned_pass() -> None:
    """Pinned at the call site, because the whole validity of the leg is this one argument."""
    import inspect
    src = inspect.getsource(P.run_governor_stress)
    assert "governor_prediction(u_fills" in src, "the prediction must come from pass LSU"
    assert "u_inputs[\"InpPropGuard\"] = \"false\"" in src
    assert "g_inputs[\"InpDailyLossCapPct\"]" in src
    # and the shipping cap is REPORTED beside the stress one, never substituted for it
    assert "shipping_cap_pct" in src and "this_is_a_stress_threshold_not_the_shipping_one" in src


def test_the_stress_says_out_loud_that_it_is_not_the_shipping_threshold() -> None:
    """A GOVERNED-PASS quoted without this sentence would read as a statement about the 3% cap.
    The constant is what the artifact carries, so the words have to be in it."""
    why = P.GOVERNOR_STRESS_WHY
    assert "VACUOUS" in why and "MUST bind" in why
    assert "not the 3% number" in why or "not the shipping" in why
    assert "UNGOVERNED" in why or "ungoverned" in why
    assert any("trailing shield" in r for r in P.GOVERNOR_NOT_MODELLED)


def test_the_stress_refuses_without_a_shipping_stance() -> None:
    """The stress is measured AGAINST the shipping stance; a run that never took one has nothing
    to compare the governed pass to, and must refuse before it stops anybody's terminal."""
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "midas_parity.py"),
                        "--governor-stress", "--window", "tickcov"],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(REPO), encoding="utf-8", errors="replace")
    assert r.returncode != 0
    assert "needs --live-stance" in (r.stdout + r.stderr)
    assert "terminal" not in r.stdout.lower(), "it must refuse BEFORE touching the terminal"


def test_the_breaker_stress_refuses_without_a_shipping_stance() -> None:
    """Same gate, second leg: the construction is the arm's own account layer with one input
    moved, so there has to be a measured stance to move it from — and the refusal must cost the
    arm nothing (nothing is stopped before it)."""
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "midas_parity.py"),
                        "--breaker-stress", "--window", "tickcov"],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(REPO), encoding="utf-8", errors="replace")
    assert r.returncode != 0
    assert "needs --live-stance" in (r.stdout + r.stderr)
    assert "terminal" not in r.stdout.lower()


# --------------------------------------------------------------------------- #
# The derived-risk leg: the SHIPPING 3% cap, made reachable by the risk per trade
# --------------------------------------------------------------------------- #
#
# WHY THIS LEG EXISTS AT ALL, measured 2026-09-22 on the tick-covered window off the venue's own
# bars: the path makes 9 fills, no UTC day holds more than 3, and the largest day drawdown at a
# close still followed by an entry is -1.007R. At the arm's own realised risk per trade that is
# ~0.16% of the day's opening equity, so a 3% day would take ~19 consecutive full stops inside one
# day. The window cannot be widened either — this program certifies only on the venue's real ticks
# (2026-09-04 onward) — so the one honest lever left is the lever the rule is denominated in.

def _walk(fills, *, deposit: float = 25_000.0, m15=None):
    return P.breaker_walk(fills, deposit=deposit, offset_min=0, m15=m15)


def test_the_breaker_derivation_needs_an_entry_after_the_breach() -> None:
    """The risk per trade is derived from the day's RUNNING LOW at a close that still has an entry
    after it — the same discipline the derived-cap leg uses, in the quantity that decides it.

    On LAST_FILL_DAY the running low reaches -3.0R on the day's LAST fill, which can refuse
    nothing; the largest usable low is the -2.0R close that the fourth fill still follows, and the
    unusable close is NAMED rather than dropped.

    AND THE SIGN CONVENTION IS THE TRAP: the walk's units are POSITIVE when the day is down, so
    the largest drawdown is the `max` — a `min` would derive the threshold from the day the
    governor is EASIEST on, i.e. a plausible-looking number from the wrong close. The values
    asserted here are positive for exactly that reason.
    """
    d = P.derive_binding_risk(_walk(LAST_FILL_DAY), cap_pct=3.0)
    # the day's -3.0R low is reached on the LAST fill (skipped); the largest USABLE low is -2.0R
    assert d["chosen_drawdown_r"] == 2.0 and d["chosen"]["entries_after"] == 1
    assert d["risk_pct"] == 1.8, d["why"]          # 3/2 carried by the declared 1.2 margin
    assert [s["drawdown_r"] for s in d["skipped"]] == [3.0]
    assert "refuses nothing" in d["skipped"][0]["why"]
    # and the derivation is a REFUSAL-READY one: the mirror predicts the entry it must refuse
    cap = P.governor_prediction(LAST_FILL_DAY, cap_pct=3.0, deposit=25_000.0, offset_min=0)
    assert cap["breach"] is None, "at the shipping risk nothing binds — that is the whole problem"


def test_the_margin_carries_the_breach_over_the_venue_s_lot_step() -> None:
    """THE MARGIN IS NOT DECORATION. The lot step quantises the risk per trade DOWN by up to one
    step's dollar risk (~$41 at this window's ATRs, ~5% of a nominal $820), so a derived threshold
    with no margin can land at 2.99% and bind nothing — the pass would come back NO-BIND and look
    like a market fact. The derived risk must therefore make the NOMINAL day loss exceed the cap,
    not merely equal it, while the exact requirement is still reported beside it.
    """
    d = P.derive_binding_risk(_walk(LAST_FILL_DAY), cap_pct=3.0)
    nominal_day_loss = d["risk_pct"] * d["chosen_drawdown_r"]
    exact = d["needed_risk_pct_before_margin"]
    assert nominal_day_loss > 3.0, "with no headroom the venue's step can put it back under"
    assert exact * d["chosen_drawdown_r"] == pytest.approx(3.0), (
        "the un-margined requirement is exactly the cap at the chosen close")
    assert d["risk_pct"] >= exact, "and the margin may only ever carry it UP"
    # rounding UP to 2dp is part of the guarantee, so the value is never 0.999 of what is needed
    assert abs(d["risk_pct"] * 100 - round(d["risk_pct"] * 100)) < 1e-9


def test_a_risk_beyond_the_ceiling_is_refused_not_run() -> None:
    """A window that would need, say, 30%/trade to reach a 3% day is not a stress of this
    strategy — at that risk the pass is a different arm, and the leg refuses instead of running
    it and printing a verdict about the wrong thing."""
    tiny = [{"key": "a", "open_ct": 1000, "close_ct": 2000, "dir": 1, "r": -0.1,
             "risk_usd": 41.20},
            {"key": "b", "open_ct": 3000, "close_ct": 4000, "dir": 1, "r": -0.1,
             "risk_usd": 41.20}]
    d = P.derive_binding_risk(_walk(tiny), cap_pct=3.0, max_risk_pct=10.0)
    assert d["risk_pct"] is None
    assert "above the 10% ceiling" in d["why"]


def test_a_path_with_nothing_after_the_breach_derives_no_risk() -> None:
    """The other NO-BIND direction: if every day's loss lands on its last fill, no risk per trade
    can be derived that binds with something left to refuse, and the leg says that instead of
    raising the risk until something happens."""
    d = P.derive_binding_risk(_walk([{"key": "a", "open_ct": 1000, "close_ct": 2000, "dir": 1,
                                      "r": -1.0, "risk_usd": 41.20}]), cap_pct=3.0)
    assert d["risk_pct"] is None and "refuses nothing" in d["skipped"][0]["why"]


def test_the_day_anchor_includes_the_floating_of_a_position_carried_over_the_roll() -> None:
    """THE EA'S ANCHOR IS NOT THE MIRROR'S, and the difference is not a detail.

    `PropDayAnchorCheck()` takes the equity on the first tick of the new UTC day, so a position
    carried across midnight contributes its floating P&L to the day's opening equity. A walk over
    closed trades anchors on the previous CLOSE, so the same day's loss comes out smaller or larger
    depending on which side of the boundary that position was on. MEASURED 2026-09-22 on this
    window: on 2026-09-11 the live path carries a short across the roll that was +$135 in profit at
    the boundary, which makes the day's loss 0.783R where the closed basis said 0.632R — and that
    24% is the difference between a derived risk that binds and one that comes back NO-BIND.
    """
    # the first fill is open across midnight (00:00 on 1970-01-02) and the second is the entry the
    # cap would refuse once the day's loss from the anchor reaches it
    carried = [{"key": "a", "open_ct": 1000, "close_ct": 90_000, "dir": -1, "entry": 100.0,
                "stop_d": 10.0, "risk_usd": 100.0, "r": -0.5},
               {"key": "b", "open_ct": 91_000, "close_ct": 92_000, "dir": -1, "entry": 100.0,
                "stop_d": 10.0, "risk_usd": 100.0, "r": -0.1}]
    # the bar CONTAINING the boundary (00:00 on 1970-01-02) prices the floating at the roll —
    # at its ADVERSE EXTREME, which for a short is the HIGH (the least favourable mark)
    bars = [{"time": 86_400, "open": 99.0, "high": 100.5, "low": 98.0, "close": 99.0}]
    no_anchor = P.breaker_walk(carried, deposit=25_000.0, offset_min=0)
    from_bar = P.breaker_walk(carried, deposit=25_000.0, offset_min=0, m15=bars)
    assert no_anchor["m15_used"] is False and from_bar["m15_used"] is True
    assert no_anchor["days"][0]["boundary_float_usd"] == 0.0
    # SHORT at 100.00 marked at the bar's HIGH 100.50: -0.50 per unit x (100/10 = 10 per unit)
    assert from_bar["days"][0]["boundary_float_usd"] == -5.0
    assert from_bar["carried_over_the_roll"][0]["float_units"] == pytest.approx(-0.05)
    # and the adverse extreme is the CONSERVATIVE direction: a smaller anchor means a SMALLER
    # measured day loss, so a breach predicted from it is one the pass has to make
    assert from_bar["days"][0]["low_units"] < no_anchor["days"][0]["low_units"]
    # the day's loss FROM THE ANCHOR is therefore larger by exactly that floating
    closed_low = no_anchor["days"][0]["low_units"]
    anchor_low = from_bar["days"][0]["low_units"]
    assert anchor_low == pytest.approx(closed_low - 0.05)
    assert P.derive_binding_risk(from_bar, cap_pct=3.0)["risk_pct"] > \
        P.derive_binding_risk(no_anchor, cap_pct=3.0)["risk_pct"], (
            "a SMALLER measured day loss needs a BIGGER risk per trade to reach the cap")


def test_every_breaching_day_contributes_its_refusals_not_just_the_first() -> None:
    """The cap is a PER-DAY rule and the breaker resets at every UTC roll, so several days can bind
    on one path — and the first of them may refuse nothing at all. MEASURED 2026-09-22: reporting
    only the first breach turned a window that could answer the question into a NO-BIND, because
    the first breach on the live path landed on a day's last fill.
    """
    fills = [{"key": "a", "open_ct": 1000, "close_ct": 2000, "dir": 1, "r": -0.2,
              "risk_usd": 100.0},
             {"key": "b", "open_ct": 3000, "close_ct": 4000, "dir": 1, "r": -1.0,
              "risk_usd": 100.0},
             {"key": "c", "open_ct": 86_400 + 1000, "close_ct": 86_400 + 2000, "dir": 1, "r": -1.0,
              "risk_usd": 100.0},
             {"key": "d", "open_ct": 86_400 + 3000, "close_ct": 86_400 + 4000, "dir": 1, "r": -0.2,
              "risk_usd": 100.0}]
    walk = _walk(fills)
    # day one's whole loss lands on its last fill (nothing to refuse); day two's first close does
    pred = P.breaker_prediction(walk, cap_pct=3.0, risk_pct=3.0, offset_min=0)
    assert [b["day"] for b in pred["breaches"]] == ["1970-01-01", "1970-01-02"]
    assert pred["breaches"][0]["refusals"] == 0
    assert pred["breach"]["day"] == "1970-01-02", "the graded breach is the first WITH a refusal"
    assert [r["open_ct"] for r in pred["must_be_absent"]] == [86_400 + 3000]
    assert pred["largest_day_loss_pct"] == 3.6        # 1.2 units x 3.0% on both days


def test_the_breaker_pass_keeps_the_arm_s_cap_and_moves_the_risk() -> None:
    """THE TWO LEGS ARE NOT INTERCHANGEABLE, pinned at both call sites: this one must pass the
    ARM'S OWN cap into the comparison and derive the risk; the other must derive the cap. A
    sentence or an artifact that confuses them misattributes the entire result."""
    import inspect
    src = inspect.getsource(P.run_breaker_stress)
    assert "breaker_prediction(u_walk" in src, "the prediction is read off pass BSU's own path"
    assert "u_inputs[\"InpPropGuard\"] = \"false\"" in src
    assert "fills_detail" in src, (
        "the derivation must be read off the LIVE path's own fills: the python bar model runs a "
        "different sequence and names days the live path never trades")
    assert "cap=cap_pct" in src, "the arm's own cap goes into the comparison"
    assert "InpDailyLossCapPct\": {\"from" in src, "the cap is named as NOT MOVED"
    assert "NOT MOVED" in src
    assert "risk_pct\": risk_pct" in src
    moved = P.breaker_stress_inputs(P.live_stance_inputs("REVERSE_DIRECTION", 1, 2, offset_min=0),
                                    risk_pct=3.28)
    declared = P.read_preset_inputs()
    assert moved["InpRiskPercent"] == "3.28"
    assert moved["InpPropBestDayPct"] == "0", (
        "the $/day ceiling is a FIXED dollar amount: at the derived risk the first good day reaches "
        "it, and left on it would refuse winning entries the cap prediction says must be present")
    assert moved["InpDailyLossCapPct"] == declared["InpDailyLossCapPct"]
    assert moved["InpPropGuard"] == "true" and moved["InpLiveExecution"] == "true"


def test_the_shield_is_measured_and_a_non_isolated_construction_is_refused() -> None:
    """THE ISOLATION IS THE CONDITION THIS LEG'S VERDICT RESTS ON, so it is measured on this very
    path rather than asserted. A shield refusal refuses the same entries the daily-cap prediction
    says must be PRESENT, and the comparison would then grade a second rule as a governor defect.
    """
    quiet = [{"key": "a", "open_ct": 1000, "close_ct": 2000, "r": 1.0, "risk_usd": 41.20},
             {"key": "b", "open_ct": 3000, "close_ct": 4000, "r": -1.0, "risk_usd": 41.20}]
    ex = P.shield_exposure(quiet, size=25_000.0, maxdd_pct=6.0, deposit=25_000.0, offset_min=0)
    assert ex["would_refuse"] == []
    # the floor sits 6% of size below the peak; the +1R leg lifts the peak by $41.20, so the
    # tightest headroom on this path is $1,500 minus exactly that
    assert ex["min_headroom_usd"] == 1458.8, "the floor is 6% of size below the peak"
    assert "pinned" in ex["why"] or "never came within" in ex["why"]

    # a path that gives back more than the shield's depth: the LAST entry is at/below the floor
    deep = [{"key": "a", "open_ct": 1000, "close_ct": 2000, "r": 4.0, "risk_usd": 820.0},
            {"key": "b", "open_ct": 3000, "close_ct": 4000, "r": -3.0, "risk_usd": 820.0},
            {"key": "c", "open_ct": 5000, "close_ct": 6000, "r": -3.0, "risk_usd": 820.0},
            {"key": "d", "open_ct": 7000, "close_ct": 8000, "r": -1.0, "risk_usd": 820.0}]
    ex = P.shield_exposure(deep, size=25_000.0, maxdd_pct=6.0, deposit=25_000.0, offset_min=0)
    assert [r["key"] for r in ex["would_refuse"]] == ["d"]
    assert ex["floor_pinned_at_size"], (
        "the close-based peak is above size + maxdd, so the floor is CLAMPED at size and no "
        "intrabar floating high can raise it — which is why the close-walk is sufficient here")


def test_the_profit_ceiling_reports_what_the_construction_switches_off() -> None:
    """Switching a rule off for a pass is only honest if the artifact says how much it would have
    refused. The ceiling is a fixed $/day, so at the derived risk it is reached on the first good
    day and its refusals would otherwise look like the daily cap's."""
    fills = [{"key": "a", "open_ct": 1000, "close_ct": 2000, "r": 1.0, "risk_usd": 820.0},
             {"key": "b", "open_ct": 3000, "close_ct": 4000, "r": -0.2, "risk_usd": 820.0},
             {"key": "c", "open_ct": 5000, "close_ct": 6000, "r": -0.2, "risk_usd": 820.0}]
    ex = P.profit_ceiling_exposure(fills, cap_usd=250.0, deposit=25_000.0, offset_min=0)
    # the ceiling is crossed by the FIRST fill's close, so every entry after it that day is refused
    assert [r["key"] for r in ex["would_refuse"]] == ["b", "c"]
    assert ex["days_reaching_it"] == ["1970-01-01"]
    assert "would have refused 2 entry(ies)" in ex["why"]
    # and a pass where the ceiling does NOT bind reports that too, rather than an empty claim
    ex2 = P.profit_ceiling_exposure(fills, cap_usd=100_000.0, deposit=25_000.0, offset_min=0)
    assert ex2["would_refuse"] == [] and ex2["days_reaching_it"] == []


def test_the_vacuous_verdict_counts_the_stops_the_cap_would_need() -> None:
    """A bare VACUOUS leaves the reader guessing whether the cap is one bad day away or
    unreachable. For this arm it is the second, and the number that says so — consecutive full
    stops inside one UTC day — is computed from the pass's own fills (41.20/25,000 = 0.165% per
    stop, so a 3% day needs 19 of them) rather than quoted."""
    fills = [dict(REAL_FILL, r=-0.5), dict(REAL_FILL, key="b", open_ct=1790097000,
                                          close_ct=1790100600, r=-0.2)]
    gov = P.stance_governor_audit(fills, preset=_declared(), deposit=25_000.0, offset_min=0)
    assert gov["verdict"] == "VACUOUS"
    assert "consecutive full stops" in gov["why"]
    assert "19 consecutive full stops" in gov["why"], gov["why"]
    assert "unreachable by this strategy at this risk" in gov["why"]
    assert "--breaker-stress" in gov["why"], "the note names the leg that does exercise it"


def test_the_two_stress_legs_name_their_own_construction() -> None:
    """Each leg's WHY paragraph has to say which quantity it moved, because a verdict quoted
    without that sentence reads as a statement about the other one."""
    assert "SHIPPING 3% CAP" in P.BREAKER_STRESS_WHY
    assert "NOT BY MOVING THE CAP" in P.BREAKER_STRESS_WHY
    assert "MUST bind" in P.GOVERNOR_STRESS_WHY
    assert "does not change that fact" in P.GOVERNOR_STRESS_WHY
    # and the comparison's wording follows the caller: the derived-risk leg names the risk
    pred = P.governor_prediction(STRESS_DAY, cap_pct=0.2, deposit=25_000.0, offset_min=0)
    ungoverned = [r["open_ct"] for r in pred["must_be_absent"] + pred["must_be_present"]]
    governed = [c for c in ungoverned if c != 1790101200]
    got, why, _ = P.governor_stress_compare(pred, ungoverned, governed, cap=3.0, dd=0.297,
                                           cap_basis="this is the ARM'S OWN cap, unchanged")
    assert got == "GOVERNED-PASS" and "the ARM'S OWN cap, unchanged" in why
    assert "BINDS" in why

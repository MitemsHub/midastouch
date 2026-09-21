"""Amendment 6 (register R5): min-lot risk refusal — python side.

Pins the frozen rule: a floored-to-min-lot trade that would risk more than
MAX_RISK_FRACTION of the sizing basis is VETOED, not oversized — in BOTH
engines (EA v1.14 mirrors the predicate with InpMaxRiskPct; the formula
here is the one the EA copies). Boundary law: strict inequality, exactly-at-
cap fills. Regression law: the certified corpus must never reach the veto,
so n=151 / +1.474R (WF REVERSE_DIRECTION, certificate …_1258's python leg)
is asserted directly — if the veto ever fires on the certified window,
the amendment's own "verified unchanged" claim is false and this suite
fails.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import midas_sweep as ms  # noqa: E402


# --- the predicate, every boundary --------------------------------------------

def test_cap_constant_is_the_frozen_amendment6_value():
    assert ms.MAX_RISK_FRACTION == 0.15
    assert ms.RISK_FRACTION == 0.01
    assert ms.MIN_LOT == 0.01 and ms.TICK_VALUE_PER_LOT == 100.0


def test_veto_fires_above_cap():
    # min-lot risk $1,000 vs cap 15% of $5,000 = $750 -> veto
    assert ms.minlot_risk_exceeds_cap(stop_d=1000.0, basis=5000.0) is True


def test_exactly_at_cap_fills():
    # $750 risk == $750 cap: strict inequality, the trade fills
    assert ms.minlot_risk_exceeds_cap(stop_d=750.0, basis=5000.0) is False


def test_below_cap_fills_and_floors():
    assert ms.minlot_risk_exceeds_cap(stop_d=749.99, basis=5000.0) is False


def test_certified_corpus_and_day_one_arms_stay_inside_the_cap():
    # the measured facts the 15% freeze rests on (protocol amendment 6):
    # the certified corpus's worst floored stop was $277.30 (5.5% of book);
    # the $50 §13 arms' day-one min-lot risk was ≈$4.55 (9.1% of basis).
    assert ms.minlot_risk_exceeds_cap(stop_d=277.30, basis=5000.0) is False
    assert ms.minlot_risk_exceeds_cap(stop_d=4.55, basis=50.0) is False


def test_small_basis_triggers_the_veto():
    # the corner the amendment exists for: a drawn-down book and a runaway stop
    assert ms.minlot_risk_exceeds_cap(stop_d=1000.0, basis=3000.0) is True
    # even a $50 arm refuses a $12+ stop under the frozen cap
    assert ms.minlot_risk_exceeds_cap(stop_d=12.0, basis=50.0) is True


# --- engine integration ---------------------------------------------------------

class _FakeRes:
    vetoed = 0


def test_runresult_carries_the_veto_counter():
    r = ms.RunResult()
    assert r.vetoed == 0


def test_veto_is_pure_and_sign_safe():
    # garbage inputs never veto silently negative: only a genuine excess fires
    assert ms.minlot_risk_exceeds_cap(stop_d=0.0, basis=0.0) is False
    assert ms.minlot_risk_exceeds_cap(stop_d=-1.0, basis=5000.0) is False


# --- certified-corpus regression law --------------------------------------------

def test_certified_wf_regen_unchanged_by_the_amendment():
    """n=151 / +1.474R is certificate …_1258's python leg (engine of record,
    pre-amendment). At the frozen 15% cap the veto must never fire on the
    certified corpus — if it ever does, the amendment's corpus-neutrality
    claim is false and this suite fails.

    `corpus='frozen'` — deliberately, and it is the ONLY test that asks for it: those 151
    trades are the frozen certificate's arithmetic, computed on the research series that is
    now archived (archive/frozen_corpus/, hash-pinned) because it is not the market the EA
    trades. It skips when the archive is not restored rather than quietly re-running on the
    venue's bars, which would silently compare two different certificates."""
    import midas_parity as P
    try:
        data = P.python_build_data(corpus="frozen")
    except SystemExit as exc:
        from pytest import skip
        skip(f"the frozen corpus is not restored on this checkout: {exc}")
    rr = P.M.run_mode(P.MODE, P.T0, P.T1, data)
    assert len(rr.trades) == 151
    assert abs(sum(t["r"] for t in rr.trades) - 1.474) < 5e-4
    assert rr.vetoed == 0, "the veto fired on the certified corpus — amendment 6's unchanged-claim is FALSE"

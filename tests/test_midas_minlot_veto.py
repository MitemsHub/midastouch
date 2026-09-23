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

def test_wf_regen_unchanged_by_the_amendment():
    """RE-POINTED 2026-09-21: n=53 / +14.256R is the engine of record on the VENUE's own bars
    over the venue-served part of the walk-forward window (2026-01-12 → 03-31), at the account
    basis. At the frozen 15% cap the min-lot veto must never fire there — if it ever does, the
    amendment's corpus-neutrality claim is false and this suite fails.

    WHAT THIS REPLACED, AND WHY. This test used to pin n=151 / +1.474R on the retired research
    series (`corpus='frozen'`). That series was deleted on 2026-09-21: the law was mathematically
    sound but it could only be re-checked by someone holding a copy of bytes that no fetch can
    reproduce, which makes it a certificate nobody can audit. The same claim — the veto does not
    move the engine of record's trade set — is now stated on the series the EA actually trades,
    whose bars are re-fetchable (`scripts/midas_fetch_history.py --suffix _upcomers`).

    The 151-trade figure is not lost as history (it is cited in docs/MIDASTOUCH_PROTOCOL.md
    §9-§15 with its corpus named); it is lost as a *re-runnable* check, which is the honest
    trade this change makes. See docs/FROZEN_CORPUS_20260921.md §4.

    Reproducibility of the pinned numbers was verified before pinning them: the parity harness's
    own wfv run on the same window, basis and corpus reports 53 trades / +14.2563R (artifact
    artifacts/midas_parity_result_20260921_1213.json), and the veto count was measured as 0.

    RE-POINTED AGAIN 2026-09-22, 53 -> 56 trades: the contract's trigger threshold moved
    (midas_parity.BB_DEV 2.0 -> 1.5, the pre-registered frequency study
    docs/FREQUENCY_AXES_PREREG_20260922.md), and the python leg's trigger array moves with it —
    that is what "one contract" means, and it necessarily moves this law's trade count. The
    figure was measured by this test's own code path on the venue corpus at the account basis:
    n=56, +15.9352R, vetoed=0. WHAT DID NOT MOVE IS THE CLAIM: the min-lot veto still never
    fires on this window, which is the amendment-6 invariant this law exists to protect.
    """
    import midas_parity as P
    spec = P._window_spec("wfv")
    try:
        data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    except SystemExit as exc:
        from pytest import skip
        skip(f"the venue's own series is not on this checkout: {exc}")
    prev = P.M._BASIS
    P.M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = P.M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        P.M._BASIS = prev
    assert len(rr.trades) == 56
    assert abs(sum(t["r"] for t in rr.trades) - 15.9352) < 5e-4
    assert rr.vetoed == 0, "the veto fired on the venue corpus — amendment 6's unchanged-claim is FALSE"

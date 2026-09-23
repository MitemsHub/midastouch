"""The 24-hour study: mechanism, verdict arithmetic, and a harness that can't drift.

WHY THIS FILE EXISTS. `docs/SESSION24_PREREG_20260923.md` fixed the rule that decides
whether the armed rule may trade all 24 hours BEFORE any measurement; `scripts/midas_second_session.py`
implements it; `artifacts/midas_session24_20260923.json` holds the measured FAIL. Three
things would make that record worthless, and each has a pin here:

  * the hour partition misclassifying a fill, so "evening" and "day" books silently blur
    (`in_evening` is the ONE definition and these tests walk its boundary);
  * the verdict arithmetic drifting after the fact, in either direction — a FAIL turning
    into a PASS by moving a threshold, or a future PASS being refused by a stale pin;
  * the harness certifying a study while its own pinned corpus law no longer reproduces.

The corpus runs are NOT re-run here (minutes each; the artifact holds them); the pins run
on synthetic books and on the module's own constants, plus one real engine call whose
trade count is pinned by the corpus law (56).
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import midas_second_session as ss  # noqa: E402


def _t(open_ct: int, side: int = 1, r: float = 0.1) -> dict:
    return {"open_ct": open_ct, "side": side, "r": r}


def test_evening_partition_boundaries():
    """18:00Z is evening, 17:59 is not; 03:59 is evening, 04:00 is not — both edges."""
    from datetime import datetime, timezone
    d0 = int(datetime(2026, 6, 2, tzinfo=timezone.utc).timestamp())
    assert ss.in_evening(17) is False
    assert ss.in_evening(18) is True
    assert ss.in_evening(23) is True
    assert ss.in_evening(0) is True
    assert ss.in_evening(3) is True
    assert ss.in_evening(4) is False
    # the definition agrees with the fills it classifies, all 24 hours
    for h in range(24):
        b = _t(d0 + h * 3600)
        assert ss.in_evening(ss._hour(b)) == (h >= 18 or h < 4)


def test_window_fills_partitions_exactly():
    """day + evening == the whole book; nothing classified twice, nothing dropped."""
    from datetime import datetime, timezone
    d0 = int(datetime(2026, 6, 2, tzinfo=timezone.utc).timestamp())
    book = [_t(d0 + h * 3600) for h in range(24)]
    day = ss.window_fills(book, evening=False)
    eve = ss.window_fills(book, evening=True)
    assert len(day) + len(eve) == len(book)
    assert len(day) == 14 and len(eve) == 10  # hours 4..17 day; 18..23,0..3 evening
    assert {id(t) for t in day} | {id(t) for t in eve} == {id(t) for t in book}


def test_t_stat_matches_textbook():
    rs = [0.1, 0.2, 0.3, 0.4, 0.5]
    m = sum(rs) / len(rs)
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (len(rs) - 1))
    assert abs(ss.t_stat(rs) - m / (sd / math.sqrt(len(rs)))) < 1e-12
    assert ss.t_stat([0.1]) == 0.0


def _verdict_with(oos_inc: dict, oos_h24: dict, wfv_inc: dict, wfv_h24: dict,
                  eve: dict | None = None) -> dict:
    runs = {"candidates": {
        "oos": {"incumbent": oos_inc, "h24": oos_h24,
                "eve_complement": eve or {"n": 0}},
        "wfv": {"incumbent": wfv_inc, "h24": wfv_h24},
    }}
    return ss.verdict(runs)


def test_verdict_fail_is_reproducible_from_artifact_numbers():
    """The recorded FAIL re-derives from the artifact's own numbers, check by check."""
    import json
    art = json.loads(Path("artifacts/midas_session24_20260923.json").read_text())
    v = art["verdict"]
    assert v["passed"] is False
    inc, h24 = art["runs"]["candidates"]["oos"]["incumbent"], art["runs"]["candidates"]["oos"]["h24"]
    wfv = art["runs"]["candidates"]["wfv"]
    checks = {
        "c1_net_r_not_lower": h24["net_r"] >= inc["net_r"],
        "c2_mean_r_survives": ((h24["mean_r"] >= 0.0155 and h24["t"] >= 1.96)
                               or h24["mean_r"] >= inc["mean_r"] - 0.02),
        "c3_dd_within_3r": h24["max_dd_r"] <= inc["max_dd_r"] + 3.0,
        "c4_direction_agrees_wfv": wfv["h24"]["net_r"] >= wfv["incumbent"]["net_r"],
        "c5_activity_real": h24["fills_per_day"] >= 0.50,
    }
    assert checks == v["checks"]


def test_verdict_would_pass_on_a_genuinely_better_book():
    """A future book that clears every fixed condition IS a PASS — the pin forbids
    a stale refusal, not just a rubber-stamp."""
    inc = {"net_r": 10.0, "mean_r": 0.08, "max_dd_r": 5.0}
    h24 = {"net_r": 12.0, "mean_r": 0.09, "max_dd_r": 7.0, "t": 2.5,
           "fills_per_day": 1.2}
    wfv_i = {"net_r": 15.0}
    wfv_h = {"net_r": 16.0}
    v = _verdict_with(inc, h24, wfv_i, wfv_h)
    assert v["passed"] is True
    assert all(v["checks"].values())


def test_verdict_thresholds_are_the_preregisters_ones():
    """The constants in the verdict ARE the pre-registration's: 0.02R parity, 3R dd
    allowance, 0.50 fpd, t-bar 1.96. Moving any of them breaks this pin."""
    import inspect
    src = inspect.getsource(ss.verdict)
    assert "0.02" in src and "3.0" in src and "0.50" in src and "1.96" in src
    assert "0.0155" in src  # the margin reading's floor, named in the pre-reg


def test_law_gate_refuses_a_moved_corpus_law():
    assert ss.law_ok(56, 15.9352) is True
    assert ss.law_ok(56, 15.9352 + 0.01) is False
    assert ss.law_ok(55, 15.9352) is False
    assert ss.law_ok(57, 15.9352) is False


def test_live_engine_still_reproduces_the_corpus_law():
    """One real engine call: the pinned law must hold today, in this tree."""
    import midas_parity as P
    import midas_sweep as M
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    n = len(rr.trades)
    total = sum(t["r"] for t in rr.trades)
    assert (n, total) == (56, 15.9352) or ss.law_ok(n, total)

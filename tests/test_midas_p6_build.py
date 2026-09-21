"""P6 build-block pins (register §2b, 2026-09-18): v1.19 in-tree, dormant.

The operator ordered the P6 amendment BUILT NOW, deployed only after the
2026-10-01 reading passes. These pins hold the boundary in place:

  * FROZEN DEFAULTS: InpEntryTF defaults to PERIOD_M15 and InpTpMult to
    2.0 — with defaults, v1.19 is byte-identical behavior to v1.18 (the
    certified paths stay certified);
  * the PERTICK/live engine is fully TF-parameterized: after the BAR-engine
    guard, NO PERIOD_M15 literal may remain in any live-path site (handles,
    TriggerOnClosedBar, TrackFreshM15Bar, GetBar, sig-open read) — each
    former site must cite InpEntryTF;
  * BAR parity stays hardwired M15 and M5+BAR fails closed at init;
  * the ERA note carries the +p6-entrytf citation (never-abort class) and
    the verdict tool admits the v1.18→v1.19 transition BOTH directions;
  * both staged LV presets exist and differ from the live preset in EXACTLY
    the registered keys (interim: InpTpMult only; winner: InpTpMult +
    InpEntryTF) — and both are QUEUED (explicit do-not-splice headers);
  * the deployer's verify contract accepts the v1.19 citation class so the
    armed chain cannot verify-fail when the source tree advances to v1.19.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"


def _src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


# --- frozen defaults: dormant by construction ---------------------------------

def test_v119_frozen_defaults():
    s = _src()
    m = re.search(r'input\s+ENUM_TIMEFRAMES\s+InpEntryTF\s*=\s*(\w+);', s)
    assert m and m.group(1) == "PERIOD_M15", "InpEntryTF must default to the certified M15"
    m2 = re.search(r'input double\s+InpTpMult\s*=\s*([\d.]+);', s)
    assert m2 and m2.group(1) == "2.0", "InpTpMult must keep the certified 2.0 default"
    mm = re.search(r'#property version\s+"([\d.]+)"', s)
    md = re.search(r'#define\s+APP_VERSION\s+"MIDAS(\d+)\.(\d+)"', s)
    assert mm and md and mm.group(1) == f"{md.group(1)}.{md.group(2)}"
    assert md.group(2) == "19", "this build block is v1.19"


def test_live_path_fully_tf_parameterized():
    """After the BAR guard, every former PERIOD_M15 live-path site must read
    InpEntryTF. The only PERIOD_M15 literals allowed are inside the BAR/parity
    engine (OnBarReplay/ReplayThrough region) and the BAR-mode spread file
    default — count them."""
    s = _src()
    # the guard exists and fails closed
    assert re.search(r'if\(InpBarModel && InpEntryTF != PERIOD_M15\)', s), \
        "M5+BAR must fail closed at init"
    assert "M15-only" in s, "the guard must say why"
    # handles
    assert re.search(r'iBands\(_Symbol, InpEntryTF,', s)
    assert re.search(r'iRSI\(_Symbol, InpEntryTF,', s)
    # trigger + fresh-bar + sig-open + GetBar
    assert "CopyClose(_Symbol, InpEntryTF, 1, 2, c1)" in s
    assert "CopyClose(_Symbol, InpEntryTF, 2, 1, c0)" in s
    assert "iTime(_Symbol, InpEntryTF, 0)" in s
    assert "iTime(_Symbol, InpEntryTF, 1)" in s
    assert "iBarShift(_Symbol, InpEntryTF, t, true)" in s
    # every remaining PERIOD_M15 literal must live in the BAR engine region
    # (after the OnBarReplay marker) or in the spread-file / entry-TF default.
    # COMMENTS ARE NOT SITES. The scan runs over comment-stripped source: a comment that
    # names PERIOD_M15 to explain why it is NOT read there (the HUD's `entryTF=` note is one)
    # is documentation, and flagging it made this test fail on a comment while the code it
    # guards was correct — the same layout-pinning mistake that reddened
    # tests/test_midas_hud.py the day the label gained its explanation.
    code = re.sub(r"//[^\n]*", "", s)
    bar_marker = code.find("void OnBarReplay()")
    assert bar_marker > 0
    for m in re.finditer(r'PERIOD_M15', code):
        line_start = code.rfind("\n", 0, m.start()) + 1
        line = code[line_start:code.find("\n", m.start())]
        in_bar = m.start() > bar_marker
        in_default = "InpSpreadFile" in line or "InpEntryTF" in line
        assert in_bar or in_default, f"stray PERIOD_M15 outside the BAR engine: {line.strip()}"


def test_era_note_carries_p6_citation():
    s = _src()
    assert 'era_note += "+p6-entrytf"' in s, \
        "v1.19 must cite the register in its ERA note (§1 never-abort class)"
    # and the citation is appended only on the non-BAR (live/paper) path
    idx_p6 = s.find('era_note += "+p6-entrytf"')
    idx_bar = s.find('if(!InpBarModel)')
    assert 0 < idx_bar < idx_p6


# --- the verdict tool admits the transition (both directions) ------------------

def test_v119_transition_exempted_both_directions(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import era as era_mod
    from midas_verdict import arm_statistics

    def _write(rows):
        p = tmp_path / "ledger.csv"
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return str(p)

    def _close(i):
        return (f"CLOSE,{1789657200 + i * 3600},{1789657200 + i * 3600},"
                f"SL,4320.00000,1.000,1.50,50.00,45.45571,0.50,2.00,0,{i}")

    # cited: v1.18 → v1.19 with the full citation chain — exempt
    rows = [f"ERA,MIDAS1.18,{era_mod.ERA_EPOCH},"
            "pertick-fills+telemetry-only-per-V2-register+diag-nofill"]
    for i in range(30):
        rows.append(_close(i))
    rows.append(f"ERA,MIDAS1.19,{1789657200 + 30 * 3600},"
                "pertick-fills+telemetry-only-per-V2-register+diag-nofill+p6-entrytf")
    for i in range(30, 61):
        rows.append(_close(i))
    s = arm_statistics(_write(rows))
    assert s["n"] == 61
    assert sorted(s["era_versions"]) == ["MIDAS1.18", "MIDAS1.19"]
    assert s.get("problems", []) == [], "cited v1.19 transition is never-abort"

    # uncited: the same transition still aborts
    rows2 = [f"ERA,MIDAS1.18,{era_mod.ERA_EPOCH},pertick-fills+diag-nofill"]
    rows2.append(_close(0))
    rows2.append(f"ERA,MIDAS1.19,{1789660800},pertick-fills")
    rows2.append(_close(1))
    s2 = arm_statistics(_write(rows2))
    assert any("version change" in p for p in s2.get("problems", [])), \
        "uncited v1.19 transition still aborts"


# --- the staged presets: exact-diff, queued, and shape-pinned -------------------

def _preset_vals(name: str) -> dict:
    vals = {}
    for line in (REPO / "mql5" / "MIDASTOUCH" / name).read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith(";") and "=" in t:
            k, v = t.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


# --- the retired presets: their ABSENCE is the decision, and it is pinned -------
#
# The seven non-trading presets this block used to diff — the LV arm, its two staged
# TP15 variants, and the M1m/M1o/M1s/M1t paper arms — were deleted by commit
# `4fba1fe` ("Delete the seven non-trading presets: one trading preset, two
# reference files"), and the 2026-10-01 P6 reading they were queued for was
# superseded when the program moved to this account. Two of these tests were the
# LOUDEST kind of stale: they read files that no longer exist, so they could not
# fail for a reason anyone could act on.
#
# Their pins are not dropped, they are INVERTED. A queued preset reappearing is now
# the assertion, because that is the event worth catching: a file carrying
# `InpLiveExecution=true` for a retired arm's magic, spliced in by a script that did
# not know it was retired. To re-instate one deliberately, delete it from this list
# in the same commit that restores its DO NOT SPLICE header and its exact-diff pins.

RETIRED_PRESETS = (
    "MidastouchAI_LV_gold.set",
    "MidastouchAI_LV_TP15_M15_gold.set",
    "MidastouchAI_LV_TP15_M5_gold.set",
    "MidastouchAI_M1m_gold.set",
    "MidastouchAI_M1o_gold.set",
    "MidastouchAI_M1s_gold.set",
    "MidastouchAI_M1t_gold.set",
)


def test_the_retired_presets_have_not_come_back_unregistered():
    still_here = [n for n in RETIRED_PRESETS
                  if (REPO / "mql5" / "MIDASTOUCH" / n).is_file()]
    assert not still_here, (
        "retired preset(s) are present again: " + ", ".join(still_here) + " — deleted "
        "by 4fba1fe as non-trading surfaces. Re-instating one is a deliberate act: the "
        "file must come back with its DO NOT SPLICE header and the exact-diff pin that "
        "went with it, in the same commit that removes it from RETIRED_PRESETS. A "
        "preset that quietly reappears is one splice away from arming a closed arm.")


def test_paper_arms_stay_certified_shape():
    """Every preset that ships is paper-only, TP 2.0, M15 — whatever ships.

    This iterates the shipped `.set` files instead of a hardcoded arm list. The old
    list (M1/M1t/M1s/M1m) went stale the moment the retired presets were deleted: a
    pin that names files which do not exist protects nothing and reports red for a
    reason nobody can fix. This one cannot go stale — a new preset is covered the day
    it ships, which is the only day that matters.
    """
    shipped = sorted((REPO / "mql5" / "MIDASTOUCH").glob("MidastouchAI_*_gold.set"))
    assert len(shipped) >= 2, (
        f"expected at least the M1 baseline and the account mirror, found {len(shipped)}")
    for path in shipped:
        vals = _preset_vals(path.name)
        assert vals["InpEntryTF"] == "15", f"{path.name}: entry TF must be the certified M15"
        assert vals["InpTpMult"] == "2.0", f"{path.name}: TP must be the certified 2.0R"
        assert vals["InpLiveExecution"] == "false", (
            f"{path.name}: a shipped preset must not arm live execution — arming is an "
            f"arming-record event, never an input edit (see docs/MIDASTOUCH_HEALTH_GUIDE.md)")


# --- the armed deployer must accept the v1.19 citation class --------------------

def test_deployer_verify_accepts_v119_citation():
    src = (REPO / "scripts" / "midas_deploy_v118.py").read_text(encoding="utf-8")
    assert '"ERA,MIDAS1.19,"' in src, "deployer verify must admit the v1.19 ERA stamp"
    assert '"ERA,MIDAS1.18,"' in src, "v1.18 acceptance retained"


def test_deployer_verify_arms_v119_ledger(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "scripts"))
    import midas_deploy_v118 as dep
    import os
    now = 1_800_000_000.0
    p = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
    p.write_text(
        "ERA,MIDAS1.18,100,pertick-fills+telemetry-only-per-V2-register+diag-nofill\n"
        "ERA,MIDAS1.19,101,pertick-fills+telemetry-only-per-V2-register+diag-nofill+p6-entrytf\n"
        "EQ,50.00\n", encoding="utf-8")
    os.utime(p, (now, now))
    v = dep.verify_arms(tmp_path, min_epoch=now - 60)
    assert v["M1"] == "ok", "a v1.19-era paper ledger must verify"

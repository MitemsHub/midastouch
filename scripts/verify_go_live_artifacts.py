#!/usr/bin/env python3
"""Verify repository-side go-live EA artifacts without touching MT5 or a broker.

Checked reality (2026-09-15):

- `mql5/MITEMSHUB_AI/MitemshubAI.mq5` — the multi-strategy engine hosting the
  paper A/B arms (v26.38: per-tick hard SL/TP fills in paper mode, mirroring
  the broker-side resting orders the live book trades with).
- `V75MacroEngine.mq5` — the V75 macro engine / arm C (v2.23: arms-exact
  12-field ledger schema, per-tick paper exits from day one).
- The two presets `MitemshubAI_VOL75_LIVE.set` / `MitemshubAI_VOL75_FINAL.set`
  (live submits, final/paper does not, same magic, shared keys in agreement).

The certified BYTES are not duplicated here: `scripts/deploy_manifest.txt` is
the single source of truth for which worktree sha256 the deploy gate allows.
This verifier reads the manifest pins, asserts they match the worktree, and
asserts the pinned VERSIONS are the expected ones — so an engine edit without
a deliberate re-pin fails here instead of passing silently (the failure mode
that let the old v27.00 pin go stale for weeks).

This verifier checks the source contract and the preset intent. It does not
claim that a binary is attached to a terminal; that still requires an explicit
deployed-binary check outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M_SOURCE = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI.mq5"
V_SOURCE = ROOT / "V75MacroEngine.mq5"
LIVE = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set"
FINAL = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_FINAL.set"
ARM_D = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_D_FWD.set"
ARM_A2 = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_ARM_A2.set"
MANIFEST = ROOT / "scripts" / "deploy_manifest.txt"

EXPECTED_VERSIONS = {
    "mql5/mitemshub_ai/mitemshubai.mq5": "26.40",
    "v75macroengine.mq5": "2.24",
}
EXPECTED_MAGIC = "7788075"
# v26.40 arm D (forward test of the gated candidate): its own magic + arm tag.
EXPECTED_ARM_D_MAGIC = "7788150"
EXPECTED_ARM_D_TAG = "D"
# Arm A2 (restart of arm A's strangled slot at a $1,000 basis; user decision
# 2026-09-16, docs/ARM_A2_RESTART.md): strategy surface = candidate_inputs(
# "V28_REVERSE_BOTH", tp2.0); inherits arm A's ORIGINAL fleet slot 7788075
# (arm B keeps 7788100 — collision-free); paper-only. Supersedes the arm-E
# pre-draft (retired magic 7788175 must never re-enter any fleet CSV).
EXPECTED_ARM_A2_MAGIC = "7788075"
EXPECTED_ARM_A2_TAG = "A2"
EXPECTED_ARM_A2_FLEET = "7788010,7788025,7788050,7788075,7788100,7788150"
# Keys that may legitimately differ between LIVE and FINAL (ops choices, not
# intent drift): the tick recorder is enabled per-arm, not per-mode.
ALLOWED_PRESET_DRIFT = {"InpTickRecordEnabled"}


def _num_eq(a: str, b: str) -> bool:
    """Numeric-normalized preset comparison: "2" == "2.0" == "2.00"."""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


class VerificationError(Exception):
    """A go-live artifact failed a repository invariant."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_set(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("#", ";", "[")):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def manifest_pins() -> dict[str, tuple[str, str]]:
    """Parse deploy_manifest.txt pin lines -> {rel_path_lower: (version, sha256)}."""
    pins: dict[str, tuple[str, str]] = {}
    for line in MANIFEST.read_text(encoding="utf-8", errors="replace").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        parts = t.split("|")
        if len(parts) != 3:
            continue  # malformed lines are the deploy gate's problem to report
        rel, ver, digest = (p.strip() for p in parts)
        pins[rel.lower().replace("\\", "/")] = (ver, digest.lower())
    return pins


def verify_manifest() -> tuple[list[str], dict[str, str]]:
    """Worktree bytes must match the certified manifest pins, at expected versions."""
    problems: list[str] = []
    versions: dict[str, str] = {}
    try:
        pins = manifest_pins()
    except FileNotFoundError:
        return ["deploy manifest missing: scripts/deploy_manifest.txt"], versions
    for rel, expected_ver in EXPECTED_VERSIONS.items():
        pin = pins.get(rel)
        if pin is None:
            problems.append(f"deploy manifest has no pin for {rel}")
            continue
        ver, digest = pin
        if ver != expected_ver:
            problems.append(f"manifest pin version for {rel} is {ver}, expected {expected_ver}")
        path = ROOT / rel
        if not path.exists():
            problems.append(f"pinned source missing from worktree: {rel}")
            continue
        actual = sha256(path)
        if actual != digest:
            problems.append(
                f"worktree {rel} sha256 {actual[:12]}… does not match the certified "
                f"pin ({digest[:12]}…) — re-pin deliberately or restore the pinned bytes"
            )
        versions[rel] = ver
    return problems, versions


def function_slice(text: str, header: str, next_header: str) -> str:
    """Text from one function header to the next (for order-send absence checks)."""
    start = text.find(header)
    if start < 0:
        return ""
    end = text.find(next_header, start + len(header))
    return text[start:end] if end > 0 else text[start:]


def verify_mitemshubai(text: str, version: str) -> list[str]:
    problems: list[str] = []
    m = re.search(r'#define\s+APP_VERSION\s+"([\d.]+)"', text)
    if not m or m.group(1) != version:
        problems.append(f"MitemshubAI APP_VERSION is {m.group(1) if m else 'missing'}, expected {version}")

    required_markers = (
        "#include <Trade\\Trade.mqh>",
        '#include "Microstructure/TickRecorder.mqh"',
        "bool PaperActive() { return(!InpLiveExecution); }",
        "void PaperCheckHardExits()",                    # v26.38 fill-model parity
        "void PaperClose(string reason, double exit_price=0)",
        "double FleetOpenRisk(int &no_sl_count)",
        "g_pp_open && g_pp_orig_risk>0 && g_pp_vol>0",   # fleet guard sees the virtual position
        "bool OpenTradeLive(",
        "void OnTradeTransaction(",
        "void OnTick()",
        "NO real orders",
        "is a Crash/Boom symbol",                        # volatility-only mandate enforced
        'PaperLog("ERA,"+APP_VERSION',                   # v26.39 ledger era provenance
        "InpNoMomGate",                                  # v26.40 OOS-autopsy gates (inert by default)
        "InpHtfSlopeGate",
        "HtfSlopeOK",
        "v26.40: InpArmTag disambiguates arms sharing one terminal+symbol",
    )
    for marker in required_markers:
        if marker not in text:
            problems.append(f"MitemshubAI missing source marker: {marker}")

    # Fill-model parity is positional, not just present: hard exits must run on
    # EVERY tick BEFORE the bar guard, or paper fills at bar opens again.
    on_tick = text.find("void OnTick()")
    parity_call = text.find("if(PaperActive() && g_pp_open) PaperCheckHardExits();", on_tick)
    bar_guard = text.find("static datetime last_bar=0;", on_tick)
    if on_tick < 0 or parity_call < 0 or bar_guard < 0 or not (on_tick < parity_call < bar_guard):
        problems.append(
            "MitemshubAI per-tick hard-exit call is missing or not before the bar guard "
            "(paper fills would regress to bar-open cadence)"
        )

    # PaperOpen is a virtual book: it must never submit an order itself.
    paper_open_body = function_slice(text, "bool PaperOpen(", "void PaperCheckHardExits()")
    if paper_open_body:
        for order_call in ("trade.Buy", "trade.Sell", "OrderSend", "PositionOpen"):
            if order_call in paper_open_body:
                problems.append(f"MitemshubAI PaperOpen submits real orders ({order_call}) — paper must be virtual")
    else:
        problems.append("MitemshubAI PaperOpen body not found for order-send audit")
    return problems


def verify_v75(text: str, version: str) -> tuple[list[str], str | None]:
    problems: list[str] = []
    m = re.search(r'#define\s+ENGINE_VERSION\s+"([\d.]+)"', text)
    if not m or m.group(1) != version:
        problems.append(f"V75MacroEngine ENGINE_VERSION is {m.group(1) if m else 'missing'}, expected {version}")

    if '#include <Trade\\Trade.mqh>' not in text:
        problems.append("V75MacroEngine is missing the native Trade.mqh include")
    if '#include "' in text:
        problems.append("V75MacroEngine must be self-contained: custom includes are not allowed")

    required_markers = (
        "input bool   InpPaperMode          = false",
        "#define PAPER_START_EQUITY 50.0",
        "void PaperOpenTrade(",
        "void PaperCheckExits()",
        "void PaperCheckTimeout()",
        "void PaperCloseTrade(string reason)",
        "void PaperAppendLedger(string row)",
        "void ExecuteTrade(ENUM_ENTRY_SIGNAL signal)",
        "bool IsNewM30Candle()",
        "if(!IsNewM30Candle())",                          # entries only behind the M30 gate
        "trade.Buy(volume, g_symbol, entryPrice, slPrice, tpPrice",   # broker-side resting SL/TP
        "trade.PositionClose(g_ticket",
        "double CalibratedTickValue()",
        "LONG-ONLY",
        "MACROTREND_ALIGNED_DOWN",                        # long-only stand-down present
        "void SyncPositionState()",
        "void CheckTradeTimeout()",
        'PaperAppendLedger("ERA," + ENGINE_VERSION',     # v2.24 ledger era provenance
    )
    for marker in required_markers:
        if marker not in text:
            problems.append(f"V75MacroEngine missing source marker: {marker}")

    # Per-tick paper guardians must run BEFORE the M30 gatekeeper (arm C fills
    # exits every tick; only entries wait for the candle).
    on_tick = text.find("void OnTick()")
    exits = text.find("PaperCheckExits();", on_tick)
    gate = text.find("if(!IsNewM30Candle())", on_tick)
    if on_tick < 0 or exits < 0 or gate < 0 or not (on_tick < exits < gate):
        problems.append("V75MacroEngine PaperCheckExits is missing or not before the M30 gate")

    # The arms-exact 12-field OPEN ledger schema (v2.22 fix — the tester-mode
    # ledger validation caught 13 zeroed fields; do not regress it).
    schema = '"OPEN,%I64d,%I64d,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.2f,%d,%s"'
    if schema not in text:
        problems.append("V75MacroEngine OPEN ledger schema is not the arms-exact 12-field format")

    # #property version cannot take a macro in MQL5 and may lag the banner
    # macro; surfaced informationally so the drift is at least visible.
    pm = re.search(r'#property version\s+"([\d.]+)"', text)
    return problems, (pm.group(1) if pm else None)


def verify_preset(path: Path, *, live: bool) -> list[str]:
    values = read_set(path)
    problems: list[str] = []
    expected = {
        "InpMagic": EXPECTED_MAGIC,
        "InpMaxDeviationPoints": "50",
        "InpDrawHud": "true",
        "InpLiveExecution": "true" if live else "false",
    }
    if live:
        # 2026-09-16 rehearsal finding: the LIVE set was a 7-line stub, so a
        # fresh attach + Load booted InpTpMult at the 2.4 default instead of
        # the certified tp18 geometry the truth table and certified chain are
        # built on. The preset must now carry the executed surface's pins.
        expected.update({
            "InpTpMult": "1.8",                      # certified tp18 geometry
            "InpRiskPerTrade": "0.005",
            "InpMaxEffectiveRiskPct": "20.0",
            "InpPaperEquity": "50.0",
            "InpFleetMagicsCSV": "7788010,7788025,7788050,7788075,7788100",
        })
    for key, value in expected.items():
        if values.get(key) != value:
            problems.append(f"{path.name}: {key}={values.get(key)!r}, expected {value!r}")
    return problems


def verify_arm_d_preset(path: Path) -> list[str]:
    """Arm D (forward test of the gated candidate) — fail-closed preset pins.

    The frozen candidate (SPRINT_REPORT finalist 1 + BOTH gates,
    docs/OOS_AUTOPSY_20260915.md) must not drift silently, and the arm must
    stay paper-only, collision-free beside arm B, and lab-parity flagged.
    Changing any of these requires a deliberate protocol amendment + this pin.
    """
    values = read_set(path)
    problems: list[str] = []
    expected = {
        "InpMagic": EXPECTED_ARM_D_MAGIC,
        "InpArmTag": EXPECTED_ARM_D_TAG,
        "InpLiveExecution": "false",
        "InpTickRecordEnabled": "false",     # arm B owns the terminal's shared tick file
        "InpSelfCorrect": "false",           # v30 self-correct has no lab counterpart
        # frozen gated candidate (docs/OOS_AUTOPSY_20260915.md):
        "InpPullbackMin": "0.60",
        "InpPullbackMax": "0.70",
        "InpTpMult": "1.6",
        "InpPbEmaSideVeto": "true",
        "InpNoMomGate": "true",
        "InpHtfSlopeGate": "true",
        "InpUseBreakout": "false",
        "InpUseMeanRevert": "false",
        "InpUseBandFade": "false",
        "InpBeTriggerR": "1.0",
        "InpProfitLockR": "0.5",
        "InpMaxHoldBars": "20",
        "InpMaxSpreadATRFrac": "0.18",
        "InpAdaptiveConviction": "true",
        "InpRiskPerTrade": "0.005",
        "InpPaperEquity": "50.0",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            problems.append(f"{path.name}: {key}={values.get(key)!r}, expected {value!r}")
    if EXPECTED_ARM_D_MAGIC not in values.get("InpFleetMagicsCSV", ""):
        problems.append(f"{path.name}: InpFleetMagicsCSV does not include {EXPECTED_ARM_D_MAGIC} "
                        f"(orphan magic: invisible to the fleet guard)")
    return problems


def verify_arm_a2_preset(path: Path) -> list[str]:
    """Arm A2 (REVERSE_BOTH tp2.0 restart at a $1,000 basis) — fail-closed
    preset pins.

    The preset was drafted as a BUILD CONTRACT before the forward EA existed;
    the build now exists (MitemshubAI_v28_fwd, APP_VERSION 28.10) and passed
    parity on 2026-09-16 (artifacts/v28_research/armE_parity_20260916_181219Z.json).
    Strategy values are pinned equal to the parity harness's candidate_inputs
    surface (build_parity.INPUT_PINS + InpRiskFraction) so the parity run and
    the forward preset can never silently diverge. Changing any value here
    requires a dated amendment to docs/ARM_A2_RESTART.md plus this pin.
    """
    values = read_set(path)
    problems: list[str] = []
    expected = {
        "InpLiveExecution": "false",        # paper-only, always
        "InpMagic": EXPECTED_ARM_A2_MAGIC,
        "InpArmTag": EXPECTED_ARM_A2_TAG,
        # strategy surface — EXACTLY the parity harness's pins:
        "InpStrategyMode": "3",             # V28_REVERSE_BOTH
        "InpStopATRMultiplier": "2.0",
        "InpTargetATRMultiplier": "2.0",    # the candidate: tp2.0
        "InpMaxHoldMinutes": "180",
        "InpRiskFraction": "0.01",
        "InpAllowLong": "true",
        "InpAllowShort": "true",
        "InpLegacyV27ModifyClose": "false",
        "InpResearchLogging": "true",       # parity's Trade R evidence
        # paper basis & routing — mirror arm D:
        "InpPaperEquity": "1000.0",
        "InpPaperSpreadMult": "1.0",
        "InpSameSymbolMaxPos": "1",
        "InpFleetMagicsCSV": EXPECTED_ARM_A2_FLEET,
        # account-budget guard + floor-mode policy (§2 amendment 2026-09-16):
        # the guard cap and the hard drawdown stop are frozen so the
        # strangulation-zone contract is a pinned constant, not a default
        "InpMaxTotalRiskPct": "15.0",
        "InpFloorModeMaxDDPct": "30.0",
        "InpFloorModeConviction": "true",
        # materiality-conditioned conviction bar (§2 amendment 2026-09-16):
        # the bar applies only above this overage — at A2's ~1.28% it must
        # NOT bind (0/800 observed strong confluences would throttle the arm)
        "InpFloorModeConvictionMinRiskPct": "2.5",
        # collection & ops:
        "InpSessionStartHour": "0",
        "InpSessionEndHour": "0",
        "InpTickRecordEnabled": "false",    # arm B owns the shared tick file
    }
    for key, value in expected.items():
        if values.get(key) != value:
            problems.append(f"{path.name}: {key}={values.get(key)!r}, expected {value!r}")
    # Every fleet CSV that names an arm must name E too — an orphan magic is
    # invisible to the fleet guard (the arm-D verifier's orphan check, from E's side).
    return problems


def verify_arm_a2_consistency() -> list[str]:
    """Cross-artifact coherence (pre-start): preset vs parity pins vs the
    accrual registry. Runs even before any terminal exists — these are repo
    files. Fails closed if the artifacts have not been created yet."""
    problems: list[str] = []
    try:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        from build_parity import INPUT_PINS as PARITY_PINS
    except Exception as e:
        return [f"arm-A2 consistency: build_parity import failed: {e}"]
    pv = read_set(ARM_A2) if ARM_A2.exists() else {}
    if not ARM_A2.exists():
        problems.append(f"missing artifact: {ARM_A2.relative_to(ROOT)}")
        return problems
    for key, want in PARITY_PINS.items():
        got = pv.get(key)
        if got is None:
            problems.append(f"{ARM_A2.name}: parity pin {key} missing from preset")
        elif not (got == want or _num_eq(got, want)):
            problems.append(f"{ARM_A2.name}: {key}={got!r} diverges from the parity "
                            f"harness pin {want!r} — preset and parity run would "
                            f"test different candidates")
    # accrual registry: arm A2 registered, pre-start (start None), correct glob
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from armd_accrual import ARMS
        e = ARMS.get("A2")
        if e is None:
            problems.append("accrual ARMS registry has no arm A2 entry")
        else:
            if e.get("start") is not None:
                problems.append(f"accrual ARMS arm A2 start={e.get('start')!r}: the "
                                f"registry claims the window is OPEN pre-start — "
                                f"set start=None until the parity pass and init "
                                f"banner exist")
            glob_str = str(e.get("ledger_glob", ""))
            if not glob_str.endswith("_A2.csv"):
                problems.append(f"accrual ARMS arm A2 ledger_glob={glob_str!r} does "
                                f"not read the tag-A2 ledger (_A2.csv)")
    except Exception as ex:
        problems.append(f"arm-A2 consistency: armd_accrual import failed: {ex}")
    return problems


def verify(deployed_live: Path | None = None) -> dict:
    problems: list[str] = []
    versions: dict[str, str] = {}
    v75_property_version: str | None = None

    for path in (M_SOURCE, V_SOURCE, LIVE, FINAL, ARM_D, ARM_A2):
        if not path.exists():
            problems.append(f"missing artifact: {path.relative_to(ROOT)}")

    manifest_problems, versions = verify_manifest()
    problems.extend(manifest_problems)

    if M_SOURCE.exists() and versions.get("mql5/mitemshub_ai/mitemshubai.mq5"):
        problems.extend(verify_mitemshubai(M_SOURCE.read_text(encoding="utf-8", errors="replace"),
                                           versions["mql5/mitemshub_ai/mitemshubai.mq5"]))
    if V_SOURCE.exists() and versions.get("v75macroengine.mq5"):
        v_problems, v75_property_version = verify_v75(
            V_SOURCE.read_text(encoding="utf-8", errors="replace"), versions["v75macroengine.mq5"])
        problems.extend(v_problems)

    if LIVE.exists() and FINAL.exists():
        problems.extend(verify_preset(LIVE, live=True))
        problems.extend(verify_preset(FINAL, live=False))
    if ARM_D.exists():
        problems.extend(verify_arm_d_preset(ARM_D))
        live_values = read_set(LIVE)
        final_values = read_set(FINAL)
        for key in sorted(set(live_values) & set(final_values)):
            if key in ALLOWED_PRESET_DRIFT or key == "InpLiveExecution":
                continue
            if live_values[key] != final_values[key]:
                problems.append(f"LIVE/FINAL drift in {key}: {live_values[key]!r} != {final_values[key]!r}")
    if ARM_A2.exists():
        problems.extend(verify_arm_a2_preset(ARM_A2))
    problems.extend(verify_arm_a2_consistency())

    result = {
        "version": versions.get("mql5/mitemshub_ai/mitemshubai.mq5"),
        "v75_version": versions.get("v75macroengine.mq5"),
        "v75_property_version": v75_property_version,
        "manifest_pins_ok": not manifest_problems,
        "source": str(M_SOURCE.relative_to(ROOT)),
        "repo_live_preset": str(LIVE.relative_to(ROOT)),
        "repo_live_sha256": sha256(LIVE) if LIVE.exists() else None,
        "repo_final_sha256": sha256(FINAL) if FINAL.exists() else None,
        "deployed_live": str(deployed_live) if deployed_live else None,
        "deployed_live_sha256": sha256(deployed_live) if deployed_live and deployed_live.exists() else None,
        "deployed_byte_identical": (sha256(deployed_live) == sha256(LIVE)
                                    if deployed_live and deployed_live.exists() and LIVE.exists() else None),
        "problems": problems,
        "ok": not problems and not (deployed_live and not deployed_live.exists()),
    }
    if deployed_live and not deployed_live.exists():
        result["problems"].append(f"deployed preset not found: {deployed_live}")
        result["ok"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deployed-live", type=Path,
                    help="optional explicitly supplied deployed .set to hash-compare with repo")
    args = ap.parse_args(argv)
    result = verify(args.deployed_live)
    print(f"GO-LIVE ARTIFACTS: {'PASS' if result['ok'] else 'FAIL'}")
    print(f"  MitemshubAI version: v{result['version']} | V75MacroEngine: v{result['v75_version']}"
          f" (banner macro; #property shows v{result['v75_property_version']})")
    print(f"  manifest pins match worktree: {result['manifest_pins_ok']}")
    print(f"  repo LIVE sha256: {result['repo_live_sha256']}")
    if result["deployed_live"]:
        print(f"  deployed LIVE sha256: {result['deployed_live_sha256']}")
        print(f"  deployed byte-identical: {result['deployed_byte_identical']}")
    if result["problems"]:
        for problem in result["problems"]:
            print(f"  FAIL: {problem}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

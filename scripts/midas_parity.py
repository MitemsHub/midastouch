#!/usr/bin/env python3
"""MIDASTOUCH Step 5 — build parity (protocol §8), v2 (keyed).

History: the original harness (run3, 2026-09-16) reported EA 150 vs python 147
and aligned trades positionally, which quantized SL/TP/timeout outcomes against
the WRONG partner trade after the first misalignment. Root-caused 2026-09-17:
both sides were stale vintages, not a live EA defect —
  * the frozen python artifact (midas_parity_python_wf_rd.json) reproduces only
    under the PRE-amendment-2 Wilder ATR (verified 2026-09-17: exact 147-trade
    match with M.wilder_atr); the engine of record now uses bounded SMA ATR
    (protocol amendment 2) and yields 151 trades / +1.47R on WF;
  * the harness predated the v1.04+ BAR-parity engine: it omitted InpBarModel
    and the InpWindowStart/End pins and pointed at the old install path.

v2 therefore:
  1. regenerates python R from the engine of record (scripts/midas_sweep.py
     run_mode, REVERSE_DIRECTION, WF window) — no frozen artifact dependency;
  2. pins the full BAR-parity contract on the tester pass (InpBarModel=true,
     InpWindowStart/End = python t0/t1, recorded spread file via tester_file);
  3. aligns trades by KEY (open_ct, close_ct, direction) — positional zip is
     banned; EA evidence comes from the agent sandbox ledger (OPEN/CLOSE join)
     with the appended journal "Trade R:" lines as a degraded fallback;
  4. rotates stale sandbox ledgers before the pass and pauses the paper arm's
     watchdog (scripts/.midas_watchdog_paused) so a tester session never fights
     the arm's auto-recovery; the terminal is always relaunched afterwards.

Tolerance (protocol §8, house standard): equal trade count AND max |dR| <=
0.01R per trade. Key agreement on open/close times and direction is itself
part of the verdict — a pure R match on mistimed trades is a fail.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "tests")

import mt5_tester_driver as T                       # noqa: E402
import mt5_ops as R                                 # noqa: E402  (terminal ops;
# was v28_sweep_runner, the closed indices sweep runner, kept alive only for these
# four primitives — they now resolve the LIVE install by account identity)
import midas_sweep as M                             # noqa: E402

# --- the account basis, declared once, on BOTH sides -----------------------
# A parity run claims the EA and the python engine agree on ONE account. They used to
# be funded differently and nothing said so: the tester ran at $1,000, the EA's
# paper-sizing input was pinned at $5,000 to match the research engine's own
# START_EQUITY, and the EA's prop governor defaulted to sizing off whatever balance
# the tester handed it. Lots are not lot-invariant where the min-lot floor binds, so
# those are three different trade sets wearing one result.
#
# So the basis is read from the account registry and applied to the tester deposit,
# the EA's sizing input and the python engine, and a missing declaration REFUSES
# rather than picking a number.
import mt5_terminals as _terms                          # noqa: E402

ACCOUNT_BASIS_USD = _terms.active_account_size()
T.TERMINAL_EXE = Path(R.terminal_exe())
# The tester's data root must be the SAME install the exe came from. It used to keep
# the house runner's hardcoded 49E0 folder (the Deriv-era tester), so "do the tester
# roots exist?" was answered by a directory belonging to a program that closed — the
# same wrong-install mistake the account-identity resolver exists to prevent.
_live_data = R.data_folder_for_terminal()
if _live_data:
    T.TERMINAL_DATA = Path(_live_data)
T._BASE_TESTER_INI["Symbol"] = "XAUUSD"
T._BASE_TESTER_INI["Period"] = "M15"
# Leverage affects MARGIN only, never size: sizing is risk-percent, so at 1% risk on
# this basis no lot this engine emits comes near the margin wall at 1:1000. Left as
# a pinned constant rather than guessed from the venue, whose leverage we have not
# verified (the registry records the account, not its contract terms).
T._BASE_TESTER_INI["Leverage"] = "1000"
T._BASE_TESTER_INI["Deposit"] = f"{ACCOUNT_BASIS_USD:.0f}"

# R6 preconditions, mirrored python-side (one commit with the EA's
# INIT_FAILED guards): the engine of record runs gold-only and treats the
# news-filter input as the no-protection value it honestly is. The harness
# declares what it feeds; python_build_data refuses if the declaration and
# the feed ever disagree.
R6_GOLD_ONLY = True
R6_NEWS_FILTER_OFF = True

EXPERT = r"MIDASTOUCH\MidastouchAI"    # the Upcomers install's layout, named for the
                                       # repo's own folder. It WAS
                                       # MITEMSHUB_AI\MidastouchAI -- the Deriv-era
                                       # 49E0 tester's legacy folder -- and the value
                                       # was an era assumption, not a fact: the
                                       # terminal is now resolved by account identity,
                                       # that install is gone, and this path has to
                                       # describe the install the harness will
                                       # actually launch into.

# The shadow certification path — the one at which un-deployed builds are
# certified (V2-register §2 baseline). It MUST stay distinct from EXPERT: the
# live gold charts load EXPERT, and a re-cert launched at the live path would
# swap the binary under the running §13 arms at relaunch (the 2026-09-17
# load-path hazard). Pinned distinct by tests/test_midas_parity_paths.py.
SHADOW_EXPERT = r"MIDASTOUCH_parity\MidastouchAI"

# EA enum ENUM_MIDAS_MODE (MidastouchAI.mq5 §47): registry order is fixed.
MODE_CODE = {"ORIGINAL": "0", "REVERSE_DIRECTION": "1", "REVERSE_TRIGGER": "2",
             "REVERSE_BOTH": "3", "LONG_ONLY": "4", "SHORT_ONLY": "5",
             "MACRO_ONLY": "6", "TRIGGER_ONLY": "7"}

# Certified parity windows. Each spec carries its own tester tag (separate
# INI/report namespaces — no cross-window collisions) and tester calendar
# extending PAST the research window (ToDate 00:00 truncation lesson, §11).
# The OOS calendar ends 2026.09.18 so a final-window signal can fill at
# 09-17 00:00 and time-out 720 min later; ticks end naturally at data end
# and the EA's tail flush drops an un-closed tail position exactly like the
# python engine (both engines are bounded by the same bar series).
WINDOW_SPECS = {
    # `server_offset_min` is the venue server's offset from UTC, PINNED here and
    # ASSERTED against the venue's own bars before any pass runs (see
    # `assert_server_offset`). `None` means "this window cannot be put on one clock",
    # which is a measured fact about it (below), not an omission.
    "wf":  {"tag": "midas_wf_rd",  "mode": "REVERSE_DIRECTION",
            "dates": ("2025.09.15", "2026.04.03"),
            "server_offset_min": 60},
    "oos": {"tag": "midas_oos_rd", "mode": "REVERSE_DIRECTION",
            "dates": ("2026.04.01", "2026.09.18"),
            "server_offset_min": 120},
    # THE TICK-COVERED WINDOW (added 2026-09-20), and the answer to "what does parity
    # certify on this venue?". A `Model=4` pass is only honest where the venue actually
    # serves real ticks, and measured on this venue that begins 2026-09-04: every pass
    # that reaches further back is refused by mt5_tester_driver.assert_declared_tick_model
    # (which reads MT5's partial-coverage statement against the pass's own FromDate).
    # So certification is RESTRICTED to windows the venue can serve per-tick — not
    # re-declared as a bar-replay model, because a bar replay decides intrabar order
    # (SL vs TP first) by a rule neither engine shares today, and "solving" that by
    # declaration would move the disagreement into a constant instead of removing it.
    # Short by construction: the venue's tick depth sets the length, not preference.
    "tickcov": {"tag": "midas_tickcov_rd", "mode": "REVERSE_DIRECTION",
                "dates": ("2026.09.04", "2026.09.18"),
                "server_offset_min": 120},
}
DEFAULT_WINDOW = "wf"

# --- the server clock: declared in UTC, translated at the EA boundary --------
#
# The EA evaluates its gates against BAR EPOCHS, and those epochs are the VENUE's
# server time. The python engine's are UTC. `wf` compared the two directly for its
# whole life, so every key in the comparison was off by the server's offset — a step
# that MOVES: measured from this venue's own bars, the server runs **+60 min** ahead
# of UTC in Jan–Mar 2026 and **+120 min** from April, because it follows EU DST.
#
# Both pinned windows sit wholly on one side of that step (`wf` ends 2026-03-31 → +60,
# `oos` starts 2026-04-01 → +120), which is what makes them normalisable at all. A
# window that SPANS the step has no single correct offset and is refused rather than
# mis-aligned on one side of April.
#
# Two consequences, and the second is why the pin is asserted rather than trusted:
#
#   * a window that crosses the step cannot be normalised by one number, and says so;
#   * the offset is a property of the venue, not of this file. It is re-derived from
#     the bars on every run and compared to the pin, so a restored clock changes the
#     answer instead of quietly invalidating every certificate.
#
# Direction of translation. The contract is declared ONCE, in UTC. On the way in,
# gates the EA reads as epochs (session, Friday cutoff, window pins) are shifted into
# server time. On the way out, the EA's ledger epochs are shifted back to UTC. Both
# halves are needed: fixing only the output would leave the EA trading a session two
# hours away from the one python models.
SERVER_OFFSET_CANDIDATES_MIN = (0, 60, 120, 180, -60, -120)
#: The venue's own corpus, fetched through the terminal (bar epochs in SERVER time).
VENUE_M15_SUFFIX = "_upcomers"


def _window_spec(name: str) -> dict:
    """Resolve a window spec: tester tag/dates + the python window epochs."""
    if name not in WINDOW_SPECS:
        raise SystemExit(f"unknown window '{name}' (have: {', '.join(WINDOW_SPECS)})")
    spec = WINDOW_SPECS[name]
    a, b = M.WINDOWS[name]
    return {**spec, "window_name": name, "t0": M.iso_to_ts(a), "t1": M.iso_to_ts(b)}


def _corpus_closes(path: str) -> dict[int, float]:
    """epoch -> close for one M15 corpus, or {} when the file is not there."""
    try:
        return {int(b["time"]): float(b["close"]) for b in M.load_bars(path)}
    except (OSError, KeyError, ValueError):
        return {}


def measure_server_offset_min(t0: int, t1: int) -> tuple[int | None, dict[str, int | None]]:
    """The venue server's offset from UTC over [t0, t1], MEASURED from bar closes.

    Two corpora, one market. `XAUUSD_M15.csv` is stamped in true UTC;
    `XAUUSD_M15_upcomers.csv` is the same instrument as the venue's terminal served
    it, in the venue's own clock. At the correct offset the two agree to cents; at
    the wrong one they disagree by dollars. So the offset is not read from a config
    — it is the alignment that minimises the median close disagreement, computed
    month by month because the answer is allowed to change at a DST boundary.

    Returns ``(offset_min, per_month)`` where `offset_min` is ``server − UTC``, the
    single constant offset across the window, or **None** when the window crosses a
    step. Measured on this venue: +60 in Jan–Mar 2026, +120 from April (EU DST).
    """
    utc = _corpus_closes(os.path.join(M.DATA_DIR, "XAUUSD_M15.csv"))
    venue = _corpus_closes(os.path.join(M.DATA_DIR, f"XAUUSD_M15{VENUE_M15_SUFFIX}.csv"))
    if not utc or not venue:
        raise SystemExit(
            f"cannot assert the server clock: the corpora are missing "
            f"({M.DATA_DIR}/XAUUSD_M15.csv and ...{VENUE_M15_SUFFIX}.csv). Fetch both "
            f"(scripts/midas_fetch_history.py) — a parity pass that cannot state which "
            f"clock each side is on cannot compare them.")

    acc: dict[str, dict[int, list[float]]] = {}
    for epoch, close in utc.items():
        if not (t0 <= epoch <= t1):
            continue
        month = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m")
        for off in SERVER_OFFSET_CANDIDATES_MIN:
            other = venue.get(epoch + off * 60)   # offset is server − UTC
            if other is not None:
                acc.setdefault(month, {}).setdefault(off, []).append(abs(other - close))

    per_month: dict[str, int | None] = {}
    for month, by_off in sorted(acc.items()):
        usable = {o: d for o, d in by_off.items() if len(d) >= 50}
        per_month[month] = (min(usable, key=lambda o: statistics.median(usable[o]))
                            if usable else None)
    distinct = sorted({v for v in per_month.values() if v is not None})
    if per_month and None not in per_month.values() and len(distinct) == 1:
        return distinct[0], per_month
    return None, per_month


def _fmt_offsets(per_month: dict[str, int | None]) -> str:
    return ", ".join(f"{m}:{v:+d}m" if v is not None else f"{m}:?"
                     for m, v in per_month.items())


def assert_server_offset(spec: dict) -> int:
    """The offset every epoch in this window must be normalised by, or a refusal.

    Refuses rather than guesses, in both directions: a window whose offset is not
    constant (it crosses the DST step) has no single correct answer, and a pin that
    no longer matches the venue means the venue's clock moved.
    """
    measured, per_month = measure_server_offset_min(spec["t0"], spec["t1"])
    shown = _fmt_offsets(per_month)
    if measured is None:
        raise SystemExit(
            f"window '{spec['window_name']}' cannot be put on one clock: the venue "
            f"server's offset from UTC is NOT constant across it (per month — {shown}). "
            f"It steps at the EU DST boundary (+60 before, +120 after), so normalising "
            f"the EA's epochs by one number would mis-align every key on one side of "
            f"the step while looking like a fix. Re-scope the window to one side of the "
            f"step — both certified windows already sit wholly on one side.")
    pin = spec.get("server_offset_min")
    if pin is not None and measured != pin:
        raise SystemExit(
            f"window '{spec['window_name']}' pins the server offset at {pin:+d} min, but "
            f"the venue's own bars measure {measured:+d} min (per month — {shown}). The "
            f"venue's clock moved or was restored: re-derive the pin deliberately rather "
            f"than letting a stale one re-align every key.")
    return measured


def to_utc(trades: list[dict], offset_min: int) -> list[dict]:
    """EA ledger epochs (venue SERVER time) → UTC, so both sides share one frame.

    Only the epochs move. The R, side and reason are the EA's own measurements and
    are frame-independent. A keyless trade (the degraded journal fallback) keeps its
    ``None`` timestamps: re-stamping those would invent keys that were never read.
    """
    if not offset_min:
        return trades
    delta = offset_min * 60
    out: list[dict] = []
    for t in trades:
        row = dict(t)
        for key in ("open_ct", "close_ct"):
            if row.get(key) is not None:
                row[key] = int(row[key]) - delta
        out.append(row)
    return out


def build_inputs(mode: str, t0: int, t1: int, offset_min: int = 0) -> dict:
    """The BAR-parity input contract, per window (mode + window pins vary).

    `offset_min` is the venue server's offset from UTC. The contract is DECLARED in
    UTC — the python engine's frame — and every gate the EA evaluates against a bar
    epoch is translated into the EA's own (server) frame here:

      * the session window and the Friday cutoff move by the offset, so `06:00-20:00`
        means 06:00-20:00 **UTC** on both sides instead of running as 04:00-18:00 on
        the EA's side;
      * the window pins move by the offset for the same reason.

    The default of 0 reproduces the pre-normalisation contract exactly, which is what
    the module-level `INPUTS` (the contract of record, pinned by tests) still is. The
    runner passes the asserted offset; nothing defaults to a guess.
    """
    shift_h = offset_min // 60
    return {
        "InpMagic": "7801001",
        "InpArmTag": "M1",
        "InpMode": MODE_CODE[mode],
        "InpMacroEmaPeriod": "20",
        "InpBBPeriod": "20",
        "InpBBDev": "2.0",
        "InpRSIPeriod": "14",
        "InpRSIUpper": "70.0",
        "InpRSILower": "30.0",
        "InpAtrPeriod": "14",
        "InpSlAtrMult": "2.0",
        "InpTpMult": "2.0",
        "InpTimeoutMinutes": "720",
        "InpSessionStartHour": str(6 + shift_h),         # UTC 06-20, in server time
        "InpSessionEndHour": str(20 + shift_h),
        "InpSpreadCapPctStop": "1.5",
        "InpFridayCutoffHour": str(20 + shift_h),          # UTC 20:00, in server time
        "InpUseNewsFilter": "false",
        "InpStaleMinutes": "30",
        "InpRiskPercent": "1.0",
        "InpLiveExecution": "false",
        "InpPaperEquity": f"{ACCOUNT_BASIS_USD:.1f}",  # = the python run's basis and the
                                                      # tester deposit: ONE sizing path
        # The venue gate is pinned OFF, and explicitly. This harness certifies the
        # STRATEGY engine against the research engine on the same window; the prop
        # governor is an account-level layer the python engine does not model, so
        # leaving it on compares two different rule sets and any mismatch it produced
        # would be a rule difference dressed as an engine difference. It was not
        # pinned at all before, and the EA's default is true — meaning every parity
        # run since the governor landed (2026-09-20) would have been gated by a 3%
        # daily cap on a $1,000 sandbox and could not have passed for a reason that
        # had nothing to do with parity.
        "InpPropGuard": "false",
        "InpDailyLossCapPct": "0",
        # Declared anyway, so the run records the account it was sized for even
        # though the gate is off for this pass.
        "InpPropAccountSize": f"{ACCOUNT_BASIS_USD:.1f}",
        # --- v1.04+ BAR-parity contract (the run3 harness predates these) -------
        "InpBarModel": "true",           # bar replay, recorded spreads — python's model
        "InpSpreadFile": "MIDASTOUCH_spread_M15.csv",  # bundled via tester_file
        "InpWindowStart": str(t0 + offset_min * 60),   # EA fail-closed without these:
        "InpWindowEnd": str(t1 + offset_min * 60),     # window pins, in server time
    }


# WF defaults at module level (the certified 2026-09-17 certificate window);
# other windows resolve through _window_spec() at run time.
_WF = _window_spec(DEFAULT_WINDOW)
TAG = _WF["tag"]
MODE = _WF["mode"]
T0, T1 = _WF["t0"], _WF["t1"]
DATES = _WF["dates"]
INPUTS = build_inputs(MODE, T0, T1)

TRADE_R_RE = re.compile(r"Trade R: ([+-]?\d+\.\d+)")
TOLERANCE = 0.01
GOLD_LEDGER = "MIDASTOUCH_paper_XAUUSD_M1.csv"   # the live paper arm's book


# --- EA evidence ------------------------------------------------------------

def agent_files_dirs() -> list[Path]:
    out: list[Path] = []
    for root in T._tester_roots():
        out += sorted(Path(root).glob("Agent-*/MQL5/Files"))
    return out


def rotate_sandbox_ledgers() -> list[str]:
    """One-deep rotation of any stale sandbox ledger in every agent Files dir.

    The sandbox persists across passes (a dangling OPEN would be adopted by the
    EA's own restore rule and poison the next run), so each certified pass
    starts from a clean ledger. Returns the rotated paths.
    """
    rotated = []
    for d in agent_files_dirs():
        p = d / "MIDASTOUCH_paper_XAUUSD_M1.csv"
        if p.exists():
            bak = p.with_suffix(".csv.prev")
            os.replace(p, bak)
            rotated.append(str(p))
    return rotated


def parse_ledger(path: Path) -> list[dict]:
    """OPEN/CLOSE join, keyed by ticket → open_ct/close_ct/side/reason/r."""
    opens: dict[str, dict] = {}
    trades: list[dict] = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            if row[0] == "OPEN" and len(row) >= 12:
                opens[row[2]] = {"open_ct": int(row[1]), "side": int(row[3])}
            elif row[0] == "CLOSE" and len(row) >= 7:
                o = opens.get(row[2], {})
                trades.append({"open_ct": o.get("open_ct"), "close_ct": int(row[1]),
                               "side": o.get("side"), "reason": row[3],
                               "r": float(row[5])})
    return trades


def journal_trade_rs(snaps: dict) -> list[float]:
    """All 'Trade R:' values in the appended journal bytes, in order."""
    out: list[float] = []
    for log in T.journal_paths():
        offset = snaps.get(log, 0)
        try:
            blob = log.read_bytes()[offset:].decode("utf-16-le", "ignore")
        except OSError:
            continue
        out += [float(m) for m in TRADE_R_RE.findall(blob)]
    return out


def collect_ea_evidence(snaps: dict) -> tuple[list[dict], str]:
    """Ledger first (keyed), journal 'Trade R:' lines as degraded fallback."""
    fresh = []
    for d in agent_files_dirs():
        p = d / "MIDASTOUCH_paper_XAUUSD_M1.csv"
        if p.exists():
            try:
                trades = parse_ledger(p)
            except OSError:
                continue
            if trades:
                fresh.append((p, trades))
    if fresh:
        # newest written ledger wins (agents may rotate ports)
        p, trades = max(fresh, key=lambda pt: pt[0].stat().st_mtime)
        return trades, f"ledger:{p.name}"
    rs = journal_trade_rs(snaps)
    return [{"open_ct": None, "close_ct": None, "side": None,
             "reason": "?", "r": r} for r in rs], "journal:TradeR"


# --- python engine of record ------------------------------------------------

def python_build_data() -> dict:
    """Indicator build shared by every mode's regen (done once per session).

    v1.16 R6 mirror (one-commit law with the EA): the python engine of
    record runs the SAME two fail-closed preconditions the EA enforces at
    init — news-filter input must be the no-protection value (false) and
    the symbol must be gold. The harness feeds exactly that (XAUUSD,
    InpUseNewsFilter=false), so a violation here is a harness bug and must
    refuse loudly instead of certifying an un-labeled configuration.
    """
    assert R6_NEWS_FILTER_OFF, "R6: news filter must be the no-protection value"
    assert R6_GOLD_ONLY, "R6: engine of record is gold-only by charter"
    assert T._BASE_TESTER_INI.get("Symbol", "").upper().startswith("XAU"), \
        "R6: harness must feed a gold symbol"
    assert inputs_declares_news_off()
    h1 = M.load_bars(os.path.join(M.DATA_DIR, "XAUUSD_H1.csv"))
    m15 = M.load_bars(os.path.join(M.DATA_DIR, "XAUUSD_M15.csv"))
    h4 = M.h4_series(h1)
    mc = [b["close"] for b in m15]
    return {
        "h1": h1, "m15": m15, "h4": h4,
        "h1_ct": [b["time"] + 3600 for b in h1],
        "h4_ct": [b["time"] + 14400 for b in h4],
        "h1_ema": M.ema([b["close"] for b in h1], 20),
        "h1_atr": M.sma_atr(h1),          # amendment 2: bounded ATR
        "h4_ema": M.ema([b["close"] for b in h4], 20),
        "m15_close": mc,
        "m15_rsi": M.rsi_wilder(mc),
        "m15_bb": [M.bb_touch(mc, i) for i in range(len(m15))],
    }


def python_regen(mode: str, t0: int, t1: int,
                 data: dict | None = None) -> list[dict]:
    """Run scripts/midas_sweep.py run_mode on the requested window (SMA ATR).

    Sized on the ACCOUNT basis, set here rather than at import: the research engine's
    certified default is its own $5,000 corpus basis, and a harness that mutated that
    global merely by being imported would silently re-basis every other consumer in
    the process.
    """
    M.use_basis(ACCOUNT_BASIS_USD)
    data = data or python_build_data()
    rr = M.run_mode(mode, t0, t1, data)
    return [{"open_ct": t["open_ct"], "close_ct": t["close_ct"], "side": t["side"],
             "reason": t["reason"], "r": t["r"]} for t in rr.trades]


# Short mode codes for per-run tester tags (INI/report namespaces).
TAG_MODE_CODE = {"ORIGINAL": "orig", "REVERSE_DIRECTION": "rd",
                 "REVERSE_TRIGGER": "rt", "REVERSE_BOTH": "rb",
                 "LONG_ONLY": "lo", "SHORT_ONLY": "so",
                 "MACRO_ONLY": "mo", "TRIGGER_ONLY": "to"}

SWEEP_ANCHOR = os.path.join("artifacts", "midas_sweep_20260917.json")


def sweep_anchor(mode: str, window: str) -> dict | None:
    """The frozen sweep's (n, net_r) for this mode/window, for cross-checking
    the regen against the engine of record's certified run. None if absent."""
    try:
        with open(SWEEP_ANCHOR) as fh:
            m = json.load(fh)["results"]["modes"][mode][window]
        return {"n": m.get("n"), "net_r": m.get("net_r")}
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def matrix_verdict(records: list[dict]) -> tuple[str, list[str]]:
    """Matrix PASS requires every mode PASS and every sweep anchor reproduced."""
    fails = [r["mode"] for r in records if r["cmp"]["verdict"] != "PASS"]
    anchors = [r["mode"] for r in records if not r["anchor_match"]]
    verdict = "PASS" if not (fails or anchors) else "FAIL"
    return verdict, fails + anchors


# --- keyed comparison (pure; unit-tested) ------------------------------------

def keyed_compare(ea: list[dict], py: list[dict], tol: float = TOLERANCE) -> dict:
    """Align trades positionally ONLY after proving the keys agree 1:1.

    A positional zip is illegal evidence: after one misalignment every later
    |dR| is quantization noise against the wrong partner trade (run3's lesson).
    The verdict requires count equality AND key agreement AND max |dR| <= tol.
    """
    n = min(len(ea), len(py))
    pairs = list(zip(ea[:n], py[:n]))
    open_bad = [i for i, (a, b) in enumerate(pairs) if a["open_ct"] != b["open_ct"]]
    close_bad = [i for i, (a, b) in enumerate(pairs) if a["close_ct"] != b["close_ct"]]
    side_bad = [i for i, (a, b) in enumerate(pairs) if a["side"] != b["side"]]
    diffs = [abs(a["r"] - b["r"]) for a, b in pairs]
    max_d = max(diffs) if diffs else None
    over = [i for i, d in enumerate(diffs) if d > tol]
    keys_ok = not (open_bad or close_bad or side_bad)
    count_match = len(ea) == len(py)
    degraded = any(a["open_ct"] is None for a in ea[:n])
    verdict = ("PASS" if count_match and keys_ok and not degraded
               and max_d is not None and max_d <= tol else "FAIL")
    return {
        "count_match": count_match,
        "open_ct_mismatches": open_bad[:20],
        "close_ct_mismatches": close_bad[:20],
        "side_mismatches": side_bad[:20],
        "degraded_keyless_source": degraded,
        "max_abs_dR": max_d,
        "trades_over_tol": over[:20],
        "n_over_tol": len(over),
        "verdict": verdict,
    }


# --- the recorded verdict (pure; unit-tested) ---------------------------------

def recorded_verdict(cmp: dict, tick_model: dict | None = None) -> tuple[str, str]:
    """The verdict that may be RECORDED, once the tick model has had its say.

    A PASS is only recordable on the ticks the pass declared. The driver already
    refuses a downgraded pass outright (mt5_tester_driver.assert_declared_tick_model,
    which now reads MT5's partial-coverage statement against the pass's own FromDate),
    so this is the belt to that braces: if that refusal is ever refactored away, the
    artifact still cannot carry a PASS measured on generated ticks. The comparison's
    verdict is demoted, never promoted — keys agreeing is not a licence to record a
    pass whose intrabar path nobody traded.

    Returns (verdict, refusal_reason); the reason is "" unless a PASS was demoted.
    """
    if cmp["verdict"] != "PASS":
        return cmp["verdict"], ""
    ticks = dict(tick_model or {})
    if ticks.get("used") == "real":
        return "PASS", ""
    return "REFUSED", (
        f"keys and R agreed, but the pass declared Model={ticks.get('declared', '?')} and "
        f"ran on {ticks.get('used') or 'unstated'} ticks "
        f"({ticks.get('evidence') or 'no tick-model statement'})")


# --- main --------------------------------------------------------------------

def _should_relaunch_terminal(stopped: bool, ran_passes: bool) -> bool:
    """The finally-block relaunch guard (2026-09-17 latent-hazard fix).

    The harness relaunches the terminal after a session because a pass
    REQUIRES stopping it first. When the flat-check gate aborts BEFORE any
    stop (live arm holding a position — the §13-protecting gate doing its
    job), the terminal is still running and must be left alone: an
    unconditional relaunch would bounce a healthy terminal mid-window.
    """
    return stopped or ran_passes


def inputs_declares_news_off() -> bool:
    """The EA input block the harness builds must carry the R6 value."""
    return str(build_inputs("ORIGINAL", 0, 1)["InpUseNewsFilter"]).lower() == "false"


def run_one_mode(mode: str, spec: dict, window_name: str, data: dict,
                 expert: str = EXPERT) -> dict:
    """One certified tester pass + keyed comparison for a single mode.

    `expert` names the binary path under MQL5\\Experts the pass runs. The
    default is the DEPLOYED path (the certified v1.10 re-cert semantics);
    --expert-path overrides it for shadow-path certification of an
    un-deployed build (V2-register baseline) without ever touching the
    live charts' load path.

    V2 register §1 awareness: the comparison is version-agnostic BY LAW —
    keys (open/close ct, side) + per-trade |dR| tolerance, never an APP
    VERSION pin. A telemetry-only build (cited per §1, e.g. v1.13's R10
    columns) changes no trade and no R, so it passes identically; live-verified
    2026-09-18 when the v1.15 shadow certified PASS at max|dR| 0.0005. Pinned
    version-agnostic by tests/test_midas_parity.py
    (TestVersionAwareness).
    """
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    # One clock — asserted BEFORE anything is stopped or run, so an un-normalisable
    # window costs a refusal instead of a stopped terminal and a mis-aligned result.
    offset_min = assert_server_offset(spec)
    tag = f"{spec['tag']}_{TAG_MODE_CODE[mode]}"
    inputs = build_inputs(mode, t0, t1, offset_min=offset_min)
    rotated = rotate_sandbox_ledgers()
    if rotated:
        print(f"  rotated stale sandbox ledgers: {rotated}")
    snaps = T.journal_snapshots()
    print(f"  pass tag={tag} mode={mode} — server clock {offset_min:+d} min, contract "
          f"declared in UTC (real ticks required; be patient)", flush=True)
    res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert)
    # Which ticks the pass ACTUALLY ran on, carried into the comparison and the
    # artifact: a parity number is only evidence next to the tick model that produced
    # it (2026-09-20: the oos pass declared real ticks and ran five months generated).
    ticks = dict(res.get("tick_model") or {})
    print(f"    tick model: {str(ticks.get('used', 'unknown')).upper()} — "
          f"{ticks.get('evidence', 'no tick-model statement in this pass')}", flush=True)
    time.sleep(10)                   # agent flushes journal + ledger after report
    ea, source = collect_ea_evidence(snaps)
    ea = to_utc(ea, offset_min)      # EA ledger epochs are venue server time
    py = python_regen(mode, t0, t1, data)
    cmp = keyed_compare(ea, py)
    verdict, refused_for = recorded_verdict(cmp, ticks)
    if refused_for:
        cmp = {**cmp, "verdict": verdict, "refused_for": refused_for}
    anchor = sweep_anchor(mode, window_name)
    anchor_match = (anchor is not None and anchor["n"] == len(py)
                    and abs((anchor["net_r"] or 0) - sum(t["r"] for t in py)) < 5e-4)
    print("  " + "-" * 66)
    print(f"  {mode:<20} py {len(py):>3}tr {sum(t['r'] for t in py):+8.3f}R | "
          f"EA {len(ea):>3}tr {sum(t['r'] for t in ea):+8.3f}R | "
          f"max|dR| {cmp['max_abs_dR']:.5f} | keys "
          f"{'OK' if not (cmp['open_ct_mismatches'] or cmp['close_ct_mismatches'] or cmp['side_mismatches']) else 'MISMATCH'} | "
          f"anchor {'reproduced' if anchor_match else ('NO-ANCHOR' if anchor is None else 'MISMATCH')} | "
          f"{cmp['verdict']}")
    if cmp.get("refused_for"):
        print(f"    REFUSED: {cmp['refused_for']}")
    if cmp["verdict"] != "PASS":
        for i in cmp["trades_over_tol"][:10]:
            a, b = ea[i], py[i]
            print(f"    trade {i}: ea {a['r']:+.4f} (ct={a['close_ct']}) vs "
                  f"py {b['r']:+.4f} (ct={b['close_ct']}) dR {a['r'] - b['r']:+.4f}")
        for name in ("open_ct_mismatches", "close_ct_mismatches", "side_mismatches"):
            if cmp[name]:
                print(f"    {name}: {cmp[name]}")
    return {"mode": mode, "tag": tag, "evidence_source": source,
            "server_offset_min": offset_min, "tick_model": ticks,
            "anchor": anchor, "anchor_match": anchor_match, "cmp": cmp,
            "python": {"n": len(py), "sum_r": round(sum(t["r"] for t in py), 4), "trades": py},
            "ea": {"n": len(ea), "sum_r": round(sum(t["r"] for t in ea), 4), "trades": ea}}


def preflight(expert: str) -> tuple[list[str], list[str]]:
    """Everything a parity pass needs on disk, checked BEFORE the terminal is touched.

    Why this exists: the harness stops the live terminal, runs a tester pass that can
    take the better part of an hour, and only then discovers the EA is not there — the
    failure mode its own comment documents as ex5-not-found. On the Upcomers install
    nothing is deployed at all, so every one of these checks would fail and the run
    could not have produced a single number while looking like it tried.

    Returns (blockers, notes). Blockers stop the pass; notes are things the pass itself
    creates (the tester root does not exist until the first pass runs, so treating it as
    a blocker would make the first run permanently impossible — which is the mistake the
    first version of this function made).
    """
    problems: list[str] = []
    notes: list[str] = []
    reg_basis = _terms.active_account_size()
    if reg_basis != ACCOUNT_BASIS_USD:
        problems.append(f"basis disagreement: registry {reg_basis:.0f} vs harness "
                        f"{ACCOUNT_BASIS_USD:.0f} — one account, one number")
    data_folder = R.data_folder_for_terminal()
    if not data_folder:
        problems.append("no terminal resolves for the active account, so the deployed "
                        "EA and the tester tree cannot be inspected")
        return problems, notes
    mql5 = Path(data_folder) / "MQL5"
    ex5 = mql5 / "Experts" / f"{expert}.ex5"
    if not ex5.exists():
        problems.append(
            f"no EA binary at {ex5}\n"
            f"      -> parity certifies a BUILD, so the build must be deployed to the "
            f"install being tested. Compile with scripts/compile_midas.py, then copy "
            f"the .ex5 into MQL5/Experts/{Path(expert).parent}/ of that install. "
            f"Deploying the binary is not arming: no chart is attached and no order "
            f"path is opened by it.")
    spread = mql5 / "Files" / "MIDASTOUCH_spread_M15.csv"
    if not spread.exists():
        problems.append(f"no recorded spread file at {spread} — the BAR-parity pass "
                        f"reads its spreads from there, and without it the EA would "
                        f"be certified on a different cost model than python's")
    # Can the pass write its /config INI at all? Asked HERE because the harness stops
    # the live terminal before running a pass, so discovering mid-session that the
    # install folder is read-only (C:\Program Files\MetaTrader 5 — what the first live
    # attempt hit, 2026-09-20) costs a stopped terminal and up to a 3600 s wait for
    # something knowable in advance. Same reason the ex5 check above exists.
    try:
        probe = T.write_config_ini("midas_parity_write_probe.ini", "[Tester]\n")
        probe.unlink(missing_ok=True)
    except (OSError, RuntimeError) as exc:
        problems.append(f"no writable /config INI location for the tester pass: {exc}")
    roots = [p for p in T._tester_roots() if Path(p).is_dir()]
    if not roots:
        notes.append(
            "no tester root under %APPDATA%/MetaQuotes/Tester/<install> yet — no tester "
            "pass has run on this install; this pass creates it")
    return problems, notes


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MIDAS keyed parity harness (protocol §11/§8)")
    ap.add_argument("--window", default=DEFAULT_WINDOW, choices=sorted(WINDOW_SPECS),
                    help="research window of record (default: wf)")
    ap.add_argument("--mode", action="append", dest="modes",
                    help="registry mode to certify (repeatable); default: the window spec's mode")
    ap.add_argument("--expert-path", default=EXPERT, dest="expert_path",
                    help="EA path under MQL5\\Experts for the tester pass "
                         "(default: the deployed binary — the certified target; "
                         "pass a shadow path to certify an un-deployed build)")
    args = ap.parse_args()
    expert = args.expert_path
    if expert != EXPERT:
        print(f"SHADOW-PATH certification: expert={expert} — the live charts' "
              f"load path ({EXPERT}) is NOT touched by this run")
    spec = _window_spec(args.window)
    problems, notes = preflight(expert)
    for n in notes:
        print(f"note: {n}")
    if problems:
        print(f"ABORT: the parity pass cannot start ({len(problems)} precondition(s) "
              f"unmet). Nothing was stopped and nothing was run:\n")
        for p in problems:
            print(f"  - {p}")
        return 5
    print(f"preflight OK — basis ${ACCOUNT_BASIS_USD:,.0f}, expert {expert}, "
          f"window {spec['window_name']}")
    modes = args.modes or [spec["mode"]]
    for m in modes:
        if m not in MODE_CODE:
            raise SystemExit(f"unknown mode '{m}' (registry: {', '.join(MODE_CODE)})")
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    matrix_run = len(modes) > 1

    # the paper arm's watchdog must not restart the terminal mid-tester-pass
    marker = os.path.join(REPO_MARK_DIR(), ".midas_watchdog_paused")
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    paused_by_us = not os.path.exists(marker)
    if paused_by_us:
        open(marker, "w").write(datetime.now(timezone.utc).isoformat() + "\n")
        print("watchdog paused for the parity session")
    stopped = False       # did THIS session stop the terminal?
    ran_passes = False    # did THIS session run tester passes?

    try:
        # flat-check gate (v28_sweep_runner discipline): the paper arm's EA
        # adopts a dangling OPEN as a live virtual position, so a tester
        # session never stops its host with an open paper trade.
        # Every gold paper book on the terminal gates the stop. The inventory used to
        # also carry the V75 arms; that program is closed, so no book of its remains.
        data_folder = R.data_folder_for_terminal()
        arms = R.inventory_arms(data_folder)
        flat, bad = R.verify_all_flat(arms)
        gold = None
        if data_folder:
            gpath = os.path.join(data_folder, "MQL5", "Files", GOLD_LEDGER)
            if os.path.exists(gpath):
                gold = R.ledger_flatness(gpath)
                flat = flat and gold["flat"]
        else:
            flat = False
            bad.append({"name": "terminal-data-folder", "problem": "unresolvable — gold ledger unverifiable"})
        if gold is not None:
            print(f"gold ledger flat-check: flat={gold['flat']} rows={gold['rows']} open={len(gold['open_positions'])}")
        if not flat:
            print("ABORT: paper ledger(s) not flat — refusing to stop the terminal:")
            for b in bad:
                print(" ", b)
            return 4
        print(f"flat-check OK ({len(arms)} gold arm book(s) on the terminal; legacy "
              f"gold ledger {'checked' if gold else 'absent'})")

        pids = R.terminal_pids_exact()
        if pids:
            print(f"terminal running (pids {pids}) — stopping first")
            stopped = R.stop_terminal(pids)
            if not stopped:
                print("ABORT: terminal did not stop cleanly — refusing to run passes "
                      "against an unverified terminal state")
                return 4

        if M.selftest() != 0:
            print("python engine selftest FAILED — refusing to certify")
            return 3
        data = python_build_data()

        print(f"parity session: window={args.window} tester_dates={dates} "
              f"modes={','.join(modes)} expert={expert}")
        records = [run_one_mode(m, spec, args.window, data, expert=expert)
                   for m in modes]
        ran_passes = True

        if matrix_run:
            verdict, why = matrix_verdict(records)
            print("=" * 70)
            print(f"MATRIX ({args.window}, {len(modes)} modes): {verdict}")
            if why:
                print("  failing:", ", ".join(why))
            out = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "harness": "midas_parity.py v2 (keyed, matrix)",
                "expert": expert, "window": {"t0": t0, "t1": t1, "name": args.window},
                "tester_dates": dates, "symbol": "XAUUSD",
                "modes": records, "matrix_verdict": verdict,
                "matrix_failing": why,
            }
            path = f"artifacts/midas_parity_matrix_{args.window}_{datetime.now():%Y%m%d_%H%M}.json"
            with open(path, "w") as fh:
                json.dump(out, fh, indent=1)
            print("artifact:", path)
            rc = 0 if verdict == "PASS" else 1
        else:
            rec = records[0]
            cmp = rec["cmp"]
            print("=" * 70)
            print(f"python ({rec['mode']}, SMA-ATR era): {len(rec['python']['trades'])} trades "
                  f"sumR {rec['python']['sum_r']:+.3f}")
            print(f"EA BAR ledger ({rec['evidence_source']}): {len(rec['ea']['trades'])} trades "
                  f"sumR {rec['ea']['sum_r']:+.3f}")
            print(f"count match:        {cmp['count_match']}")
            print(f"open_ct agreement:  {not cmp['open_ct_mismatches']}")
            print(f"close_ct agreement: {not cmp['close_ct_mismatches']}")
            print(f"side agreement:     {not cmp['side_mismatches']}")
            print(f"max |dR|:           {cmp['max_abs_dR']}")
            print(f"over tolerance:     {cmp['n_over_tol']}")
            print(f"tick model used:    {rec.get('tick_model', {}).get('used')} "
                  f"({rec.get('tick_model', {}).get('evidence')})")
            if cmp.get("refused_for"):
                print(f"refused for:        {cmp['refused_for']}")
            print(f"PARITY:             {cmp['verdict']}")
            out = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "harness": "midas_parity.py v2 (keyed)",
                "expert": expert, "tag": rec["tag"], "mode": rec["mode"],
                "window": {"t0": t0, "t1": t1, "name": args.window},
                "tester_dates": dates, "symbol": "XAUUSD",
                "server_offset_min": rec["server_offset_min"],
                "inputs": build_inputs(rec["mode"], t0, t1,
                                       offset_min=rec["server_offset_min"]),
                "evidence_source": rec["evidence_source"],
                "tick_model": rec.get("tick_model", {}),
                "python": rec["python"], "ea": rec["ea"],
                **cmp,
            }
            path = f"artifacts/midas_parity_result_{datetime.now():%Y%m%d_%H%M}.json"
            with open(path, "w") as fh:
                json.dump(out, fh, indent=1)
            print("artifact:", path)
            rc = 0 if cmp["verdict"] == "PASS" else 1
    finally:
        if paused_by_us:
            os.remove(marker)
            print("watchdog resumed")
        if _should_relaunch_terminal(stopped, ran_passes):
            R.relaunch_terminal()
            print("terminal relaunched")
        else:
            print("terminal untouched (gate aborted before any stop)")
    return rc


def REPO_MARK_DIR() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


if __name__ == "__main__":
    sys.exit(main())

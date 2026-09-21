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
from collections import Counter
import os
import re
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "tests")
# src/ as well: the news veto is `midas_prop.risk.news_calendar`'s rule, and this harness
# arms the engine of record with it directly (`news_events_for_pass`). The suite gets this
# from tests/conftest.py, but the CLI does not — and the failure is a bare
# ModuleNotFoundError before anything is stopped, which is at least the cheap direction.
sys.path.insert(0, "src")

import mt5_tester_driver as T                       # noqa: E402
import mt5_ops as R                                 # noqa: E402  (terminal ops;
# was v28_sweep_runner, the closed indices sweep runner, kept alive only for these
# four primitives — they now resolve the LIVE install by account identity)
import midas_sweep as M                             # noqa: E402
from midas_prop.risk import news_calendar as NC     # noqa: E402  (the one news rule)

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
#: The certified contract declares the gate OFF, and a pass that does not say otherwise
#: gets exactly that. It is no longer the ONLY admissible stance — it was, while the
#: python engine of record could not see the rule and a BAR pass with the gate on would
#: have named a protection that could not act. The engine of record applies the same veto
#: now, so the invariant is no longer "never on" but "never on for one engine only".
R6_NEWS_FILTER_OFF = True
R6_NEWS_MIRRORED = True

#: One file, both engines. The EA reads `InpNewsFile` out of the terminal's MQL5\Files
#: (the tester mirrors that folder read-only into the agent's sandbox), and the python side
#: reads the same path here — a pass whose two sides read different calendars would be
#: comparing two rules while reporting one.
#: The EA's recorded-spread series. It is `#property tester_file` in the EA, so the tester
#: copies it out of <data>\MQL5\Files into the agent's sandbox, and it does TWO jobs that
#: make its PROVENANCE part of the parity contract rather than a file that merely exists:
#:
#:   * it IS the cost model — the half-spread charged at every fill and at every exit;
#:   * it IS the BAR-mode membership filter — the EA's `SpreadAt()` returns 0.0 for a bar
#:     the file does not hold, and the BAR fill path skips those bars.
#:
#: Measured 2026-09-21 on the tickcov window: the staged file still held the LEGACY
#: series' spreads (a flat $0.15) while the python leg charged the VENUE series' recorded
#: spread ($0.42) on the same bars. That is a $0.135 half-spread difference per side — not
#: rounding: it put a long's stop $0.136 further from its fill and moved that stop's touch
#: by 105 minutes, and it pushed a TIMEOUT trade to |dR| 0.0102, over tolerance. The only
#: check that ever ran on this file asked whether it EXISTED. It is now derived from the
#: corpus of record on every pass, and a file that is not that corpus is refused.
SPREAD_FILE = "MIDASTOUCH_spread_M15.csv"

NEWS_FILE = "MIDASTOUCH_news_calendar.csv"
NEWS_WINDOW_MIN = 15      # MUST equal the EA's InpNewsWindowMin
NEWS_MAX_AGE_HOURS = 24   # MUST equal the EA's InpNewsMaxAgeHours
NEWS_COVER_HOURS = 24     # MUST equal the EA's InpNewsCoverHours

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
    # `corpus: frozen` — the only two windows that cannot be walked on the venue's own bars:
    # `wf` opens 119 days before the venue's history (measured: first M15 bar 2026-01-12), and
    # `oos` is a certification-intent declaration whose `Model=4` cannot run anywhere before
    # 2026-09-04. Both are therefore stated against the retired research series rather than left
    # undeclared, so running one refuses instead of quietly picking a market. That series was
    # DELETED on 2026-09-21 (docs/FROZEN_CORPUS_20260921.md §4), so these two windows are now
    # unrunnable without restoring it — which is the intended state, not a fault. Their
    # runnable replacements are `wfv` and `oosc`, both on the venue's own bars.
    "wf":  {"tag": "midas_wf_rd",  "mode": "REVERSE_DIRECTION",
            "dates": ("2025.09.15", "2026.04.03"),
            "server_offset_min": 60, "corpus": "frozen"},
    # THE VENUE-COVERED REMAINDER OF THE `wf` ERA (added 2026-09-21). `wf` spans
    # 2025-09-15..2026-03-31, and the venue's own history BEGINS 2026-01-12 — read from this
    # terminal, not assumed: first M15 bar 2026-01-12 11:15 UTC, H1 11:00, H4 10:00. So
    # 7,752 of `wf`'s bars exist ONLY in the legacy file, there is no EA side to compare
    # against in that span, and the harness refuses `wf` outright rather than comparing two
    # markets (measured at +60: 7,752 bars only in legacy, 24 only in the venue's).
    #
    # This is the largest sub-span of that era BOTH engines can be walked through: wholly
    # inside the venue's history, and wholly on one side of the April DST step that makes
    # any longer window un-clockable (measured per month: Jan +60, Feb +60, Mar +60, April
    # `None`). It is a COMPARISON window, not a new certification — see `oosc` below for why
    # it must declare `Model=1`, and for what that costs it.
    "wfv": {"tag": "midas_wfv_rd", "mode": "REVERSE_DIRECTION",
            "dates": ("2026.01.12", "2026.04.02"),
            "server_offset_min": 60, "corpus": "venue", "model": "1",
            "iso": ("2026-01-12T00:00", "2026-03-31T23:59")},
    # THE LONG WINDOWS, COMPARED ON THE TICK MODEL THEY CAN ACTUALLY RUN (added 2026-09-21).
    # Measured, and it is the reason this window exists as a separate declaration instead of
    # an edit to `oos`: run as declared (`Model=4`), the oos pass ABORTS at
    # `assert_declared_tick_model` — "declared Model=4 (every tick based on real ticks) but
    # ran on GENERATED ticks ... real ticks begin from 2026.09.04, but the window starts
    # 2026.04.01 — 156 day(s) of it ran on generated ticks". Every window that reaches
    # further back than 2026-09-04 has that property, so the choice is to declare the model
    # the pass will really use and let the verdict be refused, or to have no long-window
    # evidence at all. This declares it: `Model=1` is a deliberate re-declaration of the same
    # span, `recorded_verdict` demotes any key-matched PASS here to REFUSED, and the window's
    # only product is the key-by-key comparison — which is what the engines' agreement is
    # measured on. It can never become a certificate, by construction.
    "oosc": {"tag": "midas_oosc_rd", "mode": "REVERSE_DIRECTION",
             "dates": ("2026.04.01", "2026.09.18"),
             "server_offset_min": 120, "corpus": "venue", "model": "1",
             "iso": ("2026-04-01T00:00", "2026-09-16T23:59")},
    "oos": {"tag": "midas_oos_rd", "mode": "REVERSE_DIRECTION",
            "dates": ("2026.04.01", "2026.09.18"),
            "server_offset_min": 120, "corpus": "frozen"},
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
    # `corpus: venue` because a legacy pass here is refused: the two corpora disagree about
    # 21 bars in this window, and this is the window the parity contract lives or dies on.
    "tickcov": {"tag": "midas_tickcov_rd", "mode": "REVERSE_DIRECTION",
                "dates": ("2026.09.04", "2026.09.18"),
                "server_offset_min": 120, "corpus": "venue"},
    # THE VETOED PATH (added 2026-09-21). The tick-covered window contains NO entry the
    # news stand-down removes — the engine of record's own census over 2026-09-04..09-16 is
    # zero vetoes — so a pass there compares the no-op case and nothing else. The entries it
    # does remove are 2026-05-12 20:00, 2026-05-14 19:45, 2026-06-11 20:00, 2026-06-12
    # 13:15 and 2026-06-17 20:00 UTC, and this window covers the first two.
    #
    # `model: "1"` IS A DELIBERATE RE-DECLARATION, not a convenience. The venue's real
    # ticks begin 2026-09-04, so a May pass declaring Model=4 is downgraded to generated
    # ticks and refused by `mt5_tester_driver.assert_declared_tick_model` — correctly, since
    # this program's certification model is per-tick. What this window is FOR is the
    # bar-level question "do both engines refuse the same entry?", which needs no intrabar
    # ordering; and `recorded_verdict` demotes any key-matched PASS on non-real ticks to
    # REFUSED, so a pass here can never be recorded as a certificate.
    #
    # The tester dates are SERVER dates and must CONTAIN the UTC window on both sides, or
    # the EA is scored on a shorter window than python's and any missing trade at the end is
    # the calendar's fault, not the engine's. t1 = 2026-05-16 23:59 UTC is 2026-05-17 01:59
    # server, so ToDate is the 18th.
    "veto": {"tag": "midas_veto_rd", "mode": "REVERSE_DIRECTION",
             "iso": ("2026-05-11T00:00", "2026-05-16T23:59"),
             "dates": ("2026.05.11", "2026.05.18"),
             "server_offset_min": 120, "model": "1", "corpus": "venue"},
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
#: Where the venue server's offset from UTC is RECORDED, per era, with its evidence. The
#: venue's own bars cannot supply it and the UTC-stamped research series that used to is
#: retired, so this is the harness's one clock reference — see `measure_server_offset_min`.
SERVER_OFFSET_MANIFEST = os.path.join("configs", "mt5", "server_offsets.json")
#: The venue's own corpus, fetched through the terminal (bar epochs in SERVER time).
VENUE_M15_SUFFIX = "_upcomers"


def _window_spec(name: str) -> dict:
    """Resolve a window spec: tester tag/dates + the python window epochs."""
    if name not in WINDOW_SPECS:
        raise SystemExit(f"unknown window '{name}' (have: {', '.join(WINDOW_SPECS)})")
    spec = WINDOW_SPECS[name]
    # A window may carry its own bounds, which is how one can be added WITHOUT touching
    # `midas_sweep.WINDOWS`: that dict drives the sweep artifact and its G6 window count,
    # so appending to it would silently change a certified verdict's arithmetic.
    a, b = spec.get("iso") or M.WINDOWS[name]
    return {**spec, "window_name": name, "t0": M.iso_to_ts(a), "t1": M.iso_to_ts(b)}


def _audit_line(audit: dict) -> str:
    """How the cross-market audit reads, including when there is nothing to audit against."""
    if not audit.get("frozen_available"):
        return ("research series not present (deleted 2026-09-21) — no cross-market audit "
                "available; it is not a market, and no default may use it: see "
                "docs/FROZEN_CORPUS_20260921.md and configs/frozen_corpus.json")
    return (f"{audit['only_python']} bar(s) only in the frozen research series, "
            f"{audit['only_venue']} only in the venue's own")


def venue_bars_utc(stem: str, offset_min: int) -> list[dict]:
    """The VENUE's own series for `stem` ('XAUUSD_M15'), shifted from server time to UTC.

    THE DATA OF RECORD, AND IT IS NOT THE FILE THIS HARNESS ALWAYS READ. Until 2026-09-21
    `python_build_data` read `XAUUSD_M15.csv` — a separately fetched 50,000-bar series —
    while the tester ran the EA on the terminal's own history. Those are two different
    markets, and measured inside the tick-covered window they disagree by more than
    rounding: at the correct offset the venue series holds 18 bars the python one does not
    (2026-09-04 20:45, 09-07 and 09-16 22:00-23:45, 09-11 20:45 UTC) and lacks 3 it does
    (09-07 17:45-18:15).

    That is where the first divergent trade closed. Python's series stops at 18:15 and
    resumes at 00:00, so a 12-hour timeout opened at 08:45 could only fire at 00:15; the EA
    holds the venue's bars, which include 22:00, so the same timeout fired at 22:15. A
    7,200 s gap — exactly the venue's +120 min offset, which is why it read as a clock
    fault while the entry agreed to the second. On the venue series the same window gives
    6 of 9 keys matching instead of 2.
    """
    path = os.path.join(M.DATA_DIR, f"{stem}{VENUE_M15_SUFFIX}.csv")
    if not os.path.isfile(path):
        raise SystemExit(f"no venue series at {path} — fetch it (scripts/midas_fetch_history.py). "
                         f"A parity leg without the venue's own bars compares two markets.")
    shift = offset_min * 60
    return [{**b, "time": b["time"] - shift} for b in M.load_bars(path)]


def _frozen_bar_times() -> tuple[set[int], bool]:
    """The RETIRED corpus's bar epochs, or (empty, False) when the archive is not restored.

    The archive is OPTIONAL here on purpose: this audit exists to show how far the retired
    series and the venue's own differ, and a checkout that has not restored it can still run
    every venue-corpus window. What it must never do is read it as if it were the data of
    record — `M.frozen_bars` is the only reader and it verifies the pinned hash — so this asks
    that loader and treats its refusal as "archive not present" instead of failing the pass.
    """
    try:
        return {int(b["time"]) for b in M.frozen_bars("XAUUSD_M15")}, True
    except SystemExit:
        return set(), False


def corpus_alignment(offset_min: int, t0: int, t1: int) -> dict:
    """Which bars the two corpora disagree about inside [t0, t1] — an audit, not a guess.

    Non-zero is not a rounding error: it means the EA and the engine of record were walked
    through different markets, so every key compared between them is confounded by bars one
    side never saw. Measured rather than assumed, and refused by `run_one_mode` unless the
    python leg is on the venue's own series.
    """
    python_side, frozen_ok = _frozen_bar_times()
    venue_side = {int(b["time"]) for b in venue_bars_utc("XAUUSD_M15", offset_min)}
    a = {t for t in python_side if t0 <= t <= t1}
    b = {t for t in venue_side if t0 <= t <= t1}
    return {"offset_min": offset_min, "t0": t0, "t1": t1,
            "python_bars": len(a), "venue_bars": len(b),
            "frozen_available": frozen_ok,
            "only_python": len(a - b), "only_venue": len(b - a)}


def gold_break_utc_hour(day: date) -> int:
    """The UTC hour gold's daily maintenance break STARTS on `day`.

    The break is 17:00-18:00 **US Eastern**, so its UTC hour moves with US DST — 21:00 UTC
    under EDT (2nd Sunday of March -> 1st Sunday of November) and 22:00 UTC under EST. This is
    the one outside fact the break position needs, and it is exactly why that position cannot
    be read as the offset directly: this venue's server changes offset on the EU calendar,
    three weeks away from the US one, and between them the two shifts CANCEL. Measured: the
    break sits at server 23:00 in every month of 2026 while the offset underneath it moves
    from +60 to +120 — a break-based estimate reported +120 for January, a full hour wrong,
    and wrong in a way that reads as a clean measurement.

    So this function is the VERIFIER, not the source: `measure_server_offset_min` pins each
    era in configs/mt5/server_offsets.json and refuses when a month's break evidence is
    unanimous and disagrees with the pin. Months whose gaps are not a clean single hour —
    2026-01-13..16 and 2026-03-11..27 carry TWO-hour gaps, and 03-09/10 imply a different
    offset from the rest of their month — are simply not evidence, and the manifest records
    that instead of smoothing it over.
    """
    mar = date(day.year, 3, 1)
    nov = date(day.year, 11, 1)
    mar += timedelta(days=(6 - mar.weekday()) % 7 + 7)      # 2nd Sunday of March
    nov += timedelta(days=(6 - nov.weekday()) % 7)          # 1st Sunday of November
    return 21 if mar <= day < nov else 22


#: The era table and its lookup live in `midas_sweep`, beside the corpus paths: "what clock is
#: this epoch on" is data-of-record metadata, and a second copy of the DST rules here would be
#: a second source of truth for a frame. This module READS them, it does not redefine them.
SERVER_OFFSET_MANIFEST = M.SERVER_OFFSET_MANIFEST


def measure_server_offset_min(t0: int, t1: int) -> tuple[int | None, dict[str, int | None]]:
    """The venue server's offset from UTC over [t0, t1], from the recorded eras.

    THE CLOCK STOPPED BEING DERIVED FROM THE RETIRED SERIES. Until 2026-09-21 this compared
    the venue's series against `XAUUSD_M15.csv` — a separately fetched, true-UTC series — and
    took the alignment that minimised the median close disagreement. That measurement was
    sound and its answers are preserved here verbatim, but it made the harness's clock depend
    on the duplicate corpus this program retired: a second market series that exists to answer
    "what time is it" is a second source of truth by construction.

    The venue's own bars cannot take its place — that was tried, measured and retired the same
    day (see `gold_break_utc_hour`, which survives as the VERIFIER below rather than the
    source). So the pins live in `configs/mt5/server_offsets.json`, each with the measurement
    that produced it and the forward validation that confirms it, and the venue's own break
    position is used to CHECK them: a month whose break evidence is unanimous must agree with
    the pin, and one that disagrees is a refusal, not a warning.

    Still computed month by month, because the answer is allowed to change at a DST boundary,
    and a month the manifest cannot resolve to one era (a step inside it) is None — which is
    what makes a window crossing the step un-clockable rather than mis-clockable. Returns
    ``(offset_min, per_month)`` with `offset_min` in MINUTES, ``server − UTC``.
    """
    manifest = M.server_offset_manifest()
    path = os.path.join(M.DATA_DIR, f"XAUUSD_M15{VENUE_M15_SUFFIX}.csv")
    bars = M.load_bars(path) if os.path.isfile(path) else []
    if not bars:
        raise SystemExit(
            f"cannot assert the server clock: the venue's own series is missing ({path}). "
            f"Fetch it (scripts/midas_fetch_history.py) — a parity pass that cannot state "
            f"which clock the venue is on cannot normalise the EA's epochs.")
    hours: dict[str, dict[date, set[int]]] = {}
    for b in bars:
        if not (t0 <= b["time"] <= t1):
            continue
        at = datetime.fromtimestamp(int(b["time"]), timezone.utc)
        hours.setdefault(at.strftime("%Y-%m"), {}).setdefault(at.date(), set()).add(at.hour)
    per_month: dict[str, int | None] = {}
    for month, days in sorted(hours.items()):
        pinned = M.server_offset_for_month(month, manifest)
        # THE VERIFIER: the venue's own break position, where it is unambiguous.
        full = [d for d, covered in days.items() if d.weekday() < 5 and len(covered) >= 20]
        implied: Counter[int] = Counter()
        for d in full:
            miss = [h for h in range(24) if h not in days[d]]
            if len(miss) == 1:
                implied[(miss[0] - gold_break_utc_hour(d)) * 60] += 1
        if implied and implied.most_common(1)[0][1] * 2 >= len(full):
            seen = implied.most_common(1)[0][0]
            if pinned is not None and seen != pinned:
                raise SystemExit(
                    f"REFUSING: the venue's own bars put {month} at {seen:+d} min from UTC "
                    f"(daily-break position), while {SERVER_OFFSET_MANIFEST} pins {pinned:+d}. "
                    f"One of the two is wrong and a pass run on the wrong one mis-aligns every "
                    f"key with no visible symptom. Re-measure the era before certifying "
                    f"anything in it.")
        per_month[month] = pinned
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


def build_inputs(mode: str, t0: int, t1: int, offset_min: int = 0,
                 news: bool = False) -> dict:
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
        # The news gate, declared in BOTH stances. The python engine of record applies
        # the same +/-15-minute stand-down (scripts/midas_sweep.py `use_news`), reading
        # the same file, judged at the same instant — this bar's close, which is what the
        # EA's TimeGMT() returns when it evaluates that bar. `news=False` is the certified
        # contract; `news=True` is the parity run that used to be refused at init.
        "InpUseNewsFilter": "true" if news else "false",
        "InpNewsFile": NEWS_FILE,
        "InpNewsWindowMin": str(NEWS_WINDOW_MIN),
        "InpNewsMaxAgeHours": str(NEWS_MAX_AGE_HOURS),
        "InpNewsCoverHours": str(NEWS_COVER_HOURS),
        # NEVER refresh inside a replay. The calendar API is unavailable in the tester
        # (error 4014), and a refresh would rewrite the very file this pass is judged
        # against — the comparison would then be against a source that moved.
        "InpNewsRefreshHours": "0",
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

def python_build_data(news: bool = False, *, offset_min: int | None = None,
                      corpus: str) -> dict:
    """Indicator build shared by every mode's regen (done once per session).

    v1.16 R6 mirror, REVISED 2026-09-21 (one-commit law with the EA). The old invariant
    was "the news filter must be the no-protection value", because the python engine of
    record could not apply the rule and a pass with the gate on would have named a
    protection that could not act. The engine of record applies it now, so the invariant
    becomes the one that actually matters: **the two engines must be in the same stance**.
    The symbol must still be gold.

    `news` must equal what the EA input block this pass builds declares; a mismatch is a
    harness bug and refuses loudly rather than certifying an unlabelled configuration.

    `corpus` names WHICH MARKET the python leg is walked through, and it has NO DEFAULT —
    deliberately, and it is the correction of a defect this harness carried for its whole
    life. `venue` is the terminal's own history (`*_upcomers.csv`) shifted from server time
    into UTC by the offset the window asserted: the DATA OF RECORD, the bars the EA actually
    trades. `frozen` is the retired research series, which was a DIFFERENT MARKET — the two
    disagree about 21 bars inside the tick-covered window and even about the units of their
    spread column — and which now lives in a hash-pinned archive (see `M.frozen_bars`) that
    exists only to reproduce the frozen certification. A default would let a caller who
    merely forgot get a silently different market, which is exactly how a data-source change
    read as a clock fault for a day, so the choice has to be made out loud. `venue` also
    requires `offset_min`: a series stamped in the venue's clock cannot be read as UTC
    without it.
    """
    assert R6_GOLD_ONLY, "R6: engine of record is gold-only by charter"
    assert R6_NEWS_MIRRORED, "R6: the news gate must be mirrored by the engine of record"
    assert T._BASE_TESTER_INI.get("Symbol", "").upper().startswith("XAU"), \
        "R6: harness must feed a gold symbol"
    assert inputs_declare_news(news), (
        f"R6: this pass asked the engine of record for news={news} while the EA input "
        f"block declares the other stance — the two engines would be running different "
        f"rules and every comparison between them would be meaningless")
    if corpus == "venue":
        if offset_min is None:
            raise SystemExit(
                "REFUSING: corpus='venue' needs the server offset it must be shifted by. "
                "The venue's bars are stamped in the venue's clock, so reading them as UTC "
                "without the offset would mis-date every bar — and the shift is the whole "
                "reason this corpus is the comparable one.")
        h1 = venue_bars_utc("XAUUSD_H1", offset_min)
        m15 = venue_bars_utc("XAUUSD_M15", offset_min)
        # H4 ON THE VENUE'S OWN GRID. The EA reads the venue's H4 bars; deriving them from
        # the same H1 series is only equivalent if the buckets start where the venue's do
        # (server 00:00 = UTC 22:00 at +120). Bucketing from the Unix epoch instead put
        # every H4 bar two hours out and cost 3 of the 9 keys on the tick-covered window.
        h4 = M.h4_series(h1, offset_min=offset_min)
        return _python_data(h1, m15, h4)
    elif corpus == "frozen":
        h1 = M.frozen_bars("XAUUSD_H1")
        m15 = M.frozen_bars("XAUUSD_M15")
    else:
        raise SystemExit(f"unknown corpus '{corpus}' (have: frozen, venue)")
    # The frozen corpus is stamped in true UTC and its certified arithmetic was computed on
    # EPOCH-aligned H4 bars, so `offset_min=None` -> the epoch grid is not a leftover here:
    # re-basing it would change the numbers the SWEEP ANCHOR is cited for (the 151-trade,
    # +1.474R REVERSE_DIRECTION/wf entry in artifacts/midas_sweep_20260917.json). NOT
    # `artifacts/gold_wfo.json`: that one is produced by scripts/gold_walkforward.py, which
    # reads the TERMINAL's own bars, so it never depended on this archive.
    return _python_data(h1, m15, M.h4_series(h1, offset_min=offset_min or 0))


def _python_data(h1: list[dict], m15: list[dict], h4: list[dict]) -> dict:
    """The indicator build both corpora share, so the two can differ only in their bars."""
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
                 data: dict | None = None, news: bool = False,
                 events: tuple = (), stats: dict | None = None,
                 offset_min: int | None = None, corpus: str = "venue") -> list[dict]:
    """Run scripts/midas_sweep.py run_mode on the requested window (SMA ATR).

    Sized on the ACCOUNT basis, set here rather than at import: the research engine's
    certified default is its own $5,000 corpus basis, and a harness that mutated that
    global merely by being imported would silently re-basis every other consumer in
    the process. The news events are armed the same way and for the same reason.

    `stats`, when given, receives the engine's own counts (`news_vetoed`), so the artifact
    can say how many entries the stand-down refused rather than only what survived it.
    """
    M.use_basis(ACCOUNT_BASIS_USD)
    M.use_news(events if news else None)
    data = data or python_build_data(news=news, offset_min=offset_min, corpus=corpus)
    rr = M.run_mode(mode, t0, t1, data)
    if stats is not None:
        stats.update({"news_vetoed": rr.news_vetoed, "news_events": len(events) if news else 0})
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


def inputs_declare_news(news: bool) -> bool:
    """Does the EA input block this harness builds carry the gate in the asked state?"""
    want = "true" if news else "false"
    return str(build_inputs("ORIGINAL", 0, 1, news=news)["InpUseNewsFilter"]).lower() == want


def news_stance_consistent(inputs: dict, engine_armed: bool) -> bool:
    """Is the pass's DECLARED stance the one the engine of record was armed with?

    This is the invariant that replaced "the news filter must be off". A pass may run the
    gate either way now, but never in two stances at once: the EA's input block and the
    engine of record must agree, or every keyed comparison between them is measuring the
    difference between two rules and reporting it as an engine difference.
    """
    declared = str(inputs.get("InpUseNewsFilter", "false")).strip().lower() == "true"
    return declared == bool(engine_armed)


def news_calendar_path() -> Path | None:
    """The calendar both engines read, in the install the pass will run on.

    `<data>\\MQL5\\Files` is where the EA's `FileOpen(InpNewsFile)` resolves in the tester
    (the terminal mirrors that folder into the agent sandbox read-only), and it is where
    `MidasNewsProbe.mq5` writes. One file, so the two sides cannot disagree about the news.
    """
    data = R.data_folder_for_terminal()
    if not data:
        return None
    return Path(data) / "MQL5" / "Files" / NEWS_FILE


def news_events_for_pass(spec: dict) -> tuple:
    """The HIGH events this pass will be judged against, or a refusal that says why not.

    Refuses on the same terms the EA refuses, because a pass run against a calendar the
    EA itself would reject is a measurement of a rule nobody runs. Freshness and coverage
    are checked at the END of the window (`t1`), which is the strictest instant in it: a
    calendar that stops covering partway through would let the EA fail closed mid-window
    while python kept trading, and that would read as an engine difference.
    """
    path = news_calendar_path()
    if path is None or not path.is_file():
        raise SystemExit(
            f"REFUSING: news gate requested but there is no calendar at {path}. Attach "
            f"mql5/MIDASTOUCH/MidasNewsProbe.mq5 once to write the venue's own feed, or "
            f"run the pass with the gate OFF (its certified stance).")
    try:
        cal = NC.read_calendar(path)
    except NC.CalendarUnusable as exc:
        raise SystemExit(f"REFUSING: the calendar at {path} is unusable ({exc.reason})")
    problem = NC.source_problem(cal, int(spec["t1"]), max_age_hours=NEWS_MAX_AGE_HOURS,
                               cover_hours=NEWS_COVER_HOURS)
    if problem:
        raise SystemExit(
            f"REFUSING: {problem} (calendar {path}, judged at the window's end "
            f"{datetime.fromtimestamp(int(spec['t1']), timezone.utc):%Y-%m-%d %H:%M} UTC). "
            f"The EA fails closed on this, so a pass over a window it does not cover "
            f"compares two different rule sets.")
    return NC.top_tier_events(cal)


def run_one_mode(mode: str, spec: dict, window_name: str, data: dict,
                 expert: str = EXPERT, news: bool = False,
                 corpus: str | None = None) -> dict:
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
    corpus = corpus or spec.get("corpus")
    if not corpus:
        raise SystemExit(
            f"REFUSING: window '{window_name}' does not declare a corpus and none was given. "
            f"The python leg's market is a choice, not a default: 'venue' is the bars the EA "
            f"actually trades, 'frozen' is the retired research series in its archive. A pass "
            f"that picks one by falling back is how two markets were compared for a day and "
            f"read as a clock fault.")
    # ONE MARKET, MEASURED BEFORE ANYTHING IS STOPPED. The two corpora this harness can
    # walk python through are not the same series, and a pass whose legs saw different bars
    # cannot be compared key-by-key no matter how well the clocks are normalised — that is
    # exactly how the first tickcov divergence was mis-read as a +120 min clock error.
    audit = corpus_alignment(offset_min, spec["t0"], spec["t1"])
    print(f"  corpus: python on '{corpus}' — {audit['python_bars']} python bars vs "
          f"{audit['venue_bars']} venue bars in window; {audit['only_python']} only in "
          f"python's series, {audit['only_venue']} only in the venue's", flush=True)
    if corpus != "venue" and (audit["only_python"] or audit["only_venue"]):
        raise SystemExit(
            f"REFUSING: the python leg would run on a different market than the EA. In "
            f"window '{window_name}' the two corpora disagree about "
            f"{audit['only_python'] + audit['only_venue']} bars ({audit['only_python']} present "
            f"only in XAUUSD_M15.csv, {audit['only_venue']} only in the venue's own series, "
            f"{audit['t0']}..{audit['t1']}). Keys cannot be compared across different bars, "
            f"and this is what made the first divergence look like a clock problem. Re-run "
            f"with --corpus venue (the data of record), or choose a window whose two series "
            f"agree.")
    tag = f"{spec['tag']}_{TAG_MODE_CODE[mode]}"
    # Both engines in one stance, resolved BEFORE anything is stopped: the calendar is
    # read once and the same event tuple is handed to the EA's input block and to the
    # engine of record, so a news-on pass differs from a news-off pass by one flag and
    # nothing else. A refusal here costs nothing; discovering it mid-session costs a
    # stopped terminal and up to an hour.
    events: tuple = ()
    if news:
        events = news_events_for_pass(spec)
        print(f"  news gate ON — {len(events)} HIGH event(s) from {news_calendar_path()}",
              flush=True)
    inputs = build_inputs(mode, t0, t1, offset_min=offset_min, news=news)
    # The invariant that replaced "news must be off": the EA input block this pass feeds
    # and the engine of record's stance are the SAME, so a mismatch cannot be reported as
    # an engine difference. Cheap to check here, impossible to detect afterwards.
    assert set(inputs) >= {"InpUseNewsFilter", "InpNewsFile", "InpNewsWindowMin"}, \
        "the news contract must be declared in the input block, both stances"
    assert news_stance_consistent(inputs, news), \
        "the EA input block and the engine of record must be in one news stance"
    rotated = rotate_sandbox_ledgers()
    if rotated:
        print(f"  rotated stale sandbox ledgers: {rotated}")
    snaps = T.journal_snapshots()
    print(f"  pass tag={tag} mode={mode} — server clock {offset_min:+d} min, contract "
          f"declared in UTC (real ticks required; be patient)", flush=True)
    res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert,
                     model=spec.get("model"))
    # Which ticks the pass ACTUALLY ran on, carried into the comparison and the
    # artifact: a parity number is only evidence next to the tick model that produced
    # it (2026-09-20: the oos pass declared real ticks and ran five months generated).
    ticks = dict(res.get("tick_model") or {})
    print(f"    tick model: {str(ticks.get('used', 'unknown')).upper()} — "
          f"{ticks.get('evidence', 'no tick-model statement in this pass')}", flush=True)
    time.sleep(10)                   # agent flushes journal + ledger after report
    ea, source = collect_ea_evidence(snaps)
    ea = to_utc(ea, offset_min)      # EA ledger epochs are venue server time
    py_stats: dict = {}
    py = python_regen(mode, t0, t1, data, news=news, events=events, stats=py_stats)
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
            "corpus": corpus, "corpus_alignment": audit,
            "news": {"enabled": bool(news), "file": NEWS_FILE,
                     "window_min": NEWS_WINDOW_MIN,
                     "high_events": len(events) if news else 0,
                     "python_news_vetoed": py_stats.get("news_vetoed", 0)},
            "server_offset_min": offset_min, "tick_model": ticks,
            "anchor": anchor, "anchor_match": anchor_match, "cmp": cmp,
            "python": {"n": len(py), "sum_r": round(sum(t["r"] for t in py), 4), "trades": py},
            "ea": {"n": len(ea), "sum_r": round(sum(t["r"] for t in ea), 4), "trades": ea}}


def corpus_bars(corpus: str, offset_min: int) -> list[dict]:
    """The M15 bars of the declared corpus, in UTC — the series the python leg walks.

    `venue` is the terminal's own history (`*_upcomers.csv`), the data of record; `frozen` is
    the retired research series in its hash-pinned archive. They are not the same series (see
    `venue_bars_utc`), so the spread file staged for the EA has to come from whichever one
    this pass declared — otherwise the two engines are charged different costs on the same
    bars, which is not a comparison.
    """
    if corpus == "venue":
        return venue_bars_utc("XAUUSD_M15", offset_min)
    if corpus == "frozen":
        return M.frozen_bars("XAUUSD_M15")
    raise SystemExit(f"unknown corpus '{corpus}' (frozen|venue)")


def spread_rows(bars: list[dict], offset_min: int) -> list[tuple[int, float]]:
    """The staged file's rows for one corpus: (SERVER epoch, dollars), one per bar.

    SERVER time, because that is the frame the EA looks a bar up in — `SpreadAt(iTime(...))`
    inside the tester, where every epoch is the venue's. A file left in UTC is read one
    offset late on every bar, silently, which a flat series makes undetectable.

    Dollars, floored at `SPREAD_FLOOR`, rounded to 5 dp, because that is exactly what the
    python engine charges per bar (`max(b["spread"], SPREAD_FLOOR)`) and what the EA's
    `SpreadAt` returns; the two sides' halves then agree to the digit.
    """
    shift = offset_min * 60
    return [(int(b["time"]) + shift,
             round(max(float(b["spread"]), M.SPREAD_FLOOR), 5)) for b in bars]


def spread_file_text(rows: list[tuple[int, float]]) -> str:
    """Exactly the format the EA's `LoadSpreadFile` reads: a header, then `time,spread`."""
    return "time,spread\n" + "".join(f"{t},{v:.5f}\n" for t, v in rows)


def spread_file_path(data_folder) -> Path:
    """Where the tester bundles it from — the same folder `#property tester_file` names."""
    return Path(data_folder) / "MQL5" / "Files" / SPREAD_FILE


def stage_spread_file(data_folder, rows: list[tuple[int, float]]) -> Path:
    """Write the spread series the EA will read, from the corpus this pass declared.

    Through a temp file and `os.replace`, so a crashed write can never leave a half-series
    behind for the tester to read as membership.
    """
    path = spread_file_path(data_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(spread_file_text(rows), encoding="ascii")
    os.replace(tmp, path)
    return path


def verify_spread_file(data_folder, rows: list[tuple[int, float]]) -> list[str]:
    """Blockers if the staged spread file is not this corpus, bar for bar.

    Three ways it can be wrong, all of them silent at run time and each named with the bar
    that differs: a bar the corpus holds and the file does not (the EA skips that fill and
    runs no management on it), a bar the file holds and the corpus does not (membership the
    corpus never granted), and a value that differs (a different cost model). The value
    comparison is the one that failed unnoticed until 2026-09-21.
    """
    path = spread_file_path(data_folder)
    if not path.is_file():
        return [f"no recorded spread file at {path} — the BAR-parity pass charges its "
                f"half-spreads and takes its bar membership from there"]
    got: dict[int, float] = {}
    try:
        with open(path, newline="") as fh:
            for i, row in enumerate(csv.reader(fh)):
                if i == 0 or not row or row[0] in ("", "time"):
                    continue
                got[int(row[0])] = float(row[1])
    except (OSError, ValueError, IndexError) as exc:
        return [f"recorded spread file at {path} is unreadable: {exc}"]
    want = dict(rows)
    missing = [t for t in want if t not in got]
    extra = [t for t in got if t not in want]
    wrong = [(t, got[t], want[t]) for t in want if t in got and abs(got[t] - want[t]) > 1e-9]
    if not (missing or extra or wrong):
        return []
    if wrong:
        first = (f"first value disagreement: bar {wrong[0][0]} holds {wrong[0][1]:.5f} in "
                 f"the file, the corpus records {wrong[0][2]:.5f}")
    elif extra:
        first = f"first bar held only by the file: {extra[0]}"
    else:
        first = f"first bar held only by the corpus: {missing[0]}"
    return [f"recorded spread file at {path} is NOT the corpus of record: "
            f"{len(wrong)} value(s) differ, {len(missing)} bar(s) missing, {len(extra)} "
            f"extra — {first}.\n"
            f"      -> the EA takes both its half-spreads and its BAR-mode membership from "
            f"this file, so a stale one silently certifies a different cost model than "
            f"python's. It is re-derived from the declared corpus on every pass; this "
            f"means the derivation could not be written, or something overwrote it."]


def ensure_spread_file(data_folder, corpus: str, offset_min: int) -> list[str]:
    """Stage the spread series from the corpus of record, then prove the staged file IS it.

    Derived, never trusted — the same rule this harness already applies to the corpus audit
    and to the news calendar: one number, one source, both engines. Returns blockers; empty
    means both engines will be charged the corpus's own spreads on the corpus's own bars.
    """
    rows = spread_rows(corpus_bars(corpus, offset_min), offset_min)
    replaced = bool(verify_spread_file(data_folder, rows))
    if replaced:
        stage_spread_file(data_folder, rows)
    blockers = verify_spread_file(data_folder, rows)
    if not blockers:
        print(f"  recorded spread series {'restaged' if replaced else 'verified'} from "
              f"the '{corpus}' corpus: {len(rows)} bar(s) in server time "
              f"({offset_min:+d} min)", flush=True)
    return blockers


def preflight(expert: str, expected_spread: list | None = None) -> tuple[list[str], list[str]]:
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
    spread = spread_file_path(data_folder)
    if expected_spread is None:
        if not spread.exists():
            problems.append(f"no recorded spread file at {spread} — the BAR-parity pass "
                            f"reads its spreads from there, and without it the EA would "
                            f"be certified on a different cost model than python's")
    else:
        # CONTENTS, not existence: a file from the wrong series is worse than a missing one,
        # because it runs. `ensure_spread_file` stages the corpus's own series first.
        problems.extend(verify_spread_file(data_folder, expected_spread))
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
    ap.add_argument("--news", action="store_true",
                    help="run the pass with the news stand-down ON, on BOTH sides "
                         "(default: OFF, the certified contract). The engine of record "
                         "applies the same veto, so the pass is compared key-by-key "
                         "instead of being refused at init.")
    ap.add_argument("--corpus", choices=("frozen", "venue"), default=None,
                    help="which series the PYTHON leg is walked through: 'venue' is "
                         "the terminal's own history shifted to UTC — the bars the EA "
                         "actually trades, and the data of record; 'frozen' is the RETIRED "
                         "research series, which this program no longer treats as a market "
                         "and which exists only to reproduce the frozen certification "
                         "(deleted 2026-09-21; restore from commit 248db66). Defaults to "
                         "the window's "
                         "own declaration, and there is NO fallback: a window that declares "
                         "none and is given none refuses rather than picking a market.")
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
    corpus = args.corpus or spec.get("corpus")
    if not corpus:
        print(f"ABORT: window '{args.window}' declares no corpus and --corpus was not given. "
              f"'venue' is the bars the EA actually trades; 'frozen' is the retired research "
              f"series in its archive. There is no default on purpose. Nothing was stopped "
              f"and nothing was run.")
        return 5
    # The offset is asserted HERE rather than inside the pass, because everything after this
    # point may stop the live terminal: an un-normalisable window, or a window whose two
    # corpora disagree, must cost a refusal instead of a stopped arm.
    offset_min = assert_server_offset(spec)
    audit = corpus_alignment(offset_min, spec["t0"], spec["t1"])
    print(f"preflight OK — basis ${ACCOUNT_BASIS_USD:,.0f}, expert {expert}, "
          f"window {spec['window_name']}, server clock {offset_min:+d} min, python corpus "
          f"'{corpus}'")
    print(f"corpus audit: {_audit_line(audit)}, inside the window")
    if corpus != "venue" and (audit["only_python"] or audit["only_venue"]):
        print(f"ABORT: the two corpora disagree about "
              f"{audit['only_python'] + audit['only_venue']} bars in "
              f"'{spec['window_name']}' — a keyed comparison across different bars is not "
              f"evidence. Nothing was stopped and nothing was run. Re-run with "
              f"--corpus venue, which walks python through the venue's own bars.")
        return 5
    # ONE COST MODEL, ON THE SAME BARS — the corpus rule above, applied to the file the EA
    # charges its spreads from. The harness DERIVES that file now instead of trusting
    # whatever is on disk: on 2026-09-21 it was still the legacy series' dump (flat $0.15)
    # while python charged the venue's recorded spread ($0.42) on the same bars, and the
    # only check that ever ran asked whether the file existed.
    data_folder = R.data_folder_for_terminal()
    if not data_folder:
        print("ABORT: no terminal resolves for the active account — the spread series the "
              "EA reads cannot be placed or verified. Nothing was stopped and nothing was "
              "run.")
        return 5
    spread_blockers = ensure_spread_file(data_folder, corpus, offset_min)
    if spread_blockers:
        print("ABORT: the two engines would be charged different costs on the same bars "
              "(nothing was stopped and nothing was run):\n")
        for b in spread_blockers:
            print(f"  - {b}")
        return 5

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
        data = python_build_data(news=args.news, offset_min=offset_min, corpus=corpus)

        print(f"parity session: window={args.window} tester_dates={dates} "
              f"modes={','.join(modes)} expert={expert} "
              f"news={'ON' if args.news else 'OFF'} corpus={corpus}")
        records = [run_one_mode(m, spec, args.window, data, expert=expert, news=args.news,
                                corpus=corpus)
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
            print(f"python corpus:      {rec.get('corpus')} ({_audit_line(audit)})")
            print(f"news gate:          {'ON' if rec['news']['enabled'] else 'OFF'} "
                  f"({rec['news']['high_events']} HIGH event(s); engine of record "
                  f"vetoed {rec['news']['python_news_vetoed']} entr(y/ies))")
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
                "news": rec["news"],
                "inputs": build_inputs(rec["mode"], t0, t1, news=rec["news"]["enabled"],
                                       offset_min=rec["server_offset_min"]),
                "evidence_source": rec["evidence_source"],
                "tick_model": rec.get("tick_model", {}),
                "python_corpus": rec.get("corpus"),
                "corpus_alignment": rec.get("corpus_alignment"),
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

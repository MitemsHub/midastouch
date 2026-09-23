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
import hashlib
import json
import math
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

#: The FROZEN calendar — the one a REPLAY is judged against.
#:
#: WHY A SECOND FILE. `MidastouchAI.mq5` refreshes the rolling file from
#: `CalendarValueHistory(now - N days, now + M days)`, so its coverage moves with the clock.
#: MEASURED 2026-09-21: at 17:52Z that live refresh rewrote
#: `<data>\MQL5\Files\MIDASTOUCH_news_calendar.csv` down to a 2026-09-09..2026-10-09 window,
#: and the coverage the day's measurements were taken on (2026-01-02..2026-09-24, 2719
#: events / 369 HIGH) was gone. Every replay of the certified window then ran against a
#: calendar holding NO event in it at all: the stand-down silently became a no-op, and
#: `tests/test_parity_corpus.py`'s veto pin — still correct — went red. A pass that judges a
#: past window against the arm's rolling file is judging it against a source that moved, and
#: the failure is silent in the direction that matters: a rule that stops acting looks like a
#: rule with nothing to veto.
#:
#: So: two files, two clocks, named. The LIVE arm keeps refreshing the ROLLING one; every
#: replay reads the FROZEN snapshot under its own name, which the EA declares
#: `#property tester_file` beside the rolling one so the tester mirrors both and both sides
#: of a pass open the same bytes.
FROZEN_NEWS_FILE = "MIDASTOUCH_news_calendar_frozen.csv"
FROZEN_NEWS_SOURCE = (Path(__file__).resolve().parents[1] / "configs" / "calendars"
                      / "MIDASTOUCH_news_calendar_frozen_20260102_20260924.csv")

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
    # the calendar's fault, not the engine's. t0 = 2026-03-15 00:00 UTC is 2026-03-15 01:00
    # server and t1 = 2026-03-20 00:00 UTC is 2026-03-20 01:00 server (+60), so ToDate is 21st.
    #
    # RE-CHOSEN 2026-09-22, and the reason is the one this window's own test names. The trigger
    # threshold moved (BBDev 2.0 -> 1.5, `BB_DEV` above), which changes the SIGNAL SET — a
    # narrower band takes the trigger slots the RSI branch used to fill — and in the old window
    # (2026-05-11..16) the stand-down then refused nothing at all: measured, off_n=5 / on_n=5 /
    # news_vetoed=0 / removed=[] , so the window had stopped being a veto path.
    #
    # HOW THIS ONE WAS FOUND, because "a window was chosen" must not read as "a window was
    # widened until it passed". Every 5-day window in the venue's span was swept at ITS ERA'S OWN
    # clock (+60 Jan-Apr, +120 May-Sep, and April contributes none because it has no single
    # offset) and filtered for the property the window exists for: refuses >=1 signal, REMOVES an
    # entry, ADDS none. Exactly one week survives at the new contract — 2026-03-15..19, five
    # candidate starts, all the same week — so the choice here is between starts of a week, not
    # between configurations. The first sweep said June, and that answer was an artifact of the
    # sweep's own clock: it ran every window at +60 and June is +120, which moved the bars under
    # the stand-down until a signal fell inside one. Measured both ways to keep that on the
    # record: the June window at +60 reports vetoed=1 / removed=[06-17 19:45]; at its own asserted
    # +120 it reports vetoed=0 / removed=[]. The clock is part of the measurement, not a detail.
    "veto": {"tag": "midas_veto_rd", "mode": "REVERSE_DIRECTION",
             "iso": ("2026-03-15T00:00", "2026-03-20T00:00"),
             "dates": ("2026.03.15", "2026.03.21"),
             "server_offset_min": 60, "model": "1", "corpus": "venue"},
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
                 news: bool = False, bb_dev: float | None = None) -> dict:
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
        # THE TRIGGER THRESHOLD, AND IT MUST EQUAL `BB_DEV` BELOW. The EA's input and the
        # python leg's trigger array are the two halves of one contract: `_python_data`
        # builds `m15_bb` with the same threshold, so a pass cannot compare an EA reading a
        # 1.5-sigma band against a python leg reading a 2.0-sigma one and call the
        # difference a parity result. `bb_dev` is explicit for the one legitimate use —
        # re-running a pass recorded at an older threshold.
        "InpBBDev": f"{BB_DEV if bb_dev is None else bb_dev}",
        "InpRSIPeriod": "14",
        "InpRSIUpper": "70.0",
        "InpRSILower": "30.0",
        "InpAtrPeriod": "14",
        "InpSlAtrMult": "2.0",
        "InpTpMult": "2.0",
        "InpTimeoutMinutes": "720",
        "InpSessionStartHour": str(6 + shift_h),         # UTC 06-20, in server time
        "InpSessionEndHour": str(20 + shift_h),
        # MEASURED 2026-09-23: 1.5% of stop = 0.015R sat INSIDE the certified engine's own
        # entry-cost distribution on the 130 held-out fills (p90 0.0141R, p99 0.0184R, max
        # 0.0193R) — it refused 7 of the 130 certified fills on cost alone. 2.5% (0.025R)
        # refuses none of them, covers the live venue regime the veto exposed ($0.47-0.50
        # on a ~$25 stop), and stays a quarter of the self-check's own 0.10R ceiling. The
        # go-live grammar pins this preset generator and the Upcomers presets to the SAME
        # value, so the two move together or not at all.
        "InpSpreadCapPctStop": "2.5",
        "InpFridayCutoffHour": str(20 + shift_h),          # UTC 20:00, in server time
        # The news gate, declared in BOTH stances. The python engine of record applies
        # the same +/-15-minute stand-down (scripts/midas_sweep.py `use_news`), reading
        # the same file, judged at the same instant — this bar's close, which is what the
        # EA's TimeGMT() returns when it evaluates that bar. `news=False` is the certified
        # contract; `news=True` is the parity run that used to be refused at init.
        "InpUseNewsFilter": "true" if news else "false",
        # The FROZEN name, not the rolling one: this pass is a replay, and the EA opens
        # whatever this says. The EA's own default stays the rolling file — that default is
        # for the attached arm, which is not this.
        "InpNewsFile": FROZEN_NEWS_FILE,
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


#: THE TRIGGER THRESHOLD of the contract (Bollinger deviation), amended 2026-09-22.
#:
#: 2.0 was the value every pass of record certifies; 1.5 is the value the arm now runs, and
#: the two sides move together or the comparison is meaningless (`build_inputs` above, and
#: `_python_data` below, read this one constant). The change is pre-registered and measured in
#: docs/FREQUENCY_AXES_PREREG_20260922.md / artifacts/midas_frequency_axes_20260922.json: on
#: the venue's own bars over the held-out window (2026-04-01 -> 09-16) the armed mode at 1.5
#: takes 130 fills with +0.087R / pf 1.201 / 6.5R dd against 2.0's 111 fills with -0.003R /
#: pf 0.981 / 7.6R dd, and 1.5 also leads on the selection span. The pin in
#: scripts/gold_preset_upcomers.py (BB_DEV) carries the full table and the falsified prior.
#:
#: CERTIFIED 2026-09-22 at this threshold: `python scripts/midas_parity.py --window tickcov`
#: returned PASS on REAL ticks — artifact artifacts/midas_parity_result_20260922_1547.json
#: (14:47:00Z; identical PASSes at 14:02:45Z and 14:26:14Z, ..._1502.json and ..._1526.json,
#: certify the same contract on the previous build and are kept, neither counted twice), python
#: leg 9 trades / +0.2699R against the EA's 9 / +0.271R,
#: count/open/close/side all agreeing and max|dR| 0.0004. The certificate carries the input block
#: it used, so the threshold it describes is readable from the artifact (`InpBBDev: "1.5"`)
#: rather than inferred. The pass that preceded it (2026-09-21 12:18) certified 2.0; it is kept,
#: and it is no longer a statement about what the arm runs.
#:
#: WHY THE RE-RUNS EXIST, since an identical certificate invites the question: two files
#: on this module's side of the contract were edited at 14:14Z, AFTER the first pass, so that
#: artifact described a tree that no longer existed (measured inert — the python leg re-derived
#: from the current tree reproduces it to the digit); and the LATEST one exists because the EA
#: moved to v1.24 (the ledger-backed live census), so a certificate naming the previous build no
#: longer describes what the arm runs — re-earned on the new binary with the trade set UNCHANGED,
#: which is how "telemetry-only" is measured rather than asserted; and the pass of record moved
#: to v1.25 (the fill-row-integrity build) for the same reason, unchanged trade set again. That
#: pass is also the first to carry the ACCOUNT LAYER: run with `--live-stance`, it adds a second
#: pass in the arm's OWN stance (risk %, governor and live execution from the arm's preset) whose
#: sizing is graded against the python mirror per fill and whose governor is modelled — see the
#: section below, and note that the BAR pass still pins those inputs OFF on purpose. The pass of
#: record postdates this
#: session's correction of the four ledger readers that paired a fill with its close on the
#: `posid` field alone, which a netting fill writes as 0: the arm's own closed trade read as an
#: OPEN position, `mt5_ops.ledger_flatness` returned NOT FLAT, and this harness's flat gate
#: refuses to stop the terminal over that — so the certification run was blocked, not merely
#: un-run, until the fix landed (mt5_ops.live_fill_key, one rule, four callers).
#:
#: Note what that pass does and does not say, because the distinction is the whole point of
#: asking for one: it certifies ENGINE EQUIVALENCE at this configuration over a 12-day window
#: with real ticks. It is not an expectancy estimate and it does not move the gate — the
#: venue's criteria remain FAILED (see the arming record's gate_detail).
BB_DEV = 1.5

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
                      corpus: str, bb_dev: float | None = None) -> dict:
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
        return _python_data(h1, m15, h4, bb_dev=bb_dev)
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
    return _python_data(h1, m15, M.h4_series(h1, offset_min=offset_min or 0),
                        bb_dev=bb_dev)


def _python_data(h1: list[dict], m15: list[dict], h4: list[dict],
                 bb_dev: float | None = None) -> dict:
    """The indicator build both corpora share, so the two can differ only in their bars.

    `bb_dev` is the EA-input half of the same contract `build_inputs` writes: this leg's
    `m15_bb` array must be built at the SAME threshold the EA is told to use, or a pass
    compares two different triggers. Defaults to the module contract constant.
    """
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
        "m15_bb": [M.bb_touch(mc, i, 20, BB_DEV if bb_dev is None else bb_dev)
                   for i in range(len(m15))],
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


def frozen_news_source() -> Path:
    """The tracked snapshot every replay's news rule is judged against.

    This is the calendar the corpus was measured on — the data of record for the window,
    exactly as the venue's own bars are — and it is READ-ONLY by construction: nothing in
    the live arm writes this path.
    """
    return FROZEN_NEWS_SOURCE


def live_news_calendar_path() -> Path | None:
    """The ROLLING file the attached EA refreshes. Never a replay's source.

    It exists so that "the live arm's calendar" is nameable without borrowing the replay
    route's path — the two are different objects and only one of them is a measurement.
    """
    data = R.data_folder_for_terminal()
    if not data:
        return None
    return Path(data) / "MQL5" / "Files" / NEWS_FILE


def stage_frozen_calendar() -> Path | None:
    """Put the frozen snapshot where the tester mirrors it, and return that path.

    `<data>\\MQL5\\Files` is where the EA's `FileOpen(InpNewsFile)` resolves in the tester,
    and the terminal mirrors the folder into the agent sandbox for the names the EA declares
    `#property tester_file`. Staging from the tracked snapshot (rather than trusting whatever
    is lying in that folder) is what makes a replay's two sides read the same bytes.

    Refuses structurally: no terminal install -> None (the caller reports that), and a
    missing snapshot -> SystemExit, because a missing data-of-record file is a repo defect,
    not a machine state, and the alternative — falling back to the rolling file — is the
    failure this function exists to make impossible.
    """
    data = R.data_folder_for_terminal()
    if not data:
        return None
    if not FROZEN_NEWS_SOURCE.is_file():
        raise SystemExit(
            f"REFUSING: the frozen calendar is missing from the repo "
            f"({FROZEN_NEWS_SOURCE}). It is the data of record for a replay window, so the "
            f"pass cannot be judged without it — and the live arm's rolling calendar is "
            f"NOT an acceptable substitute.")
    dst = Path(data) / "MQL5" / "Files" / FROZEN_NEWS_FILE
    want = FROZEN_NEWS_SOURCE.read_bytes()
    if not dst.is_file() or dst.read_bytes() != want:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(want)
    return dst


def news_calendar_path() -> Path | None:
    """The calendar both engines read for a pass: the staged FROZEN snapshot.

    A pass here is always a replay of a declared window over the venue's own history, so its
    news rule has to be the rule that window was measured under. Reading the live rolling
    file instead is how a replay silently stops being a measurement (see FROZEN_NEWS_FILE).
    """
    return stage_frozen_calendar()


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


# --- THE ACCOUNT LAYER: the LIVE stance, certified instead of pinned off ----
#
# WHY THIS SECTION EXISTS. Every pass above pins `InpPropGuard=false`, `InpRiskPercent=1.0`,
# `InpArmTag=M1` and `InpBarModel=true` — and it must, because the python engine of record is a
# BAR model of the STRATEGY: the governor is an account-level layer it does not model, and
# leaving it on would compare two different rule sets and report the difference as an engine
# difference. The price of that honesty was that NOTHING in this harness said anything about the
# configuration the arm actually runs. MEASURED 2026-09-22: the sizing the venue allowed on the
# arm's first fill ($39.01 of a $62.50 configured budget — the lot step binding) was visible ONLY
# in `verify_sizing_live`, a read-only probe against the live terminal, and the governor was
# certified nowhere at all. "The live configuration is certified" was therefore false by
# construction, and a pass that pins the account layer off cannot be cited for it.
#
# SO: A SECOND STANCE. Same window, same tick model, same session/news/threshold contract — and
# the account layer moved to the numbers the ARM'S OWN PRESET declares, read from the file the
# arm is launched with (one declaration, not a copy that can drift). The differences are exactly
# three:
#   * `InpLiveExecution=true` + `InpBarModel=false` — the EA runs its LIVE path, which its own
#     comment says is "deliberately testable in the strategy tester"; in there the orders go to
#     the SIMULATED account, so the real sizing arithmetic, the real governor and the real
#     `LOPEN`/`LCLOSE` grammar are all exercised end to end;
#   * the comparison standard is the PYTHON MIRROR (`size_like_ea`), which is pinned against the
#     MQL5 it mirrors (tests/test_ea_sizing_mirror.py) — so a PASS says every fill was sized the
#     way the declared rule sizes it, at the equity the pass actually had;
#   * the governor is MODELLED here (a day-loss cap and a best-day cap on the pass's own equity
#     path) and the two are cross-checked: a modelled block that coincides with an entry the EA
#     took is a DISAGREEMENT, and a window where no rule would have bound is reported VACUOUS.
#
# WHAT IT DOES NOT SAY, written here rather than discovered later: this is not a strategy
# certificate (the BAR pass is, and it stands alone); the trailing shield floor is NOT modelled;
# and the governor leg is VACUOUS unless the window contains a day where a modelled rule binds.
LIVE_PRESET = Path("mql5/MIDASTOUCH/MidastouchAI_upcomers_gold_LIVE.set")
#: The inputs that ARE the account layer. Everything else in `build_inputs` is the strategy
#: contract, and a live-stance pass must not move any of it.
ACCOUNT_LAYER_INPUTS = ("InpMagic", "InpArmTag", "InpRiskPercent", "InpMaxRiskPct",
                        "InpLiveExecution", "InpPaperEquity", "InpDailyLossCapPct",
                        "InpPropGuard", "InpPropAccountSize", "InpPropTargetPct",
                        "InpPropMaxDdPct", "InpPropBestDayPct", "InpPropPeakOverride")
#: Rules this section's governor model implements, and the ones it does not. Named so a reader
#: never has to infer the scope of a "GOVERNOR: PASS" from the code.
GOVERNOR_MODELLED = ("daily loss cap (%, from the day's reconstructed opening equity)",
                     "best-day profit cap (the EA's PropDayProfitCapUsd(): declared target% x "
                     "declared best-day share% x the declared account size — 5% x 20% = 1% of "
                     "the account, NOT 20% of it)")
GOVERNOR_NOT_MODELLED = ("the trailing shield floor (needs the venue's peak/DD bookkeeping)",
                         "intrabar equity excursions (a cap that binds only between bars is "
                         "invisible to a close-to-close reconstruction)")
#: What `--governor-stress` is, in the artifact's own words, because a stress verdict quoted
#: without this sentence would read as a statement about the shipping threshold and it is not one.
GOVERNOR_STRESS_WHY = (
    "THE GOVERNOR, EXERCISED AT A THRESHOLD THAT BINDS. The shipping daily cap (3%) is never "
    "reached in any certified window — the largest measured day drawdown in the 12-day tickcov "
    "window is 0.318% of it — so the live stance's governor leg is honestly VACUOUS there. This "
    "leg does not change that fact and does not claim to: it derives a cap that MUST bind on the "
    "arm's own window (half the largest day drawdown the ungoverned path actually made), runs the "
    "same live path at it, and asks whether the EA refused exactly the entries the mirror "
    "predicted from the UNGOVERNED path. A prediction read off the governed pass could only agree "
    "with itself; a prediction read off the ungoverned one is a test. It certifies the governor's "
    "MACHINERY at a binding threshold — not the 3% number, which remains unexercised.")
#: What `--breaker-stress` is, and it is the OTHER leg: `--governor-stress` moves the CAP until it
#: binds; this one keeps the CAP AT ITS SHIPPING VALUE and moves the RISK PER TRADE until the same
#: number is reachable, so the certificate is about the 3% the arm runs rather than a derived
#: stand-in. A reader who sees one of these quoted without the other cannot tell which number was
#: tested, which is why each artifact carries its own paragraph.
BREAKER_STRESS_WHY = (
    "THE SHIPPING 3% CAP, MADE REACHABLE BY THE RISK PER TRADE — NOT BY MOVING THE CAP. MEASURED "
    "2026-09-22 on the tick-covered window (the only span this venue serves real ticks for, and the "
    "only one a pass may be certified on): the arm's own stance makes nine fills and the largest "
    "UTC-day drawdown among them is -1.007R, so at the shipping risk (0.25%/trade, and less once "
    "the venue's min lot floors the size) the 3% cap needs about twelve consecutive full stops in "
    "one day — it is unreachable, and `--governor-stress` therefore certifies the machinery at a "
    "DERIVED cap instead. This leg changes what a window cannot change: the risk per trade is "
    "derived from the path's own worst day (the largest day drawdown that is still followed by an "
    "entry, so the breach lands before something there is left to refuse) and the pass then runs "
    "the EA's LIVE path AGAINST THE SHIPPING 3% CAP. What is certified is the cap the arm "
    "actually runs, at the one resolution a closed-trade record allows; the risk per trade in this "
    "pass is a STRESS input and is named as one, and the derivation is reported beside the result.")
#: THE MARGIN ON THE DERIVED RISK PER TRADE, and it covers two measured quantisations rather than
#: being a round number: (1) the venue's lot step, which rounds the risk DOWN by up to one step's
#: dollar value (~$41 at this window's ATRs — ~2% at the derived size, and ~34% at the arm's own
#: shipping risk, where the min lot floors it); (2) the anchor's resolution, because the boundary
#: floating is priced from the bar closing at the roll and the EA sees the tick after it. Without a
#: margin a derived threshold can land at 2.99% and bind nothing — a NO-BIND that would read like a
#: market fact. The margin is declared and the artifact reports the loss the pass ACTUALLY made, so
#: it never stands in for the measurement.
BREAKER_STRESS_RISK_MARGIN = 1.20


def read_preset_inputs(path: Path | str = LIVE_PRESET) -> dict[str, str]:
    """The `key=value` inputs of a terminal preset — the arm's own declaration, as launched.

    Comments (`;...`) are not inputs, and a preset that cannot be read raises rather than
    returning an empty stance: a live-stance pass with no numbers to declare is a pass that
    would silently certify the harness's defaults.
    """
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"REFUSING: no preset at {p} — the live stance must come from the arm's "
                         f"own declaration, and there is nothing to read it from.")
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith(";") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def live_stance_inputs(mode: str, t0: int, t1: int, offset_min: int = 0,
                       *, preset: Path | str = LIVE_PRESET, news: bool = False) -> dict:
    """The certified strategy contract with ONLY the account layer moved to the arm's stance.

    Anything the preset does not declare REFUSES: a default here would be a second declaration of
    the arm's risk, and the whole reason this stance exists is that the account layer had one
    home (the preset) and no certificate.
    """
    d = build_inputs(mode, t0, t1, offset_min=offset_min, news=news)
    declared = read_preset_inputs(preset)
    missing = [k for k in ACCOUNT_LAYER_INPUTS if k not in declared]
    if missing:
        raise SystemExit(
            f"REFUSING: {preset} does not declare {missing}. The live stance is the arm's own "
            f"account layer; filling it in from a harness default would certify a configuration "
            f"nobody runs.")
    d.update({k: declared[k] for k in ACCOUNT_LAYER_INPUTS})
    # THE LIVE PATH, ON PURPOSE (see the section note): bar replay OFF, execution ON. In the
    # tester those orders hit the simulated account, which is what makes the real sizing, the
    # real governor and the real LOPEN/LCLOSE grammar measurable without a market.
    d["InpBarModel"] = "false"
    if d.get("InpLiveExecution", "").lower() != "true":
        raise SystemExit(
            f"REFUSING: {preset} declares InpLiveExecution={d.get('InpLiveExecution')!r}, so a "
            f"live-stance pass would run the PAPER path and certify the paper arm's sizing. An "
            f"armed preset declares it true — that is what arming IS.")
    return d


def stance_ledger_candidates(tag: str) -> list[Path]:
    """Every tester-agent ledger carrying the arm's own tag, newest first."""
    name = f"MIDASTOUCH_paper_XAUUSD_{tag}.csv"
    hits = [d / name for d in agent_files_dirs() if (d / name).is_file()]
    return sorted(hits, key=lambda p: p.stat().st_mtime, reverse=True)


def parse_stance_fills(path: Path) -> tuple[list[dict], list[str]]:
    """The LIVE rows of one stance pass, joined by the ONE identity rule (`mt5_ops.live_fill_key`).

    Returns closed fills only — an open one has no realized R yet, and the sizing audit walks the
    equity path, which only closes move. Rows that cannot be read are PROBLEMS, never skipped
    silently: a fill dropped from an audit is an audit that certifies fewer trades than the arm
    took.
    """
    opens: dict[str, dict] = {}
    order: list[str] = []
    problems: list[str] = []
    fills: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for ln, line in enumerate(fh, 1):
            p = line.strip().split(",")
            if not p or not p[0]:
                continue
            if p[0] == "LOPEN":
                if len(p) < 14:
                    problems.append(f"line {ln}: LOPEN row has {len(p)} fields (<14)")
                    continue
                key = R.live_fill_key(p) or f"line:{ln}"
                opens[key] = {"line": ln, "key": key, "open_ct": int(p[1]), "dir": int(p[5]),
                              "entry": float(p[6]), "lots": float(p[9]),
                              "risk_usd": float(p[10]), "stop_d": float(p[11]), "tag": p[13],
                              "cfg": audit_risk_tail(p)}
                order.append(key)
            elif p[0] == "LCLOSE":
                if len(p) < 6:
                    problems.append(f"line {ln}: LCLOSE row has {len(p)} fields (<6)")
                    continue
                key = R.live_fill_key(p) or f"line:{ln}"
                op = opens.get(key)
                if op is None:
                    problems.append(f"line {ln}: LCLOSE for {key} closes no LOPEN row")
                    continue
                fills[key] = {**op, "close_ct": int(p[1]), "reason": p[3],
                              "exit": float(p[4]), "r": float(p[5])}
    for key in order:
        if key not in fills:
            problems.append(f"LOPEN {key} (line {opens[key]['line']}) is still OPEN at the end of "
                            f"the pass — a live position, and no sizing verdict can be drawn "
                            f"for it from a closed-trade audit")
    return [fills[k] for k in order if k in fills], problems


def audit_risk_tail(parts: list[str]) -> dict:
    """The row's own `cfg=<usd>@<pct>` token, read off the END (the v1.22 grammar)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import midas_first_fills_audit as ffa
        return ffa.read_risk_tail(parts)
    except Exception as exc:                                     # noqa: BLE001
        return {"malformed": f"configured-risk token unreadable ({exc})"}


def stance_sizing_audit(fills: list[dict], *, preset: dict, spec, deposit: float) -> dict:
    """Every fill's size, against the python mirror, at the equity the fill actually had.

    The mirror (`size_like_ea`) is the pinned copy of the MQL5 arithmetic; the equity it is given
    is the pass's own: the tester's deposit plus the realized dollars of the fills before it
    (`R x risk_usd`, which the fill rows carry — no market data and no terminal needed).

    TWO NUMBERS ARE GRADED, and they grade different failure modes: `lots` (did the arm send the
    size the rule computes, at this equity and this stop) and `risk_usd` (does the row's stated
    risk equal stop x lots x $/unit — which is equity-independent, so a wrong equity basis cannot
    hide behind it). A third number is DISCLOSED, never graded: the configured budget, because
    the venue's lot step is allowed to leave part of it unspent and that gap is a property of the
    venue, not a rule the arm can violate.
    """
    from midas_prop.execution.prop_execution import size_like_ea
    pct = float(preset["InpRiskPercent"])
    maxpct = float(preset["InpMaxRiskPct"])
    eq = float(deposit)
    rows: list[dict] = []
    mismatches: list[str] = []
    for f in fills:
        m = size_like_ea(spec, equity=eq, risk_percent=pct, max_risk_pct=maxpct,
                         stop_distance_price=f["stop_d"])
        ok_lots = abs(m.lots - f["lots"]) <= 1e-9
        ok_risk = abs(m.risk_usd - f["risk_usd"]) <= 0.005
        row = {"key": f["key"], "open_ct": f["open_ct"], "stop_d": f["stop_d"],
               "equity_basis": round(eq, 2), "lots_ea": f["lots"], "lots_python": m.lots,
               "risk_usd_ea": f["risk_usd"], "risk_usd_python": round(m.risk_usd, 4),
               "budget_usd_python": round(m.budget_usd, 4), "budget_usd_ea": f["cfg"].get("cfg_risk_usd"),
               "cfg_risk_pct_ea": f["cfg"].get("cfg_risk_pct"), "floored_to_min_lot": bool(m.lots <= spec.min_lot + 1e-9),
               "vetoed_python": bool(m.vetoed), "agrees": bool(ok_lots and ok_risk and not m.vetoed)}
        if not ok_lots:
            mismatches.append(f"fill {f['key']} @{f['open_ct']}: lots {f['lots']} vs mirror {m.lots}")
        if not ok_risk:
            mismatches.append(f"fill {f['key']} @{f['open_ct']}: risk ${f['risk_usd']:.2f} vs mirror ${m.risk_usd:.2f}")
        if m.vetoed:
            mismatches.append(f"fill {f['key']} @{f['open_ct']}: the mirror REFUSES this order ({m.veto_reason}) and the arm took it")
        if f["cfg"].get("malformed"):
            mismatches.append(f"fill {f['key']}: {f['cfg']['malformed']}")
        elif f["cfg"] and abs(float(f["cfg"].get("cfg_risk_pct", -1)) - pct) > 1e-9:
            mismatches.append(f"fill {f['key']}: the row's configured percent {f['cfg'].get('cfg_risk_pct')} "
                              f"is not the preset's {pct}")
        rows.append(row)
        eq += f["r"] * f["risk_usd"]
    floored = sum(1 for r in rows if r["floored_to_min_lot"])
    return {"risk_percent": pct, "max_risk_pct": maxpct, "deposit": float(deposit),
            "end_equity": round(eq, 2), "fills": len(rows), "rows": rows,
            "floored_to_min_lot": floored, "mismatches": mismatches,
            "verdict": "PASS" if rows and not mismatches else "FAIL" if mismatches else "NO-FILLS",
            "why": ("every fill's lots and risk equal the python mirror at the equity the fill "
                    "had" if rows and not mismatches else
                    "no fill closed in this window — there is no sizing to certify"
                    if not rows else "; ".join(mismatches[:6]))}


def stance_governor_audit(fills: list[dict], *, preset: dict, deposit: float,
                          offset_min: int) -> dict:
    """The governor, MODELLED on the pass's own equity path and cross-checked against its entries.

    The EA's governor reads `AccountInfoDouble(ACCOUNT_EQUITY)` on every tick and latches its
    daily-loss breaker for the rest of the UTC day; this model walks the same path at the only
    resolution a closed-trade record allows — after each close — and asks the one question that
    can be answered: would a declared rule have refused an entry the arm took?

    A DAY WHERE A RULE BINDS AND AN ENTRY FOLLOWS IT IS A DISAGREEMENT. A window where no rule
    ever binds is reported VACUOUS, in that word, because "the governor behaved" and "the "
    "governor was never asked" are different claims and only one of them is evidence.
    """
    cap_pct = float(preset.get("InpDailyLossCapPct", 0) or 0)
    best_pct = float(preset.get("InpPropBestDayPct", 0) or 0)
    target_pct = float(preset.get("InpPropTargetPct", 0) or 0)
    account = float(preset.get("InpPropAccountSize", 0) or 0)
    # THE BEST-DAY CAP IS NOT `account x best_pct`. MEASURED 2026-09-22 beside the EA's own
    # `PropDayProfitCapUsd()` (mql5/MIDASTOUCH/MidastouchAI.mq5): it is `size x InpPropTargetPct/100
    # x InpPropBestDayPct/100`, i.e. 5% x 20% = 1% of the account = **$250/day** here, not $5,000.
    # Read as $5,000 this model would need a day twenty times larger before the rule could be seen
    # to bind, so its VACUOUS verdict would have been a false negative dressed as evidence — and
    # the number is the one the venue's Best Day rule is actually enforced at. The research mirror
    # (`scripts/gold_governed_wfo.py`) has always used the product; this brings the parity stance
    # to the same rule. A preset that declares a best-day share but NO target cannot have this cap
    # computed at all, and is refused rather than guessed.
    best_cap_usd = account * target_pct / 100.0 * best_pct / 100.0
    modelled = list(GOVERNOR_MODELLED)
    unmodelled = list(GOVERNOR_NOT_MODELLED)
    if best_pct > 0 and target_pct <= 0:
        modelled = [r for r in modelled if not r.startswith("best-day")]
        unmodelled = unmodelled + [
            f"the best-day cap (the preset declares InpPropBestDayPct={best_pct:g} with "
            f"InpPropTargetPct={target_pct:g}; the EA's rule is a SHARE OF THE TARGET, so with no "
            f"target the cap cannot be computed and is refused, not guessed)"]
        best_cap_usd = 0.0
    if cap_pct <= 0 and best_cap_usd <= 0:
        return {"verdict": "NOT-ARMED", "modelled_rules": modelled,
                "not_modelled": unmodelled, "days": [], "blocks_modelled": 0,
                "coincident_entries": [], "best_cap_usd": best_cap_usd,
                "why": "the preset declares no daily cap and no computable best-day cap — the "
                       "governor has no rule to exercise, so this stance certifies nothing "
                       "about it"}
    def iso(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def utc_day(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")

    shift = offset_min * 60
    # The EQUITY PATH is walked in close order; an entry is bucketed by the UTC day it was TAKEN,
    # because that is the day whose rules gate it (the EA's breaker resets at the UTC roll).
    entries_by_day: dict[str, list[dict]] = {}
    for f in sorted(fills, key=lambda x: x["open_ct"]):
        entries_by_day.setdefault(utc_day(f["open_ct"] - shift), []).append(
            {"key": f["key"], "open_utc": f["open_ct"] - shift, "close_utc": f["close_ct"] - shift})
    days: dict[str, dict] = {}
    eq = float(deposit)
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        at = f["close_ct"] - shift
        d = days.setdefault(utc_day(at), {"day": utc_day(at), "open_equity": eq, "low_equity": eq,
                                         "end_equity": eq, "cap_pct": cap_pct,
                                         "best_cap_pct": best_pct,
                                         "best_cap_target_pct": target_pct,
                                         "best_cap_usd": best_cap_usd,
                                         "cap_breach_at": None, "best_cap_hit_at": None})
        eq += f["r"] * f["risk_usd"]
        d["end_equity"] = eq
        d["low_equity"] = min(d["low_equity"], eq)
        # the breaker latches on the tick the loss is SEEN, i.e. at or before this close
        if cap_pct > 0 and d["cap_breach_at"] is None and d["open_equity"]:
            loss_pct = (d["open_equity"] - d["low_equity"]) / d["open_equity"] * 100.0
            if loss_pct >= cap_pct:
                d["cap_breach_at"] = at
        if best_pct > 0 and d["best_cap_hit_at"] is None and d["best_cap_usd"] > 0:
            if eq - d["open_equity"] >= d["best_cap_usd"]:
                d["best_cap_hit_at"] = at
    coincident: list[dict] = []
    blocks = 0
    for day, d in days.items():
        d["loss_pct_peak"] = round((d["open_equity"] - d["low_equity"]) / d["open_equity"] * 100.0, 4) \
            if d["open_equity"] else 0.0
        d["headroom_pct"] = round(cap_pct - d["loss_pct_peak"], 4) if cap_pct else None
        for rule, at in (("daily loss cap", d["cap_breach_at"]),
                         ("best-day cap", d["best_cap_hit_at"])):
            if at is None:
                continue
            blocks += 1
            for e in entries_by_day.get(day, []):
                if e["open_utc"] >= at:
                    coincident.append({"day": day, "rule": rule, "refused_from_utc": iso(at),
                                       "entry_open_utc": iso(e["open_utc"]), "key": e["key"]})
        d["entries"] = [{"key": e["key"], "open_utc": iso(e["open_utc"]),
                         "close_utc": iso(e["close_utc"])}
                        for e in entries_by_day.get(day, [])]
        d["end_equity"] = round(d["end_equity"], 2)
        for k in ("cap_breach_at", "best_cap_hit_at"):
            d[k] = None if d[k] is None else iso(d[k])
    # HOW FAR THIS WINDOW IS FROM THE CAP, IN THE UNIT THAT DECIDES IT — full stops. A bare
    # "VACUOUS" says the governor was never asked and leaves the reader to guess whether that is
    # one bad day away or unreachable, and for this arm, at this risk, it is the SECOND. MEASURED
    # 2026-09-22 on the tick-covered window: the worst UTC day there is -1.007R and the realised
    # risk per trade is ~0.16% of the equity it was taken on (the venue's min lot floors it), so a
    # 3% day would take about nineteen consecutive full stops INSIDE one day. That is a
    # measurement, and it is computed from THIS pass's own fills rather than quoted.
    worst_stop_pct = 0.0
    for f in fills:
        rec = days.get(utc_day(f["open_ct"] - shift))
        if rec and rec.get("open_equity"):
            worst_stop_pct = max(worst_stop_pct, f["risk_usd"] / rec["open_equity"] * 100.0)
    worst_day = max((d["loss_pct_peak"] for d in days.values()), default=0.0)
    reachability_note = ""
    if cap_pct > 0 and worst_stop_pct > 0:
        stops = int(math.ceil(cap_pct / worst_stop_pct - 1e-9))
        reachability_note = (
            f" At this window's own realised risk per trade ({worst_stop_pct:.3f}% of equity at "
            f"its largest), a {cap_pct:g}% day would take {stops} consecutive full stops inside "
            f"ONE UTC day, and the window's worst day is {worst_day:.3f}% "
            f"({worst_day / cap_pct * 100:.1f}% of the cap): the cap is not one bad day away, it is "
            f"unreachable by this strategy at this risk, and the refusal path is exercised by the "
            f"DERIVED-RISK leg (`--breaker-stress`), which keeps this cap and moves the risk.")
    if coincident:
        verdict, why = "FAIL", "; ".join(
            f"{c['rule']} would have refused entries from {c['refused_from_utc']} on "
            f"{c['day']} and the arm entered at {c['entry_open_utc']}" for c in coincident[:4])
    elif blocks:
        verdict, why = "PASS", (f"{blocks} modelled rule(s) bound in this window and no entry "
                                f"followed any of them")
    else:
        verdict, why = "VACUOUS", (
            f"no modelled rule bound in this window (largest day drawdown "
            f"{max((d['loss_pct_peak'] for d in days.values()), default=0.0):.3f}% of a "
            f"{cap_pct:g}% cap), so the governor was never asked." + reachability_note)
    return {"verdict": verdict, "modelled_rules": modelled,
            "not_modelled": unmodelled, "best_cap_usd": best_cap_usd,
            "best_cap_basis": (f"target {target_pct:g}% x best-day {best_pct:g}% x size "
                               f"${account:,.0f} = ${best_cap_usd:,.2f}/UTC day (the EA's "
                               f"PropDayProfitCapUsd())"),
            "days": list(days.values()),
            "blocks_modelled": blocks, "coincident_entries": coincident, "why": why}


def measure_contract_spec(symbol: str = "XAUUSD"):
    """The venue's contract terms for the sizing mirror, MEASURED rather than read off a spec
    field that has been wrong before ($100 per unit per lot vs the spec's $10).

    `verify_sizing_live.measure_basis` is the measurement, reused rather than re-implemented: a
    second `order_calc_profit` call site is a second answer to "what is a lot worth here", which
    is the failure this repository keeps paying for. Returns (spec, refusal_reason).
    """
    try:
        import MetaTrader5 as mt5
        import verify_sizing_live as VSL
        from midas_prop.execution.prop_execution import ContractSpec
    except Exception as exc:                                     # noqa: BLE001
        return None, f"the sizing verifier or the bridge is unavailable ({exc})"
    if not mt5.initialize():
        return None, f"initialize() failed ({mt5.last_error()})"
    info = mt5.symbol_info(symbol)
    if info is None:
        return None, f"symbol_info({symbol}) returned None ({mt5.last_error()})"
    basis, detail = VSL.measure_basis(mt5, symbol, float(info.volume_min))
    if basis is None:
        return None, f"could not measure a dollar basis for {symbol} ({detail})"
    return ContractSpec(symbol=symbol, min_lot=float(info.volume_min),
                        lot_step=float(info.volume_step), max_lot=float(info.volume_max),
                        digits=int(info.digits), usd_per_unit_per_lot=float(basis),
                        basis="order_calc_profit",
                        tick_value_field=float(info.trade_tick_value)), ""


def run_live_stance(mode: str, spec: dict, *, contract, preset_path: Path | str = LIVE_PRESET,
                    expert: str = EXPERT) -> dict:
    """One tester pass in the arm's OWN stance + the two account-layer audits.

    The pass is deliberately NOT compared key-by-key against the python engine: the engine of
    record is a BAR model and this stance runs the LIVE path, whose fill mechanics are the arm's
    own (the divergence the BAR pass documents). What is comparable here is the ACCOUNT LAYER —
    the size of every fill and the rules that decide whether an entry happens at all — and that
    is what this returns a verdict for.
    """
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    offset_min = assert_server_offset(spec)
    declared = read_preset_inputs(preset_path)
    inputs = live_stance_inputs(mode, t0, t1, offset_min=offset_min, preset=preset_path)
    tag = f"{spec['tag']}_{TAG_MODE_CODE[mode]}_LST"
    deposit = float(T._BASE_TESTER_INI.get("Deposit", 0) or 0)
    if deposit <= 0:
        return {"verdict": "REFUSED", "refused_for": "the tester deposit is not declared, so "
                "the mirror has no equity basis to size from"}
    print(f"  live stance: tag={tag} arm={declared.get('InpArmTag')} "
          f"risk={declared.get('InpRiskPercent')}% max={declared.get('InpMaxRiskPct')}% "
          f"governor={declared.get('InpPropGuard')} cap={declared.get('InpDailyLossCapPct')}% "
          f"deposit=${deposit:,.0f} — the EA's LIVE path, in the tester", flush=True)
    snaps = T.journal_snapshots()
    res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert,
                     model=spec.get("model"))
    ticks = dict(res.get("tick_model") or {})
    print(f"    tick model: {str(ticks.get('used', 'unknown')).upper()} — "
          f"{ticks.get('evidence', 'no tick-model statement in this pass')}", flush=True)
    time.sleep(10)                       # agent flushes the journal + ledger after the report
    arm_tag = str(declared.get("InpArmTag", ""))
    cands = stance_ledger_candidates(arm_tag)
    if not cands:
        return {"verdict": "REFUSED", "tick_model": ticks, "preset": str(preset_path),
                "arm_tag": arm_tag, "declared": {k: declared[k] for k in ACCOUNT_LAYER_INPUTS},
                "refused_for": f"no tester-agent ledger named for tag {arm_tag} — the live path "
                               f"wrote no fill rows, so there is nothing to certify"}
    path = cands[0]
    fills, problems = parse_stance_fills(path)
    sizing = stance_sizing_audit(fills, preset=declared, spec=contract, deposit=deposit)
    gov = stance_governor_audit(fills, preset=declared, deposit=deposit, offset_min=offset_min)
    print("  " + "-" * 66)
    print(f"  live stance {mode}: {len(fills)} closed fill(s) in {path.name}; "
          f"SIZING {sizing['verdict']}"
          + (f" ({sizing['floored_to_min_lot']}/{sizing['fills']} floored to the venue's min lot)"
             if sizing["fills"] else ""))
    print(f"  live stance {mode}: GOVERNOR {gov['verdict']} — {gov['why']}")
    for m in sizing["mismatches"][:6]:
        print(f"    sizing: {m}")
    verdict = ("FAIL" if sizing["verdict"] == "FAIL" else
               "REFUSED" if sizing["verdict"] == "NO-FILLS" else "PASS")
    return {"mode": mode, "tag": tag, "ledger": path.name, "tick_model": ticks,
            "preset": str(preset_path),
            "declared": {k: declared[k] for k in ACCOUNT_LAYER_INPUTS},
            "deposit": deposit, "server_offset_min": offset_min,
            "fills": len(fills), "ledger_problems": problems,
            "fill_open_ct": sorted(f["open_ct"] for f in fills),
            # THE PATH ITSELF, not just how many fills it made: `--breaker-stress` derives the risk
            # per trade that brings the daily cap into reach from THIS path (its R sequence and the
            # geometry each fill was sized on), because the derivation has to name a day the pass
            # will actually walk. Kept to the fields that derivation and the anchor model read.
            "fills_detail": [{"key": f["key"], "open_ct": f["open_ct"],
                              "close_ct": f["close_ct"], "dir": f.get("dir"),
                              "entry": f.get("entry"), "stop_d": f.get("stop_d"),
                              "risk_usd": f["risk_usd"], "r": f["r"]} for f in fills],
            "sizing": sizing, "governor": gov, "verdict": verdict,
            "why": (sizing["why"] if sizing["verdict"] != "PASS" else gov["why"])}


def stance_ledger_snapshot(tag: str, *, not_before: float | None = None) -> dict | None:
    """The newest tester-agent ledger for `tag`, WITH the provenance of the file itself.

    A stress verdict is a comparison between two passes, so which file each pass wrote has to be
    on the record: hash and mtime, the same discipline the deployer applies to a binary. Without
    it a reader cannot tell a fresh pass from a stale ledger that was still lying around.

    `not_before` is the FRESHNESS GATE and it is not decoration: the tester agent writes ONE file
    per arm tag, so a pass that writes nothing leaves the previous pass's ledger in place and the
    newest-by-mtime lookup would happily hand back the WRONG pass's fills — a comparison between a
    pass and itself, reported as a certificate. A ledger older than the pass that is supposed to
    have written it is returned as `stale`, never as fills.
    """
    cands = stance_ledger_candidates(tag)
    if not cands:
        return None
    p = cands[0]
    st = p.stat()
    snap = {"path": str(p), "sha256_8": hashlib.sha256(p.read_bytes()).hexdigest()[:8],
            "bytes": st.st_size,
            "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")}
    if not_before is not None and st.st_mtime < not_before:
        snap["stale"] = (f"the ledger's mtime predates this pass by "
                         f"{not_before - st.st_mtime:.0f}s — the tester agent wrote nothing, so "
                         f"these fills belong to an earlier pass and could not be graded")
    return snap


def _iso_ct(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_day_ct(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")


def governor_prediction(fills: list[dict], *, cap_pct: float, deposit: float,
                        offset_min: int) -> dict:
    """What a declared daily-loss cap WOULD refuse, on the path THESE fills walk.

    THE SEPARATION IS THE WHOLE VALUE. The fills handed in come from a pass run with the governor
    OFF, so the equity path is the strategy's own and the prediction cannot be a restatement of
    what the EA actually did. Handing this a governed pass's fills would produce an audit that can
    only ever agree with itself — the difference between a certificate and a tautology.

    Resolution is the close that breaches. The boundary is NAMED (`boundary`) rather than rounded:
    an entry on the breaching bar itself may be taken just before the tick that latches the
    breaker or just after, and neither ordering is a disagreement to report as one.

    With `cap_pct` above every day's loss (the `inf` probe), this is also the day-drawdown
    measurement the stress threshold is derived from — one walk, one meaning.
    """
    shift = offset_min * 60
    eq = float(deposit)
    days: dict[str, dict] = {}
    day = None
    anchor = eq
    breach = None
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        at = f["close_ct"] - shift
        d = _utc_day_ct(at)
        if d != day:
            day, anchor = d, eq
        eq += f["r"] * f["risk_usd"]
        rec = days.setdefault(d, {"day": d, "open_equity": anchor, "low_equity": eq,
                                  "end_equity": eq})
        rec["low_equity"] = min(rec["low_equity"], eq)
        rec["end_equity"] = eq
        if breach is None and cap_pct > 0 and anchor:
            loss_pct = (anchor - rec["low_equity"]) / anchor * 100.0
            if loss_pct >= cap_pct:
                breach = {"day": d, "at_ct": f["close_ct"], "from_utc": _iso_ct(at),
                          "day_open_equity": round(anchor, 2), "equity_at_breach": round(eq, 2),
                          "loss_pct": round(loss_pct, 4), "cap_pct": cap_pct}
    for d in days.values():
        d["loss_pct_peak"] = (round((d["open_equity"] - d["low_equity"]) / d["open_equity"] * 100.0, 4)
                              if d["open_equity"] else 0.0)
        d["end_equity"] = round(d["end_equity"], 2)
    absent: list[dict] = []
    present: list[dict] = []
    boundary: list[dict] = []
    if breach is not None:
        for f in sorted(fills, key=lambda x: x["open_ct"]):
            row = {"open_ct": f["open_ct"], "dir": f["dir"],
                   "open_utc": _iso_ct(f["open_ct"] - shift)}
            if _utc_day_ct(f["open_ct"] - shift) != breach["day"]:
                present.append(row)
            elif f["open_ct"] > breach["at_ct"]:
                absent.append(row)
            elif f["open_ct"] == breach["at_ct"]:
                boundary.append(row)
            else:
                present.append(row)
    return {"breach": breach, "days": sorted(days.values(), key=lambda x: x["day"]),
            "largest_day_loss_pct": max((d["loss_pct_peak"] for d in days.values()), default=0.0),
            "must_be_absent": absent, "must_be_present": present, "boundary": boundary}


def governor_stress_compare(prediction: dict, ungoverned_ct: list[int], governed_ct: list[int],
                            *, cap: float, dd: float,
                            dd_basis: str = "the largest day drawdown that still had an entry "
                                           "after it",
                            cap_basis: str | None = None) -> tuple[str, str, dict]:
    """Grade one governed pass against the prediction read off the ungoverned one.

    THE VERDICT IS THE DISAGREEMENT, not a score: an entry the mirror says the cap refuses and the
    EA took anyway, an entry the mirror says survives and the governed pass does not hold, or an
    entry that appears in the governed pass and was never on the ungoverned path at all — the last
    one is the quietest failure of the three and the only one that cannot be explained by the
    governor, since a governor that only refuses can never ADD a trade.

    Pure: no terminal, no ledger, no clock. It is the part of the stress a test can hold still.
    """
    g_set = set(governed_ct)
    u_set = set(ungoverned_ct)
    refused_ok = [r for r in prediction["must_be_absent"] if r["open_ct"] not in g_set]
    refused_bad = [r for r in prediction["must_be_absent"] if r["open_ct"] in g_set]
    kept_ok = [r for r in prediction["must_be_present"] if r["open_ct"] in g_set]
    kept_bad = [r for r in prediction["must_be_present"] if r["open_ct"] not in g_set]
    unexpected = sorted(g_set - u_set)
    verdict = ("GOVERNED-PASS" if (refused_ok and not refused_bad and not kept_bad
                                   and not unexpected) else "GOVERNED-FAIL")
    # `cap_basis` is the word for HOW this pass made the rule reachable, because the two legs make
    # it reachable in opposite ways: `--governor-stress` derives the cap (so the cap is the
    # construction), `--breaker-stress` keeps the shipping cap and derives the risk (so the risk
    # is the construction). A sentence that names the wrong one misattributes the whole result.
    basis = cap_basis or (f"derived from {dd_basis} on the ungoverned path, {dd:.4f}%")
    if verdict == "GOVERNED-PASS":
        why = (f"at a cap of {cap:g}% ({basis}), the mirror predicted "
               f"{len(refused_ok)} refusal(s) on {prediction['breach']['day']} from "
               f"{prediction['breach']['from_utc']} and the governed EA took none of them, while "
               f"taking all {len(kept_ok)} entr(y/ies) the mirror said would survive. It certifies "
               f"the governor's MACHINERY at a threshold that BINDS.")
    else:
        bits = []
        if refused_bad:
            bits.append(f"{len(refused_bad)} entry(ies) the mirror said the cap refuses and the "
                        f"governed EA TOOK anyway "
                        f"({', '.join(_iso_ct(r['open_ct']) for r in refused_bad[:3])})")
        if kept_bad:
            bits.append(f"{len(kept_bad)} entry(ies) the mirror said survive and the governed "
                        f"pass does NOT hold "
                        f"({', '.join(_iso_ct(r['open_ct']) for r in kept_bad[:3])})")
        if unexpected:
            bits.append(f"{len(unexpected)} entry(ies) in the governed pass that were never on "
                        f"the ungoverned path ({', '.join(_iso_ct(c) for c in unexpected[:3])})")
        why = "; ".join(bits) or "the two passes disagree and no single clause names it"
    return verdict, why, {"refused_as_predicted": len(refused_ok),
                          "refused_but_taken": len(refused_bad),
                          "survived_as_predicted": len(kept_ok),
                          "lost_without_prediction": len(kept_bad),
                          "unexpected_entries": len(unexpected)}


def derive_binding_threshold(fills: list[dict], *, deposit: float, offset_min: int) -> dict:
    """The LARGEST daily-loss cap that still has an entry left to refuse, on this path.

    WHY NOT "HALF THE LARGEST DAY DRAWDOWN". MEASURED 2026-09-22 on the arm's own window: half of
    the largest day drawdown (0.318% -> 0.15%) breaches on a bar with **nothing after it on that
    day**, so the cap binds and refuses no entry — a threshold that produces no prediction at all.
    A cap is only a test if the breach lands BEFORE an entry, so the derivation is: walk the
    ungoverned path in close order and keep every (close, cap) pair where the day's drawdown is
    positive AND at least one entry on that day comes after that close. Take the LARGEST such
    drawdown — the most demanding threshold the window can still answer — then truncate it to two
    decimals, which can only move the breach earlier (more refusals, and the guarantee survives).

    A day whose losses all come last has no such close, and is named as skipped rather than
    silently dropped: the reason a window cannot be asked the question is part of the answer.
    """
    shift = offset_min * 60
    eq = float(deposit)
    day = None
    anchor = eq
    candidates: list[dict] = []
    skipped: list[dict] = []
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        at = f["close_ct"] - shift
        d = _utc_day_ct(at)
        if d != day:
            day, anchor = d, eq
        eq += f["r"] * f["risk_usd"]
        if not anchor:
            continue
        dd_pct = (anchor - eq) / anchor * 100.0
        after = [g for g in fills
                 if _utc_day_ct(g["open_ct"] - shift) == d and g["open_ct"] > f["close_ct"]]
        if dd_pct <= 0:
            continue
        if after:
            candidates.append({"day": d, "at_ct": f["close_ct"], "drawdown_pct": round(dd_pct, 4),
                               "entries_after": len(after),
                               "open_ct_after": sorted(g["open_ct"] for g in after)})
        else:
            skipped.append({"day": d, "at_ct": f["close_ct"], "drawdown_pct": round(dd_pct, 4),
                            "why": "the day's loss lands on its last fill, so this cap would "
                                   "refuse nothing"})
    if not candidates:
        return {"cap_pct": None, "candidates": [], "skipped": skipped,
                "why": ("no positive day drawdown in this path is followed by another entry on "
                        "the same day, so no cap can be derived that binds with something left "
                        "to refuse")}
    best = max(candidates, key=lambda c: c["drawdown_pct"])
    cap = float(int(best["drawdown_pct"] * 100.0)) / 100.0
    if cap <= 0:
        cap = best["drawdown_pct"]          # identical arithmetic as the walk: `>=` is exact
    return {"cap_pct": cap, "chosen": best, "candidates": candidates, "skipped": skipped,
            "rule": ("truncate to 2dp the largest day drawdown that is followed by another entry "
                     "on that day; the breach therefore lands at or before that close and at "
                     "least one entry is left for the governor to refuse")}


def run_governor_stress(mode: str, spec: dict, *, contract,
                        preset_path: Path | str = LIVE_PRESET, expert: str = EXPERT,
                        shipping: dict | None = None) -> dict:
    """The governor at a threshold DERIVED to bind, verified against the ungoverned path.

    THE TWO PASSES. `LSU` runs the arm's live path with the governor OFF: that is the strategy's
    own sequence, and it is the only thing the prediction may be read from. `LSG` runs the same
    path with the governor ON at a cap derived to bind (half the largest day drawdown `LSU`"
    "made). The verification is then specific and falsifiable: every entry the mirror said must be
    absent from `LSG` is absent, every entry it said must survive did survive, and no entry
    appears that was never on the ungoverned path at all.

    WHAT IT DOES NOT DO, stated here: it does not move the shipping 3% cap, does not stand in for
    the shipping stance's VACUOUS verdict, and does not model the trailing shield floor (named in
    `not_modelled`, as everywhere else in this section).
    """
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    offset_min = assert_server_offset(spec)
    declared = read_preset_inputs(preset_path)
    base = live_stance_inputs(mode, t0, t1, offset_min=offset_min, preset=preset_path)
    deposit = float(T._BASE_TESTER_INI.get("Deposit", 0) or 0)
    if deposit <= 0:
        return {"verdict": "REFUSED", "why": GOVERNOR_STRESS_WHY,
                "refused_for": "the tester deposit is not declared, so the mirror has no equity "
                               "basis to derive a binding threshold from"}
    code = TAG_MODE_CODE[mode]
    arm_tag = str(declared.get("InpArmTag", ""))
    out: dict = {"why": GOVERNOR_STRESS_WHY, "deposit": deposit,
                 "not_modelled": list(GOVERNOR_NOT_MODELLED), "passes": {},
                 "cap_modelled": "the daily-loss cap only (the derived threshold is a daily-loss "
                                 "cap; the best-day cap is graded by the shipping stance's own "
                                 "day table at its correct $/day, target% x best-day% x size)"}

    def run(suffix: str, inputs: dict, label: str) -> tuple[list[dict], dict | None]:
        tag = f"{spec['tag']}_{code}_{suffix}"
        print(f"  governor stress {suffix}: tag={tag} — {label}, the EA's LIVE path, in the "
              f"tester", flush=True)
        started = time.time()
        res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert,
                         model=spec.get("model"))
        ticks = dict(res.get("tick_model") or {})
        time.sleep(10)                    # agent flushes the ledger after its report
        snap = stance_ledger_snapshot(arm_tag, not_before=started - 5)
        if snap is None:
            out["passes"][suffix] = {"tag": tag, "ledger": None, "tick_model": ticks}
            return [], ticks
        if snap.get("stale"):
            out["passes"][suffix] = {"tag": tag, "ledger": snap, "fills": None, "stale": True,
                                    "tick_model": ticks}
            print(f"    {suffix}: REFUSED — {snap['stale']}", flush=True)
            return [], ticks
        fills, problems = parse_stance_fills(Path(snap["path"]))
        out["passes"][suffix] = {"tag": tag, "ledger": snap, "fills": len(fills),
                                "problems": problems, "tick_model": ticks}
        print(f"    {suffix}: {len(fills)} closed fill(s), ledger {snap['sha256_8']} "
              f"({snap['mtime_utc']})", flush=True)
        return fills, ticks

    # PASS U: the governor OFF — the path the prediction is read from.
    u_inputs = dict(base)
    u_inputs["InpPropGuard"] = "false"
    u_fills, u_ticks = run("LSU", u_inputs, "governor OFF (the ungoverned path)")
    if not u_fills:
        u_snap = (out["passes"].get("LSU") or {}).get("ledger") or {}
        return {**out, "verdict": "REFUSED",
                "refused_for": (u_snap.get("stale") or
                                "the ungoverned pass closed no fills, so there is no equity path "
                                "to predict a refusal on")}
    probe = governor_prediction(u_fills, cap_pct=float("inf"), deposit=deposit,
                                offset_min=offset_min)
    dd = float(probe["largest_day_loss_pct"])
    derived = derive_binding_threshold(u_fills, deposit=deposit, offset_min=offset_min)
    dd_basis = (f"the largest day drawdown that still had an entry after it "
                f"(the path's largest overall was {dd:.4f}%, and its breach lands on the day's "
                f"last fill, so a cap derived from it refuses nothing)")
    cap = derived.get("cap_pct")
    if cap is None:
        return {**out, "verdict": "NO-BIND", "ungoverned": {"fills": len(u_fills),
                "largest_day_loss_pct": dd, "days": probe["days"]},
                "derivation": derived, "refused_for": None, "why_verdict": derived["why"]}
    prediction = governor_prediction(u_fills, cap_pct=cap, deposit=deposit, offset_min=offset_min)
    if prediction["breach"] is None or not prediction["must_be_absent"]:
        return {**out, "verdict": "NO-BIND", "stress_cap_pct": cap, "derivation": derived,
                "ungoverned": {"fills": len(u_fills), "days": probe["days"]},
                "why_verdict": (f"even the largest derived cap ({cap:g}%) breaches with no entry "
                                f"left to refuse on this window")}

    # PASS G: the governor ON at the derived cap.
    g_inputs = dict(base)
    g_inputs["InpDailyLossCapPct"] = f"{cap:g}"
    g_fills, g_ticks = run("LSG", g_inputs, f"governor ON at the DERIVED cap {cap:g}%")
    if not g_fills:
        g_snap = (out["passes"].get("LSG") or {}).get("ledger") or {}
        return {**out, "verdict": "REFUSED", "stress_cap_pct": cap, "prediction": prediction,
                "refused_for": (g_snap.get("stale") or
                                "the governed pass closed no fills — a pass that traded nothing "
                                "cannot be said to have refused the right entries")}

    u_ct = [f["open_ct"] for f in u_fills]
    g_ct = [f["open_ct"] for f in g_fills]
    chosen_dd = float((derived.get("chosen") or {}).get("drawdown_pct", dd))
    verdict, why_verdict, comparison = governor_stress_compare(prediction, u_ct, g_ct, cap=cap,
                                                               dd=chosen_dd, dd_basis=dd_basis)
    print(f"  governor stress: cap {cap:g}% derived from the ungoverned path (largest day loss "
          f"{dd:.3f}%), breach {prediction['breach']['from_utc']} on "
          f"{prediction['breach']['day']}")
    print(f"  governor stress: {verdict} — {why_verdict}")
    return {**out, "verdict": verdict, "stress_cap_pct": cap,
            "derivation": {**derived,
                           "largest_day_loss_pct_ungoverned": dd,
                           "chosen_drawdown_pct": chosen_dd,
                           "chosen_because": dd_basis,
                           "shipping_cap_pct": float(declared.get("InpDailyLossCapPct", 0) or 0),
                           "this_is_a_stress_threshold_not_the_shipping_one": True},
            "ungoverned": {"fills": len(u_fills), "open_ct": sorted(u_ct),
                           "days": probe["days"],
                           "same_entries_as_the_shipping_stance": (
                               None if not (shipping or {}).get("fill_open_ct") else
                               sorted(u_ct) == sorted(shipping["fill_open_ct"]))},
            "governed": {"fills": len(g_fills), "open_ct": sorted(g_ct)},
            "prediction": {k: prediction[k] for k in ("breach", "must_be_absent",
                                                      "must_be_present", "boundary")},
            "verification": comparison,
            "why_verdict": why_verdict}


# --- the DERIVED-RISK leg: the SHIPPING 3% cap, made reachable by the risk per trade ---------
# THE TWO STRESS LEGS ANSWER OPPOSITE QUESTIONS and neither replaces the other:
#   * `--governor-stress` moves the CAP until it binds. Its certificate is about the governor's
#     ARITHMETIC, and it cannot be quoted for the 3% the arm runs.
#   * `--breaker-stress` keeps the cap AT 3% and moves the RISK PER TRADE until a 3% day exists on
#     the arm's own path. Its certificate is about the number in the preset.
# A reader who is handed one verdict without knowing which of the two it is will read it as the
# other, so each artifact carries its own paragraph (GOVERNOR_STRESS_WHY / BREAKER_STRESS_WHY) and
# neither may be quoted alone.
#
# WHY A CONSTRUCTION AT ALL, measured rather than assumed (2026-09-22, tick-covered window off the
# venue's own bars, the arm's mode and contract): the path makes nine fills, no UTC day contains
# more than three of them, and the largest day drawdown at a close still followed by an entry is
# -1.007R. At the shipping risk (0.25%/trade, and less wherever the venue's min lot floors the
# size) that is 0.16% of the day's opening equity, so the 3% cap would need ~19 consecutive full
# stops inside one UTC day. The window CANNOT be widened to find a bigger drawdown either: this
# program only certifies on the venue's real ticks (2026-09-04 onward), so every candidate outside
# that span is demoted to REFUSED by `recorded_verdict`. That leaves one honest lever, and it is
# the lever the venue's rule is actually denominated in: the risk per trade.
#
# R IS RISK-INVARIANT, which is what makes the construction legitimate rather than a second
# strategy: a trade's R is its profit over its own risk, and the ENTRY, the stop distance, the
# target and the timeout all decide themselves without reference to the lot size. Raising the risk
# per trade therefore moves WHEN the rule binds and the ORDER of nothing; the entries are the
# strategy's own, and the artifact records whether the derived-risk path took exactly the same
# entries as the shipping stance (it should, and a difference would be a finding, not a detail).


def boundary_bar(m15: list[dict], when_ct: int) -> dict | None:
    """The bar that CONTAINS a day boundary — the only price information a bar series has for it.

    WHY THIS EXISTS. `PropDayAnchorCheck()` takes `AccountInfoDouble(ACCOUNT_EQUITY)` on the first
    tick of the new day, so the day's opening equity INCLUDES the floating P&L of any position
    carried across the boundary — a walk over closed trades cannot see it, and MEASURED 2026-09-22
    it is not a detail: on 2026-09-11 the live path carries a short across the boundary and the day
    comes out 0.783R under the EA's anchor where a closed-trade walk says 0.632R.

    AND THE BAR DOES NOT PIN THE PRICE. MEASURED on the same day, twice, the hard way: the pass's
    own `DAILY BREAKER TRIPPED` line says the day fell 7.46% at the second close, and solving that
    for the anchor puts the boundary price at 4321.05 — inside the boundary bar (o 4320.76,
    h 4324.48, l 4316.11, c 4321.14) and $3.85 away from the PREVIOUS bar's close (4317.20), which
    is the number a "close of the bar ending at the boundary" rule would have used. That $3.85 is
    $108 of floating on the carried size, i.e. 0.43% of equity against a 3% cap — so the rule
    decides a 2.98%-vs-3.00% comparison and a bar series cannot settle it. Hence `breaker_walk`
    prices the anchor at the boundary bar's ADVERSE EXTREME (below): the difference between the
    extreme and a guess is the only part of this that can be made safe, and it is made safe in the
    direction that keeps a predicted breach predicted.
    """
    rows = [b for b in m15 if b["time"] <= when_ct < b["time"] + 900]
    if rows:
        return rows[0]
    after = [b for b in m15 if b["time"] > when_ct]
    return after[0] if after else None


def breaker_walk(fills: list[dict], *, deposit: float, offset_min: int,
                 m15: list[dict] | None = None) -> dict:
    """The EA's OWN UTC-day arithmetic, modelled: closed equity PLUS the floating at the roll.

    THE ANCHOR IS THE WHOLE POINT. A daily-loss cap is measured from the day's opening equity, and
    the EA opens a day on the first tick after 00:00 UTC — so any position carried across the roll
    contributes its floating P&L to that anchor. A close-to-close walk cannot see it, and the two
    disagree in BOTH directions (a position deep underwater at the roll makes the day's loss look
    SMALLER than the closes suggest). MEASURED 2026-09-22, and it is why this function exists: the
    first derived-risk pass came back NO-BIND after deriving 3.28%/trade from the closed basis —
    the ONE live-path day with an entry left to refuse (2026-09-11, breach 07:15Z, entry 14:00Z)
    carries a short across the roll whose floating was -0.146R at the boundary, so at 3.28% the
    EA's own day loss at that close was 2.54%, not the 3.30% the closed basis predicted.

    THE DAY IS THE PASS'S OWN DAY, WHICH IS THE VENUE'S, NOT UTC. `TimeUTCNow()` returns
    `TimeGMT()`, and INSIDE THE STRATEGY TESTER `TimeGMT()` IS THE VENUE'S CLOCK — so a pass rolls
    its day at SERVER midnight (UTC 22:00 at this venue's +120) while the live arm rolls at true
    UTC midnight. MEASURED 2026-09-22 by reading the pass's own journal: the EA prints
    `STALE feed — bar skipped` at 00:00:00 SERVER on each day of this window, and solving its
    `DAILY BREAKER TRIPPED: equity down 7.46%` line puts the anchor at that same instant (the bar
    opening then, not the one closing at UTC midnight, which is 3.85 dollars — and one extra
    incident — away). The day labels here are therefore SERVER days, and `day_clock` says so; a
    leg that certified the live arm's UTC-day instant would be certifying an instant this pass
    never had.

    EVERYTHING IS IN UNITS OF THE PASS'S OWN RISK PER TRADE (each fill's `risk_usd`), which is what
    makes the derivation risk-invariant: a derived risk r puts the day r x |low_units| percent
    down, because both the realised losses AND the boundary floating scale with the risk.

    THE BOUNDARY FLOATING IS PRICED AT THE BOUNDARY BAR'S ADVERSE EXTREME, and the direction is
    the point: a long is priced at the bar's LOW and a short at its HIGH, i.e. at the least
    favourable price the bar admits. That makes this walk's day loss the SMALLEST one compatible
    with the bar — so a breach predicted from it is a breach the pass must make whatever the tick
    inside that bar actually was, instead of a coin flip on a 2.98%-vs-3.00% comparison.

    `m15` (the venue's own bars, UTC-shifted) prices the boundary; without it the floating is 0 and
    this is the closed-basis walk — which the returned `m15_used` flag states, because a silent
    fallback here would be a different model wearing the same verdict.
    """
    shift = offset_min * 60
    rows = sorted(fills, key=lambda x: x["close_ct"])
    # THE PASS'S DAY = the SERVER day (see the note above): the ledger's epochs are the venue's
    # clock, so the day label is taken from them UNSHIFTED, and the boundary instant is server
    # midnight expressed on the bars' UTC axis.
    opens_by_day: dict[str, list[dict]] = {}
    for f in fills:
        opens_by_day.setdefault(_utc_day_ct(f["open_ct"]), []).append(f)
    days: dict[str, dict] = {}
    eq = float(deposit)
    carried: list[dict] = []
    day = None
    for f in rows:
        close_utc = f["close_ct"] - shift
        d = _utc_day_ct(f["close_ct"])
        risk_usd = float(f["risk_usd"])
        if d != day:
            # THE ROLL: closed equity so far, plus the floating of everything still open, priced at
            # the boundary bar's adverse extreme. The anchor is taken ONCE per day, like the EA.
            boundary_server = int(datetime.strptime(d, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp())      # server midnight, on the ledger's clock
            boundary_utc = boundary_server - shift      # the same instant on the bars' UTC axis
            bar = boundary_bar(m15, boundary_utc) if m15 else None
            float_usd = 0.0
            open_now: list[dict] = []
            for g in fills:
                if g["open_ct"] <= boundary_server < g["close_ct"]:
                    if bar is None or not g.get("stop_d") or not g.get("dir"):
                        open_now.append({"key": g["key"], "priced": False})
                        continue
                    per_unit = float(g["risk_usd"]) / float(g["stop_d"])
                    # ADVERSE EXTREME: a long is marked at the bar's low and a short at its high,
                    # which is the least favourable price the bar admits and therefore the
                    # SMALLEST anchor — the direction that keeps a predicted breach predicted.
                    adverse = float(bar["low"]) if float(g["dir"]) > 0 else float(bar["high"])
                    pl = (adverse - float(g["entry"])) * float(g["dir"]) * per_unit
                    float_usd += pl
                    open_now.append({"key": g["key"], "priced": True,
                                     "bar": {k: bar[k] for k in ("open", "high", "low", "close")},
                                     "adverse_price": adverse,
                                     "float_usd": round(pl, 2),
                                     "float_units": round(pl / risk_usd, 4)})
            if open_now:
                carried.append({"boundary_server_day": d, "boundary_utc": _iso_ct(boundary_utc),
                                "positions": open_now, "float_usd": round(float_usd, 2),
                                "float_units": round(float_usd / risk_usd, 4)})
            day = d
            days[d] = {"day": d, "anchor_closed_equity": round(eq, 2),
                       "boundary_float_usd": round(float_usd, 2),
                       "anchor_equity": round(eq + float_usd, 2),
                       "carried": [p["key"] for p in open_now],
                       "closes": [], "fills": 0}
        rec = days[d]
        eq += f["r"] * risk_usd
        # the day's running loss is measured FROM THE ANCHOR, so the low is relative to it
        units = (rec["anchor_equity"] - eq) / risk_usd
        after = [g for g in opens_by_day.get(d, []) if g["open_ct"] > f["close_ct"]]
        rec["closes"].append({"close_ct": f["close_ct"], "close_utc": _iso_ct(close_utc),
                              "close_server_day": _utc_day_ct(f["close_ct"]),
                              "key": f["key"], "r": f["r"], "equity": round(eq, 2),
                              "loss_units": round(units, 4),
                              "entries_after": len(after),
                              "entries_after_utc": sorted(_iso_ct(g["open_ct"] - shift)
                                                          for g in after)})
        rec["fills"] += 1
    for rec in days.values():
        # THE DAY'S LOW IS THE LARGEST POSITIVE LOSS, not the smallest number: these units are
        # positive when the day is down (the convention `derive_binding_risk` states at its own
        # `max`), so a `min` here reports the day's BEST moment as its worst and shrinks every
        # derived threshold with it.
        rec["low_units"] = round(max([c["loss_units"] for c in rec["closes"]] or [0.0]), 4)
        rec["end_equity"] = rec["closes"][-1]["equity"] if rec["closes"] else rec["anchor_equity"]
    return {"days": [days[d] for d in sorted(days)], "carried_over_the_roll": carried,
            "fills": fills, "m15_used": bool(m15),
            "day_clock": (f"the pass's own: days roll at SERVER midnight ({offset_min:+d} min from "
                          f"UTC), because TimeGMT() inside the strategy tester is the venue's "
                          f"clock. The LIVE arm's day is true UTC midnight, and this leg models "
                          f"the pass, not that instant."),
            "anchor_note": ("the day's anchor is the closed equity at the roll PLUS the floating of "
                            "every position open across it, marked at the boundary bar's ADVERSE "
                            "EXTREME (the EA's own PropDayAnchorCheck, priced in the only direction "
                            "a bar series cannot contradict: the smallest admissible anchor, so a "
                            "breach predicted from it is one the pass has to make).")}


def derive_binding_risk(walk: dict, *, cap_pct: float,
                        margin: float = BREAKER_STRESS_RISK_MARGIN,
                        max_risk_pct: float = 10.0) -> dict:
    """The risk per trade at which THIS path's own worst day reaches the cap, with an entry left.

    THE UNIT IS THE DAY, and the quantity is the day's RUNNING LOSS FROM THE EA'S OWN ANCHOR in
    units of the pass's risk per trade (see `breaker_walk`) — so the conversion is one line:
    risk% = cap% / |loss in units|, and it does not depend on the risk it is deriving.

    THE "FOLLOWED BY AN ENTRY" RULE IS NOT DECORATION. A threshold is only a test if the breach
    falls before something there is left to refuse; a day whose loss lands on its last fill can be
    asked nothing, and those closes are NAMED as skipped rather than quietly dropped.

    THE MARGIN is for the venue's lot step, which quantises the risk per trade DOWNWARD: at a
    nominal $820 the step is worth up to ~$41 here, i.e. ~5% — so a derivation with no margin can
    land at 2.99% and bind nothing. `max_risk_pct` refuses a derivation that has stopped describing
    this strategy: above it the pass is a different arm, not a stress of this one.
    """
    candidates: list[dict] = []
    skipped: list[dict] = []
    for d in walk["days"]:
        for c in d["closes"]:
            if c["loss_units"] <= 0:
                continue
            rec = {"day": d["day"], "at_ct": c["close_ct"], "at_utc": c["close_utc"],
                   "drawdown_r": c["loss_units"], "entries_after": c["entries_after"],
                   "entries_after_utc": c["entries_after_utc"]}
            if c["entries_after"]:
                candidates.append(rec)
            else:
                skipped.append({**rec, "why": ("the day's loss lands at or after its last entry, so "
                                              "a threshold derived here refuses nothing")})
    if not candidates:
        return {"risk_pct": None, "candidates": [], "skipped": skipped, "margin": margin,
                "why": ("no day on this path has a drawdown at a close that is followed by "
                        "another entry on that day, so no risk per trade can be derived that "
                        "binds with something left to refuse")}
    # THE SIGN CONVENTION IS THE TRAP IN THIS FUNCTION, so it is stated rather than implied: the
    # walk's `loss_units` is POSITIVE when the day is down (which is the whole point of the
    # quantity — it is the loss the cap is about), so the largest drawdown is a `max`. A `min`
    # would quietly pick the SMALLEST loss on the path and derive a risk threshold from the day the
    # governor is easiest on: plausible-looking, wrong, and it would bind nothing.
    best = max(candidates, key=lambda c: c["drawdown_r"])
    dd = abs(float(best["drawdown_r"]))
    needed = cap_pct / dd * margin
    risk_pct = math.ceil(needed * 100.0 - 1e-9) / 100.0
    if risk_pct > max_risk_pct:
        return {"risk_pct": None, "candidates": candidates, "skipped": skipped,
                "chosen": best, "margin": margin, "needed_risk_pct": needed,
                "max_risk_pct": max_risk_pct,
                "why": (f"this window would need {risk_pct:g}%/trade for a {cap_pct:g}% day, above "
                        f"the {max_risk_pct:g}% ceiling this leg will run: at that risk the pass "
                        f"would be a different arm rather than a stress of this one")}
    return {"risk_pct": risk_pct, "chosen": best, "candidates": candidates, "skipped": skipped,
            "margin": margin, "needed_risk_pct_before_margin": cap_pct / dd,
            "chosen_drawdown_r": dd,
            "rule": ("cap% / the largest day drawdown in R at a close still followed by an entry "
                     "on that day, times a declared margin for the venue's lot step, rounded UP to "
                     "2dp so the breach cannot land a hair under the cap"),
            "why": (f"{cap_pct:g}% over the -{dd:.3f}R day at {best['at_utc']} needs "
                    f"{cap_pct / dd:.3f}%/trade, carried to {risk_pct:g}%/trade with the "
                    f"{margin:g} margin")}


def breaker_prediction(walk: dict, *, cap_pct: float, risk_pct: float,
                       offset_min: int) -> dict:
    """What the SHIPPING cap WOULD refuse on this path, at this derived risk — EVERY day, not one.

    WHY NOT `governor_prediction`. That function reports the FIRST breach on the path, which is the
    right question for a cap DERIVED to bind (one threshold, one earliest refusal). A cap that is
    already fixed and a risk derived to reach it can bind on SEVERAL days — the breaker resets at
    every UTC roll — and the first of them may well be a day whose loss lands on its last fill.
    MEASURED 2026-09-22: with the first derived risk, the first breach on the live path was
    2026-09-11 and it refused nothing, while the derivation had been asked about a later close on
    the same day. Reporting only the first breach turned a window that could answer the question
    into a NO-BIND. So every breaching day contributes its own refusals, and `breach` names the
    first one that actually has something to refuse — the one the comparison is graded on.

    Resolution is the close that breaches, on the EA's own anchor (see `breaker_walk`). An entry
    opened on the breaching close itself is BOUNDARY, not graded: the latch happens on a tick
    inside that bar and neither ordering is a disagreement to report as one.
    """
    shift = offset_min * 60
    breaches: list[dict] = []
    absent: list[dict] = []
    boundary: list[dict] = []
    refused_ct: set[int] = set()
    boundary_ct: set[int] = set()
    for d in walk["days"]:
        hit = None
        for c in d["closes"]:
            if risk_pct > 0 and c["loss_units"] * risk_pct >= cap_pct:
                hit = c
                break
        if hit is None:
            continue
        day_abs: list[dict] = []
        for f in sorted((g for g in walk["fills"] if _utc_day_ct(g["open_ct"]) == d["day"]),
                        key=lambda x: x["open_ct"]):
            row = {"open_ct": f["open_ct"], "open_utc": _iso_ct(f["open_ct"] - shift),
                   "dir": f.get("dir")}
            if f["open_ct"] > hit["close_ct"]:
                day_abs.append(row)
            elif f["open_ct"] == hit["close_ct"]:
                boundary_ct.add(f["open_ct"])
                boundary.append(row)
        breaches.append({"day": d["day"], "at_ct": hit["close_ct"],
                         "from_utc": hit["close_utc"],
                         "day_anchor_equity": d["anchor_equity"],
                         "boundary_float_usd": d["boundary_float_usd"],
                         "loss_pct": round(abs(hit["loss_units"]) * risk_pct, 4),
                         "cap_pct": cap_pct, "refusals": len(day_abs)})
        absent += day_abs
        refused_ct |= {r["open_ct"] for r in day_abs}
    # EVERY ENTRY NOT PREDICTED ABSENT IS GRADED, on every day — not only on the days that breach.
    # Restricting `must_be_present` to the breaching day would make an over-refusal on any OTHER
    # day invisible to the comparison, which is the failure that would matter most: a governor
    # refusing trades it has no rule to refuse them with.
    present = [{"open_ct": f["open_ct"], "open_utc": _iso_ct(f["open_ct"] - shift),
                "dir": f.get("dir")}
               for f in sorted(walk["fills"], key=lambda x: x["open_ct"])
               if f["open_ct"] not in refused_ct and f["open_ct"] not in boundary_ct]
    first = next((b for b in breaches if b["refusals"]), None)
    return {"breach": first, "breaches": breaches,
            "days": [{"day": d["day"], "anchor_equity": d["anchor_equity"],
                      "boundary_float_usd": d["boundary_float_usd"],
                      "loss_pct_at_risk": round(abs(d["low_units"]) * risk_pct, 4),
                      "loss_units_low": d["low_units"], "fills": d["fills"],
                      "carried": d["carried"]} for d in walk["days"]],
            "largest_day_loss_pct": max((round(abs(d["low_units"]) * risk_pct, 4)
                                         for d in walk["days"]), default=0.0),
            "must_be_absent": absent, "must_be_present": present, "boundary": boundary,
            "rule": ("every UTC day whose loss FROM THE EA'S OWN ANCHOR reaches the cap contributes "
                     "the entries it would have refused; the graded one is the first that has any")}


def shield_exposure(fills: list[dict], *, size: float, maxdd_pct: float, deposit: float,
                    offset_min: int) -> dict:
    """Would the TRAILING SHIELD have refused anything on this path, at its shipped depth?

    THE ISOLATION HAS TO BE MEASURED, NOT DECLARED, and it is the condition this leg's verdict
    rests on. The derived risk per trade that makes a 3% DAY reachable also makes larger
    multi-day excursions reachable, and a shield refusal refuses the same entries the daily-cap
    prediction says must be PRESENT — which the comparison would then grade as a governor
    defect. So the walk below mirrors the EA's own `PropShieldFloor()`
    (max(size - maxdd, min(peak - maxdd, size)), peak = max(initial peak, equity)) close by close
    and reports every entry whose equity at that moment is at or below the floor.

    RESOLUTION, named: the peak is taken from closes, and the EA's peak also sees intrabar
    floating highs. That can only raise the floor toward the clamp, and the clamp is `size` — so a
    path whose close-based peak is already above `size + maxdd` has its floor PINNED at exactly
    `size` and no floating high can move it. Where that does not hold, this returns the headroom
    it did see and the pass refuses rather than certifying a pass whose isolation it cannot show.
    """
    shift = offset_min * 60
    maxdd = size * maxdd_pct / 100.0
    eq = float(deposit)
    peak = max(float(deposit), size)
    path: list[dict] = []
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        eq += f["r"] * f["risk_usd"]
        peak = max(peak, eq)
        floor = max(size - maxdd, min(peak - maxdd, size))
        path.append({"close_ct": f["close_ct"], "equity": eq, "floor": floor,
                     "headroom": eq - floor, "peak": peak})
    refused: list[dict] = []
    for f in sorted(fills, key=lambda x: x["open_ct"]):
        prior = [p for p in path if p["close_ct"] <= f["open_ct"]]
        if not prior:
            continue
        at = prior[-1]
        if at["headroom"] <= 0:
            refused.append({"key": f["key"], "open_utc": _iso_ct(f["open_ct"] - shift),
                            "equity": round(at["equity"], 2), "floor": round(at["floor"], 2)})
    tightest = min((p["headroom"] for p in path), default=0.0)
    pinned = bool(path) and path[-1]["peak"] - maxdd >= size
    return {"size": size, "maxdd_pct": maxdd_pct, "maxdd_usd": round(maxdd, 2),
            "floor_pinned_at_size": pinned,
            "min_headroom_usd": round(tightest, 2),
            "would_refuse": refused,
            "worst_point_utc": (min(path, key=lambda p: p["headroom"])["close_ct"] if path else None),
            "why": (("the shield would have refused " + str(len(refused)) + " entry(ies) on this "
                     "path") if refused else
                    (f"the shield never came within ${tightest:,.2f} of its floor on this path"
                     + (" (and its floor is pinned at the declared size, so intrabar floating "
                        "highs cannot raise it further)" if pinned else "")))}


def profit_ceiling_exposure(fills: list[dict], *, cap_usd: float, deposit: float,
                            offset_min: int) -> dict:
    """What the FIFTH-rule profit ceiling WOULD have refused on this path (measured, not modelled).

    The derived risk per trade raises the day's PROFIT as well as its loss, and the venue's Best
    Day ceiling is a fixed $/day (target% x best-day% x declared size = 5% x 20% x $25,000 = $250
    here), so at a stress risk the ceiling is reached on the first good day and would refuse entries
    the daily-cap prediction says must be present. The construction therefore switches it OFF by
    declaration — and this walk reports what it would have refused, so the isolation is visible
    rather than convenient. The shipping stance grades the ceiling at its own $/day; this leg
    grades the 3% cap.
    """
    shift = offset_min * 60
    days: dict[str, dict] = {}
    eq = float(deposit)
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        d = _utc_day_ct(f["close_ct"] - shift)
        rec = days.setdefault(d, {"day": d, "open_equity": eq, "hit_at": None, "high": eq})
        eq += f["r"] * f["risk_usd"]
        rec["high"] = max(rec["high"], eq)
        if rec["hit_at"] is None and cap_usd > 0 and eq - rec["open_equity"] >= cap_usd:
            rec["hit_at"] = f["close_ct"]
    entries_after: list[dict] = []
    for d, rec in days.items():
        if rec["hit_at"] is None:
            continue
        for f in fills:
            if _utc_day_ct(f["open_ct"] - shift) == d and f["open_ct"] > rec["hit_at"]:
                entries_after.append({"day": d, "key": f["key"],
                                      "open_utc": _iso_ct(f["open_ct"] - shift)})
    return {"cap_usd": cap_usd,
            "days_reaching_it": [d for d, r in sorted(days.items()) if r["hit_at"] is not None],
            "would_refuse": entries_after,
            "why": (f"at this risk the ${cap_usd:,.2f}/day ceiling is reached on "
                    f"{len([d for d, r in days.items() if r['hit_at'] is not None])} day(s) and "
                    f"would have refused {len(entries_after)} entry(ies)")}


def breaker_stress_inputs(base: dict, *, risk_pct: float) -> dict:
    """The arm's live stance with ONLY the inputs this construction needs moved, each named.

    Two inputs move and both are declared in the artifact beside their reason:
      * `InpRiskPercent` — the lever. R is risk-invariant, so this moves WHEN the 3% rule binds,
        not which entries the strategy takes.
      * `InpPropBestDayPct` — set to 0, because the ceiling is a fixed $/day and at the derived
        risk the first good day reaches it: left on, it would refuse winning entries that the
        daily-cap prediction says must be present, and the comparison would be grading two rules
        while claiming one. `profit_ceiling_exposure` reports exactly what it would have refused.
    `InpDailyLossCapPct` is NOT touched — it is the number being certified.
    """
    d = dict(base)
    d["InpRiskPercent"] = f"{risk_pct:g}"
    d["InpPropBestDayPct"] = "0"
    return d


def run_breaker_stress(mode: str, spec: dict, *, data: dict | None = None,
                       preset_path: Path | str = LIVE_PRESET, expert: str = EXPERT,
                       shipping: dict | None = None) -> dict:
    """The arm's own 3% cap, exercised at the risk per trade that brings it into reach.

    THE TWO PASSES, same shape as the other stress leg and for the same reason: `BSU` runs the
    EA's LIVE path with the governor OFF at the derived risk, so the prediction is read off a path
    the governor never touched; `BSG` runs it with the governor ON at the SHIPPING cap. The
    verification is then falsifiable in four specific ways (`refused_as_predicted`,
    `refused_but_taken`, `survived_as_predicted`, `lost_without_prediction`, `unexpected_entries`).

    WHAT IT DOES NOT SAY: this is still the venue's real-tick window and the arm's own contract,
    but the RISK PER TRADE in this pass is a stress input — the shipping arm runs 0.25%, not the
    derived number. The cap, the strategy, the window, the tick model and the entry sequence are
    the arm's own; the size is the construction, and the artifact says so in its own field.
    """
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    offset_min = assert_server_offset(spec)
    declared = read_preset_inputs(preset_path)
    base = live_stance_inputs(mode, t0, t1, offset_min=offset_min, preset=preset_path)
    deposit = float(T._BASE_TESTER_INI.get("Deposit", 0) or 0)
    cap_pct = float(declared.get("InpDailyLossCapPct", 0) or 0)
    arm_tag = str(declared.get("InpArmTag", ""))
    code = TAG_MODE_CODE[mode]
    out: dict = {"why": BREAKER_STRESS_WHY, "deposit": deposit,
                 "shipping_cap_pct": cap_pct,
                 "declared_risk_pct": float(declared.get("InpRiskPercent", 0) or 0),
                 "preset": str(preset_path), "passes": {},
                 "risk_margin": BREAKER_STRESS_RISK_MARGIN}
    if deposit <= 0 or cap_pct <= 0:
        return {**out, "verdict": "REFUSED",
                "refused_for": ("the tester deposit or the declared daily cap is missing, so "
                                "there is no percentage basis to derive a risk against")}

    # THE DERIVATION IS READ OFF THE PATH THIS PASS WILL WALK, which is the LIVE path — not the
    # python engine's. MEASURED 2026-09-22: they are not the same sequence on this window (python
    # takes 9 trades where the live path takes 7, and the python path's worst usable day is
    # 2026-09-15, a day the live path never trades at all). Deriving from python produced a risk
    # that could not bind on the live path — a derivation from the wrong market, not a finding
    # about the governor. The shipping stance's own fills are that path, already measured in this
    # run (its governor is VACUOUS here, so what it holds is the ungoverned sequence).
    path_fills = [f for f in (shipping or {}).get("fills_detail") or [] if f.get("risk_usd")]
    if not path_fills:
        return {**out, "verdict": "REFUSED",
                "refused_for": ("the live stance reported no fills with a risk per trade, so there "
                                "is no path to derive a risk from — and deriving it from the "
                                "python bar model instead would derive it from a different "
                                "sequence of trades")}
    m15 = (data or {}).get("m15")
    walk = breaker_walk(path_fills, deposit=deposit, offset_min=offset_min, m15=m15)
    derived = derive_binding_risk(walk, cap_pct=cap_pct)
    out["derivation"] = {
        **derived,
        "source": (f"the live stance's own fills ({len(path_fills)} closed fill(s)) — the arm's "
                   f"live path on the venue's real ticks, which is the path this pass walks; the "
                   f"python engine of record runs a DIFFERENT sequence (9 bar-model trades here "
                   f"against the live path's 7) and its worst usable day, 2026-09-15, is a day the "
                   f"live path never trades"),
        "anchor": walk["anchor_note"],
        "day_clock": walk["day_clock"],
        "m15_used_for_the_anchor": walk["m15_used"],
        "carried_over_the_roll": walk["carried_over_the_roll"],
        "days": [{k: d[k] for k in ("day", "anchor_equity", "boundary_float_usd", "low_units",
                                   "carried", "fills")}
                 for d in walk["days"]]}
    if derived.get("risk_pct") is None:
        return {**out, "verdict": "NO-BIND", "refused_for": None, "why_verdict": derived["why"]}
    risk_pct = float(derived["risk_pct"])
    day = (derived.get("chosen") or {}).get("day")

    def run(suffix: str, inputs: dict, label: str) -> tuple[list[dict], dict]:
        tag = f"{spec['tag']}_{code}_{suffix}"
        print(f"  breaker stress {suffix}: tag={tag} — {label}, the EA's LIVE path, in the "
              f"tester", flush=True)
        started = time.time()
        res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert,
                         model=spec.get("model"))
        ticks = dict(res.get("tick_model") or {})
        time.sleep(10)                    # agent flushes the ledger after its report
        snap = stance_ledger_snapshot(arm_tag, not_before=started - 5)
        if snap is None:
            out["passes"][suffix] = {"tag": tag, "ledger": None, "tick_model": ticks}
            return [], ticks
        if snap.get("stale"):
            out["passes"][suffix] = {"tag": tag, "ledger": snap, "fills": None, "stale": True,
                                     "tick_model": ticks}
            print(f"    {suffix}: REFUSED — {snap['stale']}", flush=True)
            return [], ticks
        fills, problems = parse_stance_fills(Path(snap["path"]))
        out["passes"][suffix] = {"tag": tag, "ledger": snap, "fills": len(fills),
                                 "problems": problems, "tick_model": ticks}
        print(f"    {suffix}: {len(fills)} closed fill(s), ledger "
              f"{snap['sha256_8']} ({snap['mtime_utc']})", flush=True)
        return fills, ticks

    # PASS U: the governor OFF, at the derived risk — the only path a prediction may be read from.
    u_inputs = breaker_stress_inputs(base, risk_pct=risk_pct)
    u_inputs["InpPropGuard"] = "false"
    u_fills, u_ticks = run("BSU", u_inputs, f"governor OFF at the DERIVED risk {risk_pct:g}%")
    out["moved_inputs"] = {
        "InpRiskPercent": {"from": declared.get("InpRiskPercent"), "to": f"{risk_pct:g}",
                           "why": ("the lever: R is risk-invariant, so this moves WHEN the cap "
                                   "binds and the order of nothing")},
        "InpPropBestDayPct": {"from": declared.get("InpPropBestDayPct"), "to": "0",
                              "why": ("a fixed $/day ceiling reached by the first good day at "
                                      "this risk; left on it would refuse winning entries the "
                                      "daily-cap prediction says must be present")},
        "InpDailyLossCapPct": {"from": declared.get("InpDailyLossCapPct"),
                               "to": declared.get("InpDailyLossCapPct"),
                               "why": "NOT MOVED — this is the number being certified"}}
    if not u_fills:
        u_snap = (out["passes"].get("BSU") or {}).get("ledger") or {}
        return {**out, "verdict": "REFUSED", "risk_pct": risk_pct,
                "refused_for": (u_snap.get("stale") or
                                "the ungoverned pass closed no fills, so there is no equity path "
                                "to predict a refusal on")}
    out["ungoverned"] = {"risk_pct": risk_pct, "fills": len(u_fills),
                         "days": _stance_day_table(u_fills, deposit=deposit,
                                                   offset_min=offset_min),
                         "tick_model": u_ticks,
                         "same_entries_as_the_shipping_stance": (
                             None if not (shipping or {}).get("fill_open_ct") else
                             sorted(f["open_ct"] for f in u_fills)
                             == sorted(shipping["fill_open_ct"]))}
    # the prediction is read off the pass's OWN path (BSU), on the EA's own anchor, at the derived
    # risk — never off the governed pass, which could only agree with itself
    u_walk = breaker_walk(u_fills, deposit=deposit, offset_min=offset_min, m15=m15)
    prediction = breaker_prediction(u_walk, cap_pct=cap_pct, risk_pct=risk_pct,
                                    offset_min=offset_min)
    out["prediction_path"] = {"walk": [{k: d[k] for k in ("day", "anchor_equity",
                                                          "boundary_float_usd", "low_units",
                                                          "carried", "fills")}
                                       for d in u_walk["days"]],
                              "anchor_note": u_walk["anchor_note"]}
    if prediction["breach"] is None:
        bound = [b for b in prediction["breaches"] if b["refusals"]]
        why = (f"the derived risk {risk_pct:g}%/trade left no day over the shipping {cap_pct:g}% "
               f"cap with an entry after the breach, on the EA's own anchor: the largest day loss "
               f"was {prediction['largest_day_loss_pct']:.3f}% and "
               f"{len(prediction['breaches'])} day(s) breached"
               + (f", every one of them on its own last fill (" +
                  ", ".join(f"{b['day']} {b['from_utc'][11:16]}Z {b['loss_pct']:.2f}%"
                            for b in prediction["breaches"]) + ")"
                  if prediction["breaches"] else "")
               + " — reported as a DERIVATION that bound nothing, not as a governor result")
        return {**out, "verdict": "NO-BIND", "risk_pct": risk_pct, "bound_days": len(bound),
                "largest_day_loss_pct": prediction["largest_day_loss_pct"],
                "breaches": prediction["breaches"], "why_verdict": why}

    # THE ISOLATION, MEASURED: the derived risk also makes the other rules reachable, and a second
    # refusing rule would corrupt the comparison rather than enrich it. Both are reported, and a
    # shield that would have refused REFUSES the construction.
    shield = shield_exposure(u_fills, size=float(declared.get("InpPropAccountSize", 0) or 0),
                             maxdd_pct=float(declared.get("InpPropMaxDdPct", 0) or 0),
                             deposit=deposit, offset_min=offset_min)
    ceiling = profit_ceiling_exposure(
        u_fills,
        cap_usd=(float(declared.get("InpPropAccountSize", 0) or 0)
                 * float(declared.get("InpPropTargetPct", 0) or 0) / 100.0
                 * float(declared.get("InpPropBestDayPct", 0) or 0) / 100.0),
        deposit=deposit, offset_min=offset_min)
    out["isolation"] = {"shield": shield, "profit_ceiling": ceiling,
                        "why": ("the object under test is ONE rule: the daily-loss cap. The shield "
                                "is measured on this very path at its shipped depth and the "
                                "ceiling by declaration switched off, with what it would have "
                                "refused reported, so the isolation is visible rather than "
                                "convenient.")}
    if shield["would_refuse"]:
        return {**out, "verdict": "REFUSED", "risk_pct": risk_pct,
                "refused_for": (f"at the derived risk {risk_pct:g}% the trailing shield would also "
                                 f"have refused {len(shield['would_refuse'])} entry(ies) on this "
                                 f"path, so a governed pass could not be graded against the "
                                 f"daily-cap prediction alone: the construction is not isolated")}

    # PASS G: the governor ON at the SHIPPING cap, at the same derived risk.
    g_inputs = breaker_stress_inputs(base, risk_pct=risk_pct)
    g_fills, g_ticks = run("BSG", g_inputs,
                           f"governor ON at the SHIPPING cap {cap_pct:g}% (risk {risk_pct:g}%)")
    if not g_fills:
        g_snap = (out["passes"].get("BSG") or {}).get("ledger") or {}
        return {**out, "verdict": "REFUSED", "risk_pct": risk_pct, "prediction": prediction,
                "refused_for": (g_snap.get("stale") or
                                "the governed pass closed no fills — a pass that traded nothing "
                                "cannot be said to have refused the right entries")}

    u_ct = [f["open_ct"] for f in u_fills]
    g_ct = [f["open_ct"] for f in g_fills]
    cap_basis = (f"this is the ARM'S OWN cap, unchanged, and the derived quantity is the RISK PER "
                 f"TRADE {risk_pct:g}% — {cap_pct:g}% over the {derived['chosen_drawdown_r']:.3f}R "
                 f"day on {day} ({derived['chosen']['at_utc']}, breach with "
                 f"{derived['chosen']['entries_after']} entry(ies) left to refuse) carried at a "
                 f"{BREAKER_STRESS_RISK_MARGIN:g} margin for the venue's lot step") if derived.get(
                     "chosen") else f"the arm's own {cap_pct:g}% cap at a derived risk"
    verdict, why_verdict, comparison = governor_stress_compare(
        prediction, u_ct, g_ct, cap=cap_pct,
        dd=float(prediction["breach"]["loss_pct"]),
        cap_basis=cap_basis)
    print(f"  breaker stress: risk {risk_pct:g}%/trade derived from the -"
          f"{derived['chosen_drawdown_r']:.3f}R day on {day}; breach "
          f"{prediction['breach']['from_utc']} at {prediction['breach']['loss_pct']:.3f}% of the "
          f"{cap_pct:g}% cap")
    print(f"  breaker stress: {verdict} — {why_verdict}")
    return {**out, "verdict": verdict, "risk_pct": risk_pct,
            "ungoverned": {**out["ungoverned"], "open_ct": sorted(u_ct),
                           "largest_day_loss_pct": prediction["largest_day_loss_pct"]},
            "governed": {"fills": len(g_fills), "open_ct": sorted(g_ct),
                         "tick_model": g_ticks,
                         "days": _stance_day_table(g_fills, deposit=deposit,
                                                   offset_min=offset_min)},
            "prediction": {k: prediction[k] for k in ("breach", "must_be_absent",
                                                      "must_be_present", "boundary")},
            "verification": comparison,
            "why_verdict": why_verdict}


def _day_r_table(trades: list[dict], *, offset_min: int) -> list[dict]:
    """Per-UTC-day R arithmetic of a path — the table a threshold derivation is read off."""
    shift = offset_min * 60
    days: dict[str, dict] = {}
    for t in sorted(trades, key=lambda x: x["close_ct"]):
        d = _utc_day_ct(t["close_ct"] - shift)
        rec = days.setdefault(d, {"day": d, "fills": 0, "sum_r": 0.0, "low_r": 0.0})
        rec["fills"] += 1
        rec["sum_r"] = round(rec["sum_r"] + t["r"], 4)
        rec["low_r"] = round(min(rec["low_r"], rec["sum_r"]), 4)
    return [days[d] for d in sorted(days)]


def _stance_day_table(fills: list[dict], *, deposit: float, offset_min: int) -> list[dict]:
    """Per-UTC-day DOLLARS of a pass's own fills — what the cap is actually measured against."""
    shift = offset_min * 60
    days: dict[str, dict] = {}
    eq = float(deposit)
    for f in sorted(fills, key=lambda x: x["close_ct"]):
        d = _utc_day_ct(f["close_ct"] - shift)
        rec = days.setdefault(d, {"day": d, "open_equity": round(eq, 2), "fills": 0,
                                  "low_equity": eq, "end_equity": eq})
        eq += f["r"] * f["risk_usd"]
        rec["fills"] += 1
        rec["low_equity"] = min(rec["low_equity"], eq)
        rec["end_equity"] = eq
    for rec in days.values():
        rec["loss_pct_peak"] = (round((rec["open_equity"] - rec["low_equity"])
                                      / rec["open_equity"] * 100.0, 4) if rec["open_equity"] else 0.0)
        for k in ("low_equity", "end_equity"):
            rec[k] = round(rec[k], 2)
    return [days[d] for d in sorted(days)]


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
    ap.add_argument("--live-stance", action="store_true",
                    help="ALSO run a second pass in the arm's OWN stance (the account layer "
                         "from mql5/MIDASTOUCH/MidastouchAI_upcomers_gold_LIVE.set: risk %%, "
                         "prop governor, live execution) over the same window and tick model, "
                         "and certify what no BAR pass can: that every fill is sized the way the "
                         "declared rule sizes it at the equity it actually had, and that no "
                         "modelled governor rule would have refused an entry the arm took. "
                         "The strategy certificate is unaffected — this is a SECOND stance.")
    ap.add_argument("--governor-stress", action="store_true", dest="governor_stress",
                    help="with --live-stance, ALSO exercise the prop governor at a threshold "
                         "DERIVED to bind (half the largest day drawdown the arm's own ungoverned "
                         "path made), in two passes: the governor OFF to read the prediction from, "
                         "then ON to check the EA refused exactly those entries and no others. "
                         "This is a STRESS threshold, not the shipping cap: the shipping 3%% cap "
                         "is unreached in every certified window and stays reported VACUOUS.")
    ap.add_argument("--breaker-stress", action="store_true", dest="breaker_stress",
                    help="with --live-stance, ALSO exercise the ARM'S OWN 3%% daily-loss cap — not "
                         "a derived cap — by deriving the RISK PER TRADE that brings it into reach "
                         "on this window (cap%% over the largest day drawdown still followed by an "
                         "entry, plus a declared margin for the venue's lot step), then running two "
                         "passes at that risk: the governor OFF to read the prediction from, then "
                         "ON at the shipping 3%% to check the EA refused exactly those entries and "
                         "no others. The risk per trade in this pass is a STRESS input; the cap, "
                         "the strategy, the window and the entry sequence are the arm's own.")
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
    if args.governor_stress and not args.live_stance:
        raise SystemExit("REFUSING: --governor-stress needs --live-stance. The stress is measured "
                         "AGAINST the shipping stance, and a run that never took one has nothing "
                         "to compare the governed pass to.")
    if args.breaker_stress and not args.live_stance:
        raise SystemExit("REFUSING: --breaker-stress needs --live-stance. The construction is the "
                         "arm's own account layer with one input moved, so the stance it is built "
                         "from has to have been declared and measured in the same run.")
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
    # The live-stance contract terms are measured BEFORE anything is stopped: the measurement
    # goes through the terminal (order_calc_profit), and the harness stops it below. A refusal
    # here costs nothing; discovering it after the pass would cost a stopped arm and an hour.
    live_contract = None
    if args.live_stance:
        live_contract, why = measure_contract_spec()
        if live_contract is None:
            print(f"ABORT: --live-stance needs the venue's contract terms and they could not be "
                  f"measured ({why}). Nothing was stopped and nothing was run.")
            return 5
        print(f"live stance preflight: contract measured — min lot {live_contract.min_lot:g}, "
              f"step {live_contract.lot_step:g}, ${live_contract.usd_per_unit_per_lot:,.2f} per "
              f"unit per lot ({live_contract.basis})")

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
        # MEASURED 2026-09-22 (docs/LIVE_EXIT_AUDIT_20260922.md §5): the profile inventory
        # misses a start-up-attached arm by construction (MT5 never saves a start-up chart
        # to Profiles), so on the one machine that matters the legacy GOLD_LEDGER path is
        # absent, `arms` came up empty, and `verify_all_flat([])` returned vacuous truth
        # while the arm held an OPEN live position — and two certification runs stopped the
        # terminal under it. Every gold paper book on the terminal gates the stop, and the
        # books are discovered the way the watchdog discovers them: profiles PLUS the
        # attach config, deduped by ledger; an armed record with zero books refuses.
        data_folder = R.data_folder_for_terminal()
        arms = R.inventory_arms(data_folder)
        rec = R.arming_record() or {}
        seen = {os.path.normcase(a["ledger"]) for a in arms}
        for a in R.startup_attached_arms(data_folder):
            if os.path.normcase(a["ledger"]) in seen:
                continue
            arms.append({"magic": str(rec.get("magic") or ""), "name": a["tag"] or "startup",
                         "tag": a["tag"], "chart": os.path.join(a["data_folder"], "config", R.ATTACH_INI),
                         "ledger": a["ledger"]})
        if not arms:
            armed = R.arming_state()
            if armed.get("armed"):
                print(f"ABORT: arming record names arm '{armed.get('arm', '?')}' but no gold "
                      f"arm book was discovered (no profile chart, no attach config) — "
                      f"'no books' is not 'flat'; refusing to stop the terminal")
                return 4
            print("flat-check: no gold arm book discovered and nothing is armed — "
                  "vacuously flat")
        flat, bad = R.verify_all_flat(arms)
        # THE SECOND WITNESS. The ledger is a file this program writes; the venue's own
        # position book is the thing that actually holds the trade. If the armed arm's
        # ledger reads flat while the venue holds a position with OUR magic, the ledger
        # is the thing that is wrong — and that is exactly the state in which stopping
        # the terminal strands a live trade. The venue is asked only when the arming
        # record names a magic; an unanswerable venue REFUSES (fail-closed), because the
        # pre-fix gate passed vacuously on exactly this kind of silence.
        armed = R.arming_state()
        if armed.get("armed"):
            try:
                amagic = int(rec.get("magic") or 0)
            except (TypeError, ValueError):
                amagic = 0
            asym = str(rec.get("symbol") or "")
            if amagic and asym:
                vopen = R.venue_open_position_count(asym, amagic)
                if vopen is None:
                    flat = False
                    bad.append({"name": "venue-cross-check",
                                "problem": (f"the venue could not be asked about {asym} magic {amagic} "
                                            f"(python API unavailable) — the ledger is the only "
                                            f"witness, and it said flat; refusing on the silence")})
                elif vopen > 0:
                    flat = False
                    bad.append({"name": "venue-cross-check",
                                "problem": (f"the venue holds {vopen} open position(s) with magic "
                                            f"{amagic} on {asym} while the discovered book(s) read "
                                            f"flat — the ledger is missing a live trade")})
                else:
                    print(f"venue cross-check: 0 open position(s) with magic {amagic} "
                          f"on {asym} — the ledger's 'flat' is the venue's 'flat'")
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
        print(f"flat-check OK ({len(arms)} gold arm book(s) on the terminal (profiles + "
              f"attach config); legacy gold ledger {'checked' if gold else 'absent'})")

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
        # THE SECOND STANCE (--live-stance): the same window and tick model with the arm's own
        # account layer, certified against the python sizing mirror and a modelled governor.
        # It runs AFTER the strategy pass so a refusal there cannot cost the certificate.
        live = None
        stress = None
        breaker = None
        if args.live_stance:
            live = run_live_stance(modes[0], spec, contract=live_contract, expert=expert)
            if args.governor_stress:
                stress = run_governor_stress(modes[0], spec, contract=live_contract,
                                             expert=expert, shipping=live)
            if args.breaker_stress:
                breaker = run_breaker_stress(modes[0], spec, data=data, expert=expert,
                                             shipping=live)
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
            if live is not None:
                print(f"ACCOUNT LAYER:      {live['verdict']}"
                      + (f" (sizing {live['sizing']['verdict']}, governor "
                         f"{live['governor']['verdict']})" if "sizing" in live else ""))
                if live.get("refused_for"):
                    print(f"  live stance REFUSED: {live['refused_for']}")
                else:
                    print(f"  live stance sizing: {live['sizing']['why']}")
                    print(f"  live stance governor: {live['governor']['why']}")
                    print(f"  live stance does NOT model: {'; '.join(live['governor']['not_modelled'])}")
            if stress is not None:
                print(f"GOVERNOR (DERIVED CAP): {stress['verdict']}"
                      + (f" at a derived {stress['stress_cap_pct']:g}% cap"
                         if stress.get("stress_cap_pct") is not None else ""))
                print(f"  governor stress: {stress.get('why_verdict') or stress.get('refused_for')}")
                print("  governor stress moves the CAP; it is not the shipping threshold. The "
                      "shipping 3% cap is certified by the breaker stress below.")
            if breaker is not None:
                print(f"GOVERNOR (SHIPPING CAP): {breaker['verdict']}"
                      + (f" at the arm's own {breaker['shipping_cap_pct']:g}%"
                         if breaker.get("shipping_cap_pct") else "")
                      + (f", risk {breaker['risk_pct']:g}%/trade"
                         if breaker.get("risk_pct") is not None else ""))
                print(f"  breaker stress: "
                      f"{breaker.get('why_verdict') or breaker.get('refused_for')}")
                if breaker.get("isolation"):
                    print(f"  breaker isolation: {breaker['isolation']['shield']['why']}; "
                          f"{breaker['isolation']['profit_ceiling']['why']} (switched off for "
                          f"this pass by declaration)")
                if breaker.get("ungoverned", {}).get("same_entries_as_the_shipping_stance") is not None:
                    print(f"  breaker entries == the shipping stance's entries: "
                          f"{breaker['ungoverned']['same_entries_as_the_shipping_stance']}")
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
                "live_stance": live,
                "governor_stress": stress,
                "breaker_stress": breaker,
                **cmp,
            }
            path = f"artifacts/midas_parity_result_{datetime.now():%Y%m%d_%H%M}.json"
            with open(path, "w") as fh:
                json.dump(out, fh, indent=1)
            print("artifact:", path)
            # A live-stance FAIL blocks too: "the strategy is certified" and "the arm is
            # configured the way it declares" are two claims, and a run that answers the first
            # with PASS must not print a clean exit code while the second failed. A
            # GOVERNED-FAIL blocks harder: it is the governor disagreeing with the mirror that
            # describes it. A NO-BIND stress verdict does not block — it is an honest "this
            # window cannot ask the question", and the live stance already says so.
            rc = 0 if (cmp["verdict"] == "PASS"
                       and (live is None or live["verdict"] == "PASS")
                       and (stress is None or stress["verdict"] != "GOVERNED-FAIL")
                       and (breaker is None or breaker["verdict"] != "GOVERNED-FAIL")) else 1
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

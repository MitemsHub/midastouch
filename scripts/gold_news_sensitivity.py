#!/usr/bin/env python3
"""What the news stand-down costs the certified corpus.

THE QUESTION. `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` carries a standing policy — no new
entries within +/-15 minutes of a top-tier USD release — and the EA can now enforce it
(`InpUseNewsFilter`, v1.19c). The frozen walk-forward in `artifacts/gold_wfo.json` was
produced with NO news rule at all: the protocol (`docs/GOLD_WFO_PROTOCOL.md`) never
mentions one. So switching the gate on does not "add protection" to a certified
strategy — it CHANGES the strategy, and the change has never been priced. A rule that
removes trades moves the distribution it was certified on, in either direction, and
"it can only help" is exactly the kind of claim this repository refuses to make without
a measurement. This is that measurement.

WHAT IS HELD FIXED. Everything. The corpus, the 24-configuration grid, the fold
structure, the selection rule, the cost model, the control seed and the V1-V6 criteria
are `scripts/gold_walkforward.py`'s own code, imported — not re-implemented — so the two
legs differ in exactly one thing. The veto is applied the way the EA applies it: as an
ENTRY veto on the bar whose signal is being evaluated, never as an exit rule (a rule that
could trap a position through a release would breach the shield it claims to protect).

THE CONTROL THAT MAKES THIS EVIDENCE. Leg A (veto off) must reproduce
`artifacts/gold_wfo.json` — same picks, same per-fold R, same t — or this script REFUSES
and reports nothing. Without that, a difference between the legs could be an artefact of
the harness rather than the rule, and there would be no way to tell.

TWO CONVENTIONS, DECLARED RATHER THAN ASSUMED.

1. WHICH INSTANT THE VETO JUDGES. The engine enters at bar `i`'s CLOSE (it fills at
   `close[i]`), and the EA evaluates the signal on the same bar with `TimeGMT()` as
   "now". Those are the same instant: `epoch[i] + 900`. So a bar is in blackout when a
   HIGH event sits within +/-15 minutes of `epoch[i] + 900`. Using the bar's OPEN would
   shift every judgement one bar early and silently under-count.

2. WHICH EVENTS. Exactly the EA's rule: `HIGH` importance only, and the file must be
   usable by `src/midas_prop/risk/news_calendar.py`'s own standards — fresh, covering
   the frozen window, not truncated, not empty — because a veto measured against a
   calendar the EA would have refused is not a measurement of the EA's rule.

TWO MODES, BECAUSE THE FROZEN WINDOW IS THE ONLY ONE THE CONTROL CAN APPLY TO.
`--corpus-end frozen` (default) truncates to the certified range and REQUIRES the
veto-off leg to reproduce `artifacts/gold_wfo.json` exactly; that is what makes the delta
attributable to the rule. `--corpus-end now` takes the corpus as it stands, as a NEW
window of its own: no reproduction is possible there, so the control is declared
inapplicable rather than quietly skipped, and the veto-off leg stays the reference (same
code, same bars, one difference).

LEAVE-ONE-FOLD-OUT IS REPORTED WITH EVERY DELTA. The window holds ~31 folds, so an
eight-day fold that carries the whole difference is not a finding about the rule — it is
a finding about that fold. The total is additive across folds by construction, so
`total - fold_i` is exact.

NOTE ON THE SOURCE OF RECORD. The venue's calendar is the only one that counts, and it
is reachable only from MQL5 (`MidasNewsProbe.mq5`); the Python API exposes no calendar
function at all. Point it at the file the probe wrote:

    python scripts/gold_news_sensitivity.py --calendar "<terminal>\\MQL5\\Files\\MIDASTOUCH_news_calendar.csv"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_walkforward as W  # noqa: E402  the frozen protocol, imported not copied
from mt5_data import load_m5  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

FROZEN = ROOT / "artifacts" / "gold_wfo.json"
NEWS_WINDOW_MIN = 15
M15_SEC = 900
#: Recomputation is expected to be BIT-EXACT (same code, same corpus, same seeds). The
#: tolerance is only there so a last-bit float difference is not mistaken for a finding;
#: anything above it is a refusal, not a rounding note.
CONTROL_TOL = 1e-9


def protocol_digest(frozen: dict) -> str:
    """SHA-256 over everything the comparison depends on, so a declaration cannot outlive it.

    A pre-registration is worth nothing if the protocol can move underneath it: if the grid,
    the fold structure, the criteria or the frozen artifact changes after the declaration is
    written, the declared expectation is about a different experiment. Hashing the code that
    implements the protocol (not this file's prose) and the frozen reference's own spec means
    any such move is visible as a refusal rather than as a silently re-interpreted result.
    """
    h = hashlib.sha256()
    for p in (ROOT / "scripts" / "gold_walkforward.py",
              ROOT / "scripts" / "gold_news_sensitivity.py"):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update(json.dumps({
        "fold_days": W.FOLD_DAYS, "warmup": W.WARMUP_BARS, "seed": W.CONTROL_SEED,
        "configs": W.configs(), "flat_by_utc_hour": W.FLAT_BY_UTC_HOUR,
        "spread_bps": W.SPREAD_BPS, "commission": W.COMMISSION_PER_LOT_RT,
        "frozen_spec": frozen.get("spec"), "frozen_checks": frozen.get("checks"),
        "frozen_total_r": frozen.get("stats", {}).get("_total"),
    }, sort_keys=True, default=str).encode())
    return h.hexdigest()


def prereg_verdict(picks_changed: list[str], off_checks: dict, on_checks: dict,
                   d_total: float) -> tuple[str, list[str]]:
    """The decision rule, fixed BEFORE the amended leg is computed and applied after.

    P1 is the test that matters. The veto is applied while the walk-forward SELECTS, so a
    pick change is the rule altering the strategy's own search rather than filtering its
    entries — and a configuration chosen under the amendment is not the configuration the
    frozen protocol certified. P2 refuses a regression on any leg; P3 refuses a rule that
    costs R on the window that certified the strategy it is amending.
    """
    failed = []
    if picks_changed:
        failed.append(f"P1: the selection changed in {', '.join(picks_changed)} — the rule "
                      f"altered the strategy's own configuration search, so this is an "
                      f"amendment to certify, not a filter to enable")
    lost = [k for k in off_checks if k.startswith("V")
            and off_checks[k] and not on_checks.get(k)]
    if lost:
        failed.append(f"P2: legs lost under the amendment: {', '.join(lost)}")
    if d_total <= 0:
        failed.append(f"P3: delta {d_total:+.3f}R is not positive on the certifying window")
    order = {"P1": 0, "P2": 1, "P3": 2}
    failed.sort(key=lambda s: order.get(s[:2], 9))
    return ("REJECTED" if failed else "INERT-ACCEPTABLE"), failed


def fold_attribution(off_picks: list[dict], off_rs: list[float], on_rs: list[float],
                     d_total: float) -> list[dict]:
    """Per-fold contribution to the delta, with the total recomputed without each mover.

    The total is the sum of the per-fold out-of-sample R by construction, so `d_total - d_i`
    is exact rather than approximate. This is what separates "the rule moved the window"
    from "the rule moved one eight-day fold", and the second reading is much weaker.
    """
    out = []
    for po, ro, rn in zip(off_picks, off_rs, on_rs):
        d = rn - ro
        if abs(d) > 1e-9:
            out.append({"fold": po["fold"], "contribution_r": d,
                        "total_without_fold_r": d_total - d})
    return out


def default_calendar() -> Path | None:
    """The venue's calendar in the running terminal's data folder, or None."""
    try:
        import mt5_ops  # noqa: PLC0415
        data = mt5_ops.data_folder_for_terminal()
    except Exception:      # pragma: no cover — no terminal on this machine
        return None
    if not data:
        return None
    return Path(data) / "MQL5" / "Files" / "MIDASTOUCH_news_calendar.csv"


def blackout_mask(epoch: np.ndarray, events: tuple[NC.Event, ...],
                  window_min: int = NEWS_WINDOW_MIN) -> np.ndarray:
    """Per-bar: would the EA veto an entry on this bar?

    The instant judged is the bar's CLOSE (`epoch[i] + 900`) — see the module docstring.
    Vectorised rather than looped because the corpus is ~16k bars x ~370 events and this
    runs inside every leg.
    """
    close_t = epoch.astype(np.int64) + M15_SEC
    mask = np.zeros(len(epoch), dtype=bool)
    window_s = window_min * 60
    highs = np.array([e.epoch for e in events if e.is_top_tier], dtype=np.int64)
    if len(highs) == 0:
        return mask
    left = np.searchsorted(highs, close_t - window_s, side="left")
    right = np.searchsorted(highs, close_t + window_s, side="right")
    return (right - left) > 0


def corpus(symbol: str, last_epoch: int | None) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    """The window's bars, plus the regime flags and hours `main()` builds.

    TRUNCATED TO THE CERTIFIED RANGE ON PURPOSE when `last_epoch` is given. The corpus
    keeps growing (16263 M15 bars today against 16224 when the artifact was written), and a
    replay that included the newer bars could not be compared to the artifact at all — the
    control would fail for a reason that has nothing to do with news.

    `last_epoch=None` takes the corpus as it stands, which is what `--corpus-end now` is
    for: the same pair of legs over the venue's newest bars, as a NEW window rather than a
    reproduction of the certified one.
    """
    bars = int(60000)
    m15 = load_m5(symbol, timeframe=W.EXEC_TF, bars=bars)
    h1 = load_m5(symbol, timeframe="H1", bars=bars // 4 + 100)
    h4 = load_m5(symbol, timeframe="H4", bars=bars // 16 + 100)
    B = {k: m15.array[k].astype(float) for k in
         ("epoch", "open", "high", "low", "close", "spread", "volume")}
    if last_epoch is not None:
        keep = int(np.searchsorted(B["epoch"], last_epoch, side="right"))
        for k in B:
            B[k] = B[k][:keep]
    epoch = B["epoch"]
    n = len(epoch)

    atr = W.wilder_atr(B["high"], B["low"], B["close"], W.ATR_PERIOD)

    h1e = h1.array["epoch"].astype(float)
    h1c = h1.array["close"].astype(float)
    h1_ef, h1_em, h1_es = (W.ema(h1c, k) for k in (8, 21, 50))
    h4e = h4.array["epoch"].astype(float)
    h4c = h4.array["close"].astype(float)
    h4_ef = W.ema(h4c, 20)

    h1_ok_long = np.zeros(n, dtype=bool)
    h1_ok_short = np.zeros(n, dtype=bool)
    h4_ok_long = np.zeros(n, dtype=bool)
    h4_ok_short = np.zeros(n, dtype=bool)
    for i in range(n):
        t = float(epoch[i])
        k = W.last_closed_index(h1e, t, W.H1_TF_SEC)
        if k >= 0:
            h1_ok_long[i] = h1_ef[k] > h1_em[k] > h1_es[k]
            h1_ok_short[i] = h1_ef[k] < h1_em[k] < h1_es[k]
        m = W.last_closed_index(h4e, t, W.H4_TF_SEC)
        if m >= 0:
            h4_ok_long[i] = h4c[m] > h4_ef[m]
            h4_ok_short[i] = h4c[m] < h4_ef[m]

    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)
    return B, atr, hours, (h1_ok_long, h1_ok_short, h4_ok_long, h4_ok_short)


def leg(B: dict, atr, hours, flags, blackout: np.ndarray | None,
        control_reps: int) -> dict:
    """One full walk-forward pass, identical to `gold_walkforward.main()`, with the veto.

    `blackout=None` is the certified configuration (no news rule). A mask suppresses the
    entry signal on those bars — the same thing the EA does when it returns before sizing.
    """
    epoch = B["epoch"]
    n = len(epoch)
    h1_ok_long, h1_ok_short, h4_ok_long, h4_ok_short = flags
    if blackout is not None:
        h1_ok_long = h1_ok_long & ~blackout
        h1_ok_short = h1_ok_short & ~blackout

    folds = W.build_folds(epoch)
    all_cfgs = W.configs()
    trades_by_cfg = [
        W.simulate(B, hours, h1_ok_long, h1_ok_short, h4_ok_long, h4_ok_short, atr,
                   cfg, start=W.WARMUP_BARS, end=n)
        for cfg in all_cfgs]

    oos_rs: list[float] = []
    picks: list[dict] = []
    prev_pick = max(range(len(all_cfgs)),
                    key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    for fi in range(1, len(folds)):
        _pn, plo, phi = folds[fi - 1]
        _n2, nlo, nhi = folds[fi]
        scored = []
        for k, tr in enumerate(trades_by_cfg):
            r = sum(t["net_r"] for t in tr if plo <= t["entry_i"] < phi)
            cfgd = all_cfgs[k]
            scored.append((r, -cfgd["stop_mult"], -cfgd["tp_mult"], -k, k))
        scored.sort(reverse=True)
        if scored[0][0] != 0.0:
            prev_pick = scored[0][4]
        pick = prev_pick
        oos = sum(t["net_r"] for t in trades_by_cfg[pick] if nlo <= t["entry_i"] < nhi)
        oos_rs.append(oos)
        picks.append({"fold": folds[fi][0], "config": all_cfgs[pick], "oos_r": oos})

    held_by_fold, oos_detail = [], []
    for fi in range(1, len(folds)):
        _n2, nlo, nhi = folds[fi]
        k = W._pick_index(all_cfgs, picks[fi - 1]["config"])
        held_by_fold.append(sum(1 for t in trades_by_cfg[k] if nlo <= t["entry_i"] < nhi))
        for t in trades_by_cfg[k]:
            if nlo <= t["entry_i"] < nhi:
                oos_detail.append({"fold": folds[fi][0], "entry_i": t["entry_i"],
                                   "net_r": t["net_r"]})
    n_oos = sum(held_by_fold)

    control_totals = []
    for rep in range(control_reps):
        tot = 0.0
        for fi in range(1, len(folds)):
            _n2, nlo, nhi = folds[fi]
            tot += sum(t["net_r"] for t in W.random_control(
                B, hours, atr, held_by_fold[fi - 1], picks[fi - 1]["config"],
                start=nlo, end=nhi, seed=W.CONTROL_SEED + rep * 1000 + fi))
        control_totals.append(tot)
    control_total = float(np.mean(control_totals)) if control_totals else 0.0

    checks = W.criteria(oos_rs, control_total)
    return {"folds": folds, "picks": picks, "oos_rs": oos_rs, "checks": checks,
            "control_total": control_total, "oos_trades": n_oos,
            "oos_detail": oos_detail, "trades_by_cfg": trades_by_cfg,
            "all_cfgs": all_cfgs,
            "entry_bars": {t["entry_i"] for t in oos_detail}}


def signal_census(B: dict, atr, hours, flags, blackout: np.ndarray) -> dict:
    """Signal bars the veto would suppress, counted INDEPENDENTLY of position state.

    The trade count understates the rule's reach: a signal on a blackout bar while a
    position is already open would have been skipped anyway. This counts the bars where
    every entry condition holds and the bar is in blackout, so the exposure is visible
    even where it changed no trade.
    """
    epoch = B["epoch"]
    n = len(epoch)
    h1_ok_long, h1_ok_short, h4_ok_long, h4_ok_short = flags
    atr_lo = W.trailing_percentile(atr, W.ATR_LOOKBACK, W.ATR_LOW_PCT)
    atr_hi = W.trailing_percentile(atr, W.ATR_LOOKBACK, W.ATR_HIGH_PCT)
    per_win = {"7-20": (7, 20), "13-18": (13, 18)}
    total = masked = 0
    for emas in W.EMA_SETS:
        e_f, e_m, e_s = (W.ema(B["close"], p) for p in emas)
        up = (e_f > e_m) & (e_m > e_s)
        dn = (e_f < e_m) & (e_m < e_s)
        for lo, hi in per_win.values():
            in_win = np.array([lo <= h <= hi and h < W.FLAT_BY_UTC_HOUR
                               for h in hours], dtype=bool)
            band = np.array([not (math.isnan(atr[i]) or math.isnan(atr_lo[i])
                                  or math.isnan(atr_hi[i]))
                             and atr_lo[i] < atr[i] <= atr_hi[i] and atr[i] > 0
                             for i in range(n)], dtype=bool)
            sig = np.zeros(n, dtype=bool)
            sig[W.WARMUP_BARS:] = True
            sig &= in_win & band
            sig &= ((up & h1_ok_long & h4_ok_long) | (dn & h1_ok_short & h4_ok_short))
            total += int(sig.sum())
            masked += int((sig & blackout).sum())
    return {"signal_bars": total, "signal_bars_in_blackout": masked}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=W.SYMBOL)
    ap.add_argument("--calendar", help="the probe's calendar file (default: the running "
                                      "terminal's MQL5\\Files copy)")
    ap.add_argument("--window-min", type=int, default=NEWS_WINDOW_MIN)
    ap.add_argument("--control-reps", type=int, default=None,
                    help="random-control repetitions (default: the frozen artifact's own)")
    ap.add_argument("--frozen", default=str(FROZEN), help="the artifact to reproduce")
    ap.add_argument("--corpus-end", choices=("frozen", "now"), default="frozen",
                    help="'frozen' truncates to the certified range and enforces the "
                         "control; 'now' takes the venue's newest bars as a NEW window, "
                         "where no reproduction of the artifact is possible")
    ap.add_argument("--preregister", nargs="?", const="artifacts/gold_news_preregistration.json",
                    default=None,
                    help="declare the question, the hypothesis and the decision rule BEFORE "
                         "the amended leg is computed, then judge the run by it")
    ap.add_argument("--out", default="artifacts/gold_news_sensitivity.json")
    a = ap.parse_args(argv)

    frozen_path = Path(a.frozen)
    if not frozen_path.is_file():
        raise SystemExit(f"no frozen artifact at {frozen_path} — this measurement exists "
                         f"to be a delta against it")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    first = datetime.fromisoformat(frozen["data"]["first"]).timestamp()
    last = datetime.fromisoformat(frozen["data"]["last"]).timestamp()
    control_reps = frozen["spec"]["control_reps"] if a.control_reps is None \
        else a.control_reps

    # ---- the pre-registration, written and honour-digested BEFORE any leg is computed ----
    prereg_path = Path(a.preregister) if a.preregister else None
    if prereg_path is not None and not prereg_path.is_absolute():
        prereg_path = ROOT / prereg_path
    digest = protocol_digest(frozen)
    prereg = None
    if prereg_path is not None:
        declaration = {
            "declared_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol_digest": digest,
            "question": "does the news stand-down change what the frozen walk-forward "
                        "SELECTS, or only which of the selected signals it takes?",
            "hypothesis": "the veto is an entry filter, so every fold selects the same "
                          "configuration as the certified run and only the entry set moves",
            "decision_rule": {
                "P1": "no fold's selected configuration changes",
                "P2": "no V-leg pass on the certified leg is lost",
                "P3": "delta total R is positive on the certifying window",
                "ACCEPT": "INERT-ACCEPTABLE if P1 and P2 and P3 hold",
                "REJECT": "otherwise: an amendment that must be certified on its own terms",
            },
            "frozen_reference": {"artifact": frozen_path.name,
                                 "oos_trades": frozen["oos_trades"],
                                 "total_r": frozen["stats"]["_total"],
                                 "t": frozen["stats"]["_t"],
                                 "checks": frozen["checks"]},
        }
        if prereg_path.is_file():
            prior = json.loads(prereg_path.read_text(encoding="utf-8"))
            if prior.get("protocol_digest") != digest:
                raise SystemExit(
                    f"REFUSING: {prereg_path} declares protocol "
                    f"{str(prior.get('protocol_digest'))[:16]} but this harness is "
                    f"{digest[:16]} — the protocol moved after the declaration was written, "
                    f"so the declared expectation is about a different experiment. Delete "
                    f"the declaration and declare again.")
            prereg = prior
            print(f"prereg  : declaration honoured — {prereg_path.name}, declared "
                  f"{prior['declared_utc']}, protocol {digest[:12]}")
        else:
            prereg_path.parent.mkdir(parents=True, exist_ok=True)
            prereg_path.write_text(json.dumps(declaration, indent=2, default=str),
                                   encoding="utf-8")
            prereg = declaration
            print(f"prereg  : declaration WRITTEN to {prereg_path} (before any leg ran)")
        print("          the rule this run will be judged by:")
        for k, v in prereg["decision_rule"].items():
            print(f"            {k}: {v}")

    cal_path = Path(a.calendar) if a.calendar else default_calendar()
    if cal_path is None or not cal_path.is_file():
        raise SystemExit(f"no calendar at {cal_path or '<unresolved>'} — attach "
                         f"mql5/MIDASTOUCH/MidasNewsProbe.mq5 once to write the venue's "
                         f"own feed (the Python API has no calendar function at all)")
    try:
        cal = NC.read_calendar(cal_path)
    except NC.CalendarUnusable as exc:
        raise SystemExit(f"REFUSING: the calendar at {cal_path} is unusable "
                         f"({exc.reason}). A veto measured against a calendar the EA "
                         f"itself would refuse is not a measurement of the EA's rule.")
    highs = tuple(e for e in cal.events if e.is_top_tier)
    print(f"calendar : {cal_path}")
    print(f"           {len(cal.events)} events, {len(highs)} HIGH — "
          f"{datetime.fromtimestamp(cal.window_from_utc, timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(cal.window_to_utc, timezone.utc):%Y-%m-%d}")

    truncate = None if a.corpus_end == "now" else int(last)
    B, atr, hours, flags = corpus(a.symbol, truncate)
    epoch = B["epoch"]
    n = len(epoch)
    print(f"corpus   : {n} bars  "
          f"{datetime.fromtimestamp(epoch[0], timezone.utc)} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc)}"
          f"   [--corpus-end {a.corpus_end}]")
    if a.corpus_end == "frozen":
        if int(epoch[-1]) != int(last):
            raise SystemExit(f"REFUSING: the corpus ends {int(epoch[-1])} but the frozen "
                             f"artifact ends {int(last)} — the control cannot be run")
    elif int(epoch[-1]) <= int(last):
        raise SystemExit(f"REFUSING: --corpus-end now but the corpus ends "
                         f"{int(epoch[-1])} at or before the frozen window's end "
                         f"{int(last)} — there are no newer bars to test")
    as_of = int(epoch[-1])

    # Fold inventory: an extension can only add evidence if it completes a fold. An
    # eight-day fold that is half-formed cannot be scored, so bars added without a fold
    # are exposure, not evidence.
    keep_frozen = int(np.searchsorted(epoch, int(last), side="right"))
    folds_now = W.build_folds(epoch)
    folds_frozen = W.build_folds(epoch[:keep_frozen]) if keep_frozen < n else folds_now
    added_bars = n - keep_frozen
    if a.corpus_end == "frozen":
        # No extension is being claimed here, so the fold-inventory verdict is meaningless:
        # printing "no new complete fold" on a corpus that was deliberately truncated to the
        # certified range would read as a failed attempt at one.
        print(f"           folds: {len(folds_now)}")
    else:
        no_new_fold = " — NO new complete fold: this extension cannot be second-window " \
            "evidence" if len(folds_now) == len(folds_frozen) else ""
        print(f"           vs frozen: +{added_bars} bars ({added_bars * 15 / 1440:.1f} days), "
              f"folds {len(folds_frozen)} -> {len(folds_now)}{no_new_fold}")

    problem = NC.source_problem(cal, as_of, max_age_hours=24, cover_hours=0)
    if problem:
        raise SystemExit(f"REFUSING: {problem} (calendar {cal_path}). The window being "
                         f"judged must be covered or the veto cannot be judged on it.")

    blackout = blackout_mask(epoch, highs, a.window_min)
    in_win = [(int(epoch[i]), int(epoch[i]) + M15_SEC, i)
              for i in range(n) if blackout[i]]
    print(f"blackout : {int(blackout.sum())} of {n} bars ({blackout.mean():.2%}) lie within "
          f"+/-{a.window_min} min of a HIGH release")
    print(f"           {len(highs)} HIGH events over "
          f"{(epoch[-1] - epoch[0]) / 86400:.0f} days")

    off = leg(B, atr, hours, flags, None, control_reps)
    # ---- the control: veto off MUST reproduce the frozen artifact ----
    replay_v = {k: v for k, v in off["checks"].items() if k.startswith("V")}
    breaches = []
    if a.corpus_end == "now":
        # A correlation check cannot be run against an artifact computed on other bars.
        # Declared, not skipped: the veto-off leg is still the reference, because it is
        # this same code on these same bars with exactly one difference.
        print("\nCONTROL  : N/A for --corpus-end now — the frozen artifact was computed on "
              f"{keep_frozen} bars and this window has {n}. The veto-off leg below is the "
              "reference; it cannot be checked against gold_wfo.json.")
    if replay_v != frozen["checks"]:
        breaches.append(f"V-legs {replay_v} vs {frozen['checks']}")
    if off["oos_trades"] != frozen["oos_trades"]:
        breaches.append(f"trades {off['oos_trades']} vs {frozen['oos_trades']}")
    if abs(off["control_total"] - frozen["control_total_r"]) > CONTROL_TOL:
        breaches.append(f"control {off['control_total']:.6f} vs "
                        f"{frozen['control_total_r']:.6f}")
    for k in ("_total", "_median", "_t"):
        if abs(off["checks"][k] - frozen["stats"][k]) > CONTROL_TOL:
            breaches.append(f"{k} {off['checks'][k]:.6f} vs {frozen['stats'][k]:.6f}")
    for i, (got_r, want_r) in enumerate(zip(off["oos_rs"], frozen["oos_r_per_fold"])):
        if abs(got_r - want_r) > CONTROL_TOL:
            breaches.append(f"fold {i} {got_r:.6f} vs {want_r:.6f}")
    if a.corpus_end == "frozen":
        if breaches:
            raise SystemExit(
                "REFUSING: the veto-OFF leg does not reproduce the frozen artifact, so any "
                "difference reported against the veto-ON leg would not be attributable to "
                "the rule. Breaches:\n  " + "\n  ".join(breaches))
        print("\nCONTROL  : veto-off reproduces artifacts/gold_wfo.json exactly "
              f"({off['oos_trades']} trades, total {off['checks']['_total']:+.4f}R, "
              f"t {off['checks']['_t']:+.4f})")

    on = leg(B, atr, hours, flags, blackout, control_reps)
    census = signal_census(B, atr, hours, flags, blackout)

    def fmt(legd: dict, label: str) -> str:
        c = legd["checks"]
        legs = " ".join(f"[{'P' if c[k] else 'F'}]{k.split()[0]}"
                        for k in c if k.startswith("V"))
        return (f"  {label:22s} trades={legd['oos_trades']:4d}  total={c['_total']:+8.2f}R  "
                f"mean={c['_total'] / len(legd['oos_rs']):+.3f}R/fold  t={c['_t']:+.3f}  "
                f"control={legd['control_total']:+8.2f}R  {legs}")

    print("\n== the frozen window, replayed with and without the news stand-down ==")
    print(fmt(off, "veto OFF (certified)"))
    print(fmt(on, f"veto ON (+/-{a.window_min}m HIGH)"))

    d_trades = on["oos_trades"] - off["oos_trades"]
    d_total = on["checks"]["_total"] - off["checks"]["_total"]
    d_t = on["checks"]["_t"] - off["checks"]["_t"]
    print(f"\n  change: {d_trades:+d} trades ({d_trades / max(off['oos_trades'], 1):+.1%}), "
          f"{d_total:+.2f}R, t {d_t:+.3f}")
    print(f"  signal census: {census['signal_bars_in_blackout']} of "
          f"{census['signal_bars']} entry-condition bars "
          f"({census['signal_bars_in_blackout'] / max(census['signal_bars'], 1):.2%}) "
          f"sit inside a blackout (counted independently of position state)")

    flips = [po["fold"] for po, pn in zip(off["picks"], on["picks"])
             if po["config"] != pn["config"]]
    verdict, failed = prereg_verdict(flips, off["checks"], on["checks"], d_total)
    if prereg is not None:
        print(f"\n== pre-registered verdict: {verdict} ==")
        print(f"   P1 picks changed: {flips if flips else 'none'}")
        for f in failed:
            print(f"   {f}")
        if not failed:
            print("   all three conditions hold: the rule removed entries without changing "
                  "what the grid selected")
        outcome = {"measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "verdict": verdict, "picks_changed": flips, "delta_total_r": d_total,
                   "delta_trades": d_trades,
                   "off": {k: off["checks"][k] for k in off["checks"] if k.startswith("V")},
                   "on": {k: on["checks"][k] for k in on["checks"] if k.startswith("V")},
                   "corpus_end": a.corpus_end}
        prereg_path.write_text(json.dumps({**prereg,
                                           "runs": (prereg.get("runs") or []) + [outcome]},
                                          indent=2, default=str), encoding="utf-8")
        print(f"   recorded in {prereg_path.name} (appended, never overwritten)")

    print("\n== per fold ==")
    for po, pn, ro, rn in zip(off["picks"], on["picks"], off["oos_rs"], on["oos_rs"]):
        same = po["config"] == pn["config"]
        print(f"  {po['fold']}: off {ro:+.2f}R  on {rn:+.2f}R  ({rn - ro:+.2f})  "
              f"pick {'same' if same else 'CHANGED'}")
    print(f"  picks changed by the veto: {flips if flips else 'none'}")

    # ---- which folds carry it: an eight-day fold can be the whole finding ----
    movers = fold_attribution(off["picks"], off["oos_rs"], on["oos_rs"], d_total)
    print("\n== leave-one-fold-out: does any single fold carry the whole delta? ==")
    if not movers:
        print("  no fold moved: the veto changed no fold's out-of-sample R")
    for m in movers:
        share = abs(m["contribution_r"]) / abs(d_total) if d_total else float("inf")
        print(f"  drop {m['fold']}: total {m['total_without_fold_r']:+.3f}R "
              f"(that fold carries {m['contribution_r']:+.3f}R = {share:.0%} of the delta)")

    print("\n== the walk-forward legs (docs/GOLD_WFO_PROTOCOL.md section 6) ==")
    for k in (k for k in off["checks"] if k.startswith("V")):
        o, w = off["checks"][k], on["checks"][k]
        mark = "  <-- flips" if o != w else ""
        print(f"  {k:22s} veto OFF {'PASS' if o else 'FAIL'}   "
              f"veto ON {'PASS' if w else 'FAIL'}{mark}")
    print(f"  V1..V6 all hold      veto OFF "
          f"{all(off['checks'][k] for k in off['checks'] if k.startswith('V'))}   "
          f"veto ON {all(on['checks'][k] for k in on['checks'] if k.startswith('V'))}")

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(json.dumps({
        "fold_attribution": {
            "movers": movers,
            "folds_scored": len(off["oos_rs"]),
            "folds_moved": len(movers),
            "share_of_delta_in_largest_mover": (
                max(abs(m["contribution_r"]) for m in movers) / abs(d_total)
                if movers and d_total else None)},
        "spec": {"symbol": a.symbol, "window_min": a.window_min,
                 "calendar": str(cal_path),
                 "corpus_end": a.corpus_end,
                 "preregistration": ({"path": prereg_path.name,
                                      "protocol_digest": digest,
                                      "declared_utc": prereg.get("declared_utc"),
                                      "verdict": verdict, "failed": failed}
                                     if prereg is not None else None),
                 "bars_added_vs_frozen": added_bars,
                 "folds_now": len(folds_now),
                 "folds_frozen": len(folds_frozen),
                 "new_folds": len(folds_now) - len(folds_frozen),
                 "calendar_events": len(cal.events),
                 "calendar_high": len(highs),
                 "calendar_generated_utc": cal.generated_utc,
                 "frozen_artifact": frozen_path.name,
                 "control_reps": control_reps,
                 "reproduced_frozen": a.corpus_end == "frozen",
                 "judged_instant": "bar close (epoch[i] + 900), matching the EA's TimeGMT() "
                                   "at the same bar"},
        "corpus": {"bars": n, "blackout_bars": int(blackout.sum()),
                   "blackout_share": float(blackout.mean()),
                   "first": str(datetime.fromtimestamp(epoch[0], timezone.utc)),
                   "last": str(datetime.fromtimestamp(epoch[-1], timezone.utc))},
        "veto_off": {"oos_trades": off["oos_trades"], "oos_r_per_fold": off["oos_rs"],
                     "checks": {k: bool(v) for k, v in off["checks"].items()
                                if k.startswith("V")},
                     "stats": {k: off["checks"][k] for k in off["checks"]
                               if k.startswith("_")},
                     "control_total_r": off["control_total"],
                     "picks": [p["config"] for p in off["picks"]]},
        "veto_on": {"oos_trades": on["oos_trades"], "oos_r_per_fold": on["oos_rs"],
                    "checks": {k: bool(v) for k, v in on["checks"].items()
                               if k.startswith("V")},
                    "stats": {k: on["checks"][k] for k in on["checks"]
                              if k.startswith("_")},
                    "control_total_r": on["control_total"],
                    "picks": [p["config"] for p in on["picks"]]},
        "delta": {"trades": d_trades, "total_r": d_total, "t": d_t,
                  "picks_changed": flips},
        "signal_census": census,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

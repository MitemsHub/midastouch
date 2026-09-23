#!/usr/bin/env python3
"""The forward resolver for the Asian-range sweep shadow record.

WHAT THIS READS, AND FROM WHOM
  `MIDAS1.28` appends one `SWEEPSHADOW` row per evaluated M15 bar to the armed arm's own
  ledger — the setup, never an outcome. This program resolves those setups to closed
  hypothetical outcomes **through the engine of record's own `run_mode`**, so no outcome
  arithmetic is re-implemented here: the number is `scripts/midas_sweep.py`'s.

WHY THE SPLIT IS THE WAY IT IS
  The EA cannot know the future, and a record containing a claim its writer could not have
  measured is not evidence. So the EA writes the levels, the direction and the stop
  distance; this resolver writes the R. The ledger rows are the LIVE, timestamped,
  non-repainting statement of what the mechanism said on the bars the arm actually
  evaluated; this side turns them into outcomes.

THE BINDING SELF-CHECK
  Two checks run before anything is reported, and either one refusing means the run is void:

  1. The pinned venue-corpus law reproduces (`wfv REVERSE_DIRECTION n=56 / +15.9352R`,
     `tests/test_midas_minlot_veto.py`) — proves the engine is the engine.
  2. The PUBLISHED secondary-window number reproduces from the moved mechanism
     (`oos` `SWEEP_CONT` n=152 / +0.1955R / t 2.208, `artifacts/midas_asia_sweep_20260922.json`)
     — proves the mechanism this resolver feeds the engine is the one the study measured.
     The mechanism was moved out of `midas_asia_sweep.py` into `midas_sweep.py` on
     2026-09-22 so there could be exactly one definition; this check is how that move is
     kept honest rather than asserted.

  Then a THIRD, per-run check: the resolver rebuilds the sweep signal array independently
  and must agree with the EA's own rows on every bar the arm recorded. A lookalike recorder
  is worth nothing, so a disagreement exits without reporting.

VERDICT VOCABULARY (fixed in `docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md`, not here)
  ACCUMULATING   N < 60 resolved outcomes. The only quotable word below the target.
  PASS           all four pre-registered tests hold.
  FAIL           one of tests 1-3 failed, and the verdict names which.
  VOID           the direction checks inverted forward: the recorder is measuring something
                 other than the mechanism that was measured, which invalidates the recorder
                 rather than the hypothesis.

READ-ONLY. This program has no order path and cannot have one: it is not in the live
closure (see `scripts/audit_program_surface.py`), and it only reads bars and a ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import midas_parity as P  # noqa: E402  the engine of record
import midas_sweep as M  # noqa: E402  the certified mode engine and its metrics
from midas_decision_attribution import day_stats, needed_for_t15, t_stat  # noqa: E402

ART = ROOT / "artifacts" / "sweep_shadow_forward.json"
PREREG = "docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md"

#: The pre-registered rule. Repeated here as CONSTANTS so a reader of the verdict can see
#: the numbers it was judged against without opening the document, and pinned against the
#: document's own text by `tests/test_sweep_shadow.py` so the two cannot drift.
N_TARGET = 60
T_BAR = 2.4
MIN_PER_DAY = 0.30
VARIANT = "SWEEP_CONT"
DIRECTION_CHECKS = ("SWEEP_FADE", "RECLAIM_REV")

#: `SWEEPSHADOW,<write>,<sig_open>,<utc_day>,<asian_hi>,<asian_lo>,<range_bars>,<side>,`
#: `<first>,<reclaim>,<stop_d>,<off_min>,<version>` — 13 fields.
#:
#: There is no separate `dir` field, deliberately: `side` is nonzero only on the FIRST sweep of
#: that day on that side, so it IS `SWEEP_CONT`'s direction. Storing both would put a field in
#: the row that can never differ from another, and `SWEEP_FADE` (= -side) and `RECLAIM_REV`
#: (=-side on a reclaim bar) are derivable — which is what stops this record later reading as
#: if three hypotheses had been tested.
ROW_FIELDS = 13


def self_check() -> None:
    """Reproduce BOTH pinned laws, or refuse to print a single number."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
        n, total = len(rr.trades), sum(t["r"] for t in rr.trades)
        print(f"self-check 1  wfv {spec['mode']}: n={n} totalR={total:+.4f} vetoed={rr.vetoed}")
        if n != 56 or abs(total - 15.9352) >= 5e-4:
            raise SystemExit(
                "REFUSING: the pinned venue-corpus law did not reproduce (expected n=56 / "
                "+15.9352R, tests/test_midas_minlot_veto.py). Every number below would be "
                "a lookalike.")

        oos = P._window_spec("oos")
        d2 = P.python_build_data(offset_min=P.assert_server_offset(oos), corpus="venue")
        sig = M.sweep_signals(d2["m15"])[VARIANT]
        rr2 = M.run_mode("TRIGGER_ONLY", oos["t0"], oos["t1"], {**d2, "m15_bb": sig},
                         win_lo=M.SWEEP_WINDOW[0], win_hi=M.SWEEP_WINDOW[1])
        rs = [t["r"] for t in rr2.trades]
        n2, exp, t2 = len(rs), sum(rs) / len(rs) if rs else 0.0, t_stat(rs)
        print(f"self-check 2  oos {VARIANT} secondary: n={n2} expR={exp:+.4f} t={t2:+.3f}")
        if n2 != 152 or abs(exp - 0.1955) >= 5e-4 or abs(t2 - 2.208) >= 5e-3:
            raise SystemExit(
                "REFUSING: the mechanism does not reproduce the published secondary-window "
                "number (expected n=152 / +0.1955R / t 2.208, "
                "artifacts/midas_asia_sweep_20260922.json). The definition that was moved "
                "into midas_sweep.py is NOT the one the study measured.")
    finally:
        M._BASIS = prev
    print("              both laws reproduced -> the arithmetic below is the engine of record's,")
    print("              on the mechanism the study measured.\n")


# ── the ledger side ─────────────────────────────────────────────────────────
def read_rows(ledger: Path) -> tuple[list[dict], list[str]]:
    """`SWEEPSHADOW` rows off the ledger, plus the lines that could not be read.

    A short or malformed row is REPORTED and skipped, never read generously: a row with no
    direction is not a statement about a setup, and defaulting it to 0 would let the
    agreement check below pass on a row that says nothing. That is the same failure the
    `ERA` reader in `live_readiness` documents having learned.
    """
    rows: list[dict] = []
    broken: list[str] = []
    try:
        text = ledger.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SystemExit(f"cannot read the arm's ledger at {ledger}: {exc}")
    for ln, line in enumerate(text.splitlines(), 1):
        if not line.startswith("SWEEPSHADOW,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != ROW_FIELDS:
            broken.append(f"line {ln}: {len(parts)} fields, expected {ROW_FIELDS}")
            continue
        try:
            rows.append({
                "write": int(parts[1]), "sig_open": int(parts[2]), "utc_day": parts[3],
                "asian_hi": float(parts[4]), "asian_lo": float(parts[5]),
                "range_bars": int(parts[6]), "side": int(parts[7]), "first": int(parts[8]),
                "reclaim": int(parts[9]), "stop_d": float(parts[10]),
                "off_min": int(parts[11]), "version": parts[12],
            })
        except ValueError as exc:
            broken.append(f"line {ln}: {exc}")
    rows.sort(key=lambda r: r["sig_open"])
    return rows, broken


def arm_ledger() -> tuple[Path | None, str, Path | None]:
    """`(the armed arm's book, its tag, the terminal data dir)` — or Nones with a reason.

    Derived from the arming record's tag, never globbed: a retired arm's book, or the parity
    harness's own tagged file, sits in `MQL5/Files` for the rest of the program's life and a
    glob would report on a chart nobody started. Same resolution `live_readiness` uses.
    """
    import live_readiness as LR  # noqa: PLC0415 — keeps a compile run off the prop layer

    term_data: Path | None = None
    try:
        import MetaTrader5 as mt5  # type: ignore
        if mt5.initialize():
            ti = mt5.terminal_info()
            if ti is not None and getattr(ti, "data_path", ""):
                term_data = Path(str(ti.data_path))
    except ImportError:
        pass
    tag = LR.armed_arm_tag()
    books = LR.running_ledgers(term_data, tag)
    book = books[0] if books else None
    return book, tag, term_data


# ── the venue's own bars, extended to now ───────────────────────────────────
def live_bars(off_min: int, n_m15: int, n_h1: int) -> tuple[list[dict], list[dict]]:
    """`(m15, h1)` from the terminal, shifted out of the venue's clock into true UTC.

    The shift is the ARM'S OWN recorded offset, applied exactly as `venue_bars_utc` applies
    it to the series of record (`time - off*60`), so the appended bars and the corpus bars
    are in one frame.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return [], []
    if not mt5.initialize():
        return [], []
    try:
        shift = off_min * 60

        def grab(tf, n, tf_sec):
            r = mt5.copy_rates_from_pos("XAUUSD", tf, 0, n)
            if r is None:
                return []
            # CLOSED BARS ONLY, IN ONE FRAME. MEASURED 2026-09-23 ~07:18Z vs ~07:26Z:
            # position 0 is the still-forming bar, and a resolve that ran mid-bar produced
            # an outcome (SWEEP_CONT −1.92R) that no longer existed 8 minutes later — the
            # partial bar's high/low and ATR inputs moved under it. A forward record whose
            # rows can flip is not evidence, so a bar is kept only once its close time has
            # passed. MEASURED ~07:31Z, the first cut of that filter compared the raw
            # `b["time"]` — a SERVER-wall epoch — against true-UTC now and silently dropped
            # the newest two hours of CLOSED bars (series ended 05:15Z while the arm had
            # rows for 07:00/07:15Z): every live row read "unmatched" and no EA-vs-engine
            # agreement could ever be computed. The close test is in UTC: shift first.
            now_s = int(time.time())
            out = []
            for b in r:
                utc_open = int(b["time"]) - shift
                if utc_open + tf_sec <= now_s:
                    out.append({"time": utc_open, "open": float(b["open"]),
                                "high": float(b["high"]), "low": float(b["low"]),
                                "close": float(b["close"]), "spread": float(b["spread"])})
            return out
        return (grab(mt5.TIMEFRAME_M15, n_m15, 15 * 60),
                grab(mt5.TIMEFRAME_H1, n_h1, 60 * 60))
    finally:
        try:
            mt5.shutdown()
        except Exception:      # noqa: BLE001
            pass


def build_series(off_min: int) -> tuple[list[dict], list[dict], dict]:
    """The m15/h1 the resolver walks: the series of record, EXTENDED by the terminal's bars.

    The corpus (`data/forex/xauusd/*_upcomers.csv`) is the data of record and stops at its
    last fetch; the forward record necessarily runs past it. The extension is the same
    venue's own bars from the same terminal, shifted by the same offset, so the series stays
    one market — and the seam is REPORTED rather than silent, because "the number is computed
    on a series whose provenance changed at a stamp" is exactly the kind of thing this
    program exists to be able to see.
    """
    m15 = P.venue_bars_utc("XAUUSD_M15", off_min)
    h1 = P.venue_bars_utc("XAUUSD_H1", off_min)
    prov: dict = {"corpus_m15_rows": len(m15), "corpus_h1_rows": len(h1),
                  "corpus_last_m15": m15[-1]["time"] if m15 else None,
                  "offset_min": off_min, "appended_m15_rows": 0, "appended_h1_rows": 0,
                  "source": "venue corpus + terminal, same venue, one offset"}
    lv_m15, lv_h1 = live_bars(off_min, 1200, 600)
    if lv_m15:
        cut = m15[-1]["time"] if m15 else 0
        add = [b for b in lv_m15 if b["time"] > cut]
        prov["appended_m15_rows"] = len(add)
        m15 = m15 + add
    if lv_h1:
        cut = h1[-1]["time"] if h1 else 0
        add = [b for b in lv_h1 if b["time"] > cut]
        prov["appended_h1_rows"] = len(add)
        h1 = h1 + add
    prov["last_m15"] = m15[-1]["time"] if m15 else None
    return m15, h1, prov


# ── resolution ──────────────────────────────────────────────────────────────
def summarise(trades: list[dict], t0: int, t1: int) -> dict:
    rs = [t["r"] for t in trades]
    m = M.metrics(trades)
    return {**{k: m.get(k) for k in ("n", "net_r", "expectancy_r", "pf", "win_rate",
                                     "max_dd_r")},
            "mean_r": round(sum(rs) / len(rs), 4) if rs else None,
            "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs),
            **day_stats(trades, t0, t1)}


def span_signal_bars(m15: list[dict], arr: list[int], t0: int) -> int:
    """Signal bars in the DECLARED WINDOW at or after `t0` — one definition, two callers.

    The published study's `signal_bars` counts the whole array (205 for `oos` `SWEEP_CONT`),
    which is fine when the window is the whole span and misleading when it is a forward tail.
    Everything this file reports counts what it names: bars inside UTC 07-18 from `t0` on.
    """
    lo, hi = M.SWEEP_WINDOW
    n = 0
    for i, b in enumerate(m15):
        if b["time"] < t0 or arr[i] == 0:
            continue
        if lo <= datetime.fromtimestamp(b["time"], tz=timezone.utc).hour < hi:
            n += 1
    return n


def resolve(m15, h1, off_min, t0, t1) -> tuple[dict, dict]:
    """Every variant over the forward span, through the engine, at the certified geometry."""
    h4 = M.h4_series(h1, offset_min=off_min)
    data = P._python_data(h1, m15, h4)
    # `bb_dev` is irrelevant here and is left at its default on purpose: `m15_bb` — the array
    # the engine reads its trigger from — is replaced below by the sweep signal, exactly as
    # `midas_asia_sweep.py` and `midas_cross_asset.py` do. Nothing else about the engine
    # moves: certified stop (2.0xATR H1), target (2.0R), 48-bar timeout, half-spread on both
    # sides, SPREAD_FLOOR when a bar records none.
    sig = M.sweep_signals(m15)
    out: dict[str, dict] = {}
    for v in M.SWEEP_VARIANTS:
        rr = M.run_mode("TRIGGER_ONLY", t0, t1, {**data, "m15_bb": sig[v]},
                        win_lo=M.SWEEP_WINDOW[0], win_hi=M.SWEEP_WINDOW[1])
        out[v] = {**summarise(rr.trades, t0, t1), "vetoed": rr.vetoed,
                  "signal_bars": span_signal_bars(m15, sig[v], t0)}
    return out, sig


def check_rows_against_engine(rows: list[dict], m15: list[dict], sig: list[int],
                              t0: int) -> dict:
    """The EA's rows against the independently rebuilt signal array. Disagreement voids.

    The engine's array is indexed by bar, so the lookup is by the bar's own OPEN epoch — the
    same stamp the EA writes as `sig_open`. A row whose bar is not in the series at all is
    reported as `unmatched` rather than as a disagreement: the corpus and the terminal can
    legitimately differ by a bar at the seam, and calling that a repaint would be its own
    kind of lie.
    """
    idx = {b["time"]: i for i, b in enumerate(m15)}
    disagree: list[str] = []
    unmatched: list[dict] = []
    in_window = 0
    fired_rows = 0
    for r in rows:
        # The EA's row carries a SERVER-stamped bar open; the series (corpus via
        # `venue_bars_utc`, the terminal extension via `live_bars`) is keyed on true UTC.
        # The row's own `off_min` converts it — the SAME conversion the hour check below
        # applies. MEASURED on the first live row 2026-09-23 07:15Z: keying the lookup on
        # the raw stamp matched nothing (the corpus/terminal frame is UTC), so every row
        # would have read `unmatched` forever and no EA-vs-engine agreement would ever
        # have been computed — the entire point of the forward record.
        utc_open = r["sig_open"] - r["off_min"] * 60
        i = idx.get(utc_open)
        if i is None:
            unmatched.append({"sig_open": r["sig_open"], "side": r["side"]})
            continue
        utc_hour = datetime.fromtimestamp(utc_open, tz=timezone.utc).hour
        if not (M.SWEEP_WINDOW[0] <= utc_hour < M.SWEEP_WINDOW[1]):
            continue                      # outside the declared window: not the shadow's claim
        in_window += 1
        if r["side"] != 0:
            fired_rows += 1
        if sig[i] != r["side"]:
            disagree.append(f"bar {r['sig_open']} ({utc_hour:02d}Z): EA side={r['side']} vs "
                            f"engine SWEEP_CONT={sig[i]}")
    engine_signal_bars = span_signal_bars(m15, sig, t0)
    return {"rows_total": len(rows), "rows_in_window": in_window,
            "rows_with_a_signal": fired_rows,
            "engine_signal_bars_in_span": engine_signal_bars,
            "coverage": (round(fired_rows / engine_signal_bars, 4)
                         if engine_signal_bars else None),
            "unmatched_rows": unmatched[:20], "n_unmatched": len(unmatched),
            "disagreements": disagree[:20], "n_disagreements": len(disagree)}


def verdict(res: dict, checks: dict) -> tuple[str, list[str]]:
    """The pre-registered rule, applied to the forward record and nothing else."""
    main = res[VARIANT]
    n = main.get("n") or 0
    if checks["n_disagreements"]:
        return "VOID", [f"{checks['n_disagreements']} bar(s) where the EA's row and the engine "
                        f"disagree — the recorder is not recording the mechanism"]
    if n < N_TARGET:
        return "ACCUMULATING", [f"N={n} of {N_TARGET} resolved outcomes"]
    why: list[str] = []
    if main.get("t") is None or main["t"] < T_BAR:
        why.append(f"t={main.get('t')} < {T_BAR}")
    if (main.get("per_day") or 0) < MIN_PER_DAY:
        why.append(f"fills/day={main.get('per_day')} < {MIN_PER_DAY}")
    if (main.get("mean_r") or 0) <= 0:
        why.append(f"mean forward R={main.get('mean_r')} is not positive")
    for v in DIRECTION_CHECKS:
        m = res[v].get("mean_r")
        if m is not None and m > 0:
            return "VOID", [f"the direction check {v} is POSITIVE forward (mean {m:+.4f}R): "
                            f"the record is measuring something other than the mechanism the "
                            f"study and the external series both reported"]
    return ("PASS" if not why else "FAIL"), why or ["all four pre-registered tests hold"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=None,
                    help="the arm's book; default: derived from the arming record's tag")
    ap.add_argument("--no-terminal", action="store_true",
                    help="resolve from the corpus alone (no live append; for offline runs)")
    a = ap.parse_args()

    self_check()

    now = datetime.now(timezone.utc)
    book, tag, term_data = (Path(a.ledger), "", None) if a.ledger else arm_ledger()
    if book is None or not book.exists():
        print(f"no armed arm's book found (tag={tag!r}, terminal={term_data}) — "
              f"the shadow has not started, or nothing is armed.")
        print(f"pre-registration: {PREREG}")
        return 0

    rows, broken = read_rows(book)
    off_min = None
    if rows:
        off_min = rows[-1]["off_min"]
    if off_min is None:
        import live_readiness as LR  # noqa: PLC0415
        off_min = LR.init_offset_min(book)
    if off_min is None:
        import live_readiness as LR  # noqa: PLC0415
        off_min = LR.venue_offset_min(now)

    if a.no_terminal:
        m15 = P.venue_bars_utc("XAUUSD_M15", off_min)
        h1 = P.venue_bars_utc("XAUUSD_H1", off_min)
        prov = {"corpus_m15_rows": len(m15), "corpus_h1_rows": len(h1), "appended_m15_rows": 0,
                "appended_h1_rows": 0, "offset_min": off_min, "source": "corpus only"}
    else:
        m15, h1, prov = build_series(off_min)

    t0 = (min(r["sig_open"] for r in rows) // 86400) * 86400 if rows else int(now.timestamp())
    t1 = int(now.timestamp()) + 86400

    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        res, sig = resolve(m15, h1, off_min, t0, t1)
        checks = check_rows_against_engine(rows, m15, sig[VARIANT], t0)
    finally:
        M._BASIS = prev

    verdict_word, why = verdict(res, checks)

    out = {
        "harness": "midas_sweep_shadow.py",
        "ts": now.isoformat(timespec="seconds"),
        "prereg": PREREG,
        "arm": {"tag": tag, "ledger": str(book), "rows": len(rows), "unreadable_lines": broken[:20]},
        "series": prov,
        "window_utc": list(M.SWEEP_WINDOW),
        "rule": {"variant": VARIANT, "n_target": N_TARGET, "t_bar": T_BAR,
                 "min_per_day": MIN_PER_DAY, "direction_checks": list(DIRECTION_CHECKS)},
        "checks": checks,
        "forward": {"t0": t0, "t1": t1, "results": res},
        "verdict": verdict_word, "verdict_detail": why,
    }
    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"arm      tag={tag!r}  ledger={book.name}  SWEEPSHADOW rows={len(rows)}"
          + (f"  UNREADABLE={len(broken)}" if broken else ""))
    print(f"series   corpus {prov['corpus_m15_rows']} m15 + {prov.get('appended_m15_rows', 0)} "
          f"appended from the terminal; offset +{off_min} min")
    print(f"window   UTC {M.SWEEP_WINDOW[0]}-{M.SWEEP_WINDOW[1]}")
    print(f"checks   EA rows in window {checks['rows_in_window']}, engine signal bars "
          f"{checks['engine_signal_bars_in_span']}, coverage {checks['coverage']}, "
          f"disagreements {checks['n_disagreements']}, unmatched {checks['n_unmatched']}")
    for v in M.SWEEP_VARIANTS:
        r = res[v]
        print(f"  {v:12s} sig {r['signal_bars']:4d}  n {r['n']:4d}  /day {r.get('per_day') or 0:5.2f}  "
              f"zero {(r.get('zero_day_share') or 0):6.1%}  meanR "
              f"{(r.get('mean_r') if r.get('mean_r') is not None else float('nan')):+8.4f}  "
              f"t {(r.get('t') if r.get('t') is not None else float('nan')):+6.3f}")
    print(f"\nVERDICT: {verdict_word} — {'; '.join(why)}")
    print(f"artifact: {ART.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

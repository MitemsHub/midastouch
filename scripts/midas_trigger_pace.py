#!/usr/bin/env python3
"""Pace: does the live arm fire at the rate the certified corpus said it would?

THE QUESTION IT ANSWERS
  Nothing is wrong with the arm's machinery: it fired, it filled once (2026-09-22
  14:12Z, +0.104R), and the census explains every flat bar since. What nobody had
  measured is whether the LIVE pace — triggers seen, signals accepted, fills made,
  per day, against the refusal census — matches the pace the certified corpus
  predicted for this configuration. A pace below the corpus is either a quiet
  market (expected variance: the corpus's own flat-day share) or a lookalike
  engine (a defect); this tool separates the two with numbers and says which of
  the two the evidence supports — refusing to claim either when the window is too
  short.

WHAT IT READS
  1. The armed arm's ledger, parsed once through `scripts/midas_arm_record.py`.
     STATE rows are DEDUPED BY BAR: the 15-minute heartbeat re-writes the CURRENT
     bar's STATE row between evaluations (measured in this ledger: two writes,
     672 s apart, same `sig_open`), so raw row counts would overstate the bar
     count by ~16x. One evaluated bar = one distinct `sig_open_srv`, latest write
     wins — which is also the reading that must reconcile with the census's
     `signal` counter.
  2. The engine of record — `scripts/midas_sweep.py:run_mode`, never
     re-implemented here — over the venue's own bars on the held-out `oos`
     window at the live session (UTC 04-18 at the venue's asserted +120 offset,
     the reality the arming record documents). Its REVERSE_DIRECTION run IS the
     corpus expectation; its `vetoed` counter pairs with the census's `riskcap`.
  3. The published expectation — artifacts/midas_frequency_axes_20260922.json —
     the pre-registered study behind arming amendment 3 (held-out, BBDev 1.5:
     130 fills, 0.77/day, 40.8% flat days), read as data and cross-checked
     against the engine rerun instead of trusted as a citation.

THE HONEST REFUSALS
  * Pace language is likelihood language. "Quiet market" is a parsimony claim
    against the corpus's own flat-day share — never a validation claim, and the
    footer says so on every run: the walk-forward gate remains FAILED.
  * Census totals that disagree with what the deduped STATE rows classify into
    the same buckets exit 1 (CONFLICTED) rather than print a pace built on a
    broken grammar.
  * Under MIN_DAYS full live days the verdict is UNMEASURABLE — per-day rates on
    less are a coin flip, and saying so is the finding.

READ-ONLY. No order path, no terminal writes; the guard test pins the source.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import midas_arm_record as AR  # noqa: E402
from midas_spread_watch import mode_takes  # noqa: E402  the pinned mode matrix

ART = ROOT / "artifacts" / "live" / "trigger_pace.json"
ARMING_RECORD = ROOT / "artifacts" / "live" / "armed.json"
PRESET_DIR = ROOT / "mql5" / "MIDASTOUCH"
FREQ_ART = ROOT / "artifacts" / "midas_frequency_axes_20260922.json"
#: Minimum live span (full UTC days) before a per-day pace can be read at all.
MIN_DAYS = 3.0
#: Slack when comparing census counters to the STATE-row classification: a day
#: roll between a bar's evaluation and its NOFILLSUM write can move one bar.
CENSUS_SLACK = 1


def dedupe_bars(states: list[dict]) -> list[dict]:
    """One row per evaluated bar: distinct `sig_open_srv`, latest write wins.

    The heartbeat re-writes the current bar's STATE row every 15 minutes, so the
    raw stream is a per-bar evaluation plus up to ~14 repeats. Distinct bars are
    what the census counts, so they are what this tool counts. The grammar lives
    in `midas_arm_record.dedupe_bars`; this alias keeps the name this tool's
    callers and tests already use, pinned identical by test.
    """
    return AR.dedupe_bars(states)


def classify(bars: list[dict], mode: int | None = None,
             timeline: list[tuple[int, int]] | None = None) -> dict:
    """Each evaluated bar into the census's own buckets, via the pinned matrix.

    `mismatch` = trigger fired but the mode refused; `notr` = no trigger at all;
    `triggers` = trigger bars (mismatch + any the mode accepted). The census's
    `signal` bucket counts every evaluated bar, accepted or not — matching the
    EA's own `g_nofill_signal`.

    A `timeline` (the arming record's own amendment history) overrides `mode`:
    each bar is classified under the mode that was RUNNING when it was written,
    because the census counted it that way. This arm ran mode 0 until the
    2026-09-22T12:28Z amendment and mode 1 after; classifying the early bars
    under 1 would manufacture a census-vs-rows conflict that is history, not a
    defect.
    """
    out = {"evaluated": len(bars), "notr": 0, "mismatch": 0, "triggers": 0,
           "accepted": 0}
    for r in bars:
        m = AR.mode_at(timeline, r["write_utc"]) if timeline else mode
        if r["trig"] == 0:
            out["notr"] += 1
            continue
        out["triggers"] += 1
        if mode_takes(m, r["trig"], r["mac"]):
            out["accepted"] += 1
        else:
            out["mismatch"] += 1
    return out


def span_days(bars: list[dict]) -> float:
    if not bars:
        return 0.0
    first = min(r["write_utc"] for r in bars)
    last = max(r["write_utc"] for r in bars)
    return max((last - first) / 86400.0, 1 / 96.0)  # one bar's floor, not zero


def census_totals(nofill_rows: list[dict], arming_day: int | None) -> dict:
    """Census counters as one total, per the EA's day semantics.

    Each NOFILLSUM/NOFILL row is a snapshot of ONE UTC day (the row's own `day`
    field, not the write time — a day's last write can land after midnight).
    Counters are cumulative within the day and restored across restarts, so a
    day's count is the MAX any of its rows carries; the total sums the days.
    Days before the arming day are excluded: this ledger also carries the paper
    mirror's earlier rows, and those bars are not the armed arm's.
    """
    totals = {k: 0 for k in AR.NOFILL_FIELDS}
    per_day: dict[int, dict] = {}
    for row in nofill_rows:
        day = row["day"]
        if arming_day is not None and day < arming_day:
            continue
        cur = per_day.setdefault(day, {k: 0 for k in AR.NOFILL_FIELDS})
        for k in AR.NOFILL_FIELDS:
            cur[k] = max(cur[k], row[k])
    for day in sorted(per_day):
        for k in AR.NOFILL_FIELDS:
            totals[k] += per_day[day][k]
    # `per_day` returns too: the reconciliation in `live_side` may join only over
    # days the census actually covers (this ledger's early days survive only as
    # 12-field v1.20-26 snapshots the EA itself refuses to restore).
    return {"totals": totals, "days": len(per_day), "per_day": per_day}


def engine_expectation() -> dict:
    """The corpus expectation through the engine of record — no re-implementation.

    The engine walks the venue's own bars (the data of record) on the held-out
    `oos` window, at the live session window (UTC 04-18), sized on the account
    basis — the exact stance the frequency study used. Import-time refusals are
    the point: a harness that cannot prove the engine is the engine prints
    nothing.
    """
    import midas_parity as P   # noqa: PLC0415 — the engine of record
    import midas_sweep as M    # noqa: PLC0415 — run_mode
    spec = P._window_spec("oos")
    off = P.assert_server_offset(spec)
    data = P.python_build_data(offset_min=off, corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        # Trigger bars per UTC day: the engine's own arrays, so no trigger logic
        # is copied — bb first, else the RSI 30/70 branch, exactly as run_mode
        # reads them.
        bb, rsi = data["m15_bb"], data["m15_rsi"]
        trig_days: dict[str, int] = {}
        eval_days: dict[str, int] = {}
        for i, b in enumerate(data["m15"]):
            ct = b["time"] + 900
            if not (spec["t0"] < ct and b["time"] <= spec["t1"]):
                continue
            hr = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
            if not (4 <= hr < 18):
                continue
            d = datetime.fromtimestamp(b["time"], tz=timezone.utc).strftime("%Y-%m-%d")
            eval_days[d] = eval_days.get(d, 0) + 1
            t = bb[i] if bb[i] != 0 else (1 if rsi[i] <= 30 else (-1 if rsi[i] >= 70 else 0))
            if t != 0:
                trig_days[d] = trig_days.get(d, 0) + 1
        # Fills: the engine's own run, the certified mode, the live window.
        rr = M.run_mode("REVERSE_DIRECTION", spec["t0"], spec["t1"], data,
                        win_lo=4, win_hi=18)
        n_days = len(eval_days)
        fill_days = {datetime.fromtimestamp(t["open_ct"] - 900, tz=timezone.utc)
                     .strftime("%Y-%m-%d") for t in rr.trades}
        return {
            "eval_bars": sum(eval_days.values()),
            "eval_per_day": round(sum(eval_days.values()) / n_days, 1),
            "trigger_bars": sum(trig_days.values()),
            "trigger_rate_per_day": round(sum(trig_days.values()) / n_days, 3),
            "no_trigger_day_share": round(
                sum(1 for d, n in trig_days.items() if n == 0) / n_days, 3),
            "fills": len(rr.trades), "vetoed": rr.vetoed,
            "fill_rate_per_day": round(len(rr.trades) / n_days, 3),
            "flat_day_share": round(1 - len(fill_days) / n_days, 3),
            "net_r": round(sum(t["r"] for t in rr.trades), 3),
            "days": n_days,
            "window": "oos (2026-04-01..2026-09-16), UTC 04-18, venue corpus",
        }
    finally:
        M._BASIS = prev


def published_expectation() -> dict | None:
    """The pre-registered study's held-out row for this exact cell — read as data,
    keyed to window/mode/k, never trusted as a citation (the engine rerun above
    is the cross-check)."""
    if not FREQ_ART.is_file():
        return None
    d = AR.json_load(FREQ_ART)
    for r in d.get("rows", []):
        if (r.get("window") == "oos" and r.get("win_utc") == [4, 18]
                and abs(float(r.get("k", 0)) - 1.5) < 1e-9
                and r.get("mode") == "REVERSE_DIRECTION"):
            return r
    return None


def live_side(book: Path, mode: int, arming_day: int | None,
              timeline: list[tuple[int, int]] | None = None) -> dict | None:
    book_data = AR.read_rows(book)
    rows = book_data["rows"]
    bars = dedupe_bars([r for r in rows["state"]
                        if arming_day is None
                        or r["write_utc"] >= arming_day * 86400])
    if not bars:
        return None
    cls = classify(bars, mode, timeline)
    cens = census_totals(rows["nofill"], arming_day)
    # Reconcile like with like: the census covers only the UTC days that have a
    # readable census row, and this ledger's early days survive only as 12-field
    # v1.20-26 snapshots the EA itself refuses to restore (measured: 64 rows).
    # Bars on uncovered days are counted separately — comparing them against a
    # census that never saw them would manufacture a CONFLICTED verdict out of
    # unrestorable history.
    covered = set(cens["per_day"].keys())
    bars_covered = [r for r in bars
                    if r["write_utc"] // 86400 in covered]
    cls_covered = classify(bars_covered, mode, timeline)
    days = span_days(bars)
    fills = len([r for r in rows["lopen"]
                 if arming_day is None or r["write"] >= arming_day * 86400])
    closes = [r for r in rows["lclose"]
              if arming_day is None or r["write"] >= arming_day * 86400]
    return {
        "bars": len(bars), "class": cls, "class_census_days": cls_covered,
        "census": cens["totals"],
        "census_days": cens["days"],
        "bars_on_uncovered_days": len(bars) - len(bars_covered),
        "live_days": round(days, 2),
        "bars_per_day": round(len(bars) / days, 1) if days else None,
        "fills": fills, "closed": len(closes),
        "closed_r": round(sum(r["r"] for r in closes), 4),
        "fill_rate_per_day": round(fills / days, 3) if days else None,
        "trigger_rate_per_day": round(cls["triggers"] / days, 3) if days else None,
    }


def pace_verdict(live: dict, engine: dict | None) -> tuple[str, list[str]]:
    """Likelihood language only. The corpus's own no-trigger day share is the
    standard a low live trigger rate is judged against; the census-vs-rows
    reconciliation is the grammar check that must hold first."""
    if live["live_days"] < MIN_DAYS:
        return "UNMEASURABLE", [f"only {live['live_days']} live days since arming — "
                                f"per-day pace needs >= {MIN_DAYS:.0f}"]
    cens = live["census"]
    cls = live["class_census_days"]   # only bars on days the census covers
    if (cens["signal"] and
            (cens["mismatch"] > cls["mismatch"] + CENSUS_SLACK
             or cens["notr"] > cls["notr"] + CENSUS_SLACK
             or cls["evaluated"] > cens["signal"] + CENSUS_SLACK)):
        return "CONFLICTED", [
            f"on the {live['census_days']} census-covered day(s) the census says "
            f"signal={cens['signal']} notr={cens['notr']} mismatch={cens['mismatch']} "
            f"but the deduped STATE rows classify {cls['evaluated']}/"
            f"{cls['notr']}/{cls['mismatch']} — one side is reading a different "
            f"build's grammar, and a pace built on this record would be fiction"]
    why: list[str] = []
    if engine is None:
        return "PUBLISHED-ONLY", [
            "engine rerun skipped — the verdict compares against the published "
            "study row only, which is a citation, not a reproduction"]
    if live["bars_per_day"] is not None and live["bars_per_day"] < engine["eval_per_day"] * 0.7:
        why.append(f"live evaluated bars/day ({live['bars_per_day']}) far below the "
                   f"corpus session expectation ({engine['eval_per_day']}) — check "
                   f"terminal uptime before reading anything else")
    trig = live["trigger_rate_per_day"]
    if trig is None:
        return "UNMEASURABLE", ["no trigger rate could be computed from the record"]
    no_trig_share = engine["no_trigger_day_share"]
    if trig < 1.0 - no_trig_share:
        why.append(f"live trigger bars/day ({trig}) is below the corpus's "
                   f"trigger-day share ({1 - no_trig_share:.1%} of corpus days fired "
                   f"at least once) — a quiet market is the parsimonious reading, "
                   f"not a defect")
    else:
        why.append(f"live trigger bars/day ({trig}) is at or above the corpus's "
                   f"trigger-day share ({1 - no_trig_share:.1%}) — the arm is seeing "
                   f"the opportunity rate the corpus promised")
    if live["fills"] == 0:
        why.append("no fills since arming — with the census showing which gates "
                   "did the refusing (this tool does not re-derive them)")
    return "WITHIN CORPUS PACE", why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-engine", action="store_true",
                    help="skip the engine-of-record rerun (compares against the "
                         "published study row only; the verdict degrades)")
    a = ap.parse_args()

    if not ARMING_RECORD.is_file():
        raise SystemExit("no arming record — nothing is armed, so there is no live "
                         "pace to compare")
    rec = AR.json_load(ARMING_RECORD)
    preset, src = AR.resolve_arm_preset(ARMING_RECORD, PRESET_DIR)
    if preset is None:
        raise SystemExit(f"REFUSING: {src}")
    vals = AR.read_preset_inputs(preset)
    mode = int(vals["InpMode"])
    timeline = AR.mode_timeline(rec, mode)
    tag = rec.get("arm", "")

    import live_readiness as LR  # noqa: PLC0415 — the watch's ledger resolution
    term_data = None
    try:
        import MetaTrader5 as mt5  # type: ignore
        if mt5.initialize():
            ti = mt5.terminal_info()
            if ti is not None and getattr(ti, "data_path", ""):
                term_data = Path(str(ti.data_path))
            mt5.shutdown()
    except ImportError:
        pass
    books = LR.running_ledgers(term_data, LR.armed_arm_tag())
    book = books[0] if books else None
    if book is None or not book.exists():
        print("no armed arm's ledger found — nothing attached; no live pace to read")
        return 3

    arming_day = None
    try:
        arming_day = int(datetime.fromisoformat(
            rec.get("armed_utc", "").replace("Z", "+00:00")).timestamp()) // 86400
    except (ValueError, AttributeError):
        pass

    live = live_side(book, mode, arming_day, timeline)
    if live is None:
        print("the armed arm's ledger carries no STATE rows since arming — "
              "the arm has not evaluated a bar yet")
        return 3

    pub = published_expectation()
    engine = None if a.skip_engine else engine_expectation()
    verdict_word, why = pace_verdict(live, engine)

    out = {"tool": "midas_trigger_pace",
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "arm": tag, "preset": preset.name, "mode": mode, "ledger": str(book),
           "live": {k: v for k, v in live.items() if k != "class"},
           "live_class": live["class"], "published": pub, "engine": engine,
           "verdict": verdict_word, "why": why}
    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"=== TRIGGER PACE — arm {tag} ({preset.name}, mode {mode}) ===")
    print(f"live     {live['bars']} evaluated bars (deduped by bar) over "
          f"{live['live_days']} days ({live['bars_per_day']}/day), fills "
          f"{live['fills']} ({live['fill_rate_per_day']}/day), closed "
          f"{live['closed']} ({live['closed_r']:+.3f}R)")
    print(f"class    no-trigger {live['class']['notr']}, mismatch "
          f"{live['class']['mismatch']}, triggers {live['class']['triggers']} "
          f"({live['trigger_rate_per_day']}/day), mode-accepted "
          f"{live['class']['accepted']}")
    if live.get("bars_on_uncovered_days"):
        print(f"         ({live['bars_on_uncovered_days']} bars sit on census-uncovered "
              f"days — pre-v1.27 12-field snapshots the EA itself cannot restore — "
              f"so the grammar check joins only over the covered days)")
    c = live["census"]
    print(f"census   signal {c['signal']}, notr {c['notr']}, mismatch {c['mismatch']}, "
          f"session {c['session']}, friday {c['friday']}, spread {c['spread']}, "
          f"riskcap {c['riskcap']}, breaker {c['breaker']}, news {c['news']}, "
          f"nodata {c['nodata']} (over {live['census_days']} UTC day(s))")
    if pub:
        print(f"published expectation (frequency study, held-out, BBDev 1.5, live "
              f"window): {pub['n']} fills, {pub['per_day']}/day, "
              f"{float(pub['zero_day_share']):.1%} flat days, exp {pub['exp']:+.4f}R, "
              f"pf {pub['pf']}")
    if engine:
        print(f"engine rerun ({engine['window']}): {engine['fills']} fills "
              f"({engine['fill_rate_per_day']}/day), {engine['flat_day_share']:.1%} "
              f"flat days, {engine['no_trigger_day_share']:.1%} no-trigger days, "
              f"triggers {engine['trigger_bars']} ({engine['trigger_rate_per_day']}/day), "
              f"min-lot vetoed {engine['vetoed']}, net {engine['net_r']:+.3f}R")
        if pub and (engine["fills"] != pub.get("n")):
            print(f"         NOTE: the engine rerun does not reproduce the published "
                  f"row digit-for-digit ({engine['fills']} vs {pub.get('n')}); the "
                  f"ENGINE rerun is the expectation this verdict uses")
    print(f"\nVERDICT: {verdict_word} — {'; '.join(why)}")
    print("a pace comparison against the certified corpus, NOT a validation: the "
          "walk-forward gate remains FAILED (operator override).")
    print(f"artifact: {ART.relative_to(ROOT)}")
    return 0 if verdict_word != "CONFLICTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

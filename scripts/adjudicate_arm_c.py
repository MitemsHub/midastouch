"""Arm-C candidate adjudicator — the frozen daily-paired rule.

Pre-registered in docs/ARM_C_TEMPLATE.md (rule 2026-09-15; G5 amendment
2026-09-15, appended before any candidate data exists). This tool implements
that text and nothing else:

  G1 count     : C has >= 30 CLOSED trades with exit epoch <= C-end epoch.
                 Below 30: KEEP COLLECTING (ETA from the observed rate) —
                 count is a schedule gate, not an evidence-poisoning gate.
  G2 coverage  : C's window spans >= 21 calendar days AND arm A's ledger is
                 alive on every one of C's trading days AND A's ledger covers
                 >= 70% of the window's calendar days. A dead-A day under a
                 trading C is a G2/G3 event -> INVALID (a paired day with no
                 reference is not a paired day).
  G3 integrity : both ledgers clean — zero unmatched CLOSE rows (CLOSE whose
                 key has no OPEN row), zero duplicate OPEN tickets, at most 1
                 dangling OPEN (a live trade), C's veq bookkeeping exact
                 (close-to-close equity delta == that row's pnl; V75 paper
                 book updates equity only at closes), and zero WLOST
                 quarantine tags in the journals over the window.
  G4 contamination : per-engine journal init-banner blocks within the window
                 must be pairwise identical after version tokens are masked
                 (an input change -> INVALID, the same standard the primary
                 A/B demanded). Zero init blocks found, or no journals
                 provided -> the frozen rule cannot be verified -> INVALID
                 (data-gate class, like a stale monitor). One init block is
                 clean by MQL5 semantics: inputs are fixed at init and cannot
                 change without a re-init. Version tokens are reported, not
                 diffed (a version bump is not an input change).
  G5 strangulation floor (amendment 2026-09-15): the window MINIMUM of C's
                 equity (ledger CLOSE veq rows, close-boundary resolution)
                 must be >= the ATR monitor's floor_certified at every point
                 of the window — the minimum, not the end value. A stale
                 monitor (> 8 days) or a missing block fails G5 as a data
                 gate. Sub-cases: start equity already below floor = (a) the
                 floor rose (ATR drift -> floor-amendment path); start
                 compliant then dipped = (b) the streak death mode (window
                 INVALIDATION, not a candidate verdict — no REJECTED is
                 recorded and re-collection at compliant equity is allowed).
                 Intra-trade floating drawdown is not in the ledger; G5 sees
                 realized equity at trade boundaries, as the frozen text
                 specifies ("taken from its own ledger EQ rows").

  Statistics   : one observation per calendar day on which BOTH arms closed
                 >= 1 trade: d_i = meanR_C(day) - meanR_A(day). Primary:
                 mean(d_i) and the paired one-sample t against 0 (the
                 template's "Welch t of the daily paired series"; the exact
                 formula is recorded in the artifact). n_d in [13,14] always
                 breaks to INCONCLUSIVE (scarcity never manufactures
                 confidence).
  Decision     : CONFIRMED  n_d >= 15 AND T >= +1.0 AND mean(d_i) > 0 AND
                            totalR_C >= totalR_A(concurrent) AND G1-G5 clean
                 REJECTED   n_d >= 15 AND T <= -1.0 AND mean(d_i) < 0
                 else       INCONCLUSIVE (collect to 30 paired days max)

Day keys are UTC calendar days of the broker-epoch timestamps; both arms
share the broker clock, so pairing is clock-consistent (the boundary choice
only moves near-midnight trades between adjacent days, identically defined
for both arms).

Usage:
  python scripts/adjudicate_arm_c.py --c-dir "<FB9A>/MQL5/Files" \
      --a-ledger artifacts/v75_replay/armA_reference_<date>.csv \
      --journal-dir "<FB9A>/MQL5/Logs" [--journal-dir "<71BF>/MQL5/Logs"]
Writes: artifacts/v75_replay/arm_c_adjudication.json
"""
from __future__ import annotations

import argparse
import calendar
import glob
import json
import math
import os
import re
import time

try:
    from artifact_spec import assert_spec_integrity, spec_block
except ImportError:  # package-style import (tests)
    from scripts.artifact_spec import assert_spec_integrity, spec_block

try:
    import era
except ImportError:  # package-style import (tests)
    from scripts import era

OUT = os.path.join("artifacts", "v75_replay", "arm_c_adjudication.json")
C_LEDGER_NAME = "V75MacroEngine_paper_Volatility_75_Index.csv"
MONITOR_PATH = os.path.join("artifacts", "v75_replay", "atr_drift_monitor.json")

MIN_TRADES = 30            # G1
MIN_SPAN_DAYS = 21         # G2
MIN_A_COVERAGE = 0.70      # G2
MIN_PAIRED_DAYS = 15       # decision mapping
CAP_PAIRED_DAYS = 30       # INCONCLUSIVE collection cap
TIEBREAK_LO, TIEBREAK_HI = 13, 14
T_DECLARE = 1.0
FLOOR_STALE_DAYS = 8       # G5 monitor staleness
MAGIC_C = 7788125

JOURNAL_TS = re.compile(r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})")
VERSION_TOKEN = re.compile(r"v\d+\.\d+")
ENGINE_CHANNELS = ("MitemshubAI", "V75MacroEngine")


def day_key(epoch: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def day_diff(k0: str, k1: str) -> int:
    t0 = time.strptime(k0, "%Y-%m-%d")
    t1 = time.strptime(k1, "%Y-%m-%d")
    return (calendar.timegm(t1) - calendar.timegm(t0)) // 86400


def parse_ledger(path: str, engine: str):
    """Unified OPEN/CLOSE/EQ parser — one format serves both engines.

    OPEN,epoch,ticket,dir,entry,sl,tp,vol,eff_risk$,stop_dist,max_hold,tag
    CLOSE,epoch,ticket|open_epoch,reason,exit,r,pnl,veq
    EQ,veq
    (V75MacroEngine writes its OPEN epoch in the ticket column; matching by
    that key works identically for both engines.)"""
    trades, curve, problems = [], [], []
    open_rows = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            parts = line.strip().split(",")
            if not parts or parts[0] == "":
                continue
            if parts[0] == "ERA":
                continue   # provenance row (v26.39+ / v2.24+); scripts/era.py owns it
            if parts[0] == "OPEN":
                if len(parts) < 4:
                    problems.append(f"line {ln}: OPEN row too short")
                    continue
                key = parts[2]
                if key in open_rows:
                    problems.append(f"duplicate OPEN ticket {key}")
                open_rows[key] = int(parts[1])
            elif parts[0] == "CLOSE":
                if len(parts) < 8:
                    problems.append(f"line {ln}: CLOSE row too short")
                    continue
                key = parts[2]
                matched = key in open_rows
                if not matched:
                    problems.append(f"CLOSE without OPEN row (key {key})")
                else:
                    del open_rows[key]
                trades.append({
                    "epoch": int(parts[1]), "key": key, "reason": parts[3],
                    "r": float(parts[5]), "pnl": float(parts[6]),
                    "veq": float(parts[7]), "matched": matched, "line": ln,
                })
            elif parts[0] == "EQ":
                curve.append(float(parts[1]))
    if len(open_rows) > 1:
        problems.append(f"{len(open_rows)} OPEN rows never closed (live trade + extras)")
    if engine == "V75MacroEngine":
        # exact paper-book check: equity moves only at closes, by that row's pnl
        for a, b in zip(trades, trades[1:]):
            if abs((b["veq"] - a["veq"]) - b["pnl"]) > 0.011:
                problems.append(
                    f"veq bookkeeping break at close epoch {b['epoch']}: "
                    f"delta {b['veq'] - a['veq']:.2f} != pnl {b['pnl']:.2f}")
                break
    return trades, curve, problems


def read_journal_lines(path: str):
    raw = open(path, "rb").read()
    for enc in ("utf-16-le", "cp1252", "utf-8"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-16-le", errors="replace").splitlines()


def scan_journals(dirs, w0: int, w1: int):
    """Window-filtered journal scan -> (wlost, banner_blocks, veto_counts).

    banner_blocks: engine -> list of blocks; a block is a time-clustered run
    of version-tagged lines (gap <= 120s, >= 3 lines = an init banner)."""
    wlost, blocks, veto = [], {}, {}
    for d in dirs or []:
        for path in sorted(glob.glob(os.path.join(d, "*.log"))):
            for line in read_journal_lines(path):
                m = JOURNAL_TS.search(line)
                if not m:
                    continue
                ts = calendar.timegm(time.strptime(m.group(1), "%Y.%m.%d %H:%M:%S"))
                if ts < w0 or ts > w1:
                    continue
                if "WLOST" in line:
                    wlost.append({"path": os.path.basename(path), "ts": ts,
                                  "line": line.strip()[:160]})
                engine = next((e for e in ENGINE_CHANNELS if e + " (" in line), None)
                if engine is None or not VERSION_TOKEN.search(line):
                    continue
                msg = VERSION_TOKEN.sub("vX", line.split("\t")[-1].strip())
                blocks.setdefault(engine, []).append((ts, msg))
                if "REFUSED" in line.upper() or "RISK-CAP" in line.upper() \
                        or "RISK CAP" in line.upper():
                    veto[engine] = veto.get(engine, 0) + 1
    clustered = {}
    for engine, items in blocks.items():
        items.sort()
        runs, cur = [], []
        for ts, msg in items:
            if cur and ts - cur[-1][0] > 120:
                runs.append(cur)
                cur = []
            cur.append((ts, msg))
        if cur:
            runs.append(cur)
        clustered[engine] = [msgs for run in runs if len(run) >= 3
                             for msgs in [[m for _, m in run]]]
    return wlost, clustered, veto


def evaluate_g4(clustered: dict):
    """Returns (status, detail). status in {"clean", "INVALID", "UNVERIFIED"}."""
    if not clustered:
        return "UNVERIFIED", "no version-tagged journal lines in window"
    details, ok = {}, True
    for engine, cl in sorted(clustered.items()):
        if not cl:
            details[engine] = "no init banner found -> UNVERIFIED"
            ok = False
            continue
        first = cl[0]
        diffs = [i for i, b in enumerate(cl[1:], 2) if b != first]
        details[engine] = (f"{len(cl)} init block(s); "
                           + ("all identical" if not diffs
                              else f"block(s) {diffs} differ from block 1"))
        if diffs:
            ok = False
            details[engine + " diff sample"] = [
                x for a, b in zip(cl[0], cl[diffs[0] - 1]) if a != b for x in (f"'{a}' -> '{b}'",)][:4]
    return ("clean" if ok else "INVALID"), details


def load_floor(monitor_path: str):
    """-> (floor_certified or None, error or None) from the ATR monitor."""
    if not os.path.exists(monitor_path):
        return None, f"monitor artifact missing: {monitor_path}"
    readings = json.load(open(monitor_path, encoding="utf-8-sig"))
    if not readings:
        return None, "monitor artifact has no readings"
    last = readings[-1]
    sf = last.get("strangulation_floor") or {}
    floor = sf.get("floor_certified")
    if floor is None:
        return None, "latest monitor reading has no strangulation_floor block"
    gen = last.get("generated_utc")
    if gen:
        try:
            gen_ts = calendar.timegm(time.strptime(gen[:19], "%Y-%m-%dT%H:%M:%S"))
            age = (time.time() - gen_ts) / 86400.0
            if age > FLOOR_STALE_DAYS:
                return None, f"monitor reading stale ({age:.1f}d > {FLOOR_STALE_DAYS}d)"
        except ValueError:
            return None, f"unparseable monitor timestamp: {gen}"
    return float(floor), None


def paired_t(deltas):
    """Paired one-sample t against 0 (the template's 'Welch t of the daily
    paired series'). Zero-variance series: +-999 (perfectly consistent)."""
    m = len(deltas)
    if m < 2:
        return 0.0
    mean = sum(deltas) / m
    var = sum((x - mean) ** 2 for x in deltas) / (m - 1)
    if var <= 0:
        return 0.0 if mean == 0 else (999.0 if mean > 0 else -999.0)
    return mean / math.sqrt(var / m)


def run(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c-dir", default=None, help="terminal Files dir holding C's V75MacroEngine_paper ledger")
    ap.add_argument("--c-ledger", default=None, help="override C ledger path")
    ap.add_argument("--a-ledger", required=True, help="arm A reference ledger (byte-copy snapshot at activation)")
    ap.add_argument("--c-start-epoch", type=int, default=None)
    ap.add_argument("--c-end-epoch", type=int, default=None)
    ap.add_argument("--journal-dir", action="append", default=[], help="MQL5/Logs dir (repeatable)")
    ap.add_argument("--monitor", default=MONITOR_PATH)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    assert_spec_integrity()
    out = {
        "rule": "docs/ARM_C_TEMPLATE.md daily-paired rule (2026-09-15) + G5 amendment (2026-09-15)",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "spec": spec_block(artifact="arm_c_adjudication", tp_mult="candidate"),
        "inputs": {k: getattr(args, k) for k in
                   ("c_dir", "c_ledger", "a_ledger", "c_start_epoch", "c_end_epoch",
                    "journal_dir", "monitor", "out")},
        "gates": {}, "stats": {}, "external_checks": [], "verdict": None,
    }
    invalid = []   # list of {"gate", "detail"[, "sub_case"]}

    # ---- ledgers
    c_path = args.c_ledger or os.path.join(args.c_dir, C_LEDGER_NAME)
    engines = {}
    for name, path, engine in (("C", c_path, "V75MacroEngine"), ("A", args.a_ledger, "MitemshubAI")):
        if not os.path.exists(path):
            invalid.append({"gate": "data", "detail": f"{name} ledger missing: {path}"})
            engines[name] = ([], [], [f"missing: {path}"])
            continue
        engines[name] = parse_ledger(path, engine)
    c_trades, c_curve, c_prob = engines["C"]
    a_trades, a_curve, a_prob = engines["A"]

    # ---- era separation (OPERATING_SUMMARY 2026-09-15 amendment, append-only):
    # pre-v26.38 arm-A trades carry bar-open fills; the candidate comparison is
    # defined on the per-tick-fill era only. C's side is a no-op today (its
    # engine always filled per tick) but stays symmetric and future-proof.
    era_rows_c = era.parse_era_rows(c_path)
    era_rows_a = era.parse_era_rows(args.a_ledger)
    era_c_split = era.era_split(c_trades, "V75MacroEngine", era_rows_c)
    era_a_split = era.era_split(a_trades, "MitemshubAI", era_rows_a)
    a_trades = era.era_filter(a_trades, "MitemshubAI", era.ERA_POST, era_rows_a)
    c_trades = era.era_filter(c_trades, "V75MacroEngine", era.ERA_POST, era_rows_c)
    out["era"] = {
        "boundary_epoch": era.ERA_EPOCH,
        "boundary_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(era.ERA_EPOCH)),
        "filter": era.ERA_POST,
        "c_split": era_c_split, "a_split": era_a_split,
        "n_c_post": len(c_trades), "n_a_post": len(a_trades),
        "c_era_rows": era_rows_c, "a_era_rows": era_rows_a,
        "note": "pre-boundary arm-A trades (bar-open fills) are excluded from every statistic; "
                "the G1 count and the paired statistics are post-era only",
    }

    out["inputs"]["c_ledger_resolved"] = c_path
    out["inputs"]["n_c_close_rows_total"] = len(c_trades)
    out["inputs"]["n_a_close_rows_total"] = len(a_trades)

    # ---- window
    w0 = args.c_start_epoch or (min((t["epoch"] for t in c_trades), default=None))
    w1 = args.c_end_epoch or (max((t["epoch"] for t in c_trades), default=None))
    if w0 is None or w1 is None:
        # no C data yet: judge nothing, scan nothing, keep collecting
        now = int(time.time())
        w0, w1 = now - 86400, now
        out["external_checks"].append("C has no closed trades: window defaulted to last 24h")
    out["inputs"]["window"] = [w0, w1, day_key(w0), day_key(w1)]

    # ---- journals (G3 WLOST clause + G4 + auxiliary funnel counters)
    wlost, clustered, veto = scan_journals(args.journal_dir, w0, w1)
    if wlost:
        invalid.append({"gate": "G3", "detail": f"{len(wlost)} WLOST quarantine tag(s) in journals over window",
                        "samples": wlost[:3]})

    # ---- G3 ledger integrity (both ledgers)
    g3_prob = c_prob + a_prob
    out["gates"]["G3"] = {"problems": g3_prob or "clean",
                          "wlost_in_window": len(wlost)}
    if g3_prob:
        invalid.append({"gate": "G3", "detail": "; ".join(g3_prob[:5])})

    # ---- G4 contamination
    g4_status, g4_detail = evaluate_g4(clustered)
    out["gates"]["G4"] = {"status": g4_status, "detail": g4_detail}
    if g4_status != "clean":
        invalid.append({"gate": "G4", "detail":
                        "cannot verify the frozen no-input-change rule" if g4_status == "UNVERIFIED"
                        else f"input change detected: {g4_detail}"})

    # ---- G5 strangulation floor
    floor, floor_err = load_floor(args.monitor)
    out["gates"]["G5"] = {"floor_certified": floor, "monitor_error": floor_err}
    if floor_err:
        invalid.append({"gate": "G5", "detail": f"floor data gate: {floor_err}"})
    elif c_trades:
        pts = []
        for t in c_trades:
            pts.append((t["epoch"], t["veq"] - t["pnl"]))   # equity before the close
            pts.append((t["epoch"], t["veq"]))              # equity after the close
        pts.append((w0, c_trades[0]["veq"] - c_trades[0]["pnl"]))
        win_min = min(v for _, v in pts)
        start_eq = pts[0][1]
        daily_min = {}
        for e, v in pts:
            k = day_key(e)
            daily_min[k] = min(daily_min.get(k, float("inf")), v)
        breach_days = sorted(k for k, v in daily_min.items() if v < floor)
        out["gates"]["G5"].update({
            "window_min_equity": round(win_min, 2), "start_equity": round(start_eq, 2),
            "daily_min_by_day": {k: round(v, 2) for k, v in sorted(daily_min.items())},
            "breach_days": breach_days,
            "resolution_note": "close-boundary equity (ledger CLOSE veq rows); floating DD not in ledger",
        })
        if breach_days:
            sub = "a" if start_eq < floor else "b"
            invalid.append({"gate": "G5",
                            "detail": (f"window-min equity {win_min:.2f} < floor_certified {floor:.2f} "
                                       f"(start {start_eq:.2f}); sub-case ({sub}): "
                                       + ("floor rose above equity (ATR drift -> floor-amendment path)"
                                          if sub == "a" else
                                          "equity fell below a stable floor (streak death mode; window "
                                          "INVALIDATION, not a candidate verdict — re-collect at "
                                          "compliant equity under the same template)")),
                            "sub_case": sub})

    # ---- G2 coverage (day-span membership, not epoch bounds: A's trades that
    # closed later on C's final day are still in the same calendar-day span)
    w0d, w1d = day_key(w0), day_key(w1)
    c_days = sorted({day_key(t["epoch"]) for t in c_trades})
    a_days = sorted({day_key(t["epoch"]) for t in a_trades if w0d <= day_key(t["epoch"]) <= w1d})
    span_days = (day_diff(day_key(w0), day_key(w1)) + 1) if c_trades else 0
    a_alive_on_c_days = set(c_days) <= set(a_days)
    coverage = (len(a_days) / span_days) if span_days else 0.0
    out["gates"]["G2"] = {"span_days": span_days, "c_trading_days": len(c_days),
                          "a_days_in_window": len(a_days),
                          "a_alive_on_all_c_days": a_alive_on_c_days,
                          "a_coverage": round(coverage, 3)}
    if c_trades and span_days < MIN_SPAN_DAYS:
        keep_collecting = (f"C window {span_days}d < {MIN_SPAN_DAYS}d — not yet adjudicable")
    if c_trades and not a_alive_on_c_days:
        invalid.append({"gate": "G2", "detail":
                        "arm A not alive on every C trading day (dead-reference day under a trading C)"})
    elif c_trades and coverage < MIN_A_COVERAGE:
        invalid.append({"gate": "G2", "detail":
                        f"A coverage {coverage:.3f} < {MIN_A_COVERAGE} of the window"})

    # ---- G1 count
    n_c = len(c_trades)
    out["gates"]["G1"] = {"closed_trades": n_c, "required": MIN_TRADES}
    eta = None
    if c_trades and 0 < span_days:
        rate = n_c / span_days
        eta = {"days_to_30": round((MIN_TRADES - n_c) / rate, 1) if n_c < MIN_TRADES else 0}
    out["gates"]["G1"]["eta"] = eta

    # ---- statistics + decision (only on a fully clean gate stack)
    keep_msg = locals().get("keep_collecting")
    if c_trades and n_c < MIN_TRADES and not keep_msg:
        keep_msg = f"C has {n_c} closed trades < {MIN_TRADES} (G1) — count is a schedule gate"
    if invalid:
        names = sorted({i["gate"] for i in invalid})
        out["verdict"] = {"status": "INVALID", "gates": names, "reasons": invalid}
        out["stats"]["note"] = "nothing is declared on an INVALID window (frozen §1 rule)"
    elif keep_msg:
        out["verdict"] = {"status": "KEEP COLLECTING", "reason": keep_msg, "eta": eta,
                          "note": "count/span shortfalls are schedule gates, not evidence gates"}
    else:
        c_win = [t for t in c_trades if w0 <= t["epoch"] <= w1]   # G1's epoch rule for C
        # A's concurrent book: every A trade on a day inside C's day span
        a_win = [t for t in a_trades if w0d <= day_key(t["epoch"]) <= w1d]
        c_by_day, a_by_day = {}, {}
        for t in c_win:
            c_by_day.setdefault(day_key(t["epoch"]), []).append(t["r"])
        for t in a_win:
            a_by_day.setdefault(day_key(t["epoch"]), []).append(t["r"])
        days = sorted(set(c_by_day) & set(a_by_day))
        deltas = [sum(c_by_day[d]) / len(c_by_day[d]) - sum(a_by_day[d]) / len(a_by_day[d])
                  for d in days]
        n_d, mean_d, t = len(days), (sum(deltas) / len(deltas) if deltas else 0.0), paired_t(deltas)
        totalR_c = sum(t_["r"] for t_ in c_win)
        totalR_a = sum(t_["r"] for t_ in a_win)

        def mix(ts):
            return {k: sum(1 for x in ts if x["reason"] == k) for k in sorted({x["reason"] for x in ts})}

        out["stats"] = {
            "n_paired_days": n_d, "cap": CAP_PAIRED_DAYS,
            "mean_d_i": round(mean_d, 4), "t": round(t, 2),
            "t_formula": "paired one-sample t: mean(d_i)/sqrt(var(d_i)/n_d); zero-variance -> +-999",
            "total_r_c": round(totalR_c, 2), "total_r_a_concurrent": round(totalR_a, 2),
            "aux": {
                "c": {"n": len(c_win), "wr": round(100 * sum(1 for x in c_win if x["r"] > 0) / len(c_win), 1) if c_win else None,
                      "reasons": mix(c_win), "trades_per_day": round(len(c_win) / span_days, 2) if span_days else None},
                "a": {"n": len(a_win), "wr": round(100 * sum(1 for x in a_win if x["r"] > 0) / len(a_win), 1) if a_win else None,
                      "reasons": mix(a_win)},
                "funnel_veto_counts_journals": veto,
            },
        }
        if TIEBREAK_LO <= n_d <= TIEBREAK_HI:
            status = "INCONCLUSIVE"
            reason = (f"n_d={n_d} in [{TIEBREAK_LO},{TIEBREAK_HI}] — pre-declared tie-breaker: "
                      "scarcity breaks toward INCONCLUSIVE, never toward a verdict")
        elif n_d >= MIN_PAIRED_DAYS and t >= T_DECLARE and mean_d > 0 and totalR_c >= totalR_a:
            status, reason = "VALIDATED-CANDIDATE-CONFIRMED", (
                f"n_d={n_d} >= {MIN_PAIRED_DAYS}, T={t:.2f} >= +{T_DECLARE}, mean(d_i)={mean_d:.4f} > 0, "
                f"totalR_C {totalR_c:.2f} >= totalR_A {totalR_a:.2f}, G1-G5 clean")
        elif n_d >= MIN_PAIRED_DAYS and t <= -T_DECLARE and mean_d < 0:
            status, reason = "REJECTED", (
                f"n_d={n_d} >= {MIN_PAIRED_DAYS}, T={t:.2f} <= -{T_DECLARE}, mean(d_i)={mean_d:.4f} < 0 "
                "-> teardown; the candidate is retired, not re-tuned")
        else:
            status = "INCONCLUSIVE"
            reason = (f"n_d={n_d} < {MIN_PAIRED_DAYS}" if n_d < MIN_PAIRED_DAYS else
                      f"n_d={n_d}, T={t:.2f}, mean(d_i)={mean_d:.4f} does not meet either declare branch")
            if n_d < CAP_PAIRED_DAYS:
                reason += f" -> collect to {CAP_PAIRED_DAYS} paired days max; then REJECTED-with-honor"
        out["verdict"] = {"status": status, "reason": reason}
        out["stats"]["paired_days"] = days

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    v = out["verdict"]
    print(f"verdict: {v['status']}")
    print(f"  {v.get('reason') or '; '.join(v['gates'])}")
    print(f"artifact: {args.out}")
    return out


def main():
    run()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The one stable state cell, tested on the FORWARD record instead of the window.

THE DECLARATION IS `docs/GOLD_PREREG_FORWARD_CELL_20260921.md` AND CAME FIRST. Four things in it
decide this file's shape, and each one is a refusal rather than a convenience:

* **The cell is a post-hoc STATE LABEL, not the arm's rule.** The deployed preset runs with
  `InpUseNewsFilter=false`, so the arm trades through news; the `news=out` axis is applied here to
  the finished ledger. The axis definitions are taken from `gold_persistence_state` — the module
  that FOUND the cell — rather than re-typed, so the forward label cannot drift from the
  selection's label.
* **The sample is declared, so a verdict is impossible below it.** `n_required` is computed from
  the declared MDE and dispersion; below the futility floor the only legal output is
  `NOT EVALUABLE`, with counts and projections. A short record is never "encouraging".
* **Two frames, and the conversion refuses rather than defaults.** Ledger epochs are broker SERVER
  time; the session axis is a UTC policy. A month whose DST step leaves no single offset is
  UNVERIFIABLE — excluded and counted, exactly as `midas_first_fills_audit` treats it.
* **Unlabellable rows are quarantined, not guessed.** A row beyond the data of record, or in an
  unresolvable month, cannot be asserted to be in the cell; if more than the declared 20% of
  otherwise-qualifying rows are unlabellable the harness FAILS LOUDLY, because a statistic on a
  quietly shrinking subset is the failure mode this whole apparatus exists to prevent.

Exit codes: 0 evaluated · 3 NOT EVALUABLE (below the futility floor) · 4 KILL (cell declared dead)
· 2 no ledger / unreadable · 1 unlabellable flood or unusable declaration inputs.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg  # noqa: E402
import gold_persistence_state as gps  # noqa: E402
import gold_walkforward as gw  # noqa: E402
import midas_first_fills_audit as ffa  # noqa: E402
import midas_sweep as S  # noqa: E402
from midas_prop.risk import news_calendar as nc  # noqa: E402

DECLARED_DOC = "docs/GOLD_PREREG_FORWARD_CELL_20260921.md"
#: This declaration's own moment. Rows entered before it cannot be counted, so the sample can
#: never be assembled retrospectively.
CUTOFF_EPOCH = 1790001518
#: Built from the SAME constants that produce the labels (`gps.cell_of` formats these strings),
#: so a re-binning of the selection's axes cannot leave this file testing a cell that the study
#: never measured.
_VOL_NORMAL = next(name for lo, hi, name in gps.VOL_BINS if name == "normal")
_SESS_0612 = next(name for lo, hi, name in gps.SESSIONS if name == "06-12")
CELL_PRIMARY = f"vol={_VOL_NORMAL}|sess={_SESS_0612}|news=out"
#: Secondary A drops the news axis (the wider cell), secondary B is the CONTRAST cell vs non-cell.
CELL_SECONDARY_A_PREFIX = f"vol={_VOL_NORMAL}|sess={_SESS_0612}"
#: Declared planning inputs — see the declaration §3. Changing either changes the sample the
#: document promises, which is why `tests/test_forward_cell_prereg.py` pins both.
MDE_R = 0.15
SD_PLAN = 1.10
Z_POWER = 0.8416          # one-sided 80% power
FUTILITY_N = 51           # declared look; spends NO efficacy alpha, so the final t stays at 1.96
UNLABELLABLE_MAX = 0.20   # declared: above this the harness fails rather than report a subset
ACCOUNT_SIZE = 25000.0    # the Upcomers U25 evaluation the arm is attached to
#: The fill lands one M15 bar after the signal bar closes, so the signal bar OPENED 1800s before
#: the ledger's OPEN stamp. This is the same two-step subtraction
#: `midas_first_fills_audit.audit_trade` performs (-900 for the signal bar's close, -900 again for
#: its open); the forward mask and the wire-contract audit must agree on which bar the signal is.
FILL_LAG = 1800
DAILY_WALL_PCT = 0.03
BEST_DAY_PCT = 0.20
#: Section 13's adjudication floor, quoted so the printed output and the declaration agree.
CERT_T = gw.selection_threshold(1)


def n_required(mde: float = MDE_R, sd: float = SD_PLAN, t: float = CERT_T) -> int:
    """Cell trades needed for t >= `t` at this effect size (the engine's own formula)."""
    n = gg.power_trades(mde, sd, t)
    if n is None:                                          # pragma: no cover - declared inputs
        raise SystemExit("declared MDE/sd are not a usable power input")
    return n


def n_power80(mde: float = MDE_R, sd: float = SD_PLAN, t: float = CERT_T) -> int:
    """The same sample with 80% power: (t + z_beta) instead of t."""
    return int(math.ceil(((t + Z_POWER) * sd / mde) ** 2))


def discover_ledger(tag: str) -> str | None:
    """The arm's own paper ledger, newest across terminal data folders.

    Deliberately keyed on the ARM TAG. `midas_first_fills_audit.discover_ledger()` globs
    `*_M1.csv`, which matches the retired micro-era books and not this arm's `..._U25.csv`; the
    tag is what says whose record this is.
    """
    root = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
    hits = [(os.path.getmtime(p), p) for p in
            glob.glob(os.path.join(root, "*", "MQL5", "Files",
                                   f"MIDASTOUCH_paper_*_{tag}.csv"))]
    return max(hits)[1] if hits else None


def utc_of_server(epoch: int) -> tuple[int | None, str]:
    """A broker-SERVER epoch as a UTC epoch through the pinned era table, or a refusal.

    `None` is not a default here: grading a server-clock hour against a UTC session rule without
    the conversion is off by the whole offset, and silently assuming one turns correct trades into
    apparent violations (and cell members into non-members).
    """
    month = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m")
    off = S.server_offset_for_month(month)
    if off is None:
        return None, (f"{month} contains a DST step, so the venue's offset is not a single "
                      f"number for it")
    return epoch - off * 60, ""


def build_axes(symbol: str, bars: int, *, as_of: int | None = None) -> dict:
    """The SELECTION's axes, built once from the venue's data of record.

    The per-bar M15 Wilder ATR(14), its causal trailing median, the UTC hour, the news mask — the
    exact inputs `gold_persistence_state.cell_of` consumed when the cell was found. Built through
    the same call (`gg.venue_data`) the selection study used, so the forward label and the
    selection's label are the same measurement rather than two implementations of one sentence.

    `as_of` passes through to `gps.news_axis`: the instant calendar freshness is judged at.
    `label_rows` leaves it at the default (corpus tail); a caller judging a declared window
    passes that window's end — see `news_axis` for why the default is not enough.
    """
    B, epoch, n, atr, hours, ok = gg.venue_data(symbol, bars)
    news_mask, news_note = gps.news_axis(epoch, n, as_of=as_of)
    return {"index": {int(e): i for i, e in enumerate(epoch)},
            "atr": atr, "atr_med": gw.trailing_percentile(atr, gw.ATR_LOOKBACK, 0.5),
            "hours": hours, "ok": ok, "news_mask": news_mask, "news_note": news_note,
            "last_epoch": int(epoch[n - 1]) if n else 0}


#: How many disagreements to print in full. The count is always recorded; the samples exist so a
#: reader can see WHICH kind of disagreement it is (an offset hour, or a row on a bin edge).
MAX_SAMPLES = 5


def recorded_axes(t: dict) -> tuple[dict | None, str]:
    """The axes the EA STAMPED into this row at fill time, or (None, why it cannot be asserted).

    This is the preferred source: the stamp is written by the engine that took the trade, from the
    bars and the calendar it was looking at, and it survives the data of record being refreshed,
    rotated away or absent altogether. It is not trusted blindly — `na` (no usable calendar) and the
    sentinels (`hour_utc=-1`, `vol_ratio=0.0`) are REFUSED here, because those rows cannot be placed
    in a cell and the declaration forbids guessing them into one.
    """
    state = t.get("state") or {}
    if not state:
        return None, ("no state stamp on the row (written before v1.19e, or a strategy-tester "
                      "row — the stamp is deliberately off there)")
    if state.get("malformed"):
        return None, f"malformed state stamp ({state['malformed']})"
    hour = int(state["hour_utc"])
    ratio = float(state["vol_ratio"])
    news = str(state["news"]).strip().lower()
    missing = []
    if not 0 <= hour <= 23:
        missing.append(f"hour_utc={hour} (no offset could be vouched for)")
    if ratio <= 0.0:
        missing.append(f"vol_ratio={ratio:.5f} (not computable in the terminal)")
    if news not in ("in", "out"):
        missing.append(f"news={news!r} (the calendar could not be asserted)")
    if missing:
        return None, "stamp cannot be read as a cell: " + "; ".join(missing)
    return {"ratio": ratio, "hour": hour, "news": news == "in",
            "sig_ct": int(state["sig_ct"]), "off_min": int(state["off_min"])}, ""


def rebuilt_axes(t: dict, axes: dict) -> tuple[dict | None, str]:
    """The axes the VENUE's data of record implies for this row, or (None, why it cannot).

    The control, not the source of record: it is how `tests/test_forward_cell_prereg.py` proved the
    forward mask reproduces the selection's own cell, and it is what reconciles the stamp. It needs
    three things the stamp does not: a resolvable month offset, a series that still reaches the
    row's signal bar, and a usable calendar.
    """
    sig_open_utc, why = utc_of_server(int(t["open_ct"]) - FILL_LAG)
    if sig_open_utc is None:
        return None, f"unresolvable server offset ({why})"
    i = axes["index"].get(int(sig_open_utc))
    if i is None:
        return None, ("signal bar beyond the data of record — refresh it "
                      "(scripts/midas_fetch_history.py --suffix _upcomers)")
    mask = axes["news_mask"]
    return {"ratio": (float(axes["atr"][i]) / float(axes["atr_med"][i])
                      if axes["atr_med"][i] else float("nan")),
            "hour": int(axes["hours"][i]),
            "news": (None if mask is None else bool(mask[i])),
            "sig_open_utc": int(sig_open_utc)}, ""


def cell_of_axes(a: dict, with_news: bool = True) -> str:
    """A label from one axis triple, through the study's own binning function."""
    return gps.label_of_values(a["ratio"], a["hour"], a["news"] if with_news else None)


def label_rows(trades: list[dict], axes: dict) -> tuple[list[dict], dict]:
    """Label every trade, preferring the EA's OWN stamp and reconciling it with the rebuild.

    Order of preference, and each choice is counted: RECORDED (the engine that took the trade wrote
    its state down), then REBUILT from the data of record, then EXCLUDED. Excluded is not the same
    as out-of-cell and the two are never merged: one is a gap, the other is evidence.

    Wherever BOTH exist they are reconciled on the axes both can assert, and a disagreement is
    reported with samples rather than absorbed, because two independent statements of the same three
    axes disagreeing is either an implementation drifting or a row sitting a hair off a bin edge —
    and both change which side of the cell a trade lands on.
    """
    labelled: list[dict] = []
    excluded: dict[str, int] = {}
    stamp_unusable: dict[str, int] = {}
    source_counts = {"recorded": 0, "rebuilt": 0}
    recon = {"agree": 0, "disagree": 0, "recorded_only": 0, "rebuilt_only": 0}
    samples: list[dict] = []
    for t in trades:
        rec, rec_why = recorded_axes(t)
        reb, reb_why = rebuilt_axes(t, axes)
        if rec is None and reb is None:
            key = f"unassertable — stamp: {rec_why}; rebuilt: {reb_why}"
            excluded[key] = excluded.get(key, 0) + 1
            continue
        if rec is not None:
            chosen, source, sig_open_utc = rec, "recorded", None
            sig_open_utc = int(rec["sig_ct"]) - int(rec["off_min"]) * 60
        else:
            chosen, source = reb, "rebuilt"
            sig_open_utc = int(reb["sig_open_utc"])
            stamp_unusable[rec_why] = stamp_unusable.get(rec_why, 0) + 1
        if rec is not None and reb is not None:
            both_news = reb["news"] is not None
            if cell_of_axes(rec, both_news) == cell_of_axes(reb, both_news):
                recon["agree"] += 1
            else:
                recon["disagree"] += 1
                if len(samples) < MAX_SAMPLES:
                    samples.append({
                        "sig_open_utc": int(sig_open_utc),
                        "recorded": cell_of_axes(rec, both_news),
                        "rebuilt": cell_of_axes(reb, both_news),
                        "ratio_recorded": round(float(rec["ratio"]), 6),
                        "ratio_rebuilt": round(float(reb["ratio"]), 6),
                        "hour_recorded": int(rec["hour"]), "hour_rebuilt": int(reb["hour"]),
                        "news_recorded": rec["news"], "news_rebuilt": reb["news"]})
        elif rec is not None:
            recon["recorded_only"] += 1
        else:
            recon["rebuilt_only"] += 1
        row = dict(t)
        row["sig_open_utc"] = int(sig_open_utc)
        row["label_source"] = source
        row["cell"] = gps.label_of_values(chosen["ratio"], chosen["hour"], chosen["news"])
        row["cell_2axis"] = gps.label_of_values(chosen["ratio"], chosen["hour"], None)
        labelled.append(row)
        source_counts[source] += 1
    return labelled, {"news_axis_note": axes["news_note"],
                      "news_axis_measurable": axes["news_mask"] is not None,
                      "excluded": excluded, "label_source": source_counts,
                      "stamp_unusable": stamp_unusable,
                      "reconciliation": recon, "reconciliation_samples": samples}


def net_r_of(t: dict) -> float:
    """The row's net R, whichever name its producer used.

    `midas_first_fills_audit.read_ledger` exposes it as `r` (the wire contract's own field name);
    the research engine's trade dicts call it `net_r`. Reading only one of the two crashed this
    harness on its first synthetic ledger row — a defect the arm's EMPTY forward record could not
    have shown, and the end-to-end tests in `tests/test_forward_cell_prereg.py` did.
    """
    return float(t["net_r"] if "net_r" in t else t["r"])


def unlabellable_flood(n_excluded: int, n_qualifying: int) -> tuple[bool, float]:
    """The declared 20% cap on rows whose cell membership cannot be asserted."""
    if n_qualifying <= 0:
        return False, 0.0
    share = n_excluded / n_qualifying
    return share > UNLABELLABLE_MAX, share


def count_live_rows(path: str) -> int:
    """How many LIVE-layer rows sit in the paper ledger (excluded from the statistic).

    The deployed preset runs `InpLiveExecution=true`, so a live fill writes `LOPEN`/`LCLOSE` into
    the same file. They are a different instrument with different fills; mixing them into the
    paper statistic would double-count one signal with two execution models.
    """
    n = 0
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            if line.startswith(("LOPEN", "LCLOSE")):
                n += 1
    return n


def decide(n_cell: int, st: dict, props: dict, n_req: int) -> tuple[str, str]:
    """The declared decision, in the declared order (declaration §4, fixed before any data).

    Order matters and is not cosmetic: KILL outranks FAIL, so a record whose mean has gone negative
    can never be reported as a merely-decidability-pending result, and the sample floor outranks
    everything, so a short record can never be reported as promising.
    """
    if n_cell >= FUTILITY_N and st["mean_r"] is not None and st["mean_r"] <= 0:
        return "KILL", (f"at n={n_cell} >= {FUTILITY_N} the cell's mean is "
                         f"{st['mean_r']:+.4f}R <= 0: the cell is declared dead and is not to be "
                         f"re-cut")
    if n_cell < FUTILITY_N:
        return "NOT EVALUABLE", (f"n={n_cell} < {FUTILITY_N}: the futility look cannot fire and "
                                  f"no efficacy look exists below {n_req}")
    if n_cell < n_req:
        note = (f"n={n_cell} < n_required {n_req}: t={st['t']:+.2f} is not yet decidable at the "
                f"declared MDE")
        if st["sd"] and abs(st["sd"] - SD_PLAN) > 0.001:
            note += (f" | variance-only revision: realized sd {st['sd']:.4f} moves n_required to "
                     f"{n_required(sd=st['sd'])}")
        return "NOT EVALUABLE", note
    if st["t"] < CERT_T:
        return "FAIL", (f"n={n_cell} >= {n_req} and t={st['t']:+.2f} < {CERT_T:.4f}: the cell "
                         f"does not carry forward")
    if not (props["daily_ok"] and props["best_day_ok"]):
        return "FAIL", ("the cell's own record breaches a venue rule: the statistic cannot pass "
                         "while the account's rules did not hold")
    return "PASS", (f"n={n_cell}, mean {st['mean_r']:+.4f}R, t={st['t']:+.2f} >= {CERT_T:.4f}, "
                     f"venue rules held — a CANDIDATE, not a validation")


def prop_checks(rows: list[dict], account_size: float) -> dict:
    """The venue's own rules, re-derived from the ledger's closed rows.

    The governor already gates entries; this is the independent read, and it is deliberately
    reported as UNVERIFIABLE for any row whose month has no single offset rather than anchored
    to a guessed UTC day.
    """
    by_day: dict[str, float] = {}
    unverifiable = 0
    for t in rows:
        day_utc, why = utc_of_server(int(t["close_ct"]))
        if day_utc is None:
            unverifiable += 1
            continue
        key = datetime.fromtimestamp(day_utc, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[key] = by_day.get(key, 0.0) + float(t["pnl"])
    worst = min(by_day.values()) if by_day else None
    best = max(by_day.values()) if by_day else None
    total = sum(by_day.values())
    return {
        "days": len(by_day),
        "worst_day_usd": round(worst, 2) if worst is not None else None,
        "best_day_usd": round(best, 2) if best is not None else None,
        "daily_wall_usd": round(account_size * DAILY_WALL_PCT, 2),
        "daily_ok": (worst is None) or (worst >= -account_size * DAILY_WALL_PCT),
        "best_day_share": (round(best / total, 4) if (best is not None and total > 0) else None),
        "best_day_ok": (best is None) or (total <= 0) or (best <= total * BEST_DAY_PCT),
        "rows_unverifiable_frame": unverifiable,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=None, help="ledger path (default: newest for the arm tag)")
    ap.add_argument("--arm-tag", default="U25")
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--account-size", type=float, default=ACCOUNT_SIZE)
    ap.add_argument("--out", default="artifacts/gold_forward_cell_prereg.json")
    a = ap.parse_args(argv)

    n_req, n_pow = n_required(), n_power80()
    print(f"declaration: {DECLARED_DOC}")
    print(f"cell (primary): {CELL_PRIMARY}")
    print(f"declared inputs: MDE {MDE_R:+.2f}R  sd {SD_PLAN:.2f}R  t_required {CERT_T:.4f}")
    print(f"declared sample: n_required {n_req} cell trades   |   80% power {n_pow}   |   "
          f"futility look at n={FUTILITY_N} (mean <= 0 kills)")

    ledger = a.ledger or discover_ledger(a.arm_tag)
    if not ledger or not os.path.exists(ledger):
        print(f"no ledger for tag {a.arm_tag} — the arm has not written one yet "
              f"(nothing to evaluate)")
        return 2
    print(f"ledger: {ledger}")
    led = ffa.read_ledger(ledger)
    raw_live = count_live_rows(ledger)
    if led["eras"]:
        print(f"era: {led['eras'][-1]}")
    for p in led["problems"]:
        print(f"  ledger note: {p}")

    qualifying = [t for t in led["trades"] if int(t["open_ct"]) >= CUTOFF_EPOCH]
    print(f"\nclosed paper trades on file: {len(led['trades'])}   "
          f"at/after the declaration cutoff: {len(qualifying)}")
    print(f"live-layer rows (LOPEN/LCLOSE), EXCLUDED from the statistic by declaration: "
          f"{raw_live}")

    axes = build_axes(a.symbol, a.bars)
    labelled, meta = label_rows(qualifying, axes)
    print(f"news axis: {'MEASURED' if meta['news_axis_measurable'] else 'NOT MEASURABLE'} — "
          f"{meta['news_axis_note']}")
    for reason, count in sorted(meta["excluded"].items()):
        print(f"  excluded {count:>4}  {reason}")
    src = meta["label_source"]
    print(f"label source: RECORDED (the EA's stamp at fill time) {src['recorded']}  |  "
          f"rebuilt from the data of record {src['rebuilt']}  |  "
          f"unassertable {sum(meta['excluded'].values())}")
    for reason, count in sorted(meta["stamp_unusable"].items()):
        print(f"  stamp unusable on {count:>4}  {reason}")
    rc = meta["reconciliation"]
    print(f"stamp vs rebuild, where both exist: agree {rc['agree']}, disagree {rc['disagree']} "
          f"| recorded only {rc['recorded_only']}, rebuilt only {rc['rebuilt_only']}")
    for s in meta["reconciliation_samples"]:
        when = datetime.fromtimestamp(s["sig_open_utc"], tz=timezone.utc)
        print(f"  DISAGREE {when:%Y-%m-%d %H:%M}Z  recorded {s['recorded']} vs rebuilt "
              f"{s['rebuilt']}  (ratio {s['ratio_recorded']:.5f}/{s['ratio_rebuilt']:.5f}, "
              f"hour {s['hour_recorded']}/{s['hour_rebuilt']}, "
              f"news {s['news_recorded']}/{s['news_rebuilt']})")
    if rc["disagree"]:
        print(f"  -> the statistic uses the RECORDED label; {rc['disagree']} row(s) disagree "
              f"with the rebuild, and every one of them could move a trade across the cell edge.")
    flood, share = unlabellable_flood(sum(meta["excluded"].values()), len(qualifying))
    if flood:
        print(f"\nFAIL-LOUD: {share:.1%} of qualifying rows are unlabellable "
              f"(declared maximum {UNLABELLABLE_MAX:.0%}). No statistic is reported on a "
              f"shrinking subset — refresh the data of record and re-run.")
        return 1

    primary = [t for t in labelled if t["cell"] == CELL_PRIMARY]
    by_src: dict[str, int] = {}
    for t in primary:
        by_src[t["label_source"]] = by_src.get(t["label_source"], 0) + 1
    sec_a = [t for t in labelled if t["cell_2axis"].startswith(CELL_SECONDARY_A_PREFIX)]
    stats_cell = gps.stats([net_r_of(t) for t in primary])
    stats_a = gps.stats([net_r_of(t) for t in sec_a])
    stats_all = gps.stats([net_r_of(t) for t in labelled])

    print(f"\n== primary cell {CELL_PRIMARY}")
    print(f"   label sources in this cell: "
          + (", ".join(f"{k} {v}" for k, v in sorted(by_src.items())) or "none yet"))
    print(f"   n={stats_cell['n']} of {n_req} required"
          + (f"   mean={stats_cell['mean_r']:+.4f}R  sd={stats_cell['sd']:.4f}  "
             f"t={stats_cell['t']:+.2f}" if stats_cell["n"] else ""))
    print(f"== secondary A {CELL_SECONDARY_A_PREFIX} (family of 2, t>={gw.selection_threshold(2):.4f})")
    print(f"   n={stats_a['n']}"
          + (f"   mean={stats_a['mean_r']:+.4f}R  t={stats_a['t']:+.2f}" if stats_a["n"] else ""))
    print(f"== all labelled rows (the arm as deployed)")
    print(f"   n={stats_all['n']}"
          + (f"   mean={stats_all['mean_r']:+.4f}R  t={stats_all['t']:+.2f}"
             if stats_all["n"] else ""))

    props = prop_checks(labelled, a.account_size)
    if props["days"]:
        print(f"\nvenue rules from the ledger: {props['days']} UTC days, worst "
              f"{props['worst_day_usd']:+.2f} vs wall -{props['daily_wall_usd']:.2f} "
              f"({'OK' if props['daily_ok'] else 'BREACH'}), best-day share "
              + (f"{props['best_day_share']:.1%}" if props["best_day_share"] is not None
                 else "n/a (no profit)")
              + f" ({'OK' if props['best_day_ok'] else 'BREACH'})")

    # ---- the declared decision, in the declared order --------------------- #
    n_cell = stats_cell["n"]
    verdict, reason = decide(n_cell, stats_cell, props, n_req)

    print(f"\nverdict: {verdict}")
    print(f"  {reason}")
    if verdict == "NOT EVALUABLE" and n_cell:
        first = min(t["sig_open_utc"] for t in primary)
        last = max(t["sig_open_utc"] for t in primary)
        span_d = max((last - first) / 86400.0, 1e-9)
        rate = n_cell / span_d
        print(f"  observed cell flow: {n_cell} trades over {span_d:.2f} days = "
              f"{rate:.4f}/day -> {n_req} needs {n_req / rate:.0f} more days")
    print("\nNothing here is a validation: the forward record is the instrument, and a PASS is "
          "a candidate that a further record must confirm.")

    out = {
        "declared": {"document": DECLARED_DOC, "declared_epoch": CUTOFF_EPOCH,
                     "cell_primary": CELL_PRIMARY,
                     "cell_secondary_a_prefix": CELL_SECONDARY_A_PREFIX,
                     "mde_r": MDE_R, "sd_plan_r": SD_PLAN,
                     "t_required": round(CERT_T, 4),
                     "t_secondary_a": round(gw.selection_threshold(2), 4),
                     "t_secondary_b": round(gw.selection_threshold(3), 4),
                     "n_required": n_req, "n_power80": n_pow,
                     "futility_n": FUTILITY_N,
                     "unlabellable_max": UNLABELLABLE_MAX,
                     "geometry": "the arm as deployed: stop 2.0xATR(H1,14), target +2.0R, "
                                 "720-min timeout, session 06-20 UTC, news gate OFF"},
        "ledger": ledger,
        "eras": led["eras"],
        "counts": {"closed_paper": len(led["trades"]), "qualifying": len(qualifying),
                   "labelled": len(labelled), "cell_primary": n_cell,
                   "cell_secondary_a": stats_a["n"], "live_rows_excluded": raw_live},
        "excluded": meta["excluded"],
        "labels": {"source": src, "primary_cell_by_source": by_src,
                   "stamp_unusable": meta["stamp_unusable"],
                   "reconciliation": rc,
                   "reconciliation_samples": meta["reconciliation_samples"],
                   "preference": "the EA's own stamp at fill time, rebuilt label as the control"},
        "news_axis": {"measurable": meta["news_axis_measurable"], "note": meta["news_axis_note"]},
        "stats": {"cell_primary": stats_cell, "cell_secondary_a": stats_a, "all_labelled": stats_all},
        "prop_checks": props,
        "verdict": verdict, "reason": reason,
    }
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {dest}")
    return {"PASS": 0, "FAIL": 0, "KILL": 4, "NOT EVALUABLE": 3}[verdict]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""One parser for the armed arm's own record rows — and one place that refuses.

WHAT THIS IS
  The armed EA writes one append-only ledger (`MIDASTOUCH_paper_XAUUSD_<tag>.csv`)
  whose rows are the program's evidence stream. Several tools now need to read
  different row types of THAT one file. Each keeping a private grammar is how a
  reader/writer order disagreement (the 2026-09-21 NOFILL mislabel) happens twice,
  so the grammars live here — keyed and positional exactly as the EA's writers
  emit them — and every caller gets the same rows.

  Every function here is read-only: this module opens ledgers and presets, and it
  can never write, rename or delete anything. It imports no order path and no
  terminal-writing helper; the guard test (`tests/test_midas_arm_record.py`)
  pins the source for order-sending calls, file removal, unlinking and tree
  deletion.

THE CLOCK FRAMES, WHICH ARE NOT THE SAME AND MUST NOT BE MERGED
  A STATE row's field [1] is `TimeUTCNow()` — the writer's wall clock, true UTC.
  Its field [2] is `g_hud_sig_ct` — the SIGNAL BAR's open, stamped like every bar
  epoch in this program in the VENUE'S SERVER frame. The two are different frames
  and both are needed: [1] answers "when was this measured", [2] answers "which
  bar was evaluated", and converting one into the other silently is the
  whole-offset error class this repo has paid for twice (the +120-minute clock
  fault of 2026-09-20, the unmatched sweep rows of 2026-09-23).

  Where a caller needs bar hours, the row itself carries the conversion: the
  state stamp's last field (`off_min`) is the venue's server−UTC offset, so
  `bar_open_utc = server_open − off_min*60`. This module hands callers BOTH
  stamps untouched, plus a conversion helper that takes the offset from the row
  it converts — never a module global.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

#: `STATE,<write_utc>,<sig_open_srv>,<mac>,<h4>,<h1>,<trig>,<rsi_x100>,<sess>,`
#: `<lots_x100>,<risk_x100>,<daypnl>,<cap>,<floor>` + state stamp tail
#: `<sig_ct>,<hour_utc>,<vol_ratio_x10000>,<news>,<off_min>` + `cfg=<usd>@<pct>`.
STATE_HEAD = 14          # fields [0..13]: through `floor`
STATE_STAMP = 5          # the v1.19e stamp: sig_ct, hour_utc, vol_x10000, news, off_min
STATE_MIN = STATE_HEAD + STATE_STAMP   # 19 — below this the row is unreadable
#: `NOFILLSUM,<write>,<utc_day>,` + the ten counters IN THE EA'S WRITER ORDER
#: (`DiagCounters`, MidastouchAI.mq5 v1.27): signal, mismatch, session, friday,
#: spread, riskcap, breaker, notr (the journal's "no-trigger"), news, nodata.
#: `notr` sits between breaker and news in the ROW while morning_status prints it
#: third from the end — the writer's order is the contract, so a reader cannot
#: re-derive it from the labels and silently transpose two refusals.
NOFILL_FIELDS = ("signal", "mismatch", "session", "friday", "spread",
                 "riskcap", "breaker", "notr", "news", "nodata")
NOFILL_MIN = 13          # writer + head = 13 fields; v1.27's own floor

#: `LCLOSE,<write>,<posid>,<reason>,<exit>,<r>` — 6 fields, v1.29 vocabulary.
LCLOSE_MIN = 6

#: `LOPEN,<write>,<posid>,<order>,<deal>,<dir>,<entry>,<sl>,<tp>,<lots>,<risk>,`
#: `<stop_d>,<timeout>,<tag>` + optional `_FLOORED` + state stamp + `cfg=` token
#: — so `dir` sits at [5] (after DEAL at [4]), `lots` at [9], risk at [10], stop
#: at [11]. MEASURED 2026-09-23: reading `dir` at [4] read the DEAL field and
#: every later field shifted one left, which failed the whole row on a decimal
#: timeout. The `cfg=` token is keyed off the END.
LOPEN_MIN = 13
LOPEN_DIR = 5
LOPEN_LOTS = 9
LOPEN_RISK = 10

#: `SPREADHOUR,<write>,<day>` + 24 × `<hour>,<n>,<mean>,<max_x100>` — 98 fields.
SPREADHOUR_MIN = 98


def parse_state(parts: list[str], ln: int = 0) -> dict | None:
    """One `STATE` row -> a dict, or None when the row is too short to be honest.

    THREE SHAPES ON ONE RECORD (measured 2026-09-23 on the armed arm's own
    ledger, 217 STATE rows): 20 fields (v1.27+, head 14 + stamp 5 [+ cfg]), 15
    (v1.22-26, head + cfg), 14 (v1.21, head only). All three carry the head the
    classification needs (trig/mac/sess/lots/risk), so a legacy row is parsed as
    a HEAD-ONLY row — `stamp=False`, `off_min=None` — rather than dropped:
    dropping the v1.21-26 bars would delete the arming day's own refusals from
    the record and make the census-vs-rows reconciliation falsely conflict.

    Field [5] `trig` and [6] `rsi_x100` are the trigger reading the EA took on the
    bar; [7] `sess_ok` is the SESSION gate's answer for that bar's open hour in the
    EA's own frame (server hours against the declared window — the 04-18 UTC
    reality the arming record documents, not the 06-20 the labels claim).
    """
    if len(parts) < STATE_HEAD:
        return None
    try:
        row: dict = {
            "ln": ln, "write_utc": int(parts[1]), "sig_open_srv": int(parts[2]),
            "mac": int(parts[3]), "h4": int(parts[4]), "h1": int(parts[5]),
            "trig": int(parts[6]), "rsi": int(parts[7]) / 100.0,
            "sess_ok": parts[8] == "1", "lots": int(parts[9]) / 100.0,
            "risk_usd": int(parts[10]) / 100.0,
            "daypnl": float(parts[11]), "cap": float(parts[12]),
            "floor": float(parts[13]),
            "stamp": False, "sig_ct_srv": None, "hour_utc": None,
            "vol_ratio": None, "news": None, "off_min": None,
        }
        if len(parts) >= STATE_MIN:
            row.update({
                "stamp": True,
                "sig_ct_srv": int(parts[14]),
                "hour_utc": int(parts[15]),
                # MEASURED on this ledger (2026-09-23): the stamp's third field is a
                # `%.5f` float ("0.71068"), the vol ratio itself — reading it as an
                # int x10000 dropped every STATE row on the real file.
                "vol_ratio": float(parts[16]),
                "news": parts[17],
                "off_min": int(parts[18]),
            })
        return row
    except (ValueError, IndexError):
        return None


def parse_nofill(parts: list[str], kind: str = "nofillsum") -> dict | None:
    """One census row -> the ten counters, keyed by the writer's order.

    Two shapes, and the day field is the difference: `NOFILLSUM` carries its own
    utc day (13 fields, counters at [3..12]); the daily-roll `NOFILL` does not —
    it carries the FINAL counters of the day that ended (12 fields, counters at
    [2..11]), so its day is the write's UTC day minus one. A reader that keyed
    the roll row on its write time would count the ended day's refusals onto the
    new day and the two sources would disagree by a day.
    """
    if kind == "nofillsum":
        if len(parts) < NOFILL_MIN:
            return None
        day_i, body = 2, 3
    else:
        if len(parts) < NOFILL_MIN - 1:
            return None
        day_i, body = None, 2
    try:
        counters = {k: int(v) for k, v in zip(NOFILL_FIELDS, parts[body:body + 10])}
        write = int(parts[1])
        if day_i is not None:
            day = int(parts[day_i])
        else:
            day = write // 86400 - 1          # the day that ended, not the writer's day
        return {"write": write, "day": day, "kind": kind, **counters}
    except (ValueError, IndexError):
        return None


def parse_lclose(parts: list[str]) -> dict | None:
    """One `LCLOSE` row — the arm's realized record, who-closed and R."""
    if len(parts) < LCLOSE_MIN:
        return None
    try:
        return {"write": int(parts[1]), "posid": parts[2], "reason": parts[3],
                "exit": float(parts[4]), "r": float(parts[5])}
    except (ValueError, IndexError):
        return None


def parse_lopen(parts: list[str]) -> dict | None:
    """One `LOPEN` row — a live fill. `risk_usd` is positional [9]."""
    if len(parts) < LOPEN_MIN:
        return None
    try:
        return {"write": int(parts[1]), "posid": parts[2], "order": parts[3],
                "deal": parts[4], "dir": int(parts[LOPEN_DIR]),
                "entry": float(parts[6]), "sl": float(parts[7]),
                "tp": float(parts[8]), "lots": float(parts[LOPEN_LOTS]),
                "risk_usd": float(parts[LOPEN_RISK]),
                "stop_d": float(parts[11]), "timeout": int(parts[12])}
    except (ValueError, IndexError):
        return None


def parse_spreadhour(parts: list[str]) -> dict | None:
    """One `SPREADHOUR` row -> {utc_hour: (n, mean$, max$)} for the day it rolls."""
    if len(parts) < SPREADHOUR_MIN:
        return None
    try:
        body = parts[3:]
        out: dict[int, tuple[int, float, float]] = {}
        for i in range(24):
            h, n, mean, mx = body[i * 4:(i + 1) * 4]
            out[int(h)] = (int(n), float(mean), int(mx) / 100.0)
        return {"write": int(parts[1]), "day": int(parts[2]), "hours": out}
    except (ValueError, IndexError):
        return None


def mode_timeline(rec: dict, preset_mode: int) -> list[tuple[int, int]]:
    """[(from_utc, mode)] — the configuration timeline the ARMING RECORD itself
    documents, from its own amendments.

    MEASURED 2026-09-23: the arm ran InpMode=0 from arming until the 2026-09-22
    12:28:47Z amendment, then 1. Classifying the earlier bars under the preset's
    mode would call every mode-0 refusal a mode-1 refusal and make the census
    (which counted the bars under the mode that was RUNNING) disagree with the
    STATE rows for reasons that are history, not grammar. The record is the
    authority for the timeline; a record with no InpMode amendment gets the
    preset mode for everything, which is the truth it can support.
    """
    import re
    changes: list[tuple[int, int, int]] = []
    for a in rec.get("amendments") or []:
        what = str(a.get("what", ""))
        if "InpMode" not in what:
            continue
        ts = iso_utc(a.get("utc"))
        m = re.search(r"InpMode\s+(\d+)\s*(?:->|→)\s*(\d+)", what)
        if ts is not None and m:
            changes.append((ts, int(m.group(1)), int(m.group(2))))
    if not changes:
        return [(0, preset_mode)]
    changes.sort()
    tl = [(0, changes[0][1])]                 # the mode the arm started on
    for ts, _frm, to in changes:
        tl.append((ts, to))
    return tl


def mode_at(timeline: list[tuple[int, int]], ts: int) -> int:
    """The mode in force at `ts` under a `mode_timeline` ordering."""
    mode = timeline[0][1]
    for t0, m in timeline:
        if ts >= t0:
            mode = m
        else:
            break
    return mode


def iso_utc(s) -> int | None:
    """An ISO/Z stamp -> epoch seconds, or None — never 0 on a bad stamp."""
    from datetime import datetime, timezone
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def read_rows(ledger: Path) -> dict:
    """The whole ledger, once, into typed rows — the one file pass every caller shares.

    Short rows are DROPPED, never read generously: a truncated tail (a writer killed
    mid-append) would otherwise put a confident zero or a stale value into a census.
    The count of what was dropped is reported next to what was kept, so "the arm's
    account of itself was unreadable" can never dress as "the arm was idle".
    """
    rows: dict[str, list] = {"state": [], "nofill": [], "lclose": [],
                             "lopen": [], "spreadhour": [], "era": []}
    broken: list[str] = []
    try:
        text = Path(ledger).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SystemExit(f"cannot read the arm's ledger at {ledger}: {exc}")
    for ln, line in enumerate(text.splitlines(), 1):
        parts = line.strip().split(",")
        tag = parts[0] if parts else ""
        row = None
        if tag == "STATE":
            row = parse_state(parts, ln)
            if row is not None:
                rows["state"].append(row)
        elif tag in ("NOFILLSUM", "NOFILL"):
            row = parse_nofill(parts, tag.lower())
            if row is not None:
                rows["nofill"].append(row)
        elif tag == "LCLOSE":
            row = parse_lclose(parts)
            if row is not None:
                rows["lclose"].append(row)
        elif tag == "LOPEN":
            row = parse_lopen(parts)
            if row is not None:
                rows["lopen"].append(row)
        elif tag == "SPREADHOUR":
            row = parse_spreadhour(parts)
            if row is not None:
                rows["spreadhour"].append(row)
        elif tag == "ERA":
            rows["era"].append({"ln": ln, "version": parts[1] if len(parts) > 1 else "",
                                "stamp_srv": parts[2] if len(parts) > 2 else ""})
            continue
        if tag in ("STATE", "NOFILLSUM", "NOFILL", "LCLOSE", "LOPEN", "SPREADHOUR") and row is None:
            broken.append(f"line {ln}: short/malformed {tag} ({len(parts)} fields)")
    return {"rows": rows, "broken": broken}


def bar_open_utc(state_row: dict) -> int | None:
    """The evaluated bar's open in true UTC, converted by the ROW's own offset.

    Returns None when the offset is unknown — never 0, because a `0` in an epoch
    column is read as an epoch by every downstream reader, and a bar misplaced by
    a whole offset is exactly the failure `midas_sweep_shadow` measured on its
    first live rows (2026-09-23).
    """
    off = state_row.get("off_min")
    if off is None:
        return None
    return state_row["sig_open_srv"] - off * 60


def dedupe_bars(states: list[dict]) -> list[dict]:
    """One row per evaluated bar: distinct `sig_open_srv`, latest write wins.

    MEASURED 2026-09-23: the heartbeat re-writes the current bar's STATE row
    every 15 minutes, so the raw stream holds the per-bar evaluation plus up to
    ~14 repeats. The census counts bars once; every per-bar count (accepted
    signals, triggers, vetoes) must count them once too, or one accepted signal
    that survived three heartbeats reads as three.
    """
    by_bar: dict[int, dict] = {}
    for r in states:
        cur = by_bar.get(r["sig_open_srv"])
        if cur is None or r["write_utc"] >= cur["write_utc"]:
            by_bar[r["sig_open_srv"]] = r
    return sorted(by_bar.values(), key=lambda r: r["sig_open_srv"])


def read_preset_inputs(path: Path) -> dict[str, str]:
    """A `.set` file as a plain dict — the grammar `attach_chart_ea.read_preset`
    uses, kept here so a second copy does not drift from the first."""
    vals: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith(";") or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        vals[k.strip()] = v.strip()
    return vals


def resolve_arm_preset(record: Path, preset_dir: Path) -> tuple[Path | None, str]:
    """The preset the arming record names — the same authority `verify_sizing_live`
    resolves through, without importing its terminal stack."""
    try:
        rec = json_load(record)
    except (OSError, ValueError) as exc:
        return None, f"arming record {record} is unreadable ({exc})"
    name = rec.get("preset")
    if not name:
        return None, f"arming record names no preset"
    p = Path(preset_dir) / name
    if not p.is_file():
        return None, f"arming record names {name}, which is not in {preset_dir}"
    return p, "named by the arming record"


def json_load(path: Path) -> dict:
    """A tiny indirection so callers do not each import json for one read."""
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))

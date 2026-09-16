#!/usr/bin/env python3
"""Era classification for the arm paper ledgers.

Why this exists: v26.38 (deployed 2026-09-15, banners 19:52:35 / 19:58:03
UTC+1 on 71BF/FB9A) changed HOW the paper book fills hard SL/TP — frombar-open evaluation to per-tick fills at the resting level, mirroring the
broker-side resting orders the live book trades with. The fill-cost stress
protocol priced that difference at −8.3R/window on the certified corpus:
trades from the two regimes are drawn from different distributions, and one
expectancy statistic must never mix them (docs/OPERATING_SUMMARY.md,
"2026-09-15, ERA BOUNDARY" amendment, append-only).

Three layers, one rule:

1. **Data-native (writer, v26.39+):** each engine stamps an era tag row into
   its own ledger at init, right after its header rows:
       ERA,<version>,<boundary_epoch>,<era_name>
   A repeated stamp on every restart is idempotent — readers keep the first
   one (rows are append-only, so the first stamp is the oldest claim).

2. **Fallback (readers, pre-registered):** ledgers written by older builds
   carry no ERA row. For them, classification falls back to the frozen
   boundary epoch ERA_EPOCH keyed by engine family:
   - MitemshubAI-ledger trades with close epoch <  ERA_EPOCH → baropen-fills
   - MitemshubAI-ledger trades with close epoch >= ERA_EPOCH → pertick-fills
     (26.38+ runs per-tick; 26.39+ proves it with its own row anyway)
   - V75MacroEngine trades are ALWAYS pertick-fills (it filled exits per
     tick from day one; its M30 gate never covered management).
   The boundary sits inside the verified no-EA window between the last
   pre-deploy ledger activity (17:50:48 UTC) and the first v26.38 init
   (17:52:35 UTC), so no real trade can straddle it by construction.

3. **Consumers:** every statistics consumer filters trades through
   `era_filter(...)` before computing anything. The DEFAULT filter is
   ERA_POSTFILL — pre-registered continuation, not a new decision: the gate
   clock restarted at the v26.38 deploy boundary, so "the statistic" means
   post-fill trades unless a caller explicitly asks for the full history
   (display) or a specific era (audit).
"""
from __future__ import annotations

import calendar

ERA_PRE = "baropen-fills"    # v26.37-and-earlier MitemshubAI paper book
ERA_POST = "pertick-fills"   # v26.38+ MitemshubAI / all V75MacroEngine paper
ERA_UNKNOWN = "unknown-era"  # unparseable ledger: consumers must not invent eras

# Frozen boundary: 2026-09-15 17:51:40 UTC — the midpoint of the verified
# EA-silence window (last pre-deploy arm-A/B ledger activity 17:50:48 UTC,
# terminals stopped 17:52:18, first v26.38 init 17:52:35 UTC). Both engines
# were DOWN for the whole window, so no trade can straddle the boundary by
# construction: every pre-deploy close sits before it, every post-deploy
# close after it.
ERA_EPOCH = 1789494700

# Engine keys are the `engine` strings the unified parsers already use.
# MitemshubAI family (any file matching these prefixes) changed fill cadence
# at the boundary; V75MacroEngine never did.
_ENGINE_RULES = {
    "mitemshubai": ("boundary", ERA_PRE, ERA_POST),
    "v75macroengine": ("always", None, ERA_POST),
}


def _rule(engine: str) -> tuple[str, str, str]:
    return _ENGINE_RULES.get((engine or "").strip().lower(), ("unknown", None, None))


def parse_era_rows(path: str) -> list[dict]:
    """All ERA rows in a ledger (usually 0 or 1; idempotent restamps tolerated).

    ERA,<version>,<boundary_epoch>,<era_name> — malformed rows are returned
    as-is with ok=False rather than raising; callers decide how loud to be.
    """
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for ln, line in enumerate(f, 1):
                parts = line.strip().split(",")
                if not parts or parts[0] != "ERA":
                    continue
                ok = len(parts) >= 4
                boundary = int(parts[2]) if ok and parts[2].lstrip("-").isdigit() else None
                row = {
                    "line": ln,
                    "version": parts[1] if len(parts) > 1 else "",
                    "boundary": boundary,
                    "era": parts[3] if len(parts) > 3 else "",
                    "ok": ok,
                }
                if ok and (boundary is None or boundary != ERA_EPOCH):
                    # A stamp we cannot fully trust (unparseable boundary, or
                    # the writer disagrees with the frozen one) is marked not
                    # ok: consumers fall back to the epoch rule instead of
                    # honoring a provenance claim that fails inspection.
                    row["ok"] = False
                rows.append(row)
    except FileNotFoundError:
        return []
    return rows


def era_for_engine(engine: str, epoch: int) -> str:
    """Fallback classification of one close epoch for an engine family."""
    mode, pre, post = _rule(engine)
    if mode == "always":
        return post
    if mode == "boundary":
        return pre if epoch < ERA_EPOCH else post
    return ERA_UNKNOWN


def era_of_trade(engine: str, trade: dict, era_rows: list[dict] | None = None) -> str:
    """Era of one closed trade.

    Positional stamp rule (append-only ledgers): the writer appends its ERA
    row at the file's CURRENT end, so rows ABOVE the first stamp line predate
    the stamp and are classified by the frozen boundary epoch; rows BELOW it
    carry the stamp's era. The stamp therefore divides the file exactly where
    the regime changed, and a re-stamp on every restart is harmless. When the
    trade has no line position (or the stamp is malformed/boundary-mismatched),
    fall back to the per-engine epoch rule — for the MitemshubAI family that
    rule alone is already correct, because the fill regime switched exactly at
    ERA_EPOCH."""
    mode, pre, post = _rule(engine)
    if mode == "always":
        return post
    if mode == "boundary":
        if era_rows:
            first = era_rows[0]
            if (first.get("ok") and first.get("era") in (ERA_PRE, ERA_POST)
                    and trade.get("line") is not None and trade["line"] > first["line"]):
                return first["era"]
        return pre if trade.get("epoch", 0) < ERA_EPOCH else post
    return ERA_UNKNOWN


def era_filter(trades: list[dict], engine: str, era: str = ERA_POST,
               era_rows: list[dict] | None = None) -> list[dict]:
    """Trades from exactly one era. Default ERA_POST = the pre-registered
    gate statistic. Use ERA_PRE for the historical sim audit, ERA_UNKNOWN
    never matches anything (an unclassifiable trade is a loud zero, not a
    silent inclusion)."""
    return [t for t in trades if era_of_trade(engine, t, era_rows) == era]


def era_split(trades: list[dict], engine: str, era_rows: list[dict] | None = None) -> dict:
    """Counts per era — the morning-status / display view of the ledger."""
    out = {ERA_PRE: 0, ERA_POST: 0, ERA_UNKNOWN: 0}
    for t in trades:
        out[era_of_trade(engine, t, era_rows)] += 1
    return out

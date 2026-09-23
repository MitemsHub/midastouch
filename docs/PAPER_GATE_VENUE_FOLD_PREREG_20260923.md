# Pre-registration — the paper gate's 30-trade tally folds venue-attributed closes

**Written 2026-09-23 ~22:30Z, before the wiring exists.** The measure that makes this
legitimate is already on the arming record (amendment 12): the EA's ledger undercounts
its own closes — all four LOPEN rows but one LCLOSE row, because a re-entry moved the
EA's position tracker before its exit scan adopted the operator's manual close — while
the account's deal history holds all three closes. This document fixes, in advance,
how the gate's counter may be corrected by the venue's record. Nothing here widens the
gate: the bar stays ≥30 closed trades with positive expectancy. What changes is *which
record counts the trades*, and it changes in one direction only — toward the venue,
which is the same source the $-realized figures already come from.

## The defect being corrected, measured

On 2026-09-23 the corrected ingest (`scripts/midas_vps_ingest.py`, pinned by
`tests/test_midas_vps_ingest.py`) showed, for the one position both records hold
(pos 18874164), **exact parity**: the EA's own LCLOSE row says R 0.104, the venue-paired
R is 0.1046. The ledger is not wrong about what it records; it is *incomplete* —
its LCLOSE writer depends on an in-process position tracker that a manual close plus
re-entry defeats. Two closed wins (+0.1934, +0.1883) existed only in the venue's
history. A gate that counted the ledger alone would count a world smaller than the
one that happened.

## The rule, fixed here

For the U25 arm's paper gate counter ONLY (`MIN_TRADES = 30`, the `[3b]` closed-line
and the `[3]` MIDAS inventory row):

1. **The count is `LCLOSE rows ∪ venue-attributed closes`, by position id.**
   The venue side is `ingest()`'s positions with `close_in_local_ledger == false`,
   attributed by `mt5_ops.attribute_deal` under the arming record's magic — the same
   fail-closed rule that adopts platform (magic-0) closes and refuses strangers.
2. **The statistic is over the SAME union.** Every counted trade's R enters the mean:
   ledger R for LCLOSE rows, venue R (`dir*(exit−entry)/|LOPEN stop_d|`) for the
   venue-only trades. The denominator is the EA's own order-time stop — the certified
   risk — never a fill-price derivation.
3. **The era marker is not part of the rule.** The count is a property of the record,
   not of whether a VPS migration is in flight. The ingest artifact is read whether or
   not `midas_vps_hosting.json` exists; the DAILY TASK overwrites it with a NO-OP out
   of era, so the wiring must preserve the last era artifact's `positions` (see §4).
4. **Era trades survive `clear-era`.** When the era marker is cleared, archived at
   `artifacts/midas_vps_hosting_*.json` eras' ingested positions stay in the count
   forever, attributed to the era they happened in (runbook §0d item 4, now binding).
   The mechanism: `vps_fills.json`'s NO-OP overwrites must never erase
   previously-ingested positions — the fold reads a **cumulative** store, not the
   artifact's ephemeral `tally`.
5. **A trade is never double-counted.** The union is by position id; a position whose
   close exists in BOTH records counts once, from the ledger row.
6. **Health semantics unchanged.** A failing or stale ingest artifact remains a
   PROBLEM in the era (the tally's heartbeat), exactly as wired in
   `_vps_fills_line`. The fold never fabricates: an unreadable venue contributes
   zero trades, not a guess.

## What would falsify this amendment

* The venue-attributed R ever disagreeing with the EA's LCLOSE R on a position both
  record (parity tolerance ±0.001R — currently exact). A divergence means one
  denominator or one attribution is wrong, and the fold stops until it is explained.
* The union double-counting, or a stranger's position entering under the arm's magic.
* The cumulative store losing positions across a NO-OP overwrite or a `clear-era`.

## What this does NOT do

It does not change MIN_TRADES, the positive-expectancy requirement, the walk-forward
gate (FAILED, operator override, untouched), or any arming condition. It does not let
python edit the EA's ledger — the ledger stays the EA's voice; this rule only refuses
to pretend the ledger's silence means "no trade happened".

## Wiring, when it happens

One shared helper in `scripts/morning_status.py` (the fold both `[3]` and `[3b]`
print through), backed by a cumulative positions store derived from
`artifacts/live/vps_fills.json` and every archived era artifact. Tests pin: the union
and its de-duplication, the cumulative store surviving a NO-OP overwrite, survival of
`clear-era` (archived artifacts read), R provenance per side, and the honest
out-of-era display (`(folded from the venue: N)`) so the operator can always see how
much of the count the ledger did not record.

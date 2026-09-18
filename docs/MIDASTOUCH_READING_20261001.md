# The 2026-10-01 First §13 Reading — Runbook

**Pre-registered 2026-09-18.** The reading is the first monthly verdict of
the four §13 gold arms (M1, M1t, M1m, M1s) under the frozen §13 gate
(docs/MIDASTOUCH_PROTOCOL.md §13, Amendment-4 values as pinned by
`tests/test_midas_verdict.py`). Nothing in this document may be edited
after 2026-09-30 23:59 UTC except by a registered amendment — the reading
judges the ARMS, and a runbook edited on reading day judges nothing.

## 1. Preconditions (the night before, 2026-09-30)

1. **Morning status green or its problems understood.** Run
   `python scripts/morning_status.py`. Preset drift, watchdog restups, or
   WLOST lines do not abort the window by themselves — the verdict tool
   pulls §12 evidence itself — but each one must be explainable in the
   reading note.
2. **No pending deploy.** The register's queue is frozen from 2026-09-30
   18:00 UTC until the reading is filed: no shadow refresh, no preset
   splices, no terminal restarts except watchdog-initiated.
3. **Watchdog healthy.** `python scripts/midas_watchdog.py --status` —
   `consecutive_restups: 0`. A watchdog restart mid-window is §12
   evidence, not a blocker; a watchdog FIGHTING (≥2 consecutive) must be
   resolved before reading so the record is stable.
4. **Clock baseline current.** [3b] footer: the offset of record with age.
   If the age is stale (no v1.12+ banner in the arms yet — they run v1.10),
   run the probe walk-through (health guide §4) BEFORE reading day so the
   reading note cites a fresh offset.

## 2. The reading (2026-10-01, any time after 00:05 UTC)

```bash
# human-readable verdicts per arm:
python scripts/midas_verdict.py

# machine artifact for the record:
python scripts/midas_verdict.py --json > artifacts/midas_reading_20261001.json
```

The tool reads each arm's paper ledger, applies the frozen gate
(`n >= 60 AND totalR > 0 AND maxDD <= 25% AND meanR >= 0.05` → VALIDATED;
`n >= 60 AND (totalR < 0 OR maxDD > 30% OR meanR <= 0)` → REJECTED;
everything else → CONTINUE-UNPROVEN), walks the §1 version-transition
exemption (cited telemetry-only builds never abort; anything uncited
aborts), and consumes §12 watchdog evidence (a restart INSIDE the window
aborts; PAUSED markers are expected and clean).

**Expected outcomes, stated in advance:** every arm will read
**CONTINUE-UNPROVEN on n < 60**. The portfolio's first fill was
2026-09-17; ~2 weeks of M30-gated trading cannot reach 60 closed trades
across four arms (observed fills: M1m 2, M1t 1, M1s 0, M1 0 as of
2026-09-18). **This is the gate working as designed** — a tiny-n VALIDATED
would be the bad outcome. The only arms that could read otherwise are
ones with structural-abort rows (version changes, watchdog restarts,
negative-equity pollution) or a REJECTED via totalR/DD — and both of those
would be honest evidence, recorded as such.

## 3. Filing the result

1. Keep the JSON artifact. Copy its per-arm verdict table into
   `docs/MIDASTOUCH_CLOSEOUT_20261001.md` (create it — pattern:
   CLOSEOUT_20260917.md) with: n, totalR, maxDD, meanR, verdict, abort
   evidence (if any), and the offset-of-record citation.
2. Update the register §3 sequencing: mark step 2 done; the first
   parity-gated era (v1.16 R6 preconditions or v1.13 telemetry columns —
   operator's choice, ONE at a time) is now unlocked.
3. Changelog entry: `[§13 — first reading filed: all arms …] - 2026-10-01`.

## 4. After the reading — the decision tree (frozen now)

- **All arms CONTINUE-UNPROVEN (expected):** proceed to the first
  parity-gated era on the ALREADY-CERTIFIED shadow line. Order per
  register §3: v1.16 (R6, in-tree, compiled 0/0 via compile_midas.py,
  awaiting its explicit WF cert when the flat gate opens) deploys FIRST;
  v1.13 telemetry columns (already §1-safe) ride in the same binary —
  both are already merged in the v1.16 tree. Fresh ledgers per affected
  arm; old ledgers archived to `artifacts/paper_ledgers/`; era note cites
  the register; the next window re-accrues from zero.
- **Any arm REJECTED on totalR or DD:** the era still proceeds (a code
  deploy cannot fix a strategy verdict), but the rejected arm's §14 slot
  is flagged in the closeout and its preset is NOT touched without a
  separate registered amendment.
- **Any structural abort:** investigate BEFORE any deploy — the abort
  names its evidence (version transition / watchdog restart / veq
  pollution). A polluted window is never judged and never re-accrued
  silently; the incident gets a closeout section, then a fresh era.

## 5. What this reading does NOT decide

- It does not authorize live trading (that is the §13 VALIDATED ladder;
  the paper line's own path to live deploy is post-VALIDATED).
- It does not re-open adjudicated items (R1–R6 are closed; the review's
  rejected claims stay rejected).
- It does not start the P-series (§2b) — that queue opens only after
  R6/R7b/R8/R9 are all adjudicated, and R7b/R8/R9 are REGISTERED, not
  built. One amendment at a time remains the law.

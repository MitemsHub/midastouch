# SESSION-HOURS STUDY — VERDICT — 2026-09-21

Protocol: `docs/GOLD_SESSION_HOURS_EA_20260921.md` (pre-registered; required sample computed
before the run). Artifact: `artifacts/gold_session_hours_ea.json`.

**Verdict: UNDERPOWERED BY CONSTRUCTION — no per-hour claim is decidable, and the one
decidable statement says the shipped gate is not costing money.**

---

## 1. The declaration held

| requirement | trades |
|---|---|
| declared effect +0.10R/trade, sd 3.31 | **n >= 4,209** |
| same, with 80% power | n >= 8,590 |
| the largest bucket measured | **114** (06–20 UTC) |

Every hour is reported `NOT EVALUABLE`, exactly as §2 of the protocol said it would be. The
per-hour table is descriptive; it is not evidence that any hour is better or worse, in either
direction, and it must not be read as a reason to widen or narrow the window.

## 2. The one thing the run does decide

Run with the session gate REMOVED (`win 0–24`), on the same eras, clock pins, engine and cost
model:

| | trades | total R | mean R/trade |
|---|---|---|---|
| gate ON (the arm's shipped policy) | 136 (42 + 94) | **+11.767R** | +0.0865R |
| gate OFF (this study) | 203 (60 + 143) | **+9.296R** | +0.0458R |

**Discarding 41% of the signals costs nothing on this window; keeping them would have paid
less.** The naive reading — "we are refusing the hours that make the money" — is what the
descriptive buckets suggest (outside 06–20: mean +0.1223R, n=89; the 00–04 block: +0.1774R,
n=57; inside: −0.0139R, n=114), and it is **an artefact of the comparison**:

**Occupancy makes those buckets non-comparable.** One position at a time means an entry at
03:00 blocks an in-session signal that the gated run would have taken. So the 114 in-session
trades of the gate-off run are *not* the 136 the gate produces — they are a different, smaller
population, and comparing their means compares two different sequences, not two hour sets. The
honest statement is the one in the table above, in total R, where both runs are whole.
(For the record, the earlier signal-level count — 368 signals over 174 days, 217 in session,
41% discarded — remains true and is about signals, not trades.)

## 3. What would decide it

The declared sample: ~4,209 trades in a bucket, i.e. ~15 years at this flow, or an effect size
of +0.5R/trade which this rule has never shown on any window. A window change would need that
forward sample, not another look at these eight months — the same bars have now been examined
four times (parity, the arming record, the EA walk-forward, this study), and each further look
is weaker evidence than the last.

**Nothing in this study changes a preset.** The session window stays 06–20 UTC.

# ARM E FORWARD TEST PROPOSAL — tp2.0 (REVERSE_BOTH, sl2/tp2/h180/r1%)

**STATUS: PRE-DRAFT — NOTHING RUNS.** Written 2026-09-16, before any forward
data exists, in the exact discipline of `docs/ARM_D_FORWARD_TEST.md`: the
verdict gates below are frozen NOW and become the only rulebook for arm E's
window the moment the arm starts. After start, amendments are append-only and
dated; editing a gate after data exists is an amendment-grade violation.

Fill-in placeholders are marked `[FILL: …]`. They are the only things this
document awaits.

---

## 0. What this proposal is

A pre-registered forward test of ONE candidate: **REVERSE_BOTH at
sl 2.0 / TP 2.0 ATR / hold 180 min / risk 1%** ("tp2.0") — the cell the V28
sweep spent its single OOS run on. It proposes a second paper arm (arm E)
whose entire purpose is the one thing no backtest in this repo can provide:
an unpolluted, pre-committed adjudication window.

Arm D's forward doc froze the rule "no second candidate on THIS window". Arm E
honors that by never touching arm D's window: fresh arm tag, fresh magic,
fresh ledger, fresh clock. This document pre-declares the program's
forward-test registry count: **exactly two** (arm D's gated candidate, arm E's
tp2.0). A third requires a dated, reasoned amendment to this line.

**Start condition (frozen):** arm E starts only after arm D's window reaches
its adjudication (VALIDATED or REJECTED) or after a structural restart of
that window. Rationale: the program holds at most one open forward verdict at
a time — every concurrently open window is a standing temptation to
rationalize across windows.

## 1. Selection provenance (the disclosure's backbone)

tp2.0 was not discovered; it was **selected** from a swept family, and the
forward window is the out-of-sample test OF THAT SELECTION. Full path, all
registry receipts:

1. **Stage-1 mode matrix** (V28-0017–0032): REVERSE_BOTH is the only mode
   positive on is90/is180/wf.
2. **Exit sweep, 15 cells** (V28-0033–0046 is180; V28-0047–0060 wf): all
   cells REFUSED per the frozen promotion gate — thin samples, no OOS.
3. **Family aggregation** (protocol §9 amendment 4): mode-level edge
   SUPPORTED in-regime (is180 p = 0.0000), borderline out-of-regime (wf
   p = 0.066; hangs on the sl1.0 cell alone per the leave-one-out
   diagnostic).
4. **OOS one-shot** (§9 amendment 3, user-authorized 2026-09-16): spent on
   tp2.0 — the best wf cell (solo permutation p = 0.051, survives every
   leave-one-out drop). Result V28-0061: positive sign, n = 12 →
   **CONTINUE_THIN**. The OOS window is closed forever; nothing may be tuned
   against it.

Selection used held windows only (is180 + wf + the single spent OOS read).
That is the honest best case AND the honest problem: every held number above
participated in choosing this cell, so **none of them is independent
evidence anymore**. The forward window is the only evidence this candidate
will ever earn that it did not help select itself.

## 2. Thin-sample disclosure (built in; quote verbatim)

> **THIN-SAMPLE DISCLOSURE — accompanies every citation of the tp2.0
> candidate, anywhere, forever:** tp2.0's only independent (out-of-sample)
> evidence is a single **12-trade** sample: +$20.55, **+0.225R**, PF **1.07**
> (registry V28-0061). That is a positive sign, not an established
> expectancy: a 12-trade mean of +0.225R carries a confidence interval wide
> enough to include zero under any realistic per-trade variance, and PF 1.07
> is inside the range a near-symmetric 12-trade coin flip produces. The
> in-sample (n = 29) and walk-forward (n = 27) samples are held-window
> evidence that survived dedupe and leave-one-out checks, but they are one
> regime and one selection path. Until arm E's own window resolves at
> n ≥ 60 under §5, nothing in this program may describe tp2.0 as "proven",
> "validated", or "profitable" — the strongest permitted phrasing is
> "directionally positive, thin, forward test pending".

## 3. What runs (pins frozen now)

- **Strategy**: V28 REVERSE_BOTH (`InpStrategyMode=3`), geometry
  `InpStopATRMultiplier=2.0`, `InpTargetATRMultiplier=2.0`,
  `InpMaxHoldMinutes=180`, `InpRiskFraction=0.01`. No other input differs
  from the sweep's `candidate_inputs()` surface — the complete explicit input
  set, never a partial one.
- **Build parity precondition (hard gate before start):** the sweep evidence
  came from the research build (`MitemshubAI_v28`). Before arm E starts, the
  forward EA build must demonstrate **trade-set-level parity** with the
  research build on one held shadow window (same window, same inputs:
  matching trade count and per-trade R within tick-fill tolerance — the
  v26.38 paper fill-model parity precedent). No parity pass, no window: a
  forward test of a different engine would be a test of nothing.
  Harness (built 2026-09-16, pre-start): `scripts/build_parity.py` — runs
  both builds on identical inputs over a held window, diffs the trade sets
  per trade (side, entry time, R; tolerance 0.02R per trade, 0.05R total,
  n≥10), and writes the verdict artifact. The `oos` block is refused
  outright; inconclusive never opens the window.
- **Arm identity**: magic **7788175** (A +75 = D; E follows the +25 offset),
  `InpArmTag=E`, paper-only (`InpLiveExecution=false`), virtual equity $50,
  24/7 session. Host: the dedicated paper terminal (49E0 install), own chart,
  alongside arm D — the sweep runner's ledger-flat gate automatically covers
  arm E's ledger before any terminal stop. `[FILL: chart path, data folder]`
- **Basis honesty** (identical to arm D §4): at $50 virtual equity the
  min-lot stop-risk is ~$5 (≈10% per trade, tolerated inside the 20% cap).
  Statistics are **R-denominated from the tagged ledger's CLOSE rows,
  post-era only**; dollar conclusions at larger bases go through the
  strangulation-floor machinery, never through this $50 book.
- **First fills**: `[FILL: first init banner datetime]` — the accrual clock
  starts at the ERA stamp, never before.

## 4. Hypothesis under test

**Post-era closed trades of tp2.0 accrue positive totalR with bounded
drawdown under per-tick paper fills on live V75 ticks, in a window the
candidate played no part in selecting.**

## 5. Verdict rule (frozen BEFORE any data exists)

Read monthly (first reading `[FILL: first-month date]`); weekly
`morning_status` glances are ops, never judgment. With **n** = post-era
closed trades — gates identical to arm D's frozen rule:

| verdict | condition |
|---|---|
| **VALIDATED** | n ≥ 60 AND totalR > 0 AND max drawdown ≤ 25% AND meanR ≥ 0.05 |
| **CONTINUE-UNPROVEN** | n < 60, or the gray zone (positive totalR, calm DD, meanR in (0, 0.05); or DD in (25%, 30%] with positive R) — keep collecting, no action |
| **REJECTED** | n ≥ 60 AND (totalR < 0 OR drawdown > 30% OR meanR ≤ 0) |

- **VALIDATED** advances tp2.0 to the pre-registered live-sizing path
  (GO_LIVE_CHECKLIST truth table + dynamic strangulation floor + this
  proposal's own adjudication branch). It does NOT authorize live orders by
  itself, and the thin-sample disclosure of §2 attaches to the proposal as a
  known limitation: 60 forward trades retire the thin-sample problem, not
  the regime question.
- **REJECTED** parks arm E and retires tp2.0 with a data-backed negative.
  The window then closes forever as a fitting target — no re-tuning against
  it, no gate re-design from it.
- **Structural aborts (any time, restart the clock):** ledger integrity
  problems flagged by `morning_status`, input drift from §3's pins (the
  preset verifier must stay clean), or a loaded-but-dead engine signature.
  After a structural fix, arm E restarts on a FRESH ledger and the window
  re-accrues from zero — a polluted window is never judged.
- **Expected duration, stated now so it cannot disappoint later:** the
  family's observed rates are ~0.13–0.30 trades/day (oos 12/90d, is180
  29/180d, wf 27/90d). n ≥ 60 therefore needs **roughly 7–15 months**. This
  is the cost of an honest n, not a delay to be engineered around.

## 6. Multiplicity and scope honesty

- ONE pre-registered forward test of ONE candidate, pre-declared as the
  program's second (see §0). No interim parameter changes, no
  peeking-driven design edits, no second candidate on this window.
- Arms A/B/C/D are NOT inputs to this adjudication; arm D's outcome is a
  start-timing gate (§0), never evidence about tp2.0.
- The spent OOS row (V28-0061) is context in §1 and never an input to §5.
- DONE pre-start (2026-09-16): `scripts/armd_accrual.py` generalized to an
  `ARMS` registry with an `arm` parameter — arm E is a registered pre-start
  entry (gates frozen verbatim, `start: None`, ledger glob `SET-ON-START-DAY*`)
  so the idempotent daily accrual and the weekly §[6] verdict wiring already
  cover it. On start day the only registry actions are §8's: set the real
  terminal id in `ledger_glob`, confirm the true init date, changelog row.

## 7. Evidence register (context, NOT forward evidence — all selection-tainted)

| window | ID | n | net $ | R (cum) | R (money-impl) | PF | max DD |
|---|---|---|---|---|---|---|---|
| is180 (held) | V28-0037 | 29 | +733.75 | +7.115 | +7.00 | 4.58 | $72.18 (0.7% of $10k) |
| wf (held) | V28-0051 | 27 | +302.18 | +3.029 | +2.97 | 1.67 | $166.34 (1.7%) |
| oos (spent) | V28-0061 | 12 | +20.55 | +0.225 | +0.20 | 1.07 | $150.44 (1.5%) |

Family context (protocol §9 amendments 4/4a): is180 family p = 0.0000;
wf family p = 0.066 with sl1.0 the sole drag; tp2.0 solo wf p = 0.051.
Tester basis $10,000; forward basis $50 virtual; R-denominated stats are
basis-independent.

## 8. Fill-in checklist at arm start

- [ ] Parity pass artifact (§3): `python scripts/build_parity.py --forward-expert
      "MITEMSHUB_AI\MitemshubAI_v28_fwd"` — verdict must be PASS (exit 0),
      artifact at `artifacts/v28_research/armE_parity_*` with both builds'
      identities and the input-pin table
- [ ] Preset file + verifier pin — PRE-DRAFTED 2026-09-16:
      `mql5/MITEMSHUB_AI/MitemshubAI_VOL75_ARM_E.set` (the frozen tp2.0
      surface + paper-arm keys, magic 7788175, tag E), enforced by
      `verify_arm_e_preset` + `verify_arm_e_consistency` in
      `scripts/verify_go_live_artifacts.py` (preset vs parity pins vs
      accrual registry, all fail-closed). The preset is a BUILD CONTRACT:
      the forward EA must implement it before start. Start-day action:
      confirm `verify()` still PASSES, then deploy the preset to the
      arm-E terminal.
- [ ] Arm E init banner datetime, chart path, data folder (§3)
- [ ] First accrual row in the generalized tracker; first monthly reading
      date (§5)
- [ ] This document's STATUS line flipped PRE-DRAFT → RUNNING with the date;
      changelog row; from then on §5 is unamendable except append-only

---

## APPENDIX (2026-09-16, append-only): SUPERSEDED BY ARM A2

User decision of 2026-09-16 (`docs/ARM_A2_RESTART.md`): the same candidate
(V28 REVERSE_BOTH sl2.0/tp2.0/h180/r1%) proceeds to forward testing as the
**arm A2 restart** — arm A's strangled $50 window repurposed, $1,000 virtual
basis, magic 7788100, tag A2. The §0 start gate (wait for arm D) is amended
away; every other section of this proposal — gates, thin-sample disclosure,
build-parity precondition, preset pins — carries over to A2 unchanged in
content. Arm E never opened a window (no parity run, no banner, no ledger);
this document remains on record as the design template and the evidence
register. The A2 accrual registry entry supersedes this proposal's §6 note.

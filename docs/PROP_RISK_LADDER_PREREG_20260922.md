# Pre-registration — the prop-state risk ladder, and what the minimum lot makes possible

**Written 2026-09-22, before the run it governs. Results appended below §Results.**

## The question, and the constraint that shapes it

The prop-math research read in-browser (`aifo.com/blog/guide/risk-per-trade-prop-firm-challenge/`,
updated 2026-09-07) prescribes a **risk ladder keyed to account state**: hold base risk while the
account is fresh, reduce or stop after consecutive losses and as the daily-loss floor approaches, and
**trade smaller — not bigger — above 70 % of the profit target**. It sizes risk from the *smallest*
of the remaining daily-loss room, the maximum-loss room and a personal daily stop, then subtracts a
cost cushion.

**MEASURED, and it changes what a ladder can even be on this account.** At $25,004 with the venue's
**0.01 lot minimum** and the measured 2×ATR(H1) stop, one R is **$41.31 = 0.165 %** of equity. The
pre-set ladder's *reduction* half is therefore **unavailable**: there is no smaller trade to take.
Risk quantises to `0.01 lots = $41.31 (0.165 %)` · `0.02 = $82.62 (0.33 %)` · `0.03 = $123.93
(0.50 %)`, so the declared `0.25 % = $62.51` sits between two steps and is **unreachable**. On this
account the only *downward* lever a ladder has is **skipping an entry**, not shrinking it.

## What is simulated, and on what

- **The sequence is real:** the armed mode's held-out fills (`oos`, 2026-04-01 → 2026-09-16), taken
  in their actual chronological order in the arm's own live frame (UTC 04–18), each carrying its own
  `r`, its own entry timestamp and its own UTC day. R-multiples are lot-invariant, and `1R = $41.31`
  is the measured dollar value at the arm's size, so nothing here is a hypothetical fill.
- **Account constants:** equity basis **$25,004.26**; daily-loss cap **3 %** of the day's opening
  equity; daily profit ceiling **$250** (`size × target% × best-day%`, the EA's own function); shield
  floor at **6 % / $1,500**.

## The three variants, declared before the run

| variant | rule |
|---|---|
| `FIXED` | take every entry at 0.01 lots (the arm's live behaviour) |
| **`LADDER`** | skip an entry when any holds: **(i)** two consecutive losing closes already today; **(ii)** today's realised P&L ≤ **−2 %** of the day's opening equity (two-thirds of the 3 % floor); **(iii)** today's realised profit ≥ **70 %** of the $250 ceiling. Otherwise take it, unchanged size |
| `SHIPPED` | the governor as deployed: min-lot risk veto, 3 % breaker, $250/day ceiling **blocking further entries once reached**, 6 % shield |

`LADDER`'s thresholds are the researched prescription applied to this account, **declared here and
not swept** — a swept ladder would be another search on 130 trades.

## The metrics, and the pass rule

Reported for each variant: fills taken, **P(positive 30-trade block)**, **P(any day breaching the 3 %
cap)**, medians of fills-to-30 and of the block's max drawdown, and the net R over the whole held-out
sequence.

**`LADDER` may replace the shipped behaviour ONLY IF, on the held-out sequence:**

1. `P(positive 30-trade block) ≥` `FIXED`'s, **and**
2. `P(daily-cap breach) <` `FIXED`'s, **and**
3. it does not delay the 30-trade record by more than **25 %** (median fills-to-30 and days-to-30).

## Disclosures, before the numbers

- **Skipping does not create opportunities.** A skipped entry in this simulation does not free the
  position slot for a later signal the way it would live, so `LADDER`'s fill count is **understated**
  and its delay **overstated**. That direction is against the variant being tested and is stated
  rather than corrected.
- **P(30-trade block) is a circular block bootstrap** over the real sequence (blocks of 20 wrapped),
  so it re-uses the same 130 fills and is a *shape* statement, not independent evidence. The
  deterministic replay of the actual sequence is reported beside it.
- **No EA change in this study.** If `LADDER` wins, the implementation lands in
  `PropPhaseCheck()`/`LiveSendOrder()` beside the existing governor, with the account layer re-verified
  by `scripts/verify_sizing_live.py`, and recorded in `armed.json`.
- **The default stays 0.01 lots** unless this study contradicts it: a near-zero measured edge does not
  justify scaling variance, and 0.33 % requires 0.02 lots — the next quantisation step, not a dial.

---

# RESULT — 2026-09-22 — **NOT-BINDING** (the ladder was never reached)

Artifact `artifacts/midas_risk_ladder_20260922.json`. Sequence: the armed mode's **130 real held-out
fills**, live frame UTC 04–18, **+0.0869R** mean, 1R = **$41.31 = 0.165%** of $25,004. The pinned
venue-corpus law reproduced first (`wfv REVERSE_DIRECTION n=56 totalR=+15.9352`, vetoed 0), so the
arithmetic below is the engine of record's.

## The measurement that decides it is the day structure, not the ladder

| | measured |
|---|---|
| active days / calendar days | 100 / 169 (**40.8%** of days hold no fill) |
| fills per day | `{1: 70, 2: 30}` — **maximum 2** |
| worst day | **−2.01R = −0.332% of equity = 11.1% of the 3% cap** |

| variant | fills | skipped | netR | P(blk>0) | breach% | fills/day | days→30 | blockDD% |
|---|---|---|---|---|---|---|---|---|
| FIXED | 130 | 0 | +11.30 | 67.2% | 0.0% | 1.300 | 23.1 | 0.74 |
| LADDER | 130 | **0** | +11.30 | 67.5% | 0.0% | 1.300 | 23.1 | 0.75 |
| SHIPPED | 130 | 0 | +11.30 | 67.3% | 0.0% | 1.300 | 23.1 | 0.75 |

**`LADDER` skipped 0 of 130 fills.** Every within-day condition the research prescribes is unreachable
on this arm as it stands:

- **two consecutive losing closes today** requires a **third** fill that day (two losses *then* an
  entry still to be vetoed), and the maximum this window ever holds is **two fills in a day**; the
  threshold sits at **fill 3** in a market that gives at most **fill 2**.
- **day down 2%** needs **−12.1R in one day**; the measured worst day is **−2.01R** — the stop is
  **9×** further than the worst day this strategy has produced in five months.
- **70% of the $250 ceiling banked in a day** needs **+$175**; two fills at the candidate's own
  expectancy hold roughly **$0.50**.

## What this is, and what it is not

**It is not "the ladder is wrong".** It is: *the ladder cannot be tested here.* The researched
prescription — reduce or stop risking once the day is already losing or the account is deep in
profit — is a **conditional** rule, and this arm's days are too small and too rare for its conditions
to occur. At **0.165%** risk per trade and **1.3 fills/day**, a day's excursion is **11%** of the cap.
The rule would need either **~6× more fills per day** or a **stop distance several times** the current
2×ATR(H1) before a single one of its triggers could fire, and moving either to make a rule fire is
precisely the curve-fitting this program refuses.

## Two defects this run found in itself, both kept on the record

1. **The first bootstrap mis-modelled the block as one day.** It resampled 30 *trades*, then applied
   the ladder's day-level thresholds to that block as if it were a single day — resetting the state
   never where it should reset ~40 times. It reported `LADDER` **P(block>0) = 45.6%** against
   `FIXED` **70.6%**, i.e. an apparent **25-point penalty for a rule that never fired**. The unit is
   now the **day**, drawn at the window's own inert-day rate; the corrected figures are **67.2% vs
   67.5%**, a difference of bootstrap noise on the *same* kept set, which is what a no-op rule must
   produce. The artifact was re-run; the misleading number is not in it.
2. **A vacuous check was printed as a refutation.** With both variants at **0.0%** daily-cap breaches,
   `P(breach) < FIXED` reported **FAIL** — a comparison with nothing on either side of it. The harness
   now carries a **`binding`** field decided by the ladder's own skip count and marks such a check
   **VACUOUS**, and the verdict vocabulary for a rule that never fires is **`NOT-BINDING`** rather
   than `FAIL`. Same distinction the live-stance governor leg already uses.

**Disposition: not implemented.** No EA line changes, no preset changes, nothing armed or disarmed.
The default remains **0.01 lots**. The 0.25% declared risk remains unreachable by quantisation
(0.01 lots = $41.31 / 0.02 = $82.62 / declared = $62.51), which is itself the finding that makes the
"reduce size" half of any such ladder unavailable here.

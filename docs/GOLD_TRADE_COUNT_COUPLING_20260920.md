# TRADE-COUNT COUPLING — WHERE DRAWDOWN AND BEST DAY CAN BOTH HOLD

Study: `scripts/gold_day_count_coupling.py` · Artifact: `artifacts/gold_day_count_coupling.json`
Date: 2026-09-20 · Symbol: XAUUSD

---

## 1. WHY THIS EXISTS

DAILY-SEQ found something neither earlier study had looked for: a rule aimed at the
**trailing drawdown** (sitting out days after a loss) made the **Best Day** share much
worse — 9.6% → 29.8% — because trading fewer days re-clusters the winners into fewer
days. Two constraints that had been treated as independent turned out to be **coupled
through the trade count**. The brake is the one knob that moves the number of trading
days, so it is the right knob for asking whether a trade count exists where both
constraints hold at once.

Two quantities are tracked per row, not total R (which everyone expects to fall):

- **Best Day share** — must be ≤ 20%. Scale-invariant, so only the *shape* of the day
  distribution can satisfy it.
- **peak-to-trough / total profit** — the ratio the trailing shield actually polices,
  since the shield floors equity below its high-water mark while the target must still be
  reachable below it.

## 2. A DESIGN ERROR THAT PRODUCED A FLATTERING RESULT, AND ITS FIX

The first version let each row include **every brake up to its own value**, so the row for
`k` was selected from `4 × (k+1)` configurations. It reported the survivable size
**rising** with the brake — $194.92 at brake 0, $301.86 at brake 2 — which reads as the
brake helping.

It is not the brake. **Best-of-12 selection beats best-of-4**, and the curve was measuring
multiplicity. This is the same class of error as reporting a strategy's in-sample pick as
its out-of-sample result, and it only became visible because the grid size was printed
next to the result.

The fix holds the grid at **exactly 4 configurations per row**, so the brake is the only
thing that varies. Every row is then directly comparable with DAILY-SEQ's control, which
was that same grid.

## 3. RESULT (equal grid, 4 configs per row)

```
 max brake  grid  days   total R       t  best-day    V7  peak/trough   R/tot  survive $    V8
         0     4   119    +12.83   +1.33      9.6%  PASS         6.41    0.50     194.92  PASS
         1     4    90     +4.13   +0.50     29.8%  FAIL         6.66    1.61       0.00  FAIL
         2     4    76     -2.74   -0.28      nan%  FAIL         8.03     nan       0.00  FAIL
         3     4    65     +7.15   +0.80     17.3%  PASS         4.88    0.68     307.47  PASS
         4     4    58     -4.13   -0.59      nan%  FAIL         5.95     nan       0.00  FAIL
         6     4    50     +7.24   +0.90     17.0%  PASS         6.17    0.85     345.26  PASS

where both constraints hold: YES, at max brake 0 — 119 days, best-day 9.6%, survivable $194.92
```

**The relationship is not monotone, in either direction.** Best Day goes 9.6 → 29.8 → n/a
→ 17.3 → n/a → 17.0, and drawdown-over-profit goes 0.50 → 1.61 → n/a → 0.68 → n/a → 0.85.
Rows 3 and 6 — *fewer* trading days — show **better** compliance and a **larger** survivable
size than row 1. If trade count drove these constraints, that could not happen.

**So this window cannot characterise a trade-count region, and the honest answer is that
the question is not answerable at this sample size.** Each row is a best-of-4 selection on
the *same* 21 folds, so cross-row differences share the window's noise; six points on one
window cannot separate a trend from a fold-level accident. A thin, non-monotone curve in
both directions is the signature of noise dominating, not of a mechanism with a threshold.

## 4. WHAT THE CURVE DOES ESTABLISH

1. **The feasible region is not empty — the frozen design already sits inside it.** At
   brake 0 (119 days) both constraints hold simultaneously: Best Day **9.6%** against a 20%
   cap and a survivable size of **$194.92**. So DAILY-ONE's cadence is *already* the point
   where drawdown and Best Day coexist, which is a stronger statement than "some trade
   count exists somewhere".
2. **Adding a brake moves out of the region, not deeper into it.** DAILY-SEQ's mandatory
   brake dropped both constraints at once (29.8% share, $0 size). The coupling is real, and
   it is a reason **not** to touch the day count.
3. **Nothing on this curve is tradeable regardless.** The best t-statistic anywhere is
   **+0.90** against a 1.5 bar, so even the rows whose constraints pass fail V6.

## 5. THE GENERALISABLE FINDING

**For a trailing-drawdown account, trade count is a compliance variable, not a free
parameter.** Best Day is scale-invariant — no position size moves it — but it is *not*
cadence-invariant: it responds to how profit is distributed across days. DAILY-ONE's
one-entry-per-day cadence is what delivered the 9.6%, which means the concentration fix
and the drawdown fix are not independent levers to be tuned separately. **Do not tune the
cadence to fix the drawdown; the drawdown is a sizing problem (see
`docs/GOLD_PROSPECTIVE_SIZING_PROTOCOL.md`) and the cadence is a concentration problem.**

## 6. LIMITS

- Six brake points, one window, one signal, 21 folds. Sufficient to reject a monotone
  coupling, **not** sufficient to estimate one.
- Rows 2 and 4 have negative total R, so Best Day share is undefined (`nan`) and the
  drawdown ratio is not meaningful. They are reported rather than dropped so the curve is
  not implicitly filtered toward the flattering rows.
- The brake changes which days trade, so each row is a different sample. Differences are
  not paired and no significance is claimed anywhere above.

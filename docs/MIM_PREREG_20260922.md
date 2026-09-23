# MARKET INTRADAY MOMENTUM — PRE-REGISTRATION — 2026-09-22 (23:0xZ, before any measurement)

**Written before this file's mechanism was run on any span.** The rule below, the spans, the
gates, and the verdict text are fixed here first; `scripts/midas_mim.py` implements exactly
what is written and nothing else. Any later edit to this file must be dated and justified in
place, never silently.

## 0. Why this family, and what it is NOT

The operator's complaint (2026-09-22 evening): the arm declined to join a visible rally. The
census of the same hour shows the armed mode is structurally a fade of extremes and cannot
join a sustained move; the sweep-shadow family is a liquidity mechanism, also not a
with-trend one. The missing basket is a **with-trend** family with published out-of-sample
evidence.

**The candidate: market intraday momentum (MIM).** Gao, Han, Li & Zhou, *Journal of Financial
Economics* 129 (2018) 394–414: on US index ETFs, the **first half-hour return positively
predicts the last half-hour return**, robust out-of-sample, and replicated in commodity ETFs
(Xu et al. 2020), Chinese commodity futures (Zhang et al. 2020), and internationally (Li,
Intraday Time-Series Momentum: International Evidence). This is *time-series* momentum at
intraday resolution — the same asset's morning predicting its afternoon — which is a
**different hypothesis** from the cross-sectional momentum the Mahadzva series measured to be
uniformly negative (`docs/EXTERNAL_LITERATURE_RECONCILIATION_20260922.md`, `7435081`), and
different again from opening-range breakouts (all four of their ORB combinations lost; MIM
enters mid-session on accumulated direction, not at the open on a range break). Both
distinctions are stated because the honest base rate is: **three of our last four external
leads died on this venue.** This pre-registration expects the same possibility.

## 1. The mechanism, fixed

Gold's venue day under the armed gate runs 04:00–18:00 UTC. Split it at the midpoint:

* **First-half return** `r1 = close(bar opening 10:45Z) − open(bar opening 04:00Z)`
  (the 04:00 bar's open to the 10:45 bar's close — 28 M15 bars, no gaps assumed, venue bar
  series as of record).
* **Decision at the 10:45Z close** (11:00Z bar open = the fill, the engine's own
  signal-bar → next-bar-open convention, no lookahead).
* **Signal**: `+1` if `r1 > +thr`, `−1` if `r1 < −thr`, else `0` — where
  `thr = c × ATR14(H1)` at the decision bar, Wilder ATR on the venue's own H1 series,
  `c ∈ {0.0, 0.25, 0.50}`.
* **Variants**: `MOM_*` trade **with** the sign of `r1` (the MIM hypothesis);
  `REV_*` trade **against** it — the direction check the literature says should lose. If a
  `REV_*` variant beats its `MOM_*` twin on the held-out span, the finding inverts and the
  inversion is the recorded result.
* One signal per day maximum (the 10:45Z bar is the only bar that can carry a nonzero
  entry), one horizon (the engine's own exit geometry: 2.0×ATR H1 stop, 2R target, 48-bar
  timeout, half-spread both sides — the certified defaults, unchanged).

Clarified before running, dated: **PASS requires `MOM_0` itself to clear every gate**;
"at least two of the three `MOM_*`" is robustness evidence recorded beside the verdict, not
an alternative path to PASS. And `r2` in §3 is the second half's price return:
`close(bar opening 17:45Z) − open(bar opening 11:00Z)`, matching the entry horizon.
One more, same standing: "`thr` read at the decision bar" means **the last H1 bar CLOSED
before the decision** (the 09:00Z bar for a 10:45Z-bar decision) — the engine's closed-bars
convention; reading the still-open 10:00Z bar would be lookahead.

Family size: **6** (3 thresholds × 2 directions). The program-wide hurdle is applied at
t ≥ 2.4 on the held-out span with n ≥ 30 and ≥ 0.30 fills/day, same sign on the selection
span — the identical pass rule the Asian-sweep pre-registration set (`T_BAR=2.4`,
`MIN_TRADES=30`, `MIN_PER_DAY=0.30`), with family size 6 declared for any deflation
accounting. **Primary cell, declared now: `MOM_0`** (pure sign — the paper's own
specification, and the one that fires most often, which is also the operator's stated want:
activity). The threshold variants are robustness, not a search.

## 2. Spans of record

The repository's existing pinned split — `P._window_spec("wf")` for selection,
`P._window_spec("oos")` for the held-out report — over the venue corpus
(`data/forex/xauusd/XAUUSD_M15_upcomers.csv` + its H1 companion, the same series every other
study used). No new data, no re-rolling of windows, no peeking at `oos` before `wf` is
written down.

## 3. Descriptive statistics (declared, not gates)

Alongside the tradeable cells, the pure predictability regression is reported per span:
`r2 = a + b·r1 + e` with OLS t on `b`, and the sign-contingency table. These describe the
effect; only the engine's trade cells can pass or fail.

## 4. Verdict rule (fixed before running)

* **PASS**: `MOM_0` (or, robustly, at least two of the three `MOM_*`) on the held-out span:
  t ≥ 2.4, n ≥ 30, ≥ 0.30 fills/day, mean > 0, same sign on `wf`, and no `REV_*` twin
  beating its `MOM_*` twin. Only then does a shadow-recorder conversation begin — this
  pre-registration arms nothing and touches no EA input.
* **FAIL**: any gate unmet. The verdict line names which gate failed and the counts that
  failed it. A FAIL is a result: it is the second external momentum lead to die here, and
  the record says so in those words.
* **VOID**: the series or the split fails its own self-check (pinned corpus law does not
  reproduce), or the day-split arithmetic disagrees with the engine census.

## 5. What this pre-registration does not claim

It does not claim MIM works on gold on this venue — nobody has measured that here; the
papers are on other instruments and their numbers may not transfer. It does not propose an
EA change, a preset change, or an arming event. If it passes, the *next* step is the same
forward shadow treatment the sweep family got: rows first, verdict later, orders never.

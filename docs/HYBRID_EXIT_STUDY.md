# HYBRID EXIT STUDY — pre-registered 2026-09-15, frozen BEFORE implementation and runs

**Candidate:** per-tick first-touch stop fills with bar-open management retained
("the hybrid"). Motivated by the 09-15 STOP-gap decomposition: the paper engine's
exit cadence overshot its stops by −0.251R/event (n=7, CI [−0.411, −0.114],
drop-worst still excludes 0), while the same cadence let winners ride (+1.658R net
on the paper sample). This study isolates the two effects on the certified 60-day
window, end-to-end, on one shared signal stream.

**Hypothesis, stated so it can lose:** the hybrid's advantage over the engine-cadence
book is **≥ +0.08R/trade** on the certified window. If it is smaller, the candidate
dies and nothing goes to paper.

## 1. Fixed inputs (no freedom)

- Data: the certified window exactly as the baseline of record —
  `artifacts/v75_replay/m15.csv` + `h1.csv` (2026-07-07 → 2026-09-04, 60 days),
  harness `scripts/certify_v75.py` with `--tp-mult 1.8` (arm-A geometry), default
  equity $50, spread 18.5, v26.36 spread-in-pnl cost model, micro-fit ON.
- Signal stream: identical across variants by construction (same bars, same gates,
  same funnel) — variants differ **only** in exit booking.

## 2. The three books (variants frozen now)

- **H — hybrid (touch):** the harness's existing default exit model. Stops fill at
  the stop level on first touch (entry bar included); TP fills at touch; SL(ambig)
  when both touch in one bar (conservative). Management (BE, trail, PLOCK, ECUT,
  TIME, cooldown, pause) unchanged.
- **L0 — engine cadence, ideal spike fills:** the paper engine's evaluation cadence
  mirrored exactly:
  1. At each bar-open after the entry bar (engine's ladder tick): SELL: if
     `O ≥ SL` → exit filled **at O** (gap-through), reason SL; elif `O ≤ TP` →
     exit filled at O (favorable overshoot), reason TP. BUY mirrored. SL checked
     before TP when both are true at the open (conservative).
  2. Intrabar stop touch (any bar incl. entry bar): **spike-path** fill at the
     current stop level exactly (idealized — no overshoot).
  3. Intrabar TP touch after the entry bar: **no fill** — the engine's ladder does
     not see it; the position rides to the next bar-open (this is the winner-ride
     effect). Entry-bar TP touch fills at TP (spike-path, conservative).
  4. SL and TP both touched intrabar in one bar → SL (conservative, mirrors the
     sim's SL(ambig) rule).
- **L1 — engine cadence, paper-measured spike fills:** identical to L0 except rule 2:
  spike-path stop fills carry the paper stream's measured mean overshoot
  **0.251R adverse** (`fill = stop ± 0.251·sd` against the position). This is the
  engine-as-observed book.

Management is byte-identical in all three books. Nothing else differs.

## 3. Frozen gates (checked in this order; no post-hoc reinterpretation)

- **G0 — control reproduction:** the H run must reproduce the baseline of record
  `cert_report_fresh60_tp18_net.json`: n=114 and total_r = +4.37 within ±0.05R.
  Failure ⇒ harness drift ⇒ **STOP everything**, fix the harness, re-register.
- **G1 — candidate bar (primary, H vs L0):** mean paired per-trade ΔR (H − L0)
  ≥ **+0.08R/t** AND paired t ≥ **1.0** (the house P1 bar) AND ≥ **4 of 6**
  consecutive 10-day folds with positive ΔR sum. Primary comparison is against L0 —
  the *hardest* book, engine cadence without even the overshoot pathology — so a
  pass cannot be an artifact of the slippage model.
- **G2 — config bar:** H total_r ≥ 0 on the window (a hybrid that only narrows
  losses is not a live-candidate config; the tree requires positive expectancy).
- **G3 — robustness:** H vs L1 must also clear ΔR/t ≥ +0.08 with t ≥ 1.0. If G1
  passes but G3 fails, verdict = CONDITIONAL (mechanism depends on the overshoot
  model) — no paper test.
- **G4 — anti-tuning:** every constant above (0.251R, fold count, bar levels) was
  fixed before the first run. Any deviation voids the study and must be logged as
  a failed pre-registration.

## 4. Statistics

Paired per-trade deltas keyed on (sig_t, strat, dir) — the books share the signal
stream, so pairing is exact. Report: n pairs, mean ΔR/t, 20k-resample bootstrap 95%
CI, paired t, per-fold ΔR sums (6 × 10-day folds via the harness's `--start/--end`
slices with full-history indicator burn-in).

## 5. Decision mapping (frozen)

- **PASS (G0–G3):** the hybrid becomes an exit-mode candidate. It does **not** touch
  any arm now. Path: wait for the primary A/B adjudication to complete (the running
  duel may not be contaminated), then a NEW pre-registered paper protocol on a
  dedicated arm (arm C is a different engine; a third Mitemshub arm or a
  post-adjudication repurpose — decided in that protocol, not here), ≥30 closed
  trades, new adjudication rule. Live consideration only through
  `GO_LIVE_CHECKLIST.md` afterwards.
- **FAIL (any gate):** candidate dead. Recorded here and in the changelog; no retry
  without a new pre-registration with a new mechanism story.

## 6. Provenance

Baseline of record `cert_report_fresh60_tp18_net.json` (+0.038R/t, t=0.35, n=114);
stop-gap decomposition `stop_gap_decomposition_20260915.json` (amended 09-15 PM:
−0.251R/stop mean, CI [−0.411, −0.114], flat conditional-jump test, net cadence
package +1.658R on the paper sample); house bars: P1 |t|≥1.0 (`ab_adjudicate.py`),
+0.08R/t materiality (`V75_SPREAD_TIER_STUDY.md` §4).

## 7. RESULT — adjudicated 2026-09-15 (same day, runs 09:57–10:05): **FAIL — candidate dead**

- **G0 first failed, then passed.** The worktree harness no longer reproduces the
  certified baseline (n=84, −14.57R: it gained micro-fit 1.5% and the sd ≥ 107.7
  min-stop floor since 09-05, and those alone flip the book). The certified era was
  recovered at HEAD (commit `841bf97`); the frozen study harness is
  `scripts/study_frozen_certify_v75.py` = HEAD + only the exit-mode patch. On it,
  H reproduces the baseline **exactly** (n=114, +4.37R, WR 45.6%, $53.44). G0 PASS.
- **G1 FAIL (primary, H−L0):** 98 exact pairs, mean ΔR **+0.0391R/t** (bar: +0.08),
  t=+1.33, CI [−0.015, +0.099] straddles 0, fold sums [+3.36, −1.00, −0.59, +1.80,
  +0.27, 0.00] → 3/6 positive (bar: 4/6). The hybrid's advantage over the engine
  cadence is real in sign but **half the bar and not significant** on the window.
- Books: H +4.37R (n=114) vs L0 −2.36R (n=117) vs L1 −4.61R (n=**6**).
- **G3 uninformative by collapse:** with the measured −0.251R spike overshoot, L1
  triggers **589 risk-cap vetoes** — at $50 the drag grinds equity below the 20% cap
  until the book strangles to 6 trades. The overshoot pathology is not primarily an
  exit-model question at tiny size; it is an account-scale question.
- **Decision, per §5:** FAIL ⇒ the hybrid exit mode does not go to paper. Collection
  continues unchanged; any retry needs a new pre-registration with a new mechanism
  story (e.g. sizing-aware exit design, not exit cadence alone).
- **Side finding promoted to the playbook:** the certified baseline is now
  reproducible only from the frozen snapshot — the worktree harness has drifted
  past it. The NO-GO playbook's Step 2 R1 check must pin the harness version
  (HEAD + dated patches), not the worktree file. Amended there, dated 09-15.

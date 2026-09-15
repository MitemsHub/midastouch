# SPIKE CONTINUATION STUDY — design frozen 2026-09-15 before the run

**Claim under test (from the stop-gap decomposition):** per-tick spike-path stop
fills land "into cascades" — a move fast enough to trip the spike path tends to
continue after the fill, making the overshoot structural rather than bad luck.
The paper evidence was 2 events. This study tests the claim on the whole tick
corpus with **no positions involved** — pure market mechanics.

## Frozen design

- **Data:** `artifacts/data/volatility_75_index_ticks_fresh90.csv` (epoch_ms, bid,
  ask; 2026-07-07 → 09-02, 3.88M ticks — covers 58 of the certified window's 60
  days). Mid = (bid+ask)/2. Entries into M15 bars by epoch bucket.
- **Event definition (position-free):** a bar **crosses** a stop level ℓ if
  bar[i-1].close is on one side and min/max(mid) of bar[i] reaches ℓ (ℓ = 1R below
  bar[i-1].close for down-crossings, 1R above for up-crossings — 1R ≡ the bar's own
  last close ± 1.0 × the window-median M15 true range; the exact scale cancels in
  the continuation ratio). For every crossing tick we measure **post-fill
  continuation**: mid movement from the crossing tick to
  {5s, 30s, 2min, 8min} later, signed in the crossing's direction
  (positive = continued, negative = reverted).
- **Spike vs control split:** a bar is a **spike bar** if its (high−low) exceeds
  the 90th percentile of trailing-24h M15 ranges **and** |open→crossing-tick move|
  happened within the first 10 minutes of the bar (speed condition — the engine's
  per-tick path fires on fast moves). Bars crossing their level slowly (crossing
  tick after min 10, or range < p70) form the **slow-control** group; bars crossing
  fast without an extreme range form the **fast-control** group. The claim predicts:
  **spike bars continue more than both controls at every horizon.**
- **Estimator:** median and mean continuation per group per horizon, plus
  P(continuation > 0). Bootstrap CIs (20k) and a permutation test: shuffle the
  spike labels among crossing bars (10k shuffles) for the group difference in mean
  continuation at 2min — the frozen primary statistic.
- **Primary statistic (frozen):** Δ2min = mean continuation(2min | spike bars) −
  mean continuation(2min | slow-control bars), in R units. Claim holds iff
  Δ2min > 0 with permutation p < 0.05 AND the same sign holds at 30s and 8min.
- **Also recorded (secondary):** the overshoot proxy — median further adverse move
  in the 8min after crossing for spike vs control (bounds what an overshoot-prone
  fill could cost), and the count of crossings per group (precision).
- **Anti-tuning:** thresholds (p90 range, 10-min speed split, horizons) frozen
  above; one run, then verdict. Parameter changes void the study.

## RESULT — run 2026-09-15, appended after the single frozen run: **CLAIM HOLDS**

Run on the full corpus: 8,640 M15 bars, **2,421 crossing events** with measurable
continuation — spike **n=516**, fast-control **n=491**, slow-control **n=1,414**.
One implementation bug was caught and fixed before any result was read (the bar's
list index was used as an epoch base for the speed test, forcing all events into
the slow group); the fix touched only the speed-test base, not the frozen
definitions. The single run then produced:

**Primary (frozen): Δ2min = +0.1785R, permutation p < 0.0001 (0/10,000 shuffles),
bootstrap CI [+0.153, +0.204] — and the sign holds at 30s and 8min. CLAIM: TRUE.**

Continuation after a 1R-level crossing, by group (positive = continues in the
crossing direction):

| group | 30s | 2min | 8min | P(continue)@8min |
|---|---|---|---|---|
| **spike** (fast + extreme range) | **+0.042R** | **+0.135R** | **+0.321R** | **78.5%** |
| fast control (fast, ordinary range) | −0.004R | −0.048R | −0.153R | 38.3% |
| slow control | −0.018R | −0.044R | −0.070R | 42.8% |

Readings:
1. **The cascade correlation is a market-level fact, not a 2-trade accident.**
   After a spike-classified crossing, price continues in the crossing direction:
   median **+0.334R further by 8 minutes**, 78.5% of events. Controls revert.
   The paper-measured 0.251R mean overshoot sits inside this distribution — the
   two paper events were representative of the mechanism.
2. **It is the spike signature, not speed alone.** Fast-but-ordinary crossings
   *revert* (−0.15R at 8min). Only the fast+extreme class continues. This kills
   the "any fast fill suffers" alternative explanation.
3. **The continuation builds over 30s→8min** (5s is noise) — consistent with an
   impulse lasting minutes, which is exactly the window a bar-open ladder cannot
   escape but a spike-path fill lands inside.

Consequences: (a) the L1 book in the hybrid study — ladder + measured overshoot —
rests on validated mechanics, so its risk-cap strangle finding (account-scale
problem) stands; (b) the stop-gap decomposition's "structural, not luck" verdict
now has a market mechanism with ~260× the original event count; (c) caveat kept
honest: this study is position-free with a proxy level (prior close ± 1 median-TR);
the engine's exact per-fill overshoot distribution still comes best from the paper
stream or an enabled TickRecorder archive.

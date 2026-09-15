# VIABLE-SCALE GEOMETRY STUDY (VSG) — pre-registered 2026-09-15, before any variant run

**Question (from the strangulation-floor amendment, GO_LIVE_CHECKLIST 2026-09-15):**
can ANY risk input + stop sizing make arm C's geometry viable at $150 — and if the
current stop geometry cannot, what minimal change makes it so? This doc freezes the
answer space and the gates BEFORE any candidate variant is replayed. Amendments
append-only and dated. Execution follows the certified chain: this study → fresh
window → (only on VALIDATED-CANDIDATE) a paper arm under the frozen arm-C
adjudication rule.

## 1. The re-pricing (computed 2026-09-15 from frozen data — the frontier)

Forward simulation over the certified replay's own 114-trade sequence
(`cert_report_fresh60_tp18_net.json`: per-trade stop distance `sd`, R sequence),
percentage-regime sizing with min-lot refusal modeled exactly
(`refuse when r%·E < sd·k`, k at the conservative frozen max 0.014884), bisection
for the thresholds:

| risk input r% | min $ for 0 refusals | max DD at that $ | verdict at $150 |
|---|---|---|---|
| 1.0 (production) | $1,446 | 3.3% | INERT (the known static result) |
| 2.0 | $672 | 6.5% | INERT |
| 3.0 | $442 | 9.8% | INERT |
| 5.0 | $268 | 16.1% | INERT |
| 7.5 | $181 | 23.7% | INERT (all entries refused) |
| **10.0** | **$138** | **31.0%** | **admitted, unstrangled through the full window** |
| 12.5 | $121 | 46.1% | admitted but DD breaches the 45% freeze line |
| 15.0 | $141 | 63.6% | DD far past any survivable band |

Cross-check: the percentage regime needs `E ≥ s/r` = 20.50/0.10 = $205, plus the
one-trade-after-streak buffer → **$225.54, the strangulation floor computed
independently** (`s·(k+5)`, GO_LIVE_CHECKLIST amendment). Two derivations, one
number. The frontier is real.

## 2. The frozen answer space — exactly two candidate variants

**V1 — risk-input only (minimal change):** `InpRiskPercent: 1.0 → 10.0` at the
*unchanged* stop geometry (2.0 × H1 ATR(14)). Nothing else moves.
- Feasibility at $150: 0 refusals over the certified window; worst window DD
  31.0% (window contains the k=6 streak; total 114 trades, +4.37R before
  re-pricing costs — the variant does not claim edge, only survivability).
- The cost: each stop = −10% (−18.9% worst at kmax geometry, e.g. sd 1268 pts).
  Three stops = −27.1%. This is an aggressive small-account profile by design —
  the study's job is to measure it, not to like it.

**V2 — stop-scaling only (risk input unchanged at 1.0):** `--stop-mult` s* < 1
shrinks every stop distance; min-lot risk scales down linearly. Frozen grid:
s* ∈ {1/3, 0.5, 2/3} (admission bound: s* ≤ 0.487 makes the p95 worst stop fit
$10 at $50; 0.5 → worst ≈ $10.25, 2/3 → ≈ $13.67).
- The trap this variant must clear (frozen before the run): the tick corpus
  measured **median intra-bar M15 range = 0.541R** (stop_gap_decomposition,
  2026-09-15, n≈1000 bars). At s* = 0.5 the stop sits at ~0.5R-equivalent of
  ORIGINAL-R space — **inside ordinary intra-bar noise**, so the stop-hit rate
  must rise mechanically. The spike-continuation study (516 spike crossings
  continue a median +0.334R further) predicts tighter stops are harvested by
  exactly the cascade mechanism that already costs −0.251R/stop on the arms.
- V2 is registered to be *falsified properly*, not to win: G2 below is its gate.

**Nothing else is a candidate.** Wider stops raise s and the floor; hybrid exit
cadence was killed by its own frozen gates (HYBRID_EXIT_STUDY 2026-09-15); TP
changes are arm B's duel, not a scale fix. Hand-tuning between variants is
illegal; the grids above are the whole space.

## 3. Gates (frozen; evaluated on the pinned harness,
`scripts/study_frozen_certify_v75.py`, on the SAME certified window as the
frontier so variant-vs-frontier differences are pure variant effects)

- **G0 (control):** rerun of record reproduces (n=114, +4.37R ±0.02, funnel
  shape). Same amendment as the NO-GO playbook: pin the harness, never the worktree.
- **G1 (V1):** 0 min-lot refusals at E=$150 over the window AND max equity DD
  ≤ 45% (the arms' 3-loss compounding bound, kept as the freeze line) AND
  n ≥ 100 (the population stays the certified window's; a variant that
  strangulates the sample fails outright).
- **G2 (V2):** all G1 conditions at r=1.0 AND stop-hit rate does not rise by
  more than +5 percentage points over the control's 54.4% (62/114 losses) —
  the intra-bar-noise prediction must NOT materialize beyond noise.
  Pre-declared expectation: V2 FAILS here (median intra-bar range 0.541R ≥ the
  scaled stop). If it unexpectedly passes, V2 beats V1 on DD and proceeds.
- **G3 (winner):** the surviving variant goes forward ONLY as a pre-registered
  hypothesis doc (stated so it can lose) → fresh-window certified run → arm-C
  paper test under the frozen adjudication rule with the account at the
  recomputed floor for THAT variant. No direct-to-live path exists.
- **Materiality bar (both variants):** the variant does not create edge — it
  re-prices scale. If the variant's mean R/t on the window is worse than the
  control's +0.0383 by more than 0.02R/t, the variant is DEAD regardless of
  survivability (a survivable strategy with worse expectancy is still a loser).

## 4. Pre-declared outcome mapping

- V1 passes G1+G3 → V1 is the scale candidate; V2 runs anyway for the record
  (its G2 result is the intra-bar-noise hypothesis's test).
- V2 passes G2+G3 and V1 fails → V2 proceeds (would imply the noise prediction
  wrong — itself a finding).
- Both fail → the honest answer to the amendment's question is **NO at $150**;
  the checklist's live-authorization floor for this geometry becomes
  ≈$226+ at 10%-risk (≈$138 static) or ≈$1,446 at 1%-risk, and arm C stays a
  collection-only regime exercise until funding or geometry changes through
  the chain.

## 5. Status

Registered 2026-09-15. Not yet executed — runs must use the pinned harness and
append results + verdicts below (append-only), with artifacts under
`artifacts/v75_replay/` and a changelog entry per the house style.

---

## 6. Results — executed 2026-09-15 on the pinned harness (append-only)

**Harness amendment (declared before the runs, in service of G0):** the pinned
harness had no risk-input lever (`risk_money = eq * 0.005` hardcoded).
`--risk-frac` was added with default 0.005 — the certified path stays
byte-identical, proven by G0 below. No other harness change.

**G0 control — PASS (exact reproduction).** `cert_report_vsg_g0_control.json`:
n=114, total +4.37R (mean +0.0383R/t), win rate 45.6, funnel identical to the
baseline of record (score 2727, spread-gate 10, risk-cap 0, paused 1002,
auto-disable 45), worst streak 6, loss rate 62/114 = 54.4% (the G2 reference).
Harness pin holds under the `risk_frac` addition.

**V1 (risk 10%, geometry unchanged, E=$150) — FAIL G1.**
`cert_report_vsg_v1_r10.json`: n=114 (unchanged sequence), total +4.37R,
**0 refusals** (risk-cap 0; max risk exactly 10.0% — even the max-sd fill
1058 pts = $15.75 min-lot risk sits under the $30 cap), materiality bar
trivially clean (identical trades → identical mean R/t). But
**max_drawdown_pct = 52.1% > the frozen 45% line.** The §1 projection (31.0%)
was wrong and the pre-registered rule is right: the projection modeled dollar
losses through the k-band; the harness applies the engine's real money chain
— 0.75^consec volume scaling compounds multiplicatively (0.9^6 ≈ 0.53 through
a 6-loss streak), and V1's admission makes the scale-down lever moot until
well after the streak. Survivability ≠ admission. **V1 is DEAD at $150 under
G1 as frozen.**

**V2 (stop-scaling grid, risk unchanged 0.5%) — ALL FAIL; the noise
prediction is CONFIRMED.**

| s* | n | totalR | meanR | WR | DD% | worst streak | vs gates |
|---|---|---|---|---|---|---|---|
| 1/3 | 80 | −10.60 | −0.1325 | 37.5 | 16.7 | 5 | G2 FAIL (hit-rate +8.1pp), materiality FAIL (−0.171R/t) |
| 0.5 | 131 | −13.01 | −0.0993 | 42.7 | 34.2 | 12 | G2 pass (+2.9pp ≤ +5pp) but materiality FAIL (−0.138R/t) |
| 2/3 | 133 | −12.63 | −0.0950 | 45.9 | 50.2 | 7 | G1 FAIL (DD 50.2% > 45%), materiality FAIL (−0.133R/t) |

The pre-declared trap fired exactly as written: scaling the stop into the
intra-bar noise band (median intra-bar range 0.541R) converts ordinary noise
into stop-outs. Every s* point turns the +0.038R/t control decisively negative
(−0.10 to −0.13R/t) — the stop-hit rate rises only modestly at s*=0.5, but the
R lost per hit and the trade mix shift do the killing. n also drifts (80–133
vs 114) because pause/auto-disable cadence moves with geometry — noted, and
itself a reason G0 pins the control. **V2 is DEAD across the whole frozen
grid.**

**Verdict: the §4 outcome mapping's NO-at-$150 branch fires.** No risk input
or stop sizing in the frozen answer space makes $150 viable at DD ≤ 45% with
non-degraded expectancy. Consequences, per §4:

- The checklist's live-authorization floor for the current geometry stands at
  **≈$226 (10%-risk static admission) / ≈$1,446 (1%-risk)** — and the V1
  result adds a sharper warning: 10%-risk at $226–308 must be expected to eat
  a ~50% drawdown through its own certified streak; the DD line, not refusal,
  is the binding constraint in the percentage regime.
- Arm C remains a collection-only regime exercise until funding or geometry
  changes through the chain. The frozen adjudication rule (incl. G5) applies
  unchanged whenever a future candidate clears a study — but no candidate
  exists at $150 under this study's answer space.
- V1's failure mode (multiplicative DD, not strangulation) is recorded for any
  future scale study: the strangulation floor answers *admission*; a separate
  DD-survivability bound governs the percentage regime. Any future study must
  freeze BOTH from the start.

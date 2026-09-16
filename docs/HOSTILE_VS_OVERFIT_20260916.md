# HOSTILE-REGIME vs OVERFIT STUDY — frozen 2026-09-16, before the feature/anatomy runs

**The open question of the program** (TRAINING_PROTOCOL §caveat, sprint,
Amendment C, tuning): every 2026-06-01→09-02 out-of-sample window failed on
every symbol and every config — including configs that printed +10 to +20R
in-sample. Two explanations remain, and this study is designed to separate
them **with discriminating evidence, not vibes**:

- **H1 — HOSTILE REGIME:** Jun–Sep 2026 is an objectively unusual market
  state (measured on price alone, no trades involved) that breaks the
  family's thesis. Prediction: the window's regime features are extreme
  vs the corpus's own history, the losing trades cluster exactly where the
  extreme feature says, a directionless benchmark also degrades, and the
  same calendar window inverts V100 (whose config never saw V75 data).
- **H2 — OVERFIT:** the configs are fit to their in-sample windows; the OOS
  window is ordinary. Prediction: the window's features sit inside
  historical norms, losses are diffuse rather than clustered on one
  mechanism, the benchmark shows no degradation, and V100 holds up.

Honesty note: the autopsy already established a V-shaped bull recovery in
Jun–Sep. This study does NOT get credit for "discovering" it; it tests
whether that shape is **statistically extreme by the corpus's own 417-day
history** and whether the damage pattern matches it.

## 1. Pre-declared primary regime features (computed on price only)

Computed for EVERY 92-day window end-date in the 417-day corpus (rolling),
plus the fixed IS/OOS partitions. Primary four:

1. **R90** — 90-day log return (trend persistence/squeeze measure).
2. **PC20** — pullback-continuation index: of all EMA20-touches (M15 close
   within 0.35×ATR of EMA20 in a stack-aligned direction), the fraction
   whose next 8 bars continue ≥ +0.5×ATR in the stack direction. This is
   the family's thesis as a market property — zero parameters from any
   candidate.
3. **VOLR** — realized M15 volatility (last 30d) ÷ trailing 12m median.
4. **TREND_DAYS** — fraction of days with |daily return| > 2× daily vol
   (trend-day fraction).

Secondary (recorded, not verdict-bearing): mean |H1 EMA100 24h slope|
normalized by ATR (the HTF-SLOPE gate's feature), gap frequency.

**Extremity rule:** a feature is EXTREME if the Jun–Sep value exceeds the
95th percentile of all rolling 92-day values in the corpus. NORM if < 75th.

## 2. Anatomy across all of today's runs (discriminating)

- **Trade-level correlation:** monthly totalR correlation across the
  shipped / rebuilt / gated configs on the shared window. R ≈ +0.8+ →
  common regime driver; near-zero → config-specific.
- **Loser decomposition (fresh batch, per-trade):** shipped + rebuilt +
  gated, IS and OOS, full trade rows. Split OOS losers by month, direction,
  leg, regime label, and the sign of the counter-move that killed them.
  H1 requires the losses to concentrate in the mechanism the extreme
  feature names (e.g., counter-trend SELLs during the squeeze leg).
- **Overfit signature (independent of any regime claim):** rank correlation
  between IS totalR and OOS totalR across all of today's configs
  (training stage-1 subset with recorded OOS + sprint finalists + tuning
  finalists). Strongly NEGATIVE = the more a config was optimized for IS,
  the worse its OOS — the classic overfit gradient. Near-zero = window
  effect dominates.

## 3. Benchmarks

- **Random-entry control (frozen):** 200 shuffled-direction trades evenly
  spread over each window (IS and OOS), same spread/geometry cost model
  (entry→exit after 8 bars, ±). No parameters. H1 predicts the control's
  OOS/IS performance ratio ≪ 1 (a hostile window punishes everyone);
  H2 predicts ratio ≈ 1 (only the family's edge died, not the window).
- **Cross-symbol simultaneity:** V100 rebuilt entry (AMENDMENT_C_V100 +
  CROSS_SYMBOL_SCAN_v100): its OOS is the SAME calendar Jun–Sep window on
  an independent instrument whose config never saw V75. If V100's gross
  signal dies in the same calendar window, a shared regime state is
  implicated (H1); if it holds, the failure is V75-config-specific (H2).

## 4. Verdict mapping (frozen BEFORE the runs)

- **HOSTILE-REGIME** if (≥2 of 4 primary features EXTREME) AND anatomy
  clustering matches the named mechanism.
- **OVERFIT** if (≤0 primary features EXTREME) OR losses are diffuse.
- **MIXED (weighted)** if the discriminators split — report each test's
  result individually with its weight; do NOT average them into a false
  single label. Expected honest outcome space includes: "regime extreme
  AND tuning amplified exposure to it" — which convicts both, and names
  the fix (participation gates must key on the feature that was extreme).
- Consequence of HOSTILE-REGIME: participation-gate design (v2) gets a
  concrete target feature. Consequence of OVERFIT: the tuning program's
  remaining search budget is cut and forward data becomes the only judge
  (already the standing state via arm D).

Artifacts: `artifacts/train/REGIME_FEATURES.json`,
`HOSTILE_VS_OVERFIT_TRADES.json`, `HOSTILE_VS_OVERFIT_RESULTS.json`.
Verdict rows are appended to this file after the runs. No engine, preset,
or standing config changes from this study.

## 5. Results (2026-09-16, after the runs)

### 5.1 Feature extremity (OOS vs all rolling 92d windows, n≈46)

| feature | OOS value | percentile | call |
|---|---|---|---|
| R90 | +0.535 log (~+70% 90d) | **95.7** | **EXTREME** |
| PC20 | 0.647 | 78.7 | MIDDLE |
| VOLR | 1.03 | 61.7 | NORM |
| TREND_DAYS | 0.043 | 21.3 | NORM |

The window is a **historic one-way squeeze** — the largest 90-day advance in
417 days — but volatility is ordinary and the pullback thesis itself still
functioned (PC20 above its own median).

### 5.2 Anatomy (8 runs re-generated; all recorded rows reproduced exactly)

- Monthly-R correlation across configs: shipped|legacy24 **0.985**,
  shipped|rebuilt 0.69, rebuilt|gated **−0.15** — a dominant common driver
  for the shipped family, none between rebuilt and gated.
- Losers cluster on ONE mechanism in every config: **BUYs into the squeeze**
  (shipped: BUY −47.4R vs SELL −16.1R; bull-labeled trades −45.3R). June is
  the worst month everywhere (shipped −32.1R).
- **IS→OOS gradient (Spearman, n=8): −0.714.** The more in-sample R a config
  printed, the worse its OOS — the +20R tuning finalists died hardest
  (−6.87R each). The classic overfit gradient.

### 5.3 Benchmarks

- **Random-entry control:** IS +12.21R vs OOS +13.26R (ratio **1.086**) — a
  directionless participant with the same cost model did fine in BOTH
  windows. The window did not punish participation per se.
- **Cross-symbol simultaneity (V100, rebuilt entry, true spec):** IS +9.40R
  (n=79) → **OOS +1.46R (n=39, DD 10%) — POSITIVE in the same calendar
  window**. The same pullback thesis, on an instrument whose config never
  saw V75 data, survived Jun–Sep 2026.

## 6. Verdict (per the frozen §4 mapping)

**MIXED — weighted toward CONFIG-SPECIFIC FRAGILITY (overfit), with the
regime extreme only in trend magnitude.** The frozen HOSTILE bar (≥2 of 4
features EXTREME) is NOT met (1 of 4); both benchmarks and the gradient
point at the configs, not the calendar.

**The mechanism, stated once:** the regime supplied the traps (a relentless
one-way advance that keeps baiting pullback entries and then removing them
via the counter-move stop); the overfit supplied the maximum exposure to
those traps, in exact proportion to in-sample optimization. Evidence that
the trap was escapable: the gated candidate (+1.53R OOS) and the same
thesis on V100 (+1.46R OOS) both came out positive inside the window.

**Consequences:** (1) participation-gate v2 keys on the one genuinely
extreme feature (R90-type squeeze magnitude) — pre-register before use;
(2) the tuning program's search budget stays cut — arm D's forward window
remains the only clean judge (standing state, docs/ARM_D_FORWARD_TEST.md).

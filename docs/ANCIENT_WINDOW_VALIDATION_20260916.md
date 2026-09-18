# ANCIENT-WINDOW VALIDATION — pre-registered 2026-09-16, before data collection

**Question:** every backtest window in the repo (2025-07-26 → 2026-09-03) has been
consumed or discredited by exposure (training, sprint, autopsy, tuning; IS→OOS
gradient −0.714). The broker serves **native H1 back to 2023-11-06** and M15 back
to **2025-04-13**. The window **2025-04-20 → 2025-07-26** (~97 days) predates the
entire optimization program and has never been loaded by any study. This is the
last truly independent historical test that can exist for this strategy family.

**What this is NOT:** a tuning exercise. No search, no variants beyond the three
frozen configs below. The forward test (arm D) remains the only clean judge for
anything post-2026-09-03; this window only tests whether the family generalizes
to history it has never seen.

## Frozen design

**Data (collected AFTER this freeze, once):**
- M15 from broker `Volatility 75 (1s) Index`, earliest served (2025-04-13) → 2025-07-26.
- H1 native from broker, 2024-12-01 → 2025-07-26 (≥ 3 months warm-up for the
  H1 EMA100 slope, matching fresh90's warm-up generosity).
- Provenance gates (pre-committed, mechanical):
  - D1: bar count vs calendar — a 24/7 symbol should yield ~96 bars/day; if any
    calendar day has < 48 bars the window is flagged DATA-GAP and reported.
  - D2: continuity — no M15 gap > 1 bar inside 2025-04-20 → 2025-07-26 without
    a same-day flag.
  - If either gate fails, results still run but the verdict is capped at
    INFORMATIVE-NOT-DECISIVE regardless of numbers.

**Configs (fixed, no search — identical to their canonical definitions):**
1. `shipped` — TP 1.8, module-default PB band (0.30–2.20), MR on, EMA-side off,
   gates off. (Deployed-production analogue.)
2. `rebuilt` — TP 1.6, PB band 0.60–0.70, EMA-side veto ON, MR off, BF off.
3. `gated` — rebuilt + HTF-SLOPE ON + NO-MOM ON. **The candidate under test.**

Window: start 2025-04-20 00:00 (7 M15 days burn-in inside the dataset), end
2025-07-26 00:00 exclusive. Costs: module defaults (spread 18.5 pts, spread-gate
0.18, USD-per-unit 1.009) — the certified harness's own constants, unchanged.

**Verdict gates (mechanical, no discretion):** for each config, PASS iff
- n ≥ 30, AND
- totalR > 0, AND
- max drawdown ≤ 25%, AND
- meanR ≥ +0.05R/trade.

- `gated` PASS → the family has historical generality: candidate graduates with
  a second independent window on its side (forward test still governs live).
- `gated` FAIL but `shipped`/`rebuilt` PASS → gates are regime-specific: candidate
  stays forward-only, note recorded.
- ALL FAIL → the edge is epoch-specific to the trained era: the only remaining
  path to live is arm D's forward accrual, unchanged. NO backtest-derived
  re-parameterization is authorized by any outcome of this study.

**Honesty pre-commitments:** all three configs run in one batch, same process
settings, results appended to this doc verbatim (including failures); the JSON
artifact is written before interpretation; no re-run with different flags after
seeing numbers.

## Results

(appended after execution)

## Results (executed 2026-09-16, one batch, verbatim)

Provenance: M15 9312/9312 expected bars, zero days <48 bars (D1 PASS), zero gaps
(D2 PASS); H1 2328/2328 bars, zero gaps. Data: broker-native
`Volatility 75 (1s) Index`, M15 from 2025-03-23, H1 from 2024-11-18.

| config | n | totalR | meanR | DD | gates | verdict |
|---|---|---|---|---|---|---|
| shipped (TP 1.8, MR on) | 32 | −10.09R | −0.315 | 5.0% | totalR, meanR FAIL | FAIL |
| rebuilt (no gates) | 1 | −0.67R | −0.670 | 0.3% | n, totalR, meanR FAIL | FAIL |
| gated (candidate) | 1 | −0.67R | −0.670 | 0.3% | n, totalR, meanR FAIL | FAIL |

**Frozen mapping outcome: ALL FAIL → the family's edge is epoch-specific to the
trained era (2025-07 → 2026-07). No backtest-derived re-parameterization is
authorized by this outcome. The only path to live remains arm D's forward
accrual under docs/ARM_D_FORWARD_TEST.md.**

### Anatomy (from the gated run's own funnel, not interpretation)

`score 9225 → spread-gate 41 → no-mom 21 → 1 trade`. The rebuilt entry's PB band
(0.60–0.70 ATR) and MOM-leg combinations almost never form in this era: the
starvation is the strategy family declining to participate, not a data defect.

### Post-hoc observations (labeled POST-HOC — collected AFTER the verdict, no runs)

1. The ancient window is itself a historic one-way squeeze: V75(1s) rose
   3273.7 → 7239.1 inside the window (**+121%**), with lower absolute vol
   (mean H-L ~32 pts vs ~40 pts in Jun–Sep 2026). The same one-way-grind
   signature that the hostile-vs-overfit study identified (R90 p95.7) also
   defines 2025-04→07. Two independent eras, same signature, same failure mode
   (trapped pullbacks / non-participation). This *strengthens* the mechanism
   claim and sharpens participation-gate v2's pre-registrable target: an
   R90-magnitude filter, not hours or regime labels.
2. The shipped config DID participate (n=32) and lost −10.09R — consistent with
   the trap mechanism rather than with non-participation.

Artifact: `artifacts/ANCIENT_WINDOW_RESULTS.json` (written before interpretation).

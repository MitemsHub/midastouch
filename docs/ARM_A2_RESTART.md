# ARM A2 RESTART — REVERSE_BOTH tp2.0 AT A $1,000 VIRTUAL BASIS

**STATUS: AUTHORIZED (user decision, 2026-09-16). NOTHING RUNS YET.** The
restart executes only after the forward build passes the §3 parity gate.
Written BEFORE any A2 forward data exists, in the arm-D discipline: the
gates below are frozen now and are the only rulebook. After start,
amendments are append-only and dated.

## 0. What this is and why it supersedes arm E

Arm A (pullback kernel, TP×1.8, $50 basis) accrued 14 forward trades:
**−4.16R, 36% win, 55% drawdown, virtual equity $50 → $30.73**. Its final
state is structural, not unlucky: the observed min-lot candidate risk
($4.64–$6.10) exceeds the 15% account-budget cap ($4.61) at that equity, and
the crossover equity for the cheapest observed candidate is **$30.93**. Arm A
is below it. It can never trade again at its config. It is repurposed, not
rescued.

Arm E (`ARM_E_TP20_FORWARD_PROPOSAL`) was pre-drafted to forward-test the
same candidate — V28 REVERSE_BOTH sl2.0/tp2.0/h180/r1% — but behind a start
gate (arm D adjudicates first, 7–15 months at observed rates). **That gate
is hereby amended away**: the program's only supported positive finding
(family p = 0.0000 in-regime; OOS sign positive at +0.225R on the single
pre-authorized shot) should not wait a year behind a window while the family
the paper arms actually prove is bleeding (A+B: −6.2R over 24 trades, DDs
over 40%). Arm E's build contract, parity harness, and verifier pins carry
over to A2 **unchanged in content** — only the arm identity changes. Arm E
is marked SUPERSEDED in its own doc (append-only), never deleted: its
frozen-gates design is the template this restart follows.

## 1. Why the basis changes ($50 → $1,000), stated so it cannot be misread

At $50 virtual, one minimum lot risks ~10% of the book — the risk plumbing
self-vetoes and no trade can physically pass the guard tree (the
strangulation computed above). At $1,000, min-lot risk ≈ 0.5% and the
account-budget guard functions as designed for the first time in the
program's forward arms. **The $1,000 number is an accounting unit, not
capital**: every statistic this program publishes stays R-denominated from
the ledger's CLOSE rows (basis-independent by construction), dollar
conclusions still go through the strangulation-floor machinery, and no real
funds are touched (paper-only stays hard-false-locked). What the basis
changes is only this: trades become possible.

## 2. What runs (pins frozen now)

- **Candidate**: V28 REVERSE_BOTH, `InpStrategyMode=3`, sl 2.0 / tp 2.0 /
  hold 180 min / risk 1% — the §3 surface of the superseded arm-E proposal,
  byte-identical to the parity harness's pins.
- **Build**: the forward v28 build (v28 strategy core + v26.40 paper-arm
  module). The parity harness (`scripts/build_parity.py`) runs unchanged;
  the A2 preset inherits `MitemshubAI_VOL75_ARM_E.set`'s keys with
  `InpMagic=7788100` (arm A's fleet slot, so the fleet guard and every
  existing inventory keeps working) and `InpArmTag=A2` (fresh ledger
  `MitemshubAI_paper_Volatility_75_Index_A2.csv`, fresh clock).
- **Floor-mode policy (amended 2026-09-16, pre-data)**: the engine's
  strangulation-zone contract is frozen in the build and pinned in the
  preset — `InpMaxTotalRiskPct=15.0` (now explicit), `InpFloorModeMaxDDPct=30.0`,
  `InpFloorModeConviction=true`. When a broker floor ever exceeds the strategy
  fraction, the paper engine takes the minimum lot only if (1) virtual equity
  is above the hard floor (30% below window start — breach = loud halt, and
  restart is a structural abort on a fresh ledger) and (2) the signal carries
  the strong BB+RSI conviction bar — then the account-budget guard applies as
  always. Layer 2 (amended 2026-09-16, protocol §10.7): every floor-mode
  evaluation also consults the frozen P(win) bucket table
  (`MitemshubAI_filter_table_A2.csv`, bucket-side-tod-v0) — a FILTER CONSULT
  print and FCONSULT ledger row accrue the ML evidence base from day one. The
  shipped table is ACTIVATION=PASSIVE: it can never veto (veto authority
  requires a five-leg gate on fresh re-run data, certified by
  `signal_filter_table.py --certify`; recon says today's evidence fails 4 of
  5 legs). At A2's $1,000 basis floor mode never activates; the policy exists
  so the account can trade at ANY balance, never silently. Parity re-run
  post-amendment: PASS (n=27, max |dR|=0.0063) — the tester path is untouched.
- **Host**: the dedicated paper terminal (49E0), arm A's chart slot,
  M15, 24/7 session. Arm B (TP×2.4 pullback pair) is untouched — the A/B
  pair's record stays on disk as the pullback family's forward evidence.
- **Hard preconditions, in order**: (1) forward build compiles and passes
  parity (PASS verdict, artifact receipt); (2) arm A's ledger archived to
  `artifacts/paper_ledgers/` with its final row intact; (3) preset verifier
  PASS with the A2 pins; (4) init banner datetime recorded here.

## 3. Verdict rule (frozen BEFORE any data exists — arm-D rulebook verbatim)

Read monthly. With **n** = post-era closed trades:

| verdict | condition |
|---|---|
| **VALIDATED** | n ≥ 60 AND totalR > 0 AND max drawdown ≤ 25% AND meanR ≥ 0.05 |
| **CONTINUE-UNPROVEN** | n < 60, or the gray zones (positive R, calm DD, meanR in (0, 0.05); or DD in (25%, 30%] with positive R) |
| **REJECTED** | n ≥ 60 AND (totalR < 0 OR drawdown > 30% OR meanR ≤ 0) |

- VALIDATED advances the candidate to the pre-registered live-sizing path
  with the thin-sample disclosure attached (the spent OOS row's n=12 caveat
  rides along until this window resolves).
- REJECTED retires REVERSE_BOTH with a data-backed negative and closes this
  program's forward line — no re-tuning against the window, ever.
- **Structural aborts (any time, restart the clock on a fresh ledger)**:
  ledger integrity problems, input drift from §2's pins (verifier must stay
  clean), or a loaded-but-dead engine signature. The strangulation lesson is
  now a standing abort: if the budget guard's effective cap falls below the
  observed min-lot risk for 14 consecutive days, that is a structural abort,
  not a pause.
- **Expected duration**: the family's tester rates are ~0.13–0.30
  trades/day; at a $1,000 basis nothing in the guard tree suppresses them.
  n ≥ 60 needs roughly **7–15 months** — but the clock starts when the
  build lands, not after another arm adjudicates, and unlike arm A this arm
  can actually trade from day one.

## 4. Honesty register (what this restart does NOT claim)

- The candidate's evidence is **selection-tainted held-window data plus one
  thin OOS sign**. A2 exists to earn the only evidence it never had.
- The pullback family's forward losses (A/B) are **not** evidence against
  REVERSE_BOTH (different signal path), but they ARE the program's base rate
  for " tester edge → forward result", and it is 0 for 2. A2 is the third
  attempt, not the coronation.
- The 55%/41% forward drawdowns at $50 are partly basis artifacts (10%
  risk/trade); A2's DD stats at 0.5%/trade are the first forward DD numbers
  this program will read at a sane risk scale.

## 5. Start-day execution record

| gate | status | receipt |
|---|---|---|
| 1. forward build parity PASS | **SATISFIED 2026-09-16** | `artifacts/v28_research/armE_parity_20260916_181219Z.json` — research `[v28.00]` vs forward `[v28.10]`, wf window, n=27 aligned in order, max \|dR\|=0.0063 ≤ 0.02, totalR +3.0280 vs +3.0293 (\|d\|=0.0013 ≤ 0.05), input pins verified from both reports |
| 2. arm-A ledger archived | **SATISFIED 2026-09-16** | `artifacts/paper_ledgers/MitemshubAI_paper_Volatility_75_Index__armA_final_20260916.csv` — 43 rows, sha256 `393c0830…` matches the FB9A source byte-for-byte, final row is the v26.39 era marker. **EA stopped the same day**: FB9A was already shut down (its last EA journal write was 17:47, before this operation), and arm A's expert block was removed from FB9A's Default profile `chart01.chr` (verified: 0 experts on chart01; arm C's expert on chart03 untouched, magic 7788125). Pre-edit chart backup: `artifacts/paper_ledgers/armA_FB9A_chart01_chr_backup_20260916.chr` (sha256 `4ced7443…`). FB9A stays down; the A2 chart slot is 49E0's spare chart (Vol75, EA-less) — attaching A2 there needs no FB9A action |
| 3. preset verifier PASS (A2 pins) | **SATISFIED 2026-09-16** | `GO-LIVE ARTIFACTS: PASS` with A2 checks live (preset pins, parity-pin equality, registry pre-start state) |
| 4. init banner datetime | **DONE — 2026-09-16 21:15:32 (terminal-local)** | attached autonomously via profile splice (chart01.chr expert block from the verifier-pinned preset; pre-edit backup `chart01.chr.pre_A2_20260916.bak`). Banner on the 49E0 Experts log: `[v28.10] MITEMSHUB V75 MACRO started | mode=3 | experiment=ARM_A2_REVERSE_BOTH_TP20 | gate=M30 | macro=H4+H1 EMA20 | trigger=M30 BB20/2 or RSI14 | risk=1.00%` — PAPER resume $1000.00 from the fresh A2 ledger (era stamp 28.10), FILTER TABLE banner: buckets=8 global=0.565 ACTIVATION=ABSENT (consult-only: never vetoes). Arm D resumed normally on chart02. |

Build provenance: forward build `MitemshubAI_v28_fwd.mq5` (APP_VERSION 28.10)
= v28 strategy core verbatim + v26.40 paper module ported (virtual equity,
per-tick hard SL/TP mirror, tagged ledger, fleet-mirror guard, floor-mode
sizing) + the `Trade R:` per-close parity line. Compiled clean (0 errors,
0 warnings); parity harness also validated its own evidence layer against
the live journals (sign-bearing `Trade R:` lines, CLOSE-R fallback for the
research build, tag-addressed segments, flush-lag retry).

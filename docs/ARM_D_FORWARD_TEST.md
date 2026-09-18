# ARM D FORWARD TEST — pre-registered adjudication (frozen 2026-09-16)

**Written BEFORE arm D's first trade (ledger holds only the ERA row).** This
document is the only rulebook by which arm D's forward window is judged.
Amendments are append-only and dated. Arm D accrues the **independent
out-of-sample window** that no backtest in the repo can provide — every
backtest window we hold has been consumed or disqualified by exposure
(TRAINING_PROTOCOL 2026-09-15, SPRINT_ENTRY_REDESIGN 2026-09-15,
OOS_AUTOPSY 2026-09-15, V75LOW_H1_TUNING 2026-09-15).

## 1. What runs

The **gated candidate** — the only config in this program's history to pass
every frozen in-sample bar and the OOS gate matrix
(docs/OOS_AUTOPSY_20260915.md §4, "BOTH" primary):

- Kernel: trend-side pullback, PB band **0.60–0.70 × ATR**, EMA-side veto ON,
  TP **1.6R**, stop 1.7×ATR widened to the 5-bar extreme (engine-standard).
- Exits: BE at +1R, PLOCK 0.5R, trail from +1R at 0.7R, TIME 20 bars.
- Gates: **InpNoMomGate=true** (MOM-leg combos vetoed) and
  **InpHtfSlopeGate=true** (PB entries vetoed against the 24h slope of the
  H1 EMA100), applied post-decision exactly like the lab.
- MR / BF / BO legs OFF; v30 self-correct OFF (no lab counterpart).
- Governor: spread gate 0.18, conviction throttle ON, cooldown 3 bars with
  win-rearm, consec-loss pause 3 — all harness-modelled, left ON for parity.

Deployed as **MitemshubAI v26.40** (compile 0/0, deploy-manifest pin
`6459f3ad…`), magic **7788150**, `InpArmTag=D`, paper-only
(`InpLiveExecution=false`), virtual equity $50, 24/7 session, on the
dedicated paper terminal (49E0, install `MitemshubMT5_B`), chart
`Default/chart03` (Volatility 75 Index, M15), first init banner
2026-09-16 00:38:04 local. Files: `MitemshubAI_paper_Volatility_75_Index_D.csv`
+ `_D.jsonl` (v26.40 `InpArmTag` suffixes all output). The terminal's tick
recorder stays owned by arm B; arm D records no ticks.

Backtest reference points (NOT evidence, context only): IS +12.74R (n=116,
DD 11.3%), OOS +1.53R (n=25, DD 3.8%) — with the recorded circularity caveat
that NO-MOM was designed from that same OOS window.

## 2. Hypothesis under test

The gated candidate's positive expectancy persists in an unpolluted window:
**post-era closed trades accrue positive totalR with bounded drawdown under
per-tick paper fills on live V75 ticks.**

Statistics are R-denominated from the tagged ledger (CLOSE rows), post-era
rows only (arm D is per-tick by construction; the ERA stamp is 26.40).

## 3. Verdict rule (frozen BEFORE any data exists)

Read monthly (first reading **2026-10-01**); weekly `morning_status` glances
are ops, never judgment. With **n** = post-era closed trades:

| verdict | condition |
|---|---|
| **VALIDATED** | n ≥ 60 AND totalR > 0 AND max drawdown ≤ 25% AND meanR ≥ 0.05 |
| **CONTINUE-UNPROVEN** | n < 60, or stats in the gray zone — keep collecting, no action |
| **REJECTED** | n ≥ 60 AND (totalR < 0 OR drawdown > 30% OR meanR ≤ 0) |

- **VALIDATED** advances the candidate to the pre-registered live-sizing path
  (GO_LIVE_CHECKLIST arm-C-style truth table + dynamic strangulation floor +
  the candidate's own adjudication branch). It does NOT authorize live orders
  by itself.
- **REJECTED** parks arm D and retires the candidate with a data-backed
  negative. The forward window is then closed forever as a fitting target:
  no re-tuning against it, no gate re-design from it — that would destroy
  the independence that is this arm's entire purpose.
- **Structural aborts (any time, restart the clock):** ledger integrity
  problems flagged by `morning_status`, a loaded-but-dead engine signature,
  or input drift from the frozen pins (`verify_arm_d_preset` must stay
  clean). After a structural fix, arm D restarts on a FRESH ledger file and
  the window re-accrues from zero — a polluted window is never judged.

## 4. Multiplicity and scope honesty

- This is ONE pre-registered forward test of ONE candidate. No interim
  parameter changes, no peeking-driven design edits, no second candidate on
  this window.
- Arms A/B/C are NOT inputs to this adjudication — they run their own
  pre-registered purposes (A/B gate clock, arm C collection).
- Basis honesty: at $50 virtual equity the min-lot stop-risk is ~$5.03
  (≈10.1% per trade, TOLERATED inside the 20% cap — v26.40 fit telemetry).
  R-denominated statistics are unaffected by the account basis; dollar
  conclusions at larger bases go through the strangulation-floor machinery,
  never through arm D's $50 book.

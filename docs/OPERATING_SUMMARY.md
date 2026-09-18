# OPERATING SUMMARY — post-study, 2026-09-05

**State in one line:** sound machinery, every research question closed by a
frozen protocol, zero VALIDATED-CANDIDATE configs, paper gate at 0/30 closed
trades (clock starts at first fill) — and one decision tree that decides
everything from here: the gate outcome.

---

## 1. Questions closed by protocol (no open research debt)

| # | Question | Verdict | Evidence |
|---|---|---|---|
| 1 | Is the engine arithmetic honest? | **Cost-inclusive re-baseline** — fills pay the 18.5-unit spread; old engine reproduced bit-identically | `*_check0905.json`, legacy == stored (135 trades), net re-baselines exact |
| 2 | Is there directional information in tick data? | **NO** — generator is a memoryless 0.5 Hz step machine; variance ratios inside null bands at every horizon | `docs/GENERATOR_FINGERPRINT.md` |
| 3 | Does the regime axis predict direction? | **NO** — zero causal separation (drift tracker), z-gate forms died on validation | `docs/DRIFT_SIGMA_TRACKER.md`, `docs/Z_GATE_PROTOCOL.md` |
| 4 | Lone momentum as a standalone? | **REJECT** — duel lost on fresh data | `docs/MOM_STANDALONE_DUEL.md` |
| 5 | V100 as a second instrument? | **NOT CERTIFIED** — gross edge dies under true specs + true cost; "personality flip" was a fictional 0.01-lot grid | `docs/V100_NET_EDGE_STUDY.md` |
| 6 | Wider-stop / lower-frequency geometry on V75? | **NO-ADOPT 5/5** — cost-dilution dead; deployed config remains the best known V75 geometry | `docs/V75_COST_DILUTION_STUDY.md` (commit `21fd55d`) |
| 7 | Broker-side spread lever? | **DEAD on Deriv MT5** — spread is flat 16.96 median every hour (2.46M ticks); raw == standard (18.5 is lake p99); zero-spread account cannot beat raw on synthetics. Deliverable: pricing slope **+0.0022R/t per unit** | `docs/V75_SPREAD_TIER_STUDY.md` (commit `1c8c08e`) |
| 7b | Does the family have an edge on other broker symbols? | **SCAN 2026-09-15: NO-EDGE on both.** V100 (2y, true spec, rebuilt entry): rebuilt shows gross signal (+9.4R, WR 51.9%) but 1.0-lot floor at $300 → DD 49.5% — untradeable at small scale, re-confirming Q5. V75 (1s) Index: collected live 2026-09-15 (96,055 M15 bars, ~2.9y); ALL configs deeply negative (shipped −58.2R/377t; rebuilt −18 to −26R); spread = 5.6% of stop distance vs 2.2% on the 1-tick V75 (2.6× relative toll) — structurally untradeable at M15 | `docs/CROSS_SYMBOL_SCAN_20260915.md`, `artifacts/train/CROSS_SYMBOL_SCAN_*.json` |
| 8 | Is the EA itself sound? | **Audited** — 4 bugs fixed (paper-equity guard, out-of-range slots fail closed, magic, banner); 0-error compile; 15/15 presets | `docs/FULL_EA_AUDIT_v2635.md`, milestone `8d155fe` |
| 9 | Is the data path sound? | **Drilled** — synthetic wire-format ledgers through adjudicator + reconciler, 10/10; caught 2 real bugs (OPEN-epoch pairing, zero-pairs crash) | `scripts/first_trade_drill.py`, commit `db7e2fc` |
| 10 | Would arm C start fast? | **PROVEN** — activation ≈ 1 minute (authorized T+6s, banner T+8s), parked by protocol | `docs/ARM_C_TEMPLATE.md`, commit `333473f` |
| 11 | Can a regime filter stand the engine aside in hostile 2026? | **REJECTED** — no entry-regime separation: per-trade abs(rho) ≤ 0.05 (perm p ≥ 0.67) on atr_z/adx/slope; train-fit filters invert or no-op out-of-sample; the walkforward warning stands as the operative 2026 risk. Not protocol-frozen — closes these four features only | `artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt` (2026-09-14) |

Nothing above can be reopened by vibes: each carries a frozen protocol, an
artifact, and a commit. The discipline going forward is to add rows here, not
to re-litigate them. The one sanctioned reopening path is pre-registered in
`docs/V75_RECERT_PROTOCOL.md` (2026-09-14): forward-only fresh-window
collection with frozen statistical gates, for the long-only pullback-buy
config after the walkforward inversion.

## 2. The one open gate (pre-registered 2026-09-04, do not move the goalposts)

Paper arms A (TP 1.8, magic 7788075) and B (TP 2.4, magic 7788100) each run
its own MT5 terminal. **2026-09-14: arm B moved to the dedicated ARMS terminal
(`MitemshubMT5_C` install, data folder 71BF) — that terminal is reserved for
paper collection and tester/research sessions must never close it; its old
host 49E0 (`MitemshubMT5_B`) is tester/reserve-only and carries no arm —
since 2026-09-15 it is also the sanctioned **WIP staging terminal**: a
candidate build proves telemetry-liveness there (`check_wip_liveness.py
--collect`) before `-AllowWip` may deploy it anywhere.**
**Live trading is authorized only when ALL of these hold:**

| Gate leg | Rule | Auto-fires |
|---|---|---|
| **TJ1 — paper A/B adjudication** | ≥30 closed arm-A trades AND arm-A net expectancy positive AND paired verdict (|t| ≥ 1.0 on paired mean R delta A−B, sign matches total-R difference, no ledger-integrity failure) | Sunday 06:30 pipeline (`ab_adjudicate.py`) |
| **TJ2 — tick reconciliation** | paper fills within tolerance of the 1.5M-tick baseline | self-arms at ≥7 days of ledger |
| **TJ3 — watchdog** | morning status: both arms telemetry fresh, 2 terminals, no integrity problems | `morning_status.py --strict` daily |

Current status: **gate clock has not started** (no closed paper trades yet —
the v26.35-fixed engine only began producing real statistics). At the observed
signal rate the A/B expects ~2–3 weeks to reach 30. There is also a
pre-registered *accelerated* path: gate TJ3 + **20** closed arm-A trades with
positive expectancy + reconciliation on ≥5 days → live at the minimum viable
size ($50), keeping the paper arms running.

**2026-09-14, TJ2 early look:** arm A's 13 closed trades (5.09d) reconciled
against the tick baseline — R agrees (mean +0.188R, CI covers 0, 0 exit-price
violations) but reason-agreement 0.692 < 0.75 ⇒ verdict REASON-DRIFT. Mechanism
pinned: the paper ladder runs per M15 bar-open (11/13 closes on boundaries)
while the study baseline walks every tick; TJ2 stays unarmed (7d gate) and the
bar-open-vs-tick baseline question is now the open item before any arming.
`artifacts/v75_replay/paper_tick_reconciliation.json`, changelog 2026-09-14.

**2026-09-15, TJ2 amendment (pre-registered) + MATCHED:** the reconciler gained
`--mode baropen` (baseline evaluates on the first tick at/after each M15
boundary — the engine's `new_bar` gate semantics — SL/TP boundary hits stay
per-tick). Same 13 trades: delta +0.022R, CI covers 0, reason-agreement
0.846 ≥ 0.75, zero exit violations → **MATCHED**; every-tick mode reproduces
the 09-14 REASON-DRIFT (+0.188R / 0.692) unchanged. The drift was evaluation
cadence, not mechanics; TJ2's arming question is resolved. Same artifact,
final state `MATCHED | mode: baropen`, changelog 2026-09-15. Collection is
now 24/7 (session gates off in both arm charts, verified by boot banners
`Session=00-00`; terminals stay open).

**2026-09-15, ERA BOUNDARY — v26.38 paper fill-model parity (append-only):**
the fill-cost stress protocol priced the bar-open fill cadence at −8.3R/window
vs the live book's broker-side resting orders; v26.38 closes that defect (hard
SL/TP now fill per tick at the resting level, management exits stay bar-granular
— the exact semantics of the TJ2 baropen MATCHED baseline). Consequence for the
gate: **the 30-trade clock restarts at the 19:52/19:58 UTC+1 deploy boundary.**
Trades closed before it carry bar-open fills (arms A/B), trades after carry
per-tick fills; one expectancy statistic must not mix the two regimes. Arm
equities persist (continuity preserved) but trade counts are era-tagged from
the changelog entry forward. The 23 pre-boundary trades remain honest data
about the OLD sim — and the arm-A risk-cap refusals at $30.73 (19:30/19:45,
min-lot $6.57 > cap $6.15) are the VSG strangulation floor operating live.
G5/G1 mechanics unchanged; only the clock and the fill semantics reset.

## 3. Decision tree — what each outcome MEANS (pre-declared, applies verbatim)

```
GATE ADJUDICATES (TJ1, TJ2, TJ3 all evaluated)
│
├─ TJ1 arm-A positive AND TJ2 PASS AND TJ3 green
│    → GO LIVE on terminal A chart01, magic 7788075, MiitemshubAI_VOL75_LIVE.set
│      at the pre-registered size ($50 floor, $100 recommended).
│      Paper arms keep running for the full A/B.
│
├─ TJ1 arm-A positive AND (TJ2 FAIL or TJ3 red)
│    → DO NOT GO LIVE. Fix the failing leg (reconciler drift: investigate
│      ledger-vs-tick divergence; watchdog: operational fix). Re-evaluate
│      at the next pipeline run. No strategy change.
│
├─ TJ1 INCONCLUSIVE (paired |t| < 1.0 despite ≥30 trades)
│    → KEEP COLLECTING. The rule is threshold, not time-box: more paired
│      trades → more power. Board at 50 and 75 trades. Do NOT hand-tune
│      while collecting — the governor drift that tuning introduces is what
│      gates are for.
│
├─ TJ1 arm-A NEGATIVE (or net expectancy ≤ 0 at ≥30 trades)
│    → NO GO on this config, and this is a decision, not a setback:
│      (a) re-baseline on the fresh 60-day certified window to see whether
│          the paper stream matches the replay (cost regression check);
│      (b) investigate protocol-ordered causes only: spread regime shift
│          (price the change with the +0.0022R/t-per-unit slope), session
│          mix changes, governor interactions (funnel diffs vs replay);
│      (c) re-certify any candidate remedy on a FRESH window before it may
│          touch a paper arm. Collection continues meanwhile.
│      Probable truth if this happens: the replay's +0.038R/t (t=0.35) was
│      not distinguishable from zero — the gate exists precisely to catch this.
│      (Execution playbook, frozen 2026-09-15: docs/NO_GO_BRANCH_PLAYBOOK.md
│      — re-baseline drill, spread-regime pricing, governor funnel diffs,
│      frozen outcomes A/B/C; run Steps 2–4 read-only if INCONCLUSIVE.)
│
├─ TJ1 arm-B positive while arm-A negative (TP 2.4 wins the duel)
│    → Do NOT adopt by hand. Re-run the 210-day certified walk-forward with
│      TP 2.4 net-of-cost first; only if it re-certifies clean may the LIVE
│      preset's InpTpMult change — and that change itself then goes through
│      a paper test on arm C (see below), not straight to live.
│      (Note: fresh60 2026-09-05 shows TP 2.4 NEGATIVE net −4.07R — an
│      unlikely branch, but the tree must exist before it happens.)
│
└─ No verdict needed yet (gate not reached)
     → KEEP COLLECTING. Nothing to do but keep the system watched.
```

### The arm-C branch (any future VALIDATED-CANDIDATE, e.g. a config that
### clears a study's frozen bar)

```
1. A study returns VALIDATED-CANDIDATE (none has, as of 2026-09-05;
   the first live candidate-path study is the pre-registered viable-scale
   re-pricing: docs/VIABLE_SCALE_GEOMETRY_STUDY.md, 2026-09-15 — it re-prices
   scale only and cannot manufacture edge; its output feeds step 3's sizing,
   never skips step 2).
2. ONLY AFTER the primary A/B has adjudicated uncontaminated:
     - write a NEW pre-registered adjudication rule (candidate vs arm A
       reference — not an A/B rerun) BEFORE the candidate's 30th trade
       (the template now exists and is frozen: docs/ARM_C_TEMPLATE.md,
       2026-09-15 pre-registration — daily-paired C−A rule, gates G1–G4,
       VALIDATED-CANDIDATE-CONFIRMED / REJECTED / INCONCLUSIVE mapping; only
       the fill-at-activation fields remain open; amendment 2026-09-15 added
       G5, the adjudication-time strangulation-floor gate — a window collected
       below the monitor's floor is INVALID, never adjudicated);
     - activate arm C (one input edit → Start-Process → confirm banner;
       measured ≈ 1 minute, docs/ARM_C_TEMPLATE.md);
     - add {"C_cand": 7788125} to morning_status.py magics.
3. Candidate collects ≥30 closed trades; adjudicated by the new rule.
     - wins → update LIVE preset via the same certified-path discipline;
     - loses → teardown C (delete data folder + install). Nothing references
       magic 7788125.
```

## 4. Non-negotiables (never change, whatever the outcomes above)

- **Live only on terminal A chart01, magic 7788075.** Paper arms stay paper forever.
- **No hand-tuning.** Any config change must be (a) frozen in a protocol doc,
  (b) certified on a fresh window, (c) paper-tested on an arm. The LIVE preset
  changes only through that chain.
- **Funding floor**: live equity ≥ $50 (hard floor $31 — the broker lot floor
  vetoes below it), working buffer ≥ $100; withdraw weekly everything above
  the buffer. The trading-size ceiling is fixed by the pre-registered plan —
  the compound-growth goal is served by *edge + time*, not by raising risk.
- **Every artifact is spec-stamped** (2026-09-05) — any run that can't show
  its specs, cost model, and geometry is invalid on its face.
- **Data is the only judge.** Intuition, opinions, and "I just feel it" open
  no branches in this tree.

## 5. Cadence (the whole operation, daily)

| When | What |
|---|---|
| Daily, ~09:00 | `python scripts/morning_status.py --strict` — arms, gaps, gate X/30 |
| Sunday 06:30 UTC | `paper_pipeline.py` — gate adjudication fires automatically once data exists |
| On any study result | Adjudicate vs frozen criteria → verdict row + changelog + commit (nothing else) |
| On gate pass | Execute section 3's GO LIVE branch; keep morning_status running |
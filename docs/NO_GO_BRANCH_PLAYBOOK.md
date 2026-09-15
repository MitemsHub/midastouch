# NO-GO BRANCH PLAYBOOK — executed the day TJ1 adjudicates arm-A negative

**Frozen pre-registration: 2026-09-15, before adjudication.** This playbook is written
*before* the gate fires so the response to a NO-GO is procedure, not improvisation.
It operationalizes the decision tree's `TJ1 arm-A NEGATIVE` branch in
`docs/OPERATING_SUMMARY.md` (§3) and nothing else. Amendments are append-only and dated.

## 0. What fires this playbook — and what does not

Fire on **exactly one** adjudicator output, produced by `scripts/ab_adjudicate.py`
(frozen rule, pre-registered 2026-09-04; verdict strings in code):

- `arm-A NEGATIVE`: arm A has ≥30 closed trades and mean R ≤ 0, **or**
- `INCONCLUSIVE` **and** arm-A mean R ≤ 0 — treated as NO-GO-leaning; the tree's
  threshold rule says INCONCLUSIVE alone keeps collecting, so on INCONCLUSIVE this
  playbook runs **read-only** (Steps 2–4 as diagnostics, no remediation, no arm stops)
  while collection continues to 50, then 75 trades per the standing rule.

Does **not** fire on: TJ2/leg failures (each has its own tree line), arm-B wins the
duel (separate branch — TP-2.4 re-certification, not this playbook), ledger-integrity
failure (P3 → fix the leg, re-adjudicate), or arm C (separate arm-C branch;
VALIDATED-CANDIDATE is a precondition, never an authorization — `GO_LIVE_CHECKLIST.md`).

Day 0 definition: the first `paper_pipeline.py` run (Sundays 06:30) whose
`ab_adjudication.json` shows the firing condition. Day 0 actions run that day.

## 1. Step 1 — Freeze and preserve (Day 0, ~30 min, read-mostly)

Nothing gets tuned or "improved" — the value of the paper stream is as evidence.

1. Snapshot both ledgers to
   `artifacts/v75_replay/arm_{A,B}_ledger_final_<date>.csv` (byte copy; no rewrite).
2. Record in the changelog: final n, mean R, total R, win rate, reasons mix,
   paired-delta summary — copy the adjudicator's own numbers, do not recompute.
3. Keep both arms **running** unless P3 integrity failed (collection continues per
   the tree; the stream is the control for everything below).
4. Do NOT touch chart inputs, presets, governor knobs, or the account. The replay
   baseline (Step 2) must be comparable to a paper stream that did not change.

## 2. Step 2 — Re-baseline drill on the fresh 60-day certified window (Day 0–1)

**Question answered:** does the paper stream match the certified replay, or did the
paper run degrade relative to it (cost regression, drift, defects)?

**Baseline of record:** `cert_report_fresh60_tp18_net.json` — n=114, total +4.37R,
**mean +0.038R/trade (t = 0.35)**, on the fresh-60-day tick window with the v26.36
spread-in-pnl cost model (spread 18.5 units, `usd_per_unit_per_lot` 1.009, min lot
0.01 — see `ab_adjudication.json` spec block). This is the same +0.038R/t figure the
decision tree cites, and it was **never distinguishable from zero** (t=0.35) —
Step 2 primarily tests *stream health*, not edge rediscovery.

**Drill (read-only, no arm involvement):**

```bash
CERT_DATA_DIR=<fresh60 tick dir> python scripts/certify_v75.py --tag rebaseline_<date>
```

Defaults carry the certified geometry (spread 18.5 via `CERT_SPREAD`; do not override
other env unless reproducing a specific prior run). Acceptance checks, in order:

- **R1 reproducibility:** the run reproduces the baseline within tolerance
  (n=114 ± a few bars of drift, mean R within ±0.02R of +0.038, same funnel shape).
  If R1 fails → data or harness drifted; stop and fix the harness before anything else.
  **Amendment 2026-09-15 (hybrid study's G0 finding):** pin the harness, not the
  worktree file — reproduce from `scripts/study_frozen_certify_v75.py` (HEAD `841bf97`
  + the study's exit-mode patch, exit-mode ignored) or re-snapshot HEAD the same way.
  The worktree `certify_v75.py` gained micro-fit 1.5% + the sd ≥ 107.7 min-stop floor
  after 09-05 and no longer reproduces the baseline (n=84, −14.57R); it is the v27
  research line, not the certified-era harness.
- **R2 stream-vs-replay:** re-run the reconciler (`reconcile_paper_ticks.py --mode
  baropen`, the 09-15 amended cadence) over the final 30 arm-A trades. PASS bars:
  |ΔR| CI covering 0 and reason-agreement ≥ 0.75 (the frozen TJ2 bars).
- **R3 cost regression check:** compare realized mean spread paid (adjudicator spec:
  18.5) against the live spread distribution sampled from arm-A fills. If live mean
  spread exceeds the model's by >10%, the cost model understated live costs —
  price the gap with the Step 3 slope before concluding anything about "edge decay".

**Outputs:** `artifacts/v75_replay/rebaseline_<date>.json` + R1/R2/R3 table in the
changelog. Verdict phrase: "stream healthy" (R1+R2 pass), "stream degraded" (R2 fails),
or "harness drifted" (R1 fails).

## 3. Step 3 — Spread-regime pricing with the +0.0022R/t slope (Day 0–1, arithmetic)

**The tool (frozen by the spread-tier study, `V75_SPREAD_TIER_STUDY.md` §3):**

> Δ expectancy ≈ **+0.0022R per trade per 1-unit spread reduction**
> (≈ +0.0023 measured on the 70-day cost-dilution window, 158 trades — same number
> within rounding). Reverse direction: each +1 unit of spread costs ≈ 0.0022R/t.
> The bar: to move net expectancy by +0.08R/t would need ≈ **−25 spread units** —
> no synthetic venue plausibly offers that; the account "grows or dies on
> expectancy, not on hunting a cheaper toll" (study §4).

**Procedure:**

1. Compute live realized mean spread over the paper window: per-trade
   (entry fill vs concurrent bid/ask is not recorded per-row), so use the fill-price
   method — for each ledger trade, `spread_est = |fill vs mid|×2` averaged, and
   cross-check against the spread telemetry in the arms' JSONL hearts. Record the
   number and the sample.
2. Price the regime: `ΔR/t = 0.0022 × (18.5 − live_mean_spread)`.
   - Δ ≥ +0.02R/t (i.e. live spread ≥ ~9 units tighter than model): the regime
     shifted **in our favor** — does NOT rescue a NO-GO (it makes it worse: the
     replay's +0.038 would be even less attainable); record and close.
   |Δ| < +0.02R/t: no material shift; the cost structure held. Record and close.
   Δ ≤ −0.02R/t (live spread ≥ ~9 units **wider**, e.g. ≥ 27): real cost regression;
   this becomes a named cause in Step 4's output, with its R/t price attached.
3. Sanity anchor: the tier study's zero-spread ceiling on fresh60 still failed the
   frozen materiality bar — so even a best-case regime finding cannot, alone,
   reopen the config. It only re-weights causes.

**Output:** one line in the changelog + a row in the Step 4 table: measured spread,
priced ΔR/t, cause weighted or dismissed.

## 4. Step 4 — Governor funnel diffs, replay vs paper (Day 1–2)

**Question answered:** are the two systems admitting the same trades? A funnel
mismatch means the paper stream tested a different trade population than the replay
certified — an explanation that is about machinery, not edge.

**Counters (offline side):** `certify_v75.py` emits the funnel dict:
`score, spread-gate, risk-cap, paused, time-block, auto-disable, family-throttle,
pb-failure-classifier, micro` (exact keys in any `cert_report_*.json`).

**Live-side proxies (journal greps, both arm hosts, whole window):** the engine's
actual print strings (v26.36 source, grep-verified):

- `"SKIP ... governor spread gate: spread ... > ...% of stop"` → spread-gate
- `"SKIP ... min-lot risk $... exceeds cap"` → risk-cap
- `"PAUSED — consecutive-loss breaker"` → paused
- `"SKIP ... ACCOUNT GUARD: fleet $... + new $... > cap"` → account-guard
  (paper-mode fleet-basis defect documented 09-15, **fixed v26.37 same day** —
  FleetOpenRisk now mirrors the instance's virtual position at the original stop;
  count separately and note it; a nonzero paper count after v26.37 is a NEW defect,
  never blended into a strategy cause)
- `"SUPPRESSED (probing every ...th signal)"` → auto-disable/probe
- `"SKIP ... meta-label gate"` → meta-label (replay has no meta table either:
  "meta-label table not found — sizing at 1.0x base risk"; counts should be ~0 both
  sides or the diff is a config drift, not an edge result)

**Diff table (required in the artifact):** per counter — replay count (normalized
per 1000 signals evaluated), paper count (same normalization), delta, verdict
(match / drifted / defective). Normalization matters: the replay consumed ~200 bars
of warmup per cert run while the paper arms ran continuously; compare *rates*, not
raw counts.

**Known-bad patterns this step exists to catch:**
- spread-gate firing on paper but ~0 in replay → live spread regime (cross-check Step 3);
- account-guard firing on paper → the $0 fleet-equity defect, machinery cause;
- `paused` firing heavily on paper but not replay → loss-streak dynamics differ
  because the paper population differs (a *symptom* of an earlier funnel divergence);
- any counter firing on one side only with rates differing >2× → name it, and only
  protocol-ordered remedies follow (see §5).

**Output:** `artifacts/v75_replay/funnel_diff_<date>.json` (table + per-counter
journal-grep counts + replay funnel from the Step 2 re-baseline run).

**Automated (2026-09-15):** `scripts/funnel_diff.py` produces this exact output
contract on demand and as the weekly pipeline's §5 leg — per-counter rates
(replay per 1000 of `funnel.score`, live per 1000 of the arms' combined sig
events), frozen verdict words (`match` / `LOW-COUNT: not adjudicable at this
window` for counts < 5, honoring F4 / `drifted (>2x rate)` / `CONFIG DRIFT` for
the ~0-both-sides counters / account-guard CLASSIFIED-vs-DEFECTIVE by per-firing
timestamp against the v26.37 deploy), and a cumulative
`funnel_diff_history.json` so journal expiry can never silently destroy counts.
Real-execution usage: `--replay <rebaseline run's cert_report_*.json>` so the
replay funnel comes from the SAME run R1 validated, not the baseline of record.

## 5. What may be concluded — and the only legal outcomes

Combine Steps 2–4 into **one** of these frozen outcomes (write the letter, with the
supporting rows, into the changelog; append-only afterwards):

- **Outcome A — stream healthy, edge absent (expected).** R1+R2 pass, spread shift
  immaterial, funnel matches. Conclusion: the +0.038R/t replay edge (t=0.35) does not
  survive; the gate did its job. Action: arms keep collecting **as a research
  stream only**; the config is retired from live consideration; next investigation
  must enter through the study chain (a pre-registered hypothesis + fresh-window
  test), never through arm edits. No timeline pressure — the $50 stays a paper
  account until a VALIDATED-CANDIDATE exists through the arm-C branch.
- **Outcome B — stream degraded (machinery cause).** R2 fails or a funnel counter
  drifts >2× with a named defect (e.g. account-guard paper basis). Action: fix the
  defect through the certified chain (study → fresh window → paper), then re-run
  this playbook once, complete, on the repaired stream. A repaired stream may
  justify ONE re-adjudication, clearly labeled as such, only if the defect plausibly
  suppressed winners (the 09-08 dropped-row class) — pre-declared here so it cannot
  be invented post-hoc.
- **Outcome C — cost regression (regime cause).** Step 3 prices ≥ −0.02R/t of
  spread widening, funnel spread-gate confirms. Action: re-price the same config on
  the widened-spread assumption (CERT_SPREAD = live measured); if the re-priced
  replay also goes ≤ 0, the regime explanation is complete and this collapses into
  Outcome A with a named cause. No venue hunting: the study's −25-unit bar stands.

**Never legal under any outcome:** editing arm charts, presets, governor thresholds,
risk inputs, or the TP duel to "see if it helps"; hand-tuning of any kind (the tree's
own warning); adopting arm B's config by hand (that branch has its own rule);
treating any of this as a backtest result without the tester artifact.

## 6. Cadence after the verdict

- **Day 0:** Step 1 + kick off Step 2. **Day 1:** Steps 3–4. **Day 2:** outcome
  letter written and frozen; changelog + artifact links complete.
- Ongoing: the Sunday pipeline continues (collection is research, not a live path);
  `morning_status` daily; WLOST / canary alerts unchanged.
- **Re-entry into live consideration** requires, in order, and nothing less:
  1. a pre-registered hypothesis doc (new, dated, falsifiable, like
     `V75_RECERT_PROTOCOL.md` §2's pattern — "the hypothesis, stated so it can lose"),
  2. a VALIDATED-CANDIDATE verdict on a **fresh** window by the certified harness,
  3. a new paper arm (or repurposed arm C at its pre-registered ≥$100 floor) trading
     the candidate ≥30 closed trades under a newly pre-registered adjudication rule,
  4. only then the `GO_LIVE_CHECKLIST.md` gate, with the account ground truth
     re-verified the same week (the real account is shared — this rule is not waived).

## 7. Provenance

- Decision tree / branch wording: `docs/OPERATING_SUMMARY.md` §3 (verbatim branch).
- Baseline of record: `cert_report_fresh60_tp18_net.json` (+0.038R/t, t=0.35, n=114).
- Working R1 invocation (validated by the 2026-09-15 drill — the §2 command sketch
  fails verbatim: the spec-integrity guard requires all four spec vars alongside
  CERT_DATA_DIR, and the certified window lives in `artifacts/v75_replay`):
  `CERT_DATA_DIR=artifacts/v75_replay CERT_SPREAD=18.5 CERT_USD_PER_UNIT_PER_LOT=1.009 CERT_MIN_LOT=0.01 CERT_LOT_STEP=0.001 python scripts/study_frozen_certify_v75.py --tp-mult 1.8 --tag rebaseline_<date>`
- Slope: `docs/V75_SPREAD_TIER_STUDY.md` §3–4 (+0.0022–0.0023R/t per unit; −25-unit
  bar; zero-spread ceiling fails materiality).
- Gate rule: `scripts/ab_adjudicate.py` module docstring (P1 |t|≥1.0, P2 sign
  agreement, P3 integrity; frozen 2026-09-04).
- Funnel counters: `scripts/certify_v75.py` (funnel dict) and the v26.36 SKIP/SUPPRESS
  print strings listed in §4.
- Reconciliation bars: `scripts/reconcile_paper_ticks.py` `--mode baropen` (09-15
  amendment; MATCHED on the 13-trade sample: ΔR +0.022, agreement 0.846).
- Known defects carried into evidence handling: silent row drop (fixed v26.36
  verified writers + WLOST quarantine), account-guard paper fleet-basis blindness
  (fixed v26.37 2026-09-15: FleetOpenRisk mirrors the virtual position at the
  original stop, calibrated tick value; live path byte-identical — so the funnel
  diff is clean of the class and any paper account-guard firing is a NEW defect),
  restart force-close of an open position (open).

## 8. Rehearsal log (append-only)

- **2026-09-15 — Steps 2–4 dry-run on live data (DRILL; adjudicates nothing).**
  Artifact: `nogo_playbook_drill_20260915.json`. R1 **PASS — exact reproduction**
  (n=114, +4.37R, +0.0383R/t, t=0.35, funnel shape identical) from the pinned
  harness. R2 **PASS** (baropen reconciler, 14 arm-A trades: ΔR +0.002, CI
  [−0.229, +0.341], reason-agreement 0.857, zero exit violations → MATCHED).
  R3 **PASS** — live spread ~7.7% tighter than model (spot 17.08 vs 18.5; fill-shift
  median 8.32 = half-spread at entry), no cost regression. Step 3: ΔR/t = +0.0031
  — immaterial by the frozen band; no regime shift. Step 4: no comparable counter
  diverges >2×; account-guard fired **1×** on FB9A (the known $0-basis defect,
  counted separately as required). Five findings recorded (F1–F5), two already
  folded into §7: the working R1 command and the unresolved CERT_DATA_DIR path.
  Others: no spread field in arm telemetry (Step-3 cross-check impossible —
  TickRecorder enablement fixes permanently), journal retention (~6d) shorter than
  the paper window (Step-4 diffs must use the overlap at real execution), and
  R2's "final 30" wording ran on 14 trades. The playbook's first real execution
  will not be its first execution.
- **2026-09-15, same day — post-drill defect closure.** The account-guard firing
  the drill counted (1×) is closed: v26.37 (manifest re-pinned deliberately,
  0-error compile ×2 trees, both arm hosts restarted and banner-verified, paper
  equity restored exactly) makes FleetOpenRisk mirror the instance's own virtual
  position, so the guard's operands are truthful in paper mode. Diagnosis note
  recorded honestly: the 07:45 refusal this morning was the *total-risk guardrail*
  firing correctly on paper numbers (min-lot $6.01 > 15% × $37.09 = $5.56, arm A
  flat) — the fleet-sum blindness was a structural defect that produced a $0.00
  panel operand and misattributable veto classes, not the cause of that refusal.
  Future funnel diffs should see account-guard = 0 in paper; nonzero is a new defect.

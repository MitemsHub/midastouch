# Changelog

## [H1 timeframe test on V75 (1s): cost stops binding, signal appears (+10.5R IS) — OOS persistence still fails; frozen verdict NO-EDGE] - 2026-09-15

### Amendment A to docs/CROSS_SYMBOL_SCAN_20260915.md, pre-registered before any H1 run
- **Setup:** H1-primary replay (H1 series in the harness's primary slot, H4 context aggregated from the same source — no synthetic bars), same four frozen configs, same gates, one pass; V75(1t)@H1 as the control. Spread constants are per-trade and timeframe-independent.
- **Control first:** V75(1t)@H1 is miserable everywhere (shipped −16.64R, DD 67%; trained_best −20.31R) — the H1 horizon is not a general fix.
- **The finding:** V75(1s)@H1 shipped config = the ONLY SCAN pass on any alternative symbol or timeframe: +10.51R over 406 trades, DD 25.7%, streak 6, WR 48.0%. Spread toll drops to 1.24% of stop distance (M15 1s: 5.6%; M15 1t: 2.2%) — the lowest cost burden of any combination tested. At H1, cost is no longer what kills this family.
- **What fails:** OOS persistence — −3.97R (n=53, DD 33.8% > 30 gate) over the shared Jun–Sep 2026 window. This is the same failure mode as the home symbol's rebuilt entry (+11.9R IS → −5.7R OOS). Honest caveat now on record: every OOS test this cycle shares one 3-month window — one regime draw, not independent confirmations. Distinguishing a hostile regime from pervasive overfit is THE open question of the program; an independent later window is the only clean separator.
- Artifacts: CROSS_SYMBOL_SCAN_v75low_H1.json, CROSS_SYMBOL_SCAN_v75t_H1.json; H1-primary datasets under artifacts/train/v75low_h1/ and v75t_h1/.

## [Cross-symbol edge scan: NO-EDGE on V100 and V75 (1s); new 2.9-year V75(1s) corpus collected live] - 2026-09-15

### Executed — docs/CROSS_SYMBOL_SCAN_20260915.md (frozen before runs) + scripts/cross_symbol_scan.py
- **Scope honesty first:** the repo held no V75-low data; V100 was already adjudicated for the OLD configs (`docs/V100_NET_EDGE_STUDY.md`: gross dies net, Q1/Q2 NO, 1.0-lot floor). The scan's open question was whether the REBUILT entry (EMA-side kernel, MR-off) has an edge where the old configs did not.
- **V100 (2y, true spec — spread 0.26, $1.0/unit/lot, 1.0-lot floor): NO-EDGE.** The rebuilt entry shows gross signal even here (+9.40R, n=79, WR 51.9%) — the kernel's directional effect transfers across symbols — but the 1.0-lot floor at a $300 basis risks 3–5%/trade and DD hits 49.5% inside a winning run. Independently re-confirms Q5: V100 is untradeable at small scale regardless of signal quality.
- **V75 (1s) Index: NO-EDGE, decisively — and the symbol had no data in the repo, so it was collected live.** `symbol_select` woke the dormant subscription; spec measured live (spread 1.90 units, $1.0/unit/lot, min lot 0.05, step 0.001); 96,055 M15 bars (2023-11-06 → 2026-09-15, ~2.9 years, the largest corpus we hold) pulled chunked and saved to artifacts/train/v75low/. All four configs deeply negative (shipped −58.19R/377t; rebuilt −18.10/−26.47R). Mechanism priced: M15 TR is ~7× smaller (30.8 vs 220.3) while spread is ~10× smaller (1.90 vs 18.5) → spread is 5.6% of the 1.7·ATR stop vs 2.2% on the 1-tick V75 — a 2.6× relative cost toll, structural at this timeframe.
- Verdict recorded in OPERATING_SUMMARY question table (row 7b): the strategy family's edge, where it exists at all, is specific to the 1-tick V75 index; no second instrument is certifiable from held data. Artifacts: CROSS_SYMBOL_SCAN_v100.json, CROSS_SYMBOL_SCAN_v75low.json. Engine code and presets untouched.

## [Entry redesign sprint: EMA-side kernel + MR-off rebuilds the family (+11.9R IS, −5.7R OOS) — still NO-SHIP on the frozen gates] - 2026-09-15

### Executed — docs/SPRINT_ENTRY_REDESIGN_20260915.md (frozen before runs) + scripts/entry_lab.py + scripts/sprint_entry_redesign.py
- **Lab fidelity proven first:** scripts/entry_lab.py is a byte-copy of the certified harness with five inert-by-default knobs (use_bandfade, m15_full_stack, h1_sep, disable_mr, mom_confirm); anchors ema-side off AND on reproduce the harness EXACTLY (same n, totalR, DD) before any candidate counted. Certified files untouched.
- **The rebuilt entry:** trend-side pullback core (ema_side ON), PB band narrowed to 0.6–0.7·ATR, TP 1.6R, mean-revert legs disabled. IS: +11.89R over 137 trades (DD 14.6%, streak ≤8) vs the shipped config's −4.3R on the identical window. OOS: −5.73R (n=40, DD 13.8%) vs the shipped baseline's −15.10R (n=119, DD 29.7%) on the identical window — beats the gate-5 margin by ~9.4R and halves the drawdown.
- **Still NO-SHIP, and the gates are right:** OOS totalR is negative (g2) and meanR degraded below half of IS (g4). A config that loses less than baseline is not a config that makes money. All three finalists (incl. the full-M15-stack variant, +10.56R IS) failed identically: the Jun–Sep 2026 out-of-sample regime is hostile to the entire family.
- **Two auxiliary findings priced:** (1) BandFade legs never fire on this corpus (strategy mix PB 163 / MOM+PB 104 / MR 16 / MOM+MR 3), so the preset-vs-harness BF fidelity question is moot here — gap exactly 0.0R. (2) The MR leg is the family's biggest bleed source: ~19 IS trades costing ≈−10R; disabling it is the single largest improvement lever found (recorded as the lead design fact for the next iteration, not shipped).
- **Two driver bugs caught and fixed before conclusions:** a duplicate-kwarg crash in family C, and a wrong OOS baseline row (pinned CLI defaults instead of the module constants PB 0.30/2.2 — corrected to the true shipped baseline, n=119/−15.10R, matching the training protocol's row exactly).
- Artifacts: artifacts/train/SPRINT_REPORT.json (equivalence proof, 72 IS runs, finalists, OOS rows, gate matrix), docs/SPRINT_ENTRY_REDESIGN_20260915.md. Engine code and presets untouched; the rebuilt entry is a candidate, not a deployment.

## [V75 parameter training: NO-SHIP — no trainable edge over the shipped config on 417 days of data] - 2026-09-15

### Executed — docs/TRAINING_PROTOCOL_20260915.md (frozen before the runs) + scripts/train_v75_grid.py
- **The question:** user directive to train the EA on the data we hold, today. The protocol froze the split (IS 2025-08-01→2026-06-01, OOS 2026-06-01→2026-09-02 from the 40k-bar/417-day broker corpus, converted to harness format in artifacts/train/), the fill model (touch = broker-side resting-order approximation), the search space, the selection rule, and six ship gates BEFORE any run.
- **Stage 1 (108 runs): 0 eligible.** Best ≈ −4.3R over 10 months; nearly all of the 108-configuration space is deeply negative (tp 2.4 rows: −14 to −28R, DD 40–75%). Parameters cannot rescue the entries.
- **Amendment A (declared after stage 1, before OOS):** structural levers on IS only. `ema_side_filter` is the one real finding — it flips the family from ≈−15R to +1.5R (n=194) and its best geometry reaches +0.71R with DD 24.3% — but still fails the frozen eligibility bar on the loss-streak bound (9 vs ≤8), and OOS turns it negative (−7.8R; baseline itself −15.1R over the same 93 days). `legacy_sl` re-confirms the walkforward inversion mechanism: −39R, 95% DD. min-score and family-throttle variants destroy the trade count without fixing expectancy.
- **Verdict (frozen rule, applied mechanically): NO-SHIP.** The shipped parameters remain the certified ones. The certified fresh-60 +4.37R is now honestly recontextualized: 93 of its 94 days overlap the OOS segment where the same config scores −15.1R — favorable-regime luck, not a stable edge. The EMA-side filter is the only lever with a measured directional effect; it is recorded as the lead candidate for a strategy redesign (entry side must be trend-aware), not as a preset change.
- Artifacts: artifacts/train/TRAINING_REPORT.json (consolidated, 108+14 runs + OOS diagnostics), TRAIN_LOG.txt, AMENDMENT_A_*.json, OOS_DIAGNOSTICS.json; protocol with Amendment A: docs/TRAINING_PROTOCOL_20260915.md. Engine code and presets untouched.

## [Ledger ERA provenance — pre/post-v26.38 fill regimes are now separated in every statistic, automatically] - 2026-09-15

### Added — scripts/era.py + era stamps in both engines (v26.39 / v2.24) + era-aware consumers + tests (18 new)
- **The rule being enforced:** the fill-cost stress protocol priced the pre-v26.38 bar-open fill cadence at −8.3R/window vs per-tick fills, so the two regimes are different distributions and must never share an expectancy statistic (OPERATING_SUMMARY 2026-09-15 era-boundary amendment). Until now the separation was a manual convention; it is now data-native.
- **The writers:** each engine stamps an idempotent provenance row `ERA,<version>,<boundary_epoch>,pertick-fills` into its own paper ledger at init. MitemshubAI v26.39 stamps in `PaperInit()` before any early return, `PaperActive()`-guarded (LIVE book untouched); V75MacroEngine v2.24 stamps in `OnInit` under `InpPaperMode`. Strategy and fill model are unchanged — the stamp is provenance only. Restarts append another stamp; readers keep the FIRST (append-only files, so the first is the oldest claim) — pinned by test.
- **The boundary (frozen, pre-registered):** `ERA_EPOCH = 1789494700` = 2026-09-15 17:51:40 UTC, the midpoint of the verified EA-down window (last pre-deploy ledger activity 17:50:48 UTC, terminals stopped 17:52:18, first v26.38 init 17:52:35 UTC) — no real trade can straddle it by construction. An earlier draft froze the boundary outside the silence window; caught in self-review and corrected before any consumer shipped. A stamp whose boundary mismatches the frozen one is marked not-ok and ignored (consumers fall back to the epoch rule).
- **The readers:** `era.parse_era_rows` (integrity-marked), `era_of_trade` (positional: rows ABOVE the first stamp are classified by the frozen epoch rule, rows BELOW carry the stamp era — necessary because append-only stamps sit at the file's current end), `era_filter` (default `pertick-fills` = the pre-registered gate statistic), `era_split` (display). Wired into: `ab_adjudicate.py` (TJ1 pairs/t/count are post-era only, era block in the artifact), `adjudicate_arm_c.py` (arm-A reference filtered post-era, G1 count post-era, era block), `morning_status.py` (X/30 clock is post-era with a pre-excluded count shown, rate projection suppressed below 3 trades in <12h — a single close can no longer claim "24/day"), `reconcile_paper_ticks.py` (only post-era trades are eligible; pre-era trades would reconcile against the wrong regime by construction). All parsers skip ERA rows and carry CLOSE line numbers.
- **Smoke on real ledgers caught a real pre-existing bug:** with arm A's 14 trades all pre-era, the filtered list is empty — and the TJ1 KEEP-COLLECTING branch crashed on `arm_stats({})['trades_per_day']` (KeyError) while also passing arm A's equity curve for arm B's rate projection. Fixed (`.get()` + per-arm curve); the smoke verdict now reads correctly: `KEEP COLLECTING — A_tp18 has 0/30 post-era trades; B_tp24 has 1/30 post-era trades`.
- **Deployed and verified live:** compile 0/0 both engines (49E0 + sync build gate); manifest re-pinned (`26.39|568f4930…`, `2.24|91e78c87…`); arms restarted from a verified-zero process state (tasklist, not WMI — a bash-quoting trap made a first `Get-CimInstance` kill attempt silently misfire, caught by re-checking with tasklist before launch); banners show `[v26.39]` / `v2.24` + `PAPER ledger era stamp` on both hosts (21:44:17/19); ledger stamps verified ok on all three ledgers; splits: A 14 pre-era / 0 post, B 9 pre / 1 post (a post-v26.38 fill landed before this deploy), C no trades yet. Suite: era 18/18, go-live 25/25, adjudicator 18/18, morning_status 15/15.
- **Note for tomorrow's status read:** arm B is currently PAUSED by the consecutive-loss breaker (3 losses today, dailyPnL −15.00) — pre-existing engine behavior, resumes next session day; not related to this change.

## [Go-live artifact contract re-pinned to the deployed two-engine line — the stale v27.00 test debt is closed with teeth] - 2026-09-15

### Fixed — scripts/verify_go_live_artifacts.py + tests/test_go_live_artifacts.py: the suite pins reality, and can never go stale silently again
- **The debt:** both files pinned the unshipped v27.00 narrow-engine design (`EXPECTED_VERSION = "27.00"`, `ProcessM30Gate`/`MAX_HOLD_SECONDS`-era markers) and had been failing 7 tests on the untouched worktree since the v26.36 re-pin — a green-suite lie waiting at the exact moment a go-live check mattered.
- **The design change:** certified BYTES are no longer duplicated in a second constant. The verifier now reads `scripts/deploy_manifest.txt` (the deploy gate's own single source of truth), asserts the worktree matches the pins, and asserts the pinned versions are the expected ones (MitemshubAI `26.38`, V75MacroEngine `2.23`). An engine edit without a deliberate re-pin now fails here AND at the deploy gate — the two can no longer drift apart.
- **The contract is two engines now:** MitemshubAI (arms A/B host, v26.38 markers incl. `PaperCheckHardExits`, `PaperClose(reason, exit_price=0)`, paper-aware `FleetOpenRisk`, volatility-only refusal, TickRecorder include) and V75MacroEngine (arm C, v2.23 markers incl. per-tick `PaperCheckExits` before the M30 gate, the arms-exact 12-field OPEN schema, self-containment/no-custom-includes, long-only stand-down, calibrated tick value with the 5% identity rule). Preset checks extended: shared magic 7788075, LIVE submits / FINAL does not, and drift between them is confined to declared keys (`InpLiveExecution`, `InpTickRecordEnabled`) — anything else is intent drift.
- **The fill-parity invariant is positional and mutation-tested:** the suite fails unless the per-tick hard-exit call sits inside `OnTick` BEFORE the bar guard (moving it after the guard — the bar-open regression class that priced −8.3R/window — was simulated and caught), unless hard exits fill AT the resting level with STOP checked before TP, and unless management exits (PLOCK/ECUT/TIME) stayed bar-granular. `PaperOpen`'s body is audited to contain no order-send calls.
- **Suite result: 24/24 green;** the mutation check on the parity invariant caught the planted regression; the CLI (`python scripts/verify_go_live_artifacts.py`, exit 0, `--deployed-live` byte-compare preserved) still satisfies the GO_LIVE_CHECKLIST/PRODUCTION_CONFIGS contract. Full local suite after the change: 1316 passed, 15 skipped, 0 failed.
- **Docs de-staled with it:** PRODUCTION_CONFIGS.md rewritten from the unshipped v27.00 contract to the deployed v26.38 line (per-tick subsystems, fill-model parity, governor/fleet-guard/fit-router entry flow, verified-append writers); GO_LIVE_CHECKLIST's banner-expectation rows now expect `v26.38` with a note that the live book's fills are unchanged by the parity fix. #property version on V75MacroEngine ("2.22") still lags its ENGINE_VERSION banner macro ("2.23") — surfaced informationally in the verifier output rather than asserted, since MQL5 cannot take a macro there.

## [v26.38 PAPER FILL-MODEL PARITY — hard SL/TP now fill per tick at the resting level, ending the machinery-vs-strategy confound in the gate] - 2026-09-15

### Fixed — mql5/MITEMSHUB_AI/MitemshubAI.mq5: the paper book's exit cadence no longer differs from the live book's
- **The defect and its price:** `OnTick` returned early unless `new_bar`, so `PaperManage()` (arms A/B) evaluated the virtual ladder once per M15 bar, while the live engine sends resting SL/TP with the entry order and the broker fills them intrabar. The fill-cost stress protocol (`docs/FILL_COST_STRESS_PROTOCOL.md`, artifacts `fill_cost_stress_decision.json`) priced this exactly: on the certified 60-day window, touch-fill control +4.12R vs engine-mirror −4.18R — **−8.3R/window of pure machinery**, attributed to the TP-cadence term (18 rides-back −3.65R; 7 intrabar TPs that a bar-open model books as SL −6.66R; stops nearly identical). A gate adjudicating this data would rule on machinery, not strategy. Arm C (V75MacroEngine v2.23) already filled per tick (`PaperCheckExits()` before its M30 gatekeeper) — the defect was arms A/B only.
- **The fix (strategy untouched, entry path untouched):** new `PaperCheckHardExits()` runs on EVERY tick before the bar guard, mirrors resting-order semantics (long: bid<=SL → fill AT SL, bid>=TP → fill AT TP; shorts on ask; STOP checked before TP when one tick spans both). `PaperClose(reason, exit_price=0)` takes an explicit fill price for resting-order exits; management exits (PLOCK/ECUT/TIME, BE, trail) deliberately remain bar-granular — they are decisions, not orders. Fill-at-level is the no-slippage mirror of a broker's resting fill; slippage remains a separately measurable stress overlay.
- **Pre-registered agreement, not a new baseline:** TJ2's `--mode baropen` (adjudicated MATCHED, +0.022R, CI95 covers 0, reason-agreement 0.846, zero exit-price violations) models exactly these semantics — management at bar opens, SL/TP boundary hits per tick. The engine now implements the baseline that already reconciled; no TJ2 amendment needed.
- **Era boundary (append-only, docs/OPERATING_SUMMARY.md §4):** trades closed before this deploy carry bar-open fills; trades after carry per-tick fills. Mixing regimes in one expectancy statistic would measure the change, not the strategy — the 30-trade gate clock restarts at the boundary. Arms keep their virtual equity (continuity preserved), and the −8.3R handicap is now understood as machinery cost, not strategy evidence — the 23 collected trades remain honest data about the OLD sim.
- **Live verification (timestamped):** FB9A `[v26.38]` init 19:58:03 — state restored ($30.73, dailyPnL −6.36, cooldown 3→2→1 across bars), tick recorder ON, FIT ROUTER TOLERATED, arm C v2.23 $50.00; 71BF `[v26.38]` init 19:52:35 — $42.72 restored, recorder ON. Compile 0 errors/0 warnings (49E0 staging + all trees via sync build gate); manifest re-pinned deliberately (`mql5/MITEMSHUB_AI/MitemshubAI.mq5|26.38|4c9e5bd9…`); morning_status all green post-restart.
- **Deploy incident, honestly logged:** the first relaunch used `/portable` on the default-install terminal, silently redirecting its data path away from FB9A (no journal, no logs for ~6 min; 71BF, a local install, was unaffected). Killed, relaunched without the flag, verified via the terminal's own log (`data folder` line) before re-checking banners. Also noted pre-restart: arm A's 19:30/19:45 signals were REFUSED by the 20% cap (min-lot risk $6.57 > cap $6.15) — the paper arm at $30.73 is already partially strangulated, matching the VSG floor prediction live.
- Pre-existing test debt flagged, not introduced here: `tests/test_go_live_artifacts.py` pins the obsolete v27.00 V75 shape and fails on the untouched worktree (7 failures predate this change).

## [VSG study executed: NO at $150 — V1's 10% risk breaches the DD line (52.1% > 45%) and V2's stop grid confirms the intra-bar-noise prediction; the adjudicator ships tested] - 2026-09-15

### scripts/study_frozen_certify_v75.py --risk-frac + docs/VIABLE_SCALE_GEOMETRY_STUDY.md §6 results + scripts/adjudicate_arm_c.py + tests (18/18)
- G0 control PASS — exact reproduction on the pinned harness (n=114, +4.37R, funnel identical: 2727/10/0/1002/45, streak 6, loss rate 54.4%); the new --risk-frac lever (added to the harness because V1 had no risk parameter; default 0.005 keeps the certified path byte-identical, proven by G0 itself).
- **V1 (risk 10%, E=$150): FAIL G1** — 0 refusals and materiality trivially clean (identical trade sequence), but max DD 52.1% breaches the frozen 45% line. The §1 frontier projection (31.0%) was wrong and the pre-registered rule right: the engine's 0.75^consec volume scaling compounds multiplicatively (0.9^6 ~= 0.53 through the certified 6-loss streak), so the percentage regime's binding constraint is multiplicative DD, not strangulation. Survivability != admission.
- **V2 (stop-mult 1/3 | 0.5 | 2/3 at 0.5%): ALL FAIL, noise prediction CONFIRMED** — meanR -0.13/-0.10/-0.10 vs the +0.038 control (materiality bar 0.02 kills all three); sm=0.5 passes the G2 hit-rate bound (+2.9pp) yet still loses 0.14R/t; sm=2/3 also breaches G1 DD (50.2%). Tighter stops convert intra-bar noise into stop-outs exactly as pre-declared (median intra-bar range 0.541R).
- **Verdict: the §4 NO-at-$150 branch fires.** Live-authorization floor for the current geometry stands at ~$226 (10%-risk) / ~$1,446 (1%-risk), with the sharper warning that 10%-risk must expect a ~50% DD through its own certified streak — any future scale study must freeze BOTH an admission floor and a DD-survivability bound. Arm C stays collection-only.
- scripts/adjudicate_arm_c.py written and tested BEFORE any candidate data exists (18/18 synthetic-ledger tests): unified OPEN/CLOSE/EQ parser (both engines), G1-G5 incl. the G5 window-min-equity floor with sub-case (a)/(b) classification, G4 banner-diff contamination gate (UNVERIFIED -> INVALID when journals cannot verify it), G1 <30 as a schedule gate (KEEP COLLECTING, never a statistics verdict), daily-paired t with the 13/14 tie-breaker, full frozen decision mapping.

## [Arm-C adjudication gains G5 — the strangulation floor is now checked at verdict time, not just at activation; a strangled window is INVALID, never adjudicated] - 2026-09-15

### docs/ARM_C_TEMPLATE.md amendment (append-only) + cross-links (GO_LIVE_CHECKLIST floor amendment, OPERATING_SUMMARY arm-C branch)
- The hole closed: the ~$226 floor was an activation precondition (§4) only — nothing re-verified it at adjudication, so a candidate could start compliant, eat its own certified worst streak mid-window, and pass G1-G4 on a sample whose tail trades were collected strangled (the L1 death mode laundering itself into a statistics result).
- **G5 mechanics, frozen:** arm C's window-minimum equity (ledger EQ rows) must be >= the ATR monitor's `floor_certified` at every point of the window — the minimum, not the end value, because equity can dip below the floor mid-window and recover. Single source of truth: `strangulation_floor` block in `atr_drift_monitor.json`; k and s are never re-derived by the adjudicator; a stale block (>8 days) fails G5 as a data gate, same class as a dead ledger. Implemented in `scripts/adjudicate_arm_c.py` (code-checked, not prose-checked) when that tool is written.
- Two failure sub-cases, different paths: (a) floor rose above equity (ATR drift) -> append-only floor amendment, fresh window at the amended floor; (b) equity fell below a stable floor (the streak death mode) -> window INVALIDATION, not a candidate verdict — no REJECTED recorded, the no-re-adjudication ban is not triggered, re-collection allowed at compliant equity under the same template. Strangulation biases the daily-paired series itself (cap-bound days admit a thinned, adversarially-selected subsample), so no statistic on it is interpretable — same INVALID-only logic as the G4 contamination gate.
- Consequential edit to §3's mapping: CONFIRMED now requires G1-G5 all clean; REJECTED/INCONCLUSIVE unchanged (a verdict on a G5-failing window is not a verdict at all).

## [Viable-scale geometry study pre-registered — the ~$226 floor question answered by frontier, not judgment; 10%-risk or nothing at $150] - 2026-09-15

### docs/VIABLE_SCALE_GEOMETRY_STUDY.md — new frozen protocol + cross-links (GO_LIVE_CHECKLIST, OPERATING_SUMMARY arm-C branch)
- The strangulation-floor amendment left one question open: can ANY risk input + stop sizing make arm C viable at $150? The study re-prices from the certified replay's own 114-trade sequence (per-trade stop distances, R sequence, frozen k band) — percentage-regime bisection for min-lot refusals: 1% needs $1,446 (the known static result), 5% needs $268, 7.5% is admitted but every entry is refused, **10% needs $138 with 0 refusals and max window DD 31.0%**; 12.5%/15% breach the DD freeze line. Cross-check: percentage regime needs E >= s/r = $205 + the after-streak buffer = $225.54 — the strangulation floor reproduced by an independent derivation.
- Answer space frozen to exactly two candidates: **V1 risk-input only** (InpRiskPercent 1.0 -> 10.0, unchanged 2.0 x H1 ATR(14) geometry; each stop -10%, worst -18.9%) and **V2 stop-scaling only** (s* in {1/3, 0.5, 2/3} at 1% risk), with V2's trap pre-declared: median intra-bar M15 range 0.541R >= the scaled stop, so the stop-hit rate must rise mechanically — gate G2 bounds it at +5pp over the control's 54.4% or V2 is falsified. Nothing else is a candidate (wider stops raise s and the floor; hybrid cadence already killed by its own gates; TP is arm B's duel).
- Gates G0–G3 frozen before any run: G0 harness re-pin (the NO-GO drill's amendment), G1 survivability (0 refusals, DD <= 45%, n >= 100), G2 the V2 noise bound, G3 winner -> hypothesis doc -> fresh window -> arm-C paper under the frozen adjudication rule — plus a materiality bar (mean R/t regression > 0.02 kills any variant: re-pricing scale cannot manufacture edge). Pre-declared outcome mapping includes the honest NO-at-$150 branch (checklist floor becomes ~$226 at 10% / ~$1,446 at 1%; arm C stays collection-only). Not yet executed; results append to the study.

## [Strangulation floor computed — the sizing truth table's static admission misses the L1 death mode; honest minimum is ~$226, not $100] - 2026-09-15

### GO_LIVE_CHECKLIST amendment (append-only) + atr_drift_monitor strangulation_floor block + ARM_C_TEMPLATE precondition update
- The hybrid study's L1 book died by a mechanism the frozen table never modeled: min-lot risk is PINNED in dollars (broker volume floor) while the 20% cap shrinks with equity, so a loss streak strangles admission below a computable floor. Mechanics validated against observation — L1 died at equity ~= risk$/0.20 with 589 risk-cap vetoes. Formula, frozen: eq_floor = s x (k+5) — 5s static admission + k*s absorb the worst certified streak + s trade again after it.
- Inputs cited, not remembered: k = 6 (cert_report_fresh60_tp18_net.json worst_loss_streak field, n=114; arms observed 5/3 at n=14/9, consistent), s = $20.50 (p95 worst min-lot stop, ATR reading #6). **Certified floor $225.54; tail k=7 $246.05; engineering s=$28 $308.00 — all above every frozen row ($50-$150).** The $100 MINIMUM-VIABLE and $150 RECOMMENDED-BUFFER rows stand for static admission but do NOT survive a certified-replay streak unstrangled (at $150 the streak's tail ends below the $30 cap, which then refuses everything).
- Consequence recorded: the arm-C branch's precondition now reads $100 minimum to trade at all, ~$226 minimum to survive the config's own worst certified streak; between them is a strangulation-prone regime (the L1 death mode). The weekly ATR monitor re-derives the floor every reading (strangulation_floor block); a floor above actual account equity is an amendment-grade finding. Truth-table re-derivation unchanged this reading (WATCH on the $100 static row).

## [TickRecorder live on both MitemshubAI hosts — every future arm exit is forensically exact; a .chr text-edit corruption caught and repaired in the process] - 2026-09-15

### mql5/MITEMSHUB_AI/{VOL75_FINAL,VOL75_TP24}.set + chart inputs + morning_status canary — playbook finding F3 closed
- Design established from the module source before enabling: the recorder writes a per-TERMINAL, per-SYMBOL file (MITEMSHUB_ticks_Volatility_75_Index_<day>.csv, ts/bid/ask/mid), so ONE recorder per terminal is correct — arm A on FB9A also covers arm C (same feed, same symbol; V75MacroEngine has no recorder module and the artifact test pins it include-free). Arm A + arm B recorders cover all three arms' forensics. Enabled in the repo presets AND byte-surgically in the arm charts (InpTickRecordEnabled=true, flush 100 ticks / 10s).
- A restart for the chart surgery silently dropped both arm EAs (charts loaded EA-less for ~21 minutes, 12:44-13:05): my first .chr edit used text-mode UTF-16 writes that doubled the file's newline structure and MT5 refused to restore the EA (chart03, unedited, loaded fine — the discriminating evidence). Restored from the pre-surgery backups, re-applied via byte-exact insertion with a round-trip assertion (new == backup + insertion only, proven), relaunched from a verified-zero-process state (the prior "relaunch" had hit already-running terminals — Start-Process is a no-op then, and a sloppy grep presented stale 12:19 banners as fresh). Missed M15 evaluations: 12:45 and 13:00, identically on both hosts (one shared stream; no differential effect on A/B, no positions open during the gap).
- Verified end-to-end: [TickRecorder] ON in both journals, CSVs live and growing (377/376 rows, 3s fresh, identical last-tick = shared feed), morning_status gained a TickRecorder canary (missing/stale >15min archive on a MitemshubAI host = unhealthy; V75MacroEngine charts correctly skipped), presets synced to Common so the weekly preset-drift check stays consistent. All three arms healthy: A 14/30 ($30.73), B 9/30 ($42.72), C 0/30 ($50.00) — gate clock unchanged.

## [Funnel diff automated — the playbook's Step-4 output contract is now one command, with journal-expiry counts archived forever] - 2026-09-15

### scripts/funnel_diff.py — new tool + paper_weekly §5 + playbook §4 registration
- The NO-GO drill ran Step 4 by hand; finding F4 (journal retention ~6d vs the 60d replay window) meant those counts rot. The new tool emits the playbook's exact output contract on demand and as the weekly pipeline's §5 leg: per-counter rates (replay per 1000 of funnel.score, live per 1000 of the arms' combined sig events — the shared-stream denominator from the 09-15 measurement), frozen verdict words, and a cumulative funnel_diff_history.json so expiry can never silently destroy counts again.
- Honesty guards frozen: counts < 5 -> LOW-COUNT (window-limited, never drift evidence); meta-label/time-block/family-throttle nonzero either side -> CONFIG DRIFT; account-guard classified PER FIRING against the v26.37 deploy — all-pre-deploy = CLASSIFIED closed class (informational), any post-deploy firing = DEFECTIVE (new defect, never blended into strategy causes). First automated run: 0 flagged — funnel clean; the 07:47:04 firing correctly classifies pre-v26.37.
- Two tool defects caught on its own first run and fixed before registration: day-slice [:10] kept the log extension (breaking timestamp parse and silently dropping the firing classification) and the account-guard verdict word mislabeled a fully pre-deploy history as DEFECTIVE. The buggy first run's history row was removed (my own artifact from this session); the live numerator cannot be attributed per-instance (same EA/symbol both hosts) so denominator = A+B sig events combined, recorded in the artifact.
- Playbook §4 now names the tool as the standard Step-4 producer with the real-execution usage (--replay pointing at the rebaseline run's cert report, so the funnel comes from the same run R1 validated). Weekly pipeline re-run: [5] leg green.

## [ACCOUNT GUARD fleet-basis defect fixed in v26.37 — the funnel diff is clean of the class before the gate adjudicates] - 2026-09-15

### mql5/MITEMSHUB_AI/MitemshubAI.mq5 — FleetOpenRisk mirrors the virtual book in paper mode
- The drill's Step 4 counted the known defect live (account-guard 1x on FB9A). Root cause pinned: the cap side was paper-aware since v26.35, but the fleet-sum operand iterated real account positions only — structurally $0.00 in paper mode, blind to the instance's own virtual position. Fix: when PaperActive() and a virtual position is open, FleetOpenRisk adds its risk at the ORIGINAL stop (g_pp_orig_risk) with the calibrated tick value — exactly how the live loop values a real position (a trailed/breakeven stop would flatter the number identically live). Live path byte-identical (PaperActive() false). Both call sites (guard veto + Comment panel) covered by fixing inside FleetOpenRisk.
- Diagnosis honesty: the 07:45 refusal was the total-risk guardrail firing CORRECTLY on paper numbers (min-lot $6.01 > 15% x $37.09 = $5.56, arm A flat) — the fleet blindness produced a $0.00 panel operand and misattributable veto classes, not that refusal. The fix makes the guard truthful; it would not have admitted the signal.
- Deploy discipline: v26.37 bumped, manifest re-pinned deliberately with the drill-proven rationale recorded in the manifest itself, 0-error/0-warning compile (FB9A tree) then 640 files synced to 5 instances with the build gate passing, both arm hosts restarted by PID, banners verified (v26.37, PAPER MODE, Session=00-00, FIT ROUTER evaluating), virtual equity restored exactly (A $30.73, B $42.72), both arms flat at restart so no force-close, telemetry fresh on both hosts. V75MacroEngine untouched at v2.23. Morning status green: A 14/30, B 9/30, C 0/30 — gate clock unchanged.
- Playbook defect register amended (4 mentions): account-guard paper basis moved to fixed, with the rule that a nonzero paper account-guard count after v26.37 is a NEW defect; rehearsal log gains the closure entry. Test note: the 7 test_go_live_artifacts failures are pre-existing (expect the v27 go-live-artifact line's markers; fail identically with the edit stashed) — not caused by, and not blocking, this fix.

## [NO-GO playbook rehearsed end-to-end on live data (DRILL) — R1/R2/R3 all pass, five findings folded back into the playbook] - 2026-09-15

### docs/NO_GO_BRANCH_PLAYBOOK.md §8 + artifacts/v75_replay/nogo_playbook_drill_20260915.json — the first real execution will not be the first execution
- Step 2 R1 **PASS — exact reproduction** of the baseline of record (n=114, +4.37R, +0.0383R/t, t=0.35, funnel shape identical) from the pinned harness (study_frozen_certify_v75.py), proving the playbook's harness-pinning amendment works under drill conditions. The §2 command sketch itself FAILED verbatim — the spec-integrity guard requires all four spec vars alongside CERT_DATA_DIR, and the CERT_DATA_DIR placeholder was unresolved; the working invocation is now recorded in §7 (findings F1/F2).
- Step 2 R2 **PASS** — baropen-mode reconciler over arm A (14 closed trades; playbook says final 30 — F5): ΔR +0.002, CI [−0.229, +0.341] covers zero, reason-agreement 0.857 ≥ 0.75, zero exit violations → MATCHED. R3 **PASS** — live spread ~7.7% TIGHTER than the 18.5 model (spot 17.08; fill-shift median 8.32 = half-spread at entry): no cost regression.
- Step 3: ΔR/t = +0.0031 (slope +0.0022 × 1.42-unit gap) — immaterial by the frozen ±0.02 band; no spread-regime shift. Drill finding F3: the Step-3 "spread telemetry cross-check" is impossible — the arms' telemetry carries no spread field; fill-vs-mid + the reconciler's fill-shift carry Step 3 alone, and TickRecorder enablement would fix this permanently.
- Step 4: rate-normalized funnel diff, no comparable counter diverges >2× (spread-gate, risk-cap, auto-disable, meta-label, time-block, family-throttle all match-direction; replay's 1002 pauses not comparable — its loss-streak stretch predates the ~6-day journal retention, F4). Account-guard fired 1× on FB9A — the known $0 paper-basis defect, counted separately per the playbook. Drill finding F4 also fixed procedurally: Step-4 diffs at real execution must use the overlapping window, or journals get copied into artifacts weekly.
- Frozen outcome mapping: the drill would map to Outcome A mechanics — deliberately NO edge statement; edge adjudication stays TJ1's job. Playbook §8 (rehearsal log, append-only) opened; changelog carries the R1/R2/R3 table per the playbook's own output contract.

## [Weekly ATR-drift monitor registered — the frozen $28 sizing bound is now revalidated from live data every paper_weekly run] - 2026-09-15

### scripts/atr_drift_monitor.py — new tool + paper_weekly §4 + protocol registration
- The arm-C sizing truth table froze min-lot stop-risk at $10.00–$17.85 from 8 tester fills — a function of H1 ATR(14) (SL = 2.0 × H1 ATR, V75MacroEngine.mq5), which drifts with the volatility regime. A drifting ATR silently invalidates the $100 MINIMUM-VIABLE floor (a formal arm-C-branch precondition). The monitor re-derives the whole table weekly from live H1 bars (1000-bar lookback, Wilder iATR replication) via the per-fill calibration chain k = risk$/volume/stop-dist read back from the surviving tester ledger (all 8 fills re-derived, band reproduced exactly).
- Frozen verdict tiers on the **p95 ATR geometry**: HOLD (≤ $20 worst stop) / WATCH ($20–24, $100 row stale → review) / AMEND (> $24, formal append-only amendment required before any live decision cites the table), symmetric SHRINK-WATCH at the low tail (≤ $5), CALIBRATION-DRIFT caps at WATCH, SKIPPED-STALE on a feed older than 3h (never HOLD on old data).
- **First reading fired WATCH on day one**: p95 ATR 688.8 → worst min-lot stop $20.50 vs the $100 row's $20 budget; $100 re-derives as PARTIAL at the tail, $120/$150 hold; today's band [10.86–18.12] still brackets the frozen [10.00–17.85]. The table is sound at the median and marginal at the volatility tail — exactly what WATCH means. History: artifacts/v75_replay/atr_drift_monitor.json.
- Registered in GO_LIVE_CHECKLIST (validity-monitor section, verdict tiers, first reading) and ARM_C_TEMPLATE §4 (AMEND suspends the template's preconditions until the amendment lands); wired into paper_weekly as section [4] with NEXT-ACTIONS propagation and a monitor crash can never take the weekly leg down. Unit checks: Wilder ATR vs synthetic ramp, band math, verdict boundaries, row re-derivation, calibration reproduction — all pass; full pipeline re-run green (weekly leg CERTIFIED).

## [Arm-C adjudication rule pre-registered — the arm-C branch is now executable, not aspirational] - 2026-09-15

### docs/ARM_C_TEMPLATE.md — frozen before any candidate config exists, per OPERATING_SUMMARY §3
- The tree's arm-C branch required "a NEW pre-registered adjudication rule (candidate vs arm A reference) BEFORE the candidate's 30th trade" — now written, frozen, and fill-in-the-blank only at activation. Key design facts, all measured not assumed: the two engines do NOT share a signal stream (arm_b_rate_decomposition_20260915.json), so the A/B nearest-epoch pairing cannot transfer — the rule is a **daily-paired concurrent-window design** (d_i = meanR_C(day) − meanR_A(day), Welch t vs 0) with arm A as the reference stream.
- Gates G1–G4 frozen: ≥30 closed trades; ≥21 days coverage with A alive; ledger integrity (WLOST quarantine, unmatched CLOSE, canary alarms); input-contamination check vs the activation snapshot. The hybrid-study lesson is built in — C's veto/skip funnel is diffed against A's and reported, so the $50-scale risk-cap strangle confound can never masquerade as an edge result.
- Verdict mapping frozen: CONFIRMED (n_d ≥ 15, T ≥ +1.0, mean(d_i) > 0, totalR_C ≥ totalR_A, all gates clean → LIVE preset changes only through the certified chain); REJECTED (T ≤ −1.0 → teardown, no re-tuning); INCONCLUSIVE (collect to n_d = 30 paired days max, then REJECTED-with-honor — INCONCLUSIVE is never read as encouraging, same discipline as TJ1). Scarcity tie-breaker points at INCONCLUSIVE, never at a verdict.
- Preconditions wired to the standing rules: TJ1 adjudicated uncontaminated first; candidate entered through the study chain; the sizing truth table's $100 minimum-viable floor is a formal precondition (below it G1 is unreachable — the geometry is INERT). Teardown unchanged. Cross-linked from OPERATING_SUMMARY §3 and the GO_LIVE_CHECKLIST sizing section.

## [Spike-continuation study: the cascade-correlation claim is a market-level fact — 516 spike crossings continue, controls revert] - 2026-09-15

### docs/SPIKE_CONTINUATION_STUDY.md — position-free design frozen before the run; single run adjudicates the claim
- The stop-gap decomposition's "spike fills land into cascades" rested on 2 paper trades. This study tests it on the whole tick corpus (3.88M ticks, 8,640 M15 bars, 07-07→09-02) with **no positions involved**: 2,421 events where price crossed a 1R-away level, split by the frozen signature — spike (crossing within 10min + range > trailing-p90), fast-control, slow-control.
- **Primary (frozen): Δ2min = +0.1785R (spike minus slow), permutation p < 0.0001, CI [+0.153, +0.204]; sign consistent at 30s and 8min → CLAIM TRUE.** Spike crossings continue a median **+0.334R further within 8 minutes** with **78.5%** probability; fast-but-ordinary crossings *revert* (−0.15R) — it is the spike signature, not speed alone. The paper-measured 0.251R overshoot sits inside this distribution.
- One implementation bug caught before any result was read (list-index-vs-epoch base in the speed test forced all events "slow"); the fix touched only that base, not the frozen definitions.
- Consequences recorded: the hybrid study's L1 book (ladder + measured overshoot) rests on validated mechanics — its risk-cap strangle finding stands; the "structural, not luck" verdict gains a market mechanism with ~260× the original evidence. Caveat kept: position-free proxy level (prior close ± 1 median-TR); exact engine per-fill overshoot still best measured via paper stream or an enabled TickRecorder.
- Tool: `scripts/spike_continuation_study.py`; artifact `artifacts/v75_replay/spike_continuation_20260915.json`.

## [Hybrid exit study: pre-registered, run, and FAILED — the frozen gates kill the candidate before paper] - 2026-09-15

### docs/HYBRID_EXIT_STUDY.md — hypothesis frozen before implementation; result appended same-day (§7)
- **G0 (control) first caught real harness drift:** the worktree `certify_v75.py` no longer reproduces the certified baseline (n=84, −14.57R vs n=114, +4.37R — it gained micro-fit 1.5% and the sd ≥ 107.7 min-stop floor since the 09-05 commit `841bf97`). Study rebuilt on a frozen snapshot `scripts/study_frozen_certify_v75.py` (HEAD + only the registered exit-mode patch); H then reproduces the baseline **exactly**. The NO-GO playbook's R1 amended to pin harness versions.
- **Three books, one shared signal stream, identical management:** H (first-touch stops + bar-open management = the hybrid) +4.37R/n=114; L0 (engine bar-open ladder mirrored, ideal spike fills) −2.36R/n=117; L1 (ladder + the paper-measured −0.251R spike overshoot) −4.61R/**n=6**.
- **G1 FAIL:** H−L0 mean ΔR **+0.0391R/t** vs the frozen +0.08 bar (t=+1.33, CI [−0.015, +0.099] straddles 0, 3/6 positive folds vs 4/6 required). The hybrid's edge is half the materiality bar and not significant — **the candidate is dead and does not go to paper.**
- **Mechanism finding (promoted, not buried):** L1's book strangled at $50 — the −0.251R/stop drag triggers **589 risk-cap vetoes** until the 20% cap silences entries. At tiny scale the overshoot pathology is an **account-scale problem first**, an exit-model problem second; any future exit work must be sized-aware.
- **Honest bookkeeping:** the frozen books ignore the engine's intrabar TP spike-exit (conservative against the hybrid — G1's failure is not a modeling bias artifact); worktree `certify_v75.py` restored byte-equivalent in behavior to its pre-study state after the study ran (safety run reproduces n=84/−14.57).

## [STOP-gap decomposition amended for the 10th STOP — verdict unchanged and stronger: structural, not luck, not bar-open gaps] - 2026-09-15

- Arm A's 10th STOP (09-15 10:45, SC9, −1.271R) postdates every offline tick corpus (TickRecorder is default-OFF), so the structural test was extended with live-terminal M15 bars via the MT5 API: **1000 bar-opens** (2× the morning's 575). Max boundary jump 0.067R; P(jump>0.1R) still 0%.
- The new exit is a bar-open ladder stop with **0.271R overshoot** — but its boundary jump was only 0.023R: ~0.25R of the cost is **intra-bar drift past the stop**, invisible to the 15-min ladder. Arm B took the identical signal and printed the identical exit price and R — paper-internal reproducibility, not arm-specific luck.
- Aggregates on n=7 gap events: total **−1.760R**, mean **−0.251R**, bootstrap CI [−0.411, −0.114]; **drop-worst robustness (n=6): CI [−0.304, −0.082] — still excludes 0**. Drag −0.185R/day over the 9.50-day span (−0.126R per closed trade). Sign test 7/7 adverse (p=0.016) noted as construction-biased; the magnitude tests carry the argument.
- New conditional test closes the last regime excuse: E[bar-open jump | prior-bar range quartile] is **flat** (0.0134→0.0153R) — big bars do not produce dangerous boundaries, and the two big ladder overshoots occurred after a p91-range and a p8-range bar respectively.
- Counterfactuals updated for 14 trades: ledger −4.160R, every-tick ladder −5.818R, hybrid −2.400R; net cadence package **+1.658R** to the ledger. The hybrid (per-tick first-touch stop + bar-open management) remains the one falsifiable candidate via the certified path only.
- Amendment block appended to `artifacts/v75_replay/stop_gap_decomposition_20260915.json` (append-only, dated).

## [NO-GO branch playbook pre-registered — the day the gate fires becomes procedure, not improvisation] - 2026-09-15

### docs/NO_GO_BRANCH_PLAYBOOK.md — frozen before adjudication
- Fires on exactly one condition: `ab_adjudicate.py` output arm-A negative (or INCONCLUSIVE-negative → read-only diagnostics, collection continues per the standing rule). Excludes the arm-B-wins branch, P3 leg failures, arm C.
- **Step 1 freeze:** byte-copy ledgers, record adjudicator's own numbers, arms keep running, zero knob-touching.
- **Step 2 re-baseline drill:** reproduce `cert_report_fresh60_tp18_net.json` (+0.038R/t, t=0.35, n=114 — the tree's cited baseline, never distinguishable from zero) on the fresh-60-day window with acceptance checks R1 reproducibility / R2 stream-vs-replay (baropen-mode TJ2 bars) / R3 cost regression (>10% live-vs-model spread gap).
- **Step 3 spread pricing:** the frozen +0.0022R/t-per-unit slope from the tier study (−25-unit bar to clear +0.08R/t; zero-spread ceiling already failed materiality) — live mean spread measured from fills+telemetry, priced ±0.02R/t materiality, venue hunting explicitly closed.
- **Step 4 funnel diffs:** replay funnel (`certify_v75.py`: score/spread-gate/risk-cap/paused/time-block/auto-disable/family-throttle/pb-failure-classifier) vs live journal greps of the v26.36 SKIP/SUPPRESS print strings, **rate-normalized per 1000 signals**; account-guard's known $0 paper-basis defect counted separately so a machinery cause can't masquerade as an edge result.
- **Frozen outcomes only:** A (stream healthy, edge absent → config retired from live consideration, collection continues as research), B (machinery cause → certified-chain fix + one pre-declared re-adjudication), C (cost regression → re-price at live spread; collapses into A). Hand-tuning illegal under every outcome; re-entry to live consideration requires hypothesis doc → VALIDATED-CANDIDATE on fresh window → new arm ≥30 trades under new pre-registered rule → go-live gate, in that order.
- Cross-linked from the decision tree (`OPERATING_SUMMARY.md` §3 branch) and `GO_LIVE_CHECKLIST.md`'s verdict item.

## [Arm B rate decomposition — 8-vs-13 is uptime, not TP geometry and not the 24/7 switch] - 2026-09-15

### Question: is B's slow trade rate (8 closed vs A's 13) the TP 2.4 geometry or the session change?
- **Neither.** OPEN rows prove one **shared signal stream** (identical entry epochs/tags across arms on shared bars — 16 distinct entry events). The arms diverge only by availability: B missed the 5-entry 09-10..11 block while its host was offline (71BF added 09-14, ~14h less live clock than A), and B missed one signal to restart-repair cooldown. TP 2.4's blocking cost is measurable and tiny: median holds differ by ~0 bars (2.75h vs 2.6h), TJ1-era in-trade overlap 4.4% → **~0.1 expected lost entries** of the 5-entry gap. Rate while both were live and on-session: 1.18/day (A) vs 1.06/day (B) — near-identical.
- The 24/7 switch has **zero negative effect** — it strictly widens the shared signal window; the residual `SESSION-OFF` prints come from pre-restart loads still carrying the contaminated 06-21 window (FB9A showed 3× `Session=06-21` loads before its 08:16 `Session=00-00` load — the 09-14 16:31 reload is the suspected regression vector; repaired by the morning's preset rewrite).
- Side-findings for follow-up: (1) B's 06:47 entry was force-closed by the 08:16 upgrade restart via the historical-restore path; (2) A's 07:45-bar signal was refused by the fleet **ACCOUNT GUARD** reading fleet equity as $0.00 in paper mode — fleet-equity basis under paper needs a look; (3) one pre-restart B fill (07:47 v26.35) never reached the ledger (restart-closed) — verified writers intact.
- Recorded in `artifacts/v75_replay/arm_b_rate_decomposition_20260915.json`.

## [Arm C minimum viable size pre-registered — $100 floor, $150 buffer, own truth table in the go-live checklist] - 2026-09-15

### Pre-registration — frozen before any arm-C sizing decision exists to bias it
- Grounding frozen from the v2.23 tester measurements (8 real fills, stops 1121–1466 pts): **min-lot (0.01) stop-risk $10.00–$17.85, typical $14–17.85**, engineering bound ≈ $28 at the 2× median-ATR stop. Production 1%-risk input can never fit this geometry below ~$1,800 — a live attach would require a pre-registered risk-input change through the certified chain, never a silent edit.
- Truth table ($50–$150, per the global 20% cap): **$50 INERT (measured — every entry refused)**; $75 NOT VIABLE (unpredictable partial admission); $85 MARGINAL; **$100 MINIMUM VIABLE** (all 8 measured geometries admitted); $120 headroom; **$150 RECOMMENDED BUFFER** (covers the ≈$28 bound). The knife, stated in the doc: at $100 one stop = −17.9%, and the arms' observed 3-loss streak compounds to ≈ −45% on running equity.
- Governance: the truth table is a **precondition, never an authorization** — live arm C additionally requires the arm-C branch (VALIDATED-CANDIDATE + pre-registered adjudication, `OPERATING_SUMMARY.md` §3); until then its FB9A run stays a collection-only regime exercise. Amending the frozen numbers requires a protocol amendment.
- Recorded in `docs/GO_LIVE_CHECKLIST.md` (new "Arm C sizing truth table" section beside the arms' $50 table).

## [STOP-exit gap decomposition — the cost is real but NOT bar-open gaps; the bar-open cadence package is net +1.9R on the sample] - 2026-09-15

### Question — how much did bar-open gap slippage cost arm A's 9 STOP exits vs the tick ladder, and is it structural or luck?
- **The cost is real and located:** 6 of the 9 STOPs were original-stop hits; total gap-through **−1.489R** (mean −0.248R/stop, bootstrap CI [−0.433, −0.089] — excludes 0), i.e. −0.29R/day over the 5.09d window vs the certified replay edge of ~+0.10R/day. Split: 4 bar-open-ladder exits −0.457R, 2 per-tick spike-path exits −1.033R.
- **But the hypothesis is dead:** measured over all 575 bar-opens in the window, V75 **does not gap at bar-opens** — max jump 0.048R, P(jump>0.1R) = 0%, E[jump | jump>0] = 0.014R, and 3 of the 4 ladder-exit overshoots sit right at that expectation. The two big overshoots are spike-path fills into intra-bar cascades, at the 15th and 69th percentile of the ordinary intra-bar range distribution (median 0.539R) — correlated with their own trigger, not freak luck.
- **The offsetting side of the same cadence:** the bar-open ladder lets winners ride past where an every-tick ladder would cut them — +1.833R (TP 2.521 vs ladder SL 0.688), +1.320R (TP vs PLOCK), +0.265R — total **+3.418R**. Net cadence effect on the sample: **+1.929R in the ledger's favor** (ledger −2.889R vs every-tick-ladder −4.818R).
- **Counterfactual table (diagnostic):** every-tick ladder −4.818R; ledger as-run −2.889R; hybrid (per-tick first-touch stops + bar-open management) −1.399R. The hybrid is a falsifiable candidate, nothing more — it changes engine behavior and must go through the certified path (study → fresh window → paper arm); n=13 makes all of this fragile.
- Verdict: stop gap-through is **structural (intra-bar path continuation vs 1R stops), not bar-open gaps and not luck**; the engine's bar-open cadence was net-positive on this sample and must not be "fixed" by hand. Evidence: `artifacts/v75_replay/stop_gap_decomposition_20260915.json`; the reconciliation artifact re-finalized in baropen mode (MATCHED).

## [Sunday pipeline dry-run — all four legs verdicted; two leg crashes fixed; recon leg moved to the bar-open baseline] - 2026-09-15

### Fixes — pipeline legs that silently died on today's run
- `paper_weekly.py` crashed with `UnicodeEncodeError` under the pipeline (child stdout through pipes used the cp1252 console codec; the report's `→` is unencodable). Fixed: the tool reconfigures its stdout to UTF-8-replace; the pipeline decodes children as UTF-8 (and emits UTF-8 itself), with `PYTHONIOENCODING=utf-8` exported to every child. Leg verdict restored: **CERTIFIED**.
- `regime_gate_study_v3.py` crashed with IndexError: its v2 clean-OOS context block slices `build_folds()[16:]` — defined on the retired 210-day window's 26 folds, but the current certified dataset is the fresh 60-day window with 7 folds. The block now skips honestly with an explanatory note when F17-F26 don't exist (the paper branch and its pre-registered verdict are unaffected); the 0-closed-trades path also prints its `Verdict:` line so the pipeline can parse it. Leg verdict restored: **KEEP COLLECTING (no closed paper trades)**.
- `paper_pipeline.py` recon leg now runs the reconciler with `--mode baropen` (amendment 2026-09-15 — the engine evaluates its ladder per M15 bar-open; the every-tick walk remains available as `--mode tick`).
- Note: `ab`'s ETA arithmetic uses each arm's own observed rate — B's 8th trade was a loss collected slowly, so its ETA reads ~25d vs A's ~7d; the duel adjudicates when BOTH arms reach 30.

## [Paper-ledger writers hardened — verified append with retry + WLOST quarantine; v26.36 + v2.23 deployed to all three arms] - 2026-09-15

### Why — close the silent-row-drop defect class for good (audit found one lost CLOSE row)
- **The class:** every writer in both engines appended with unchecked `FileWriteString`/`FileWrite` results and printed success unconditionally — a failed open/append stayed invisible while the journal claimed the row was written. That is how arm A's ledger lost trade #5's CLOSE row (2026-09-08 00:30) without a trace.
- **The fix (`AppendVerified` in MitemshubAI v26.36, `AppendVerifiedV75` in V75MacroEngine v2.23):** a row only counts as written when the bytes are **verified on disk by re-reading** (file size must have grown by the row length after close — deliberately not trusting `FileFlush` return values, which this MQL5 compiler build returns as void); one retry with a 50 ms backoff; a row failing twice is **quarantined to the journal with the `WLOST` tag** including the full row content, so it is loud, greppable, and hand-restorable. Wired into every hot writer: paper ledger (OPEN/CLOSE/EQ), telemetry JSONL, and the trade-history CSV (header handling preserved).
- **Watchdog counterpart:** `morning_status` now scans each arm's today-journal for `WLOST` and alerts unhealthy (the quarantined row never entered the ledger file, so ledger parsers alone can never see it); 2 new unit tests pin the scan. The canary gained telemetry-after-banner as liveness evidence earlier the same day (24/7 quiet bars journal nothing; pinned by 2 tests) and was refactored onto a shared `journal_lines_today` helper.
- **Deploy discipline:** v27 WIP backed up to `MitemshubAI_v27_research_backup.mq5`, v26.35 restored from HEAD as the patch base, hardening applied, bumped to v26.36 (VTAG single-source; no strategy/config change — the arms' equity continuity $37.09/$55.20 and both presets' signatures verified in the boot banners, `Session=00-00` intact). Manifest re-pinned twice after compile-gate iterations corrected my own code (the gate refused my edited bytes both times — working exactly as designed); final shas `48a4d866…` (v26.36) and `2e164ff8…` (v2.23); sync 640 files, build gate green ×5 trees; both terminals restarted and banner-verified on the new builds (all three arms flat during the restart).
- **Validation:** V28 research suite + canary (13) + liveness + collector + V75 surface: **90 passed**. The arm-C tester drill re-run end-to-end on v2.23: production config still correctly refuses every entry at the $50 floor (min-lot guard), config-variant pass produces **8 OPEN / 8 CLOSE / 8 EQ with zero problems, watchdog parse 8 closed / veq 44.61 / no problems, telemetry fill:8 close:8** — the hardened append path produces byte-valid ledgers under real tester fills.
- MQL5 note recorded for future patches: `FileWrite` and `FileFlush` are void-typed in this compiler build (error 151 on return-value use) — byte-count + on-disk re-read verification is the portable pattern.

## [24/7 collection live; three config/integrity defects found and fixed; TJ2 bar-open baseline amendment proves the paper engine MATCHED] - 2026-09-15

### Why — the operator directive: stop gating collection on a session, keep the terminals open, fix every defect found
- **No session gate existed in the engines — it was config.** Both arm charts carried `InpSessionStartHour=6 / InpSessionEndHour=21` (the v26.35 code defaults; the certified presets say 0/0 but were never the source of the chart inputs). Both arms now boot with the certified preset applied byte-exact and the banner proves it: **`Session=00-00`** (FB9A 06:41:10, 71BF 06:41:12). Collection runs 24/7 from the terminals staying open; V75 arm C never had a gate and collected through the nights all along (03:00 telemetry writes).
- **Defect 1 — arm A's chart had silently lost its preset** (most likely in the 09-13 WIP re-attach churn): the chart carried TP 2.4 + Breakout/BandFade ON (v27-style code defaults) instead of the certified FINAL preset (TP 1.8, Breakout/BandFade OFF). The duel was protected by luck, not design: the ledger's own OPEN rows prove **all 13 closed trades ran TP 1.8** (TP/SL distance ratio exactly 1.8 ×13) — the drift happened after the last close. Any fill from the drifted chart would have been off-strategy and polluted the A/B. New tool `scripts/set_chart_preset.py` writes a preset byte-exact into a chart's `<inputs>` block (removes keys not in the preset so code defaults can't masquerade as config), with backup + re-parse verification; both arm charts repaired from the certified presets.
- **Defect 2 — one ledger CLOSE row silently failed to write.** State says 14 trades / −2.3886R; the ledger has 13 CLOSE rows / −2.8886R. Reconciled exactly: 13 rows − 0.50R (trade #5, the STOP +0.456R winner whose close fired on 09-08 00:30) = 14-trade state total. The surviving journal coverage (files for 09-05..07 are gone, MT5 rotation) cannot pinpoint the mechanism, so it stays classed as an unattributed silent write drop; the ledger is the adjudication source and the loss of a winner is conservative. The writer-hardening fix (verified append with retry + loud failure tag) ships in v26.36 rather than an out-of-band change to the certified build.
- **Defect 3 — the collector test asserted a foreign broker's symbol table.** `tests/test_mt5_collector.py` expected `R_75 → SYN75`; live probe via the MT5 API on the operative account (DerivSVG-Server-03) shows **SYN75/SYN100 do not exist** and `Volatility 75 Index` does (bid 45987). Code was right, test was wrong (written against a different Deriv server); test corrected to the operative reality, 5/5 pass.
- **TJ2 closed with evidence (amendment 2026-09-15, pre-registered before bar-open data was scored):** `reconcile_paper_ticks.py --mode baropen` evaluates the ladder on the first tick at/after each M15 boundary (the engine's `new_bar` gate semantics) while keeping SL/TP boundary hits per-tick (the engine's spike-exit path is per-tick). Same 13 trades: **bar-open baseline → ladder delta +0.022R, CI95 [−0.230, +0.382] covers 0, reason-agreement 0.846 ≥ 0.75, zero exit-price violations → MATCHED**; every-tick baseline unchanged (+0.188R / 0.692 → REASON-DRIFT), so the 09-14 result is reproduced, not overwritten. The "drift" was evaluation cadence, not mechanics. Artifact final state: `MATCHED | mode: baropen`. TJ2's arming question is resolved: when arm A reaches 7 days of ledger, the baseline tests the engine's actual hypothesis.
- **Canary amended for 24/7 reality (caught live, false-positive → fixed within the hour):** with sessions off, a quiet bar journals nothing, and the init-silence canary fired on both healthy arms at 06:41+20m. Telemetry is admissible liveness evidence (heartbeats write every bar even when the journal is quiet): the corpse signature remains exactly *banner, then no journal line AND no telemetry write ever*. Live: both arms `canary ok (telemetry written after init)`; 11 canary tests pass including two new pins (telemetry-after-banner ok; telemetry-only-before-banner still alerts).
- Ponytail review (over-engineering hunt) over the new tooling: one dead `import random` removed from the reconciler; everything else lean.
- Full battery: pytest suite green (collector fixed; the rest of the 1,275-test run unaffected by today's changes), sync steady-state 630 files / 0 pruned / build gate green, deploy gate held throughout.

## [Arm C paper-ledger tester validation — CLOSE row proven end-to-end; two v2.21 ledger defects found and fixed (v2.22); arm C config inert at the $50 floor] - 2026-09-15

### Result — the watchdog reads a filled V75 paper trade end-to-end (verdict PASS, with one pre-registered operational finding)
- Drill (`scripts/validate_armc_paper_ledger_tester.py`, new): drives V75MacroEngine v2.22 in **paper mode** through the Strategy Tester headlessly on 49E0 (tester-only terminal; the arms' terminals were never closed — preflight checks the tester *install* is not running, per-install not global), over the cached 71-day real-tick window with arm C's exact chart inputs. Validates every row against the v2.21/2.22 writer schema, replays equity from the ledger's own columns ($50 start), then hands the file to the **real watchdog parser** (`morning_status.parse_ledger`) — the same object the A/B machinery consumes.
- **Variant pass (risk=40%): 8 OPEN / 8 CLOSE / 8 EQ rows, equity replay exact (44.60 == ledger 44.61), R accounting exact per trade, watchdog parse: 8 closed, zero problems, telemetry `fill:8 / close:8` alongside 3407 heartbeats and 1353 signals.** All exits ECUT (2h timeout) — matching the regression gate's established all-timeout pattern on this window for the wide-stop geometry (0 SL/TP hits; the stop is disaster-only by design).
- **Primary finding (pre-declared as a possible outcome, now measured): the production config (1% risk at the $50 virtual floor) is INERT — every entry refused** (`PAPER TRADE REFUSED: computed volume < broker minimum`, max computed volume 0.008 vs the 0.01 min lot). Arm C's 2×H1-ATR stop implies min-lot stop-risk **≈ $14–17 = 28–34% of $50** — the arms' "$50 tolerated at 9–13%/trade" story does **not** transfer to this geometry (their stop is ~$4.6–6.5). The engine's guard behaved exactly as designed (never violating the risk contract); recorded in `docs/GO_LIVE_CHECKLIST.md`: **arm C needs its own pre-registered minimum viable size (~$85–120 at ≤20%/trade) before it can trade anywhere** — until then its FB9A paper run is a collection-only regime exercise.
- **Two v2.21 ledger defects caught by the drill, fixed in v2.22:** (1) the OPEN writer emitted **13 fields** (an extra ATR column shifted every field after col8 off the arms' schema — the A/B adjudicator would misread volume as risk); (2) the `%.5f` SL/TP slots were fed `DoubleToString` *strings*, which MQL prints as `0.00000` — OPEN rows carried zeroed stop/target geometry (the virtual book itself was correct; ECUT-only closes never touched the broken columns, which is why live telemetry looked healthy). v2.22 writes the arms' exact 12-field schema (`OPEN,ts,ticket,dir,entry,sl,tp,vol,eff_risk$,stop_dist,max_hold,tag`), numbers as numbers; CLOSE rows switched from string-arg to numeric formatting in the same pass.
- **Identity discipline:** the first v2.22 deploy still printed "v2.21" in its init banner — a hardcoded string behind on the version bump, caught on the FB9A reload before any restart-dependent validation ran. The banner now derives from a single `ENGINE_VERSION` macro (the canary greps this line as run identity); re-pinned (sha `ad53c09…`), redeployed (0 errors ×5 trees), and FB9A arm C verified live on `v2.22 initialized (…PAPER)` at 01:32. Arms A/B untouched throughout (deploy gate held; B's "stale" telemetry in the same window is the session-off boundary, not a fault).
- Evidence: `artifacts/v75_macro_engine_tester/armc_paper_ledger_20260915.json` (both passes, identities v2.22, verdict PASS, findings block with the refusal measurements); sandbox-clear before each pass documented in the drill (append-only writers would otherwise splice runs).

## [sync-mt5 -AllowWip liveness gate — a WIP must prove it is alive before it may deploy over the arms] - 2026-09-15

### Added — telemetry-liveness evidence requirement on the explicit bypass path
- Closes the last sanctioned-accident path from the 2026-09-13 incident class: `-AllowWip` previously deployed any mismatching worktree source on a bare human assertion — the exact action that froze both paper arms for ~2 days when it happened *without* intent. The bypass is now machine-checked: `sync-mt5.ps1 -AllowWip` runs `scripts/check_wip_liveness.py` (verify mode) against the worktree bytes **before** deploying, and refuses fail-closed when the recorded evidence does not validate them (exit 1, deployed builds untouched, exact staging remedy in the message).
- What counts as proof (pre-registered 2026-09-15, seven conditions C1–C7, all required on at least one terminal): the source declares its own version (bindable banner); evidence comes from a **non-arm terminal only** — any chart carrying 7788075/7788100/7788125 excludes the terminal, since a WIP already sitting on an arm is the incident, not evidence; the staging terminal's deployed source sha256-matches the worktree source and its `.ex5` is fresh (the running build IS these bytes); a version-bound init banner on the EA's own journal channel (today/yesterday, real 4th-field channel format); the banner ≥ one bar-grace old (16m MitemshubAI / 31m V75MacroEngine — at least one bar interval to live); ≥1 post-init journal line (the inverse of the banner-then-silence signature the morning_status canary alerts); and telemetry written **after** the banner.
- Modes: `--collect` probes the running terminals and records `artifacts/deploy_wip_liveness.json` — FAIL attempts are recorded too, the audit trail matters; verify (default, called by sync) re-checks that artifact against the **current** worktree bytes, so any edit after validation re-locks the deploy, and rejects evidence older than 48h (`--max-age-hours`).
- Staging flow (recorded in the `scripts/deploy_manifest.txt` header): copy the WIP into the staging terminal's Experts tree manually (a sync refuses it), compile in place, attach to a chart, wait one bar interval, `python scripts/check_wip_liveness.py --collect --src <src>`, then sync with `-AllowWip`. **49E0** — tester/reserve-only, no arm magics by construction — is the staging terminal (role noted in `docs/OPERATING_SUMMARY.md`).
- Verified: live `--collect` on today's terminals returns FAIL with the correct per-terminal reasons (FB9A/71BF excluded as arm hosts; 49E0/Common/Community fail sha binding against their deployed v26.35 copies) and the artifact records it; `-AllowWip` dry-run now exits 1 with refusal + remedy (previously it deployed); steady-state sync without `-AllowWip` unchanged (630 files, 0 pruned, build gate green, exit 0). 12 new unit tests (`tests/test_wip_liveness.py`) pin every condition with synthetic terminals in the real journal/chart formats — including the 09-13 banner-then-silence signature, the arm-terminal exclusion, byte-drift refusal, wrong-version banners, and the V75 family path (31m grace, own file names). Full suites: 52 passed.

## [TJ2 tick reconciliation on arm A (13 trades) — R agrees, exit reasons drift: the paper ladder runs per bar-open, the baseline per tick] - 2026-09-14

### Finding — pre-registered verdict REASON-DRIFT; mechanism identified as evaluation cadence, not bookkeeping drift
- Run: `reconcile_paper_ticks.py` on arm A's 13 closed trades (2026-09-05 21:45 → 09-11 12:00; **5.09 days close-to-close — formally below the 7-day arming gate**, run as an early look at `--min-days 5`, coverage recorded in the artifact so nothing is overstated). Window ticks auto-pulled read-only from the broker via the MT5 API; ladder constants imported from `study_fastfail_ticks`, so the baseline cannot silently diverge from the study.
- Pre-registered verdict: **REASON-DRIFT** (F3 reason-agreement **0.692 < 0.75**), even though every R-leg passed: mean ladder delta **+0.188R**, bootstrap CI95 **[−0.157, +0.593] covers 0** (not OPTIMISTIC-DRIFT), **zero** exit-price violations (F4), integrity ok, 13/13 simulated, fill-shift **+8.32** ≈ the designed entry-shift conservatism (spread multiplier). Mean abs delta 0.472R.
- Structure of the drift (per-trade table): all four reason mismatches are **ledger-better** — TP-vs-trail divergences (+1.833, +1.320, +0.872, +0.265R) where the ledger rode to target while the tick ladder PLOCKed earlier — while pure-STOP trades show the ledger *worse* than the ladder (−1.63, −1.40, −1.31 vs clean −1.00 exits: gap-through slippage a bar-open ladder cannot see). Ledger mean −0.222R vs tick-ladder mean −0.410R.
- **Mechanism, evidence not theory:** v26.35 evaluates its virtual ladder **once per M15 bar open** — `OnTick` returns early unless `new_bar` (HEAD `MitemshubAI.mq5` ~L1056) and `PaperManage()` sits inside that gate (~L1083) — while the study baseline walks **every tick**. Ledger timestamps confirm it: **11 of 13 closes sit exactly on M15 boundaries** (`epoch % 900 == 0`); the two mid-bar exceptions (the +2.521R TARGET at :724s and a STOP at :898s, with the mid-bar OPEN chained to that TP close in the same second) match the secondary per-tick spike-exit path. Config equality checked first (arm A chart inputs == study ladder: PLOCK 0.5 / BE 1.0 / trail 1.0/0.7), and the engine's ladder code is textually identical to the study's — cadence is the only remaining difference.
- Standing consequence: **TJ2 remains unarmed and unchanged** — the artifact records 5.09d < 7d, and a ≥7d arming would hit the same bar-open-vs-tick gap by construction. The real reconciliation question for the gate is "does the paper engine match a bar-open ladder baseline"; closing it needs either a bar-open replay mode in the baseline or a pre-registered allowance for cadence-driven reason drift. Neither is decided here — the frozen 2026-09-04 rules stay frozen until amended pre-registered.
- Evidence: `artifacts/v75_replay/paper_tick_reconciliation.json` (verdict REASON-DRIFT; arms.A: 13/13 simmed, integrity ok, mean +0.188R, CI [−0.157, +0.593], F3 0.692, F4 0, fill-shift 8.32, days 5.09).

## [morning_status init-silence canary — the loaded-but-dead EA signature now alerts within one bar] - 2026-09-14

### Added — canary anchored on the EA's init banner in its own journal channel
- Closes the detection gap that let the 09-13/14 v27 WIP freeze both arms for ~2 days: the WIP printed its init banner and then emitted **nothing** — no bar processing, no telemetry — across three loads on one terminal, while the existing watchdog only fires on telemetry age > 2h. The canary (`init_silence_canary`) anchors on the arm EA's newest init banner in **today's** `MQL5/Logs` journal (`initialized` / `vX.YZ started`), filtered to the EA's own 4th journal field (`MitemshubAI (…)` / `V75MacroEngine (…)` — sibling EAs' lines and name-prefix collisions like `MitemshubAI_v28` cannot satisfy it), and alerts when the banner is ≥ its grace window old **and** no journal line follows it at all.
- Grace windows are per-EA and must exceed one bar interval, because a healthy EA's first post-init journal line can be its first bar event: 16m for the M15 MitemshubAI arms, 31m for the M30 V75MacroEngine arm. Three non-alert states keep it honest: `armed` (inside grace — no false alarm right after a restart), `ok` with in-window lines (normal), and `ok` for a quiet period (banner at night before the session, resumed later — *later* processing proves life; ongoing cadence after that remains the telemetry-staleness check's job). An `alert` marks the arm unhealthy (strict exit 1) with the banner time and elapsed age in the message.
- Verified live against all three arms (`[OK] canary ok` ×3 — B: 2 journal lines within 16m of its 23:30 init; A: 2 within 16m of the 22:12 restart; C: 1 within 31m) and pinned by 9 unit tests in `tests/test_morning_status.py` using synthetic journals in the exact real line format — including the two traps that would matter in the field: channel isolation (another EA's banner/lines on a shared terminal must neither arm nor satisfy the canary) and the 09-13 scenario itself (banner + silence → alert).

## [Dedicated ARMS terminal — arm B migrated off the tester terminal; paper collection is now isolation-safe] - 2026-09-14

### Changed — the arms own a terminal that research never closes
- Motivation: arm B lived on `MitemshubMT5_B` (49E0) — the same terminal the V75MacroEngine tester requires closed for every regression run, and the 09-13/09-14 tester sessions froze B's gate clock for ~4 days in total. The arms now have a dedicated terminal research tooling must not touch: the idle **`MitemshubMT5_C`** install (data folder **71BF**), which was already credentialed for account 140778269 (journal-proven) and had been sitting powered-off since 09-05.
- Migration performed with the terminal off, mirrors of the arm-C chart activation discipline: B's six `MitemshubAI_*` ledger/telemetry/state files copied byte-for-byte with mtimes preserved; the parked 7788126 rehearsal chart archived (`chart01.chr.bak_parked7788126`, rehearsal Files archived under `_armC_rehearsal_archive_20260914/`) and replaced by B's exact expert block (magic 7788100, `InpLiveExecution=false`), re-parse verified before boot. First boot: authorized in seconds, full v26.35 startup, **`Loaded intelligence: Trades=7 WR=57.1% R=+0.64`** — the accrued history restored from the transplanted state, and a fresh `fit` telemetry event at the next M15 boundary. Zero errors in the journal.
- 49E0 retired as an arm host: EA detached from its chart with backup (`chart01.chr.bak_armB_20260914_233330`), its six arm-B artifacts archived (`_armB_migrated_20260914/`) so no duplicate `B_tp24` magic can ever run from there. 49E0 is now tester/reserve-only — the tester's close-and-relaunch cycle can no longer cost the gate any collection time.
- Verified by the watchdog: `morning_status` reports **2 processes hosting all 3 arms** (B_tp24 + C_v75 fresh; A_tp18 + C_v75 on FB9A), B with **no connection gaps** in its journal window, and ledger continuity intact ($55.20 / 7 closed unchanged). Topology recorded in `docs/OPERATING_SUMMARY.md` and `docs/GO_LIVE_CHECKLIST.md`: **71BF is paper-collection-reserved — tester runs and research sessions must never close it; the tester flow uses the default install (49E0).**
- Standing risk unchanged: FB9A hosts arm A + arm C and the future live chart, so a 49E0-style close never touches them — but if FB9A itself is ever closed for research, both its arms freeze; the strict watchdog (TJ3) is the tripwire either way.

## [sync-mt5 deploy gate — WIP can no longer reach the terminals by accident] - 2026-09-14

### Added — fail-closed sha256 manifest gate on the deploy script
- The 2026-09-13 incident (a routine sync deployed the uncommitted, non-functional v27 WIP over the certified paper arms and froze them for ~2 days) is now structurally closed: `sync-mt5.ps1` evaluates `scripts/deploy_manifest.txt` before touching any terminal, and refuses to copy/compile any EA whose worktree source does not match its pinned sha256 — pinned today: `V75MacroEngine.mq5` = v2.21 (live-validated on arm C), `MitemshubAI.mq5` = v26.35 (the certified arms build, HEAD's copy). The deployed copy is left untouched and protected from the prune pass. Repo-as-source-of-truth is preserved — the manifest lives in the repo and any new pin is a deliberate, diff-reviewable edit (validate → sha256sum → pin → changelog), never an accident of worktree state.
- Overrides: `-AllowWip` deploys a mismatching worktree copy **explicitly** (loud per-terminal bypass notice — the sanctioned path for shipping a validated candidate), and `-DryRun` previews the gate decision, per-file mirror plan, and compile plan without touching anything. Missing manifest ⇒ refuse everything (fail-closed).
- Gate-consistent plumbing: the mirror skips a gated source **and its binary artifacts**; prune (orphan + stale) skips gated files; the LIVE-EA build gate waives staleness for a gated source/binary pair but still fails loudly if a gated EA's binary is **missing** (a terminal restart would not reload it), with the exact remedy in the message; the stale-source check is scoped to the live build's actual inputs (`MitemshubAI.mq5` + includes), so sibling research EAs (`MitemshubAI_v28.mq5`) no longer false-trip it.
- Verified: dry-run on both paths (default denies 1 pin / mirrors 112 files; `-AllowWip` mirrors 113); steady-state sync PASS (630 files to 5 trees, 0 pruned, build gate passed, exit 0); all five deployed trees uniform on v26.35 (source sha `c13b5eb…`, fresh `.ex5`); V75 v2.21 deploys and compiles 0 errors throughout; arms' telemetry uninterrupted.
- **Incident during this change, recorded honestly:** the first gated sync deleted the arms' deployed `MitemshubAI.ex5` binaries from all trees. Two stacked causes, both fixed: (1) a gate check inside `ForEach-Object` used `return`, which skips only one script-block invocation, not the pipeline — the stale-prune then deleted the gated binary; the check moved into `Where-Object` (comment left in the script). (2) A zombie worktree binary `mql5/MITEMSHUB_AI/MitemshubAI.ex5` — the 09-09 **v27 build, gitignored and invisible to `git status`** — was mirrored over the restored binary with `Copy-Item`'s preserved old mtime, which prune 2b then correctly deleted as stale. Running EAs were never affected (loaded in memory); binaries were restored by compiling the deployed certified source in place (0 errors ×5 trees, `.ex5` fresh vs source), the zombie was removed from the worktree (recompilable from the v27 source any time), and two forgotten trees (Common, Community) that still held 09-09 v27 **source** were aligned to v26.35. A gated sync that finds a missing gated binary now names the failure and the fix instead of failing silently.

## [V75MacroEngine v2.21 — PAPER MODE: the engine becomes arm C on its own virtual book] - 2026-09-14

### Added — InpPaperMode: virtual fills, zero broker orders, watchdog-format bookkeeping
- Arm-C machinery applied to the macro engine: with `InpPaperMode=true` the EA runs its full pipeline (H4/H1 alignment, M30 springboard, 1% risk, 2h timeout, 1:2 ATR geometry) against **virtual equity starting at $50** (the same floor the paper arms started on), fills at ask/bid (the exit pays the spread), and **never touches `CTrade`** — no broker order can exist on the paper path, by construction. With `InpPaperMode=false` (default) the binary is behaviorally v2.20: same guards, same constants, same output lines.
- Bookkeeping lands in `MQL5\Files\` in the exact formats the A/B machinery already parses: `V75MacroEngine_paper_<symbol>.csv` (`OPEN,<12 cols>` / `CLOSE,<8>` / `EQ` — the MitemshubAI ledger schema, including the `PAPER` tag where arms store their session id) and `V75MacroEngine_paper_telemetry_<symbol>.jsonl` (per-bar `hb` heartbeat at **every** M30 open *before* any stand-down return — watchdog freshness must not depend on regime — plus `sig` with the trigger outcome, `fill` and `close` events). Virtual equity continuity is enforced through the EQ rows; geometry (entry/SL/TP prices, volume, slDistance, riskAmount) rides the OPEN row like the arms'.
- `morning_status.py` now discovers arm C (`C_v75`, magic 7788125 — the number pre-declared for the first VALIDATED-CANDIDATE in the operating summary's arm-C branch) via the V75 spelling `InpMagicNumber` as well as `InpMagic`, resolves **per-EA** ledger/telemetry names, counts distinct terminals hosting arms for the running-terminals check, and labels arm C as telemetry-only (NOT a gate input — the paper gate remains arms A/B).
- **Activation (2026-09-14 21:02, FB9A chart03):** the magic 7500 **live-capable** chart was re-inputted to paper mode + 7788125 while the terminal was closed (`.chr` backup kept: `chart03.chr.bak_live7500`). The 7788125 reservation on the parked 71BF chart01 (the arm-C template's MitemshubAI chart) was moved to 7788126 (`chart01.chr.bak_7788125`) so exactly one arm C exists. Init banner verified: `v2.21 initialized (LONG-ONLY, 2h timeout, PAPER)` + `virtual fills only`. First heartbeats landed at the 21:30/22:00 M30 opens. Aligned-DOWNTREND means entries wait for an uptrend regime — the arm warms up meanwhile.
- **Account ground truth (same sweep):** FB9A's account 140778269 is **REAL** (`trade_mode: REAL`, $50.22 — the go-live funding precondition is now MET), and all three terminals log into that one real account; paper safety is EA-level throughout. Recorded with the Algo-switch rule in `docs/GO_LIVE_CHECKLIST.md`; arm-C template amended (`docs/ARM_C_TEMPLATE.md`).
- Three defects found and fixed during activation, in order: (1) the first build logged the heartbeat *after* the macro stand-down returns, so a DOWNTREND regime (today's) would never write telemetry and the watchdog would false-alarm a healthy arm — heartbeat moved to the top of the per-bar block (the single-position gate lost in that edit was restored immediately); (2) the writers used `FILE_CSV`, which field-quotes verbatim comma rows and mangles the JSON line — switched to the arms' proven `FILE_TXT|FILE_ANSI|FILE_SHARE_READ` pattern, with loud errors instead of silent no-ops; (3) the file names embedded the symbol with spaces while the machinery convention (and `morning_status.py`) expects underscores — fixed via `PaperSymbolTag()`, existing telemetry renamed in place.
- Evidence: FB9A journal 20:43/21:02/21:35 init blocks; compile gates 0 errors ×3 terminals ×4 builds (final `.ex5` 22:12:00–05); telemetry file with `hb` records at eq 50.00 / magic 7788125; `scripts/morning_status.py` extended in the same pass.
## [V75 regime analysis — no entry-regime filter qualifies; stand-aside rejected, walkforward warning stands] - 2026-09-14

### Finding — the 2026 deficit cannot be filtered away with the standard regime states
- The open question after v2.20 was whether the losing 2026 segment could be dodged by a stand-aside filter: measure regime state at each of the 75 real long-only entries (H1 ATR(14) z-score, H1 ADX(14), 6h EMA slope, month realized vol from M30) and correlate against PnL at both granularities, with the repo's walkforward convention (fit on 2024.01–2025.08, evaluate 2025.09–2026.09 out-of-sample).
- **Nothing correlates.** Per-trade — the granularity at which an EA filter actually fires — the best is |ρ| = 0.05 (adx), atr_z +0.03, slope −0.02; permutation p ≥ 0.67, i.e. pure noise. Month-level (n=29) tops out at atr_z ρ +0.22 (p≈0.25) across eight scanned feature-direction cells — unremarkable after the scan.
- **The train-fit filters fail their own out-of-sample.** The best full-window month rule (atr_z ≥ 0.84, kept +786.61) works only by dropping the train segment's single losing month and never fires OOS (test kept −236.04 = the unfiltered baseline). The per-trade rules are worse than useless OOS: atr_z ≤ 1.19 keeps −333.84 while dropping +97.80; adx ≤ 36.99 keeps −330.58 while dropping +94.54. The nominal "best OOS separation" (slope ≤ 0.53) drops zero trades — the baseline restated, not a filter.
- **The granularities disagree in sign** on the one feature with any signal (month-level keeps high atr_z; the per-trade train fit drops high atr_z). A real effect does not flip sign under re-aggregation; noise does.
- Decision: **no stand-aside input is added to the engine; v2.20 geometry stands unchanged.** The 2026 deficit is the already-recorded walkforward inversion (every config flips negative on the test window) showing up feature-wise — edge decay, not a filterable regime state. Limits recorded: 75 entries / 22 test trades = low power; the verdict closes these four features, not the space — reopening requires a new pre-registered feature + fresh window per the ledger discipline.
- Evidence: `artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt` (reproduced bit-identically on re-run); generator `scripts/v75_regime_analysis.py`; ledger row #11 in `docs/OPERATING_SUMMARY.md`.

## [V75MacroEngine v2.20 — timeout re-derived: 3h → 2h on buy-side MFE/MAE evidence] - 2026-09-14

### Changed — the hard timeout is now 2 hours; SL/TP geometry untouched
- The 71-day path-forensics claim was re-measured on the full window with deep terminal history (M30 44,353 bars + H1 22,177 bars, 2024.03–2026.09): the published p75=0.64R MFE was **sell-dragged** — the 75 real long-only entries measure **p50 0.71R / p75 1.14R / max 3.31R**, with 32% reaching 1R. But MAE is the binding side: 29% of buys touch −1R eventually, and every extra hold-hour converts timeouts into SL hits. The what-if grid over TP×hold shows **2h beats 3h at every TP level** (at spec TP: offline +7.84 → +10.14R, PF 1.51 → 1.99), while 4–8h holds collapse. TP is a plateau across 0.8–2.0R at 2h — the liquidation time is the lever, not the target — so the TP stays at spec 4× ATR and only `TIMEOUT_SECONDS` changes.
- **Validation (real ticks):** 71-day gate reproduces the 8-buy entry stream exactly (zero sells, all bar-open entries, 8/8 reconciliations — exit paths differ by design). 31-month pass: **76 fills, +867.90 (PF 1.794, R-sum +8.38, final balance 10,866.84)** vs v2.10's +730.66/PF 1.529 — SL hits 4→1, negative months 10→7, 2026 −236→−120, one extra fill from the freed slot. 2026 remains net negative: regime risk stands.
- The validation driver is now build-generic (`v210_longonly_validate.py [prefix]`, e.g. `v220`): entry-stream invariants stay hard for every build, PnL pins apply only where the exit paths are pinned. The runner's identity hook now also parses the v2.x init line (`V75 Macro Engine vN.NN initialized`), so every pass records what actually ran.
- Evidence: `artifacts/v75_macro_engine_tester/v220_exit_rederivation_evidence_20260914.txt` + `exit_rederivation_20260914.txt`; script `scripts/v75_exit_rederivation.py`; reports `V75_regress_v220_71d.htm` / `V75_regress_v220_31m.htm`.

## [V75MacroEngine v2.10 — LONG-ONLY: the sell leg is cut on 31-month evidence] - 2026-09-14

### Changed — aligned-DOWN regimes now stand down; the SELL springboard is removed
- Five independent 31-month real-tick runs (spec exits + four TP/trail variants) all show the same side split: **buys +748/+704/+693/+252/+478, sells −1,081/−810/−1,024/−913/−551** — the sell arm loses under every exit geometry, worsening by year (+69 / −481 / −669). Entry-drift stats corroborate: the buy signal lifts the 1-bar directional hit rate 50.7%→62.7%; the sell signal is indistinguishable from base (54.3% vs 51.9%, negative mean; between-arm difference p≈0.016). The aligned_down MFE data adds the mechanism: mean peak 0.39R, max 1.81R vs the 2.0R target — the sell arm's 1:2 never materializes (0 TP hits in 167 spec trades).
- v2.10 makes the **minimal surgical change**: aligned-DOWN regimes stand down in `OnTick` before the springboard; the sell branch, `bbUpper` read, `ENTRY_SELL` enum member and `InpRSISellLevel` input are deleted. Constants, 3h timeout, 1% sizing, single-position cap and HUD are untouched. Init print is now `V75 Macro Engine v2.10 initialized (LONG-ONLY)`.
- **Validation (real ticks, same rig):** PASS 1, the 71-day regression window, reproduces the v2.00 buy arm **exactly** — 8 fills, zero sells, R sequence [−0.58, 0.32, 0.21, 0.27, −0.39, −0.06, 0.13, −0.38] identical, PnL −45.77 vs −45.92 (one 15-cent tick-fill difference at a timeout close) — proving the removed sell arm was path-isolated. PASS 2, the full 31-month window 2024.03.01–2026.09.10: **75 fills, +730.66 (final balance 10,728.71), PF 1.529, R-sum +7.15**, 4 SL / 0 TP / 71 timeouts — within 2.3% of the tpA2 buy-arm reference (+747.55 / PF 1.56), the gap being buy flow the sells had been blocking while holding the single-position slot. Per-year: 2024 +639 / 2025 +328 / 2026 −236; 10 of 29 months negative.
- Recorded honestly: 2026 remains net negative even long-only — the walkforward warning (train 2024.01–2025.08 → test 2025.09–2026.09 flips every config negative) stands, so the long-only fix removes the structural bleed but the current regime is hostile to the pullback-buy style. The exit geometry is deliberately left untouched (spec 2×/4× ATR + 3h timeout); the MFE evidence says the 4×ATR TP is unreachable and a re-derived exit (~0.8R targets) is the next strategy decision, but it is a change with its own validation burden, not part of this fix.
- Rig note: the live terminal (`MitemshubMT5_B`) silently absorbs a `/config:` tester launch (single-instance MT5) — a v210_71d pass then times out with no agent activity. All tester runs in this repo require the terminal closed; the two v2.10 passes were run with it closed and it was relaunched afterwards (0 open positions at close).
- Evidence: `artifacts/v75_macro_engine_tester/v210_longonly_evidence_20260914.txt`; reports `V75_regress_v210_71d.htm` / `V75_regress_v210_31m.htm`; forensics `scripts/v75_exit_geometry_study.py`; driver `scripts/v210_longonly_validate.py`.

## [V28 scorecard/gate state dollars and R as a matched pair, and the 32-record matrix is re-reported] - 2026-09-13

### Change — both R measures travel with every record, and a verdict quotes the pair
- The scorecard and promotion gate now report `cumulative_r` (sum of per-trade ratios — what `OnTester()` scores) beside `money_implied_r` (net P&L / mean risk — the figure that multiplies back to dollars), with `mean_risk`, `risk_source` and `expectancy_r_money`. A refusal reason now names the money and the R that correspond to each other, e.g. `out-of-sample money-implied R is not positive (-0.2021 = -20.17 USD / mean risk 99.79)`. A record with no denominator is refused outright and the reason names the fix (`backfill`) rather than silently substituting the ratio-sum figure.
- The 32 matrix records predate the EA's `R_RECONCILE` line, so `cmd_backfill` now resolves each one's mean denominator from **its own journal segment** (never another pass's): the pass's `R_RECONCILE` line when present, else reconstructed from its OPEN geometry via the EA's own formula — `(stop_distance / tick_size) * CalibratedTickValue() * volume`, which on V75 reduces to `|entry - SL| * volume` because the calibrated value is the geometric `tick_size*contract_size`.
- **Reconstruction validated against a pass carrying both sources** (262 closes): reconstructed mean 96.48, min 89.24, max 103.59 vs the EA's own 96.86 / 89.24 / 104.04 — 0.4% on the mean, identical minimum; the residual is that the EA's POSITION source uses the actual fill while the OPEN print shows the requested price. Backfill result: **32/32 records carry `mean_risk`** (all `open_lines`), range 80.10–106.14, **0 identity violations** (`test_pnl == money_implied_r * mean_risk`) and **0 sign disagreements** between money-implied R and P&L.
- Re-reported matrix: **all eight hypotheses remain REFUSED, and no verdict changes** — the numbers that decide them (P&L, PF, trade counts, exit splits) were already verified. What is new is that every refusal now also states a consistent dollar/R pair, so the ratio-sum R cannot be mistaken for something that converts back to money. `REVERSE_DIRECTION` is where the measures diverge most (ratio −1.192 vs money −1.501); `REVERSE_BOTH` stays positive in is/wf and negative in the untouched oos (−0.185 / −0.202), exactly as the 33-month run showed.
- One harness detail fixed while doing this: storing `mean_risk` rounded to 2dp but computing the implied R from the unrounded value left `V28-0016` violating the identity by 0.0012; the implied R is now derived from the stored denominator.
- Evidence: `artifacts/v28_research/r_measures_surfaced_20260913.txt`; refreshed exports `registry.csv` / `registry.json`; pre-backfill registry archived as `registry_pre_reconcile.jsonl`. 31 tests pass in `tests/test_v28_research.py` (5 new pins), 70 passed / 1 skipped across the V28/V75 suites. Still open and unchanged: the 16 defect-era registry records in `registry_backfilled_contaminated_20260913.jsonl` carry invalid cumulative R and must not be read for R.

## [V28 MFE study — why every exit is a timeout, and what a different exit would have captured] - 2026-09-13

### Finding — the take-profit is not being beaten by the timeout, it is unreachable
- The question could not be answered from the existing logs: a trade that times out reports where it finished, never how far in front it ever was. Added tick-true excursion tracking to the EA — `TrackPeakExcursion()` samples `POSITION_PROFIT / g_risk_money` **every tick ahead of the guardian**, `g_peak_r` is folded with realised R at the close and printed as `peak_r` on every CLOSE line, and `MFE_SUMMARY` prints how many trades cleared each level of {0.25…2.00}R. All eight modes re-run on M30 2024.01.01–2026.09.10 (100% real ticks, 42.4M ticks), **16,449 trades**; every mode's captured close count matches its report's Total Trades (8/8).
- **2 of 16,449 trades (0.012%) ever reached 2.00R; the largest favourable excursion anywhere was 2.005R.** The spec's TP is 4×ATR against a 2×ATR stop, i.e. 2.0R. The 92% timeout share is not the timeout winning a race — the target is at a price the instrument simply does not visit. The median trade peaks at 0.35R: 70% of the way to the stop, 18% of the way to the target.
- **The MFE distribution is nearly identical in every mode**: mean 0.391–0.465R, p90 0.785–1.035R, in all eight, across entry rules that disagree on direction, trigger and filter. In R units the favourable excursion over a 3-hour hold is a property of the instrument's volatility over that window, not of the signal — if the entries carried directional information these distributions would have to differ.
- **Exit geometry is not the lever.** Pricing a TP at kR (exact here: a trade whose MFE reached k must have reached it while open, so the TP fires first) leaves six of eight modes negative at their best level; `ORIGINAL` is best left alone at 2.0R; the two positive modes gain at most +34% (REVERSE_BOTH +87.94 → +117.58, PF 1.02 → 1.03) — inside noise and far below the PF 1.30 gate. The tight targets that help the losing modes (0.25–0.50R) are exactly the ones that destroy the modest winners.
- Limits recorded: the counterfactual holds the entry sequence and sizing fixed (a tighter TP frees the one-position slot earlier, which needs a re-run to price); fills are assumed at the level with no slippage; MAE is not tracked, so tighter *stops* cannot be priced from this corpus.
- Evidence: `artifacts/v28_research/mfe_exit_geometry_20260913.txt`. 75 offline tests pass across the V28/V75 suites (two new pins: peak tracked before the guardian and reported per close, and the excursion state reset per pass).

## [V28 REVERSE_BOTH on 33 months — the last open thread closes negative] - 2026-09-13

### Result — the 3-of-4-window profitability does not survive a bigger sample
- `REVERSE_BOTH` was the only matrix configuration profitable in 3 of 4 windows with trustworthy R (+1.895 / +6.604 / +2.516 / −0.185) but under the 30-trade gate in all of them (18 / 29 / 27 / 12). Re-testing it on those same windows would be circular, so it was run on the **full cached range**: M30 2024.01.01–2026.09.10, **100% real ticks**, 47,184 bars, 42,442,757 ticks, 181 trades (6× the gate).
- **181 trades, net +87.94, PF 1.02, expectancy +0.0065R, cumulative R +1.1711, balance drawdown 1,364.04 (13.09% ≈ 14.1R), win rate 49.2%, 0 TP / 15 SL exits (91.7% timeout).** That is +0.88% total return over 33 months against a 13% drawdown — and it fails profit factor, expectancy and drawdown while passing the sample gate. First V28 candidate to clear the sample gate and still be refused.
- The four-window impression was a property of the window. Sliced at the selection boundary: **selection era (2025.09.15+, the 12 months that picked it) 68 trades, +858.62, PF 1.985; virgin era (<2025.09.15, 20.5 months) 113 trades, −760.99, PF 0.754.** The two eras cancel (matching the +97.63 aggregate). Contiguous 90-day blocks are 6/11 positive, and the break is a regime property rather than an artefact of the split: the last four blocks are all positive (2025.09.28→2026.09.03) while the seven before are 2/7 — the same signature as the V75MacroEngine walk-forward inversion.
- Caveat recorded: the virgin era is virgin only with respect to *this mode's* selection; other V28 modes and the V75MacroEngine research have used 2024–2025 data.
- Accounting cross-check on the new log, over 181 trades and 33 months: `ratio_sum_r=+1.1711` equals the report's own `OnTester` field, `mean_risk=96.45` sits in the same 89–104 band as every other V28 run, `gap=+0.2593` inside `dispersion_bound=6.2201` → `consistent=true`.
- `tests/v75_tester_runner.py`'s `parse_report` now also returns the deal table with simulated timestamps (the journal is wall-clock only), so any sub-period can be sliced without re-running the tester. Evidence: `artifacts/v28_research/reverseboth_long_sample_20260913.txt` + `reverseboth_long.json`.

## [MitemshubAI v28 — R denominator reconciled: the gap was arithmetic, not a defect] - 2026-09-13

### Finding — the per-trade denominator is correct; "implied risk" was the wrong statistic
- The open question was that is90 `REVERSE_DIRECTION` showed net −144.81 against cumulative R −1.192, implying ~$122 of risk per trade where the close audit showed $89–104 (mean $96.86). Auditing **all 262 closes**: the per-row identity holds on **0/262 violations**, `sum(pnl_i/risk_i)` recomputes to **−1.1922** against the EA's own `cum_R` −1.1920 and the report's `OnTester` −1.1920, and the denominators are tight (min 89.24, median 97.44, max 104.04; all `ENTRY`/`POSITION`, zero fallbacks).
- **The gap is the arithmetic of summing ratios.** `sum(pnl_i/risk_i) == sum(pnl)/mean_risk` only when every denominator is identical. Measured: ratio-sum **−1.1922** vs money-implied **−1.4951**, difference **+0.3029**, `corr(1/risk, pnl) = +0.053` — a ±8% risk spread from equity drift and lot rounding accounts for it. Nothing in `CommitTradeRisk` or `CaptureManagedPosition` needed changing.
- Added `LogRAccounting()`, called from `OnTester()`: it accumulates `sum(risk)`, `sum(|pnl|)`, `min/max(risk)` per close (all reset in `ResetTestMetrics`, so nothing leaks between passes) and emits `R_RECONCILE … ratio_sum_r money_implied_r gap dispersion_bound consistent`. `consistent` compares the gap against the exact bound `sum|pnl_i| · max_dev(1/risk)`, so a genuinely wrong denominator is reported as a WARNING rather than hiding behind the benign effect. `ratio_sum_r` is for comparing candidates; `money_implied_r` is for converting R back to dollars.
- Measured line: `trades=262 mean_risk=96.86 risk_min=89.24 risk_max=104.04 ratio_sum_r=-1.1920 money_implied_r=-1.4951 gap=+0.3030 dispersion_bound=9.7843 consistent=true net_pnl=-144.81 implied_risk_by_ratiosum=121.48`.

### Fixed — the research driver recorded the wrong P&L
- `run_experiment` set `test_pnl` to the report's **deal-table sum**, not the run's net profit — one-directionally optimistic by ~$0.05/trade (up to $60 on a 1,200-trade run), wrong on 23 of 32 records (e.g. −129.24 recorded against −144.81 actual). That bias fed the promotion gate's out-of-sample P&L.
- New `choose_whole_run_pnl()` takes the EA's own counter → the report's `Total Net Profit` → the deals sum, and records the choice in a new `pnl_source` field. Verified end-to-end on a fresh pass: `test_pnl −144.81`, `pnl_source ea_journal`, `cumulative_r −1.192`.
- Evidence: `artifacts/v28_research/r_denominator_reconciliation_20260913.txt`. 24 offline tests pass (three new pins: reconciliation log + dispersion bound, accumulator reset, P&L source order).

## [V28 matrix re-run on the fixed binary — which findings survive trustworthy R] - 2026-09-13

### Result — the corrupted R made the program look ~2.2x worse than it is, and killed one false positive
- Re-ran all 32 cells (4 windows × 8 modes, unchanged windows, 100% real ticks) on the fixed `MitemshubAI_v28` build. Sign agreement between cumulative R and net P&L goes **10/32 → 1/32**, and the one residual is a flat run (is180 `REVERSE_DIRECTION`: net −25.73, R +0.246), not a defect.
- The era's R was not merely noisy, it was **magnitude-inflated and sometimes sign-flipped**: is180 `REVERSE_DIRECTION` +63.484 → **+0.246** (258x), oos `MACRO_ONLY` −81.669 → −6.514 (12.5x), and 6 records flipped sign outright (e.g. is180 `TRIGGER_ONLY` net −2140.63, era R +51.387 → −24.061). Aggregate R across the 32 records: **−401.5 → −184.4**.
- Trading is unchanged: P&L, PF and trade counts are identical on all 32, and the 22 records whose era R already agreed are unchanged to 3 decimals. Only the accounting moved.
- **`REVERSE_DIRECTION` is a false positive that the corrupted R was carrying.** Its era R was positive in all four windows (+29.5/+63.5/+20.8/+18.4) while its money was negative (−144.81/−25.73/−1667.12/−916.28) — that discrepancy *was* the defect. Real R: −1.19/+0.25/−17.97/−9.35.
- Survivors: `ORIGINAL` is negative in all four windows (PF 0.40/0.17/0.53/0.86); only 8 of 32 runs are profitable; the 4×ATR target is unreachable at matrix scale — **7,597 trades → 4 TP, 602 SL, 6,991 timeout exits (92%)**; the sell-side asymmetry holds (`SHORT_ONLY` worse than `LONG_ONLY` in every window, bootstrap profitable share 0.00). All eight promotion verdicts remain **REFUSED**, now for legitimate reasons (oos P&L/R not positive, walk-forward sign flips, bootstrap p05 far below zero) instead of corrupted R.
- The one open thread: `REVERSE_BOTH` is the only configuration positive in 3 of 4 windows with trustworthy R (+1.895/+6.604/+2.516/−0.185) — but it is below the 30-trade gate in every window (18/29/27/12 trades) and negative out-of-sample. A hypothesis for a much larger sample, not a result.

### Fixed — two harness defects that corrupted the re-run itself
- **Reused run tags broke every research-line capture.** The tag was `v28_<window>_<hypothesis>` — deterministic, so a re-run reuses an earlier pass's tag, and `journal_has_tag()` searched the whole journal, matched the older line and returned immediately; the delta parse then found nothing and all 32 passes silently fell back to the report field. Tags now carry pid + timestamp (one tag = one pass) and the wait is offset-scoped.
- **`cmd_backfill` imported superseded numbers.** It used `re.search` and took the *oldest* matching line, replacing post-fix whole-run R with defect-era values on **24 of 32 records**; its docstring claimed the tag was unique per pass. It now takes the newest match. Both rules are pinned by tests, the 32 records were rebuilt from their own reports (OnTester R, Total Net Profit, deal-reason exit split), and the contaminated intermediate is archived for audit.
- Evidence: `artifacts/v28_research/matrix_rerun_postfix_20260913.txt`, `registry.jsonl` (post-fix) vs `registry_defect_era_full_20260913.jsonl` (defect era) vs `registry_backfilled_contaminated_20260913.jsonl`.

## [MitemshubAI v28 — research framework, and a fatal v27 execution defect] - 2026-09-13

### Fixed — v27 (and therefore every prior backtest) never actually held a position
- `ConfigureFilledPosition()` treated a rejected `PositionModify` as fatal and market-closed the position. On Deriv V75 the entry order **already carries the exact ATR stops**, so the corrective modify asks for values identical to the held ones and the server answers `10016 invalid stops`. The EA then destroyed a perfectly protected trade.
- Evidence: **6,390** `EXACT ATR PROTECTION FAILED: retcode=10016 invalid stops; closing` journal lines, and the instrumented trace proving the values are identical — `want_sl=35540.25 want_tp=38239.32 held_sl=35540.25 held_tp=38239.32 stops_level=10770`, i.e. 89,969 points of stop distance against a 10,770-point broker minimum (so it was never a distance problem).
- Effect on results: every v27 backtest measured *open → close at the opposite side of the spread*. Mode 0 on 2026.06.12–2026.09.10: **27 fills, 100% losers, PF 0.00, `OnTester` R −0.344**, each trade exiting in the same second it opened. After the fix the same config holds its trades: fill count falls (the one-position gate is now genuinely occupied), exits become real lifecycle events, and P&L is finally a measurement of the strategy.
- Fix: a rejected modify now verifies what the broker actually holds and keeps an already-protected position; only a genuinely **unprotected** position is closed, so v27's safety intent is preserved. The full geometry (want/held/levels/point/bid/ask) is logged on any rejection — a 10016 is no longer unattributable.
- New input `InpLegacyV27ModifyClose` (default `false`) reproduces v27 here byte-for-byte, so the original behaviour stays auditable; `v28_research.py equivalence` proves `v27 ≡ v28 mode 0` with that switch on.

### Added — V28 as a research framework (no self-modifying logic)
- Eight deterministic strategy modes (original / reverse-direction / reverse-trigger / reverse-both / long-only / short-only / macro-only / trigger-only), each a hypothesis rather than a mutation. The EA never rewrites its own logic during live trading; `InpLiveExecution=false` remains the default safety setting.
- Tunable geometry (`InpRiskFraction`, `InpStopATRMultiplier`, `InpTargetATRMultiplier`, `InpMaxHoldMinutes`) with **bounded validation** — out-of-range values fail `OnInit` loudly instead of letting an optimizer trade absurd stop geometry, and the recommended (narrower) search ranges are documented.
- **Whole-run tester metrics** (`g_test_*`) reset once per pass in `OnInit` and never at midnight; `OnTester()` returns whole-run cumulative R. The tester now also skips terminal global variables, so one pass cannot inherit another's session accounting.
- `RESEARCH_RESULT` is a single machine-readable journal line carrying the candidate identity and the exit-reason split (`sl_exits`/`tp_exits`/`timeout_exits`) alongside trades, wins, losses, win rate, P&L and R.
- `scripts/v28_research.py`: append-only experiment registry with unique ids, scorecard (net P&L, cumulative R, PF, drawdown, expectancy, win rate, avg win/loss, longest losing streak, trade count, recovery factor, OOS P&L, walk-forward consistency), robustness probes (fixed-seed trade bootstrap, drop-best-1/3, order-shuffle drawdown) and a **promotion gate that refuses any candidate without is+wf+oos evidence, ≥30 trades per role and a robustness pass**. Windows are reserved up front; the OOS block is never used for selection.
- `mql5/MITEMSHUB_AI/V28_RESEARCH_PROTOCOL.md` — tester setup, mode/matrix definition, walk-forward protocol, optimization ranges and the interpretation rules.
- `tests/v28_research.py` + `tests/test_v28_research.py` (25 offline tests pin identity, input completeness, window roles, bootstrap determinism and every promotion refusal).
- v27 (`mql5/MITEMSHUB_AI/MitemshubAI.mq5`) is untouched and still the live EA; v28 ships beside it as `MitemshubAI_v28.mq5`. Both compile **0 errors, 0 warnings** in all five terminal trees.

### Fixed — whole-run R accounting: 77 of 262 closes were silently dropped, flipping the sign of cumulative R
- The timeout guardian and an M30 entry can fire on the **same tick** (an entry opens on a bar open and the 180-minute hold is exactly six M30 bars, so a timeout expiry *always* lands on a bar open). `CaptureManagedPosition()` then overwrote the tracked trade's identity with the new position, so the closed trade was never booked — no `CLOSE` line, and no `POSITION GONE` line either.
- Measured in `REVERSE_DIRECTION` on M30 2026.06.12–2026.09.10 (100% real ticks): **262 opens, 185 booked closes**, 242 distinct tickets liquidated, **77 liquidated but never booked**, and exactly 77 opens sharing a journal second with a liquidation request. The report's net was **−144.81** while the EA's counters held **+2826.52 / +29.4700 R** — opposite signs, and `OnTester()` returned that corrupted `+29.47`. This is the mechanism behind the "10 of 32 records with R and P&L of opposite sign" finding.
- Fix: adoption now has one owner. `CaptureManagedPosition()` books a superseded trade (`RecoverClosedPosition()`) *before* adopting the new position, and clears the stale identity rather than carrying a stale denominator forward; `PollManagedPosition()`'s changed-identifier branch routes through the same path. The R denominator likewise has one writer (`CommitTradeRisk`), bound to the position id and plausibility-bounded, and **every close now logs `risk=` and `risk_src=` plus running `cum_pnl`/`cum_R`**.
- Verified on the same window with the same 262 trades: **262 opens / 262 booked closes, 0 unbooked liquidations, 0 silent clears**, exits TIMEOUT 242 / SL 20 / TP 0, EA `test_pnl` **−144.81 (== the report's net profit)** and `test_R` **−1.1920 (== the report's own `OnTester result` −1.192019807083707)** — signs agree. `ORIGINAL` on the same window is unchanged (18 trades, −229.41, R −2.3075), so the change is accounting-only.
- Denominator audit: `risk_src` 203/203 `ENTRY`, risk **$89.79–$104.04** (was $4.39–$79.46), and **0/203** per-trade `sign(pnl) != sign(R)`. Three source-level regression pins added to `tests/test_v28_research.py` (19 tests pass).
- Caveat: records produced by pre-fix builds still have unreliable cumulative R — only their P&L / PF / exit counts remain valid, and the registry should be re-run before any promotion decision reads R. Evidence: `artifacts/v28_research/r_accounting_fix_20260913.txt`.

## [V75 research — tick cache 31→35 months; two-sample walk-forward protocol] - 2026-09-13

### Added — the two-sample (walk-forward) protocol, so selection can be separated from validation
- `tests/v75_walkforward.py`: splits the cached months into TRAIN (selection) and TEST (untouched validation), runs every config on both sides, and reports the transfer — per-config train/test expectancy + PF, the train-winner's rank on each side, Spearman(train E, test E), and the 30-trade gate per segment. Selection is train expectancy only (PF breaks ties). Presets: `legacy` (2024.03-05 / 2024.06-08) and `powered` (2024.01-2025.08 / 2025.09-2026.09). Cells are banked to `walkforward_<name>.json` as they land and a relaunch **resumes**.
- `tests/v75_tester_runner.py` gains `report_inputs()`, so the "what did this pass actually run with" check (the input-cache gotcha) has one owner. `tests/test_v75_walkforward_protocol.py` (10 offline tests) pins the preset geometry, the selection rule, the sample gate, the uneven-side/resume fix, and explicit-input completeness.
- Fixed during the run: `persist()` summarised as soon as *either* segment had any cell, raising `KeyError` on segment-specific name sets; the summary now ranks only configs present in both, and the crash path is a regression test.

### Changed — tick cache 31 → 35 months, and the earlier "floor = 2024.03" was wrong
- Three real-tick probes: **2024.01-2024.02 runs complete** (2,832 M30 bars, 2,547,536 ticks, 12 fills) → `202401`/`202402` added; **2023 Q4 is partial** (384 bars over 3 months, 60% history quality, 1 fill) → `202311`/`202312` added but flagged unusable for research. Pre-Oct-2023 still resolves to no symbol. The usable floor is therefore **2024.01**, not 2024.03.

### Result — an adequately powered split shows selection *anti*-transfers
- **Powered** (train 111 fills / test 70 fills, gate met): train is positive for every config (E +0.030…+0.054R, PF 1.17…1.27); test is negative for every config (E −0.091…−0.173R, PF 0.42…0.60). The train-selected winner (`tp090`) is **test rank 5/5**, Spearman **−0.9**.
- **Legacy** (18/14 fills, gate NOT met): same inversion, `tp090` again 5/5, Spearman −0.7.
- Tripling the sample strengthened the inversion rather than dissolving it, so the P&L sign is a property of the time segment, not of the exit geometry. Bounds every earlier single-window "best cell" claim in this repo, and matches the entry-attribution finding (the loss lives in the regime and on the sell side). Caveat recorded: the powered TEST block overlaps windows used in earlier A/Bs, so a virgin holdout should be reserved before the next selection round.
- Evidence: `artifacts/v75_macro_engine_tester/cache_extension_and_walkforward_20260913.txt`, `walkforward_legacy.json`, `walkforward_powered.json`, both probe reports.

## [V75MacroEngine v1.29 — Pass-C springboard grid: no cell is robust] - 2026-09-12

### Changed — v1.29: the springboard thresholds are now inputs
- `InpRSIBuyLevel` (35.0) and `InpRSISellLevel` (65.0) replace the hardcoded `35.0`/`65.0` literals, with an init-time `Springboard:` identity print. Compiled defaults are the spec values, so out-of-the-box behavior is unchanged; a rig test pins both defaults and asserts the triggers consume the inputs. This is what made the springboard griddable at all.

### Pass-C grid — RSI {30,35,40} × BB {2.0,2.3,2.6}, 6-month real-tick window
- All 9 cells net negative; **TP hits = 0 everywhere**. Expectancy spans only **−0.207R to −0.292R** — the per-trade loss rate is essentially threshold-invariant.
- **The RSI axis is degenerate at 30 and 35**: those rows are byte-identical in every BB column (same PnL to the cent), the empirical confirmation of the inert-RSI-leg finding. Only RSI 40 activates the leg — so the grid is effectively 2-valued on that axis, not 3.
- Wider BB bands do not help: at RSI 30/35, 2.0 → 2.6 cuts fills 29 → 5 and PF 0.17 → 0.00 (zero winners).
- **The 6-month "best" cell (rsi40_bb2.6, PF 0.36, n=15) fails out-of-sample**: on the full window it is PF 0.80 / E −0.054R, *worse* than the spec default's PF 0.92 / E −0.019R. Its edge was small-sample noise. The non-monotonic RSI-40 PF sequence (0.23/0.17/0.36) is the same noise.
- Structural power limit: BB 2.6 yields only 5–15 fills per 6 months against the 30-trade gate. Pre-computed from the audit corpus (band = MA ± k·σ), predicted fill counts matched observed closely (predicted 29/16/5 vs actual 29/19/5 at RSI 30; 34/22/13 vs 34/25/15 at RSI 40), so future grids can be pre-screened rather than burned on the tester.
- The spec reference cell reproduced the independent isolated baseline exactly (167/−333.31/PF 0.92/152 timeouts/0 TP), validating the grid driver. Evidence: `artifacts/v75_macro_engine_tester/passc_springboard_grid_20260912.txt` + per-cell JSON.

## [V75MacroEngine v1.28 — entry attribution: the RSI leg never fires, the sell side bleeds] - 2026-09-12

### Added — v1.28: springboard branch + entry context reach the audit CSV
- The branch was computed (`bbTrigger`/`rsiTrigger`) then **discarded**, so "which leg fired" was unrecoverable; `trade_closed` rows carried no entry context. v1.28 encodes the branch in the existing `signal` token (`buy_bb` / `buy_rsi` / `buy_bb_rsi` / `sell_*`) and writes the entry regime + branch onto `trade_closed` rows — **no new columns**. Trading unchanged: the isolated run reproduces the baseline exactly (167 fills, −333.31, PF 0.920, R-sum −3.16) and the tier-3 gate is 10/10 green. Two rig invariants added.

### Finding — half the spec's entry logic has never operated
- Over **32,553 aligned bars**, entries came from: `bb_only` 166, `both` 1, **`rsi_only` 0**. RSI contributed exactly one entry in 19 months (the 6-month pooled corpus agrees: 0 of 6,621).
- It is structural, not rare: the alignment filter mechanically bounds M30 RSI away from the thresholds — `aligned_up` min RSI **34.06** vs the required ≤35 (1 bar in 15,166); `aligned_down` max RSI **64.51** vs ≥65 (0 bars in 17,387). Thresholds sit ~1.0–1.5 points outside the achievable range. The engine is in practice a **single-rule** system (EMA alignment + Bollinger pierce).

### Finding — all the negative expectancy is on the sell side
- Full window, isolated run: `aligned_up` n=75 **sumR +7.18** (mean +0.096R, win 60.0%, meanPeak 0.50R) vs `aligned_down` n=92 **sumR −10.34** (mean −0.112R, win 43.5%, meanPeak 0.39R). Neither arm alone is significant (t=+1.52 / −1.93), but the **difference** is marginally significant (mean diff +0.208R, t≈+2.4, ~p=0.016).
- Post-signal drift (close-to-close, aligned M30 bars, points): the **buy** signal lifts the one-bar directional hit rate from 50.7% (base) to **62.7%** with median favorable move +6 → **+449 points** (mean +627); the **sell** signal is indistinguishable from base (54.3% vs 51.9%) with a negative mean. The buy edge is real at entry but **given back by the exit** (~0.57R one-bar drift → +0.096R realized), consistent with the TP study's p75 = 0.64R MFE.
- Hit rate ≈ **0.5% of aligned bars** (74/15,166 up, 92/17,387 down) — roughly one entry per 200 aligned bars, which is why the 30-trade gate needs months to clear.
- The 6-month window is specifically a **short-side disaster**: its subset shows `aligned_down` n=13, meanR −0.532, **win rate 7.7%** — explaining why its headline (−389.05, PF 0.35) is far worse than the full window (−73.43, PF 0.97).
- Evidence: `artifacts/v75_macro_engine_tester/entry_attribution_20260912.txt`.

## [V75MacroEngine — tick-cache floor found; 6h+trail revalidated on v1.27] - 2026-09-12

### Finding — the V75 tick cache cannot be extended: 2024.03 is the broker's floor
- Probes at 2023.09, 2022.09 and 2021.09 each produced a report with **no symbol resolved (`Period M0 1970.01.01–1970.01.01`, Bars 0, Ticks 0)** and downloaded **zero** tick months, while Mar 2024 (5 fills) and Sep 2024 (9 fills) probes have real data. The local cache (`202403.tkc` → `202609.tkc`, 31 months) already covers **everything the broker serves** — the window cannot be grown by adding months.

### Revalidated — canonical 6h+trail on v1.27, full 31-month window
- Config: `InpExitManager=TRAIL`, 0.2R trigger, 1.0× H1 ATR trail, spec 4×ATR TP, 6h timeout; complete explicit `[TesterInputs]`; $10k; real ticks. Identity print: `Breakeven @ 0.20R + ATR trail 1.00x`.
- Window `2024.03.01–2026.09.10`, **100% real ticks, 44,304 bars, 39,852,025 ticks**: **173 fills, −73.43, PF 0.974, R-sum −0.53 (E −0.003R/trade)**, 142 SL / 2 TP / 29 timeout exits, 4,321 SL ratchets with **0 modify failures**, all entries on M30 bar opens, final balance 9,915.29, balance DD 1,172.09 (10.68% ≈ 11.7R), equity DD 1,259.54 (11.42% ≈ 12.6R).
- **Byte-identical to the archived v1.25/v1.26 canonical on the same window** — an independent confirmation that the v1.27 always-on peak tracking is trading-inert on the shipping config.
- Gate table: sample (173 vs ≥30) ✓ · TIME-exit share (16.8% vs ≤40%) ✓ · max DD (11.7R balance vs ≤12R) ✓ marginal · **PF (0.974 vs ≥1.30) ✗ · expectancy (−0.003R vs ≥+0.15R) ✗** → back to research, do not promote. Note the DD gate is the one metric that flips on balance-vs-equity basis (11.7R vs 12.6R).
- Evidence: `artifacts/v75_macro_engine_tester/cache_floor_and_6h_trail_reval_20260912.txt` + `V75_regress_reval6htrail.htm`.

## [V75MacroEngine v1.27 — data-driven TP derivation, contamination corrected] - 2026-09-12

### Fixed — the `peak_r` audit column was dead in the spec-default config
- `g_exitPeakR` was only updated inside `ManageOpenProfit()`, which returns immediately in the default `EXIT_MANAGER_NONE` mode — so every spec-default trade wrote `peak_r = 0.00` to the CSV. The documented pipeline column carried no information exactly when the shipping default was running.
- v1.27 gives it **one owner**: `TrackPeakExcursion()`, called from `OnTick` on every tick ahead of the exit manager and independent of the exit-manager mode. Trading behavior is provably unchanged — the pre-fix and post-fix 4×ATR baseline passes match on every metric (167 fills, −333.31, PF 0.920, 15 SL, 0 TP, 152 timeouts, R-sum −3.16) and the tier-3 regression gate is 10/10 green on v1.27. New rig invariant `test_peak_tracking_is_mode_independent` fails CI if the peak write moves back behind the mode gate.

### Finding — the earlier TP derivation was built on a contaminated sample
- The 2026-09-11 take-profit derivation used 60 rows labelled "uncensored 6m-OFF MFE" that in fact **pooled several runs sharing one `run_id`**, including runs whose TP already capped the peak (mixed row schemas, out-of-order timestamps), and was dominated by the dead column above. Its 0.03R median — and the 0.30R target derived from it — were artifacts.
- Clean uncensored distribution (n=167, 31 months, 3h hold, no early exit): **p25 0.16R · p50 0.38R · p75 0.64R · p90 0.88R · p95 1.06R · max 1.81R**. Max observed excursion (1.81R) is below the spec's 4×ATR target (2.0R) — that target is literally unreachable on this data, which explains 0 TP hits across every previous run.

### A/B — identical 31-month window and exits; only the TP changed
| TP target | Fills | Net PnL | PF | TP hits | Timeouts | R-sum |
|---|---|---|---|---|---|---|
| 4×ATR (spec = 2.0R) | 167 | −333.31 | 0.920 | 0 | 152 | −3.16 |
| 0.90R (p90) | 167 | −330.81 | 0.921 | 16 | 136 | −3.20 |
| **0.60R (p75) — derived** | 168 | **−105.88** | **0.974** | 53 | 100 | **−0.98** |
| 0.30R (previous contaminated pick) | 171 | −661.27 | 0.820 | 98 | 57 | −6.80 |
- The data-derived p75 target beats the fixed 4×ATR spec target on every axis (−68% net loss, PF 0.920 → 0.974, R-sum −3.16 → −0.98); p90 is a wash (only 16 trades reach it); the old 0.30R pick is the **worst** cell tested. Still below the PF ≥ 1.30 promotion gate — best geometry found, not an edge. Evidence: `artifacts/v75_macro_engine_tester/data_tp_derivation_20260912.txt` + `mfe_sample_31m_off_clean.csv` + four `.htm` reports.

## [V75MacroEngine cache extended to 32 months; 173-trade sample verdict] - 2026-09-11

### Changed — real-tick cache 13 → 32 months via on-demand broker download
- Probes at Mar 2025 and Sep 2024 proved the broker serves years of V75 tick history (the 13-month limit was an artifact of what had been downloaded, not a server cap); each probe month pulled a full half-year block (~10MB/month). Terminal B's cache is now **2024.03 → 2026.09 (32 months)**, fully local — any future range back to Mar 2024 runs with zero download time.

### Added — v1.26: data-derived R-multiple TP mode
- `ENUM_TP_MODE` (`TP_MODE_ATR_MULTIPLE` spec default / `TP_MODE_R_MULTIPLE`) + `InpTPRMultiple`, wired into `DeriveProtectivePrices`, with an init-time `TP mode:` identity print and a HUD field. Compiled default = spec 4×ATR, so out-of-the-box behavior is unchanged (tier-3 regression gate re-run on v1.26: **10/10 pass**, pinned 71-day invariants hold).

### Findings — long-window sample study (canonical 6h+trail, 0.2R/1.0×, spec 4×ATR TP, $10k, real ticks)
- Sample ladder: 71d = 15 fills / +11.67 / PF 1.07 · 6m = 31 / −389.05 / 0.35 · 12m = 72 / −684.32 / 0.50 · **31m (2024.03.01→2026.09.10) = 173 fills / −73.43 / PF 0.97 / R-sum −0.53** — sample gate cleared by ~6×.
- The 173-trade verdict: the strategy is **≈break-even, not an edge** (PF 0.97 vs the ≥1.30 gate; expectancy −0.003R/trade vs the ≥+0.15R gate). Positive tail months exist (Sep 2024 probe +298.33, Mar 2025 +58.62) but are cancelled by negative regimes; drawdown stays bounded (final balance 9,915.29 after a −684 valley). Exit machinery exonerated: 4,321 trail ratchets / 0 modify failures, all entries on M30 bar opens.
- Data-TP stack (0.3R) generalizes worse: 173 fills / −356.73 / PF 0.87 / R-sum −3.53 — the 0.3R cap helps short-window draws but bleeds R on 31 months of runners. Reports + summary archived in `artifacts/v75_macro_engine_tester/` (`long_window_sample_20260911.txt`, both `.htm` reports).

## [V75MacroEngine tester regression gate] - 2026-09-11

### Added — tier 3: the Strategy Tester validation is now a repeatable gate
- `tests/v75_tester_runner.py` + `tests/test_v75_tester_gate.py`: an opt-in tier (`V75_TESTER_TESTS=1`) that runs two headless real-tick tester passes on the fully-cached 71-day window (exit OFF, trail opt-in) and asserts the verified invariants — fill counts (13/15), entries only on M30 bar opens, OFF-mode exits all timeout-backstop (0 SL/TP hits), trail ratchet count (25) with 0 modify failures, exactly-one `POSITION CLOSED` reconciliation per trade, and PnL/PF/R-ledger values (−176.50/−16.65, PF 0.35/0.81, R −1.79/−0.17). 10 tests, ~75s end-to-end.
- Encodes the session's hard-won gotchas so future runs can't re-trip them: explicit `[TesterInputs]` mandatory (agent input-cache reuse), the EA's init-time identity print as the run discriminator, append-only journal parsing via pre-launch byte-offset snapshots, and the `[Tester]` section header requirement for generated INIs.

## [V75MacroEngine 6-month protocol validation fails promotion gates] - 2026-09-11

### Changed — tick cache extended 3→13 months; full protocol range run
- The Strategy Tester auto-downloaded Sep 2025–Sep 2026 real ticks on the first 6-month run; terminal B's V75 tick cache now covers 13 months.
- 6-month real-tick range (2026.03.11 → 2026.09.10, M30, $10k): spec config (exit OFF, 3h timeout) = 29 fills, −783.90, PF 0.17, 0 TP hits, 24 timeouts; best-known config (6h timeout + 0.2R/1.0× trail) = **31 fills (sample gate cleared)**, −389.05, PF 0.35, 0 TP hits, 6 timeouts, max balance DD ≈ 5.1R.
- Protocol verdict: sample-size gate passes for the trail config, but PF (0.35 vs ≥1.30) and expectancy (≈−0.13R vs ≥+0.15R) fail decisively → **back to research, no promotion**. The 71-day +11.67 (PF 1.07) result did not generalize — out-of-sample refutation, not confirmation.
- Structural conclusion unchanged and now 6-month-proven: the 4×ATR take-profit was never reached in 60 trades across both configs; negative expectancy (~−0.13R/trade) persists under every exit machinery tested, isolating the deficit in the entry layer (H4/H1 EMA alignment + M30 BB/RSI springboard). Reports archived in `artifacts/v75_macro_engine_tester/`.

## [V75MacroEngine exit manager defaults to OFF] - 2026-09-11

### Changed — opt-in profit protection, spec-pure default contract
- `InpExitManager` compiled default flipped from `TRAIL` to `NONE` (v1.25): out of the box the EA is the spec-pure SL/TP + 3h-timeout contract, and the ATR-trail/breakeven protection is an explicit opt-in. Opt-in values unchanged (0.2R trigger / 1.0× ATR trail, evidence-set; 6h+trail remains the only net-positive cell at +11.67, PF 1.07).
- Tester-verified both directions on the same real-tick window: pure default reproduces the timeout-only baseline exactly (13 fills, −176.50, PF 0.35, 0 SL modifications), and the opt-in trail run still matches the known trail result (15 fills, −16.65, 25+ ratchets).
- Test rig now pins the OFF default (`test_default_exit_manager_is_evidence_based`), so a silent default flip fails CI.
- Headless-tester gotcha discovered during verification: an INI with no `[TesterInputs]` section reuses the agent's last cached input set rather than the compiled defaults — verification runs must pass inputs explicitly, and the EA's init-time identity print is the discriminator.

## [V75MacroEngine open-profit protection (ratchet exits)] - 2026-09-11

### Added — ATR trail / breakeven so open profit survives the 3h timeout
- New `ManageOpenProfit()` runs on every tick behind the (unchanged) 3h timeout backstop. It is ratchet-only: the SL can move in the trade's favor and never wider, gated by a one-point improvement check and the broker's minimum stop distance, with modifies reported/failed loudly in the journal.
- Three modes via `InpExitManager`: `NONE` (original SL/TP + timeout behavior, byte-identical regression verified), `BE` (one ratchet to entry+offset at the trigger), `TRAIL` (BE step, then trail at `InpTrailATRMult` × H1 ATR — the new default).
- Defaults (`0.2R` trigger, `1.0×` ATR trail) are evidence-set, not aesthetic: in the Jul–Sep 2026 real-tick validation the 3h window never produced a +1.0R favorable excursion (max peak 0.44R), so a 1.0R trigger could never arm; at 0.2R/1.0× the same 71-day run cut net loss from −176.50 to −16.65 (−90.6%), PF 0.35 → 0.81. Trade-off is real and documented: winners are surrendered at the trail instead of running to timeout.
- The peak favorable excursion of every closed trade is now printed at reconciliation ("below trigger — protection never armed" when applicable), making arming behavior auditable from the journal alone.
- Managed/adopted-context invariant preserved: external positions have no R-yardstick (`g_initialSL = 0`) and are never SL-managed; R accounting still happens exactly once through the single cleanup path.
- Strategy Tester evidence in `artifacts/v75_macro_engine_tester/`; repeatable run configs in `config_tester/` and terminal-B `config/v75_*.ini` (`[TesterInputs]` section is the reliable way to pass inputs — named `.set` presets were silently ignored by the tester in this setup).

## [V75MacroEngine verification rig and truthful HUD status] - 2026-09-11

### Added — permanent regression gate for the V75 macro engine
- `tests/test_v75_macro_engine_surface.py` re-verifies the engine after every edit: static spec-invariant assertions on the `.mq5` source, the sizing/refusal math mirrored against real V75 symbol constants (the min-lot clamp-up regression stays proven fixed), and a deployed-binary freshness gate that fails when any terminal copy of the EA diverges from the repo or its `.ex5` is older than its source.
- Live tier (`V75_LIVE_TESTS=1`) attaches read-only to a running terminal and re-checks the tick-value overwrite and sizing verdicts against real broker data; no orders are sent.
- `scripts/sync-mt5.ps1` now deploys, compiles, and build-gates `V75MacroEngine.mq5` in every terminal instance using the same MetaEditor CLI pattern as the live EA, closing the repo↔terminal dual-copy trap for this EA.

### Fixed — HUD no longer contradicts the decision path
- The engine now owns a status string (`g_entryStatus`) set at each decision branch (diverged stand-down, aligned-waiting, entry blocked, order sent, and the undercapitalization refusal); the flat-state HUD renders it verbatim instead of always claiming "Waiting for Macro Alignment", which was misleading on a $50 account where every entry is refused for minimum-lot infeasibility.

## [V75 M30/H1/H4 macro engine] - 2026-09-09

### Changed — replaced the legacy multi-strategy entry surface with a disciplined, self-contained V75 engine
- Entry analysis is now behind a new-M30-candle gate; every tick only services the three-hour guardian, managed-position polling, session accounting, and HUD.
- Direction requires previous H4/H1 closes aligned around their own EMA(20); the M30 springboard uses BB(20,2) or RSI(14) thresholds 35/65.
- The active trade contract is one position, 1% equity sizing, 2× H1 ATR(14) SL, 4× H1 ATR(14) TP, calibrated tick value with a 5% identity tolerance, and forced liquidation at exactly three hours.
- The EA is now self-contained with only the native `<Trade\\Trade.mqh>` include, and its V75 presets explicitly separate paper/off from live execution.
- Added source/preset regression checks for the new gate, macro alignment, risk geometry, timeout, polling, and no-live-order default.
- No order was sent and no terminal state was changed during this pass.

All notable changes to Synthetic AI Trader are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Execution idempotency and horizon fail-closed hardening] - 2026-09-08

### Fixed — duplicate closes and malformed research configuration cannot corrupt state
- Close bookkeeping now returns immediately after the tracked position has already been cleared, preventing an `OnTradeTransaction` event plus fallback/local close from double-counting P/L, learning, or paper results.
- Persisted `ENGINE` rows are accepted only when all five fields are present, so truncated state files cannot read beyond their schema.
- Optional horizon mode now rejects invalid geometry, confidence, agreement, and lookback parameters at initialization; its configured lookback is used for momentum and path efficiency instead of being silently fixed at 32 bars.
- Deployed V75 presets remain unchanged: horizon mode is off and no live order was sent.

## [Fresh-install governor initialization] - 2026-09-08

### Fixed — new charts no longer start in probe-only mode
- Strategy-enable flags are now initialized to enabled before persisted review state is loaded.
- Existing state files still override those defaults, while a brand-new chart can evaluate the configured V75 strategies normally instead of silently allowing only every 10th signal.
- No signal thresholds, exit geometry, risk sizing, presets, or live execution behavior changed.

## [Blind 90-day A/B replay and standard-path micro-balance fix] - 2026-09-05

### Fixed — normal Volatility entries bypassed `InpMicroFitPct`
- The two-terminal blind replay used identical Deriv MT5 M15/H1 history from 2026-06-07 18:00 UTC through 2026-09-05 18:00 UTC, with exact OHLC agreement across terminals A and B.
- Before the fix, accepted $50-account trades risked 6–20% because the standard `OpenTrade` path clamped to the 0.01 minimum lot and enforced only the 20% cap; the alternate opener already had micro-balance fitting.
- v26.36 applies the 1.5% micro-fit to the standard path, preserves broker/spread stop floors, recomputes effective risk, and pins `InpMicroFitPct=1.5` in both V75 paper presets.
- Baseline result: Arm A TP 1.8 ended $18.96 (-62.08%, 36 trades, -6.88R); Arm B TP 2.4 ended $21.00 (-58.00%, 48 trades, -5.60R). These are diagnostic results, not a live authorization.
- Source and replay fix are pending compile/deployment; no terminal `.ex5` was replaced and no live order was sent.

## [Go-live checklist rehearsed: every artifact verified in place, abort criteria pre-written] - 2026-09-05

### Added — docs/GO_LIVE_CHECKLIST.md, the exact $50 execution procedure (do NOT run until the gate passes)
- **Everything verified in place on terminal A** (data folder `FB9A56D617EDDDFE29EE54EBEFFE96C1`): `MitemshubAI.ex5`/`.mq5` v26.35 present, `MitemshubAI_VOL75_LIVE.set` present and **byte-identical to repo** with `InpLiveExecution=true`, `InpMagic=7788075`, `InpTpMult=1.8`, fleet CSV covering A+B.
- **Expected banner lines extracted from source**: LIVE attach shows `MITEMSHUB AI v26.35 ... Standard Mode` with **NO `PAPER MODE:` line** (the discriminator), `FIT ROUTER: instruments vs a $50.00 account` + `TOLERATED ... each trade risks ~9-13% of equity`, `RiskCap=20%` + tiny-account warning (expected at $50), `[SELFTEST] OK`. Live orders print `Executing BUY/SELL vol=.. SL=.. TP=..`; failures print `ORDER FAILED retcode=..`.
- **$50 truth table**: ~$4.6-6.5 min-lot stop-risk ≈ 9-13%/trade (TOLERATED); $31 floor ≈ 20% (at cap); below $31 → `CANNOT FIT` vetoes everything; $100+ ≈ 5-7% (sane compounding size).
- **Abort criteria pre-written**: PAPER MODE in banner / CANNOT FIT at funded balance / wrong magic or TP / dashboard MODE not LIVE / any ORDER FAILED / first fill wrong symbol or magic.
- Also flagged: 2026-09-04 record said real account at $0.57 — funding to ≥$50 must be confirmed broker-side at attach (the FIT ROUTER banner prints the true balance).

## [Operating summary: every question closed by protocol, the gate tree pre-declared] - 2026-09-05

### Added — docs/OPERATING_SUMMARY.md, the single reference for what is and isn't open
- **10 closed questions** with verdicts (engine honesty, generator memorylessness, regime axis, MOM duel, V100, cost-dilution, spread tiers, EA audit, data path, arm C) — each with its frozen protocol + artifact + commit, and the rule that nothing reopens by vibes.
- **The one open gate**: TJ1 paper A/B (≥30 arm-A trades, positive expectancy, paired |t|≥1.0) + TJ2 tick reconciliation (self-arms 7d) + TJ3 watchdog — with the current status (clock not yet started, 0/30) and the pre-registered accelerated path (20 trades + 5d reconciliation).
- **Decision tree for every gate outcome**, pre-declared: GO LIVE (all three green) · NO GO if any leg fails with the fix-first order · INCONCLUSIVE → keep collecting with 50/75-trade boarding · arm-A negative → re-baseline + protocol-ordered investigation, collection continues · TP-2.4-wins branch (re-certify on the 210-day window before any preset change, then arm-C paper test) · and the full arm-C candidate branch (new pre-registered rule, activation ≈1 min, teardown on loss).
- Non-negotiables restated (live = A/chart01/7788075 only; no hand-tuning; funding floors; spec-stamped artifacts; data is the only judge) + the daily cadence.

## [V75 spread-tier study: the broker-side lever is dead on Deriv synthetics] - 2026-09-05

### Executed — frozen protocol (docs/V75_SPREAD_TIER_STUDY.md, committed `ded5e3a` before any measurement)
- **Measurement, 2,460,772 ticks (Jul 7–Sep 2, both lake files)**: V75 effective spread is a step grid (levels ~16.0/17.0/17.9/18.5) **flat at 16.96 median for every hour of day** — no hour-gate exists to exploit. The live 18.5 calibration sits at the lake's p99: the standard account's spread IS the raw model spread (16.96 = −8.3% vs 18.5, under the 25% materiality threshold). Deriv's Zero Spread MT5 account cannot price below the generator's raw spread on synthetics.
- **Net edge per tier (fresh60, deployed tp 1.8; integrity gate: t185 ledger bit-identical to stored)**: raw 16.96 → +0.048R/t, 14 → +0.054R/t, 9.25/4.6 → +0.031/+0.028R/t (non-monotonic — governor re-routing noise at 120 trades), spread 0 → +0.162R/t BUT that ceiling is a different strategy (band-fade reopens, 9 trades +11.1R) and structurally unpurchasable.
- **Robustness (70d, 9 folds)**: near-linear cost response, **+0.0023R/t per unit of spread** (matches mean(1/sd) exactly) — the deliverable pricing slope for any future venue quote. Even the zero-spread ceiling fails fold consistency (3/9).
- **Verdict**: NO tier clears the frozen +0.08R/t bar on either window; P1 and P2 both held. Hour-gate idea dead by measurement; broker-side lever dead on this platform; no EA change, no arm-C candidate. Cost structure remains the binding constraint — growth depends on the paper gate's verdict, not on hunting a cheaper toll.

## [Arm C activation rehearsal: minutes-scale promise PROVEN] - 2026-09-05

### Executed — supervised 10-minute run of docs/ARM_C_TEMPLATE.md, verbatim
- **T0 12:22:46** → `authorized '140778269' on DerivSVG-Server-03` at **T+6s** → full v26.35 banner (SELFTEST OK, GARCH ready, 200-bar cold-start catch-up, `PAPER MODE: virtual equity $50.00`, tick value calibrated, `FIT ROUTER ... TOLERATED` $4.59 at live spread) at **T+8s**. Pre-flight had verified the `common.ini` login pointer (UTF-16 — plain grep reads nothing), chart magic 7788125, paper mode, and the fleet (2 running: A, B; C off).
- **Steady state**: EA evaluated real bars (first `sig`/SKIP telemetry event), state CSV fresh; telemetry quiet-window behavior matched healthy arm B exactly (event-driven cadence — recorded in the template so nobody misreads quiet as dead).
- **Parked** at T+23min — about 1 minute of procedure, the rest deliberate observation — via PID-from-ExecutablePath kill; A/B untouched, both wrote telemetry at the next M15 close. Time-to-operational ≈ **1 minute**; the doc's "minutes, not hours" promise is now measured, not assumed.

## [Spec-integrity guard: cross-instrument cert runs must STATE their specs] - 2026-09-05

### Added — the V100 0.01-lot lesson, made mechanical
- `certify_v75.py`: `assert_spec_integrity()` runs inside `certify()` — if `CERT_DATA_DIR` is set, all four spec variables (`CERT_SPREAD`, `CERT_USD_PER_UNIT_PER_LOT`, `CERT_MIN_LOT`, `CERT_LOT_STEP`) must be explicit or the run **exits 1 before any data pull**, with the correct V75 truth printed in the error. Default V75 runs (no `CERT_DATA_DIR`) are exempt: the defaults ARE the V75 truth. Every caller (walkforward, study scripts) is covered transitively.
- **Spec stamp in every artifact**: `spec_block()` — data_dir, spread, usd/unit/lot, min_lot, lot_step, cost model, geometry (`tp_mult`/`stop_mult`/`min_score_bonus`), which env vars were explicit, guard version — is written into every `cert_report_*.json` and every walk-forward artifact (which also stamps its full config registry). An artifact whose sizing implies a lot grid the instrument cannot trade is now self-identifying as invalid.
- `z_gate_phaseA.py` declares its specs explicitly (its data IS V75, pulled via `pull_v75_week`) — custom-dir runs state them like anyone else.

### Verified — four-point battery, all green
- **T2 loud-fail**: non-V75 dir without specs → `SPEC-INTEGRITY FAIL`, exit 1, no artifact written. **T2b**: z_gate's import satisfies the guard via module-level setdefaults. **T3**: explicit specs run clean and the stamp reflects them.
- **T1 bit-identity**: legacy fresh60 re-run at `--tp-mult 1.8` equals the stored 09:01 artifact on all 135 trades and every metric. Two footguns surfaced and were resolved honestly: (1) the CLI's default is `TP_MULT_CERT = 2.4` — omitting `--tp-mult 1.8` silently certifies the wrong geometry (now visible in the spec stamp's `geometry` block); (2) the stored artifact's `funnel.paused` is 947 vs 948 in every re-run — **including from a pristine worktree of the committing SHA**. A gap-aware reconstruction from the trade ledger independently computes 948, so the ledger-relevant contract reproduces exactly and the stored 947 is attributed to the transient pre-commit working tree (runs 08:58–09:01, commit 09:03). No engine issue.

## [Arm C paper-terminal template: built, validated, PARKED] - 2026-09-05

### Added — docs/ARM_C_TEMPLATE.md: a third paper arm that can start collecting within minutes of an adoption decision
- Clone of B's install at `%LOCALAPPDATA%\MitemshubMT5_C`, data folder `71BF6B2AB5548CFBA970FA2F38007C31`, magic **7788125** (verified unused), chart = arm A's validated paper chart (TP 1.8 placeholder), auto-login verified (`authorized '140778269' on DerivSVG-Server-03`), sync gate PASS, v26.35 banner + FIT ROUTER TOLERATED ($4.65 min-lot risk, 9.3%/trade at $50 virtual) + paper equity $50 initialized.
- **Login gotcha recorded**: `accounts.dat` alone does not enable auto-login — the pointer lives in `config\common.ini` (`Login=`/`Server=`). Also: launch MT5 clones via PowerShell `Start-Process` (Bash `&` hangs on the child's handles), and never kill by image name (the 2026-09-04 terminal-A mishap) — kill by PID from the ExecutablePath.
- **Parked by protocol**: the cost-dilution verdict was NO-ADOPT 5/5 and no study has ever returned VALIDATED-CANDIDATE, so C stays OFF until (a) a candidate exists and (b) the primary A/B adjudicates uncontaminated. A running C before adoption would trade an un-adopted config and mint unread data. Activation is a one-input edit + one Start-Process + a morning-status line.

## [V75 cost-dilution study: NO-ADOPT 5/5 — geometry cannot outrun the spread] - 2026-09-05

### Executed — frozen protocol (docs/V75_COST_DILUTION_STUDY.md), one pass, priors held exactly
- **Amendment before the pull** (transparent, committed): the frozen "28 days yields 8 folds" was arithmetically wrong; the power requirement (≥8 fresh folds) dominates, window corrected to 70 days. One pull (Jun 27 → Sep 5, 6,719 bars), all six arms on the same file, cost-inclusive engine, 9×8-day folds.
- **Result**: ws13 −5.42R/141tr, ws17 −4.27R/128tr, ws25 +1.51R/111tr, lf13 −2.65R/143tr, bs17 −4.27R/128tr vs ref −1.21R/158tr — best variant expectancy +0.014R/trade vs the frozen W4 bar of +0.08R. **All five NO-ADOPT, matching all five frozen priors; the cost-dilution thesis is dead on V75.**
- **Reference-failure clause examined, NOT exercised**: ref printed 3/9 positive folds but worst −3.33R (inside its normal certified range) — choppy window, not a regime break; re-pulling after seeing the reference fail would be outcome-fishing.
- **Descriptive finding**: bs17's folds are identical to ws17's — the MinScore+1 frequency lever never bound at current volatility; MinScore is not a live frequency lever on V75.
- **Consequence**: no geometry lever exists on V75; the path forward is the paper A/B gate on the deployed config, and if a cost lever exists it is broker-side (spread tier), not geometry-side. EA and presets untouched.
- Artifact: `artifacts/v75_costdil/costdil_results.json` (+ `walkforward` env block in the doc).

## [V100 net-edge study: NO EDGE + 2y artifact retracted] - 2026-09-05

### Executed — pre-registered study (docs/V100_NET_EDGE_STUDY.md): does the gross edge survive V100's 15x-lower spread cost? NO.
- **Integrity gate caught a systemic confounder first**: the stored Sep-4 2y/210d "gross" V100 runs set spread+tick-value but left `CERT_MIN_LOT/CERT_LOT_STEP` at V75's 0.01 defaults — a broker-impossible lot grid for V100 (true floor 1.0). Every signal traded on negligible dollar size (`max_risk_pct: 0.5` gives it away). Old-code vs new-code on identical envs agree bit-exactly, so the cost refactor was not the cause.
- **Q1 (survival) — the edge DIES.** True-spec net walk-forward, 53×14d folds, ~1,700 trades/config: legacy +29.21→**−20.06R**, v2629 +13.86→**−20.07R**, tp18 +23.09→**−24.55R**. Per-trade cost ≈0.028R (2–3× the naive arithmetic — the −62% price grind shrinks stops while the spread stays fixed, so cost share *rises* over time). Full-period cert at $200: $200→$17.61, DD 94.9% — the true 1.0-lot floor plus early-era wide stops risks up to 20%/trade.
- **Q2 (gate) — nothing passes V1–V6**, matching the frozen prior. V100 stays uncertified; funding follows certification; EA unchanged.
- **Retraction**: the Sep-4 "V100 personality flip" (stack +15.1R on 210d) was an artifact of the same fictional lot grid — under true specs the stack scores **−33.76R (t=−3.00)** on the same window. "No universal geometry" stands for a blunter reason: no validated geometry exists on V100 at all.
- **Standing rule (fourth small-sample-lead-class death, now systemic)**: every cross-instrument cert run must set all five CERT_* spec variables explicitly; any artifact whose `max_risk_pct` implies sizing the instrument cannot trade is invalid on its face. V75 default-spec runs exempt (0.01 IS the V75 truth).
- Artifacts: `artifacts/v100_replay/walkforward_v100_2y_gross_repro.json` (true-spec gross baseline), `walkforward_v100_2y_net.json`, `walkforward_v100_210d_truespec_net.json`, `artifacts/v75_replay/cert_report_v100_2y_net200.json`.

## [Morning status tool + first-trade drill + 2 adjudicator fixes] - 2026-09-05

### Added — scripts/morning_status.py: the one-command morning check (read-only)
- Arm health per terminal (process count via tasklist, EA telemetry write age with a 2h staleness line, ledger veq + integrity), night-gap audit from the UTF-16 terminal journals ("connection lost → authorized" pairs, cross-midnight capable, sub-60s MT5 access-point flaps summarized instead of listed), and go-live gate progress X/30 per arm with days-to-30 at the observed rate. `--strict` exits 1 on unhealthy signals. Validated live: catches the 01:14→08:24 sleep exactly.

### Added — scripts/first_trade_drill.py: prove the paper-data path BEFORE the first real fill (10/10 green)
- Generates synthetic ledgers in the exact EA v26.35 wire format (OPEN/CLOSE/EQ, seconds epochs) in temp dirs and runs the real downstream tools: adjudicator verdicts for empty arms (KEEP COLLECTING), below-gate (ETA projection), clean A-win (P1/P2/P3 all hold), and symmetric-noise pairs (INCONCLUSIVE — the rule refuses to declare on noise); reconciler 7-day gate fires with no broker pull; morning-status ledger parser + cross-midnight journal pairing unit-checked. Ends by restoring truthful real-state artifacts (removes drill-written ones when no real ledger exists yet).
- **Bug found by the drill #1 (HIGH): `ab_adjudicate.py` paired on CLOSE epochs, not the frozen OPEN-epoch rule** — the arms hold different durations under different TP geometry, so in production their CLOSE times would almost never align and the adjudication would starve. Fixed to pair on `open_epoch` (falls back to close epoch only for OPEN-less rows).
- **Bug found by the drill #2 (MEDIUM): zero pairs crashed the adjudicator** (`None` mean formatted with `:+.3f` → TypeError, exit 1, no verdict line). Now prints an explicit zero-pair diagnostic.
- Drill-design lesson recorded in-code: giving the B arm a different `tp_mult` in the "no signal" scenario embeds a REAL winner-pay effect (2.4 vs 1.8) that the paired test correctly catches — the noise arm must share A's outcomes plus symmetric noise.

### Added — docs/MILESTONE_MEMO_v2635.md: one-page milestone memo
- What was claimed (cost-blind +130%), what the re-baseline says (+4.37R net, t=0.35, TP 2.4 negative), the critique replication outcome (cost flaw confirmed; structure claims rejected), the four v26.35 EA fixes, the pre-registered gate as sole authorizer, and the honest standing risks.

## [Verification re-run + CLI hotfix] - 2026-09-05 (morning)

### Fixed — certify_v75.py CLI crashed after writing every report (cosmetic, engine untouched)
- **Bug** — `certify()` pops `r_extra`/`tp_r` from trade records before returning, but `main()`'s trade-dump print loop still read `t['r_extra']` → `KeyError` after the report file was written. Every CLI invocation of the new engine crashed at the final print step; last night's verifications imported `certify()` directly and never hit it. Fix: `t.get('r_extra', 0.0)`.
- **Backward test re-run (legacy engine, CERT_COST_LEGACY=1)** — fresh60 window reproduces the stored `cert_report_legacy_repro_tp18.json` **bit-identically**: all metrics AND all 135 trade records equal (+13.23R / 48.1% / DD 42.2% / $114.76).
- **Forward test re-run (cost-inclusive engine)** — all three re-baselines reproduce exactly: TP 1.8 +4.37R/114/45.6%, TP 2.4 −4.07R/68/39.7%, TP 1.8 @$100 +4.37R/114. Four reports in `artifacts/v75_replay/*_check0905.json`.
- **EA-side deploy gate re-check** — `verify_set_inputs.py` 15/15 presets PASS on v26.35 source.
- **Morning ops check** — both paper arms healthy (v26.35, router TOLERATED at $50 virtual, clean reconnects); PC slept ~01:14→08:24 (accepted: broker archives make any data window pullable on demand; only the paper ledger accrues and sleep nights stretch, never lose, gate time). No closed paper trades yet — gate clock starts with the first fill.

## [Cost-inclusive certification engine + re-baseline] - 2026-09-05

### Fixed — certify_v75.py pays the spread in PnL (fills at bid/ask, not mid)
- **Why** — the critique replication (same day) proved the engine used the 18.5-unit spread only as a veto gate; PnL never paid it. Audit arithmetic said −4.34R on +13.23R; the full dynamic re-baseline says worse.
- **How** — entry fills at the adverse half-spread (BUY at ask, SELL at bid), exit pays the other half via `r_extra`; SL/TP/BE/trail anchor to the real fill like the EA. `CERT_COST_LEGACY=1` restores the cost-blind engine.
- **Integrity** — legacy mode reproduces the published fresh60 run **bit-identically** (+13.23R / 135 / 48.1%) before the new mode is trusted.
- **Re-baseline (fresh 60d, $100)** — TP 1.8: **+4.37R / 114 trades / DD 36.7% / net expectancy +0.038R per trade (t=0.35)** — statistically indistinguishable from zero on this window. TP 2.4: **−4.07R** (negative net of costs; the A/B now adjudicates marginal-positive vs negative). Governor trajectory shifts (MOM+PB auto-disabled at −2.08R; PB carries +6.22R alone). Funding Monte-Carlo re-priced on the net stream: $31 → 10% P(profit), $50 → 39%, $100 → 92% survival, median +$3.42/60d.
- **Consequence** — the pre-registered go-live gate (≥30 positive-expectancy arm-A paper trades + tick reconciliation PASS + watchdog) is the only authorizer; a non-positive gate outcome triggers investigation, not live deployment.
- Artifacts: `cert_report_fresh60_tp18_net.json`, `cert_report_fresh60_tp24_net.json`, `cert_report_fresh60_tp18_net100.json`, `cert_report_legacy_repro_tp18.json`, `funding_plan.json`.

## [Critique replication: Tests A/C, drift audit, cost correction] - 2026-09-05

### Added — docs/CRITIQUE_REPLICATION.md + scripts/critique_replication.py: external critique's demands executed under frozen protocol
- **Why** — an external critique challenged the project's claims (Band Fade contradiction, small-sample "certification", missing costs, EMA regime as noise). Response: verify its factual claims against artifacts, then run its Tests A–C on our own data under a pre-registered protocol (`frozen before execution`, one pass).
- **Test A (variance ratios, 8s→256h + supplementary 0.5h/1h/2h/4h)** — all inside surrogate null bands (2.46M ticks + 19 months of H1): no linear trend/mean-revert structure at any horizon. Generator confirmed memoryless at every tested scale.
- **Test C (regime-conditional forward drift, exact EA mirror)** — the EMA regime axis carries NO directional information; sign is weakly anti-continuation (BULLISH label → negative forward drift, consistent 8/8 across eras/horizons, strongest fresh-era episode t=−2.57). Vol terciles: nothing. The regime axis's remaining legitimate role is volatility-aware gating/sizing, never direction.
- **Cost flaw CONFIRMED and quantified** — the cert engine never subtracted the 18.5-unit spread from PnL (veto gate only). Corrected: +13.23R → **+8.89R net** (0.098R→0.066R/trade). Engine fix queued so all future certs are cost-inclusive.
- **Small-sample honesty applied to ourselves** — fresh60 Wilson 95% LB = 39.9% win rate, per-trade t=0.96: the honest claim is "consistent with zero-to-small positive expectancy", and the ≥30-trade live paper gate (not backtests) decides live value. Drift audit: 19-month −78% downtrend then a near-doubling Feb→Jul 2026 — long-run drift real but sign-unstable; hourly-grain drift unpredictable (t=−1.62); drift capture would be a position strategy, not M15.
- Artifacts: `artifacts/critique_replication/results.json`, `vr_long_horizon.json`.
- **Queued fix**: spread-cost-inclusive fills in certify_v75.py (all future certifications cost-inclusive, flagship numbers re-baselined once).

## [Drift-vs-Σ tracker: CLOSED (1/3) — no EA integration] - 2026-09-05

### Registered → executed in one pass (docs/DRIFT_SIGMA_TRACKER.md, artifacts/drift_sigma/)
- **Question**: can a causal tick-stream tracker (EWMA drift µ₂ / EWMA σ₂ over trailing 1800 steps) estimate the generator controller's state well enough to feed the EA a regime-confidence input?
- **Tick lake extended**: July gap filled (+1,165,557 quotes → 2.46M ticks, Jun 7 → Sep 2).
- **K1 predictiveness — FAIL, sign inverted**: quintiles flat, daily spread t = −1.90 (wrong sign), Spearman −0.056 → the EWMA drift estimate **mean-reverts** (hours that trended hard give it back). No positive predictive power.
- **K2 economic gating — FAIL per frozen bar**: gating kept +9.73R/72 vs blocked +3.50R/63 (D = +6.23R, better per-trade expectancy) but t = 0.57, worst fold −5.83R — two of three requirements missed. Base arm reproduced the published +13.23R/135 exactly (integrity check held).
- **K3 vol forecast — PASS decisively**: tick-EWMA σ beat M15 ATR(14) on all 716 hours (RMSE 7.7× lower, MAE 11.9× lower; caveat: shared-scale advantage vs a range-based proxy).
- **Verdict: CLOSED (1/3)** — no EA change. Only legitimate open thread: K1's inversion suggests a *fade-the-drift* mechanism, re-registrable only as a new protocol. The M15 regime layer remains the validated intelligence.

## [Generator fingerprint study: the V75 machine decoded] - 2026-09-04 (night)

### Added — `scripts/generator_fingerprint.py` + docs/GENERATOR_FINGERPRINT.md: how the tick generator actually works
- **Data**: 1,295,215 real ticks over 30 continuous days (broker archive), cadence cross-validated against broker-history probes (the feed itself is 0.5 Hz — one tick per 2.000 s, zero jitter: a deterministic step machine).
- **Findings (T1–T7)**: Gaussian steps (skew 0.00, kurtosis 0.01); up/down 0.4998; tick-return ACF max |ρ|=0.0025 over 100 lags (no direction memory); run lengths match a memoryless coin to 4 decimals; variance ratio ≈ 1.00 at 1s–1m and 0.97–0.98 at 15m–1h (pure random walk); no volatility clustering at tick scale; hour-of-day vol flat to 1.8% (per-step vol targeting confirmed).
- **Conclusions**: "working ahead of the generator" at tick level is mathematically impossible — each step carries zero information about the next, so tick-momentum, spike-runs, and tick-mean-reversion are coin-flip noise by construction (consistent with the earlier tick-fade rejection). The only evolving signal is slow drift-vs-vol — exactly what the M15/H1 regime layer and GARCH already estimate. **The M15 operating point is the correct one, not a compromise.** The 2s clock is an execution/simulation gift (event-exact fills, reconciler ground truth).
- No EA config changes; research direction settled: regime intelligence at bar scale, not tick-speed reflexes.

## [v26.35 — Full pre-live code audit: 4 bugs fixed] - 2026-09-04 (night)

### Fixed — findings from the line-by-line audit (docs/FULL_EA_AUDIT_v2635.md)
- **CRITICAL (paper)**: the ACCOUNT GUARD in `OpenTrade` compared fleet risk against **real account equity** while sizing used paper virtual equity — with $0.57 real vs $50 paper, every paper entry was vetoed (`fleet $0 + $6.25 > $0.086 cap`). Root cause of the weeks-long v26.28-era paper silence. Guard now uses the same equity basis as sizing (`PaperActive() ? PaperEquity() : AccountEquity()`). Consequence: paper A/B statistics genuinely start from tonight; pre-fix paper data is zero by construction.
- **HIGH (live)**: `StratEnabledOrProbe(i)` returned `true` on out-of-range index — a latent governor bypass on any future slot-index slip (the v26.34 VB-BURST `8` bug would have sailed through). Now fail-closed (OOB = deny).
- **MEDIUM (live)**: default `InpMagic` was `7788211` — an orphan not in the fleet CSV, invisible to the fleet guard and close filters on a default-input attach. Now `7788075`.
- **COSMETIC**: self-test banner had 9 format specifiers / 6 args (doubles consumed `%d` slots → garbage `regime 1250694476/5`); counters cast to int. Dashboard fleet-cap display got the same equity-basis fix.
- **Verified clean**: sizing chain = certified model; server-side SL/TP always attached; stops-level validity + entry-abort guards; exit ladder = certified ladder; close detection triple-redundant with dedupe; state files symbol-tagged and terminal-local; all 15 presets PASS; zero CB remnants in live paths.
- **Deployed**: MetaEditor 0 errors / 0 warnings, `.ex5` synced to 13 instances, both paper terminals auto-restored on v26.35 (banner, `TOLERATED` router at $6.31/12.6%, paper $50) — paper A/B continues on the fixed engine.

## [MOM-standalone duel: REJECT] - 2026-09-04 (night)

### Registered, executed, closed — lone-momentum trading is noise-chasing (docs/MOM_STANDALONE_DUEL.md)
- **Trigger**: the 2026-09-04 19:15–21:15 V75 waterfall (1,417 pts) that the EA skipped via the lone-momentum demotion — hindsight showed 2 would-be SELL winners. Treated as a hindsight teaser and pre-registered instead of acted on.
- **Engine**: `certify_v75.py` gained a surgical `mom_standalone` toggle (default off — verified to reproduce the published fresh60 run to the trade: +13.23R/135/48.1%).
- **Window (a), fresh 60 days, 8 paired folds**: demote **+13.23R/135** vs standalone **+10.01R/167** → D = −3.22R ✓, t = −1.70 ✓, worse in 6/8 folds (one −11.55R blowup fold) → **REJECT**. The standalone arm even triggered governor auto-disable (MOM, MOM+PB) and *still* finished worse while being rescued.
- **Window (b), 19 months (z-gate data), 28 paired folds**: full-window totals confounded by stateful-governor divergence (auto-disable killed PB in the demote arm: 69 vs 719 trades) — clean fold deltas: +2.17R/fold, t = +1.15, neither REJECT nor ADOPT → **NO-ADOPT** for that era (standalone still net-negative overall, −23R).
- **Methodology lesson recorded**: in long continuous sims the stateful governor (auto-disable, loss-scaling) diverges between arms — full-window totals stop being a pure signal-rule comparison; fold-based paired deltas with state reset are the honest statistic (all future duels).
- **Decision**: `InpMomentumStandalone` stays `false`; deployed preset and paper A/B untouched.

## [Funding-growth plan tool] - 2026-09-04 (evening)

### Added — `scripts/funding_plan.py`: balance simulation + withdrawal-schedule comparison
- Replays the certified 60-day TP 1.8 trade sequence (135 trades, `sd`/`r` pairs) through the exact EA money layer (`v75_money.py`: min-lot clamp, 0.75^loss scaling, 20% effective-risk cap, compounding) at $31/$50/$100/$200 starting equity.
- **Monte Carlo**: 1,000 shuffles of the trade order (geometry kept paired with its own outcome); measures P(profit), P(ever min-lot-stuck), terminal-equity percentiles.
- **Withdrawal policies simulated inside the walk** (later trades sized on post-withdrawal equity): compound / weekly bank-above-$100-buffer / weekly bank-half-of-profit.
- **Findings**: $31 viable in name only (93% stuck, 25% profitable, median $22); $50 coin-flip (59% stuck, p05 ≈ $19); **$100 = safe floor (97.6% profitable, path-independent +$64.76, veto rare and recovering)**; $200 adds only veto headroom. Recommended schedule: weekly withdrawal of everything above a $100 working buffer (banked $92 in 60 days at $100 start, min equity $72).
- Outputs: `artifacts/v75_replay/funding_plan.{json,md}` (md carries the frozen recommendation). `docs/LIVE_READINESS.md` funding section updated to cite it.

## [Paper A/B live + LIVE readiness package] - 2026-09-04 (evening)

### Added — both paper arms running (operator steps 2+3 completed autonomously)
- **Arm B terminal created without user action**: cloned the MT5 install to `%LOCALAPPDATA%\MitemshubMT5_B` (non-portable first launch generated data folder `49E0383C…`), copied login/`accounts.dat`/`servers.dat` from terminal A, seeded a UTF-16 `chart01.chr` cloned from A's validated profile with `InpTpMult=2.4` + `InpMagic=7788100`, ran `sync-mt5.ps1` (13 instances), launched — EA auto-attached with the v26.34 banner, paper mode, router TOLERATED, authorized on the same demo account.
- **chart04 landmine resolved** by MT5's own exit-flush: the Default profile now holds only chart01 (EA, validated config) + one plain chart; detacher verified nothing to strip.
- One controlled mishap during B's setup: the name-based process fallback killed terminal A alongside B; A was relaunched immediately and auto-restored the validated config (v26.34 banner, TOLERATED router). No state lost (paper mode).

### Added — live-trading readiness (`docs/LIVE_READINESS.md`)
- **`MitemshubAI_VOL75_LIVE.set`** — identical to `VOL75_FINAL` except `InpLiveExecution=true` (TP 1.8, magic 7788075); `verify_set_inputs.py` PASS.
- **Broker-exact funding math** (`order_calc_profit`-based, cross-checked against the EA's FIT ROUTER): V75 min-lot stop-risk $6.19 ⇒ **$31 equity floor** (20% cap); $10 accounts cannot trade V75 on this broker (lot floor, not strategy); $2,800 unlocks V100 (uncertified).
- **Fresh 60-day certification** (Jul 7 → Sep 4): TP 1.8 **+13.23R, $50 → $114.76** (135 trades, 48.1% WR, 42.2% max DD) vs TP 2.4 +4.60R — third consecutive fresh window with TP 1.8 ahead.
- **Pre-registered GO-LIVE GATE**: A/B expectancy positive at ≥30 trades + tick reconciliation PASS + watchdog CERTIFIED; documented accelerated option (20 trades + recon PASS) and the live-deploy procedure.

## [v26.34 — Crash/Boom engine physically removed] - 2026-09-04

### Removed — the dormant CB engine is gone from the source tree (user request)
- **Deleted**: `mql5/MITEMSHUB_AI/CrashBoom/` (CrashBoomEngine, CrashBoomStrategy, SpikeDetector, TickPatternAnalyzer, MultiTimeframeConfirm, TimeOfDayAwareness, SymbolCalibration, DynamicRiskSizing) — ~9 modules reachable only from the retired CB path. History preserved in git and `artifacts/v2633_source_backup/`.
- **Deleted from the EA**: every CB input (mode/is-crash/micro-fade/AUTO-param sources/quick-TP/tick-fade/burst-guard group), the learned CB spike gate (EWMA + `MitemshubAI_cblearn` persistence), the burst-guard policy self-check table, `CBRecordReject` reject-accounting (counters kept, no longer incremented), the CB signal branch and CB exits in both live and paper manage paths.
- **Survived, deliberately**: the Volatility-only init guard (now cites v26.34), the tick recorder (`TickRecorder.mqh` relocated to `Microstructure/` — the opt-in microstructure archive, default OFF), `OpenTradeLive` (the engine-plan opener, kept for the VB-BURST leg) now using the standard risk-planned sizing chain, and the v26.12 reject counters for state-file continuity.
- **Strategy table**: 9 → 6 slots (PB/BO/MOM/MR/BF + VB-BURST at slot 5); `STRAT_SLOTS=6`, names table, governor thresholds, and the state-file loader (old rows 5–8 dropped cleanly) all aligned. Fixed a latent bug in the same stroke: the VB-BURST governor gate called `StratEnabledOrProbe(8)`, which would have silently bypassed the governor on the 6-slot table.
- **Verified**: MetaEditor compile **0 errors / 0 warnings**, fresh `.ex5` synced to all 12 instances (108 orphans pruned on first sync), `verify_set_inputs.py` passes on the V75 presets (zero CB keys), weekly drift report parses v26.34 banners.


## [Paper pipeline: weekly scheduled run] - 2026-09-04

### Added — automated weekly verdict tracking (no manual runs to remember)
- **`scripts/paper_pipeline_weekly.cmd`** — scheduled-task entry point (repo's `%~dp0` wrapper convention, venv python); appends every run to `artifacts/v75_replay/paper_pipeline_sched.log` so unattended runs are permanently recorded.
- **Scheduled task `Mitemshub Paper Pipeline Weekly`** — Sundays 06:30, deliberately 30 min after the existing `Mitemshub Weekly Data Refresh` (Sundays 06:00) so reconciliation/regime tools see the week's fresh bars. Read-only by design.
- Verified end-to-end via `Start-ScheduledTask`: run completed with result 0, next fire 2026-09-06 06:30. From the first paper trade onward, the log's diff section is the automatic "which verdicts changed" report.

---

## [Regime-gate study round 2 (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gating re-tested on the 210-day sample: NOT VALIDATED, three independent ways
- **"What changed after Aug 9" — nothing anomalous.** Post-Aug9 legacy fold z-scores −0.08..−1.23 sit inside the pre-Aug distribution (9/22 pre-Aug folds were also negative); fold-to-fold R autocorrelation is **−0.12** (a momentum regime gate would have scored +23.7R vs buy-and-hold-the-strategy's +51.4R). A perfect ex-ante gate's oracle bound is +40R over legacy — the prize exists, so the question moved to trade level.
- **Trade level (scripts/regime_gate_study_v2.py, pre-registered calibration F01–F16 / validation F17–F26 split)**: on 283 calibration PB trades, mild separators finally appear at real sample size — mid-|z| bucket +0.203R vs tails −0.032R, hour-bucket B1 +0.270R, and the family-throttle's causal basis is real but weak (trades taken while the 10-trade window is below −3R: +0.013R vs +0.099R cold). The chosen `|z| ≤ 1.08` gate was directionally right out-of-sample (vetoed bucket worse OOS, kept-total higher) but **deleted 56% of trades to gain +0.3R** → G3 fail → GATE NOT VALIDATED.
- **Round-4 walk-forward (walkforward_210d_r4_gate.json, reference = tp18)**: the never-tested tp18+throttle combination scores **+45.88R vs tp18's +52.42R — the throttle costs 6.5R on the validated base config**. Every adaptive variant (throttle, gate+stack, tp18+thr) fails V2/V3/V4/V6; static **TP 1.8 remains the only walk-forward-consistent config**.
- Standing architecture: the harness keeps `--family-throttle` for re-testing as paper data grows, and trades now carry `atr_pct` in their records for future regime work — but no gate is deployed. The EA's existing outcome-adaptive machinery (per-strategy auto-disable, 3-loss pause, probe re-entry) remains the only adaptation with a validated basis.

## [TP-duel fresh-data test] - 2026-09-04

### Studied — the last uncontaminated V75 window adjudicates the TP duel: CONFIRMS-TP18-LEAD
- **Design** (docs/TP_DUEL_FRESH_TEST.md, frozen before execution): legacy TP 2.4 had never run on pre-Feb-2026 bars, so the paired difference on 2025-08 .. 2026-01 was uncontaminated; D = legacy − tp18 with registered thresholds (CONFIRMS ≤ −3.0R & t ≤ −1.0; tie-band between; UPSET ≥ +3.0R & t ≥ +1.0 relabels the favorite but never touches the preset); 3 registered ~2-month folds; one look, then closed.
- **Result**: legacy +10.86R vs tp18 +20.98R → **D = −10.12R, fold deltas [−7.71, +4.42, −13.70], t = −1.06 → CONFIRMS-TP18-LEAD**. TP 1.8 wins 2/3 folds; both arms positive on the window; deployed preset unchanged; paper A/B proceeds as the final judge (two-sided by design).
- **Standing duel record**: Feb–Sep 2026 (26 folds, ~500 tr): tie (+52.42 vs +51.44). Aug 2025–Jan 2026 (fresh one-shot): tp18 by +10.12R. Historical power for this question is now exhausted — paper data is the only remaining adjudicator, as it always was. Also notable: the tp18 family is now positive on **three** disjoint multi-month spans (Oct–Dec 2024 +17.4R probe, Aug 2025–Jan 2026 +20.98R, Feb–Sep 2026 +52.4R).

## [V100 two-year walk-forward] - 2026-09-04

### Studied — the stack-vs-legacy flip was fold-count noise: the veto+depth stack loses on BOTH instruments; question settled
- **Power**: 2 years of V100 bars (2024-08 .. 2026-09, 71,038 M15 bars; 210-day set snapshotted), 53×14-day folds, ~2,000 trades per config — ~5× the V75 round-3 power. Driver gained env knobs (`WF_FOLD_DAYS`, `WF_CONFIGS`) so per-symbol runs never touch V75 defaults.
- **Result**: legacy TP 2.4 +31.66R (26/53 folds, t=+0.67) | **v2629 stack −7.09R (t=−0.18)** | tp18 +25.01R (reference). The 210-day stack lead (+15.1R vs legacy −2.05R) **inverts completely under power** — the stack is now measured harmful on V75 (~33R drag) AND net-negative on V100. There is no instrument where it wins; the "V100's config" hypothesis is dead.
- **Second settled question**: no V100 geometry validates (best t=+0.67, worst fold −13.5R). V100 stays uncertified — the fit router may name it, but funding follows certification, and V75 remains the only certified instrument.
- **Meta-lesson (third occurrence)**: August filters → 33R drag at 26 folds; mid-z effect → sign flip on fresh data; V100 stack flip → inversion at 53 folds. Every small-sample lead this project has chased died under power. The pre-registered walk-forward discipline is the only reason none of them reached the EA.

## [Pipeline runner] - 2026-09-04

### Added — scripts/paper_pipeline.py: one command runs every study tool and reports which verdicts changed
- Dynamic tools re-executed (all self-gating, read-only): A/B adjudicator, paper↔tick reconciler, regime-gate replication v3, weekly report (ledger + watchdog + preset drift). Registered one-look contracts read from artifacts, never re-run: z-gate Phase A, V75/V100 walk-forwards, regime3 interim.
- Arm A/B discovery is automatic (chart-magic scan of terminal profiles, ledger-presence fallback). Verdict extraction handles VERDICT/Verdict lines and the watchdog's CERTIFIED/VIOLATIONS format.
- State: `artifacts/v75_replay/pipeline_state.json` — every run diffs verdicts against the previous run and prints NEW / CHANGED (was → now) / unchanged. This is the "re-run once a week of paper data exists and report what changed" deliverable: it is one command, and it reports nothing-but-the-truth today (arm dirs: none — still gated on the MT5 reload; zgate NOT VALIDATED; both walk-forwards NOT VALIDATED for adaptive configs; watchdog CERTIFIED 36/0/28).

## [Z-gate Phase A] - 2026-09-04

### Studied — the z-only gate gets its pre-registered fresh-data test and fails comprehensively: NOT VALIDATED, final for this generation
- **Protocol first** (docs/Z_GATE_PROTOCOL.md, frozen before any data point was examined): Phase A on strictly untouched history (2024-08 .. 2026-01 — zero overlap with the burned Feb–Sep 2026 window), gate forms committed in advance (PRIMARY tertile-keep, FALLBACK median-keep), calibration pre-bar C1–C3, one-shot validation W1–W5 with segment-consistency requirements, multiple-comparisons ban on further threshold archaeology. Pull tooling gained `--end` for historical windows; `z_gate_phaseA.py` executes the contract mechanically.
- **Outcome**: calibration passed decisively (720 PB trades, keep +0.125R vs veto −0.038R, gap +0.163 → edges frozen |z| ∈ (0.420, 1.240]) — then validation (one shot, 170 trades) **flipped sign**: kept +0.017R vs vetoed +0.159R (gap −0.14), kept only 25% of trades, and keeping mid-z trades cost −12.9R/−7.4R per segment against +20.98R for trading everything. W1–W5 all false → NOT VALIDATED, final.
- **Reading**: the mid-z effect was window-luck with a clean mechanism-shaped costume — it fit in Feb–Sep 2026, reversed in Aug 2025–Jan 2026. This is exactly what the protocol was designed to catch: one look, fresh data, sign-flip exposed. The |z| gate question is closed at this sample size.
- **Descriptive silver lining** (not a criterion): the tp18 base strategy scored +20.98R on the Aug 2025–Jan 2026 window — positive on two disjoint ~7-month spans now.

## [Cross-instrument certification: V100] - 2026-09-04

> **SUPERSEDED 2026-09-05**: the V100 numbers below (and the "personality flip") used the V75 0.01-lot default — a broker-impossible grid for V100. See the 2026-09-05 net-edge study entry and docs/V100_NET_EDGE_STUDY.md. Kept for the audit trail.

### Studied — the harness now certifies any Volatility symbol; V100 measured, NOT VALIDATED, and the lesson is structural
- **Capability (sharpening the Volatility mandate)**: `certify_v75.py` is now symbol-agnostic via env (`CERT_DATA_DIR/CERT_SPREAD/CERT_USD_PER_UNIT_PER_LOT/CERT_MIN_LOT/CERT_LOT_STEP/CERT_SPREAD_GATE_FRAC`), `pull_v75_week.py` takes `--symbol/--outdir`. V75 defaults byte-identical; all prior artifacts reproduce.
- **V100 fit (live specs)**: honest broker tick value (identity verified — unlike V75's 100× lie), spread 0.26 (3% of a 1.7×ATR stop, so the spread gate passes instead of strangling), min lot 1.0 → $8.76/min-lot trade = 4.4% at $200. Risk-wise the best Volatility instrument yet.
- **V100 verdict (210 days, 26 folds, ~500 trades, pre-registered V1–V6)**: every config NOT VALIDATED. The surprise is a **personality flip vs V75**: legacy TP 2.4 scores −2.05R (t=−0.09) while the v26.29 stack scores +15.1R (t=+0.69) — the veto+depth filters that were a 33R drag on V75 are a +17R swing on V100. There is **no universal geometry**: instrument personality differs, and every symbol needs its own walk-forward + paper evidence before funding. Per protocol nothing is deployed for V100; the stack-positive lead (t=0.69, 12/26 folds) is recorded for a future, properly powered study (2y of V100 bars or a paper arm) — not promoted on t=0.69.
- **Standing conclusion hardened**: V75 (TP 1.8) remains the only certified instrument. "Sharpening Volatility skills" = per-instrument certification discipline, now executable in one env-prefixed command for any symbol in the family.

## [MITEMSHUB AI EA v26.33] - 2026-09-04

### Changed — VOLATILITY-ONLY MANDATE (owner decision: nothing to do with Crash/Boom, ever)
- **`OnInit` refuses Crash/Boom symbols** — `INIT_FAILED` with a loud log naming the mandate; the EA can no longer be attached to a Boom/Crash chart by accident. Rationale on record: spike-gap mechanics fill stops at post-spike quotes (structurally incompatible with the BE/trail ladder), the tick-burst family measured net-negative across the full 70-cell calibration, and no CB walk-forward exists or is planned.
- **Fit-router universe trimmed** to Volatility 10/25/50/75/100 — the router can no longer recommend Crash 500 (or any CB) to a small account; its advice now always points inside the certifiable Volatility family.
- **CB presets deleted** (`MitemshubAI_BOOM1000_CB.set`, `MitemshubAI_CRASH1000_CB.set`) from the repo and all terminals; sync prunes them henceforth (24 orphans pruned on this deploy). CB *engine code* stays dormant for historical reference — nothing references it on Volatility charts.
- **Banner rebranded** ("Volatility-Only | Standard Mode"); `APP_VERSION` → 26.33. Deploy gate passed (preset validator PASS, 12 instances synced, fresh `.ex5` newer than source). The v26.32 strategy config on the paper presets is untouched.

## [Regime-gate study round 3 protocol] - 2026-09-04

### Added — scripts/regime_gate_study_v3.py: pre-registered replication protocol for the near-miss separators, triggered by paper data
- **Protocol** (fixed before any paper data exists): bucket edges FROZEN from the v2 calibration artifact (abort rather than re-fit if missing); sample gate ≥150 closed arm-A paper trades over ≥21 days; features attach to ledger trades by pairing OPENs to harness sig_t ≤120s (z/hour recomputed with identical definitions; unmatched counted as signal-drift indicator); criteria R1 mid-z paper gap ≥+0.10R, R2 hour-B1 gap ≥+0.10R, R3 AND-keep economics ≥+0.15R/trade over ≥40% of trades, R4 same-sign agreement on the harness companion sample over the paper window. Verdict: VALIDATED-CANDIDATE (→ EA-input design + dedicated walk-forward + paper A/B, never auto-deploy) or NO GATE. Interim mode reports the in-sample extension when run without paper data.
- **Interim result already informative**: on all 440 harness PB trades (Feb–Sep) both gaps persist (mid-z +0.129, hour +0.212) — but the clean-OOS context (v2 validation folds only, n=90) splits them: **mid-z +0.316 (replicates, stronger than calibration), hour-B1 −0.281 (sign flips — calibration-window luck)**. Expectation for the paper round: the v2 AND-gate likely fails via R2, and the surviving candidate is a z-only gate, which would need its own pre-registered protocol — the v3 artifact preserves the evidence trail for that decision.
- Still gated on the operator reload: no paper ledger exists yet.

## [Weekly report tooling] - 2026-09-04

### Added — scripts/paper_weekly.py: one command for ledger expectancy + watchdog verdict + preset drift
- **[1] Ledger expectancy** — per terminal: n, days, total/mean R (vs the walk-forward tp18 reference +0.105R/trade), WR, $pnl, virtual-equity drawdown, worst streak, exit-reason split; explicitly exploratory below 30 closed trades. Prompts the A/B adjudicator + tick reconciler once n ≥ 30.
- **[2] Watchdog** — reuses demo_watchdog's audit()/paper_audit() verbatim (same checks, same verdict).
- **[3] Preset drift, three layers** — (a) chart-attached inputs (parsed from each terminal's UTF-16 `.chr` profile: the ground truth for what the EA would run with after a reload) vs the magic-matched deployed preset — catches the "preset updated, EA never reloaded" failure mode; (b) repo preset vs deployed Common\Presets copy; (c) terminal .ex5 mtime vs repo source. Also flags banner-version staleness, duplicate magics across charts, and V75 charts with InpLiveExecution=true. Read-only; writes weekly_report_YYYYMMDD.json.
- **First live run caught two real findings**: chart01 runs v26.28-era inputs (InpTpMult 2.4 vs deployed 1.8 — the never-done reload, now machine-verified), and chart04 is a second V75 chart with **InpLiveExecution=true and the same magic 7788075** — on demo it contaminates the experiment (double signals, one magic); migrated to a funded terminal as-is it would trade real money on unvalidated settings. Both flagged with explicit NEXT ACTIONS.

### Added — scripts/reconcile_paper_ticks.py: verifies the live paper engine against the tick-study baseline the first week data exists
- **Purpose** — the fast-fail tick study validated the EA exit ladder offline against 1.5M real broker ticks; this tool checks the LIVE paper engine still matches that reality and catches drift early. Per closed ledger trade, re-simulates the identical ladder (constants imported from study_fastfail_ticks — single source of truth) through real broker ticks from the ledger's own fill, and measures: ladder delta (ledger R − tick R), fill shift vs the fair tick fill (quantifies the InpPaperSpreadMult conservatism), exit-reason agreement (STOP→SL / TARGET→TP), and exit-price sanity (≤3×median spread).
- **Pre-registered verdicts**: KEEP COLLECTING (<7d coverage) / MATCHED (|mean ΔR| ≤ 0.10R, CI covers 0, mechanics pass) / OPTIMISTIC-DRIFT (ledger better than reality — dangerous) / CONSERVATIVE-DRIFT (ledger worse — cert numbers understate live) / REASON- or PRICE-DRIFT (mechanics diverged). Auto-pulls missing tick windows from the broker (pull_v75_ticks.py).
- **Self-tested against the real 1.5M-tick file** with synthetic ledgers in the exact EA wire format: zero-bias → MATCHED (Δ −0.007R, CI[−0.057,+0.041]), +0.25R → OPTIMISTIC-DRIFT, −0.25R → CONSERVATIVE-DRIFT, short window and missing ledger → KEEP COLLECTING. All five verdicts correct; injected +4.0 fill shift recovered exactly.
- **Ledger-format correction found on the way**: ledger epochs are SECONDS (TimeCurrent), not ms. Fixed a latent units bug in scripts/ab_adjudicate.py (pairing tolerance was 25h instead of 90s; days/ETA 1000× off); re-verified pairing at 60s offsets and sane ETA.

## [A/B adjudicator tooling] - 2026-09-04

### Added — scripts/ab_adjudicate.py: pre-registered decision rule for the TP 1.8 vs TP 2.4 paper arms
- Fixes the verdict rule **before** any paper data exists: data gate (≥30 closed trades/arm, with ETA from observed rate), greedy pairing by OPEN epoch within 90s (arms share the signal engine and broker clock), then declare only if P1 |paired t| ≥ 1.0, P2 sign agreement between paired delta and total-R difference, P3 ledger integrity (dangling OPENs, veq discontinuity). Otherwise KEEP COLLECTING / INCONCLUSIVE. Scope note: adjudicates TP only — the veto/depth question was settled by the 210-day walk-forward and must not be resurrected on paper subsamples.
- Self-tested on synthetic ledgers in the exact EA wire format, 5 scenarios (A wins, B wins, tie → INCONCLUSIVE, <30 trades → KEEP COLLECTING with ETA, missing arm → KEEP COLLECTING): PASS. Key validity detail: paired tests need shared per-pair market noise to have power (independent draws are unpairable) — real arms share signals, so this holds live.
- One command the moment data flows: `python scripts/ab_adjudicate.py --a-dir "<terminalA>/MQL5/Files" --b-dir "<terminalB>/MQL5/Files"` → `artifacts/v75_replay/ab_adjudication.json`.

## [VOL75 preset v26.32] - 2026-09-04

### Changed — 210-day walk-forward (26 folds) overturns the August filter conclusions
- **Data** — pulled 210 days of broker M15/H1 (2026-02-06 → 2026-09-04, 20,160 bars; 40-day snapshots preserved as `m15/h1_40d_snapshot_20260904.csv`). Round 3 of scripts/walkforward_v75.py: 26×8-day folds, 5 configs, pre-registered criteria (V1–V6), ~508 trades per config.
- **Result** — the strategy family was never broken: legacy geometry scores **+51.4R (t=1.57)** over 7 months; August (the basis of rounds 1–2) was merely a drawdown stretch. **TP 1.8 alone is the best config: +52.4R, t=1.68, 15/26 folds positive** — the only candidate passing the edge criteria (V1 total>0, V4 beats legacy, V5 median>0, V6 t≥1.5). The v26.29 static stack (EMA-side veto + pb-min 0.60) measures **+18.3R — a ~33R drag** vs legacy on the long sample: curve-fit to August, now **OFF** (`InpPbEmaSideVeto=false`, `InpPullbackMin=0.30` in VOL75_FINAL.set; `InpTpMult=1.8` kept). The family throttle adds nothing over tp18 (+50.4R).
- **Still honest** — every candidate failed the strict 60%-positive-folds bar (58% best). Modest, choppy edge on one instrument/broker/regime-stretch; the paper run remains the final gate before any live capital.
- Note: 4-fold walk-forwards on 5 weeks of data are noise machines. Minimum viable validation from here on: 25+ folds or paper data, never both-datasets-from-August.

## [v26.31 strategy round (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gate: the honest answer is that no causal regime feature separates PB wins from losses
- **Diagnostic** — characterized every walk-forward fold (ATR level/percentile, EMA separation, trend age, |z|, path efficiency): F3 (Aug 17–25) was the *most* trending fold (net +7.2%, highest path efficiency) yet PB's *worst* (−9.07R) — runaway markets don't retrace; churn happens in all measured regimes. Every causal feature split tested put BOTH buckets negative; vetoing "bad-regime" trades would mostly just delete trades (some good).
- **Built anyway, as outcome-adaptation instead** — `certify_v75.py --family-throttle`: when the PB family's last 10 trades sum < −3R, PB-family signals need a probe (every 5th) until the window recovers. Zero fitted regime constants; the gate watches realized expectancy only. Full-period: −8.03R → −4.72R, DD 33.7% → 24.8% (on legacy entries, honest booking).
- **Pre-registered gate round (scripts/walkforward_v75.py round 2, artifact walkforward_v2631_gate.json): NOT VALIDATED.** Throttle-on-legacy: +0.92R total vs legacy +1.36R (G1 ✗ — the legacy book's interleaved strategies blunt it end-to-end), positive folds 1/4 (G2 ✗). gate+stack: +7.35R vs stack +7.06R (G4 ✓, tiny gain), positive folds 1/4 (G5 ✗), worst fold −4.0R (G6 ✗). Conclusion: the static **tp18-only** config remains the only walk-forward-consistent improvement (+5.49R, positive 3/4 folds); throttle helps the full-period metric but not fold-consistency; the deployed v26.29 stack (veto+depth) is carried by F1–F2 luck per round 1. Standing decision unchanged: paper data adjudicates, not these folds.

## [MITEMSHUB AI EA v26.30] - 2026-09-04

### Added — Min-lot risk router: tiny accounts get truth, not silent ruin
- **Why** — at $10 on V75 the broker minimum lot (0.01) risks the *full calibrated* $5.10 ≈ 51% of the account on one trade; the 20% cap then vetoes every signal, and before this version the EA did so **silently** — the operator had no way to know the instrument cannot fit the account.
- **`RunFitRouter()` (init) + OnTick gate** — measures the chart symbol's smallest achievable stop-risk (broker min lot × calibrated tick value at the EA's real stop geometry, `InpRouterScanATR`×ATR): fits the 0.5% plan → good fit; exceeds plan but inside `InpMaxEffectiveRiskPct` → tolerated with loud per-trade risk warning; exceeds the cap → entries refused (`g_fit_ok=false`) and `ScanFitAlternatives()` prints which monitored instruments *do* fit. Auto re-checks when equity grows 50% (a grown account may unlock the symbol). Emits a `fit` telemetry event; both money paths use the v26.25 `CalibTickValue()` identity — the router must not inherit the broker's 100× tick-value lie (raw-broker math falsely "fits" V75 at $0.05/trade).
- **Measured with live broker specs (calibrated)** — at $10 every monitored symbol is refused (cheapest honest fit: Crash 500 ≈ $2.23/min-lot trade → needs ≈ $12); V75 needs ≈ $26. At $50 all ten symbols fit (V75 = 10.2% per trade). Instrument choice cannot be defaulted any more: the EA states the minimum funding for each chart.
- Inputs default ON (`InpFitRouter=true`, `InpRouterScanATR=1.7`), pinned in VOL75_FINAL.set; paper mode untouched.

---

## [MITEMSHUB AI EA v26.29] - 2026-09-04

### Changed — VOL75 strategy: first positive certification (+0.85R, was −30.05R)
- **Why** — cert200 forensics showed PB/MOM+PB's −29R was three stacked causes: (1) the cert harness booked every SL as −1.00R even after break-even had moved the stop (~23.5R accounting artifact, fixed in scripts/certify_v75.py with `--legacy-sl` preserving the old numbers exactly); (2) an asymmetric exit ladder (TP 2.4R vs −1R losses with winners PLOCK-capped ≤0.5R); (3) genuine entry-churn (26/34 losers went ≥0.25R in favor first, then rolled over).
- **Fix (VOL75_FINAL preset)** — `InpTpMult` 2.4 → **1.8**; new input `InpPbEmaSideVeto=true` (veto the pullback leg when the close pierces EMA20 against the trend — the single biggest contributor, −30.05 → −3.17R); `InpPullbackMin` 0.30 → **0.60** (skip shallow chases). End-to-end through the full governor: **$200 → $213.24, +0.85R, WR 50%, max DD 20.2%** (n=56). At the paper scenario ($50): $50 → $52.09, −1.13R vs the old preset's $50 → $19.70.
- **Caveat carried, not buried** — the EMA-side veto showed no separation on the independent 103-trade baseline (−0.62 vs −0.59 R/trade) and TP 1.8 partially contradicts the v26.27 OOS-validated 2.4. This stack is the paper run's candidate, not proven edge; walk-forward validation is the gate before any funded deployment. EA defaults stay OFF (`InpPbEmaSideVeto=false`) so other instruments are unaffected.
- Also — fast-fail reflex (cut stalled trades early, re-enter) was tested and **rejected by the data** on M15 bars (−0.72R vs −0.13R on the filtered stack): BE already rescues the trades the reflex would convert into small losses. A tick-level version can be revisited once the paper ledger has data.
- **Tick-level fast-fail follow-up: still rejected** — scripts/study_fastfail_ticks.py replayed the certified trade sets through 1.5M real broker V75 ticks (data/v75_ticks_cert_window.csv, COPY_TICKS_INFO, real-spread fills; note data/R_75_ticks.csv is a mislabeled non-V75 series, return corr 0.011 — do not reuse). Eight FF arms (giveback G0.3–0.8, stall 45–90m) vs the EA ladder, paired with bootstrap CIs: no arm significantly positive on both sets (best v2629 arm +0.085R/trade CI[−0.12,+0.29]; the one "significant" baseline-arm result +0.088 fails to replicate on v2629 and is the expected 1-in-16 multiple-comparison fluke). Tick-true ladder for v2629 = −1.30R vs −0.18R bar-sim → spread+intra-bar friction ≈ 0.02R/trade, well inside the paper engine's ×1.5 spread conservatism. WR inflation from FF arms (77% vs 48%) is an illusion — expectancy unchanged. The BE+trail ladder already captures what FF would.
- **Walk-forward gate (same day): NOT VALIDATED** — scripts/walkforward_v75.py, 4 scored 8-day folds + tail, 7 pre-registered configs, criteria fixed before running. Totals F1–F4: v2629 +7.06R > legacy +1.36R (C1 ✓), TP-neighbor robustness ✓ (+11.7R combined), but consistency failed: positive in only 2/4 folds (C2 ✗), worst fold −4.29R (C3 ✗), and only the TP ablation beats legacy — the veto's contribution flips sign across folds (C5 ✗). Period effect dominates: every config printed its best numbers in F1 (Aug 1–9) and struggled after. The stack stays the PAPER candidate (zero-cost to test live-data), but funded promotion is now blocked on paper-first evidence, not on this backtest.

## [MITEMSHUB AI EA v26.28] - 2026-09-04

### Added — Real paper trading engine (the stub is gone)
- **Why** — `InpLiveExecution=false` was a stub: it faked a ticket with a timestamp, the ticket was then zeroed by the position-search fallback, and virtual positions were **never managed or closed**. No exits, no learning, no data — useless for validating the system without a demo account.
- **`PaperOpen/PaperManage/PaperClose`** — virtual fill at live bid/ask with a configurable conservatism multiplier (`InpPaperSpreadMult`); the position runs the **exact ManagePosition ladder** (STOP/TARGET/PLOCK/ECUT/TIME/BE/trailing + CB spike exits, same thresholds and reason strings); every close flows through `HandleTradeClose` so the governor, learning tables, cooldown, and pause logic all train on paper trades.
- **Virtual equity** — `InpPaperEquity` (default **50.0**) drives `g_eq` in paper mode, so sizing, the 20% real-risk cap, loss-streak scaling, and compounding all validate the *funded* scenario instead of the real account balance. Paper equity persists across restarts via `MitemshubAI_paper_*.csv` (EQ/OPEN/CLOSE ledger, dangling-position restore).
- **Instrumentation** — `paper_open`/`paper_close` telemetry events + a `PAPER:` dashboard row; the watchdog's [2]/[3] checks now work in paper mode via the `veq` field. Banner prints the paper-mode line at init.

## [MITEMSHUB AI EA v26.27] - 2026-09-04

### Fixed — VOL75_FINAL preset fidelity: TP 2.0 -> 2.4, BandFade disabled for the live-spread regime
- **Why** — the 5-week certification backtest (103 trades, 17.5% WR, -62.6R) exposed two preset/source inconsistencies. The source default `InpTpMult=2.4` is OOS-validated (63-cell scalp sweep, artifacts/scalp_sweep_volatility_75_index.json, all tighter cells OOS-negative) but the preset carried 2.0. BandFade's geometry (~22-unit stops) can never pass the v26.23 spread gate against V75's ~18.5-unit live spread (18% of stop): **100% of BF entries were vetoed live**, and the 8 BF trades in the 5-week replay (stop-capped at 1.5% of price) all lost.
- **Fix** — preset `InpTpMult=2.4`; preset `InpUseBandFade=false` on V75 (kept ON where spreads allow). Certification harness: scripts/certify_v75.py (full governor + v26.26 money layer on real bars). Watchdog for demo accounts: scripts/demo_watchdog.py.

## [MITEMSHUB AI EA v26.26] - 2026-09-03

### Added — Post-entry Risk Sentinel: the broker's fill is now audited, never trusted
- **Why** — the v26.25 incident proved that planned and real risk can diverge silently: every pre-send guard validated the *plan*, and nothing re-measured after the fill. Any broker-side volume normalization, stop adjustment, fill slippage, or spec change would have altered real risk invisibly.
- **`RunRiskSentinel()`** — runs after every confirmed entry (main opener, CB opener, and orphan recovery) and reads the position back as the **broker recorded it** (`POSITION_PRICE_OPEN`, `POSITION_SL`, `POSITION_VOLUME`). Computes real dollar-at-risk with **calibrated** tick values, prints a `RISK AUDIT` line (planned vs actual, with `[broker adjusted]` flag on any divergence), and **adopts the broker geometry** into `g_entry/g_sl/g_orig_risk/g_risk_money` so R-math, exit management, and the learning tables all operate on truth.
- **Breach = fatal, not advisory** — if real risk exceeds `InpMaxEffectiveRiskPct` of equity (the same policy the entry chain enforces), the EA pauses itself, logs a `SENTINEL BREACH`, writes a `sentinel` telemetry event, and force-closes the position. The 2026-09-03 failure mode (57% of equity at stake while every guard passed) is now structurally impossible to repeat silently.

## [MITEMSHUB AI EA v26.25] - 2026-09-03

### Fixed — CRITICAL: position sizing consumed a broker tick value 100x understated on Volatility 75 Index
- **Root cause (evidence, not theory)** — Deriv SVG reports `SYMBOL_TRADE_TICK_VALUE=0.0001` for V75 with `tick_size=0.01`, `contract_size=1.0`, account USD. The true value, measured from the 2026-09-03 closed trade (SELL 0.03, 251.55 pts, +$7.55 = $1.0009 per price-unit per 1.0 lot), is **$1.0009** — the broker number is **100.09x understated**. Sibling symbols (V100, Crash 1000, Boom 1000) are consistent with the identity `tick_value == tick_size * contract_size`; only V75 lies.
- **Impact** — the sizing chain believed the 500-point stop risked $5/lot and sized 0.03–0.04 lots; the *real* risk was **$15.03 (57% of equity)** on the morning trade and **$20.02 (61%)** on the 15:00 signal. Every guardrail (`InpMaxEffectiveRiskPct=20%`, fleet cap, v26.6 micro-fit) validated against the same poisoned number and passed silently. The dashboard's `Risk: 0.50%` was fiction. The user's manual save of the morning trade hid this from the account record.
- **Fix** — new `CalibTickValue(sym)`: when profit currency == account currency, the identity `tick_value == tick_size * contract_size` must hold; if the broker value deviates >5%, the geometry value is used and a loud `TICKVALUE CALIBRATED` line prints. Non-USD-quoted instruments keep the broker value (genuine conversion factor). Wired into **all** consumers: main trade opener, CB opener (which feeds the CB engine's dynamic sizing), detached-close recovery, and fleet-wide open-risk accounting.
- Post-fix behavior on this account: wanted vol for a 500pt stop ≈ 0.0003 lots → min-lot 0.01 clamps to **$5.00 true risk = 14.7% of equity**, and the v26.6 micro-fit then shrinks SL/TP to bring effective risk to ≈1.5% (spread-bound floor). Realistic worst case per trade falls from 57–61% to ~4%.

## [MITEMSHUB AI EA v26.24] - 2026-09-03

### Fixed — Governor bootstrap: fresh installs/migrations can no longer wake up benched
- **State-load hardening (`LoadReviewState`)** — a `STRAT,i` row with `enabled=0` but **zero recorded trades** is now loaded as enabled. The performance review needs ≥ `InpMinTradesToJudge` (15) trades to legitimately disable a strategy, so a zero-trade suppress can only come from a stale/zeroed state file — and under v26.20's `StratEnabledOrProbe` gate it benched the strategy at init (Sep-03 Volatility 75: banner said `Trades=0` yet PB/BO/MOM/MR all showed `(probe n/10)`; every candidate bar was vetoed, the classic legs could never fire, and no probe trade could ever accumulate to earn reinstatement — a permanent deadlock).
- Probe counters for zero-trade strategies are reset so probing restarts from a clean slate.

### Fixed — Cold-start blindness: regime/sigma/GARCH gates are warm on the first bar after a restart
- **`SeedHistoryState()` (new, called from `OnInit`)** — after a restart/migration the EA previously woke up blind: the ATR-percentile history was empty (percentile pinned at the 50 default → the regime classifier could not leave `RANGING` → Pullback/BO-sell sat out every trend), the sigma EMA was unseeded (`exp_ratio ≈ 1.0` → BandFade's `>1.25` expansion gate could not pass), and the GARCH module was cold (telemetry `z` stuck on the legacy-stddev scale for another 50 bars, tagged `[GARCH warmup]`).
- The replay walks the last `max(InpAtrLookback, InpGarchWarmupBars+2)` closed bars oldest→newest through the **same** per-bar feeds as live (`ClassifyRegime`'s ATR append, `GarchFeedBar`, `UpdateSigmaBaseline` EMA with `PerBarSigma`/`ActiveBarSigma` now accepting a shift so historical sigma is measured as-of each replay cursor). One-time init log: `Cold-start catch-up: N bars replayed | ATR hist N | GARCH obs N | sigma EMA X`.
- Short-history charts (< need+2 bars) keep the old gradual warmup. Defensive no-op when state is already warm (state files do not persist these series by design).
- Sep-03 evidence: dashboard showed `Telem: z=-4.02 … [GARCH warmup]`, `ATR%: 50` (pinned), `Regime: RANGING` through a 2,400-point trend day, `exp 1.00x` while price collapsed — all four classic strategies either benched (bug 1) or regime/sigma-starved (bug 2). Zero trades was the product of both, not signal selectivity.

## [MITEMSHUB AI EA v26.15] - 2026-09-01

### Added — Quick-TP tick-fade exit mode (v26.15)
- **`InpCBQuickTP` / `InpCBQuickTPTPMult` (default OFF / 2.5)** — opt-in Quick-TP exit for the tick-fade leg: banks a small fixed target (`N x ATR`) and disables trailing, profit locks, early cut and breakeven on tick-fade positions (exits at TP/SL/time only). The M5 fade path and Volatility-mode management are untouched.
- Backed by `scripts/cb_quick_tp_study.py` (new): EA-order tick-fade replay with a TP × minRR × trail-mode × cooldown × hold sweep over all recorded Boom/Crash 1000 tick sessions, plus an EA-faithful band-fade target/cooldown sweep on the 104-day M5 caches, plus the F1–F4 robustness gate (≥4 trades, no session < −1.5R, ATR ×0.8/×1.2 ≥ 0R, spread ×1.5 ≥ 0R).
- **Study verdict (why the mode ships OFF):** only TP ≥ 3.2×ATR geometries survive the gate; the deployed TP 4.0 trail-ON itself fails F2 (worst session −3.8R, ATR ×1.2 stress +0.8R). Quick-TP's best family (TP 2.5×ATR, trail off, +42.9R base) fails F2 at −2.1R — cutting the target truncates the +10R runners that pay for the stop-outs. Both deployed .set files carry the new keys at OFF; policy table logs `quick-tp`.

## [MITEMSHUB AI EA v25.1] - 2026-08-29

### Overview
Fade-only Crash/Boom mode with optimized parameters from 60-day real-broker sweeps, tick microstructure recorder, fleet risk guard, and removal of live parameter drift.

### Changed — Crash/Boom strategy reoptimized
- **Fade-only by default** — grind gated by `InpCBEnableGrind` (off); EA only trades post-spike fade on Boom/Crash
- Defaults re-optimized from 60-day sweep: spike threshold 3.0→2.8, cooldown 2→1 bars, entry retrace 30%→40%, SL 0.5x→0.4x ATR, TP 1.5x→3.5x ATR, max spike prob 0.65→0.70
- New minimum R:R filter (2.0), spike direction filter, ATR minimum filter, retrace quality window (max 50%)
- Duplicate-bar guard prevents double-processing cooldowns and spike ages
- Spike threshold read from detector instead of calibration profile
- **Removed live parameter drift** — SymbolCalibration no longer mutates fade_depth/tp/threshold from live samples; parameters stable until offline review

### Added — Tick microstructure recorder
- New `TickRecorder.mqh`: buffered CSV writes (every 500 ticks or 60s), daily rotation, degrades to no-op on errors
- Integrated into `OnTick()` (runs first, captures every tick), `OnInit()`, `OnDeinit()`, and dashboard

### Added — Fleet risk guard
- `OpenCBTrade()` now rejects trades if fleet-wide risk exceeds cap
- Safety net for ticket=0 on accepted orders

### New inputs
`InpCBEnableGrind`, `InpCBRequireSpikeDirection`, `InpCBMinATRPoints`, `InpTickRecordEnabled`, `InpTickFlushTicks`, `InpTickFlushSeconds`

### Updated `.set` files
- BOOM1000_CB: TP 1.8→3.2, fade-only, tick recorder on, fleet cap 12→13%, added magic 7788300
- CRASH1000_CB: TP 1.8→3.5, magic→7788300, fade-only, tick recorder on, fleet cap 12→13%

---

## [MITEMSHUB AI EA v22.0] - 2026-08-25

### Fixed — why the live bot was bleeding opportunities (Aug 17 journal: 1W/8L, −19.87, 287 signals blocked)

#### `mql5/MITEMSHUB_AI/MitemshubAI.mq5` (v21.1 → v22.0)
- **Permanent pause latch removed** — after `InpMaxConsecLoss` losses, `g_paused` latched forever (day rollover never reset it): the #1 opportunity killer. Now auto-resets with counters on each session-day rollover.
- **Dead daily-loss halt wired** — `InpMaxDailyLossPct` existed but was never referenced; now freezes new entries at −3% from the day-start equity baseline and resets next session day.
- **Effective-risk guardrail** — broker min-lot on a ~$30 account forced ~25–27% equity risk per trade. New `InpMaxEffectiveRiskPct` (default 30%) hard-caps REAL min-lot risk and skips the trade (with a loud log) instead of silently over-risking; target risk lowered to 0.5%.
- **Momentum demoted** — a lone big candle no longer triggers an entry (`InpMomentumStandalone=false`); this chase-top/chase-bottom behavior produced all eight Aug-17 losses (entries at bb_position 0.0).
- **HIGH_VOL regime no longer a global block** — only legs that self-gate skip it; the new band-fade leg *trades* expansion by design.
- **Band-geometry guard** — sigma-derived stops/targets only apply when the winning direction matches the direction band-fade fired; otherwise classic ATR geometry is used.
- **Regime-TF ladder completed** — M5→M30→H4 mapping fixed (was M5→H4); entry/regime timeframe overrides (`InpEntryTFOverride`, `InpRegimeTFOverride`) let you run M15 execution off an H1 chart.
- Order comments updated to `MITEM_v22.0`; startup banner/dashboard show the new controls.

#### Added
- **Band-fade strategy leg** (port of validated `band_geometry.py` semantics): fade |z_dev| ≥ 2σ extensions only when volatility just expanded (> 1.25× its EMA baseline), stop = 0.10×sigma_h, target = 0.80×sigma_h, per-trade hold horizon in seconds, min-RR and max-stop-% gates. This is the walk-forward-validated edge (PF≈3.02) that was previously trapped in Python-only backtests.

#### Configs (same filenames the controller deploys)
- `MitemshubAI_VOL100_FINAL.set` / `MitemshubAI_VOL75_FINAL.set` regenerated with **complete v22 key coverage** — the old files were written for v15 input names, so MT5 silently dropped them and traded code defaults.

#### Tooling & integrations
- **`scripts/verify_set_inputs.py`** — cross-checks every `.set` key against EA `input` declarations, flags missing critical inputs, and brace-checks the source. Run before any deploy: `python scripts/verify_set_inputs.py mql5/MITEMSHUB_AI/MitemshubAI.mq5 mql5/MITEMSHUB_AI/*.set`.
- **`src/dashboard.py`** — EA-log parser now understands `[v22]` lines (was hard-coded to `[v21.1]`, which would have blinded the dashboard to v22 trades).

#### Telemetry journal (v22.0, 2026-08-25)
- **Per-bar measured values**: `UpdateBandTelemetry()` computes `z_dev`, sigma-expansion ratio (`sigma/sigma_base`) and per-bar sigma once per closed entry-TF bar, BEFORE strategy evaluation — gates and dashboard consume the same numbers the journal records.
- **JSONL journal** `MQL5\Files\MitemshubAI_v22_telemetry.jsonl` with three event types:
  - `sig` — every evaluated bar with a fired leg: action TAKE/SKIP, skip reason (e.g. `mom-demoted-lone-candle`, `score B2/S0 < min 3`), fired legs (`"legs":"MOM-|MR-|BF-"`), buy/sell scores, regime, z, exp, sigma/base, band-geometry flag.
  - `open` — ticket, dir, entry/sl/tp, volume, effective $ risk, legs, regime, timeframe, z, exp.
  - `close` — exit reason/price, R multiple, money P&L, consec-loss count, pause/daily-halt state.
- **Dashboard row 11** shows live `z=… exp=…x sig=… base=…`; StratBandFade now reuses the measured globals instead of recomputing (identical semantics).

#### Strategy Tester validation kit (v22.0, 2026-08-25)
- **`STRATEGY_TESTER_VALIDATION.md`** — exact tester panel settings, 3-pass protocol (raw edge / $30 realism / robustness sweep) and quantitative pass criteria for validating the band-fade leg on Volatility 75 & 100 over 6 months of M15.
- **`MitemshubAI_TESTER_BFONLY_VOL100.set` / `_VOL75.set`** — isolation rigs (band-fade only, breakers neutralized, trailing/BE off) for clean raw-edge measurement; verified against EA inputs. Deploy configs unchanged.

#### Five-symbol parallel profiles (v22.1, 2026-08-25)
- **`MitemshubAI_VOL10_FINAL.set` / `_VOL25_` / `_VOL50_`** — vol-tier-scaled band-fade tunes for low-volatility synthetics: deeper z-entry (2.3/2.2/2.0), nearer targets (0.60/0.70/0.80 σ_h), tighter max-stop-% and risk caps where min-lot finally allows sane sizing. Marked UNVALIDATED — Strategy-Tester Pass-A gates required before sizing up.
- **Unique magic per chart** across all five FINAL sets (`7788010/025/050/075/100` = `77880`+vol tier) so parallel EA instances never cross-attribute positions; V75/V100 re-magicked from the old ad-hoc values — reattach fresh.
- **PRODUCTION_CONFIGS.md** gained the five-symbol matrix plus a venue-name warning: this Deriv terminal has no "Volatility XX Index" symbols — tradable names are SYN-series (SYN75/SYN100 verified in `mt5_collector.DERIV_SYMBOL_MAP`).

#### Pass-A real-data validation of VOL10/25/50 profiles (2026-08-25)
- `backtest_real_history.py` extended: per-profile tuned z/targets, exit-reason tracking, avg band-stop-width %, and explicit promotion-gate verdicts (≥30 tr, PF≥1.30, expR≥+0.15, maxDD≤12R, TIME≤40%).
- **208-day real M15 verdicts**: VOL10 ❌ REJECTED (PF 0.96, expR −0.04 — no edge; spread ≈26% of its 0.013% band stops); VOL25 ⏸ SHELVED (PF 1.44/+0.36R but 27R DD); VOL50 🟡 CONDITIONAL (PF 1.55/+0.46R, 0% TIME exits, DD 16R → risk ≤0.9%). Reference anchors V75/V100 pass all edge gates and trip only the fixed DD line.
- **Gate policy revision** documented: fixed R-drawdown gate replaced by sizing rule (`risk% ≤ tolerance / DD_R`), since every always-on leg exceeds 12R over 7 months.

#### Telemetry-native replay (2026-08-25)
- **`scripts/replay_v22_bandfade.py`** now auto-discovers `MitemshubAI_v22_telemetry.jsonl` (explicit `--telem` → MT5 terminal Files dirs → repo fallbacks). When found, a new **Part T** replaces proxy-based auditing with EXACT EA values: ticket-paired trades (R/$/z/exp/legs/risk), band-fade vs classic-ATR leg performance split, skip-reason histograms (`mom-demoted-lone-candle`, score blocks…), live gate hit-rates (|z|≥2 / expansion>1.25× / both), breaker-state counts, and still-open tickets. `--legacy` forces the old proxy Parts A+B; without telemetry the script behaves exactly as before.

#### Live-terminal ground truth & real-history validation (2026-08-25)
- **`scripts/mt5_probe.py`** — read-only Deriv terminal probe: enumerates all 730 symbols, verifies trade modes/min-lots/tick values, computes per-symbol min-lot risk floors at reference stop sizes, exports real candle history to `artifacts/real_*.csv`.
- **SYN-series claim REVERSED by ground truth**: the terminal DOES expose "Volatility XX Index" display names (FULL-tradeable) and has NO SYNxx symbols. `DERIV_SYMBOL_MAP` now maps R_10…R_100 (+V75/V100) to verified display names; controller aliases simplified to a safety net. Earlier stale comment removed.
- **Min-lot risk floors rewrite the fleet plan**: V75 min lot 0.01 → ~$0.08/trade risk floor (🟢 anchor); V100 $10.39 (42% eq); V25/V10 unviable ($23/$40 = 90%/162%). PRODUCTION_CONFIGS matrix updated — live fleet is V75-first, equity-gated.
- **`scripts/backtest_real_history.py`** — EA-faithful band-fade backtest over 208 days of real broker M5 candles (exported via probe). Result: deployed **z=2.0 wins on ALL tested symbols at M15** (V75 PF 1.57 +0.50R; V100 PF 1.63 +0.52R; V75(1s) PF 1.62); looser z gates from the synthetic sweep do NOT survive real microstructure; H1 loses → M15-only confirmed. Deployed configs validated as-is.
- **`scripts/daily_scoreboard.py --weekly`** — ISO-week rollups plus an explicit promotion verdict (≥20 demo trades, expectancy ≥ +0.15R, positive total, beats old-logic baseline when present) printing PROMOTE CANDIDATE / HOLD ON DEMO with unmet criteria.

#### Band-fade frequency sweep tooling (2026-08-25)
- **`scripts/sweep_bandfade_params.py`** — grid-sweeps `z_entry` × timeframe(M15/M30/H1) × `stop_sigma_mult`(0.10/0.20) through the repo's own EGARCH band-strategy runner (`run_vol_band_backtest`) with risk-halts relaxed to expose raw edge; synthesizes seeded 1-min calibrated series per vol tier (GBM + AR(1) clustering, post-hoc variance-normalized), optional `--ticks-csv` real-data sanity, automatic walk-forward half-split on frontier winners, JSON export.
- **Fixed import-blocking bug**: duplicate `DERIV = "deriv"` enum member in `backtest/synthetic_generator.py` crashed the entire `synthetic_trader.backtest` package under Python 3.14.
- 120-day findings (see artifacts/bandfade_sweep.json): M15 dominates the frequency-profit frontier; `z=1.0/stop=0.10` roughly doubles trade frequency vs the deployed `z=2.0` at modest expectancy cost and passes walk-forward halves on both symbols; stop=0.20 fails outright on R_100. Deployed configs unchanged pending real-broker tester confirmation.

#### Symbol alignment across the stack (2026-08-25 audit)
- **Root cause documented**: the Python engine trades INTERNAL names (`R_75`/`R_100`; every CLI default) and its forward-demo is an OFFLINE tick replay — it never touched MT5. Meanwhile this broker's terminal only exposes SYN-series symbols (`SYN75`/`SYN100` verified), so the controller keyed to "Volatility XX Index" could never find its symbols and silently skipped enablement.
- **`autonomous_controller.py`** now resolves configured symbols through `SYMBOL_ALIASES` (display name → SYN fallback, cached) at all `symbol_info`/`symbol_select` sites including order routing.
- **`mt5_collector.DERIV_SYMBOL_MAP` fixed**: `V75`/`V100` no longer map to Boom/Crash 1000 (different instruments!) but to SYN75/SYN100. `R_10/R_25/R_50` deliberately unmapped until venue names are Market-Watch-verified — unknowns fail loudly by design.
- **Docs de-staled**: attach instructions and Strategy-Tester symbol rows now name SYN-series; legacy `_LIVE.set` rows marked superseded.
- Known leftovers: old one-off forensics/backtest scripts (`backtest_v17_*`, `walk_forward.py`, `v100_forensic.py`) still probe display-name symbols — inert research artifacts, not part of the live loop.

#### Audit completion pass (2026-08-25, session 2)
- **Dead shadow map removed**: `mt5_collector.DERIV_SYMBOL_MAP` was defined twice — a stale SYN/SURGE/DROP/LEAP dict silently overridden by the corrected map below it. Dead dict deleted; single authoritative map remains.
- **PRODUCTION_CONFIGS.md de-staled** (three dangerous leftovers): safety rule #6 demanded ONE shared magic (7788123), contradicting the v22.1 unique-magic fleet design — now mandates per-chart fleet magics; attach instructions still claimed "SYN-series only" — replaced with the verified display-name truth; tiny-account advice recommended V10/V25 — backwards per verified min-lot floors ($40/$22 = 162%/90% of $30 equity) — now points at V75 ($0.08 floor).
- **Dashboard log parser accepts `[v22.x]` tags**: matched literal `[v22]`, which would have missed `[v22.1]`-tagged journal lines (same blindness class the v22 fix targeted).
- **Controller SYMBOLS params aligned to deployed tunes**: z_entry 1.8→2.0, targets →1.20 (V75) / 0.80 (V100), timeframe H1→M15, vol_ratio→1.25 (= InpBandVolExtRatio). Self-optimization suggestions are now comparable to what actually trades.
- **Exposure-guard inputs pinned in all seven sets**: `InpMaxTotalRiskPct=15` + full five-magic fleet CSV on the FINAL profiles; `=100` (neutralized like their other breakers) on the `_TESTER_BFONLY_` rigs. `verify_set_inputs.py` reports zero default-fallback notes.
- **Artifact-clobber footgun fixed**: a `--only` rerun of `backtest_real_history.py` rewrote `bandfade_real_M15.json` with just its own rows, silently erasing every other symbol's results (the recorded V75/V100 M15 cells were lost exactly this way). Output now MERGES by (symbol, tf, z, tgt) — partial reruns update their own cells and keep the rest.
- **Deal comments bumped to `MITEM_v22.1`** for order traceability. Telemetry filename deliberately stays `MitemshubAI_v22_telemetry.jsonl` — replay/scoreboard auto-discovery depends on it; renaming would blind the analytics pipeline. Verified: `daily_scoreboard.py` tag regexes already capture any `[vNN.N]` build tag.

#### Terminal source deployment + AGGRO profiles (2026-08-25)
- **Root cause of "MetaEditor still shows v21.1" found and fixed**: the terminals' `MQL5\Experts\MitemshubAI.mq5` copies were never updated — only the repo had v22.1, so every recompile rebuilt the OLD engine. Deployed the v22.1 source (old file preserved as `MitemshubAI_v21_1_backup_20260825.mq5`) to ALL THREE terminal data folders on this machine, plus all nine current `.set` files into each terminal's Presets and Experts locations.
- **AGGRO max-frequency profiles** `MitemshubAI_VOL100_AGGRO.set` / `_VOL75_AGGRO.set`: z=1.0 (deepest validated gate, ~3× frequency), consec-loss pause 6, cooldown 1 bar, account ceiling 50%. V100's effective-risk cap raised to 45% so its ~$10.39 min-lot floor can trade at $30 equity — documented with the explicit math that ~40%/trade means three losers ≈ −78% of the account.

#### Config de-stale pass: `MitemshubAI_V100_H1.set` (2026-08-25)
- The last `.set` still carrying a v21.1 header was also missing all four v22-critical inputs (`InpBandZEntry/StopSigma/TargetSigma`, `InpMaxEffectiveRiskPct`) and pinned the hazardous legacy `InpRiskPerTrade=0.25` (= 25% target risk under fraction semantics that date back to v16). Regenerated with full v22.1 coverage: band-fade V100 tune (z=2.0 / stop 0.10σ / target 0.80σ), momentum-standalone demoted, effective-risk cap 30%, account guard `InpMaxTotalRiskPct=15` with fleet CSV extended by this profile's own magic 7788211 for correct self-accounting. TF overrides intentionally left at CURRENT to preserve the file's H1 identity. `verify_set_inputs.py` now PASSES it. Remaining stale `.set` families (PAPER_TEST, SYN TIER/LIVE ×8, V6/V16–V20 archaeology) are superseded research artifacts per PRODUCTION_CONFIGS.md — do not load them on v22.x.

#### Daily scoreboard (v22.0, 2026-08-25)
- **`scripts/daily_scoreboard.py`** — accumulating daily comparison of v22 demo results vs old-logic baselines. Sources combine when present: v22 telemetry JSONL (trades, R/$, exit split, band share, avg entry-z; plus decision analytics — TAKE/SKIP counts and lone-momentum chase-entries avoided, reported as counts only, never invented P&L), MT5 Experts logs (true parallel-shadow per build tag `[v22]`/`[v21.1]`/`[v16.5]`), and Python-engine journals (`--engine-glob`) as historical baseline. `--selftest` verifies the pipeline on synthetic events; `--json` exports the summary.

### ⚠️ Deploy note
The terminal previously ran an unknown build printing "v10 starting" that matches nothing in this repo. **Recompile `MitemshubAI.mq5` v22.0 in MetaEditor, attach it fresh with the regenerated `.set` file, and verify the chart prints `[v22] ... started`.** Until then, what trades live is not what's in this repo.

---

## [0.1.0] - 2026-07-25

### Added

#### Infrastructure & Deployment
- **Terraform templates** for AWS EC2 deployment (Windows Server 2022)
- Application Load Balancer with HTTP listener
- Security groups: RDP restricted to admin IP, web traffic through ALB
- Auto-start on boot via PM2 + Windows Scheduled Task
- Chocolatey-based provisioning: Node.js 20, Python 3.10, Git, PM2

#### Operator Dashboard (Next.js 15)
- **Trade Plan Panel** — Real-time trade recommendations with entry/invalidation/target levels
- **AI Market Intelligence** — Regime analysis, bias scoring, market thesis
- **Multi-Timeframe Alignment** — Visual alignment matrix across 4H→1H→15M→5M
- **Bullish vs Bearish Evidence** — Ranked evidence with strength bars
- **Current Market Thesis** — AI-generated thesis with confidence and invalidation
- **Health Dashboard** — System health monitoring, MT5 diagnostics, bridge status
- **Trade History** — Complete trade journal with outcomes and performance metrics
- **Mobile-First Design** — Responsive layout with bottom navigation
- **Dark Mode** — Full dark theme support with proper contrast ratios
- **Haptic Feedback** — Tactile feedback for mobile interactions (`src/components/ui/haptic.ts`)
- **Pull-to-Refresh** — Swipe down to refresh market data on mobile
- **Loading Skeletons** — Shimmer states for MultiTimeframe, Evidence, and MarketThesis panels
- **Intel Accordion** — Collapsible intelligence panels with smooth animations

#### Python Trading Engine
- **Missing live-watch functions restored** — `run_live_watch`, `render_live_snapshot_text`, `render_live_watch_alert_text`, `build_live_watch_review_snapshot`, `render_live_watch_review_text`, `build_watch_alert_from_prepared_state`, `_append_journal`
- **Bucket-based cooldown** — `DEFAULT_CONTEXT_ALERT_COOLDOWN=2` for context update suppression
- **StopIteration handling** — Clean exit when snapshot source is exhausted
- **MT5 price sanity check** — Alerts when CSV tick prices deviate from expected ranges
- **build_watch_alert** — Added `why` field from briefing for better explainability

#### Documentation
- **Comprehensive README.md** — Architecture diagrams, quickstart guide, CLI commands, deployment docs
- **CHANGELOG.md** — This file
- **Architecture diagrams** — ASCII art showing full system flow

### Fixed
- **Missing Python functions** that caused import errors breaking the Python engine bridge
- **Cooldown mechanism** — Restored bucket-based countdown (was incorrectly using 120-second epoch-based)
- **Dark mode command-rail** — Fixed washed-out appearance with proper dark theme CSS overrides
- **StopIteration in run_live_watch** — Previously fell into reconnect handler, creating spurious journal entries
- **build_decision_summary** — Now falls back to `briefing` when `why` is not present

### Changed
- **Merged feature/mt5-rollout-enablement into main** — All development consolidated into production branch
- **Updated .env.example** — `SYNTHETIC_ENGINE_MAX_LIVE_TICKS=5` → `15`
- **README overhaul** — Complete rewrite with architecture, features, CLI, and deployment documentation

---

## Previous Phases

### Phase 4 — AI Evolution & Self-Improving Intelligence
See [docs/PHASE4_SUMMARY.md](docs/PHASE4_SUMMARY.md)
- FeatureSelector, ModelCalibrator, ConfidenceScorer
- EnsembleModel, ModelMonitor, FeatureImportanceReport
- 13 new tests, experiment tracking framework

### Phase 3 — Core Intelligence Engine
See [docs/PHASE3_SUMMARY.md](docs/PHASE3_SUMMARY.md)
- 4-timeframe hierarchy with confluence scoring
- Continuous background scanner
- Call lifecycle management (forming→actionable→confirmed→failing→cancelled)
- Hurst exponent, entropy, volatility clustering
- FVG detection, internal BOS, equal highs/lows, liquidity sweeps
- Regime detection with persistence
- 8-component decision fusion
- Confidence calibration (isotonic + Platt)
- Explainability engine

### Phase 1–2 — Foundation
- Market data ingestion and candle construction
- Online logistic regression model
- Paper execution and journaling
- Walk-forward validation
- Risk engine with position sizing and drawdown limits

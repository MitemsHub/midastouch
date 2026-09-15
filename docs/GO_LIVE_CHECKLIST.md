# GO-LIVE CHECKLIST — $50, terminal A, magic 7788075 (written 2026-09-05, rehearsed read-only)

This is the exact procedure to execute when the pre-registered gate passes
(TJ1 paper A/B positive + TJ2 tick reconciliation + TJ3 watchdog — see
`docs/OPERATING_SUMMARY.md`). It was rehearsed read-only on 2026-09-05; every
file and expected string below was verified against the live system. **Do not
execute until the gate says go.**

## Preconditions (all must be true)

- [ ] Gate verdict = GO LIVE (TJ1 + TJ2 + TJ3, from the Sunday pipeline).
- [ ] If the verdict is instead the NO-GO branch (arm-A negative / INCONCLUSIVE-negative),
      execute `docs/NO_GO_BRANCH_PLAYBOOK.md` (frozen 2026-09-15): Step 1 freeze, Step 2
      re-baseline drill vs `cert_report_fresh60_tp18_net.json`, Step 3 spread pricing
      (+0.0022R/t slope), Step 4 governor funnel diffs — outcome letter A/B/C is final
      for this config; re-entry only via §6's four-step chain.
- [ ] Real account **140778269** funded ≥ $50. (2026-09-04 record: $0.57 —
      **2026-09-14 record: $50.22 — PRECONDITION MET**, verified via the MT5 API
      `account_info()` from this terminal: trade_mode=REAL, DerivSVG-Server-03,
      1:1000 leverage, 0 open positions. Hard floor $31 — below it every signal is
      vetoed by the broker lot floor, by design.)

### Account ground truth (verified 2026-09-14, record for the Algo-switch decision)

- **All terminals log into the ONE real account 140778269** (DerivSVG-Server-03).
  There is no demo account in this operation. Paper safety is enforced at the
  **EA level**, never by the account: arms A/B run `InpLiveExecution=false`,
  arm C (V75MacroEngine v2.21) runs `InpPaperMode=true` — its paper path never
  constructs a broker order.
- **Terminal topology (2026-09-14): the paper arms have a DEDICATED terminal.**
  `MitemshubMT5_C` (data folder 71BF) hosts arm B and is reserved for paper
  collection — **tester runs and research sessions must never close it**; the
  tester flow uses the default install (49E0), which no longer carries any arm.
  FB9A (default install) hosts arm A + arm C and, per the go-live procedure
  below, the future live chart. Arm B's ledger/telemetry continuity was
  preserved verbatim in the migration (equity $55.20, 7 closed, banner restore
  verified).
- **The master Algo Trading switch on this terminal gates every EA's ability to
  order.** Grounded recommendation: leave it **OFF** until this checklist is
  executed; telemetry and ledger writes are plain file I/O and are unaffected by
  the switch, so the paper arms lose nothing while it is off. The go-live
  procedure below is the only sanctioned reason to turn it on.
- **Server-side algo enablement is UNVERIFIED for this account.** Deriv gates
  algo trading per account server-side (precedent: error 10026 on demo 5098680,
  `docs/DERIV_SUPPORT_EMAIL.md`). If the live order at step N is rejected with
  10026, the fix is the Deriv support request, not the terminal.
- Session history note (2026-09-14): the v2.20 build briefly ran live-capable
  (magic 7500) on this account before being converted to arm C (paper, 7788125).
  No order resulted — the aligned-DOWNTREND stand-down held. This near-miss is
  the concrete argument for the Algo-off rule above.
- [ ] Terminal A running (`C:\Program Files\MetaTrader 5 Terminal\terminal64.exe`,
      data folder `FB9A56D617EDDDFE29EE54EBEFFE96C1`).
- [ ] Preset in place and validated — `MQL5\Experts\MITEMSHUB_AI\MitemshubAI_VOL75_LIVE.set` (repo source: `mql5/MITEMSHUB_AI/MitemshubAI_VOL75_LIVE.set`)
      **byte-identical to repo** (verify with `python scripts/verify_go_live_artifacts.py`; repository-side identity checked 2026-09-05): `InpLiveExecution=true`,
      `InpMagic=7788075`, `InpTpMult=1.8`, `InpPaperEquity=50.0` (inert in live),
      `InpFleetMagicsCSV=...,7788075,7788100` (A and B both in the account-wide
      fleet guard — both must stay in the CSV; B stays paper).
- [ ] EA build = v26.39 (`MitemshubAI.mq5` + compiled `.ex5` synced; the same
      build that has run paper arms — no unverified build ever goes live first).
      v26.38 is the paper fill-model parity build: hard SL/TP fill per tick at
      the resting level, mirroring broker-side resting orders (changelog
      2026-09-15). The live book's fills are unchanged by this fix.
      v26.39 adds the ledger ERA provenance stamp (banner line `PAPER ledger
      era stamp`); statistics consumers separate pre/post-boundary trades
      via scripts/era.py — the gate clock is post-era only.

## Procedure — terminal A, chart01, V75 M15

1. **Stop the paper EA**: chart01 → right-click EA → Remove (or Delete). Confirm
   the Experts log shows the EA removed. (B stays running — do NOT touch B.)
2. **Re-attach the EA**: drag `MitemshubAI` onto chart01 → in the dialog press
   **Load** → select `MitemshubAI_VOL75_LIVE.set` → **OK**.
3. **Enable Algo Trading** if prompted (MT5 toolbar button / `Ctrl+E`).
4. **Confirm the banner** — the Experts log must contain ALL of:

   | expected line (exact markers) | meaning |
   |---|---|
   | `MITEMSHUB AI v26.39 started ... Standard Mode` + `PAPER ledger era stamp: 26.39` | correct build |
   | **NO `PAPER MODE:` line** | the discriminator — live, not paper |
   | `FIT ROUTER: instruments vs a $50.00 account` (or your funded $) | live balance read |
   | `Volatility 75 Index min-lot stop-risk $X.XX ... TOLERATED, each trade risks Y.Y% of equity` | sizing fits at $50 (expect X ≈ 4.5–6.5, Y ≈ 9–13% depending on current ATR) |
   | `RiskCap=20%` line + `WARNING: risk cap > 10% — tiny-account mode.` | expected at $50, not an error |
   | `[SELFTEST] ... OK`, `GARCH ready`, `Telemetry -> ...`, `State -> ...` | engine initialized |

5. **Confirm magic + TP on the chart**: input tab (F7) shows `InpMagic=7788075`,
   `InpTpMult=1.8`, `InpLiveExecution=true`. Dashboard **MODE shows `LIVE`**.
6. **Do NOT modify any input** by hand. The preset IS the config.

## First-trade confirmations (within the first signals)

- Journal shows real order lines: `Executing BUY vol=0.01 SL=... TP=... | <reason>`
  (or SELL) — this is the live path (`trade.Buy/Sell`), and the position appears
  in the terminal's Trade tab with magic 7788075.
- Any `SKIP ... min-lot risk $X exceeds cap $Y (Z% equity)` lines are the governor
  vetoing — expected and correct (not errors).
- Any `ORDER FAILED retcode=...` → **STOP** (see abort).

## $50 truth table (what to expect and why it's OK)

| account | min-lot stop-risk (today's ATR) | per trade | verdict |
|---|---|---|---|
| **$50 (live)** | ≈ $4.6–6.5 | ≈ 9–13% of equity | TOLERATED — trades, sharply. This is the pre-registered minimum-viable size. |
| $31 (floor) | ≈ $4.6–6.5 | ≈ 20% (the cap) | TOLERATED at cap — absolute floor, not a target |
| < $31 | same $ | > 20% | `CANNOT FIT` — every signal vetoed. Fund or don't attach. |
| $100+ | same $ | ≈ 5–7% | the sane size for later compounding |

**This table is about the ARMS' geometry (MitemshubAI, ≈$4.6–6.5 min-lot
stop-risk) — it does NOT transfer to arm C (V75MacroEngine).** Arm C's
2×H1-ATR stop is far wider: tester-measured 2026-09-15 (`armc_paper_ledger
validation`: 40% risk ⇒ volume 0.012–0.017, stop-dist 1120–1466 points ⇒
min-lot stop-risk ≈ **$14–17**), i.e. ≈28–34% of the $50 floor. At the
production 1%-risk config every entry is refused (`computed volume < broker
minimum`) — correct guard behavior, but the config is **inert at $50**. Arm C's
own sizing truth table is pre-registered below; until its arm-C branch
adjudicates a VALIDATED-CANDIDATE, its paper run on FB9A is a
collection-only regime exercise.

Model: long-run cost-inclusive expectancy ≈ +0.038R/trade (net, certified window,
t=0.35) → at 0.01 lots ≈ +$0.20/trade expected; the account grows by surviving
and compounding ~2 trades/day, not by heroics. Risk is the constraining resource.

## Arm C sizing truth table (PRE-REGISTERED 2026-09-15, $50–$150)

Grounding (frozen from the v2.23 tester measurements,
`artifacts/v75_macro_engine_tester/armc_paper_ledger_20260915.json`, 8 real
fills, stops 1121–1466 points): **min-lot (0.01) stop-risk = $10.00–$17.85**,
typical band $14–17.85; the engineering bound for a 2× median-ATR stop is
≈ $28. The per-trade risk ceiling is the global 20% cap. These numbers are
frozen; changing them requires a protocol amendment, not judgment.

| account | budget @20% cap | worst stop $17.85 | typical $14–17 | verdict |
|---|---|---|---|---|
| $50 | $10.00 | refused | refused | **INERT (measured)** — every entry refused; collection-only regime exercise |
| $75 | $15.00 | refused | partial | **NOT VIABLE** — unpredictable partial admission, worst geometry always vetoed |
| $85 | $17.00 | refused | fits | **MARGINAL** — still refuses the worst measured stop |
| **$100** | $20.00 | fits | fits | **MINIMUM VIABLE (pre-registered)** — all 8 measured geometries admitted |
| $120 | $24.00 | fits | fits | headroom for ATR drift |
| $150 | $30.00 | fits | fits | **RECOMMENDED BUFFER** — covers the ≈$28 2×ATR engineering bound |
| (any) | 1%-risk production config | needs ≥ ~$1,800 | — | the 1% input can never fit this geometry at these sizes — a live attach would require a pre-registered risk-input change through the certified chain |

**The knife, stated plainly:** at the $100 minimum, one stop = −17.9% of
equity; the arms' 3-consecutive-loss pattern compounds to ≈ **−45%**
(sized on running equity) — and the arms have already printed 3-loss streaks
on thinner edges. Arm C at
minimum viable size lives at the edge by construction — that is exactly why
it is NOT a gate input, its live path exists only through the arm-C branch
(VALIDATED-CANDIDATE + pre-registered adjudication, `OPERATING_SUMMARY.md`
§3), and the $150 recommended buffer plus the weekly withdrawal-above-buffer
rule are part of this pre-registration, not optional extras.

## AMENDMENT 2026-09-15 (append-only) — the dynamic strangulation floor

The frozen table above answers **static admission** only (budget ≥ worst stop).
It misses the failure mode the hybrid-exit study observed live (L1 book: 589
risk-cap vetoes, book dead at n=6): **min-lot risk is pinned in dollars by the
broker volume floor while the 20% cap shrinks with equity.** A loss streak
therefore strangles admission below a computable floor:

```
eq_floor = s × (k + 5)
  5·s : static admission of the worst stop (the frozen table's criterion)
  k·s : absorb the worst certified loss streak without strangulation
  +1·s: still able to trade AFTER the streak
```

Inputs, frozen and cited: **k = 6** — the worst loss streak of the certified
replay (`cert_report_fresh60_tp18_net.json`, `worst_loss_streak`, n=114; the
paper arms observed 5/3 at n=14/9, consistent); **s = $20.50** — the p95 worst
min-lot stop from the live ATR distribution (reading #6, 2026-09-15);	ail = k=7, one loss beyond anything observed; engineering bound s = $28.
Mechanics validated against observation: the L1 book died at equity ≈ risk$/0.20,
exactly this formula's death threshold.

| scenario | s | floor | vs frozen rows |
|---|---|---|---|
| **certified streak (k=6)** | $20.50 | **$225.54** | above every frozen row ($50–$150) |
| tail (k=7) | $20.50 | $246.05 | — |
| engineering bound (s=$28, k=6) | $28.00 | $308.00 | — |

**Consequences, frozen:** the $100 MINIMUM-VIABLE and $150 RECOMMENDED-BUFFER
rows stand for **static admission** but do NOT survive a certified-replay loss
streak without strangulation (at $150 the streak's tail ends below the $30 cap,
which then refuses every entry). A live arm C at $100–$150 is therefore a
**strangulation-prone regime**, and the honest minimum for *unstrangled* operation
is **≈ $226 (certified), $246 (tail), $308 (engineering)**. Until the account
meets the floor, any arm-C activation inherits the L1 death mode; the arm-C
branch's $100 precondition now reads as: **$100 minimum to trade at all, ≈$226
minimum to survive the config's own worst certified streak.** The weekly ATR
monitor re-derives this floor every reading (`strangulation_floor` block in
`atr_drift_monitor.json`); a floor rising above the actual account equity is an
amendment-grade finding. **The floor is also an adjudication-time gate, not just
an activation precondition:** the arm-C rule's G5 (ARM_C_TEMPLATE.md, amendment
2026-09-15) re-verifies the window-minimum equity against the monitor's
`floor_certified` before any candidate verdict — a window collected below the
floor is INVALID, never adjudicated, so the L1 death mode cannot be laundered
into a statistics result.

**The question this floor forces — can ANY risk input + stop sizing make $150
viable — is now answered by a frozen study, not by judgment:**
`docs/VIABLE_SCALE_GEOMETRY_STUDY.md` (pre-registered 2026-09-15, gates G0–G3
before any run). Its frontier computed from the certified replay's own 114-trade
sequence: **no risk input at the unchanged geometry makes $150 unstrangled AND
DD-bounded except 10%-risk** (min $138, max window DD 31.0% — each stop −10%),
and the stop-scaling alternative carries the frozen intra-bar-noise prediction
(median intra-bar range 0.541R ≥ the scaled stop). Read §4 of the study for the
pre-declared outcome mapping before citing any number from it.

Below $100, arm C does nothing (correctly). Between $100–150 it trades at the
edge. Live authorization for arm C additionally requires its own adjudicated
candidate verdict — the truth table is a precondition, never an authorization.
The adjudication rule itself is now frozen too: `docs/ARM_C_TEMPLATE.md`
(2026-09-15 pre-registration — candidate vs arm A, daily-paired, gates G1–G4,
frozen verdict mapping), written before any candidate exists; the $100 floor
above is one of its formal preconditions (G1 is unreachable below it).

## Truth-table validity monitor (REGISTERED 2026-09-15, runs weekly)

The frozen band is a function of H1 ATR(14) (SL = 2.0 × H1 ATR,
`V75MacroEngine.mq5`), which drifts with the volatility regime. The weekly
pipeline re-derives the table from live data (`scripts/atr_drift_monitor.py`,
paper_weekly §4; history in `artifacts/v75_replay/atr_drift_monitor.json`):

- **Calibration**: per-fill k = risk$/volume/stop-dist from the tester ledger
  (8 fills, frozen band k ∈ [0.0089, 0.0149] → $10.00–$17.85); a >15%
departure flags CALIBRATION-DRIFT (contract/quote change) and caps the
verdict at WATCH.
- **Verdict on the p95 ATR geometry** (what the engine will actually meet),
  frozen tiers: **HOLD** (p95 worst stop ≤ $20 — every row stands) →
**WATCH** ($20–$24 — the $100 row's claim is stale; review at the next
protocol review) → **AMEND** (> $24 — the $120 row also fails; formal
append-only amendment required BEFORE any live decision cites the table;
arm-C branch precondition unmet until it lands). A symmetric **SHRINK-WATCH**
fires if the p05 worst stop falls to ≤ $5 — a table that lies in the benign
direction is amended too. Stale feed (bar > 3 h old) → SKIPPED-STALE, never HOLD.
- **First reading, 2026-09-15: WATCH** — p95 geometry implies worst min-lot
  stop **$20.50** vs the $100 row's $20 budget; the $100 MINIMUM-VIABLE row
re-derives as PARTIAL admission at the p95 geometry, $120/$150 rows hold.
Today's band [10.86–18.12] still brackets the frozen [10.00–17.85] — the
table is sound at the median and marginal at the volatility tail. No
amendment yet; the monitor tracks it weekly.

## Abort criteria (any one → stop immediately, investigate, do not trade)

- Banner contains `PAPER MODE:` (the LIVE set did not load — load failed silently).
- `FIT ROUTER ... CANNOT FIT` at your funded balance (account < floor → fund it).
- `InpMagic != 7788075` or `InpTpMult != 1.8` on the chart after load.
- Dashboard MODE is not `LIVE`.
- Any `ORDER FAILED` retcode (network/broker issue → check, don't retry blindly).
- First live fill symbol ≠ Volatility 75 Index, or magic != 7788075 in the Trade tab.

## After attach — steady state

- Keep running `python scripts/morning_status.py --strict` daily (arms, gaps,
  gate X/30 — now also shows the live arm).
- Compare live fills vs the paper ledger: **the same signals should print in both**
  — any divergence means the live attach drifted from the preset; stop and re-run
  the checklist.
- B keeps paper-testing TP 2.4 until the A/B duel finishes, then is parked.
- Withdraw weekly everything above a $100 working buffer (funding plan) — never
  drain below the $50 live floor.
# MIDASTOUCH CLOSEOUT — 2026-09-16

Gold-only pivot from the V75/V28 synthetic-indices program, executed in one session per
the approved 6-step plan. Nothing was deleted; the synthetic program is archived.

## Directive (verbatim)

> Alright we are going to trade gold then, ... you are just creating an engine that only
> trades gold ... anything that trades indices, stop it, any background stuff that is
> running behind the scene stop it ... please DO NOT complicate things

## Step 1 — Indices activity stopped (nothing deleted)

- Scheduled tasks disabled: `MitemshubA2FirstTradeWatch`, `SyntheticIndicesPaperPipeline`.
- All four paper arms (A2, D_fwd, B, C) verified **flat** via `verify_all_flat` before
  their terminals stopped; expert blocks stripped from every chart profile across all
  three terminal installs (backups kept), so nothing re-attaches on relaunch.
- Five ledgers archived with SHA-256 checksums into `archive/v75_ledgers_20260916/`.
- Synthetic closeout record: `docs/V75_CLOSEOUT_20260916.md`.

## Step 2 — Ground truth probe (`scripts/deriv_symbol_probe.py`)

- **XAUUSD exists on our real account** (login 140778269, DerivSVG-Server-03, 1:1000).
  Specs live: `artifacts/deriv_symbols_20260916.json`.
- **Cost geometry: toll 0.69%** of a typical H1 stop (spread $0.34 vs $49.59) — the
  killer metric was 5.6% on V75-1s.
- **Floor math:** XAUUSD min-lot 0.01 = 1 oz → $49.59/trade → ~$4,959 equity at 1% risk;
  **XAUUSDmicro min-lot 0.1 = 0.1 oz → $4.96/trade → ~$496 at 1%**. XAUUSDmicro is our
  instrument at the real account's $50.22; standard XAUUSD stays research-only.
- Feed depth: H1 2024-04-10 → 2026-09-16 continuous (2.4y); one honest **112-day broker
  hole (2023-12-20 → 2024-04-10)** on H1/D1, disclosed and excluded from research.
- Validated history: `data/forex/xauusd/` (H1 full span; M15 50k bars = terminal cap),
  validation artifact `artifacts/midas_history_20260916.json`.

## Step 3 — Playbook (measured, not folklore)

`docs/MIDASTOUCH_GOLD_PLAYBOOK.md` — instrument specs, session fingerprint from our own
14,414 H1 bars (volatility peak 13:00–15:00 UTC London/NY overlap; spread ~$0.10 steady,
$0.17 worst at rollover), news policy, weekend-gap policy.

## Step 4 — Frozen protocol + honest sweep

- `docs/MIDASTOUCH_PROTOCOL.md`: gates G1–G6 frozen **before** any run; Amendments 1–2
  appended after runs, append-only, with reasons (A1: pending-fill fidelity; A2: SMA-ATR
  parity fix triggering a full 8-mode re-sweep — no gate shopping).
- `scripts/midas_sweep.py`: 8 modes × 4 windows on 50k M15 bars, 8/8 self-tests.
- **Verdict of record: all 8 modes NO-SHIP** under frozen gates (best: SHORT_ONLY,
  PF 1.343, expectancy +0.160R — refused by G6 era-alternation: is1 +8.26R / is2 −12.11R
  / wf −7.25R / oos +8.51R; 2/4 positive windows). Gates untouched; recorded in §9.

## Step 5 — EA + parity

- `mql5/MIDASTOUCH/MidastouchAI.mq5` **v1.03** — compiles 0 errors / 0 warnings;
  gold-pinned by charter, paper-default, session gate, spread veto, weekend policy,
  SL-first per-tick paper mirror, house ledger contract (OPEN 12 / CLOSE 8 / EQ / ERA).
- `mql5/MIDASTOUCH/MidastouchAI_M1_gold.set` preset.
- Parity campaign (v1.00→v1.03, documented in protocol Amendments):
  1. +1-bar fill skew → same-bar evaluate-and-fill fix;
  2. Wilder-ATR history-depth divergence (tester's short preload vs converged python
     series) → **bounded SMA-ATR(14) of closed H1 bars on both sides** — entries then
     aligned exactly (timestamps and sides), terminal vs CSV H1 bars proven identical.
- Outcomes still drift (150 vs 147 trades, small exit R differences) — **not yet at
  certification parity**; the divergence analysis is preserved in the protocol. Next
  session: root-cause remaining drift before any gate consideration.

## Step 6 — Gold paper arm LIVE

- Chart01 (terminal 49E0, active profile): **XAUUSDmicro M15, MidastouchAI v1.03,
  InpArmTag=M1, paper** — mirrors the real account's floor reality ($50 virtual equity
  = actual $50.22; min-lot risk $5.31/trade matches the probe).
- Banner: `[MIDAS1.03] MIDASTOUCH started | mode=0 | symbol=XAUUSDmicro (GOLD-OK) |
  execution=PAPER`; ledger `MIDASTOUCH_paper_XAUUSDmicro_M1.csv` initialized (ERA row
  1789599864, pertick-fills), 0 fills so far.
- `scripts/morning_status.py` gained section **[3b] MIDASTOUCH GOLD ARM** (chart health,
  gold-charter check, ledger age/integrity, live position, R progress); all 16 existing
  morning-status tests pass. Scheduled tasks remain disabled — status is run manually.

## What runs right now

- One terminal (49E0) with the single gold chart; EA paper-only.
- No scheduled tasks, no python monitors, no indices EAs anywhere.
- Next session: (a) verify first gold fills land on the ledger; (b) continue parity
  root-cause (remaining drift); (c) `python scripts/morning_status.py` each morning —
  section [3b] is the gold arm's health line.

## Artifacts index

| artifact | path |
|---|---|
| Synthetic closeout | `docs/V75_CLOSEOUT_20260916.md` |
| Symbol probe | `scripts/deriv_symbol_probe.py` → `artifacts/deriv_symbols_20260916.json` |
| History + validator | `scripts/midas_fetch_history.py` → `data/forex/xauusd/`, `artifacts/midas_history_20260916.json` |
| Playbook | `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` |
| Protocol (frozen gates + amendments) | `docs/MIDASTOUCH_PROTOCOL.md` |
| Sweep engine + verdict | `scripts/midas_sweep.py`, `artifacts/midas_sweep_20260916.json` |
| EA v1.03 + preset | `mql5/MIDASTOUCH/MidastouchAI.mq5`, `MidastouchAI_M1_gold.set` |
| Parity driver | `scripts/midas_parity.py` |
| Morning status [3b] | `scripts/morning_status.py` |

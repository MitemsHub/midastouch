# MIDASTOUCH

**Gold-only algorithmic trading program on Deriv MT5 (XAUUSD / XAUUSDmicro).**

MIDASTOUCH is the successor program to the MitemsHub synthetic-indices effort
(V75MacroEngine / MitemshubAI). The synthetic program is archived; every new
line of work lives here and trades **gold only** — by charter, the EA refuses
to run on anything else.

## Status (2026-09-17)

| component | state |
|---|---|
| Ground-truth probe | ✅ XAUUSD + XAUUSDmicro confirmed on account 140778269; cost toll **0.69%** of a typical H1 stop |
| Validated history | ✅ H1 continuous 2024-04-10 → 2026-09-16; M15 50k bars (terminal cap) |
| Frozen protocol | ✅ Gates G1–G6 frozen before any strategy run |
| 8-mode sweep | ✅ Run — **all 8 modes NO-SHIP** under frozen gates (honest verdict, no gate shopping) |
| EA `MidastouchAI` v1.03 | ✅ Compiles 0/0; gold-pinned; paper-default |
| Parity (EA ↔ python) | 🟡 Entries exact; outcome-level drift remains — open task |
| Gold paper arm | ✅ LIVE — XAUUSDmicro M15, $50 virtual equity (mirrors the real account) |
| Live authorization | ❌ None. No live money is traded, ever, until gates pass |

## Repo layout

```
docs/        MIDASTOUCH_GOLD_PLAYBOOK.md   measured instrument facts (ours, not folklore)
             MIDASTOUCH_PROTOCOL.md        frozen gates G1–G6 + append-only amendments
             MIDASTOUCH_CLOSEOUT_*.md      the pivot record (shutdown → live arm)
scripts/     deriv_symbol_probe.py         read-only broker symbol/floor probe
             midas_fetch_history.py        validated history pull → data/forex/xauusd/
             midas_sweep.py                8-mode research sweep (frozen costs, self-tests)
             midas_parity.py               EA ↔ python parity driver
             morning_status.py             daily status (section [3b] = gold arm health)
mql5/        MIDASTOUCH/MidastouchAI.mq5   the EA (v1.03) + preset
tests/       unit tests (16 morning-status tests + runner suites)
data/        validated XAUUSD/XAUUSDmicro OHLC (commit-checked into git)
artifacts/   probe/sweep/parity verdicts of record (commit-checked into git)
```

## Daily operation

```bash
python scripts/morning_status.py        # [3b] is the gold arm's health line
python scripts/morning_status.py --strict   # exit 1 when anything is unhealthy
```

Research (never re-tune gates after seeing results):

```bash
python scripts/midas_sweep.py --self-test
python scripts/midas_sweep.py           # writes artifacts/midas_sweep_<date>.json
```

## The rules that make this work

1. **Gold only.** The EA fails closed on any non-gold chart.
2. **Paper default.** `InpExecutionMode=PAPER` until certification gates pass.
3. **Frozen gates.** `docs/MIDASTOUCH_PROTOCOL.md` gates are pre-registered;
   amendments are append-only with recorded reasons.
4. **Honest verdicts.** All 8 modes are currently NO-SHIP. That is the record.
5. **Costs first.** Every backtest carries the broker's real spread/slippage model.

## Requirements

- Windows + MetaTrader 5 (Deriv), account with XAUUSD/XAUUSDmicro
- Python 3.11+ (`pip install MetaTrader5 pytest` for probe/status/sweep)
- MetaEditor for EA builds (`scripts/_compile_fwd.ps1`)

## Provenance

The evidence factory (frozen gates, ledger discipline, parity tooling, flat-check
safety) was proven across 8,426 registry trades in the synthetic program and is
reused here wholesale. The archived program's workspace remains untouched at
`../Synthetic Indices Bot/`.

# MITEMSHUB V75 Macro Engine — Production Configuration Guide

> EA version: **v27.00**
> Source: `MitemshubAI.mq5`
> Scope: **Volatility 75 Index only**

## Operating contract

- The EA evaluates entries only on the first tick of a newly opened M30 candle. Attaching or restarting arms the detector and does not immediately evaluate an entry.
- Macro direction requires the previous H4 close and previous H1 close to both be above their own EMA(20) for BUY, or both below their own EMA(20) for SELL. Divergence stands down.
- The previous M30 close is the springboard: BUY at/below the lower Bollinger(20, 2) band or RSI(14) ≤ 35; SELL at/above the upper band or RSI(14) ≥ 65.
- `PositionsTotal() == 0` is required before any entry attempt.
- Risk is exactly 1% of current account equity when the broker lot grid can represent it. If the minimum lot would exceed that amount, the EA refuses the trade rather than silently over-risking.
- SL is exactly 2× H1 ATR(14) from the actual fill and TP is exactly 4× H1 ATR(14). The broker's tick value is replaced by `tick_size × contract_size` when it differs by more than 5%.
- The time guardian runs on every tick and closes a tracked position at `entry time + 10,800 seconds`, regardless of P/L. Position polling and position-identifier close reconciliation recover broker SL/TP and manual closes.
- The HUD displays equity, current-day session P&L, cumulative R, macro state, last gate, active direction, and remaining three-hour lifecycle.

## Presets

| Preset | `InpLiveExecution` | Use |
|---|---:|---|
| `MitemshubAI_VOL75_FINAL.set` | `false` | Safe paper/off validation profile |
| `MitemshubAI_VOL75_PAPER.set` | `false` | Explicit paper/off template |
| `MitemshubAI_VOL75_LIVE.set` | `true` | Explicit order-submission opt-in only |

The EA source itself defaults to `false`; no order is submitted in paper/off mode. Do not infer deployment from a `.set` file alone: compile the source, attach the resulting binary to the intended chart, confirm the Experts startup line and HUD mode, and verify the input value after loading.

## Verification

```bash
python scripts/verify_go_live_artifacts.py
python -m pytest -q tests/test_go_live_artifacts.py
```

MetaEditor compilation and a paper/off terminal run are required before any live use. This repository change does not send orders or alter terminal state.

## Risk note

The strategy contract is deterministic and intentionally sparse; it is not a profitability guarantee. V75 synthetic-index behavior, broker stop levels, minimum lot size, tick-value semantics, spread, slippage, and account currency can materially change realized risk. Confirm the broker's symbol specification and minimum-lot risk before enabling live execution.

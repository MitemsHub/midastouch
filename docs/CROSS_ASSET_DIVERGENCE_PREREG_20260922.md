# Pre-registration — cross-asset structural divergence: does gold disagreeing with AUD carry edge here?

**Written 2026-09-22, before the run it governs.** Results are appended below §Results.

## Why this, and why now

This is the **first signal in this program that is not derived from gold's own price history**, and
it exists because of an external measurement rather than because it sounded good:
`docs/EXTERNAL_LITERATURE_RECONCILIATION_20260922.md` records that a 2026 ten-paper series — which
found **zero** surviving retail rule families in 45 combinations and **zero** surviving
momentum/breakout combinations in ~46 — reports its **strongest single result** as comparing
**gold's swing structure against the Australian dollar's**: it cleared a permutation test, achieved
that program's maximum post-correction Deflated Sharpe, held on a locked holdout, and survived a
disclosed 100× cost increase, while failing their walk-forward-efficiency gate and resting on a
short history. Their own paper reports that two other operationalizations of the same idea failed
comprehensively before that one worked.

Our own audit says the same thing from the other direction: the arm's trigger is the binding rarity
(**82.66 %** of in-session bars produce no trigger), everything protective is free, and the
constraint on learning anything is data. A signal that is *structurally* different, fires on
structure rather than on band extremes, and adds **information instead of parameters** is therefore
the one new direction the evidence actually supports.

## The data, fetched for this study, and its provenance

| | |
|---|---|
| gold | `data/forex/xauusd/XAUUSD_{M15,H1}_upcomers.csv` — unchanged, the series every certificate uses |
| context | `data/forex/xauusd/AUDUSD_{M15,H1}_upcomers.csv` — **NEW**, fetched 2026-09-22 |
| fetch | `python scripts/midas_fetch_history.py --symbols AUDUSD --suffix _upcomers` |
| provenance | terminal `C:\Program Files\MetaTrader 5` build 6204, account **1428765 @ Upcomers-Server**, balance 25004.26 USD — the SAME terminal, account and server as gold's series, recorded in `artifacts/midas_history_20260922-upcomers.json` |
| coverage | AUDUSD H1 **4,316 bars**, M15 **17,250 bars**, 2026-01-12 → 2026-09-22, all validation checks PASS |
| clock | both series are the terminal's own server clock and are shifted by **the same** pinned offset per window (`midas_parity.assert_server_offset`) |
| the gold default is untouched | `--symbols` was ADDED; `SYMBOLS` still contains only `XAUUSD`, so no existing artifact's provenance becomes ambiguous |

## The signal, fixed in advance, and non-repainting by construction

**Swings (H1, on each leg independently).** A bar `i` is a swing high iff `high[i] > high[i-1]` and
`high[i] > high[i+1]` and `high[i] > high[i+2]`. It is **CONFIRMED only at the close of bar `i+2`**
— never earlier, and the signal code uses the confirmation time, not the swing's own time. The
mirror defines a swing low.

**Structure direction at time `t`** = `+1` if, among the swings **confirmed at or before `t`**, the
latest swing high exceeds the previous swing high **and** the latest swing low exceeds the previous
swing low; `−1` if both are lower; `0` otherwise (including "fewer than two swings yet"). At least
two confirmed highs and two confirmed lows are required.

**Divergence** at a gold M15 bar closing at `ct` = gold's direction and AUD's direction are both
non-zero **and differ**. Only H1 bars whose close is `<= ct` are visible (`bisect_right` on the
close-time array, the same rule `run_mode` uses for its own `mac`).

**Three variants, declared before the run:**

| variant | fires | direction |
|---|---|---|
| `DIVERGE` | gold and AUD structures disagree | gold's own direction |
| `FADE` | gold and AUD structures disagree | against gold's own direction |
| `ALIGN` | gold and AUD structures agree (both non-zero) | gold's own direction |

## The engine, the windows, and the pass rule

- **Engine:** `midas_sweep.run_mode`, called **unchanged** except that `data["m15_bb"]` — the array
  the engine already reads its trigger from, exactly as the frequency-axes study used it — is
  replaced by the variant's signal array. Mode `TRIGGER_ONLY`, so the macro gate is **not** applied
  and the signal is tested on its own. Geometry, sizing, costs and session window at their defaults
  (2.0 × ATR(H1) stop, 2.0R target, 0.25 % of the account basis, 06–20 UTC).
- **Windows:** the repository's own pre-registered split — **select on `wf` (2026-01-12→03-31),
  report on `oos` (2026-04-01→2026-09-16)**. Both legs use the same offset in both windows.
- **Self-check, binding:** the pinned venue-corpus law (`wfv REVERSE_DIRECTION n=56 / +15.9352R`)
  must reproduce before any table prints. A lookalike signal on a lookalike engine is worth nothing.
- **A variant passes ONLY IF, on the held-out window:** (1) `t >= 2.4` — the 95th-percentile max-|z|
  for a **3-variant** family, which is the program's own rule for a searched family; (2) `n >= 30`
  closed trades; (3) `>= 0.30` fills/day. Failing any one of the three is a **FAIL**, and the
  verdict says which.
- **What it is measured against:** the armed mode's own held-out numbers on the same window
  (`+0.0355R` over 127 fills, 0.75/day, DD 6.3R) — printed in the same table, so the comparison is
  visible rather than implied.

## Disclosures before the numbers

- **The trial count is larger than 3 and this study cannot fix that.** The external program already
  searched several operationalizations of this idea, and I had read that before writing this. The
  3-variant threshold is therefore an **understatement** of the true search; `t >= 2.4` is a weak
  bar for a hypothesis that arrived pre-selected, and a pass will be reported with that sentence
  attached.
- **AUD is a proxy, not the mechanism.** The economic story is commodity/risk currency versus
  haven metal; nothing here tests the story, only whether the joint structure carries information
  about gold's next move on THIS venue's bars.
- **8 months, two clock eras, one instrument.** The same short-history fragility the external paper
  discloses about its own result applies verbatim here, and its authors' own reproduction fell
  short of their original magnitude.
- **The swing parameters (1 before, 2 after) are fixed here and not swept.** That is deliberate:
  sweeping them would multiply the search on 8 months of data. They are declared, not optimised.
- **No EA change.** This study is offline only; MQL5 ports nothing unless a variant passes, and a
  port would then be its own change with its own parity certificate.

---

# Results (appended after the run) — **the hypothesis FAILS, and it fails in both spans**

**Self-check passed first:** `wfv REVERSE_DIRECTION: n=56 totalR=+15.9352 vetoed=0`. The signal is
supplied through `data["m15_bb"]` with the engine otherwise untouched, so the arithmetic below is
the engine of record's. Artifact: `artifacts/midas_cross_asset_20260922.json` · Harness:
`scripts/midas_cross_asset.py` · Pins: `tests/test_cross_asset.py`.

### A defect found during verification, before anything was reported

The first run expressed the **context** series in bar **OPEN** times while the gold leg used
`h1_ct` (closes). That gave the AUD leg's swings **one H1 bar of lookahead** — a signal at `t` could
depend on bar `t`'s high. It was caught by reading the code against its own claim, fixed, and the
pins in `tests/test_cross_asset.py` now include a direct **repaint test**: perturbing a future bar's
high must not move a single earlier signal. **The verdict is negative either way** — no variant was
rescued by the lookahead — but the number reported is the one with it removed, and the window-scoped
bar counts were corrected in the same pass (they had printed the whole corpus twice).

### The measurement — signal counts first, because rarity was never the problem

| window | M15 bars | divergent bars | aligned bars | gold structure non-zero | AUD non-zero |
|---|---|---|---|---|---|
| `wf` | 5,072 | 525 (10.35 %) | 1,127 | 2,789 | 2,911 |
| `oos` | 10,972 | 1,089 (9.93 %) | 2,710 | 6,458 | 6,349 |

**The signal is not rare — it is wrong.** Roughly 10 % of bars disagree structurally, and it fills
~1.0/day, *more* often than the armed mode.

### The ablation (held-out `oos`; the incumbent printed in the same table for scale)

| variant | n | /day | zero days | expR | pf | win | DD(R) | t | n for t≥1.5 |
|---|---|---|---|---|---|---|---|---|---|
| REVERSE_DIRECTION (armed, baseline) | 127 | 0.75 | 41.4 % | **+0.0355** | 1.074 | 0.433 | 6.3 | +0.39 | 1,931 |
| `DIVERGE` (their reading: gold's own direction) | 165 | 0.98 | 39.1 % | **−0.0278** | 0.930 | 0.461 | 16.1 | −0.35 | — |
| `FADE` (against gold's direction) | 164 | 0.97 | 39.1 % | −0.0115 | 0.964 | 0.451 | 16.3 | −0.14 | — |
| `ALIGN` (both structures agree) | 203 | 1.20 | 32.5 % | −0.0283 | 0.923 | 0.429 | 19.3 | −0.39 | — |

Selection span `wf`: `DIVERGE` **−0.1598** (n=77, t −1.41), `FADE` −0.1814, `ALIGN` −0.1084. Every
variant is **negative in BOTH spans**, and the held-out failure is not an underpower problem: the
sign is consistent, the samples are 164–203 trades, and the drawdowns (16–19R) are three times the
incumbent's.

### The verdict, against the rule fixed before the run

```
PASS RULE on the held-out window (t >= 2.4, n >= 30, fills/day >= 0.30):
  DIVERGE  FAIL: t=-0.347 < 2.4
  FADE     FAIL: t=-0.140 < 2.4
  ALIGN    FAIL: t=-0.385 < 2.4
```

**All three fail on the first test and only that test** — n and frequency both clear their bars, so
this is not "not enough trades": it is the wrong sign on more than enough trades. The one signal in
the external literature that survived its own program's full stack **does not transfer to this
venue, this instrument or this span.**

### What this means, in the words of the program's own two questions

- **Does the system still refuse what it cannot justify?** Unchanged and intact: the signal never
  reached the EA. Nothing was ported, nothing was armed, and no MQL5 line moved.
- **What is between us and a validated strategy?** One more candidate is now *closed* rather than
  open. The external result's own disclosed weakness ("a fresh reproduction attempt falls short of
  the original magnitude") is here extended to its limit: on the venue's own bars it does not
  reproduce at all, and the negative is better powered than the positive it fails to confirm.
- **The honest reading of the whole exercise:** the request was to improve the EA's intelligence
  using the outside research. The outside research's single strongest lead was tested here, at the
  first opportunity, with a pre-registered rule and a lookahead bug caught before reporting — and it
  is dead on arrival. That is the value of the exercise, and it is why the EA's own measured
  structure (a rare trigger, a macro leg that buys drawdown rather than expectancy, and every
  protective gate free) has still not been beaten by anything brought in from outside.

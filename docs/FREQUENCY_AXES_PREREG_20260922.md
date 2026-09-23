# Pre-registration — the frequency axes (session window × trigger threshold)

**Written: 2026-09-22, before the sweep it governs was run.** The numbers live in
`artifacts/midas_frequency_axes_20260922.json` and in §Results, which was appended after.

## The question

The arm is live-armed and has placed **zero** trades. Its own refusal census
(`NOFILLSUM`, UTC day 20718, last row `25,4,0,0,0,0,0,21,0`) says where that comes from:

| counter | value | meaning |
|---|---|---|
| `signal` | 25 | bars evaluated with no trade |
| `mism` | 4 | a trigger fired and the MODE refused it |
| `notr` | 21 | no trigger fired at all |
| `session`/`friday`/`spread`/`riskcap`/`brk`/`news` | **0** | no protective gate refused anything |

So every safety measure in the file is currently free, and the fill rate is decided by two
things: **how often a trigger fires inside the window**, and **whether the window is the one
the certification measured**. Both are axes, not gates, which is why this study changes neither
the mode nor any protective rule.

## What was measured, and on what

- **Corpus:** `data/forex/xauusd/*_upcomers.csv` — the venue's own bars, the market the EA
  trades, shifted into true UTC by the window's pinned offset (`midas_parity.python_build_data
  (corpus="venue")`). **Not** the retired 50,000-bar research series: its bytes were deleted on
  2026-09-21 and `archive/frozen_corpus/` is not on this checkout.
- **Engine:** `midas_sweep.run_mode`, called **unchanged** — every keyword at its certified
  default except `win_lo`/`win_hi`, which the engine already exposes (`run_mode`'s own docstring:
  "a caller could not sweep them — and the grid axes a walk-forward needs ... are exactly those
  four. Every one is also a live EA input"). The trigger array is what the engine already reads
  from its data dict (`data["m15_bb"]`), so a different threshold is a different array, not a
  different engine.
- **Mode:** `REVERSE_DIRECTION`, the armed mode. Nothing here proposes a mode change.
- **Self-check, and it is binding:** the harness must first reproduce the pinned venue-corpus law
  `wfv` = **53 trades / +14.256R** (`tests/test_midas_minlot_veto.py`, re-pointed 2026-09-21).
  If it does not, it exits without printing a table.

## The rule, fixed in advance

- **Select on `wf`** (2025-09-15 → 2026-03-31). **Report on `oos`** (2026-04-01 → 2026-09-16).
  Both are the repository's own pre-registered windows, not windows chosen for this study.
- **Axes:** session window ∈ {(6,20) certified, (4,18) what live does today, (8,22) live-aligned,
  (4,20), (6,22), (0,24)} in true UTC; trigger threshold k ∈ {2.0 live/frozen, 1.5, 1.0}.
- **A cell may replace the incumbent ONLY IF, on the held-out window, it**
  1. raises entries per day (`n`/day), **and**
  2. gives up no more than **0.10R** of expectancy, **and**
  3. gives up no more than **2R** of max drawdown.
- **Reported beside every cell, and treated as a first-class outcome:** the share of days with
  **no entry at all**. A configuration that averages ~0.7 entries/day but sits flat on ~half of
  days is not a configuration a prop account can be evaluated on, whatever its expectancy is.
- **If no cell passes, the answer is "the armed configuration is at its certified frequency"**
  and the response to a zero-fill day is patience plus the machine-side fix — not a relaxed gate.

## Disclosures, before the numbers

- **The k prior is contaminated and this study cannot undo that.** The Sep-18 sweep
  (`artifacts/midas_variant_research_20260918.json`) measured the same axis on the **retired,
  deleted** series — a *different market* from the venue's, per the repo's own measurement — and
  I had read its table before writing this. That table says k=1.0 beats k=2.0 monotonically at
  every RSI band. So `oos` here is a **stability check across corpora and spans, not a blind
  holdout**: it can falsify the prior, and its passing does not establish the prior.
- **The session-window axis is not a new idea being fitted.** (4,18) is not a hypothesis; it is
  what the live arm does today, measured from the ledger and the source (§ above). (6,20) is
  what every cited number was measured on. Comparing them measures the cost of a frame
  discrepancy, which is a defect if it is one, and this study does not assume which way it cuts.
- **Sizing is the account basis, `risk_fraction` left at its default.** R-multiples are
  lot-invariant, so expectancy/pf/dd are comparable across cells; the min-lot floor and its veto
  are the only places where size enters, and `vetoed` is reported per cell.
- **`tickcov` is not used.** It is 8-12 days wide and cannot support a frequency claim.

## What would make this study wrong

A cell that passes on `oos` but whose entries cluster in a handful of days (visible as a
zero-day share that does not improve alongside `n`/day), or whose expectancy gain comes from
trades the min-lot veto should have refused (`vetoed` > 0). Both are printed, so the check is
readable rather than implied.

---

# Results (appended after the run)

**Self-check passed first:** `wfv REVERSE_DIRECTION: n=53 totalR=+14.2563 vetoed=0` — the pinned
venue-corpus law, reproduced by the harness before it printed anything. The table below is
therefore the engine of record's arithmetic.

### Held out — `oos`, 2026-04-01 → 2026-09-16, 168 days, mode REVERSE_DIRECTION

| window UTC | k | n | /day | zero-entry days | expR | pf | win | ddR | netR |
|---|---|---|---|---|---|---|---|---|---|
| 6–20 certified | **2.0 live** | 107 | 0.63 | **49.7 %** | **−0.031** | **0.917** | 0.402 | 7.0 | −3.34 |
| 6–20 | 1.5 | 127 | 0.75 | 41.4 % | +0.035 | 1.074 | 0.433 | 6.3 | +4.50 |
| 6–20 | 1.0 | 138 | 0.82 | 36.1 % | −0.019 | 0.942 | 0.413 | 11.7 | −2.65 |
| **4–18 live window** | **2.0 live** | 111 | 0.66 | 50.3 % | −0.003 | 0.981 | 0.414 | 7.6 | −0.29 |
| **4–18 live window** | **1.5 chosen** | **130** | **0.77** | **40.8 %** | **+0.087** | **1.201** | 0.462 | **6.5** | **+11.30** |
| 4–18 | 1.0 | 140 | 0.83 | 37.3 % | −0.009 | 0.966 | 0.414 | 8.9 | −1.33 |
| 8–22 | 1.5 | 117 | 0.69 | 43.8 % | +0.070 | 1.159 | 0.453 | 6.2 | +8.21 |
| 4–20 | 1.5 | 138 | 0.82 | 39.1 % | +0.085 | 1.196 | 0.457 | 7.5 | +11.67 |
| 0–24 | 1.5 | 177 | 1.05 | 30.8 % | +0.025 | 1.048 | 0.424 | 9.3 | +4.44 |

Selection span `wf` (the same cells, for the record): 4–18 at k=2.0 = 50 fills / +0.426R / pf 2.377;
at k=1.5 = 52 fills / +0.500R / pf 2.798; at k=1.0 = 58 fills / +0.394R / pf 2.192. The ordering is
the same in both spans.

### What the rule selected

**4–18 UTC (the window the arm actually runs) at k=1.5.** Checked against the rule fixed above,
on the held-out window: entries/day 0.63 → **0.77 (+22 %)**; expectancy −0.003R → **+0.087R** (a
gain of 0.090R, far inside the 0.10R allowance it did not even need); drawdown 7.6R → **6.5R**;
zero-entry days 50.3 % → **40.8 %**; `vetoed` = 0 in every cell. **It passes all three tests, and
the incumbent fails outright** — at the live threshold the armed mode is a net loser on the
venue's own bars in the held-out window with half of all days flat.

### The prior this falsified

The Sep-18 table pointed at k=1.0. On the venue's bars, in the held-out window, **k=1.0 is the
worst of the three** — negative expectancy in every window tested, pf 0.942–0.981. The mechanism
is in the code rather than in the numbers: the trigger is `bb_touch`, ELSE the RSI branch, so
narrowing the band **displaces** the RSI trigger instead of adding to it. A monotone in-sample
sweep on a deleted corpus from a different market could not show that; a held-out window on the
market the EA trades could, and did.

### The window axis: a mismatch that costs nothing

The live arm's session is UTC **04:00–18:00** (the EA compares its "UTC" inputs against
`iTime`, i.e. server hours, and this venue's clock is +2), while the certified window is
06:00–20:00. Swept on the venue's own bars, **the live window is better in both spans** — at k=1.5,
held-out: 130 fills / +0.087R / pf 1.201 against the certified window's 127 / +0.035R / 1.074.
So nothing was changed here. What was wrong was the record's silence about it: the parity contract
normalises the session inputs by the offered offset precisely so the *tester* frame agrees with
python, and `build_inputs`'s own docstring says the live side "runs as 04:00-18:00". That is now
stated here and in the amendment instead of being left for someone to rediscover.

### What this is not

Not a validation. At +0.087R over 130 trades the t-statistic is ≈0.9, so the held-out expectancy
is statistically indistinguishable from zero; the venue's own gate (pf ≥ 1.30, expectancy ≥ +0.15R)
remains **FAILED**; the account remains an operator override on an unvalidated strategy. It is an
**ordering** between three thresholds that held on two spans and one market under a rule written
before the numbers existed.

### The certificate, run after the change (2026-09-22)

`python scripts/midas_parity.py --window tickcov` — the only window with real ticks, and the only
one whose PASS is recordable — returned **PASS** at the new threshold:
`artifacts/midas_parity_result_20260922_1547.json` (14:47:00Z, run on the v1.24 build the arm now
runs; two earlier passes at 14:02 and 14:26 certify the same contract on v1.23 and are kept),
the python leg 9 trades /
**+0.2699R** against the EA's 9 / **+0.271R**, count, open time, close time and side all agreeing,
`max|dR|` **0.0004**, `tick_model used: real`. The artifact carries the input block the pass used
(`InpBBDev: "1.5"`), so what it describes is readable from it. The trade set **moved** — two entries
present at 2.0 are gone and two new ones appear — so this certifies a changed configuration rather
than a no-op. It says the two engines are one contract at this threshold; it says nothing about
expectancy, and the venue's own gate remains FAILED. Recorded in `artifacts/live/armed.json` under
`parity_certification`. An identical PASS at 14:02:45Z (`..._1502.json`) certifies the same contract
and is kept but not counted twice; the **later** one is the pass of record because the two files on
the contract's side were edited at 14:14Z (measured inert: the python leg re-derived from the current
tree reproduces it to the digit) **and** because the arm's own first fill had blocked a fresh pass —
see below.

**And the arm traded.** At 14:00:00 UTC the same day it took a live SHORT (0.01 XAUUSD @ 4333.07,
signal bar 13:45), closed by the venue at 14:06:37 for **+$4.31 / +0.104R** — the account went
25,000 → **25,004.26**. That first fill then exposed **four** false statements in the record-keeping
path, all fixed and pinned — the worst of them, in four separate readers, was that a *closed* fill
read as an **open** position because a netting `LOPEN` carries `posid = 0` at write time while its
LCLOSE carries the real position id. One of those readers, `mt5_ops.ledger_flatness`, is the gate
this very harness refuses to stop the terminal over, so the fill did not merely mislead a report: it
**blocked the certification run** this document's deployment depends on. That is the reason the pass
of record was taken after the fix rather than before it. See the CHANGELOG for 2026-09-22.

The account layer — which no parity pass can cover, since `midas_parity` pins `InpPropGuard=false`
and `InpRiskPercent=1.0` because the python engine of record does not model it — was measured
directly with `scripts/verify_sizing_live.py`: **legal**, at **0.01 lots risking $39.01 of a $62.51
budget**, quantised down by the venue's minimum lot (exit 4, `LEGAL_BUT_NOT_ARMED`, because the
python-side gate needs a validation record this override does not create). Recorded beside the
certificate in `artifacts/live/armed.json`.

### Things this study moved that it did not set out to move

Making the trigger threshold part of the contract moved the contract's own regression laws. All
three were re-measured and re-pointed with the reason recorded:

- `tests/test_midas_minlot_veto.py`: the venue-corpus wfv law **53 → 56 trades**, +14.2563R →
  **+15.9352R**; the amendment-6 invariant (**the min-lot veto never fires there**) is unchanged.
- `tests/test_parity_corpus.py`: the parity **veto window had to be re-chosen**, because at 1.5 the
  old window (2026-05-11..16) refused nothing at all (`news_vetoed=0`, `removed={}`) — a window
  whose own docstring says it must be re-chosen rather than asserted around. Found by sweeping
  every 5-day window of the venue span at its era's own clock: exactly one week survives
  (2026-03-15..20, removing the entry at 2026-03-19 19:45, adding none). The first sweep said June;
  that was the sweep's own clock error, and both readings are recorded in `WINDOW_SPECS`.
- `tests/test_morning_status_preset.py`: the reformatting fixture compared against a literal
  (`"2.0"`) and went stale; it now reads the pin's own value, so it cannot rot the next time a pin
  legitimately moves.

Full suite after the change: **1444 passed, 10 skipped, 1 failed** — the failure is the
pre-existing environmental `test_forward_cell_prereg` (661 against its literal 658), unchanged by
this work and on no changed file's path. (After the ledger-reader fixes and the re-run the same
suite reads **1450 passed, 10 skipped, 1 failed** — same single pre-existing failure.)

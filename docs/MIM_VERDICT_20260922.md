# MARKET INTRADAY MOMENTUM — VERDICT — 2026-09-22 (night)

**FAIL — failed gate(s): t.** The with-trend family the operator's complaint pointed at was
pre-registered (`docs/MIM_PREREG_20260922.md`, written before any measurement), implemented
exactly as registered (`scripts/midas_mim.py`), run on both pinned spans through the engine
of record, and **did not clear its bar**. This is the second external momentum lead to die
on this venue, and this file says so in those words.

## 1. The numbers (artifact: `artifacts/midas_mim_20260922.json`)

Self-check reproduced the pinned corpus law (wfv `REVERSE_DIRECTION`: n=56, +15.9352R)
before anything else was computed.

| cell (held-out `oos`) | n | fills/day | mean R | pf | t | verdict gate |
|---|---|---|---|---|---|---|
| **MOM_0 (primary)** | 182 | **1.08** | +0.0136 | 1.017 | **0.17** | t ≥ 2.4 **FAILED** |
| MOM_0.25 | 166 | 0.98 | +0.0183 | 1.027 | 0.22 | FAILED |
| MOM_0.5 | 158 | 0.94 | −0.0033 | 0.981 | −0.04 | FAILED |
| REV_0.0 | 187 | 1.11 | −0.0591 | 0.871 | −0.76 | direction check: lost, as predicted |
| REV_0.25 | 172 | 1.02 | −0.0915 | 0.809 | −1.15 | direction check: lost |
| REV_0.5 | 161 | 0.95 | −0.0809 | 0.834 | −0.98 | direction check: lost |

Selection span (`wf`): same shape — best MOM cell +0.0377R, t 0.31. Robustness: **0/3** MOM
cells clear the t-bar anywhere.

## 2. The predictability regression, and what its decay means

The raw descriptive regression (§3 of the pre-reg) is the most informative part:

* selection span: `beta = 0.464`, `t_beta = 2.297` — *nearly* the published effect, in-sample;
* held-out span: `beta = 0.103`, `t_beta = 0.763` — **the effect decays out-of-sample**.

This is the signature the whole program exists to catch: a real-looking in-sample
relationship that does not survive the span boundary. The engine cells make it concrete —
MIM would have traded **182 times** held out (1.08 fills/day — the "active" book the
operator asked for) and earned **+0.0136R per trade**, which after this venue's half-spread
on both sides and commission is a statistical zero. Activity without edge is the precise
thing the gates exist to refuse.

## 3. What the direction checks add

Every `REV_*` twin lost held out while every `MOM_*` twin was flat-to-slightly-positive:
the *sign* of MIM is right on gold (morning direction carries into the afternoon more than
it reverses), but the edge per trade is smaller than the cost of taking it at M15 with the
certified geometry. A real effect, one order of magnitude too small for this clock and cost
structure. That is a measurement, not a defeat: it is the same shape as the Mahadzva
Bollinger null (their 2,231-trade +0.022R vs our 127-trade +0.0355R), and it is why the
verdict is FAIL and not VOID.

## 4. The evening census this study answers (`scripts/midas_evening_census.py`)

The complaint that motivated this ("the market is going up and the EA does nothing") measured
out as: the day was net **−4.68 pts** (high 4375.88 at 00:00Z, crash to 4291.39 at 08:30Z);
the afternoon recovery **did begin in-gate** (15:00–18:00Z: +22.87 pts inside the 04–18Z
window) but the armed trigger never fired on it; the evening's +16.46-pt run off the 18:00Z
low is entirely outside the gate. The arm's ledger shows **zero safety refusals today** —
nothing was vetoed; the triggers simply were not there. The armed mode cannot join a
sustained rally by construction; MIM was the with-trend alternative, and it is a null here.

## 5. What follows

* **Nothing is armed, disarmed, or re-risked.** The EA, the preset, and the arming record are
  untouched by this study.
* The **sweep-continuation family remains the strongest frequency upgrade on the table** —
  held-out 152 trades, +0.1955R, t +2.21 — and its forward shadow recorder is running
  (v1.28 `SWEEPSHADOW`, first rows due with the next 07:00Z window). Frequency, if it is
  ever justified, will come through that gate, not by lowering this one.
* The MIM result is closed as **measured-and-refused**: 182 held-out trades is a real
  sample, the answer is no, and re-testing the same family with a different threshold is
  exactly the multiple-testing drift this program exists to refuse.

## 6. Defects found and fixed on the way

* `midas_sweep_shadow.live_bars` called `.get()` on numpy structured scalars — caught on its
  first live use by the evening census, fixed (`b["spread"]`), exercised live. The shadow
  recorder's first real morning would have hit this; now it cannot.
* The MIM harness pins the closed-bar ATR read (the 09:00Z bar for a 10:45Z decision) —
  reading the still-open 10:00Z bar would have been lookahead, and the pin in
  `tests/test_mim.py` holds that line.

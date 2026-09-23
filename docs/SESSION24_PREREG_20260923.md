# Pre-registration — 24-hour operation: can this arm trade the full session intelligently?

**Written 2026-09-23 02:49 UTC, before any measurement below was run.** The question was
asked by the operator directly: "Can the EA actually be intelligent enough to trade the
full 24 hours session?" This document fixes the study that answers it.

## The question, stated so it can fail

Not "can the EA mechanically run 24 hours" — it can; the window is two preset inputs. The
question is whether **the armed rule's own trigger earns money in the hours the preset
currently refuses to look at** (UTC 18:00–04:00, the complement of the certified window
04–18Z), measured on the data of record, with a verdict rule fixed before the numbers.

## What is measured

- **Engine:** `midas_sweep.run_mode`, called unchanged, mode `REVERSE_DIRECTION` (the armed
  rule), certified geometry (2.0×ATR(H1) stop, 2.0R target). The ONLY thing that moves is
  the `win_lo`/`win_hi` keyword — exactly what the preset's session inputs control live.
- **Corpus:** the data of record per window declaration (`corpus="venue"` for the venue
  era, `"frozen"` for `oos`), through `midas_parity.python_build_data` at each window's
  declared server offset.
- **Windows (the repository's own):** select on `wfv` (2026-01-12 → 03-31, +1h era), held
  out on `oos` (2026-04-01 → 09-16, +2h era). No new split is invented.

## Contamination, disclosed before the numbers

Twice in this session, BEFORE this document existed, runs on the engine at other windows
were printed to the operator:

- the with/without-window comparison on `wf`/`wfv`/`oos` (with-window rows reproduce the
  certified laws; the without-window rows showed `oos` +4.44R vs +4.50R with-window);
- the 22 Sep single-day counterfactuals and the MIM study (`docs/MIM_VERDICT_20260922.md`).

None of those numbers set this study's thresholds — the thresholds below come from the
repository's existing laws (the sweep pre-reg's t-bar, the session-compat study's fill-day
floor). But the *choice to look at the evening hours* was prompted by watching the evening
tape move, so this is a **stability check on a mechanism stated in advance** (snap-back in
quiet flow vs expansion — the same mechanism statement the session-compat pre-reg made),
not a blind discovery. The forward record remains the real arbiter.

## Candidates, fixed in advance

| candidate | window (UTC) | meaning |
|---|---|---|
| **incumbent** | 04–18 | the armed preset, unchanged |
| **`24H`** | 00–24 | the gate deleted; the rule sees every hour |
| `EVE-ADD` | 18–04 (evaluated in addition, verdict-only) | the complement, judged on its own |

`EVE-ADD` is not a preset candidate — the EA cannot express a wrap-around window without
new code. It is measured to *attribute* any `24H` verdict: if `24H` fails but the evening
complement alone passes, the study says so and names the follow-up (a window with wrap
support). If both fail, the complement is dead too.

## The pass rule, fixed in advance

`24H` may replace the incumbent ONLY IF, on the **held-out** span (`oos`, frozen corpus):

1. **net R ≥ incumbent's net R** (it must not give up return to buy activity), **and**
2. **mean R per trade ≥ incumbent's mean R − 0.02** (per-trade edge must survive the
   dilution of 24-hour bars; 0.02R ≈ half this arm's spread cost at the held-out stop
   width — named so the rule is a number, not a vibe), **and**
3. **max drawdown ≤ incumbent max DD + 3.0R** (activity that triples the drawdown is not
   "more opportunity", it is a different risk), **and**
4. **the direction of the comparison agrees on the selection span** (`wfv`: `24H` net R ≥
   incumbent net R), **and**
5. **fills/day ≥ 0.50 held out** (the operator's request is activity; a change that
   produces none is not what was asked).

All five conditions must hold. If any fails, the verdict is **FAIL** and names which.

## Multiple-testing honesty (skill rule 1)

This is a **2-candidate** decision (`24H` vs incumbent), not a search: no grid, no sweep,
no parameter was tried. Threshold: with N=1 pre-named hypothesis the conventional t-bar is
1.96; the mean-R comparison in condition 2 carries that burden explicitly — `24H` must show
held-out mean R **≥ +0.0155R with t ≥ 1.96** for condition 2 to count as met by margin;
otherwise condition 2 is met only by the incumbent-parity reading (mean within 0.02R of
incumbent). This dual reading is fixed here, before the run, so the verdict cannot drift.

## Power, computed before the run

From the held-out with-window fills of this exact rule: mean +0.0355R, sd ≈ 1.05R (measured
in this session's earlier tables). To clear the incumbent-parity reading at t ≥ 1.96 the
evening complement must add a distinguishable positive: n ≈ (1.96·1.05/0.0355)² ≈ **3,180
trades** for the added hours alone to prove themselves at the conventional bar. The `oos`
evening complement holds ~50 fills per ~5.5 months. **The study is therefore powered to
REFUSE, not to confirm** — and this document says so before running. A FAIL is a result:
it retires the request until the evidence base changes (more history, or a family that
passes forward like the sweep shadow).

## Verdict wording (fixed in advance)

- **PASS** → the artifact and CHANGELOG name it, and the next step is a preset change by
  arming record (never by editing an input), with parity re-certification.
- **FAIL** → the record says the incumbent window stays; the request is retired until new
  evidence (forward shadow verdict, or a new corpus era) changes the basis. No re-run with
  a different threshold. That is the rule this document exists to enforce.

## EVE-ADD attribution bar (fixed before the run)

`EVE-ADD` (the 18–04Z complement, judged alone) is reported to *attribute* a `24H` verdict.
To avoid a post-hoc story, its reading is fixed now: if the held-out complement shows mean R
≥ +0.0355R with t ≥ 1.96, the study says the evenings earn a dedicated follow-up (a
wrap-capable window needs EA code and its own pre-reg); any weaker result is reported as
"no evidence the evenings earn a place", regardless of how close it lands. There is no
technicality reading for the complement — it either clears the same bar a new family would
(t ≥ 1.96 on a positive mean) or it does not.

## Results

Measured 2026-09-23 ~03:5x UTC by `scripts/midas_second_session.py` (artifact:
`artifacts/midas_session24_20260923.json`; corpus law self-check reproduced first:
wfv defaults n=56, +15.9352R exactly).

| span | book | n | net R | mean R | PF | max DD | fills/day |
|---|---|---|---|---|---|---|---|
| wfv (select) | incumbent 04–18Z | 56 | +15.94 | +0.2846 | 1.38 | 3.8 | 0.28 |
| wfv | 24H | 77 | +24.99 | +0.3245 | 1.71 | 6.0 | 0.97 |
| **oos (held out)** | incumbent 04–18Z | 129 | **+10.26** | +0.0796 | 1.16 | 5.24 | 0.74 |
| **oos** | **24H** | 178 | +5.56 | +0.0312 | 1.06 | **9.49** | 1.05 |
| oos | eve complement (18–04Z alone) | 74 | +4.46 | +0.0602 | 1.17 | 4.95 | — (t = 0.52) |

**VERDICT: FAIL** — conditions c1 (net R), c2 (mean R), c3 (drawdown) all fail on the
held-out span; c4 (direction on selection) and c5 (activity) pass. The 24-hour book gives
up **−4.71R** held out to gain 49 fills, at **+4.25R more drawdown**, and its per-trade
mean (+0.0312R, t = 0.68) does not clear the margin reading (+0.0155R at t ≥ 1.96) nor
match the incumbent within 0.02R.

**Attribution (`EVE-ADD`, rule fixed before the run):** the evening complement alone made
**+4.46R on 74 fills** (pf 1.17) — but at **t = 0.52** it does not come remotely near the
family bar (t ≥ 1.96 on a positive mean). The study says: **no evidence the evenings earn
a place** — and by the pre-registered wording, there is no technicality reading. On the
selection span the complement measured +14.18R (t 2.42), which is exactly the shape of an
in-sample attraction that does not survive the held-out half; trusting it would be the
repository's named failure mode.

**A structural finding the single-position engine forces (measured, new):** the engine
holds ONE position, so "adding the evening hours" is not additive — the 24H book is a
DIFFERENT PATH, not incumbent-plus-evenings. On `oos`, 53 certified incumbent fills are
absent from the 24H book (an evening position occupied the slot), 28 new day fills appear,
76 are shared. Any future evening design must be measured as a full-path candidate against
the incumbent, exactly as this study did — never as an overlay.

**Consequence, per the verdict wording fixed in advance:** the incumbent window stays.
The request is retired until the evidence base changes — a forward shadow verdict (the
sweep family's rows begin accumulating at 07:00Z today) or a new corpus era. No re-run
with a different threshold. The frozen corpus was restored from the pinned commit
(248db66) solely so the `oos` leg could run — **every file SHA-256-verified against the
manifest before use, all three OK** — and the bytes were returned to retirement
immediately after the run, per `docs/FROZEN_CORPUS_20260921.md` §5; the tree is back in its
recorded state and the artifact holds the numbers. It remains retired as the data of record.

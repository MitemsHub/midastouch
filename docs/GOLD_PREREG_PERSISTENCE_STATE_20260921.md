# Pre-registration: is the decay regime-driven? (state split, selected on H1, tested on H2)

**Declared** 2026-09-21, before the run. **Harness** `scripts/gold_persistence_state.py` →
`artifacts/gold_persistence_state.json`.

## Why this one is structurally different

The last three exit studies all decayed in their second half (+0.68→+0.17, +0.57→+0.17,
+0.99→+0.22 in mean R). Every one of them split **by trade order** and then reported the second
half as a caveat. This study uses a **time split at the window midpoint**, and — the point — it
**selects a state rule on the first half and freezes it before touching the second**.

That is the first genuinely split-sample test in this program: H1 is the earlier calendar period,
H2 the later one, so an H1-selected rule tested on H2 is tested forward in time. It does not make
the whole program out-of-sample (the trigger and the geometry were both found on this window), but
it is a real holdout for the *state* being tested, and the declaration below fixes it before any
number exists.

## The axes, fixed here

| axis | bins |
|---|---|
| **volatility** | H1 ATR at the entry bar vs its **causal trailing median** (`trailing_percentile`, the same lookback the frozen engine uses): **low** < 0.8×, **normal** 0.8–1.3×, **high** > 1.3× |
| **session (UTC)** | **00–06**, **06–12**, **12–17**, **17–22** — the trigger study's own convention, reused so the bins are not re-invented |
| **news proximity** | inside the **±15-minute** blackout around a **HIGH** (top-tier) release, per `midas_prop.risk.news_calendar` — the same module, window and filter the EA uses at runtime |

**Cells: 24 with the news axis, 12 without.** The news axis is measured **only if** the calendar
source resolves and passes the module's own `source_problem` freshness/coverage check. If it does
not, the axis is **dropped and the reason recorded** — a state split built on a stale or missing
calendar would be a label with nothing behind it, which this program already refused once (V2
register R6).

**Entry set and rule:** the arm's session (06–20 UTC), priced with the **parent rule** — stop
**1.0×ATR**, **no take-profit**, ≤48 bars, flat by 22:00 UTC. The geometry is *not* re-optimised
here; the derived 1.384 stop is reported as a declared robustness line with the **same** frozen
cell, never re-selected.

## The procedure, fixed here

1. **Split by time** at the midpoint of the venue's served window (`first + (last-first)/2`), not
   by trade count.
2. **On H1 only**: score every cell with `n ≥ 30` (declared minimum) and take the highest mean R.
3. **Pay for the selection**: the H1 winner must reach `selection_threshold(n_cells)` — 2.883 at 12
   cells, 3.071 at 24 — computed in the run, not quoted.
4. **If it does not clear**: **no state rule is carried to H2.** Reported as "no state rule survives
   selection in H1"; step 5 does not run. This is a declared, acceptable outcome and not a prompt to
   try another cell definition.
5. **If it does**: freeze that cell and test it on H2 as a **single hypothesis at t ≥ 1.96** — the
   selection cost was paid on H1, and H2 has not been looked at.
6. **Separately, with no selection at all** (`descriptive`, reported regardless): decompose the
   H1→H2 change in the *unfiltered* rule into **composition** and **within-state** parts.
   `mean_H2_actual` is what happened; `mean_H2_at_H1_mix = Σ_c w_H1(c) · mean_H2(c)` is what H2 would
   have averaged if its state mix had matched H1's. If the counterfactual sits near H1's mean, the
   decay is **a change in which states occurred**; near the actual H2 mean, the decay is
   **within-state** — the edge itself weakening. This is the question "is the decay regime-driven?"
   answered without picking a winner, and it is immune to the cell-search problem because no cell
   is chosen.

## Falsifiers and kill rules, fixed here

- **NO STATE RULE** — no H1 cell clears the priced threshold. The decay is not explained by a
  selectable state, and no H2 test follows.
- **KILL** — the frozen cell's H2 mean ≤ 0. The state rule is dead and is not re-cut.
- **FAIL** — frozen cell's H2 t < 1.96 at n ≥ 30.
- **PASS** — H2 t ≥ 1.96. Even then this is a *candidate*, not a validated rule: one forward
  window, one state definition, no execution costs beyond the frozen model.

## Contamination, stated first

The trigger and the exit geometry were both found on this same window, so H2 is not a clean
holdout for them — only for the **state conditioning**, which is what H1 selection is allowed to
choose. The window is eight months of one instrument in one regime era; if the decay is a genuine
regime shift, eight months is a thin basis for saying so. `docs/GOLD_FORWARD_PREREG_20260921.md`
remains the only instrument that can validate a rule.

Run and verdict: `docs/GOLD_PERSISTENCE_STATE_TEST_20260921.md`.

# PROGRAM STRUCTURE DECISION — 2026-09-19

**Question put to the architect:** *"do you think we can restructure that MIDASTOUCH
totally and then build the XAUUSD as the new MIDASTOUCH … you will decide"*

## DECISION: No. Not a total restructuring, and not under that name.

Three findings decided it. Each is verifiable in this repo, and the first is a blocker that
outranks the question itself.

---

## Finding 1 (BLOCKER): a live gold EA may still be running, and we cannot see it

`artifacts/midas_vps_hosting.json`, read today:

```json
{ "active": true,
  "set_utc": "2026-09-18T12:19:30Z",
  "evidence": "journal 12:46:27 '6898457: automated trading disabled after migration
               and enabled on virtual hosting'",
  "subscription": "6898457",
  "surface": "VPS hosts the LV live EA after operator sync; paper arms keep collecting locally",
  "clear_when": "surface returns to the local terminal (delete this file)" }
```

`clear_when` is **unmet** — the file is still present, so nothing in this repo's record says
the VPS surface was ever switched off. `docs/MIDASTOUCH_CLOSEOUT_20260919.md` states the
consequence in its own words:

> *This machine has no reach into it, so the local stop above does not stop the live arm.
> Until steps 1–3 are confirmed, treat the gold program as **live and unattended**.*

**Therefore: do not create a second gold surface.** Standing up a "new MIDASTOUCH" while an
unverified gold arm may still be trading means two EAs on one instrument, positions we
cannot attribute, and no clean P&L. That is precisely what the repo's one-instrument /
one-magic rule exists to prevent. **Close the VPS hole first — it is a two-minute operator
action and it is the actual priority.**

Local state verified today (clean, for the record): one `terminal64` (PID 15640, the Upcomers
account) and one `MetaEditor64`; **no** `midas_*` process; the `MIDAS Watchdog Autostart`
task is unregistered; both synthetic tasks are `Disabled`.

## Finding 2: gold already has its own repository, and it holds the only validated gold assets

`Desktop/Projects/MIDASTOUCH` (origin `MitemsHub/midastouch`) is a complete program:
`mql5/`, `src/`, `tests/`, `config_tester/`, `data/`, `docs/`, `artifacts/`, plus
`start_midas_watchdog.bat` and `run-paper-pipeline-task.ps1`.

The closeout records what it contains:

> *certified XAUUSD corpus, parity/tester evidence, 25 gold test suites*

and the archived evidence is genuinely strong, not marketing:

* `midas_parity_result_20260918_0544.json` — **WF certificate PASS, 151/151 keyed,
  max |dR| 0.0005R**
* 4× `midas_parity_matrix_oos_*` — **8/8 registry matrix PASS**

**This is the only validated gold machinery that exists.** A "total restructure" would throw
it away and rebuild it, to fix a failure it did not cause. Building gold here instead would
fork the gold program across two repositories — which is the exact disease
`docs/INDEX.md` was written to cure ("five documents that each read as current state and none
that said which one won").

## Finding 3: MIDASTOUCH's failure was procedural, and the name carries that history

What actually killed it, from its own records:

* it went **live on an operator instruction rather than a gate**;
* on an account whose equity was **$39.58**, where the broker's minimum lot made correct
  sizing arithmetically impossible;
* it closed its **only** real trade at **−$0.50**.

None of that is a code defect. And the substantive blocker is untouched by any restructuring:
`docs/GOLD_WFO_VERDICT_20260919.md` — the pre-registered walk-forward on gold ended
**NOT VALIDATED, t = +0.52**, with one 8-day window carrying the entire result. **There is no
validated gold edge to build on.** Restructuring the EA layer would be effort aimed at the one
part of the stack that is not the problem.

Reusing the name would also import that history into a program that has not earned it. The
repo's rule is that a program earns its identity at the gate (`docs/SYNTHETIC_GATE_V2.md`),
not by declaration.

---

## So what we will do instead

The real structural problem is not the name — it is that **the venue layer and the strategy
layer live in different repositories and are not connected.** They are different layers and
should stay separate; the fix is to make the boundary explicit and let assets cross it.

| layer | owner | contains |
|---|---|---|
| **Venue** (Upcomers rules, cost model, probes, ranking) | **this repo** | `risk/upcomers_rules.py`, `upcomers_cost_rank.py`, `venue_probe.py`, `profile_instrument.py`, the `upcomers` preset/`configs` namespaces |
| **Strategy** (gold entries, exits, EA, certified corpus, parity harness) | **`MitemsHub/midastouch`** | `MidastouchAI.mq5`, the 9 gold presets, `config_tester/`, 25 gold test suites, the certified XAUUSD corpus |
| **Methodology** (pre-registered protocol, walk-forward, verdict rule) | **this repo, portable** | `docs/GOLD_WFO_PROTOCOL.md`, `gold_walkforward.py`, `docs/SYNTHETIC_GATE_V2.md` |

**Decisions that follow:**

1. **No new EA folder, no new codename, no `MIDASTOUCH v2`.** The gold-on-Upcomers effort is
   the **Upcomers XAUUSD program**, living under the existing `upcomers` namespace. A codename
   is earned when a configuration clears the gate; inventing one now would be the fifth name
   for a thing that has no edge.
2. **Do not rewrite `MidastouchAI.mq5`.** Reuse it and its certified corpus. The gold WFO
   harness is portable to that repo and should be consumed there, not duplicated.
3. **Do not touch the closed windows.** `MIDASTOUCH_CLOSEOUT_20260919.md` parked the program
   with nothing deleted, and `GOLD_WFO_VERDICT_20260919.md` §5 closed the 2026-01-12 →
   2026-09-18 research window. Both stand.
4. **The next gold work is strategy research, not code restructuring**: re-derive gold's
   stop/target geometry from its own path statistics (the random-entry baseline came in at
   **−0.152R/trade**, so entries were being judged on a negative-expectancy geometry), then
   test entries on a **fresh window**.

**STATUS UPDATE (2026-09-19, later the same session) — the blocker is RETIRED.** The operator
reported the Deriv terminal uninstalled and account **140778269 no longer funded**, which
neutralises the VPS surface without needing positive confirmation from it: an unfunded account
cannot trade whether or not the EA is loaded. The hosting marker was archived and its live
path cleared, and `scripts/morning_status.py` confirms no gold arm. Full grounds, evidence and
the accepted residual uncertainty: **`docs/GOLD_SURFACE_RETIREMENT_20260919.md`**.

The objection in Finding 1 — *do not create a second gold surface while an unverified one may
be live* — is now satisfied, so the rest of this decision stands on its own merits.

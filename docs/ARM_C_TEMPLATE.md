# ARM C — PAPER-TERMINAL TEMPLATE (built & parked 2026-09-05)

## What exists

| component | value |
|---|---|
| Install | `%LOCALAPPDATA%\MitemshubMT5_C` (clone of B's proven install) |
| Data folder | `%APPDATA%\MetaQuotes\Terminal\71BF6B2AB5548CFBA970FA2F38007C31` |
| Magic | **7788125** (A = 7788075, B = 7788100; 7788125 verified unused) |
| Chart | `MQL5\Profiles\Charts\Default\chart01.chr` — clone of arm A's validated chart, EA `MitemshubAI` on Volatility 75 Index M15, `InpLiveExecution=false` (paper), `InpPaperEquity=50`, TP placeholder 1.8 |
| Credentials | auto-login verified: `authorized '140778269' on DerivSVG-Server-03` (the pointer lives in `config\common.ini` `Login=`/`Server=` — copying `accounts.dat` alone is NOT enough; that cost an hour on 2026-09-05) |
| Build & presets | synced by `sync-mt5.ps1` (75 files, build gate PASS; auto-discovers the folder) |
| Validation launch | 2026-09-05 11:10 UTC: v26.35 banner, FIT ROUTER TOLERATED ($4.65 min-lot risk = 9.3%/trade at $50 virtual), self-check clean, paper equity $50.00 initialized, state + telemetry written |
| **Activation rehearsal** | 2026-09-05 12:22:46 local, supervised 10-minute run: launch → `authorized '140778269'` **T+6s** → full v26.35 banner + PAPER MODE + FIT ROUTER TOLERATED ($4.59, live spread varies) **T+8s** → EA evaluated bars (first `sig`/SKIP event in telemetry) → parked at T+23min by PID-from-ExecutablePath; A/B untouched and wrote telemetry at the next M15 close. Procedure worked verbatim; time-to-operational ≈ 1 minute. |
| Current state | **SUPERSEDED 2026-09-14 — see amendment below. The 71BF reservation was moved to magic 7788126 (`chart01.chr.bak_7788125`) and stays parked; the single arm C now runs on FB9A.** |

## The standing rule (from docs/V75_COST_DILUTION_STUDY.md)

Arm C stays OFF until BOTH hold:
1. A study returns **VALIDATED-CANDIDATE** (as of 2026-09-05: zero candidates —
   cost-dilution was NO-ADOPT 5/5; the TP A/B question belongs to arms A/B).
2. The primary A/B (arm A vs arm B) has adjudicated **without contamination**
   from the candidate experiment.

A running arm C before an adoption decision trades an un-adopted config and
mints data nobody reads — parked is the correct default state.

## Activation procedure (minutes, not hours)

1. **Point the chart at the adopted config** (only step that changes per adoption):
   edit `71BF6B2AB5548CFBA970FA2F38007C31\MQL5\Profiles\Charts\Default\chart01.chr`
   (UTF-16): set the adopted `InpTpMult` / any adopted inputs. Keep
   `InpMagic=7788125`, `InpLiveExecution=false`.
2. `powershell -Command "Start-Process -FilePath 'C:\Users\USER\AppData\Local\MitemshubMT5_C\terminal64.exe'"`
   (the Bash `&` background trick hangs the shell — use Start-Process).
3. Verify within ~60s: journal line `authorized '140778269'` in
   `logs\<today>.log`; Experts log `MQL5\Logs\<today>.log` shows the
   `[v26.35]` banner + `FIT ROUTER ... TOLERATED` and `PAPER MODE`; magic
   7788125 appears in telemetry (`fit` event).
4. `python scripts/morning_status.py` must now show **3** terminals / three arms.

## 2026-09-14 amendment — arm C activated as V75MacroEngine v2.21 on FB9A chart03

The first VALIDATED-CANDIDATE machinery was applied to the macro engine itself
(the regime study + recertification protocol made it the live research
frontier), so arm C is **not** this template's parked MitemshubAI chart:

- **Where:** FB9A (`FB9A56D6…`) `Default\chart03.chr` — the chart that
  briefly ran v2.20 live-capable (magic 7500) on 2026-09-14. Re-inputted while
  the terminal was closed: `InpMagicNumber=7788125`, `InpPaperMode=true`
  (backup: `chart03.chr.bak_live7500`).
- **What:** V75MacroEngine v2.21 PAPER — virtual fills at bid/ask on a $50
  virtual book, geometry identical to live, `CTrade` never touched on the
  paper path; ledger/telemetry in the arms' formats
  (`V75MacroEngine_paper_*`), discovered by `morning_status.py` as `C_v75`.
- **Account note:** all terminals share the ONE real account 140778269;
  paper safety is EA-level. Ground truth + Algo-switch rule recorded in
  `docs/GO_LIVE_CHECKLIST.md` (account section, 2026-09-14).
- `morning_status.py` shows three arms across two terminals; C_v75 is
  telemetry-only and NOT a gate input.

## Adding arm C to the tooling (at activation)

- `scripts/morning_status.py`: extend `MAGICS` with `{"C_cand": 7788125}` (one line).
- `scripts/paper_pipeline.discover_arm_dirs()` discovers A/B by magic; the
  candidate's adjudication must be a NEW pre-registered rule (candidate vs
  arm A reference), written before its 30th trade — not an A/B rerun.

## Rehearsal learnings (2026-09-05)

- **Telemetry cadence is event-driven, not periodic**: a fresh arm writes a burst at launch (banner + first `sig` evaluation, usually a SKIP) and then only at EA events. A 10–30 min quiet window after launch is **normal** — healthy arm B showed the identical cadence (quiet 12:15→12:45 while C ran). The 2h watchdog staleness threshold stands; do not misread quiet as dead. In quiet periods the state CSV's `DAILY` row (rewritten daily) is the better liveness check.
- **MT5 config files are UTF-16** (`config/common.ini`, `logs/*.log`, chart profiles): POSIX `grep` silently reads nothing. Read them with `io.open(..., encoding="utf-16")` — this is why the `Login=` pointer appeared missing until decoded.
- Launch/kill discipline re-validated: `Start-Process` never hangs, kill only by PID resolved from `ExecutablePath -like '*MitemshubMT5_C*'`.

## Teardown (if the candidate is rejected)

Delete the data folder `71BF6B2AB5548CFBA970FA2F38007C31` and the install
`%LOCALAPPDATA%\MitemshubMT5_C`. Nothing else references magic 7788125.

## 2026-09-15 pre-registration — arm C's adjudication rule (frozen before the candidate's 30th trade)

This section freezes the rule **before any candidate config has been chosen**;
it is executed the day a study returns VALIDATED-CANDIDATE per
`OPERATING_SUMMARY.md` §3. Like every pre-registration here: it states the rule
so it can lose. Amendments are append-only and dated. Fill the blank fields at
activation; they cannot change what the rule computes.

### 0. Fill-at-activation fields (frozen at the moment arm C starts, before trade 1)

| field | value at activation |
|---|---|
| Candidate preset | `__________` (the exact adopted inputs; SHA-256 recorded) |
| Candidate engine | `__________` (engine + version; if V75MacroEngine, ledger prefix `V75MacroEngine_paper_*`) |
| Arm-A reference snapshot | byte-copy of A's ledger at activation → `artifacts/v75_replay/armA_reference_<date>.csv` |
| C start epoch | the epoch of the activation banner, recorded before the first signal is evaluated |
| C end epoch | set at trade 30 CLOSE (the adjudication moment); nothing after it is read |

**Why arm A is the reference and why pairing is BY DAY:** arm A is the
longest-running, healthiest stream on the certified geometry, and the two
engines do **not** share a signal stream (A/B's identical entry epochs came from
one shared MitemshubAI stream; the macro engine generates its own — measured
2026-09-15, `arm_b_rate_decomposition_20260915.json`), so the A/B
nearest-epoch pairing (`ab_adjudicate.py`) cannot transfer. The candidate is
instead compared against A's *concurrent* performance — the window is the
control.

### 1. Data gates (any failure → INVALID, nothing is declared)

- **G1 — count:** C has ≥30 CLOSED trades with a CLOSE row whose exit epoch ≤ C-end epoch. No substitutes, no projections.
- **G2 — coverage:** C ran ≥21 calendar days and ≥70% of the window covered by arm A's ledger in the same span (A is alive on every one of C's trading days; if A was down and C traded, that's C's day too — but if C was down, the day does not count toward the 21).
- **G3 — integrity:** P3 leg clean for both ledgers: no `WLOST` quarantine tags in either journal over C's window, zero unmatched CLOSE rows (a CLOSE without its OPEN row), zero duplicate tickets, zero ledger liveness alarms (`morning_status` canary) spanning >1 trading day.
- **G4 — contamination:** no input change on C or A over the window (journal config-line diffs vs the activation snapshot; any diff → INVALID — this is the same contamination standard the primary A/B demanded).

### 2. Statistics (computed by extension of `ab_adjudicate.py` — new script `scripts/adjudicate_arm_c.py`, never a rerun of the A/B tool)

**Daily paired series.** One observation per calendar day on which both arms closed ≥1 trade:
`d_i = meanR_C(day) − meanR_A(day)`. Primary statistic: **mean of d_i over the series, Welch t against 0** (paired-by-day replaces the un-pairable epoch pairing).

**Auxiliary (reported, not gated):** totalR_C vs totalR_A on C's window;
win rates; exit-reason mixes; C's veq_max_dd; trades/day. The hybrid-study
lesson (L1 book strangled by risk-cap vetoes at small equity) is checked
explicitly: **C's journal veto/skip counters are diffed against A's over the
window and reported** — if C's admission funnel differs materially, the
geometry confound is named in the verdict even if the primary passes.

### 3. Decision (frozen mapping — no judgment calls)

Let T = Welch t of the daily paired series, n_d = number of paired days.

| condition | verdict |
|---|---|
| n_d ≥ 15 AND T ≥ +1.0 AND mean(d_i) > 0 AND C's totalR ≥ A's totalR AND G1–G4 all clean | **VALIDATED-CANDIDATE-CONFIRMED** → update LIVE preset only through the certified chain (§3 non-negotiables); then arm C returns to park or continues as the new reference arm by amendment |
| n_d ≥ 15 AND T ≤ −1.0 AND mean(d_i) < 0 | **REJECTED** → teardown per the procedure above; the study's candidate is retired, not re-tuned |
| anything else | **INCONCLUSIVE** → C keeps collecting to n_d = 30 paired days max; if still inconclusive, **REJECTED-with-honor** — the candidate failed to distinguish itself in its fair window; teardown. INCONCLUSIVE is never read as encouraging (same discipline as TJ1). |

**Pre-declared tie-breaker:** the concurrent-window totalR comparison breaks
n_d ∈ [13,14] boundary cases toward INCONCLUSIVE, never toward a verdict
(the series is too short to trust; scarcity never manufactures confidence).

### 4. Preconditions that gate the whole template (from the standing rules)

- The primary A/B (TJ1) has adjudicated **without contamination** — arm C's data
  collected before that moment is not an input here.
- The candidate entered through the study chain (frozen protocol → certified
  fresh window → this paper test) — hand-tuned presets have no path here.
- Arm C trades at its pre-registered size floor (**$100 minimum viable,
  $150 recommended buffer** — `GO_LIVE_CHECKLIST.md` sizing truth table,
  2026-09-15): below $100 the geometry is INERT/refused and the run cannot
  even reach G1. The truth table is a precondition, never an authorization.
  **And it must be current**: the sizing numbers derive from H1 ATR(14),
  which drifts — the weekly ATR-drift monitor (`scripts/atr_drift_monitor.py`,
  `GO_LIVE_CHECKLIST.md` validity-monitor section) re-derives the table from
  live data every paper_weekly run. An **AMEND** verdict suspends the $100
  floor's validity (and with it this template's preconditions) until the
  append-only table amendment lands; WATCH is a review flag, not a blocker.
  **And it must be survivable (amendment 2026-09-15):** the table answers
  static admission; the dynamic strangulation floor — `s·(k+5)` with k the
  certified worst loss streak (6) — requires **≈$226 at the p95 geometry**
  ($246 tail, $308 engineering) for *unstrangled* operation (the L1 study's
  589-veto death mode). $100 remains the precondition to trade at all; below
  ≈$226 an activated arm C inherits the strangulation regime. The monitor's
  `strangulation_floor` block re-derives this weekly; a floor above the actual
  account equity is an amendment-grade finding.
- `morning_status.py` MAGICS carries `C_cand`/`C_v75` and its health canary
  covers C's ledger for the whole window (a dead-arm day is a G2/G3 event,
  not a footnote).

### 5. What this rule deliberately does NOT do

- It does **not** compare C to arm B (B is a TP-duel arm, not a reference).
- It does **not** use the A/B nearest-epoch pairing (engines don't share a
  stream — the mechanism was measured, not assumed).
- It does **not** declare on total R alone (a lucky streak is not an edge;
  the t-requirement exists so a candidate must beat the reference *consistently*,
  not once loudly).
- It does **not** permit re-adjudication after a REJECTED verdict. A retired
  candidate re-enters only through a new study and a new pre-registration.
- It does **not** adjudicate a strangulated window (G5, amendment below — a
  sample collected under risk-cap strangulation is not evidence of anything).

---

## AMENDMENT 2026-09-15 (append-only) — G5: the strangulation-floor gate moves
## from activation-only to adjudication-time

**The hole this closes.** §4 requires the account at the strangulation floor
(≈$226 certified / $246 tail / $308 engineering, `s·(k+5)`, k = 6) **at
activation**. Nothing previously re-verified it at adjudication. The floor
exists precisely because a loss streak can drive equity below the cap-admission
line *during* collection — so a candidate could start compliant, eat its own
worst certified streak mid-window, collect its tail trades strangled (entries
refused or thinned whenever the 20% cap bit), and still pass G1–G4 on that
sample. A strangled window is not evidence of edge or of failure — it is not
evidence of anything. G5 makes that sample INVALID.

**G5 — strangulation floor (read as part of §1's gate list; any failure →
INVALID, nothing is declared):**

- **Equity condition:** the daily minimum of arm C's equity over the candidate
  window, taken from its own ledger EQ rows (the V75 ledger format carries EQ
  rows), must be ≥ the monitor's `floor_certified` at every point in the window.
  The window **minimum**, not the end value — an end-of-window check is exactly
  the hole being closed (equity can dip below the floor mid-window and recover).
- **Floor source, single point of truth:** `floor_certified` from the latest
  `strangulation_floor` block in `artifacts/v75_replay/atr_drift_monitor.json`
  (re-derived weekly from live H1 ATR(14); k and s are **never** re-derived by
  the adjudicator). `floor_tail_k7` and `floor_engineering_s28` remain advisory
  inputs to the floor-amendment path, not gate thresholds.
- **Monitor staleness:** if the `strangulation_floor` block is missing or its
  reading is older than 8 days at adjudication (weekly cadence + one day
  slack), G5 fails as a **data gate** — same class as a dead ledger, not a
  discretionary call.
- **Who computes it:** `scripts/adjudicate_arm_c.py` (the tool §2 commits to)
  implements G5 as a data gate alongside G1–G4, code-checked not prose-checked;
  its INVALID output names the failing gate explicitly.

**Two failure sub-cases, different paths (frozen so the day-of response is
procedure):**

- **(a) Floor rose above equity** (ATR drift worsened the geometry while equity
  held): the G5 failure cites the monitor reading; the path is the append-only
  floor amendment in `GO_LIVE_CHECKLIST.md`, then a fresh collection window at
  the amended floor. The strangled window is never adjudicated.
- **(b) Equity fell below a stable floor** (the streak death mode — the exact
  L1 failure): the window is a strangulation sample by definition → INVALID.
  This is a **window invalidation, not a candidate verdict**: consistent with
  §1's own rule ("any failure → INVALID, nothing is declared"), no REJECTED is
  recorded and the no-re-adjudication ban is not triggered; the candidate may
  re-collect only at compliant equity under this same frozen template.

**Consequential edit to §3's mapping (from this amendment forward):** the
CONFIRMED condition reads "G1–**G5** all clean" where it previously read
"G1–G4 all clean". REJECTED and INCONCLUSIVE mappings are unchanged — a
verdict reached on a window that fails G5 is not a verdict at all.

**Why INVALID rather than a veto inside the statistics:** strangulation biases
the daily-paired series itself (C's admitted trades on cap-bound days are a
thinned, adversarially-selected subsample), so no statistic computed on it is
interpretable — the confound is the sample, not the arithmetic. This is the
same reasoning that makes G4's contamination gate INVALID-only.

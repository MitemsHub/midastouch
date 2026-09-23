# ENTRY STRUCTURE AUDIT — 2026-09-22 (the day the market rallied and the arm did not)

**What this document is.** An audit of one live day, counted bar by bar, answering the
operator's question — *"the market is going up, what is the EA doing?"* — with the only
currency this program accepts: counts from the engine of record and the arm's own ledger.
It is **not** a study (n = 1 day proves nothing about any rule family) and **not** a
change record (no protective rule, gate, threshold or risk number moved). What moved in
response is recorded separately: `docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md` and build
`MIDAS1.28`.

**Where its numbers come from.** The repo's venue corpus stops at 2026-09-18 20:45Z, so
today's bars were read **from the terminal** (`copy_rates_from_pos`, read-only) and
shifted to UTC at the arm's own recorded offset (+120 min), then run through the
**engine of record's own code** — `P._python_data` for the indicator build,
`M.h4_series` for the venue-grid H4, `midas_decision_attribution.walk()` for the census.
No arithmetic was re-implemented for this audit.

---

## 1. The day, bar by bar

84 evaluated M15 bars (00:00Z → 20:45Z). The session gate is **server** 06:00–20:00 =
**UTC 04:00–18:00** at today's offset, which holds **56** of them.

| class (all 84 / in-session 56) | count | share of in-session |
|---|---|---|
| no trigger at all | 69 / **46** | **82.1 %** |
| `trig_macro_anti` — the armed mode's class | 8 / **8** | 14.3 % |
| `trig_macro_agree` — ORIGINAL's class | 3 / 1 | 1.8 % |
| `trig_macro_divergent` | 4 / 1 | 1.8 % |

Every one of the 15 trigger bars (side, regime `mac`, class):

| sig close | src | trig | mac | class | in-session |
|---|---|---|---|---|---|
| 00:15Z | rsi | −1 | 0 | divergent | no |
| 00:30Z | bb | +1 | 0 | divergent | no |
| 02:30Z | bb | −1 | 0 | divergent | no |
| 05:45Z | rsi | +1 | 0 | divergent | **yes** |
| 07:45Z | rsi | +1 | −1 | **anti** | **yes** |
| 08:00Z | rsi | +1 | −1 | **anti** | **yes** |
| 08:15Z | rsi | +1 | −1 | **anti** | **yes** |
| 08:30Z | rsi | +1 | −1 | **anti** | **yes** |
| 08:45Z | bb | −1 | −1 | agree (ORIGINAL) | **yes** |
| 10:15Z | bb | +1 | −1 | **anti** | **yes** |
| 12:45Z | bb | +1 | −1 | **anti** | **yes** |
| 13:30Z | bb | +1 | −1 | **anti** | **yes** |
| 14:00Z | bb | +1 | −1 | **anti** | **yes** |
| 18:45Z | bb | +1 | +1 | agree (ORIGINAL) | no (gate ends 18:00Z) |
| 20:00Z | bb | +1 | +1 | agree (ORIGINAL) | no |

In-session RSI peaked at **69.6** (one tick under the 70 threshold); the 71.2 reading is
00:00Z, outside the window. The day's thrust ran roughly 17:45Z → 19:30Z server
19:45 → 21:30 — **after** the gate closed at 18:00Z.

## 2. Reconciliation with the arm's own ledger

The same day, told by the ledger's restart-persistent census (`NOFILLSUM` rows, UTC day
20718), in three stretches separated by the day's reloads:

| stretch (build / mode in charge) | census |
|---|---|
| pre-12:28Z, mode=0 (v1.22/1.23) | `signal=45 no-trigger=40 mismatch=5` |
| 12:28Z → 20:42Z reloads, mode=1 (v1.23→1.27) | `signal=28 no-trigger=24 mismatch=4` |
| after 20:42Z, mode=1, v1.28 (13-field floor, fresh counters) | `signal=6 no_trigger=5 mismatch=1` |

Summed: **79 evaluated, 69 no-trigger, 10 mismatch** — matching the engine's own
classification of the same bars (69 no-trigger all-day; 8 anti + 1 agree + 1 divergent
in-session, with the 18:45Z/20:00Z agree bars and the 02:30Z divergent bar outside the
gate). The `mismatch` counter is the anti class plus the in-session divergent bar, exactly
as the mode classifies them. The protective counters, all three stretches:
`session=0 friday=0 spread=0 riskcap=0 breaker=0 news=0` — **no safety measure refused
anything today.** Every refusal was the entry rule.

## 3. The counterfactual: what the rule would have *done* (measured, not argued)

`run_mode` over today's live bars, armed geometry, UTC 04–18 window, $25,000 basis:

| configuration | fills | outcome |
|---|---|---|
| **REVERSE_DIRECTION** (armed, mode 1) | **2** — 07:45Z short, 10:15Z short | **both SL, −1.726R and −1.532R = −3.258R** |
| **ORIGINAL** (mode 0 — what the chart ran until 12:28Z) | **1** — 08:45Z short | **SL, −1.659R** |

Two facts this table states and no adjectives improve:

1. **The complaint's premise inverts on today's data.** The "lazy" rule was the day's only
   *profitable* agent: the real book is **+0.104R** (one fill, closed externally),
   while the active rule — the one the arm actually trades — would have lost **−3.258R**
   taking both signals it is built to take. Activity was what cost money today, at
   2×ATR stop distances into a regime that kept rising.
2. **Part of the day's quiet was configuration lag, not the entry rule.** The chart ran
   mode=0 until the 12:28:47Z watchdog splice (recorded at CHANGELOG line ~973). Under
   mode=0, the four morning anti bars (07:45–08:30Z) were refused by the *mirror* mode —
   the census's `mismatch=5` stretch. The preset fixed this mid-day; the reconciliation
   matters because "the arm missed the morning" conflates a setup error with the rule.

## 4. The structural answer (the part no parameter change fixes)

The armed mode is a **counter-regime extreme fade**: it buys oversold into a bullish
regime and sells overbought into a bearish one. A long trigger requires `mac == trigger`
(`mac=+1, trig=+1`) — precisely the *agree* class the mode **refuses by construction**.
In a sustained rally, the mode is structurally incapable of joining; today it fired eight
shorts into a market that rallied ~60 points off the 07:00Z low, and the one bar that
would have been "the trade you wanted" (18:45Z, agree) is barred by the mode's sign —
then by the session gate, which closed at 18:00Z. This is why "shed off whatever makes it
slow" has a counted answer: the slowness *is* the rule, at 82.1 % no-trigger rarity, and
removing the refusal would have put the mirror of today's loss on the book.

## 5. What was done about it (the honest direction)

The strongest measured number in this program — the Asian-range sweep continuation on its
held-out UTC 07–18 window (152 trades, +0.1955R, pf 1.499, t +2.21, mirror −0.1584R,
textbook reversal −0.1425R) — is now being **recorded forward with no order path at all**
(`MIDAS1.28` `SWEEPSHADOW` rows; `scripts/midas_sweep_shadow.py` resolves them through the
same `run_mode`). If activity is ever justified by evidence rather than by impatience, it
will be this family, judged by the rule fixed in the pre-registration **before** any row
existed: N ≥ 60 resolved outcomes, t ≥ 2.4, ≥ 0.30 fills/day, mean positive, both
direction checks still negative — or the verdict names which test failed.

## 6. What this audit does NOT claim

- **Nothing about the rule family.** One day, two hypothetical stops: that is noise with
  a sign, not evidence in either direction. The walk-forward verdict for the armed
  configuration remains **FAILED / NOT VALIDATED**, and today changes that not at all.
- **Not that gates should move.** The census's protective counters read zero in every
  stretch; widening or removing them was refuted by counts (CHANGELOG, 2026-09-22 entry,
  line ~960).
- **Not that the external close was the EA's.** The one real fill was closed by a mobile
  order (`docs/LIVE_EXIT_AUDIT_20260922.md`); its +0.104R is on the account and the
  counterfactual table above assumes nothing from it.

Artifacts: this audit's census is reproducible from the terminal bars via
`P._python_data` + `mda.walk` (the commands are in the session record); the ledger is
`MIDASTOUCH_paper_XAUUSD_U25.csv` (terminal `D0E8209F…`), the journal
`MQL5\Logs\20260922.log` (UTF-16), and the parity certificate of record
`artifacts/midas_parity_result_20260922_2134.json`.

# MIDASTOUCH presets — what each file is for

**The rule: exactly ONE of these files is ever attached to a chart on the funded
account.** Everything else is either a reference pin for the monitoring tooling or a
staged experiment that has not been run. If you are looking for "which preset do I
load", the answer is the first row and only the first row.

| file | role | live orders |
|---|---|---|
| `MidastouchAI_upcomers_gold.set` | **THE trading preset** — $25,000 Upcomers evaluation, magic 7825001, arm tag U25, all four venue rules pinned | **no** (arming is a frozen-gate event; no signal has passed the gate) |
| `MidastouchAI_M1_gold.set` | reference pin the watchdog and `morning_status` read as the canonical baseline (`REPO_PRESET`) | no |
| `MidastouchAI_LV_gold.set` | base of the P6 TP-1.5R comparison; the LV arm's own historical record | no |
| `MidastouchAI_LV_TP15_M15_gold.set` | **staged**, not run: the P6 variant queued behind the 2026-10-01 reading | no |
| `MidastouchAI_LV_TP15_M5_gold.set` | **staged**, not run: same reading, M5 entry | no |
| `MidastouchAI_M1m_gold.set`, `M1o`, `M1s`, `M1t` | historical mode-sweep arms (modes 2/5/6 and the re-pinned ORIGINAL). **Retained only because the monitoring test suite pins them** (`test_midas_p6_build`, `test_midas_golive_grammar`, `test_midas_watchdog` seed charts for `M1o`/`M1t`). They are not trading presets and no chart should carry them. | no |

## Why the arm presets were not all deleted

They look like clutter and they are not, in three specific ways:

1. **The monitoring tooling names them.** `scripts/midas_watchdog.py` holds
   `REPO_PRESET = MidastouchAI_M1_gold.set` and resolves any arm as
   `MidastouchAI_<tag>_gold.set`; `scripts/morning_status.py` pins the same baseline and
   does byte-exact chart-vs-preset identity checks against it; `midas_verdict.py` and
   `deploy_portfolio.py` use `preset_for_tag`. Deleting those two breaks the tools that
   watch the account.
2. **The P6 pair is staged work, not dead weight.** `LV_TP15_M15` and `LV_TP15_M5` are
   the TP-1.5R variants *queued behind the 2026-10-01 reading* — deleting them would
   delete a planned experiment rather than tidy up after a finished one.
3. **Retiring the four mode-sweep arms is a test change, not a file deletion.**
   2026-09-20: they were deleted, measured, and restored the same day. `preset_for_tag`
   tolerates a missing file by design (*"Missing file -> the caller observes without pin
   enforcement"*), so the *tooling* survives the deletion — but three test files pin those
   arms by name (they seed `M1o`/`M1t` charts and iterate the arm list), so deleting the
   files left the suite red. The files stay until those tests are updated to the
   single-account reality; that update is the follow-up, not a delete.

## Two things every file here now guarantees

- **`InpLiveExecution=false` on all of them**, checked by
  `scripts/gold_preset_upcomers.py --check` (which also refuses a preset naming an input
  the EA does not have, and refuses duplicate keys). The three Deriv-era files that still
  armed live execution were neutralised on 2026-09-20, with the original value kept as a
  comment.
- **Sized for the real account.** `InpPaperEquity` was `50.0` — the old $50 synthetic arm.
  On a $25,000 evaluation that understates every lot by ~500×, so the trading preset pins
  the true size.

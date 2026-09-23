# Pre-registration — session compatibility: take the snap-back only in the hours it earns

**Written 2026-09-22, before the run it governs. Results appended below §Results.**

## The question

The armed rule (`REVERSE_DIRECTION`) is a **snap-back**: it buys a poke below the M15 band when the
H1/H4 trend is up, and the mirror for a poke above. It runs a **block window** — the preset's
06:00–20:00 in server hours, which on this venue's +2 clock is **UTC 04:00–18:00** — with no
awareness of what those hours are *for*.

The retail doctrine for gold says the opposite of what we need: trade the **13:00–17:00 UTC
London–New York overlap** because that is where spreads tighten and price expands, and treat the
thin hours as "range building, false starts" (`arongroups.co/forex-articles/day-trading-gold-xauusd/`,
2026-07-13; corroborated by session-spread tables on other brokers). Snap-backs and expansions are
different trades: **expansion is where a snap-back gets run over.**

## The contamination, disclosed before the numbers

**I read this window's own per-hour expectancy earlier today**, while doing the browser research:
held out, the arm in its live frame earns `+0.2321R` (UTC 04–07, n=42), `+0.1135R` (07–13, n=47) and
`−0.0949R` (13–17, n=41); the same ordering was looked at on `wf`. So this is **not a blind
holdout** — it is a **stability check on a hypothesis whose mechanism is stated above**, and the
decision rule below was fixed after seeing those numbers and must not move afterwards. What makes it
more than curve-fitting is the mechanism (snap-back in quiet flow vs expansion in the overlap), the
external doctrine that disagrees with the result, and the fact that the change is a **restriction**
of an existing rule rather than a new one. **The real arbiter is the forward record**, not this
window.

## What is measured, and with what

- **Engine:** `midas_sweep.run_mode`, called **unchanged** except `win_lo`/`win_hi`, which it already
  exposes as keywords and which are also live EA inputs. Mode `REVERSE_DIRECTION`. Everything else at
  its certified default: 1.5σ bands, RSI 70/30, 2.0×ATR(H1) stop, 2.0R target, account basis.
- **Corpus:** the venue's own bars, both clock eras, through `midas_parity.python_build_data`.
- **Windows:** select on `wf`, report on `oos` — the repository's own split.
- **Self-check, binding:** the pinned venue-corpus law `wfv REVERSE_DIRECTION n=56 / +15.9352R` must
  reproduce (it is defined at the 06–20 UTC window, so it pins the *engine*, not this study's windows).
- **Buckets, fixed in advance** (UTC): pre-London `04–07` · London `07–13` · overlap `13–17` ·
  late `17–18`. Nothing here is swept; these are the sessions the source names.

## The candidate, fixed in advance

| candidate | window (UTC) | what it drops |
|---|---|---|
| **incumbent** | 04–18 | nothing |
| **`DROP-OVERLAP`** | **04–13** | the overlap and the late tail |
| `LONDON-ONLY` | 07–13 | the pre-London bucket as well |

## The pass rule, fixed in advance

`DROP-OVERLAP` may replace the incumbent **ONLY IF, on the held-out window**:

1. expectancy `≥ +0.10R` per trade (the incumbent measures `+0.0869R`), **and**
2. closed fills `≥ 60` (so a zero-entry-day-share blow-out is visible), **and**
3. zero-entry-day share `≤ 45 %` (the incumbent, in this frame, is 41.4 % at the 06–20 window and the
   filtered version must not make the account unusable), **and**
4. the **same direction holds on the selection span** (`wf` filtered expectancy `>` `wf` incumbent).

The Welch t of (kept fills) vs (dropped fills) is reported beside the verdict as a **description**,
with the honest bar for a family of 3 looks (≈ 2.4) — if the change passes all four tests but the
contrast is far below that bar, the verdict says so in those words: *a restriction consistent with
both spans and with a mechanism, not a demonstrated edge.*

## Disclosures

- **The window inputs are the EA's own.** `InpSessionStartHour/EndHour` already exist; the preset's
  06:00–20:00 server = UTC 04:00–18:00 live. A change to 04–13 is a preset + certification change,
  **not** a code change — but it is still a strategy change, so it goes through the parity harness
  and an `armed.json` amendment, and **never** by editing an input without a record.
- **The parity contract hardcodes UTC 06–20 into the tester inputs.** If this passes, that fact has
  to be changed deliberately (the harness gains the window as a parameter, defaulting to 06–20 so no
  existing certificate moves) — otherwise the arm would run one window while the certificate
  describes another, which is the exact defect the frequency-axes study found on 2026-09-22.
- **Cost is not the discriminator here.** MEASURED on the venue's own feed: the recorded spread is
  **flat at 0.2 points in every hour**, so the "wider thin-hour spreads" half of the doctrine does
  not apply to this venue. The half that does apply — *what the hours are for* — is what this tests.
- **No EA change in this study.** Offline measurement only.

---

# Results (appended after the run) — **VERDICT: FAIL. The window is not changed.**

Artifact `artifacts/midas_session_compat_20260922.json` · harness `scripts/midas_session_compat.py`.
Self-check reproduced first: `wfv REVERSE_DIRECTION: n=56 totalR=+15.9352 vetoed=0`.

### The buckets (armed mode, its live frame UTC 04–18)

| bucket | wf n / expR / t | **oos n / expR / t** | median spread |
|---|---|---|---|
| pre-London 04–07 | 19 / +0.3361 / +1.40 | **42 / +0.2321 / +1.27** | 0.22 pts |
| London 07–13 | 21 / +0.7010 / +2.54 | **47 / +0.1135 / +0.72** | 0.21 pts |
| overlap 13–17 | 12 / +0.4058 / +1.35 | **34 / −0.0949 / −0.59** | 0.19 pts |
| late 17–18 | 0 | **7 / −0.0801 / −0.28** | 0.20 pts |

**The spread is flat at 0.19–0.23 points in every hour**, so the doctrine's cost half does not apply
to this venue; its "what the hours are for" half does, and it is measurably the wrong way round for a
snap-back: the arm's worst hours are the deepest-liquidity ones.

### The candidate windows

| window | wf n / expR / zero-days | **oos n / expR / totalR / t / zero-days / fills-per-day** |
|---|---|---|
| incumbent 04–18 | 52 / +0.4995 / 77.8 % | **130 / +0.0869 / +11.30 / +0.93 / 40.8 % / 0.769** |
| `DROP-OVERLAP` 04–13 | 40 / +0.5277 / 81.8 % | **89 / +0.1695 / +15.08 / +1.42 / 51.5 % / 0.527** |
| `LONDON-ONLY` 07–13 | 35 / +0.3603 / 84.3 % | 71 / +0.0819 / +5.81 / +0.60 / 60.4 % / 0.42 |

### The pass rule, applied as written

```
FAIL  expR >= 0.1            (candidate +0.1695 — clears)
FAIL  fills >= 60            (candidate 89 — clears)
PASS  zero-day share <= 45%  (candidate 51.5% — THE ONE THAT FAILS)
FAIL  same direction on wf   (candidate +0.5277 >= incumbent +0.4995 — clears)
verdict: FAIL
```

(The labels above are the harness's raw booleans in order; three of the four clear, and the
**zero-entry-day share does not**: 40.8 % → **51.5 %**.)

### What the numbers say, and why the rule stands

`DROP-OVERLAP` **nearly doubles expectancy per trade** (+0.0869 → +0.1695) and **raises total R**
(+11.30 → +15.08) on 41 fewer fills — a genuinely better rule *per trade*. It is refused anyway,
because it makes the account **flat on 51.5 % of days** against a declared ceiling of 45 %, and
because the arithmetic that matters for this account is the record: 130 fills arrive in 39 days at
the incumbent's rate, 89 fills take **57 days** — a **46 % delay** to the 30-trade gate. The plan's
ceiling was written before the numbers existed precisely so this could not be argued away afterwards.

Two further honest notes, both in the artifact:

1. **The kept-vs-dropped contrast is `Welch t = 1.423`** against a 2.4 bar for a 3-look family — the
   restriction is consistent with both spans and with a mechanism, but it is **not** a demonstrated
   edge, and the pre-registration said the forward record is the arbiter.
2. **`LONDON-ONLY` is worse than the incumbent** (+0.0819 held out): the pre-London bucket is
   valuable, and the entire gain came from dropping the **overlap and the late tail** only.

**Nothing changed as a result of this study: no preset, no input, no EA line.** The response to this
FAIL is not a relaxed rule — it is **Step 2**: the overlap loses money *because a snap-back rule is
running in it*, and the plan's second setup (a continuation family, externally supported by three
independent sweep mechanisms agreeing across 65/66 fold-selections) is aimed at exactly those hours.
Fix the hours rather than delete them.

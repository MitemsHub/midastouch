# Pre-registration: the late-session short cell

**Declared:** 2026-09-21, before `scripts/gold_prereg_late_short.py` was run.
**Harness:** `scripts/gold_prereg_late_short.py` · **Artifact:** `artifacts/gold_prereg_late_short.json`

---

## 1. Where the rule came from, stated as the contamination it is

`docs/GOLD_TRIGGER_EDGE_AND_PATH_GOVERNOR_20260921.md` §2 found a cell — short entries with
H1 and H4 both down inside the 17–22 UTC window — at +0.1329R/trade over 469 observations
and named 190 trades as the sample it would need. That run used the whole venue window, so
**this rule was selected on the data it is now tested against**. Every number below is
therefore contaminated, and the declaration says so in its first line rather than in a
footnote. The clean tests are forward, and §3 fixes what they are.

One correction that matters for the required sample: the 469 observations were **five exit
geometries over the same signal bars**, not 469 independent trades. The single declared
geometry here (stop 1.0 × ATR, target 3.0R, the certified family's own pair) yields **120
trades** on the same window. The declared requirement stays at 190 — the number that was
published before this ran — because lowering a declared sample after measuring is the
failure this file exists to prevent.

## 2. The declared rule, in full

Take the frozen engine's own signals, restricted to:

* **shorts only**, entered when the H1 trend (EMA 8 > 21 > 50) **and** the H4 trend
  (close vs EMA 20) are both down — the engine's own `h1_ok_short` / `h4_ok_short`, not a
  re-derivation;
* entry hour **17–21 UTC** (the engine's flat-by-22:00 rule makes 22+ untradeable);
* exit geometry **stop 1.0 × ATR, target 3.0R** — unchanged from the certified family;
* the engine's own ATR band (0.20–0.95 trailing percentiles), one position at a time, and
  the venue's measured cost model (spread 1.073 bps, $10/lot round trip).

Longs are suppressed **at the signal** (all-False long flags into `simulate`), not by
deleting trades from a finished list, because a deleted trade frees its slot for the next
signal and would report a sequence the EA could not have traded.

## 3. Pass and kill conditions, declared in advance

* **Pass:** at the declared sample, mean net R > 0 **and** trade-level t ≥ 1.5.
* **Kill:** at the declared sample, mean net R ≤ 0 → the rule is dead.
* **Before the sample:** INSUFFICIENT EVIDENCE. A positive intermediate mean is not a
  result, and cannot be upgraded by re-running on a friendlier window.
* **What "clean" means here:** forward trades after 2026-09-21T13:25Z. At the observed
  ~0.65 trades/day, 190 trades is roughly ten months. No split of the discovery window is
  a holdout.

## 4. The first measured result (contaminated, reported because it was declared first)

| slice | window | n | mean net R | t | total |
|---|---|---|---|---|---|
| pooled | 2026-01-12 .. 09-21 | **120** | **+0.0963** | **+0.70** | +11.56R |
| first half | 01-12 .. 05-19 | 65 | +0.1592 | +0.79 | +10.35R |
| second half | 05-19 .. 09-21 | 55 | +0.0220 | +0.12 | +1.21R |
| under the EA's governor | full | 101 | +0.0911 | +0.61 | +9.20R |

**Verdict: INSUFFICIENT EVIDENCE.** The declared sample is not met (120 of 190), the pooled
t-statistic is +0.70 against the declared +1.5, and **four fifths of the total sits in the
first half** — the effect decays to +0.022R in the second. The pooled +0.0963R is also well
below the +0.1329R the discovery run reported, which is what the 5-geometry overlap looks
like when it is removed.

**One finding worth keeping.** Under the governor the declared filter produces **0 shield
breaches and 3 daily breaches** (worst day −3.20R = −$801 against the $750 cap), where the
certified grid produced 5 shield and 5 daily. The worst-day overshoot is 51 dollars; the
filter removes the shield problem almost entirely and leaves the daily one. That is a real
signal about *where* the breaches live, and it points at the daily cap being the one that
cannot be filtered away by regime selection.

## 5. What would make this a result

Only the forward record, and `docs/GOLD_FORWARD_PREREG_20260921.md` is where its arithmetic
lives. If the forward sample lands at 190 trades with t ≥ 1.5 and the venue rules intact,
the rule has earned a place in the certified family. If it lands at ≤ 0R/trade, it is dead
by §3 and should be recorded as a result, not re-specified.

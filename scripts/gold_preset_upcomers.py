#!/usr/bin/env python3
"""Build and validate the Upcomers-era gold preset for MIDASTOUCH.

WHY THIS EXISTS. The presets in `mql5/MIDASTOUCH/` were written for the Deriv era, and
one key in them is not a comment — it is a number the EA sizes with:

    InpPaperEquity=50.0

That was the $50 synthetic arm's virtual equity. On a $25,000 Upcomers evaluation the
paper mirror would size **every trade as if the account held $50**, so its lots, its R
and its drawdowns would be unrepresentative of the account by a factor of ~500 — and
the paper ledger is the only forward record this program has. A preset is not a
document; it is the configuration under which the forward evidence is collected, which
is why this is generated and validated rather than hand-edited.

WHAT IT REFUSES. Three failure modes that are silent in MT5 and expensive here:

1. **A key the EA does not have.** MT5 ignores unknown keys in a `.set` without a word,
   so a preset can look like it pins a rule while the rule is not set at all. Every key
   is checked against the EA's `input` declarations.
2. **`InpLiveExecution=true` with no arming record.** Live execution is a frozen-gate
   event, never an input edit. The builder refuses to emit it, and the checker refuses
   to pass it.
3. **An unpinned input.** The repo's convention is that a preset is the *complete* key
   set, so that what is on disk is what the EA is doing. Any input the file omits is
   reported — an omission is how a default changes under you.

    python scripts/gold_preset_upcomers.py                # check + show the plan
    python scripts/gold_preset_upcomers.py --write        # write the preset
    python scripts/gold_preset_upcomers.py --check        # validate existing presets
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
PRESET_DIR = ROOT / "mql5" / "MIDASTOUCH"
SOURCE = PRESET_DIR / "MidastouchAI_M1_gold.set"
TARGET = PRESET_DIR / "MidastouchAI_upcomers_gold.set"

#: The account this preset is for. Matches ThunderboltClassicRules' default size.
ACCOUNT_SIZE = 25_000.0

#: RISK PER TRADE, and it is a MEASURED number rather than the EA's 1.00 default.
#:
#: The sizing scan in `artifacts/gold_prereg_no_target.json` (`sizing_scan_post_hoc`: the
#: prop governor inside, the venue's own bars, the 3% UTC-day line at $750) is where this
#: comes from. 0.25% is the only size it scanned that breaches the venue's daily rule on NO
#: day: worst day -$466.60 against the $750 line, i.e. $283.40 of headroom per day, 0 of 30
#: days beyond. Every larger size breached:
#:
#:     1.00%  ->  worst day -$804.84, 13 days beyond the line
#:     0.75%  ->  worst day -$803.46,  7 days beyond
#:     0.50%  ->  worst day -$805.91, 10 days beyond
#:     0.25%  ->  worst day -$466.60,  0 days beyond   <- this file
#:
#: The mechanism is worth keeping in view, because it is not "smaller is always safer":
#: cutting the size makes the 6% trailing shield stop vetoing, so MORE entries are kept
#: (498 at 0.25% against 67 at 1.00%) and the worst day is smaller anyway. The daily rule is
#: a statement about SIZE, not about entry timing.
#:
#: What this number is NOT: it is the worst day of the no-target policy, not of the exact
#: geometry this arm runs (stop 2.0xATR/TP 2.0R), so it is the closest measurement that
#: exists rather than a measurement of the live exit. At 0.25% the $62.50 budget also sits
#: above the venue's min-lot floor (~$33 for a stop this wide), so the EA can size within it
#: instead of the floor forcing an overshoot.
RISK_PERCENT = "0.25"

#: STRATEGY MODE, and it is the mode the certification machinery was actually run on.
#:
#: The arm was armed on InpMode=0 (ORIGINAL), and the arming record flagged the mismatch
#: itself: every parity window and the walk-forward gate certify InpMode=1
#: (REVERSE_DIRECTION), and the 2026-09-21 12:18 parity PASS is a REVERSE_DIRECTION pass.
#: Running mode 0 meant no parity run and no gate verdict spoke about the live
#: configuration at all — in either direction.
#:
#: WHAT THIS CHANGE IS NOT: a claim that mode 1 is the better mode. Both are NO-SHIP on
#: the pre-registered gate (pf < 1.30 AND expectancy < +0.15R, both modes), and the venue
#: sweep (artifacts/midas_sweep_20260921.json) has ORIGINAL ahead in three of the four
#: windows and mode 1 ahead in the one window a mode could not have been selected on:
#:
#:   window             ORIGINAL                     REVERSE_DIRECTION
#:   is1  (in-sample)    142 tr  +0.1668R  pf 1.390   186 tr  +0.0402R  pf 1.076
#:   is2  (in-sample)    209 tr  +0.1166R  pf 1.223   259 tr  +0.0297R  pf 1.003
#:   wf                  115 tr  +0.0953R  pf 1.128   151 tr  +0.0098R  pf 0.930
#:   oos  (out-of-sample) 94 tr  +0.0697R  pf 1.141   108 tr  +0.0759R  pf 1.158
#:
#: So the case is configuration integrity — a certified NAME that matches the certified
#: CONFIGURATION — plus the only out-of-sample window, where mode 1 wins on expectancy,
#: on total (+8.199R against +6.555R) and on max drawdown (5.41R against 6.87R), with 15%
#: more fills. Mode 0's in-sample lead is the lead of a mode that was chosen there; it is
#: not evidence. Neither number is large, and neither mode is validated.
#:
#: THE MECHANISM, MEASURED ON THIS ARM'S OWN LEDGER (not inferred from the sweep): of the 31
#: bars the EA evaluated from 2026-09-21 20:00 UTC on, every bar that carried a trigger at
#: all (3 of them, each mac=-1/trig=+1) was refused by ORIGINAL's macro requirement and is
#: an entry under mode 1. Mode 1 is not a superset — it refuses the agreement case
#: (mac == trig) that ORIGINAL takes — so it trades a different set, not simply more.
#:
#: The M1 FORWARD-COLLECTION CONTROL STAYS ORIGINAL: protocol §2/§10 Amendment 2 pins it
#: to the plainest variant, and its own header records the 2026-09-17 incident where an
#: unregistered drift put mode=2 on that arm. Mode is therefore an ARM-level key pinned in
#: tests/test_midas_golive_grammar.py (ARM_MODE), not part of the family-wide literal.
MODE = "1"

#: THE TRIGGER THRESHOLD (Bollinger deviation), amended 2026-09-22 because the arm was flat.
#:
#: WHY IT MOVED. The arm has placed ZERO trades, and its own refusal census says why: over the
#: UTC day's 25 evaluated bars, 21 carried no trigger at all ('notr') and the 4 that did were
#: refused by the mode; every protective counter — session, friday, spread, riskcap, breaker,
#: news — was 0. So no safety measure had refused anything, and the fill rate was decided by how
#: often a trigger fires. That is a threshold, not a gate: this changes the trigger's
#: sensitivity and touches no protective rule, no size and no mode.
#:
#: THE MEASUREMENT (pre-registered 2026-09-22 in docs/FREQUENCY_AXES_PREREG_20260922.md BEFORE
#: it ran; artifact artifacts/midas_frequency_axes_20260922.json). Engine: midas_sweep.run_mode
#: UNCHANGED, every keyword at its certified default. Corpus: the VENUE'S OWN BARS
#: (data/forex/xauusd/*_upcomers.csv) shifted into true UTC — NOT the retired 50,000-bar
#: research series, whose bytes were deleted 2026-09-21 and whose table is what seeded (and
#: then failed to confirm) this hypothesis. Mode: REVERSE_DIRECTION, the armed mode.
#: Harness self-check (binding): it must reproduce the pinned wfv law n=53 / +14.2563R first.
#:
#:   HELD OUT — oos 2026-04-01 -> 2026-09-16, 168 days, window = what the arm actually runs
#:   k      n     /day   zero-entry days   expR     pf      win     ddR    netR
#:   2.0  111    0.66        50.3%       -0.003   0.981   0.414    7.6    -0.29   <- was
#:   1.5  130    0.77        40.8%       +0.087   1.201   0.462    6.5   +11.30   <- now
#:   1.0  140    0.83        37.3%       -0.009   0.966   0.414    8.9    -1.33
#:   SELECT — wf 2025-09-15 -> 2026-03-31: 2.0 = +0.426R / pf 2.377, and 1.5 = +0.500R / pf 2.798
#:   (same ordering, different span), against 1.0 = +0.394R / pf 2.192.
#:
#: So 1.5 is better than the incumbent on BOTH spans, on the entry rate AND on quality, and it
#: is the cell that survived the pre-registered rule (raise entries/day, lose <=0.10R of
#: expectancy, lose <=2R of drawdown, on the held-out window): +17% entries, expectancy from
#: -0.003R to +0.087R, drawdown 7.6R -> 6.5R, days with no entry 50.3% -> 40.8%.
#:
#: THE PRIOR THIS FALSIFIED, AND WHY IT IS RECORDED RATHER THAN QUIETLY DROPPED. The Sep-18
#: sweep (artifacts/midas_variant_research_20260918.json, the retired series) showed smaller k
#: better at EVERY RSI band, monotonically, and pointed at k=1.0. On the venue's own bars in
#: the held-out window k=1.0 is the WORST of the three: negative expectancy in every window
#: tested, pf < 0.97. The mechanism is visible in the code: the trigger is `bb_touch`, ELSE
#: the RSI branch (`elif t_rsi >= 70 / <= 30`), so narrowing the band does not ADD to the RSI
#: trigger, it DISPLACES it — at k=1.0 the band touches often enough to swallow the RSI
#: signals that carry the edge, and the trade set becomes band-touch-only mean reversion.
#: 1.5 is the point where both branches still contribute. A monotone in-sample sweep could not
#: have shown this; only a held-out window on the market the EA trades did.
#:
#: WHAT THIS IS NOT. Not a validation and not a claim of profitability: at +0.087R over 130
#: trades the t-statistic is ~0.9, so the held-out expectancy is statistically indistinguishable
#: from zero, and the venue's own gate (pf>=1.30, expectancy>=+0.15R) is still FAILED. It is an
#: ordering between three thresholds that held on two spans and one market, measured under a
#: pre-registered rule; the account remains an operator override on an unvalidated strategy.
#: A PARITY PASS AT 1.5 WAS RUN AND PASSED, 2026-09-22: `--window tickcov --live-stance` on real
#: ticks, artifact artifacts/midas_parity_result_20260922_1654.json — the pass of record, because
#: it ran the build the arm runs (v1.25, source 011e0ab9) — python 9 trades / +0.2699R
#: against the EA's 9 / +0.271R, keys agreeing, max|dR| 0.0004. The certificate is about this
#: configuration and not a no-op: the FIRST pass at 1.5 ran a trade set that MOVED from 2.0's
#: (two entries present at 2.0 are gone, two new ones appear), and the trade set has not moved
#: since — which is the measurement that the two builds after it (v1.24, v1.25) are telemetry and
#: fill-row integrity respectively. It certifies engine equivalence, not profitability: the
#: venue's gate is still FAILED and the operator override still stands.
#: THAT SAME ARTIFACT ALSO CARRIES THE ACCOUNT LAYER, which no earlier pass could: a SECOND pass
#: in the arm's OWN stance (`--live-stance`: risk 0.25 %, the prop governor on, live execution,
#: all read from MidastouchAI_upcomers_gold_LIVE.set) reported SIZING PASS on 7 closed fills —
#: each sized the way the declared rule sizes it at the equity it actually had, 5 of them floored
#: to the venue's min lot — with the governor leg VACUOUS (no modelled rule bound: the largest
#: day drawdown was 0.318 % of the 3 % cap). The BAR pass pins those inputs OFF, so before this
#: the sizing and the governor were certified nowhere.
#: (The earlier 14:02Z, 14:26Z and 14:47Z passes, artifacts ..._1502.json, ..._1526.json and
#: ..._1547.json, certify the SAME contract with the same nine trades on the PREVIOUS builds
#: (v1.23 and v1.24); all are kept, and none is counted twice.)
BB_DEV = "1.5"
#: The SPREAD COST CAP (InpSpreadCapPctStop), measured 2026-09-23 BEFORE the change was
#: made — the veto is `spread > cap% x stop`, so the cap in R is cap% / 100. The certified
#: engine of record's own entry costs on the 130 held-out fills (oos, venue corpus, UTC
#: 04-18): mean 0.0080R, p90 0.0141R, p99 0.0184R, max 0.0193R — so the OLD 1.5% cap
#: (0.015R) sat INSIDE the certified trade set's own cost distribution and would have
#: refused 7 of the 130 certified fills (+1.133R of certified expectancy) on cost alone.
#: The live venue regime that exposed this (SPREADHOUR, 2026-09-23): $0.47-0.50 spread on
#: a ~$25 stop = 0.0188-0.0200R, above 1.5% and below 2.0%. 2.5% is the smallest tenth
#: step that (a) refuses 0 of the 130 certified fills — the cap admits the exact strategy
#: that was validated instead of carving it, (b) covers the live regime with margin, and
#: (c) stays a quarter of the engine's own G7 ceiling (mean spread cost > 0.10R fails the
#: self-check) — 0.025R <= 0.0333R. Trigger, stop, target, session, mode and sizing are
#: UNCHANGED: the trade set is identical; only the cost gate's floor moved, and it moved
#: DOWN in effective terms (from vetoing part of the certified set to vetoing none of it).
#: Recorded as amendment 10 in artifacts/live/armed.json on the same commit.
SPREAD_CAP_PCT = "2.5"
#: Distinct from the Deriv-era 7801001 so a ledger cannot mix two eras' fills.
MAGIC = 7825001
ARM_TAG = "U25"

#: Pinned to the venue's published rules; these are the EA's own defaults, written out
#: explicitly so a future change of default cannot silently alter a live account's risk.
PROP_KEYS = {
    "InpPropGuard": "true",
    "InpPropAccountSize": f"{ACCOUNT_SIZE:.1f}",
    "InpPropTargetPct": "5.0",
    "InpPropMaxDdPct": "6.0",
    "InpPropBestDayPct": "20.0",
    "InpPropPeakOverride": "0.0",
}

ARMING_RECORD = ROOT / "artifacts" / "live" / "armed.json"

_INPUT_RE = re.compile(r"^\s*input\s+(?!group)([A-Za-z_][\w]*)\s+([A-Za-z_][\w]*)\s*=\s*([^;]+);")


def ea_inputs(text: str) -> dict[str, str]:
    """Every `input` declared by the EA, name -> default literal.

    The regex skips `input group "..."` declarations deliberately: a group is a label,
    not a parameter, and counting one as a parameter would make every preset look
    incomplete.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _INPUT_RE.match(line)
        if m:
            out[m.group(2)] = m.group(3).strip()
    return out


def read_set(path: Path) -> tuple[list[str], dict[str, str], list[str]]:
    """(comment lines, key -> value, duplicate keys).

    Duplicates are reported rather than silently collapsed, because the neutraliser can
    MANUFACTURE them when it is wrong: a first version rewrote a comment that merely
    documented the live key, and then rewrote its own inserted note on a second run. The
    result was real duplicate keys that had never existed, and this check is what caught
    it. MT5's behaviour on a repeated key is unspecified, so a file carrying one cannot
    be read as a statement of what it configures.
    """
    comments: list[str] = []
    keys: dict[str, str] = {}
    dupes: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            comments.append(raw.rstrip())
            continue
        if "=" not in line:
            raise ValueError(f"{path.name}: not a key=value line: {line!r}")
        k, v = line.split("=", 1)
        k = k.strip()
        if k in keys:
            dupes.append(k)
        keys[k] = v.strip()
    return comments, keys, dupes


def classify(keys: dict[str, str], declared: dict[str, str], *,
             armed: bool, where: str = "preset",
             dupes: tuple[str, ...] | list[str] = ()) -> tuple[list[str], list[str]]:
    """Split the problems into (errors, warnings).

    The split is not cosmetic. An ERROR is a preset that is WRONG NOW — it pins a key
    the EA does not have, or it enables live execution without a gate record. A WARNING
    is a preset written before an input existed: a genuine historical artifact whose
    remedy is a new preset, not an edit to the old one. Failing the check on those would
    mean the checker's first act was to demand history be rewritten.
    """
    errs: list[str] = []
    warns: list[str] = []
    for k in sorted(set(dupes)):
        errs.append(f"{where}: key {k!r} is declared more than once — MT5's behaviour on "
                    f"a repeated key is unspecified, so the file does not state what it "
                    f"configures")
    for k in keys:
        if k not in declared:
            errs.append(f"{where}: key {k!r} is not an input of the EA — MT5 would "
                        f"ignore it silently, so it pins nothing")
    live = str(keys.get("InpLiveExecution", "false")).lower()
    if live in ("true", "1") and not armed:
        errs.append(f"{where}: InpLiveExecution is TRUE with no arming record at "
                    f"{ARMING_RECORD.relative_to(ROOT)} — live execution is a "
                    f"frozen-gate event, never a preset edit")
    missing = sorted(set(declared) - set(keys))
    if missing:
        warns.append(f"{where}: {len(missing)} input(s) unpinned — the EA runs its code "
                     f"defaults for these: {', '.join(missing)}")
    return errs, warns


def validate(keys: dict[str, str], declared: dict[str, str], *,
             armed: bool, where: str = "preset") -> list[str]:
    """All findings, errors first. Empty means the preset is sound for use."""
    errs, warns = classify(keys, declared, armed=armed, where=where)
    return errs + warns


def build(comments: list[str], source_keys: dict[str, str], declared: dict[str, str],
          symbol: str, *, live: bool = False) -> str:
    """The Upcomers preset as text: source keys, overwritten and completed.

    `live=True` emits the LIVE variant — byte-identical inputs except `InpLiveExecution=true`,
    which is the EA's only order-sending switch. The caller refuses that without an arming
    record, so this function is the translation step and not the authorisation.
    """
    header = [
        "; MIDASTOUCH — UPCOMERS gold preset (paper arm for the $25,000 evaluation)",
        "; Generated by scripts/gold_preset_upcomers.py — edit the generator, not this.",
        ";",
        f"; Account:  ${ACCOUNT_SIZE:,.0f} Upcomers Thunderbolt Classic (MT5, netting).",
        f"; Symbol:   {symbol} — chosen on the CHART; a .set cannot pin a symbol, so",
        ";           this line is documentation and the checker verifies it separately.",
        f"; Magic:    {MAGIC} (distinct from the Deriv-era 7801001 so no ledger can mix",
        ";           the two eras' fills) · arm tag " + ARM_TAG + ".",
        ";",
        "; WHAT CHANGED FROM THE DERIV-ERA PRESETS, AND WHY: InpPaperEquity was 50.0 —",
        "; the old $50 synthetic arm — so the paper mirror sized every trade as if the",
        "; account held $50. On this account that understates every lot by ~500x, which",
        "; would make the only forward record we have unrepresentative of the account it",
        "; is supposed to represent.",
        ";",
        f"; STRATEGY MODE IS {MODE} (REVERSE_DIRECTION) — THE ONE THE CERTIFICATION RAN ON",
        "; (2026-09-22). The arm was armed on InpMode=0 (ORIGINAL), which no parity pass and",
        "; no gate verdict describes: the walk-forward gate certifies mode 1 and FAILED it",
        "; too. So this aligns the NAME to the certified CONFIGURATION; it is not a claim that",
        "; mode 1 is the better mode. Venue bars (artifacts/midas_sweep_20260921.json):",
        ";   ORIGINAL           is1 142tr +0.1668R | is2 209tr +0.1166R | wf 115tr +0.0953R",
        ";   REVERSE_DIRECTION  is1 186tr +0.0402R | is2 259tr +0.0297R | wf 151tr +0.0098R",
        ";   oos (the one window not used to pick a mode): ORIGINAL 94tr +0.0697R pf 1.141",
        ";   maxDD 6.87R, REVERSE_DIRECTION 108tr +0.0759R pf 1.158 maxDD 5.41R, +8.199R vs",
        ";   +6.555R total and 15% more fills. Both modes are NO-SHIP on the gate.",
        "; MEASURED on this arm's own ledger: all 3 of the 31 evaluated bars that carried a",
        "; trigger (each mac=-1/trig=+1) were refused by ORIGINAL and are entries under mode",
        "; 1. Mode 1 also refuses the agreement case, so it trades a different set, not more.",
        "; The change is an arming-record amendment (artifacts/live/armed.json), not an edit.",
        ";",
        f"; RISK PER TRADE IS {RISK_PERCENT}%, AND IT IS A MEASURED NUMBER (2026-09-21).",
        "; The EA's own default is 1.00%, which the sizing scan in",
        "; artifacts/gold_prereg_no_target.json measures as breaching the venue's 3% daily line",
        "; on 13 of 30 days (worst day -$804.84 against $750). 0.25% is the only scanned size",
        "; that breaches on NO day: worst day -$466.60, i.e. $283.40 of headroom per day. The",
        "; governor enforces the line either way; this is the size that keeps it from being",
        "; reached. See scripts/gold_preset_upcomers.py (RISK_PERCENT) for the full table and",
        "; for what it does not measure.",
        ";",
        "; THE PROP GOVERNOR IS PINNED HERE. The EA now enforces all four venue rules",
        "; before an entry: the 3% UTC-day cap, the 6% trailing Dynamic Risk Shield, the",
        "; 5% profit target and the 20% Best Day ceiling on one day's gain. Their",
        "; arithmetic mirrors src/midas_prop/risk/upcomers_rules.py.",
        ";",
        "; THE NEWS GATE IS OFF HERE, AND THAT IS A DECISION, NOT AN OVERSIGHT.",
        "; InpUseNewsFilter=false means the playbook's standing policy (+/-15 minutes around",
        "; top-tier USD releases) is NOT enforced on this arm. Turning it ON is a real",
        "; configuration change with two consequences worth stating: the EA then refreshes",
        "; the venue's own calendar and refuses entries whenever that source is missing,",
        "; stale, uncovered, truncated or EMPTY (an empty calendar is 'cannot see the news',",
        "; never 'no news'), and this arm would no longer be running the configuration the",
        "; walk-forward certified. The gate is entry-only either way — it never blocks an",
        "; exit.",
        ";",
        "; THE STATE STAMP IS ON HERE (v1.19e), AND IT IS NOT A TRADING RULE.",
        "; InpRecordStateLabel=true makes the EA append the entry's own state to the OPEN row",
        "; (sig_ct, hour_utc, vol_ratio, news, off_min). Nothing reads it back as a gate: it",
        "; exists so the pre-registered forward cell",
        "; (docs/GOLD_PREREG_FORWARD_CELL_20260921.md) can label THIS arm's rows from the",
        "; record the arm made, instead of rebuilding them from a history file that may not",
        "; reach the newest row. It also keeps the calendar file fresh even with the gate",
        "; OFF, because a stale source would otherwise stamp `na` forever (na is not `out`).",
    ]
    header += (
        [
            "; ARMED — THIS ARM PLACES REAL ORDERS ON THE FUNDED ACCOUNT.",
            "; InpLiveExecution=true, and the ONLY thing that makes that legitimate is the",
            "; arming record artifacts/live/armed.json: read it before touching this file.",
            "; It states what was authorised, and — if the walk-forward gate did not pass —",
            "; that this is an OPERATOR OVERRIDE rather than a validation.",
            "; The prop governor (daily / trailing-shield / Best Day / target) gates ENTRIES",
            "; and is unchanged by this header; it was already enforced on the paper arm.",
        ] if live else
        [
            "; PAPER ONLY. InpLiveExecution=false is HARD. Arming is a frozen-gate event and",
            "; is expressed as an arming record, never as an input edit — so this preset",
            "; places no orders, and the generator refuses to emit a live-enabling file",
            "; without that record (see --live).",
        ]
    )
    header += [
        ";",
        "; The original Deriv-era header is kept below as the record it is:",
    ]
    body = header + [f";   {c.lstrip('; ')}" for c in comments]
    keys = dict(source_keys)
    keys.update({
        "InpMagic": str(MAGIC),
        "InpArmTag": ARM_TAG,
        "InpPaperEquity": f"{ACCOUNT_SIZE:.1f}",
        "InpRiskPercent": RISK_PERCENT,     # see RISK_PERCENT: the measured survivable size
        "InpMode": MODE,                    # see MODE: the parity/gate-certified mode
        "InpBBDev": BB_DEV,                 # see BB_DEV: the measured trigger threshold
        "InpSpreadCapPctStop": SPREAD_CAP_PCT,   # see SPREAD_CAP_PCT: the measured cost gate
        "InpLiveExecution": "true" if live else "false",
        # v1.19e: the state stamp, ON for this arm. Its default is false so the frozen
        # Deriv-era baseline preset and every certified parity run stay byte-identical;
        # this arm is the one whose forward record has to be labelable.
        "InpRecordStateLabel": "true",
        **PROP_KEYS,
    })
    for k in declared:
        keys.setdefault(k, declared[k])
    # MEASURED 2026-09-21, in the EA's own journal, after the state stamp started reading the
    # calendar file: `NewsSourceProblem()` printed `calendar file missing
    # ("MIDASTOUCH_news_calendar.csv")` — with the quotes IN the filename. A `.set` (and the
    # `[StartUp] ExpertParameters` route that consumes it) hands a string input its value
    # LITERALLY, so a default copied out of the declaration (`= "MIDASTOUCH_news_calendar.csv"`)
    # arrives as a filename that cannot exist: `FileIsExist()` is false and every write fails.
    # The consequence is not cosmetic — with `InpUseNewsFilter=true` the gate is fail-closed, so
    # the arm would have stood down forever and reported a missing calendar nobody could find.
    # The tester route (`midas_parity.build_inputs`) always wrote the bare value; now both do.
    keys = {k: (v[1:-1] if len(v) > 1 and v.startswith('"') and v.endswith('"') else v)
            for k, v in keys.items()}
    ordered = {k: keys[k] for k in declared if k in keys}
    ordered.update({k: v for k, v in keys.items() if k not in declared})
    body.append("")
    body += [f"{k}={v}" for k, v in ordered.items()]
    return "\n".join(body) + "\n"


#: Written verbatim above the key it changes. The original value is kept as a comment
#: rather than deleted: the question "what was this file doing in September?" must stay
#: answerable from the file itself.
NEUTRAL_NOTE = (
    "; 2026-09-20 NEUTRALISED: this key was TRUE (the Deriv-era LV arm). The Deriv account\n"
    "; is closed, MT5 now points at a funded $25,000 Upcomers evaluation, and no gold\n"
    "; signal has passed the walk-forward gate — so a preset that can send real orders is\n"
    "; a loaded switch, not a record. What happened under the live setting lives in the\n"
    "; ledgers and the commit history, not in this line. Restoring it is a frozen-gate\n"
    "; event, not an edit."
)


def neutralise(path: Path) -> str:
    """Set `InpLiveExecution=false` on a preset that still arms live trading.

    WHY THIS IS A REPO OPERATION AND NOT A HAND EDIT. Three presets in this directory
    were written to send REAL orders on an account that no longer exists. Loading one on
    the connected Upcomers account would arm live execution with no gate record, so the
    fix belongs in version control where it can be reviewed, re-run and tested — and the
    original value has to survive as a comment, because silently rewriting a live
    instruction file is how the next person loses the ability to tell what it used to do.
    """
    # LINE-WISE AND COMMENT-AWARE, and both of those are lessons from doing it wrong.
    #
    # The first version searched the text for the literal `InpLiveExecution=true` and
    # replaced every hit. Two things went wrong, and neither was visible in the result:
    #
    #   1. These headers DOCUMENT the key — `;   InpLiveExecution=true` appears as prose
    #      describing what the live arm does. A text replace rewrote that comment, which
    #      injected a real key line into the middle of a comment block.
    #   2. The inserted note itself contains the string it was searching for, so the next
    #      run rewrote the note. Running it twice nested the notes and produced real
    #      duplicate keys that had never existed — and the duplicate-key checker then
    #      reported a defect that was entirely my own.
    #
    # So: skip comments, parse `key=value` from real lines only, and write the note once.
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    note_written = any(ln.strip().startswith(";") and "NEUTRALISED" in ln for ln in lines)
    out: list[str] = []
    changed = 0
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith(";") and "=" in s:
            k, v = s.split("=", 1)
            token = v.strip().split()[0].lower() if v.strip() else ""
            if k.strip() == "InpLiveExecution" and token in ("true", "1"):
                if not note_written:
                    out += [NEUTRAL_NOTE, ";   was: InpLiveExecution=true"]
                    note_written = True
                out.append("InpLiveExecution=false")
                changed += 1
                continue
        out.append(ln)
    if not changed:
        return f"{path.name}: already inert"
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return f"{path.name}: InpLiveExecution true -> false"


def collapse_duplicate_keys(path: Path) -> str:
    """Drop repeated keys whose values agree; REFUSE when they disagree.

    Agreement is compared on the value TOKEN, not the whole tail: these files carry an
    inline note after some values (`InpLiveExecution=false (the sole execution
    switch...)`), and comparing whole tails would call two identical settings different.
    When the tokens disagree, one of the two lines is a lie about the configuration and
    there is no way to tell which — so the right move is to stop, not to pick one.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    first: dict[str, str] = {}
    keep: list[str] = []
    dropped: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(";") or "=" not in s:
            keep.append(ln)
            continue
        k, v = s.split("=", 1)
        k, token = k.strip(), v.strip().split()[0] if v.strip() else ""
        if k not in first:
            first[k] = token
            keep.append(ln)
            continue
        if first[k] != token:
            raise ValueError(
                f"{path.name}: {k} declared twice with DIFFERENT values "
                f"({first[k]!r} and {token!r}) — the file cannot be resolved by guessing")
        dropped.append(k)
    if not dropped:
        return f"{path.name}: no duplicate keys"
    keep.append(f"; 2026-09-20: removed {len(dropped)} repeated key line(s) whose values "
                f"agreed: {', '.join(sorted(set(dropped)))}. The first occurrence is kept.")
    path.write_text("\n".join(keep), encoding="utf-8", newline="\n")
    return (f"{path.name}: collapsed {len(dropped)} duplicate line(s) "
            f"({', '.join(sorted(set(dropped))) })")


def symbol_present(symbol: str) -> tuple[bool, str]:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        return False, f"MetaTrader5 not installed ({exc})"
    if not mt5.initialize():
        return False, "terminal not reachable"
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False, f"{symbol} NOT OFFERED by this broker"
        return True, (f"{symbol} present: digits {info.digits}, point {info.point}, "
                      f"min lot {info.volume_min:g}")
    finally:
        mt5.shutdown()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the preset")
    ap.add_argument("--live", action="store_true",
                    help="emit the LIVE variant instead: same inputs, InpLiveExecution=true, "
                         "written to <TARGET stem>_LIVE.set. REFUSES without an arming "
                         "record — the record is the authorisation and this flag only "
                         "translates it into the one input that places orders.")
    ap.add_argument("--check", action="store_true",
                    help="validate the presets on disk and exit non-zero on any problem")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--neutralise-live", action="store_true",
                    help="set InpLiveExecution=false on every preset still arming real "
                         "orders, recording the old value in a comment")
    ap.add_argument("--offline", action="store_true",
                    # `%APPDATA%` must be escaped: argparse %-formats help strings, and an
                    # unescaped % raises "badly formed help string" at add_argument time —
                    # which made this whole CLI unrunnable while its --help looked fine
                    # (measured 2026-09-20: the documented `--write` workflow could not run
                    # at all). The tests never called main(), which is how it survived.
                    help="skip the broker symbol check (the MT5 bridge finds a running "
                         "terminal regardless of %%APPDATA%%, so --offline is the only way "
                         "to test the refusal path)")
    a = ap.parse_args(argv)

    declared = ea_inputs(EA.read_text(encoding="utf-8", errors="replace"))
    if not declared:
        print(f"REFUSING: no `input` declarations parsed from {EA.name} — the parser or "
              f"the file is wrong, and a preset built against nothing is worse than none.")
        return 3
    print(f"EA declares {len(declared)} inputs; prop governor present: "
          f"{sorted(k for k in declared if k.startswith('InpProp'))}")

    if a.neutralise_live:
        changed = 0
        for p in sorted(PRESET_DIR.glob("*.set")):
            for fn in (neutralise, collapse_duplicate_keys):
                try:
                    line = fn(p)
                except ValueError as exc:
                    print(f"  REFUSED {exc}")
                    return 2
                print(f"  {line}")
                changed += "->" in line or "collapsed" in line
        print(f"\n{changed} preset(s) changed")
        if not changed:
            return 0
        a.check = True   # fall through to the check so the result is verified, not assumed

    if a.check:
        errs: list[str] = []
        warns: list[str] = []
        presets = sorted(PRESET_DIR.glob("*.set"))
        armed = ARMING_RECORD.is_file()
        for p in presets:
            try:
                _c, keys, dupes = read_set(p)
            except ValueError as exc:
                errs.append(str(exc))
                continue
            e, w = classify(keys, declared, armed=armed, where=p.name, dupes=dupes)
            errs += e
            warns += w
        for pr in errs:
            print(f"  ERROR   {pr}")
        for pr in warns:
            print(f"  warning {pr}")
        print(f"\nchecked {len(presets)} presets: {len(errs)} error(s), "
              f"{len(warns)} warning(s)")
        return 1 if errs else 0

    if not a.offline:
        ok, detail = symbol_present(a.symbol)
        print(f"  symbol check: {detail}")
        if not ok:
            print("REFUSING: the intended symbol is not tradable here, so a preset "
                  "naming it would be a plan that cannot execute.")
            return 3

    # THE LIVE VARIANT IS GATED ON THE RECORD, HERE AND NOT IN PROSE. `--live` writes the
    # same inputs with `InpLiveExecution=true`; what makes that legitimate is an arming
    # record on disk (a gate pass, or an operator override whose record says so). Nothing
    # else in this repo may flip that input, which is what keeps "arming is an arming-record
    # event, never an input edit" a mechanism rather than a policy.
    armed = ARMING_RECORD.is_file()
    live = bool(a.live)
    target = TARGET if not live else TARGET.with_name(TARGET.stem + "_LIVE.set")
    if live and not armed:
        print(f"REFUSING: --live needs an arming record at "
              f"{ARMING_RECORD.relative_to(ROOT)}. Live execution is authorised by that "
              f"file and by nothing else — no flag, no input edit, no operator memory.")
        return 3

    comments, source_keys, source_dupes = read_set(SOURCE)
    if source_dupes:
        print(f"REFUSING: the source preset repeats {sorted(set(source_dupes))} — it does "
              f"not state its own configuration, so it cannot be the base of another.")
        return 3
    text = build(comments, source_keys, declared, a.symbol, live=live)
    new_keys = dict(re.findall(r"^([A-Za-z_]\w*)=(.*)$", text, re.M))
    problems = validate(new_keys, declared, armed=armed, where=target.name)
    if problems:
        for pr in problems:
            print(f"  PROBLEM {pr}")
        print("REFUSING to write a preset that fails validation.")
        return 1

    print(f"  keys: {len(new_keys)} of {len(declared)} declared inputs pinned; "
          f"live execution {'TRUE — REAL ORDERS' if live else 'false'}; "
          f"arming record {'present' if ARMING_RECORD.is_file() else 'ABSENT'}")
    if not a.write:
        print(f"\ndry run. Re-run with --write to create {target.relative_to(ROOT)}")
        return 0
    target.write_text(text, encoding="utf-8", newline="\r\n")
    print(f"\nwrote {target.relative_to(ROOT)} ({len(text)} bytes, CRLF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

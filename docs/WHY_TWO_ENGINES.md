# WHY TWO ENGINES — why this program is half MQL5 and half python, on purpose

*A question worth answering once, properly, because it comes back every time a session
feels slow: "why are we maintaining two implementations of the same strategy?"*

The short answer: **because the two halves have opposite failure modes, and the
architecture is built so neither can hide behind the other.** The long answer follows,
and it is not aesthetic preference — each property below was paid for by a measured
incident.

## 1. MQL5 is the only thing that can reach the venue

Order placement, server-side SL/TP, position management, indicator handles computed on
the venue's own bars, the `OnTick`/`OnTimer` lifecycle, the Strategy Tester and its
optimiser, attachment to a live chart — none of that exists from python. Python has no
order path to MetaTrader 5. To get one you would insert a *bridge process* between your
money and your engine, and this program has already paid for that class of intermediate:

- A **certification run stopped the live terminal with a position open**
  (`docs/LIVE_EXIT_AUDIT_20260922.md`, §5 — the 14:01:40Z and 14:25:29Z passes). The
  position survived only because SL/TP live at the venue and the EA re-adopts state on
  re-init. That was one program touching another program's terminal **on the same
  machine**. A bridge architecture makes that class of incident permanent.
- The **file-vs-chart lesson** of 2026-09-22: a deployed binary is not a running expert.
  It took a gate that reads the chart's own `ERA` row (`live_readiness`, the build legs)
  to close it — and that gate exists *because* the execution side is a process nobody's
  python can see into.

The fewer processes between the decision and the order, the better. This design has
**one**: the EA.

## 2. Python is where the dishonest work is cheap — so the dishonest work must not be done in the execution language

Every claim this program lives on is a python one-liner family:

- anchored walk-forward and its frozen gate (`docs/GOLD_WFO_PROTOCOL.md`),
- deflated Sharpe, PBO/CSCV, purged CV (`.claude/skills/quant-validation`),
- block bootstrap, permutation against a random-entry null,
- minimum-detectable-effect arithmetic — "1,931 trades ≈ 7 years at this frequency"
  (`docs/DECISION_ENGINE_AUDIT_20260922.md`),
- the pre-registration discipline itself: a rule written after the numbers exist is a
  description of the past, and only a language with cheap statistics makes writing the
  rule *first* the path of least resistance.

These are ten lines of numpy and several hundred lines of fragile MQL5. MQL5's optimiser
will hand you a beautiful equity curve and will never tell you it was the 7,708th trial
you ran. So:

> **the language that can compute a p-value is deliberately not the language that can
> place an order, and the language that can place an order has no statistics in it.**

That asymmetry is the entire safety property: **the research side cannot arm anything,
and the execution side cannot rationalise anything.** A single program that could do both
would be able to justify itself — which is precisely the failure mode this architecture
exists to refuse. ("We edited the input and it trades better" is not evidence; the
arming record and the frozen gate are, and neither speaks MQL5 nor lives in the EA.)

## 3. The parity contract makes them one system

Every configuration that trades is certified by running **both** engines over the same
bars and demanding trade-for-trade agreement — count, open time, close time, side, and R
within tolerance (`scripts/midas_parity.py`, keyed v2; today's certificate of record:
`artifacts/midas_parity_result_20260922_2134.json`, 9 vs 9 trades, `max|dR| 0.0004`).

The python leg is not a copy of the EA; it is the **oracle** that proves the EA implements
the certified rule and *nothing else*. This is why the repository's hard rule reads
"change both sides in the same commit or the parity comparison is meaningless" — and why
every EA version banner since v1.19 ends with the same sentence: display/record only, no
decision reads it, certified parity ledgers stay byte-identical. When v1.28 added the
`SWEEPSHADOW` recorder, the proof it changed nothing that decides was exactly this: the
same nine trades, `max|dR| 0.0004`, 0 over tolerance.

With one implementation you can detect a change in **output**, but never a change in
**behaviour**. Two implementations that must agree on every trade are the only way to
say "nothing else changed".

## 4. What "just use one language" would actually cost

- **You lose the statistics.** They do not survive translation into MQL5, and the
  walk-forward gate cannot move to the execution side without taking the arming decision
  with it.
- **You lose the oracle.** One implementation = output-diffing only = the v1.26→v1.27
  class of incident (a binary one version behind, everything green) becomes undetectable.
- **You still need MQL5.** The venue does not speak python. So "one language" always
  means "delete python and move the research layer into the execution language" — a
  strict downgrade, not a simplification.

## 5. The honest cost of the design

The asymmetry is paid for in operational machinery, and the bills are real:

- deploys need a compile (0 errors / 0 warnings), a copy, a hash check, a hidden
  relaunch with the attach config, and a gate that reads the chart's own `ERA` row
  (`scripts/compile_midas.py`, `live_readiness` build legs — the second leg was born
  2026-09-22, after the first deploy proved the first leg insufficient);
- every EA change is two changes (the `.mq5` and the engine), pinned together
  (`tests/test_midas_v128_record.py`, `tests/test_sweep_shadow.py`);
- the census, the STATE/SPREADHOUR/SWEEPSHADOW rows, and `morning_status` exist because
  the EA is the only witness to its own behaviour — so it is made to *write* its
  evidence, in keyed rows, and python reads it.

That machinery is expensive **because** of the incidents in §1. The alternative — one
process that both trades and justifies itself — is cheap right up until the day it is
wrong, and then it is wrong with money attached.

*The one-paragraph version:* **MQL5 because only it can reach the venue; python because
only it can refuse to lie; parity because two honest witnesses that agree beat one
confident one.**

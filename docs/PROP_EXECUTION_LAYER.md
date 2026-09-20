# PROP EXECUTION LAYER — 2026-09-19

**What this is.** The layer that turns the venue's rules into lot sizes, refuses
trades that would breach a limit, and holds the switch that keeps the whole thing
inert until a configuration has cleared the walk-forward gate.

**What it is not.** It is not a strategy. There is no signal in it, and it will
not trade on its own even if you arm it — `ARMED` changes what is *permitted*, not
what is *attempted*. The entry logic is still the thing that does not exist,
because the gold walk-forward has not produced a configuration that clears its
own gate.

| file | role |
|---|---|
| `src/synthetic_trader/risk/upcomers_rules.py` | the rules and costs as arithmetic (pre-existing; one bug fixed here) |
| `src/synthetic_trader/execution/prop_execution.py` | **new** — sizing, legality, arming |
| `scripts/verify_sizing_live.py` | **new** — measures the broker's own basis and reports what a trade would be |
| `tests/test_prop_execution.py` | **new** — 51 pins |

---

## 1. Sizing: a budget is not a size until the broker agrees

`size_position()` turns a rule-derived risk budget into a lot size, and it is
built around three facts from this program's own history.

**The dollar basis is measured, not read.** `trade_tick_value` and
`contract_size` disagreed by **10×** for XAUUSD — the spec implied $10 per $1.00
move per lot where the broker's own calculator says **$100**. So
`ContractSpec.basis` records where the number came from, and **`size_position`
refuses to size a live order on anything but a measurement**. The live run
confirms the disagreement is still there and still caught:

```
measured basis  $100.0000 per 1.0 price unit per 1.0 lot (order_calc_profit)
spec fields     imply $10.0000 -> DISAGREES 10.00x
```

**The minimum lot is a veto, not a floor to round up to.** MIDASTOUCH went live on
a **$39.58** account where 0.01 lot risked **17× the whole budget**. Sizing now
returns an explicit refusal naming the factor, rather than a smaller-but-wrong
number:

> minimum lot 0.01 risks $9.89 against a $0.59 budget (16.8x over). This is
> arithmetically impossible to trade correctly — it is the condition MIDASTOUCH
> went live on and lost its only trade to.

**Rounding is always DOWN.** Flooring uses a tick count rather than `//` so
`0.3` does not become `0.29`; rounding *up* would breach the budget that was just
computed, which is the one thing a budget may not do.

`safety_fraction` defaults to **0.5**, not 1.0, and that is a risk decision rather
than a convenience: at 1.0 a single loss consumes the entire 3% daily allowance,
so one loss ends the day and two end the evaluation.

---

## 2. Two bugs this layer found

It was built to enforce rules, and building it exposed two places where the rules
were being enforced wrong.

### 2.1 `risk_budget_usd` ignored the account's actual equity

The function took `equity` and `balance` as arguments and **never used them**. It
derived the daily allowance from `account_size` — the nominal size — regardless of
what the account was actually worth.

That is the MIDASTOUCH condition in arithmetic: on a $39.58 account it would have
reported a **$750** daily allowance and permitted a lot size ~17× too large, and
every downstream guard would have agreed, because they all read the same wrong
number.

Fixed to derive the allowance from `0.03 × min(account_size, max(equity, balance))`.
The `min` is the conservative reading of an unknown midnight reference in **both**
directions: fallen accounts give a tight proxy, risen accounts give one that
understates the allowance rather than overstating it. Pinned by
`test_budget_uses_the_reference_equity_not_the_nominal_account_size`.

### 2.2 Best Day was modelled as a deadlock

The first implementation blocked any trade whose day would breach the 20% cap.
Read literally, the cap on day one is `$0.00` — any profit at all is 100% of total
profit — so **the system could never place its first trade**. A rule that forbids
starting is not a constraint.

Corrected: the rule binds as a **day-level profit cap**, not a per-trade
forbiddance. Blocking happens once today's *realised* profit has reached today's
cap; before any profit exists there is no breach to deepen. The day-one
consequence is stated plainly rather than hidden, and it is a real property of the
venue's rule:

> Best Day: nothing banked on other days, so today's cap is $0.00 — any profit
> today is 100% of total profit, so the first profitable close ends the day. The
> 5% target needs >= 5 profitable days.

`best_day_mode="advise"` reports without blocking, for a strategy that owns its
own day target.

---

## 3. The Best Day rule is a profit ceiling, and it is under-modelled everywhere

Rearranging `max_day <= f × total` with `R` banked on other days gives
`today <= f·R/(1−f)` — at the venue's 20%, simply `R/4`. `best_day_budget_usd`
returns the remaining allowance.

The consequence worth internalising: **a 5% target and a 20% cap together fix a
minimum number of profitable days, not a minimum number of trades.**
`best_day_days_required` returns `⌈100/best_day_pct⌉ = 5`. No single day, however
good, can substitute for spreading the profit.

This rule breaches **independently of whether the strategy has an edge**, which is
why it is enforced here rather than left to the strategy: the *last* gold
walk-forward run breached it at **55.5% of profit in one day against a 20% cap**,
on a result whose t-statistic was +0.52. Fixing concentration is required whether
or not there is ever an edge to concentrate.

---

## 4. The arming switch: fail-closed on three independent axes

`ArmingGate` is **OFF by default**. Three separate things must hold:

1. A `ValidationRecord` exists on disk, and the artifact it cites exists with a
   **matching sha256** (a verdict whose evidence is missing or changed is a claim,
   not a result).
2. That record clears every `GateCriteria` threshold — t ≥ **1.5**, ≥ **60%** of
   folds positive, ≥ **100** OOS trades, beats its matched null, cost included.
   These are the frozen criteria from `docs/SYNTHETIC_GATE_V2.md` and the
   pre-registered `docs/GOLD_WFO_PROTOCOL.md`, pinned in tests so they cannot
   drift.
3. An **operator** arming file names the **same `config_id`**.

(1)+(2) are the strategy's business; (3) is the human's. They are separate files
on purpose — a gate that one file can satisfy is a gate that one mistake can
satisfy. Absent, unreadable, malformed, expired, tampered, or mismatched all
return `armed=False` **with a reason**; none of them raises into a default-allow.

### The switch refuses the real gold result

Run against `artifacts/gold_wfo_v2.json` with the operator switch deliberately set
to **armed: true** — the worst case:

```
gate result -> armed = False
   REFUSED: validation verdict is 'NOT VALIDATED', not PASS
   REFUSED: t-stat +0.71 is below the required 1.5 — indistinguishable from zero
   REFUSED: 48% of folds positive, below the required 60% — the result is
            carried by a minority of the window
```

That is the design goal stated as a result: **the operator cannot arm the system on
a result that has not earned it, even deliberately.**

---

## 5. Live verification, end to end

`scripts/verify_sizing_live.py`, run against the funded account:

```
=== SIZING VERIFICATION — XAUUSD @ 2026-09-19 21:33 UTC ===
account      1428765 @ Upcomers-Server  USD
                 equity $25,000.00  balance $25,000.00
measured basis  $100.0000 per 1.0 price unit per 1.0 lot (order_calc_profit)
spec fields     imply $10.0000 -> DISAGREES 10.00x
stop distance   9.89 price units
daily limit     $750.00  shield $1,500.00  (floor $23,500.00)
best-day        20% cap; needs >= 5 profitable days; today's remaining allowance $0.00

BLOCK
  lots=0.37 risk=$365.93 budget=$375.00 (daily 3% limit)
  BLOCKED: arming switch is OFF: operator arming file absent — the switch
           defaults to OFF
VERDICT: BLOCKED
```

The sizing is **legal**: 0.37 lots, $365.93 of a $375.00 budget, on a $9.89 stop.
The block is *only* the switch — which is precisely right, and the script prints
the distinction:

> A legal trade is not an armed system.

The script exits non-zero whenever the trade is not placeable, so it can gate a
pipeline. It places no orders and imports no order-sending path.

---

## 6. What is still missing, stated plainly

* **No entry logic.** Nothing generates signals. The execution layer is complete
  and idle.
* **No arm file, no validation record.** Both are absent by design; the switch is
  off.
* **The single-trade loss cap is still unmodelled.** `risk_budget_usd` says so in
  its note on every run: *"single-trade cap not modelled — verify the current
  rulebook."* It is an explicit opt-in parameter rather than a baked-in fact,
  because it was not re-confirmed against the current rulebook.
* **`account_size` is the shield's baseline, not a live measurement.** If the
  account is ever resized or re-funded, `ThunderboltClassicRules.account_size`
  must change with it, or the 6% floor is computed from a licence that no longer
  exists.

**How to arm, when there is something to arm.** Produce a walk-forward artifact
that clears the gate, write a `ValidationRecord` alongside it with the artifact's
sha256, and then — deliberately, by hand — write an arming file naming that
`config_id`. If any of those three is wrong, the gate says which one.

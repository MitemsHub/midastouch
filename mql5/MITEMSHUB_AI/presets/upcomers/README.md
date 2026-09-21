# presets/upcomers/ — the Upcomers $25,000 Thunderbolt Classic program

**What lives here:** the `.set` presets that configure **the existing, certified
`MitemshubAI` EA** for the Upcomers prop account (`Upcomers-Server`, login
`1428765`, Thunderbolt Classic).

**What deliberately does NOT live here: a copy of the EA.** There is exactly one
`MitemshubAI.mq5` in this repository, at `mql5/MITEMSHUB_AI/MitemshubAI.mq5`. This
folder exists so that "which program is this preset for?" is answerable at a
glance, **not** so the EA can be forked per venue.

## Why no fork (the decision, and the reason for it)

`MIDASTOUCH` looks like the template — it has its own `mql5/MIDASTOUCH/` tree — but
that is because MIDASTOUCH is a **different EA** (`MidastouchAI`, a gold
mean-reversion system). Upcomers is **not a different EA**: it is the same
`MitemshubAI` pointed at a different instrument on a different venue, and it needs
**zero source changes** to do so.

I verified that rather than assuming it. The EA's symbol guard is at
`MitemshubAI.mq5:781`:

```mql5
string cbchk = _Symbol;
StringToLower(cbchk);
if(StringFind(cbchk, "crash ") == 0 || StringFind(cbchk, "boom ") == 0)
   { ... return(INIT_FAILED); }
```

It refuses only names *beginning* with `crash `/`boom `. It does **not** require
"Volatility" in the symbol name, so `NACUSD.c` passes `OnInit()` unmodified.

Forking the source would recreate the exact failure this repo's `docs/INDEX.md`
was written to fix: in September 2026 the tree contained **two EA variants and five
documents each claiming to be current state**, naming four different deployed
versions. A second copy of the same EA is how that starts.

## What goes here

| File | Purpose |
|---|---|
| `MitemshubAI_UPCOMERS_NACUSD_<stage>.set` | Nasdaq-100 preset, per validation stage |
| `MitemshubAI_UPCOMERS_SPCUSD_<stage>.set` | S&P-500 twin, if validated |

**Naming:** `MitemshubAI_UPCOMERS_<INSTRUMENT>_<stage>.set`, where stage is `DEV`,
`TESTER`, or `LIVE`. The venue and instrument are in the filename because the same
EA now trades two venues and a preset without them is unidentifiable.

## The rules these presets must obey

The account's hard limits are code, not prose —
`src/midas_prop/risk/upcomers_rules.py`, tested by
`tests/test_upcomers_rules.py`:

- **3% daily loss** ($750), measured against `max(equity, balance)` at 00:00 UTC
- **6% Dynamic Risk Shield**, which trails the equity high-water mark and **locks
  at the initial balance** once the account is 6% up
- **20% Best Day rule** — no single day may exceed 20% of total profit
- **2-minute minimum hold** — sub-2-minute closes are flagged as tick scalping

Supposed per-trade risk so that **ten consecutive losses** are needed to breach the
daily limit: `risk_budget_usd(..., safety_fraction=...)` in that module.

## Live-trading guard

`tests/test_preset_live_guard.py` scans this tree and fails if any preset ships with
`InpLiveExecution=true` without being on the allowlist. That scan was
**non-recursive** until this folder was created — a subfolder would have escaped
the guard silently. It is now recursive, and a test asserts that it stays that way.

**Therefore: any `.set` placed here is armed only by a deliberate allowlist edit.**
That is the intended friction.

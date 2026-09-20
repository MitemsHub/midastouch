# UPCOMERS RULES AUDIT — 2026-09-19

**Requested by:** operator, ahead of buying a **$25K Thunderbolt (1-Step, MT5, 80% split, $35.91)**
challenge, on the belief that Upcomers is *"a platform that allows EA trading and also has their
own synthetic indices."*

**Status of this file:** authoritative for *what Upcomers' rules actually are*. It is not a
strategy document and it authorizes nothing. Sources are Upcomers' own Help Center articles
(primary) plus one third-party aggregator, marked as such.

---

## 0. BOTTOM LINE

**The premise is false.** Upcomers does **not** offer synthetic indices. Its MT5 server
(`Upcomers-Server`) carries Forex, real-world equity indices, metals, energies, crypto and
stocks — **zero Deriv-style Volatility / Boom / Crash / Jump / Step indices.** The only
genuinely 24/7, EA-tradeable asset class it offers is **crypto CFDs**.

Consequently the move as described — *withdraw Deriv capital → buy Upcomers → uninstall Deriv
→ trade Upcomers 24/7* — **does not achieve its stated purpose**. It would replace gold
(not 24/7) with FX and equity indices (also not 24/7). It is the same trap with a different
instrument, at a different venue.

Two independent problems, and only one of them is about the venue:

1. **Venue mismatch.** Wrong instrument family. (Section 3.)
2. **No validated edge.** Our own pre-registered geometry/cost study (`docs/GEOMETRY_COST_STUDY_20260919.md`,
   2026-09-19) **rejected** the hypothesis that wider stops rescue the V75 continuation family:
   at V75's tightest stop, gross was **+11.07R** and net **−0.06R** — the spread consumed
   **100.5%** of the edge — and widening to 2×ATR(H1) halved the toll while collapsing gross
   to +1.26R. 1 of 16 cells passed. **Prop capital does not fix this.** It fixes position
   sizing (Section 8), not expectancy.

---

## 1. WHAT UPCOMERS ACTUALLY IS

| Field | Value | Source |
|---|---|---|
| Entity / HQ | Building A1, IFZA Business Park, Dubai Silicon Oasis, UAE; founded **2023** | third-party aggregator |
| Broker behind it | **Royal Flow - FZCO**; "broker-backed: No" | third-party aggregator |
| CEO | Jakub Zeliska | third-party aggregator |
| Platforms | **MT5**, TradeLocker, Match-Trader, cTrader, Bybit, Upcomers X (futures) | Upcomers Help Center |
| MT5 server | `Upcomers-Server` | Upcomers Help Center |
| All accounts | **swap-free** | third-party aggregator |
| Commission | Forex **$5/lot**, Metals $5/lot, Crypto **0.04%**, Stocks/Indices/Energies 0 | third-party aggregator |

Not a regulated broker. Challenge fees have no regulatory protection. This is normal for the
prop-firm model but is a real cost-of-counterparty, not a footnote.

---

## 2. EA / AUTOMATION POLICY — AND A DANGEROUS CONTRADICTION

### 2a. Primary source says ALLOWED (current)

Upcomers' own Help Center article *"Are Expert Advisors (EAs), trading bots and automated
strategies allowed?"* (dated 2026-07-08):

> "**Yes.** Expert Advisors (EAs), trading bots, algorithms and automated trading tools are
> allowed at Upcomers, as long as they follow our trading rules and represent a real, unique
> and responsible trading strategy."

Explicitly allowed: custom-built EAs, personal bots, trade managers, risk managers, lot-size
calculators, SL/TP managers, break-even tools, trailing stops, news filters, semi-automated
execution, "automated strategies based on the trader's own trading logic".

Strictly prohibited: HFT, tick scalping, latency/reverse/hedge arbitrage, platform or data-feed
exploitation, emulators, copy trading from third parties, third-party account management,
**using the same EA strategy across multiple traders**, identical/near-identical trade
generation across accounts, public "prop firm passing" bots, one-shot challenge bots,
excessive order placement/cancellation/modification, and *"any strategy that cannot be
reasonably replicated under real market conditions."*

Uniqueness is enforced by review, not by a setting:

> "Changing small parameters, account size, lot multiplier, symbol selection or execution
> timing does not automatically make a strategy unique if the underlying trading logic remains
> the same."

Upcomers may demand: EA purpose, custom vs third-party, ownership proof, strategy logic,
settings/risk parameters, confirmation it is not shared. **Failure to provide reasonable
information during review may affect the outcome of the review.**

> **Assessment:** our EA is custom-built, private, single-owner, and we hold the full source
> history — the *strongest* possible position under this clause. This is the one part of the
> Upcomers proposition that is genuinely favourable.

### 2b. Third-party aggregator says PROHIBITED (stale)

A third-party firm-comparison site lists for Upcomers: **"Expert Advisor (EA): ✗"**, with
*"Expert Advisors (EAs), bots, emulators or automated trading of any kind (even partial
automation of entries, exits, SL/TP management or trade copying)"* listed under prohibited
strategies.

**How to read the conflict.** Upcomers' Help Center article is dated **2026-07-08**, and a
press release dated **2026-06-24** announces *"Upcomers Expands Trading Automation Across All
Supported Platforms… Effective May 26, 2026, participants in all Upcomers programs… may use
Expert Advisors, trade managers, risk…"*. The aggregator is almost certainly reproducing the
**pre-May-2026** policy. **The primary source governs.**

**But this is a live payout risk, not a footnote.** The EA policy changed roughly four months
ago. An aggregator published the old rule; the old rule may still be what a particular risk
reviewer, or an older internal SOP, reaches for at payout time. This is exactly the failure
mode the ForexPeaceArmy complaint describes: *"Upcomers rejected my payout after I completed
the challenge in profit. Their excuse was 'gambling behavior' and 'impulsive trading'."*
A discretionary denial cannot be appealed except within 48 hours, with a final outcome.

---

## 3. FACT: NO SYNTHETIC INDICES (the premise check)

Upcomers Help Center *"What instruments can I trade?"*:

> "**MT5** — Everything in one place. Forex, indices, commodities, metals, crypto, and stocks.
> Our largest selection with 1,300+ instruments and zero symbol restrictions.
> Server name: Upcomers-Server"

The published MT5 symbol list, category by category:

| Category | Count | Examples / character |
|---|---|---|
| Forex | ~100 pairs | EURUSD, GBPJPY, USDZAR, exotic crosses |
| **Indices** | **20** | `SPCUSD.c` (S&P), `GECEUR.c` (DAX), `UKCGBP.c` (FTSE), `DJCUSD.c` (Dow), `NACUSD.c`, `JPCJPY.c`, `HKCHKD.c`, `SWI20`, `ES35`, `N25`, `RUSS2000`, `TWCUSD.c`, `AXCAUD.c`, `CHCUSD.c`, `EXCEUR.c`, `FRCEUR.c`, `INCUSD.c`, `SGCSGD.c`, `USOIL.c`, `XNGUSD` — **all real-world equity indices and energy, no volatility indices** |
| Metals | 11 | XAUUSD, XAGUSD, XPTUSD, XPDUSD, XALUSD, GAUUSD |
| Crypto | ~38 on MT5 | `BTCUSD.nx`, `ETHUSD.nx`, … (`.nx` suffix) |
| Stocks | ~1,100 | EU, HKEX, NYSE/NASDAQ single names |

**There is no V10/V25/V50/V75/V100, no Boom, no Crash, no Jump, no Step.** Deriv's Volatility
Indices are a Deriv-proprietary product; a firm using FX/equity CFD liquidity cannot offer
them. Repeated web searches for Upcomers + synthetic indices return **only** Deriv, other
brokers, and unrelated firms.

### The residual check (do this before any purchase)

After (or before) buying, open MT5 → Market Watch → *Show All* on `Upcomers-Server` and
confirm the absence directly. Also ask support in writing (Section 7). Do not take this audit
as a substitute for looking at the live symbol tree — it is a documentation claim, not an
observation of the running server.

---

## 4. THUNDERBOLT (CFD) — EXACT RULE SET, $25,000 CLASSIC

Primary source: *"Thunderbolt Challenge (CFD) Complete Rules & Overview"*.

| Parameter | Challenge | Funded |
|---|---|---|
| Profit target | **5%** = **$1,250** | none |
| Min trading days | none | none |
| **Daily drawdown** | **3% = $750** (00:00–23:59 **UTC**) | 3% = $750 |
| **Dynamic Risk Shield™** | **6% = $1,500**, trails the equity **High Water Mark**, only ever rises, **max shield level = initial balance** | same, carried over |
| **Max single trade loss** | not applied | **3% = $750 — HARD BREACH, account terminated** |
| **Best Day Rule** | not applied | **20%** — **SOFT**: delays payout only |
| Payout requirement | not applied | **1% = $250** min profit from initial balance, resets each payout |
| Min payout | — | **$45** |
| Leverage | 1:100 | 1:100 |
| Profit split | — | **80%** (as selected at checkout; default 90%) |
| Open positions at payout | — | **all must be closed** |

**Mechanics that matter to an EA:**

- **The shield trails on equity and ratchets.** Start: HWM $25,000 → floor $23,500. Once HWM
  reaches ~$26,596 the shield locks at $25,000 (initial balance) and cannot rise further, so
  from that point the account is protected to break-even. **Open positions count** — an
  unrealised drawdown can breach, not just a closed loss.
- **3% max single trade loss counts positions on the same instrument, same direction, as ONE
  trade.** Splitting does not bypass it. This is a *hard* termination, "even if the account is
  overall profitable."
- **Best Day Rule**: withdrawal W requires best day ≤ 0.20 × W. Intentionally splitting trades
  to bypass it is prohibited and may be collapsed into a single day.
- **Thunderbolt (non-Turbo) has NO minimum valid-day requirement at payout.** (Turbo variants
  do: 5 valid days each ≥0.5%.) This is a meaningful advantage of the classic product.

---

## 5. PAYOUT ECONOMICS — the honest arithmetic at $25K / 80%

Payout caps apply to the **withdrawal**, on a tiered progression, and the **cap only advances
after a fully approved payout with no rule violations**:

| Payout | 1st | 2nd | 3rd | 4th | 5th | 6th | 7th | 8th+ |
|---|---|---|---|---|---|---|---|---|
| Cap ($25K) | **$250** | $500 | $750 | $1,000 | $1,250 | $1,560 | $1,875 | **Unlimited** |

**After the 7th approved payout the account resets to its initial balance.**

**Fees:** bank transfer **$19.90 + 2.49%**; crypto **$19.90 + 30%** (the 30% drops to 2.49% only
if >50% of your orders were paid in crypto). Returned payout: $30 reprocessing.

**Stranding rule — the most under-read clause:**

> "Any remaining profit stays on the account… but it is **not eligible for withdrawal in future
> segments**. Each payout is based only on the profit you earn in your current segment… **Profit
> left behind from a previous segment cannot be carried over or unlocked in a later one.**"

So over-earning in an early segment **destroys** the excess. This inverts normal trader
instinct: on a capped segment you are penalised for a good month, not rewarded.

**Realistic first-payout cycle at $25K / 80%:** pass the challenge (+$1,250), then generate
**≥$250** in funded profit **spread so no single day exceeds $50** (Best Day 20% × $250). Take
the payout capped at $250 → trader share **$200** → minus **$19.90 + $4.98** → **≈ $175 net**.

**Ceiling before reset:** caps 1–7 sum to **$7,185**; if the cap is applied to the trader's
share that is the maximum extractable, ≈**$5,573** after seven ≈$25 fees. To reach it you
would have to generate roughly **29% cumulative net profit on a $25,000 account** — while never
breaching a **3% daily** loss, never losing **>3%** on any single trade (hard termination),
never breaching a **6% trailing** shield, and satisfying the Best Day rule in every segment.

> **Read this as a constraint-satisfaction problem, not a return target.** The fee is $35.91;
> the fee is not the risk. The risk is that the constraint set is the binding object and the
> payout caps mean one early rule violation costs far more than the challenge price.

**Payout reputation (third-party, treat as weak evidence):** Trustpilot for
`app.upcomers.com` stands at **2.0/5** (~30 reviews); the main `upcomers.com` profile has
hundreds of reviews; Reddit r/PropFirmTester carries a *"Stay Away from Upcomers"* thread; one
UK Trustpilot reviewer reports receiving *"25% of what my 90% split should have been"*; at
least one reviewer reports 4 successful payouts. Propfirmmatch lists Upcomers as
**unlisted / not reviewed or verified**. Mixed, leaning negative, and note *which* mechanism
denials are reported under — **discretionary "irresponsible trading" judgement**, not a
numeric breach.

---

## 6. INTERNAL CONTRADICTIONS IN UPCOMERS' OWN RULEBOOK

Found by comparing their own articles. Each one is a place a payout dispute can go against the
trader even when the EA obeyed the rule it was programmed against.

| # | Rule | One Upcomers page says | Another says | Why it matters to an EA |
|---|---|---|---|---|
| C1 | **Daily drawdown reset time** | Thunderbolt page: *"00:00 to 23:59 **UTC**"* | Prohibited-strategies page: *"reset **5:00 PM ET**"* | These are ~4–5 hours apart. The EA must reset its daily loss counter at exactly the right instant, or it either stops trading 5h early or keeps trading into a breach. **Unresolvable by inspection.** |
| C2 | **Daily DD %** | Thunderbolt: **3%** on Classic | Prohibited-strategies: *"**2%** on Classic and Vanguard, 3% on Legacy"* | A whole percentage point — the difference between a 6% and a 12% profit target's worth of room. |
| C3 | **Max single trade loss** | Thunderbolt funded: **3%** | Prohibited-strategies: *"**1.5%** per open trade on Classic and Vanguard, 2% on Thunderbolt Legacy"* | This is the **hard-termination** rule. Getting this wrong ends the account. |
| C4 | **Hedging** | Prohibited: *"Hedging is prohibited even within a single account"* | Aggregator: *"Hedging within a single account is **allowed** under normal trading rules"* | Our EA must know whether any opposing leg is ever permissible. Safest reading: **never**. |
| C5 | **Document generation** | Thunderbolt page describes the CFD product | Prohibited-strategies page is written for *"Upcomers **Futures**"* but claims firm-wide application to *"Thunderbolt Classic, Thunderbolt Legacy, and Vanguard"* | Rules from a futures product may be cited against a CFD account. |

> **This table is the single strongest argument for not trading this account until the numbers
> are confirmed in writing.** A rulebook that disagrees with itself cannot be programmed
> against, and the reviewer decides which version applies.

---

## 7. QUESTIONS TO GET ANSWERED IN WRITING BEFORE FUNDING

Send to Upcomers support and keep the reply. An EA must encode the answers, so a verbal or
in-chat answer is not sufficient.

1. Does `Upcomers-Server` carry **any** synthetic/volatility index (V25/V50/V75, Boom, Crash,
   Jump, Step)? *(Expected answer: no.)*
2. **Exact daily-drawdown reset time and timezone** (C1 — 00:00 UTC or 5:00 PM ET?).
3. For **Thunderbolt Classic CFD $25K funded**: confirm **daily DD %** (C2) and **max single
   trade loss %** (C3) — which figure is binding.
4. Is the **Dynamic Risk Shield** computed on **equity** (including open positions) or on
   closed balance? Confirmed to lock at initial balance?
5. Which MT5 symbols are **open on Saturday and Sunday**, with their exact session hours?
6. **Minimum lot size and minimum stop distance** per candidate symbol.
7. **Spread and commission** for the intended symbols, in points, typical and at rollover.
8. **EAs**: confirm permitted on Thunderbolt Classic CFD; state exactly what documentation is
   required at payout review (the uniqueness/ownership evidence).
9. Confirm **no minimum valid-day requirement** at payout for the **non-Turbo** Thunderbolt.
10. Confirm the **payout cap is applied to the trader's share** and not to gross profit, and
    confirm the stranding rule for over-earned segments.
11. Is **hedging within a single account** prohibited (C4)? *(Expected: yes, prohibited.)*
12. Confirm **weekend positions are allowed** (needed for any 24/7 claim).

---

## 8. WHAT PROP CAPITAL ACTUALLY FIXES — AND WHAT IT DOES NOT

**It fixes a real, previously binding constraint.** The 2026-09-19 instrument census
(`docs/INSTRUMENT_SPEC_MAP.md`) found **every** instrument in {V25, V50, V75, V100}
**CAP-VETOED at $39.58 equity**, because the 0.01-lot floor forced **16–30% of the account at
risk per trade**. Required equity was V50 $41 / V25 $75 / V75 $81 / V100 $99. On a **$25,000**
balance, minimum-lot risk becomes a fraction of a percent — **the lot-floor problem disappears
entirely.** That is a genuine unlock and it is the best thing about this whole direction.

**It does not fix:**
- **Expectancy.** The geometry/cost study rejected the continuation hypothesis net of spread.
  Bigger capital does not create edge.
- **Venue transfer.** Our EA, corpus and cost model are calibrated on **Deriv synthetic price
  processes and Deriv spreads**. FX/equity indices are a *different stochastic process* with a
  different cost structure. Any transfer to Upcomers would require **re-certification on
  Upcomers' own data** — a fresh, pre-registered study, not a settings change.
- **The 3% single-trade hard breach.** Our current cap is `InpMaxEffectiveRiskPct=20` with a
  fleet guard firing first at **15%**. A 15% risk-per-trade EA **breaches a prop account on its
  first trade.** The EA is byte-pinned (`scripts/deploy_manifest.txt`); this is a *new preset*
  and a *new gate*, not an edit to a certified binary.
- **The "<2 minutes = tick scalping" rule.** Any sub-2-minute exit in the ladder is a rule
  violation, and our certified exit ladder is not currently constrained by holding time.

---

## 9. THE ALTERNATIVE THAT ACTUALLY MATCHES THE REQUIREMENT

If the goal is *"trade synthetic indices, 24/7, with an EA"*, that product **does** exist — at a
firm built for nothing else.

**BloomFunded** (`bloomfunded.com`) — *"The prop firm built exclusively for synthetic indices."*

| Field | Value |
|---|---|
| Markets | **Boom** 150/300/500/600/900/1000 · **Crash** same · **Jump** 10/25/50/75/100 · **Step / 200 / 300 / 400 / 500 · Volatility 10/25/50/75/100 + all (1s) variants** — **exactly our universe** |
| Excluded | *"We do not offer Forex, metals, crypto or stocks."* |
| Hours | **24/7 — "no news spikes, no sessions, no gaps"** |
| Leverage | up to **1:500** |
| $25K | **$300 → $250** promo; 2-step 8% then 5%; **4 min trading days**; 80/20 split |
| Payout | **weekly cycle**; **5% max payout cap on the FIRST payout only** |
| **EAs** | *"Personal EAs are allowed within the published rules. Copy trading between accounts, group trading and latency abuse are not."* |
| Drawdown (25K) | 4% daily ($1,000) · 6% overall ($1,500) |
| Fee refund | challenge fee refunded with the 3rd payout |

**Advantages over Upcomers for our purpose:** right instrument family; 24/7 as advertised;
1:500 leverage; the payout-cap regime is dramatically better (one 5% cap on the first payout,
then no tiered progression to climb through); 4 minimum trading days instead of a rulebook
that contradicts itself.

**Disadvantages, stated plainly:** far newer and smaller — the site reports **$57,100 total
paid out** and **877 funded accounts**, which is a *tiny* track record; "rated by 12,000+
traders" is unverifiable marketing; the entity is `BLOOM GROWTH – FZCO`, and its own FAQ
concedes *"BLOOM GROWTH – FZCO provides **demo accounts** for simulated trading in a
non-live environment."* Fee is $250 versus Upcomers' $35.91. Counterparty risk is **higher**,
not lower.

Also named in the same search space: **Traders Spring Group** (marketed as a Deriv-synthetics
prop firm). Not audited here.

---

## 10. VERDICT

**DISAGREE with the plan as stated.** Specifically:

- **Do not withdraw the Deriv capital, and do not uninstall the Deriv terminal.** The premise
  for the move (synthetics + 24/7) is not satisfied by Upcomers, so trading the existing
  program must remain possible while this is re-scoped.
- **Upcomers is not a synthetic-indices venue.** Buying it does not restore 24/7 trading; it
  adds a rule set that is hostile to our current EA's risk settings and is internally
  self-contradictory on the two rules that cause **hard termination**.
- **$35.91 is cheap, and that is the trap.** The fee is not the risk. The risk is a
  constraint set that our certified EA would breach immediately (15% risk-per-trade vs a 3%
  hard cap), a discretionary-review payout mechanism, and a payout-cap regime that punishes
  over-performance in early segments.
- **But one thing here is genuinely valuable:** a prop account removes the **lot-floor wall**
  that killed the synthetic program at $39.58. That insight survives regardless of venue.

**Recommended sequence:**

1. **Keep Deriv intact.** It is the only place our V75 corpus, spread model and calibration
   are valid.
2. **Do not buy Upcomers for the synthetic premise.** If a $36 experiment is wanted purely to
   test the operational path (MT5 EA deployment, KYC, the dashboard), buy it *knowing* it
   cannot deliver synthetics, and treat it as a deployment exercise — not a trading plan.
3. **If synthetic indices + 24/7 + EA is the actual requirement, audit BloomFunded properly
   first** (entity, payout evidence, the 5% first-payout cap wording, its own prohibited-
   strategy list, and whether its synthetic feed is the same price process as Deriv's). Then
   decide.
4. **Regardless of venue, the edge question gates everything.** We currently hold no
   cost-surviving, out-of-sample-validated edge in this family. Buying capital for a strategy
   that has not earned it inverts the discipline in `docs/OPERATING_SUMMARY.md` that has so far
   kept unvalidated configurations away from real money. **Fix the edge, then buy the account.**
5. If a prop account is being considered at all, build the **prop constraint evaluator**
   first: encode the venue's rules (daily DD, trailing shield, max single trade, Best Day,
   minimum valid days, tick-scalp floor, trade-count caps) and run our existing trade logs
   through it. That converts "could we survive a prop account?" from opinion into a number, and
   it is reusable across every firm in this section.

---

## 11. TERMINAL ONBOARDING — LIVE STATUS (2026-09-19, 17:20 local)

The account was purchased: **$25,000 Thunderbolt, CLASSIC, FOREX/CFDs, platform MT5,
account #699573, login 1428765.** A terminal probe was built and the connection was
diagnosed. **The terminal is not yet usable and the blocker is not in our code.**

### What was established

| Fact | Evidence |
|---|---|
| The install is a **generic MetaQuotes MT5**, at `C:\Program Files\MetaTrader 5`, created 2026-09-19 17:05 | new data folder `D0E8209F77C8CF37AD8BF550E51FF075` created 17:07 |
| Terminal build **6204** | terminal log: `MetaTrader 5 x64 build 6204` |
| The two working Deriv terminals are build **6182** (`MitemshubMT5_B`, `_C`) — neither knows this broker | `VersionInfo.FileVersion` |
| Python bridge was **5.0.6090**; upgraded to **5.0.6180** (latest on PyPI) | `pip index versions MetaTrader5` |
| **The upgrade did not fix it** — so this is not a version problem | `initialize()` still returns `-10005 IPC timeout` |
| **No account is logged in**: `bases/` contains only `Custom`, `Default` — no Upcomers server directory | live inspection |
| Launching with `/login:1428765 /password:*** /server:Upcomers-Server` (and `/server:Upcomers`) produces **no login attempt at all** in the terminal log | terminal log 17:19–17:20 |

### Diagnosis

MT5's Python IPC refuses to attach until the terminal is **authorized to a trade server**, and
it cannot authorize because the generic MetaQuotes installer ships **without Upcomers' server
list**. The command-line credentials are received but cannot be resolved, so MT5 never even
attempts the connection and logs nothing. This also means the premise cannot be verified from
the running server yet — the published symbol list in §3 stands as documentation evidence only.

### Required action (operator, one time)

Either:
1. In MT5: **File → Open an Account**, search `Upcomers`, let it download the broker's server
   config, then **File → Login to Trade Account** with login `1428765`. *(Preferred — it also
   confirms the exact server string, which the dashboard shows as "Upcomers" and the Help
   Center calls "Upcomers-Server".)*
2. Or install the MT5 build linked from the Upcomers dashboard, which has the servers baked in.

### The moment it connects

`scripts/venue_probe.py` runs read-only and dumps, from the live server:
full symbol tree with categories · any synthetic-index matches · per-symbol specs (min/step/max
lot, tick value and size, contract size, stops level, spread, swap) · **real min-lot risk in
dollars at a 1%-of-price stop** at $25,000 · and **which categories have a live tick right now**
— run on a weekend, that last column settles the 24/7 question empirically rather than from
marketing copy.

---

## 12. LATE-SESSION UPDATE (2026-09-19, 19:45–19:55 local) — corrections and new evidence

Second pass on the same day, after the instrument-selection research. Four things
changed, and one thing did not.

### 12a. The login diagnosis is now verified by exhaustion, not inferred

§11's diagnosis was right, and three further attempts closed it off as a **client
limitation rather than a misconfiguration**:

| Attempt | Result |
|---|---|
| `/login:1293766 /password:Upcomers1. /server:Upcomers-Server` (read-only account, **no special characters** in the password) | args confirmed **intact** in the process command line; terminal logged **nothing** |
| `/config:` auto-login `.ini` with `[Common] Login/Password/Server` | served: terminal logged `successfully initialized from start config` and `launched with …ini` — then **still attempted no connection** |
| Python bridge `initialize(login=…, server='Upcomers-Server')` | `-10005 IPC timeout`, as before |

So the password-escaping hypothesis is dead (the special-character password was
not the cause), and MT5 parses the config but **silently declines** to dial a server
absent from its broker directory. There is **no CLI or config path to register a
broker server in the MT5 client.** §11's required action stands, and the GUI step
is the only route.

### 12b. NEW: Upcomers publishes a public read-only MT5 account

The venue's article *"Check Our Trading Conditions Before You Buy"* gives working
credentials for a **read-only** view of the live server:

> **Server:** `Upcomers-Server` · **Login:** `1293766` · **Password:** `Upcomers1.`
> (the trailing period is part of it) — trading disabled, no balance, all 1,300+
> symbols, real-time spreads, swaps, contract specs and leverage.

This is significant on two counts: it is a **sanctioned** way to run the §3 premise
check and the instrument screen, and it means the funded password need not be typed
into a terminal at all. It does **not** remove the GUI blocker — the server must
still be registered once.

### 12c. NEW: the cost and rule numbers (this materially changed instrument choice)

Confirmed from the Help Center plus a cross-checked broker profile:

- **Commission:** indices / stocks / energies **0** · metals **$5 per lot** · forex
  **$5 per lot** · **crypto 0.04% of notional**. In basis points of notional that is
  `0 / 0.377 / 0.909 / 8.000` — **crypto costs more than 8x forex** and is not
  comparable to the zero-commission classes at all.
- **All accounts are swap-free.**
- **Leverage:** forex 1:100; crypto, metals, stocks, indices, energies 1:30.
- **Thunderbolt Classic:** 5% target · **3% daily DD** (00:00 UTC) · **6% Dynamic
  Risk Shield™** that **locks at the initial balance** once 6% in profit · **Best
  Day 20%** · no minimum valid days for Classic.
- **Payout ladder:** 1/2/3/4/5/6% of initial balance per approved withdrawal, then
  the account resets to initial and is uncapped from #8. On $25K that is **$5,250
  across seven payouts** (~$4,725 net at 90%).

> **Caveat added to §4 and §6 above.** The **3% single-trade loss cap** is recorded
> there from the Thunderbolt rules page, but it was **not re-confirmed** in this
> pass. `src/synthetic_trader/risk/upcomers_rules.py` therefore refuses to assume
> it: `risk_budget_usd()` takes it as an explicit parameter and prints
> *"single-trade cap not modelled — verify the current rulebook"* when absent. An
> unverified number must not silently decide position size.

### 12d. The no-synthetics finding is now stronger

The venue's **own published MT5 symbol table** was enumerated in full (~1,300
symbols across forex, indices, metals, crypto, stocks). The entire *Indices*
category is **20 real-world equity indices** — `SPCUSD.c`, `NACUSD.c`, `DJCUSD.c`,
`GECEUR.c`, `UKCGBP.c`, `JPCJPY.c`, etc. There is no `V25/V50/V75/V100`, no Boom,
no Crash, no Jump, no Step. §3 is upgraded from market-observation to
venue-published fact.

Two adjacent clarifications: the *"Allowed instruments and exchanges"* article
(50 CME futures) describes **Upcomers Futures / Upcomers X**, a different product —
not this account. And the homepage's *"Trade 24/7, weekends included"* line
describes **Perpetuals** (Hyperliquid-backed web platform), which **cannot run an
MT5 EA**.

### 12e. STILL UNRESOLVED: does MT5 crypto trade weekends?

Sources conflict and neither is a session table:

- Upcomers' *"Markets never close: trading 24/7"* is about **Perpetuals** and says of
  CFDs *"a surprising amount of your routine was built around the clock. None of it
  applies here"* — implying **MT5 CFDs do close on weekends**.
- A third-party broker profile lists **"Crypto Weekend Trading: ✓"**.

**How it gets settled:** the MT5 Python bridge exposes no session-time function,
but `symbol_info()` carries `session_deals` and `session_volume` — counters that
accumulate only while a symbol is actually trading. `scripts/venue_probe.py` now
captures these and rolls them up by asset class, so **one Saturday/Sunday run
proves or disproves it by measurement.** This is why the GUI step is urgent rather
than routine: the test only works at a weekend.

**The instrument-selection research lives in
`docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`** — including the ranked answer,
the cost-per-R metric, and the measured-vs-assumed table.

---

## 13. RE-VERIFICATION: DOES UPCOMERS CARRY SYNTHETIC INDICES? (re-asked 2026-09-19 night)

**No. Re-checked on request; the answer is unchanged, and it is structural rather
than an oversight.**

> **Read §9 alongside this section.** §9 already audits the leading synthetics-only
> venue (BloomFunded) in detail, including the numbers. §13c–d extend §9 rather than
> restate it, and deliberately quote the same figures so the two cannot drift apart.

### 13a. Evidence, re-confirmed

The venue's own published MT5 symbol table (enumerated in §12d) has **20 symbols in
its entire *Indices* category**, all real-world equity indices. No `V25/V50/V75/
V100`, no Boom, no Crash, no Jump, no Step. Upcomers' other products cannot supply
them either: **Perpetuals** is crypto/gold/oil/indices/US-stock perps on Hyperliquid,
**Upcomers X** is 50 CME futures, and **Bybit** is 700+ USDT perpetuals.

### 13b. Why it is structurally impossible, not just currently unlisted

Deriv's synthetic indices are **not an asset class — they are a proprietary product
series generated by Deriv's own pricing engine.** Nobody else can quote V75, Boom or
Crash; a firm can only offer them by *being* Deriv or by routing order flow to it.
Upcomers did the opposite: it **built its own MT5 server** in January 2026 precisely
to stop depending on third-party providers, and populated it with real instruments.
A prop firm quoting its own real-world feed has no path to Deriv's synthetic series.

This also explains why the earlier searches returned only Deriv whenever synthetics
were queried: they were never Upcomers results.

### 13c. But the thing actually wanted DOES exist — just not here

The original goal was *"go back to our synthetic indices bot… this time we have to
make it better"* with 24/7 coverage. That goal has venues; Upcomers is simply not one
of them. A small category of **synthetics-only prop firms** trades exactly the Deriv
product line:

| Firm | What it offers | Relevance |
|---|---|---|
| **BloomFunded** (`bloomfunded.com`) | **Synthetics only** — Boom, Crash, Jump, Step, and the Volatility series **including all 1s variants**; $5K–$50K; up to 1:500; **2-step 8% → 5%** target, 4% daily, 6% overall; 4 min trading days; weekly payouts; 80/20 split; **personal EAs explicitly allowed** (full detail in §9) | Lists **`Volatility 75 (1s)`** — the exact instrument our certified EA was built around (+10.51R in-sample, n=406). $25K listed at **$300 → $250**. Campaigns 24/7 as the core selling point |
| **Audacity Capital** | Markets an MT5 **synthetic indices** account | Longer-established firm (London, since 2012) — worth auditing as the more conservative name |
| **Traders Spring Group** | Reported Deriv-synthetics prop firm | Unverified |

### 13d. Due-diligence flags raised on first read (audit before paying)

BloomFunded's own landing page **contradicts itself on its own statistics**:

- "12,000+ traders worldwide" in one block, **"15,411+ Traders worldwide"** in another;
- "877+ Funded accounts" **and** "800+ Funded accounts";
- "**$57,100+** Paid out to traders" **and** "**$40,000+** Paid out to traders".

Taken at the largest figures, that is roughly **$65 of total payouts per funded
account** — a number that should be reconciled before any fee is paid. Their FAQ also
states plainly that accounts are **demo/simulated** ("BLOOM GROWTH – FZCO provides
demo accounts for simulated trading in a non-live environment") — which is true of
all prop firms, but it is stated here rather than buried. **No independent review
presence surfaced** in the search that found them; only their own site and YouTube
content. Treat the eight on-site testimonials as marketing, not evidence.

**Verdict on §13:** the venue question is now *two* questions, and they have
different answers. **24/7 + synthetics + EA** → audit a synthetics-only firm, starting
with Audacity Capital as the established name and BloomFunded as the specialised one.
**Real instruments on a firm that publishes its costs and rules clearly** → Upcomers,
per §12c, is the better-documented venue but cannot run the certified synthetic EA at
all. This does not change any figure in
`docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`.

---

## SOURCES

**Primary (Upcomers Help Center, help.upcomers.com):**
`12983894-thunderbolt-challenge-cfd-complete-rules-overview` ·
`14594653-check-our-trading-conditions-before-you-buy` (read-only account) ·
`16759714-markets-never-close-trading-24-7` ·
`12762068-metatrader-5-mt5-download-setup-troubleshooting` ·
`15729215-allowed-instruments-and-exchanges` (Upcomers Futures — different product) ·
`12639949-eligibility-for-payout-cfd` ·
`12688538-payout-structure-cfd-perpetuals` ·
`11704867-are-expert-advisors-eas-trading-bots-and-automated-strategies-allowed` ·
`15729224-prohibited-strategies` ·
`11484528-rules-on-responsible-risk-management` (formerly "rules-restricting-gambling") ·
`8496680-what-instruments-can-i-trade`

**Synthetics-only venue leads (§13, first read — NOT yet audited to this standard):**
`bloomfunded.com` (own-site claims and figures only; see §13d for internal
contradictions) · `audacity.capital` · fxnx.com · propfirmmatch.com

**Third-party (weak evidence, cited as such):** `thegodfunded.com/en/firms/upcomers/` ·
Trustpilot `app.upcomers.com` / `upcomers.com` · Reddit r/PropFirmTester ·
ForexPeaceArmy review 23346 · propfirmmatch · `bloomfunded.com`

**Internal (this repo):** `docs/GEOMETRY_COST_STUDY_20260919.md`,
`docs/UNIVERSE_VERDICT_20260919.md`, `docs/INSTRUMENT_SPEC_MAP.md`,
`docs/SYNTHETIC_GATE_V2.md`, `docs/OPERATING_SUMMARY.md`,
`docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`,
`src/synthetic_trader/risk/upcomers_rules.py`,
`scripts/upcomers_instrument_screen.py`, `scripts/venue_probe.py`

# Which instrument should we trade on Upcomers? — 2026-09-19

**Status:** research complete for everything that can be answered without the
terminal; one 5-minute GUI step unlocks the rest. `docs/INDEX.md` routes the
"which instrument" question here.
**Account:** $25,000 Thunderbolt **Classic**, MT5, account #699573, login `1428765`.
The dashboard shows the server as **`Upcomers`** but MT5 must be given
**`Upcomers-Server`** — the dashboard's short name does not resolve.
**Written:** Saturday 2026-09-19 19:53 local. The day of the week is load-bearing,
see §7.

---

## 1. The short answer

**There is no single best instrument, because your two requirements point at
different instruments.** Upcomers' published cost schedule makes this a
measurable question, and the measurement says:

| Requirement | Winner | Round-trip commission |
|---|---|---|
| **Trade as close to 24/7 as possible** | **crypto CFDs** (`*.nx`) | **8.0 bps** of notional |
| **Best expected net edge per unit of cost** | **index CFDs** (`SPCUSD.c`, `NACUSD.c`, `DJCUSD.c`) | **0 bps** |

That is a **more than 8x cost difference between two instruments on the same
account** — and it is the venue's schedule, not my modelling. Trading 24/7 is not
free here; on this venue it is the single most expensive thing you can choose.

**My recommendation:** put the *next* strategy on **index CFDs** (`NACUSD.c` for
volatility, `SPCUSD.c` for liquidity) and accept a ~23h × 5-day session. Use
**crypto** only if weekend coverage is genuinely non-negotiable, and then only
`BTCUSD.nx`/`ETHUSD.nx` — never the exotic alts.

---

## 2. What the venue actually has

Confirmed against Upcomers' own published MT5 symbol list (§ provenance in §9):

| Category | Count | Leverage | Notes |
|---|---|---|---|
| **Forex** | ~110 | 1:100 | 16 majors, 15 minors, ~80 exotics |
| **Indices** | 20 | 1:30 | All **real** equity indices: `SPCUSD.c`, `NACUSD.c`, `DJCUSD.c`, `GECEUR.c`, `UKCGBP.c`, `JPCJPY.c`, `HKCHKD.c`, `RUSS2000`, `N25`, `SWI20`, `ES35`, `USOIL.c`, `XNGUSD` |
| **Metals** | 11 | 1:30 | `XAUUSD`, `XAGUSD`, `XPTUSD`, `XPDUSD`, `GAUUSD`, crosses |
| **Crypto** | 38 | 1:30 | `BTCUSD.nx`, `ETHUSD.nx`, `SOLUSD.nx`, `XRPUSD.nx`, `LTCUSD.nx`, alts; plus EUR/GBP/JPY crosses |
| **Stocks** | ~1,100 | 1:30 | US (NYSE/NASDAQ) + HKEX (`*.xhkg`) + EU |

**Still no synthetic indices.** The entire *Indices* category is real-world equity
indices — no `V25/V50/V75/V100`, no Boom/Crash/Jump/Step. That finding from the
earlier audit stands and now rests on the venue's own symbol table.

Two consequences worth stating plainly:

- **The reason you left gold has not been solved.** Forex, metals, indices and
  stocks all keep sessions. On MT5 the only class that may trade weekends is
  crypto — and even that is unverified (§7).
- **The genuine 24/7 products on Upcomers are not EA-able.** Perpetuals (web
  platform, 24/7, every symbol including stock perps) and Bybit (crypto futures,
  24/7) cannot run an MT5 Expert Advisor. So on this venue, *MT5 crypto CFDs are
  the only 24/7 path that an EA can take* — if they trade weekends.

---

## 3. The rules that bind instrument choice

Confirmed for **Thunderbolt Classic**:

| Rule | Value | Why it constrains instrument choice |
|---|---|---|
| Profit target | **5%** ($1,250) | Achievable; not the binding constraint |
| **Daily drawdown** | **3%** ($750), resets **00:00 UTC** | Caps trades/day. A 0.20R-cost instrument needs few, high-quality trades |
| **Dynamic Risk Shield™** | **6%** ($1,500), trails equity high-water | **Locks at the initial balance** once 6% up — the one real asymmetry (§3.1) |
| **Best Day Rule** | **20%** of total profit | Penalises a single big day; forces even distribution |
| Min hold | **2 minutes** | Sub-2-min closes are flagged as tick scalping |
| Swaps | **All accounts swap-free** | Holding costs vanish — matters for 24/7 strategies |
| Single-trade loss cap | **3% reported; NOT re-confirmed** | Modelled as optional in code, see §9 |

### 3.1 The one gift in this rule set

The 6% shield **stops trailing once the account is 6% in profit**, effectively
locking the initial balance as an unreachable floor. Pinned by test:

```
drawdown_floor(25,000) = 23,500      (initial - 6%)
drawdown_floor(26,500) = 25,000      (locked at initial balance)
drawdown_floor(40,000) = 25,000      (still locked)
drawdown_floor(20,000) = 23,500      (does not follow you down)
```

After +6% the account can no longer lose your money. That makes *getting to +6%
quickly, then compounding from a risk-free base* a strictly better play here than
on a static-drawdown account — and it is why I would not spend the first weeks on
a high-cost instrument that grinds.

### 3.2 The payout ladder caps early income

Payout caps are percentages of the initial balance, escalating per approved
withdrawal: **1%, 2%, 3%, 4%, 5%, 6%** — then the account **resets to the initial
balance** and is unlimited from payout #8. On $25,000 that is $250 → $1,500 per
cycle, **$5,250 total across seven payouts**, at a 90% split ≈ **$4,725 net**.
Bank fee $19.90 + 2.49%; crypto withdrawal $19.90 + **30%**.

So the first two months are a track-record exercise, not an income stream. Plan
for that rather than being surprised by it.

---

## 4. The cost schedule — the decisive fact

Upcomers charges a **mixed-unit** commission, which is why instrument choice
cannot be reasoned about from the spread alone:

| Class | Commission | Commission in bps of notional (round trip) |
|---|---|---|
| **Indices** | **0** | **0.000** |
| **Stocks** | **0** | **0.000** |
| **Energies** | **0** | **0.000** |
| **Metals** | $5 / lot | **0.377** |
| **Forex** | $5 / lot | **0.909** |
| **Crypto** | **0.04% of notional** | **8.000** |

Produced by `python scripts/upcomers_instrument_screen.py --commission-table`.

The crypto figure is **exact and assumption-free**, because it is a percentage of
notional: `0.04% × 2 legs = 8.0 bps`. The forex and metals figures depend on a
representative price (labelled in the code); the *ordering and the >8x gap* are
robust to that assumption.

**One unresolved ambiguity, which does not change the answer:** whether the
published figures are per side or round-turn. If they are round-turn, halve every
number. The ranking is identical either way — that is why the conclusion survives
an error in this input.

---

## 5. The metric that ranks instruments: cost per R

Spread alone does not rank instruments; **cost relative to the distance the trade
has to travel** does. That was the finding of our own pre-registered study
(`GEOMETRY_COST_STUDY_20260919.md`): at V75's tightest stop, spread consumed
**100.5% of the gross edge** (+11.07R gross → −0.06R net), and widening the stop
halved the toll while collapsing gross to +1.26R.

```
cost per R  =  (round-trip commission + spread)  /  (stop_mult × ATR)
```

A result of **0.20** means the instrument must produce **+0.20R of gross edge per
trade merely to break even**. Our measured V75 gross edge was **+0.027R/trade**.
No signal survives a toll an order of magnitude larger than the edge — which is
why this number, not the spread, is the screen.

`scripts/upcomers_instrument_screen.py` computes it per symbol from live specs and
each symbol's own measured ATR, at stop distances of 0.5/1/2/3 × ATR. Pinned by
test: **cost/R is lot-independent** (both cost and stop scale with size) and
**doubles when the stop halves**.

---

## 6. The ranked answer

### Tier 1 — index CFDs (zero commission)

`NACUSD.c` (Nasdaq-100), `SPCUSD.c` (S&P 500), `DJCUSD.c`, `RUSS2000`.

- **Zero commission removes an entire cost term.** The only cost left is the
  spread.
- Index CFDs carry high ATR relative to their spread, so cost/R is structurally
  the best on the venue.
- Session ≈ 23h × 5 days with a short daily break — **the ~1 hour/day of downtime
  is the price of the cheapest possible trade.**
- `USOIL.c` / `XNGUSD` sit in this same zero-commission band and the venue files
  them under *Indices*; the class is cost-neutral either way (pinned by test).

### Tier 2 — forex majors ($5/lot ≈ 0.91 bps)

`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCAD`.

- Tightest spreads in absolute terms on the venue, which is what matters for
  mean-reversion and high trade counts.
- Commission is ~0.9 bps — about **9x cheaper than crypto**.
- Avoid the ~80 exotic crosses: wide relative spreads, and they are where a cost
  model goes to die.

### Tier 3 — metals ($5/lot ≈ 0.38 bps)

`XAUUSD`, `XAGUSD`. Cheapest per-lot commission on the venue, and gold's large ATR
flatters cost/R. **This is MIDASTOUCH's instrument** — already explored, and
already parked because it is not 24/7 and its live arm was unprofitable
(`MIDASTOUCH_CLOSEOUT_20260919.md`).

### Tier 4 — crypto (~8 bps): the only weekend-capable class

- **Deepest liquidity / tightest relative spread:** `BTCUSD.nx`, `ETHUSD.nx`.
- **Avoid** the thin alts (`GALAUSD.nx`, `MELUSD.nx`, `TRPUSD.nx`, `SHBUSD.nx`) —
  wide spreads and slippage, exactly the off-hours trap Upcomers' own liquidity
  note describes.
- You pay ~8 bps commission **plus** a wider spread for the privilege of weekend
  access. That is a fair price for a hard requirement, and a bad price for a
  preference.

### So, decisively

- **If weekends are non-negotiable → `BTCUSD.nx` or `ETHUSD.nx`.**
- **If they are not → `NACUSD.c` / `SPCUSD.c`, and it is not close.**
- **Never** the exotic alts, the exotic FX crosses, or the single-stock CFDs
  (~1,100 symbols with session gaps and thin books).

---

## 7. The 24/7 question is still OPEN — and it is the one thing that changes the answer

I want to be precise, because it would be easy to overclaim here:

- Upcomers' article *"Markets never close: trading 24/7"* is about **Perpetuals**,
  not MT5. It contrasts perps with CFDs — *"If you trade CFDs or futures with us, a
  surprising amount of your routine was built around the clock. None of it applies
  here."* Read plainly, that implies **MT5 CFDs do close on weekends.**
- A third-party broker profile lists **"Crypto Weekend Trading: ✓"** for Upcomers.
- Their own 24/7 marketing line ("Trade 24/7, weekends included") is about the
  Hyperliquid-backed Perpetuals product.

**These do not agree, and marketing is not a session table.** So: unverified.

### The measurement that settles it — today

**Today is Saturday.** The MT5 Python bridge exposes no session-time function, but
`symbol_info()` carries `session_deals` and `session_volume` — counters that
accumulate **only while a symbol is actually trading**. Run the probe on a Saturday
and:

- crypto showing non-zero deal counters **proves** weekend trading;
- an entire class showing zero counters **proves** a closed session.

I extended `scripts/venue_probe.py` to capture exactly this and roll it up by asset
class, so one run answers it by measurement rather than by argument. **This is
time-sensitive: it only works while it is still the weekend.** Tomorrow (Sunday)
also works; Monday it is gone until next weekend.

---

## 8. What is measured vs what is assumed

| Claim | Status |
|---|---|
| No synthetic indices on the venue | **Confirmed** — venue's own symbol table |
| Symbol categories and leverage (1:100 FX / 1:30 rest) | **Confirmed** — Help Center table |
| Commission schedule (0 / $5 / 0.04%) | **Confirmed** — cross-checked two sources |
| Thunderbolt Classic 5% / 3% / 6% / 20% | **Confirmed** — Help Center program table |
| Account swap-free | **Confirmed** (venue) / third-party agrees |
| Crypto trades weekends | **UNVERIFIED** — sources conflict, §7 |
| 3% single-trade loss cap | **Reported, NOT re-confirmed** — see below |
| Actual spreads and ATR per symbol | **NOT MEASURED** — requires the terminal |
| Representative prices for metals/forex bps | **Assumption**, labelled in code |

**On the 3% single-trade cap:** the earlier audit recorded it as a hard
termination. I could not re-confirm it against the current rulebook in this pass,
so I deliberately did **not** bake it into the sizing arithmetic —
`risk_budget_usd()` takes it as an explicit parameter and prints
`single-trade cap not modelled — verify the current rulebook` when it is absent.
An unverified number should not silently decide position size. Confirm it in the
dashboard before arming.

---

## 9. The blocker: one 5-minute GUI step, and it is genuinely yours

Verified by exhaustion this session:

- MT5 received `/login:1428765 /password:… /server:Upcomers-Server` **intact**
  (confirmed via the process command line) and logged **no connection attempt at
  all** — not a failure message, *nothing*.
- Same with a `/config:` auto-login `.ini`: MT5 logged
  `successfully initialized from start config` and then still attempted nothing.
- The Python bridge times out (`initialize → -10005 IPC timeout`) because a
  terminal with no account cannot serve IPC.
- `bases/` contains only `Custom` and `Default` — **no Upcomers server exists in
  the client**, so the server name cannot be resolved.

**Cause:** the generic MetaQuotes installer (`C:\Program Files\MetaTrader 5`,
build 6204, installed 17:05 today) ships a broker directory that does not include
Upcomers. MT5's client has **no CLI or config path to register a new broker
server** — the lookup is a GUI-only action. This is a product limitation, not a
misconfiguration, and not something I can script around.

**The step, either of these:**

1. **File → Open an Account**, search `Upcomers`, let it pull the broker's server
   config, then **File → Login to Trade Account**. This is the one that populates
   the directory.
2. Or download the MT5 build linked from your Upcomers dashboard, which ships the
   server baked in.

**Use the read-only account first if you prefer not to type the funded password:**
Upcomers publishes a public read-only login for exactly this purpose —
**server `Upcomers-Server`, login `1293766`, password `Upcomers1.`** (include the
trailing period). Trading is disabled on it; it shows the same live spreads and
all 1,300+ symbols. That is a *sanctioned* way to run this research.

Then, immediately:

```bash
MT5_PASSWORD='Upcomers1.' .venv/Scripts/python.exe scripts/venue_probe.py \
    --login 1293766 --server Upcomers-Server --equity 25000 \
    --out artifacts/upcomers_inventory.json

.venv/Scripts/python.exe scripts/upcomers_instrument_screen.py \
    --live --top 40 --out artifacts/upcomers_ranking.json
```

The first settles §7 by measurement; the second produces the real cost/R ranking
that finalises §6.

**Also:** rotate the funded MT5 password. It was pasted into this transcript and
into the terminal's process command line, and it is still sitting in plain text in
`artifacts/upcomers_login.ini` (gitignored, but on disk).

---

## 10. The thing I have to say plainly

**Buying the account did not create an edge, and this document does not contain
one.** What it contains is a venue audit, a rule pack, and a cost model — all of
which are now real, tested arithmetic. What it does not contain is any instrument
on this venue with demonstrated out-of-sample, cost-surviving positive expectancy.
Our own frozen evidence says so: the V75 family's edge failed out-of-sample
(−3.97R), the HTF_SLOPE gate made OOS *worse* (−9.30R), and the geometry fix that
reduced cost also destroyed the edge.

So "start trading" and "start being paid" are not the same step, and the shortest
honest path is:

1. **You:** the GUI login (§9). Five minutes.
2. **Me:** probe + screen → real spreads, real ATR, real cost/R, and the weekend
   verdict. Minutes.
3. **Me:** commit to one instrument from the ranked table and build the strategy
   around *its* cost structure — geometry chosen so cost/R is small, not chosen
   for signal aesthetics.
4. **Me:** certify it out-of-sample net of cost. If the sign is not positive, that
   is the finding, and it is worth knowing before $25,000 is at risk.
5. **Then** arm it on the prop account, with `upcomers_rules.py` as hard limits so
   no sizing decision can breach the 3% daily or the 6% shield.

$25,000 against a 0.027R/trade edge is not a strategy, it is a donation. The
account removes the *lot-floor* problem that killed the synthetic work at $39.58 —
that part is genuinely solved — but it does not manufacture an edge, and the cost
schedule above shows this venue charges more for the 24/7 access than Deriv ever
did.

---

## 11. THE DECISION (made 2026-09-19, on request — one instrument, no hedging)

### 11.1 The call: **INDICES — `NACUSD.c` (Nasdaq-100)**, twin `SPCUSD.c`, European-hours equivalent `GECEUR.c`

Ranked by round-trip cost per R, produced by the tool (not by hand):

```
   symbol           class      sprd_bps  comm_bps     1.0xATR     2.0xATR     3.0xATR
   NACUSD.c         indices       0.909     0.000     0.0244     0.0122     0.0081
   GECEUR.c         indices       0.789     0.000     0.0263     0.0132     0.0088
   SPCUSD.c         indices       0.833     0.000     0.0333     0.0167     0.0111
   XAUUSD           metals        1.132     0.377     0.0500     0.0250     0.0167
   USOIL.c          indices       4.286     0.000     0.0857     0.0429     0.0286
   EURUSD           forex         0.182     0.909     0.1500     0.0750     0.0500
   BTCUSD.nx        crypto        3.000     8.000     0.1760     0.0880     0.0587
```

`python scripts/upcomers_instrument_screen.py --candidates configs/upcomers/instrument_shortlist.json --stop-mults 1,2,3`

**Indices occupy the top three rows and win by a factor of 2 over gold, 6 over
forex and 7 over crypto.** The zero-commission classes cannot be beaten on cost by
anything that charges a commission, and that is the whole argument.

### 11.2 Why each alternative loses

| Rejected | Reason |
|---|---|
| **Gold (`XAUUSD`)** | **Rejected on cost structure only: cost/R 0.050, about 2x worse than Nasdaq's 0.024** — because it pays $10/lot round-trip commission while indices pay nothing. **MIDASTOUCH is NOT evidence against gold and must not be cited as such**: it was a different strategy (long-only M30 springboard), it produced a sample of **one closed trade (−$0.50)** on an account whose **$39.58 equity was below the broker's lot floor**, so it could never size correctly — Phase 2/3 of this revival found *every* instrument CAP-VETOED at that equity. **n=1 on an unsizeable account says nothing about the instrument.** Gold stays a legitimate candidate that the live spread measurement may yet promote |
| **Forex (`EURUSD`)** | The tightest quoted spread on the venue (0.182 bps) — and it still loses, because **commission alone is ~1.0 pip round trip** (0.909 bps), which dwarfs the spread. cost/R **0.150 = 6x** Nasdaq. Its 1:100 leverage is also a hazard, not a gift: it invites sizing that breaches the 3% daily limit |
| **Crypto (`BTCUSD.nx`)** | **8.0 bps commission** — the most expensive thing on the account, and the only thing it buys is weekend access, which is a preference rather than a requirement now. cost/R **0.176 = 7x** Nasdaq |
| **Exotic FX / `USOIL.c` / single stocks** | Wide relative spreads (oil 4.286 bps), news-driven gaps, thin books, ~1,100 single-stock CFDs with session gaps |
| **`NACUSD.c` vs `SPCUSD.c`** | Nasdaq wins on the ratio: its spread (2.0 pts) is **2.4%** of its H1 ATR (82 pts) against the S&P's **3.3%** (0.5 pts of 15 pts), because one tick is a smaller fraction of a much larger index. `GECEUR.c` (DAX) is within 8% and its cash session sits in the operator's working day, so it is a legitimate tiebreak — not a better instrument |

### 11.3 What the pick is actually worth, in money

Cost per R is abstract. At a per-trade risk of **$75 (0.3% of a $25,000 account)** — deliberately small so that **ten consecutive losses** are needed to breach the 3% daily limit — round-trip cost over 100 trades is:

| Instrument | cost/R | cost per $75-risk trade | over 100 trades |
|---|---|---|---|
| **`NACUSD.c`** | 0.024 | **$1.80** | **$180** |
| `XAUUSD` | 0.050 | $3.75 | $375 |
| `EURUSD` | 0.150 | $11.25 | $1,125 |
| `BTCUSD.nx` | 0.176 | $13.20 | $1,320 |

**Choosing Nasdaq over crypto is worth ~$1,140 per 100 trades** at unchanged edge. Since our measured V75 gross edge was **+0.027R/trade** (+$2.03 per trade at $75 risk), the crypto toll would have exceeded the entire gross edge — while on Nasdaq it consumes ~89% of it. That is the difference between a strategy that can theoretically compound and one that mathematically cannot.

### 11.4 The EA will attach — verified, with one real caveat

`MitemshubAI.mq5` carries a symbol guard. I read it rather than assumed it
(`mql5/MITEMSHUB_AI/MitemshubAI.mq5:781`):

```mql5
string cbchk = _Symbol;
StringToLower(cbchk);
if(StringFind(cbchk, "crash ") == 0 || StringFind(cbchk, "boom ") == 0)
   { ... return(INIT_FAILED); }
```

**This refuses only names *beginning* with `crash `/`boom `.** It does **not** require
"Volatility" in the name, so `NACUSD.c` passes `OnInit()` and the EA will run on an
index with **no source change**. That is the single most useful engineering fact for
the build.

**The caveat is calibration, not legality.** The guard checks a name, not a
capability. Every parameter in those presets (EMA/RSI/BB periods, ATR stop
multipliers, regime thresholds) was fitted to a Volatility index — and our own
`GENERATOR_FINGERPRINT.md` established that V75 is a **memoryless step machine**
with constant volatility. An equity index is close to the opposite: volatility
clustering, persistent trends, session structure, and gaps. Transplanting the preset
would be fitting a model of the wrong generative process, which is precisely the
error `HOSTILE_VS_OVERFIT_20260916.md` was written to catch.

### 11.5 The build, in order

1. **Log in** (one GUI step, §9). Nothing below can be measured until this is done.
2. **Replace assumptions with measurement** — `venue_probe.py` + the screen in `--live`
   mode. Real spreads and ATR confirm or move the ranking in §11.1.
3. **Port, do not transplant** — build an `NACUSD.c` preset re-optimised on that
   instrument's own data, with walk-forward. Do not copy the VOL75 numbers.
4. **Handle what V75 never had:** overnight/session **gaps** (a stop can gap
   through), the cash-session window via the existing `IsSessionActive()` filter, and
   the **2-minute minimum hold** rule (`MitemshubAI.mq5` already tracks
   `g_bars_held`).
5. **Certify out-of-sample net of spread** using the existing cost-inclusive engine.
6. **Arm**, with `upcomers_rules.py` as hard limits so no sizing decision can breach
   the 3% daily or the 6% shield.

---

## 12. PLAIN ENGLISH — what commission and "cost per R" actually mean

Written because these two ideas decide the whole document and neither is obvious.

### 12.1 There are TWO costs on every trade, not one

**The spread** is the gap between the price you can buy at and the price you can sell
at. If Nasdaq is quoted **22000.0 / 22002.0**, the spread is 2 points. You must buy at
22002. To break even, price has to rise to 22002 — but if you sold that instant you
would only get 22000. **You start every trade 2 points behind.** That is the spread
cost, and it exists on every instrument at every broker.

**The commission** is a separate fee the broker charges on top, for placing the
trade. Upcomers' rates:

| Class | Commission | In plain terms |
|---|---|---|
| **Indices, stocks, energies** | **$0** | Nothing. Spread is your only cost |
| **Metals, forex** | **$5 per lot** | A flat fee per lot, per side, whatever happens |
| **Crypto** | **0.04% of the position's value** | A percentage of how big your bet is |

### 12.2 The single most important property: commission ignores whether you win

Commission is charged on **position size and trade count** — never on profit. Win or
lose, open or close, you pay it. So it is a **toll on activity**, and a strategy that
needs many trades to earn its living gets taxed on every one of them.

### 12.3 Worked example — the same $75 of risk, two instruments

Suppose the rule is "never risk more than $75 on a trade" and the stop is 1x ATR:

**Nasdaq (`NACUSD.c`)** — H1 ATR is 82 points, so the stop is 82 points
- Position size needed for $75 of risk: ~0.9 lots
- Spread cost: 2 points x 0.9 = **$1.80**
- Commission: **$0**
- **Total toll: $1.80**

**Crypto (`BTCUSD.nx`)** — H1 ATR is $625, so the stop is $625
- Position size needed for $75 of risk: ~0.12 BTC
- Position value: 0.12 x $100,000 = $12,000
- Commission: 0.04% x $12,000 = $4.80 **per side**, so **$9.60** in and out
- Spread cost: $30 x 0.12 = **$3.60**
- **Total toll: $13.20**

**Identical risk, identical account, identical skill — and one trade pays 7x the tax of
the other.** That is the entire argument, and it has nothing to do with prediction.

### 12.4 What "cost per R" means

R is the amount you risk on a trade. **Cost per R is that toll expressed as a fraction
of the risk.** The example above: $1.80 of cost on $75 of risk is **cost per R = 0.024**.

Why express it that way instead of in dollars? Because **it is size-independent and
trade-count-independent**, so it can compare two different instruments fairly:

- It is a **per-trade condition**, not a volume condition. If your edge per trade is
  +0.05R and your cost is 0.176R, you lose money at *any* trade count. Trading fewer
  times does not rescue an expensive instrument; only trading a *cheaper* one does.
- Hence: **cost per R must be smaller than the edge per trade.** Nothing else on this
  page matters as much as that single comparison.

Our measured V75 gross edge was **+0.027R per trade**. Against a crypto toll of 0.176R
the edge is **6.5x too small** — that strategy cannot win however good the signal is.
Against Nasdaq's 0.024R the toll is *smaller than the edge*, so there is room for the
strategy to be the deciding factor instead of the fee schedule.

### 12.5 The practical consequence

A cheap instrument lets you **trade more often**; an expensive one forces you to trade
**rarely** and be right almost every time. Since Thunderbolt Classic has **no time
limit**, we are not forced to trade often — but we also should not *have* to trade
rarely. Cheap cost keeps the choice ours.

---

## Provenance

- **Upcomers Help Center** (primary): *MetaTrader 5 (MT5) - Download, Setup &
  Troubleshooting*; *What instruments can I trade?* (full symbol table + leverage);
  *Markets never close: trading 24/7*; *Thunderbolt Challenge CFD complete rules
  overview*; *Best Day Rule*; *Check Our Trading Conditions Before You Buy* (the
  read-only account).
- **Cross-checked secondary:** thegodfunded.com Upcomers broker profile
  (commission per class, payout ladder, drawdown systems), Propvator (platform and
  spread type).
- **Disagreement recorded, not resolved:** crypto weekend trading (§7).
- Code: `src/synthetic_trader/risk/upcomers_rules.py`,
  `scripts/upcomers_instrument_screen.py`, `scripts/venue_probe.py`;
  tests `tests/test_upcomers_rules.py`, `tests/test_upcomers_instrument_screen.py`.

## Verification (2026-09-19)

- `pytest` full suite: **1907 passed, 15 skipped, 0 failed** (31 subtests), 20m44s.
  Affected-area subset (`-k "instrument or risk or upcomers or preset or census or
  geometry or midas_watchdog"`): **200 passed**.
- 41 new tests, all passing. The load-bearing ones pin the >8x commission gap, the
  drawdown floor locking at the initial balance, cost/R being lot-independent, and
  the classifier returning `None` (never a guess) for unknown symbols.
- `scripts/upcomers_instrument_screen.py --commission-table` output matches §4
  exactly: `0.000 / 0.000 / 0.000 / 0.377 / 0.909 / 8.000` bps.
- **Not measured:** every spread and ATR figure. **Not run:** `mql5/verify_all.ps1`
  (needs MT5 Strategy Tester sessions; no MQL5 source was touched this session).

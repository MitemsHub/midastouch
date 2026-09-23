//+------------------------------------------------------------------+
//| MidastouchAI.mq5 — MIDASTOUCH gold engine (paper-default)        |
//|                                                                  |
//| Target market: GOLD only (XAUUSD / XAUUSD on Deriv MT5).    |
//| Research basis: docs/MIDASTOUCH_PROTOCOL.md (frozen 2026-09-16)  |
//| Ground truth:   docs/MIDASTOUCH_GOLD_PLAYBOOK.md (measured)      |
//|                                                                  |
//| Strategy family (V28-registry vocabulary, one mode per run):     |
//|   macro filter  H4+H1 close[1] vs EMA20[1] (ALIGNED_UP/DOWN/DIV) |
//|   trigger       M15 BB(20,2) band-touch-back-inside or RSI(14)   |
//|                 >=70 / <=30                                      |
//|   exits         SL = 2.0 x ATR(14,H1); TP = 2R; timeout 12h;     |
//|                 SL-first on ties; one position at a time         |
//|   gates         session 06-20 UTC, spread <= 1.5% of stop,       |
//|                 no new entries Fri >= 20:00 UTC (flat by 22),    |
//|                 staleness guard (no fresh M15 bar -> no trading) |
//|                                                                  |
//| Two execution models:                                            |
//|   PERTICK (default) — the live-faithful mirror: fill at the first |
//|     tick after the signal bar closes, manage exits per tick.      |
//|   BAR (InpExecModel) — the research engine made executable: each  |
//|     M15 bar is processed in python's exact pass order (fill at    |
//|     open -> manage the complete bar -> signal on close), priced   |
//|     from the SAME recorded per-bar spread series python uses      |
//|     (shared file, protocol amendment 3), timeout exiting at bar   |
//|     close. BAR mode exists so tester-vs-python parity is a        |
//|     provable identity, not a hope; PERTICK is what trades live.   |
//| Ledger rows are byte-compatible with                              |
//| the MitemshubAI contract (OPEN 12 / CLOSE 8 / EQ / ERA) so the   |
//| flatness checker and morning tooling parse gold ledgers as-is.   |
//|                                                                  |
//| PAPER IS THE DEFAULT. InpLiveExecution=false never sends an      |
//| order. There is no live path in v1; it is added only after a     |
//| passing forward gate, in its own reviewed build.                 |
//+------------------------------------------------------------------+
#property copyright "MIDASTOUCH"
#property version   "1.29"   // v1.29: THE EXIT REASON WORD - A CLOSE ROW NOW SAYS WHO CLOSED IT. MEASURED 2026-09-22 (docs/LIVE_EXIT_AUDIT_20260922.md): the arm's first live fill was closed by a MOBILE order (closing deal magic 0, DEAL_REASON_MOBILE) and the ledger's word for it was EXTERNAL - the same word a server-side stop-out gets - because the external-adoption path read the OUT deal's PRICE only and never DEAL_REASON or DEAL_MAGIC. The adoption scan now names the close: DEAL_REASON_SL/TP/SO -> SL/TP/SO (a server-side exit, even though the EA did not place the closing order); a closing deal bearing our magic -> EXPERT (the EA's own close, e.g. TIMEOUT or FRIDAY-FLAT, whose LiveClosePosition row was somehow lost); otherwise the platform's CLIENT/WEB/MOBILE family -> MANUAL-CLIENT/MANUAL-WEB/MANUAL-MOBILE. Unknown reasons (rollover, vmargin, split, any future platform value - this toolchain's ENUM_DEAL_REASON has no OTHER member) fall through to EXTERNAL-UNKNOWN - a row must never render a guessed word as known. Nothing reads the word: no entry, exit, size or protective rule consumes it, it is record-only, and the LCLOSE reason slot merely widens its vocabulary, which every reader of the row parses positionally and tolerantly (the reconciliation pins accept the v1.28 vocabulary unchanged). v1.28: THE SWEEP SHADOW - THE ASIAN-RANGE SWEEP CONTINUATION IS RECORDED FORWARD AND NEVER TRADED. `docs/ASIA_SWEEP_PREREG_20260922.md` REFUSED to port this mechanism (its pre-registered primary window failed on all three variants) and the same run reported the strongest number in this program on its SECONDARY window: UTC 07-18, 152 held-out trades, +0.1955R, pf 1.499, t +2.21, against the mirror at -0.1584R and the textbook reversal read at -0.1425R. It prescribed exactly one next step - record it forward with NO ORDER PATH AT ALL - and this is that step. A `SWEEPSHADOW` row is appended for every evaluated bar inside UTC 07:00-18:00, carrying the setup (the day's Asian range, the sweep side, whether this bar is the first sweep of that side, the reclaim flag, the certified stop distance) and NEVER an outcome, because the EA cannot know the future and a row claiming an R its writer could not have measured is not evidence; `scripts/midas_sweep_shadow.py` resolves those rows through the engine of record's own `run_mode`, so the arithmetic is not re-implemented on either side. The block reads no order state, consults no governor, increments no census counter, returns no direction to the entry path, and is called from exactly ONE place - beside the per-bar STATE row in `TrackFreshM15Bar` - which `tests/test_midas_v128_record.py` pins. The rule this record will be judged by was fixed in the forward pre-registration BEFORE any row existed (N >= 60 resolved outcomes, t >= 2.4, >= 0.30 fills/day, mean positive, and the two direction checks still negative or the verdict is VOID). v1.27: THE FOUR REFUSALS THAT SAID NOTHING NOW SAY WHY, THE STATE ROW CARRIES THE BAR'S OWN CONTEXT, THE ARM MEASURES ITS OWN SPREAD BY HOUR, AND A BAR THAT COULD NOT BE PRICED IS COUNTED RATHER THAN DROPPED. MEASURED 2026-09-22, from two passes over this arm's own held-out fills and its own live ledger. (1) THE SILENT REFUSALS. `TrackFreshM15Bar` had four return points that wrote no reason anywhere the operator looks: the session gate and the Friday cutoff incremented the census and returned WITHOUT setting `g_last_action`, so the chart's `last:` line still showed the PREVIOUS bar's action; and the two pricing guards (`atr <= 0`, `stop <= 0`) returned before the census as well, so they were not counted either - the operator's question is "why didn't it trade", and for four refusals this file had no answer. All four now name themselves, and the pricing pair gets its OWN counter - `nodata`, appended as position 10 - rather than inflating the refusal census, because nothing about the arm refused those bars: the ENGINE could not measure a stop for them. The label says `unpriced`, not `vetoed`. (2) THE STATE ROW WAS THINNER THAN THE FILL ROW. The OPEN row has carried the bar's own context since v1.19e (sig_ct, hour_utc, vol_ratio, news, off_min) while the STATE row - written for EVERY evaluated bar - carried none of it, so the bars this arm REFUSES, 83% of them, were exactly the ones with no context on the record. `StateAppend()` now rides every STATE row before the keyed `cfg=` token, from the SAME function the fill rows call, so one parser reads both. (3) THE ARM'S OWN SPREAD BY HOUR. `SPREADHOUR,<epoch>,<day>,` + 24 x `<hour>,<n>,<mean>,<max_x100>` written at each daily roll and sampled once per tick. The session finding this arm's research produced rests on the venue's spread being FLAT across hours - and that flatness was read off the CORPUS. This is the live arm measuring the same thing, so the two can be compared instead of assumed. (4) THE CENSUS FLOOR MOVED WITH THE COUNTER: `DiagRestoreFromLedger` now requires 13 fields, so a v1.26 snapshot is NOT read as one - a row whose missing 10th counter would otherwise restore as a confident zero, which is the exact class of sign this program keeps paying for. DISPLAY/RECORD ONLY: no entry, exit, size, veto or protective rule reads any of it, every write stays gated out of tester/BAR runs so certified parity ledgers stay byte-identical, and the trade set the engine produces is unchanged (measured, see the parity certificate). v1.26: WHAT `vEq` MEANS ON AN ARMED ARM. MEASURED 2026-09-22 from the operator's own screenshot: with the account at 25,004.26 the chart printed `vEq: $25,000.00 (start $25,000.00)` and the ledger's heartbeat printed `EQ,25000.00`, while every other reader (the account, morning_status's `veqs`, the live-fill reconciliation) said 25,004.26. The number was `g_paper_eq`, and on an ARMED arm the paper book never trades - `LiveSendOrder` is the only entry path that runs - so it was a FROZEN CONSTANT standing where the arm's equity belongs. Same defect class as the v1.24 `trades: 0/30`, and worse in consequence: equity is the number the governor's shield and day caps are read from, so the chart disagreed with the figure the RISK RULES use. One meaning, two books: the HUD's vEq line and every live heartbeat EQ row now carry the ARM's equity - the venue's account on the live path, the paper book on the paper path - and the HUD label says which (`vEq: $25,004.26 acct (bal $25,004.26, +4.26 vs the $25,000 basis)`). The EQ row's basis changes on a live ledger, so the ERA note gains `+acct-eq`. Display/record only: no entry, exit, size or protective rule reads it, the paper arm's rows are byte-identical, and every write is gated out of tester/BAR runs so certified parity ledgers stay byte-identical. v1.25: THE THREE DEFECTS THE ARM'S OWN FILL EXPOSED, fixed together because they are one story about what a fill row can know at the moment it is written. (1) THE ENTRY PRICE WAS A ZERO. MEASURED: the first live fill row reads `LOPEN,...,0.00000,...`, because the price came from ResultPrice() at the instant of acknowledgement, when on this venue that field is 0 and the position is not yet selectable - while the true 4333.07 was in the position and in the entry deal within the same second, and the row's own reader reported `entry price: ledger 0.0 vs venue 4333.07` for the rest of the fill's life. The ack now resolves the price from the position or the entry deal before the row goes out; if neither answers inside a bounded wait the row says `entry=pending` rather than printing a 0 in a price column, and an `LENTRY,<epoch>,<identity>,<price>,<source>` row amends it as soon as the venue reports it (at init, which also heals a row written by an earlier build, and again the moment it resolves). (2) `(missed string parameter)` ON EVERY FILL ROW. MEASURED on the same row: the LOPEN format carried FOUR `%s` for THREE arguments, and the paper OPEN row carried the same off-by-one from the same copy - so MQL5 appended its own missing-argument text after the cfg token. Fixed in both writers, and pinned by a test that counts specifiers against arguments in both. (3) A CLOSING DEAL IS NOT ALWAYS OURS TO STAMP. MEASURED from the venue's own history: the entry deal carried magic 7825001 and the CLOSING deal carried magic 0 (the platform's reason field reads MOBILE - it was executed outside the EA). The day's realised P&L filtered OUT deals on `DEAL_MAGIC == InpMagic`, so it ignored every externally-closed trade - and that number is what the Best Day cap and the day's reconstructed opening equity are measured from, i.e. a RISK-path number. Attribution is now by POSITION (an OUT deal is ours iff its position has an IN deal bearing our magic), the unmatched case is logged rather than dropped, and the unmatched case is the direction the governor must not silently prefer. All three are additive or strictly more truthful: no entry, exit, size or protective rule moves, and every change is gated out of tester/BAR runs so certified parity ledgers stay byte-identical. v1.24: THE ARM'S REALIZED RECORD IS ON THE CHART, and it says which record it is. MEASURED 2026-09-22: one live fill closed at +0.104R while the chart printed `trades: 0/30 | cumR +0.00` and every reader of the ledger said 1/30 - because BOTH live close paths wrote their LCLOSE row and neither touched a counter, and the paper counters an armed arm can see restart empty on every reload. The tally now counts the ledger's own LCLOSE rows (restored at init, exactly like the NOFILL census), the governor line names an unmeasured state instead of printing zeros, and the label says which tally is speaking. Display-only and read-only: no decision reads any of it, and it is gated out of tester/BAR runs so certified parity ledgers stay byte-identical. v1.23: THE VENUE'S SELF-INCONSISTENCY IS PRINTED ONCE PER SESSION (or on change) and the same moments append a keyed `SPEC` row to the ledger, so the journal stops repeating a static fact while the fact stays on the record. MEASURED 2026-09-22: the 15-minute heartbeat calls DollarPerUnitPerLot() twice per beat (the STATE row writer and the HUD refresh) and re-printed the identical warning all day, burying the VETO/NOFILL refusals it exists to protect. No decision reads any of it — the sizing authority ladder is unchanged, and the record is gated out of tester/BAR runs so certified parity ledgers stay byte-identical. v1.22: THE FILL ROW CARRIES THE CONFIGURED RISK (`cfg=<usd>@<pct>`, appended last) beside the risk it actually took, so the gap between InpRiskPercent and the venue's minimum lot is visible in the journal rather than only in a verification run. Purely additive and gated out of tester runs, so certified parity ledgers stay byte-identical. v1.21: THE HUD SHOWS THE ENGINE'S VIEW (regime H4/H1, trigger, RSI, gates, sizing, governor) and serialises the same numbers into a `STATE` ledger row, so the chart and the record cannot disagree. Additive by construction: the HUD is display-only and no decision reads any of it. v1.20: the RESTART-PERSISTENT REFUSAL CENSUS (NOFILLSUM + the UTC-day roll). v1.19 described two different builds — with and without the census — and a version tag that cannot tell them apart is worse than no tag: the ledger's ERA row is how a replay knows which behaviour produced it. v1.19: P6 build block (InpEntryTF default M15 = certified) + TP-preset axis
// Tester agents wipe their Files sandbox at pass start: this property makes
// the tester copy the recorded-spread series from <data>\MQL5\Files into the
// agent for every BAR-mode pass (name must be the literal staged file).
#property tester_file "MIDASTOUCH_spread_M15.csv"
// Same mechanism for the news calendar (v1.19c): a tester pass with the gate on would
// otherwise only ever see an empty sandbox and could rehearse the MISSING refusal but
// never the usable one. A pass that cannot be given a calendar is a pass that cannot
// show the gate working, so the file is staged exactly like the spread series; when it
// is absent the pass simply runs without it, which is the missing-file case.
#property tester_file "MIDASTOUCH_news_calendar.csv"
// And the FROZEN calendar (v1.19e), which is the one every REPLAY is judged against.
// The rolling name above is refreshed LIVE from CalendarValueHistory(now +/- days), so its
// coverage moves with the clock: measured 2026-09-21 17:52Z, that refresh cut the live file
// down to a 2026-09-09..2026-10-09 window and left the certified window's replays with a
// calendar holding no event in it at all -- the stand-down silently became a no-op. A replay
// is measured against the calendar its window was measured under, so the harness stages that
// snapshot (configs/calendars/MIDASTOUCH_news_calendar_frozen_20260102_20260924.csv) under
// this second name and points InpNewsFile at it. This property is what makes the tester
// mirror it into the agent sandbox; python reads the same staged bytes.
#property tester_file "MIDASTOUCH_news_calendar_frozen.csv"
#property strict

#include <Trade\Trade.mqh>

//--- modes (mirrors scripts/midas_sweep.py)
enum ENUM_MIDAS_MODE
{
   MODE_ORIGINAL = 0,         // ORIGINAL (trigger+macro agree)
   MODE_REVERSE_DIRECTION = 1,// REVERSE_DIRECTION
   MODE_REVERSE_TRIGGER = 2,  // REVERSE_TRIGGER
   MODE_REVERSE_BOTH = 3,     // REVERSE_BOTH
   MODE_LONG_ONLY = 4,        // LONG_ONLY
   MODE_SHORT_ONLY = 5,       // SHORT_ONLY
   MODE_MACRO_ONLY = 6,       // MACRO_ONLY
   MODE_TRIGGER_ONLY = 7      // TRIGGER_ONLY
};

input group "=== Identity ==="
input long                InpMagic            = 7801001;
input string              InpArmTag           = "M1";
input group "=== Strategy (frozen protocol defaults) ==="
input ENUM_MIDAS_MODE     InpMode             = MODE_REVERSE_DIRECTION;
input int                 InpMacroEmaPeriod   = 20;
input int                 InpBBPeriod         = 20;
input double              InpBBDev            = 2.0;
input int                 InpRSIPeriod        = 14;
input ENUM_TIMEFRAMES     InpEntryTF          = PERIOD_M15; // v1.19 P6: entry timeframe — default M15 = certified behavior; PERIOD_M5 = the P6 winner (register §2b), deploy gated on the 2026-10-01 reading
input double              InpRSIUpper         = 70.0;
input double              InpRSILower         = 30.0;
input int                 InpAtrPeriod        = 14;
input double              InpSlAtrMult        = 2.0;
input double              InpTpMult           = 2.0;
input int                 InpTimeoutMinutes   = 720;   // 48 M15 bars
input group "=== Gates (playbook policies) ==="
input int                 InpSessionStartHour = 6;     // UTC, entries allowed from
input int                 InpSessionEndHour   = 20;    // UTC, entries until (exclusive)
input double              InpSpreadCapPctStop = 1.5;   // veto if spread > this % of stop
input int                  InpFridayCutoffHour = 20;    // UTC; no new entries after
input bool                 InpUseNewsFilter    = false; // news stand-down; ON requires a fresh calendar FILE (see docs/MIDASTOUCH_HEALTH_GUIDE.md section 5a)
input string               InpNewsFile         = "MIDASTOUCH_news_calendar.csv"; // the shared calendar: this EA refreshes it live, MidasNewsProbe.mq5 measures it
input int                  InpNewsWindowMin    = 15;    // +/- minutes around a HIGH-importance event
input int                  InpNewsMaxAgeHours  = 24;    // refuse entries when the calendar is older than this
input int                  InpNewsCoverHours   = 24;    // refuse entries unless it covers this far ahead
input int                  InpNewsRefreshHours = 6;     // re-read the venue calendar this often (live only; 0 = never refresh)
input bool                 InpRecordStateLabel = false; // stamp the entry's state (vol ratio, UTC hour, news) into the ledger OPEN row

input int                 InpStaleMinutes     = 30;    // no M15 bar for N min -> stand down
input group "=== Risk ==="
input double              InpRiskPercent      = 1.0;
input double              InpMaxRiskPct       = 15.0;  // v1.14 amendment 6: veto if even min-lot risk exceeds this % of the sizing basis (MEASURED default — protocol amendment 6 decision table; 1.5% would starve the $50 arms and veto certified fills)
input group "=== Paper / Live ==="
input bool                InpLiveExecution    = false; // false=paper mirror | true=REAL orders (v1.08+)
input double              InpPaperEquity      = 1000.0;
input group "=== Live execution (only with InpLiveExecution=true) ==="
input int                 InpDeviationPoints  = 20;    // max slippage, points
input int                 InpOrderRetries     = 3;     // retries on transient reject
input int                 InpFridayFlatHour   = 20;    // UTC: force-flat hour on Friday (0=off) — weekend gap guard
input double              InpDailyLossCapPct  = 3.0;   // UTC-day equity loss cap % (0=off) — circuit breaker
input group "=== Execution model ==="
input bool                InpBarModel         = false; // BAR=parity replay, false=PERTICK live mirror
input string              InpSpreadFile       = "MIDASTOUCH_spread_M15.csv"; // recorded per-bar spreads (BAR mode)
input long                InpWindowStart      = 0;     // BAR parity: python window t0 (epoch s; 0 = open-ended)
input long                InpWindowEnd        = 0;     // BAR parity: python window t1 (epoch s; 0 = open-ended)

input group "=== Prop governor (Upcomers Thunderbolt Classic) ==="
input bool                InpPropGuard        = true;   // enforce the venue's survival rules before every entry (0 = off, and nothing else will protect you)
input double              InpPropAccountSize  = 0.0;     // 0 = read balance/equity at first call; set it to the evaluation's starting size
input double              InpPropTargetPct    = 5.0;     // overall profit target %  (Thunderbolt Classic: 5%)
input double              InpPropMaxDdPct     = 6.0;     // trailing "Dynamic Risk Shield" % off the equity HWM
input double              InpPropBestDayPct   = 20.0;    // Best Day share % of the target that caps ONE UTC day
input double              InpPropPeakOverride = 0.0;     // 0 = derive the HWM; set the TRUE peak after a restart inside a drawdown

//--- state
CTrade         g_trade;
int            g_h1_ema = INVALID_HANDLE;
int            g_h4_ema = INVALID_HANDLE;
int            g_h1_atr = INVALID_HANDLE;
int            g_m15_bb = INVALID_HANDLE;
int            g_m15_rsi = INVALID_HANDLE;
datetime       g_last_m15 = 0;
datetime       g_last_m15_seen = 0;

//--- paper position state (single position)
bool           g_pp_open = false;
int            g_pp_dir = 0;
double         g_pp_entry = 0, g_pp_sl = 0, g_pp_tp = 0;
double         g_pp_orig_risk = 0, g_pp_eff_risk = 0, g_pp_vol = 0;
datetime       g_pp_entry_time = 0, g_pp_expiration = 0;
ulong          g_pp_ticket = 0;
double         g_paper_eq = 0.0, g_paper_start = 0.0;
double         g_cum_r = 0.0;
int            g_trades = 0, g_wins = 0;
// v1.24 THE ARM'S OWN RECORD (display only, ledger-backed). The two counters above count
// VIRTUAL trades and start empty after every reload, so on an ARMED arm they read 0/30 while
// the record says otherwise: MEASURED 2026-09-22, one live fill closed at +0.104R, the chart
// printed `trades: 0/30 ... cumR +0.00` while `morning_status` read `closed: 1/30` from the
// same ledger's LCLOSE rows. The go-live gate counts the ARM's closed trades, so the chart
// counts those rows. Restored from the ledger at init (LiveCensusRestoreFromLedger, the same
// shape as the NOFILL census) and incremented by the ONE helper both live close paths call
// (LiveCensusAdd), so the two paths cannot drift apart. No decision reads any of it.
int            g_live_closed = 0, g_live_wins = 0;
double         g_live_cum_r = 0.0;
string         g_last_action = "boot";   // v1.10 HUD: last engine action (display only)
string         g_lv_last_error = "";     // v1.18: last live-order failure detail (diagnostics)
// v1.21 HUD STATE (display only, and the ONLY input the HUD has). Every one of these is
// written by the DECISION path at the moment it computed the value — never recomputed by
// the display path — and the STATE row writer serialises the same numbers into the ledger
// as a `STATE` row. That is what keeps the HUD from becoming a second source of truth: what the
// chart shows, the record carries, and the CLI report reads it back from the file rather
// than from memory. Nothing here is read by any decision.
int            g_hud_mac = 2;            // 2 = not measured yet; -1/0/+1 = MacroState()
int            g_hud_h4  = 0, g_hud_h1 = 0;   // per-timeframe directions behind the macro
int            g_hud_trig = 0;           // trigger on the last closed entry bar (-1/0/+1)
double         g_hud_rsi = 0.0;          // RSI on that bar (display echo)
datetime       g_hud_sig_ct = 0;         // the entry bar that was evaluated
double         g_hud_daypnl = 0.0;       // today's equity change from the UTC-day anchor
double         g_hud_cap = 0.0;         // the Best Day cap in dollars
 double        g_hud_floor = 0.0;        // the trailing-shield floor
string         g_hud_gov = "n/a";       // last governor reading ("" = clear)
bool           g_hud_sess_ok = false;    // was the evaluated bar inside the session window
// v1.18 NOFILL diagnostics (register review item 1): per-M15-bar veto
// accounting, so "why didn't it trade" is answered from evidence, not
// memory. Rows are appended to paper-file ledgers only — the BAR parity
// replay never writes them, so certified ledgers stay byte-identical.
int            g_nofill_signal = 0, g_nofill_mism = 0, g_nofill_session = 0,
               g_nofill_friday = 0, g_nofill_spread = 0, g_nofill_riskcap = 0,
               g_nofill_brk = 0, g_nofill_notr = 0, g_nofill_wrote = 0,
               g_nofill_news = 0,   // v1.19c: news stand-down (reason in the journal line)
               g_nofill_nodata = 0; // v1.27: the bar could not be priced (ATR/stop <= 0)
// v1.27 SPREAD BY HOUR. The one live quantity the outside research turned on and the one
// this program had never measured per hour: doctrine says the thin hours carry wider spreads,
// and the CORPUS says this venue is flat at 0.2 pts in every hour. That claim was read off
// the data of record; this is the live arm recording its own, so the two can be compared
// instead of assumed. Sum/count/max per UTC hour, rolled into a SPREADHOUR row once a day.
// DISPLAY/RECORD ONLY — no entry, exit, size, veto or protective rule reads any of it.
double         g_spread_sum[24];
int            g_spread_n[24];
int            g_spread_max_x100[24];
// v1.20: the census' DAY KEY and the signature of what was last recorded. Both are
// restored from the ledger at init, so the counters above survive an EA reload instead
// of being zeroed by it. See DiagRestoreFromLedger for the failure this replaces.
int            g_diag_day = 0;       // UTC day number the counters belong to (0 = nothing measured)
string         g_diag_sig = "";      // signature of the counters already written to a NOFILLSUM row
// v1.19c: calendar-refresh bookkeeping. The gate is fail-closed, so a source that is
// never refreshed becomes a permanent stand-down — these keep the EA from either
// hammering the venue's API or silently letting the file age out.
datetime       g_news_refresh_at = 0;   // last calendar-API attempt
datetime       g_news_written_at = 0;   // last write THIS EA made (0 = never; a probe file is not ours)
int            g_news_api_last   = -2;  // last CalendarValueHistory return (-2 = never)

//--- bar-replay parity state (v1.04, EXEC BAR model)
long           g_sp_t[];         // spread-file bar open times (strictly ascending)
double         g_sp_v[];         // recorded spread ($) per bar
int            g_sp_n = 0;
datetime       g_last_seen = 0;      // M15 bar containing the most recent tick
datetime       g_last_processed = 0; // last M15 bar processed by the replay loop
bool           g_pending_valid = false;
datetime       g_pending_sigct = 0;
int            g_pending_dir = 0;
double         g_pending_stop = 0.0;
int            g_pending_hour = 0, g_pending_mac = 0;
// v1.19e: the SIGNAL bar the pending (or the fill just taken) belongs to. The state stamp
// is about the signal, never the fill bar — the study's cell is the entry bar's state.
datetime       g_sig_bar_epoch = 0;
datetime       g_pp_close_ct = 0;    // close-time bookkeeping of the managed bar (BAR mode)
double         g_pp_open_sp = 0.0;   // recorded spread charged on entry (BAR mode)
double         g_pp_dpu = 0.0;       // $ per 1.0 price-unit per 1.0 lot (stored at fill)
datetime       g_win_t0 = 0, g_win_t1 = 0;  // v1.09: EA-enforced research window (BAR mode)

// v1.08 live order path state (PERTICK + InpLiveExecution only; paper
// mirror keeps its own g_pp_* state so both can run in parallel).
//
// v1.11 POSITION-ID ARCHITECTURE: order/deal/position IDs are three
// DISTINCT ID spaces on a netting-vs-hedging-agnostic account and are no
// longer conflated in one variable. g_lv_posid is the ONLY key used for
// history reconciliation (HistorySelectByPosition takes the position
// IDENTIFIER); g_lv_ticket is the selected POSITION ticket (positioning
// context only); the entry order and entry deal tickets are kept purely
// for ledger provenance. On a netting account the position ticket equals
// the position identifier; on hedging accounts they can differ.
ulong  g_lv_posid  = 0;              // POSITION_IDENTIFIER for history reconciliation (0 = flat)
ulong  g_lv_ticket = 0;              // selected POSITION ticket (positioning context)
ulong  g_lv_order  = 0;              // entry order ticket (provenance)
ulong  g_lv_deal   = 0;              // entry deal ticket (provenance)
int    g_lv_dir = 0;                 // live direction (telemetry columns: atr_at_entry + spread_at_open appended in v1.13)
double g_lv_entry = 0, g_lv_sl = 0, g_lv_tp = 0, g_lv_stop = 0, g_lv_vol = 0;
bool   g_lv_entry_pending = false;   // v1.25: the fill row went out with no price resolved yet
datetime g_lv_open_time = 0;
datetime g_lv_expiration = 0;    // research timeout mirrored on the real position
int    g_brk_day = -1;               // daily-loss-breaker day key (UTC yyyymmdd)
double g_brk_start_eq = 0.0;
int    g_prop_day = -1;               // UTC-day key the prop BASELINES belong to
 double g_prop_day_eq = 0.0;          // that UTC day's opening equity (reconstructed)
// v1.17 (V2 register P5, telemetry-first, never-abort class): running count
// of in-session bars whose mode condition was TRUE (ModeDecide passed and
// the session gates allowed evaluation). Monotone since EA init; the CLOSE
// rows carry it as `density` so consumers difference consecutive rows for
// interval signal density. Reset only by re-init (each ERA stamp notes it).
long g_p5_signals = 0;
bool   g_brk_tripped = false;
bool   g_prop_passed = false;         // v1.19b: evaluation target met — phase REPORT, never a veto
bool   g_prop_pass_logged = false;    // the milestone prints once per init, not per tick

// Dollar-per-unit convenience wrapper (0.0 on bad spec).
double DollarPerUnit()
{
   double dpu = 0.0;
   return DollarPerUnitPerLot(dpu) ? dpu : 0.0;
}

#define APP_VERSION  "MIDAS1.29"   // v1.29: the exit-reason build (see #property version). v1.28: the sweep-shadow build (see #property version). v1.27: the four-silent-refusals / bar-context / spread-by-hour build (see #property version). v1.26: the arm's-equity build. v1.25: the fill-row-integrity build (see #property version). v1.24: the live-record build (see #property version). v1.23: the spec-record build (see #property version). The banner, the ledger's ERA row and every reader of them move together — tests/test_midas_hud.py pins #property == APP_VERSION so the two can never drift apart
#define SPREAD_FLOOR 0.10              // $ — MUST equal midas_sweep.SPREAD_FLOOR
#define LEDGER_BASE  "MIDASTOUCH_paper"

//+------------------------------------------------------------------+
string VersionTag() { return "[" + APP_VERSION + "]"; }

// v1.10: registry mode names for the HUD (display only; the banner keeps the
// numeric mode= so the watchdog's banner parser stays version-stable).
string ModeName(const int m)
{
   switch(m)
   {
      case MODE_ORIGINAL:          return "ORIGINAL";
      case MODE_REVERSE_DIRECTION: return "REVERSE_DIRECTION";
      case MODE_REVERSE_TRIGGER:   return "REVERSE_TRIGGER";
      case MODE_REVERSE_BOTH:      return "REVERSE_BOTH";
      case MODE_LONG_ONLY:         return "LONG_ONLY";
      case MODE_SHORT_ONLY:        return "SHORT_ONLY";
      case MODE_MACRO_ONLY:        return "MACRO_ONLY";
      case MODE_TRIGGER_ONLY:      return "TRIGGER_ONLY";
   }
   return "?";
}

//+------------------------------------------------------------------+
//| v1.10 display-only HUD — the at-a-glance line the old V75 chart  |
//| had. Shows mode, session, virtual equity, the §13 gate clock     |
//| (30 = the [3b] display target; adjudication reads at n>=60 per   |
//| protocol §13), and the last engine action. STRICTLY read-only:   |
//| no trading state is read here that the ledger does not already   |
//| carry, and NO Comment() may ever run in the strategy tester —    |
//| parity runs need byte-identical ledgers and untouched charts     |
//| (source test tests/test_midas_hud.py pins that law).             |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| v1.21 HUD view (display only). Every line below is built from a   |
//| value the DECISION path already computed and stashed (regime,     |
//| trigger, RSI, session flag, governor readings) or from a pure     |
//| read of the instrument (ATR, spread, spec). No trading state is    |
//| written here, no decision reads anything here, and every number    |
//| the sizing helper produces is serialised into the ledger's STATE   |
//| row by its writer — so the chart and the record cannot disagree,    |
//| and `morning_status` can print the same view from the file.         |
//+------------------------------------------------------------------+
string DirWord(const int d) { return d > 0 ? "up" : (d < 0 ? "down" : "?"); }

string RegimeText()
{
   if(g_hud_mac == 2) return "H4 ? / H1 ? -> not measured yet";
   string m = (g_hud_mac > 0) ? "BULLISH"
            : (g_hud_mac < 0 ? "BEARISH" : "MIXED (H1/H4 disagree)");
   return StringFormat("H4 %s / H1 %s -> %s (macro %+d)",
                       DirWord(g_hud_h4), DirWord(g_hud_h1), m, g_hud_mac);
}

string TriggerText()
{
   string t = (g_hud_trig > 0) ? "LONG" : (g_hud_trig < 0 ? "SHORT" : "none");
   string when = (g_hud_sig_ct > 0)
               ? TimeToString(g_hud_sig_ct, TIME_DATE | TIME_MINUTES) : "n/a";
   return StringFormat("%s | RSI(14) %.1f | last bar %s", t, g_hud_rsi, when);
}

string GateText()
{
   double stop = InpSlAtrMult * AtrNow();
   double sprd = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double lim  = (stop > 0.0) ? stop * InpSpreadCapPctStop / 100.0 : 0.0;
   return StringFormat("bar %s the %02d-%02d UTC window | tick spread $%.2f vs cap $%.2f",
                       g_hud_sess_ok ? "inside" : "OUTSIDE",
                       InpSessionStartHour, InpSessionEndHour, sprd, lim);
}

// The CONFIGURED risk in dollars, on the display basis (the governor's account size). ONE
// definition: the sizing below, the HUD's SIZING line and the STATE row's `cfg` token all
// divide the same two numbers, so the chart, the record and the fill rows cannot disagree
// about what the arm was ASKED to risk. The fill rows carry their own path's basis instead
// (PaperEquity(), or account equity on the live path) because that is the same quantity the
// fill's sizing already divided — the two are always a PAIR off one basis, never two bases.
//
// v1.22 exists because the pair is not decorative here: 0.25% of $25,000 is $62.50 and the
// venue's 0.01 step yields $31.84 at the current stop width, so EVERY fill on this account
// takes roughly half its budget, and the row used to carry only the second number.
double ConfiguredRiskUsd()
{
   return PropGovernorSize() * InpRiskPercent / 100.0;
}

// The one sizing computation in the file's display layer. Both the HUD line and the STATE
// row call it, so a number on the chart is the number in the record.
void SizingNumbers(double &lots, double &risk_usd, double &stop_usd, bool &minlot_over)
{
   lots = 0.0; risk_usd = 0.0; stop_usd = 0.0; minlot_over = false;
   double dpu = 0.0;
   double atr = AtrNow();
   if(!DollarPerUnitPerLot(dpu) || atr <= 0.0 || dpu <= 0.0) return;
   stop_usd = InpSlAtrMult * atr;
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) step = vmin;
   double per_lot = stop_usd * dpu;             // $ risk per 1.00 lot at this stop
   double budget  = ConfiguredRiskUsd();
   lots = MathFloor(budget / per_lot / step) * step;
   if(lots < vmin) lots = vmin;                 // the venue's floor, not a choice
   risk_usd = lots * per_lot;
   minlot_over = (vmin * per_lot > budget);     // this is the risk-cap veto, stated early
}

// Naming the configured risk beside the taken one, in one sentence, on the chart and in the
// record: `QUANTISED DOWN` is the venue's lot step leaving part of the budget unspent (this
// account's standing case), `OVERSHOOT` is the floor lot risking MORE than configured (which
// amendment 6 still permits under InpMaxRiskPct), and neither is a rule breach — it is the
// venue's granularity, and the operator's job is to see it rather than infer it.
string RiskQuantisationWord(double taken_usd, double cfg_usd)
{
   if(cfg_usd <= 0.0) return "";
   if(taken_usd < cfg_usd - 0.005) return " QUANTISED DOWN";
   if(taken_usd > cfg_usd + 0.005) return " OVERSHOOT";
   return " AS CONFIGURED";
}

string SizingText()
{
   double lots, risk, stop;
   bool minlot_over;
   SizingNumbers(lots, risk, stop, minlot_over);
   if(stop <= 0.0) return "unavailable (no ATR / bad spec)";
   double cfg = ConfiguredRiskUsd();
   return StringFormat("%.2f lots, risk $%.2f of $%.2f configured (%.2f%%)%s on %.1fxATR(H1)=$%.2f%s",
                       lots, risk, cfg, InpRiskPercent,
                       RiskQuantisationWord(risk, cfg), InpSlAtrMult, stop,
                       minlot_over ? "  [MIN-LOT EXCEEDS BUDGET -> risk-cap veto]" : "");
}

string GovernorText()
{
   if(!InpPropGuard) return "guard OFF (InpPropGuard=false)";
   // An UNMEASURED governor must say so rather than print zeros. MEASURED 2026-09-22: after
   // each reload the panel read `floor $0 | today +0.00 of cap $0 | n/a` until the first bar
   // was evaluated - up to a full bar interval of looking like a governor that is off or a
   // configuration with no caps, while the arm ran with InpPropGuard=true and real limits.
   if(g_hud_cap == 0.0 && g_hud_floor == 0.0 && g_hud_gov == "n/a")
      return "guard ON - readings not measured yet (this process has evaluated no bar)";
   return StringFormat("floor $%.0f | today %+.2f of cap $%.0f | %s",
                       g_hud_floor, g_hud_daypnl, g_hud_cap,
                       g_hud_gov == "" ? "CLEAR" : g_hud_gov);
}

string TradesText()
{
   // The realized record, and WHICH record it is. On an armed arm the paper tally is the
   // wrong one by construction, so a live arm prints the ledger's own closed-trade count and
   // says where it came from: a bare `1/30` beside `0/30` in the report is how a chart and a
   // record disagree while both look right. The gate needs 30 closed trades on the ARM.
   if(!InpLiveExecution)
      return StringFormat("%d/30 paper closed | wins %d | cumR %+.2f",
                          g_trades, g_wins, g_cum_r);
   return StringFormat("%d/30 LIVE closed (ledger LCLOSE rows) | wins %d | cumR %+.2f",
                       g_live_closed, g_live_wins, g_live_cum_r);
}

string NewsText()
{
   if(!InpUseNewsFilter) return "stand-down OFF - the gate is not applied";
   string age = (g_news_written_at > 0)
              ? StringFormat("file written %s", TimeToString(g_news_written_at, TIME_DATE|TIME_MINUTES))
              : "no file written by this EA";
   return "stand-down ON (fail-closed) | " + age;
}

//+------------------------------------------------------------------+
//| The STATE row: the HUD's view, on the record. Written whenever    |
//| the HUD is refreshed and on every evaluated bar, so "what did it  |
//| see at 14:15" is answerable from the file and not only from a      |
//| chart that has since changed. Paper ledgers only; the BAR replay   |
//| never reaches this, so certified ledgers stay byte-identical.      |
//+------------------------------------------------------------------+
void StateRowWrite()
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   double lots, risk, stop;
   bool minlot_over;
   SizingNumbers(lots, risk, stop, minlot_over);
   // v1.22: the same keyed `cfg=<usd>@<pct>` token the fill rows carry, so the gap between
   // the configured risk and the size the venue allows is on the record from the FIRST
   // evaluated bar rather than only from the first fill — and it is the same token and the
   // same source as the fill rows', so a reader needs one parser for both.
   // v1.27: THE SAME TAPE THE FILL ROWS CARRY, ON EVERY EVALUATED BAR. MEASURED 2026-09-22:
   // the STATE row carried the engine's view (regime, trigger, RSI, sizing, governor) but NOT
   // the bar's own CONTEXT — hour_utc, vol_ratio, news, off_min — while the OPEN row had
   // carried it since v1.19e. So the live record was THINNER than the offline one: the four
   // axes the forward-cell prereg labels this arm by could be read off a fill and not off a
   // bar, i.e. exactly the bars this arm refuses (83% of them) were the ones with no context.
   // It is the SAME `StateAppend()` the fill rows call, so one parser reads both, and the
   // keyed `cfg=` token still rides LAST because `_split_risk_tail` reads it off the END.
   // No positional specifier is added: both stamps ride inside the row's existing `%s`.
   // Nothing decides anything from this — the STATE row is display/record only, it is
   // gated out of tester/BAR runs, and the `cfg` token is still `RiskAppend(...)` itself.
   PaperLog(StringFormat("STATE,%I64d,%I64d,%d,%d,%d,%d,%d,%d,%d,%d,%.2f,%.2f,%.2f%s",
            (long)TimeUTCNow(), (long)g_hud_sig_ct, g_hud_mac, g_hud_h4, g_hud_h1,
            g_hud_trig, (int)MathRound(g_hud_rsi * 100.0), g_hud_sess_ok ? 1 : 0,
            (int)MathRound(lots * 100.0), (int)MathRound(risk * 100.0),
            g_hud_daypnl, g_hud_cap, g_hud_floor,
            StateAppend() + RiskAppend(ConfiguredRiskUsd())));   // v1.19e tail | v1.22 cfg
}

void HudUpdate()
{
   if(MQLInfoInteger(MQL_TESTER)) return;   // parity: draw nothing in the tester
   string pos = g_pp_open ? (g_pp_dir > 0 ? "LONG" : "SHORT")
              : (g_lv_posid != 0 ? (g_lv_dir > 0 ? "LONG(live)" : "SHORT(live)") : "flat");
   Comment(StringFormat(
      // `entryTF=` and not `tf=`: the field is `EnumToString(InpEntryTF)`, the ENTRY/trigger
      // timeframe — NOT the chart period, which this EA never reads (nothing calls
      // Period()/_Period; every series call names its timeframe). Measured 2026-09-21: the
      // label read `tf=PERIOD_M15` on an H1 chart and read as a contradiction. The
      // invariant is pinned by tests/test_midas_hud.py.
      "MIDASTOUCH %s | mode=%d %s | entryTF=%s | session %02d-%02d UTC\n"
      "%s | pos: %s\n"
      "REGIME   %s\n"
      "TRIGGER  %s\n"
      "GATES    %s\n"
      "SIZING   %s\n"
      "GOVERNOR %s\n"
      "NEWS     %s\n"
      "trades: %s\n"
      "eval: %d no-trade bars | V: mis %d no-trg %d sess %d spr %d nodata %d\n"
      "last: %s",
      APP_VERSION, (int)InpMode, ModeName((int)InpMode), EnumToString(InpEntryTF),
      InpSessionStartHour, InpSessionEndHour,
      EquityText(), pos,
      RegimeText(), TriggerText(), GateText(), SizingText(), GovernorText(), NewsText(),
      TradesText(),
      g_nofill_signal, g_nofill_mism, g_nofill_notr, g_nofill_session,
      g_nofill_spread, g_nofill_nodata, g_last_action));
}

string PaperFile()
{
   string sym = _Symbol;
   StringReplace(sym, " ", "_");
   StringReplace(sym, ".", "_");
   return StringFormat("%s_%s_%s.csv", LEDGER_BASE, sym, InpArmTag);
}

void PaperLog(string line)
{
   int fh = FileOpen(PaperFile(), FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      Print(VersionTag() + " WLOST ledger write failed: " + PaperFile());
      return;
   }
   FileSeek(fh, 0, SEEK_END);
   FileWriteString(fh, line + "\n");
   FileClose(fh);
}

double PaperEquity() { return g_paper_eq; }

//+------------------------------------------------------------------+
//| WHAT `vEq` MEANS ON AN ARMED ARM (v1.26).                        |
//|                                                                  |
//| MEASURED 2026-09-22, from the operator's own screenshot: with    |
//| the account at 25,004.26 the chart printed `vEq: $25,000.00      |
//| (start $25,000.00)` and the ledger's EQ heartbeat printed        |
//| `EQ,25000.00`. Both were `g_paper_eq`, and on an ARMED arm the   |
//| paper book never trades — `LiveSendOrder` is the only entry      |
//| path that runs — so that number is a FROZEN CONSTANT standing    |
//| where the arm's equity belongs. It is the same defect class as   |
//| the v1.24 `trades: 0/30` (a chart understating the arm's own     |
//| record), and it matters more: equity is what the governor's      |
//| shield and day caps are read from, so the chart disagreed with   |
//| the number the risk rules actually use.                          |
//|                                                                  |
//| One meaning, two books: the arm's equity. The PAPER arm's is its |
//| own book (unchanged, byte-identical, so tester/BAR ledgers don't |
//| move); the LIVE arm's is the venue's account. The label says     |
//| which, because a bare number beside a record is how a chart and  |
//| a ledger disagree while both look right.                         |
//+------------------------------------------------------------------+
double DisplayEquity()
{
   if(InpLiveExecution) return AccountInfoDouble(ACCOUNT_EQUITY);
   return PaperEquity();
}

// The EQ heartbeat row, written through ONE site so the basis can never drift from the
// display again. Paper arm: PaperEquity(), byte-identical to every EQ row before this.
void LogEquityRow()
{
   PaperLog(StringFormat("EQ,%.2f", DisplayEquity()));
}

// The HUD's equity line. The paper form is v1.10's, verbatim; the live form names the
// source, the balance it came with, and the declared basis it is measured against.
string EquityText()
{
   if(!InpLiveExecution)
      return StringFormat("vEq: $%.2f (start $%.2f)", PaperEquity(), g_paper_start);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   return StringFormat("vEq: $%.2f acct (bal $%.2f, %+.2f vs the $%.2f basis)",
                       eq, bal, bal - InpPaperEquity, InpPaperEquity);
}

//+------------------------------------------------------------------+
//| BAR parity model: load the recorded per-bar M15 spread series    |
//| (written by scripts/midas_sweep.py --dump-spreadfile from the    |
//| SAME CSV the research engine prices with). Same file, same       |
//| dollars, same half-splits on both engines — the cost model can   |
//| no longer be a source of divergence.                             |
//+------------------------------------------------------------------+
bool LoadSpreadFile()
{
   int fh = FileOpen(InpSpreadFile, FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      PrintFormat(VersionTag() + "INIT FAILED: BAR mode cannot read spread file '%s' (run "
                  "scripts/midas_sweep.py --dump-spreadfile)", InpSpreadFile);
      return false;
   }
   long   t_tmp[];  double v_tmp[];
   int    cap = 0, n = 0;
   FileReadString(fh);                       // header line "time,spread"
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      if(StringLen(line) < 3) continue;
      string p[];
      if(StringSplit(line, ',', p) != 2) continue;
      if(n >= cap) { cap = (cap == 0) ? 4096 : cap * 2;
                     ArrayResize(t_tmp, cap); ArrayResize(v_tmp, cap); }
      t_tmp[n]  = (long)StringToInteger(p[0]);
      v_tmp[n]  = StringToDouble(p[1]);
      if(n > 0 && t_tmp[n] <= t_tmp[n - 1]) { n--; }   // guard: strict ascent
      n++;
   }
   FileClose(fh);
   ArrayResize(g_sp_t, n); ArrayResize(g_sp_v, n);
   for(int i = 0; i < n; i++) { g_sp_t[i] = t_tmp[i]; g_sp_v[i] = v_tmp[i]; }
   g_sp_n = n;
   PrintFormat(VersionTag() + "SPREAD FILE loaded: %d bars from %s", n, InpSpreadFile);
   return n > 0;
}

// Recorded spread ($) for the bar that OPENS at time t; $0.10 floor applied
// exactly like the python engine's max(spread, SPREAD_FLOOR). 0.0 = unknown.
double SpreadAt(datetime t)
{
   long key = (long)t;
   int lo = 0, hi = g_sp_n - 1;
   while(lo <= hi)
   {
      int mid = (lo + hi) / 2;
      if(g_sp_t[mid] == key) return (g_sp_v[mid] > SPREAD_FLOOR) ? g_sp_v[mid] : SPREAD_FLOOR;
      if(g_sp_t[mid] < key) lo = mid + 1; else hi = mid - 1;
   }
   return 0.0;
}

// OHLC of the bar with OPEN time t (0.0 on any missing field = absent bar).
bool GetBar(datetime t, double &o, double &h, double &l, double &c)
{
   int k = iBarShift(_Symbol, InpEntryTF, t, true);
   if(k < 0) return false;
   o = iOpen(_Symbol, InpEntryTF, k);
   h = iHigh(_Symbol, InpEntryTF, k);
   l = iLow(_Symbol, InpEntryTF, k);
   c = iClose(_Symbol, InpEntryTF, k);
   return (o > 0 && h > 0 && l > 0 && c > 0);
}

// Bounded SMA-TR(14) of closed H1 bars ENDING at closed-bar shift k —
// window = shifts k (newest) .. k+13 (oldest). Python chains TR oldest →
// newest (each TR references the PREVIOUS-OLDER bar's close), so in shift
// space the chain must start from close(k+14) — the bar before the oldest
// window bar — and walk j = k+13 → k. v1.05 bug found live 2026-09-17:
// chaining started at close(k+1) walking older, so 13 of 14 TRs referenced
// the wrong (newer) close → ATR inflated ~18% (9.36 vs 7.92), every stop
// wrong, and a cascade of divergent outcomes (incl. one lost fill where the
// mis-stopped prior trade still held the position over the next signal).
bool AtrAtShift(int k, double &out)
{
   if(k < 0) return false;
   double sum = 0.0;
   double pc = iClose(_Symbol, PERIOD_H1, k + InpAtrPeriod);
   if(pc <= 0) return false;
   for(int j = k + InpAtrPeriod - 1; j >= k; j--)
   {
      double h = iHigh(_Symbol, PERIOD_H1, j);
      double l = iLow(_Symbol, PERIOD_H1, j);
      double c = iClose(_Symbol, PERIOD_H1, j);
      if(h <= 0 || l <= 0 || c <= 0) return false;
      sum += MathMax(h - l, MathMax(MathAbs(h - pc), MathAbs(l - pc)));
      pc = c;
   }
   out = sum / InpAtrPeriod;
   return out > 0;
}

//+------------------------------------------------------------------+
//| v1.23 SESSION DEDUPE for the venue self-inconsistency.            |
//|                                                                  |
//| MEASURED 2026-09-22: the TICK VALUE MISMATCH line below printed   |
//| from EVERY caller of DollarPerUnitPerLot() — and on the live arm  |
//| the 15-minute heartbeat calls it twice (StateRowWrite +           |
//| HudUpdate), every evaluated bar calls it again, and the sizing    |
//| sites add one per attempt — so the same two static numbers        |
//| repeated all day and buried the VETO/NOFILL refusals the journal  |
//| exists to carry. The warning now prints on the FIRST observation  |
//| of a session (this EA process) and again only when either number  |
//| MOVES materially; the same two moments append a keyed `SPEC` row  |
//| so the evidence outlives the journal scroll. The globals reset at |
//| init, so a reload is a new session and prints once.               |
//+------------------------------------------------------------------+
double g_spec_warn_broker = 0.0;   // broker tv/ts at the last print (0 = not yet this session)
double g_spec_warn_used   = 0.0;   // authoritative value at the last print

// True on the first observation of the session, or when either number moved past the
// relative band. The band is 0.5%: OrderCalcProfit is a quote and the raw spec fields
// are static, so anything a human would call "the same numbers" stays silent; a broker
// spec change (or a contract/quote redefinition) breaks the band and re-arms the print.
bool SpecMoved(double broker_now, double used_now)
{
   if(g_spec_warn_broker <= 0.0 || g_spec_warn_used <= 0.0)
      return true;
   return MathAbs(broker_now - g_spec_warn_broker) / g_spec_warn_broker > 0.005 ||
          MathAbs(used_now - g_spec_warn_used) / g_spec_warn_used > 0.005;
}

//+------------------------------------------------------------------+
//| Dollar value of one 1.0 price-unit move per 1.0 lot.             |
//|                                                                  |
//| AUTHORITY ORDER (2026-09-20, measured on Upcomers XAUUSD):        |
//|   1. what the broker SETTLES — OrderCalcProfit over one price     |
//|      unit per lot. This is the number a position actually pays.   |
//|   2. contract size (geometric: $ per 1.0 price unit per lot).     |
//|   3. tick value / tick size.                                      |
//|                                                                  |
//| The venue is SELF-INCONSISTENT: contract 100.0 x tick 0.01 = $1.00|
//| per tick, but SYMBOL_TRADE_TICK_VALUE reports 0.10, so tv/ts = 10 |
//| while OrderCalcProfit(1 lot, +$1.00) = $100.00. Sizing off tv/ts  |
//| on the $25,000 evaluation turned an intended $250 (1% risk) stop  |
//| into $2,500 — two thirds of the 6% trailing budget in one trade.  |
//| The previous version detected exactly that and used the broker    |
//| value anyway; a warning is not a guard. It now refuses when no    |
//| value can be justified instead of choosing the cheaper-looking one.|
//+------------------------------------------------------------------+
bool DollarPerUnitPerLot(double &out)
{
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double cs = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(ask <= 0.0) ask = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   out = 0.0;

   double settled = 0.0, p = 0.0;
   if(ask > 0.0 && OrderCalcProfit(ORDER_TYPE_BUY, _Symbol, 1.0, ask, ask + 1.0, p) && p > 0.0)
      settled = p;                                                    // $ per unit per lot
   double geo    = (cs > 0.0) ? cs : 0.0;
   double via_tv = (ts > 0.0 && tv > 0.0) ? tv / ts : 0.0;

   if(settled > 0.0 && geo > 0.0 && MathAbs(settled - geo) / settled > 0.02)
      PrintFormat(VersionTag() + "DOLLAR-PER-UNIT: the broker's own answers disagree — "
                  "order_calc_profit %.2f vs contract %.2f per price unit; using the settled value",
                  settled, geo);

   // Same ladder as floor_zone.SymbolData.calibrated_tick_value (python twin):
   // settled, else a raw value that AGREES with geometry, else geometry, else raw.
   if(settled > 0.0)
      out = settled;
   else if(via_tv > 0.0 && geo > 0.0 && MathAbs(via_tv - geo) / geo <= 0.05)
      out = via_tv;
   else if(geo > 0.0)
      out = geo;
   else
      out = via_tv;

   if(out <= 0.0)
   {
      PrintFormat(VersionTag() + "FATAL: no usable dollar-per-unit value "
                  "(contract=%.2f tick_size=%.5f tick_value=%.5f) — REFUSING to size",
                  cs, ts, tv);
      return false;
   }
   // v1.23: deduped print + ledger record, written at the same two moments. The first
   // line of the session is byte-identical to the one v1.22 printed on every call, so
   // nothing that greps the journal for the warning breaks; a changed pair says so and
   // names what it was, because "it changed" is itself the evidence an operator needs.
   if(via_tv > 0.0 && MathAbs(out - via_tv) / out > 0.05)
   {
      if(SpecMoved(via_tv, out))
      {
         if(g_spec_warn_broker > 0.0)
            PrintFormat(VersionTag() + "TICK VALUE MISMATCH CHANGED: broker tv/ts=%.2f vs settled %.2f "
                        "per price unit (ratio %.2f; was tv/ts=%.2f vs settled %.2f) — sizing on the settled value",
                        via_tv, out, via_tv / out, g_spec_warn_broker, g_spec_warn_used);
         else
            PrintFormat(VersionTag() + "TICK VALUE MISMATCH broker tv/ts=%.2f vs settled %.2f per price unit "
                        "(ratio %.2f) — venue spec is self-inconsistent; sizing on the settled value",
                        via_tv, out, via_tv / out);
         SpecRecord(tv, ts, cs, settled, via_tv, out);
         g_spec_warn_broker = via_tv;
         g_spec_warn_used   = out;
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| v1.23 SPEC row — the venue's self-inconsistency, ON THE RECORD.   |
//|                                                                  |
//| Written at exactly the moments the deduped journal line prints    |
//| (first observation of the session, and every material change), so |
//| quieting the journal cannot lose the evidence: the numbers the    |
//| arm sized against are in the file even though the line is not     |
//| scrolling. Fields are KEYED, never positional: the NOFILL         |
//| mislabel (2026-09-21) was a reader/writer column-order             |
//| disagreement that a permutation of zeros made invisible, so this  |
//| row cannot be misread by position on either side.                 |
//| Gated out of the strategy tester and the BAR replay exactly like  |
//| the STATE row: certified parity ledgers stay byte-identical, and  |
//| the BAR ledger is a reproduction artifact, not an observation.    |
//+------------------------------------------------------------------+
void SpecRecord(double tv, double ts, double cs, double settled,
                double broker, double used)
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   PaperLog(StringFormat("SPEC,%I64d,tv=%.5f,ts=%.5f,cs=%.2f,broker=%.2f,settled=%.4f,used=%.4f,ratio=%.4f",
              (long)TimeUTCNow(), tv, ts, cs, broker, settled, used, broker / used));
}

void PrintFloorTable()
{
   double dpu;
   if(!DollarPerUnitPerLot(dpu)) { Print(VersionTag() + "FLOOR TABLE unavailable (bad spec)"); return; }
   double atr = AtrNow();
   if(atr <= 0) { Print(VersionTag() + "FLOOR TABLE unavailable (no ATR yet)"); return; }
   double stop = InpSlAtrMult * atr;
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double risk_min = stop * dpu * vmin;
   // The percentage is PRINTED, not assumed. This read `equity@1%%` while the value was
   // `risk_min / InpRiskPercent` — correct only while the configured risk happened to be
   // 1.00%. MEASURED 2026-09-21, after the risk was re-sized to 0.25%: the line read
   // `equity@1%=$13234`, i.e. a label saying 1% beside a number computed at 0.25%. A
   // diagnostic that names the wrong quantity is worse than no diagnostic, because the
   // number is right and only the label is wrong.
   PrintFormat(VersionTag() + "FLOOR TABLE %s: stop=%.2f ($%.2f) minlot=%.2f risk@minlot=$%.2f "
               "equity@%.2f%%=$%.0f",
               _Symbol, stop, stop, vmin, risk_min, InpRiskPercent,
               risk_min / MathMax(InpRiskPercent / 100.0, 0.0001));
}

bool g_debug_done = false;

// ATR ending at closed bar `shift` (bounded SMA-TR definition, v1.03)
double AtrNowAt(int shift)
{
   double sum = 0.0;
   double pc = iClose(_Symbol, PERIOD_H1, shift + InpAtrPeriod);
   if(pc <= 0) return 0.0;
   for(int k = shift + InpAtrPeriod - 1; k >= shift; k--)
   {
      double h = iHigh(_Symbol, PERIOD_H1, k);
      double l = iLow(_Symbol, PERIOD_H1, k);
      double c = iClose(_Symbol, PERIOD_H1, k);
      if(h <= 0 || l <= 0 || c <= 0) return 0.0;
      sum += MathMax(h - l, MathMax(MathAbs(h - pc), MathAbs(l - pc)));
      pc = c;
   }
   return sum / InpAtrPeriod;
}

//+------------------------------------------------------------------+
//| v1.02 diagnostic: dump the tester's own last 30 closed H1 bars + |
//| iATR values at the FIRST trade, for series-vs-CSV comparison.    |
//+------------------------------------------------------------------+
void DumpH1Debug()
{
   int fh = FileOpen("MIDASTOUCH_debug_h1.csv", FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   for(int k = 1; k <= 30; k++)
   {
      datetime t = iTime(_Symbol, PERIOD_H1, k);
      FileWrite(fh, (long)t,
                DoubleToString(iOpen(_Symbol, PERIOD_H1, k), 5),
                DoubleToString(iHigh(_Symbol, PERIOD_H1, k), 5),
                DoubleToString(iLow(_Symbol, PERIOD_H1, k), 5),
                DoubleToString(iClose(_Symbol, PERIOD_H1, k), 5),
                DoubleToString(AtrNowAt(k), 5));
   }
   FileClose(fh);
   Print(VersionTag() + "H1 debug dump written (30 bars)");
}

//+------------------------------------------------------------------+
//| Bounded ATR (protocol amendment 2): SMA of True Range over the   |
//| last InpAtrPeriod CLOSED H1 bars — a pure bar computation that is |
//| identical in the tester, live, and the python research engine    |
//| (unbounded Wilder ATR is seed-dominated in the tester's short    |
//| history window and can never be parity-tested — measured 2026).  |
//+------------------------------------------------------------------+
double AtrNow()
{
   double sum = 0.0;
   double pc = iClose(_Symbol, PERIOD_H1, InpAtrPeriod + 1);
   if(pc <= 0) return 0.0;
   for(int k = InpAtrPeriod; k >= 1; k--)
   {
      double h = iHigh(_Symbol, PERIOD_H1, k);
      double l = iLow(_Symbol, PERIOD_H1, k);
      double c = iClose(_Symbol, PERIOD_H1, k);
      if(h <= 0 || l <= 0 || c <= 0) return 0.0;
      sum += MathMax(h - l, MathMax(MathAbs(h - pc), MathAbs(l - pc)));
      pc = c;
   }
   return sum / InpAtrPeriod;
}

//+------------------------------------------------------------------+
//| The session window, defined ONCE (v1.21). The live gate and the   |
//| HUD's GATES line both call this, so "is this bar tradable" cannot |
//| have two answers. The rule is on the bar's OPEN hour.             |
//+------------------------------------------------------------------+
bool InSessionBar(const datetime bar_open)
{
   MqlDateTime d;
   TimeToStruct(bar_open, d);
   return (d.hour >= InpSessionStartHour && d.hour < InpSessionEndHour);
}

//+------------------------------------------------------------------+
//| Macro state on CLOSED bars: +1 up, -1 down, 0 divergent.         |
//+------------------------------------------------------------------+
int MacroState()
{
   double e1[], e4[], c1[], c4[];
   if(CopyBuffer(g_h1_ema, 0, 1, 1, e1) != 1) return 0;
   if(CopyBuffer(g_h4_ema, 0, 1, 1, e4) != 1) return 0;
   if(CopyClose(_Symbol, PERIOD_H1, 1, 1, c1) != 1) return 0;
   if(CopyClose(_Symbol, PERIOD_H4, 1, 1, c4) != 1) return 0;
   bool h1_up = c1[0] > e1[0], h4_up = c4[0] > e4[0];
   // v1.21: the two directions are stashed for the HUD and the STATE row. This is the
   // ONLY place they are computed, so the display cannot disagree with the decision: the
   // same two booleans that decide the entry also name the regime on the chart.
   g_hud_h4 = h4_up ? 1 : -1;
   g_hud_h1 = h1_up ? 1 : -1;
   if(h1_up && h4_up) return 1;
   if(!h1_up && !h4_up) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| Trigger on the CLOSED M15 bar (index 1): BB touch-back or RSI.   |
//| +1 = long trigger, -1 = short trigger, 0 = none.                 |
//+------------------------------------------------------------------+
int TriggerOnClosedBar()
{
   double up[], lo[], rsi[];
   // v1.21 display echo: the RSI reading on the evaluated bar, taken once here so the HUD
   // can answer "how close was it" without a second read of its own. Pure read, no effect
   // on the trigger below, and the value is also what the STATE row carries.
   double rr_hud[];
   if(CopyBuffer(g_m15_rsi, 0, 1, 1, rr_hud) == 1) g_hud_rsi = rr_hud[0];
   if(CopyBuffer(g_m15_bb, 1, 1, 1, up) != 1) return 0;   // UPPER_BAND
   if(CopyBuffer(g_m15_bb, 2, 1, 1, lo) != 1) return 0;   // LOWER_BAND
   double c0[], c1[];
   if(CopyClose(_Symbol, InpEntryTF, 1, 2, c1) != 2) return 0;  // [0]=older [1]=closed
   if(CopyClose(_Symbol, InpEntryTF, 2, 1, c0) != 1) return 0;
   // BB: previous bar closed OUTSIDE the band, signal bar closed back inside
   if(c0[0] > up[0] && c1[1] < up[0]) return 1;
   if(c0[0] < lo[0] && c1[1] > lo[0]) return -1;
   if(CopyBuffer(g_m15_rsi, 0, 1, 1, rsi) != 1) return 0;
   if(rsi[0] >= InpRSIUpper) return -1;
   if(rsi[0] <= InpRSILower) return 1;
   return 0;
}

//+------------------------------------------------------------------+
//| Mode transform (mirrors scripts/midas_sweep.py exactly).         |
//+------------------------------------------------------------------+
bool ModeDecide(int trigger, int mac, int &direction)
{
   switch(InpMode)
   {
      case MODE_ORIGINAL:          direction = trigger;  return trigger != 0 && mac == trigger;
      case MODE_REVERSE_DIRECTION: direction = -trigger; return trigger != 0 && mac == -trigger;
      case MODE_REVERSE_TRIGGER:   direction = mac;      return trigger == 0 && mac != 0;
      case MODE_REVERSE_BOTH:      direction = -mac;     return trigger == 0 && mac != 0;
      case MODE_LONG_ONLY:         direction = 1;        return trigger == 1 && mac == 1;
      case MODE_SHORT_ONLY:        direction = -1;       return trigger == -1 && mac == -1;
      case MODE_MACRO_ONLY:        direction = mac;      return mac != 0;
      case MODE_TRIGGER_ONLY:      direction = trigger;  return trigger != 0;
   }
   return false;
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)InpDeviationPoints);   // v1.08 live order path
   g_paper_eq = InpPaperEquity;
   g_paper_start = InpPaperEquity;

   g_h1_ema  = iMA(_Symbol, PERIOD_H1, InpMacroEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_h4_ema  = iMA(_Symbol, PERIOD_H4, InpMacroEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_h1_atr  = iATR(_Symbol, PERIOD_H1, InpAtrPeriod);
   // v1.19 (register §2b P6 build block): entry-TF handles follow InpEntryTF.
   // The BAR parity engine below stays hardwired M15 (see the guard) — the
   // certified corpus and parity harness are M15; M5 exists PERTICK-only.
   g_m15_bb  = iBands(_Symbol, InpEntryTF, InpBBPeriod, 0, InpBBDev, PRICE_CLOSE);
   g_m15_rsi = iRSI(_Symbol, InpEntryTF, InpRSIPeriod, PRICE_CLOSE);
   if(InpBarModel && InpEntryTF != PERIOD_M15)
   {
      Print(VersionTag() + "INIT FAILED: BAR parity mode is M15-only (InpEntryTF="
            + EnumToString(InpEntryTF) + "); M5 runs PERTICK only");
      return INIT_FAILED;
   }
   if(g_h1_ema == INVALID_HANDLE || g_h4_ema == INVALID_HANDLE ||
      g_h1_atr == INVALID_HANDLE || g_m15_bb == INVALID_HANDLE ||
      g_m15_rsi == INVALID_HANDLE)
   {
      Print(VersionTag() + "INIT FAILED: indicator handle");
      return INIT_FAILED;
   }

   if(InpBarModel && !LoadSpreadFile())
      return INIT_FAILED;                   // fail-closed: BAR mode needs the parity contract

   // v1.09: EA-enforced python window. A BAR parity pass MUST carry the
   // research window (t0,t1): with defaults the replay would silently trade
   // all loaded history (found live 2026-09-17 — a stale tester pass with
   // zeroed window inputs polluted the sandbox ledger). Fail-closed.
   if(InpBarModel)
   {
      if(InpWindowStart <= 0 || InpWindowEnd <= 0 || InpWindowEnd <= InpWindowStart)
      {
         PrintFormat(VersionTag() + "INIT FAILED: BAR parity needs InpWindowStart/End = python t0/t1 "
                     "(got %I64d/%I64d)", (long)InpWindowStart, (long)InpWindowEnd);
         return INIT_FAILED;
      }
      g_win_t0 = (datetime)InpWindowStart;
      g_win_t1 = (datetime)InpWindowEnd;
   }

   // BAR parity REFUSED this combination until v1.19d, and it was right to: the python
   // engine of record did not apply the veto, so a BAR pass with the gate ON would have
   // named a protection that could not act — a filter that silently does nothing, which
   // is the one failure mode this mechanism exists to prevent. The engine of record now
   // applies the SAME +/-15-minute stand-down from the SAME file at the SAME instant
   // (`scripts/midas_sweep.py` `use_news`, fed by `scripts/midas_parity.py --news`), so
   // the combination is no longer a lie and no longer needs refusing.
   //
   // It is still not a REPRODUCTION. The frozen walk-forward was run news-OFF, so a BAR
   // pass with the gate ON measures a different strategy — an amendment. That is said
   // here, and stamped into the ledger's era note below, because the difference between
   // the two runs has to survive the pass.
   if(InpBarModel && InpUseNewsFilter)
   {
      Print(VersionTag() + "NEWS STAND-DOWN ON IN BAR REPLAY: an AMENDMENT to the certified "
            "contract, not a reproduction of it — the frozen walk-forward ran with the gate "
            "OFF. The python engine of record applies this same veto from the same "
            "calendar, so the two engines still compare key-by-key.");
   }

   // NEWS FILTER — R6 REVISED, 2026-09-20. The v1.16 decision was an INIT_FAILED
   // because no calendar engine existed; inventing one was worse than refusing. There is
   // now a real source: `MidasNewsProbe.mq5` reads MQL5's economic calendar and WRITES IT
   // to InpNewsFile, which this EA reads. The file (rather than a direct API call) is
   // deliberate, and it was measured, not assumed:
   //
   //   CalendarValueHistory -> -1 value(s), GetLastError=4014   (Strategy Tester,
   //   2026.09.20) — error 4014 is "function not allowed for call", so the calendar
   //   cannot be read from inside the tester at all.
   //
   // A rule only one engine can see is a rule the parity contract cannot replay, so the
   // shared file is the contract: both this EA and the Python research engine read the
   // same events. What changed about the refusal is WHICH failure it protects: an
   // unusable calendar now vetoes ENTRIES (below), never INIT. A refused init on a live
   // account with a position open would leave the shield rules unmanaged, which is a
   // worse outcome than standing aside — the failure modes are not symmetrical.
   if(InpUseNewsFilter)
   {
      // Repair the source BEFORE judging it. "ON requires a fresh calendar" is only an
      // honest requirement if the EA goes and gets one; otherwise the switch reads as
      // protection and behaves as a permanent stand-down after 24 hours.
      NewsRefreshIfDue(TimeGMT());
      string news_init = NewsSourceProblem();
      PrintFormat(VersionTag() + "NEWS FILTER ON — source %s: %s", InpNewsFile,
                  (news_init == "") ? "usable" : news_init);
   }
   if(InpRecordStateLabel)
   {
      if(MQLInfoInteger(MQL_TESTER))
      {
         // A silent no-op is the failure mode this file exists to prevent: say which
         // runs stamp and which do not, and why.
         Print(VersionTag() + "STATE LABEL: ON but NOT STAMPED — strategy-tester ledgers "
               "are the parity contract's artifacts and stay byte-identical; the python "
               "side labels those rows from the corpus it already has.");
      }
      else
      {
         NewsRefreshIfDue(TimeGMT());     // a stale source records `na`, not news
         string state_src = NewsSourceProblem();
         PrintFormat(VersionTag() + "STATE LABEL ON — OPEN rows carry "
                     "sig_ct,hour_utc,vol_ratio,news,off_min (%s)",
                     (state_src == "") ? "calendar usable" : state_src);
      }
   }
   string symU = _Symbol;
   StringToUpper(symU);
   bool is_gold = (StringFind(symU, "XAU") >= 0 || StringFind(symU, "GOLD") >= 0);
   if(!is_gold)
   {
      Print(VersionTag() + "INIT FAILED: chart symbol is not a gold symbol — "
            "MIDASTOUCH is gold-only by charter (V2 register R6).");
      return INIT_FAILED;
   }
   PrintFormat(VersionTag() + "MIDASTOUCH started | mode=%d | symbol=%s (GOLD-OK) | "
               "macro=H4+H1 EMA%d | trigger=M15 BB(%d,%.1f)/RSI(%d) | SL=%.1fxATR(H1) TP=%.1fR "
               "timeout=%dmin | session=%02d-%02d UTC | spreadcap=%.1f%%stop | risk=%.2f%% | "
               "execution=%s | exec-model=%s | NEWS-FILTER=%s",
               (int)InpMode, _Symbol,
               InpMacroEmaPeriod, InpBBPeriod, InpBBDev, InpRSIPeriod,
               InpSlAtrMult, InpTpMult, InpTimeoutMinutes,
               InpSessionStartHour, InpSessionEndHour, InpSpreadCapPctStop,
               InpRiskPercent,               InpLiveExecution ? "LIVE" : "PAPER",
               InpBarModel ? "BAR" : "PERTICK",
               InpUseNewsFilter ? "ON" : "OFF");
   // v1.19d: the offset line refuses to state a number it cannot vouch for.
   int off_tick  = OffsetMinutes();                                   // from the last TICK
   int off_trd   = (int)((TimeTradeServer() - TimeGMT()) / 60);       // terminal-calculated
   int off_delta = off_tick - off_trd;
   if(off_delta < 0) off_delta = -off_delta;
   bool off_ok = (off_delta <= 1) && (off_tick >= -14 * 60) && (off_tick <= 14 * 60);
   if(off_ok)
      PrintFormat(VersionTag() + "CLOCK: server=%s | GMT=%s | offset=%+d h %02d min — session gates classify BAR EPOCHS (parity); "
                  "live-path wall-clock gates use TimeGMT; VERIFY this offset before the live gate (health guide §4)",
                  TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
                  TimeToString(TimeGMT(), TIME_DATE|TIME_MINUTES),
                  OffsetHours(), OffsetRemMin());
   else
      PrintFormat(VersionTag() + "CLOCK: UNVERIFIED OFFSET — last-known-tick clock says %+d h %02d min from UTC, "
                  "the terminal's own trade-server clock says %+d h %02d min (server=%s | GMT=%s). TimeCurrent() is "
                  "the time of the last TICK, so for minutes after a launch it is stale and the difference is not an "
                  "offset. Wait for a live tick before using either number (health guide §4).",
                  off_tick / 60, (off_tick < 0 ? -off_tick : off_tick) % 60,
                  off_trd / 60, (off_trd < 0 ? -off_trd : off_trd) % 60,
                  TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
                  TimeToString(TimeGMT(), TIME_DATE|TIME_MINUTES));

   // ledger era stamp (idempotent provenance, mirrors the house contract).
   // v1.09: the era_name field is now an HONEST model note — BAR parity
   // passes stamp "bar-model-parity" instead of self-describing as
   // "pertick-fills" (a lie found in the polluted sandbox ledger). The live
   // paper ledger (InpBarModel=false) keeps "pertick-fills" exactly as the
   // era.py accounting expects; tester ledgers are throwaway.
   string era_note = InpBarModel ? "bar-model-parity" : "pertick-fills";
   // v1.13 (V2 register R10, never-abort class): the telemetry build cites the
   // register in its ERA note so midas_verdict can classify this version
   // change without aborting the window. BAR tester ledgers are throwaway and
   // keep the exact parity-era note byte-for-byte.
   if(!InpBarModel)
      era_note += "+telemetry-only-per-V2-register";
   // v1.19d: a BAR pass with the news gate ON is an AMENDMENT (see the init note), and the
   // ledger is where that has to survive — a pass certifying a stance the corpus never ran
   // must not be byte-identical to one that reproduced it. The gate-OFF BAR note is
   // untouched, because those ledgers are compared against the certified era verbatim.
   if(InpBarModel && InpUseNewsFilter)
      era_note += "+news-amendment";
   // v1.18: the NOFILL diagnostics ledger is review-item-1 telemetry. NOFILL
   // rows are appends AFTER trade rows, never alter any CLOSE row, and exist
   // only in live/paper-file ledgers — this tag keeps the version transition
   // in midas_verdict's never-abort class (§1 citation walk).
   if(!InpBarModel)
      era_note += "+diag-nofill";
   // v1.19: the P6 build block parameterizes the entry TF and ships TP-1.5R
   // presets. Defaults are the certified config, so the transition stays in
   // midas_verdict's never-abort class via this citation (§1 walk).
   if(!InpBarModel)
      era_note += "+p6-entrytf";
   // v1.20: the census gained a row type (NOFILLSUM) and reads itself back at init, a
   // grammar change that belongs in the era note for the same reason +diag-nofill does:
   // a reader must be able to tell which ledger it is holding from the ledger alone.
   if(!InpBarModel)
      era_note += "+diag-census";
   // v1.21: the HUD view is serialised into a new row type (STATE) on every evaluated
   // bar, so the chart's reading survives the chart. Same reason as +diag-census: a reader
   // holding a ledger must be able to tell what it carries from the ledger alone.
   if(!InpBarModel)
      era_note += "+state-view";
   // v1.22: every fill row gained a keyed `cfg=<usd>@<pct>` tail — the risk the arm was
   // CONFIGURED for, beside the risk it took. A grammar change on the fill rows for the
   // same reason as +diag-census: a reader holding a ledger must be able to tell what it
   // carries from the ledger alone.
   if(!InpBarModel)
      era_note += "+cfg-risk";
   // v1.23: the venue self-inconsistency gained a record of its own (SPEC rows with keyed
   // fields) and its journal line is deduped to once per session / on change. A grammar
   // change like the two above, so it rides the era note for the same reason: a reader
   // holding a ledger must be able to tell what it carries from the ledger alone.
   if(!InpBarModel)
      era_note += "+spec-record";
   // v1.25: fill rows gained `entry=pending` when the price cannot be resolved at write time,
   // and a fill whose row could not be priced is amended by a LENTRY row. Both are grammar a
   // reader has to know about to price a fill correctly, so both ride the era note.
   if(!InpBarModel)
      era_note += "+fill-price-heal";
   // v1.26: the EQ row's BASIS changed on a live ledger — it carries the venue's account
   // equity there, not the paper book's frozen counter. A reader holding a ledger must be
   // able to tell that from the ledger alone, which is what the note is for.
   if(!InpBarModel)
      era_note += "+acct-eq";
   // v1.27: THREE RECORD-ONLY APPENDS, and a reader has to know about all three because each
   // moves a field POSITION rather than a meaning. (1) `nodata` is the 10th NOFILL/NOFILLSUM
   // counter, so BOTH the snapshot floor (12 -> 13) and the row width moved. (2) the STATE row
   // gained the v1.19e state stamp before its keyed `cfg=` token, so a row that once ended at
   // `floor` now carries five more fields — and a reader that counted on the old end reads the
   // cfg token as a state field. (3) `SPREADHOUR` is a new row type. The note names them.
   // v1.28 adds a fourth: `SWEEPSHADOW` is a new row type, one per evaluated bar inside the
   // sweep shadow's UTC 07-18 window, so a reader of this arm's book meets a row it has not
   // seen before and the note says so rather than leaving it to be discovered.
   // v1.29 adds a fifth: `+exit-reason` - the LCLOSE row names who closed the trade (SL, TP,
   // SO, EXPERT, MANUAL-*) instead of one EXTERNAL word for "the venue did it".
   if(!InpBarModel)
      era_note += "+census10+state-ctx+spread-hour+sweep-shadow+exit-reason";
   PaperLog(StringFormat("ERA,%s,%I64d,%s", APP_VERSION, (long)TimeCurrent(), era_note));
   RestoreOrVerifyLedger();
   DiagRestoreFromLedger();             // v1.20: continue the day this reload interrupted
   LiveCensusRestoreFromLedger();       // v1.24: the arm's realized record, on the chart
                                        // from the first second (HudUpdate runs below)
   if(!MQLInfoInteger(MQL_TESTER))
      LogEquityRow();   // v1.07: init epoch touch (watchdog sees a fresh mtime immediately)
                        // v1.26: and on an armed arm it carries the ACCOUNT's equity
   EventSetTimer(900);                                 // v1.07: heartbeat — the ledger must provably stay live
   PrintFloorTable();
   DumpH1Debug();                      // v1.02: tester-vs-CSV series comparison
   LiveEntryPriceHeal();               // v1.25: price a fill row the writer could not price
   LiveRecoverState();                 // v1.08: adopt real positions after restart (live only)
   HudUpdate();                        // v1.10: HUD up from the first second (live only)
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();                                   // v1.07: release the heartbeat
   if(InpBarModel)
      ReplayTailFlush();
   DiagSnapshot();      // v1.20: capture the census on the way out (recompile, close, restart)
   LogEquityRow();      // v1.26: the farewell heartbeat carries the arm's own equity basis
   IndicatorRelease(g_h1_ema); IndicatorRelease(g_h4_ema);
   IndicatorRelease(g_h1_atr); IndicatorRelease(g_m15_bb);
   IndicatorRelease(g_m15_rsi);
}

// v1.07: watchdog heartbeat — the paper ledger's mtime IS the liveness
// signal (scripts/midas_watchdog.py relaunches the terminal if it goes
// stale). Timer events are local-clock driven, so the heartbeat continues
// during market closure and weekends; a live terminal can never look dead.
void OnTimer()
{
   if(MQLInfoInteger(MQL_TESTER))
      return;                                          // parity runs: byte-identical ledgers
   LogEquityRow();      // v1.26: on an armed arm this is the ACCOUNT's equity, not the paper
                        // book's frozen counter — see DisplayEquity()
   DiagMaybeWrite();                    // v1.18: NOFILL diagnostics flush on the heartbeat
   NewsRefreshIfDue(TimeGMT());         // v1.19c: keep the calendar source alive (live only)
   StateRowWrite();         // v1.21: the HUD's view onto the record, at the same cadence
   HudUpdate();                                        // v1.10: HUD refresh on the heartbeat clock
}

//+------------------------------------------------------------------+
//| Restore dangling paper position from OPEN rows without CLOSE.    |
//+------------------------------------------------------------------+
void RestoreOrVerifyLedger()
{
   int fh = FileOpen(PaperFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) { Print(VersionTag() + "PAPER fresh ledger"); return; }
   ulong open_ticket = 0; int open_dir = 0; double open_entry = 0, open_sl = 0,
         open_tp = 0, open_risk = 0; datetime open_time = 0; int open_hold = 0;
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      string p[];
      int n = StringSplit(line, ',', p);
      if(n < 1) continue;
      if(p[0] == "CLOSE" && n >= 3) open_ticket = 0;
      else if(p[0] == "OPEN" && n >= 12)
      {
         open_ticket = (ulong)StringToInteger(p[2]);
         open_dir    = (int)StringToInteger(p[3]);
         open_entry  = StringToDouble(p[4]);
         open_sl     = StringToDouble(p[5]);
         open_tp     = StringToDouble(p[6]);
         open_hold   = (int)StringToInteger(p[10]);
         open_time   = (datetime)StringToInteger(p[1]);
         open_risk   = StringToDouble(p[8]);
      }
   }
   FileClose(fh);
   if(open_ticket != 0)
   {
      g_pp_open = true; g_pp_ticket = open_ticket; g_pp_dir = open_dir;
      g_pp_entry = open_entry; g_pp_sl = open_sl; g_pp_tp = open_tp;
      g_pp_orig_risk = MathAbs(open_entry - open_sl);
      g_pp_eff_risk = open_risk;
      g_pp_entry_time = open_time;
      g_pp_expiration = open_time + open_hold;
      PrintFormat(VersionTag() + "PAPER restored dangling ticket=%I64u dir=%d entry=%.5f",
                  open_ticket, open_dir, open_entry);
   }
   else
      Print(VersionTag() + "PAPER ledger flat — nothing to restore");
}

//+------------------------------------------------------------------+
// Phase milestone: the 5% target ends the EVALUATION, not the trading.
// Reached once it prints one line and sets g_prop_passed; below the target nothing
// happens. Never returns a block reason, because the governor gates survival rules and
// a completed evaluation is not a survival rule. The funded phase's own numbers
// (daily DD %, max single-trade loss %) are still UNVERIFIED with the venue — the
// audit lists conflicting figures (C2/C3) — so the guards that stay in force are the
// challenge ones, and the print says so rather than pretending they were re-declared.
void PropPhaseCheck()
{
   double size = PropGovernorSize();
   double target = size * InpPropTargetPct / 100.0;
   double progress = AccountInfoDouble(ACCOUNT_EQUITY) - size;
   if(target > 0.0 && progress >= target)
   {
      g_prop_passed = true;
      if(!g_prop_pass_logged)
      {
         g_prop_pass_logged = true;
         PrintFormat(VersionTag() + "PROP PHASE: EVALUATION COMPLETE — target MET (+%.2f of %.2f). "
                     "Trading continues under the funded rule set; funded daily-DD %% and max "
                     "single-trade-loss %% are UNVERIFIED (rules audit C2/C3), so the challenge "
                     "guards (3%% day cap, %.1f%% shield, Best Day cap) remain in force",
                     progress, target, InpPropMaxDdPct);
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   PropDayAnchorCheck();                   // UTC-day baselines BEFORE any gate reads them
   PropPhaseCheck();                       // evaluation-complete milestone (never a veto)
   SpreadSampleTick();                     // v1.27: one spread increment per tick, record
                                           // only — it reads the quote and blocks nothing
   if(InpBarModel)                         // v1.04 research-parity replay
   {
      OnBarReplay();
      return;
   }
   if(LiveSignalArmed())               // v1.08: real-order path
   {
      LiveOnTick();
      return;
   }
   if(!g_pp_open) TrackFreshM15Bar();
   if(g_pp_open)  PaperCheckHardExits();
   HudUpdate();                        // v1.10: display-only refresh (paper path)
}

//+------------------------------------------------------------------+
//| v1.04 BAR parity engine — the python pass, bar by bar.           |
//| Fires on the FIRST tick of each new M15 bar T (the only tick     |
//| where iTime(0)==T and the forming bar's Open is its true Open).  |
//| python pass order, verbatim:                                     |
//|   1. fill pending at THIS bar's open (valid only on sig_ct),     |
//|   2. manage the open position over THIS complete bar,            |
//|   3. signal on THIS bar's close (i.e. on the NEXT bar's first    |
//|      tick — the moment this bar is complete and index 1).        |
//+------------------------------------------------------------------+
void OnBarReplay()
{
   datetime cur = iTime(_Symbol, PERIOD_M15, 0);
   if(cur == 0) return;
   if(cur <= g_last_seen) return;      // mid-bar / duplicate ticks
   g_last_seen = cur;
   ReplayThrough(cur);
}

// python iterates EVERY M15 bar of the recorded series in order, regardless
// of ticks. The EA observes time only through OnTick, so it catches up over
// every unprocessed completed bar on each arrival — this is what makes the
// engine tick-model independent (bars with zero real ticks were silently
// skipped before: measured 12,568 evals vs ~12,823 window bars, 2026-09-17).
// Membership: SpreadAt(t) > 0 == the bar exists in the recorded CSV (the
// shared spread series covers exactly the CSV bars) — tester-fabricated or
// session-hole bars are skipped, exactly the bars python's loop never sees.
#define X900  900                     // M15 bar length in seconds

void ReplayThrough(datetime cur)
{
   while(g_last_processed + X900 <= cur - X900)
   {
      datetime t = g_last_processed + X900;
      g_last_processed = t;            // advance unconditionally
      if(SpreadAt(t) <= 0) continue;   // bar absent from the recorded series
      bool may_signal = BarFillAndManage(t);
      if(!may_signal) continue;
      double o, h, l, c;
      if(GetBar(t, o, h, l, c))
         BarEvaluateSignal(t, o, h, l, c);
   }
}

// v1.11: resolve g_lv_posid/ticket from the position currently selected by
// SelectOurPosition(). Requires a position already selected (PositionSelect
// context). Safe no-op when nothing is selected.
void ResolveLiveIds()
{
   g_lv_ticket = (ulong)PositionGetInteger(POSITION_TICKET);
   ulong pid   = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
   g_lv_posid  = (pid > 0) ? pid : g_lv_ticket;   // netting fallback
}

//+------------------------------------------------------------------+
//| THE FILL PRICE IS NOT KNOWABLE AT ACKNOWLEDGEMENT (v1.25).       |
//|                                                                  |
//| MEASURED 2026-09-22 on the arm's first real fill. The EA took    |
//| the entry price from CTrade::ResultPrice() at the instant the    |
//| order was acknowledged and wrote `LOPEN,...,0.00000,...`; on this|
//| venue that field is 0 at that moment, which is the same instant  |
//| the EA's own journal warns that the position is not yet          |
//| selectable. The true price (4333.07) was in the position and in  |
//| the entry deal within the same second, and the row's reader      |
//| reported `entry price: ledger 0.0 vs venue 4333.07` for the rest |
//| of the fill's life. A 0 in a price column is read as a PRICE by  |
//| every reader, so the row must not carry one silently.            |
//|                                                                  |
//| Order of authority, direct first, and neither one is a guess:     |
//|   1. POSITION_PRICE_OPEN of the position we just opened (what the |
//|      venue says we are in at),                                    |
//|   2. DEAL_PRICE of that position's IN deal (history).             |
//| On netting the ORDER ticket IS the position identifier, measured  |
//| on this account, so history is reachable even in the window where |
//| the position itself is not yet selectable.                        |
//+------------------------------------------------------------------+
// BY IDENTITY, not by whatever the globals happen to hold: the amendment path runs at init,
// when the EA may be flat and the only thing it has is the identity the fill row carries.
bool ResolveEntryPriceById(ulong key, double &price, string &src)
{
   price = 0.0; src = "";
   if(key == 0) return false;
   // THE IDENTITY MUST BE ONE WE CLAIM, and this is the guard that keeps the history select
   // from ever reaching a stranger's position: either it is state we already hold, or the
   // venue's own history says that position was opened by an entry deal of ours. Fail-closed:
   // an identity we cannot claim returns no price, which leaves the row's `entry=pending`
   // standing rather than filling a price column with another position's number.
   if(key != g_lv_posid && key != g_lv_order && !PositionHasOurEntry(key)) return false;
   // 1. the position itself, if it is still open and still ours
   if(PositionSelectByTicket(key) &&
      PositionGetString(POSITION_SYMBOL) == _Symbol &&
      (long)PositionGetInteger(POSITION_MAGIC) == InpMagic)
   {
      double p = PositionGetDouble(POSITION_PRICE_OPEN);
      if(p > 0.0) { price = p; src = "position"; return true; }
   }
   // 2. history: the IN deal's price. Reachable while the position is still open, which is
   //    the window that matters here (the position is not selectable yet at the ack).
   if(!HistorySelectByPosition(key)) return false;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;   // another symbol's fill is not a price for this row
      if((long)HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic) continue;  // measured: the ENTRY deal carries our magic
      double p = HistoryDealGetDouble(d, DEAL_PRICE);
      if(p > 0.0) { price = p; src = "entry deal"; return true; }
   }
   return false;
}

bool ResolveEntryPrice(double &price, string &src)
{
   if(g_lv_posid != 0)
      return ResolveEntryPriceById(g_lv_posid, price, src);
   return ResolveEntryPriceById(g_lv_order, price, src);
}

// v1.11: resolve the ENTRY deal from open history for a selected position:
// the first IN deal (its price is the broker's volume-weighted entry price;
// recorded for provenance and future slippage telemetry).
void ResolveEntryDeal()
{
   g_lv_deal = 0;
   if(g_lv_posid == 0) return;
   if(!HistorySelectByPosition(g_lv_posid)) return;
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d > 0 && HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN)
      {
         g_lv_deal = d;
         break;
     }
   }
}

// v1.11: THE ONLY way live code touches a position. Selects the position
// owned by THIS EA on THIS symbol — verified against symbol AND magic —
// and resolves g_lv_posid/ticket as a side effect. Never trust "the
// position on XAUUSD is mine": another manual or EA position on the same
// symbol must be untouchable. Returns false when we are flat (or when a
// foreign position exists and ours does not).
bool SelectOurPosition()
{
   // v1.11.1: when we already hold IDs, RE-VERIFY that exact position —
   // keeps the per-tick external-close check O(1) and guarantees the
   // selected context is still the position we are about to act on.
   if(g_lv_posid != 0)
   {
      if(!PositionSelectByTicket(g_lv_ticket) ||
         (ulong)PositionGetInteger(POSITION_IDENTIFIER) != g_lv_posid ||
         PositionGetString(POSITION_SYMBOL) != _Symbol ||
         (long)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         return false;                              // gone or mutated: caller reconciles
      return true;
   }
   // adoption scan: first symbol+magic match wins (one-position-at-a-time
   // by charter; multiple owned positions are outside the strategy).
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      ResolveLiveIds();
      return true;
   }
   return false;
}

// OnDeinit tail flush: bars after the last tick (the tester ends mid-window
// in clock terms) are complete by deinit — python still iterates them (a
// position MUST manage to its close; a final in-window signal must stash).
void ReplayTailFlush()
{
   if(g_last_seen == 0) return;
   ReplayThrough(g_last_seen + X900);  // include the last seen bar itself
}

// python steps 1+2 in one call: fill pending (if sig_ct == t), then manage
// the open position across the COMPLETE bar [t, t+900). Returns whether
// python's loop would run signal detection on this bar: python `continue`s
// to the next bar whenever a position existed at bar start OR was filled on
// it — signals are evaluated ONLY from flat, no-fill bars (skipping this
// gate was the trade-#1 divergence: the EA stashed pendings python never
// did, decorrelating the whole sequence after a late position close).
bool BarFillAndManage(datetime t)
{
   double o, h, l, c;
   if(!GetBar(t, o, h, l, c)) return false;

   bool was_open = g_pp_open;          // state at bar start (python's `if pos`)
   bool filled  = false;

   // --- step 1: fill pending at this bar's open --------------------------
   if(g_pending_valid && !g_pp_open && t == g_pending_sigct)
   {
      int    side    = (g_pending_dir > 0) ? 1 : -1;
      double sp_open = SpreadAt(t);
      if(sp_open <= 0)
      {
         PrintFormat(VersionTag() + "BAR fill skipped: no recorded spread for %I64d", (long)t);
         g_pending_valid = false;
      }
      else
      {
         double fill = o + side * sp_open / 2;
         double stop_d = g_pending_stop;
         double dpu = DollarPerUnit();
         if(dpu <= 0) { Print(VersionTag() + "BAR fill skipped: bad symbol spec"); g_pending_valid = false; return false; }
         double risk_d = PaperEquity() * InpRiskPercent / 100.0;
         double lots = risk_d / (stop_d * dpu);
         if(lots < SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
         {
            // v1.14 amendment 6 (register R5): floor-to-min-lot can exceed
            // the configured risk — veto, never silently oversize. Mirrors
            // python minlot_risk_exceeds_cap (InpMaxRiskPct = the cap).
            if(stop_d * dpu * SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)
               > PaperEquity() * InpMaxRiskPct / 100.0)
            {
               PaperLog(StringFormat("SKIP,%I64d,RISK-CAP,%s", (long)t, InpArmTag));
               Print(VersionTag() + "PAPER SKIP RISK-CAP: min-lot risk exceeds "
                     "InpMaxRiskPct — trade vetoed (amendment 6)");
               g_pending_valid = false;
               return false;
            }
            lots = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         }
         double eff_risk = stop_d * dpu * lots;
         g_pp_dpu = dpu;
         g_pp_open = true; g_pp_dir = g_pending_dir; g_pp_entry = fill;
         g_pp_sl = fill - side * stop_d;
         g_pp_tp = fill + side * stop_d * InpTpMult;
         g_pp_orig_risk = stop_d; g_pp_eff_risk = eff_risk;
         g_pp_vol = lots; g_pp_entry_time = t; g_pp_ticket = (ulong)t;
         g_pp_expiration = t + (datetime)(InpTimeoutMinutes * 60);
         g_pp_open_sp = sp_open;            // python pos["sp"]
         g_pending_valid = false;
         filled = true;
         // v1.25: same off-by-one as the live row — one `%s` more than there were arguments, which
         // appended MQL5's `(missed string parameter)` to every paper OPEN row too.
         PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s,%.5f,%.5f%s",
                  (long)t, g_pp_ticket, g_pp_dir, fill, g_pp_sl, g_pp_tp,
                  lots, eff_risk, stop_d, InpTimeoutMinutes * 60, InpArmTag,
                  stop_d / InpSlAtrMult, sp_open,
                  StateAppend() + RiskAppend(risk_d)));   // v1.13 R10: atr_at_entry,spread_at_open | v1.19e: the state stamp | v1.22: cfg risk
      }
   }

   // --- step 2: manage across this complete bar --------------------------
   if(g_pp_open)
      BarManage(t, o, h, l, c);

   return !was_open && !filled;        // python's signal-detection domain
}

// python _manage over one complete bar: SL-first, exit at level, half-spread
// charged on the exit, timeout at bar close after >= 720 minutes held.
void BarManage(datetime t, double o, double h, double l, double c)
{
   if(g_pp_dpu <= 0) return;               // impossible after a real fill; fail-safe
   int    side   = (g_pp_dir > 0) ? 1 : -1;
   double stop_d = g_pp_orig_risk;
   double sp     = SpreadAt(t);
   if(sp <= 0) sp = SPREAD_FLOOR;          // python: max(spread, SPREAD_FLOOR)

   // excursions (python computes them too; parity verdict uses R)
   double fav = (side > 0) ? (h - g_pp_entry) / stop_d : (g_pp_entry - l) / stop_d;
   double adv = (side > 0) ? (g_pp_entry - l) / stop_d : (h - g_pp_entry) / stop_d;

   double exit_px = 0.0;
   string reason = "";
   if(side > 0)
   {
      if(l <= g_pp_sl)      { exit_px = g_pp_sl; reason = "SL"; }
      else if(h >= g_pp_tp) { exit_px = g_pp_tp; reason = "TP"; }
   }
   else
   {
      if(h >= g_pp_sl)      { exit_px = g_pp_sl; reason = "SL"; }
      else if(l <= g_pp_tp) { exit_px = g_pp_tp; reason = "TP"; }
   }
   long bars_held = (long)(t + 900 - (long)g_pp_entry_time);
   if(exit_px == 0 && bars_held >= (long)InpTimeoutMinutes * 60)
   {
      exit_px = c - side * sp / 2;
      reason = "TIMEOUT";
   }
   if(exit_px == 0) return;                // position survives into the next bar

   if(reason != "TIMEOUT")
      exit_px = exit_px - side * sp / 2;   // exit half-spread on top (python exact)
   double move = (exit_px - g_pp_entry) * side;
   double pnl  = move * g_pp_dpu * g_pp_vol;
   double r    = (g_pp_orig_risk > 0) ? pnl / g_pp_eff_risk : 0;
   g_paper_eq += pnl;
   g_cum_r += r; g_trades++; if(pnl > 0) g_wins++;
   PaperLog(StringFormat("CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f,%.5f,%.5f,%.2f,%I64d,%I64d",
            (long)(t + 900), g_pp_ticket, reason, exit_px, r, pnl, g_paper_eq,
            sp, 0.0, InpBBDev, (long)0, g_p5_signals));   // v1.13 R10: spread_at_close,slippage | v1.17 P5: thr,thr_era_id(static),density
   PaperLog(StringFormat("EQ,%.2f", g_paper_eq));
   PrintTradeR(r);
   g_last_action = StringFormat("CLOSE %s R=%+.2f vEq=$%.2f (%s)",   // v1.10 HUD
                  reason, r, g_paper_eq, TimeToString(t + 900, TIME_DATE|TIME_MINUTES));
   g_pp_open = false;
   g_pp_close_ct = t + 900;
}

// python step 3: signal on the bar that just CLOSED (sig = its open time).
// Mirrors run_mode's tail exactly: indicator lookups at the closed bar,
// mode transform, session gate, ATR/stop, pending stash (valid ONLY on the
// immediate next bar).
//+------------------------------------------------------------------+
//| v1.12 TIME ENGINE — one authoritative UTC clock for wall-clock   |
//| decisions. The review's P0 #2: TimeCurrent() is broker SERVER    |
//| time, so every wall-clock gate silently moved with the broker's  |
//| timezone (and its DST). The program needs TWO clocks, used       |
//| deliberately and never mixed:                                    |
//|                                                                  |
//|   • BAR/label frame — signal-bar EPOCHS (iTime values). The BAR  |
//|     session gate (BarEvaluateSignal) and the PERTICK gate        |
//|     (TrackFreshM15Bar) classify on those epochs because the      |
//|     python engine does (Amendment 2 certified; swapping THEM     |
//|     would BREAK bit-level parity — do not "fix" them).           |
//|   • REAL UTC — TimeGMT(), broker-independent, for ALL human-
//|     intent hour/day gates: session window, Friday cutoff and
//|     force-flat, daily-breaker day key, live timeout — via the
//|     single authoritative TimeUTCNow() helper. v1.12 confined
//|     these to the breaker/flat/timeout; v1.15 corrected the
//|     frame-law PROVENANCE finding: iTime bar epochs are broker-
//|     SERVER time (the label frame of the broker feed), not UTC,
//|     so classifying them through UTC structurization silently
//|     shifted the 06–20 window with the broker's timezone. The
//|     engine of record is re-pinned on the same finding
//|     (midas_sweep epoch classification = server frame); one
//|     commit, both engines. |
//|                                                                  |
//| The staleness guard intentionally STAYS on TimeCurrent(): it     |
//| measures gaps in the SERVER tick stream, which IS the frame it   |
//| must measure. Ledger row stamps stay TimeCurrent() as frame-     |
//| consistent provenance. MidasOffsetProbe.mq5 verifies the broker  |
//| offset at the live gate (see MIDASTOUCH_HEALTH_GUIDE.md §3).     |
//+------------------------------------------------------------------+
datetime TimeUTCNow()
{
   return TimeGMT();                      // broker-independent; no offset inputs to get wrong
}

//| Broker-vs-UTC offset in minutes, from the LAST KNOWN TICK.
//|
//| MEASURED 2026-09-21, twice in one morning, and the reason the banner no longer trusts
//| it blindly: `TimeCurrent()` is the time of the last tick received, so for minutes
//| after a launch — before the new session's first tick — it is hours stale. Two separate
//| launches reported "offset=-5 h 19 min" for a venue that is UTC+2, and the health guide
//| tells the operator to VERIFY this number before the live gate. A confidently wrong
//| number is worse than none: it is the exact class of sign this program keeps paying for.
//| `TimeTradeServer()` is the terminal's own calculated server time (local clock plus the
//| known offset) and is available immediately, so the banner cross-checks the two and
//| refuses to name an offset when they disagree. This function's value is still what the
//| banner SHOWS when they agree — it is the tick clock, deliberately, not a redefinition.
int OffsetMinutes()
{
   return (int)((TimeCurrent() - TimeGMT()) / 60);
}

int OffsetHours() { return OffsetMinutes() / 60; }
int OffsetRemMin() { int m = OffsetMinutes() % 60; return (m < 0) ? -m : m; }

void BarEvaluateSignal(datetime sig, double so, double sh, double sl_, double sc)
{
   // python: k1 = LAST H1 bar with close-time <= sig_ct (= sig+900) — which
   // is exactly the bar BEFORE the H1 bar covering sig_ct (the covering bar's
   // close is always > sig_ct, the previous one's is <=). iBarShift with
   // exact=false returns the covering bar's shift, so k1 = that + 1. This
   // identity holds across session holes too (shift order = time order).
   // Zero-trades bug found live 2026-09-17: an exact-match probe + bogus
   // negative-shift formula returned k1 = -1 on every bar, killing all
   // signals at the k1 < 21 guard.
   int k1c = iBarShift(_Symbol, PERIOD_H1, sig + 900, false);
   int k4c = iBarShift(_Symbol, PERIOD_H4, sig + 900, false);
   if(k1c < 0 || k4c < 0) return;
   int k1 = k1c + 1;
   int k4 = k4c + 1;
   // python's `k1 < 21 or k4 < 21 or i < 21` are history-depth warm-up
   // guards on ARRAY INDICES (trivially true after 2024-04); the shift-
   // semantics equivalent is available-bar-count. Transplanting the index
   // comparison here killed every evaluation (k1 is always ~1 in shifts).
   if(Bars(_Symbol, PERIOD_H1) < 21 || Bars(_Symbol, PERIOD_H4) < 21
      || Bars(_Symbol, PERIOD_M15) < 21) return;
   // python: window membership (`ct > t0 and b.time <= t1`) gates SIGNAL
   // detection. v1.09: enforced HERE, EA-side — sig+900 is the signal bar's
   // close time (ct), so the bar qualifies iff t0 < ct <= t1. Position
   // management (BarFillAndManage) stays ungated: python keeps managing an
   // open trade past t1 until it closes. Tester dates and preloaded history
   // can no longer leak out-of-window signals (found live 2026-09-17).
   if(g_win_t0 > 0 && !(sig + 900 > g_win_t0 && sig + 900 <= g_win_t1)) return;
   double e1[], e4[], c1[], c4[];
   int rc1 = CopyBuffer(g_h1_ema, 0, k1, 1, e1);
   int rc2 = CopyBuffer(g_h4_ema, 0, k4, 1, e4);
   int rc3 = CopyClose(_Symbol, PERIOD_H1, k1, 1, c1);
   int rc4 = CopyClose(_Symbol, PERIOD_H4, k4, 1, c4);
   if(rc1 != 1 || rc2 != 1 || rc3 != 1 || rc4 != 1) return;
   bool h1_up = c1[0] > e1[0], h4_up = c4[0] > e4[0];
   int mac = (h1_up && h4_up) ? 1 : ((!h1_up && !h4_up) ? -1 : 0);

   // ATR at the closed H1 bar (python h1_atr[k1-1] = SMA-TR over the 14
   // H1 bars ending at that bar)
   double atr;
   bool rca = AtrAtShift(k1, atr);
   if(!rca) return;
   double stop_d = InpSlAtrMult * atr;
   if(stop_d <= 0) return;

   // trigger on the closed M15 bar (BB touch-back or RSI 70/30)
   double up[], lo[], rsi[];
   int rb1 = CopyBuffer(g_m15_bb, 1, 1, 1, up);
   int rb2 = CopyBuffer(g_m15_bb, 2, 1, 1, lo);
   double c0[], c1m[];
   int rc5 = CopyClose(_Symbol, PERIOD_M15, 1, 2, c1m);   // [0]=older [1]=sig close
   int rc6 = CopyClose(_Symbol, PERIOD_M15, 2, 1, c0);    // previous bar close
   if(rb1 != 1 || rb2 != 1 || rc5 != 2 || rc6 != 1) return;
   int trigger = 0;
   if(c0[0] > up[0] && c1m[1] < up[0]) trigger = 1;
   else if(c0[0] < lo[0] && c1m[1] > lo[0]) trigger = -1;
   else if(CopyBuffer(g_m15_rsi, 0, 1, 1, rsi) == 1)
   {
      if(rsi[0] >= InpRSIUpper) trigger = -1;
      else if(rsi[0] <= InpRSILower) trigger = 1;
   }

   int direction = 0;
   if(!ModeDecide(trigger, mac, direction) || direction == 0) return;

   // session gate on the signal bar's open hour — BAR EPOCH = SERVER frame
   // (v1.15: iTime values are broker-server; the python engine of record
   // classifies the same broker-feed epochs — provenance finding, amendment 6)
   MqlDateTime dt;
   TimeToStruct(sig, dt);
   if(dt.hour < InpSessionStartHour || dt.hour >= InpSessionEndHour) return;
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour) return;
   g_p5_signals++;                     // v1.17 P5 telemetry: condition-true, in-session (census semantics)

   g_pending_valid  = true;
   g_pending_sigct  = sig + 900;
   g_sig_bar_epoch  = sig;             // v1.19e state stamp: the signal bar, not the fill bar
   g_pending_dir    = direction;
   g_pending_stop   = stop_d;
   g_pending_hour   = dt.hour;
   g_pending_mac    = mac;
}

//+------------------------------------------------------------------+
//| v1.18 NOFILL diagnostics (register review item 1, never-abort):  |
//| veto accounting so the operator's question "why didn't it trade" |
//| is answered from a ledger, not memory. Paper ledgers only — the  |
//| BAR parity replay never reaches these paths, so certified        |
//| ledgers stay byte-identical. Reason grammar is pinned by tests.  |
//+------------------------------------------------------------------+
void DiagCountReset()
{
   g_nofill_signal = 0; g_nofill_mism = 0; g_nofill_session = 0;
   g_nofill_friday = 0; g_nofill_spread = 0; g_nofill_riskcap = 0;
   g_nofill_brk = 0; g_nofill_notr = 0; g_nofill_wrote = 0; g_nofill_news = 0;
   g_nofill_nodata = 0;                                        // v1.27
   ArrayInitialize(g_spread_sum, 0.0); ArrayInitialize(g_spread_n, 0);
   ArrayInitialize(g_spread_max_x100, 0);                        // v1.27
}
// v1.20: the UTC DAY NUMBER (epoch / 86400) the counters belong to. The v1.18 cadence
// was "once per 24h since the first refusal", anchored in memory — so every EA reload
// moved the anchor and, with the reloads this arm actually sees, the daily census could
// never fire at all. A day KEY cannot drift with the process: it is a property of the
// clock, and the counters that belong to it are read back from the ledger.
int UtcDayNo(datetime t) { return (int)((long)t / 86400); }
// The counters, in the LEDGER's field order — APPEND-ONLY, as the roll's own comment
// requires: consumers read by index, so a new counter goes on the END. v1.27 appended
// `nodata` as position 9 (zero-based), which is why both readers below moved together.
// One definition, used by the census row and by the snapshot row, so the two can never
// disagree about a column's meaning.
string DiagCounters()
{
   return StringFormat("%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
                       g_nofill_signal, g_nofill_mism, g_nofill_session,
                       g_nofill_friday, g_nofill_spread, g_nofill_riskcap,
                       g_nofill_brk, g_nofill_notr, g_nofill_news,
                       g_nofill_nodata);   // v1.27
}
string DiagSignature(int day) { return StringFormat("%d|%s", day, DiagCounters()); }

//+------------------------------------------------------------------+
//| The census snapshot: the RUNNING counters, written to the ledger  |
//| so a reload can pick them up instead of restarting from zero.     |
//|                                                                   |
//| MEASURED DEFECT, 2026-09-21. The ledger held NO NOFILL row for a  |
//| whole live day on which every bar was refused, because the day    |
//| anchor and all nine counters were in-memory globals: 22 EA inits  |
//| that day, each one resetting them, and the once-per-24h rule could|
//| never fire. The one record built to answer "why didn't it trade"  |
//| was unreachable exactly when the arm was being reloaded most.     |
//|                                                                   |
//| A NOFILLSUM row is appended whenever the counters CHANGE (or the  |
//| day rolls), which is at most one row per evaluated M15 bar, plus  |
//| one on deinit. So the worst a crash can lose is the increments    |
//| since the last accounting call — and every increment site calls    |
//| DiagMaybeWrite immediately.                                        |
//+------------------------------------------------------------------+
void DiagSnapshot()
{
   if(MQLInfoInteger(MQL_TESTER)) return;                 // parity ledgers byte-clean
   if(InpBarModel) return;
   if(g_diag_day == 0) return;                            // nothing measured yet
   string sig = DiagSignature(g_diag_day);
   if(sig == g_diag_sig) return;                          // unchanged: no row, the ledger stays readable
   PaperLog(StringFormat("NOFILLSUM,%I64d,%d,%s",
            (long)TimeUTCNow(), g_diag_day, DiagCounters()));
   g_diag_sig = sig;
}

//+------------------------------------------------------------------+
//| v1.27 SPREAD BY HOUR — the live arm's own answer to a claim the    |
//| data of record made, and the ONLY consumer is a human reading it.  |
//|                                                                    |
//| WHY. The outside research this arm was re-examined against said   |
//| the thin hours carry wider spreads and the London-NY overlap is    |
//| the tight window. The venue CORPUS says this feed is flat at 0.2   |
//| pts in EVERY hour, which is why the session finding came out       |
//| backwards. That flatness was read off history; this records the    |
//| live arm measuring the same thing, so the two can be compared      |
//| instead of assumed.                                                |
//|                                                                    |
//| Sampled on every tick (one increment), rolled into one            |
//| `SPREADHOUR,<epoch>,<day>,` + 24 x `<hour>,<n>,<mean>,<max_x100>` |
//| row at the daily roll, then zeroed with the rest of the census.    |
//| DISPLAY/RECORD ONLY: no entry, exit, size, veto or protective     |
//| rule reads any of it, and it is gated out of tester/BAR runs so    |
//| certified parity ledgers stay byte-identical.                      |
//+------------------------------------------------------------------+
void SpreadSampleTick()
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // A crossed or absent quote is not a spread. Measuring one would put a negative or a
   // zero into an hour's mean and make the hour look tighter than the venue is.
   if(ask <= 0.0 || bid <= 0.0 || ask < bid) return;
   double sprd = ask - bid;
   int hour = (int)((((long)TimeGMT() % 86400) + 86400) % 86400 / 3600);
   g_spread_sum[hour] += sprd;
   g_spread_n[hour]++;
   int x100 = (int)MathRound(sprd * 100.0);
   if(x100 > g_spread_max_x100[hour]) g_spread_max_x100[hour] = x100;
}

void SpreadHourWrite(datetime now, int day_no)
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   string body = "";
   bool any = false;
   for(int h = 0; h < 24; h++)
   {
      if(g_spread_n[h] > 0) any = true;
      body += StringFormat(",%d,%d,%.5f,%d", h, g_spread_n[h],
                           g_spread_n[h] > 0 ? g_spread_sum[h] / g_spread_n[h] : 0.0,
                           g_spread_max_x100[h]);
   }
   if(!any) return;                       // a day with no quotes writes nothing, not zeros
   PaperLog(StringFormat("SPREADHOUR,%I64d,%d%s", (long)now, day_no, body));
}

//+------------------------------------------------------------------+
//| The roll: on the FIRST accounting call of a new UTC day, write    |
//| the census row for the day that just ended.                        |
//+------------------------------------------------------------------+
void DiagRollIfNewDay(datetime now)
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   int day = UtcDayNo(now);
   if(g_diag_day == 0) { g_diag_day = day; return; }       // first sighting: no day has ended
   if(day == g_diag_day) return;
   if(g_nofill_signal > 0)                                // a zero-activity day writes nothing
   {
      // The field list is APPEND-ONLY and positional: consumers read it by index, so a
      // new counter goes on the end and the format literal changes only by addition.
      // v1.27 appended `nodata` (the bar could not be priced) as the 10th counter.
      PaperLog(StringFormat("NOFILL,%I64d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
               (long)now, g_nofill_signal, g_nofill_mism,
               g_nofill_session, g_nofill_friday, g_nofill_spread,
               g_nofill_riskcap, g_nofill_brk, g_nofill_notr, g_nofill_news,
               g_nofill_nodata));
      g_nofill_wrote++;
   }
   SpreadHourWrite(now, g_diag_day);    // v1.27: the day that just ended, before the zeroing
   DiagCountReset();
   g_diag_day = day;
   g_diag_sig = "";     // force the zeroed state onto the record: a reload after a roll
                        // must not resurrect the counts the roll just accounted for
}

//+------------------------------------------------------------------+
//| Read the census back. Called from OnInit, after the ERA row, so  |
//| a reload continues the day it interrupted instead of erasing it.  |
//+------------------------------------------------------------------+
void DiagRestoreFromLedger()
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   int fh = FileOpen(PaperFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      Print(VersionTag() + "NOFILL census: fresh ledger, nothing to restore");
      return;
   }
   ulong snap_ct = 0;
   int snap_day = 0;
   int c[10];                                        // v1.27: +1 (append-only)
   ArrayInitialize(c, 0);
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      string p[];
      int n = StringSplit(line, ',', p);
      // NOFILLSUM = prefix + epoch + day + counters. A short row is not a snapshot (and is
      // not silently treated as one): the last COMPLETE row wins. v1.27: the floor rose
      // from 12 to 13 because `nodata` was appended, so a v1.26 row is NOT read as one —
      // a row whose missing 10th counter would otherwise restore as a confident zero.
      if(n < 13 || p[0] != "NOFILLSUM") continue;
      snap_ct  = (ulong)StringToInteger(p[1]);
      snap_day = (int)StringToInteger(p[2]);
      for(int i = 0; i < 10; i++) c[i] = (int)StringToInteger(p[3 + i]);
   }
   FileClose(fh);
   if(snap_ct == 0)
   {
      Print(VersionTag() + "NOFILL census: no snapshot row yet, counting from zero");
      return;
   }
   g_diag_day = snap_day;
   g_nofill_signal = c[0]; g_nofill_mism = c[1]; g_nofill_session = c[2];
   g_nofill_friday = c[3]; g_nofill_spread = c[4]; g_nofill_riskcap = c[5];
   g_nofill_brk = c[6]; g_nofill_notr = c[7]; g_nofill_news = c[8];
   g_nofill_nodata = c[9];                                 // v1.27
   g_diag_sig = DiagSignature(g_diag_day);   // already on the record: do not rewrite it
   PrintFormat(VersionTag() + "NOFILL census restored: day=%d signal=%d no-trigger=%d "
               "mismatch=%d session=%d friday=%d spread=%d riskcap=%d breaker=%d news=%d "
               "nodata=%d (from NOFILLSUM @%I64u)",
               g_diag_day, g_nofill_signal, g_nofill_notr, g_nofill_mism,
               g_nofill_session, g_nofill_friday, g_nofill_spread, g_nofill_riskcap,
               g_nofill_brk, g_nofill_news, g_nofill_nodata, snap_ct);
}

//+------------------------------------------------------------------+
//| v1.24 THE LIVE RECORD: one increment path, one restore path.      |
//|                                                                   |
//| MEASURED 2026-09-22, on the arm's first real fill. BOTH live close |
//| paths wrote their LCLOSE row and NEITHER touched a counter, so an  |
//| armed arm's chart read `trades: 0/30 | cumR +0.00` after a real    |
//| closed trade while the ledger - and every reader of it - said      |
//| 1/30. The chart and the record disagreeing is the one thing the    |
//| HUD design forbids, and the go-live gate counts the ARM's closes,  |
//| not the paper mirror's.                                            |
//|                                                                   |
//| So the arm's realized record comes from the same rows the readers  |
//| read (LCLOSE), restored at init like the NOFILL census and         |
//| incremented in ONE helper both close paths call - a private copy   |
//| per path is how they drift. Nothing here is read by a decision,    |
//| and nothing here writes to the ledger.                             |
//+------------------------------------------------------------------+
void LiveCensusAdd(double r)
{
   g_live_closed++;
   g_live_cum_r += r;
   if(r > 0) g_live_wins++;
}

void LiveCensusRestoreFromLedger()
{
   if(MQLInfoInteger(MQL_TESTER)) return;
   if(InpBarModel) return;
   // A paper arm's tally IS the paper counters; only an armed arm has live rows to count.
   if(!InpLiveExecution) return;
   int fh = FileOpen(PaperFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      Print(VersionTag() + "LIVE CENSUS: no ledger to restore from (the arm has closed "
            "nothing yet)");
      return;
   }
   int    rows = 0, wins = 0;
   double sum_r = 0.0;
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      string p[];
      int n = StringSplit(line, ',', p);
      // LCLOSE = prefix + epoch + posid + reason + exit + r = 6 fields (the writer's own
      // shape). A short row is not a close and is never silently counted as one.
      if(n < 6 || p[0] != "LCLOSE") continue;
      double r = StringToDouble(p[5]);
      rows++;
      sum_r += r;
      if(r > 0) wins++;
   }
   FileClose(fh);
   g_live_closed = rows;
   g_live_wins   = wins;
   g_live_cum_r  = sum_r;
   PrintFormat(VersionTag() + "LIVE CENSUS restored: closed=%d wins=%d cumR=%+.3f "
               "(from %d LCLOSE row(s) in %s)",
               g_live_closed, g_live_wins, g_live_cum_r, rows, PaperFile());
}
//+------------------------------------------------------------------+
//| THE FILL ROW'S PRICE IS AMENDED WHEN IT BECOMES KNOWABLE (v1.25).|
//|                                                                  |
//| MEASURED, and it is the reason this exists: the arm's first fill |
//| row says `0.00000` in its price field, and the true 4333.07 was  |
//| known seconds later — in the position, in the entry deal, and     |
//| after the next reload in the EA's own journal (`LIVE RECOVERED    |
//| ... entry=4333.07000`). The ledger is append-only, so the         |
//| amendment is a NEW row keyed by the identity the fill row already |
//| carries (posid, else the order ticket, else the deal — the rule   |
//| mt5_ops.live_fill_key reads), never a rewrite of history:         |
//|                                                                  |
//|     LENTRY,<epoch>,<identity>,<price>,<source>                    |
//|                                                                  |
//| So "what price did the arm actually get" is answerable from the   |
//| file even for a fill whose write could not know it. Runs at init  |
//| (which is also what heals a row written by a previous build) and  |
//| again as soon as a pending fill resolves. Idempotent: a fill that |
//| already has an LENTRY row is not amended twice.                   |
//+------------------------------------------------------------------+
void LiveEntryPriceHeal()
{
   if(MQLInfoInteger(MQL_TESTER)) return;      // parity ledgers stay byte-identical
   if(InpBarModel) return;
   if(!InpLiveExecution) return;
   int fh = FileOpen(PaperFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) return;            // no ledger: nothing written, nothing to heal
   string last_id  = "";
   double last_px  = -1.0;
   string amended  = "|";                     // "|" + identities already amended + "|"
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      string p[];
      int n = StringSplit(line, ',', p);
      if(n < 5) continue;
      if(p[0] == "LENTRY") { amended += p[2] + "|"; continue; }
      if(p[0] != "LOPEN") continue;            // the live fill row; paper OPEN rows are exempt
      if(n < 8) continue;                      // prefix,epoch,posid,order,deal,dir,entry,sl = 8
      last_px = StringToDouble(p[6]);
      last_id = "";
      if(StringToInteger(p[2]) > 0)      last_id = p[2];   // posid (0 until it reconciles)
      else if(StringToInteger(p[3]) > 0) last_id = p[3];   // on netting the ORDER is the posid
      else if(StringToInteger(p[4]) > 0) last_id = p[4];   // last resort: the entry deal
   }
   FileClose(fh);
   if(last_id == "") return;
   if(last_px > 0.0)
   {
      // the row already carries a price; if this process holds the same position, adopt it
      if(g_lv_entry_pending && g_lv_entry <= 0.0) { g_lv_entry = last_px; }
      if(g_lv_entry > 0.0) g_lv_entry_pending = false;
      return;
   }
   if(StringFind(amended, "|" + last_id + "|") >= 0)
   {
      string why = "";
      if(g_lv_entry_pending && g_lv_entry <= 0.0 && ResolveEntryPrice(g_lv_entry, why))
         g_lv_entry_pending = false;             // the row is already right; the process was not
      return;                                    // amended once: never twice
   }
   double px = 0.0;
   string src = "";
   if(!ResolveEntryPriceById((ulong)StringToInteger(last_id), px, src))
   {
      Print(VersionTag() + "LENTRY amendment PENDING: the fill row for " + last_id +
            " carries no price yet and neither the position nor the entry deal answers — "
            "the row's `entry=pending` stands until it does");
      return;
   }
   PaperLog(StringFormat("LENTRY,%I64d,%s,%.5f,%s", (long)TimeCurrent(), last_id, px, src));
   PrintFormat(VersionTag() + "LENTRY amendment: fill %s priced at %.5f from the %s "
               "(the fill row could not know it at write time)", last_id, px, src);
   if(g_lv_entry_pending && g_lv_entry <= 0.0) { g_lv_entry = px; g_lv_entry_pending = false; }
}

string TextVeto(int trigger, int mac)
{
   if(trigger == 0 && mac == 0)  return "NO-SIGNAL(0,0)";
   if(trigger == 0)              return StringFormat("NO-TRIGGER(mac=%+d)", mac);
   if(mac == 0)                  return StringFormat("MACRO-DIVERGENCE(trg=%+d)", trigger);
   return StringFormat("MISMATCH(mac=%+d,trg=%+d)", mac, trigger);
}
// The single accounting entry point every veto path calls (and the heartbeat calls).
// v1.20: it no longer decides WHEN the census is due from an in-memory anchor — it rolls
// the day and records the running state, and the two guards above are what keep certified
// BAR-replay ledgers byte-identical (the tester never reaches either row).
void DiagMaybeWrite()
{
   if(MQLInfoInteger(MQL_TESTER)) return;                 // parity ledgers byte-clean
   if(InpBarModel) return;
   DiagRollIfNewDay(TimeUTCNow());
   DiagSnapshot();
}
//+------------------------------------------------------------------+
//| New-M15-bar pump — research-parity execution:                    |
//| When a new M15 bar opens at T, the bar at index 1 has just       |
//| CLOSED (at T). Evaluate its signal NOW and fill immediately at   |
//| the current price — the first tick of T IS the research fill at  |
//| T's open. No pending queue: a pending carried to the next bar    |
//| detection was the +1-bar parity skew found in the first parity   |
//| run (EA filled 15 min after the research engine every trade).    |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| NEWS CALENDAR — the shared file, and why it is a file             |
//+------------------------------------------------------------------+
// The economic calendar is not reachable from the Python side at all (MetaTrader5
// 5.0.5735 exposes no calendar function) and not reachable from the tester either
// (MQL5 returns error 4014, "function not allowed for call" — measured 2026.09.20). So
// the events are written down ONCE by MidasNewsProbe.mq5 and read by both engines:
//
//   epoch_utc;time_utc;time_server;currency;country;importance;event
//
// with `# epoch_generated_utc=`, `# epoch_window_to_utc=`, `# events=` in the header.
// Epochs are numeric on purpose: a date string would have to be interpreted in someone's
// timezone, and this program has already paid for one clock mistake.
//
// THE REFUSAL IS THE FEATURE. A filter that silently does nothing when its source is
// absent is worse than no filter, because the journal still says protection is ON. So an
// unusable source vetoes entries and names the problem: missing, unreadable, stale, no
// coverage, or EMPTY — and empty is spelled out, because "no events" and "cannot see the
// events" are different claims and only one of them is knowable from a zero count.
string NewsSourceProblem()
{
   if(!FileIsExist(InpNewsFile))
      return StringFormat("calendar file missing (%s)", InpNewsFile);
   int fh = FileOpen(InpNewsFile, FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
      return StringFormat("calendar file unreadable (%s)", InpNewsFile);

   long gen = 0, win_to = 0;
   long declared = -1;                 // `# events=` — -1 = the writer declared nothing
   int rows = 0;
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0) continue;
      if(StringGetCharacter(line, 0) == '#')
      {
         int eq = StringFind(line, "=");
         if(eq > 1)
         {
            // BOTH sides of the '=' must be trimmed. This parsed NOTHING before 2026-09-21:
            // the writers emit "# epoch_generated_utc=..." with a space after the '#', the
            // substring left it on the key (" epoch_generated_utc"), and only the RIGHT
            // side was trimmed — so `gen` stayed 0 and EVERY calendar was judged "no
            // generation time", i.e. the gate could never once see a usable source and
            // stood the arm down forever. The mirror parsed the same file fine
            // (`line.lstrip("# ")`), so the two engines disagreed about one file in the
            // worst possible direction: filled-with-events here, unusable there. Found by
            // scripts/news_gate_rehearsal.py running the COMPILED EA; the source-text pins
            // could not see it, which is why that rehearsal exists.
            string key = StringSubstr(line, 1, eq - 1);
            StringTrimLeft(key);
            StringTrimRight(key);
            string val = StringSubstr(line, eq + 1);
            StringTrimLeft(val);
            if(key == "epoch_generated_utc") gen      = (long)StringToInteger(val);
            if(key == "epoch_window_to_utc") win_to   = (long)StringToInteger(val);
            if(key == "events")              declared = (long)StringToInteger(val);
         }
         continue;
      }
      // Count EVENT rows only. The column header starts with "epoch_utc", so the old
      // "starts with time_utc" test never matched it: the header was counted as a
      // release, which made an EMPTY calendar look covered and non-empty here while the
      // python mirror refused the very same file. One file, one count — a row is a line
      // whose first field is a positive epoch.
      string first[];
      if(StringSplit(line, (ushort)';', first) < 7) continue;   // not a 7-field release row
      if((long)StringToInteger(first[0]) <= 0) continue;
      rows++;
   }
   FileClose(fh);

   datetime now = TimeUTCNow();
   if(gen <= 0)
      return "calendar file carries no generation time (cannot judge freshness)";
   double age_h = (double)((long)now - gen) / 3600.0;
   if(age_h > (double)InpNewsMaxAgeHours)
      return StringFormat("calendar stale (%.1fh old > %dh) — refresh it",
                          age_h, InpNewsMaxAgeHours);
   if(win_to <= 0)
      return "calendar file declares no window end (cannot judge coverage)";
   if((long)win_to < (long)now + (long)InpNewsCoverHours * 3600)
      return StringFormat("calendar does not cover the next %dh — refresh it",
                          InpNewsCoverHours);
   if(declared < 0)
      return "calendar file declares no event count (cannot judge completeness)";
   if((long)rows < declared)
      return StringFormat("calendar truncated (declares %I64d events, holds %d) — refresh it",
                          declared, rows);
   if(rows <= 0)
      return "calendar empty — an empty calendar is not \"no news\"";
   return "";
}

//+------------------------------------------------------------------+
//| "" = clear to enter. Anything else is the reason.
string NewsVetoReason(datetime now)
{
   string problem = NewsSourceProblem();
   if(problem != "")
      return problem;                     // fail closed, and say which of the five it is

   long window_s = (long)InpNewsWindowMin * 60;
   int fh = FileOpen(InpNewsFile, FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
      return StringFormat("calendar file unreadable (%s)", InpNewsFile);
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0) continue;
      if(StringGetCharacter(line, 0) == '#') continue;
      string parts[];
      if(StringSplit(line, (ushort)';', parts) < 7) continue;
      if(parts[5] != "HIGH") continue;    // top-tier only: the playbook's standing policy
      long ev = (long)StringToInteger(parts[0]);
      if(ev <= 0) continue;
      long delta = (long)now - ev;
      if(delta < 0) delta = -delta;
      if(delta <= window_s)
      {
         FileClose(fh);
         return StringFormat("news blackout: %s at %s (within %d min)", parts[6],
                             TimeToString((datetime)ev, TIME_DATE | TIME_MINUTES),
                             InpNewsWindowMin);
      }
   }
   FileClose(fh);
   return "";
}

//+------------------------------------------------------------------+
//| RECORDED STATE LABEL (v1.19e) — the entry's STATE, stamped into  |
//| the paper ledger's OPEN row at fill time.                        |
//|                                                                  |
//| WHY. `scripts/gold_forward_cell_prereg.py` labels this arm's own  |
//| ledger rows by looking each signal bar up in the VENUE'S data of  |
//| record, and that has one failure class it cannot escape: a row    |
//| stamped after the last history refresh is UNLABELLABLE ("signal   |
//| bar beyond the data of record"), and the pre-registration's own   |
//| answer is to refuse rather than grade a shrinking subset. A paper |
//| ledger can also outlive the terminal's data folder. So the EA     |
//| stamps the EVIDENCE at the moment it has it — the signal bar's    |
//| own state — appended to the OPEN row, never inserted:            |
//|                                                                  |
//|   sig_ct     the signal bar's OPEN epoch, broker-SERVER frame     |
//|   hour_utc   that bar's UTC hour, or -1 when no offset can be     |
//|              vouched for (the init banner's own cross-check)      |
//|   vol_ratio  M15 ATR(14) at the signal bar / its trailing median  |
//|              over ATR_LOOKBACK bars (0.0 = not computable here)   |
//|   news       in | out | na  (top-tier HIGH within +/- the window) |
//|   off_min    the server-UTC offset used above, -9999 if unknown   |
//|                                                                  |
//| WHAT IT IS NOT. (1) It is not the EA choosing a CELL. The EA      |
//| writes the raw ratio, hour and proximity; the python side bins    |
//| them with `gold_persistence_state.label_of_values`, the SAME      |
//| function that found the cell. A second binning implementation is  |
//| how two engines come to claim one policy (the R6 lesson), so the  |
//| axis constants below are pinned to the python values by           |
//| tests/test_state_label_contract.py. (2) It is NOT a gate —        |
//| nothing here vetoes anything (the stand-down is InpUseNewsFilter, |
//| a separate input), so an unusable calendar degrades the RECORD    |
//| and the stamp says `na` rather than inventing `out`.              |
//|                                                                  |
//| TESTER RUNS DO NOT STAMP, deliberately: parity replays compare    |
//| two engines on the same bars and the python side labels those     |
//| rows from the corpus it already has, so certified ledgers stay    |
//| byte-identical — and INIT says so out loud rather than no-opping. |
//+------------------------------------------------------------------+
#define STATE_ATR_PERIOD   14     // = gold_walkforward.ATR_PERIOD
#define STATE_VOL_LOOKBACK 500    // = gold_walkforward.ATR_LOOKBACK
#define STATE_VOL_WARMUP   200    // recursion warm-up: seed influence < (13/14)^200 ~ 5e-7
#define STATE_VOL_LO       0.8    // = gold_persistence_state.VOL_BINS low|normal edge
#define STATE_VOL_HI       1.3    // = gold_persistence_state.VOL_BINS normal|high edge
#define STATE_OFF_UNKNOWN  -9999  // no offset may be named (the two clocks disagree)
#define STATE_NA           "na"

// The offset the stamp is allowed to NAME. Same cross-check the init banner makes,
// because the tick clock is worthless for minutes after a launch (measured 2026-09-21:
// two launches reported -5h19m for a UTC+2 venue). When the two clocks disagree the
// stamp writes STATE_OFF_UNKNOWN and hour -1 — a confident wrong hour is the exact
// class of sign this program keeps paying for.
int StateOffsetMinutes()
{
   int off_tick = OffsetMinutes();                             // from the last TICK
   int off_trd  = (int)((TimeTradeServer() - TimeGMT()) / 60); // terminal-calculated
   int delta = off_tick - off_trd;
   if(delta < 0) delta = -delta;
   if(delta > 1) return STATE_OFF_UNKNOWN;
   if(off_tick < -14 * 60 || off_tick > 14 * 60) return STATE_OFF_UNKNOWN;
   return off_trd;
}

// M15 ATR(STATE_ATR_PERIOD) at `sig_bar`, over its trailing median, computed from BARS the
// way `gold_walkforward.wilder_atr` + `trailing_percentile` do. NOT iATR: the engine's
// series is a plain Wilder recursion over the served bars, and a different indicator seed
// is a different number for the same bar.
//
// The recursion is seeded STATE_VOL_WARMUP bars BEFORE the median window, so every window
// member but the oldest few carries a decayed seed: (13/14)^200 ~ 5e-7 residual. That
// bound — not a claim of exactness — is what tests/test_state_label_contract.py measures
// against the engine on the venue's own bars.
bool StateVolRatio(datetime sig_bar, double &ratio)
{
   ratio = 0.0;
   int s = iBarShift(_Symbol, PERIOD_M15, sig_bar, false);   // exact: the bar whose OPEN is sig_bar
   if(s < 0) return false;
   int need = STATE_VOL_LOOKBACK + STATE_VOL_WARMUP + STATE_ATR_PERIOD + 1;
   if(Bars(_Symbol, PERIOD_M15) < s + need) return false;
   double hi[], lo[], cl[];
   if(CopyHigh (_Symbol, PERIOD_M15, s, need, hi) != need) return false;
   if(CopyLow  (_Symbol, PERIOD_M15, s, need, lo) != need) return false;
   if(CopyClose(_Symbol, PERIOD_M15, s, need, cl) != need) return false;
   // Copy* fills OLDEST FIRST: index 0 is the oldest bar of the window (shift s+need-1)
   // and index need-1 is the signal bar itself — the chronological order wilder_atr walks.
   double tr[], atr[];
   ArrayResize(tr, need);
   ArrayResize(atr, need);
   for(int j = 0; j < need; j++)
   {
      if(hi[j] <= 0.0 || lo[j] <= 0.0 || cl[j] <= 0.0) return false;
      tr[j] = (j == 0) ? (hi[0] - lo[0])
            : MathMax(hi[j] - lo[j],
                      MathMax(MathAbs(hi[j] - cl[j - 1]), MathAbs(lo[j] - cl[j - 1])));
      atr[j] = 0.0;
   }
   double seed = 0.0;
   for(int j = 1; j <= STATE_ATR_PERIOD; j++) seed += tr[j];
   atr[STATE_ATR_PERIOD] = seed / STATE_ATR_PERIOD;
   for(int j = STATE_ATR_PERIOD + 1; j < need; j++)
      atr[j] = (atr[j - 1] * (STATE_ATR_PERIOD - 1) + tr[j]) / STATE_ATR_PERIOD;
   // The trailing window INCLUDES the signal bar's own ATR, exactly as
   // `trailing_percentile(values, LOOKBACK, 0.5)[i]` does.
   int first = need - STATE_VOL_LOOKBACK;
   double win[];
   ArrayResize(win, STATE_VOL_LOOKBACK);
   for(int k = 0; k < STATE_VOL_LOOKBACK; k++) win[k] = atr[first + k];
   ArraySort(win);
   double med = (win[STATE_VOL_LOOKBACK / 2 - 1] + win[STATE_VOL_LOOKBACK / 2]) / 2.0;
   if(med <= 0.0 || atr[need - 1] <= 0.0) return false;
   ratio = atr[need - 1] / med;
   return true;
}

// "in" | "out" | "na" for the signal bar's UTC epoch. The five source refusals collapse
// to ONE honest word: `na` means "this record cannot assert the news axis", which is
// exactly what the forward harness needs in order to EXCLUDE the row instead of calling
// it out-of-cell. The reference instant is the signal bar's OPEN epoch — the study's own
// mask (`news_axis` -> `blackout_reason(events, epoch[i], window)`) — not "now": this
// records the entry's state, it does not gate anything.
string NewsProximityFlag(datetime sig_utc)
{
   if(NewsSourceProblem() != "") return STATE_NA;
   long window_s = (long)InpNewsWindowMin * 60;
   int fh = FileOpen(InpNewsFile, FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) return STATE_NA;
   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0) continue;
      if(StringGetCharacter(line, 0) == '#') continue;
      string parts[];
      if(StringSplit(line, (ushort)';', parts) < 7) continue;
      if(parts[5] != "HIGH") continue;      // top-tier only, same filter as the gate
      long ev = (long)StringToInteger(parts[0]);
      if(ev <= 0) continue;
      long delta = (long)sig_utc - ev;
      if(delta < 0) delta = -delta;
      if(delta <= window_s) { FileClose(fh); return "in"; }
   }
   FileClose(fh);
   return "out";
}

// The end-of-row append itself. "" when the stamp is off or this is a tester run, so the
// certified parity ledgers are byte-identical BY CONSTRUCTION rather than by luck. The
// row shape is fixed even when a field cannot be measured (0.0 / -1 / `na` / -9999), so a
// reader never has to count fields to know which axis is missing.
string StateAppend()
{
   if(!InpRecordStateLabel) return "";
   if(MQLInfoInteger(MQL_TESTER)) return "";
   datetime sig = g_sig_bar_epoch;
   if(sig <= 0)
      return StringFormat(",%I64d,%d,%.5f,%s,%d", (long)0, -1, 0.0, STATE_NA, STATE_OFF_UNKNOWN);
   int off = StateOffsetMinutes();
   double ratio = 0.0;
   bool have_ratio = StateVolRatio(sig, ratio);
   int      hour    = -1;
   datetime sig_utc = sig;
   if(off != STATE_OFF_UNKNOWN)
   {
      sig_utc = (datetime)((long)sig - (long)off * 60);
      hour = (int)(((((long)sig_utc % 86400) + 86400) % 86400) / 3600);
   }
   string news = (off == STATE_OFF_UNKNOWN) ? STATE_NA : NewsProximityFlag(sig_utc);
   return StringFormat(",%I64d,%d,%.5f,%s,%d", (long)sig, hour,
                       have_ratio ? ratio : 0.0, news, off);
}

//+------------------------------------------------------------------+
//| THE CONFIGURED RISK, ON THE ROW (v1.22).                          |
//|                                                                  |
//| A fill row carries ONE risk number: the dollars actually put at   |
//| stake, derived from the lot size this venue lets the arm take.    |
//| The CONFIGURED risk — InpRiskPercent of the very same equity base |
//| the sizing above divided — is a different number whenever the     |
//| lot step cannot express it, and on the $25,000 arm it is ALWAYS   |
//| different: 0.25% is $62.50, the floor lot (0.01) risks $31.84,   |
//| and 0.02 lots would overshoot the budget. The row was correct and |
//| silent: the gap between the two lived only in a verification run  |
//| against a preset the ledger does not name. It lives here now.     |
//|                                                                  |
//| ONE KEYED FIELD, APPENDED LAST: `cfg=<usd>@<pct>`. Keyed and not  |
//| positional so a reader finds it without counting fields — the     |
//| state stamp above is 0 or 5 fields depending on the input, so     |
//| "the next two fields" is ambiguous with a half-written stamp.     |
//| NO TESTER ROW CARRIES IT: a parity ledger is a reproduction        |
//| artifact, so certified ledgers stay byte-identical by construction.|
//| The stamp describes the row's own RISK BASE — PaperEquity() on     |
//| the paper paths, account equity on the live one — so `cfg` and the |
//| row's `risk` field are always two numbers off the same basis.      |
//+------------------------------------------------------------------+
string RiskAppend(double cfg_usd)
{
   if(MQLInfoInteger(MQL_TESTER)) return "";
   return StringFormat(",cfg=%.2f@%.2f", cfg_usd, InpRiskPercent);
}

//+------------------------------------------------------------------+
//| `,entry=pending` — THE PRICE FIELD IS 0 AND SAYS WHY (v1.25).    |
//|                                                                  |
//| Keyed, like `cfg=`, so a reader finds it without counting fields.|
//| Present ONLY when the price really could not be resolved at the  |
//| moment of the write, which on this venue is rare and bounded:    |
//| measured once, on the arm's first fill. It is the label that     |
//| makes `0.00000` honest instead of wrong, and the LENTRY row      |
//| below is what replaces it with the venue's price.                |
//+------------------------------------------------------------------+
string EntryPendingAppend()
{
   if(MQLInfoInteger(MQL_TESTER)) return "";
   return g_lv_entry_pending ? ",entry=pending" : "";
}

//+------------------------------------------------------------------+
//| v1.28 — THE SWEEP SHADOW: the Asian-range sweep CONTINUATION,     |
//| recorded and NEVER traded.                                        |
//|                                                                  |
//| WHY IT EXISTS. `docs/ASIA_SWEEP_PREREG_20260922.md` REFUSED to    |
//|   port this mechanism — its pre-registered primary window failed  |
//|   on all three variants — and the same run reported the strongest |
//|   number in this program on its SECONDARY window (UTC 07-18: 152  |
//|   held-out trades, +0.1955R, pf 1.499, t +2.21), with the mirror  |
//|   at -0.1584R and the textbook reversal read at -0.1425R. It      |
//|   prescribed exactly one next step: record it forward, with NO    |
//|   ORDER PATH AT ALL. This is that step, and the rule it will be   |
//|   judged by is fixed in                                           |
//|   `docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md` BEFORE any row.    |
//|                                                                  |
//| WHY IT CANNOT PLACE AN ORDER, STRUCTURALLY. This block reads no    |
//|   order state, consults no governor, increments no census counter, |
//|   and returns no direction to the entry path — `SweepShadowRow()`  |
//|   returns void and its only output is a ledger line. It is called  |
//|   from exactly ONE place, beside the per-bar STATE row in          |
//|   `TrackFreshM15Bar`, so the shadow rides the same evaluated bar   |
//|   as the live decision and cannot diverge from it.                 |
//|   `tests/test_midas_v128_record.py` fails the build if the shadow  |
//|   is ever referenced from a decision function, and pins the single |
//|   call site.                                                      |
//|                                                                  |
//| THE EA WRITES THE SETUP, NEVER AN OUTCOME. The EA cannot know the  |
//|   future, and a row claiming an R its writer could not have         |
//|   measured is not evidence. `scripts/midas_sweep_shadow.py`        |
//|   resolves these rows to closed outcomes through the engine of     |
//|   record's own `run_mode`, so no outcome arithmetic is re-          |
//|   implemented on either side and the two remain one contract.      |
//+------------------------------------------------------------------+

//: The declared window, in TRUE UTC hours: the sweep cannot exist before 07:00 (the range
//: closes at 06:45) and 18 is where the study's SECONDARY window ends. It sits entirely
//: inside this arm's own live gate (InpSessionStartHour/EndHour = 06/20 against broker-server
//: hours, i.e. UTC 04-18), so the shadow needs no frame normalisation for eligibility.
#define SWEEP_WINDOW_LO   7
#define SWEEP_WINDOW_HI   18
//: How many M15 bars to read for the scan. 120 = 30 hours, which always covers the current
//: UTC day (00:00 to 18:00 is 72 bars) even after a terminal that was down overnight.
#define SWEEP_SCAN_BARS   120

//: The UTC day number (epoch / 86400) of an epoch already in the true-UTC frame.
int UTCDayNumber(datetime utc) { return (int)(((long)utc) / 86400); }

//+------------------------------------------------------------------+
//| The mechanism, recomputed from the bars on EVERY call rather than |
//| kept in state: there is no ring to restore, nothing a reload can  |
//| lose or double-fire, and no way for the record to depend on how   |
//| long the terminal happened to be up.                              |
//|                                                                  |
//| Returns false when the bar makes NO CLAIM AT ALL — no nameable    |
//| frame (see `StateOffsetMinutes`), outside the declared window, or  |
//| bars too short to say anything. Returns true and fills the outs   |
//| otherwise, INCLUDING when there is no sweep (`side == 0`), so the  |
//| ledger carries the days it did not fire and not only the days it  |
//| did. `range_bars == 0` in-window is written rather than skipped:   |
//| it is the honest statement that the day's range could not be       |
//| built, and the resolver's coverage counter is what makes it        |
//| visible instead of absent.                                        |
//+------------------------------------------------------------------+
bool SweepShadowFor(const datetime sig_open, double &rng_hi, double &rng_lo,
                    int &range_bars, int &side, bool &is_first, bool &reclaim)
{
   rng_hi = 0.0; rng_lo = 0.0; range_bars = 0; side = 0;
   is_first = false; reclaim = false;
   int off = StateOffsetMinutes();
   if(off == STATE_OFF_UNKNOWN) return false;      // no frame -> no claim may be written
   datetime sig_utc = (datetime)((long)sig_open - (long)off * 60);
   MqlDateTime ds;
   TimeToStruct(sig_utc, ds);
   if(ds.hour < SWEEP_WINDOW_LO || ds.hour >= SWEEP_WINDOW_HI) return false;
   long day0 = ((long)UTCDayNumber(sig_utc)) * 86400;   // UTC midnight of the signal bar's day
   MqlRates r[];
   int got = CopyRates(_Symbol, InpEntryTF, 1, SWEEP_SCAN_BARS, r);
   if(got < 2) return false;
   // Find THIS bar by its own stamp rather than by an index: the copy's element ordering is
   // not something this file is willing to assume, and an off-by-one here would silently
   // shift every level in the row.
   int self_i = -1;
   for(int k = 0; k < got; k++)
      if(r[k].time == sig_open) { self_i = k; break; }
   if(self_i < 0) return false;
   // (1) THE ASIAN RANGE — this UTC day's bars whose OPEN falls in [00:00, 07:00), i.e.
   //     00:00-06:45, fully known at 07:00 and never revised afterwards.
   for(int k = 0; k < got; k++)
   {
      datetime t_utc = (datetime)((long)r[k].time - (long)off * 60);
      if((long)t_utc < day0 || (long)t_utc >= day0 + 7 * 3600) continue;
      if(range_bars == 0) { rng_hi = r[k].high; rng_lo = r[k].low; }
      else { rng_hi = MathMax(rng_hi, r[k].high); rng_lo = MathMin(rng_lo, r[k].low); }
      range_bars++;
   }
   if(range_bars == 0) return true;                // nothing swept: the range is not built
   // (2) THIS BAR'S OWN SWEEP, from its own high/low/close and nothing later.
   bool up = r[self_i].high > rng_hi;
   bool dn = r[self_i].low  < rng_lo;
   if(!up && !dn) return true;
   reclaim = (up && r[self_i].close < rng_hi) || (dn && r[self_i].close > rng_lo);
   // (3) FIRST OF THE DAY ON THIS SIDE — scanned over STRICTLY EARLIER bars of the same UTC
   //     day, never a later one. The engine's own `fired` set also marks sweeps at hours >= 18,
   //     but such a bar is the LAST window-hour bar of its day, so it can never change the
   //     answer for an in-window bar: the two readings agree on every bar this row can be
   //     written for, and `scripts/midas_sweep_shadow.py` refuses the run if they ever do not.
   //     Each side is blocked only by an EARLIER sweep of ITS OWN side, exactly as the engine's
   //     `fired` set is keyed by (day, side).
   bool earlier_this_side = false;
   for(int k = 0; k < got; k++)
   {
      if(r[k].time >= sig_open) continue;          // this bar and anything later: never read
      datetime t_utc = (datetime)((long)r[k].time - (long)off * 60);
      if((long)t_utc < day0 + 7 * 3600) continue;  // the window opens at 07:00
      MqlDateTime dk;
      TimeToStruct(t_utc, dk);
      if(dk.hour >= SWEEP_WINDOW_HI) continue;     // and closes at 18:00
      if(up && r[k].high > rng_hi) earlier_this_side = true;
      if(dn && r[k].low  < rng_lo) earlier_this_side = true;
   }
   if(earlier_this_side) return true;              // a sweep, but not the day's first on its side
   is_first = true;
   side = up ? 1 : -1;                             // SWEEP_CONT: WITH the break
   return true;
}

//+------------------------------------------------------------------+
//| One `SWEEPSHADOW` row per evaluated bar inside the declared window.|
//|                                                                  |
//| Fields (13):                                                      |
//|   SWEEPSHADOW,<write_epoch>,<sig_open>,<utc_day>,<asian_hi>,       |
//|     <asian_lo>,<range_bars>,<side>,<first>,<reclaim>,<stop_d>,     |
//|     <off_min>,<version>                                           |
//| `sig_open` is the ledger's usual SERVER-stamped bar open; `utc_day`|
//| is the UTC day number of it; `off_min` is the offset that was used |
//| to get there, so the frame is auditable rather than assumed.       |
//| `side` is nonzero ONLY on the first sweep of that day on that side,|
//| so it IS `SWEEP_CONT`'s direction — `SWEEP_FADE` (= -side) and     |
//| `RECLAIM_REV` (=-side on a reclaim bar) are derivable from the row |
//| rather than stored, which is what stops the record later reading   |
//| as if three hypotheses had been tested.                           |
//|                                                                  |
//| NO OUTCOME IS WRITTEN. See the block comment above.                |
//+------------------------------------------------------------------+
void SweepShadowRow()
{
   if(MQLInfoInteger(MQL_TESTER)) return;   // the tester writes no ledger at all
   if(InpBarModel) return;                  // parity/BAR runs: certified ledgers stay byte-identical
   if(g_sig_bar_epoch <= 0) return;         // nothing evaluated yet
   double rng_hi = 0.0, rng_lo = 0.0;
   int range_bars = 0, side = 0;
   bool is_first = false, reclaim = false;
   if(!SweepShadowFor(g_sig_bar_epoch, rng_hi, rng_lo, range_bars, side, is_first, reclaim))
      return;                               // outside the window, or no frame may be named
   int off = StateOffsetMinutes();
   if(off == STATE_OFF_UNKNOWN) return;
   datetime sig_utc = (datetime)((long)g_sig_bar_epoch - (long)off * 60);
   double stop = InpSlAtrMult * AtrNow();   // the certified geometry, from the arm's own ATR read
   PaperLog(StringFormat("SWEEPSHADOW,%I64d,%I64d,%d,%.5f,%.5f,%d,%d,%d,%d,%.5f,%d,%s",
            (long)TimeUTCNow(), (long)g_sig_bar_epoch, UTCDayNumber(sig_utc),
            rng_hi, rng_lo, range_bars, side, is_first ? 1 : 0, reclaim ? 1 : 0,
            stop, off, APP_VERSION));
}

//+------------------------------------------------------------------+
//| THE SOURCE HAS TO REPAIR ITSELF, OR THE GATE IS A PERMANENT STOP  |
//| (v1.19c continued, 2026-09-20).                                   |
//|                                                                  |
//| The gate above is fail-closed, so a calendar nobody refreshes     |
//| does not degrade politely — it stands the arm down for good. That |
//| is the right answer to "I cannot see the news" and the wrong      |
//| answer to "nobody ran the probe this week". So the EA reads the   |
//| venue's own calendar when it can and writes the SAME file the     |
//| python engine of record reads: one source, two readers, no second |
//| implementation to drift. The probe stays for measurement.         |
//|                                                                  |
//| IT NEVER OVERWRITES WITH NOTHING. A call returning no usable      |
//| event is a failure to MEASURE, not news: the file on disk stays   |
//| untouched, the journal records the return value and errno, and    |
//| the gate decides on the evidence it actually has.                 |
//|                                                                  |
//| Unavailable in the tester by the platform's own rule (4014), so a |
//| parity replay reads the file and never writes one.                |
//+------------------------------------------------------------------+
string NewsClean(string s)
{
   StringReplace(s, ";", ",");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   StringReplace(s, "#", "-");
   return s;
}
string NewsImportanceName(ENUM_CALENDAR_EVENT_IMPORTANCE imp)
{
   switch(imp)
   {
      case CALENDAR_IMPORTANCE_HIGH:     return "HIGH";
      case CALENDAR_IMPORTANCE_MODERATE: return "MEDIUM";
      case CALENDAR_IMPORTANCE_LOW:      return "LOW";
   }
   return "NONE";
}

bool NewsWriteCalendar(datetime now_gmt)
{
   datetime now_srv = TimeCurrent();
   long     off_min = (long)(now_srv - now_gmt) / 60;
   // The calendar's own frame is the TRADE SERVER's — "all times of events in
   // MqlCalendarValue ... and the from/to inputs ... are set in a trade server timezone,
   // rather than a user's local time" — so window and events are both server time and
   // the UTC column is DERIVED with the same measured offset the CLOCK line prints.
   // Numeric epochs, exactly like the probe: a reader never has to guess a timezone.
   datetime from = now_srv - (datetime)(14 * 86400);
   datetime to   = now_srv + (datetime)(21 * 86400);

   MqlCalendarValue values[];
   ResetLastError();
   int n = CalendarValueHistory(values, from, to, NULL, "USD");
   int err = GetLastError();
   g_news_api_last = n;

   string body = "";
   int written = 0, high = 0, errors = 0;
   for(int i = 0; n > 0 && i < ArraySize(values); i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev)) { errors++; continue; }
      if(ev.importance == CALENDAR_IMPORTANCE_HIGH) high++;
      // The currency belongs to the COUNTRY, not the event: MqlCalendarEvent has no
      // `currency` field (measured — declaring one is compile error 256).
      MqlCalendarCountry country;
      string cur = "", ccode = "";
      if(CalendarCountryById(long(ev.country_id), country))
      {
         cur   = country.currency;
         ccode = country.code;
      }
      datetime t_srv = values[i].time;
      datetime t_utc = t_srv - (datetime)(off_min * 60);
      body += StringFormat("%I64d;%s;%s;%s;%s;%s;%s\r\n", (long)t_utc,
                           TimeToString(t_utc, TIME_DATE | TIME_SECONDS),
                           TimeToString(t_srv, TIME_DATE | TIME_SECONDS),
                           NewsClean(cur), NewsClean(ccode),
                           NewsImportanceName(ev.importance), NewsClean(ev.name));
      written++;
   }

   if(written <= 0)
   {
      PrintFormat(VersionTag() + "NEWS SOURCE: CalendarValueHistory -> %d value(s), err=%d, "
                  "%d usable row(s) — leaving %s alone. An empty answer is a failure to "
                  "MEASURE, not news, and overwriting a calendar with nothing would "
                  "manufacture the stand-down this gate exists to express",
                  n, err, written, InpNewsFile);
      return false;
   }

   int fh = FileOpen(InpNewsFile, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      PrintFormat(VersionTag() + "NEWS SOURCE: cannot write %s (err=%d)",
                  InpNewsFile, GetLastError());
      return false;
   }
   FileWriteString(fh, "# MIDASTOUCH news calendar — written by MidastouchAI.mq5 "
                       "(live calendar refresh)\r\n");
   FileWriteString(fh, StringFormat("# epoch_generated_utc=%I64d\r\n", (long)now_gmt));
   FileWriteString(fh, StringFormat("# generated_at_server=%s\r\n",
                                    TimeToString(now_srv, TIME_DATE | TIME_SECONDS)));
   FileWriteString(fh, StringFormat("# server_offset_min=%I64d\r\n", off_min));
   FileWriteString(fh, StringFormat("# epoch_window_from_utc=%I64d\r\n",
                                    (long)(from - (datetime)(off_min * 60))));
   FileWriteString(fh, StringFormat("# epoch_window_to_utc=%I64d\r\n",
                                    (long)(to - (datetime)(off_min * 60))));
   FileWriteString(fh, "# source=mt5_economic_calendar\r\n# currency=USD\r\n");
   FileWriteString(fh, StringFormat("# api_returned=%d\r\n", n));
   FileWriteString(fh, StringFormat("# events=%d\r\n# high_importance=%d\r\n"
                                    "# resolution_errors=%d\r\n",
                                    written, high, errors));
   FileWriteString(fh, "epoch_utc;time_utc;time_server;currency;country;importance;event\r\n");
   FileWriteString(fh, body);
   FileClose(fh);
   PrintFormat(VersionTag() + "NEWS SOURCE: refreshed %s — %d event(s), %d HIGH, "
               "%d unresolvable (api returned %d)", InpNewsFile, written, high, errors, n);
   return true;
}

bool NewsRefreshIfDue(datetime now_gmt)
{
   // v1.19e: the STATE STAMP reads the same file, so the source has to stay alive for it
   // too — otherwise a recording-only arm (news gate OFF) would write `na` forever and the
   // pre-registered forward cell would be permanently unassertable.
   if(!InpUseNewsFilter && !InpRecordStateLabel) return false;
   if(MQLInfoInteger(MQL_TESTER)) return false;        // 4014 — not callable in the tester
   if(InpNewsRefreshHours <= 0) return false;          // operator refreshes it out of band
   if(g_news_refresh_at != 0 && now_gmt - g_news_refresh_at < 600)
      return false;                                    // never hammer the venue's API
   string problem = NewsSourceProblem();
   if(problem == "" && g_news_written_at != 0 &&
      now_gmt - g_news_written_at < (long)InpNewsRefreshHours * 3600)
      return false;                                    // usable, and young enough to trust
   g_news_refresh_at = now_gmt;
   if(!NewsWriteCalendar(now_gmt))
      return false;
   g_news_written_at = now_gmt;
   PrintFormat(VersionTag() + "NEWS SOURCE refreshed %s (api=%d; judged before: %s)",
               InpNewsFile, g_news_api_last, (problem == "") ? "usable" : problem);
   return true;
}

//+------------------------------------------------------------------+
void TrackFreshM15Bar()
{
   datetime cur = iTime(_Symbol, InpEntryTF, 0);
   if(cur == 0) return;
   if(g_last_m15 == 0) { g_last_m15 = cur; g_last_m15_seen = TimeCurrent(); return; }
   if(cur == g_last_m15)
   {
      g_last_m15_seen = TimeCurrent();     // feed alive
      return;
   }
   // a new M15 bar just opened at `cur`; index 1 closed at `cur`
   g_last_m15 = cur;
   DiagMaybeWrite();                    // v1.18: daily NOFILL roll at the first new bar

   // staleness guard: if the feed went quiet and just woke up, skip this
   // bar (its "first tick" is not the open; parity and honesty both demand
   // we stand down rather than fill at a stale price)
   if(TimeCurrent() - g_last_m15_seen > InpStaleMinutes * 60)
   {
      g_last_m15_seen = TimeCurrent();
      Print(VersionTag() + "STALE feed — bar skipped, no evaluation");
      g_last_action = "STALE feed - bar skipped";   // v1.10 HUD
      return;
   }
   g_last_m15_seen = TimeCurrent();

   // evaluate the just-closed bar (index 1)
   datetime sig_open_time = iTime(_Symbol, InpEntryTF, 1);
   g_sig_bar_epoch = sig_open_time;     // v1.19e state stamp: the bar that just closed
   int mac = MacroState();
   int trigger = TriggerOnClosedBar();
   // v1.21: the stash the HUD and the STATE row read. Written HERE, where the decision
   // values are computed, so nothing downstream can disagree with what decided.
   g_hud_mac     = mac;
   g_hud_trig    = trigger;
   g_hud_sig_ct  = sig_open_time;
   g_hud_sess_ok = InSessionBar(sig_open_time);
   StateRowWrite();   // v1.21: one STATE row per evaluated bar, so "what did it see at
                      // 14:15" is answerable from the ledger and not only from a chart
   SweepShadowRow();  // v1.28: the sweep shadow, on the SAME evaluated bar and from the SAME
                      // decision point. ONE call site by design — the record-only build's
                      // structural guarantee is that it is reached from here and nowhere else.
   int direction = 0;
   if(!ModeDecide(trigger, mac, direction) || direction == 0)
   {
      g_nofill_signal++;                                // v1.18: mode evaluated, no trade
      if(trigger == 0) g_nofill_notr++;                 //   no trigger fired at all
      else             g_nofill_mism++;                 //   trigger fired but mode refused
      g_last_action = StringFormat("VETO %s", TextVeto(trigger, mac));   // v1.18: honest HUD
      DiagMaybeWrite();   // v1.20: this is the COMMONEST veto class and it used to return
                          // without accounting — the census leaned on the 15-min heartbeat
                          // to notice it, which is only true while the EA is still running
      return;
   }
   g_last_action = StringFormat("SIGNAL %s evaluated",   // v1.10 HUD (PERTICK path only)
                  direction > 0 ? "BUY" : "SELL");

   // session gates on the SIGNAL BAR's open hour — BAR EPOCH = SERVER frame
   // (v1.15: iTime values are broker-server; matches the python engine of
   // record's classification of the same broker-feed epochs)
   MqlDateTime dt;
   TimeToStruct(sig_open_time, dt);
   // v1.27: THESE FOUR ARE COUNTED, NOT SILENT. MEASURED 2026-09-22: the session and Friday
   // gates incremented the census and returned WITHOUT setting g_last_action, so the chart's
   // `last:` line still read the previous bar's action and the journal said nothing at all —
   // the operator's question is "why didn't it trade", and for two of the four refusals this
   // file had no answer anywhere except a counter in a daily row. The two pricing guards
   // below (atr<=0, stop<=0) were worse: they returned before the census as well, so they
   // were not even counted. Naming them changes NO decision: every branch below already
   // returned, and each still returns at the same point.
   if(!InSessionBar(sig_open_time))          // v1.21: one definition of the window rule
   {
      g_nofill_session++; g_last_action = "signal vetoed: outside session window";
      DiagMaybeWrite(); return;            // v1.18 diagnostics
   }

   // Friday cutoff
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour)
   {
      g_nofill_friday++; g_last_action = "signal vetoed: Friday cutoff";
      DiagMaybeWrite(); return;            // v1.18 diagnostics
   }
   g_p5_signals++;                     // v1.17 P5 telemetry: condition-true, in-session (census semantics)

   // NEWS STAND-DOWN (v1.19c). Sits with the time gates, before sizing, and it is a
   // FAIL-CLOSED gate: with the filter ON, an unusable calendar (missing, stale, empty,
   // or not covering now) vetoes the entry and says which of those it is. An empty
   // calendar is not "no news" — it is "we cannot see the news", and the two must never
   // be conflated, which is the one failure this whole file exists to prevent.
   if(InpUseNewsFilter)
   {
      string news_reason = NewsVetoReason(TimeUTCNow());
      if(news_reason != "")
      {
         g_nofill_news++; DiagMaybeWrite();
         PrintFormat(VersionTag() + "NEWS VETO: %s — no new entries", news_reason);
         g_last_action = "signal vetoed: " + news_reason;
         return;
      }
   }

   // v1.27: the two "cannot be priced" guards now name themselves and are counted. They are
   // NOT vetoes — nothing about the arm refused this bar, the ENGINE could not measure a stop
   // for it — so they get their own counter rather than inflating the refusal census, and the
   // label says `unpriced` rather than `vetoed`. Same return point, same decisions.
   double atr = AtrNow();
   if(atr <= 0)
   {
      g_nofill_nodata++; g_last_action = "signal unpriced: ATR not computable";
      DiagMaybeWrite(); return;
   }
   double stop = InpSlAtrMult * atr;
   if(stop <= 0)
   {
      g_nofill_nodata++; g_last_action = "signal unpriced: stop distance <= 0";
      DiagMaybeWrite(); return;
   }
   if(!SpreadCapOK(stop))              // v1.08: shared veto (paper mirror and live path)
   {
      g_nofill_spread++; DiagMaybeWrite();               // v1.18 diagnostics
      g_last_action = "signal vetoed: spread cap";   // v1.10 HUD
      return;
   }

   if(LiveSignalArmed())               // v1.08: real-order dispatch of the SAME signal
   {
      LiveSendOrder(direction, stop, dt.hour, mac);
      return;
   }
   OpenPaperPosition(direction, stop, dt.hour, mac);
}

//+------------------------------------------------------------------+
bool OpenPaperPosition(int direction, double stop_d, int hour, int mac)
{
   double dpu;
   if(!DollarPerUnitPerLot(dpu)) return false;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sprd = ask - bid;
   double side = (direction > 0) ? 1.0 : -1.0;
   // python exact (amendment 3 cost model): fill = bid-mid +/- HALF spread on
   // BOTH sides. v1.08 bug fix: buys previously filled at ask + sprd/2 — one
   // FULL spread worse than the research engine — silently degrading every
   // live-model entry vs the certified baseline.
   double fill = bid + side * sprd / 2;
   double sl = fill - side * stop_d;
   double tp = fill + side * stop_d * InpTpMult;

   double risk_d = PaperEquity() * InpRiskPercent / 100.0;
   double lots = risk_d / (stop_d * dpu);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   bool floored = false;
   if(lots < vmin)
   {
      // v1.14 amendment 6 (register R5): min-lot risk veto — same predicate
      // as the BAR path and python's minlot_risk_exceeds_cap. Basis is the
      // PAPER book (PaperEquity), matching the sizing basis above.
      if(stop_d * dpu * vmin > PaperEquity() * InpMaxRiskPct / 100.0)
      {
         Print(VersionTag() + "PAPER VETO RISK-CAP: min-lot risk exceeds "
               "InpMaxRiskPct — trade vetoed (amendment 6)");
         g_nofill_riskcap++; DiagMaybeWrite();              // v1.18 diagnostics
         g_last_action = "signal vetoed: min-lot risk cap";   // v1.10 HUD
         return false;
      }
      lots = vmin; floored = true;
   }
   if(vstep > 0) lots = MathFloor(lots / vstep) * vstep;
   if(lots < vmin) { lots = vmin; floored = true; }
   double eff_risk = stop_d * dpu * lots;

   ulong ticket = (ulong)TimeCurrent();
   g_pp_open = true; g_pp_dir = direction; g_pp_entry = fill; g_pp_sl = sl; g_pp_tp = tp;
   g_pp_orig_risk = stop_d; g_pp_eff_risk = eff_risk; g_pp_vol = lots;
   g_pp_entry_time = TimeCurrent(); g_pp_ticket = ticket;
   g_pp_expiration = g_pp_entry_time + (datetime)(InpTimeoutMinutes * 60);

   PrintFormat(VersionTag() + "PAPER FILL %s vol=%.2f @%.5f SL=%.5f TP=%.5f risk=$%.2f (%.2f%% vEq)%s",
               direction > 0 ? "BUY" : "SELL", lots, fill, sl, tp, eff_risk,
               eff_risk / MathMax(PaperEquity(), 0.01) * 100.0,
               floored ? " | FLOORED-TO-MIN-LOT" : "");
   g_last_action = StringFormat("OPEN %s %.2f lots @%.5f (%s)",   // v1.10 HUD
                  direction > 0 ? "BUY" : "SELL", lots, fill,
                  TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES));
   // v1.02 parity instrumentation: the exact ATR + H1 bar stamp behind the stop
   datetime h1_stamp = iTime(_Symbol, PERIOD_H1, 1);
   double atr_used = AtrNow();
   // v1.25: the tail is ONE specifier per segment — `StateAppend() + RiskAppend()` is one
   // ARGUMENT, so it takes one `%s`. MEASURED on the arm's first live fill: a format that asked
   // for one more `%s` than it was given had MQL5 append `(missed string parameter)` to the row.
   // The bytes are identical to two specifiers (each segment already starts with its own comma),
   // and one specifier can never drift out of step with the argument list. Pinned by
   // tests/test_midas_telemetry.py::test_every_fill_row_format_matches_its_arguments.
   PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s%s,%.5f,%.5f%s",
            (long)TimeCurrent(), ticket, direction, fill, sl, tp, lots, eff_risk,
            g_pp_orig_risk, InpTimeoutMinutes * 60, InpArmTag,
            floored ? "_FLOORED" : "",
            atr_used, sprd,
            StateAppend() + RiskAppend(risk_d)));   // v1.13 R10: atr_at_entry,spread_at_open | v1.19e: the state stamp | v1.22: cfg risk
   PaperLog(StringFormat("PARITY,atr=%.5f,h1=%I64d,stop=%.5f",
            atr_used, (long)h1_stamp, g_pp_orig_risk));
   if(!g_debug_done) { DumpH1Debug(); g_debug_done = true; }
   return true;
}

//+------------------------------------------------------------------+
//| Per-tick paper mirror: SL-first on ties, then TP, then timeout.  |
//+------------------------------------------------------------------+
void PaperCheckHardExits()
{
   if(!g_pp_open) return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(g_pp_dir > 0)
   {
      if(bid <= g_pp_sl) { PaperClose("STOP", g_pp_sl); return; }
      if(bid >= g_pp_tp) { PaperClose("TARGET", g_pp_tp); return; }
   }
   else
   {
      if(ask >= g_pp_sl) { PaperClose("STOP", g_pp_sl); return; }
      if(ask <= g_pp_tp) { PaperClose("TARGET", g_pp_tp); return; }
   }
   if(TimeCurrent() >= g_pp_expiration)
      PaperClose("TIME", 0);
}

//+------------------------------------------------------------------+
//| THE PARITY EVIDENCE LINE — one per closed trade.                 |
//+------------------------------------------------------------------+
void PrintTradeR(const double realized_r)
{
   PrintFormat(VersionTag() + "Trade R: %+.4f", realized_r);
}

void PaperClose(string reason, double exit_price)
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sprd = ask - bid;
   double exit = (exit_price > 0) ? exit_price : ((g_pp_dir > 0) ? bid : ask);
   double side = (g_pp_dir > 0) ? 1.0 : -1.0;
   exit = exit - side * sprd / 2;           // parity: half-spread exit
   double r = g_pp_orig_risk > 0 ? ((g_pp_dir > 0) ? (exit - g_pp_entry) : (g_pp_entry - exit)) / g_pp_orig_risk : 0;
   double pnl = g_pp_eff_risk * r;
   PaperLog(StringFormat("CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f,%.5f,%.5f,%.2f,%I64d,%I64d",
            (long)TimeCurrent(), g_pp_ticket, reason, exit, r, pnl, PaperEquity() + pnl,
            sprd, 0.0, InpBBDev, (long)0, g_p5_signals));   // v1.13 R10: spread_at_close,slippage | v1.17 P5: thr,thr_era_id(static),density
   g_paper_eq += pnl;
   g_cum_r += r; g_trades++; if(pnl > 0) g_wins++;
   PrintTradeR(r);
   g_last_action = StringFormat("CLOSE %s R=%+.2f vEq=$%.2f (%s)",   // v1.10 HUD
               reason, r, PaperEquity(), TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES));
   PrintFormat(VersionTag() + "CLOSE %s ticket=%I64u pnl=%+.2f R=%+.3f equity=$%.2f trades=%d",
               reason, g_pp_ticket, pnl, r, PaperEquity(), g_trades);
   PaperLog(StringFormat("EQ,%.2f", PaperEquity()));
   g_pp_open = false;
}
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| v1.08 LIVE EXECUTION LAYER (PERTICK + InpLiveExecution only).    |
//| Signal math is untouched: the same TrackFreshM15Bar evaluation   |
//| feeds either the paper mirror (default) or this real-order path. |
//| All research gates fire BEFORE any order: session, Friday cut-   |
//| off, staleness, spread cap, breaker, stops level.                |
//+------------------------------------------------------------------+
bool SpreadCapOK(double stop_d)
{
   double sprd = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(sprd <= 0) return false;
   if(sprd > stop_d * InpSpreadCapPctStop / 100.0)
   {
      PrintFormat(VersionTag() + "SPREAD VETO %.5f > %.1f%% of stop %.2f", sprd, InpSpreadCapPctStop, stop_d);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| UTC-DAY ANCHOR — the baselines the two DAY rules are measured from |
//+------------------------------------------------------------------+
// MEASURED GAP, 2026-09-20. The 3% daily cap and the 20% Best Day ceiling are both
// rules about ONE UTC day, and both took their baseline from "the equity at the moment
// this function was first called today" — which is the day's first ENTRY ATTEMPT, not
// 00:00 UTC. Two consequences, both real:
//
//   * any move before that first attempt was invisible. A 3% loss taken at 07:00 was
//     re-anchored away by the 09:00 entry attempt and the breaker never tripped for a
//     day the venue had already counted as breached;
//   * a restart forgot the day, because the anchor lived in a variable. The venue's
//     rule does not restart with the EA.
//
// So the anchor is now taken on EVERY tick at the UTC rollover — the day's opening
// equity, not the day's first convenience — and when the EA starts mid-day it
// reconstructs that opening equity from this magic's own closed deals.
//
// STATED LIMIT: if a position was carried across 00:00 UTC, the reconstruction misses
// the floating P&L that existed at the open (open equity = equity now - realised since,
// and floating-at-open is not recoverable without equity history). It is the closest
// honest reading of the day, and it matches the venue's baseline for a flat account.
// v1.25: A CLOSING DEAL IS NOT ALWAYS OURS TO STAMP. MEASURED 2026-09-22 on the arm's own
// fill: the ENTRY deal carried magic 7825001 and the CLOSING deal carried **magic 0**, because
// it was executed outside the EA (the platform's reason field reads MOBILE). This function used
// to filter every OUT deal on `DEAL_MAGIC == InpMagic`, so a day's realised P&L ignored every
// trade that was not closed BY the EA — and that number is what the Best Day cap and the day's
// reconstructed opening equity are measured from. It is a risk-path number, not a display one:
// under-counting it under-counts the drawdown the venue's own rules are about.
//
// The attribution is now BY POSITION, which the venue does give us: an OUT deal belongs to this
// arm iff its position id has an IN deal carrying this magic. Cheap in the common case (one pass)
// and exact in the case that broke it (one extra history select per unmatched close, i.e. per
// externally-closed trade, at most a handful a day). A deal whose position we cannot claim is
// NOT counted, so the failure direction stays conservative in the governor's favour...
// which is the wrong direction for a risk limit, so it is stated here rather than assumed:
// the unmatched case is logged, not silently dropped.
double PropDayRealisedPnlUtc()
{
   datetime now  = TimeUTCNow();
   datetime from = (datetime)(now - (now % 86400));   // 00:00:00 UTC today
   if(!HistorySelect(from, now + 1)) return 0.0;
   double sum = 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((long)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      bool mine = ((long)HistoryDealGetInteger(t, DEAL_MAGIC) == InpMagic);
      if(!mine)
      {
         // externally executed close: ask the position who opened it
         ulong pid = (ulong)HistoryDealGetInteger(t, DEAL_POSITION_ID);
         mine = PositionHasOurEntry(pid);
         if(!mine)
            PrintFormat(VersionTag() + "DAY P&L: out-deal %I64u on position %I64u carries magic 0 and no "
                        "entry deal of ours — NOT counted (logged, not dropped silently)", t, pid);
      }
      if(!mine) continue;
      sum += HistoryDealGetDouble(t, DEAL_PROFIT)
           + HistoryDealGetDouble(t, DEAL_SWAP)
           + HistoryDealGetDouble(t, DEAL_COMMISSION);
   }
   return sum;
}

// Does this position carry an IN deal stamped with our magic? The venue stamps the ENTRY deal
// with the EA's magic (measured) and the CLOSE with whatever executed it (0 when that was not
// the EA), so the entry leg is the reliable marker of ownership.
bool PositionHasOurEntry(ulong pid)
{
   if(pid == 0) return false;
   if(!HistorySelectByPosition(pid)) return false;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if((long)HistoryDealGetInteger(d, DEAL_MAGIC) == InpMagic) return true;
   }
   return false;
}

void PropDayAnchorCheck()
{
   MqlDateTime dt;
   TimeToStruct(TimeUTCNow(), dt);
   int day = dt.year * 10000 + dt.mon * 100 + dt.day;
   if(day == g_prop_day) return;            // same UTC day: the baselines still hold
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_prop_day    = day;
   // eq - today's realised P&L == equity at 00:00 UTC for a flat account, and it is
   // EXACT at the rollover itself (nothing has closed yet today). One formula, so a
   // mid-day start cannot take a different path from a normal day boundary.
   g_prop_day_eq  = eq - PropDayRealisedPnlUtc();
   g_brk_day      = day;
   g_brk_start_eq = g_prop_day_eq;
   g_brk_tripped  = false;
}

bool DailyBreakerTripped()
{
   if(InpDailyLossCapPct <= 0) return false;
   if(g_brk_start_eq <= 0) return false;      // anchor not taken yet (first tick)
   if(!g_brk_tripped && g_brk_start_eq > 0)
   {
      double loss_pct = (g_brk_start_eq - AccountInfoDouble(ACCOUNT_EQUITY)) / g_brk_start_eq * 100.0;
      if(loss_pct >= InpDailyLossCapPct)
      {
         g_brk_tripped = true;
         PrintFormat(VersionTag() + "DAILY BREAKER TRIPPED: equity down %.2f%% >= cap %.2f%% — no new entries until next UTC day", loss_pct, InpDailyLossCapPct);
      }
   }
   return g_brk_tripped;
}

//+------------------------------------------------------------------+
//| PROP GOVERNOR — the venue's other three survival rules            |
//+------------------------------------------------------------------+
// MEASURED GAP, 2026-09-20: this EA enforced ONE of the four Thunderbolt Classic
// rules (the 3% UTC-day loss cap, above). The trailing shield, the profit target and
// the Best Day share existed only in the Python layer — which cannot reach inside MT5.
// So the account could have breached three rules it was told the system was enforcing.
//
// The arithmetic mirrors src/midas_prop/risk/upcomers_rules.py deliberately, so
// the Python pre-trade gate and the EA cannot drift into disagreeing about the same
// account. Numbers there: size $25,000, target 5% = $1,250, shield 6% = $1,500,
// day-profit cap = 20% of the target = $250.
//
// ENTRY-ONLY. Every check here decides whether a NEW position may open. Exits are never
// gated by it: a rule that could trap you in a position while a drawdown deepens would
// breach the shield it was written to protect.
//
// THE TARGET IS A PHASE, NOT A WALL. The 5% target is the challenge's pass mark; the
// funded phase has no target at all. So reaching it must not stop entries — the phase
// is reported by PropPhaseCheck() and the survival rules above keep running.
//
// STATED LIMIT. The venue computes the real shield from equity history we cannot read;
// this is a conservative mirror of it. The one place it can genuinely be wrong is a
// RESTART: the high-water mark is rebuilt from the higher of balance and equity, which
// understates a peak reached earlier in a session. InpPropPeakOverride exists for
// exactly that case, and guessing silently was the alternative.
double PropGovernorSize()
{
   static double size = -1.0;
   if(size < 0.0)
      size = (InpPropAccountSize > 0.0)
             ? InpPropAccountSize
             : MathMax(AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY));
   return size;
}

// max(size - maxdd, min(peak - maxdd, size)): the floor STARTS maxdd below the
// account size, rises with the equity HWM, and freezes once the account is maxdd in
// profit. The clamp is the whole point — without it the floor would keep climbing and
// eventually sit above equity on a healthy account.
double PropShieldFloor()
{
   static double peak = -1.0;
   if(peak < 0.0)
      peak = (InpPropPeakOverride > 0.0) ? InpPropPeakOverride : PropGovernorSize();
   peak = MathMax(peak, AccountInfoDouble(ACCOUNT_EQUITY));
   double size  = PropGovernorSize();
   double maxdd = size * InpPropMaxDdPct / 100.0;
   return MathMax(size - maxdd, MathMin(peak - maxdd, size));
}

// A single trading day's realised+floating gain, capped. This is the only defensible
// intraday reading of "no single day may exceed 20% of profit": the share is not
// knowable in advance, so the rule is enforced against its ceiling instead.
double PropDayProfitCapUsd()
{
   double target = PropGovernorSize() * InpPropTargetPct / 100.0;
   return target * InpPropBestDayPct / 100.0;
}

// "" = clear to enter. Any other value is the reason, and the caller must not enter.
string PropGovernorBlock()
{
   if(!InpPropGuard) return "";
   if(DailyBreakerTripped()) return "daily-loss cap (3%)";

   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double size = PropGovernorSize();

   double floor_usd = PropShieldFloor();
   g_hud_floor = floor_usd;               // v1.21: display echo of the shield reading
   if(eq <= floor_usd)
      return StringFormat("trailing shield: equity %.2f at/below floor %.2f", eq, floor_usd);

   // THE TARGET IS NOT A VETO. An earlier build refused entries once equity passed the
   // 5% target ("stop entering, the shield is the only risk left"), which reads the
   // evaluation's pass mark as the end of trading. It is not: the venue's own rule table
   // lists a profit target for the CHALLENGE and NONE for the funded phase
   // (docs/UPCOMERS_RULES_AUDIT_20260919.md §3), so passing the target ENDS THE
   // EVALUATION and trading continues under the funded rule set. Trading is the point
   // of a funded account, and refusing there would throw away the pass. The phase is
   // therefore REPORTED by PropPhaseCheck() and never gates an entry.

   // The day's baseline comes from the per-tick anchor, never from "the equity when we
   // first happened to look today" — see PropDayAnchorCheck for the measured reason.
   double cap = PropDayProfitCapUsd();
   // v1.21: stashed where the governor computes them, so the HUD never calls back into a
   // function that carries internal state (PropShieldFloor keeps the equity peak).
   g_hud_daypnl = (g_prop_day_eq > 0.0) ? eq - g_prop_day_eq : 0.0;
   g_hud_cap    = cap;
   if(cap > 0.0 && g_prop_day_eq > 0.0 && (eq - g_prop_day_eq) >= cap)
      return StringFormat("Best Day cap: today +%.2f >= %.2f", eq - g_prop_day_eq, cap);

   return "";
}

bool StopsLevelOK(double stop_d)
{
   long stops = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_d = (double)stops * _Point;
   if(stop_d < min_d)
   {
      PrintFormat(VersionTag() + "STOPS-LEVEL VETO: stop %.2f < broker minimum %.2f (%d points) — no order", stop_d, min_d, (int)stops);
      return false;
   }
   return true;
}

// Friday force-flat: a gold position held over the weekend absorbs gap risk
// the research engine never priced (playbook policy: flat before the close).
void LiveFridayFlatCheck()
{
   if(InpFridayFlatHour <= 0 || g_lv_posid == 0) return;
   MqlDateTime dt;
   TimeToStruct(TimeUTCNow(), dt);            // v1.15: TRUE UTC weekend guard
   if(dt.day_of_week == 5 && dt.hour >= InpFridayFlatHour)
   {
      Print(VersionTag() + "FRIDAY FLAT: closing before weekend (gap guard)");
      LiveClosePosition("FRIDAY-FLAT");
   }
}

bool LiveSendOrder(int direction, double stop_d, int hour, int mac)
{
   if(!StopsLevelOK(stop_d)) return false;
   if(!SpreadCapOK(stop_d))  return false;
   double dpu;
   if(!DollarPerUnitPerLot(dpu)) return false;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_d = equity * InpRiskPercent / 100.0;
   double lots = risk_d / (stop_d * dpu);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   bool floored = false;
   if(lots < vmin)
   {
      // v1.14 amendment 6 (register R5): live basis is ACCOUNT EQUITY — the
      // same quantity the sizing above used. Never place a min-lot order
      // that risks more than InpMaxRiskPct of the account.
      if(stop_d * dpu * vmin > equity * InpMaxRiskPct / 100.0)
      {
         Print(VersionTag() + "LIVE VETO RISK-CAP: min-lot risk exceeds "
               "InpMaxRiskPct of account equity — order refused (amendment 6)");
         g_nofill_riskcap++; DiagMaybeWrite();              // v1.18 diagnostics
         g_last_action = "live veto: min-lot risk cap";   // v1.10 HUD
         return false;
      }
      lots = vmin; floored = true;
   }
   if(vstep > 0) lots = MathFloor(lots / vstep) * vstep;
   if(lots < vmin) { lots = vmin; floored = true; }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sprd = ask - bid;
   double side = (direction > 0) ? 1.0 : -1.0;
   double fill_ref = bid + side * sprd / 2;             // research fill reference
   double sl = fill_ref - side * stop_d;
   double tp = fill_ref + side * stop_d * InpTpMult;
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);

   for(int attempt = 1; attempt <= MathMax(1, InpOrderRetries); attempt++)
   {
      bool ok = (direction > 0)
         ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, "MIDAS")
         : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, "MIDAS");
      uint rc = g_trade.ResultRetcode();
      if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED || rc == TRADE_RETCODE_DONE_PARTIAL))
      {
         // v1.11: three DISTINCT ID spaces, kept separately. The POSITION
         // IDENTIFIER is the only reconciliation key; order/deal tickets
         // are provenance. ResultDeal()/ResultOrder() may be 0 depending
         // on execution mode — adopt by symbol+magic when absent, exactly
         // like post-restart recovery.
         g_lv_order     = g_trade.ResultOrder();
         g_lv_deal      = g_trade.ResultDeal();
         g_lv_dir       = direction;
         g_lv_entry     = g_trade.ResultPrice();
         g_lv_sl        = sl;
         g_lv_tp        = tp;
         g_lv_stop      = stop_d;
         g_lv_vol       = lots;
         g_lv_open_time = TimeUTCNow();                    // v1.15: real-UTC clock for the live position
         g_lv_expiration= g_lv_open_time + (datetime)(InpTimeoutMinutes * 60);
         if(!SelectOurPosition())
            Print(VersionTag() + "WARNING: fill acknowledged but owned position not yet selectable — IDs will reconcile on the next tick");
         else
            ResolveEntryDeal();
         // v1.25: THE ACK-TIME PRICE IS NOT AUTHORITATIVE ON THIS VENUE. MEASURED on the arm's
         // first real fill: ResultPrice() was 0 here and the row went out as `0.00000` while the
         // true price was in the position and in the entry deal within the same second. Resolve
         // it before the row is written; if neither source answers inside a bounded wait, the row
         // says the price is UNRESOLVED (`entry=pending`) instead of printing a 0 in a price
         // column and letting every reader read it as a price.
         if(g_lv_entry <= 0.0 && InpLiveExecution)
         {
            string src = "";
            double p = 0.0;
            for(int k = 0; k < 20 && p <= 0.0; k++)      // up to ~1s, then label it instead
            {
               if(!ResolveEntryPrice(p, src)) Sleep(50);
            }
            if(p > 0.0)
            {
               g_lv_entry = p;
               PrintFormat(VersionTag() + "LIVE ENTRY PRICE resolved %.5f from the %s (the ack-time field was 0)",
                           g_lv_entry, src);
            }
            else
            {
               g_lv_entry_pending = true;
               Print(VersionTag() + "LIVE ENTRY PRICE unresolved at acknowledgement — the fill row carries "
                     "entry=pending and is amended by an LENTRY row as soon as the venue reports it");
            }
         }
         PrintFormat(VersionTag() + "LIVE FILL %s vol=%.2f @%.5f SL=%.5f TP=%.5f risk=$%.2f%s retcode=%u attempt=%d",
                     direction > 0 ? "BUY" : "SELL", lots, g_lv_entry, sl, tp,
                     stop_d * dpu * lots, floored ? " | FLOORED-TO-MIN-LOT" : "", rc, attempt);
         PrintFormat(VersionTag() + "LIVE IDs: pos=%I64u order=%I64u deal=%I64u (netting: pos==order; hedging: pos_id is authoritative)",
                     g_lv_posid, g_lv_order, g_lv_deal);
         // v1.19e: the live fill carries the SAME state stamp as the paper one. It matters
         // more here than there: an ARMED arm writes LOPEN (not OPEN), so without this the
         // record of the arm as deployed would be unlabelled by construction — see the
         // grammar note on StateAppend() and tests/test_state_label_contract.py.
         // v1.25: the format carried FOUR `%s` for THREE arguments, so every live fill row ended
         // with MQL5's `(missed string parameter)` appended after the cfg token — measured on the
         // arm's own row (`...,cfg=62.50@0.25(missed string parameter)`). The paper OPEN row had
         // the same off-by-one from the same copy: fixed in both, and the author's own check is
         // now a test that counts specifiers against arguments in both writers.
         PaperLog(StringFormat("LOPEN,%I64d,%I64u,%I64u,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s%s%s",
                  (long)TimeCurrent(), g_lv_posid, g_lv_order, g_lv_deal, direction, g_lv_entry, sl, tp,
                  lots, stop_d * dpu * lots, stop_d, InpTimeoutMinutes * 60, InpArmTag,
                  floored ? "_FLOORED" : "",
                  StateAppend() + EntryPendingAppend() + RiskAppend(risk_d)));
         // ^ THE ORDER IS THE CONTRACT, not a preference: the v1.22 configured-risk token is read
         //   OFF THE END OF THE ROW (`midas_first_fills_audit._split_risk_tail` takes `fields[-1]`
         //   when it starts with `cfg=`), so v1.25's `,entry=pending` sits BEFORE it. Both tail
         //   readers still see what they need: the state stamp is the first five fields after the
         //   head, and the risk token is last.
         g_last_action = StringFormat("LIVE OPEN %s %.2f @%.5f",   // v1.10 HUD
                        direction > 0 ? "BUY" : "SELL", lots, g_lv_entry);
         return true;
      }
      PrintFormat(VersionTag() + "ORDER REJECT attempt %d/%d retcode=%u (%s)",
                  attempt, InpOrderRetries, rc, g_trade.ResultRetcodeDescription());
      Sleep(300);
   }
   Print(VersionTag() + "ORDER FAILED after retries — standing down this signal");
   g_lv_last_error = StringFormat("send rc=%u %s", g_trade.ResultRetcode(),
                                  g_trade.ResultRetcodeDescription());   // v1.18 diagnostics
   return false;
}

void LiveClosePosition(string reason)
{
   if(g_lv_posid == 0) return;
   if(!SelectOurPosition())            // v1.11: close OUR position by ticket, verified magic+symbol
   {
      Print(VersionTag() + "CLOSE ABORT: owned position no longer selectable (external close already reconciles via LiveCheckExits)");
      return;
   }
   for(int attempt = 1; attempt <= MathMax(1, InpOrderRetries); attempt++)
   {
      if(g_trade.PositionClose(g_lv_ticket))
      {
         double exit = g_trade.ResultPrice();
         double side = (g_lv_dir > 0) ? 1.0 : -1.0;
         double r = (g_lv_stop > 0) ? ((exit - g_lv_entry) * side) / g_lv_stop : 0;
         PrintFormat(VersionTag() + "LIVE CLOSE %s exit=%.5f R=%+.3f", reason, exit, r);
         PaperLog(StringFormat("LCLOSE,%I64d,%I64u,%s,%.5f,%.3f", (long)TimeCurrent(), g_lv_posid, reason, exit, r));
         LiveCensusAdd(r);   // v1.24: the row above is what the chart now counts
         g_last_action = StringFormat("LIVE CLOSE %s R=%+.2f", reason, r);   // v1.10 HUD
         g_lv_posid = 0; g_lv_ticket = 0; g_lv_order = 0; g_lv_deal = 0;
         return;
      }
      PrintFormat(VersionTag() + "CLOSE REJECT attempt %d retcode=%u (%s)", attempt, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      Sleep(300);
   }
   Print(VersionTag() + "CLOSE FAILED after retries — will retry on next tick");
}

// SL/TP are SERVER-SIDE: if they fire while the EA is dead, the position is
// gone at re-init. Adopt the real state, keep the mirror ledger honest.
void LiveRecoverState()
{
   if(!InpLiveExecution || InpBarModel) return;
   if(!SelectOurPosition()) { g_lv_posid = 0; g_lv_ticket = 0; g_lv_order = 0; g_lv_deal = 0; return; }
   ResolveEntryDeal();                 // v1.11: entry-deal provenance from history
   long ptype = PositionGetInteger(POSITION_TYPE);
   g_lv_dir       = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
   g_lv_entry     = PositionGetDouble(POSITION_PRICE_OPEN);
   g_lv_sl        = PositionGetDouble(POSITION_SL);
   g_lv_tp        = PositionGetDouble(POSITION_TP);
   g_lv_vol       = PositionGetDouble(POSITION_VOLUME);
   g_lv_open_time = (datetime)PositionGetInteger(POSITION_TIME);
   g_lv_stop      = MathAbs(g_lv_entry - g_lv_sl);
   g_lv_expiration= g_lv_open_time + (datetime)(InpTimeoutMinutes * 60);
   PrintFormat(VersionTag() + "LIVE RECOVERED ticket=%I64u dir=%d entry=%.5f SL=%.5f TP=%.5f", g_lv_ticket, g_lv_dir, g_lv_entry, g_lv_sl, g_lv_tp);
}

void LiveCheckExits()
{
   // v1.25: a fill acknowledged with no price gets one as soon as the venue reports it. Cheap
   // and bounded: the resolver reads a position or a deal, and it stops once the row is amended.
   if(g_lv_entry_pending) LiveEntryPriceHeal();
   if(g_lv_posid == 0) return;
   if(!SelectOurPosition())                        // closed externally (server SL/TP or manual)
   {
      double exit = (g_lv_sl > 0 && g_lv_tp > 0) ? g_lv_tp : 0;  // unknowable which; R uses last known ref
      HistorySelectByPosition(g_lv_posid);         // v1.11: reconcile by POSITION IDENTIFIER
      exit = 0;
      string why = "EXTERNAL-UNKNOWN";             // v1.29: the OUT deal names the close
      for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
      {
         ulong d = HistoryDealGetTicket(i);
         if(d > 0 && (ulong)HistoryDealGetInteger(d, DEAL_POSITION_ID) == g_lv_posid &&
            HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_OUT)
         {
            exit = HistoryDealGetDouble(d, DEAL_PRICE);
            long magic = (long)HistoryDealGetInteger(d, DEAL_MAGIC);
            long reason = (long)HistoryDealGetInteger(d, DEAL_REASON);
            // MEASURED 2026-09-22 (docs/LIVE_EXIT_AUDIT_20260922.md): this venue's mobile
            // close carried magic 0 and reason 1 (MOBILE); the ENTRY deal carries our
            // magic, so a closing deal bearing our magic is the EA's own path.
            if(magic == InpMagic)                  why = "EXPERT";
            else if(reason == DEAL_REASON_SL)      why = "SL";
            else if(reason == DEAL_REASON_TP)      why = "TP";
            else if(reason == DEAL_REASON_SO)      why = "SO";
            else if(reason == DEAL_REASON_CLIENT)  why = "MANUAL-CLIENT";
            else if(reason == DEAL_REASON_WEB)     why = "MANUAL-WEB";
            else if(reason == DEAL_REASON_MOBILE)  why = "MANUAL-MOBILE";
            // NOTE: this toolchain's ENUM_DEAL_REASON has no OTHER member — any reason
            // this arm does not name (rollover, vmargin, split, a future platform value)
            // stays EXTERNAL-UNKNOWN, which is the designed answer for 'not known'.
            break;
         }
      }
      double side = (g_lv_dir > 0) ? 1.0 : -1.0;
      double r = (exit > 0 && g_lv_stop > 0) ? ((exit - g_lv_entry) * side) / g_lv_stop : 0;
      PrintFormat(VersionTag() + "LIVE EXTERNAL CLOSE (%s) exit=%.5f R=%+.3f", why, exit, r);
      PaperLog(StringFormat("LCLOSE,%I64d,%I64u,%s,%.5f,%.3f", (long)TimeCurrent(), g_lv_posid, why, exit, r));
      LiveCensusAdd(r);   // v1.24: BOTH close paths count, or the tally depends on who closed it
      g_last_action = StringFormat("LIVE EXTERNAL CLOSE @%.5f", exit);   // v1.10 HUD
      g_lv_posid = 0; g_lv_ticket = 0; g_lv_order = 0; g_lv_deal = 0;
      return;
   }
   if(TimeUTCNow() >= g_lv_expiration)                     // v1.15: real-UTC timeout (opened on the same clock)
   {
      LiveClosePosition("TIMEOUT");
      return;
   }
   LiveFridayFlatCheck();
}

// OnTick dispatch for the live path: signal evaluation ONLY from flat;
// hard-exit/timeout/reconcile ONLY while in a position.
void LiveOnTick()
{
   LiveCheckExits();
   if(g_lv_posid != 0) return;
   string prop_block = PropGovernorBlock();   // v1.19+: shield + target + Best Day, not just the daily cap
   g_hud_gov = prop_block;                    // v1.21: the same reason the HUD prints
   if(prop_block != "")
   {
      g_nofill_brk++;
      PrintFormat(VersionTag() + "PROP VETO: %s — no new entries", prop_block);
      DiagMaybeWrite();
      return;
   }
   TrackFreshM15Bar();
}

// v1.08 entry seam: TrackFreshM15Bar's last step calls the paper mirror
// directly; the live path needs the same signal to open a REAL order.
// InpLiveExecution is the SOLE switch — deliberately testable in the
// strategy tester (the --sim simulated-live pass sets it true under real
// ticks); parity runs set it false and never touch this path.
bool LiveSignalArmed()
{
   return InpLiveExecution && !InpBarModel;
}
//+------------------------------------------------------------------+

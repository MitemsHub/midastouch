//+------------------------------------------------------------------+
//| MidastouchAI.mq5 — MIDASTOUCH gold engine (paper-default)        |
//|                                                                  |
//| Target market: GOLD only (XAUUSD / XAUUSDmicro on Deriv MT5).    |
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
#property version   "1.18"   // v1.18: NOFILL diagnostics (reason-logged vetoes + daily NOFILL ledger rows) — never-abort class, certified paths unchanged
// Tester agents wipe their Files sandbox at pass start: this property makes
// the tester copy the recorded-spread series from <data>\MQL5\Files into the
// agent for every BAR-mode pass (name must be the literal staged file).
#property tester_file "MIDASTOUCH_spread_M15.csv"
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
input bool                 InpUseNewsFilter    = false; // R6: INIT_FAILED when true — no calendar engine exists (never set true)

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
string         g_last_action = "boot";   // v1.10 HUD: last engine action (display only)
string         g_lv_last_error = "";     // v1.18: last live-order failure detail (diagnostics)
// v1.18 NOFILL diagnostics (register review item 1): per-M15-bar veto
// accounting, so "why didn't it trade" is answered from evidence, not
// memory. Rows are appended to paper-file ledgers only — the BAR parity
// replay never writes them, so certified ledgers stay byte-identical.
int            g_nofill_signal = 0, g_nofill_mism = 0, g_nofill_session = 0,
               g_nofill_friday = 0, g_nofill_spread = 0, g_nofill_riskcap = 0,
               g_nofill_brk = 0, g_nofill_notr = 0, g_nofill_wrote = 0;
datetime       g_diag_day0 = 0;

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
datetime g_lv_open_time = 0;
datetime g_lv_expiration = 0;    // research timeout mirrored on the real position
int    g_brk_day = -1;               // daily-loss-breaker day key (UTC yyyymmdd)
double g_brk_start_eq = 0.0;
// v1.17 (V2 register P5, telemetry-first, never-abort class): running count
// of in-session bars whose mode condition was TRUE (ModeDecide passed and
// the session gates allowed evaluation). Monotone since EA init; the CLOSE
// rows carry it as `density` so consumers difference consecutive rows for
// interval signal density. Reset only by re-init (each ERA stamp notes it).
long g_p5_signals = 0;
bool   g_brk_tripped = false;

// Dollar-per-unit convenience wrapper (0.0 on bad spec).
double DollarPerUnit()
{
   double dpu = 0.0;
   return DollarPerUnitPerLot(dpu) ? dpu : 0.0;
}

#define APP_VERSION  "MIDAS1.18"   // v1.18: NOFILL diagnostics (reason-logged vetoes) — no certified-path behavior change
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
void HudUpdate()
{
   if(MQLInfoInteger(MQL_TESTER)) return;   // parity: draw nothing in the tester
   string pos = g_pp_open ? (g_pp_dir > 0 ? "LONG" : "SHORT")
              : (g_lv_posid != 0 ? (g_lv_dir > 0 ? "LONG(live)" : "SHORT(live)") : "flat");
   Comment(StringFormat(
      "MIDASTOUCH %s | mode=%d %s | session %02d-%02d UTC\n"
      "vEq: $%.2f (start $%.2f) | pos: %s\n"
      "trades: %d/30 (gate reads at n=60) | wins %d | cumR %+.2f\n"
      "eval: %d no-trade bars | V: mis %d no-trg %d sess %d spr %d\n"
      "last: %s",
      APP_VERSION, (int)InpMode, ModeName((int)InpMode),
      InpSessionStartHour, InpSessionEndHour,
      PaperEquity(), g_paper_start, pos,
      g_trades, g_wins, g_cum_r,
      g_nofill_signal, g_nofill_mism, g_nofill_notr, g_nofill_session,
      g_nofill_spread, g_last_action));
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
   int k = iBarShift(_Symbol, PERIOD_M15, t, true);
   if(k < 0) return false;
   o = iOpen(_Symbol, PERIOD_M15, k);
   h = iHigh(_Symbol, PERIOD_M15, k);
   l = iLow(_Symbol, PERIOD_M15, k);
   c = iClose(_Symbol, PERIOD_M15, k);
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
//| Dollar value of one 1.0 price-unit move per 1.0 lot, with the    |
//| geometric identity check from the playbook (contract x tick).    |
//+------------------------------------------------------------------+
bool DollarPerUnitPerLot(double &out)
{
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double cs = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(ts <= 0 || tv <= 0) return false;
   out = tv / ts;
   double geo = cs * ts;                    // $ per tick per lot, geometric
   if(geo > 0 && MathAbs(tv - geo) / geo > 0.05)
      PrintFormat(VersionTag() + "TICK VALUE WARNING broker=%.5f geometric=%.5f (ratio %.2f) — using broker value",
                  tv, geo, tv / geo);
   return true;
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
   PrintFormat(VersionTag() + "FLOOR TABLE %s: stop=%.2f ($%.2f) minlot=%.2f risk@minlot=$%.2f equity@1%%=$%.0f",
               _Symbol, stop, stop, vmin, risk_min, risk_min / MathMax(InpRiskPercent / 100.0, 0.0001));
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
   if(CopyBuffer(g_m15_bb, 1, 1, 1, up) != 1) return 0;   // UPPER_BAND
   if(CopyBuffer(g_m15_bb, 2, 1, 1, lo) != 1) return 0;   // LOWER_BAND
   double c0[], c1[];
   if(CopyClose(_Symbol, PERIOD_M15, 1, 2, c1) != 2) return 0;  // [0]=older [1]=closed
   if(CopyClose(_Symbol, PERIOD_M15, 2, 1, c0) != 1) return 0;
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
   g_m15_bb  = iBands(_Symbol, PERIOD_M15, InpBBPeriod, 0, InpBBDev, PRICE_CLOSE);
   g_m15_rsi = iRSI(_Symbol, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE);
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

   // v1.16 (V2 register R6, fail-closed preconditions — the build-time
   // decision the register queued): the news-filter input names protection
   // that does not exist, and MIDASTOUCH is gold-only by charter. Both are
   // INIT_FAILED preconditions BEFORE the banner prints (a refused attach
   // must not announce itself as a healthy start), instead of honest labels
   // on absent protection / an out-of-charter symbol. The tester harness
   // and every preset pass InpUseNewsFilter=false on a gold symbol, so
   // behavior on every certified path is unchanged.
   if(InpUseNewsFilter)
   {
      Print(VersionTag() + "INIT FAILED: InpUseNewsFilter=true names a calendar "
            "engine that does not exist (V2 register R6). No news protection "
            "can be provided; refusing to run under a false label.");
      return INIT_FAILED;
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
   PrintFormat(VersionTag() + "CLOCK: server=%s | GMT=%s | offset=%+d h %02d min — session gates classify BAR EPOCHS (parity); "
               "live-path wall-clock gates use TimeGMT; VERIFY this offset before the live gate (health guide §4)",
               TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
               TimeToString(TimeGMT(), TIME_DATE|TIME_MINUTES),
               OffsetHours(), OffsetRemMin());

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
   // v1.18: the NOFILL diagnostics ledger is review-item-1 telemetry. NOFILL
   // rows are appends AFTER trade rows, never alter any CLOSE row, and exist
   // only in live/paper-file ledgers — this tag keeps the version transition
   // in midas_verdict's never-abort class (§1 citation walk).
   if(!InpBarModel)
      era_note += "+diag-nofill";
   PaperLog(StringFormat("ERA,%s,%I64d,%s", APP_VERSION, (long)TimeCurrent(), era_note));
   RestoreOrVerifyLedger();
   if(!MQLInfoInteger(MQL_TESTER))
      PaperLog(StringFormat("EQ,%.2f", PaperEquity()));   // v1.07: init epoch touch (watchdog sees a fresh mtime immediately)
   EventSetTimer(900);                                 // v1.07: heartbeat — the ledger must provably stay live
   PrintFloorTable();
   DumpH1Debug();                      // v1.02: tester-vs-CSV series comparison
   LiveRecoverState();                 // v1.08: adopt real positions after restart (live only)
   HudUpdate();                        // v1.10: HUD up from the first second (live only)
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();                                   // v1.07: release the heartbeat
   if(InpBarModel)
      ReplayTailFlush();
   PaperLog(StringFormat("EQ,%.2f", PaperEquity()));
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
   PaperLog(StringFormat("EQ,%.2f", PaperEquity()));
   DiagMaybeWrite();                    // v1.18: NOFILL diagnostics flush on the heartbeat
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
void OnTick()
{
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
         PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s,%.5f,%.5f",
                  (long)t, g_pp_ticket, g_pp_dir, fill, g_pp_sl, g_pp_tp,
                  lots, eff_risk, stop_d, InpTimeoutMinutes * 60, InpArmTag,
                  stop_d / InpSlAtrMult, sp_open));   // v1.13 R10: atr_at_entry,spread_at_open (end-of-row append)
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

int OffsetMinutes()                      // broker-vs-UTC offset (minutes; may exceed ±60 on odd servers)
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
   g_nofill_brk = 0; g_nofill_notr = 0; g_nofill_wrote = 0;
}
string TextVeto(int trigger, int mac)
{
   if(trigger == 0 && mac == 0)  return "NO-SIGNAL(0,0)";
   if(trigger == 0)              return StringFormat("NO-TRIGGER(mac=%+d)", mac);
   if(mac == 0)                  return StringFormat("MACRO-DIVERGENCE(trg=%+d)", trigger);
   return StringFormat("MISMATCH(mac=%+d,trg=%+d)", mac, trigger);
}
void DiagMaybeWrite()
{
   if(MQLInfoInteger(MQL_TESTER)) return;                 // parity ledgers byte-clean
   if(InpBarModel) return;
   if(g_nofill_signal == 0) return;                       // nothing to account
   if(g_diag_day0 == 0) g_diag_day0 = TimeUTCNow();
   if(TimeUTCNow() - g_diag_day0 < 86400) return;         // once per UTC day
   PaperLog(StringFormat("NOFILL,%I64d,%d,%d,%d,%d,%d,%d,%d,%d",
            (long)TimeUTCNow(), g_nofill_signal, g_nofill_mism,
            g_nofill_session, g_nofill_friday, g_nofill_spread,
            g_nofill_riskcap, g_nofill_brk, g_nofill_notr));
   g_nofill_wrote++;
   DiagCountReset();
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
void TrackFreshM15Bar()
{
   datetime cur = iTime(_Symbol, PERIOD_M15, 0);
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
   datetime sig_open_time = iTime(_Symbol, PERIOD_M15, 1);
   int mac = MacroState();
   int trigger = TriggerOnClosedBar();
   int direction = 0;
   if(!ModeDecide(trigger, mac, direction) || direction == 0)
   {
      g_nofill_signal++;                                // v1.18: mode evaluated, no trade
      if(trigger == 0) g_nofill_notr++;                 //   no trigger fired at all
      else             g_nofill_mism++;                 //   trigger fired but mode refused
      g_last_action = StringFormat("VETO %s", TextVeto(trigger, mac));   // v1.18: honest HUD
      return;
   }
   g_last_action = StringFormat("SIGNAL %s evaluated",   // v1.10 HUD (PERTICK path only)
                  direction > 0 ? "BUY" : "SELL");

   // session gates on the SIGNAL BAR's open hour — BAR EPOCH = SERVER frame
   // (v1.15: iTime values are broker-server; matches the python engine of
   // record's classification of the same broker-feed epochs)
   MqlDateTime dt;
   TimeToStruct(sig_open_time, dt);
   if(dt.hour < InpSessionStartHour || dt.hour >= InpSessionEndHour)
   { g_nofill_session++; DiagMaybeWrite(); return; }  // v1.18 diagnostics

   // Friday cutoff
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour)
   { g_nofill_friday++; DiagMaybeWrite(); return; }   // v1.18 diagnostics
   g_p5_signals++;                     // v1.17 P5 telemetry: condition-true, in-session (census semantics)

   double atr = AtrNow();
   if(atr <= 0) return;
   double stop = InpSlAtrMult * atr;
   if(stop <= 0) return;
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
   PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s%s,%.5f,%.5f",
            (long)TimeCurrent(), ticket, direction, fill, sl, tp, lots, eff_risk,
            g_pp_orig_risk, InpTimeoutMinutes * 60, InpArmTag,
            floored ? "_FLOORED" : "",
            atr_used, sprd));   // v1.13 R10: atr_at_entry,spread_at_open (end-of-row append)
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

bool DailyBreakerTripped()
{
   if(InpDailyLossCapPct <= 0) return false;
   MqlDateTime dt;
   TimeToStruct(TimeUTCNow(), dt);            // v1.15: TRUE UTC day key (the breaker is an operator guarantee)
   int day = dt.year * 10000 + dt.mon * 100 + dt.day;
   if(day != g_brk_day)                       // new UTC day: re-arm
   {
      g_brk_day = day;
      g_brk_start_eq = AccountInfoDouble(ACCOUNT_EQUITY);
      g_brk_tripped = false;
   }
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
         PrintFormat(VersionTag() + "LIVE FILL %s vol=%.2f @%.5f SL=%.5f TP=%.5f risk=$%.2f%s retcode=%u attempt=%d",
                     direction > 0 ? "BUY" : "SELL", lots, g_lv_entry, sl, tp,
                     stop_d * dpu * lots, floored ? " | FLOORED-TO-MIN-LOT" : "", rc, attempt);
         PrintFormat(VersionTag() + "LIVE IDs: pos=%I64u order=%I64u deal=%I64u (netting: pos==order; hedging: pos_id is authoritative)",
                     g_lv_posid, g_lv_order, g_lv_deal);
         PaperLog(StringFormat("LOPEN,%I64d,%I64u,%I64u,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s%s",
                  (long)TimeCurrent(), g_lv_posid, g_lv_order, g_lv_deal, direction, g_lv_entry, sl, tp,
                  lots, stop_d * dpu * lots, stop_d, InpTimeoutMinutes * 60, InpArmTag,
                  floored ? "_FLOORED" : ""));
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
   if(g_lv_posid == 0) return;
   if(!SelectOurPosition())                        // closed externally (server SL/TP or manual)
   {
      double exit = (g_lv_sl > 0 && g_lv_tp > 0) ? g_lv_tp : 0;  // unknowable which; R uses last known ref
      HistorySelectByPosition(g_lv_posid);         // v1.11: reconcile by POSITION IDENTIFIER
      exit = 0;
      for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
      {
         ulong d = HistoryDealGetTicket(i);
         if(d > 0 && (ulong)HistoryDealGetInteger(d, DEAL_POSITION_ID) == g_lv_posid &&
            HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_OUT)
         { exit = HistoryDealGetDouble(d, DEAL_PRICE); break; }
      }
      double side = (g_lv_dir > 0) ? 1.0 : -1.0;
      double r = (exit > 0 && g_lv_stop > 0) ? ((exit - g_lv_entry) * side) / g_lv_stop : 0;
      PrintFormat(VersionTag() + "LIVE EXTERNAL CLOSE exit=%.5f R=%+.3f", exit, r);
      PaperLog(StringFormat("LCLOSE,%I64d,%I64u,EXTERNAL,%.5f,%.3f", (long)TimeCurrent(), g_lv_posid, exit, r));
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
   if(DailyBreakerTripped()) { g_nofill_brk++; DiagMaybeWrite(); return; }   // v1.18 diagnostics
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

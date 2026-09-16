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
//| Paper path fills at the NEXT M15 OPEN +/- half spread — exactly |
//| the research engine's model — so tester-vs-python parity is a    |
//| testable claim, not a hope. Ledger rows are byte-compatible with |
//| the MitemshubAI contract (OPEN 12 / CLOSE 8 / EQ / ERA) so the   |
//| flatness checker and morning tooling parse gold ledgers as-is.   |
//|                                                                  |
//| PAPER IS THE DEFAULT. InpLiveExecution=false never sends an      |
//| order. There is no live path in v1; it is added only after a     |
//| passing forward gate, in its own reviewed build.                 |
//+------------------------------------------------------------------+
#property copyright "MIDASTOUCH"
#property version   "1.00"
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
input int                 InpFridayCutoffHour = 20;    // UTC; no new entries after
input bool                InpUseNewsFilter    = false; // HONEST: calendar integration pending
input int                 InpStaleMinutes     = 30;    // no M15 bar for N min -> stand down
input group "=== Risk ==="
input double              InpRiskPercent      = 1.0;
input group "=== Paper ==="
input bool                InpLiveExecution    = false; // MUST stay false in v1
input double              InpPaperEquity      = 1000.0;

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

#define APP_VERSION  "MIDAS1.03"
#define LEDGER_BASE  "MIDASTOUCH_paper"

//+------------------------------------------------------------------+
string VersionTag() { return "[" + APP_VERSION + "]"; }

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

   string symU = _Symbol;
   StringToUpper(symU);
   bool is_gold = (StringFind(symU, "XAU") >= 0 || StringFind(symU, "GOLD") >= 0);
   PrintFormat(VersionTag() + "MIDASTOUCH started | mode=%d | symbol=%s (%s) | "
               "macro=H4+H1 EMA%d | trigger=M15 BB(%d,%.1f)/RSI(%d) | SL=%.1fxATR(H1) TP=%.1fR "
               "timeout=%dmin | session=%02d-%02d UTC | spreadcap=%.1f%%stop | risk=%.2f%% | "
               "execution=%s | NEWS-FILTER=%s (calendar pending)",
               (int)InpMode, _Symbol, is_gold ? "GOLD-OK" : "NOT-GOLD WARN",
               InpMacroEmaPeriod, InpBBPeriod, InpBBDev, InpRSIPeriod,
               InpSlAtrMult, InpTpMult, InpTimeoutMinutes,
               InpSessionStartHour, InpSessionEndHour, InpSpreadCapPctStop,
               InpRiskPercent, InpLiveExecution ? "LIVE-DISABLED-IN-V1" : "PAPER",
               InpUseNewsFilter ? "ON" : "OFF");
   if(!is_gold)
      Print(VersionTag() + "WARNING: chart symbol is not a gold symbol — MIDASTOUCH is gold-only by charter");

   // ledger era stamp (idempotent provenance, mirrors the house contract)
   PaperLog(StringFormat("ERA,%s,%I64d,pertick-fills", APP_VERSION, (long)TimeCurrent()));
   RestoreOrVerifyLedger();
   PrintFloorTable();
   DumpH1Debug();                      // v1.02: tester-vs-CSV series comparison
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   PaperLog(StringFormat("EQ,%.2f", PaperEquity()));
   IndicatorRelease(g_h1_ema); IndicatorRelease(g_h4_ema);
   IndicatorRelease(g_h1_atr); IndicatorRelease(g_m15_bb);
   IndicatorRelease(g_m15_rsi);
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
   if(!g_pp_open) TrackFreshM15Bar();
   if(g_pp_open)  PaperCheckHardExits();
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

   // staleness guard: if the feed went quiet and just woke up, skip this
   // bar (its "first tick" is not the open; parity and honesty both demand
   // we stand down rather than fill at a stale price)
   if(TimeCurrent() - g_last_m15_seen > InpStaleMinutes * 60)
   {
      g_last_m15_seen = TimeCurrent();
      Print(VersionTag() + "STALE feed — bar skipped, no evaluation");
      return;
   }
   g_last_m15_seen = TimeCurrent();

   // evaluate the just-closed bar (index 1)
   datetime sig_open_time = iTime(_Symbol, PERIOD_M15, 1);
   int mac = MacroState();
   int trigger = TriggerOnClosedBar();
   int direction = 0;
   if(!ModeDecide(trigger, mac, direction) || direction == 0) return;

   // session gates on the SIGNAL BAR's open hour (research classification)
   MqlDateTime dt;
   TimeToStruct(sig_open_time, dt);
   if(dt.hour < InpSessionStartHour || dt.hour >= InpSessionEndHour) return;
   // Friday cutoff
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour) return;

   double atr = AtrNow();
   if(atr <= 0) return;
   double stop = InpSlAtrMult * atr;
   double sprd = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(stop <= 0 || sprd <= 0) return;
   if(sprd > stop * InpSpreadCapPctStop / 100.0)
   {
      PrintFormat(VersionTag() + "SPREAD VETO %.5f > %.1f%% of stop %.2f", sprd, InpSpreadCapPctStop, stop);
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
   double fill = (direction > 0) ? ask + sprd / 2 : bid - sprd / 2;  // parity: half-spread entry
   double sl = fill - side * stop_d;
   double tp = fill + side * stop_d * InpTpMult;

   double risk_d = PaperEquity() * InpRiskPercent / 100.0;
   double lots = risk_d / (stop_d * dpu);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   bool floored = false;
   if(lots < vmin) { lots = vmin; floored = true; }
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
   // v1.02 parity instrumentation: the exact ATR + H1 bar stamp behind the stop
   datetime h1_stamp = iTime(_Symbol, PERIOD_H1, 1);
   double atr_used = AtrNow();
   PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s%s",
            (long)TimeCurrent(), ticket, direction, fill, sl, tp, lots, eff_risk,
            g_pp_orig_risk, InpTimeoutMinutes * 60, InpArmTag,
            floored ? "_FLOORED" : ""));
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
   PaperLog(StringFormat("CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f",
            (long)TimeCurrent(), g_pp_ticket, reason, exit, r, pnl, PaperEquity() + pnl));
   g_paper_eq += pnl;
   g_cum_r += r; g_trades++; if(pnl > 0) g_wins++;
   PrintTradeR(r);
   PrintFormat(VersionTag() + "CLOSE %s ticket=%I64u pnl=%+.2f R=%+.3f equity=$%.2f trades=%d",
               reason, g_pp_ticket, pnl, r, PaperEquity(), g_trades);
   PaperLog(StringFormat("EQ,%.2f", PaperEquity()));
   g_pp_open = false;
}
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//|                                        MitemshubAI_v28_fwd.mq5   |
//|            MITEMSHUB V75 MACRO ENGINE v28.10 — FORWARD BUILD     |
//|                                                                  |
//| The v28 strategy core (byte-faithful signal logic, all 8 modes,  |
//| R accounting, RESEARCH_RESULT surface) + the v26.40 paper-arm    |
//| module (virtual equity, per-tick hard SL/TP fills, tagged        |
//| ledger, fleet-mirror account guard) so the A2 forward arm can    |
//| trade the swept candidate on live ticks.                         |
//|                                                                  |
//| Parity contract (scripts/build_parity.py): with the SAME input   |
//| surface, this build and MitemshubAI_v28 must produce the SAME    |
//| trade set on a held window — identical (side, entry_time) in     |
//| order, per-trade R within 0.02. R is volume-invariant, so the    |
//| paper basis changes money but not R. The v28-differences are     |
//| strictly downstream of signal construction: sizing basis,        |
//| account-budget guard, paper fills, ledger.                       |
//|                                                                  |
//| Forward-only additions (never present in the research build):    |
//|   * per-trade "Trade R:" journal line at every close — the       |
//|     parity harness's per-trade R evidence (the research build    |
//|     cannot emit it; parity reads it from THIS build and the      |
//|     RESEARCH_RESULT/CLOSE lines from both).                      |
//|   * floor-mode sizing: when the broker minimum lot risks more    |
//|    than the strategy fraction, the trade takes the minimum lot   |
//|    if the ACCOUNT budget allows it (never silently blocked —     |
//|    the account must be tradeable at any balance), else the      |
//|    account-budget guard vetoes exactly as v26.40 prints it.     |
//|                                                                  |
//| PAPER ONLY by default. InpLiveExecution=true is the research     |
//| contract and stays available for tester parity runs; the A2      |
//| preset keeps it false.                                           |
//+------------------------------------------------------------------+
#define APP_VERSION "28.10"

#property copyright "MITEMSHUB AI"
#property version   APP_VERSION
#property strict

#include <Trade\Trade.mqh>

//--- baseline strategy geometry (identical to v28)
const int    MACRO_EMA_PERIOD       = 20;
const int    RSI_PERIOD              = 14;
const int    ATR_PERIOD              = 14;
const int    BOLLINGER_PERIOD       = 20;
const double BOLLINGER_DEVIATIONS   = 2.0;
const double TICK_VALUE_TOLERANCE    = 0.05;

const double RISK_FRACTION_LIMIT     = 0.10;
const double STOP_ATR_MIN             = 0.25;
const double STOP_ATR_LIMIT           = 6.0;
const double TARGET_ATR_MIN           = 0.25;
const double TARGET_ATR_LIMIT         = 12.0;
const int    HOLD_MINUTES_MIN         = 15;
const int    HOLD_MINUTES_LIMIT       = 720;
const double RISK_PLAUSIBILITY_BOUND  = 5.0;

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group "=== V75 Macro Execution ==="
input bool   InpLiveExecution       = false; // false = paper module (virtual fills); true = research contract (real orders)
input long   InpMagic               = 7788075;
input int    InpMaxDeviationPoints  = 50;
input bool   InpDrawHud             = true;

enum ENUM_V28_STRATEGY_MODE
{
   V28_ORIGINAL = 0,
   V28_REVERSE_DIRECTION = 1,
   V28_REVERSE_TRIGGER = 2,
   V28_REVERSE_BOTH = 3,
   V28_LONG_ONLY = 4,
   V28_SHORT_ONLY = 5,
   V28_MACRO_ONLY = 6,
   V28_TRIGGER_ONLY = 7
};

input group "=== V28 Research / Strategy Mutation ==="
input ENUM_V28_STRATEGY_MODE InpStrategyMode = V28_ORIGINAL;
input bool   InpResearchLogging      = true;
input string InpExperimentTag        = "V28_BASELINE";
input bool   InpAllowLong            = true;
input bool   InpAllowShort           = true;
input bool   InpLegacyV27ModifyClose = false;

input group "=== V28 Tunable Risk / Exit Geometry ==="
input double InpRiskFraction         = 0.01;
input double InpStopATRMultiplier    = 2.0;
input double InpTargetATRMultiplier  = 4.0;
input int    InpMaxHoldMinutes      = 180;

//+------------------------------------------------------------------+
//| v26.40 forward paper module — the A2 arm's infrastructure.        |
//| In live mode (InpLiveExecution=true) every one of these is inert. |
//+------------------------------------------------------------------+
input group "=== Forward Paper Module (A2) ==="
input string InpArmTag               = "";      // suffixes ALL Files output (ledger/tag separation); empty = legacy names
input double InpPaperEquity          = 1000.0;  // virtual starting equity in paper mode
input double InpPaperSpreadMult      = 1.0;     // conservative virtual fill: spread x this
input double InpMaxTotalRiskPct      = 15.0;    // ACCOUNT GUARD: max summed open risk (fleet) as % of virtual equity
input double InpFloorModeMaxDDPct    = 30.0;    // FLOOR MODE: hard entry halt when vEq is this % below window start
input bool   InpFloorModeConviction  = true;    // FLOOR MODE: min-lot entries require the strong BB+RSI trigger
input double InpFloorModeConvictionMinRiskPct = 2.5; // FLOOR MODE: conviction bar applies only when min-lot risk exceeds this % of vEq
input string InpFilterTable          = "MitemshubAI_filter_table";  // ML consult table (consult-only unless ACTIVATION=ACTIVE)
input string InpFleetMagicsCSV       = "";      // fleet magics whose open risk counts against the budget

//+------------------------------------------------------------------+
//| Runtime state (v28 core)                                          |
//+------------------------------------------------------------------+
CTrade trade;

int g_h4_ema = INVALID_HANDLE;
int g_h1_ema = INVALID_HANDLE;
int g_h1_atr = INVALID_HANDLE;
int g_m30_rsi = INVALID_HANDLE;
int g_m30_bands = INVALID_HANDLE;

datetime g_last_m30_bar = 0;
datetime g_last_gate_time = 0;
string   g_last_gate = "WAITING FOR M30 BAR";
string   g_last_macro = "UNKNOWN";
string   g_last_trigger = "NONE";

bool     g_has_active_trade = false;
bool     g_close_booked = false;
bool     g_timeout_requested = false;
int      g_missing_close_polls = 0;
ulong    g_position_ticket = 0;
ulong    g_position_id = 0;
int      g_position_direction = 0;
datetime g_entry_time = 0;
datetime g_expiration_time = 0;
datetime g_last_timeout_attempt = 0;
double   g_entry_price = 0.0;
double   g_active_atr = 0.0;
double   g_active_sl = 0.0;
double   g_active_tp = 0.0;
double   g_risk_money = 0.0;
ulong    g_risk_money_id = 0;
string   g_risk_money_src = "NONE";
string   g_entry_trigger = "";

datetime g_session_day = 0;
double   g_session_pnl = 0.0;
double   g_cumulative_r = 0.0;
double   g_test_pnl = 0.0;
double   g_test_r = 0.0;
long     g_test_trades = 0;
long     g_test_wins = 0;
long     g_test_losses = 0;
long     g_test_sl_exits = 0;
long     g_test_tp_exits = 0;
long     g_test_timeout_exits = 0;
double   g_sum_risk = 0.0;
double   g_sum_abs_pnl = 0.0;
double   g_risk_min = 0.0;
double   g_risk_max = 0.0;
const double MFE_GRID[6] = {0.25, 0.50, 0.75, 1.00, 1.50, 2.00};
double   g_peak_r = 0.0;
long     g_mfe_hits[6] = {0, 0, 0, 0, 0, 0};
double   g_mfe_sum = 0.0;
double   g_mfe_max = 0.0;
string   g_gv_prefix = "";

//+------------------------------------------------------------------+
//| Paper module state (v26.40 port)                                  |
//+------------------------------------------------------------------+
bool     g_paper_active = false;
double   g_paper_eq = 0.0;
double   g_paper_start = 0.0;
bool     g_pp_open = false;
int      g_pp_dir = 0;
double   g_pp_entry = 0.0;
double   g_pp_sl = 0.0;
double   g_pp_tp = 0.0;
double   g_pp_orig_risk = 0.0;
double   g_pp_vol = 0.0;
double   g_pp_eff_risk = 0.0;
datetime g_pp_entry_time = 0;
ulong    g_pp_ticket = 0;
string   g_pp_tag = "";
long     g_fleet_magics[];
int      g_fleet_count = 0;

//+------------------------------------------------------------------+
//| Small utilities                                                   |
//+------------------------------------------------------------------+
string VersionTag()
{
   return("[v" + APP_VERSION + "] ");
}

bool IsTesterRun()
{
   return(MQLInfoInteger(MQL_TESTER) != 0);
}

bool PaperActive()
{
   return(g_paper_active);
}

string ModeText(const int mode)
{
   switch(mode)
   {
      case V28_ORIGINAL:          return("V28_ORIGINAL");
      case V28_REVERSE_DIRECTION: return("V28_REVERSE_DIRECTION");
      case V28_REVERSE_TRIGGER:   return("V28_REVERSE_TRIGGER");
      case V28_REVERSE_BOTH:      return("V28_REVERSE_BOTH");
      case V28_LONG_ONLY:         return("V28_LONG_ONLY");
      case V28_SHORT_ONLY:        return("V28_SHORT_ONLY");
      case V28_MACRO_ONLY:        return("V28_MACRO_ONLY");
      case V28_TRIGGER_ONLY:      return("V28_TRIGGER_ONLY");
   }
   return("V28_UNKNOWN");
}

string SafeSymbolKey()
{
   string key = _Symbol;
   StringReplace(key, " ", "_");
   StringReplace(key, ".", "_");
   StringReplace(key, "#", "_");
   return(key);
}

// v26.40 tag convention, byte-compatible: base_SymbolTag_TAG.ext — the accrual
// registry's glob (MitemshubAI_paper_*_A2.csv) only ever matches tag A2 output.
string SymbolTaggedFile(const string base, const string ext)
{
   if(StringLen(InpArmTag) > 0)
      return StringFormat("%s_%s_%s%s", base, SafeSymbolKey(), InpArmTag, ext);
   return StringFormat("%s_%s%s", base, SafeSymbolKey(), ext);
}

string PaperFile() { return(SymbolTaggedFile("MitemshubAI_paper", ".csv")); }

//+------------------------------------------------------------------+
//| ML SIGNAL-FILTER CONSULT TABLE (bucket-side-tod-v0).              |
//| Frozen P(win) buckets from the v28 sweep dataset (protocol §10.7).|
//| CSV rows: ACTIVATION=PASSIVE|ACTIVE, version=..., then            |
//| side,tod,p_win,source — tod is UTC hour / 6 (0..3); '*' = global. |
//| CONSULT-ONLY CONTRACT: p=0.50 means "no opinion" and the table    |
//| NEVER vetoes unless the file's ACTIVATION is exactly ACTIVE —     |
//| which requires the frozen §10.7 gate (n>=500, coverage>=50%,      |
//| wf AUC>0.55 in >=5/6 folds, worst fold >= -0.05R) to pass on      |
//| fresh re-run data. PASSIVE mode still logs every read so the      |
//| forward evidence accrues from day one.                            |
//+------------------------------------------------------------------+
double  g_filter_global_p = 0.50;     // 0.50 = table absent or muted
string  g_filter_activation = "ABSENT";
int     g_filter_rows = 0;
string  g_filter_consult_side = "";   // set at the paper entry point with the trigger

struct FilterBucket { string side; int tod; double p; };
FilterBucket g_filter_buckets[];

string FilterTableFile()
{
   if(StringLen(InpArmTag) > 0)
      return StringFormat("%s_%s.csv", InpFilterTable, InpArmTag);
   return StringFormat("%s.csv", InpFilterTable);
}

bool LoadFilterTable()
{
   g_filter_global_p = 0.50;
   g_filter_activation = "ABSENT";
   g_filter_rows = 0;
   ArrayResize(g_filter_buckets, 0);
   string name = FilterTableFile();
   if(!FileIsExist(name))
   {
      PrintFormat(VersionTag() + "FILTER TABLE: %s absent — consult disabled (rule-based conviction bar stays authoritative)", name);
      return(false);
   }
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      PrintFormat(VersionTag() + "FILTER TABLE: %s unreadable — consult disabled", name);
      return(false);
   }
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0) continue;
      if(StringFind(line, "ACTIVATION=") == 0)
      {
         g_filter_activation = StringSubstr(line, 11);
         continue;
      }
      if(StringFind(line, "version=") == 0)
         continue;                       // meta line, parsed on demand
      if(StringFind(line, "#") == 0)
         continue;
      string parts[];
      if(StringSplit(line, ',', parts) < 4)
         continue;
      double p = StringToDouble(parts[2]);
      if(parts[0] == "*" && parts[1] == "*")
      {
         g_filter_global_p = p;
         g_filter_rows++;
         continue;
      }
      int n = ArraySize(g_filter_buckets);
      ArrayResize(g_filter_buckets, n + 1);
      g_filter_buckets[n].side = parts[0];
      g_filter_buckets[n].tod  = (int)StringToInteger(parts[1]);
      g_filter_buckets[n].p    = p;
      g_filter_rows++;
   }
   FileClose(h);
   PrintFormat(VersionTag() + "FILTER TABLE: %s loaded v=bucket-side-tod-v0 buckets=%d "
               "global=%.3f ACTIVATION=%s%s",
               name, ArraySize(g_filter_buckets), g_filter_global_p, g_filter_activation,
               g_filter_activation == "ACTIVE" ? "" : " (consult-only: never vetoes)");
   return(g_filter_rows > 0);
}

double FilterLookup(const string side, const datetime entry_time, bool &is_bucket)
{
   MqlDateTime dt;
   TimeToStruct(entry_time, dt);
   int tod = dt.hour / 6;
   is_bucket = false;
   for(int i = 0; i < ArraySize(g_filter_buckets); i++)
      if(g_filter_buckets[i].tod == tod && g_filter_buckets[i].side == side)
      {
         is_bucket = true;
         return(g_filter_buckets[i].p);
      }
   return(g_filter_global_p);
}

//+------------------------------------------------------------------+
//| The ML consult leg. Returns true when the signal may proceed.     |
//| CONTRACT: in PASSIVE mode (or p == 0.50 "no opinion") this NEVER  |
//| vetoes — it prints and logs, building the forward evidence base.  |
//| Only an ACTIVATION=ACTIVE file (gate-certified) may skip a trade. |
//+------------------------------------------------------------------+
bool FilterConsultAllows(const string side, const datetime entry_time)
{
   MqlDateTime dt;
   TimeToStruct(entry_time, dt);
   int tod = dt.hour / 6;
   bool is_bucket = false;
   double p = FilterLookup(side, entry_time, is_bucket);
   bool can_veto = (g_filter_activation == "ACTIVE") && (p != 0.50);
   string decision = can_veto ? (p >= 0.50 ? "TAKE" : "WOULD-VETO") : "OBSERVE";
   PrintFormat(VersionTag() + "FILTER CONSULT: side=%s tod=%d p=%.3f src=%s "
               "activation=%s -> %s",
               side, tod, p, is_bucket ? "BUCKET" : "GLOBAL",
               g_filter_activation, decision);
   PaperLog(StringFormat("FCONSULT,%s,%d,%.4f,%s,%s",
            side, tod, p, is_bucket ? "BUCKET" : "GLOBAL",
            can_veto ? (p >= 0.50 ? "TAKE" : "VETO") : "OBSERVE"));
   if(!can_veto)
      return(true);                      // PASSIVE: never a veto
   return(p >= 0.50);
}

datetime StartOfDay(const datetime when)
{
   MqlDateTime parts;
   TimeToStruct(when, parts);
   parts.hour = 0;
   parts.min = 0;
   parts.sec = 0;
   return(StructToTime(parts));
}

bool IsV75Symbol()
{
   string name = _Symbol;
   StringToLower(name);
   return(StringFind(name, "volatility 75") >= 0 || StringFind(name, "v75") >= 0);
}

int PriceDigits()
{
   return((int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
}

double NormalizePrice(const double price)
{
   return(NormalizeDouble(price, PriceDigits()));
}

int VolumeDigits()
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   int digits = 0;
   while(digits < 8 && MathAbs(step - NormalizeDouble(step, digits)) > 1e-12)
      digits++;
   return(digits);
}

double NormalizeVolumeDown(const double volume)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0 || min_volume <= 0.0 || max_volume < min_volume)
      return(0.0);

   double clipped = MathMin(volume, max_volume);
   double stepped = MathFloor((clipped + 1e-12) / step) * step;
   stepped = NormalizeDouble(stepped, VolumeDigits());
   if(stepped < min_volume - 1e-12)
      return(0.0);
   return(stepped);
}

string DirectionText(const int direction)
{
   if(direction > 0) return("BUY");
   if(direction < 0) return("SELL");
   return("NONE");
}

string DealReasonText(const long reason)
{
   if(reason == DEAL_REASON_SL) return("SL");
   if(reason == DEAL_REASON_TP) return("TP");
   if(reason == DEAL_REASON_SO) return("STOP_OUT");
   if(reason == DEAL_REASON_EXPERT) return("EXPERT");
   if(reason == DEAL_REASON_CLIENT) return("MANUAL");
   if(reason == DEAL_REASON_MOBILE) return("MOBILE");
   if(reason == DEAL_REASON_WEB) return("WEB");
   return("BROKER");
}

double CalibratedTickValue()
{
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double broker_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double contract_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(tick_size <= 0.0 || contract_size <= 0.0)
      return(0.0);

   double geometric_value = tick_size * contract_size;
   if(broker_value <= 0.0 || MathAbs(broker_value - geometric_value) > TICK_VALUE_TOLERANCE * geometric_value)
   {
      PrintFormat(VersionTag() + "TICK VALUE OVERRIDE: broker=%.10f geometry=%.10f "
                  "(tick size %.10f x contract %.4f)",
                  broker_value, geometric_value, tick_size, contract_size);
      return(geometric_value);
   }
   return(broker_value);
}

bool StopsMeetBrokerMinimum(const double entry, const double sl, const double tp)
{
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      return(false);
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minimum = (double)MathMax(stops_level, freeze_level) * point;
   return(MathAbs(entry - sl) + point * 0.1 >= minimum &&
          MathAbs(tp - entry) + point * 0.1 >= minimum);
}

bool ReadIndicator(const int handle, const int buffer, const int shift, double &value)
{
   value = 0.0;
   if(handle == INVALID_HANDLE || BarsCalculated(handle) < shift + 1)
      return(false);
   double values[1];
   ResetLastError();
   if(CopyBuffer(handle, buffer, shift, 1, values) != 1)
      return(false);
   if(!MathIsValidNumber(values[0]) || values[0] == EMPTY_VALUE)
      return(false);
   value = values[0];
   return(true);
}

//+------------------------------------------------------------------+
//| Signal core — byte-faithful to MitemshubAI_v28                    |
//+------------------------------------------------------------------+
bool ReadMacroDirection(int &direction, string &description)
{
   direction = 0;
   description = "NO TRADE";

   if(InpStrategyMode == V28_TRIGGER_ONLY)
   {
      description = "TRIGGER-ONLY";
      return(true);
   }

   double h4_close = iClose(_Symbol, PERIOD_H4, 1);
   double h1_close = iClose(_Symbol, PERIOD_H1, 1);
   double h4_ema = 0.0;
   double h1_ema = 0.0;
   if(h4_close <= 0.0 || h1_close <= 0.0 ||
      !ReadIndicator(g_h4_ema, 0, 1, h4_ema) ||
      !ReadIndicator(g_h1_ema, 0, 1, h1_ema) ||
      h4_ema <= 0.0 || h1_ema <= 0.0)
   {
      description = "DATA NOT READY";
      return(false);
   }

   bool h4_up = h4_close > h4_ema;
   bool h4_down = h4_close < h4_ema;
   bool h1_up = h1_close > h1_ema;
   bool h1_down = h1_close < h1_ema;

   int base_direction = 0;
   string base = "";
   if(h4_up && h1_up)
   {
      base_direction = 1;
      base = "ALIGNED UP (H4/H1)";
   }
   else if(h4_down && h1_down)
   {
      base_direction = -1;
      base = "ALIGNED DOWN (H4/H1)";
   }
   else if((h4_up && h1_down) || (h4_down && h1_up))
   {
      base = "DIVERGENT H4/H1";
   }
   else
   {
      base = "H4/H1 EMA NEUTRAL";
   }

   if(base_direction == 0)
   {
      description = base;
      return(true);
   }

   direction = base_direction;
   if(InpStrategyMode == V28_REVERSE_DIRECTION || InpStrategyMode == V28_REVERSE_BOTH)
      direction *= -1;

   description = (direction != base_direction ? "REVERSED " : "") + base;
   if(InpStrategyMode == V28_MACRO_ONLY)
      description = "MACRO-ONLY | " + description;
   return(true);
}

bool ReadM30Springboard(const int direction, string &trigger)
{
   trigger = "NONE";
   double close = iClose(_Symbol, PERIOD_M30, 1);
   double lower = 0.0;
   double upper = 0.0;
   double rsi = 0.0;
   if(close <= 0.0 ||
      !ReadIndicator(g_m30_bands, 2, 1, lower) ||
      !ReadIndicator(g_m30_bands, 1, 1, upper) ||
      !ReadIndicator(g_m30_rsi, 0, 1, rsi) ||
      lower <= 0.0 || upper <= 0.0)
      return(false);

   bool oversold = (close <= lower) || (rsi <= 35.0);
   bool overbought = (close >= upper) || (rsi >= 65.0);
   bool strong_oversold = (close <= lower && rsi <= 35.0);
   bool strong_overbought = (close >= upper && rsi >= 65.0);

   if(InpStrategyMode == V28_TRIGGER_ONLY)
   {
      if(strong_oversold) trigger = "TRIGGER_ONLY_BUY_BB+RSI";
      else if(oversold) trigger = "TRIGGER_ONLY_BUY";
      else if(strong_overbought) trigger = "TRIGGER_ONLY_SELL_BB+RSI";
      else if(overbought) trigger = "TRIGGER_ONLY_SELL";
      return(true);
   }

   bool reverse_trigger = (InpStrategyMode == V28_REVERSE_TRIGGER || InpStrategyMode == V28_REVERSE_BOTH);

   if(direction > 0)
   {
      if((!reverse_trigger && strong_oversold) || (reverse_trigger && strong_overbought))
         trigger = reverse_trigger ? "M30_REVERSED_BB_UPPER+RSI" : "M30_BB_LOWER+RSI";
      else if((!reverse_trigger && oversold) || (reverse_trigger && overbought))
         trigger = reverse_trigger ? "M30_REVERSED_EXTREME" : "M30_OVERSOLD_EXTREME";
   }
   else if(direction < 0)
   {
      if((!reverse_trigger && strong_overbought) || (reverse_trigger && strong_oversold))
         trigger = reverse_trigger ? "M30_REVERSED_BB_LOWER+RSI" : "M30_BB_UPPER+RSI";
      else if((!reverse_trigger && overbought) || (reverse_trigger && oversold))
         trigger = reverse_trigger ? "M30_REVERSED_EXTREME" : "M30_OVERBOUGHT_EXTREME";
   }
   return(true);
}

//+------------------------------------------------------------------+
//| Session accounting                                                |
//+------------------------------------------------------------------+
void BuildGlobalNames()
{
   g_gv_prefix = StringFormat("MITEMSHUB_V75M_%I64d_%s", InpMagic, SafeSymbolKey());
}

void SaveSessionState()
{
   if(g_gv_prefix == "") return;
   if(IsTesterRun()) return;
   GlobalVariableSet(g_gv_prefix + "_DAY", (double)g_session_day);
   GlobalVariableSet(g_gv_prefix + "_PNL", g_session_pnl);
   GlobalVariableSet(g_gv_prefix + "_R", g_cumulative_r);
}

void LoadSessionState()
{
   g_session_day = StartOfDay(TimeCurrent());
   g_session_pnl = 0.0;
   g_cumulative_r = 0.0;

   if(IsTesterRun())
      return;

   string day_name = g_gv_prefix + "_DAY";
   if(GlobalVariableCheck(day_name) && (datetime)(long)GlobalVariableGet(day_name) == g_session_day)
   {
      if(GlobalVariableCheck(g_gv_prefix + "_PNL"))
         g_session_pnl = GlobalVariableGet(g_gv_prefix + "_PNL");
      if(GlobalVariableCheck(g_gv_prefix + "_R"))
         g_cumulative_r = GlobalVariableGet(g_gv_prefix + "_R");
   }
   SaveSessionState();
}

void ResetTestMetrics()
{
   g_test_pnl = 0.0;
   g_test_r = 0.0;
   g_test_trades = 0;
   g_test_wins = 0;
   g_test_losses = 0;
   g_test_sl_exits = 0;
   g_test_tp_exits = 0;
   g_test_timeout_exits = 0;
   g_sum_risk = 0.0;
   g_sum_abs_pnl = 0.0;
   g_risk_min = 0.0;
   g_risk_max = 0.0;
   g_peak_r = 0.0;
   g_mfe_sum = 0.0;
   g_mfe_max = 0.0;
   ArrayInitialize(g_mfe_hits, 0);
}

void MaintainSessionDay()
{
   datetime today = StartOfDay(TimeCurrent());
   if(today != g_session_day)
   {
      g_session_day = today;
      g_session_pnl = 0.0;
      SaveSessionState();
   }
}

//+------------------------------------------------------------------+
//| R denominator (v28 single-owner contract)                         |
//+------------------------------------------------------------------+
// Sizing basis: paper mode sizes on VIRTUAL equity (v26.40 contract), so the
// virtual book compounds on its own numbers. R stays volume-invariant.
double SizingEquity()
{
   return(PaperActive() ? PaperEquity() : AccountInfoDouble(ACCOUNT_EQUITY));
}

double IntendedRiskMoney()
{
   return(SizingEquity() * InpRiskFraction);
}

void CommitTradeRisk(const double risk, const ulong position_id, const string source)
{
   g_risk_money = risk > 0.0 ? risk : 0.0;
   g_risk_money_id = position_id;
   g_risk_money_src = source;
}

void ClearActiveState()
{
   g_has_active_trade = false;
   g_close_booked = false;
   g_timeout_requested = false;
   g_missing_close_polls = 0;
   g_last_timeout_attempt = 0;
   g_position_ticket = 0;
   g_position_id = 0;
   g_position_direction = 0;
   g_entry_time = 0;
   g_expiration_time = 0;
   g_entry_price = 0.0;
   g_active_atr = 0.0;
   g_active_sl = 0.0;
   g_active_tp = 0.0;
   CommitTradeRisk(0.0, 0, "NONE");
   g_entry_trigger = "";
}

//+------------------------------------------------------------------+
//| Paper ledger — v26.40 semantics, VERIFIED APPEND included         |
//+------------------------------------------------------------------+
double PaperEquity() { return(g_paper_eq > 0 ? g_paper_eq : InpPaperEquity); }

bool AppendVerified(const string file, const string line, const string tag)
{
   uint want = StringLen(line) + 2;
   for(int attempt = 0; attempt < 2; attempt++)
   {
      int h = FileOpen(file, FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
      if(h != INVALID_HANDLE)
      {
         FileSeek(h, 0, SEEK_END);
         long before = (long)FileSize(h);
         uint got = FileWriteString(h, line + "\r\n");
         FileClose(h);
         int v = FileOpen(file, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
         bool on_disk = false;
         if(v != INVALID_HANDLE)
         {
            on_disk = ((long)FileSize(v) >= before + (long)want);
            FileClose(v);
         }
         if(got >= want && on_disk)
            return(true);
      }
      Sleep(50);
   }
   Print(VersionTag() + "WLOST [" + tag + "] append failed twice err=" + IntegerToString(GetLastError()) + " line=" + line);
   return(false);
}

void PaperLog(string line)
{
   AppendVerified(PaperFile(), line, StringSubstr(line, 0, 5));
}

void ParseFleetMagics()
{
   g_fleet_count = 0;
   ArrayResize(g_fleet_magics, 0);
   string parts[];
   int n = StringSplit(InpFleetMagicsCSV, ',', parts);
   for(int i = 0; i < n; i++)
   {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      long m = StringToInteger(s);
      if(m <= 0) continue;
      ArrayResize(g_fleet_magics, g_fleet_count + 1);
      g_fleet_magics[g_fleet_count] = m;
      g_fleet_count++;
   }
}

// v26.37 fleet-mirror semantics: a single open VIRTUAL position IS the fleet
// contribution (it was once read as $0.00 while a trade was live — the defect
// class that build fixed). Other fleet magics' REAL positions are summed too.
double FleetOpenRisk()
{
   double total = 0.0;
   if(g_pp_open && g_pp_eff_risk > 0.0)
      total += g_pp_eff_risk;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      long magic = (long)PositionGetInteger(POSITION_MAGIC);
      if(magic == InpMagic) continue;         // own (paper) risk counted above
      for(int k = 0; k < g_fleet_count; k++)
      {
         if(magic == g_fleet_magics[k])
         {
            double sl = PositionGetDouble(POSITION_SL);
            double open = PositionGetDouble(POSITION_PRICE_OPEN);
            double vol = PositionGetDouble(POSITION_VOLUME);
            if(sl > 0.0 && open > 0.0 && vol > 0.0)
            {
               double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
               double tick_value = CalibratedTickValue();
               if(tick_size > 0.0 && tick_value > 0.0)
                  total += (MathAbs(open - sl) / tick_size) * tick_value * vol;
            }
            break;
         }
      }
   }
   return(total);
}

// The ACCOUNT GUARD print's exact shape is load-bearing: scripts/funnel_diff.py
// parses "ACCOUNT GUARD: fleet $X + new $Y > cap $Z" for its classification.
bool AccountBudgetAllows(const double new_risk)
{
   double cap = PaperEquity() * InpMaxTotalRiskPct / 100.0;
   double fleet = FleetOpenRisk();
   if(fleet + new_risk > cap + 1e-9)
   {
      PrintFormat(VersionTag() + "SKIP %s — ACCOUNT GUARD: fleet $%.2f + new $%.2f > cap $%.2f",
                  g_entry_trigger != "" ? g_entry_trigger : "SIGNAL", fleet, new_risk, cap);
      return(false);
   }
   return(true);
}

//+------------------------------------------------------------------+
//| FLOOR-MODE POLICY (the strangulation-zone contract).              |
//| Floor mode = the broker minimum lot risks more than the strategy  |
//| fraction of virtual equity (paper only; the tester path keeps the |
//| research contract byte-faithful). The account must still trade —  |
//| but only the highest-conviction signals, and never into a         |
//| collapsing book. Two gates run BEFORE the account-budget guard,   |
//| and both print their operands loudly:                             |
//|   1. HARD DRAWDOWN STOP — at InpFloorModeMaxDDPct below the       |
//|      window-start equity, entries halt (structural-abort          |
//|      territory: restart on a fresh ledger, per ARM_A2_RESTART).   |
//|   2. RAISED ENTRY BAR — only the strong BB+RSI trigger pays the   |
//|      floor's ~10x risk premium; plain EXTREME signals stand down. |
//| A normally-sized account (e.g. A2 at $1,000) never enters floor   |
//| mode and is untouched by both gates.                              |
//+------------------------------------------------------------------+
bool IsStrongTrigger(const string trigger)
{
   // Strong springboards carry both the band tag and the RSI confluence:
   // M30_REVERSED_BB_UPPER+RSI / M30_BB_LOWER+RSI / TRIGGER_ONLY_*_BB+RSI.
   // Plain *_EXTREME signals carry neither.
   return(StringFind(trigger, "BB") >= 0 && StringFind(trigger, "+RSI") >= 0);
}

bool FloorModePolicyAllows(const double min_lot_risk)
{
   double veq = PaperEquity();
   double floor_eq = g_paper_start * (1.0 - InpFloorModeMaxDDPct / 100.0);
   if(veq <= floor_eq)
   {
      PrintFormat(VersionTag() + "FLOOR MODE HALT: virtual equity $%.2f <= hard floor $%.2f "
                  "(%s%% below window start $%.2f) — entries halted; restart is a "
                  "structural abort on a fresh ledger",
                  veq, floor_eq, DoubleToString(InpFloorModeMaxDDPct, 1), g_paper_start);
      return(false);
   }
   // ML consult leg (§10.7): consult-only in PASSIVE mode — the decision
   // rides on the rule-based conviction bar until the frozen gate certifies
   // the table ACTIVE. Every read is printed and ledgered either way.
   if(g_filter_consult_side != "" &&
      !FilterConsultAllows(g_filter_consult_side, TimeCurrent()))
      return(false);
   // Conviction bar is MATERIALITY-CONDITIONED (amended 2026-09-16, pre-data):
   // the strong BB+RSI confluence appeared in 0 of ~800 observed sweep entries,
   // so demanding it for a 1.28% overage (A2 at $1,000) would throttle the arm
   // to ~zero trades — the silent-strangulation failure the policy exists to
   // prevent, reborn through the bar itself. The premium is only demanded
   // when the min-lot overage is material (> InpFloorModeConvictionMinRiskPct
   // of vEq — ~10% at a $50 book). Below the threshold the ordinary budget
   // guard still applies with full force.
   if(InpFloorModeConviction &&
      min_lot_risk / veq * 100.0 > InpFloorModeConvictionMinRiskPct &&
      !IsStrongTrigger(g_entry_trigger))
   {
      PrintFormat(VersionTag() + "FLOOR MODE: signal %s lacks the strong BB+RSI conviction bar "
                  "(min lot = %.1f%% of vEq $%.2f > %.1f%% bar) — standing down",
                  g_entry_trigger != "" ? g_entry_trigger : "SIGNAL",
                  min_lot_risk / veq * 100.0, veq,
                  InpFloorModeConvictionMinRiskPct);
      return(false);
   }
   return(true);
}

bool PaperInit()
{
   g_paper_eq = InpPaperEquity;
   g_paper_start = InpPaperEquity;
   // Era provenance stamp — idempotent; readers keep the first one (v26.39).
   if(PaperActive())
   {
      PaperLog("ERA," + APP_VERSION + ",1789494700,pertick-fills");
      PrintFormat(VersionTag() + "PAPER ledger era stamp: %s (per-tick fills from the v26.38 boundary)", APP_VERSION);
   }
   int h = FileOpen(PaperFile(), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE)
      return(true);                     // fresh start
   double last_veq = InpPaperEquity;
   // OPEN/CLOSE sequential pairing on the single-position book. A dangling
   // OPEN (terminal stopped mid-trade) restores the virtual position so the
   // hard-exit mirror keeps managing it — never orphaned, never re-opened.
   bool   d_open = false; int d_dir = 0; double d_entry = 0, d_sl = 0, d_tp = 0;
   double d_vol = 0, d_eff = 0, d_orig = 0; int d_hold = 0;
   string d_tag = ""; ulong d_ticket = 0; datetime d_time = 0;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) < 4) continue;
      string p[];
      int n = StringSplit(line, ',', p);
      if(n < 2) continue;
      if(p[0] == "CLOSE" && n >= 8)
      {
         d_open = false;
         last_veq = StringToDouble(p[7]);
      }
      else if(p[0] == "OPEN" && n >= 12)
      {
         d_open = true;
         d_time = (datetime)(long)StringToInteger(p[1]);
         d_ticket = (ulong)StringToInteger(p[2]);
         d_dir = (int)StringToInteger(p[3]);
         d_entry = StringToDouble(p[4]);
         d_sl = StringToDouble(p[5]);
         d_tp = StringToDouble(p[6]);
         d_vol = StringToDouble(p[7]);
         d_eff = StringToDouble(p[8]);
         d_orig = StringToDouble(p[9]);
         d_hold = (int)StringToInteger(p[10]);
         d_tag = p[11];
      }
      else if(p[0] == "ERA")
      {
         // provenance only
      }
   }
   FileClose(h);
   g_paper_eq = last_veq;
   if(d_open && d_dir != 0 && d_entry > 0.0)
   {
      g_pp_open = true; g_pp_dir = d_dir; g_pp_entry = d_entry; g_pp_sl = d_sl;
      g_pp_tp = d_tp; g_pp_vol = d_vol; g_pp_eff_risk = d_eff;
      g_pp_orig_risk = d_orig; g_pp_entry_time = d_time; g_pp_ticket = d_ticket;
      g_pp_tag = d_tag;
      PrintFormat(VersionTag() + "PAPER resume: dangling OPEN restored (ticket=%I64u dir=%d entry=%.5f) — hard exits re-armed",
                  d_ticket, d_dir, d_entry);
   }
   PrintFormat(VersionTag() + "PAPER resume: virtual equity $%.2f from ledger %s", g_paper_eq, PaperFile());
   LoadFilterTable();                   // ML consult — banner-proven, consult-only
   return(true);
}

bool PaperOpen(int direction, double entry, double sl, double tp, double vol,
               double eff_risk, string tag)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sprd = ask - bid;
   double extra = MathMax(InpPaperSpreadMult - 1.0, 0.0) * sprd;
   double fill = (direction > 0) ? ask + extra : bid - extra;
   double delta = fill - entry;
   if(MathAbs(delta) > 0) { entry += delta; sl += delta; tp += delta; }
   ulong ticket = (ulong)TimeCurrent();
   g_pp_open = true; g_pp_dir = direction; g_pp_entry = entry; g_pp_sl = sl;
   g_filter_consult_side = "";          // consult consumed for this entry
   g_pp_tp = tp; g_pp_orig_risk = MathAbs(entry - sl); g_pp_vol = vol;
   g_pp_eff_risk = eff_risk; g_pp_entry_time = TimeCurrent(); g_pp_tag = tag;
   g_pp_ticket = ticket;
   // Commit the R denominator to the v28 single-owner contract so the close
   // accounting and the "Trade R:" parity line divide by the committed risk.
   CommitTradeRisk(eff_risk, 0, "ENTRY");
   g_entry_price = entry; g_active_sl = sl; g_active_tp = tp;
   g_entry_time = g_pp_entry_time;
   g_expiration_time = g_pp_entry_time + (datetime)MathMax(1, InpMaxHoldMinutes) * 60;
   PrintFormat(VersionTag() + "PAPER FILL %s vol=%.2f @%.5f SL=%.5f TP=%.5f risk=$%.2f (%.2f%% vEq) | %s",
               direction > 0 ? "BUY" : "SELL", vol, entry, sl, tp, eff_risk,
               eff_risk / MathMax(PaperEquity(), 0.01) * 100.0, tag);
   PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s",
            (long)TimeCurrent(), ticket, direction, entry, sl, tp, vol, eff_risk,
            g_pp_orig_risk, (int)(InpMaxHoldMinutes * 60), tag));
   return(true);
}

//+------------------------------------------------------------------+
//| Per-tick hard-exit mirror (v26.38): SL/TP fill on first touch,    |
//| STOP checked before TP when one tick spans both. Plus the paper   |
//| time exit — v28's hold contract is MINUTES (expiration_time),     |
//| not bars, so the mirror enforces it here.                         |
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
   if(TimeCurrent() >= g_expiration_time)
   {
      PaperClose("TIME", 0);
      return;
   }
}

//+------------------------------------------------------------------+
//| THE PARITY EVIDENCE LINE: one "Trade R:" per closed trade, on     |
//| every close, paper and live. build_parity.py aligns these (in     |
//| order) with the report's paired deals; without them no parity     |
//| run can ever be more than INCONCLUSIVE.                           |
//+------------------------------------------------------------------+
void PrintTradeR(const double realized_r)
{
   PrintFormat(VersionTag() + "Trade R: %+.4f", realized_r);
}

void PaperClose(string reason, double exit_price = 0)
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double exit = (exit_price > 0) ? exit_price : ((g_pp_dir > 0) ? bid : ask);
   double r = g_pp_orig_risk > 0 ? ((g_pp_dir > 0) ? (exit - g_pp_entry) : (g_pp_entry - exit)) / g_pp_orig_risk : 0;
   double pnl = g_pp_eff_risk * r;
   ulong ticket = g_pp_ticket;
   PaperLog(StringFormat("CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f",
            (long)TimeCurrent(), ticket, reason, exit, r, pnl, PaperEquity() + pnl));
   // v28 whole-run accounting (R denominator = the committed eff_risk)
   double realized_r = r;   // paper r IS pnl/risk by construction
   g_session_pnl += pnl;
   g_cumulative_r += realized_r;
   g_test_pnl += pnl;
   g_test_r += realized_r;
   g_test_trades++;
   if(pnl > 0.0) g_test_wins++;
   else if(pnl < 0.0) g_test_losses++;
   if(reason == "STOP") g_test_sl_exits++;
   else if(reason == "TARGET") g_test_tp_exits++;
   else if(reason == "TIME") g_test_timeout_exits++;
   if(g_pp_eff_risk > 0.0)
   {
      g_sum_risk += g_pp_eff_risk;
      g_sum_abs_pnl += MathAbs(pnl);
      if(g_risk_min <= 0.0 || g_pp_eff_risk < g_risk_min) g_risk_min = g_pp_eff_risk;
      if(g_pp_eff_risk > g_risk_max) g_risk_max = g_pp_eff_risk;
   }
   SaveSessionState();
   g_paper_eq += pnl;
   PaperLog(StringFormat("EQ,%.2f", g_paper_eq));
   PrintFormat(VersionTag() + "PAPER CLOSE %s R=%+.3f pnl=$%+.2f vEq=$%.2f",
               reason, realized_r, pnl, g_paper_eq);
   PrintTradeR(realized_r);
   g_pp_open = false; g_pp_dir = 0; g_pp_entry = 0; g_pp_sl = 0; g_pp_tp = 0;
   g_pp_orig_risk = 0; g_pp_vol = 0; g_pp_eff_risk = 0; g_pp_ticket = 0;
   ClearActiveState();
}

//+------------------------------------------------------------------+
//| Managed-position ownership (live/research contract only — paper   |
//| mode never owns a real position)                                  |
//+------------------------------------------------------------------+
bool FindManagedPosition(ulong &ticket, ulong &identifier)
{
   ticket = 0;
   identifier = 0;
   for(int index = 0; index < PositionsTotal(); index++)
   {
      ulong candidate = PositionGetTicket(index);
      if(candidate == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      ticket = candidate;
      identifier = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      return(true);
   }
   return(false);
}

void CaptureManagedPosition(const ulong ticket, const ulong identifier)
{
   if(!PositionSelectByTicket(ticket))
      return;

   if(g_has_active_trade && g_position_id != 0 && identifier != g_position_id)
   {
      RecoverClosedPosition();
      if(g_has_active_trade && identifier != g_position_id)
         ClearActiveState();
   }

   g_has_active_trade = true;
   g_position_ticket = ticket;
   g_position_id = identifier;
   g_position_direction = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
   g_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   g_active_sl = PositionGetDouble(POSITION_SL);
   g_active_tp = PositionGetDouble(POSITION_TP);
   g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
   if(g_entry_time <= 0) g_entry_time = TimeCurrent();
   g_expiration_time = g_entry_time + (datetime)MathMax(1, InpMaxHoldMinutes) * 60;
   g_peak_r = 0.0;

   if(g_active_atr <= 0.0 && g_active_sl > 0.0)
      g_active_atr = MathAbs(g_entry_price - g_active_sl) / InpStopATRMultiplier;
   if(g_active_atr <= 0.0)
      ReadIndicator(g_h1_atr, 0, 1, g_active_atr);

   if(g_risk_money <= 0.0)
   {
      double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = CalibratedTickValue();
      double volume = PositionGetDouble(POSITION_VOLUME);
      double stop_distance = MathAbs(g_entry_price - g_active_sl);
      double planned = IntendedRiskMoney();
      double derived = 0.0;
      if(tick_size > 0.0 && tick_value > 0.0 && volume > 0.0 && stop_distance > 0.0)
         derived = (stop_distance / tick_size) * tick_value * volume;

      if(derived > 0.0 && planned > 0.0 && derived <= planned * RISK_PLAUSIBILITY_BOUND)
         CommitTradeRisk(derived, identifier, "POSITION");
      else
         CommitTradeRisk(planned, identifier, derived > 0.0 ? "FALLBACK_BOUND" : "FALLBACK");
   }
   else if(g_risk_money_id == 0)
      g_risk_money_id = identifier;
   g_missing_close_polls = 0;
}

void PollManagedPosition()
{
   if(PaperActive())
      return;                            // the virtual book is the only position in paper mode
   ulong ticket = 0;
   ulong identifier = 0;
   if(FindManagedPosition(ticket, identifier))
   {
      if(!g_has_active_trade)
      {
         CaptureManagedPosition(ticket, identifier);
         if(InpLiveExecution && g_active_atr > 0.0)
            ConfigureFilledPosition(g_active_atr);
      }
      else if(identifier != g_position_id)
      {
         CaptureManagedPosition(ticket, identifier);
      }
      else
      {
         g_position_ticket = ticket;
         g_position_id = identifier;
         if(PositionSelectByTicket(ticket))
         {
            g_active_sl = PositionGetDouble(POSITION_SL);
            g_active_tp = PositionGetDouble(POSITION_TP);
         }
      }
      return;
   }

   if(g_has_active_trade)
      RecoverClosedPosition();
}

//+------------------------------------------------------------------+
//| Close bookkeeping (live/research path)                            |
//+------------------------------------------------------------------+
bool IsClosingDeal(const ulong deal_ticket)
{
   if(deal_ticket == 0) return(false);
   long entry = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);
   return(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT);
}

void FinalizeClosedTrade(const ulong deal_ticket, const double pnl, const double exit_price,
                        const string reason)
{
   if(!g_has_active_trade || g_close_booked)
      return;
   g_close_booked = true;

   double risk_used = 0.0;
   string risk_src = "NONE";
   if(g_risk_money > 0.0 &&
      (g_risk_money_id == 0 || g_position_id == 0 || g_risk_money_id == g_position_id))
   {
      risk_used = g_risk_money;
      risk_src = g_risk_money_src;
   }
   else
   {
      risk_used = IntendedRiskMoney();
      risk_src = "MISMATCH";
   }

   double realized_r = 0.0;
   if(risk_used > 0.0)
      realized_r = pnl / risk_used;
   g_session_pnl += pnl;
   g_cumulative_r += realized_r;
   g_test_pnl += pnl;
   g_test_r += realized_r;
   g_test_trades++;
   if(pnl > 0.0) g_test_wins++;
   else if(pnl < 0.0) g_test_losses++;
   if(reason == "SL") g_test_sl_exits++;
   else if(reason == "TP") g_test_tp_exits++;
   else if(reason == "TIMEOUT") g_test_timeout_exits++;
   if(risk_used > 0.0)
   {
      g_sum_risk += risk_used;
      g_sum_abs_pnl += MathAbs(pnl);
      if(g_risk_min <= 0.0 || risk_used < g_risk_min)
         g_risk_min = risk_used;
      if(risk_used > g_risk_max)
         g_risk_max = risk_used;
   }
   if(realized_r > g_peak_r)
      g_peak_r = realized_r;
   g_mfe_sum += g_peak_r;
   if(g_peak_r > g_mfe_max)
      g_mfe_max = g_peak_r;
   for(int mfe = 0; mfe < 6; mfe++)
      if(g_peak_r >= MFE_GRID[mfe])
         g_mfe_hits[mfe]++;
   SaveSessionState();

   PrintFormat(VersionTag() + "CLOSE %s ticket=%I64u pnl=%+.2f R=%+.3f risk=%.2f "
               "risk_src=%s peak_r=%.3f cum_pnl=%+.2f cum_R=%+.3f exit=%.5f hold=%d sec",
               reason, g_position_ticket, pnl, realized_r, risk_used, risk_src, g_peak_r,
               g_test_pnl, g_test_r, exit_price,
               g_entry_time > 0 ? (int)(TimeCurrent() - g_entry_time) : 0);
   PrintTradeR(realized_r);
   ClearActiveState();
}

bool FindClosingDeals(ulong &latest_deal_ticket, double &pnl, double &exit_price, string &reason)
{
   latest_deal_ticket = 0;
   pnl = 0.0;
   exit_price = 0.0;
   reason = "BROKER";
   datetime from = g_entry_time > 60 ? g_entry_time - 60 : 0;
   datetime to = TimeCurrent() + 60;
   if(!HistorySelect(from, to))
      return(false);

   long latest_time = -1;
   int matched = 0;
   int total = HistoryDealsTotal();
   for(int index = total - 1; index >= 0; index--)
   {
      ulong candidate = HistoryDealGetTicket(index);
      if(candidate == 0 || !IsClosingDeal(candidate)) continue;
      if(HistoryDealGetString(candidate, DEAL_SYMBOL) != _Symbol) continue;
      ulong position_id = (ulong)HistoryDealGetInteger(candidate, DEAL_POSITION_ID);
      long deal_magic = HistoryDealGetInteger(candidate, DEAL_MAGIC);
      if(g_position_id != 0)
      {
         if(position_id != g_position_id) continue;
      }
      else if(deal_magic != InpMagic)
      {
         continue;
      }

      pnl += HistoryDealGetDouble(candidate, DEAL_PROFIT) +
             HistoryDealGetDouble(candidate, DEAL_SWAP) +
             HistoryDealGetDouble(candidate, DEAL_COMMISSION);
      matched++;
      long deal_time = HistoryDealGetInteger(candidate, DEAL_TIME);
      if(deal_time >= latest_time)
      {
         latest_time = deal_time;
         latest_deal_ticket = candidate;
         exit_price = HistoryDealGetDouble(candidate, DEAL_PRICE);
         reason = DealReasonText(HistoryDealGetInteger(candidate, DEAL_REASON));
      }
   }
   return(matched > 0);
}

void RecoverClosedPosition()
{
   if(!g_has_active_trade || g_close_booked)
      return;

   ulong deal_ticket = 0;
   double pnl = 0.0;
   double exit_price = 0.0;
   string reason = "BROKER";
   if(FindClosingDeals(deal_ticket, pnl, exit_price, reason))
   {
      if(g_timeout_requested) reason = "TIMEOUT";
      FinalizeClosedTrade(deal_ticket, pnl, exit_price, reason);
      return;
   }

   g_missing_close_polls++;
   if(g_missing_close_polls >= 3)
   {
      Print(VersionTag() + "POSITION GONE without a matching close deal; "
            "clearing internal state conservatively");
      ClearActiveState();
   }
}

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(PaperActive())
      return;
   if(transaction.type != TRADE_TRANSACTION_DEAL_ADD || transaction.deal == 0)
      return;
   if(!g_has_active_trade || g_close_booked)
      return;
   if(HistoryDealGetString(transaction.deal, DEAL_SYMBOL) != _Symbol)
      return;
   if(!IsClosingDeal(transaction.deal))
      return;

   ulong position_id = (ulong)HistoryDealGetInteger(transaction.deal, DEAL_POSITION_ID);
   long deal_magic = HistoryDealGetInteger(transaction.deal, DEAL_MAGIC);
   if(g_position_id != 0)
   {
      if(position_id != g_position_id)
         return;
   }
   else if(deal_magic != InpMagic)
   {
      return;
   }

   ulong ticket = 0;
   ulong identifier = 0;
   if(FindManagedPosition(ticket, identifier))
      return;

   ulong latest_deal = 0;
   double pnl = 0.0;
   double exit_price = 0.0;
   string reason = "BROKER";
   if(!FindClosingDeals(latest_deal, pnl, exit_price, reason))
   {
      latest_deal = transaction.deal;
      pnl = HistoryDealGetDouble(transaction.deal, DEAL_PROFIT) +
            HistoryDealGetDouble(transaction.deal, DEAL_SWAP) +
            HistoryDealGetDouble(transaction.deal, DEAL_COMMISSION);
      exit_price = HistoryDealGetDouble(transaction.deal, DEAL_PRICE);
      reason = DealReasonText(HistoryDealGetInteger(transaction.deal, DEAL_REASON));
   }
   if(g_timeout_requested) reason = "TIMEOUT";
   FinalizeClosedTrade(latest_deal, pnl, exit_price, reason);
}

void TrackPeakExcursion()
{
   if(!g_has_active_trade || g_risk_money <= 0.0 || g_position_ticket == 0)
      return;
   if(!PositionSelectByTicket(g_position_ticket))
      return;
   double floating_r = PositionGetDouble(POSITION_PROFIT) / g_risk_money;
   if(floating_r > g_peak_r)
      g_peak_r = floating_r;
}

void ManageTimeGuardian()
{
   if(PaperActive())
      return;                            // paper time exit lives in PaperCheckHardExits
   if(!g_has_active_trade || g_expiration_time <= 0)
      return;
   if(TimeCurrent() < g_expiration_time)
      return;

   if(g_last_timeout_attempt == TimeCurrent())
      return;
   g_last_timeout_attempt = TimeCurrent();
   g_timeout_requested = true;
   ResetLastError();
   if(!trade.PositionClose(g_position_ticket, InpMaxDeviationPoints))
   {
      PrintFormat(VersionTag() + "TIMEOUT CLOSE RETRY: ticket=%I64u retcode=%u %s",
                  g_position_ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
   }
   else
   {
      PrintFormat(VersionTag() + "TIMEOUT LIQUIDATION requested: ticket=%I64u hold=%dmin",
                  g_position_ticket, InpMaxHoldMinutes);
   }
}

//+------------------------------------------------------------------+
//| Risk and entry. Sizing basis: virtual equity in paper mode.       |
//| FLOOR MODE (the trade-any-account contract): when the broker      |
//| minimum lot risks more than the strategy fraction, the trade      |
//| takes the minimum lot if the ACCOUNT budget allows — never a      |
//| silent block. The account-budget guard (v26.40 print) is the      |
//| only veto, and it always prints its operands.                     |
//+------------------------------------------------------------------+
bool CalculateVolume(const double entry, const double atr, double &volume, double &risk_money)
{
   volume = 0.0;
   risk_money = SizingEquity() * InpRiskFraction;
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = CalibratedTickValue();
   if(entry <= 0.0 || atr <= 0.0 || tick_size <= 0.0 || tick_value <= 0.0 || risk_money <= 0.0)
      return(false);

   double stop_distance = InpStopATRMultiplier * atr;
   double risk_per_lot = (stop_distance / tick_size) * tick_value;
   if(risk_per_lot <= 0.0)
      return(false);

   double min_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double min_lot_risk = risk_per_lot * min_volume;

   if(!PaperActive())
   {
      // Research contract, byte-faithful: the tester blocks absurd sizing.
      if(min_lot_risk > risk_money + 1e-8)
      {
         PrintFormat(VersionTag() + "ENTRY BLOCKED: broker minimum lot risks %.2f, "
                     "which exceeds configured %.2f%% equity risk %.2f",
                     min_lot_risk, InpRiskFraction * 100.0, risk_money);
         return(false);
      }
   }
   else if(min_lot_risk > risk_money + 1e-8)
   {
      // FLOOR MODE: the broker floor exceeds the strategy fraction. Take the
      // minimum lot (the account exists to trade) under the floor-mode
      // policy gates and the ACCOUNT budget — loudly, never silently.
      PrintFormat(VersionTag() + "FLOOR MODE: min lot risks $%.2f (%.1f%% of vEq) > strategy %.2f%% "
                  "($%.2f) — trading the minimum lot under the account budget",
                  min_lot_risk, min_lot_risk / PaperEquity() * 100.0,
                  InpRiskFraction * 100.0, risk_money);
      if(!FloorModePolicyAllows(min_lot_risk))
         return(false);
      if(!AccountBudgetAllows(min_lot_risk))
         return(false);
      volume = min_volume;
      risk_money = min_lot_risk;
      return(true);
   }

   // FLOOR MODE also applies when the NORMAL sizing result would breach the
   // account budget: the budget is the account-level constraint, the fraction
   // is the strategy preference. Check it before committing.
   volume = NormalizeVolumeDown(risk_money / risk_per_lot);
   if(volume <= 0.0)
      return(false);

   double commit_risk = (volume / risk_per_lot > 0.0)
                        ? volume * risk_per_lot
                        : (risk_money / risk_per_lot) * risk_per_lot;
   if(PaperActive() && !AccountBudgetAllows(commit_risk))
      return(false);

   risk_money = commit_risk;
   return(true);
}

bool ConfigureFilledPosition(const double atr)
{
   if(!PositionSelectByTicket(g_position_ticket))
      return(false);

   double actual_entry = PositionGetDouble(POSITION_PRICE_OPEN);
   int direction = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
   double sl = direction > 0 ? actual_entry - InpStopATRMultiplier * atr
                              : actual_entry + InpStopATRMultiplier * atr;
   double tp = direction > 0 ? actual_entry + InpTargetATRMultiplier * atr
                              : actual_entry - InpTargetATRMultiplier * atr;
   sl = NormalizePrice(sl);
   tp = NormalizePrice(tp);
   if(!StopsMeetBrokerMinimum(actual_entry, sl, tp))
   {
      Print(VersionTag() + "FILLED POSITION HAS INVALID BROKER STOP DISTANCE; "
            "closing instead of leaving it unmanaged");
      trade.PositionClose(g_position_ticket, InpMaxDeviationPoints);
      return(false);
   }

   if(!trade.PositionModify(g_position_ticket, sl, tp))
   {
      double held_sl = PositionGetDouble(POSITION_SL);
      double held_tp = PositionGetDouble(POSITION_TP);
      bool protected_now = !InpLegacyV27ModifyClose &&
         held_sl > 0.0 && held_tp > 0.0 &&
         ((direction > 0 && held_sl < actual_entry && held_tp > actual_entry) ||
          (direction < 0 && held_sl > actual_entry && held_tp < actual_entry));

      PrintFormat(VersionTag() + "ATR PROTECTION MODIFY REJECTED: retcode=%u %s | "
                  "entry=%.2f want_sl=%.2f want_tp=%.2f held_sl=%.2f held_tp=%.2f "
                  "atr=%.2f dir=%d stops_level=%d point=%.5f bid=%.2f ask=%.2f -> %s",
                  trade.ResultRetcode(), trade.ResultRetcodeDescription(),
                  actual_entry, sl, tp, held_sl, held_tp, atr, direction,
                  (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                  SymbolInfoDouble(_Symbol, SYMBOL_POINT),
                  SymbolInfoDouble(_Symbol, SYMBOL_BID), SymbolInfoDouble(_Symbol, SYMBOL_ASK),
                  protected_now ? "kept (already protected)"
                                : "closing (no valid protection held)");
      if(!protected_now)
      {
         trade.PositionClose(g_position_ticket, InpMaxDeviationPoints);
         return(false);
      }
   }
   g_entry_price = actual_entry;
   g_position_direction = direction;
   g_active_atr = atr;
   g_active_sl = sl;
   g_active_tp = tp;
   return(true);
}

bool OpenMacroTrade(const int direction, const double atr, const string trigger)
{
   // Exactly one open trade account-wide, real OR virtual (v26.40 contract).
   if(PositionsTotal() != 0 || g_pp_open)
      return(false);
   if(!InpLiveExecution)
   {
      // PAPER PATH (v26.40): conservative virtual fill, ledger, virtual equity.
      MqlTick tick;
      if(!SymbolInfoTick(_Symbol, tick))
         return(false);
      double entry = direction > 0 ? tick.ask : tick.bid;
      double sl = direction > 0 ? entry - InpStopATRMultiplier * atr
                                 : entry + InpStopATRMultiplier * atr;
      double tp = direction > 0 ? entry + InpTargetATRMultiplier * atr
                                 : entry - InpTargetATRMultiplier * atr;
      sl = NormalizePrice(sl);
      tp = NormalizePrice(tp);

      double volume = 0.0;
      double risk_money = 0.0;
      g_entry_trigger = trigger;   // floor-mode policy reads the signal name
      g_filter_consult_side = (direction > 0) ? "BUY" : "SELL";
      if(!CalculateVolume(entry, atr, volume, risk_money))
         return(false);

      return(PaperOpen(direction, entry, sl, tp, volume, risk_money, trigger));
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return(false);
   double entry = direction > 0 ? tick.ask : tick.bid;
   double provisional_sl = direction > 0 ? entry - InpStopATRMultiplier * atr
                                         : entry + InpStopATRMultiplier * atr;
   double provisional_tp = direction > 0 ? entry + InpTargetATRMultiplier * atr
                                         : entry - InpTargetATRMultiplier * atr;
   provisional_sl = NormalizePrice(provisional_sl);
   provisional_tp = NormalizePrice(provisional_tp);
   if(!StopsMeetBrokerMinimum(entry, provisional_sl, provisional_tp))
   {
      Print(VersionTag() + "ENTRY BLOCKED: H1 ATR geometry is inside broker stops/freeze level");
      return(false);
   }

   double volume = 0.0;
   double risk_money = 0.0;
   if(!CalculateVolume(entry, atr, volume, risk_money))
      return(false);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   g_active_atr = atr;
   CommitTradeRisk(risk_money, 0, "ENTRY");
   g_entry_trigger = trigger;
   bool sent = direction > 0
      ? trade.Buy(volume, _Symbol, 0.0, provisional_sl, provisional_tp, "V75-MACRO-3H")
      : trade.Sell(volume, _Symbol, 0.0, provisional_sl, provisional_tp, "V75-MACRO-3H");
   uint retcode = trade.ResultRetcode();
   if(!sent || (retcode != TRADE_RETCODE_DONE && retcode != TRADE_RETCODE_DONE_PARTIAL &&
                retcode != TRADE_RETCODE_PLACED))
   {
      PrintFormat(VersionTag() + "ORDER FAILED retcode=%u %s",
                  retcode, trade.ResultRetcodeDescription());
      g_active_atr = 0.0;
      CommitTradeRisk(0.0, 0, "NONE");
      g_entry_trigger = "";
      return(false);
   }

   ulong ticket = 0;
   ulong identifier = 0;
   if(!FindManagedPosition(ticket, identifier))
   {
      Print(VersionTag() + "ORDER accepted but position is not visible yet; polling will recover it");
      return(true);
   }
   CaptureManagedPosition(ticket, identifier);
   if(!ConfigureFilledPosition(atr))
      return(false);

   g_last_gate = "OPENED " + DirectionText(direction);
   PrintFormat(VersionTag() + "OPEN %s volume=%.4f entry=%.5f SL=%.5f TP=%.5f "
               "risk=$%.2f risk_src=%s expiry=%s trigger=%s",
               DirectionText(direction), PositionGetDouble(POSITION_VOLUME),
               g_entry_price, g_active_sl, g_active_tp, g_risk_money, g_risk_money_src,
               TimeToString(g_expiration_time, TIME_DATE | TIME_SECONDS), trigger);
   return(true);
}

//+------------------------------------------------------------------+
//| M30 gatekeeper — byte-faithful to v28 (one added paper gate)      |
//+------------------------------------------------------------------+
void EvaluateNewM30Bar(const datetime bar_open)
{
   g_last_gate_time = bar_open;
   g_last_macro = "UNKNOWN";
   g_last_trigger = "NONE";

   if(PositionsTotal() != 0 || g_pp_open)
   {
      g_last_gate = g_pp_open ? "BLOCKED: VIRTUAL POSITION EXISTS" : "BLOCKED: POSITION EXISTS";
      return;
   }

   int macro_direction = 0;
   string macro_description = "";
   if(!ReadMacroDirection(macro_direction, macro_description))
   {
      g_last_macro = macro_description;
      g_last_gate = "BLOCKED: DATA NOT READY";
      return;
   }
   g_last_macro = macro_description;
   if(macro_direction == 0 && InpStrategyMode != V28_TRIGGER_ONLY)
   {
      g_last_gate = "STAND DOWN: " + macro_description;
      return;
   }

   string trigger = "NONE";
   if(InpStrategyMode != V28_MACRO_ONLY)
   {
      if(!ReadM30Springboard(macro_direction, trigger))
      {
         g_last_gate = "BLOCKED: M30 DATA NOT READY";
         return;
      }
      g_last_trigger = trigger;
   }

   if(InpStrategyMode == V28_TRIGGER_ONLY)
   {
      if(StringFind(trigger, "BUY") >= 0)
         macro_direction = 1;
      else if(StringFind(trigger, "SELL") >= 0)
         macro_direction = -1;
      else
      {
         g_last_gate = "STAND DOWN: NO M30 TRIGGER";
         return;
      }
   }
   else if(InpStrategyMode != V28_MACRO_ONLY && trigger == "NONE")
   {
      g_last_gate = "STAND DOWN: NO M30 SPRINGBOARD";
      return;
   }

   if(InpStrategyMode == V28_LONG_ONLY)
   {
      if(macro_direction != 1)
      {
         g_last_gate = "STAND DOWN: LONG-ONLY";
         return;
      }
   }
   else if(InpStrategyMode == V28_SHORT_ONLY)
   {
      if(macro_direction != -1)
      {
         g_last_gate = "STAND DOWN: SHORT-ONLY";
         return;
      }
   }

   if(macro_direction > 0 && !InpAllowLong)
   {
      g_last_gate = "STAND DOWN: LONG DISABLED";
      return;
   }
   if(macro_direction < 0 && !InpAllowShort)
   {
      g_last_gate = "STAND DOWN: SHORT DISABLED";
      return;
   }

   double atr = 0.0;
   if(!ReadIndicator(g_h1_atr, 0, 1, atr) || atr <= 0.0)
   {
      g_last_gate = "BLOCKED: H1 ATR NOT READY";
      return;
   }
   if(OpenMacroTrade(macro_direction, atr, trigger))
      g_last_gate = "OPENED " + DirectionText(macro_direction);
}

void ProcessM30Gate()
{
   datetime current_bar = iTime(_Symbol, PERIOD_M30, 0);
   if(current_bar <= 0)
      return;
   if(g_last_m30_bar == 0)
   {
      g_last_m30_bar = current_bar;
      return;
   }
   if(current_bar == g_last_m30_bar)
      return;

   g_last_m30_bar = current_bar;
   EvaluateNewM30Bar(current_bar);
}

//+------------------------------------------------------------------+
//| Dashboard                                                         |
//+------------------------------------------------------------------+
string RemainingText()
{
   datetime exp = PaperActive() ? (g_pp_open ? g_expiration_time : 0) : g_expiration_time;
   if(!PaperActive() && (!g_has_active_trade || exp <= 0))
      return("--:--:--");
   if(PaperActive() && !g_pp_open)
      return("--:--:--");
   long remaining = (long)exp - (long)TimeCurrent();
   if(remaining < 0) remaining = 0;
   int hours = (int)(remaining / 3600);
   int minutes = (int)((remaining % 3600) / 60);
   int seconds = (int)(remaining % 60);
   return(StringFormat("%02d:%02d:%02d", hours, minutes, seconds));
}

void UpdateHud()
{
   if(!InpDrawHud)
   {
      Comment("");
      return;
   }
   double equity = PaperActive() ? PaperEquity() : AccountInfoDouble(ACCOUNT_EQUITY);
   string mode = InpLiveExecution ? "LIVE" : "PAPER";
   bool open = PaperActive() ? g_pp_open : g_has_active_trade;
   double ep = PaperActive() ? g_pp_entry : g_entry_price;
   string active = open
      ? DirectionText(PaperActive() ? g_pp_dir : g_position_direction) + " @ " + DoubleToString(ep, PriceDigits())
      : "NONE";
   Comment(
      "MITEMSHUB V75 MACRO ENGINE v" + APP_VERSION + (PaperActive() ? " (FORWARD/A2)" : "") + "\n",
      "Mode: " + mode + " | Symbol: " + _Symbol + (StringLen(InpArmTag) > 0 ? " | arm " + InpArmTag : "") + "\n",
      StringFormat("Equity: $%.2f | Session PnL: $%+.2f\n", equity, g_session_pnl),
      StringFormat("Cumulative performance: %+.3f R\n", g_cumulative_r),
      "Macro: " + g_last_macro + "\n",
      "Last gate: " + g_last_gate + "\n",
      "Active trade: " + active + " | Lifecycle remaining: " + RemainingText() + "\n",
      "M30 gate: " + (g_last_gate_time > 0
         ? TimeToString(g_last_gate_time, TIME_DATE | TIME_MINUTES) : "ARMING") +
      " | Trigger: " + g_last_trigger
   );
}

//+------------------------------------------------------------------+
//| Lifecycle                                                         |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskFraction <= 0.0 || InpRiskFraction > RISK_FRACTION_LIMIT)
   {
      PrintFormat(VersionTag() + "INIT FAILED: InpRiskFraction %.4f outside (0, %.2f]",
                  InpRiskFraction, RISK_FRACTION_LIMIT);
      return(INIT_FAILED);
   }
   if(InpStopATRMultiplier <= STOP_ATR_MIN || InpStopATRMultiplier > STOP_ATR_LIMIT)
   {
      PrintFormat(VersionTag() + "INIT FAILED: InpStopATRMultiplier %.3f outside (%.2f, %.2f]",
                  InpStopATRMultiplier, STOP_ATR_MIN, STOP_ATR_LIMIT);
      return(INIT_FAILED);
   }
   if(InpTargetATRMultiplier <= TARGET_ATR_MIN || InpTargetATRMultiplier > TARGET_ATR_LIMIT)
   {
      PrintFormat(VersionTag() + "INIT FAILED: InpTargetATRMultiplier %.3f outside (%.2f, %.2f]",
                  InpTargetATRMultiplier, TARGET_ATR_MIN, TARGET_ATR_LIMIT);
      return(INIT_FAILED);
   }
   if(InpMaxHoldMinutes < HOLD_MINUTES_MIN || InpMaxHoldMinutes > HOLD_MINUTES_LIMIT)
   {
      PrintFormat(VersionTag() + "INIT FAILED: InpMaxHoldMinutes %d outside [%d, %d]",
                  InpMaxHoldMinutes, HOLD_MINUTES_MIN, HOLD_MINUTES_LIMIT);
      return(INIT_FAILED);
   }

   if(!IsV75Symbol())
   {
      Print(VersionTag() + "REFUSED: attach this EA only to a Volatility 75 symbol");
      return(INIT_FAILED);
   }

   g_h4_ema = iMA(_Symbol, PERIOD_H4, MACRO_EMA_PERIOD, 0, MODE_EMA, PRICE_CLOSE);
   g_h1_ema = iMA(_Symbol, PERIOD_H1, MACRO_EMA_PERIOD, 0, MODE_EMA, PRICE_CLOSE);
   g_h1_atr = iATR(_Symbol, PERIOD_H1, ATR_PERIOD);
   g_m30_rsi = iRSI(_Symbol, PERIOD_M30, RSI_PERIOD, PRICE_CLOSE);
   g_m30_bands = iBands(_Symbol, PERIOD_M30, BOLLINGER_PERIOD, 0,
                        BOLLINGER_DEVIATIONS, PRICE_CLOSE);

   if(g_h4_ema == INVALID_HANDLE || g_h1_ema == INVALID_HANDLE ||
      g_h1_atr == INVALID_HANDLE || g_m30_rsi == INVALID_HANDLE ||
      g_m30_bands == INVALID_HANDLE)
   {
      Print(VersionTag() + "INIT FAILED: one or more native indicator handles could not be created");
      return(INIT_FAILED);
   }

   g_paper_active = !InpLiveExecution;
   ParseFleetMagics();
   if(g_paper_active)
   {
      PaperInit();
      PrintFormat(VersionTag() + "PAPER MODE: virtual equity $%.2f | fills at live spread x%.1f | NO real orders",
                  PaperEquity(), InpPaperSpreadMult);
   }

   ResetTestMetrics();
   BuildGlobalNames();
   LoadSessionState();
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   ulong ticket = 0;
   ulong identifier = 0;
   if(!g_paper_active && FindManagedPosition(ticket, identifier))
      CaptureManagedPosition(ticket, identifier);

   g_last_m30_bar = iTime(_Symbol, PERIOD_M30, 0);
   PrintFormat(VersionTag() + "MITEMSHUB V75 MACRO started | mode=%d | experiment=%s | gate=M30 "
               "| macro=H4+H1 EMA20 | trigger=M30 BB20/2 or RSI14 | risk=%.2f%% "
               "| SL=%.2fxH1 ATR14 | TP=%.2fxH1 ATR14 | timeout=%dmin | live=%s | paper=%s | arm=%s",
               (int)InpStrategyMode, InpExperimentTag, InpRiskFraction * 100.0,
               InpStopATRMultiplier, InpTargetATRMultiplier, InpMaxHoldMinutes,
               InpLiveExecution ? "true" : "false", g_paper_active ? "true" : "false",
               StringLen(InpArmTag) > 0 ? InpArmTag : "-");
   UpdateHud();
   return(INIT_SUCCEEDED);
}

double OnTester()
{
   double win_rate = g_test_trades > 0 ? (double)g_test_wins / (double)g_test_trades : 0.0;
   if(InpResearchLogging)
      PrintFormat(VersionTag() + "RESEARCH_RESULT tag=%s mode=%d mode_name=%s "
                  "trades=%d wins=%d losses=%d win_rate=%.2f%% test_pnl=%+.2f "
                  "test_R=%+.4f sl_exits=%d tp_exits=%d timeout_exits=%d "
                  "risk=%.4f sl_atr=%.2f tp_atr=%.2f hold_min=%d live=%s",
                  InpExperimentTag, (int)InpStrategyMode, ModeText((int)InpStrategyMode),
                  (int)g_test_trades, (int)g_test_wins, (int)g_test_losses,
                  win_rate * 100.0, g_test_pnl, g_test_r,
                  (int)g_test_sl_exits, (int)g_test_tp_exits, (int)g_test_timeout_exits,
                  InpRiskFraction, InpStopATRMultiplier, InpTargetATRMultiplier,
                  InpMaxHoldMinutes, InpLiveExecution ? "true" : "false");
   if(InpResearchLogging)
   {
      LogMfeSummary();
      LogRAccounting();
   }
   return(g_test_r);
}

void LogMfeSummary()
{
   if(g_test_trades <= 0)
      return;
   string reached = "";
   for(int mfe = 0; mfe < 6; mfe++)
      reached += StringFormat(" ge%.2fR=%d(%.1f%%)", MFE_GRID[mfe], (int)g_mfe_hits[mfe],
                              100.0 * (double)g_mfe_hits[mfe] / (double)g_test_trades);
   PrintFormat(VersionTag() + "MFE_SUMMARY trades=%d mean_peak_r=%.4f max_peak_r=%.4f%s",
               (int)g_test_trades, g_mfe_sum / (double)g_test_trades, g_mfe_max, reached);
}

void LogRAccounting()
{
   if(g_test_trades <= 0 || g_sum_risk <= 0.0)
      return;

   double mean_risk = g_sum_risk / (double)g_test_trades;
   double money_implied_r = g_test_pnl / mean_risk;
   double gap = g_test_r - money_implied_r;
   double deviation = 0.0;
   if(g_risk_min > 0.0)
      deviation = MathMax(MathAbs(1.0 / g_risk_min - 1.0 / mean_risk),
                          MathAbs(1.0 / g_risk_max - 1.0 / mean_risk));
   double bound = g_sum_abs_pnl * deviation;
   bool consistent = (MathAbs(gap) <= bound + 1e-9);
   double implied_risk = (g_test_r != 0.0) ? g_test_pnl / g_test_r : 0.0;

   PrintFormat(VersionTag() + "R_RECONCILE trades=%d mean_risk=%.2f risk_min=%.2f risk_max=%.2f "
               "ratio_sum_r=%+.4f money_implied_r=%+.4f gap=%+.4f dispersion_bound=%.4f "
               "consistent=%s net_pnl=%+.2f implied_risk_by_ratiosum=%.2f",
               (int)g_test_trades, mean_risk, g_risk_min, g_risk_max,
               g_test_r, money_implied_r, gap, bound,
               consistent ? "true" : "false", g_test_pnl, implied_risk);
   if(!consistent)
      PrintFormat(VersionTag() + "R_RECONCILE WARNING: money-implied R differs from the ratio sum "
                  "by %.4f, beyond the dispersion bound %.4f — a per-trade denominator is wrong; "
                  "check risk=/risk_src= on the CLOSE lines.", gap, bound);
}

void OnDeinit(const int reason)
{
   if(g_h4_ema != INVALID_HANDLE) IndicatorRelease(g_h4_ema);
   if(g_h1_ema != INVALID_HANDLE) IndicatorRelease(g_h1_ema);
   if(g_h1_atr != INVALID_HANDLE) IndicatorRelease(g_h1_atr);
   if(g_m30_rsi != INVALID_HANDLE) IndicatorRelease(g_m30_rsi);
   if(g_m30_bands != INVALID_HANDLE) IndicatorRelease(g_m30_bands);
   Comment("");
}

void OnTick()
{
   MaintainSessionDay();
   if(PaperActive() && g_pp_open)
      PaperCheckHardExits();               // per-tick mirror BEFORE anything else (v26.38)
   PollManagedPosition();
   TrackPeakExcursion();
   ManageTimeGuardian();
   UpdateHud();

   ProcessM30Gate();
}

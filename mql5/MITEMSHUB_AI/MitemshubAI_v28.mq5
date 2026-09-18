//+------------------------------------------------------------------+
//|                                             MitemshubAI.mq5      |
//|                  MITEMSHUB V75 MACRO ENGINE v28.00               |
//|                                                                  |
//| Disciplined directional engine for Deriv Volatility 75 Index.    |
//|                                                                  |
//| Operating contract                                                |
//|   * Entry evaluation happens only once, on the first tick of a   |
//|     newly opened M30 candle.                                     |
//|   * Direction requires the previous H4 and H1 closes to be on    |
//|     the same side of their respective 20 EMA.                    |
//|   * The previous M30 close/RSI is the only springboard trigger.   |
//|   * One account position maximum, 1% equity risk, H1 ATR exits.  |
//|   * Every tick is reserved for the 3-hour guardian, lightweight  |
//|     position-state polling, and HUD refresh.                     |
//|                                                                  |
//| The default is PAPER/OFF. Set InpLiveExecution=true only after   |
//| attaching and validating this exact binary and preset on the     |
//| intended V75 account.                                            |
//|                                                                  |
//| V28 adds RESEARCH ONLY controls. Mode 0 reproduces v27 exactly;   |
//| every other mode is a deterministic hypothesis for the Strategy   |
//| Tester. The EA never rewrites its own logic during live trading.  |
//| Promote nothing from a single backtest: use the in-sample /       |
//| walk-forward / out-of-sample protocol (see scripts/v28_research.py |
//| and mql5/MITEMSHUB_AI/V28_RESEARCH_PROTOCOL.md).                  |
//+------------------------------------------------------------------+
#define APP_VERSION "28.00"

#property copyright "MITEMSHUB AI"
#property version   APP_VERSION
#property strict

#include <Trade\Trade.mqh>

//--- baseline strategy geometry. These defaults preserve v27 behavior.
const int    MACRO_EMA_PERIOD       = 20;
const int    RSI_PERIOD              = 14;
const int    ATR_PERIOD              = 14;
const int    BOLLINGER_PERIOD       = 20;
const double BOLLINGER_DEVIATIONS   = 2.0;
const double TICK_VALUE_TOLERANCE    = 0.05;

//--- research guard rails. Values outside these bounds are rejected at init so
//--- an optimizer can never trade absurd geometry; the recommended search
//--- ranges (narrower than these limits) live in V28_RESEARCH_PROTOCOL.md.
const double RISK_FRACTION_LIMIT     = 0.10;   // hard ceiling: 10% of equity
const double STOP_ATR_MIN             = 0.25;
const double STOP_ATR_LIMIT           = 6.0;
const double TARGET_ATR_MIN           = 0.25;
const double TARGET_ATR_LIMIT         = 12.0;
const int    HOLD_MINUTES_MIN         = 15;
const int    HOLD_MINUTES_LIMIT       = 720;

//--- A position captured before its protective stops are visible reports SL=0,
//--- which makes a position-derived risk as large as the price itself. Such a
//--- value would render R incomparable between trades, so a derived risk is only
//--- trusted while it stays within this multiple of the planned risk.
const double RISK_PLAUSIBILITY_BOUND  = 5.0;

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group "=== V75 Macro Execution ==="
input bool   InpLiveExecution       = false; // Safety default: false suppresses all order submission
input long   InpMagic               = 7788075;
input int    InpMaxDeviationPoints  = 50;
input bool   InpDrawHud             = true;

//+------------------------------------------------------------------+
//| V28 strategy research controls                                   |
//| Each mode is a deterministic hypothesis. The EA never mutates     |
//| itself during live trading; use MT5 Strategy Tester optimization  |
//| to compare candidates, then validate survivors out-of-sample.     |
//+------------------------------------------------------------------+
enum ENUM_V28_STRATEGY_MODE
{
   V28_ORIGINAL = 0,              // v27-equivalent baseline
   V28_REVERSE_DIRECTION = 1,     // bullish macro -> SELL; bearish -> BUY
   V28_REVERSE_TRIGGER = 2,       // overbought/oversold trigger interpretation reversed
   V28_REVERSE_BOTH = 3,          // reverse macro direction + trigger
   V28_LONG_ONLY = 4,             // take BUY candidates only
   V28_SHORT_ONLY = 5,            // take SELL candidates only
   V28_MACRO_ONLY = 6,            // macro direction is signal; ignore M30 trigger gate
   V28_TRIGGER_ONLY = 7           // M30 trigger direction drives signal; ignore H4/H1 alignment
};

input group "=== V28 Research / Strategy Mutation ==="
input ENUM_V28_STRATEGY_MODE InpStrategyMode = V28_ORIGINAL;
input bool   InpResearchLogging      = true;  // emits experiment metadata to Journal/Tester log
input string InpExperimentTag        = "V28_BASELINE";
input bool   InpAllowLong            = true;
input bool   InpAllowShort           = true;
// v27 closed the position whenever the protective modify was rejected
// (Deriv answers 10016 when the requested SL/TP already equals the held one,
// which is the normal case here because the entry order already carried them).
// That defect meant v27 never held a position. Leave false for the corrected
// contract; set true to reproduce v27's behaviour byte-for-byte for audit.
input bool   InpLegacyV27ModifyClose = false;

input group "=== V28 Tunable Risk / Exit Geometry ==="
input double InpRiskFraction         = 0.01;  // default = 1% equity risk
input double InpStopATRMultiplier    = 2.0;
input double InpTargetATRMultiplier  = 4.0;
input int    InpMaxHoldMinutes      = 180;

//+------------------------------------------------------------------+
//| Runtime state                                                    |
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
double   g_risk_money = 0.0;          // R denominator for the active trade
ulong    g_risk_money_id = 0;         // position id the denominator belongs to
string   g_risk_money_src = "NONE";   // provenance, printed on every close
string   g_entry_trigger = "";

//--- session values are kept in terminal global variables so a chart
//--- re-attach does not erase the HUD's current-day accounting.
datetime g_session_day = 0;
double   g_session_pnl = 0.0;
double   g_cumulative_r = 0.0;
// Whole-run tester metrics. Unlike session values, these are NEVER reset at midnight.
double   g_test_pnl = 0.0;
double   g_test_r = 0.0;
long     g_test_trades = 0;
long     g_test_wins = 0;
long     g_test_losses = 0;
long     g_test_sl_exits = 0;
long     g_test_tp_exits = 0;
long     g_test_timeout_exits = 0;
// R-accounting reconciliation. Cumulative R is a SUM OF RATIOS, so it converts
// back to money only through the mean denominator, and those denominators
// legitimately disperse (equity drift + lot rounding). These accumulators let
// OnTester() report both figures and bound their difference, so a wrong
// per-trade denominator can never hide behind the arithmetic.
double   g_sum_risk = 0.0;        // sum of the per-trade R denominators
double   g_sum_abs_pnl = 0.0;     // sum of |pnl|, for the dispersion bound
double   g_risk_min = 0.0;        // tightest committed risk this run
double   g_risk_max = 0.0;        // widest committed risk this run
// Peak favourable excursion (MFE), in R, tracked tick-by-tick. The exit
// geometry question — "what would a tighter take-profit have captured?" —
// cannot be answered from realised outcomes, because a trade that times out
// reports only where it finished, never how far in front it ever was. g_peak_r
// is the best NON-NEGATIVE excursion seen while the trade was open (0.000 if it
// never went favourable), it is printed on every CLOSE line as peak_r, and the
// run summary counts how many trades cleared each MFE_GRID level.
const double MFE_GRID[6] = {0.25, 0.50, 0.75, 1.00, 1.50, 2.00};
double   g_peak_r = 0.0;
long     g_mfe_hits[6] = {0, 0, 0, 0, 0, 0};
double   g_mfe_sum = 0.0;
double   g_mfe_max = 0.0;
string   g_gv_prefix = "";

//+------------------------------------------------------------------+
//| Small utilities                                                  |
//+------------------------------------------------------------------+
string VersionTag()
{
   return("[v" + APP_VERSION + "] ");
}

// The Strategy Tester reuses terminal processes between passes, so anything
// cached in terminal global variables can leak across unrelated tester runs.
// Session state is therefore a live-chart convenience only; the whole-run
// metrics used by OnTester() are reset explicitly in OnInit().
bool IsTesterRun()
{
   return(MQLInfoInteger(MQL_TESTER) != 0);
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

//+------------------------------------------------------------------+
//| Broker geometry                                                  |
//+------------------------------------------------------------------+
// The V75 contract must not blindly trust a poisoned broker tick value.
// When it differs from tick_size * contract_size by more than 5%, the
// geometric identity is the sizing value, exactly as required by this EA.
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

// Reads one indicator value. Validity means *finite and not EMPTY_VALUE* only:
// RSI legitimately prints 0.0, so a non-positive read is NOT an error sentinel
// here. Callers that need positive geometry (EMA, ATR, Bollinger bands) check
// that themselves, which keeps the sentinel honest for every indicator.
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

bool ReadMacroDirection(int &direction, string &description)
{
   direction = 0;
   description = "NO TRADE";

   // Trigger-only research does not require H4/H1 macro data.
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
      h4_ema <= 0.0 || h1_ema <= 0.0)      // EMAs are positive geometry
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
      lower <= 0.0 || upper <= 0.0)        // bands are positive; RSI is 0..100
      return(false);

   bool oversold = (close <= lower) || (rsi <= 35.0);
   bool overbought = (close >= upper) || (rsi >= 65.0);
   bool strong_oversold = (close <= lower && rsi <= 35.0);
   bool strong_overbought = (close >= upper && rsi >= 65.0);

   // Trigger-only mode: use the natural directional interpretation.
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
      // Original BUY = oversold. Reversed BUY = overbought.
      if((!reverse_trigger && strong_oversold) || (reverse_trigger && strong_overbought))
         trigger = reverse_trigger ? "M30_REVERSED_BB_UPPER+RSI" : "M30_BB_LOWER+RSI";
      else if((!reverse_trigger && oversold) || (reverse_trigger && overbought))
         trigger = reverse_trigger ? "M30_REVERSED_EXTREME" : "M30_OVERSOLD_EXTREME";
   }
   else if(direction < 0)
   {
      // Original SELL = overbought. Reversed SELL = oversold.
      if((!reverse_trigger && strong_overbought) || (reverse_trigger && strong_oversold))
         trigger = reverse_trigger ? "M30_REVERSED_BB_LOWER+RSI" : "M30_BB_UPPER+RSI";
      else if((!reverse_trigger && overbought) || (reverse_trigger && oversold))
         trigger = reverse_trigger ? "M30_REVERSED_EXTREME" : "M30_OVERBOUGHT_EXTREME";
   }
   return(true);
}

//+------------------------------------------------------------------+
//| Session accounting                                               |
//+------------------------------------------------------------------+
void BuildGlobalNames()
{
   g_gv_prefix = StringFormat("MITEMSHUB_V75M_%I64d_%s", InpMagic, SafeSymbolKey());
}

void SaveSessionState()
{
   if(g_gv_prefix == "") return;
   if(IsTesterRun()) return;                 // never leak across tester passes
   GlobalVariableSet(g_gv_prefix + "_DAY", (double)g_session_day);
   GlobalVariableSet(g_gv_prefix + "_PNL", g_session_pnl);
   GlobalVariableSet(g_gv_prefix + "_R", g_cumulative_r);
}

void LoadSessionState()
{
   g_session_day = StartOfDay(TimeCurrent());
   g_session_pnl = 0.0;
   g_cumulative_r = 0.0;

   // A tester pass must never inherit another pass's session accounting.
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

// Whole-run metrics never reset at midnight and are reset once per pass here,
// so OnTester() always scores exactly this run.
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
//| Managed-position ownership and recovery                          |
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

// The planned risk of one trade: what the sizing decision committed, and the
// fallback denominator whenever a position-derived value cannot be trusted.
double IntendedRiskMoney()
{
   return(AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskFraction);
}

// Single owner of the R denominator. It is written once per trade — at entry,
// or once when a position is recovered — and never recomputed from live
// position state afterwards, so a close is always divided by the risk that was
// actually committed for that trade.
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

// | Adopting a position must never discard an unbooked close. The timeout
// | guardian and an M30 entry can land on the same tick (entries open at a bar
// | open and the hold window is an exact multiple of M30 bars), so a different
// | position id can appear while the previous trade is still tracked. That
// | trade is closed and must reach the counters; adopting on top of it would
// | erase its identity and silently drop its P&L from the whole-run totals.
void CaptureManagedPosition(const ulong ticket, const ulong identifier)
{
   if(!PositionSelectByTicket(ticket))
      return;

   if(g_has_active_trade && g_position_id != 0 && identifier != g_position_id)
   {
      RecoverClosedPosition();
      // History lag is bounded by the retry path; if the superseded trade is
      // still unbooked, clear it rather than carry its identity onto the new
      // position (a stale denominator would corrupt every later R value).
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
   g_peak_r = 0.0;      // per-trade excursion starts fresh with the position

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
      g_risk_money_id = identifier;      // bind the entry snapshot to this position
   g_missing_close_polls = 0;
}

// Called on every tick. This is intentionally an O(positions) ownership check,
// not a history scan. History is consulted only once the position disappears.
void PollManagedPosition()
{
   ulong ticket = 0;
   ulong identifier = 0;
   if(FindManagedPosition(ticket, identifier))
   {
      if(!g_has_active_trade)
      {
         CaptureManagedPosition(ticket, identifier);
         // A market request may be acknowledged before the position book is
         // visible. Re-anchor protection when polling discovers that fill so
         // SL/TP are still based on the actual execution price, not the
         // provisional quote used for the request.
         if(InpLiveExecution && g_active_atr > 0.0)
            ConfigureFilledPosition(g_active_atr);
      }
      else if(identifier != g_position_id)
      {
         // The tracked trade closed and a different position is already live.
         // Adopt through the single capture path, which books the closed trade
         // first instead of overwriting its identity.
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
//| Close bookkeeping                                                |
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

   // Divide by the risk committed for THIS trade. A denominator that is not
   // bound to this position belongs to another trade, so the planned risk is
   // the honest fallback and the substitution is logged, never hidden.
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
   // The exit fill itself can be the trade's best excursion, so fold realised R
   // in before the peak is recorded for this trade.
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
      // Manual/client closes commonly carry magic 0. Position identity is the
      // authoritative ownership key once a managed position was captured.
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

   // History can lag the position book by a tick or two. Retry a bounded
   // number of polls; then clear state rather than leaving a phantom guardian.
   g_missing_close_polls++;
   if(g_missing_close_polls >= 3)
   {
      Print(VersionTag() + "POSITION GONE without a matching close deal; "
            "clearing internal state conservatively");
      ClearActiveState();
   }
}

//+------------------------------------------------------------------+
//| Transaction callback is fast-path; polling above remains the      |
//| recovery contract for terminals/brokers that omit or delay it.   |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
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
   // A human close has DEAL_MAGIC=0; the captured position identifier still
   // proves that this closing deal belongs to the managed trade.
   if(g_position_id != 0)
   {
      if(position_id != g_position_id)
         return;
   }
   else if(deal_magic != InpMagic)
   {
      return;
   }

   // A partial close must not erase the active trade state. The next tick
   // polls the position and only finalizes after the last unit is gone.
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
      // The transaction can arrive before HistorySelect exposes the deal.
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

//+------------------------------------------------------------------+
//| Peak favourable excursion                                        |
//+------------------------------------------------------------------+
// Runs on every tick BEFORE the guardian, so the peak recorded is the peak that
// actually existed while the trade was open — not the peak that happened to
// survive to the close. Floating P&L is divided by the same R denominator the
// close accounting uses, so peak_r and R are directly comparable.
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

//+------------------------------------------------------------------+
//| Time guardian                                                    |
//+------------------------------------------------------------------+
void ManageTimeGuardian()
{
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
//| Risk and entry                                                   |
//+------------------------------------------------------------------+
bool CalculateVolume(const double entry, const double atr, double &volume, double &risk_money)
{
   volume = 0.0;
   risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskFraction;
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
   if(min_lot_risk > risk_money + 1e-8)
   {
      PrintFormat(VersionTag() + "ENTRY BLOCKED: broker minimum lot risks %.2f, "
                  "which exceeds configured %.2f%% equity risk %.2f", min_lot_risk, InpRiskFraction * 100.0, risk_money);
      return(false);
   }

   volume = NormalizeVolumeDown(risk_money / risk_per_lot);
   if(volume <= 0.0)
      return(false);
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
      // A rejected modify must NOT destroy a position that is already
      // protected: the broker may hold valid levels from the entry order even
      // when an identical modify is refused (Deriv's V75 rejects the exact-ATR
      // modify while holding the order's own stops). Verify what is actually
      // held before escalating, and only close a genuinely unprotected trade.
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
   if(PositionsTotal() != 0)
      return(false);
   if(!InpLiveExecution)
   {
      PrintFormat(VersionTag() + "PAPER/OFF signal: %s %s; no order submitted",
                  DirectionText(direction), trigger);
      g_last_gate = "SIGNAL (PAPER/OFF) " + DirectionText(direction) + " | " + InpExperimentTag;
      return(false);
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
   CommitTradeRisk(risk_money, 0, "ENTRY");   // bound to the position once captured
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
//| M30 gatekeeper                                                   |
//+------------------------------------------------------------------+
void EvaluateNewM30Bar(const datetime bar_open)
{
   g_last_gate_time = bar_open;
   g_last_macro = "UNKNOWN";
   g_last_trigger = "NONE";

   // This literal account-wide gate is intentionally first: exactly one
   // open trade means no second position can enter from this EA or a fleet.
   if(PositionsTotal() != 0)
   {
      g_last_gate = "BLOCKED: POSITION EXISTS";
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

   // Directional subset experiments. These are deliberately applied after
   // signal construction so they measure the same signal family, filtered
   // to one side only.
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

   // Directional permission switches. Both default to true, so the baseline
   // signal family is untouched; they exist so an experiment can restrict the
   // tradeable side (and so the optimizer cannot silently ignore them).
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
   OpenMacroTrade(macro_direction, atr, trigger);
}

void ProcessM30Gate()
{
   datetime current_bar = iTime(_Symbol, PERIOD_M30, 0);
   if(current_bar <= 0)
      return;
   if(g_last_m30_bar == 0)
   {
      // Attaching to a chart is not a new-candle signal. Arm the gate and
      // wait for the next actual M30 open.
      g_last_m30_bar = current_bar;
      return;
   }
   if(current_bar == g_last_m30_bar)
      return;

   g_last_m30_bar = current_bar;
   EvaluateNewM30Bar(current_bar);
}

//+------------------------------------------------------------------+
//| Dashboard                                                        |
//+------------------------------------------------------------------+
string RemainingText()
{
   if(!g_has_active_trade || g_expiration_time <= 0)
      return("--:--:--");
   long remaining = (long)g_expiration_time - (long)TimeCurrent();
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
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   string mode = InpLiveExecution ? "LIVE" : "PAPER/OFF";
   string active = g_has_active_trade
      ? DirectionText(g_position_direction) + " @ " + DoubleToString(g_entry_price, PriceDigits())
      : "NONE";
   Comment(
      "MITEMSHUB V75 MACRO ENGINE v" + APP_VERSION + "\n",
      "Mode: " + mode + " | Symbol: " + _Symbol + "\n",
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
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
int OnInit()
{
   // Bounded validation. An optimizer step outside these bounds must produce
   // an explicit refusal rather than a silently absurd trade plan.
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

   ResetTestMetrics();
   BuildGlobalNames();
   LoadSessionState();
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   // Recover an already-open managed position after a terminal/chart restart.
   ulong ticket = 0;
   ulong identifier = 0;
   if(FindManagedPosition(ticket, identifier))
      CaptureManagedPosition(ticket, identifier);

   g_last_m30_bar = iTime(_Symbol, PERIOD_M30, 0);
   PrintFormat(VersionTag() + "MITEMSHUB V75 MACRO started | mode=%d | experiment=%s | gate=M30 "
               "| macro=H4+H1 EMA20 | trigger=M30 BB20/2 or RSI14 | risk=%.2f%% "
               "| SL=%.2fxH1 ATR14 | TP=%.2fxH1 ATR14 | timeout=%dmin | live=%s",
               (int)InpStrategyMode, InpExperimentTag, InpRiskFraction * 100.0,
               InpStopATRMultiplier, InpTargetATRMultiplier, InpMaxHoldMinutes,
               InpLiveExecution ? "true" : "false");
   UpdateHud();
   return(INIT_SUCCEEDED);
}

double OnTester()
{
   // Whole-run score used by MT5 Strategy Tester optimization.
   // No daily/session reset is involved. Lower drawdown can be layered in
   // later through a custom fitness function; the first job is to compare
   // strategy hypotheses on identical data and identical execution rules.
   double win_rate = g_test_trades > 0 ? (double)g_test_wins / (double)g_test_trades : 0.0;
   // Single machine-readable line for the external research registry
   // (scripts/v28_research.py). The original keys are preserved; the added
   // fields carry the candidate identity and the exit-reason split, so a
   // result can never be attributed to the wrong geometry.
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

// Cumulative R is sum(pnl_i / risk_i) — the standard expectancy measure, and
// what OnTester() scores. It converts back to money only through the MEAN
// denominator: sum(pnl_i/risk_i) == sum(pnl)/mean_risk holds ONLY when every
// risk_i is identical. Equity drift and lot rounding move the committed risk by
// roughly +/-8%, which shifts the money-implied R by ~20% against the ratio sum
// with nothing wrong. So both figures are reported, together with the exact
// dispersion bound of their difference:
//     |sum pnl_i (1/risk_i - 1/mean_risk)| <= sum|pnl_i| * max_dev(1/risk)
// ratio_sum_r   -> compare candidates with this (it IS OnTester)
// money_implied_r -> convert R back to dollars with this
// How many trades cleared each level of the grid. A take-profit at level k can
// only ever be hit by a trade whose MFE reached k, so these counts ARE the
// achievable hit rate for that target on this entry sequence — no re-run
// needed to find out whether a tighter target is reachable, only to find out
// what it would have been worth.
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
   // These are the only every-tick responsibilities. No entry rules,
   // microstructure recorder, tick velocity model, or polling history loop
   // runs here.
   MaintainSessionDay();
   PollManagedPosition();
   TrackPeakExcursion();
   ManageTimeGuardian();
   UpdateHud();

   // All structural analysis and signal generation is behind this M30 gate.
   ProcessM30Gate();
}
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//|                                             MitemshubAI.mq5      |
//|                  MITEMSHUB V75 MACRO ENGINE v27.00               |
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
//+------------------------------------------------------------------+
#define APP_VERSION "27.00"

#property copyright "MITEMSHUB AI"
#property version   APP_VERSION
#property strict

#include <Trade\Trade.mqh>

//--- immutable strategy geometry
const int    MACRO_EMA_PERIOD       = 20;
const int    RSI_PERIOD              = 14;
const int    ATR_PERIOD              = 14;
const int    BOLLINGER_PERIOD       = 20;
const double BOLLINGER_DEVIATIONS   = 2.0;
const double RSI_BUY_LEVEL           = 35.0;
const double RSI_SELL_LEVEL          = 65.0;
const double H1_ATR_STOP_MULT        = 2.0;
const double H1_ATR_TARGET_MULT      = 4.0;
const double RISK_FRACTION           = 0.01;
const int    MAX_HOLD_SECONDS        = 3 * 60 * 60;
const double TICK_VALUE_TOLERANCE    = 0.05;

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group "=== V75 Macro Execution ==="
input bool   InpLiveExecution       = false; // Safety default: false suppresses all order submission
input long   InpMagic               = 7788075;
input int    InpMaxDeviationPoints  = 50;
input bool   InpDrawHud             = true;

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
double   g_risk_money = 0.0;
string   g_entry_trigger = "";

//--- session values are kept in terminal global variables so a chart
//--- re-attach does not erase the HUD's current-day accounting.
datetime g_session_day = 0;
double   g_session_pnl = 0.0;
double   g_cumulative_r = 0.0;
string   g_gv_prefix = "";

//+------------------------------------------------------------------+
//| Small utilities                                                  |
//+------------------------------------------------------------------+
string VersionTag()
{
   return("[v" + APP_VERSION + "] ");
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

bool ReadIndicator(const int handle, const int buffer, const int shift, double &value)
{
   value = 0.0;
   if(handle == INVALID_HANDLE || BarsCalculated(handle) < shift + 1)
      return(false);
   double values[1];
   ResetLastError();
   if(CopyBuffer(handle, buffer, shift, 1, values) != 1)
      return(false);
   if(!MathIsValidNumber(values[0]) || values[0] <= 0.0)
      return(false);
   value = values[0];
   return(true);
}

bool ReadMacroDirection(int &direction, string &description)
{
   direction = 0;
   description = "NO TRADE";
   double h4_close = iClose(_Symbol, PERIOD_H4, 1);
   double h1_close = iClose(_Symbol, PERIOD_H1, 1);
   double h4_ema = 0.0;
   double h1_ema = 0.0;
   if(h4_close <= 0.0 || h1_close <= 0.0 ||
      !ReadIndicator(g_h4_ema, 0, 1, h4_ema) ||
      !ReadIndicator(g_h1_ema, 0, 1, h1_ema))
   {
      description = "DATA NOT READY";
      return(false);
   }

   bool h4_up = h4_close > h4_ema;
   bool h4_down = h4_close < h4_ema;
   bool h1_up = h1_close > h1_ema;
   bool h1_down = h1_close < h1_ema;

   if(h4_up && h1_up)
   {
      direction = 1;
      description = "ALIGNED UP (H4/H1)";
   }
   else if(h4_down && h1_down)
   {
      direction = -1;
      description = "ALIGNED DOWN (H4/H1)";
   }
   else if((h4_up && h1_down) || (h4_down && h1_up))
   {
      description = "DIVERGENT H4/H1";
   }
   else
   {
      description = "H4/H1 EMA NEUTRAL";
   }
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
      !ReadIndicator(g_m30_rsi, 0, 1, rsi))
      return(false);

   if(direction > 0)
   {
      bool band_touch = close <= lower;
      bool rsi_trigger = rsi <= RSI_BUY_LEVEL;
      if(band_touch && rsi_trigger) trigger = "M30_BB_LOWER+RSI";
      else if(band_touch) trigger = "M30_BB_LOWER";
      else if(rsi_trigger) trigger = "M30_RSI<=35";
   }
   else if(direction < 0)
   {
      bool band_touch = close >= upper;
      bool rsi_trigger = rsi >= RSI_SELL_LEVEL;
      if(band_touch && rsi_trigger) trigger = "M30_BB_UPPER+RSI";
      else if(band_touch) trigger = "M30_BB_UPPER";
      else if(rsi_trigger) trigger = "M30_RSI>=65";
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
   GlobalVariableSet(g_gv_prefix + "_DAY", (double)g_session_day);
   GlobalVariableSet(g_gv_prefix + "_PNL", g_session_pnl);
   GlobalVariableSet(g_gv_prefix + "_R", g_cumulative_r);
}

void LoadSessionState()
{
   g_session_day = StartOfDay(TimeCurrent());
   g_session_pnl = 0.0;
   g_cumulative_r = 0.0;

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
   g_risk_money = 0.0;
   g_entry_trigger = "";
}

void CaptureManagedPosition(const ulong ticket, const ulong identifier)
{
   if(!PositionSelectByTicket(ticket))
      return;

   g_has_active_trade = true;
   g_position_ticket = ticket;
   g_position_id = identifier;
   g_position_direction = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
   g_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   g_active_sl = PositionGetDouble(POSITION_SL);
   g_active_tp = PositionGetDouble(POSITION_TP);
   g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
   if(g_entry_time <= 0) g_entry_time = TimeCurrent();
   g_expiration_time = g_entry_time + MAX_HOLD_SECONDS;

   if(g_active_atr <= 0.0 && g_active_sl > 0.0)
      g_active_atr = MathAbs(g_entry_price - g_active_sl) / H1_ATR_STOP_MULT;
   if(g_active_atr <= 0.0)
      ReadIndicator(g_h1_atr, 0, 1, g_active_atr);

   if(g_risk_money <= 0.0)
   {
      double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = CalibratedTickValue();
      double volume = PositionGetDouble(POSITION_VOLUME);
      double stop_distance = MathAbs(g_entry_price - g_active_sl);
      if(tick_size > 0.0 && tick_value > 0.0 && volume > 0.0 && stop_distance > 0.0)
         g_risk_money = (stop_distance / tick_size) * tick_value * volume;
      if(g_risk_money <= 0.0)
         g_risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * RISK_FRACTION;
   }
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

   double realized_r = 0.0;
   if(g_risk_money > 0.0)
      realized_r = pnl / g_risk_money;
   g_session_pnl += pnl;
   g_cumulative_r += realized_r;
   SaveSessionState();

   PrintFormat(VersionTag() + "CLOSE %s ticket=%I64u pnl=%+.2f R=%+.3f exit=%.5f "
               "hold=%d sec", reason, g_position_ticket, pnl, realized_r,
               exit_price, g_entry_time > 0 ? (int)(TimeCurrent() - g_entry_time) : 0);
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
      PrintFormat(VersionTag() + "3-HOUR TIMEOUT LIQUIDATION requested: ticket=%I64u",
                  g_position_ticket);
   }
}

//+------------------------------------------------------------------+
//| Risk and entry                                                   |
//+------------------------------------------------------------------+
bool CalculateVolume(const double entry, const double atr, double &volume, double &risk_money)
{
   volume = 0.0;
   risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * RISK_FRACTION;
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = CalibratedTickValue();
   if(entry <= 0.0 || atr <= 0.0 || tick_size <= 0.0 || tick_value <= 0.0 || risk_money <= 0.0)
      return(false);

   double stop_distance = H1_ATR_STOP_MULT * atr;
   double risk_per_lot = (stop_distance / tick_size) * tick_value;
   if(risk_per_lot <= 0.0)
      return(false);

   double min_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double min_lot_risk = risk_per_lot * min_volume;
   if(min_lot_risk > risk_money + 1e-8)
   {
      PrintFormat(VersionTag() + "ENTRY BLOCKED: broker minimum lot risks %.2f, "
                  "which exceeds exact 1%% equity risk %.2f", min_lot_risk, risk_money);
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
   double sl = direction > 0 ? actual_entry - H1_ATR_STOP_MULT * atr
                              : actual_entry + H1_ATR_STOP_MULT * atr;
   double tp = direction > 0 ? actual_entry + H1_ATR_TARGET_MULT * atr
                              : actual_entry - H1_ATR_TARGET_MULT * atr;
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
      PrintFormat(VersionTag() + "EXACT ATR PROTECTION FAILED: retcode=%u %s; closing",
                  trade.ResultRetcode(), trade.ResultRetcodeDescription());
      trade.PositionClose(g_position_ticket, InpMaxDeviationPoints);
      return(false);
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
      g_last_gate = "SIGNAL (PAPER/OFF) " + DirectionText(direction);
      return(false);
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return(false);
   double entry = direction > 0 ? tick.ask : tick.bid;
   double provisional_sl = direction > 0 ? entry - H1_ATR_STOP_MULT * atr
                                         : entry + H1_ATR_STOP_MULT * atr;
   double provisional_tp = direction > 0 ? entry + H1_ATR_TARGET_MULT * atr
                                         : entry - H1_ATR_TARGET_MULT * atr;
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
   g_risk_money = risk_money;
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
      g_risk_money = 0.0;
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
               "risk=$%.2f expiry=%s trigger=%s",
               DirectionText(direction), PositionGetDouble(POSITION_VOLUME),
               g_entry_price, g_active_sl, g_active_tp, g_risk_money,
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
   if(macro_direction == 0)
   {
      g_last_gate = "STAND DOWN: " + macro_description;
      return;
   }

   string trigger = "NONE";
   if(!ReadM30Springboard(macro_direction, trigger))
   {
      g_last_gate = "BLOCKED: M30 DATA NOT READY";
      return;
   }
   g_last_trigger = trigger;
   if(trigger == "NONE")
   {
      g_last_gate = "STAND DOWN: NO M30 SPRINGBOARD";
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
   PrintFormat(VersionTag() + "MITEMSHUB V75 MACRO started | gate=M30 | macro=H4+H1 "
               "EMA20 | trigger=M30 BB20/2 or RSI14 | risk=1%% | SL=2xH1 ATR14 "
               "TP=4xH1 ATR14 | timeout=3h | live=%s",
               InpLiveExecution ? "true" : "false");
   UpdateHud();
   return(INIT_SUCCEEDED);
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
   ManageTimeGuardian();
   UpdateHud();

   // All structural analysis and signal generation is behind this M30 gate.
   ProcessM30Gate();
}
//+------------------------------------------------------------------+

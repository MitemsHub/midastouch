//+------------------------------------------------------------------+
//|                                                V75MacroEngine.mq5 |
//|        Macro-Directional Inference Engine - Volatility 75 (V75)  |
//|                                                                  |
//|  ARCHITECTURE (v2.00 - spec-pure):                               |
//|   1. M30 New-Candle Gatekeeper: all rules run ONLY at the open   |
//|      of a new M30 bar. OnTick() otherwise does nothing but the   |
//|      per-tick guardians (timeout + state reconciliation).        |
//|   2. Multi-timeframe macro alignment: H4 and H1 20-EMA regimes   |
//|      on CLOSED bars must agree, otherwise the engine stands down.|
//|   3. M30 springboard: mean-reversion entry trigger against the   |
//|      macro direction (Bollinger Band touch/pierce OR RSI gate).  |
//|      LONG-ONLY (v2.10): the sell leg is disabled - measured      |
//|      evidence shows it carries no edge and bleeds in every exit  |
//|      geometry (see header note below).                           |
//|   4. Risk: 1% of equity, SL = 2.0x H1 ATR, TP = 4.0x H1 ATR      |
//|      (strict 1:2), tick-value calibration safety check.          |
//|   5. Hard timeout: force-closes the position at market           |
//|      v2.20: 2h (was 3h) - re-derived from the buy-side MFE/MAE   |
//|      distribution on the 75 real long-only entries: TP left at   |
//|      spec 4x ATR, but liquidating at 2h cuts SL hits 6 -> 2 and  |
//|      lifts offline R-sum +7.84 -> +10.14 (see                    |
//|      artifacts/.../exit_rederivation_20260914.txt).              |
//|      when the lifecycle expires, on every tick.                  |
//|   6. Self-contained: only native MQL5 includes (Trade.mqh).      |
//|   7. PAPER MODE (v2.21, InpPaperMode=true): arm-C machinery -     |
//|      virtual fills at bid/ask, virtual equity ($50 floor), no     |
//|      broker order is ever sent; ledger + telemetry in MQL5\Files  |
//|      in the format morning_status/ab_adjudicate already parse.    |
//|                                                                  |
//|  v2.10 WHY LONG-ONLY (31-month real-tick evidence, Mar 2024 -    |
//|  Sep 2026, identical window across five exit variants):          |
//|   * Spec exits: BUYS +747.55 (PF 1.56) vs SELLS -1,080.86 (PF    |
//|     0.62). Sells lose under every exit geometry tested and the   |
//|     deficit grows yearly (+69 / -481 / -669 by year).            |
//|   * Entry-drift stats: the buy signal lifts the one-bar          |
//|     directional hit rate 50.7% -> 62.7%; the sell signal is      |
//|     statistically indistinguishable from no signal (54.3% vs     |
//|     51.9% base, negative mean drift).                            |
//|   * 4x-ATR TP was hit 0 times in 167 spec trades (max MFE 1.81R  |
//|     vs the 2.0R target): the sell arm's R:R never materializes.  |
//+------------------------------------------------------------------+
#property copyright   "Algorithmic Trading Engine"
#property link        ""
#property version     "2.22"
#property description "V75 Macro-Directional Inference Engine"
#property description "H4/H1 EMA alignment + M30 springboard + 1:2 ATR geometry"
#property description "Strict 2h timeout - single position - 1% equity risk"
#property description "v2.10 LONG-ONLY: sell leg disabled on 31-month evidence"
#property description "v2.21 PAPER MODE: arm-C machinery (virtual fills, ledger, telemetry)"
#property description "v2.22 ledger schema fix: OPEN rows = arms' exact 12-field schema, real SL/TP"
#property description "v2.24 ledger era tag: idempotent ERA provenance row in the paper ledger"

//--- The engine version as a single macro: the OnInit banner (which the
//    morning_status canary greps as run identity) and any future version
//    checks must never drift from #property version again.
#define ENGINE_VERSION "2.24"

// Native MQL5 trading library only - no custom includes
#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| FIXED ENGINE CONSTANTS (spec-exact - deliberately not inputs)     |
//+------------------------------------------------------------------+
#define SL_ATR_MULTIPLE   2.0          // SL = exactly 2.0x H1 ATR(14)
#define TIMEOUT_SECONDS   (2 * 3600)   // hard timeout = exactly 2h (v2.20, re-derived)
#define SLIPPAGE_POINTS   10           // max deviation (points)
#define PAPER_START_EQUITY 50.0        // arm machinery: virtual equity floor (arms A/B started at $50)

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
input group "--- Time & Execution Settings ---"
input int    InpMagicNumber        = 7500;    // Magic number for trade identification

input group "--- Indicator Parameters ---"
input int    InpH4EMAPeriod        = 20;      // H4 trend EMA period
input int    InpH1EMAPeriod        = 20;      // H1 trend EMA period
input int    InpBBPeriod           = 20;      // M30 Bollinger Bands period
input double InpBBDeviation        = 2.0;     // M30 Bollinger Bands deviation
input int    InpRSIPeriod          = 14;      // M30 RSI period
input double InpRSIBuyLevel        = 35.0;    // M30 RSI oversold trigger (uptrend pullback)
input int    InpATRPeriod          = 14;      // H1 ATR period (noise isolation)

input group "--- Risk & Reward Profile ---"
input double InpRiskPercent        = 1.0;     // Risk per trade as % of account equity
input double InpRRMultiplier       = 2.0;     // Reward:Risk ratio (TP = RR x SL distance)

input group "--- Safety Checks ---"
input bool   InpEnableTickSafety   = true;    // Tick-value calibration safety check

input group "--- Paper Mode (arm-C machinery) ---"
input bool   InpPaperMode          = false;   // PAPER: virtual fills, no broker orders

//+------------------------------------------------------------------+
//| ENUMS                                                             |
//+------------------------------------------------------------------+
enum ENUM_MACROTREND
{
   MACROTREND_NONE,           // No alignment or diverged
   MACROTREND_ALIGNED_UP,     // H4 up + H1 up
   MACROTREND_ALIGNED_DOWN    // H4 down + H1 down
};

enum ENUM_ENTRY_SIGNAL
{
   ENTRY_NONE,
   ENTRY_BUY                  // Deep pullback in aligned uptrend (long-only v2.10)
};

//+------------------------------------------------------------------+
//| STATE OWNERSHIP MAP                                               |
//|   Broker pool (symbol+magic)   -> single owner of "is a trade on" |
//|   g_ticket                     -> mirrors the broker ticket       |
//|   g_entryTime/g_entryPrice/... -> trade context, torn down in ONE |
//|                                    place (ResetTradeState)        |
//|   SyncPositionState() is the ONLY function that promotes a       |
//|   position sighting into state and the ONLY one that retires it. |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_symbol = NULL;
int      g_magic  = 0;

//--- trade lifecycle. SINGLE SOURCE OF TRUTH: g_ticket mirrors the live
//    position (0 = flat, >0 = managed ticket) and is promoted/retired
//    ONLY by SyncPositionState. Every in-position decision reads it.
ulong    g_ticket       = 0;      // broker ticket of the managed position
datetime g_entryTime    = 0;      // adoption/execution time (timeout anchor)
datetime g_expireTime   = 0;      // g_entryTime + 2h - the hard deadline
double   g_entryPrice   = 0;
double   g_riskAmount   = 0;      // equity risk staged at execution
double   g_atrValue     = 0;      // H1 ATR captured at execution

//--- HUD narrative. Single writer: SetStatus(). Rendered by UpdateDashboard.
string   g_entryStatus  = "Initializing";

//+------------------------------------------------------------------+
//| Single writer of the HUD status narrative                         |
//+------------------------------------------------------------------+
void SetStatus(string status)
{
   g_entryStatus = status;
}

//+------------------------------------------------------------------+
//| In-position read: the one owner (the mirrored live ticket)       |
//+------------------------------------------------------------------+
bool InPosition()
{
   return (g_ticket != 0);
}

//--- session performance (owned by OnInit / OnTradeTransaction)
double   g_startEquity    = 0;
double   g_cumulativeR    = 0;
int      g_tradesExecuted = 0;

//--- paper book (v2.21). Virtual equity is the paper account; geometry
//    mirrors the live fields so every rule reads identically in both modes.
double   g_paperEquity  = PAPER_START_EQUITY;
int      g_paperDir     = 0;      // +1 buy / -1 sell (paper open trade)
double   g_paperVolume  = 0;
double   g_paperSL      = 0;
double   g_paperTP      = 0;

//--- indicator handles (owned by OnInit / OnDeinit)
int g_handleH4EMA = INVALID_HANDLE;
int g_handleH1EMA = INVALID_HANDLE;
int g_handleBB    = INVALID_HANDLE;
int g_handleRSI   = INVALID_HANDLE;
int g_handleATR   = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(SLIPPAGE_POINTS);
   trade.SetTypeFillingBySymbol(_Symbol);

   g_symbol = _Symbol;
   g_magic  = InpMagicNumber;

   //--- Session baseline for the HUD's Session PnL line
   g_startEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   //--- Indicator handles (each timeframe owns its own handle)
   g_handleH4EMA = iMA(g_symbol, PERIOD_H4, InpH4EMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_handleH1EMA = iMA(g_symbol, PERIOD_H1, InpH1EMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_handleBB    = iBands(g_symbol, PERIOD_M30, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);
   g_handleRSI   = iRSI(g_symbol, PERIOD_M30, InpRSIPeriod, PRICE_CLOSE);
   g_handleATR   = iATR(g_symbol, PERIOD_H1, InpATRPeriod);

   if(g_handleH4EMA == INVALID_HANDLE || g_handleH1EMA == INVALID_HANDLE ||
      g_handleBB    == INVALID_HANDLE || g_handleRSI   == INVALID_HANDLE ||
      g_handleATR   == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create one or more indicator handles");
      return INIT_FAILED;
   }

   //--- Warm-up guard: refuse to run against thin history. 2*period bars
   //    per series is the minimum for stable EMA/RSI/ATR initialization.
   int minBars = 2 * MathMax(InpH4EMAPeriod, MathMax(InpBBPeriod, InpATRPeriod)) + 10;
   if(Bars(g_symbol, PERIOD_H4) < minBars ||
      Bars(g_symbol, PERIOD_H1) < minBars ||
      Bars(g_symbol, PERIOD_M30) < minBars)
   {
      Print("WARNING: Insufficient history for indicator warm-up (need ~",
            minBars, " bars per timeframe). Signals suppressed until history loads.");
   }

   //--- Informational tick-value validation at init (the functional
   //    overwrite with the geometric identity happens in CalculateLotSize)
   if(InpEnableTickSafety)
   {
      ValidateTickValue();
   }

   SetStatus("Initialized - waiting for first M30 gate");
   Print("V75 Macro Engine v" + ENGINE_VERSION + " initialized (LONG-ONLY, 2h timeout, ",
         InpPaperMode ? "PAPER" : "LIVE-EXECUTION", ")");
   if(InpPaperMode)
   {
      Print("  PAPER MODE: virtual fills only - no broker orders will be sent");
      Print("  Virtual equity starts at $", DoubleToString(g_paperEquity, 2),
            " | ledger + telemetry: MQL5\\Files\\V75MacroEngine_paper_*");
      //--- v2.24: era provenance stamp - idempotent (readers keep the first).
      //    This engine has ALWAYS filled paper exits per tick (PaperCheckExits
      //    runs before the M30 gatekeeper), so the stamp declares pertick-fills
      //    regardless of the frozen MitemshubAI boundary; scripts/era.py keys
      //    the rule per engine family. Placed before the first possible exit.
      PaperAppendLedger("ERA," + ENGINE_VERSION + ",1789494700,pertick-fills");   // boundary = 2026-09-15 17:51:40 UTC (mid-silence)
      Print("  PAPER ledger era stamp: ", ENGINE_VERSION,
            " (per-tick fills; arm C exits were never bar-open)");
   }
   Print("  Symbol: ", g_symbol, " | Magic: ", g_magic);
   Print("  Risk: ", InpRiskPercent, "% equity | SL: ", SL_ATR_MULTIPLE,
         "x H1 ATR | TP: ", SL_ATR_MULTIPLE * InpRRMultiplier, "x H1 ATR (1:",
         DoubleToString(InpRRMultiplier, 0), ")");
   Print("  Timeout: 2h | Springboard: BB(",
         InpBBPeriod, ",", DoubleToString(InpBBDeviation, 1), ") or RSI(",
         InpRSIPeriod, ") <= ", DoubleToString(InpRSIBuyLevel, 1),
         " | sell leg disabled (long-only)");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_handleH4EMA != INVALID_HANDLE) IndicatorRelease(g_handleH4EMA);
   if(g_handleH1EMA != INVALID_HANDLE) IndicatorRelease(g_handleH1EMA);
   if(g_handleBB    != INVALID_HANDLE) IndicatorRelease(g_handleBB);
   if(g_handleRSI   != INVALID_HANDLE) IndicatorRelease(g_handleRSI);
   if(g_handleATR   != INVALID_HANDLE) IndicatorRelease(g_handleATR);

   Comment("");   // Clear the dashboard from the chart
   Print("V75 Macro Engine deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function - MAIN ENTRY POINT                           |
//|                                                                   |
//| Per-tick work: ONLY the guardians (timeout + state sync + HUD).   |
//| All rule computation is behind the M30 New-Candle Gatekeeper.     |
//+------------------------------------------------------------------+
void OnTick()
{
   //--- 1. Per-tick guardians (spec 5). Paper mode swaps the broker pool for
   //    the virtual book; every other rule reads identically in both modes.
   if(InpPaperMode)
   {
      PaperCheckExits();       // virtual SL/TP fills (bid/ask, conservative)
      PaperCheckTimeout();     // 2h hard timeout -> virtual liquidation
   }
   else
   {
      SyncPositionState();     // broker-truth reconciliation + state teardown
      CheckTradeTimeout();     // 2h hard timeout -> market liquidation
   }

   //--- 2. M30 New Candle Gatekeeper (spec 1)
   //    All structural checks and entry signals run ONLY at the exact
   //    opening second of a new M30 candle.
   if(!IsNewM30Candle())
   {
      UpdateDashboard();
      return;
   }

   //--- We are at the opening second of a new M30 candle -------------

   //--- Paper telemetry: heartbeat at EVERY M30 open, before any stand-down
   //    return - watchdog freshness must not depend on the regime.
   if(InpPaperMode)
   {
      PaperWriteTelemetry("hb");
   }

   //--- 3. Multi-timeframe directional macro alignment (spec 2)
   ENUM_MACROTREND macroTrend = GetMacroTrendAlignment();

   if(macroTrend == MACROTREND_NONE)
   {
      SetStatus("H4/H1 diverged - standing down");
      UpdateDashboard();
      return;
   }

   //--- v2.10 LONG-ONLY: aligned-DOWN regimes stand down entirely.
   if(macroTrend == MACROTREND_ALIGNED_DOWN)
   {
      SetStatus("Macro DOWN - sell leg disabled (long-only build)");
      UpdateDashboard();
      return;
   }

   //--- 4. Position gate: strictly ONE position at any time (spec 4)
   if(!CanEnterTrade())
   {
      SetStatus("Entry blocked - position already open");
      UpdateDashboard();
      return;
   }

   //--- 5. M30 structural springboard trigger (spec 3)
   ENUM_ENTRY_SIGNAL signal = GetM30EntrySignal(macroTrend);

   //--- Paper telemetry: the trigger evaluation is the decision content of
   //    the bar (signal fires or explicitly does not) - log it either way.
   if(InpPaperMode)
   {
      PaperWriteTelemetry("sig", signal == ENTRY_BUY);
   }

   if(signal == ENTRY_NONE)
   {
      SetStatus(StringFormat("Macro %s - waiting for M30 springboard",
                             macroTrend == MACROTREND_ALIGNED_UP ? "UP" : "DOWN"));
      UpdateDashboard();
      return;
   }

   //--- 6. Execute with dynamic risk management (spec 4)
   if(InpPaperMode)
   {
      PaperOpenTrade(signal);   // virtual fill - no broker order is ever sent
   }
   else
   {
      ExecuteTrade(signal);
   }

   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| M30 New Candle Gatekeeper                                         |
//| Compares the current M30 bar-open time against the last seen one. |
//| Returns true exactly once per bar (first tick of the new bar).    |
//| Cold-attach safe: the current bar is adopted on the first call    |
//| after attach/reconnect, so no signal can fire on that first tick. |
//+------------------------------------------------------------------+
bool IsNewM30Candle()
{
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(g_symbol, PERIOD_M30, 0);

   if(lastBarTime == 0)
   {
      lastBarTime = currentBarTime;   // adopt current bar - no signal on first tick
      return false;
   }

   if(currentBarTime != lastBarTime)
   {
      lastBarTime = currentBarTime;
      return true;                    // new M30 candle has opened
   }
   return false;
}

//+------------------------------------------------------------------+
//| Multi-timeframe directional macro alignment (spec 2)              |
//| Structural reads use CLOSED bars only (shift 1 = previous bar).   |
//|   Aligned UP  : prev H4 close > H4 EMA20 AND prev H1 close > H1 EMA20 |
//|   Aligned DOWN: prev H4 close < H4 EMA20 AND prev H1 close < H1 EMA20 |
//|   Anything else (divergence / equal) -> MACROTREND_NONE = stand down |
//+------------------------------------------------------------------+
ENUM_MACROTREND GetMacroTrendAlignment()
{
   //--- H4: previous candle close vs EMA (both shift 1)
   double h4Close = iClose(g_symbol, PERIOD_H4, 1);
   double h4EMA   = ReadBuffer(g_handleH4EMA, 1);
   if(h4Close <= 0 || h4EMA == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read H4 close/EMA - standing down");
      return MACROTREND_NONE;
   }

   //--- H1: previous candle close vs EMA (both shift 1)
   double h1Close = iClose(g_symbol, PERIOD_H1, 1);
   double h1EMA   = ReadBuffer(g_handleH1EMA, 1);
   if(h1Close <= 0 || h1EMA == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read H1 close/EMA - standing down");
      return MACROTREND_NONE;
   }

   bool h4Up = (h4Close > h4EMA);
   bool h1Up = (h1Close > h1EMA);

   if(h4Up && h1Up)
   {
      Print("MACRO: Aligned UPTREND  (H4 ", DoubleToString(h4Close, _Digits),
            " > EMA ", DoubleToString(h4EMA, _Digits),
            " | H1 ", DoubleToString(h1Close, _Digits),
            " > EMA ", DoubleToString(h1EMA, _Digits), ")");
      return MACROTREND_ALIGNED_UP;
   }

   if(!h4Up && !h1Up)
   {
      Print("MACRO: Aligned DOWNTREND (H4 ", DoubleToString(h4Close, _Digits),
            " < EMA ", DoubleToString(h4EMA, _Digits),
            " | H1 ", DoubleToString(h1Close, _Digits),
            " < EMA ", DoubleToString(h1EMA, _Digits), ")");
      return MACROTREND_ALIGNED_DOWN;
   }

   //--- Divergence: H4 and H1 disagree - stand down immediately
   Print("MACRO: DIVERGENCE - H4 ", h4Up ? "UP" : "DOWN",
         " vs H1 ", h1Up ? "UP" : "DOWN", " -> standing down");
   return MACROTREND_NONE;
}

//+------------------------------------------------------------------+
//| M30 structural entry trigger - The Springboard (spec 3)           |
//| Signal bar = previous CLOSED M30 candle (shift 1).                |
//|   Aligned UP : BUY when prev M30 close <= lower BB OR RSI <= 35   |
//|   v2.10 LONG-ONLY: the Aligned-DOWN sell trigger is removed       |
//|   (down-regimes stand down in OnTick before this is reached).     |
//+------------------------------------------------------------------+
ENUM_ENTRY_SIGNAL GetM30EntrySignal(ENUM_MACROTREND macroTrend)
{
   //--- Previous CLOSED M30 candle close
   double m30Close = iClose(g_symbol, PERIOD_M30, 1);
   if(m30Close <= 0)
   {
      Print("ERROR: Cannot read M30 close price");
      return ENTRY_NONE;
   }

   //--- Bollinger Bands on the same closed bar.
   //    iBands buffers: 0 = middle(base), 1 = UPPER, 2 = LOWER
   double bbLower = ReadBuffer(g_handleBB, 2, 1);
   //--- RSI on the same closed bar
   double rsi     = ReadBuffer(g_handleRSI, 0, 1);

   if(bbLower == EMPTY_VALUE || rsi == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read M30 BB/RSI indicator data");
      return ENTRY_NONE;
   }

   if(macroTrend == MACROTREND_ALIGNED_UP)
   {
      bool bbTrigger  = (m30Close <= bbLower);          // deep pullback: touch or pierce
      bool rsiTrigger = (rsi <= InpRSIBuyLevel);        // stretched down: RSI <= 35

      Print("SPRINGBOARD (bullish macro): close=", DoubleToString(m30Close, _Digits),
            " lowerBB=", DoubleToString(bbLower, _Digits), " rsi=",
            DoubleToString(rsi, 2), " | bb=", bbTrigger, " rsi=", rsiTrigger);

      if(bbTrigger || rsiTrigger)
      {
         Print("ENTRY SIGNAL: BUY (pullback springboard, ",
               bbTrigger && rsiTrigger ? "BB+RSI" : (bbTrigger ? "BB" : "RSI"), ")");
         return ENTRY_BUY;
      }
   }
   return ENTRY_NONE;
}

//+------------------------------------------------------------------+
//| Position and risk checks before entry (pure predicate: answers   |
//| yes/no only; the caller owns the HUD narrative).                 |
//| Enforces the strict single-position cap: PositionsTotal()==0.     |
//| On netting accounts PositionsTotal covers this directly; on       |
//| hedging accounts the magic-filtered count is the precise check.   |
//+------------------------------------------------------------------+
bool CanEnterTrade()
{
   //--- Strict cap: one open trade at any time (spec 4)
   if(PositionsTotal() > 0 && g_ticket == 0)
   {
      //--- A position exists that is not ours (manual or other EA):
      //    stay out - the engine never coexists with foreign flow.
      return false;
   }

   //--- This EA's own position still open?
   if(CountPositionsByMagic() >= 1)
   {
      return false;
   }

   //--- Stored ticket not yet retired (close-debounce window): still on
   if(g_ticket != 0)
   {
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| Count open positions belonging to this EA (by magic + symbol)     |
//+------------------------------------------------------------------+
int CountPositionsByMagic()
{
   int count = 0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 &&
         PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == g_magic)
      {
         count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Execute trade - full pipeline:                                    |
//|   entry price -> protective geometry -> lot sizing -> send        |
//| SL = 2.0x H1 ATR from execution price, TP = 4.0x H1 ATR (1:2 RR). |
//| Timeouts anchor on the fill time; state goes live only on success.|
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ENTRY_SIGNAL signal)
{
   bool isBuy = (signal == ENTRY_BUY);
   int  dir   = isBuy ? +1 : -1;

   //--- (1) Execution price: ASK for buys, BID for sells
   double entryPrice = isBuy ? SymbolInfoDouble(g_symbol, SYMBOL_ASK)
                             : SymbolInfoDouble(g_symbol, SYMBOL_BID);
   if(entryPrice <= 0)
   {
      Print("ERROR: Invalid execution price - trade aborted");
      return;
   }

   //--- (2) H1 ATR from the previous CLOSED H1 bar (noise insulation)
   double atrValue = ReadBuffer(g_handleATR, 1);
   if(atrValue == EMPTY_VALUE || atrValue <= 0)
   {
      Print("ERROR: Invalid H1 ATR value - trade aborted");
      return;
   }

   //--- (3) Protective geometry (spec 4):
   //    SL = 2.0x ATR behind entry, TP = 4.0x ATR ahead (strict 1:2)
   double slDistance = SL_ATR_MULTIPLE * atrValue;
   double tpDistance = SL_ATR_MULTIPLE * InpRRMultiplier * atrValue;
   double slPrice    = NormalizeDouble(entryPrice - dir * slDistance, _Digits);
   double tpPrice    = NormalizeDouble(entryPrice + dir * tpDistance, _Digits);

   //--- (4) Risk amount: exactly 1% of total account equity
   double riskAmount = AccountInfoDouble(ACCOUNT_EQUITY) * (InpRiskPercent / 100.0);
   if(riskAmount <= 0)
   {
      Print("ERROR: Invalid risk amount - trade aborted");
      return;
   }

   //--- (5) Dynamic lot sizing with tick-value calibration
   double lotSize = CalculateLotSize(riskAmount, slDistance);
   double volume  = NormalizeVolume(lotSize);

   double minLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   if(volume < minLot || volume <= 0)
   {
      //--- 1% risk cannot be honored at the broker's minimum lot.
      //    Refusing preserves the risk invariant; never upsize silently.
      double tickSize     = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
      double tickValue    = CalibratedTickValue();
      double riskPerLot   = (tickSize > 0 && tickValue > 0)
                            ? slDistance / tickSize * tickValue : 0;
      double requiredEq   = (riskPerLot > 0) ? minLot * riskPerLot / (InpRiskPercent / 100.0) : 0;
      SetStatus("Refused: min lot exceeds 1% risk budget");
      Print("TRADE REFUSED: computed volume ", DoubleToString(volume, 3),
            " < broker minimum ", DoubleToString(minLot, 3),
            " - 1% risk cannot be honored.",
            (requiredEq > 0 ? StringFormat(" Requires ~$%.2f equity.", requiredEq) : ""));
      return;
   }

   //--- (6) Send the market order
   Print("=== EXECUTING ", isBuy ? "BUY" : "SELL", " ===");
   Print("  Volume: ", DoubleToString(volume, 2),
         " | Entry: ", DoubleToString(entryPrice, _Digits),
         " | SL: ", DoubleToString(slPrice, _Digits), " (", SL_ATR_MULTIPLE, "x ATR)",
         " | TP: ", DoubleToString(tpPrice, _Digits), " (", SL_ATR_MULTIPLE * InpRRMultiplier, "x ATR)");
   Print("  Risk: $", DoubleToString(riskAmount, 2), " = ", InpRiskPercent,
         "% of equity | ATR(H1): ", DoubleToString(atrValue, _Digits));

   bool sent = isBuy
               ? trade.Buy(volume, g_symbol, entryPrice, slPrice, tpPrice, "V75 Macro BUY")
               : trade.Sell(volume, g_symbol, entryPrice, slPrice, tpPrice, "V75 Macro SELL");

   if(!sent || trade.ResultRetcode() != TRADE_RETCODE_DONE)
   {
      Print("TRADE FAILED: retcode=", trade.ResultRetcode(),
            " - ", trade.ResultRetcodeDescription());
      SetStatus("Order failed: " + trade.ResultRetcodeDescription());
      return;
   }

   //--- (7) Commit lifecycle state. The timeout anchor is the fill
   //    time; expiration is set exactly 2h into the future (v2.20).
   g_ticket       = trade.ResultOrder();
   g_entryTime    = TimeCurrent();
   g_expireTime   = g_entryTime + TIMEOUT_SECONDS;
   g_entryPrice   = entryPrice;
   g_riskAmount   = riskAmount;
   g_atrValue     = atrValue;
   g_tradesExecuted++;
   SetStatus(isBuy ? "LONG opened" : "SHORT opened");

   Print("TRADE EXECUTED: ticket ", g_ticket,
         " | entry ", TimeToString(g_entryTime),
         " | timeout expires ", TimeToString(g_expireTime));
}

//+------------------------------------------------------------------+
//| Tick-value safety check and correction (spec 4)                   |
//| If the broker's reported SYMBOL_TRADE_TICK_VALUE deviates by more |
//| than 5% from the geometric identity                               |
//|     (SYMBOL_TRADE_TICK_SIZE * SYMBOL_TRADE_CONTRACT_SIZE)         |
//| it is overwritten with that identity for accurate lot sizing.     |
//+------------------------------------------------------------------+
double CalibratedTickValue()
{
   double tickValue    = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize     = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   double contractSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double expected     = tickSize * contractSize;

   if(expected <= 0)
   {
      return tickValue;   // nothing to calibrate against
   }

   if(InpEnableTickSafety && MathAbs(tickValue - expected) / expected > 0.05)
   {
      Print("TICK VALUE CORRECTION: broker reports ", DoubleToString(tickValue, 8),
            ", identity ", DoubleToString(expected, 8),
            " (deviation ", DoubleToString(MathAbs(tickValue - expected) / expected * 100.0, 2),
            "%) -> using identity");
      return expected;
   }
   return tickValue;
}

//+------------------------------------------------------------------+
//| Informational tick-value validation at initialization             |
//+------------------------------------------------------------------+
void ValidateTickValue()
{
   double tickValue    = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize     = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   double contractSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double expected     = tickSize * contractSize;

   Print("=== TICK VALUE VALIDATION ===");
   Print("  Reported tick value: ", tickValue);
   Print("  Identity (tick size * contract size): ", expected);

   if(expected > 0)
   {
      double dev = MathAbs(tickValue - expected) / expected * 100.0;
      Print("  Deviation: ", DoubleToString(dev, 2), "% -> ",
            dev > 5.0 ? "EXCEEDS 5% - will be overwritten at lot sizing"
                      : "within tolerance");
   }
}

//+------------------------------------------------------------------+
//| Dynamic position sizing (spec 4): risk exactly 1% of equity       |
//|   Risk = Lots * (SL_Distance / TickSize) * TickValue              |
//|   Lots = Risk * TickSize / (SL_Distance * TickValue)              |
//+------------------------------------------------------------------+
double CalculateLotSize(double riskAmount, double slDistance)
{
   double tickValue = CalibratedTickValue();
   double tickSize  = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);

   if(tickValue <= 0 || tickSize <= 0 || slDistance <= 0)
   {
      Print("ERROR: Invalid symbol parameters for lot sizing - trade aborted");
      return 0;
   }

   double lots = (riskAmount * tickSize) / (slDistance * tickValue);

   //--- Cap at broker maximum only. Never clamp UP to the minimum:
   //    an unaffordable position is refused by the caller.
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);
   return MathMin(lots, maxLot);
}

//+------------------------------------------------------------------+
//| Volume normalization: floor onto the broker's volume grid and     |
//| clamp to the maximum. Deliberately never upsizes to the minimum - |
//| that decision (and its risk consequence) belongs to the caller.   |
//+------------------------------------------------------------------+
double NormalizeVolume(double rawVolume)
{
   double step   = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);

   double volume = rawVolume;
   if(step > 0)
   {
      volume = MathFloor(volume / step + 1e-9) * step;   // floor to tradable grid
      volume = NormalizeDouble(volume, 8);               // strip float dust
   }
   return MathMin(volume, maxLot);
}

//+------------------------------------------------------------------+
//| STATE OWNER: sync trade lifecycle from broker truth (spec 5)      |
//| Polls the live position (symbol + magic) on every tick and is the |
//| ONLY path that promotes or retires internal trade state - so a    |
//| trade closed by broker-side SL/TP, human intervention, or the     |
//| timeout itself is reconciled cleanly exactly once.                |
//+------------------------------------------------------------------+
void SyncPositionState()
{
   static int closeMisses = 0;   // debounce for the order-sent-not-yet-visible window
   ulong liveTicket = GetPositionTicket();

   //--- Live position sighted: mirror it into internal state
   if(liveTicket > 0)
   {
      closeMisses = 0;
      if(g_ticket != liveTicket)
      {
         g_ticket    = liveTicket;
         //--- Anchor the timeout on the position's true fill time so a
         //    restart mid-trade cannot extend the 2h lifecycle window.
         g_entryTime  = (datetime)PositionGetInteger(POSITION_TIME);
         g_expireTime = g_entryTime + TIMEOUT_SECONDS;
         Print("Position adopted (ticket ", liveTicket,
               ") - timeout anchored to fill time ", TimeToString(g_entryTime),
               ", expires ", TimeToString(g_expireTime));
      }
      return;
   }

   //--- No live position in the broker pool

   if(g_ticket == 0)
   {
      return;   // nothing stored - nothing to reconcile
   }

   closeMisses++;
   if(closeMisses < 2)
   {
      return;   // the fill/closure may still be materializing - wait one sync
   }
   closeMisses = 0;

   //--- A trade this EA ran has ended (SL / TP / timeout / manual).
   //    Account realized R from deal history, then tear down cleanly.
   AccountClosedTrade();
}

//+------------------------------------------------------------------+
//| Account a closed trade: realized R + full state teardown          |
//| (single cleanup path - called only from SyncPositionState)        |
//+------------------------------------------------------------------+
void AccountClosedTrade()
{
   Print("=== POSITION CLOSED (SL/TP/timeout/manual) - reconciling ===");

   double realizedPnL = CalculateRealizedPnL();
   if(realizedPnL != EMPTY_VALUE && g_riskAmount > 0)
   {
      double rMultiple = realizedPnL / g_riskAmount;
      g_cumulativeR += rMultiple;
      Print("  Realized PnL: $", DoubleToString(realizedPnL, 2),
            " | Trade R: ", DoubleToString(rMultiple, 2),
            " | Cumulative R: ", DoubleToString(g_cumulativeR, 2));
   }
   else
   {
      Print("  Realized PnL unavailable or no risk context - R not recorded");
   }

   ResetTradeState();
}

//+------------------------------------------------------------------+
//| Clear all trade lifecycle state (single teardown point)           |
//+------------------------------------------------------------------+
void ResetTradeState()
{
   g_ticket       = 0;
   g_entryTime    = 0;
   g_expireTime   = 0;
   g_entryPrice   = 0;
   g_riskAmount   = 0;
   g_atrValue     = 0;
   SetStatus("Flat - scanning for macro alignment");
}

//+------------------------------------------------------------------+
//| Realized PnL from the most recent closing deal (native history)   |
//+------------------------------------------------------------------+
double CalculateRealizedPnL()
{
   if(!HistorySelect(0, TimeCurrent() + 60))
   {
      Print("ERROR: HistorySelect failed - cannot read realized PnL");
      return EMPTY_VALUE;
   }

   //--- Search backwards for this EA's most recent closing deal
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket > 0 &&
         HistoryDealGetInteger(dealTicket, DEAL_MAGIC) == g_magic &&
         HistoryDealGetString(dealTicket, DEAL_SYMBOL) == g_symbol)
      {
         long entryType = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
         if(entryType == DEAL_ENTRY_OUT || entryType == DEAL_ENTRY_OUT_BY)
         {
            return HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
                 + HistoryDealGetDouble(dealTicket, DEAL_SWAP)
                 + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
         }
      }
   }
   return EMPTY_VALUE;
}

//+------------------------------------------------------------------+
//| 3-HOUR HARD TIMEOUT GUARDIAN (spec 5) - runs on EVERY tick        |
//| If now >= expiration and the position still lives, force-close    |
//| via market liquidation regardless of profit or loss. Retries on   |
//| the next tick if the close request is rejected.                   |
//+------------------------------------------------------------------+
void CheckTradeTimeout()
{
   if(g_ticket == 0 || g_expireTime == 0)
   {
      return;   // no active position to monitor
   }
   if(TimeCurrent() < g_expireTime)
   {
      return;   // lifecycle still open
   }

   Print("=== TIMEOUT EXPIRED (", TimeToString(g_expireTime),
         ") - FORCING MARKET CLOSE ===");

   if(ForceClosePosition())
   {
      Print("Position force-closed due to 2h timeout");
      //--- State teardown + R accounting happen in SyncPositionState
      //    (single cleanup path) once the position leaves the pool.
   }
   else
   {
      Print("Force-close rejected - retrying next tick");
   }
}

//+------------------------------------------------------------------+
//| Force close via market liquidation                                |
//| CTrade::PositionClose sends the correct close-side order (SELL to |
//| close a BUY, BUY to close a SELL) for the full position volume.   |
//+------------------------------------------------------------------+
bool ForceClosePosition()
{
   if(g_ticket <= 0)
   {
      return false;
   }

   //--- Select by ticket BEFORE reading position properties
   if(!PositionSelectByTicket(g_ticket))
   {
      Print("Position ", g_ticket, " no longer selectable - already closed");
      return false;   // sync path will reconcile
   }

   long type = PositionGetInteger(POSITION_TYPE);
   double volume = PositionGetDouble(POSITION_VOLUME);
   Print("Liquidating ", (type == POSITION_TYPE_BUY ? "BUY" : "SELL"), " ",
         DoubleToString(volume, 2), " lots (ticket ", g_ticket, ")");

   if(trade.PositionClose(g_ticket))
   {
      return true;
   }

   Print("ERROR: PositionClose failed - retcode ", trade.ResultRetcode(),
         ": ", trade.ResultRetcodeDescription());
   return false;
}

//+------------------------------------------------------------------+
//| Find this EA's open position ticket (symbol + magic filter)       |
//+------------------------------------------------------------------+
ulong GetPositionTicket()
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 &&
         PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == g_magic)
      {
         return ticket;
      }
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Read one indicator value at a given shift via CopyBuffer          |
//| Returns EMPTY_VALUE on any read failure (caller must check).      |
//+------------------------------------------------------------------+
double ReadBuffer(int handle, int shift)
{
   return ReadBuffer(handle, 0, shift);
}

double ReadBuffer(int handle, int bufferIndex, int shift)
{
   if(handle == INVALID_HANDLE)
   {
      return EMPTY_VALUE;
   }
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, bufferIndex, shift, 1, buf) < 1)
   {
      return EMPTY_VALUE;
   }
   return buf[0];
}

//+------------------------------------------------------------------+
//| Dashboard HUD (spec 6) - clean text overlay on the chart:         |
//| equity, session PnL, cumulative R, and a live countdown of the    |
//| active trade's remaining lifecycle.                               |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   double currentEquity = InpPaperMode ? g_paperEquity
                                       : AccountInfoDouble(ACCOUNT_EQUITY);
   double sessionPnL    = currentEquity - g_startEquity;

   //--- Countdown timer for the active trade's remaining lifecycle
   string countdown = "--:--:--";
   if(InPosition() && g_expireTime > 0)
   {
      int remaining = (int)(g_expireTime - TimeCurrent());
      if(remaining <= 0)
      {
         countdown = "LIQUIDATING";
      }
      else
      {
         countdown = StringFormat("%02d:%02d:%02d",
                                  remaining / 3600, (remaining % 3600) / 60, remaining % 60);
      }
   }

   string status = g_entryStatus;
   if(InPosition() && PositionSelectByTicket(g_ticket))
   {
      long   type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double cur  = (type == POSITION_TYPE_BUY)
                    ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                    : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      double pnl  = PositionGetDouble(POSITION_PROFIT);
      double lots = PositionGetDouble(POSITION_VOLUME);

      status = StringFormat("%s %.2f lots @ %s | PnL $%.2f (%s) | expires in %s",
                            type == POSITION_TYPE_BUY ? "LONG" : "SHORT",
                            lots,
                            DoubleToString(open, _Digits),
                            pnl,
                            DoubleToString(cur, _Digits),
                            countdown);
   }

   string dashboard =
      "+================================================+\n" +
      (InpPaperMode ? "|     V75 MACRO INFERENCE ENGINE v2.21 PAPER      |\n"
                    : "|       V75 MACRO INFERENCE ENGINE v2.21         |\n") +
      "+================================================+\n" +
      "| Equity        : " + Pad(DoubleToString(currentEquity, 2), 33) + "\n" +
      "| Session PnL   : " + Pad((sessionPnL >= 0 ? "+" : "") + DoubleToString(sessionPnL, 2), 33) + "\n" +
      "| Cumulative R  : " + Pad(DoubleToString(g_cumulativeR, 2), 33) + "\n" +
      "| Trades (sess) : " + Pad(IntegerToString(g_tradesExecuted), 33) + "\n" +
      "+------------------------------------------------+\n" +
      "| Trade timer    : " + Pad(countdown, 33) + "\n" +
      "| Engine status  : " + Pad(StringSubstr(status, 0, 33), 33) + "\n" +
      "+================================================+\n";

   string riskLine = StringFormat("Risk %.1f%% | SL %.0fxATR | TP %.0fxATR (1:%.0f) | Timeout 2h | Magic %d",
                   InpRiskPercent, SL_ATR_MULTIPLE,
                   SL_ATR_MULTIPLE * InpRRMultiplier, InpRRMultiplier,
                   g_magic);
   if(InpPaperMode) riskLine += " | PAPER";

   Comment(dashboard + riskLine);
}

//+------------------------------------------------------------------+
//| PAPER MODE (v2.21) - arm-C machinery                              |
//| Virtual fills at bid/ask, geometry identical to live execution,   |
//| ledger + telemetry in MQL5\Files in the format the watchdog and   |
//| the A/B adjudicator already parse (OPEN/CLOSE/EQ csv + jsonl).    |
//| Hard invariant: InpPaperMode=true never sends a broker order -    |
//| CTrade is never touched on the paper path.                        |
//+------------------------------------------------------------------+
string PaperSymbolTag()
{
   string tag = g_symbol;
   StringReplace(tag, " ", "_");   // arms convention: MitemshubAI_state_Volatility_75_Index.csv
   return tag;
}
string PaperLedgerPath()    { return "V75MacroEngine_paper_" + PaperSymbolTag() + ".csv"; }
string PaperTelemetryPath() { return "V75MacroEngine_paper_telemetry_" + PaperSymbolTag() + ".jsonl"; }

//--- v2.23: VERIFIED APPEND — a row only counts as written when the bytes
//    are actually written AND flushed; one retry with a short backoff; a row
//    failing twice is quarantined to the journal with the WLOST tag so the
//    watchdog integrity scan sees it and the row can be restored by hand.
//    (Class-found in the 2026-09-15 audit: FileWrite failures were never
//    checked anywhere, so a dropped row stayed silent.)
bool AppendVerifiedV75(const string file, const string line, const string tag)
{
   uint want = StringLen(line) + 2;            // + explicit "\r\n" below
   for(int attempt = 0; attempt < 2; attempt++)
   {
      int fh = FileOpen(file,
                        FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
      if(fh != INVALID_HANDLE)
      {
         FileSeek(fh, 0, SEEK_END);
         long before = (long)FileSize(fh);
         uint got = FileWriteString(fh, line + "\r\n");
         FileClose(fh);
         // verify by re-reading: the file on disk must have grown by the row
         int v = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
         bool on_disk = false;
         if(v != INVALID_HANDLE)
         {
            on_disk = ((long)FileSize(v) >= before + (long)want);
            FileClose(v);
         }
         if(got >= want && on_disk)
            return(true);
      }
      Sleep(50);                               // brief backoff, then one retry
   }
   Print("WLOST [", tag, "] append failed twice err=", GetLastError(), " line=", line);
   return(false);
}

void PaperWriteTelemetry(string type, bool fired = false)
{
   //--- FILE_TXT (not CSV): the JSON line is written verbatim; CSV mode
   //    field-quotes strings containing the delimiter and mangles the line.
   double atr = ReadBuffer(g_handleATR, 1);
   string line = StringFormat("{\"ts\":\"%s\",\"epoch\":%I64d,\"type\":\"%s\",\"sym\":\"%s\",\"fired\":%s,\"eq\":%.2f,\"pos\":%d,\"magic\":%d,\"atr\":%s}",
                              TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES | TIME_SECONDS),
                              (long)TimeCurrent(), type, g_symbol,
                              fired ? "true" : "false",
                              g_paperEquity, g_paperDir, g_magic,
                              (atr == EMPTY_VALUE || atr <= 0) ? "null" : DoubleToString(atr, _Digits));
   AppendVerifiedV75(PaperTelemetryPath(), line, type);   // telemetry must never break the engine
}

void PaperAppendLedger(string row)
{
   //--- FILE_TXT with one verbatim comma row: byte-compatible with the
   //    arms' CSV ledger (the parser splits on ','), no CSV quoting layer.
   AppendVerifiedV75(PaperLedgerPath(), row, StringSubstr(row, 0, 5));
}

void PaperOpenTrade(ENUM_ENTRY_SIGNAL signal)
{
   bool isBuy = (signal == ENTRY_BUY);
   int  dir   = isBuy ? +1 : -1;

   //--- Virtual fill at the ask (buy) / bid (sell) - same price basis as live
   double entryPrice = isBuy ? SymbolInfoDouble(g_symbol, SYMBOL_ASK)
                             : SymbolInfoDouble(g_symbol, SYMBOL_BID);
   if(entryPrice <= 0)
   {
      Print("ERROR: Invalid execution price - paper trade aborted");
      return;
   }

   double atrValue = ReadBuffer(g_handleATR, 1);
   if(atrValue == EMPTY_VALUE || atrValue <= 0)
   {
      Print("ERROR: Invalid H1 ATR value - paper trade aborted");
      return;
   }

   //--- Geometry identical to ExecuteTrade (spec 4)
   double slDistance = SL_ATR_MULTIPLE * atrValue;
   double tpDistance = SL_ATR_MULTIPLE * InpRRMultiplier * atrValue;
   double slPrice    = NormalizeDouble(entryPrice - dir * slDistance, _Digits);
   double tpPrice    = NormalizeDouble(entryPrice + dir * tpDistance, _Digits);

   //--- Risk on VIRTUAL equity; sizing math identical to live (spec 4 + the
   //    calibrated tick value, so paper lots are exactly the live lots)
   double riskAmount = g_paperEquity * (InpRiskPercent / 100.0);
   if(riskAmount <= 0)
   {
      Print("ERROR: Invalid virtual risk amount - paper trade aborted");
      return;
   }
   double lotSize = CalculateLotSize(riskAmount, slDistance);
   double volume  = NormalizeVolume(lotSize);
   double minLot  = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   if(volume < minLot || volume <= 0)
   {
      SetStatus("Paper refused: min lot exceeds 1% risk budget");
      Print("PAPER TRADE REFUSED: computed volume ", DoubleToString(volume, 3),
            " < broker minimum - 1% risk cannot be honored.");
      return;
   }

   //--- Commit to the virtual book
   g_ticket       = 1;                 // paper sentinel: nonzero = managed
   g_entryTime    = TimeCurrent();
   g_expireTime   = g_entryTime + TIMEOUT_SECONDS;
   g_entryPrice   = entryPrice;
   g_riskAmount   = riskAmount;
   g_atrValue     = atrValue;
   g_paperDir     = dir;
   g_paperVolume  = volume;
   g_paperSL      = slPrice;
   g_paperTP      = tpPrice;
   g_tradesExecuted++;

   long openEpoch = (long)g_entryTime;
   //--- Arms' OPEN schema (12 fields, byte-compatible with MitemshubAI):
   //    OPEN,ts,ticket,dir,entry,sl,tp,vol,eff_risk$,stop_dist,max_hold,tag
   //    v2.21 wrote 13 fields (an extra ATR column) with %.5f slots fed
   //    DoubleToString strings, which MQL printed as 0.00000 - caught by
   //    the tester-mode ledger validation (artifacts/v75_macro_engine_tester,
   //    2026-09-15). Numbers are now passed as numbers.
   PaperAppendLedger(StringFormat("OPEN,%I64d,%I64d,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.2f,%d,%s",
                     openEpoch, openEpoch, dir, entryPrice, slPrice, tpPrice,
                     volume, riskAmount, slDistance, TIMEOUT_SECONDS, "PAPER"));

   Print("=== PAPER EXECUTING ", isBuy ? "BUY" : "SELL", " ===");
   Print("  Volume: ", DoubleToString(volume, 2),
         " | Entry: ", DoubleToString(entryPrice, _Digits),
         " | SL: ", DoubleToString(slPrice, _Digits),
         " | TP: ", DoubleToString(tpPrice, _Digits),
         " | Risk: $", DoubleToString(riskAmount, 2));
   PaperWriteTelemetry("fill", true);
   SetStatus("PAPER LONG opened");
}

void PaperCloseTrade(string reason)
{
   //--- Virtual close at bid (long) / ask (short) - the exit pays the spread
   double exitPrice = (g_paperDir > 0) ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                                       : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   double tickSize  = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = CalibratedTickValue();
   double pnl       = 0;

   if(tickSize > 0 && tickValue > 0)
   {
      pnl = (exitPrice - g_entryPrice) / tickSize * tickValue * g_paperVolume
            * (g_paperDir > 0 ? 1.0 : -1.0);
   }
   double rMultiple = (g_riskAmount > 0) ? pnl / g_riskAmount : 0;
   g_paperEquity   += pnl;
   g_cumulativeR   += rMultiple;

   long closeEpoch = (long)TimeCurrent();
   PaperAppendLedger(StringFormat("CLOSE,%I64d,%I64d,%s,%.5f,%.3f,%.2f,%.2f",
                     closeEpoch, (long)g_entryTime, reason, exitPrice, rMultiple,
                     pnl, g_paperEquity));
   PaperAppendLedger(StringFormat("EQ,%.2f", g_paperEquity));

   Print("PAPER CLOSE ", reason, " R=", DoubleToString(rMultiple, 3),
         " pnl=$", DoubleToString(pnl, 2), " vEq=$", DoubleToString(g_paperEquity, 2),
         " | CumR: ", DoubleToString(g_cumulativeR, 2));

   //--- Teardown (single path, mirrors ResetTradeState)
   g_ticket      = 0;
   g_entryTime   = 0;
   g_expireTime  = 0;
   g_entryPrice  = 0;
   g_riskAmount  = 0;
   g_atrValue    = 0;
   g_paperDir    = 0;
   g_paperVolume = 0;
   g_paperSL     = 0;
   g_paperTP     = 0;
   SetStatus("Flat - scanning for macro alignment");
   PaperWriteTelemetry("close", true);
}

void PaperCheckExits()
{
   if(g_ticket == 0 || g_paperDir == 0)
   {
      return;
   }
   if(g_paperDir > 0)
   {
      double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
      if(bid <= g_paperSL)      { PaperCloseTrade("STOP");   return; }
      if(bid >= g_paperTP)      { PaperCloseTrade("TARGET"); return; }
   }
   else
   {
      double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      if(ask >= g_paperSL)      { PaperCloseTrade("STOP");   return; }
      if(ask <= g_paperTP)      { PaperCloseTrade("TARGET"); return; }
   }
}

void PaperCheckTimeout()
{
   if(g_ticket == 0 || g_expireTime == 0 || TimeCurrent() < g_expireTime)
   {
      return;
   }
   Print("=== PAPER TIMEOUT EXPIRED (", TimeToString(g_expireTime), ") - VIRTUAL LIQUIDATION ===");
   PaperCloseTrade("ECUT");
}

//+------------------------------------------------------------------+
//| Pad text right-aligned inside a fixed-width HUD column            |
//+------------------------------------------------------------------+
string Pad(string text, int width)
{
   int len = StringLen(text);
   if(len >= width)
   {
      return text;
   }
   string out = text;
   for(int i = 0; i < width - len; i++)
   {
      out += " ";
   }
   return out;
}
//+------------------------------------------------------------------+

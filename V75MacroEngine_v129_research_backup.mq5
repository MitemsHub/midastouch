//+------------------------------------------------------------------+
//|                                                   V75MacroEngine.mq5 |
//|   Macro-inference directional engine for Volatility 75 (V75)      |
//|   Multi-timeframe alignment, M30 springboard entries, ATR risk   |
//+------------------------------------------------------------------+
#property copyright   "Algorithmic Trading Engine"
#property link        ""
#property version     "1.29"

// Native MQL5 trading library only - no custom includes
#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| INPUT PARAMETERS & CONSTANTS                                      |
//+------------------------------------------------------------------+
input group "--- Time & Execution Settings ---"
input int    InpMagicNumber        = 7500;               // Magic number for trade identification
input int    InpMaxPositionCount   = 1;                  // Maximum open positions (enforced as 1)

input group "--- Indicator Parameters ---"
input int    InpH4EMAPeriod        = 20;                 // H4 trend EMA period
input int    InpH1EMAPeriod        = 20;                 // H1 trend EMA period
input int    InpBBPeriod           = 20;                 // Bollinger Bands period (M30 entry)
input double InpBBDeviation        = 2.0;                // Bollinger Bands deviation
input int    InpRSIPeriod          = 14;                 // RSI period (M30 entry)
input double InpRSIBuyLevel        = 35.0;               // M30 RSI oversold threshold (aligned uptrend)
input double InpRSISellLevel       = 65.0;               // M30 RSI overbought threshold (aligned downtrend)
input int    InpATRPeriod          = 14;                 // ATR period (H1 noise isolation)

input group "--- Risk & Reward Profile ---"
input double InpRiskPercent        = 1.0;                // Risk per trade as % of account equity
input double InpRRMultiplier       = 2.0;                // Take profit multiplier vs stop loss (1:2 RR)
input int    InpTradeTimeoutHours  = 3;                  // Hard timeout window in hours

input group "--- Safety Checks ---"
input bool   InpEnableTickSafety   = true;               // Enable tick value calibration check

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
   ENTRY_BUY,    // Pullback in uptrend
   ENTRY_SELL    // Overextension in downtrend
};

//+------------------------------------------------------------------+
//| Open-profit protection modes. All modes keep the 3h timeout as    |
//| the hard backstop; management only RATCHETS the stop in the       |
//| trade's favor so open profit can survive past the timeout.        |
//+------------------------------------------------------------------+
enum ENUM_EXIT_MANAGER
{
   EXIT_MANAGER_NONE  = 0,  // Off: initial SL/TP + 3h timeout only (original behavior)
   EXIT_MANAGER_BE    = 1,  // Breakeven: SL to entry(+offset) once peak reaches trigger R
   EXIT_MANAGER_TRAIL = 2   // Breakeven step, then trail SL at a multiple of H1 ATR
};

//+------------------------------------------------------------------+
//| Take-profit modes. ATR_MULTIPLE keeps the spec geometry (TP =      |
//| InpRRMultiplier * 2.0x ATR). R_MULTIPLE targets a fixed R-multiple |
//| of the initial risk, for data-derived targets mined from the audit |
//| CSVs' peak-excursion (MFE) distribution.                           |
//+------------------------------------------------------------------+
enum ENUM_TP_MODE
{
   TP_MODE_ATR_MULTIPLE = 0,  // Spec: TP = InpRRMultiplier * 2.0x ATR
   TP_MODE_R_MULTIPLE   = 1   // Data: TP = InpTPRMultiple * initial risk
};

input group "--- Take-Profit Target ---"
input ENUM_TP_MODE InpTPMode    = TP_MODE_ATR_MULTIPLE;  // TP mode (ATR multiple = spec default)
input double      InpTPRMultiple = 0.3;   // R-multiple TP (TP_MODE_R_MULTIPLE)

input group "--- Open-Profit Protection (ratchet exits) ---"
input ENUM_EXIT_MANAGER InpExitManager    = EXIT_MANAGER_NONE;  // Exit manager mode (default OFF: spec-pure SL/TP + timeout)
input double InpBETriggerR     = 0.2;     // Breakeven trigger (R multiples of initial risk)
input double InpBEOffsetPoints = 10;      // Breakeven lock-in offset (points beyond entry)
input double InpTrailATRMult   = 1.0;     // Trailing distance (multiple of H1 ATR)
// Opt-in values are evidence-set (Jul-Sep 2026 real-tick validation,
// artifacts/v75_macro_engine_tester/): at the 3h horizon a 1.0R trigger can
// never arm (max peak excursion 0.44R), while 0.2R/1.0x cut net loss ~90%
// vs timeout-only; 6h+trail was the only net-positive cell (+11.67, PF 1.07).
// The compiled default stays OFF so out-of-the-box behavior is the pure
// SL/TP + 3h-timeout contract; enable InpExitManager explicitly to opt in.

input group "--- Audit Trail (CSV for the Python analysis pipeline) ---"
input bool   InpAuditCsv        = true;    // Write CSV decision audit trail

//+------------------------------------------------------------------+
//| STATE OWNERSHIP MAP                                               |
//|   Broker pool (symbol+magic)  -> single owner of "is a trade on"  |
//|   g_ticket                    -> mirrors the broker ticket        |
//|   g_entryTime/g_entryPrice/... -> trade context captured at       |
//|                                  execution, torn down in ONE place |
//|                                  (ResetTradeState)                 |
//|   SyncPositionState() is the ONLY function that promotes a       |
//|   position sighting into state and the ONLY one that retires it. |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_symbol       = NULL;
int      g_magic        = InpMagicNumber;

//--- trade lifecycle (owned by SyncPositionState)
bool     g_isInPosition = false;   // derived: live position sighted this tick
ulong    g_ticket       = 0;       // broker ticket of the managed position
datetime g_entryTime    = 0;       // adoption/execution time (timeout anchor)
double   g_entryPrice   = 0;
double   g_stopLoss     = 0;
double   g_takeProfit   = 0;
double   g_riskAmount   = 0;       // equity risk staged at execution (>0 => executed by this EA)
double   g_atrValue     = 0;
double   g_initialSL    = 0;       // entry SL distance (price units); >0 => manage-able context
double   g_exitPeakR    = 0.0;     // best favorable excursion since entry, in R (ratchet fuel)
string   g_entryRegime = "";      // entry-bar alignment regime (attribution)
string   g_entryBranch = "";      // entry-bar springboard branch token (attribution)

//--- audit trail state (owned by the Audit* helpers below)
int      g_auditHandle   = INVALID_HANDLE;
string   g_auditPath     = "";
string   g_auditMonth    = "";
string   g_runId         = "";
double   g_auditH4Close  = EMPTY_VALUE;   // alignment snapshot for the gated bar
double   g_auditH4Ema    = EMPTY_VALUE;
double   g_auditH1Close  = EMPTY_VALUE;
double   g_auditH1Ema    = EMPTY_VALUE;
double   g_auditM30Close = EMPTY_VALUE;

//--- dashboard state (owned by OnInit / AccountClosedTrade)
double   g_startEquity    = 0;
double   g_cumulativeR    = 0;
int      g_tradesExecuted = 0;

//--- engine status (owned by the decision path: OnTick branches + ExecuteTrade).
//    Why the engine is currently flat - rendered verbatim by the HUD so the
//    flat-state narrative can never contradict the decision that produced it
//    (fixes the "says WAITING while actually refusing undercapitalized entries"
//    defect observed in the live-surface playtest).
string   g_entryStatus    = "Initializing";

//--- indicator handles (owned by OnInit / OnDeinit)
int g_hbowH4EMA, g_hbowH1EMA, g_hbowBB, g_hbowRSI, g_hbowATR;

//--- cached M30 indicator values (owned by FetchM30IndicatorValues)
double g_cachedBBUpper = EMPTY_VALUE;
double g_cachedBBLower = EMPTY_VALUE;
double g_cachedRSI     = EMPTY_VALUE;

//--- number of consecutive syncs with no live position before a stored
//    lifecycle is retired (debounces the order-sent-but-not-yet-visible
//    window; real closures reconcile one tick later)
#define CLOSE_DEBOUNCE_SYNCS 2

//+------------------------------------------------------------------+
//| AUDIT TRAIL: CSV decision log for the Python analysis pipeline     |
//| One file per month in <Common>\Files (FILE_COMMON|FILE_SHARE_READ),|
//| append-mode, flushed per row, so the repo's pandas tooling can     |
//| read it while the EA runs. Empty cell = value unavailable.         |
//| Row types:                                                         |
//|   signal_bar     - every gated M30 bar: alignment+indicator raws   |
//|   springboard    - every aligned bar: trigger inputs               |
//|   decision       - every decision branch outcome (incl. refusals) |
//|   indicator_read - read failures (the action cell names the read)  |
//|   trade_closed   - reconciliation: peak R, PnL, realized R         |
//+------------------------------------------------------------------+
string AuditNum(double value)
{
   return AuditNum(value, _Digits);
}

string AuditNum(double value, int digits)
{
   if(value == EMPTY_VALUE)
   {
      return "";                     // empty cell = value unavailable
   }
   return DoubleToString(value, digits);
}

//--- Open (or rotate to) the current month's audit CSV; header on create
bool AuditEnsureFile()
{
   if(!InpAuditCsv)
   {
      return false;
   }

   string month = StringSubstr(TimeToString(TimeCurrent(), TIME_DATE), 0, 7);  // "YYYY.MM"
   if(g_auditHandle != INVALID_HANDLE && month == g_auditMonth)
   {
      return true;                                   // current month already open
   }

   if(g_auditHandle != INVALID_HANDLE)
   {
      FileClose(g_auditHandle);                      // month rollover
      g_auditHandle = INVALID_HANDLE;
   }

   string tag  = month;
   StringReplace(tag, ".", "-");
   string name = StringFormat("V75MacroEngine_audit_%s.csv", tag);

   g_auditHandle = FileOpen(name, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ, ',');
   if(g_auditHandle == INVALID_HANDLE)
   {
      Print("AUDIT ERROR: cannot open audit CSV '", name, "' err=", GetLastError());
      return false;
   }
   g_auditMonth = month;
   g_auditPath  = name;
   FileSeek(g_auditHandle, 0, SEEK_END);
   if(FileSize(g_auditHandle) == 0)
   {
      FileWrite(g_auditHandle,
                "run_id", "timestamp", "row_type", "macro_trend",
                "h4_close", "h4_ema", "h1_close", "h1_ema",
                "m30_close", "bb_upper", "bb_lower", "rsi",
                "signal", "action", "position", "equity",
                "peak_r", "realized_pnl", "realized_r");
      FileFlush(g_auditHandle);
   }
   return true;
}

//--- One audit row; safe to call anywhere (no-op when disabled or unopenable)
void AuditRow(const string rowType, const string macroTrend, const string signal,
              const string action, const string position, double peakR,
              double realizedPnL, double realizedR)
{
   if(!AuditEnsureFile())
   {
      return;
   }
   FileWrite(g_auditHandle,
             g_runId,
             TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
             rowType, macroTrend,
             AuditNum(g_auditH4Close), AuditNum(g_auditH4Ema),
             AuditNum(g_auditH1Close), AuditNum(g_auditH1Ema),
             AuditNum(g_auditM30Close),
             AuditNum(g_cachedBBUpper), AuditNum(g_cachedBBLower), AuditNum(g_cachedRSI, 2),
             signal, action, position,
             AuditNum(AccountInfoDouble(ACCOUNT_EQUITY), 2),
             AuditNum(peakR, 2), AuditNum(realizedPnL, 2), AuditNum(realizedR, 2));
   FileFlush(g_auditHandle);
}

//--- Stamp the run identity and open the first file
void AuditInitRun()
{
   if(!InpAuditCsv)
   {
      Print("Audit CSV: disabled");
      return;
   }
   g_runId = TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS);
   StringReplace(g_runId, ":", "-");
   StringReplace(g_runId, " ", "_");
   StringReplace(g_runId, ".", "-");
   if(AuditEnsureFile())
   {
      Print("AUDIT: CSV trail enabled -> Common\\Files\\", g_auditPath,
            "  (run_id=", g_runId, ")");
   }
}

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- Initialize trade object with magic number
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_FOK);

   //--- Get symbol from chart
   g_symbol = _Symbol;
   g_magic  = InpMagicNumber;

   //--- Session baseline for the HUD's Session PnL line
   g_startEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   //--- Initialize indicator handles
   // H4 20-period EMA
   g_hbowH4EMA = iMA(g_symbol, PERIOD_H4, InpH4EMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hbowH4EMA == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create H4 EMA handle");
      return INIT_FAILED;
   }

   // H1 20-period EMA
   g_hbowH1EMA = iMA(g_symbol, PERIOD_H1, InpH1EMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hbowH1EMA == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create H1 EMA handle");
      return INIT_FAILED;
   }

   // M30 Bollinger Bands (buffers: 0=middle/base, 1=upper, 2=lower)
   g_hbowBB = iBands(g_symbol, PERIOD_M30, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);
   if(g_hbowBB == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create M30 BB handle");
      return INIT_FAILED;
   }

   // M30 RSI
   g_hbowRSI = iRSI(g_symbol, PERIOD_M30, InpRSIPeriod, PRICE_CLOSE);
   if(g_hbowRSI == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create M30 RSI handle");
      return INIT_FAILED;
   }

   // H1 ATR
   g_hbowATR = iATR(g_symbol, PERIOD_H1, InpATRPeriod);
   if(g_hbowATR == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create H1 ATR handle");
      return INIT_FAILED;
   }

   //--- Informational tick-value validation (the functional overwrite
   //    with the geometric identity happens inside CalculateLotSize)
   if(InpEnableTickSafety)
   {
      ValidateAndFixTickValue();
   }

   AuditInitRun();

   g_entryStatus = "Initialized - waiting for first M30 gate";
   Print("V75 Macro Engine initialized successfully");
   Print("Symbol: ", g_symbol);
   Print("Magic: ", g_magic);
   Print("Risk per trade: ", InpRiskPercent, "%");
   Print("RR Ratio: 1:", InpRRMultiplier);
   Print("Timeout: ", InpTradeTimeoutHours, " hours");
   Print("Exit manager: ", InpExitManager == EXIT_MANAGER_NONE ? "OFF (SL/TP + timeout only)" :
         InpExitManager == EXIT_MANAGER_BE ? StringFormat("Breakeven @ %.2fR", InpBETriggerR) :
         StringFormat("Breakeven @ %.2fR + ATR trail %.2fx", InpBETriggerR, InpTrailATRMult));
   Print("TP mode: ", InpTPMode == TP_MODE_ATR_MULTIPLE ?
         StringFormat("ATR multiple (%.1fx ATR)", InpRRMultiplier * 2.0) :
         StringFormat("R multiple (%.2fR)", InpTPRMultiple));
   Print("Springboard: RSI ", DoubleToString(InpRSIBuyLevel, 1), "/",
         DoubleToString(InpRSISellLevel, 1), " | BB deviation ",
         DoubleToString(InpBBDeviation, 2));

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   //--- Release indicator handles
   if(g_hbowH4EMA != INVALID_HANDLE) IndicatorRelease(g_hbowH4EMA);
   if(g_hbowH1EMA != INVALID_HANDLE) IndicatorRelease(g_hbowH1EMA);
   if(g_hbowBB    != INVALID_HANDLE) IndicatorRelease(g_hbowBB);
   if(g_hbowRSI   != INVALID_HANDLE) IndicatorRelease(g_hbowRSI);
   if(g_hbowATR   != INVALID_HANDLE) IndicatorRelease(g_hbowATR);

   if(g_auditHandle != INVALID_HANDLE)
   {
      FileClose(g_auditHandle);
      g_auditHandle = INVALID_HANDLE;
      Print("Audit CSV closed: ", g_auditPath);
   }

   Comment("");  // Clear the dashboard from the chart
   Print("V75 Macro Engine deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function - MAIN ENTRY POINT                            |
//+------------------------------------------------------------------+
void OnTick()
{
   //--- Per-tick guardians (run on EVERY tick, before the gatekeeper)
   SyncPositionState();      // broker truth is the single owner of trade state
   CheckTradeTimeout();      // 3h hard timeout guardian (unchanged backstop)
   TrackPeakExcursion();     // always-on MFE tracking (audit peak_r + ratchet fuel)
   ManageOpenProfit();       // ratchet-only open-profit protection

   //--- 1. M30 New Candle Gatekeeper
   // Only execute structural checks at the exact opening second of a new M30 candle
   if(!IsNewM30Candle())
   {
      UpdateDashboard();
      return;
   }

   //--- We are at the opening second of a new M30 candle
   // Perform full structural analysis and entry signal evaluation

   Print("--- New M30 Candle - Running Macro Analysis ---");

   //--- fresh audit snapshot for this gated bar (rows below fill what they read)
   g_auditH4Close  = EMPTY_VALUE;  g_auditH4Ema  = EMPTY_VALUE;
   g_auditH1Close  = EMPTY_VALUE;  g_auditH1Ema  = EMPTY_VALUE;
   g_auditM30Close = EMPTY_VALUE;

   //--- Fetch M30 indicator values via CopyBuffer for robust reads
   FetchM30IndicatorValues();

   //--- 2. Multi-timeframe directional macro alignment
   ENUM_MACROTREND trendAlignment = GetMacroTrendAlignment();

   if(trendAlignment == MACROTREND_NONE)
   {
      Print("No macro alignment - H4/H1 trends diverge or inconclusive. Standing down.");
      g_entryStatus = "H4/H1 diverged - standing down";
      AuditRow("decision", "diverged", "", "stand_down", "flat", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      UpdateDashboard();
      return;
   }

   //--- 3. Check if we can enter (max positions, no existing position)
   if(!CanEnterTrade())
   {
      Print("Cannot enter trade - position limits or existing position active");
      g_entryStatus = "Entry blocked - position limit or existing position";
      AuditRow("decision", (trendAlignment == MACROTREND_ALIGNED_UP) ? "aligned_up" : "aligned_down",
               "", "blocked", g_isInPosition ? "in_position" : "limit", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      UpdateDashboard();
      return;
   }

   //--- 4. Get entry signal from M30 springboard
   ENUM_ENTRY_SIGNAL entrySignal = GetM30EntrySignal(trendAlignment);

   if(entrySignal == ENTRY_NONE)
   {
      Print("No M30 entry trigger met. Waiting for springboard.");
      g_entryStatus = StringFormat("Macro aligned %s - waiting for M30 springboard",
                                   (trendAlignment == MACROTREND_ALIGNED_UP) ? "UP" : "DOWN");
      AuditRow("decision", (trendAlignment == MACROTREND_ALIGNED_UP) ? "aligned_up" : "aligned_down",
               "", "wait_springboard", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      UpdateDashboard();
      return;
   }

   //--- 5. Execute trade with dynamic risk management
   ExecuteTrade(entrySignal);
   string auditAction = "send_failed";
   if(g_entryStatus == "Order sent")             auditAction = "order_sent";
   else if(StringFind(g_entryStatus, "Refused") == 0) auditAction = "refused";
   AuditRow("decision", (entrySignal == ENTRY_BUY) ? "aligned_up" : "aligned_down",
            g_entryBranch, auditAction, "",
            EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);

   //--- Update dashboard after any action
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| M30 New Candle Gatekeeper                                          |
//| Cold-attach safe: the current bar is adopted on the first call,    |
//| so no signal can fire on the first tick after attach/reconnect.    |
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
//| Multi-timeframe directional macro alignment                        |
//| Structural reads use CLOSED bars only (shift 1 = previous candle)  |
//+------------------------------------------------------------------+
ENUM_MACROTREND GetMacroTrendAlignment()
{
   //--- H4 previous candle close and EMA (both shift 1)
   double h4Close = iClose(g_symbol, PERIOD_H4, 1);

   double h4EmaBuf[];
   ArraySetAsSeries(h4EmaBuf, true);
   if(CopyBuffer(g_hbowH4EMA, 0, 1, 1, h4EmaBuf) < 1 || h4EmaBuf[0] == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read H4 EMA data");
      AuditRow("indicator_read", "", "", "h4_ema_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_NONE;
   }
   double h4EMA = h4EmaBuf[0];

   if(h4Close == 0)
   {
      Print("ERROR: Cannot read H4 close data");
      AuditRow("indicator_read", "", "", "h4_close_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_NONE;
   }
   g_auditH4Close = h4Close;
   g_auditH4Ema   = h4EMA;

   //--- H1 previous candle close and EMA (both shift 1)
   double h1Close = iClose(g_symbol, PERIOD_H1, 1);

   double h1EmaBuf[];
   ArraySetAsSeries(h1EmaBuf, true);
   if(CopyBuffer(g_hbowH1EMA, 0, 1, 1, h1EmaBuf) < 1 || h1EmaBuf[0] == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read H1 EMA data");
      AuditRow("indicator_read", "", "", "h1_ema_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_NONE;
   }
   double h1EMA = h1EmaBuf[0];

   if(h1Close == 0)
   {
      Print("ERROR: Cannot read H1 close data");
      AuditRow("indicator_read", "", "", "h1_close_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_NONE;
   }
   g_auditH1Close = h1Close;
   g_auditH1Ema   = h1EMA;

   //--- Determine individual trend directions
   bool h4Uptrend   = (h4Close > h4EMA);
   bool h1Uptrend   = (h1Close > h1EMA);

   bool h4Downtrend = (h4Close < h4EMA);
   bool h1Downtrend = (h1Close < h1EMA);

   //--- Check for aligned uptrend
   if(h4Uptrend && h1Uptrend)
   {
      Print("MACRO ALERT: Aligned Uptrend detected");
      Print("  H4: Close=", DoubleToString(h4Close, _Digits),
            " EMA=", DoubleToString(h4EMA, _Digits), " -> UP");
      Print("  H1: Close=", DoubleToString(h1Close, _Digits),
            " EMA=", DoubleToString(h1EMA, _Digits), " -> UP");
      AuditRow("signal_bar", "aligned_up", "", "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_ALIGNED_UP;
   }

   //--- Check for aligned downtrend
   if(h4Downtrend && h1Downtrend)
   {
      Print("MACRO ALERT: Aligned Downtrend detected");
      Print("  H4: Close=", DoubleToString(h4Close, _Digits),
            " EMA=", DoubleToString(h4EMA, _Digits), " -> DOWN");
      Print("  H1: Close=", DoubleToString(h1Close, _Digits),
            " EMA=", DoubleToString(h1EMA, _Digits), " -> DOWN");
      AuditRow("signal_bar", "aligned_down", "", "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return MACROTREND_ALIGNED_DOWN;
   }

   //--- Divergence or inconclusive - stand down
   Print("MACRO DIVERGENCE: H4 and H1 trends not aligned");
   Print("  H4 Trend: ", h4Uptrend ? "UP" : (h4Downtrend ? "DOWN" : "NEUTRAL"));      Print("  H1 Trend: ", h1Uptrend ? "UP" : (h1Downtrend ? "DOWN" : "NEUTRAL"));

   AuditRow("signal_bar", "diverged", "", "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
   return MACROTREND_NONE;
}

//+------------------------------------------------------------------+
//| M30 structural entry trigger (The Springboard)                     |
//| Signal bar = previous CLOSED M30 candle (shift 1)                  |
//+------------------------------------------------------------------+
ENUM_ENTRY_SIGNAL GetM30EntrySignal(ENUM_MACROTREND macroTrend)
{
   //--- Get M30 previous candle close
   double m30Close = iClose(g_symbol, PERIOD_M30, 1);

   if(m30Close == 0)
   {
      Print("ERROR: Cannot read M30 close price");
      AuditRow("indicator_read", "", "", "m30_close_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return ENTRY_NONE;
   }
   g_auditM30Close = m30Close;

   //--- Use cached indicator values fetched via CopyBuffer in OnTick
   double bbUpper  = g_cachedBBUpper;
   double bbLower  = g_cachedBBLower;
   double rsiValue = g_cachedRSI;

   if(bbUpper == EMPTY_VALUE || bbLower == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read M30 Bollinger Bands (cached values empty)");
      AuditRow("indicator_read", "", "", "m30_bb_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return ENTRY_NONE;
   }

   if(rsiValue == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read M30 RSI (cached value empty)");
      AuditRow("indicator_read", "", "", "m30_rsi_read_failed", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
      return ENTRY_NONE;
   }

   //--- Up trend: Look for deep pullback (lower BB touch/pierce OR RSI <= 35)
   if(macroTrend == MACROTREND_ALIGNED_UP)
   {
      bool bbTrigger  = (m30Close <= bbLower);
      bool rsiTrigger = (rsiValue <= InpRSIBuyLevel);

      Print("M30 SPRINGBOARD CHECK (Bullish Macro)");
      Print("  M30 Close: ", DoubleToString(m30Close, _Digits));
      Print("  Lower BB: ", DoubleToString(bbLower, _Digits),
            " | Close <= BB Lower: ", bbTrigger);
      Print("  RSI(14): ", DoubleToString(rsiValue, 2),
            " | RSI <= ", DoubleToString(InpRSIBuyLevel, 1), ": ", rsiTrigger);

      if(bbTrigger || rsiTrigger)
      {
         //--- Branch attribution: WHICH trigger(s) fired. There is no
         //    dedicated column, so the branch rides in the `signal` token:
         //    buy_bb / buy_rsi / buy_bb_rsi.
         string branch = (bbTrigger && rsiTrigger) ? "buy_bb_rsi"
                       : (bbTrigger ? "buy_bb" : "buy_rsi");
         g_entryRegime = "aligned_up";
         g_entryBranch = branch;
         Print("ENTRY SIGNAL: BUY triggered (pullback springboard) [", branch, "]");
         AuditRow("springboard", "aligned_up", branch, "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
         return ENTRY_BUY;
      }
      AuditRow("springboard", "aligned_up", "", "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);

   }

   //--- Down trend: Look for overextension (upper BB touch/exceed OR RSI >= 65)
   if(macroTrend == MACROTREND_ALIGNED_DOWN)
   {
      bool bbTrigger  = (m30Close >= bbUpper);
      bool rsiTrigger = (rsiValue >= InpRSISellLevel);

      Print("M30 SPRINGBOARD CHECK (Bearish Macro)");
      Print("  M30 Close: ", DoubleToString(m30Close, _Digits));
      Print("  Upper BB: ", DoubleToString(bbUpper, _Digits),
            " | Close >= BB Upper: ", bbTrigger);
      Print("  RSI(14): ", DoubleToString(rsiValue, 2),
            " | RSI >= ", DoubleToString(InpRSISellLevel, 1), ": ", rsiTrigger);

      if(bbTrigger || rsiTrigger)
      {
         //--- Branch attribution: sell_bb / sell_rsi / sell_bb_rsi
         string branch = (bbTrigger && rsiTrigger) ? "sell_bb_rsi"
                       : (bbTrigger ? "sell_bb" : "sell_rsi");
         g_entryRegime = "aligned_down";
         g_entryBranch = branch;
         Print("ENTRY SIGNAL: SELL triggered (overextension springboard) [", branch, "]");
         AuditRow("springboard", "aligned_down", branch, "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
         return ENTRY_SELL;
      }
      AuditRow("springboard", "aligned_down", "", "", "", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE);
   }

   return ENTRY_NONE;
}

//+------------------------------------------------------------------+
//| Position and risk checks before entry                              |
//+------------------------------------------------------------------+
bool CanEnterTrade()
{
   //--- Check maximum position count (filter by this EA's magic only)
   int openPositions = CountPositionsByMagic();
   if(openPositions >= InpMaxPositionCount)
   {
      Print("Position limit reached: ", openPositions, " >= ", InpMaxPositionCount);
      return false;
   }

   //--- Check if we already have an open position
   if(g_isInPosition)
   {
      Print("Already in position - cannot enter new trade");
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| Count open positions belonging to this EA (by magic number)        |
//+------------------------------------------------------------------+
int CountPositionsByMagic()
{
   int count = 0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(PositionGetInteger(POSITION_MAGIC) == g_magic)
         {
            count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| STEP 1 of ExecuteTrade pipeline: derive risk inputs                |
//| ATR from the previous CLOSED H1 bar (shift 1); risk = 1% equity    |
//+------------------------------------------------------------------+
bool DeriveRiskInputs(double &atrValue, double &riskAmount)
{
   double atrBuf[];
   ArraySetAsSeries(atrBuf, true);
   if(CopyBuffer(g_hbowATR, 0, 1, 1, atrBuf) < 1 || atrBuf[0] == EMPTY_VALUE)
   {
      Print("ERROR: Cannot read H1 ATR for risk management");
      return false;
   }

   if(atrBuf[0] <= 0)
   {
      Print("ERROR: Invalid H1 ATR value for risk management");
      return false;
   }

   atrValue   = atrBuf[0];
   riskAmount = AccountInfoDouble(ACCOUNT_EQUITY) * (InpRiskPercent / 100.0);
   return true;
}

//+------------------------------------------------------------------+
//| STEP 2 of ExecuteTrade pipeline: derive protective prices          |
//| directionSign: +1 = buy, -1 = sell. SL = 2.0x ATR behind entry,    |
//| TP = InpRRMultiplier * 2.0x ATR ahead (enforces the 1:2 profile).  |
//+------------------------------------------------------------------+
void DeriveProtectivePrices(int directionSign, double entryPrice, double atrValue,
                            double &slPrice, double &tpPrice)
{
   double slDistance = 2.0 * atrValue;                    // 2.0x ATR stop loss
   double tpDistance;
   if(InpTPMode == TP_MODE_R_MULTIPLE)
   {
      //--- Data-derived target: InpTPRMultiple * initial risk (1R = slDistance)
      tpDistance = InpTPRMultiple * slDistance;
   }
   else
   {
      tpDistance = InpRRMultiplier * 2.0 * atrValue;     // 4.0x ATR take profit (1:2 RR)
   }

   slPrice = NormalizeDouble(entryPrice - directionSign * slDistance, _Digits);
   tpPrice = NormalizeDouble(entryPrice + directionSign * tpDistance, _Digits);
}

//+------------------------------------------------------------------+
//| STEP 3 of ExecuteTrade pipeline: size the position from risk       |
//| (lot math with tick-value safety overwrite lives in               |
//|  CalculateLotSize; grid normalization lives in NormalizeVolume)    |
//+------------------------------------------------------------------+
double CalculateLotSize(double riskAmount, double slDistance)
{
   //--- Get symbol specifications
   double tickValue    = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize     = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   double contractSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE);

   //--- Tick value safety check and correction
   if(InpEnableTickSafety)
   {
      double expectedTickValue = tickSize * contractSize;
      double tickValueRatio = (expectedTickValue > 0) ? (tickValue / expectedTickValue) : 1.0;

      if(MathAbs(1.0 - tickValueRatio) > 0.05)  // 5% deviation threshold
      {
         Print("TICK VALUE CORRECTION: Broker tick value deviated by >5%");
         Print("  Reported tick value: ", tickValue);
         Print("  Expected tick value: ", expectedTickValue);
         Print("  Ratio: ", DoubleToString(tickValueRatio, 4));
         tickValue = expectedTickValue;  // Overwrite with geometric identity
         Print("  Using corrected tick value: ", tickValue);
      }
   }

   //--- Calculate lot size
   // Risk = LotSize * SL_Distance * TickValue / TickSize
   // LotSize = Risk * TickSize / (SL_Distance * TickValue)

   if(tickValue == 0 || slDistance == 0)
   {
      Print("ERROR: Cannot calculate lot size - zero values detected");
      return 0;
   }

   double lotSize = (riskAmount * tickSize) / (slDistance * tickValue);

   //--- Cap at the broker maximum only. Never clamp UP to the minimum:
   //    an unaffordable position must be refused by the caller (1% risk
   //    invariant), not silently upsized into a many-percent-risk trade.
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);

   return MathMin(lotSize, maxLot);
}

//+------------------------------------------------------------------+
//| STEP 3b: single owner of volume normalization                      |
//| Floors onto the symbol's volume grid (never snaps below it, so a   |
//| 0.001 lot-step grid stays intact) and clamps to min/max.           |
//+------------------------------------------------------------------+
double NormalizeVolume(double rawVolume)
{
   double step   = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);

   double volume = rawVolume;

   if(step > 0)
   {
      volume = MathFloor(volume / step + 1e-9) * step;   // floor to the tradable grid
      volume = NormalizeDouble(volume, 8);               // strip float dust only
   }

   volume = MathMin(volume, maxLot);   // cap only - never upscale to the minimum
   return volume;
}

//+------------------------------------------------------------------+
//| STEP 4 of ExecuteTrade pipeline: send the market order             |
//+------------------------------------------------------------------+
bool SendMarketOrder(bool isBuy, double volume, double entryPrice,
                     double slPrice, double tpPrice, ulong &orderTicket)
{
   bool sent = false;
   if(isBuy)
   {
      sent = trade.Buy(volume, g_symbol, entryPrice, slPrice, tpPrice, "V75 Macro BUY");
   }
   else
   {
      sent = trade.Sell(volume, g_symbol, entryPrice, slPrice, tpPrice, "V75 Macro SELL");
   }

   if(!sent)
   {
      Print("TRADE FAILED: ", trade.ResultRetcodeDescription());
      return false;
   }

   orderTicket = trade.ResultOrder();
   return true;
}

//+------------------------------------------------------------------+
//| Execute trade - orchestrates the derive/size/send pipeline         |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ENTRY_SIGNAL entrySignal)
{
   //--- (1) derive risk inputs
   double atrValue = 0;
   double riskAmount = 0;
   if(!DeriveRiskInputs(atrValue, riskAmount))
   {
      return;
   }

   //--- entry price for the triggered direction
   bool   isBuy      = (entrySignal == ENTRY_BUY);
   int    dir        = isBuy ? +1 : -1;
   double entryPrice = isBuy ? SymbolInfoDouble(g_symbol, SYMBOL_ASK)
                             : SymbolInfoDouble(g_symbol, SYMBOL_BID);
   if(entryPrice <= 0)
   {
      Print("ERROR: Cannot get current market price");
      return;
   }

   //--- (2) derive protective prices (SL/TP once, sign-directed):
   //    SL = 2.0x ATR, TP = InpRRMultiplier x 2.0x ATR (1:2 profile)
   double slPrice = 0;
   double tpPrice = 0;
   DeriveProtectivePrices(dir, entryPrice, atrValue, slPrice, tpPrice);
   double slDistance = 2.0 * atrValue;   // effective stop distance for sizing

   //--- (3) size the position from the stop distance
   double lotSize = CalculateLotSize(riskAmount, slDistance);
   double volume  = NormalizeVolume(lotSize);

   double minLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   if(volume < minLot)
   {
      //--- 1% risk cannot be honored at the broker's minimum lot: refuse
      //    rather than silently open a many-percent-risk position.
      double contractSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE);
      double requiredEquity = minLot * slDistance * contractSize / (InpRiskPercent / 100.0);
      g_entryStatus = "Refused: min lot needs $" + DoubleToString(requiredEquity, 0) + " equity";
      Print("TRADE REFUSED: ", DoubleToString(volume, 3), " lots < broker minimum ",
            DoubleToString(minLot, 3), " - ", DoubleToString(InpRiskPercent, 1),
            "% risk cannot be honored.");
      Print("  Minimum equity for a min-lot trade at current ATR: $",
            DoubleToString(requiredEquity, 2), " (account equity: $",
            DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2), ")");
      return;
   }
   if(volume <= 0)
   {
      Print("ERROR: Invalid volume calculated: ", volume);
      return;
   }

   //--- Stage trade context. It becomes live state only after a
   //    successful send; on failure the stage is rolled back below so
   //    SyncPositionState never sees orphaned context.
   g_atrValue   = atrValue;
   g_riskAmount = riskAmount;
   g_entryPrice = entryPrice;
   g_stopLoss   = slPrice;
   g_takeProfit = tpPrice;
   g_initialSL  = slDistance;   // R-yardstick for the exit manager

   Print("=== EXECUTING TRADE ===");
   Print("Direction: ", isBuy ? "BUY" : "SELL");
   Print("Volume: ", DoubleToString(volume, 3));
   Print("Entry Price: ", DoubleToString(entryPrice, _Digits));
   Print("Stop Loss: ", DoubleToString(slPrice, _Digits),
         " (", DoubleToString(2.0 * atrValue, _Digits), " = 2.0x ATR)");
   string tpNote = (InpTPMode == TP_MODE_R_MULTIPLE) ?
                   StringFormat(" = %.2fR)", InpTPRMultiple) : " = 4.0x ATR)";
   Print("Take Profit: ", DoubleToString(tpPrice, _Digits),
         " (", DoubleToString((InpTPMode == TP_MODE_R_MULTIPLE) ?
               InpTPRMultiple * 2.0 * atrValue :
               InpRRMultiplier * 2.0 * atrValue, _Digits), tpNote);
   Print("Risk Amount: ", DoubleToString(riskAmount, 2), " = ",
         DoubleToString(InpRiskPercent, 1), "% of equity");
   Print("ATR (H1): ", DoubleToString(atrValue, _Digits));

   //--- (4) send the order
   ulong orderTicket = 0;
   if(SendMarketOrder(isBuy, volume, entryPrice, slPrice, tpPrice, orderTicket))
   {
      g_entryTime = TimeCurrent();
      g_ticket    = orderTicket;
      g_tradesExecuted++;
      g_entryStatus = "Order sent";

      Print("TRADE ORDER SENT SUCCESSFULLY");
      Print("Ticket: ", g_ticket);
      Print("Entry Time: ", TimeToString(g_entryTime));
      Print("Expiration Time: ", TimeToString(g_entryTime + InpTradeTimeoutHours * 3600));
   }
   else
   {
      //--- Nothing was sent: roll back the staged context
      g_atrValue   = 0;
      g_riskAmount = 0;
      g_entryPrice = 0;
      g_stopLoss   = 0;
      g_takeProfit = 0;
      g_initialSL  = 0;
   }
}

//+------------------------------------------------------------------+
//| Tick value safety validation (informational at init)               |
//+------------------------------------------------------------------+
void ValidateAndFixTickValue()
{
   double tickValue    = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize     = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   double contractSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE);

   Print("=== TICK VALUE SAFETY VALIDATION ===");
   Print("Symbol: ", g_symbol);
   Print("Broker reported tick value: ", tickValue);
   Print("Tick size: ", tickSize);
   Print("Contract size: ", contractSize);

   double expectedTickValue = tickSize * contractSize;
   Print("Expected tick value (tick size * contract size): ", expectedTickValue);

   if(expectedTickValue > 0)
   {
      double ratio = tickValue / expectedTickValue;
      Print("Ratio (reported/expected): ", DoubleToString(ratio, 6));

      if(MathAbs(1.0 - ratio) > 0.05)
      {
         Print("WARNING: Tick value deviation exceeds 5% threshold!");
         Print("This may cause inaccurate lot sizing. Correction enabled at lot calculation time.");
      }
      else
      {
         Print("Tick value is within acceptable range (<5% deviation).");
      }
   }
}

//+------------------------------------------------------------------+
//| PEAK-EXCURSION TRACKER - single owner of g_exitPeakR               |
//| Runs on EVERY tick while a managed position is open, independent   |
//| of the exit-manager mode. The exit manager consumes this value as  |
//| ratchet fuel, and the audit CSV publishes it as peak_r.            |
//| It used to be updated inside ManageOpenProfit(), which returns     |
//| immediately in the default EXIT_MANAGER_NONE mode - so peak_r was  |
//| written as 0.00 for every trade and the documented pipeline column |
//| carried no information exactly when the spec default was running.  |
//+------------------------------------------------------------------+
void TrackPeakExcursion()
{
   if(!g_isInPosition || g_ticket == 0 || g_initialSL <= 0)
   {
      return;   // no managed context (flat, or adopted external position)
   }
   if(!PositionSelectByTicket(g_ticket))
   {
      return;   // broker truth: nothing selectable, nothing to track
   }

   bool   isBuy      = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
   double closePrice = isBuy ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                             : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(closePrice <= 0)
   {
      return;
   }

   double excursionR = (isBuy ? (closePrice - entryPrice) : (entryPrice - closePrice)) / g_initialSL;
   if(excursionR > g_exitPeakR)
   {
      g_exitPeakR = excursionR;   // peaks are never forgotten
   }
}

//+------------------------------------------------------------------+
//| OPEN-PROFIT PROTECTION: ratchet-only exit management               |
//| Runs on EVERY tick (after the timeout guardian). Moves the SL in  |
//| the trade's favor only - it can never widen a stop - so open      |
//| profit can survive past the 3h timeout, which remains the hard    |
//| backstop. R distances are measured against the initial SL risk    |
//| (2.0x ATR at entry), matching the R accounting ledger.            |
//|   EXIT_MANAGER_BE    - one ratchet: SL to entry(+offset) at trigger |
//|   EXIT_MANAGER_TRAIL - BE step, then trail at InpTrailATRMult*ATR  |
//+------------------------------------------------------------------+
void ManageOpenProfit()
{
   if(InpExitManager == EXIT_MANAGER_NONE)
   {
      return;   // original behavior: initial SL/TP + timeout only
   }
   if(!g_isInPosition || g_ticket == 0 || g_initialSL <= 0)
   {
      return;   // no managed context (flat, or adopted external position)
   }
   if(!PositionSelectByTicket(g_ticket))
   {
      return;   // broker truth: nothing selectable, nothing to manage
   }

   bool   isBuy       = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double entryPrice  = PositionGetDouble(POSITION_PRICE_OPEN);
   double currentSL   = PositionGetDouble(POSITION_SL);
   double takeProfit  = PositionGetDouble(POSITION_TP);
   double closePrice  = isBuy ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                              : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(closePrice <= 0)
   {
      return;
   }

   //--- g_exitPeakR is owned by TrackPeakExcursion() (already updated this
   //    tick, ahead of this call); the manager only consumes it as fuel.
   if(g_exitPeakR < InpBETriggerR)
   {
      return;   // protection not armed yet
   }

   //--- desired SL: BE floor first, then (trail mode) the ATR trail,
   //    taking the TIGHTER of the two
   double offset = InpBEOffsetPoints * _Point;
   double newSL  = isBuy ? entryPrice + offset : entryPrice - offset;

   if(InpExitManager == EXIT_MANAGER_TRAIL && g_atrValue > 0)
   {
      double trailDist = InpTrailATRMult * g_atrValue;
      double trailSL   = isBuy ? closePrice - trailDist : closePrice + trailDist;
      newSL = isBuy ? MathMax(newSL, trailSL) : MathMin(newSL, trailSL);
   }

   if(!IsRatchetImprovement(newSL, currentSL, isBuy))
   {
      return;   // would widen or is not a full point better - leave it
   }

   //--- respect the broker's minimum stop distance
   double stopsLevel = (double)SymbolInfoInteger(g_symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(isBuy  && stopsLevel > 0 && newSL > bid - stopsLevel) return;
   if(!isBuy && stopsLevel > 0 && newSL < ask + stopsLevel) return;

   if(trade.PositionModify(g_ticket, NormalizeDouble(newSL, _Digits), takeProfit))
   {
      g_entryStatus = StringFormat("Managed: SL ratcheted to %s (peak %.2fR)",
                                   DoubleToString(newSL, _Digits), g_exitPeakR);
      Print("EXIT MANAGER: SL moved to ", DoubleToString(newSL, _Digits),
            " | peak excursion ", DoubleToString(g_exitPeakR, 2), "R");
   }
   else
   {
      Print("EXIT MANAGER: SL modify failed - ", trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| True only when newSL tightens the stop by at least one point       |
//+------------------------------------------------------------------+
bool IsRatchetImprovement(double newSL, double currentSL, bool isBuy)
{
   if(currentSL <= 0)
   {
      return true;   // no stop yet - anything is an improvement
   }
   return isBuy ? (newSL >= currentSL + _Point) : (newSL <= currentSL - _Point);
}

//+------------------------------------------------------------------+
//| STATE OWNER: sync trade lifecycle from broker truth                |
//| Polls the live position (symbol+magic) every tick and is the ONLY  |
//| path that promotes or retires internal trade state.                |
//+------------------------------------------------------------------+
void SyncPositionState()
{
   static int closeMisses = 0;   // consecutive syncs with no live position
   ulong liveTicket = GetPositionTicket();

   //--- Live position sighted: make internal state mirror broker truth
   if(liveTicket > 0)
   {
      closeMisses = 0;  // reset the close debounce on any sighting
      if(!PositionSelectByTicket(liveTicket))
      {
         return;  // transient selection failure - retry next tick
      }

      if(g_ticket != liveTicket)
      {
         //--- First sighting. EA-executed trades arrive with context
         //    already staged by ExecuteTrade (g_riskAmount > 0); any
         //    other position (e.g. opened manually) is adopted with
         //    zero risk context, so its close is not R-accounted.
         if(g_riskAmount <= 0)
         {
            Print("Adopting position ", liveTicket,
                  " (not opened by this EA session) - no risk context, R will not be recorded");
            g_entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
            g_stopLoss   = PositionGetDouble(POSITION_SL);
            g_takeProfit = PositionGetDouble(POSITION_TP);
            g_atrValue   = 0;
            g_riskAmount = 0;
            g_initialSL  = 0;   // external position: no R-yardstick, not managed
         }

         g_entryTime = TimeCurrent();
         g_ticket    = liveTicket;
         Print("Position adopted - in-position state committed (ticket: ", liveTicket, ")");
      }

      g_isInPosition = true;
      return;
   }

   //--- No live position: retire a stored lifecycle, with a small
   //    debounce for the order-sent-but-not-yet-visible window.
   g_isInPosition = false;

   if(g_ticket == 0)
   {
      return;  // nothing stored - nothing to reconcile
   }

   closeMisses++;

   if(closeMisses < CLOSE_DEBOUNCE_SYNCS)
   {
      return;  // may still be materializing - wait one more sync
   }
   closeMisses = 0;

   if(g_riskAmount > 0)
   {
      //--- A trade this EA executed has ended (SL/TP/timeout/human).
      //    R is accounted exactly once, here - the single cleanup path.
      AccountClosedTrade();
   }
   else
   {
      //--- Staged-but-never-confirmed order (rejected after send) or an
      //    adopted external position that vanished. Tear down quietly.
      Print("No live position matches stored ticket ", g_ticket, " - clearing state");
      ResetTradeState();
   }
}

//+------------------------------------------------------------------+
//| Account a closed trade: realized R + full state teardown           |
//| (single cleanup path - called only from SyncPositionState)         |
//+------------------------------------------------------------------+
void AccountClosedTrade()
{
   Print("=== POSITION CLOSED (SL/TP/timeout/manual) - RECONCILING ===");
   Print("  Peak favorable excursion: ", DoubleToString(g_exitPeakR, 2), "R",
         (InpExitManager != EXIT_MANAGER_NONE && g_exitPeakR < InpBETriggerR)
            ? " (below trigger - protection never armed)" : "");

   double realizedPnL = CalculateRealizedPnL();
   if(realizedPnL != EMPTY_VALUE)
   {
      if(g_riskAmount > 0)  // divide-by-zero guard on risk amount
      {
         double rMultiple = realizedPnL / g_riskAmount;
         g_cumulativeR += rMultiple;
         Print("Realized PnL: ", DoubleToString(realizedPnL, 2));
         Print("Trade R: ", DoubleToString(rMultiple, 2));
         Print("Cumulative R: ", DoubleToString(g_cumulativeR, 2));
      }
      else
      {
         Print("Realized PnL: ", DoubleToString(realizedPnL, 2),
               " (no risk context - R not recorded)");
      }
   }
   else
   {
      Print("WARNING: Could not read realized PnL from history - R not recorded");
   }

   //--- Attribution: carry the entry regime + springboard branch onto the
   //    close row, so per-branch / per-regime outcome stats need no fragile
   //    timestamp pairing against the entry bar.
   AuditRow("trade_closed", g_entryRegime, g_entryBranch, "closed", "", g_exitPeakR, realizedPnL,
            (realizedPnL != EMPTY_VALUE && g_riskAmount > 0) ? realizedPnL / g_riskAmount : EMPTY_VALUE);

   ResetTradeState();
}

//+------------------------------------------------------------------+
//| Clear all trade lifecycle state (single teardown point)            |
//+------------------------------------------------------------------+
void ResetTradeState()
{
   g_isInPosition = false;
   g_ticket       = 0;
   g_entryTime    = 0;
   g_entryPrice   = 0;
   g_stopLoss     = 0;
   g_takeProfit   = 0;
   g_riskAmount   = 0;
   g_atrValue     = 0;
   g_initialSL    = 0;
   g_exitPeakR    = 0.0;
   g_entryRegime  = "";
   g_entryBranch  = "";
}

//+------------------------------------------------------------------+
//| 3-Hour hard timeout guardian - runs on EVERY tick                  |
//| Force-closes via market liquidation; R accounting is left to the   |
//| single cleanup path in SyncPositionState (counted exactly once).   |
//+------------------------------------------------------------------+
void CheckTradeTimeout()
{
   if(!g_isInPosition || g_ticket == 0)
   {
      return;  // No active position to monitor
   }

   datetime currentTime    = TimeCurrent();
   datetime expirationTime = g_entryTime + (InpTradeTimeoutHours * 3600);

   if(currentTime < expirationTime)
   {
      return;
   }

   Print("=== TIMEOUT EXPIRED - FORCING CLOSE ===");
   Print("Entry time: ", TimeToString(g_entryTime));
   Print("Expiration time: ", TimeToString(expirationTime));
   Print("Current time: ", TimeToString(currentTime));

   if(ForceClosePosition())
   {
      Print("Position force-closed due to timeout expiration");
      // State teardown + R accounting happen in SyncPositionState when
      // the closed position stops appearing in the broker pool.
   }
   else
   {
      Print("ERROR: Failed to force close position - will retry next tick");
   }
}

//+------------------------------------------------------------------+
//| Force close position via market order                              |
//| CTrade::PositionClose sends the correct close-side order (SELL to  |
//| close a BUY / BUY to close a SELL) for the full position volume.   |
//| Partial close is not implemented - the whole position is closed.   |
//+------------------------------------------------------------------+
bool ForceClosePosition()
{
   if(g_ticket <= 0)
   {
      return false;
   }

   //--- Select position by ticket BEFORE reading position properties
   if(!PositionSelectByTicket(g_ticket))
   {
      // Position is already gone (SL/TP/manual) - the sync path will
      // reconcile state; there is nothing left to force-close.
      Print("Position ", g_ticket, " no longer selectable - nothing to force-close");
      return false;
   }

   //--- Read position context (now that selection is set)
   long   type           = PositionGetInteger(POSITION_TYPE);
   double positionVolume = PositionGetDouble(POSITION_VOLUME);

   Print("Force-closing position ", g_ticket, " (",
         (type == POSITION_TYPE_BUY ? "BUY" : "SELL"), " ",
         DoubleToString(positionVolume, 2), " lots)");

   if(trade.PositionClose(g_ticket))
   {
      Print("Position ", g_ticket, " closed via market order");
      return true;
   }

   Print("ERROR: PositionClose failed for ticket ", g_ticket,
         " retcode: ", trade.ResultRetcode(), " - ", trade.ResultRetcodeDescription());
   return false;
}

//+------------------------------------------------------------------+
//| Find this EA's open position ticket (symbol + magic filter)        |
//+------------------------------------------------------------------+
ulong GetPositionTicket()
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
            PositionGetInteger(POSITION_MAGIC) == g_magic)
         {
            return ticket;
         }
      }
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Fetch M30 indicator values via CopyBuffer (robust read)            |
//| iBands buffers: 0 = base(middle), 1 = UPPER band, 2 = LOWER band   |
//| All reads use shift 1 = previous CLOSED M30 bar                    |
//+------------------------------------------------------------------+
void FetchM30IndicatorValues()
{
   //--- Fetch Bollinger Bands upper (buffer 1) and lower (buffer 2)
   if(g_hbowBB != INVALID_HANDLE)
   {
      double bbBuffer[];
      ArraySetAsSeries(bbBuffer, true);

      // Copy upper band (buffer 1)
      if(CopyBuffer(g_hbowBB, 1, 1, 1, bbBuffer) > 0)
      {
         g_cachedBBUpper = bbBuffer[0];
      }
      else
      {
         g_cachedBBUpper = EMPTY_VALUE;
      }

      // Copy lower band (buffer 2)
      if(CopyBuffer(g_hbowBB, 2, 1, 1, bbBuffer) > 0)
      {
         g_cachedBBLower = bbBuffer[0];
      }
      else
      {
         g_cachedBBLower = EMPTY_VALUE;
      }
   }
   else
   {
      g_cachedBBUpper = EMPTY_VALUE;
      g_cachedBBLower = EMPTY_VALUE;
   }

   //--- Fetch RSI (single buffer)
   if(g_hbowRSI != INVALID_HANDLE)
   {
      double rsiBuffer[];
      ArraySetAsSeries(rsiBuffer, true);

      if(CopyBuffer(g_hbowRSI, 0, 1, 1, rsiBuffer) > 0)
      {
         g_cachedRSI = rsiBuffer[0];
      }
      else
      {
         g_cachedRSI = EMPTY_VALUE;
      }
   }
   else
   {
      g_cachedRSI = EMPTY_VALUE;
   }
}

//+------------------------------------------------------------------+
//| Calculate realized PnL from the most recent closed deal (MQL5 API) |
//+------------------------------------------------------------------+
double CalculateRealizedPnL()
{
   double lastPnL = EMPTY_VALUE;

   //--- Select full deal history up to now (+60s boundary margin)
   if(!HistorySelect(0, TimeCurrent() + 60))
   {
      Print("ERROR: HistorySelect failed - cannot read realized PnL");
      return EMPTY_VALUE;
   }

   //--- Search backwards through deals for this EA's most recent closing deal
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket > 0)
      {
         if(HistoryDealGetInteger(dealTicket, DEAL_MAGIC) == g_magic &&
            HistoryDealGetString(dealTicket, DEAL_SYMBOL) == g_symbol)
         {
            long entryType = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
            if(entryType == DEAL_ENTRY_OUT || entryType == DEAL_ENTRY_OUT_BY)
            {
               lastPnL = HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
                       + HistoryDealGetDouble(dealTicket, DEAL_SWAP)
                       + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
               break;
            }
         }
      }
   }

   return lastPnL;
}

//+------------------------------------------------------------------+
//| Dashboard HUD - Text-based display on chart                        |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   //--- Calculate session metrics
   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double sessionPnL = currentEquity - g_startEquity;

   //--- Calculate countdown timer if in position
   string countdown = "N/A";
   if(g_isInPosition && g_entryTime > 0)
   {
      datetime expirationTime = g_entryTime + (InpTradeTimeoutHours * 3600);
      int remainingSeconds = (int)(expirationTime - TimeCurrent());

      if(remainingSeconds > 0)
      {
         int hours   = remainingSeconds / 3600;
         int minutes = (remainingSeconds % 3600) / 60;
         int seconds = remainingSeconds % 60;
         countdown = StringFormat("%02d:%02d:%02d", hours, minutes, seconds);
      }
      else
      {
         countdown = "EXPIRED";
      }
   }

   //--- Build dashboard text
   string dashboard = "+======================================================+\n";
   dashboard += "|          V75 MACRO INFERENCE ENGINE                   |\n";
   dashboard += "+======================================================+\n";
   dashboard += "| Symbol: " + g_symbol + StringRepeat(" ", 28 - StringLen(g_symbol)) + "|\n";
   dashboard += "| Equity: " + DoubleToString(currentEquity, 2) + StringRepeat(" ", 33 - StringLen(DoubleToString(currentEquity, 2))) + "|\n";
   dashboard += "| Session PnL: " + (sessionPnL >= 0 ? "+" : "") + DoubleToString(sessionPnL, 2) + StringRepeat(" ", 28 - StringLen(DoubleToString(sessionPnL, 2))) + "|\n";
   dashboard += "| Cumulative R: " + DoubleToString(g_cumulativeR, 2) + StringRepeat(" ", 31 - StringLen(DoubleToString(g_cumulativeR, 2))) + "|\n";
   dashboard += "| Trades Executed: " + IntegerToString(g_tradesExecuted) + StringRepeat(" ", 25 - StringLen(IntegerToString(g_tradesExecuted))) + "|\n";
   dashboard += "+------------------------------------------------------+\n";
   dashboard += "| CURRENT TRADE STATUS                                  |\n";
   dashboard += "+------------------------------------------------------+\n";

   //--- Read position properties only after selecting the position
   //    by ticket (PositionSelectByTicket sets the property context)
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      long   type      = PositionGetInteger(POSITION_TYPE);
      string posType   = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl        = PositionGetDouble(POSITION_SL);
      double tp        = PositionGetDouble(POSITION_TP);
      double lots      = PositionGetDouble(POSITION_VOLUME);

      dashboard += "| Position: " + posType + StringRepeat(" ", 40 - StringLen(posType)) + "|\n";
      dashboard += "| Entry: " + DoubleToString(openPrice, _Digits) + StringRepeat(" ", 38 - StringLen(DoubleToString(openPrice, _Digits))) + "|\n";
      dashboard += "| SL: " + (sl > 0 ? DoubleToString(sl, _Digits) : "N/A") + StringRepeat(" ", 40 - StringLen(sl > 0 ? DoubleToString(sl, _Digits) : "N/A")) + "|\n";
      dashboard += "| TP: " + (tp > 0 ? DoubleToString(tp, _Digits) : "N/A") + StringRepeat(" ", 40 - StringLen(tp > 0 ? DoubleToString(tp, _Digits) : "N/A")) + "|\n";
      dashboard += "| Lots: " + DoubleToString(lots, 2) + StringRepeat(" ", 39 - StringLen(DoubleToString(lots, 2))) + "|\n";
      dashboard += "| Time Remaining: " + countdown + StringRepeat(" ", 28 - StringLen(countdown)) + "|\n";
      string exitMode = (InpExitManager == EXIT_MANAGER_NONE) ? "off (SL/TP + timeout)" :
                        (InpExitManager == EXIT_MANAGER_BE)   ? StringFormat("breakeven @ %.1fR", InpBETriggerR) :
                                                                StringFormat("BE @ %.1fR + trail %.1fxATR", InpBETriggerR, InpTrailATRMult);
      string tpModeStr = (InpTPMode == TP_MODE_ATR_MULTIPLE) ? "4xATR" :
                         StringFormat("%.2fR", InpTPRMultiple);
      dashboard += "| Exit Mgmt: " + exitMode + StringRepeat(" ", 30 - StringLen(exitMode)) + "|\n";
      dashboard += "| TP Mode: " + tpModeStr + StringRepeat(" ", 34 - StringLen(tpModeStr)) + "|\n";
      dashboard += "| Peak Excursion: " + DoubleToString(g_exitPeakR, 2) + "R" + StringRepeat(" ", 27 - StringLen(DoubleToString(g_exitPeakR, 2) + "R")) + "|\n";
      dashboard += "| ATR (H1): " + DoubleToString(g_atrValue, _Digits) + StringRepeat(" ", 34 - StringLen(DoubleToString(g_atrValue, _Digits))) + "|\n";
   }
   else
   {
      dashboard += "| No Active Position                                    |\n";
      string statusLine = StringSubstr(g_entryStatus, 0, 44);
      dashboard += "| Status: " + statusLine + StringRepeat(" ", 45 - StringLen(statusLine)) + "|\n";
      dashboard += "|                                                       |\n";
   }

   dashboard += "+======================================================+\n";
   string exitTag = (InpExitManager == EXIT_MANAGER_NONE) ? "timeout only" :
                    (InpExitManager == EXIT_MANAGER_BE)   ? "BE + timeout" : "BE + trail + timeout";
   dashboard += "V75 Macro Engine | Risk: " + DoubleToString(InpRiskPercent, 1) + "% | RR: 1:" + DoubleToString(InpRRMultiplier, 1) + " | Timeout: " + IntegerToString(InpTradeTimeoutHours) + "h | Exits: " + exitTag +
             " | Audit: " + (InpAuditCsv ? "on" : "off");

   //--- Display on chart
   Comment(dashboard);
}

//+------------------------------------------------------------------+
//| Helper function to repeat a character                              |
//+------------------------------------------------------------------+
string StringRepeat(string text, int totalLength)
{
   int currentLen = StringLen(text);
   if(currentLen >= totalLength)
   {
      return "";
   }

   string result = "";
   for(int i = 0; i < (totalLength - currentLen); i++)
   {
      result += " ";
   }
   return result;
}
//+------------------------------------------------------------------+

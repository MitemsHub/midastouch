//+------------------------------------------------------------------+
//| MidasOffsetProbe.mq5 — SCRIPT (drag onto any chart once; it      |
//| prints to the Experts/Journal tab and exits).                    |
//|                                                                  |
//| Purpose: verify the BROKER-SERVER-vs-UTC offset before the live  |
//| gate (MIDASTOUCH_HEALTH_GUIDE.md §3, P0 #2 remediation).         |
//|                                                                  |
//| It prints three clocks and the derived offset, then the checks   |
//| an operator performs against an external UTC source:             |
//|   1. server    = TimeCurrent()   (broker's trading clock)        |
//|   2. mqlGMT    = TimeGMT()       (what the EA's TimeUTCNow() uses)|
//|   3. offset    = server - mqlGMT                                 |
//| plus MQL5's own declared server timezone properties for          |
//| cross-checking.                                                  |
//|                                                                  |
//| Interpretation (full walk-through in the health guide):          |
//|   • mqlGMT must equal true UTC within ~1 min. If it does not,    |
//|     TimeGMT() is wrong on this machine/terminal build and the    |
//|     EA MUST NOT go live until that is understood.                |
//|   • The offset is informational: the EA's TimeUTCNow()-based     |
//|     gates (and the UTC classification of broker-feed bar epochs) |
//|     (daily breaker, Friday flat, live timeout) are correct       |
//|     regardless of its value. It matters for reading server-      |
//|     stamped ledgers/logs next to UTC-scheduled ops (morning      |
//|     status, watchdog clocks).                                    |
//|   • A DST change shifts the offset (most gold brokers are        |
//|     UTC+2 winter / UTC+3 summer, i.e. NY-close-anchored).        |
//|     Re-run this probe after every DST transition.                |
//+------------------------------------------------------------------+
#property copyright "MIDASTOUCH"
#property version   "1.00"
#property script_show_inputs

void OnStart()
{
   datetime srv = TimeCurrent();
   datetime gmt = TimeGMT();
   long off_min = (long)(srv - gmt) / 60;
   int oh = (int)(off_min / 60);          // C truncation toward zero
   long abs_min = (off_min < 0) ? -off_min : off_min;
   int om = (int)(abs_min % 60);          // MQL5: % is integer-only

   int dom = (int)SymbolInfoInteger(_Symbol, SYMBOL_TIME);   // may be 0 if unsupported
   PrintFormat("MIDAS OFFSET PROBE on %s", _Symbol);
   PrintFormat("  server (TimeCurrent)  = %s", TimeToString(srv, TIME_DATE|TIME_SECONDS));
   PrintFormat("  mqlGMT  (TimeGMT)     = %s   <-- compare with an external UTC clock NOW",
               TimeToString(gmt, TIME_DATE|TIME_SECONDS));
   PrintFormat("  offset (server-GMT)   = %+d h %02d min", oh, om);
   PrintFormat("  SYMBOL_TIME raw       = %I64d (0 = broker does not declare one)", (long)dom);
   Print("  CHECK 1: open a UTC clock (e.g. time.is/UTC). Does mqlGMT match it within ~1 minute?");
   Print("           NO  -> DO NOT attach the live preset; TimeGMT is untrustworthy on this build; investigate.");
   Print("           YES -> TimeGMT-based gates are correct; proceed with the checklist.");
   Print("  CHECK 2: note the offset. Server-stamped ledger rows (provenance) read as UTC+offset.");
   Print("  CHECK 3: re-run after every DST transition (offsets move by 1 h).");
}
//+------------------------------------------------------------------+

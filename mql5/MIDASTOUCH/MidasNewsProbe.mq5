//+------------------------------------------------------------------+
//| MidasNewsProbe.mq5 — the economic calendar, written down.        |
//|                                                                  |
//| WHY THIS EXISTS. The playbook's standing policy has always said  |
//| "no new entries in a +/-15-minute window around top-tier USD      |
//| releases", and the EA has never been able to honour it: the       |
//| Python side has no calendar API at all (MetaTrader5 5.0.5735      |
//| exposes 269 names, none calendar-related), and R6 therefore       |
//| registered the honest refusal — InpUseNewsFilter=true was an      |
//| INIT_FAILED, because inventing a calendar was worse than none.    |
//|                                                                  |
//| MQL5 *can* read the calendar (CalendarValueHistory). This probe   |
//| is the bridge: it queries it and WRITES IT DOWN, so the EA and    |
//| the Python research engine can both read the same events. That    |
//| shared file is the point — a filter only one engine could see     |
//| would be a rule the parity contract cannot replay, and this repo  |
//| does not ship rules it cannot replay.                             |
//|                                                                  |
//| USAGE (the same file works in both places):                       |
//|   live   : attach it to any chart once (Expert Advisors -> drag); |
//|            it writes the file, prints a summary and removes        |
//|            itself. It sends no orders and opens nothing.          |
//|   tester : run it as an Expert for a short recent window — the    |
//|            tester's Files sandbox gets the same file, and the     |
//|            journal says whether the API is even available there.  |
//|            The economic calendar is documented as NOT available   |
//|            in the Strategy Tester, so this probe reports rather   |
//|            than assumes: it prints the return value and           |
//|            GetLastError() either way, and says plainly that a     |
//|            zero count is "cannot see the news", never "no news".  |
//|                                                                  |
//| It is an EA rather than a script (unlike MidasOffsetProbe) for    |
//| exactly one reason: an Expert can also be run headlessly in the   |
//| tester, so the availability of this venue's calendar is a         |
//| measured fact on both paths instead of an assumption.             |
//|                                                                  |
//| OUTPUT  : MQL5\Files\MIDASTOUCH_news_calendar.csv                 |
//|   # generated_at_utc=... / generated_at_server=... /             |
//|   # server_offset_min=... / window_from_utc=... / window_to_utc=  |
//|   # source=mt5_economic_calendar / events=<n> / errors=<n>        |
//|   epoch_utc;time_utc;time_server;currency;country;importance;event |
//|                                                                  |
//| EPOCHS ARE NUMERIC ON PURPOSE. The first column and the two        |
//| `epoch_*` headers are Unix seconds (UTC). A reader that has to      |
//| interpret a date string has to guess whose timezone wrote it, and   |
//| this program has already paid for one clock mistake — the EA and    |
//| the Python mirror both compare numbers and never parse a date.      |
//|                                                                  |
//| The reader refuses a file that is missing, stale, empty, or does  |
//| not cover "now" — an empty calendar is not "no news", it is       |
//| "we cannot see the news", and the two must never be confused.     |
//+------------------------------------------------------------------+
#property copyright "MIDASTOUCH"
#property version   "1.00"
#property script_show_inputs

input int InpDaysBack = 14;      // calendar window: days back from now
input int InpDaysAhead = 21;     // calendar window: days ahead of now
input string InpCurrency = "USD"; // currency filter ("" = all)
input bool InpHighOnly = false;  // write only HIGH-importance events
input string InpFileName = "MIDASTOUCH_news_calendar.csv";

//+------------------------------------------------------------------+
string ImportanceName(ENUM_CALENDAR_EVENT_IMPORTANCE imp)
{
   switch(imp)
   {
      case CALENDAR_IMPORTANCE_HIGH:     return "HIGH";
      case CALENDAR_IMPORTANCE_MODERATE: return "MEDIUM";
      case CALENDAR_IMPORTANCE_LOW:      return "LOW";
   }
   return "NONE";
}

//+------------------------------------------------------------------+
//| Field clean-up: ';' is the separator and '#' starts a comment.   |
//+------------------------------------------------------------------+
string Clean(string s)
{
   StringReplace(s, ";", ",");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   StringReplace(s, "#", "-");
   return s;
}

//+------------------------------------------------------------------+
string IsoUtc(datetime t)
{
   return TimeToString(t, TIME_DATE | TIME_SECONDS) + "Z";
}

//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| The probe's whole body. Returns the number of events written.    |
//+------------------------------------------------------------------+
int WriteCalendar()
{
   datetime now_server = TimeCurrent();      // last TICK's time: stale for minutes after a launch
   datetime now_gmt    = TimeGMT();
   // MEASURED 2026-09-21. Deriving the offset from `now_server` produced `server_offset_min=-318`
   // for a UTC+2 venue, and every `time_server` / `window_*` header in the file inherited the
   // error (the `epoch_utc` column did not — it was, and still is, correct). `TimeTradeServer()`
   // is the terminal's own calculated server time, available before the first tick, so the
   // headers are now written from it and the stale tick clock is recorded beside it.
   datetime trade_server = TimeTradeServer();
   long     off_min      = (long)((trade_server - now_gmt) / 60);
   long     off_tick_min = (long)((now_server - now_gmt) / 60);

   datetime from = trade_server - (datetime)(InpDaysBack * 86400);
   datetime to   = trade_server + (datetime)(InpDaysAhead * 86400);

   MqlCalendarValue values[];
   ResetLastError();
   int n = CalendarValueHistory(values, from, to, NULL,
                                (InpCurrency == "") ? NULL : InpCurrency);
   int err = GetLastError();

   PrintFormat("MIDAS NEWS PROBE on %s", _Symbol);
   PrintFormat("  window   = %s -> %s (server clock)",
               TimeToString(from, TIME_DATE | TIME_MINUTES),
               TimeToString(to, TIME_DATE | TIME_MINUTES));
   PrintFormat("  currency = %s   high_only = %s", InpCurrency, InpHighOnly ? "true" : "false");
   PrintFormat("  CalendarValueHistory -> %d value(s), GetLastError=%d", n, err);
   if(n <= 0)
      Print("  MEASURED RESULT: the calendar returned NOTHING. Either this terminal has "
            "news disabled (Tools > Options > Server > Enable news), the venue serves no "
            "calendar, or the call is unavailable here (the Strategy Tester is documented "
            "as not supporting the economic calendar). DO NOT treat this as 'no news'.");

   int written = 0, high = 0, errors = 0;
   int fh = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
   {
      PrintFormat("  FAIL: cannot open %s for write (err=%d)", InpFileName, GetLastError());
      return -1;
   }

   // Header lines carry the provenance and the freshness a reader must check.
   FileWriteString(fh, "# MIDASTOUCH news calendar — written by MidasNewsProbe.mq5\r\n");
   FileWriteString(fh, StringFormat("# generated_at_utc=%s\r\n", IsoUtc(now_gmt)));
   FileWriteString(fh, StringFormat("# epoch_generated_utc=%I64d\r\n", (long)now_gmt));
   FileWriteString(fh, StringFormat("# generated_at_server=%s\r\n",
                                    TimeToString(trade_server, TIME_DATE | TIME_SECONDS)));
   FileWriteString(fh, StringFormat("# generated_at_server_last_tick=%s\r\n",
                                    TimeToString(now_server, TIME_DATE | TIME_SECONDS)));
   FileWriteString(fh, StringFormat("# server_offset_min=%I64d\r\n", off_min));
   FileWriteString(fh, "# server_offset_source=TimeTradeServer (terminal-calculated)\r\n");
   FileWriteString(fh, StringFormat("# server_offset_min_from_last_tick=%I64d\r\n", off_tick_min));
   FileWriteString(fh, StringFormat("# window_from_utc=%s\r\n",
                                    IsoUtc(from - (datetime)(off_min * 60))));
   FileWriteString(fh, StringFormat("# window_to_utc=%s\r\n",
                                    IsoUtc(to - (datetime)(off_min * 60))));
   FileWriteString(fh, StringFormat("# epoch_window_from_utc=%I64d\r\n",
                                    (long)(from - (datetime)(off_min * 60))));
   FileWriteString(fh, StringFormat("# epoch_window_to_utc=%I64d\r\n",
                                    (long)(to - (datetime)(off_min * 60))));
   FileWriteString(fh, "# source=mt5_economic_calendar\r\n");
   FileWriteString(fh, StringFormat("# currency=%s\r\n", InpCurrency));
   FileWriteString(fh, StringFormat("# high_only=%s\r\n", InpHighOnly ? "true" : "false"));
   FileWriteString(fh, StringFormat("# api_returned=%d\r\n", n));

   string body = "";
   for(int i = 0; i < ArraySize(values); i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
      {
         errors++;
         continue;
      }
      if(InpHighOnly && ev.importance != CALENDAR_IMPORTANCE_HIGH)
         continue;
      if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
         high++;

      // The currency is a property of the COUNTRY, not of the event: MqlCalendarEvent
      // has no `currency` field (measured — declaring one is compile error 256). So the
      // country is resolved first, and the row records both rather than assuming the
      // query filter told us which currency a row belongs to.
      MqlCalendarCountry country;
      string cur = "";
      string ccode = "";
      if(CalendarCountryById(long(ev.country_id), country))
      {
         cur   = country.currency;
         ccode = country.code;
      }

      // Event times arrive on the SERVER clock; the UTC column is derived with the
      // measured offset so a reader never has to guess which clock it is looking at.
      datetime t_srv = values[i].time;
      datetime t_utc = t_srv - (datetime)(off_min * 60);
      body += StringFormat("%I64d;%s;%s;%s;%s;%s;%s\r\n",
                           (long)t_utc,
                           IsoUtc(t_utc),
                           TimeToString(t_srv, TIME_DATE | TIME_SECONDS),
                           Clean(cur),
                           Clean(ccode),
                           ImportanceName(ev.importance),
                           Clean(ev.name));
      written++;
   }

   FileWriteString(fh, StringFormat("# events=%d\r\n", written));
   FileWriteString(fh, StringFormat("# high_importance=%d\r\n", high));
   FileWriteString(fh, StringFormat("# resolution_errors=%d\r\n", errors));
   FileWriteString(fh, "epoch_utc;time_utc;time_server;currency;country;importance;event\r\n");
   FileWriteString(fh, body);
   FileClose(fh);

   PrintFormat("  wrote %s: %d event(s) (%d HIGH, %d unresolvable) into %s",
               InpFileName, written, high, errors, TerminalInfoString(TERMINAL_DATA_PATH));
   if(MQLInfoInteger(MQL_TESTER))
      Print("  (tester run: the file is in the agent's own MQL5\\Files sandbox)");
   else
      Print("  NEXT: no hand-import step. MidastouchAI refreshes this file itself when "
            "InpUseNewsFilter=true (live terminal only — the tester cannot call the "
            "calendar, error 4014), and this probe exists to MEASURE: if the count above "
            "is 0, the EA's own refresh gets 0 too and the gate stands down rather than "
            "trade on a calendar it cannot see.");
   return written;
}

//+------------------------------------------------------------------+
int OnInit()
{
   WriteCalendar();
   // A live attach is a one-shot measurement: write, report, leave the chart as found.
   // In the tester, removing the Expert during init would end the pass early, so the
   // pass simply runs its (empty) window and the report lands normally.
   if(!MQLInfoInteger(MQL_TESTER))
      ExpertRemove();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTick() { /* probe only: no trading, no orders, no state */ }
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+

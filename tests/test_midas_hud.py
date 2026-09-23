"""Offline source tests for the MidastouchAI v1.10 display-only HUD.

Parses the EA source and pins the HUD discipline without touching a
terminal: the HUD may never run inside the strategy tester (parity runs
need byte-identical ledgers and untouched charts), every state it shows
must already exist in the paper ledger or the pinned inputs, no trading
path may draw, BAR-mode functions stay pristine except a documented
post-close epilogue, and the version tag must be consistent everywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
PRESET = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_M1_gold.set"


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


def strip_strings(s: str) -> str:
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)


def body(fn_name: str) -> str:
    """Brace-matched body of a named function (any return type)."""
    s = src()
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", s)
    assert m, f"{fn_name} missing from source"
    j = s.index("{", m.end())
    depth = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j:k]
    raise AssertionError(f"unbalanced braces after {fn_name}")


# --- the display-only law ----------------------------------------------------

def test_hud_is_tester_gated_first() -> None:
    b = body("HudUpdate")
    head = re.sub(r"^\s*//.*$", "", b.split("\n", 1)[1], flags=re.M)
    assert re.search(r"if\s*\(\s*MQLInfoInteger\s*\(\s*MQL_TESTER\s*\)\s*\)\s*return\s*;",
                     head), "HudUpdate must return immediately in the tester"


def test_exactly_one_comment_call_in_code() -> None:
    code = strip_comments(src())
    assert len(re.findall(r"\bComment\s*\(", code)) == 1


def test_hud_state_is_ledger_backed_only() -> None:
    allowed = {
        # MQL grammar
        "if", "return", "string", "int", "double", "bool", "void", "long",
        "case", "switch", "default", "true", "false",
        # calls the HUD is allowed to make
        "MQLInfoInteger", "MQL_TESTER", "StringFormat", "Comment",
        "ModeName", "PaperEquity",
        # pinned inputs (displayed verbatim)
        "InpMode", "InpSessionStartHour", "InpSessionEndHour",
        # v1.19 P6 build block: the entry TF is config echo (rides the ERA
        # note's citation class), displayed via EnumToString
        "InpEntryTF", "EnumToString",
        # paper state (already in the ledger: EQ/CLOSE/OPEN rows)
        "APP_VERSION", "g_pp_open", "g_pp_dir", "g_paper_start",
        "g_trades", "g_wins", "g_cum_r",
        # live adoption state (already in the ledger: LOPEN/LCLOSE rows;
        # v1.11 rows carry the position IDENTIFIER as the reconciliation key)
        "g_lv_posid", "g_lv_dir",
        # v1.18 NOFILL counters (the HUD eval line mirrors exactly the
        # counters written into the daily NOFILL ledger row)
        "g_nofill_signal", "g_nofill_mism", "g_nofill_notr",            "g_nofill_session", "g_nofill_spread",
            # v1.27 the tenth census counter: a bar the engine could not price. Ledger-backed
            # exactly like its nine siblings (NOFILLSUM snapshot + NOFILL roll), and read here
            # only to print the `nodata` count on the V: line.
            "g_nofill_nodata",
        # HUD state itself + the local pos label
        "g_last_action", "pos",
        # v1.21 the HUD VIEW: six display helpers that print the engine's own view. They
        # read only what the DECISION path stashed (regime parts, trigger, RSI, session
        # flag, governor readings) or a pure read of the instrument (ATR, spread, spec),
        # and StateRowWrite() serialises the same numbers into the ledger's STATE row —
        # so the chart cannot become a second source of truth. Pinned by
        # test_hud_view_layer_is_read_only and test_state_row_shares_the_hud_computation.
        "RegimeText", "TriggerText", "GateText", "SizingText", "GovernorText",
        "NewsText",
        # v1.24 the arm's realized record: read-only, ledger-backed (LCLOSE rows, the same
        # source every CLI reader counts), and it NAMES which tally it is printing. See
        # LiveCensusRestoreFromLedger and test_the_hud_tally_counts_the_arms_own_record.
        "TradesText",
        # v1.26 the ARM's equity: the account's on the live path, the paper book's on the
        # paper path — the number the governor reads and the heartbeat writes. Read-only,
        # sourced from the venue (or the paper book) and never from a decision path. See
        # test_the_equity_line_names_the_record_it_is_reading.
        "EquityText",
    }
    b = strip_strings(strip_comments(body("HudUpdate")))
    ids = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", b))
    assert ids - allowed == set(), f"HUD reads non-ledger state: {sorted(ids - allowed)}"


# --- where the HUD may and may not appear ------------------------------------

BAR_FUNCS = ["OnBarReplay", "ReplayThrough", "ReplayTailFlush",
             "BarFillAndManage", "BarManage", "BarEvaluateSignal"]


def test_bar_functions_never_draw_or_refresh() -> None:
    for fn in BAR_FUNCS:
        b = body(fn)
        assert "Comment(" not in strip_comments(b), f"{fn} must not draw"
        assert "HudUpdate()" not in strip_comments(b), f"{fn} must not refresh the HUD"


def test_bar_close_marker_is_post_close_epilogue_only() -> None:
    """The single g_last_action write allowed in BAR mode is BarManage's
    post-close epilogue: it must come AFTER the CLOSE row is logged and may
    only restate values that row already carries (reason, r, equity, close
    time). Pre-close decisions must stay byte-neutral for parity."""
    b = strip_comments(body("BarManage"))
    writes = [m.start() for m in re.finditer(r"g_last_action\s*=", b)]
    assert len(writes) <= 1, "BAR functions get at most the post-close epilogue"
    if writes:
        close_log = b.index('PaperLog(StringFormat("CLOSE')
        assert writes[0] > close_log, "epilogue must follow the CLOSE ledger row"
        epilogue = b[writes[0]:b.index(";", writes[0])]
        for tok in ("reason", "r", "g_paper_eq"):
            assert tok in epilogue, f"epilogue may only restate ledger values ({tok})"


def test_last_action_writes_confined_to_pertick_and_live_paths() -> None:
    for fn in ["TrackFreshM15Bar", "OpenPaperPosition", "PaperClose",
               "LiveSendOrder", "LiveClosePosition", "LiveCheckExits"]:
        body(fn)  # must exist
    for fn in BAR_FUNCS:
        if fn == "BarManage":
            continue
        b = strip_comments(body(fn))
        assert "g_last_action" not in b, f"{fn} must not touch HUD state"


def test_hud_hooks_land_on_live_only_paths() -> None:
    s = src()
    assert "LiveRecoverState();                 // v1.08: adopt real positions after restart (live only)\n   HudUpdate();" in s, "OnInit must bring the HUD up"
    on_timer = strip_comments(body("OnTimer"))
    # v1.26: the heartbeat's EQ row goes out through LogEquityRow() (one write site, so the
    # record's basis cannot drift from the display's again). Either form satisfies the rule
    # being pinned here — the ledger is touched BEFORE the chart is — and the helper is
    # asserted to be a real ledger write rather than a rename.
    log_at = min((on_timer.index(tok) for tok in ("LogEquityRow(", "PaperLog(")
                   if tok in on_timer), default=-1)
    assert log_at >= 0, "OnTimer must write the ledger (the mtime IS the liveness signal)"
    assert log_at < on_timer.index("HudUpdate();"), \
        "OnTimer heartbeat must log first, draw second"
    assert '"EQ,%.2f"' in body("LogEquityRow") and "DisplayEquity()" in body("LogEquityRow"), \
        "LogEquityRow must write the arm's own equity through one site"
    on_tick = body("OnTick")
    assert "HudUpdate();" in on_tick
    for fn in ("OnBarReplay", "LiveOnTick"):
        assert "HudUpdate();" not in strip_comments(body(fn)), f"{fn} must not refresh the HUD"


# --- version consistency (the #property had been stale since v1.06) ----------

def test_the_equity_line_names_the_record_it_is_reading() -> None:
    """THE NUMBER THE OPERATOR CHECKS AGAINST, AND IT WAS THE PAPER BOOK'S FROZEN COUNTER.

    MEASURED 2026-09-22 from the operator's own screenshot: the account held 25,004.26 while the
    chart printed `vEq: $25,000.00 (start $25,000.00)` and the ledger's heartbeat printed
    `EQ,25000.00`. On an ARMED arm the paper book never trades (`LiveSendOrder` is the only entry
    path that runs), so `g_paper_eq` is a constant — and equity is what the governor's shield and
    day caps are read from, so the chart disagreed with the figure the RISK RULES use.

    One meaning, two books, and the label says which: the paper form is v1.10's verbatim (BAR and
    tester ledgers must not move), the live form reads the venue and names the basis.
    """
    live = body("EquityText")
    assert "InpLiveExecution" in live, "the basis is chosen by the arming input"
    assert "AccountInfoDouble(ACCOUNT_EQUITY)" in live, \
        "the live arm's equity line must read the venue, not the paper counter"
    assert "g_paper_eq" not in live, "and never the paper book's equity"
    assert 'vEq: $%.2f (start $%.2f)' in live, "the paper form stays v1.10's, verbatim"
    # the label cannot be a bare number: it must say whose equity it is showing
    assert "acct" in live and "basis" in live, (
        "a bare figure beside a record is how a chart and a ledger disagree while both look "
        "right (v1.24's lesson, applied to equity)")
    b = strip_comments(body("DisplayEquity"))
    assert "InpLiveExecution" in b and "AccountInfoDouble(ACCOUNT_EQUITY)" in b
    assert "PaperEquity()" in b
    # the record follows the display: every live heartbeat EQ row is written through one site
    code = strip_comments(src())
    assert "LogEquityRow()" in code and '"EQ,%.2f", DisplayEquity()' in code, \
        "the EQ heartbeat row must carry the same basis the HUD shows"
    hud = strip_comments(body("HudUpdate"))
    assert "EquityText(" in hud, "the HUD must print the labelled line, not its own formula"


def test_version_tag_consistent_everywhere() -> None:
    s = src()
    prop = re.search(r'#property\s+version\s+"(\d+)\.(\d+)"', s)
    define = re.search(r'#define\s+APP_VERSION\s+"MIDAS(\d+)\.(\d+)"', s)
    assert prop and define, "both #property version and APP_VERSION must exist"
    assert prop.groups() == define.groups(), \
        f"#property {prop.groups()} != APP_VERSION {define.groups()}"
    assert '"[" + APP_VERSION + "]"' in s, "VersionTag must stay banner-stable"


def test_banner_format_is_watchdog_stable() -> None:
    """The watchdog's banner parser regexes mode=/session=/execution=/exec-model=
    — the HUD must never change those key= tokens (it renders mode names
    separately through ModeName)."""
    b = body("HudUpdate")
    assert "mode=%d" in b and "session %02d-%02d" in b


# --- the chart period is never a decision input ------------------------------
#
# ASKED, 2026-09-21, while the arm was live on an H1 chart whose HUD read
# `tf=PERIOD_M15`: "is it not contradicting each other?" It is not — the HUD's TF field is
# `EnumToString(InpEntryTF)` (the ENTRY/trigger timeframe, pinned to 15 = M15 in both
# Upcomers presets), and the EA names every series it reads: M15 (or InpEntryTF) for the
# trigger, H1 for the regime EMA + ATR, H4 for the macro. Nothing consults the chart's own
# period, which is why an H1 chart is functionally identical to an M15 one — the chart is a
# drawing surface and the attachment point, not an input. The two tests below make that an
# invariant rather than a property that happens to hold today: the day someone reaches for
# `Period()` or a bare-0 series call, the arm starts behaving differently on a chart nobody
# re-attached, and no other test in this suite would notice.

def test_nothing_in_the_ea_reads_the_chart_period() -> None:
    """No chart-period read anywhere, and every series call names its timeframe."""
    code = strip_comments(src())
    for bad in ("_Period", "Period()", "ChartPeriod(", "PeriodSeconds("):
        assert bad not in code, (
            f"the EA reads the CHART period via `{bad}`. It must not: the certified "
            f"behaviour is defined on explicit timeframes (InpEntryTF / H1 / H4), and a "
            f"chart-period read makes the same inputs behave differently depending on "
            f"which chart the EA happens to be attached to")
    series = ("Bars", "iBars", "iTime", "iOpen", "iHigh", "iLow", "iClose", "iBarShift",
              "CopyOpen", "CopyHigh", "CopyLow", "CopyClose", "CopyTime", "CopyRates")
    pat = re.compile(r"\b(" + "|".join(series) + r")\s*\(([^()]*)\)")
    checked = 0
    for m in pat.finditer(code):
        args = m.group(2)
        if "_Symbol" not in args:
            continue          # CopyBuffer(handle, buffer, ...) and friends: no timeframe
        checked += 1
        assert ("PERIOD_" in args or "InpEntryTF" in args), (
            f"series call with an implicit (chart) period: {m.group(0)}")
    assert checked >= 20, f"only {checked} series calls matched — this test lost its teeth"


def test_the_tf_field_is_the_entry_timeframe_not_the_chart() -> None:
    """The field the question is about: it displays the pinned ENTRY timeframe."""
    b = body("HudUpdate")
    assert "EnumToString(InpEntryTF)" in b, (
        "the HUD's TF field must render InpEntryTF (the entry/trigger TF). Rendering the "
        "chart period there is what made `tf=PERIOD_M15` on an H1 chart look like a "
        "contradiction")
    # comments stripped first: the label carries its own explanation now, and a regex that
    # only tolerated a quote directly after `StringFormat(` failed the moment the comment
    # landed there — the test was pinning the layout, not the invariant.
    fmt = re.search(r'StringFormat\(\s*"((?:[^"\\]|\\.)*)"', strip_comments(b), re.S)
    assert fmt and re.search(r"\b(entryTF|tf)=%s", fmt.group(1)), \
        "the HUD must label its timeframe field"
    assert "entryTF=%s" in fmt.group(1), (
        "the field must SAY it is the entry timeframe: `tf=PERIOD_M15` on an H1 chart was read "
        "as a contradiction on 2026-09-21, and the label is the cheapest place to make that "
        "misreading impossible. The displayed VALUE is InpEntryTF either way (asserted above).")
    live = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold_LIVE.set").read_text(
        encoding="utf-8-sig", errors="replace")
    assert re.search(r"^InpEntryTF=15$", live, re.M), (
        "the armed preset pins the certified M15 entry TF; if that ever changes, the HUD "
        "will read differently on purpose and this test should say so")


# --- display-only means display-only: no new inputs, no file access ----------

def test_hud_adds_no_input_and_no_file_access() -> None:
    s = src()
    assert not re.search(r"^input .*Hud", s, re.M), "HUD must be input-free"
    b = body("HudUpdate")
    for tok in ("FileOpen", "FileRead", "PaperLog", "Print", "OrderSend"):
        assert tok not in b, f"HUD must never {tok}"


def _preset_keys(path: Path) -> set[str]:
    keys = set()
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith(";") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def test_ea_inputs_match_preset_keys_exactly() -> None:
    """The .set preset is the single source of truth: the EA's input set and
    the pinned key set must be identical (the certified splice chain is
    byte-exact over all 30 keys).

    Two standards, because two files: the Deriv-era `M1_gold` baseline is history and
    deliberately does not pin what arrived after it, so the delta over THAT file is
    asserted to be exactly the registered sets below — while the preset the arm actually
    runs must pin everything, with no delta of any kind.
    """
    ea_inputs = set(re.findall(r"^input\s+(?!group)\S+\s+(Inp\w+)", src(), re.M))
    preset_keys = _preset_keys(PRESET)
    # 2026-09-20 prop governor (six inputs: shield, target, Best Day inside MT5 rather
    # than only in Python) and 2026-09-20 news stand-down (five: the calendar gate). Any
    # OTHER new input still fails here, which is the drift this test exists to catch.
    prop_governor = {
        "InpPropGuard", "InpPropAccountSize", "InpPropTargetPct",
        "InpPropMaxDdPct", "InpPropBestDayPct", "InpPropPeakOverride",
    }
    news_gate = {
        "InpNewsFile", "InpNewsWindowMin", "InpNewsMaxAgeHours",
        "InpNewsCoverHours", "InpNewsRefreshHours",
    }
    # 2026-09-21 the recorded state stamp (one: the OPEN row carries the entry's own
    # state). Registered here deliberately rather than absorbed: an input that arrives
    # unregistered is the drift this test exists to catch.
    state_stamp = {"InpRecordStateLabel"}
    unexpected = ea_inputs - preset_keys - prop_governor - news_gate - state_stamp
    assert not unexpected, f"unexpected EA-only inputs: {sorted(unexpected)}"
    assert not (preset_keys - ea_inputs), (
        f"preset-only keys: {sorted(preset_keys - ea_inputs)}")
    live = _preset_keys(PRESET.with_name("MidastouchAI_upcomers_gold.set"))
    assert live == ea_inputs, (
        "the preset the arm runs must pin every input — an omission means the EA silently "
        f"runs its code default: {sorted(ea_inputs ^ live)}")


# --- v1.21 the HUD VIEW: what the engine sees, on the chart and in the record ---------

VIEW_HELPERS = ("RegimeText", "TriggerText", "GateText", "SizingText", "GovernorText",
                "NewsText", "TradesText")


def test_hud_prints_the_engine_view_not_only_that_it_is_alive() -> None:
    """The v1.21 complaint, pinned: the chart said it was running but not what it saw.
    Regime (bullish/bearish), trigger, gates, sizing and governor must all be on it."""
    b = body("HudUpdate")
    for fn in VIEW_HELPERS:
        assert f"{fn}()" in b, f"HUD must print {fn}()"
    for word in ("REGIME", "TRIGGER", "GATES", "SIZING", "GOVERNOR", "NEWS"):
        assert word in b, f"HUD panel is missing the {word} line"


def test_regime_is_named_not_just_numbered() -> None:
    """`macro -1` is not a direction a human reads at a glance; the panel must say
    BEARISH / BULLISH / MIXED. Both the EA and the CLI reader must use those words."""
    b = body("RegimeText")
    for word in ("BULLISH", "BEARISH", "MIXED"):
        assert word in b, f"RegimeText must name {word}"
    ms = _morning_status()
    assert ms.regime_word(1) == "BULLISH" and ms.regime_word(-1) == "BEARISH"
    assert "MIXED" in ms.regime_word(0) and ms.regime_word(2) == "not measured yet"


def test_the_hud_tally_counts_the_arms_own_record() -> None:
    """MEASURED 2026-09-22: the arm's first live fill closed at +0.104R, the ledger said
    `closed: 1/30` and the chart said `trades: 0/30 | cumR +0.00`. Both live close paths
    wrote their LCLOSE row and neither touched a counter, and the paper counters an armed
    arm can see start empty on every reload — so the chart could not count a real trade at
    all, while the go-live gate counts exactly those trades.

    Pinned: the tally reads the LIVE record when armed and says so, the LIVE record comes
    from the ledger's own LCLOSE rows, and BOTH close paths increment through the same
    helper (a private copy per path is how the two drift apart).
    """
    def definition(fn_name: str) -> str:
        """Brace-matched body of a named function's DEFINITION.

        Not `body()`: that helper matches `\\w+\\s+name(`, which also matches a CALL SITE
        whenever the line above it ends in a word — the comment above
        `LiveCensusRestoreFromLedger();` in OnInit supplies exactly that, and `body()` then
        returned the NEXT function's body while still asserting nothing was wrong.
        Anchoring on the declared return type cannot match a bare call.
        """
        s = src()
        m = re.search(rf"^[ \t]*(?:void|string|double|int|bool)\s+{re.escape(fn_name)}\s*\(",
                      s, re.M)
        assert m, f"{fn_name} has no definition in the source"
        j = s.index("{", m.end())
        depth = 0
        for k in range(j, len(s)):
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    return s[j:k]
        raise AssertionError(f"unbalanced braces after {fn_name}")

    t = strip_comments(definition("TradesText"))
    assert "g_live_closed" in t and "g_live_wins" in t and "g_live_cum_r" in t, \
        "on an armed arm the tally must read the live record"
    assert "g_trades" in t, "a paper arm's tally is still the paper counters"
    assert "InpLiveExecution" in t and "LCLOSE" in t, \
        "the line must name WHICH record it is counting"
    # one increment path, called by both closes
    for fn in ("LiveClosePosition", "LiveCheckExits"):
        assert "LiveCensusAdd(" in strip_comments(definition(fn)), f"{fn} must count its close"
    # and the restore is ledger-backed (LCLOSE rows) and runs at init, before the HUD
    r = strip_comments(definition("LiveCensusRestoreFromLedger"))
    assert '"LCLOSE"' in r and "StringSplit" in r, "the census must count the ledger's LCLOSE rows"
    assert "MQL_TESTER" in r and "InpBarModel" in r, \
        "the census must be gated out of the tester and the BAR replay"
    callers = strip_comments(body("OnInit"))
    assert "LiveCensusRestoreFromLedger()" in callers, "OnInit must restore the census"
    assert callers.index("LiveCensusRestoreFromLedger()") < callers.index("HudUpdate()"), \
        "the record must be restored BEFORE the first paint, or the chart starts at 0/30"


def test_hud_view_layer_is_read_only() -> None:
    """No display function may assign to engine state: the view READS the decision's
    stash. A display path that writes state can change behaviour, and a Comment() must
    never be a strategy input."""
    for fn in VIEW_HELPERS + ("SizingNumbers", "StateRowWrite", "HudUpdate"):
        b = strip_comments(body(fn))
        assert not re.search(r"\bg_\w+\s*=(?!=)", b), f"{fn} writes engine state"


def test_state_row_is_gated_out_of_the_parity_paths() -> None:
    b = body("StateRowWrite")
    head = b[:b.index("PaperLog(")]
    assert "MQL_TESTER" in head and "InpBarModel" in head, \
        "the STATE row must be gated out of the tester and the BAR replay"


def test_state_row_and_the_hud_share_one_sizing_computation() -> None:
    """A number on the chart that is not the number in the record is the failure this
    whole design exists to prevent."""
    assert "SizingNumbers(" in strip_comments(body("SizingText"))
    assert "SizingNumbers(" in strip_comments(body("StateRowWrite"))


def _morning_status():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import morning_status as ms
    return ms


def test_state_row_field_order_matches_the_python_reader() -> None:
    """The cross-language pin. The NOFILL lesson (2026-09-21) was that a reader whose key
    order disagrees with the writer mislabels every column after the divergence, and does
    it invisibly — a permutation of zeros reads exactly like a correct parse."""
    ms = _morning_status()
    b = body("StateRowWrite")
    literal = re.search(r'"STATE,([^"]+)"', b)
    assert literal, "STATE row format literal not found"
    fmt = literal.group(1)
    # POSITIONAL specifiers only. The v1.22 configured-risk token is a KEYED tail, not a
    # column, and counting it as one is precisely the confusion the NOFILL mislabel was made
    # of — a reader whose key list is one longer than the writer's field list mislabels every
    # column from the divergence on, invisibly.
    specs = re.findall(r"%I64[du]|%[-0-9.]*[dfs]", fmt)
    assert specs == ["%I64d", "%I64d"] + ["%d"] * 8 + ["%.2f"] * 3 + ["%s"], specs
    assert len(specs) - 1 == len(ms.STATE_KEYS) + 1, (
        f"EA writes {len(specs) - 1} positional fields (including the row's own epoch), the "
        f"reader expects {len(ms.STATE_KEYS)} after it")
    assert len(ms.STATE_KEYS) == 12
    assert "RiskAppend(ConfiguredRiskUsd())" in strip_comments(b), (
        "the STATE row carries the same keyed cfg token as the fill rows, from the same "
        "source — a second definition is how two numbers come to describe one budget")


def test_state_reader_round_trips_a_written_row(tmp_path) -> None:
    """The reader is exercised on a row in the EA's own field order, with nine DISTINCT
    values so a wrong order cannot pass by symmetry."""
    ms = _morning_status()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "ERA,MIDAS1.22,1,note\n"
        "STATE,1000,900,-1,-1,-1,0,5230,1,1,3184,0.00,250.00,23540.00,cfg=62.50@0.25\n",
        encoding="utf-8")
    row = ms.state_last(str(ledger))
    assert row is not None
    assert row["mac"] == -1 and row["h4"] == -1 and row["h1"] == -1
    assert row["trig"] == 0 and row["rsi_x100"] == 5230
    assert row["lots_x100"] == 1 and row["risk_x100"] == 3184
    assert row["cap"] == 250.0 and row["floor"] == 23540.0
    assert row["cfg_risk"] == {"cfg_risk_usd": 62.50, "cfg_risk_pct": 0.25}
    text = ms.state_text(row)
    assert "BEARISH" in text and "RSI 52.3" in text and "0.01 lots risk $31.84" in text
    # and the reader names the gap the token exists to expose, rather than leaving the
    # operator to subtract two numbers from two different lines
    assert "of $62.50 configured (0.25%) QUANTISED DOWN" in text


def test_state_text_stays_silent_on_a_row_written_before_v122(tmp_path) -> None:
    """Absence is not a defect, and it must not be rendered as a zero budget either."""
    ms = _morning_status()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "ERA,MIDAS1.21,1,note\n"
        "STATE,1000,900,-1,-1,-1,0,5230,1,1,3184,0.00,250.00,23540.00\n",
        encoding="utf-8")
    row = ms.state_last(str(ledger))
    assert row["cfg_risk"] == {}
    text = ms.state_text(row)
    assert "configured" not in text and "lots risk $31.84" in text


def test_state_reader_ignores_a_short_row(tmp_path) -> None:
    ms = _morning_status()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("STATE,1000,900,-1,-1\n", encoding="utf-8")
    assert ms.state_last(str(ledger)) is None

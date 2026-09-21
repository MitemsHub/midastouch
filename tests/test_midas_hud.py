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
        "g_nofill_signal", "g_nofill_mism", "g_nofill_notr",
        "g_nofill_session", "g_nofill_spread",
        # HUD state itself + the local pos label
        "g_last_action", "pos",
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
    assert on_timer.index("PaperLog(") < on_timer.index("HudUpdate();"), \
        "OnTimer heartbeat must log first, draw second"
    on_tick = body("OnTick")
    assert "HudUpdate();" in on_tick
    for fn in ("OnBarReplay", "LiveOnTick"):
        assert "HudUpdate();" not in strip_comments(body(fn)), f"{fn} must not refresh the HUD"


# --- version consistency (the #property had been stale since v1.06) ----------

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

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
        # paper state (already in the ledger: EQ/CLOSE/OPEN rows)
        "APP_VERSION", "g_pp_open", "g_pp_dir", "g_paper_start",
        "g_trades", "g_wins", "g_cum_r",
        # live adoption state (already in the ledger: LOPEN/LCLOSE rows;
        # v1.11 rows carry the position IDENTIFIER as the reconciliation key)
        "g_lv_posid", "g_lv_dir",
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


# --- display-only means display-only: no new inputs, no file access ----------

def test_hud_adds_no_input_and_no_file_access() -> None:
    s = src()
    assert not re.search(r"^input .*Hud", s, re.M), "HUD must be input-free"
    b = body("HudUpdate")
    for tok in ("FileOpen", "FileRead", "PaperLog", "Print", "OrderSend"):
        assert tok not in b, f"HUD must never {tok}"


def test_ea_inputs_match_preset_keys_exactly() -> None:
    """The .set preset is the single source of truth: the EA's input set and
    the pinned key set must be identical (the certified splice chain is
    byte-exact over all 30 keys)."""
    ea_inputs = set(re.findall(r"^input\s+(?!group)\S+\s+(Inp\w+)", src(), re.M))
    preset_keys = set()
    for line in PRESET.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith(";") and "=" in line:
            preset_keys.add(line.split("=", 1)[0].strip())
    assert ea_inputs == preset_keys, (
        f"EA-only inputs: {sorted(ea_inputs - preset_keys)}; "
        f"preset-only keys: {sorted(preset_keys - ea_inputs)}")

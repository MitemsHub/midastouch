"""Offline source tests for the MidastouchAI v1.12 time engine.

Pins the two-clock frame law: signal-bar EPOCH classification (the
python-parity session/Friday gates) must stay on the label frame, while
live-path wall-clock decisions (daily breaker, Friday force-flat, the
live position's timeout) must go through the TimeGMT-backed UTCNow()
helper. Swapping the wrong side either breaks bit-level BAR parity or
moves the live gates with the broker's timezone/DST — the exact P0 the
external review confirmed.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
PROBE = REPO / "mql5" / "MIDASTOUCH" / "MidasOffsetProbe.mq5"


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


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


# --- the helpers -------------------------------------------------------------

def test_utcnow_is_timegmt_backed_and_single() -> None:
    code = strip_comments(src())
    defs = re.findall(r"datetime\s+TimeUTCNow\s*\(", code)
    assert len(defs) == 1, "exactly one authoritative TimeUTCNow helper"
    assert not re.search(r"\bUTCNow\s*\(", code), \
        "stale UTCNow references must be renamed to TimeUTCNow"
    m = re.search(r"datetime\s+TimeUTCNow\s*\(\s*\)\s*\{([^}]*)\}", code)
    assert m and "TimeGMT()" in m.group(1), "TimeUTCNow must be TimeGMT-backed (broker-independent)"
    assert "OffsetMinutes" in code, "offset introspection helper must exist for verification"


# --- parity gates: the LABEL frame is frozen ---------------------------------

def test_bar_parity_gate_classifies_bar_epochs() -> None:
    b = strip_comments(body("BarEvaluateSignal"))
    assert "TimeToStruct(sig," in b, "BAR gate must classify the signal-bar epoch"
    assert "TimeUTCNow(" not in b and "TimeGMT(" not in b, \
        "BAR gate must never use the wall clock (python classifies epochs)"


def test_pertick_gate_classifies_bar_epochs() -> None:
    b = strip_comments(body("TrackFreshM15Bar"))
    assert "TimeToStruct(sig_open_time," in b, "PERTICK gate must classify the signal-bar epoch"
    assert "TimeUTCNow(" not in b and "TimeGMT(" not in b, \
        "PERTICK gate must never use the wall clock (python classifies epochs)"


def test_staleness_guard_keeps_server_frame() -> None:
    b = strip_comments(body("TrackFreshM15Bar"))
    assert "TimeCurrent() - g_last_m15_seen" in b, \
        "staleness measures gaps in the SERVER stream — its own frame, deliberately"


# --- v1.15 frame law: bar EPOCHS are broker-SERVER, hour gates are UTC -------

def test_hour_gates_use_their_declared_frames_and_say_so() -> None:
    """The provenance finding (v1.15): iTime bar epochs are broker-SERVER
    time, so the 06–20/Friday gates that classify them must structurize the
    epoch — never UTCNow — or the window shifts with the broker timezone.
    The human-intent gates (breaker day key, Friday flat, live timeout) are
    the TimeUTCNow() side. Each site must carry its frame in its comment."""
    for fn, epoch_var in (("BarEvaluateSignal", "TimeToStruct(sig,"),
                          ("TrackFreshM15Bar", "TimeToStruct(sig_open_time,")):
        b = body(fn)
        assert epoch_var in b, f"{fn}: epoch classification site moved?"
        assert "SERVER" in b, \
            f"{fn}: the epoch frame (broker-server) must be documented at the site"
        assert "UTCNow(" not in b, f"{fn}: epoch gates must not structurize UTC"
    for fn in ("DailyBreakerTripped", "LiveFridayFlatCheck"):
        assert "UTC" in body(fn), f"{fn}: the UTC frame must be documented at the site"


def test_epoch_gates_and_python_of_record_agree_on_the_frame() -> None:
    """Both engines must classify the same broker-feed epochs through the
    same structurization (server frame). If the python engine ever gains a
    UTC-based hour gate, this pin and amendment 6's provenance finding must
    be re-adjudicated TOGETHER — never one side alone."""
    sweep = (REPO / "scripts" / "midas_sweep.py").read_text(encoding="utf-8")
    assert "fromtimestamp(b[\"time\"], tz=timezone.utc)" in sweep, \
        "python of record: hour gate reads the broker-feed bar epoch"
    code = strip_comments(src())
    for m in re.finditer(r"TimeToStruct\s*\(\s*(sig\w*)\s*,", code):
        assert "TimeUTCNow" not in code[m.start():m.start() + 80], \
            "EA epoch classification must not route through the UTC helper"


# --- live wall-clock decisions: TRUE UTC -------------------------------------

def test_daily_breaker_day_key_is_utc() -> None:
    b = strip_comments(body("DailyBreakerTripped"))
    assert "TimeToStruct(TimeUTCNow()" in b, "breaker day key must be a TRUE UTC day"
    assert not re.search(r"TimeToStruct\s*\(\s*TimeCurrent", b), \
        "breaker must not structurize from broker-server time"


def test_friday_flat_is_utc() -> None:
    b = strip_comments(body("LiveFridayFlatCheck"))
    assert "TimeToStruct(TimeUTCNow()" in b, "Friday force-flat must be TRUE UTC"
    assert not re.search(r"TimeToStruct\s*\(\s*TimeCurrent", b)


def test_live_timeout_clock_is_utc_end_to_end() -> None:
    ob = strip_comments(body("LiveSendOrder"))
    cb = strip_comments(body("LiveCheckExits"))
    assert "g_lv_open_time = TimeUTCNow()" in ob, "live timeout opens on the UTC clock"
    assert "TimeUTCNow() >= g_lv_expiration" in cb, "live timeout compares on the same clock"
    for b in (ob, cb):
        assert not re.search(r"TimeToStruct\s*\(\s*TimeCurrent", b)


# --- verification surface ----------------------------------------------------

def test_banner_prints_both_clocks_and_offset() -> None:
    code = strip_comments(src())
    assert '"CLOCK:' in code, "init banner must print server, GMT and the derived offset"


def test_offset_probe_exists_and_is_operational() -> None:
    p = PROBE.read_text(encoding="utf-8", errors="replace")
    assert "TimeGMT()" in p and "TimeCurrent()" in p, "probe must print both clocks"
    assert "HEALTH_GUIDE" in p, "probe must point at the documented verification walk-through"
    assert "OnStart" in p, "probe ships as a script (drag-once, prints, exits)"

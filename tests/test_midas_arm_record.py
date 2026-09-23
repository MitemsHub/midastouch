"""The armed arm's record grammar, the mode matrix, and the read-only guarantee.

WHY THIS FILE EXISTS. Three new tools read the arm's one ledger (spread watch,
trigger pace, and whatever reads it next). A private grammar per tool is how the
2026-09-21 NOFILL reader/writer order disagreement happens twice, so the
grammars are pinned here against the EA's own writers, and the three guarantees
that make the tools trustworthy are pinned with them:

  1. The rows are read in the EA's writer order — STATE's ten-engine-view fields
     and the state stamp, NOFILL's ten counters (notr between breaker and news),
     the SPREADHOUR 24x4 body.
  2. The mode matrix the tools use to classify STATE bars is `ModeDecide`
     (MidastouchAI.mq5) row for row — a lookalike matrix would classify another
     strategy's bars and every rate would be fiction.
  3. None of the three tools can place, modify, or delete anything: no
     `order_send`, no file mutation, no MT5 order API anywhere in their source.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_arm_record as AR          # noqa: E402
import midas_spread_watch as SW        # noqa: E402
import midas_trigger_pace as TP        # noqa: E402

WATCH_SRC = (REPO / "scripts" / "midas_spread_watch.py").read_text(encoding="utf-8")
PACE_SRC = (REPO / "scripts" / "midas_trigger_pace.py").read_text(encoding="utf-8")
PARSER_SRC = (REPO / "scripts" / "midas_arm_record.py").read_text(encoding="utf-8")

#: From MidastouchAI.mq5 `StateRowWrite` (v1.27): 14 head fields + 5 stamp fields.
STATE_ROW = ("STATE,1790144999,1790151300,-1,-1,-1,0,3396,1,2,5284,0.00,250.00,"
             "23504.26,1790151300,6,0.71068,out,120,cfg=62.50@0.25")
#: From `DiagCounters` (v1.27 order: notr sits between breaker and news).
NOFILLSUM_ROW = "NOFILLSUM,1790144999,20719,26,2,0,0,0,0,0,24,0,0"
LCLOSE_ROW = "LCLOSE,1790099701,18874164,EXTERNAL,4332.14000,0.104"
SPREADHOUR_ROW = ("SPREADHOUR,1790169600,20719," + ",".join(
    f"{h},1,0.50,{int(50 * (h + 1))}" for h in range(24)))


def _parts(s: str) -> list[str]:
    return s.split(",")


class TestStateGrammar:
    def test_fields_land_in_the_ea_s_own_order(self) -> None:
        r = AR.parse_state(_parts(STATE_ROW), 7)
        assert r is not None
        assert r["write_utc"] == 1790144999
        assert r["sig_open_srv"] == 1790151300
        assert r["mac"] == -1 and r["h4"] == -1 and r["h1"] == -1
        assert r["trig"] == 0 and r["rsi"] == 33.96
        assert r["sess_ok"] is True
        assert r["lots"] == 0.02 and r["risk_usd"] == 52.84
        assert r["daypnl"] == 0.0 and r["cap"] == 250.0 and r["floor"] == 23504.26
        assert r["sig_ct_srv"] == 1790151300
        assert r["hour_utc"] == 6 and abs(r["vol_ratio"] - 0.71068) < 1e-9
        assert r["news"] == "out" and r["off_min"] == 120

    def test_stampless_rows_parse_head_only_and_stamp_rows_refuse_short(self) -> None:
        # Legacy (v1.21-26) STATE rows parse as head-only, stamp=False.
        legacy = AR.parse_state(_parts(STATE_ROW)[:14], 1)
        assert legacy is not None and legacy["stamp"] is False
        assert legacy["off_min"] is None and AR.bar_open_utc(legacy) is None
        # A row PROMISING a stamp (>= 20 fields here) but carrying a broken one
        # is a different defect than a legacy row, and still refuses.
        broken_stamp = _parts(STATE_ROW)[:19]
        broken_stamp[15] = "not_an_int"
        assert AR.parse_state(broken_stamp, 1) is None

    def test_bar_open_uses_the_rows_own_offset(self) -> None:
        r = AR.parse_state(_parts(STATE_ROW), 1)
        assert AR.bar_open_utc(r) == 1790151300 - 120 * 60

    def test_unknown_offset_never_yields_an_epoch(self) -> None:
        r = AR.parse_state(_parts(STATE_ROW), 1)
        r["off_min"] = None
        assert AR.bar_open_utc(r) is None


class TestNofillGrammar:
    def test_notr_sits_between_breaker_and_news(self) -> None:
        r = AR.parse_nofill(_parts(NOFILLSUM_ROW))
        assert r is not None
        # The writer order: signal,mismatch,session,friday,spread,riskcap,breaker,notr,news,nodata
        #                     26       2        0       0      0      0       0       24   0    0
        assert r["signal"] == 26 and r["mismatch"] == 2
        assert r["notr"] == 24 and r["news"] == 0 and r["nodata"] == 0

    def test_short_snapshot_is_refused_like_the_ea_refuses_it(self) -> None:
        # DiagRestoreFromLedger's floor: a 12-field v1.26 row is not a snapshot.
        assert AR.parse_nofill(_parts(NOFILLSUM_ROW)[:12]) is None


class TestSpreadhourGrammar:
    def test_24_hour_body_parses_as_hour_keyed_means(self) -> None:
        r = AR.parse_spreadhour(_parts(SPREADHOUR_ROW))
        assert r is not None
        assert r["hours"][0] == (1, 0.50, 0.50)   # max_x100 = 50*(0+1)
        assert r["hours"][7] == (1, 0.50, 4.00)   # max_x100 = 50*(7+1)
        assert r["hours"][23] == (1, 0.50, 12.00)
        assert len(r["hours"]) == 24


class TestModeMatrix:
    """`ModeDecide` (MidastouchAI.mq5:954), row for row, all 8 modes."""

    def test_original(self) -> None:
        assert SW.mode_takes(0, 1, 1) and SW.mode_takes(0, -1, -1)
        assert not SW.mode_takes(0, 1, -1) and not SW.mode_takes(0, 0, 1)
        assert not SW.mode_takes(0, 1, 0)

    def test_reverse_direction(self) -> None:
        assert SW.mode_takes(1, 1, -1) and SW.mode_takes(1, -1, 1)
        assert not SW.mode_takes(1, 1, 1) and not SW.mode_takes(1, 0, -1)

    def test_reverse_trigger_and_both(self) -> None:
        assert SW.mode_takes(2, 0, 1) and not SW.mode_takes(2, 1, 1)
        assert SW.mode_takes(3, 0, 1) and not SW.mode_takes(3, 1, -1)

    def test_long_short_macro_trigger_only(self) -> None:
        assert SW.mode_takes(4, 1, 1) and not SW.mode_takes(4, -1, -1)
        assert SW.mode_takes(5, -1, -1) and not SW.mode_takes(5, 1, 1)
        assert SW.mode_takes(6, 0, 1) and not SW.mode_takes(6, 1, 0)
        assert SW.mode_takes(7, 1, 0) and not SW.mode_takes(7, 0, 1)

    def test_unknown_mode_takes_nothing(self) -> None:
        for trig in (0, 1, -1):
            for mac in (0, 1, -1):
                assert not SW.mode_takes(9, trig, mac)


class TestReadOnlyGuarantee:
    """None of the three tools can act on the world. Pinned on source, exactly
    like tests/test_live_readiness_order_path.py pins its own gate. The pins are
    CALL-SHAPED (`order_send(`) so a docstring that names the guarantee does not
    fail its own test."""

    def test_no_order_path_anywhere(self) -> None:
        for src in (WATCH_SRC, PACE_SRC, PARSER_SRC):
            assert "order_send(" not in src
            assert "order_check(" not in src
            assert "OrderSend" not in src
            assert "position_open(" not in src
            assert "buy(" not in src and "sell(" not in src

    def test_no_file_mutation_helpers(self) -> None:
        for src in (WATCH_SRC, PACE_SRC, PARSER_SRC):
            assert "os.remove" not in src
            assert ".unlink(" not in src
            assert "rmtree(" not in src
            assert "import shutil" not in src

    def test_the_only_writes_are_the_two_artifacts(self) -> None:
        # ART.write_text in the two tools (their own artifact); the parser must
        # not write at all.
        assert PARSER_SRC.count("write_text") == 0
        assert WATCH_SRC.count("write_text") == 1
        assert PACE_SRC.count("write_text") == 1
        assert "mkdir" in WATCH_SRC and "mkdir" in PACE_SRC  # artifacts dir only

    def test_both_tools_count_deduped_bars_not_raw_rows(self) -> None:
        # The heartbeat rewrites the current bar's STATE row every 15 minutes, so
        # a per-bar count over raw rows counts heartbeats, not signals (measured
        # 2026-09-23: the audit read 8 accepted signals where 5 bars exist).
        assert 'AR.dedupe_bars(rows["state"])' in WATCH_SRC
        assert "return AR.dedupe_bars(states)" in PACE_SRC   # one grammar, not two


class TestPaceMath:
    def test_dedupe_keeps_latest_write_per_bar(self) -> None:
        base = {"mac": -1, "h4": -1, "h1": -1, "trig": 1, "rsi": 29.7,
                "sess_ok": True, "lots": 0.02, "risk_usd": 50.0,
                "daypnl": 0.0, "cap": 250.0, "floor": 23504.26,
                "sig_ct_srv": 1790151300, "hour_utc": 6, "vol_x10000": 71068,
                "news": "out", "off_min": 120}
        bars = [{"write_utc": 100, "sig_open_srv": 1790151300, **base},
                {"write_utc": 300, "sig_open_srv": 1790151300, **base},
                {"write_utc": 200, "sig_open_srv": 1790152200, **base}]
        out = TP.dedupe_bars(bars)
        assert len(out) == 2
        assert out[0]["write_utc"] == 300      # the heartbeat repeat, not the first
        assert out[1]["sig_open_srv"] == 1790152200

    def test_classify_matches_the_census_buckets(self) -> None:
        base = {"sig_open_srv": 1, "off_min": 0}
        bars = [
            {"trig": 0, **base},                                   # notr
            {"trig": 1, "mac": -1, **base},                        # mode-1 accepted
            {"trig": 1, "mac": 1, **base},                         # mode-1 mismatch
        ]
        cls = TP.classify(bars, mode=1)
        assert cls == {"evaluated": 3, "notr": 1, "triggers": 2,
                       "mismatch": 1, "accepted": 1}

    def test_census_counts_max_per_day_from_the_rows_own_day_field(self) -> None:
        rows = [
            # day 20718 restored then grown within the day; the write lands after
            # midnight, so keying on write time would split one day into two.
            {"day": 20718, "write": 20718 * 86400 + 100,
             **{k: 0 for k in AR.NOFILL_FIELDS}, "signal": 10, "notr": 9},
            {"day": 20718, "write": 20718 * 86400 + 200,
             **{k: 0 for k in AR.NOFILL_FIELDS}, "signal": 30, "notr": 21},
            {"day": 20719, "write": 20719 * 86400 + 100,
             **{k: 0 for k in AR.NOFILL_FIELDS}, "signal": 5, "notr": 3},
        ]
        cens = TP.census_totals(rows, arming_day=None)
        assert cens["totals"]["signal"] == 35 and cens["totals"]["notr"] == 24
        assert cens["days"] == 2

    def test_census_excludes_pre_arming_days(self) -> None:
        rows = [{"day": 20717, "write": 0, **{k: 0 for k in AR.NOFILL_FIELDS},
                 "signal": 99, "notr": 99},
                {"day": 20719, "write": 0, **{k: 0 for k in AR.NOFILL_FIELDS},
                 "signal": 5, "notr": 3}]
        cens = TP.census_totals(rows, arming_day=20718)
        assert cens["totals"]["signal"] == 5 and cens["days"] == 1

    def test_verdict_refuses_short_windows(self) -> None:
        live = {"live_days": 1.9, "census": {"signal": 0}, "class": {},
                "bars_per_day": 96.0, "trigger_rate_per_day": 0.0}
        word, why = TP.pace_verdict(live, engine=None)
        assert word == "UNMEASURABLE" and "live days" in why[0]

    def test_verdict_flags_grammar_conflict(self) -> None:
        live = {"live_days": 5.0, "bars_per_day": 90.0,
                "trigger_rate_per_day": 2.0, "census_days": 4,
                "census": {"signal": 300, "notr": 200, "mismatch": 90},
                "class_census_days": {"evaluated": 299, "notr": 20, "mismatch": 1,
                                      "triggers": 21, "accepted": 20}}
        word, why = TP.pace_verdict(live, engine=None)
        assert word == "CONFLICTED"

    def test_verdict_refuses_without_the_engine(self) -> None:
        live = {"live_days": 5.0, "bars_per_day": 90.0, "trigger_rate_per_day": 2.0,
                "census_days": 4,
                "census": {"signal": 300, "notr": 200, "mismatch": 5},
                "class_census_days": {"evaluated": 300, "notr": 200, "mismatch": 5,
                                      "triggers": 205, "accepted": 200}}
        word, why = TP.pace_verdict(live, engine=None)
        assert word == "PUBLISHED-ONLY"


class TestSpreadWatchMath:
    def test_atr_is_the_eas_closed_bar_sma(self) -> None:
        # 14 closed H1 bars, flat prices, range 1.0, closes mid-range -> every
        # true range is 1.0 (no gap terms) and the SMA is exactly 1.0.
        h1 = [{"high": 100.0, "low": 99.0, "close": 99.5} for _ in range(15)]
        assert abs(SW.atr_h1_closed(h1, 14) - 1.0) < 1e-9
        assert SW.atr_h1_closed(h1[:10], 14) == 0.0   # refuses a short window

    def test_cap_is_pct_of_stop(self) -> None:
        assert abs(SW.spread_cap(25.78, 1.5) - 0.3867) < 1e-9

    def test_trend_names_its_window_or_refuses(self) -> None:
        t = SW.trend([])
        assert t["state"] == "UNMEASURABLE"

    def test_trend_reads_narrowing_from_the_record(self) -> None:
        # 8 bars: gap shrinking from +1.0 to -1.0 -> NARROWING
        bars = [{"bar_utc": 1790100000 + i * 3600, "gap": 1.0 - i * 0.25}
                for i in range(8)]
        t = SW.trend([{"bar_utc": b["bar_utc"], "gap": b["gap"]} for b in bars])
        assert t["state"] == "NARROWING"


class TestArmedPresetResolution:
    def test_resolve_goes_through_the_arming_record(self, tmp_path: Path) -> None:
        import json
        rec = tmp_path / "armed.json"
        rec.write_text(json.dumps({"preset": "the_preset.set"}), encoding="utf-8")
        (tmp_path / "the_preset.set").write_text("InpMode=1\n", encoding="utf-8")
        p, src = AR.resolve_arm_preset(rec, tmp_path)
        assert p is not None and p.name == "the_preset.set"
        assert "arming record" in src

    def test_missing_preset_is_reported_never_guessed(self, tmp_path: Path) -> None:
        rec = tmp_path / "armed.json"
        rec.write_text('{"preset": "gone.set"}', encoding="utf-8")
        p, src = AR.resolve_arm_preset(rec, tmp_path)
        assert p is None and "not in" in src

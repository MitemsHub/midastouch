"""Pins for the shared MT5 terminal resolver.

The load-bearing property is that it REFUSES rather than guessing. These tests
build fake %APPDATA% trees: the resolver must pick the install with today's
journal, fall back to charts, and raise — with a listing — when nothing
qualifies. A resolver that returned a default would silently put every one of
the seven previously-hardcoded call sites back to reporting verdicts from an
unreadable path (docs/STALE_FLAG_AUDIT_20260919.md).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import mt5_terminals as mt  # noqa: E402

DAY = datetime(2026, 9, 19, 21, 0, 0)
BUSY = "D0E8209F77C8CF37AD8BF550E51FF075"    # today's journal + charts
OLD = "49E0383CD680D7AAEC56888AFA08F49E"     # yesterday's journal, charts
CHARTONLY = "71BF6B2AB5548CFBA970FA2F38007C31"
GONE = "FB9A56D617EDDDFE29EE54EBEFFE96C1"     # referenced historically, absent


def _fake_appdata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))


def _journal(root, name, day: datetime, text="L\t0\t10:00:00.000\tEA\tstarted\n"):
    d = root / "MetaQuotes" / "Terminal" / name / "MQL5" / "Logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day:%Y%m%d}.log"
    p.write_text(text, encoding="utf-8")
    return p


def _terminal_journal(root, name, day: datetime,
                      text="IL\t0\t15:58:57.778\tTerminal\tMetaTrader 5 started\n"):
    """The terminal-level startup journal at ``<data>/logs/`` — NOT the Experts
    journal. A dead install that merely booted writes one of these."""
    d = root / "MetaQuotes" / "Terminal" / name / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day:%Y%m%d}.log"
    p.write_text(text, encoding="utf-8")
    return p


def _charts(root, name, store="Default", fname="chart01.chr"):
    d = root / "MetaQuotes" / "Terminal" / name / "MQL5" / "Profiles" / "Charts" / store
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_text("", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# roots
# --------------------------------------------------------------------------- #

def test_roots_follow_appdata(tmp_path, monkeypatch):
    _fake_appdata(tmp_path, monkeypatch)
    assert mt.terminal_root() == tmp_path / "MetaQuotes" / "Terminal"
    assert mt.tester_root() == tmp_path / "MetaQuotes" / "Tester"


def test_missing_root_is_empty_not_an_error(tmp_path, monkeypatch):
    _fake_appdata(tmp_path, monkeypatch)
    assert mt.terminal_dirs() == []
    assert mt.describe_terminals(DAY) == []


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #

def test_journals_covers_both_log_locations(tmp_path, monkeypatch):
    _fake_appdata(tmp_path, monkeypatch)
    _journal(tmp_path, BUSY, DAY)
    dup = tmp_path / "MetaQuotes" / "Terminal" / BUSY / "logs"
    dup.mkdir(parents=True, exist_ok=True)
    (dup / "hosting.6898457.experts.log").write_text("x", encoding="utf-8")
    names = sorted(p.name for p in mt.journals(tmp_path / "MetaQuotes" / "Terminal" / BUSY))
    assert names == ["20260919.log", "hosting.6898457.experts.log"]


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #

class TestResolveTerminal:
    def test_todays_journal_wins_over_older_and_over_charts(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, OLD, datetime(2026, 9, 18))
        _charts(tmp_path, OLD)
        _charts(tmp_path, CHARTONLY)
        _journal(tmp_path, BUSY, DAY)          # the only install that ran today
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY
        assert "journal for 2026-09-19" in why

    def test_most_recent_journal_wins_among_several(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        p1 = _journal(tmp_path, OLD, DAY)
        p2 = _journal(tmp_path, CHARTONLY, DAY)
        os.utime(p2, (1_000_000, 1_000_000))
        os.utime(p1, (2_000_000, 2_000_000))
        got, _why = mt.resolve_terminal(day=DAY)
        assert got.name == OLD

    def test_experts_journal_outranks_a_bare_startup_journal(self, tmp_path, monkeypatch):
        """THE regression this resolver exists for, found on this machine: the
        dead Deriv install (49E0383C) wrote logs/20260919.log at 15:58 today —
        "started for Deriv.com Limited" — while its MQL5/Logs stopped at 09-18.
        "Did it journal today?" would have said yes and returned an install with
        no account and no EA. "Did an EXPERT run here today?" says no."""
        _fake_appdata(tmp_path, monkeypatch)
        _terminal_journal(tmp_path, OLD, DAY)          # booted today, nothing else
        _journal(tmp_path, BUSY, DAY)                  # an EA actually ran today
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY
        assert "Experts journal" in why

    def test_bare_startup_journal_is_used_only_as_a_fallback(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _terminal_journal(tmp_path, OLD, DAY)
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == OLD
        assert "no Experts journal today" in why

    def test_bare_startup_journal_loses_to_charts_of_a_ran_today_install(
            self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _terminal_journal(tmp_path, OLD, DAY)
        _journal(tmp_path, CHARTONLY, DAY)
        _charts(tmp_path, CHARTONLY)
        got, _why = mt.resolve_terminal(day=DAY)
        assert got.name == CHARTONLY

    def test_charts_are_the_fallback_when_nothing_ran_today(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, OLD, datetime(2026, 9, 17))
        _charts(tmp_path, OLD)
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == OLD
        assert "chart files" in why

    def test_explicit_path_is_honoured(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        target = tmp_path / "MetaQuotes" / "Terminal" / CHARTONLY
        target.mkdir(parents=True, exist_ok=True)
        got, why = mt.resolve_terminal(explicit=target, day=DAY)
        assert got == target and "explicit" in why

    def test_explicit_path_that_does_not_exist_refuses(self, tmp_path, monkeypatch):
        """An explicit path is a claim by the operator; a wrong one must not
        quietly fall through to a different install."""
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_terminal(explicit=tmp_path / "nope", day=DAY)
        assert "explicitly requested" in str(exc.value)

    def test_live_bridge_path_is_authoritative(self, tmp_path, monkeypatch):
        """A consumer that already holds a live MT5 session can pass the
        data_path the bridge reports; that names the attached install outright."""
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        target = tmp_path / "MetaQuotes" / "Terminal" / CHARTONLY
        target.mkdir(parents=True, exist_ok=True)
        got, why = mt.resolve_terminal(bridge_path=target, day=DAY)
        assert got == target and "bridge" in why

    def test_bridge_path_outside_the_terminal_root_is_ignored(self, tmp_path, monkeypatch):
        """A bogus/foreign path must not hijack resolution — fall through to
        the on-disk evidence instead."""
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        outside = tmp_path / "somewhere_else"
        outside.mkdir(parents=True)
        got, why = mt.resolve_terminal(bridge_path=outside, day=DAY)
        assert got.name == BUSY and "bridge" not in why

    def test_no_evidence_refuses_and_lists_what_was_searched(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        # An install exists but has neither a journal nor charts.
        (tmp_path / "MetaQuotes" / "Terminal" / GONE).mkdir(parents=True)
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_terminal(day=DAY)
        msg = str(exc.value)
        assert "REFUSING to report a verdict" in msg
        assert "searched:" in msg
        assert GONE in msg, "the refusal must list the installs it rejected"

    def test_empty_appdata_refuses_without_crashing(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        with pytest.raises(mt.TerminalNotFound):
            mt.resolve_terminal(day=DAY)

    def test_mtime_alone_is_not_evidence(self, tmp_path, monkeypatch):
        """A terminal directory touched recently but holding no journal and no
        charts must NOT be selected. Recency is not evidence."""
        _fake_appdata(tmp_path, monkeypatch)
        stray = tmp_path / "MetaQuotes" / "Terminal" / GONE
        (stray / "config").mkdir(parents=True)
        (stray / "config" / "terminal.ini").write_text("x", encoding="utf-8")
        os.utime(stray / "config" / "terminal.ini", (9_000_000, 9_000_000))
        with pytest.raises(mt.TerminalNotFound):
            mt.resolve_terminal(day=DAY)


# --------------------------------------------------------------------------- #
# tester resolution
# --------------------------------------------------------------------------- #

class TestResolveTesterFiles:
    def _agent(self, tmp_path, name, agent, files):
        d = tmp_path / "MetaQuotes" / "Tester" / name / agent / "MQL5" / "Files"
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_text("row\n", encoding="utf-8")
        return d

    def test_prefers_the_agent_that_actually_holds_the_file(self, tmp_path, monkeypatch):
        """A stale agent directory must not win just because it is newer."""
        _fake_appdata(tmp_path, monkeypatch)
        want = "V75MacroEngine_paper_Volatility_75_Index.csv"
        stale = self._agent(tmp_path, OLD, "Agent-127.0.0.1-3000", ["other.csv"])
        fresh = self._agent(tmp_path, OLD, "Agent-127.0.0.1-3001", [want])
        os.utime(stale, (9_000_000, 9_000_000))
        got, why = mt.resolve_tester_files(want)
        assert got == fresh
        assert want in why

    def test_falls_back_to_most_recent_agent_when_file_is_absent(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        a = self._agent(tmp_path, OLD, "Agent-127.0.0.1-3000", ["other.csv"])
        b = self._agent(tmp_path, OLD, "Agent-127.0.0.1-3001", ["other.csv"])
        os.utime(a, (1_000_000, 1_000_000))
        os.utime(b, (2_000_000, 2_000_000))
        got, why = mt.resolve_tester_files("missing.csv")
        assert got == b
        assert "not found" in why

    def test_plain_hash_level_files_dir_is_accepted(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        d = tmp_path / "MetaQuotes" / "Tester" / OLD / "MQL5" / "Files"
        d.mkdir(parents=True)
        (d / "ledger.csv").write_text("row\n", encoding="utf-8")
        got, _why = mt.resolve_tester_files("ledger.csv")
        assert got == d

    def test_no_tester_at_all_refuses(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_tester_files("x.csv")
        assert "Tester" in str(exc.value)


# --------------------------------------------------------------------------- #
# Identity: installs are identified by the ACCOUNT in their journals
# --------------------------------------------------------------------------- #

#: The two accounts this machine has traded. The registry declares 1428765
#: active; anything citing another account is foreign and must never be resolved
#: as live. 140778269 is the closed MIDASTOUCH gold account on Deriv.
LIVE_ACCT = "1428765"
GOLD_ACCT = "140778269"


def _ident_journal(root, name, day, account, server, company,
                   sub="logs", extra=""):
    """A journal in MT5's real format, UTF-16LE, with a login line in it.

    The two lines written here are copied from an actual terminal journal
    (D0E8209F, 2026-09-19 21:00) so the parser is tested against the real format
    rather than a convenient one.
    """
    d = root / "MetaQuotes" / "Terminal" / name / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day:%Y%m%d}.log"
    text = (
        f"QQ\t0\t10:00:00.000\tNetwork\t'{account}': authorized on {server}\r\n"
        f"AB\t0\t10:00:01.000\tNetwork\t'{account}': terminal synchronized with "
        f"{company}: 0 positions, 0 orders, 1797 symbols\r\n" + extra
    )
    p.write_bytes(text.encode("utf-16-le"))
    return p


def _registry(tmp_path, monkeypatch, active=LIVE_ACCT, retired=(GOLD_ACCT,),
              name="accounts.json"):
    p = tmp_path / name
    p.write_text(json.dumps({
        "active": {"account": str(active)},
        "retired": [{"account": str(r)} for r in retired],
    }), encoding="utf-8")
    monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(p))
    monkeypatch.delenv("MITEMSHUB_MT5_ACCOUNT", raising=False)
    return p


class TestJournalIdentity:
    def test_reads_the_real_mt5_login_format(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _ident_journal(tmp_path, BUSY, DAY, LIVE_ACCT, "Upcomers-Server",
                       "Upcomers Ltd.")
        ident = mt.terminal_identity(tmp_path / "MetaQuotes" / "Terminal" / BUSY)
        assert ident.accounts == (LIVE_ACCT,)
        assert ident.servers == ("Upcomers-Server",)
        assert ident.companies == ("Upcomers Ltd.",)
        assert ident.identified and ident.cites(LIVE_ACCT)
        assert LIVE_ACCT in ident.summary()

    def test_a_bare_digit_run_is_not_an_account(self, tmp_path, monkeypatch):
        """A loose digit scan finds timestamps and tickets; the parser must not."""
        _fake_appdata(tmp_path, monkeypatch)
        p = tmp_path / "MetaQuotes" / "Terminal" / BUSY / "logs"
        p.mkdir(parents=True)
        (p / f"{DAY:%Y%m%d}.log").write_bytes(
            ("AA\t0\t10:00:00.000\tTrade\torder #178965720 executed at 123456789\r\n"
             "BB\t0\t10:00:01.000\tExperts\tEA started, equity 25000.00\r\n"
             ).encode("utf-16-le"))
        ident = mt.terminal_identity(tmp_path / "MetaQuotes" / "Terminal" / BUSY)
        assert ident.accounts == ()
        assert not ident.identified

    def test_read_journal_text_handles_both_encodings(self, tmp_path):
        utf16 = tmp_path / "u16.log"
        utf16.write_bytes("'7': authorized on S\r\n".encode("utf-16"))
        assert "authorized" in mt.read_journal_text(utf16)
        # ...and a BOM-less UTF-16LE file, which is what MT5 actually writes
        u16le = tmp_path / "u16le.log"
        u16le.write_bytes("'7': authorized on S\r\n".encode("utf-16-le"))
        assert "authorized" in mt.read_journal_text(u16le)
        # ...and plain UTF-8, which the fake trees and PowerShell logs use
        u8 = tmp_path / "u8.log"
        u8.write_text("'7': authorized on S\n", encoding="utf-8")
        assert "authorized" in mt.read_journal_text(u8)

    def test_an_unreadable_path_yields_empty_not_an_exception(self, tmp_path):
        assert mt.read_journal_text(tmp_path / "does-not-exist.log") == ""


class TestAccountRegistry:
    def test_registry_is_read_from_the_declared_path(self, tmp_path, monkeypatch):
        _registry(tmp_path, monkeypatch)
        reg = mt.load_account_registry()
        assert reg.loaded and reg.active == (LIVE_ACCT,)
        assert GOLD_ACCT in reg.retired
        assert LIVE_ACCT in reg.status()

    def test_env_var_overrides_the_declared_account(self, tmp_path, monkeypatch):
        _registry(tmp_path, monkeypatch)
        monkeypatch.setenv("MITEMSHUB_MT5_ACCOUNT", "9999999")
        assert mt.load_account_registry().active == ("9999999",)

    def test_missing_registry_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(tmp_path / "absent.json"))
        reg = mt.load_account_registry()
        assert not reg.loaded
        assert "no account registry" in reg.error

    def test_unreadable_registry_is_reported_not_raised(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(bad))
        assert not mt.load_account_registry().loaded

    def test_an_install_citing_another_account_is_foreign(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC")
        ident = mt.terminal_identity(tmp_path / "MetaQuotes" / "Terminal" / OLD)
        klass, why = mt.classify_identity(ident, mt.load_account_registry())
        assert klass == mt.FOREIGN
        assert GOLD_ACCT in why

    def test_an_install_citing_nothing_is_unknown_not_foreign(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        ident = mt.terminal_identity(tmp_path / "MetaQuotes" / "Terminal" / BUSY)
        klass, _why = mt.classify_identity(ident, mt.load_account_registry())
        assert klass == mt.UNKNOWN

    def test_without_a_registry_nothing_can_be_called_foreign(self, tmp_path, monkeypatch):
        """No declared active account means no basis to exclude; say so loudly."""
        _fake_appdata(tmp_path, monkeypatch)
        monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(tmp_path / "absent.json"))
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC")
        ident = mt.terminal_identity(tmp_path / "MetaQuotes" / "Terminal" / OLD)
        klass, why = mt.classify_identity(ident, mt.load_account_registry())
        assert klass == mt.UNKNOWN
        assert "no active account is declared" in why


class TestIdentityDrivesResolution:
    def test_active_account_wins_even_with_the_oldest_journal(self, tmp_path, monkeypatch):
        """THE CORE FIX. Recency would pick the foreign install; identity must not."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        foreign = tmp_path / "MetaQuotes" / "Terminal" / OLD
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC", sub="MQL5/Logs")
        os.utime(foreign / "MQL5" / "Logs" / f"{DAY:%Y%m%d}.log",
                 (9_000_000_000, 9_000_000_000))     # far newer than anything
        _ident_journal(tmp_path, BUSY, datetime(2026, 9, 1), LIVE_ACCT,
                       "Upcomers-Server", "Upcomers Ltd.")   # 18 days stale

        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY, "identity must outrank mtime"
        assert "active account" in why and LIVE_ACCT in why

    def test_a_retired_install_that_merely_booted_today_is_never_selected(
            self, tmp_path, monkeypatch):
        """The exact 2026-09-19 trap: a dead install with TODAY's journal.

        The foreign install has an Experts journal for today AND charts; the live
        install has only a chart and an old journal. Every recency test points at
        the dead install. Identity must overrule all of them.
        """
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC", sub="MQL5/Logs",
                       extra="IL\t0\t15:58:57.778\tTerminal\tMetaTrader 5 x64 build 6182 started for Deriv.com Limited\r\n")
        _charts(tmp_path, OLD)
        _ident_journal(tmp_path, BUSY, datetime(2026, 9, 10), LIVE_ACCT,
                       "Upcomers-Server", "Upcomers Ltd.")

        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY
        assert OLD not in str(got)
        assert "excluded" in why and GOLD_ACCT in why

    def test_foreign_install_is_excluded_even_as_the_only_one_with_charts(
            self, tmp_path, monkeypatch):
        """With the live install showing nothing, the answer is a refusal -- not
        the dead install that happens to hold charts."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _charts(tmp_path, OLD)
        _ident_journal(tmp_path, OLD, datetime(2026, 9, 12), GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC")
        (tmp_path / "MetaQuotes" / "Terminal" / BUSY).mkdir(parents=True)
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_terminal(day=DAY)
        assert "do not trade" in str(exc.value)
        assert GOLD_ACCT in str(exc.value)

    def test_refuses_when_every_install_belongs_to_a_closed_program(
            self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        for name in (OLD, CHARTONLY):
            _ident_journal(tmp_path, name, DAY, GOLD_ACCT,
                           "DerivSVG-Server-03", "Deriv (SVG) LLC")
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_terminal(day=DAY)
        msg = str(exc.value)
        assert "every install belongs to an account we do not trade" in msg
        assert "EXCLUDED" in msg

    def test_an_unknown_install_is_eligible_but_flagged(self, tmp_path, monkeypatch):
        """A fresh install that has never logged in is usable, and the ambiguity
        is stated rather than hidden."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)          # no account lines at all
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY
        assert "not confirmed as ours" in why

    def test_a_missing_registry_downgrades_loudly(self, tmp_path, monkeypatch):
        """Without the registry the exclusion cannot happen, and that must be
        visible in the reason rather than silently absent."""
        _fake_appdata(tmp_path, monkeypatch)
        monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(tmp_path / "absent.json"))
        _journal(tmp_path, BUSY, DAY)
        _got, why = mt.resolve_terminal(day=DAY)
        assert "nothing was excluded by account" in why

    def test_two_installs_citing_the_active_account_break_the_tie_by_recency(
            self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _ident_journal(tmp_path, BUSY, DAY, LIVE_ACCT,
                       "Upcomers-Server", "Upcomers Ltd.")
        _ident_journal(tmp_path, CHARTONLY, DAY, LIVE_ACCT,
                       "Upcomers-Server", "Upcomers Ltd.")
        old = tmp_path / "MetaQuotes" / "Terminal" / CHARTONLY / "logs" / f"{DAY:%Y%m%d}.log"
        os.utime(old, (1_000_000, 1_000_000))
        got, why = mt.resolve_terminal(day=DAY)
        assert got.name == BUSY
        assert "newest of 2 installs citing it" in why

    def test_an_explicit_path_still_overrides_identity(self, tmp_path, monkeypatch):
        """An operator naming a directory is not guessing; only defaults are
        subject to the identity rule."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC")
        got, why = mt.resolve_terminal(explicit=tmp_path / "MetaQuotes" / "Terminal" / OLD)
        assert got.name == OLD
        assert "explicit" in why


class TestIdentityInHolding:
    def test_holding_prefers_the_active_accounts_install(self, tmp_path, monkeypatch):
        """Both installs hold the file; the live one is the one to read."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        for name, acct, server, co in ((BUSY, LIVE_ACCT, "Upcomers-Server", "Upcomers Ltd."),
                                       (OLD, GOLD_ACCT, "DerivSVG-Server-03", "Deriv (SVG) LLC")):
            d = tmp_path / "MetaQuotes" / "Terminal" / name / "MQL5" / "Files"
            d.mkdir(parents=True)
            (d / "telemetry.jsonl").write_text("row\n", encoding="utf-8")
            _ident_journal(tmp_path, name, DAY, acct, server, co)
        os.utime(tmp_path / "MetaQuotes" / "Terminal" / OLD / "MQL5" / "Files" / "telemetry.jsonl",
                 (9_000_000_000, 9_000_000_000))
        got, why = mt.resolve_terminal_holding("telemetry.jsonl")
        assert got.name == BUSY
        assert "active account" in why

    def test_holding_warns_when_only_a_closed_program_holds_it(self, tmp_path, monkeypatch):
        """Retired evidence is still readable -- but the caller is told what it is."""
        _fake_appdata(tmp_path, monkeypatch)
        _registry(tmp_path, monkeypatch)
        d = tmp_path / "MetaQuotes" / "Terminal" / OLD / "MQL5" / "Files"
        d.mkdir(parents=True)
        (d / "ledger.csv").write_text("row\n", encoding="utf-8")
        _ident_journal(tmp_path, OLD, DAY, GOLD_ACCT,
                       "DerivSVG-Server-03", "Deriv (SVG) LLC")
        _ident_journal(tmp_path, BUSY, DAY, LIVE_ACCT,
                       "Upcomers-Server", "Upcomers Ltd.")
        got, why = mt.resolve_terminal_holding("ledger.csv")
        assert got.name == OLD, "the evidence is where it is"
        assert "closed program" in why, "...and the caller must be told that"


class TestResolveTerminalHolding:
    """"Which install is live" and "which install holds the records" are
    different questions. On 2026-09-19 they had different answers: the live
    install held zero telemetry files while two other installs held them, so a
    consumer that asked the first question and read for the second found nothing
    and graded an empty read as a verdict."""

    def _holds(self, tmp_path, name, files, sub="MQL5/Files"):
        d = tmp_path / "MetaQuotes" / "Terminal" / name / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_text("row\n", encoding="utf-8")
        return d

    def test_evidence_beats_liveness(self, tmp_path, monkeypatch):
        """BUSY ran today and has charts; OLD holds the file. OLD must win."""
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        _charts(tmp_path, BUSY)
        self._holds(tmp_path, OLD, ["MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl"])
        got, why = mt.resolve_terminal_holding("MitemshubAI*telemetry*.jsonl")
        assert got.name == OLD
        assert "MitemshubAI*telemetry*.jsonl" in why

    def test_refuses_when_nothing_holds_it(self, tmp_path, monkeypatch):
        """A readable-looking install with no matching file is NOT evidence."""
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        _charts(tmp_path, BUSY)
        with pytest.raises(mt.TerminalNotFound) as exc:
            mt.resolve_terminal_holding("MitemshubAI*telemetry*.jsonl")
        msg = str(exc.value)
        assert "MitemshubAI*telemetry*.jsonl" in msg
        assert "REFUSING" in msg

    def test_searches_the_experts_journal_location_too(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, OLD, DAY, text="banner line\n")
        got, _why = mt.resolve_terminal_holding("*.log")
        assert got.name == OLD

    def test_no_terminals_at_all_refuses_without_crashing(self, tmp_path, monkeypatch):
        _fake_appdata(tmp_path, monkeypatch)
        with pytest.raises(mt.TerminalNotFound):
            mt.resolve_terminal_holding("anything*")


# --------------------------------------------------------------------------- #
# CLI — the PowerShell tools depend on this contract
# --------------------------------------------------------------------------- #

class TestCli:
    def test_terminal_prints_a_bare_path(self, tmp_path, monkeypatch, capsys):
        _fake_appdata(tmp_path, monkeypatch)
        _journal(tmp_path, BUSY, DAY)
        monkeypatch.setattr(mt, "datetime", _FrozenDatetime)
        assert mt.main(["--terminal"]) == 0
        out = capsys.readouterr().out.strip()
        assert out.endswith(BUSY)
        assert "selected by" not in out

    def test_refusal_exits_non_zero_and_explains(self, tmp_path, monkeypatch, capsys):
        _fake_appdata(tmp_path, monkeypatch)
        assert mt.main(["--terminal"]) == 1
        err = capsys.readouterr().err
        assert "REFUSING" in err

    def test_list_exits_non_zero_when_there_is_nothing(self, tmp_path, monkeypatch, capsys):
        _fake_appdata(tmp_path, monkeypatch)
        assert mt.main(["--list"]) == 1
        assert "no terminal directories" in capsys.readouterr().out


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102
        return DAY

#!/usr/bin/env python3
"""Single source of truth for locating MT5 terminal / tester data directories.

WHY THIS EXISTS (2026-09-19). Operator tooling across this repo pinned MT5 data
directories by 32-hex install hash — seven sites, and not one of them pointed at
the terminal actually being traded on. When those installs went away, the scripts
did not fail. They read nothing and then **reported a verdict anyway**:

  * `scripts/confirm-gate-open.ps1` printed `cblearn: ... (fresh gate, OPEN until
    first trades)` — a positive assertion of an OPEN gate;
  * `scripts/funnel_diff.py` read a dead root, counted 0 for every counter, and
    would have reported `match (0)` per row;
  * `scripts/demo_watchdog.py` printed `no EA trades on this account yet` and
    exited 2, i.e. "the account is quiet" rather than "I cannot see the account";
  * `scripts/atr_drift_monitor.py` fell back to its frozen calibration band and
    still emitted a within-tolerance verdict.

A tool that reports a verdict from a path it could not read is indistinguishable
from one reporting green. That is the same fault class as the retired VPS-hosting
marker — see `docs/STALE_FLAG_AUDIT_20260919.md`.

THE RULE THIS MODULE ENFORCES. Resolve from evidence ON DISK, and refuse when
there is none. `resolve_terminal()` raises `TerminalNotFound` instead of returning
a plausible-looking default, and every consumer is expected to let that reach the
operator as a non-zero exit.

RESOLUTION PRECEDENCE (declared, in order):

  1. an explicit path, if the caller supplied one and it exists;
  2. a ``bridge_path`` hint — the ``data_path`` a live MetaTrader5 python session
     reports, which is authoritative because it is the install the bridge is
     actually attached to. Only accepted when it resolves inside the Terminal
     root, and only when the caller passes it: this module never calls
     ``mt5.initialize()`` itself, because doing so can LAUNCH a terminal as a
     side effect (see "no side effects" below);
  3. **terminal dirs whose journals cite the ACTIVE account** (see IDENTITY
     below) — this outranks every recency test;
  4. terminal dirs holding an EXPERTS journal (``MQL5/Logs/YYYYMMDD.log``) for
     today — most recently written first, but only among installs that are not
     known to belong to a foreign account;
  5. terminal dirs holding any journal for today, including the legacy
     terminal-level ``logs/`` — same restriction;
  6. terminal dirs holding chart files — most recently written first. An install
     with charts but no journal today is a real install that simply did not run;
  7. otherwise: raise, and say exactly what was searched.

IDENTITY: WHY RECENCY WAS NOT ENOUGH (2026-09-19, second pass). Steps 4-6 rank
candidates by mtime, and mtime is not identity. The DEAD Deriv install (49E0383C)
wrote ``logs/20260919.log`` at 15:58 today reading "MetaTrader 5 Terminal x64
build 6182 started for Deriv.com Limited" — so a terminal that merely BOOTED,
with no account and no EA, satisfied every recency test and was a plausible
answer to "which terminal are we trading on?". Ranking it below a better
candidate only helps when a better candidate exists; when the live install has no
journal for today, recency hands the answer to a dead one.

So installs are identified by the ACCOUNT NUMBER in their journals. MT5 writes
unambiguous lines, and they are the only thing on disk that names the account:

    '1428765': authorized on Upcomers-Server
    '1428765': terminal synchronized with Upcomers Ltd.: 0 positions, 0 orders

The registry at ``configs/mt5/accounts.json`` declares which account is active
and which are retired. Three classifications follow:

  * **active**   — the install cites the active account. Wins outright.
  * **foreign**  — the install cites only accounts we do not trade. **Excluded
    from every fallback**, so it can never be selected, however recently written.
    Retired entries in the registry are what do this; deleting one re-arms the
    trap it exists to prevent.
  * **unknown**  — the install cites no account at all (a fresh install that has
    never logged in). Eligible, and the ambiguity is stated in the "selected by"
    reason rather than hidden.

Without a registry there is no declared active account, so nothing can be called
foreign and the strong guarantee is unavailable. That is reported in the reason
string rather than passed over, so a missing registry cannot silently downgrade
the resolution to recency.

WHY EXPERTS JOURNALS OUTRANK TERMINAL JOURNALS (measured 2026-09-19). MT5 writes
two different journals: the terminal's own startup/connection journal to
``<data>/logs/``, and the Experts journal to ``<data>/MQL5/Logs/``. On this
machine the DEAD Deriv install (49E0383C) had a ``logs/20260919.log`` written at
15:58 today reading "MetaTrader 5 Terminal x64 build 6182 started for
Deriv.com Limited" — a terminal that merely booted, in an install with no
account and no EA, satisfied a naive "did this journal today?" test and would
have been a plausible answer. Its ``MQL5/Logs`` stopped at 09-18. So the test is
"did an EXPERT run here today", and the container-level journal is only a
fallback.

DELIBERATELY NOT A RULE: "most recently modified directory". A terminal directory
is touched by things other than trading, so recency alone would happily return an
install nobody trades on. Evidence is a journal or a chart, not an mtime.

NO SIDE EFFECTS. Resolution is pure filesystem inspection. ``mt5.initialize()``
can spawn a Terminal process when none is running, so this module never calls it;
consumers that already hold a live bridge pass ``bridge_path`` instead.

CLI (so the PowerShell tools can share this one implementation):

    python scripts/mt5_terminals.py --terminal     # print the resolved dir, or exit 1
    python scripts/mt5_terminals.py --list         # every terminal dir, its account, its evidence
    python scripts/mt5_terminals.py --tester FILE  # the Tester Files dir holding FILE
    #   --explain adds which evidence selected the directory
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

__all__ = [
    "TerminalNotFound",
    "AccountRegistry",
    "TerminalIdentity",
    "appdata",
    "terminal_root",
    "tester_root",
    "terminal_dirs",
    "tester_dirs",
    "journals",
    "experts_journals",
    "chart_files",
    "read_journal_text",
    "terminal_identity",
    "classify_identity",
    "load_account_registry",
    "describe_terminals",
    "resolve_terminal",
    "resolve_terminal_holding",
    "resolve_tester_files",
    "refusal",
]


class TerminalNotFound(RuntimeError):
    """No MT5 terminal directory could be resolved from evidence on disk."""


# --------------------------------------------------------------------------- #
# Roots
# --------------------------------------------------------------------------- #

def appdata() -> Path:
    """``%APPDATA%`` (Windows) or the home fallback (other platforms, tests)."""
    env = os.environ.get("APPDATA")
    if env:
        return Path(env)
    return Path.home() / ".config"


def terminal_root() -> Path:
    return appdata() / "MetaQuotes" / "Terminal"


def tester_root() -> Path:
    return appdata() / "MetaQuotes" / "Tester"


def _subdirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    except OSError:
        return []


def terminal_dirs() -> list[Path]:
    """Every terminal data directory, including ``Common``/``Community``.

    The non-hash folders are returned because they are real directories that
    consumers do look inside (``Common/MQL5/Presets``), and because excluding them
    by name would mean guessing at a naming convention.
    """
    return _subdirs(terminal_root())


def tester_dirs() -> list[Path]:
    return _subdirs(tester_root())


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #

def journals(td: Path) -> list[Path]:
    """Every journal file: the Experts journal plus the terminal-level journal."""
    out: list[Path] = []
    for sub in ("MQL5/Logs", "logs"):
        d = td / sub
        if d.is_dir():
            try:
                out += [p for p in d.glob("*.log") if p.is_file()]
            except OSError:
                continue
    return sorted(out)


def experts_journals(td: Path) -> list[Path]:
    """Only the Experts journal (``MQL5/Logs``) — where an EA's prints go.

    Kept separate from :func:`journals` because the two answer different
    questions: ``logs/`` says "this install booted", ``MQL5/Logs`` says "an
    expert ran here". The resolver ranks the second above the first.
    """
    d = td / "MQL5" / "Logs"
    if not d.is_dir():
        return []
    try:
        return sorted(p for p in d.glob("*.log") if p.is_file())
    except OSError:
        return []


def _dated(paths: list[Path], day: datetime) -> list[Path]:
    stamp = f"{day:%Y%m%d}.log"
    return [p for p in paths if p.name == stamp]


def chart_files(td: Path) -> list[Path]:
    """Chart files — an install with charts is an install somebody uses."""
    d = td / "MQL5" / "Profiles" / "Charts"
    if not d.is_dir():
        return []
    try:
        return sorted(p for p in d.glob("*/*.chr") if p.is_file())
    except OSError:
        return []


def _has_todays_journal(td: Path, day: datetime | None = None) -> bool:
    day = day or datetime.now()
    return bool(_dated(journals(td), day))


def _has_todays_experts_journal(td: Path, day: datetime | None = None) -> bool:
    day = day or datetime.now()
    return bool(_dated(experts_journals(td), day))


def newest_mtime(paths: list[Path]) -> float:
    """Most recent mtime among files, 0.0 when there are none."""
    return max((p.stat().st_mtime for p in paths), default=0.0)


# --------------------------------------------------------------------------- #
# Identity: which account does this install belong to?
# --------------------------------------------------------------------------- #

ACTIVE = "active"
"""The install cites the account we actually trade."""

FOREIGN = "foreign"
"""The install cites only accounts we do not trade. Excluded from every fallback."""

UNKNOWN = "unknown"
"""No account is named in its journals -- eligible, but flagged as ambiguous."""

#: How many of an install's most recent journals to read. Identity is stable over
#: an install's life, so a window is enough, and it bounds the cost on an install
#: that has accumulated years of logs.
IDENTITY_JOURNAL_LIMIT = 20

#: The account number MT5 quotes when it names a connection. Anchored on the
#: quoting so a 9-digit unix timestamp (178965720) or a ticket number cannot
#: match -- a loose ``\d{6,9}`` scan finds plenty of both.
_ACCOUNT_RE = re.compile(r"'(\d{5,10})'\s*:")
#: The server name has TWO line shapes in real journals and both must match:
#:   '1428765': authorized on Upcomers-Server
#:   '1428765': authorized on Upcomers-Server through Access Server DE (ping: ...)
#: so the name ends at " through" OR at end of line. Without re.M the end-of-line
#: alternative never fires on a multi-line journal and the first shape is missed.
_SERVER_RE = re.compile(
    r"'(\d{5,10})'\s*:\s*authorized on\s+([^\r\n]+?)(?:\s+through\s+|\s*$)", re.M)
_COMPANY_RE = re.compile(
    r"'(\d{5,10})'\s*:\s*terminal synchronized with\s+([^:\r\n]+):")


def read_journal_text(path: Path) -> str:
    """Decode one journal file, or return "" when it cannot be read.

    MT5 writes journals as UTF-16LE. Sniffing matters here: decoding UTF-8 as
    UTF-16 does not always raise -- it can succeed and yield interleaved NULs,
    which would make every identity regex miss silently. So the codec is chosen
    from the bytes rather than guessed from a try/except.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    # UTF-16LE with no BOM is half NUL bytes for ASCII text; UTF-8 never is.
    if b"\x00" in raw[:256]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class TerminalIdentity:
    """The account/server/company names an install's journals testify to."""

    accounts: tuple[str, ...] = ()
    servers: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    journals_scanned: int = 0

    @property
    def identified(self) -> bool:
        return bool(self.accounts)

    def cites(self, account: str | int) -> bool:
        return str(account) in self.accounts

    def summary(self) -> str:
        if not self.identified:
            return "no account named in its journals"
        parts = [f"acct {'/'.join(self.accounts)}"]
        if self.servers:
            parts.append(f"server {self.servers[0]}")
        if self.companies:
            parts.append(f"company {self.companies[0]}")
        return ", ".join(parts)


def terminal_identity(td: Path,
                      limit: int = IDENTITY_JOURNAL_LIMIT) -> TerminalIdentity:
    """Read an install's newest journals and extract who it belongs to."""
    try:
        js = sorted(journals(td), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return TerminalIdentity()
    accounts: list[str] = []
    servers: list[str] = []
    companies: list[str] = []
    for j in js:
        txt = read_journal_text(j)
        if not txt:
            continue
        for m in _ACCOUNT_RE.finditer(txt):
            if m.group(1) not in accounts:
                accounts.append(m.group(1))
        for m in _SERVER_RE.finditer(txt):
            s = m.group(2).strip()
            if s and s not in servers:
                servers.append(s)
        for m in _COMPANY_RE.finditer(txt):
            c = m.group(2).strip()   # group(1) is the account; group(2) the company
            if c and c not in companies:
                companies.append(c)
    return TerminalIdentity(tuple(accounts), tuple(servers), tuple(companies), len(js))


@dataclass(frozen=True)
class AccountRegistry:
    """The declared active account, and the accounts we have stopped trading.

    Loaded from ``configs/mt5/accounts.json``. An absent or unreadable registry
    yields an empty value with :attr:`error` set, never an exception: resolution
    must still work, it just loses the power to exclude, and that loss is
    reported in the "selected by" reason rather than passed over.
    """

    active: tuple[str, ...] = ()
    retired: tuple[str, ...] = ()
    path: str = ""
    error: str = ""
    #: The sizing basis of the active account, in USD. 0.0 means NOT DECLARED, and
    #: every reader must refuse on it: the basis used to live in three places at once
    #: ($1,000 tester deposit, $5,000 python START_EQUITY, $5,000 EA paper equity) and
    #: a default here would silently pick a fourth.
    account_size_usd: float = 0.0

    @property
    def loaded(self) -> bool:
        return bool(self.active)

    def status(self) -> str:
        if self.loaded:
            basis = (f"basis ${self.account_size_usd:,.0f}" if self.account_size_usd
                     else "basis NOT DECLARED")
            return (f"active acct {', '.join(self.active)} ({basis})"
                    + (f"; retired {', '.join(self.retired)}" if self.retired else ""))
        return self.error or "no active account declared"


def _default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs" / "mt5" / "accounts.json"


def load_account_registry(path: str | os.PathLike | None = None) -> AccountRegistry:
    """Read the account registry. Never raises.

    ``MITEMSHUB_MT5_ACCOUNT`` overrides the declared active account outright (for
    a one-off against a different login); ``MITEMSHUB_MT5_REGISTRY`` points at a
    different registry file (for tests).
    """
    p = Path(path or os.environ.get("MITEMSHUB_MT5_REGISTRY")
             or _default_registry_path())
    if not p.is_file():
        return AccountRegistry(path=str(p),
                               error=f"no account registry at {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return AccountRegistry(path=str(p), error=f"account registry unreadable: {exc}")

    act = raw.get("active") or {}
    active = [str(act.get("account", "")).strip()] if act.get("account") else []
    env = (os.environ.get("MITEMSHUB_MT5_ACCOUNT") or "").strip()
    if env:
        active = [env]
    retired = [str(r.get("account", "")).strip() for r in (raw.get("retired") or [])]
    try:
        basis = float(act.get("account_size_usd") or 0.0)
    except (TypeError, ValueError):
        basis = 0.0
    return AccountRegistry(active=tuple(a for a in active if a),
                           retired=tuple(n for n in retired if n),
                           path=str(p),
                           account_size_usd=basis)


def active_account_size() -> float:
    """The active account's sizing basis in USD, or raise.

    REFUSES rather than defaulting. Every caller that sizes anything — the parity
    tester's deposit, the python engine's starting equity, the EA's paper mirror —
    asks this one question, and a wrong answer here is a whole book of results about
    an account that does not exist. There is no sensible fallback, so there is none.
    """
    reg = load_account_registry()
    if not reg.loaded:
        raise TerminalNotFound(
            f"no active account declares a sizing basis: {reg.status()} "
            f"(registry {reg.path or 'not found'})")
    if reg.account_size_usd <= 0:
        raise TerminalNotFound(
            f"the registry declares active account {', '.join(reg.active)} with no "
            f"account_size_usd, so no engine can be told what it is sizing for "
            f"(registry {reg.path}). Add the field; do not default it.")
    return reg.account_size_usd


def classify_identity(ident: TerminalIdentity,
                      registry: AccountRegistry) -> tuple[str, str]:
    """Classify one install as active / foreign / unknown, with a reason."""
    if not ident.identified:
        return UNKNOWN, "no account named in its journals"
    if not registry.loaded:
        return UNKNOWN, (f"names acct {'/'.join(ident.accounts)} but no active "
                         f"account is declared, so it cannot be confirmed")
    for a in ident.accounts:
        if a in registry.active:
            return ACTIVE, f"journals cite the active account {a}"
    return FOREIGN, (f"journals cite acct {'/'.join(ident.accounts)}, none of "
                     f"which is the active account")


def describe_terminals(day: datetime | None = None) -> list[dict]:
    """Every terminal directory with the evidence that would select it.

    This is the payload of a refusal: the operator should be able to see which
    installs exist and why none of them qualified, without running more commands.
    """
    day = day or datetime.now()
    registry = load_account_registry()
    out = []
    for td in terminal_dirs():
        j = journals(td)
        ej = experts_journals(td)
        ch = chart_files(td)
        newest = max(j, key=lambda p: p.stat().st_mtime, default=None)
        ident = terminal_identity(td)
        klass, why = classify_identity(ident, registry)
        out.append({
            "dir": str(td),
            "name": td.name,
            "experts_today": bool(_dated(ej, day)),
            "journal_today": bool(_dated(j, day)),
            "journal_count": len(j),
            # by MTIME, not by name: 'metaeditor.log' sorts after '20260919.log'
            # alphabetically and used to be reported as the latest journal.
            "newest_journal": newest.name if newest else None,
            "charts": len(ch),
            "mtime": round(newest_mtime(j) or newest_mtime(ch), 1),
            # identity: the account this install testifies to, and what that makes it
            "accounts": ident.accounts,
            "servers": ident.servers,
            "identity": klass,
            "identity_why": why,
        })
    return out


def refusal(what: str, detail: str = "") -> TerminalNotFound:
    lines = [f"cannot resolve {what}: no evidence on disk.", ""]
    if detail:
        lines += [detail, ""]
    lines.append(f"searched: {terminal_root()}")
    rows = describe_terminals()
    if not rows:
        lines.append("  (the directory does not exist, or contains no subdirectories)")
    else:
        reg = load_account_registry()
        lines.append(f"  account registry: {reg.status()}")
        lines.append("")
        lines.append(f"  {'name':<34} {'identity':<9} {'accounts':<14} "
                     f"{'experts today':<15} {'charts':<7} newest journal")
        for r in rows:
            accts = "/".join(r.get("accounts") or ()) or "-"
            lines.append(f"  {r['name']:<34} {r.get('identity', '?'):<9} "
                         f"{accts:<14} {str(r['experts_today']):<15} "
                         f"{r['charts']:<7} {r['newest_journal'] or '-'}")
        excluded = [r for r in rows if r.get("identity") == FOREIGN]
        if excluded:
            lines.append("")
            lines.append("  EXCLUDED (they belong to an account we do not trade, "
                         "however recently they were written):")
            for r in excluded:
                lines.append(f"    {r['name']}: {r.get('identity_why', '')}")
        lines.append("")
        lines.append("  none of these qualified. Pass an explicit path if the "
                     "install lives elsewhere.")
    lines.append("")
    lines.append("REFUSING to report a verdict from a path that cannot be read "
                 "(docs/STALE_FLAG_AUDIT_20260919.md).")
    return TerminalNotFound("\n".join(lines))


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def resolve_terminal(explicit: str | os.PathLike | None = None,
                     day: datetime | None = None,
                     bridge_path: str | os.PathLike | None = None) -> tuple[Path, str]:
    """The MT5 terminal directory to operate on, and the evidence that chose it.

    Raises :class:`TerminalNotFound` when nothing qualifies — never returns a
    default. Callers that want a soft failure must catch it deliberately.

    ``bridge_path`` is for consumers that already hold a live MetaTrader5 session
    (``mt5.terminal_info().data_path``): that is authoritative, because it names
    the install the bridge is attached to. It is only accepted when it resolves to
    an existing directory under this machine's Terminal root.
    """
    day = day or datetime.now()
    if explicit:
        p = Path(str(explicit)).expanduser()
        if p.is_dir():
            return p, f"explicit path ({p.name})"
        raise refusal("the explicitly requested terminal", f"given: {explicit}")

    if bridge_path:
        bp = Path(str(bridge_path)).expanduser()
        try:
            inside = bp.resolve().is_relative_to(terminal_root().resolve())
        except (OSError, ValueError):
            inside = False
        if bp.is_dir() and inside:
            return bp, f"live MT5 bridge reports this data_path ({bp.name})"

    dirs = terminal_dirs()
    registry = load_account_registry()
    idents = {td: terminal_identity(td) for td in dirs}
    klass = {td: classify_identity(idents[td], registry) for td in dirs}

    # --- foreign installs are excluded from every fallback ----------------- #
    # Computed before the identity branch so that a SUCCESSFUL resolution also
    # reports what it passed over -- an operator who cannot see that the dead
    # install was considered and rejected cannot tell a real resolution from a
    # lucky one.
    foreign = [td for td in dirs if klass[td][0] == FOREIGN]
    eligible = [td for td in dirs if klass[td][0] != FOREIGN]
    excl_note = ""
    if foreign:
        excl_note = ("; excluded " + "; ".join(
            f"{td.name} ({idents[td].summary()})" for td in foreign))
    if not registry.loaded:
        excl_note += ("; WARNING nothing was excluded by account because "
                      f"{registry.status()}")

    # --- identity outranks every recency test ------------------------------ #
    # An install that names the account we trade IS the install we trade on. This
    # is checked before mtime because mtime is not identity: a dead install that
    # merely booted has today's journal, and if the live install did not run an
    # expert today, recency alone hands the answer to the dead one.
    active_dirs = [td for td in dirs if klass[td][0] == ACTIVE]
    if active_dirs:
        best = max(active_dirs,
                   key=lambda td: newest_mtime(journals(td) + chart_files(td)))
        why = f"journals cite the active account ({idents[best].summary()})"
        if len(active_dirs) > 1:
            why += (f" [newest of {len(active_dirs)} installs citing it; others: "
                    f"{', '.join(t.name for t in active_dirs if t != best)}]")
        return best, why + excl_note

    if not eligible:
        detail = (f"every install belongs to an account we do not trade"
                  if foreign else
                  f"no install declares an account and none ran an expert today")
        if not registry.loaded:
            detail += (f". The account registry could not be read, so installs "
                       f"cannot be classified at all: {registry.status()}")
        raise refusal("an MT5 terminal directory belonging to the active account",
                      detail)

    # An Experts journal for today is the strongest remaining offline evidence:
    # it means an EA actually ran here today, not merely that the install booted.
    with_experts = [td for td in eligible if _has_todays_experts_journal(td, day)]
    if with_experts:
        best = max(with_experts, key=lambda td: newest_mtime(experts_journals(td)))
        why = f"Experts journal for {day:%Y-%m-%d} (most recently written)"
        if not idents[best].identified:
            why += "; NOTE this install names no account, so it is not confirmed as ours"
        return best, why + excl_note

    # Then any journal for today, including the terminal-level ``logs/``.
    with_journal = [td for td in eligible if _has_todays_journal(td, day)]
    if with_journal:
        best = max(with_journal, key=lambda td: newest_mtime(journals(td)))
        why = (f"terminal-level journal for {day:%Y-%m-%d} "
               "(no Experts journal today; most recently written)")
        if not idents[best].identified:
            why += "; NOTE this install names no account, so it is not confirmed as ours"
        return best, why + excl_note

    with_charts = [(td, chart_files(td)) for td in eligible]
    with_charts = [(td, ch) for td, ch in with_charts if ch]
    if with_charts:
        best = max(with_charts, key=lambda pair: newest_mtime(pair[1]))[0]
        why = "chart files present (most recently written)"
        if not idents[best].identified:
            why += "; NOTE this install names no account, so it is not confirmed as ours"
        return best, why + excl_note

    raise refusal("an MT5 terminal directory belonging to the active account",
                  "no eligible install ran today and none of them holds charts"
                  + excl_note)


def resolve_terminal_holding(pattern: str,
                             search: tuple[str, ...] = ("MQL5/Files", "MQL5/Logs",
                                                       "logs")) -> tuple[Path, str]:
    """The terminal whose data directory holds a file matching ``pattern``.

    For consumers whose subject is a specific account's RECORDS rather than
    "whatever is live". Those are different questions, and conflating them is a
    measured failure: on 2026-09-19 the live install held zero telemetry files
    while two other installs held them, so a script that asked "where is the live
    terminal?" and then read for telemetry found nothing and reported an empty
    account as a quiet one. Ask for the evidence instead.
    """
    hits: list[Path] = []
    for td in terminal_dirs():
        for sub in search:
            d = td / sub
            try:
                if d.is_dir() and next(d.glob(pattern), None) is not None:
                    hits.append(td)
                    break
            except OSError:
                continue
    if hits:
        # This question is "who holds this evidence", which is legitimately allowed
        # to be a retired install -- `demo_watchdog` reads the closed V75 paper
        # ledgers. So foreign installs are NOT excluded here. But when the active
        # account's install also holds the file, it is the one to read.
        registry = load_account_registry()
        prefer = [td for td in hits
                  if classify_identity(terminal_identity(td), registry)[0] == ACTIVE]
        pool = prefer or hits
        best = max(pool, key=lambda td: newest_mtime(journals(td) + chart_files(td)))
        why = f"holds a file matching {pattern}"
        if prefer:
            why += "; preferred because it cites the active account"
        elif registry.loaded:
            why += ("; WARNING no install holding it cites the active account, "
                    "so this evidence may be from a closed program")
        return best, why
    raise refusal(f"a terminal holding a file matching {pattern}",
                  f"searched {', '.join(search)} in every terminal")


def resolve_tester_files(want_filename: str | None = None,
                         explicit: str | os.PathLike | None = None) -> tuple[Path, str]:
    """The Tester ``MQL5/Files`` directory, preferably the one holding a file.

    Layout is ``Tester/<hash>/Agent-<ip>-<port>/MQL5/Files``; a plain
    ``Tester/<hash>/MQL5/Files`` is also accepted. When ``want_filename`` is given,
    the agent directory actually containing it wins — otherwise a stale agent
    directory could be read instead of the one that just ran.
    """
    if explicit:
        p = Path(str(explicit)).expanduser()
        if p.is_dir():
            return p, f"explicit path ({p.name})"
        raise refusal("the explicitly requested Tester directory", f"given: {explicit}")

    candidates: list[tuple[Path, float, bool]] = []
    for td in tester_dirs():
        for d in (td / "MQL5" / "Files", *sorted(td.glob("Agent-*/MQL5/Files"))):
            if not d.is_dir():
                continue
            hit = bool(want_filename and (d / want_filename).is_file())
            candidates.append((d, d.stat().st_mtime, hit))

    if want_filename:
        hits = [c for c in candidates if c[2]]
        if hits:
            best = max(hits, key=lambda c: c[1])
            return best[0], f"Tester agent holding {want_filename}"

    if candidates:
        best = max(candidates, key=lambda c: c[1])
        evidence = ("Tester Files (most recent agent)"
                    + (f"; {want_filename} not found in any agent" if want_filename else ""))
        return best[0], evidence

    raise refusal("a Tester MQL5/Files directory",
                  f"root: {tester_root()} (no Agent-*/MQL5/Files found)")


# --------------------------------------------------------------------------- #
# CLI — so PowerShell tooling can share this implementation
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--terminal", action="store_true",
                   help="print the resolved terminal directory")
    g.add_argument("--list", action="store_true",
                   help="list every terminal directory and its evidence")
    g.add_argument("--tester", metavar="FILENAME",
                   help="print the Tester Files dir holding FILENAME")
    ap.add_argument("--explain", action="store_true",
                    help="also print which evidence selected the directory")
    a = ap.parse_args(argv)

    try:
        if a.list:
            rows = describe_terminals()
            if not rows:
                print(f"no terminal directories under {terminal_root()}")
                return 1
            reg = load_account_registry()
            print(f"# account registry: {reg.status()}  ({reg.path})")
            print(f"{'name':<34} {'identity':<9} {'accounts':<14} {'experts today':<15} "
                  f"{'charts':<7} newest journal")
            for r in rows:
                accts = "/".join(r.get("accounts") or ()) or "-"
                print(f"{r['name']:<34} {r.get('identity', '?'):<9} {accts:<14} "
                      f"{str(r['experts_today']):<15} {r['charts']:<7} "
                      f"{r['newest_journal'] or '-'}")
            for r in rows:
                if r.get("identity") == FOREIGN:
                    print(f"# EXCLUDED {r['name']}: {r.get('identity_why', '')}")
            if not reg.loaded:
                print("# WARNING: " + reg.status() +
                      " -- installs cannot be classified by account, so this "
                      "resolution falls back to recency")
            return 0
        if a.terminal:
            path, why = resolve_terminal()
        else:
            path, why = resolve_tester_files(a.tester)
    except TerminalNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(str(path))
    if a.explain:
        print(f"# selected by: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

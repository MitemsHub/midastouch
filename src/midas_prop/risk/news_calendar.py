"""The scheduled-news gate: one rule, two engines, one vocabulary.

WHY THIS EXISTS. The playbook's standing policy has always said "no new entries in a
+/-15-minute window around top-tier USD releases", and for as long as the calendar could
not be read, the honest answer was to refuse the label (V2 register R6: the EA refused
`InpUseNewsFilter=true` at INIT because no calendar engine existed). There is now a
source, and it is a FILE, for a measured reason:

  * the Python API has no calendar at all — MetaTrader5 5.0.5735 exposes 269 names, none
    calendar-related;
  * the tester cannot call it either — `CalendarValueHistory` returns -1 with
    `GetLastError() = 4014` ("function not allowed for call"), measured 2026-09-20 in the
    strategy tester;
  * so `MidasNewsProbe.mq5` reads it once and WRITES IT DOWN, and both engines read that.

A rule only one engine can see is a rule the parity contract cannot replay, which is why
this module exists rather than a second implementation inside the research engine: the EA
and this file answer with the SAME FIVE REFUSAL PHRASES. If they ever disagree, an
operator reading one engine's journal cannot tell why the other stood down.

THE REFUSAL IS THE FEATURE. A filter that does nothing when its source is missing is
worse than no filter, because the banner still says protection is ON. So an unusable
source vetoes entries and names which of the five it is — and "empty" is its own refusal,
because a zero count is not evidence of no news; it is evidence that we cannot see it.

Wire format (written by `mql5/MIDASTOUCH/MidasNewsProbe.mq5`):
    # epoch_generated_utc=<unix s>   # epoch_window_to_utc=<unix s>   # events=<n>
    epoch_utc;time_utc;time_server;currency;country;importance;event
Epochs are numeric on purpose: a date string would have to be interpreted in someone's
timezone, and this program has already paid for one clock mistake.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: The five refusals, in the EA's own words, because an operator must not have to learn
#: two vocabularies to read two engines.
REASON_MISSING = "calendar file missing"
REASON_UNREADABLE = "calendar file unreadable"
REASON_NO_GENERATION_TIME = "calendar file carries no generation time (cannot judge freshness)"
REASON_NO_WINDOW = "calendar file declares no window end (cannot judge coverage)"
REASON_STALE = "calendar stale"
REASON_NO_COVERAGE = "calendar does not cover"
REASON_NO_DECLARED_COUNT = "calendar file declares no event count (cannot judge completeness)"
REASON_TRUNCATED = "calendar truncated"
REASON_EMPTY = 'calendar empty — an empty calendar is not "no news"'

COLUMNS = ("epoch_utc", "time_utc", "time_server", "currency", "country",
           "importance", "event")

#: Top-tier only: the playbook's policy is about releases that move gold, and a filter
#: that also hides the ordinary calendar would change the strategy, not protect it.
IMPORTANCE = "HIGH"


@dataclass(frozen=True)
class Event:
    epoch: int
    currency: str
    importance: str
    name: str

    @property
    def is_top_tier(self) -> bool:
        return self.importance == IMPORTANCE


@dataclass(frozen=True)
class Calendar:
    generated_utc: int
    window_from_utc: int
    window_to_utc: int
    events: tuple[Event, ...]
    declared_events: int | None = None


class CalendarUnusable(Exception):
    """The calendar cannot be trusted, and the reason is one of the declared phrases."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse(text: str) -> Calendar:
    """Parse the probe's file. Raises `CalendarUnusable` when it cannot be judged."""
    generated = window_from = window_to = 0
    declared: int | None = None
    events: list[Event] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            key, _, value = line.lstrip("# ").partition("=")
            key, value = key.strip(), value.strip()
            if key == "epoch_generated_utc":
                generated = _int(value)
            elif key == "epoch_window_from_utc":
                window_from = _int(value)
            elif key == "epoch_window_to_utc":
                window_to = _int(value)
            elif key == "events":
                declared = _int(value)
            continue
        if line.startswith(COLUMNS[0]):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < len(COLUMNS):
            continue
        epoch = _int(parts[0])
        if epoch <= 0:
            continue
        events.append(Event(epoch=epoch, currency=parts[3], importance=parts[5],
                            name=parts[6]))
    return Calendar(generated_utc=generated, window_from_utc=window_from,
                    window_to_utc=window_to, events=tuple(events), declared_events=declared)


def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def source_problem(cal: Calendar | None, now: int, max_age_hours: int = 24,
                   cover_hours: int = 24) -> str:
    """"" when the calendar may be trusted, else one of the declared refusal phrases."""
    if cal is None:
        return REASON_MISSING
    if cal.generated_utc <= 0:
        return REASON_NO_GENERATION_TIME
    if (now - cal.generated_utc) > max_age_hours * 3600:
        return f"{REASON_STALE} ({_hours(now - cal.generated_utc):.1f}h old > {max_age_hours}h)"
    if cal.window_to_utc <= 0:
        return REASON_NO_WINDOW
    if cal.window_to_utc < now + cover_hours * 3600:
        return f"{REASON_NO_COVERAGE} the next {cover_hours}h"
    # The declared count is a truncation detector, not bookkeeping: the writer stamps it
    # in the header and fills the body afterwards, so a file that dies mid-write still
    # carries a count its rows cannot reach. Without this, a half-written calendar looks
    # exactly like a quiet news week.
    if cal.declared_events is None:
        return REASON_NO_DECLARED_COUNT
    if len(cal.events) < cal.declared_events:
        return (f"{REASON_TRUNCATED} (declares {cal.declared_events} events, "
                f"holds {len(cal.events)}) — refresh it")
    if not cal.events:
        return REASON_EMPTY
    return ""


def _hours(seconds: float) -> float:
    return seconds / 3600.0


def read_calendar(path: str | Path) -> Calendar:
    p = Path(path)
    if not p.is_file():
        raise CalendarUnusable(REASON_MISSING)
    try:
        return parse(p.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:  # pragma: no cover — permissions, a locked file
        raise CalendarUnusable(REASON_UNREADABLE) from exc


def veto_reason(cal: Calendar | None, now: int, window_min: int = 15) -> str:
    """"" = clear to enter. Anything else is the reason, in the EA's vocabulary."""
    problem = source_problem(cal, now)
    if problem:
        return problem
    assert cal is not None  # source_problem() already refused that case
    return blackout_reason(cal.events, now, window_min)


def blackout_reason(events: tuple[Event, ...], now: int, window_min: int = 15) -> str:
    """The +/- window itself. Symmetric: an event ten minutes ago still counts.

    A release that has just printed is exactly when the spread is widest and the tape is
    least like the tape the strategy was fitted on, so the past side of the window is not
    a courtesy — it is the case that matters most.
    """
    window_s = window_min * 60
    for ev in events:
        if not ev.is_top_tier:
            continue
        if abs(now - ev.epoch) <= window_s:
            return f"news blackout: {ev.name} (within {window_min} min)"
    return ""

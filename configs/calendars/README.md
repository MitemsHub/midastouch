# The calendars

Two calendars exist in this program, and they answer different questions. Neither is a
substitute for the other.

| file | where it lives | who writes it | what reads it |
|---|---|---|---|
| `MIDASTOUCH_news_calendar.csv` | `<data>\MQL5\Files` (terminal, machine-local) | the attached `MidastouchAI.mq5`, live, from `CalendarValueHistory(now - N days, now + M days)` | the live arm (its own gate), `MidasNewsProbe.mq5` |
| `MIDASTOUCH_news_calendar_frozen.csv` | staged into `<data>\MQL5\Files` from the snapshot below | the harness, from the tracked snapshot | every **replay**: `scripts/midas_parity.py` (both engines), the veto-window pin, the news studies |

## Why the second file exists

A replay judges a **past** window. The rolling file's coverage moves with the clock, so a
replay reading it is measuring a past window against a source that changed after the
measurement — and it fails in the quiet direction: a stand-down with no events in its file
refuses nothing, which reads exactly like a rule that had nothing to veto.

Measured 2026-09-21 on this machine: at 17:52Z the attached EA's live refresh rewrote the
rolling file down to a 2026-09-09 → 2026-10-09 window. The coverage every measurement that
day stood on — 2026-01-02 → 2026-09-24, 2719 events, 369 HIGH — was gone with it, and every
replay of the certified window became a no-op stand-down. `tests/test_parity_corpus.py`'s veto
pin went red against a rule that had not changed.

The harness now stages the snapshot under its own name (`midas_parity.stage_frozen_calendar`)
and sets `InpNewsFile` to it for a pass; the EA declares that name `#property tester_file`
beside the rolling one, so the tester mirrors both into the agent sandbox and the two engines
open the same bytes. With no snapshot, a pass **refuses** — it never falls back to the rolling
file.

## The snapshot

`MIDASTOUCH_news_calendar_frozen_20260102_20260924.csv`

| | |
|---|---|
| written by | `mql5/MIDASTOUCH/MidasNewsProbe.mq5`, run in the tester agent sandbox |
| generated | 2026-09-21 07:44:04Z (server 2026-09-21 02:25:26) |
| window | 2026-01-02 07:43:26Z → 2026-09-24 07:43:26Z |
| source | `mt5_economic_calendar`, currency USD, all importances |
| events | 2719 rows, **369 HIGH** |
| sha256 | `3a41c0b8f7c074c10de037efaf85777d588743989885f6b62c047e54481618e9` |
| covers | the frozen corpus windows, incl. the veto window (2026-05-10 → 2026-05-16) |

Recovered from the tester agent's sandbox copy (`...\Tester\<id>\Agent-127.0.0.1-3000\MQL5\Files\`),
which the live refresh cannot reach — the live copy had already been overwritten by the time
the loss was noticed. To refresh it deliberately, run `MidasNewsProbe.mq5` over the window,
copy the result here under a dated name, update `midas_parity.FROZEN_NEWS_SOURCE` and these
numbers, and re-run `tests/test_frozen_calendar.py` (it pins the counts, the span and the
hash).

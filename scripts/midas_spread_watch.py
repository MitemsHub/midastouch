#!/usr/bin/env python3
"""The spread watch: is the venue's spread inside the cap the arm actually refuses on?

THE QUESTION IT ANSWERS
  The armed arm's most recent refusals were the spread gate: two accepted signals
  (mode gate passed, session window open) were vetoed on 2026-09-23 because the
  live spread ($0.49-0.50) exceeded the cap (1.5% of the stop distance, after ATR
  compression pulled the cap down to ~$0.37-0.39). An operator looking at the
  chart sees "flat" and asks why; this tool answers from the two records that
  decide it —

    LIVE:   the venue's own tick (ask-bid) against the cap the ARM's stop width
            implies right now (InpSlAtrMult x ATR(H1), computed exactly like the
            EA's `AtrNow()`: SMA of true range over the last 14 CLOSED H1 bars),
            so "would an entry be accepted NOW" is measured the way the arm will
            measure it at the next bar close.
    RECORD: the arm's own ledger, which already knows every veto it made — the
            NOFILL census, the SPREADHOUR rows, and the per-bar stop width in
            each STATE row — so "how often has this blocked us since arming" is
            read off evidence, not rebuilt from a guess.

WHY THE LIVE LEG IS A WATCH AND NOT A SIGNAL
  It can never place, cancel or modify anything: it imports no order path, sends
  no order_check, and the guard test pins the source for `order_send`. "Entries
  would reopen" is a statement about a future bar the arm will evaluate itself;
  this tool reports where the gate's two numbers stand, nothing more.

WHY THE AUDIT LEG COUNTS THE CENSUS AND NOT THE GAP ALONE
  The census (NOFILLSUM) is the EA's own statement of how many bars the spread
  gate refused, restored across restarts. The STATE rows say which bars were
  accepted signals and what cap each carried. Neither alone is the answer: the
  census cannot say what the accepted bars' caps looked like, and a cap-below-
  spread gap on a STATE row does not prove the gate closed (the row carries no
  tick spread). So vetoes are COUNTED from the census, gaps are reported from
  the rows, and when the two contradict each other the tool exits 1 rather than
  printing a reconciled-looking number.

CLOCK FRAMES
  Live tick and ATR bars: true UTC (the MetaTrader5 API serves UTC epochs).
  Ledger STATE write epochs: true UTC (`TimeUTCNow`).
  Ledger bar epochs (`sig_open_srv`): the VENUE's server frame, converted by the
  row's own `off_min`. Every rendered time is labelled; no frame is converted
  silently.

READ-ONLY. Exit codes: 0 healthy/watching, 1 the record disagrees with itself,
3 the terminal could not be measured.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import midas_arm_record as AR  # noqa: E402

ART = ROOT / "artifacts" / "live" / "spread_watch.json"
ARMING_RECORD = ROOT / "artifacts" / "live" / "armed.json"
PRESET_DIR = ROOT / "mql5" / "MIDASTOUCH"
TICK_FRESH_S = 300       # an older tick is a closed market, not a spread


def utc_str(ts: int | None) -> str:
    return (datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            if ts else "—")


def atr_h1_closed(h1: list[dict], period: int = 14) -> float:
    """SMA true-range over H1 CLOSED bars — the EA's `AtrNow()` (shifts 1..period).

    `h1` must be true-UTC closed bars, ascending (as `midas_sweep_shadow.live_bars`
    returns them). Refuses to average fewer than `period` bars: a short window is a
    lookalike stop width, and the cap is that width times the cap percent.
    """
    if len(h1) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(len(h1) - period, len(h1)):
        b, p = h1[i], h1[i - 1]
        trs.append(max(b["high"] - b["low"],
                       abs(b["high"] - p["close"]), abs(b["low"] - p["close"])))
    return sum(trs) / period


def mode_takes(mode: int, trig: int, mac: int) -> bool:
    """`ModeDecide` (MidastouchAI.mq5:954) as a pure function — pinned against the
    EA's matrix row for row in tests/test_midas_arm_record.py."""
    if mode == 0:    # ORIGINAL
        return trig != 0 and mac == trig
    if mode == 1:    # REVERSE_DIRECTION
        return trig != 0 and mac == -trig
    if mode == 2:    # REVERSE_TRIGGER
        return trig == 0 and mac != 0
    if mode == 3:    # REVERSE_BOTH
        return trig == 0 and mac != 0
    if mode == 4:    # LONG_ONLY
        return trig == 1 and mac == 1
    if mode == 5:    # SHORT_ONLY
        return trig == -1 and mac == -1
    if mode == 6:    # MACRO_ONLY
        return mac != 0
    if mode == 7:    # TRIGGER_ONLY
        return trig != 0
    return False


def spread_cap(stop_d: float, cap_pct: float) -> float:
    """The cap: `InpSpreadCapPctStop` percent of the stop distance (EA line 2932)."""
    return stop_d * cap_pct / 100.0


#: The venue's dollar value of one price unit per 1.0 lot — the same contract
#: constant the engine of record sizes on (`midas_sweep.TICK_VALUE_PER_LOT`, and
#: the EA's own settled value on this account: SPEC rows, ratio 0.10 of the raw
#: spec). Position risk ($) = stop ($) x this x lots, so stop = risk / (lots x this).
DOLLAR_PER_UNIT_PER_LOT = 100.0


def stop_from_state(r: dict) -> float | None:
    """The stop width a STATE row sized on, from its own lots and risk fields.

    The row carries `risk_usd` (the position's dollar risk) and `lots`, both
    scaled x100 by the writer; the EA sizes `risk = stop x $100 x lots` on this
    venue, so the stop is `risk / (lots x 100)`. MEASURED 2026-09-23: omitting
    the $100 made every reconstructed cap 100x too wide ($35 instead of $0.35),
    and a cap that wide can never veto anything — the tool would have reported
    "open" while the arm was being vetoed.
    """
    if r["lots"] <= 0:
        return None
    stop = r["risk_usd"] / (r["lots"] * DOLLAR_PER_UNIT_PER_LOT)
    return stop if stop > 0 else None


def arm_stance() -> dict:
    """Preset values, through the arming record — never repo defaults.

    Refuses (SystemExit) when nothing is armed: a spread cap is a property of a
    configuration, and guessing the repo default on an unarmed checkout would
    report on a configuration nobody runs.
    """
    if not ARMING_RECORD.is_file():
        raise SystemExit(
            f"no arming record at {ARMING_RECORD.relative_to(ROOT)} — nothing is armed, "
            f"so there is no configuration to watch. (This tool reports on the ARMED "
            f"preset, not on repo defaults.)")
    preset, src = AR.resolve_arm_preset(ARMING_RECORD, PRESET_DIR)
    if preset is None:
        raise SystemExit(f"REFUSING: {src}")
    vals = AR.read_preset_inputs(preset)

    def num(key: str) -> float:
        try:
            return float(vals[key])
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f"REFUSING: the armed preset carries no readable {key}")

    return {"preset": preset.name, "source": src,
            "mode": int(num("InpMode")),
            "sl_mult": num("InpSlAtrMult"),
            "cap_pct": num("InpSpreadCapPctStop"),
            "atr_period": int(num("InpAtrPeriod"))}


def live_leg(symbol: str, stance: dict) -> dict | None:
    """One measured moment: tick spread, ATR stop width, cap, headroom.

    None = the terminal could not be measured (module missing, init failed, no
    tick). A dict with `stale=True` = market shut (old tick); a closed-market
    spread is not a spread, so no live verdict is stated.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    try:
        t = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0,
                                        stance["atr_period"] + 2)
        # `rates` is a numpy structured array: truthiness is ambiguous, so test
        # length explicitly.
        if t is None or info is None or rates is None or len(rates) == 0:
            return None
        age = time.time() - float(t.time)
        if age > TICK_FRESH_S:
            return {"stale": True, "age_s": age}
        # CLOSED bars only, newest last; position 0 is the still-forming bar.
        h1 = [{"high": float(b["high"]), "low": float(b["low"]),
               "close": float(b["close"])} for b in rates[:-1]]
        atr = atr_h1_closed(h1, stance["atr_period"])
        if atr <= 0:
            return {"stale": False, "atr": 0.0}
        spread = float(t.ask) - float(t.bid)
        stop_d = stance["sl_mult"] * atr
        cap = spread_cap(stop_d, stance["cap_pct"])
        return {"stale": False, "utc": int(t.time), "bid": float(t.bid),
                "ask": float(t.ask), "spread": spread,
                "points": int(info.spread), "atr": atr, "stop_d": stop_d,
                "cap": cap, "headroom": cap - spread,
                "atr_period": stance["atr_period"]}
    finally:
        try:
            mt5.shutdown()
        except Exception:      # noqa: BLE001
            pass


def hourly_spread_map(rows: dict) -> dict[str, dict[int, float]]:
    """{utc_day: {utc_hour: mean spread $}} from every SPREADHOUR row.

    Each row rolls up ONE ended UTC day, so the day key comes from the row's own
    `day` field, not from when the row was written. Hours with no samples are
    absent — a missing estimate is reported as missing, never as $0.
    """
    out: dict[str, dict[int, float]] = {}
    for row in rows["spreadhour"]:
        day = datetime.fromtimestamp(row["day"] * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
        m = out.setdefault(day, {})
        for h, (n, mean, _mx) in row["hours"].items():
            if n > 0:
                m[h] = mean
    return out


def audit_ledger(book: Path, stance: dict, t0_armed: int | None,
                 timeline: list[tuple[int, int]] | None = None) -> dict:
    """Accepted signals vs the spread vetoes the census recorded.

    An accepted-signal bar: `trig != 0`, mode-accepted (`ModeDecide` on the row's
    own mac, at the mode THE RECORD says was running — the arming record's
    amendment timeline, not just the preset's final value), inside the session
    gate (`sess_ok`). Vetoes are COUNTED from the census (max per UTC day, the
    cumulative-within-day semantics), restricted to days on or after the arming
    day when the arming stamp is readable.
    """
    tl = timeline or [(0, stance["mode"])]
    book_data = AR.read_rows(book)
    rows = book_data["rows"]
    smap = hourly_spread_map(rows)

    accepted: list[dict] = []
    # Deduped bars, not raw rows: the heartbeat re-writes the current bar, so a
    # signal that survived three heartbeats must read as one accepted signal,
    # not three. Legacy (pre-v1.27) rows carry no `off_min`; their bar time is
    # taken from the write time, which for a bar evaluated on that write is
    # within the bar itself — good enough to place the veto on a day, which is
    # the resolution the census's own per-day counters carry.
    for r in AR.dedupe_bars(rows["state"]):
        if t0_armed is not None and r["write_utc"] < t0_armed:
            continue
        mode = AR.mode_at(tl, r["write_utc"])
        if r["trig"] == 0 or not mode_takes(mode, r["trig"], r["mac"]):
            continue
        if not r["sess_ok"]:
            continue
        stop_d = stop_from_state(r)
        if stop_d is None:
            continue
        bar_utc = AR.bar_open_utc(r)
        if bar_utc is None:
            bar_utc = r["write_utc"]
        day = datetime.fromtimestamp(bar_utc, tz=timezone.utc).strftime("%Y-%m-%d")
        hour = (bar_utc // 3600) % 24
        spread_est = (smap.get(day, {}).get(hour) if day is not None and hour is not None
                      else None)
        accepted.append({
            "write_utc": r["write_utc"], "bar_utc": bar_utc,
            "trig": r["trig"], "mac": r["mac"],
            "stop_d": stop_d, "spread_cap": spread_cap(stop_d, stance["cap_pct"]),
            "spread_est": spread_est})

    # Vetoes per UTC day, cumulative-within-day -> the day's last reading wins.
    days: dict[str, int] = {}
    for row in rows["nofill"]:
        d = datetime.fromtimestamp(row["write"], tz=timezone.utc).strftime("%Y-%m-%d")
        if t0_armed is not None and row["write"] < t0_armed - 86400:
            continue
        days[d] = max(days.get(d, 0), row["spread"])
    veto_days = sorted(days.items())
    n_vetoed = sum(v for _, v in veto_days)

    n_accepted = len(accepted)
    n_gap = sum(1 for r in accepted
                if r["spread_est"] is not None and r["spread_cap"] < r["spread_est"])
    # The two records must agree in kind: a veto recorded with no accepted bar to
    # veto, or more vetoes than accepted signals, is a parsing/grammar problem.
    consistent = n_vetoed <= n_accepted
    return {
        "accepted_signals": n_accepted,
        "spread_vetoes": n_vetoed,
        "veto_days": veto_days,
        "accepted_with_cap_below_spread": n_gap,
        "accepted_veto_rate": (round(n_vetoed / n_accepted, 4) if n_accepted else None),
        "consistent": consistent,
        "unreadable_rows": len(book_data["broken"]),
        "accepted_rows": accepted[-20:],
    }


def cap_vs_spread_series(book: Path, stance: dict,
                         timeline: list[tuple[int, int]] | None = None) -> list[dict]:
    """Per-bar (cap, spread) pairs for the trend leg.

    The cap comes from each STATE row's own stop width (`risk_usd/lots` — the same
    fields the v1.22 `cfg` disclosure is built from). The spread comes from the
    SPREADHOUR roll-up covering that bar's UTC day and hour. Bars whose hour was
    never sampled are excluded from the trend — a missing estimate is not $0.10.
    """
    book_data = AR.read_rows(book)
    rows = book_data["rows"]
    smap = hourly_spread_map(rows)
    tl = timeline or [(0, stance["mode"])]
    out: list[dict] = []
    for r in rows["state"]:
        stop_d = stop_from_state(r)
        if stop_d is None:
            continue
        bar_utc = AR.bar_open_utc(r)
        if bar_utc is None:
            continue
        day = datetime.fromtimestamp(bar_utc, tz=timezone.utc).strftime("%Y-%m-%d")
        hour = bar_utc // 3600 % 24
        spread = smap.get(day, {}).get(hour)
        out.append({"write_utc": r["write_utc"], "bar_utc": bar_utc,
                    "cap": spread_cap(stop_d, stance["cap_pct"]),
                    "spread": spread, "gap": (spread_cap(stop_d, stance["cap_pct"]) - spread)
                    if spread is not None else None,
                    "trig": r["trig"], "mac": r["mac"],
                    "mode_accept": mode_takes(AR.mode_at(tl, r["write_utc"]),
                                              r["trig"], r["mac"])})
    return out


def trend(series: list[dict]) -> dict:
    """Whether the cap-vs-spread gap is narrowing — by the record, per bar.

    gap = cap - spread; a SHRINKING gap is veto risk rising. Two views, both from
    the record's own hourly spread estimates: the last 24h of evaluated bars
    against the 24h before, and the record's second half against its first.
    Widening/narrowing is a signed mean gap in dollars, never an adjective alone.
    """
    bars = [s for s in series if s["gap"] is not None]
    if len(bars) < 8:
        return {"state": "UNMEASURABLE",
                "why": f"only {len(bars)} evaluated bars carry both cap and a sampled "
                       f"hourly spread — need 8", "n": len(bars)}
    now = bars[-1]["bar_utc"]

    def mean_gap(sub: list[dict]) -> float | None:
        return statistics.fmean([s["gap"] for s in sub]) if sub else None

    def window(center: int) -> list[dict]:
        return [s for s in bars if center - 86400 <= s["bar_utc"] < center]

    m_r, m_p = mean_gap(window(now)), mean_gap(window(now - 86400))
    halves = len(bars) // 2
    first_half, second_half = mean_gap(bars[:halves]), mean_gap(bars[halves:])
    d24 = (m_r - m_p) if (m_r is not None and m_p is not None) else None
    dh = (second_half - first_half) if (first_half is not None and second_half is not None) else None
    delta = d24 if d24 is not None else dh
    if delta is None:
        state, why = "UNMEASURABLE", "no comparable window in the record"
    elif delta < -1e-9:
        state, why = "NARROWING", f"mean gap moved {delta:+.2f} toward veto territory"
    elif delta > 1e-9:
        state, why = "WIDENING", f"mean gap moved {delta:+.2f} away from veto territory"
    else:
        state, why = "FLAT", "mean gap unchanged between windows"
    return {"state": state, "why": why,
            "mean_gap_recent_24h": m_r, "mean_gap_prior_24h": m_p,
            "delta_24h": d24, "mean_gap_first_half": first_half,
            "mean_gap_second_half": second_half, "delta_halves": dh,
            "n_bars": len(bars)}


def parse_armed_utc(s: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError, TypeError):
        return None


def armed_book() -> Path | None:
    """The armed arm's ledger, resolved the way `live_readiness.running_ledgers`
    resolves it: arming tag first, attached-arms fallback, never a glob."""
    import live_readiness as LR  # noqa: PLC0415 — keeps this off the prop layer
    tag = LR.armed_arm_tag()
    term_data = None
    try:
        import MetaTrader5 as mt5  # type: ignore
        if mt5.initialize():
            ti = mt5.terminal_info()
            if ti is not None and getattr(ti, "data_path", ""):
                term_data = Path(str(ti.data_path))
            mt5.shutdown()
    except ImportError:
        pass
    books = LR.running_ledgers(term_data, tag)
    return books[0] if books else None


def print_report(stance: dict, rec: dict, book: Path, audit: dict,
                 tr: dict, live: dict | None, now: datetime) -> None:
    print(f"=== SPREAD WATCH — XAUUSD @ {now:%Y-%m-%d %H:%M} UTC ===")
    print(f"preset   {stance['preset']} ({stance['source']})")
    print(f"gate     cap = {stance['cap_pct']}% of stop = {stance['sl_mult']}xATR"
          f"(H1, {stance['atr_period']}) — the EA's own veto condition")
    if live is None:
        print("live     TERMINAL UNAVAILABLE — the live leg could not be measured")
    elif live.get("stale"):
        print(f"live     STALE TICK ({live['age_s'] / 60:.0f} min old) — market shut; "
              f"a closed-market spread is not a spread, so no live verdict")
    elif live.get("atr", 0) <= 0:
        print("live     ATR unmeasurable — refusing to state a cap without a stop width")
    else:
        print(f"live     spread ${live['spread']:.2f} ({live['points']} pts) vs cap "
              f"${live['cap']:.2f}  (stop ${live['stop_d']:.2f} = "
              f"{stance['sl_mult']}xATR ${live['atr']:.2f})")
        if live["headroom"] >= 0:
            print(f"         OPEN — headroom ${live['headroom']:.2f}: an accepted signal "
                  f"at this moment would NOT be spread-vetoed")
        else:
            print(f"         VETOING — cap exceeded by ${-live['headroom']:.2f}: an "
                  f"accepted signal would be refused until the spread narrows by that "
                  f"or ATR widens the stop (and the cap with it)")
    print(f"\nrecord   ledger {book.name}, since arming {rec.get('armed_utc', '?')}:")
    print(f"  accepted signals (mode-passed, in-session): {audit['accepted_signals']}")
    print(f"  spread vetoes (census, per UTC day max):    {audit['spread_vetoes']}")
    if audit["veto_days"]:
        tail = ", ".join(f"{d}={v}" for d, v in audit["veto_days"][-5:])
        more = " …" if len(audit["veto_days"]) > 5 else ""
        print(f"  veto days: {tail}{more}")
    print(f"  accepted-signal veto rate: "
          f"{fmt_pct(audit['accepted_veto_rate'])}")
    if audit["accepted_with_cap_below_spread"]:
        print(f"  accepted bars whose cap sat below the venue's sampled hourly "
              f"spread: {audit['accepted_with_cap_below_spread']} (the record's own "
              f"gap, not a proof of veto)")
    if audit["unreadable_rows"]:
        print(f"  UNREADABLE rows dropped by the parser: {audit['unreadable_rows']}")

    print(f"\ncap-vs-spread trend: {tr['state']}"
          + (f" — {tr['why']}" if tr.get("why") else ""))
    if tr.get("delta_24h") is not None:
        print(f"  mean gap last 24h ${tr['mean_gap_recent_24h']:+.2f} vs prior 24h "
              f"${tr['mean_gap_prior_24h']:+.2f} -> {tr['delta_24h']:+.2f}")
    if tr.get("delta_halves") is not None:
        print(f"  whole record: first half ${tr['mean_gap_first_half']:+.2f} -> "
              f"second half ${tr['mean_gap_second_half']:+.2f}")


def exit_code(audit: dict, live: dict | None) -> int:
    if live is None:
        return 3
    if not audit["consistent"]:
        return 1
    return 0


def fmt_pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--watch", type=float, default=0.0, metavar="MINUTES",
                    help="re-measure the live leg every 30s for this many minutes "
                         "(default: one measurement)")
    a = ap.parse_args()

    stance = arm_stance()
    rec = AR.json_load(ARMING_RECORD)
    timeline = AR.mode_timeline(rec, stance["mode"])
    t0_armed = parse_armed_utc(rec.get("armed_utc"))
    book = armed_book()
    if book is None or not book.exists():
        print("no armed arm's ledger found — nothing is attached to audit "
              "(live leg still runs below if the terminal is up)")
        audit = {"accepted_signals": 0, "spread_vetoes": 0, "veto_days": [],
                 "accepted_with_cap_below_spread": 0, "accepted_veto_rate": None,
                 "consistent": True, "unreadable_rows": 0, "accepted_rows": []}
        tr = {"state": "UNMEASURABLE", "why": "no ledger", "n": 0}
        live = live_leg("XAUUSD", stance)
        print_report(stance, rec, book or Path("(none)"), audit, tr, live,
                     datetime.now(timezone.utc))
        return exit_code(audit, live)

    deadline = time.time() + a.watch * 60 if a.watch > 0 else None
    while True:
        now = datetime.now(timezone.utc)
        audit = audit_ledger(book, stance, t0_armed, timeline)
        series = cap_vs_spread_series(book, stance, timeline)
        tr = trend(series)
        live = live_leg("XAUUSD", stance)
        out = {"tool": "midas_spread_watch", "ts": now.isoformat(timespec="seconds"),
               "preset": stance["preset"], "mode": stance["mode"],
               "cap_pct": stance["cap_pct"], "sl_mult": stance["sl_mult"],
               "armed_utc": rec.get("armed_utc"), "ledger": str(book),
               "audit": {k: v for k, v in audit.items() if k != "accepted_rows"},
               "trend": tr, "live": live}
        ART.parent.mkdir(parents=True, exist_ok=True)
        ART.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print_report(stance, rec, book, audit, tr, live, now)
        code = exit_code(audit, live)
        if deadline is None or time.time() >= deadline:
            print(f"\nartifact: {ART.relative_to(ROOT)}")
            return code
        print("\n--- watching (30s) ---")
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())

"""Close-anchored intraday momentum on the venue's own day close — one declared hypothesis.

This script implements `docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md` and nothing else. It has no
grid, no sweep and no alternative window: the sign, the window, the normalisation, the cost
model and the decision rule were all fixed in that file before this ran. If you are reading
this to find out what it measured, read
`docs/GOLD_INTRADAY_MOMENTUM_VERDICT_20260921.md` — the numbers are there, not here.

WHY THIS WINDOW. The venue's trading day does not end at UTC midnight. Its M15 series has the
last bar of a day stamped 22:45 and the next day starting at 00:00, with the day's one missing
hour at 23:00 — the daily maintenance break, which sits at server 23:00 in every month because
it follows US Eastern while the server's own offset moves on the EU calendar. So the last 30
minutes before the venue's close are stamps 22:15 and 22:30, which are 21:15–21:45 UTC in the
+60 era and 20:15–20:45 UTC in the +120 era. The arm's session (06–20 UTC) and its flat rule
(22:00 UTC) never trade it.

CLOCK DISCIPLINE. Stamps are server-local, so the era offset matters for saying *when* a trade
happened in UTC — and the era table is read per month, refusing on any month containing a DST
step rather than guessing one. Every alignment inside this script is stamp-to-stamp (the H1 ATR
to the entry bar), which needs no offset at all; the offset is used only for reporting.

Run:  python scripts/gold_intraday_momentum.py [--json artifacts/gold_intraday_momentum.json]
      python scripts/gold_intraday_momentum.py --selftest
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_sweep as ms  # noqa: E402  — the repo's pinned engine of record

M15_PATH = os.path.join("data", "forex", "xauusd", "XAUUSD_M15_upcomers.csv")
H1_PATH = os.path.join("data", "forex", "xauusd", "XAUUSD_H1_upcomers.csv")
ARTIFACT = os.path.join("artifacts", "gold_intraday_momentum.json")

#: Declared in the protocol, not chosen here.
STOP_ATR_MULT = 2.0
T_CRIT = 1.96
Z_POWER = 0.8416                     # 80% power, two-sided 5%
STAMPS_REQUIRED = ("00:00", "22:00", "22:15", "22:30")
ROD_OPEN, LH_OPEN, LH_CLOSE = "00:00", "22:15", "22:30"


def _utc(t: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc)


def stamp(t: int) -> str:
    """A bar's own stamp as HH:MM — the raw field, deliberately NOT converted to UTC here."""
    return _utc(t).strftime("%H:%M")


def by_day(bars: list[dict]) -> dict[str, dict[str, dict]]:
    days: dict[str, dict[str, dict]] = {}
    for b in bars:
        d = _utc(b["time"]).strftime("%Y-%m-%d")
        days.setdefault(d, {})[stamp(b["time"])] = b
    return days


def h1_atr_lookup(h1: list[dict], n: int = 14) -> list[tuple[int, float]]:
    """(stamp, ATR) pairs, so the stop can be taken from the H1 bar containing the entry."""
    atr = ms.wilder_atr(h1, n)
    return [(b["time"], a) for b, a in zip(h1, atr)]


def atr_at(lookup: list[tuple[int, float]], t: int) -> float | None:
    """ATR of the newest H1 bar stamped at or before `t` — causal, never the future."""
    best = None
    for st, a in lookup:
        if st <= t:
            best = a
        else:
            break
    return best


def era_offset(day: str) -> int | None:
    """The pinned server offset (minutes, server − UTC) for a day's month, or None when the
    month contains a DST step. None is a real answer and this script refuses on it."""
    return ms.server_offset_for_month(day[:7])


def day_row(day: str, bars: dict[str, dict], atr_lookup) -> dict | None:
    """One observation, exactly as the protocol declares it — or None with a reason."""
    for s in STAMPS_REQUIRED:
        if s not in bars:
            return None
    rod_open, lh_open, lh_close = (bars[ROD_OPEN], bars[LH_OPEN], bars[LH_CLOSE])
    r_rod = lh_open["open"] / rod_open["open"] - 1.0
    if r_rod == 0.0:                                  # declared skip: no direction
        return None
    stop = atr_at(atr_lookup, lh_open["time"])
    if not stop or stop <= 0:
        return None
    stop *= STOP_ATR_MULT
    direction = 1.0 if r_rod > 0 else -1.0
    gross = direction * (lh_close["close"] - lh_open["open"])
    s_in, s_out = max(lh_open["spread"], ms.SPREAD_FLOOR), max(lh_close["spread"],
                                                              ms.SPREAD_FLOOR)
    cost = s_in / 2.0 + s_out / 2.0
    off = era_offset(day)
    return {
        "day": day,
        "r_rod": r_rod,
        "r_lh": direction * (lh_close["close"] / lh_open["open"] - 1.0),
        "side": "long" if direction > 0 else "short",
        "gross_usd": gross, "cost_usd": cost, "net_usd": gross - cost,
        "stop_usd": stop,
        "gross_r": gross / stop, "cost_r": cost / stop, "net_r": (gross - cost) / stop,
        "entry_ct": lh_open["time"], "era_offset_min": off,
        "entry_utc": _utc(lh_open["time"] - (off or 0) * 60).strftime("%Y-%m-%d %H:%M"),
    }


def stats(rows: list[dict], key: str) -> dict:
    v = [r[key] for r in rows]
    n = len(v)
    if n < 2:
        return {"n": n, "mean": None, "sd": None, "t": None, "mde": None}
    mean = sum(v) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1))
    t = mean / (sd / math.sqrt(n)) if sd else float("nan")
    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4),
            "t": round(t, 2) if sd else None,
            "mde": round((T_CRIT + Z_POWER) * sd / math.sqrt(n), 4) if sd else None}


def slope(rows: list[dict]) -> dict:
    """Auxiliary: the paper's regression r_LH = a + b·r_ROD, in percent. The DECISION is on
    mean net R (see the protocol); this is supporting evidence and is reported as such."""
    xs = [r["r_rod"] * 100 for r in rows]
    ys = [r["r_lh"] * 100 for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return {"b": None, "t": None}
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = [y - a - b * x for x, y in zip(xs, ys)]
    s2 = sum(e * e for e in resid) / (n - 2)
    se = math.sqrt(s2 / sxx) if sxx else float("nan")
    return {"a": round(a, 4), "b": round(b, 4),
            "t": round(b / se, 2) if se else None}


def verdict(pooled: dict, eras: list[dict]) -> tuple[str, str]:
    """The declared decision rule, applied literally. No judgement calls."""
    t, mean = pooled["t"], pooled["mean"]
    era_means = [e["mean"] for e in eras if e["n"] >= 2]
    if t is None:
        return "VOID", "not enough observations to compute a t-statistic"
    if mean > 0 and t >= T_CRIT and all(m >= 0 for m in era_means):
        return "PASS", (f"pooled net {mean:+.4f}R/day, t={t:+.2f} >= {T_CRIT}, "
                        f"both eras non-negative")
    below = pooled["mde"] is not None and abs(mean) < pooled["mde"]
    if below:
        return "UNDECIDED AT THIS N", (
            f"pooled net {mean:+.4f}R/day, t={t:+.2f}; the effect is inside the "
            f"minimum detectable {pooled['mde']:.4f}R/day at n={pooled['n']} — this sample "
            f"cannot distinguish it from zero either way")
    return "FAIL", (f"pooled net {mean:+.4f}R/day, t={t:+.2f} — at or above the "
                    f"minimum detectable {pooled['mde']:.4f}R/day and it does not clear "
                    f"{T_CRIT}")


def run(m15_path: str = M15_PATH, h1_path: str = H1_PATH) -> dict:
    m15 = ms.load_bars(m15_path)
    h1 = ms.load_bars(h1_path)
    days = by_day(m15)
    atr_lookup = h1_atr_lookup(h1)

    rows, skipped, refused_months = [], {}, {}
    for day in sorted(days):
        if era_offset(day) is None:
            refused_months[day[:7]] = refused_months.get(day[:7], 0) + 1
            continue
        row = day_row(day, days[day], atr_lookup)
        if row is None:
            missing = [s for s in STAMPS_REQUIRED if s not in days[day]]
            key = ("missing stamps " + ",".join(missing)) if missing else "other"
            skipped[key] = skipped.get(key, 0) + 1
            continue
        rows.append(row)

    if not rows:
        raise SystemExit(
            f"VOID: no qualifying day in {m15_path}.\n"
            f"      examined {len(days)} stamped days; skipped {skipped}; refused months "
            f"{refused_months}\n"
            f"      -> the venue's day does not end where this protocol assumes it does, so\n"
            f"         the test is void rather than failed (protocol §Limits 4).")
    coverage = len(rows) / (len(rows) + sum(skipped.values()) + sum(refused_months.values()))
    if coverage < 0.5:
        raise SystemExit(
            f"VOID: only {coverage:.0%} of stamped days qualify ({len(rows)} of "
            f"{len(days)}; skipped {skipped}).\n"
            f"      -> a test on the minor part of the window is not the declared test.")

    eras = []
    for off in sorted({r["era_offset_min"] for r in rows}):
        sub = [r for r in rows if r["era_offset_min"] == off]
        eras.append({"era_offset_min": off, "utc_lh_window":
                     f"{sub[0]['entry_utc'][-5:]} UTC + 30m", **stats(sub, "net_r")})

    pooled = stats(rows, "net_r")
    gross = stats(rows, "gross_r")
    cost = stats(rows, "cost_r")
    v, why = verdict(pooled, eras)
    wins = sum(1 for r in rows if r["net_r"] > 0)
    return {
        "what": "close-anchored intraday momentum on the venue's own day close",
        "protocol": "docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md",
        "data_of_record": [m15_path, h1_path],
        "window": {"ldo_open_stamp": ROD_OPEN, "lh_stamps": [LH_OPEN, LH_CLOSE],
                   "stop": f"{STOP_ATR_MULT}x ATR(H1,14)", "cost": "recorded half-spread "
                   f"each side, floor ${ms.SPREAD_FLOOR:.2f}"},
        "coverage": {"qualifying_days": len(rows),
                     "stamped_days": len(days),
                     "skipped": skipped, "refused_months": refused_months},
        "pooled": {**pooled, "win_rate": round(wins / pooled["n"], 3)},
        "gross_pooled": gross,
        "cost_pooled": cost,
        "per_era": eras,
        "regression_r_lh_on_r_rod_pct": slope(rows),
        "verdict": v, "why": why,
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=ARTIFACT)
    ap.add_argument("--m15", default=M15_PATH)
    ap.add_argument("--h1", default=H1_PATH)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()

    res = run(args.m15, args.h1)
    p, g, c = res["pooled"], res["gross_pooled"], res["cost_pooled"]
    print(f"\nclose-anchored intraday momentum  |  {res['coverage']['qualifying_days']} days "
          f"of {res['coverage']['stamped_days']} stamped")
    print(f"  window: {ROD_OPEN} -> {LH_OPEN} -> {LH_CLOSE} server "
          f"= the last 30 min before the venue's 23:00 break")
    print(f"  GROSS  {g['mean']:+.4f}R/day  sd {g['sd']:.4f}  t {g['t']:+.2f}")
    print(f"  COST   {-c['mean']:+.4f}R/day")
    print(f"  NET    {p['mean']:+.4f}R/day  sd {p['sd']:.4f}  t {p['t']:+.2f}  "
          f"win {p['win_rate']:.1%}  n {p['n']}")
    print(f"  MDE(80% power) {p['mde']:.4f}R/day    regression b "
          f"{res['regression_r_lh_on_r_rod_pct']['b']} "
          f"(t {res['regression_r_lh_on_r_rod_pct']['t']})")
    for e in res["per_era"]:
        print(f"  era +{e['era_offset_min']:>3} min ({e['utc_lh_window']}): "
              f"{e['mean']:+.4f}R/day  t {e['t']:+.2f}  n {e['n']}")
    if res["coverage"]["skipped"]:
        print(f"  skipped: {res['coverage']['skipped']}")
    if res["coverage"]["refused_months"]:
        print(f"  refused months (DST step inside): {res['coverage']['refused_months']}")
    print(f"\nVERDICT: {res['verdict']} — {res['why']}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1)
        print(f"artifact: {args.json}")
    return 0


def _bar(day: str, hhmm: str, o: float, c: float, spread: float = 0.30) -> dict:
    """One synthetic bar in the shape `load_bars` produces."""
    t = ms.iso_to_ts(f"{day} {hhmm}")
    return {"time": t, "open": o, "high": max(o, c), "low": min(o, c), "close": c,
            "spread": spread}


def selftest() -> int:
    """The harness's own arithmetic, on cases whose answer is known by construction."""
    checks = []
    atr = [(ms.iso_to_ts("2026-05-04 00:00"), 5.0)]
    # momentum: day up 1%, then the last 30 min continues up -> long wins the gross
    bars = {"00:00": _bar("2026-05-04", "00:00", 100.0, 100.0),
            "22:00": _bar("2026-05-04", "22:00", 100.9, 100.9),
            "22:15": _bar("2026-05-04", "22:15", 101.0, 101.2),
            "22:30": _bar("2026-05-04", "22:30", 101.2, 101.5)}
    r = day_row("2026-05-04", bars, atr)
    checks.append(("direction is the day's, momentum", r is not None and r["side"] == "long"))
    checks.append(("gross is the 30-minute move", abs(r["gross_usd"] - 0.5) < 1e-9))
    # one full spread charged: two half-spreads of 0.30
    checks.append(("cost is one round-trip spread", abs(r["cost_usd"] - 0.30) < 1e-9))
    checks.append(("net = gross - cost", abs(r["net_usd"] - 0.20) < 1e-9))
    checks.append(("R divides by the declared stop", abs(r["stop_usd"] - 10.0) < 1e-9
                   and abs(r["net_r"] - 0.02) < 1e-9))
    # spread floor: a bar recording zero charges the floor, not nothing
    z_bars = dict(bars)
    z_bars["22:15"] = {**bars["22:15"], "spread": 0.0}
    z_bars["22:30"] = {**bars["22:30"], "spread": 0.0}
    z = day_row("2026-05-04", z_bars, atr)
    checks.append(("zero recorded spread pays the $0.10 floor each side",
                   abs(z["cost_usd"] - 0.10) < 1e-9))
    # a flat day is skipped, not traded
    flat = dict(bars)
    flat["22:15"] = {**bars["22:15"], "open": 100.0}
    flat["00:00"] = {**bars["00:00"], "open": 100.0}
    checks.append(("r_ROD == 0 is skipped", day_row("2026-05-04", flat, atr) is None))
    # a missing stamp is skipped, not interpolated
    short = {k: v for k, v in bars.items() if k != "22:30"}
    checks.append(("missing LH close is skipped", day_row("2026-05-04", short, atr) is None))
    # the decision rule, on constructed samples — including the UNDECIDED branch
    good = [{"net_r": 0.2 + 0.01 * i, "r_rod": 0.01, "r_lh": 0.002} for i in range(20)]
    p = stats(good, "net_r")
    checks.append(("a steady positive mean PASSes",
                   verdict(p, [{"n": 10, "mean": 0.2}, {"n": 10, "mean": 0.25}])[0] == "PASS"))
    checks.append(("a negative era REFUSES the pass",
                   verdict(p, [{"n": 10, "mean": 0.2}, {"n": 10, "mean": -0.01}])[0] != "PASS"))
    noisy = [{"net_r": 0.001 * (1 if i % 2 else -1)} for i in range(50)]
    checks.append(("an effect inside the MDE reads UNDECIDED",
                   verdict(stats(noisy, "net_r"), [])[0] == "UNDECIDED AT THIS N"))
    # the ATR lookup is causal
    look = [(100, 1.0), (200, 2.0)]
    checks.append(("ATR lookup never reads forward", atr_at(look, 150) == 1.0
                   and atr_at(look, 200) == 2.0 and atr_at(look, 50) is None))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    print(f"\nselftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""V28 §11 regime-conditional analysis — implements the FROZEN pre-registration.

Hypothesis under test (protocol §11, frozen 2026-09-16 before any conditional
number existed): REVERSE_TRIGGER's expectancy is positive conditional on a
decision-time regime state R. Two frozen candidates:

  R1 = H4+H1 EMA20 macro state at entry (the EA's own ReadMacroDirection rule,
       recomputed from M15 bars: H4/H1 close[1] vs EMA20 of closes[1]).
       For REVERSE_TRIGGER every trade is macro-ALIGNED by construction, so
       the contrast is ALIGNED_UP vs ALIGNED_DOWN.
  R2 = ATR(14, H1) percentile within the trailing 200 H1 bars, split at 50.

Pass gate (frozen): uplift(R=on - R=off) >= +0.10R/trade with 95% bootstrap
CI excluding zero, same sign in both chronological split halves, n(on) >= 40.

Inputs: the tagged re-run journal segments (regime_wf/oos/is180_*) — the
deterministic re-runs whose fills match the registry exactly (267/232/521).
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import build_parity as bp  # noqa: E402

RE_OPEN = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+\[v\d+\.\d+\] "
    r"OPEN (BUY|SELL).*?trigger=(\S+)")
RE_CLOSE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+\[v\d+\.\d+\] "
    r"\w+ \w+ ticket=(\d+) pnl=([+-][\d.]+) R=([+-][\d.]+)")
RE_TS = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})$")


def ts_epoch(s: str) -> int:
    m = RE_TS.match(s)
    import calendar
    return calendar.timegm((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), int(m.group(6)),
                            0, 0, 0))


def segment_lines(tag: str) -> list[str]:
    lines = bp.agent_lines_today()
    starts = [i for i, l in enumerate(lines)
              if "MACRO started" in l and f"experiment={tag}" in l]
    if not starts:
        raise SystemExit(f"segment {tag} not found")
    s = starts[-1]
    e = next((i for i in range(s + 1, len(lines))
              if "MACRO started" in lines[i]), len(lines))
    return lines[s:e]


def parse_trades(tag: str) -> list[dict]:
    opens, closes = [], []
    for l in segment_lines(tag):
        mo = RE_OPEN.search(l)
        if mo:
            opens.append({"ts": ts_epoch(mo.group(1)), "side": mo.group(2),
                          "trigger": mo.group(3)})
            continue
        mc = RE_CLOSE.search(l)
        if mc:
            closes.append({"ts": ts_epoch(mc.group(1)), "ticket": mc.group(2),
                           "pnl": float(mc.group(3)), "R": float(mc.group(4))})
    if len(opens) != len(closes):
        raise SystemExit(f"{tag}: OPEN/CLOSE count mismatch "
                         f"{len(opens)}/{len(closes)}")
    trades = []
    for o, c in zip(opens, closes):
        o | c
        trades.append({"ts": o["ts"], "side": o["side"], "trigger": o["trigger"],
                       "close_ts": c["ts"], "R": c["R"], "pnl": c["pnl"]})
    trades.sort(key=lambda t: t["ts"])
    return trades


# --- bars: H1/H4 aggregation from the M15 CSV --------------------------------

def load_h1(bars_csv: str) -> list[dict]:
    rows = []
    with open(bars_csv, encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.strip().split(",")
            if len(p) < 5:
                continue
            rows.append((int(p[0]), float(p[1]), float(p[2]),
                         float(p[3]), float(p[4])))
    rows.sort(key=lambda r: r[0])
    # H1 buckets: floor(ts/3600); O=first open, H=max high, L=min low, C=last close
    h1: dict[int, list] = {}
    for ts, o, h, l, c in rows:
        b = ts // 3600
        if b not in h1:
            h1[b] = [o, h, l, c]
        else:
            bar = h1[b]
            bar[1] = max(bar[1], h)
            bar[2] = min(bar[2], l)
            bar[3] = c
    return [{"ts": b * 3600, "o": v[0], "h": v[1], "l": v[2], "c": v[3]}
            for b, v in sorted(h1.items())]


def ema(vals: list[float], period: int = 20) -> list[float]:
    out, k = [], 2.0 / (period + 1.0)
    prev = vals[0]
    for v in vals:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def atr14(bars: list[dict]) -> list[float]:
    out, prev_close = [], bars[0]["c"]
    trs: list[float] = []
    for b in bars:
        tr = max(b["h"] - b["l"], abs(b["h"] - prev_close), abs(b["l"] - prev_close))
        trs.append(tr)
        prev_close = b["c"]
        if len(trs) < 14:
            out.append(float("nan"))
            continue
        window = trs[-14:] if len(trs) == 14 else None
        if len(out) == 13:
            out.append(sum(trs[:14]) / 14)  # first ATR = SMA of first 14 TRs
        else:
            out.append((out[-1] * 13 + tr) / 14)  # Wilder smoothing
    return out


class MacroOracle:
    """EA-faithful H4+H1 EMA20 macro state + ATR percentile, from M15 bars.

    Fail-closed: a trade timestamp outside the bars' coverage (or inside the
    indicator warm-up) yields None — the trade is excluded and counted, never
    silently conditioned on bar-zero garbage (caught live 2026-09-16: the
    fresh90 file silently answered 2025 trades with May-2026 bar 0).
    """

    WARMUP_BARS = 220  # EMA20 settling + the 200-bar ATR percentile window

    def __init__(self, bars_csv: str):
        self.h1 = load_h1(bars_csv)
        self.h1_close = [b["c"] for b in self.h1]
        self.h1_ema = ema(self.h1_close, 20)
        self.h1_ts = [b["ts"] for b in self.h1]
        # H4 buckets (4h, epoch-aligned)
        h4: dict[int, list] = {}
        for b in self.h1:
            k = b["ts"] // 14400
            if k not in h4:
                h4[k] = [b["o"], b["h"], b["l"], b["c"]]
            else:
                bar = h4[k]
                bar[1] = max(bar[1], b["h"])
                bar[2] = min(bar[2], b["l"])
                bar[3] = b["c"]
        self.h4_ts = [k * 14400 for k in sorted(h4)]
        self.h4_close = [h4[k][3] for k in sorted(h4)]
        self.h4_ema = ema(self.h4_close, 20)
        self.h1_atr = atr14(self.h1)
        self.coverage = (self.h1_ts[self.WARMUP_BARS], self.h1_ts[-1])

    def _last_closed(self, ts_list: list[int], t: int) -> int:
        # index of last bar STRICTLY before the bar containing t
        import bisect
        i = bisect.bisect_left(ts_list, (t // 3600) * 3600 if len(ts_list) and
                               ts_list[1] - ts_list[0] == 3600 else t)
        return max(0, i - 1)

    def macro(self, t: int) -> str | None:
        if t < self.coverage[0] or t > self.coverage[1]:
            return None
        i1 = self._last_closed(self.h1_ts, t)
        # H4: last closed H4 bucket before t
        import bisect
        j4 = bisect.bisect_left(self.h4_ts, (t // 14400) * 14400) - 1
        j4 = max(0, j4)
        h4_up = self.h4_close[j4] > self.h4_ema[j4]
        h1_up = self.h1_close[i1] > self.h1_ema[i1]
        if h4_up and h1_up:
            return "ALIGNED_UP"
        if (not h4_up) and (not h1_up):
            return "ALIGNED_DOWN"
        return "DIVERGENT"

    def atr_pctile(self, t: int) -> float:
        import bisect
        i1 = self._last_closed(self.h1_ts, t)
        a = self.h1_atr[i1]
        if a != a:
            return float("nan")
        window = [x for x in self.h1_atr[max(0, i1 - 200):i1 + 1] if x == x]
        return sum(1 for x in window if x <= a) / len(window) * 100.0


# --- frozen gate math ---------------------------------------------------------

def boot_ci_diff(a: np.ndarray, b: np.ndarray, n: int = 10000,
                 seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    diffs = [a[rng.integers(0, len(a), len(a))].mean()
             - b[rng.integers(0, len(b), len(b))].mean()
             for _ in range(n)]
    return tuple(np.percentile(diffs, [2.5, 97.5]))  # type: ignore


def condition_and_gate(trades: list[dict], oracle: MacroOracle,
                       label: str, split: str = "all") -> dict:
    r1, r2, uncovered = [], [], 0
    for t in trades:
        m = oracle.macro(t["ts"])
        if m is None:
            uncovered += 1
            t["R1"] = t["R2"] = None
            continue
        t["R1"] = m
        t["R2"] = "HIGH" if oracle.atr_pctile(t["ts"]) >= 50 else "LOW"
        r1.append(t["R1"])
        r2.append(t["R2"])
    covered = [t for t in trades if t["R1"] is not None]
    out: dict = {"label": label, "n": len(trades), "uncovered": uncovered,
                 "covered": len(covered)}
    for name, key, on in (("R1", "R1", "ALIGNED_UP"), ("R2", "R2", "HIGH")):
        on_r = np.array([t["R"] for t in covered if t[key] == on])
        off_r = np.array([t["R"] for t in covered if t[key] != on])
        if len(on_r) < 5 or len(off_r) < 5:
            out[name] = {"n_on": int(len(on_r)), "n_off": int(len(off_r)),
                         "verdict": "INSUFFICIENT"}
            continue
        lo, hi = boot_ci_diff(on_r, off_r)
        uplift = float(on_r.mean() - off_r.mean())
        out[name] = {"n_on": int(len(on_r)), "n_off": int(len(off_r)),
                     "expR_on": round(float(on_r.mean()), 4),
                     "expR_off": round(float(off_r.mean()), 4),
                     "uplift": round(uplift, 4),
                     "ci95": [round(lo, 4), round(hi, 4)]}
    return out


def main() -> None:
    # Explicit: the file whose coverage spans all three windows (the fresh90
    # file silently answered 2025 trades with 2026 bars — see MacroOracle).
    bars = str(REPO / "artifacts" / "data" / "volatility_75_index_m15_40000bars.csv")
    oracle = MacroOracle(bars)
    tags = {"wf": "regime_wf_20260916_202710Z",
            "oos": "regime_oos_20260916_202710Z",
            "is180": "regime_is180_20260916_203024Z"}
    report: dict = {"bars": bars, "windows": {}}
    all_trades: dict[str, list[dict]] = {}
    for win, tag in tags.items():
        trades = parse_trades(tag)
        all_trades[win] = trades
        rep = {"tag": tag, "n": len(trades),
               "all": condition_and_gate(trades, oracle, win)}
        # chronological split halves
        half = len(trades) // 2
        rep["h1"] = condition_and_gate(trades[:half], oracle, win, "first")
        rep["h2"] = condition_and_gate(trades[half:], oracle, win, "second")
        report["windows"][win] = rep
        side_agree = sum(
            1 for t in trades
            if (t["side"] == "BUY") == (t["R1"] == "ALIGNED_UP"))
        print(f"[{win}] n={len(trades)} side-vs-macro agreement: "
              f"{side_agree}/{len(trades)}")
        for grp in ("all", "h1", "h2"):
            for r in ("R1", "R2"):
                d = rep[grp].get(r, {})
                print(f"  {grp} {r}: n_on={d.get('n_on')} "
                      f"expR_on={d.get('expR_on')} expR_off={d.get('expR_off')} "
                      f"uplift={d.get('uplift')} ci={d.get('ci95')}")

    out = REPO / "artifacts" / "v28_research" / "regime_test_verdict.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"artifact: {out}")


if __name__ == "__main__":
    main()

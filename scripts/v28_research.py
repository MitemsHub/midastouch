#!/usr/bin/env python3
"""V28 research engine — experiment registry, scorecard, and promotion gate.

Turns "run the tester and eyeball the balance" into a registry. Every candidate
is an explicit hypothesis with an immutable experiment ID, launched through the
same headless launcher on the same data window as every other candidate, scored
by a scorecard (never by net profit alone), and promotable only after
in-sample -> walk-forward -> untouched out-of-sample evidence plus robustness
checks.

Rules encoded here (from the V28 spec):
  * one hypothesis = one experiment ID. A candidate is never edited after a
    losing run; a change is a NEW experiment.
  * the optimization score is the EA's whole-run cumulative R, read from the
    RESEARCH_RESULT line and cross-checked against the report's own
    "OnTester result" field — never the daily-reset session value.
  * fewer than MIN_TRADES trades cannot be promoted however large the profit.
  * promotion needs all three sample roles (is / wf / oos) for the same
    hypothesis AND a robustness pass (trade bootstrap + drop-best-N).
  * the OOS window is reserved: it is never used to choose a candidate.

Usage:
  python scripts/v28_research.py equivalence
  python scripts/v28_research.py matrix --windows is90
  python scripts/v28_research.py matrix --windows is180
  python scripts/v28_research.py matrix --windows wf
  python scripts/v28_research.py matrix --windows oos
  python scripts/v28_research.py exit-sweep --survivors V28_ORIGINAL V28_REVERSE_TRIGGER
  python scripts/v28_research.py wf-family
  python scripts/v28_research.py score
  python scripts/v28_research.py export
  python scripts/v28_research.py promote --hypothesis ORIGINAL_sl2.0_tp4.0_h180
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from v75_tester_runner import journal_paths, report_stats, run_pass   # noqa: E402

ART = REPO / "artifacts" / "v28_research"
REGISTRY = ART / "registry.jsonl"

EA_V28 = r"MITEMSHUB_AI\MitemshubAI_v28"
EA_V27 = r"MITEMSHUB_AI\MitemshubAI"

MIN_TRADES = 30          # house sample gate: below this, nothing can be promoted
MC_ITERATIONS = 2000
MC_SEED = 20260913       # fixed => reproducibility
PASS_TIMEOUT_S = 900

# Data windows. Roles are contiguous, non-overlapping 90-day blocks of the
# cached V75 real ticks. `oos` is deliberately the OLDEST block so discovery
# can never have seen it; `is` is the most recent, which is where a hypothesis
# is allowed to be discovered.
WINDOWS: dict[str, tuple[str, str, str]] = {
    "is90":  ("2026.06.12", "2026.09.10", "is"),
    "is180": ("2026.03.14", "2026.09.10", "is"),
    "wf":    ("2025.12.14", "2026.03.13", "wf"),
    "oos":   ("2025.09.15", "2025.12.13", "oos"),
}

MODES: dict[str, int] = {
    "V28_ORIGINAL": 0,
    "V28_REVERSE_DIRECTION": 1,
    "V28_REVERSE_TRIGGER": 2,
    "V28_REVERSE_BOTH": 3,
    "V28_LONG_ONLY": 4,
    "V28_SHORT_ONLY": 5,
    "V28_MACRO_ONLY": 6,
    "V28_TRIGGER_ONLY": 7,
}

# Geometry defaults == the v27 contract (2x / 4x H1 ATR14, 180 min, 1% risk).
DEFAULT_GEOMETRY = {"risk": 0.01, "sl_atr": 2.0, "tp_atr": 4.0, "hold_min": 180}

# Recommended optimization ranges. Deliberately narrower than the EA's hard
# limits so an optimizer cannot waste passes on absurd points, and ordered so
# the sweep is staged rather than combinatorial.
RECOMMENDED_RANGES = {
    "sl_atr": (1.0, 1.5, 2.0, 2.5, 3.0),
    "tp_atr": (2.0, 3.0, 4.0, 5.0, 6.0),
    "hold_min": (30, 60, 90, 120, 180, 240, 360),
    "risk": (0.005, 0.01, 0.02),
}


# ----------------------------------------------------------------------------
# Candidate identity
# ----------------------------------------------------------------------------
def hypothesis(mode: str, geometry: dict | None = None) -> str:
    """Stable identity for one hypothesis (mode + geometry). Same identity =>
    same experiment, whatever the run order."""
    g = {**DEFAULT_GEOMETRY, **(geometry or {})}
    short = mode.replace("V28_", "")
    return (f"{short}_sl{g['sl_atr']:g}_tp{g['tp_atr']:g}_h{g['hold_min']}"
            f"_r{g['risk']:g}")


def candidate_inputs(mode: str, geometry: dict | None = None,
                     tag: str | None = None) -> dict[str, str]:
    """Complete explicit [TesterInputs]: a partial set would silently merge with
    the agent's cached inputs, so every pass sends the whole surface."""
    g = {**DEFAULT_GEOMETRY, **(geometry or {})}
    return {
        "InpLiveExecution": "true",          # the tester must be allowed to trade
        "InpMagic": "7788075",
        "InpMaxDeviationPoints": "50",
        "InpDrawHud": "false",               # HUD is a chart feature, not a tester one
        "InpStrategyMode": str(MODES[mode]),
        "InpResearchLogging": "true",
        "InpExperimentTag": tag or hypothesis(mode, geometry),
        "InpAllowLong": "true",
        "InpAllowShort": "true",
        "InpLegacyV27ModifyClose": "false",
        "InpRiskFraction": str(g["risk"]),
        "InpStopATRMultiplier": str(g["sl_atr"]),
        "InpTargetATRMultiplier": str(g["tp_atr"]),
        "InpMaxHoldMinutes": str(g["hold_min"]),
    }


# ----------------------------------------------------------------------------
# Registry (append-only, unique IDs, reproducible)
# ----------------------------------------------------------------------------
def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return [json.loads(line) for line in REGISTRY.read_text().splitlines() if line.strip()]


def append_registry(record: dict) -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def next_id(records: list[dict]) -> str:
    return f"V28-{len(records) + 1:04d}"


def find_record(records: list[dict], hyp: str, window: str) -> dict | None:
    for r in records:
        if r["hypothesis"] == hyp and r["window"] == window:
            return r
    return None


# ----------------------------------------------------------------------------
# One experiment
# ----------------------------------------------------------------------------
def _kv(line: str) -> dict[str, str]:
    out = {}
    for token in line.split():
        if "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
    return out


def choose_whole_run_pnl(line_pnl: float | None, report_net: float | None,
                         deals_pnl: float) -> tuple[float, str]:
    """Whole-run P&L, in preference order, with its provenance.

    1. the EA's own counter from the RESEARCH_RESULT line — the same money the
       R denominator and OnTester() see, so R and P&L describe one run;
    2. the report's `Total Net Profit` header;
    3. the deals-table sum, last because it drifts from both by ~$0.05/trade
       (up to $60 on a 1,200-trade run) and that bias is one-directional, so it
       made out-of-sample P&L look better than it was on 23 of 32 records.
    """
    if line_pnl is not None:
        return line_pnl, "ea_journal"
    if report_net is not None:
        return report_net, "report_net"
    return deals_pnl, "deals_sum"


def money_implied_r(test_pnl: float, mean_risk: float | None) -> float | None:
    """The R figure that converts back to this run's money: net P&L / mean risk.

    `cumulative_r` is a SUM OF RATIOS, so it only recovers the money through the
    mean denominator — the two are equal only when every per-trade risk is
    identical, and equity drift plus lot rounding make them differ by ~20%
    (measured: -1.4951 money-implied vs -1.1922 ratio-sum on one run). Returns
    None when the denominator is unknown, so a caller has to say "unavailable"
    rather than quietly substituting the ratio-sum figure.
    """
    if mean_risk is None or mean_risk <= 0.0:
        return None
    return test_pnl / mean_risk


# The OPEN line prints exactly the geometry the EA submitted, so a pass that
# never emitted an R_RECONCILE line can still be reconciled. The EA's denominator
# is (stop_distance / tick_size) * CalibratedTickValue() * volume, and on V75 the
# calibrated value is the geometric identity tick_size*contract_size
# (0.01 * 1.0), which reduces the expression to |entry - SL| * volume.
_OPEN_GEOMETRY_RE = re.compile(
    r"OPEN (?:BUY|SELL) volume=([\d.]+) entry=([\d.]+) SL=([\d.]+)")


def mean_risk_from_segment(segment: list[str]) -> tuple[float | None, str]:
    """Mean per-trade risk for one pass, with its provenance.

    Preference order mirrors `choose_whole_run_pnl`: the EA's own R_RECONCILE
    line when the build emitted one, else reconstructed from the pass's OPEN
    lines. Reconstruction was validated against a pass carrying both: 96.48
    reconstructed vs 96.86 reported over 262 closes (identical minimum, maximum
    within 0.4%), the residual being that the EA's POSITION source uses the
    actual fill while the OPEN print shows the requested price.
    """
    line = next((l for l in reversed(segment) if "R_RECONCILE " in l), None)
    if line:
        kv = _kv(line.split("R_RECONCILE ", 1)[-1])
        try:
            return float(kv["mean_risk"]), "ea_reconcile_line"
        except (KeyError, ValueError):
            pass
    risks: list[float] = []
    for raw in segment:
        m = _OPEN_GEOMETRY_RE.search(raw)
        if not m:
            continue
        volume, entry, stop = (float(m.group(i)) for i in (1, 2, 3))
        if volume > 0.0 and entry > 0.0 and stop > 0.0:
            risks.append(abs(entry - stop) * volume)
    if not risks:
        return None, ""
    return sum(risks) / len(risks), "open_lines"


def run_experiment(window: str, mode: str, geometry: dict | None = None,
                   expert: str = EA_V28, tag: str | None = None) -> dict:
    """Run one candidate on one window and return its raw record."""
    if window not in WINDOWS:
        raise SystemExit(f"unknown window {window!r}; known: {list(WINDOWS)}")
    frm, to, role = WINDOWS[window]
    hyp = hypothesis(mode, geometry)
    # The run tag IS the EA's experiment tag: that makes the journal line
    # addressable by the pass that produced it (the tagged fallback capture and
    # the window-qualified identity in the log both depend on it matching).
    # The tag must identify exactly ONE pass. Experiment ids are deterministic,
    # so a bare window+hypothesis tag repeats on every re-run of the same cell —
    # and every journal lookup (wait, backfill) is tag-addressed. A stale match
    # then reads a superseded build's numbers as this pass's own.
    run_tag = f"v28_{window}_{tag or hyp}_{os.getpid()}-{time.strftime('%m%d%H%M%S')}"
    result = run_pass(run_tag, candidate_inputs(mode, geometry, run_tag),
                      dates=(frm, to), timeout_s=PASS_TIMEOUT_S, expert=expert,
                      wait_for_research_line=True)
    rep, journal, stats = result["report"], result["journal"], report_stats(run_tag)
    research = _kv(journal.get("research_result", ""))

    def stat_number(label: str) -> float:
        raw = stats.get(label, "")
        raw = raw.split("(")[0].replace(" ", "").replace("%", "")
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def num(key: str, default: float | None = 0.0) -> float | None:
        """A number from the RESEARCH_RESULT line, or `default` — never a crash
        when the journal capture flakes or an older build omits a field."""
        raw = str(research.get(key, "")).strip().rstrip("%")
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    # MT5 records what OnTester() returned in the report itself. Prefer that as
    # the whole-run score and treat the journal line as the cross-check, so a
    # missing journal field can never silently become a zero score.
    line_r = num("test_R", None)
    stats_r = stat_number("OnTester result")
    cumulative_r = line_r if line_r is not None else stats_r
    test_pnl, pnl_source = choose_whole_run_pnl(
        num("test_pnl", None),
        stat_number("Total Net Profit") if "Total Net Profit" in stats else None,
        round(rep["pnl"], 2))
    # Mean per-trade risk, from the EA's own reconciliation line. Without it the
    # record's R cannot be converted to dollars, which is why the gate refuses
    # to treat a missing denominator as "fine".
    reconcile = _kv(journal.get("r_reconcile", ""))
    try:
        mean_risk = float(reconcile.get("mean_risk", ""))
    except ValueError:
        mean_risk = None
    implied_r = money_implied_r(test_pnl, mean_risk)

    return {
        "hypothesis": hyp,
        "run_tag": run_tag,
        "mode": mode,
        "mode_id": MODES[mode],
        "geometry": {**DEFAULT_GEOMETRY, **(geometry or {})},
        "window": window,
        "window_from": frm,
        "window_to": to,
        "role": role,
        "trades": rep["fills"],
        "test_pnl": round(test_pnl, 2),
        "pnl_source": pnl_source,
        "mean_risk": round(mean_risk, 2) if mean_risk else None,
        "money_implied_r": round(implied_r, 4) if implied_r is not None else None,
        "r_reconcile": journal.get("r_reconcile", ""),
        "cumulative_r": cumulative_r,
        "win_rate_pct": num("win_rate") or 0.0,
        "sl_exits": int(num("sl_exits") or 0),
        "tp_exits": int(num("tp_exits") or 0),
        "timeout_exits": int(num("timeout_exits") or 0),
        "profit_factor": stat_number("Profit Factor"),
        "max_drawdown": stat_number("Balance Drawdown Maximal"),
        "max_drawdown_pct": float(str(stats.get("Balance Drawdown Maximal", "0"))
                                  .split("(")[-1].rstrip("%)") or 0.0),
        "expectancy": stat_number("Expected Payoff"),
        "recovery_factor": stat_number("Recovery Factor"),
        "avg_win": stat_number("Average profit trade"),
        "avg_loss": stat_number("Average loss trade"),
        "longest_loss_streak": int(stat_number("Maximum consecutive losses ($)") or 0),
        "on_tester_result": stats_r,
        "r_matches_report": (None if line_r is None
                             else abs(line_r - stats_r) <= 1e-6),
        "research_line_present": bool(research),
        "history_quality": stats.get("History Quality", ""),
        "bars": stat_number("Bars"),
        "ticks": stat_number("Ticks"),
        "trades_pnl": rep.get("trade_pnls", []),
        "entries_on_bar_open": rep.get("entries_on_bar_open", False),
        "research_line": journal.get("research_result", ""),
    }


# ----------------------------------------------------------------------------
# Robustness
# ----------------------------------------------------------------------------
def bootstrap(pnls: list[float], iterations: int = MC_ITERATIONS,
              seed: int = MC_SEED) -> dict:
    """Resample the completed trades with replacement (fixed seed => the same
    candidate always gets the same verdict). Reports the net-P&L distribution
    and the share of resamples that stay profitable."""
    if not pnls:
        return {"iterations": 0, "p05": 0.0, "p50": 0.0, "p95": 0.0, "profitable_share": 0.0}
    rng = random.Random(seed)
    n = len(pnls)
    nets = sorted(sum(rng.choice(pnls) for _ in range(n)) for _ in range(iterations))
    profitable = sum(1 for x in nets if x > 0)
    return {
        "iterations": iterations,
        "p05": round(nets[int(0.05 * iterations)], 2),
        "p50": round(nets[iterations // 2], 2),
        "p95": round(nets[int(0.95 * iterations)], 2),
        "profitable_share": round(profitable / iterations, 3),
    }


def drop_best(pnls: list[float], count: int) -> float:
    """Net P&L after removing the `count` most profitable trades — the standard
    'is the edge in a few lucky trades?' probe."""
    return round(sum(sorted(pnls)[:-count] if count else pnls), 2)


def order_shuffle_drawdown(pnls: list[float], iterations: int = MC_ITERATIONS,
                           seed: int = MC_SEED) -> dict:
    """Trade-order randomisation: the final P&L is order-invariant, but the
    drawdown is not. Reports the drawdown distribution over shuffled orders."""
    if not pnls:
        return {"p50_dd": 0.0, "p95_dd": 0.0}
    rng = random.Random(seed + 1)
    dds = []
    for _ in range(iterations):
        order = pnls[:]
        rng.shuffle(order)
        equity, peak, worst = 0.0, 0.0, 0.0
        for p in order:
            equity += p
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        dds.append(worst)
    dds.sort()
    return {"p50_dd": round(dds[iterations // 2], 2),
            "p95_dd": round(dds[int(0.95 * iterations)], 2)}


def robustness(record: dict) -> dict:
    pnls = record.get("trades_pnl", [])
    return {
        "bootstrap": bootstrap(pnls),
        "drop_best_1": drop_best(pnls, 1),
        "drop_best_3": drop_best(pnls, 3),
        "order_shuffle": order_shuffle_drawdown(pnls),
    }


def robustness_pass(rob: dict) -> bool:
    """A candidate survives only if its edge is not a few trades and not a coin
    flip. Deliberately blunt: cheap to compute, hard to game."""
    return (rob["bootstrap"]["profitable_share"] >= 0.80
            and rob["drop_best_3"] > 0
            and rob["bootstrap"]["p05"] > 0)


# ----------------------------------------------------------------------------
# Scorecard & promotion gate
# ----------------------------------------------------------------------------
def _primary_is(records: list[dict], hyp: str) -> dict | None:
    """is90 and is180 share the `is` role, so collapse them deterministically:
    prefer the long window, which is the real discovery sample."""
    is_records = [r for r in records if r.get("hypothesis") == hyp and r.get("role") == "is"]
    for window in ("is180", "is90"):
        for r in is_records:
            if r.get("window") == window:
                return r
    return is_records[0] if is_records else None


def _by_role(records: list[dict], hyp: str) -> dict[str, dict]:
    """One record per sample role, with `is` resolved to the long window."""
    out: dict[str, dict] = {}
    for r in records:
        if r.get("hypothesis") != hyp or r.get("role") == "is":
            continue
        out[r["role"]] = r
    primary = _primary_is(records, hyp)
    if primary is not None:
        out["is"] = primary
    return out


def scorecard(records: list[dict], hyp: str) -> dict:
    """Scorecard for one hypothesis across every role it has evidence for."""
    by_role = _by_role(records, hyp)
    primary = by_role.get("is") or next(iter(by_role.values()), None)
    if primary is None:
        raise SystemExit(f"no registry records for hypothesis {hyp!r}")
    rob = robustness(primary)
    is_rec, wf_rec, oos_rec = by_role.get("is"), by_role.get("wf"), by_role.get("oos")
    # .get with defaults: a record read back from an older registry (or a
    # partially written line) must never crash the scorecard.
    g = primary.get
    rows = {
        "hypothesis": hyp,
        "net_pnl": g("test_pnl", 0.0),
        # Two R measures, both reported, because they are not the same number:
        # cumulative_r is the sum of per-trade ratios (what OnTester scores),
        # money_implied_r is net P&L / mean risk (what converts back to dollars).
        "cumulative_r": g("cumulative_r", 0.0),
        "mean_risk": g("mean_risk"),
        "money_implied_r": (g("money_implied_r")
                            if g("money_implied_r") is not None
                            else money_implied_r(g("test_pnl", 0.0), g("mean_risk"))),
        "expectancy_r_money": (round(g("money_implied_r") / g("trades", 0), 4)
                               if g("money_implied_r") and g("trades", 0) else None),
        "profit_factor": g("profit_factor", 0.0),
        "max_drawdown": g("max_drawdown", 0.0),
        "expectancy_usd": g("expectancy", 0.0),
        "expectancy_r": (round(g("cumulative_r", 0.0) / g("trades", 0), 4)
                         if g("trades", 0) else 0.0),
        "win_rate_pct": g("win_rate_pct", 0.0),
        "avg_win": g("avg_win", 0.0),
        "avg_loss": g("avg_loss", 0.0),
        "longest_loss_streak": g("longest_loss_streak", 0),
        "trade_count": g("trades", 0),
        "recovery_factor": g("recovery_factor", 0.0),
        "oos_pnl": oos_rec.get("test_pnl") if oos_rec else None,
        "wf_pnl": wf_rec.get("test_pnl") if wf_rec else None,
        "walker_forward_consistency": (
            None if not (is_rec and wf_rec)
            else ("consistent" if (is_rec.get("test_pnl", 0.0) > 0) == (wf_rec.get("test_pnl", 0.0) > 0)
                  else "sign-flip")),
        "roles_present": sorted(by_role),
        "robustness": rob,
    }
    return rows


def promotion_gate(records: list[dict], hyp: str) -> tuple[bool, list[str]]:
    """Refuse every promotion that is not backed by all three sample roles,
    enough trades, and a robustness pass."""
    by_role = _by_role(records, hyp)
    reasons: list[str] = []
    for role in ("is", "wf", "oos"):
        if role not in by_role:
            reasons.append(f"missing {role} evidence (a single backtest is never enough)")
    thin = [f"{role}={by_role[role]['trades']} trades"
            for role in ("is", "wf", "oos")
            if role in by_role and by_role[role]["trades"] < MIN_TRADES]
    if thin:
        reasons.append(f"below the {MIN_TRADES}-trade sample gate: {', '.join(thin)}")
    if "oos" in by_role:
        oos = by_role["oos"]
        money_r = oos.get("money_implied_r") or money_implied_r(
            oos.get("test_pnl", 0.0), oos.get("mean_risk"))
        ratio_r = oos.get("cumulative_r")
        if oos["test_pnl"] <= 0.0:
            reasons.append(f"out-of-sample net P&L is not positive ({oos['test_pnl']:+.2f})")
        if money_r is None:
            reasons.append("out-of-sample has no mean-risk denominator, so its R cannot be "
                           "converted to dollars (run `backfill` to resolve it)")
        else:
            # Quote the money and the R that correspond to each other.
            if money_r <= 0.0:
                reasons.append(
                    f"out-of-sample money-implied R is not positive ({money_r:+.4f} = "
                    f"{oos['test_pnl']:+.2f} USD / mean risk {oos.get('mean_risk', 0.0):.2f})")
            if ratio_r is not None and (money_r > 0.0) != (ratio_r > 0.0):
                reasons.append(f"out-of-sample R measures disagree in sign (ratio-sum "
                               f"{ratio_r:+.4f} vs money-implied {money_r:+.4f})")
        if ratio_r is not None and ratio_r <= 0.0:
            reasons.append(f"out-of-sample ratio-sum R is not positive ({ratio_r:+.4f})")
    if "is" in by_role and "wf" in by_role:
        if (by_role["is"]["test_pnl"] > 0) != (by_role["wf"]["test_pnl"] > 0):
            reasons.append("walk-forward P&L sign flips versus in-sample")
    if "is" in by_role:
        rob = robustness(by_role["is"])
        if not robustness_pass(rob):
            reasons.append(
                "robustness failed: bootstrap p05 "
                f"{rob['bootstrap']['p05']:+.2f}, profitable share "
                f"{rob['bootstrap']['profitable_share']:.2f}, drop-best-3 "
                f"{rob['drop_best_3']:+.2f}")
    return (not reasons), reasons


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
def cmd_equivalence(_: argparse.Namespace) -> None:
    """Prove v28 mode 0 is the v27 strategy: identical window, identical risk
    geometry, compared trade for trade."""
    window = "is90"
    frm, to, _ = WINDOWS[window]
    v27 = run_pass(f"v28eq_v27_{window}",
                   {"InpLiveExecution": "true", "InpMagic": "7788075",
                    "InpMaxDeviationPoints": "50", "InpDrawHud": "false"},
                   dates=(frm, to), timeout_s=PASS_TIMEOUT_S, expert=EA_V27)
    # Mode 0 reproduces v27 through the legacy switch; the DEFAULT instead keeps
    # a position the broker already protects, which is the corrected contract.
    legacy_inputs = {**candidate_inputs("V28_ORIGINAL"),
                     "InpLegacyV27ModifyClose": "true"}
    legacy = run_pass(f"v28eq_m0legacy_{window}", legacy_inputs, dates=(frm, to),
                      timeout_s=PASS_TIMEOUT_S, expert=EA_V28)
    mode0 = run_experiment(window, "V28_ORIGINAL")
    same_fills = v27["report"]["fills"] == legacy["report"]["fills"]
    same_pnl = abs(v27["report"]["pnl"] - legacy["report"]["pnl"]) <= 0.5
    same_seq = (v27["report"].get("trade_pnls", []) == legacy["report"].get("trade_pnls", []))
    print(f"v27                      : fills={v27['report']['fills']} "
          f"pnl={v27['report']['pnl']:+.2f}")
    print(f"v28 mode 0 (legacy switch): fills={legacy['report']['fills']} "
          f"pnl={legacy['report']['pnl']:+.2f}")
    print(f"MOD0 REPRODUCES v27: fills={same_fills} pnl={same_pnl} "
          f"trade_sequence={same_seq} -> "
          f"{'PASS' if (same_fills and same_pnl and same_seq) else 'FAIL'}")
    print(f"v28 mode 0 (default fix)  : fills={mode0['trades']} "
          f"pnl={mode0['test_pnl']:+.2f} R={mode0['cumulative_r']:+.3f} "
          f"sl/tp/to={mode0['sl_exits']}/{mode0['tp_exits']}/{mode0['timeout_exits']}")
    print("NOTE: the default deliberately departs from v27 here — v27 closed a "
          "position the broker was already protecting, so it never held a trade.")


def cmd_matrix(args: argparse.Namespace) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    records = load_registry()
    for window in args.windows:
        for mode in MODES:
            existing = find_record(records, hypothesis(mode), window)
            if existing:
                print(f"[{window}] {existing['experiment_id']} {existing['hypothesis']} "
                      f"(already registered, skipped)")
                continue
            rec = run_experiment(window, mode)
            # Re-read before appending: a second research process may have
            # registered the same hypothesis while this pass ran, and the
            # registry must never hold two rows for one experiment.
            records = load_registry()
            if find_record(records, rec["hypothesis"], window):
                print(f"[{window}] {rec['hypothesis']} registered concurrently, skipped",
                      flush=True)
                continue
            rec["experiment_id"] = next_id(records)
            records.append(append_registry(rec))
            if not rec["research_line_present"]:
                print(f"[{window}] WARNING {rec['hypothesis']}: no RESEARCH_RESULT line "
                      f"captured; whole-run R taken from the report's OnTester field "
                      f"({rec['on_tester_result']:+.3f})", flush=True)
            print(f"[{window}] {rec['experiment_id']} {rec['hypothesis']:34s} "
                  f"trades={rec['trades']:3d} pnl={rec['test_pnl']:+9.2f} "
                  f"R={rec['cumulative_r']:+.3f} PF={rec['profit_factor']:.2f} "
                  f"sl/tp/to={rec['sl_exits']}/{rec['tp_exits']}/{rec['timeout_exits']} "
                  f"OnTester={rec['on_tester_result']:+.3f}", flush=True)


def cmd_exit_sweep(args: argparse.Namespace) -> None:
    """Staged exit/holding sweep on the survivors, one axis at a time, so the
    search stays a sequence of hypotheses instead of a combinatorial grid."""
    ART.mkdir(parents=True, exist_ok=True)
    records = load_registry()
    window = args.window
    for mode in args.survivors:
        for axis, values in (("sl_atr", RECOMMENDED_RANGES["sl_atr"]),
                             ("tp_atr", RECOMMENDED_RANGES["tp_atr"]),
                             ("hold_min", RECOMMENDED_RANGES["hold_min"])):
            for value in values:
                geom = {axis: value}
                hyp = hypothesis(mode, geom)
                if find_record(records, hyp, window):
                    print(f"[{window}] {hyp} (registered, skipped)")
                    continue
                rec = run_experiment(window, mode, geom)
                rec["experiment_id"] = next_id(records)
                rec["sweep_axis"] = axis
                records.append(append_registry(rec))
                print(f"[{window}] {rec['experiment_id']} {hyp:34s} "
                      f"trades={rec['trades']:3d} pnl={rec['test_pnl']:+9.2f} "
                      f"R={rec['cumulative_r']:+.3f} PF={rec['profit_factor']:.2f}",
                      flush=True)


# ----------------------------------------------------------------------------
# OOS one-shot gate (FROZEN 2026-09-16, before any interior OOS run exists).
#
# The stage-2 sweep produced 15 REVERSE_BOTH cells with is+wf evidence, but the
# §3 OOS block stays reserved: 90 days of one regime yields only ~12 family
# trades, so an OOS run can never satisfy the 30-trade promotion gate. Its
# honest purpose is a FINAL HISTORICAL VERDICT that decides whether the family
# has earned a pre-registered FORWARD-TEST PROPOSAL (arm-D style, fresh window,
# frozen adjudication) — never a direct ship, never re-tuning against the OOS
# result. The shot is single-use for the WHOLE interior: one run spends it,
# whatever the outcome (token + any interior oos row in the registry both
# block; deleting the token cannot re-arm it).
#
# Rule text lives in V28_RESEARCH_PROTOCOL.md §9 amendment 3. Changing these
# constants after any interior OOS row exists is an amendment-grade violation.

OOS_BASELINE_HYP = "REVERSE_BOTH_sl2_tp4_h180_r0.01"   # already has its oos row
OOS_ELIGIBILITY = {           # the bar a cell must clear on ALREADY-HELD windows
    "min_is_r": 2.0,          # is180 cumulative R: a real in-sample edge
    "min_wf_r": 1.5,          # wf cumulative R: sign-confirmed out-of-regime
    "wf_sign_must_match": True,   # wf P&L sign must match is (no flips)
    "max_dd_pct": 20.0,       # wf drawdown ceiling (% of the $10k deposit)
}
OOS_DD_ABORT_MONEY = 3000.0   # 30% of the frozen $10 000 deposit, in dollars


def oos_token_path() -> Path:
    return ART / "OOS_ONESHOT_TOKEN.json"


def oos_token_state() -> dict:
    try:
        return json.loads(oos_token_path().read_text())
    except (OSError, ValueError):
        return {"spent": False, "spent_at": None, "spent_for": None,
                "decision": None}


def oos_one_shot_eligibility(records: list[dict]) -> tuple[bool, list[dict]]:
    """Which interior sweep cells clear the frozen pre-OOS bar?

    Mechanical, from the registry only: both an is180 and a wf row must exist,
    is R >= min_is_r, wf R >= min_wf_r, wf P&L sign matching is, and wf
    drawdown within the ceiling. Two exclusions are part of the frozen rule:
    the baseline (its oos row already exists — stage 1, not the interior's
    shot), and any cell whose is180 trade set is IDENTICAL to the baseline's
    (same n and pnl: the tp3/5/6 duplicate-exit rows — they are the same
    strategy under another label, not distinct hypotheses, and must not
    multiply the shot's apparent choices).
    """
    cells: dict[str, dict[str, dict]] = {}
    for r in records:
        if (r.get("mode") == "V28_REVERSE_BOTH" and r.get("sweep_axis")
                and r["hypothesis"] != OOS_BASELINE_HYP
                and r.get("window") in ("is180", "wf")):
            cells.setdefault(r["hypothesis"], {})[r["window"]] = r
    baseline_is = next((r for r in records if r["hypothesis"] == OOS_BASELINE_HYP
                        and r.get("window") == "is180"), None)
    dup_sig = ((baseline_is["trades"], baseline_is["test_pnl"])
               if baseline_is else None)
    eligible: list[dict] = []
    for hyp, by_window in sorted(cells.items()):
        if "is180" not in by_window or "wf" not in by_window:
            continue
        if dup_sig and (by_window["is180"]["trades"],
                        by_window["is180"]["test_pnl"]) == dup_sig:
            continue   # identical trade set = the baseline's strategy, relabeled
        is_r, wf = by_window["is180"]["cumulative_r"], by_window["wf"]
        dd_pct = wf["max_drawdown"] / 10000.0 * 100.0
        if (is_r >= OOS_ELIGIBILITY["min_is_r"]
                and wf["cumulative_r"] >= OOS_ELIGIBILITY["min_wf_r"]
                and (not OOS_ELIGIBILITY["wf_sign_must_match"]
                     or (wf["test_pnl"] > 0) == (by_window["is180"]["test_pnl"] > 0))
                and dd_pct <= OOS_ELIGIBILITY["max_dd_pct"]):
            eligible.append({"hypothesis": hyp, "is_r": round(is_r, 3),
                             "wf_r": round(wf["cumulative_r"], 3),
                             "wf_dd_pct": round(dd_pct, 2),
                             "geometry": by_window["is180"]["geometry"]})
    return bool(eligible), eligible


def oos_one_shot_decision(rec: dict) -> tuple[str, list[str]]:
    """The frozen mapping from the single OOS run to its final verdict."""
    reasons: list[str] = []
    if rec["max_drawdown"] > OOS_DD_ABORT_MONEY:
        reasons.append(f"drawdown ${rec['max_drawdown']:.2f} breaches the "
                       f"${OOS_DD_ABORT_MONEY:.0f} (30%) abort line")
        return "FAMILY_RETIRED", reasons
    if rec["test_pnl"] > 0 and (rec["cumulative_r"] or 0) > 0:
        if rec["trades"] >= MIN_TRADES:
            return "EARNED_FORWARD_TEST_PROPOSAL", reasons
        reasons.append(f"positive OOS (pnl {rec['test_pnl']:+.2f}, "
                       f"R {rec['cumulative_r']:+.3f}) but n={rec['trades']} "
                       f"<{MIN_TRADES}: any proposal must carry the thin-sample "
                       f"disclosure")
        return "CONTINUE_THIN", reasons
    reasons.append(f"OOS pnl {rec['test_pnl']:+.2f} / R {rec['cumulative_r']:+.3f} "
                   f"not positive on the family's one historical shot")
    return "FAMILY_RETIRED", reasons


def cmd_oos_oneshot(args: argparse.Namespace) -> None:
    """The interior's single OOS run, gated by the frozen pre-registration."""
    ART.mkdir(parents=True, exist_ok=True)
    records = load_registry()
    token = oos_token_state()
    ok, eligible = oos_one_shot_eligibility(records)
    spent_rows = [r["hypothesis"] for r in records
                  if r.get("mode") == "V28_REVERSE_BOTH" and r.get("sweep_axis")
                  and r["hypothesis"] != OOS_BASELINE_HYP and r.get("window") == "oos"]
    print(f"OOS one-shot gate (frozen 2026-09-16): is R >= "
          f"{OOS_ELIGIBILITY['min_is_r']}, wf R >= {OOS_ELIGIBILITY['min_wf_r']}, "
          f"sign match, wf DD <= {OOS_ELIGIBILITY['max_dd_pct']}%")
    if not eligible:
        print("  no interior cell clears the bar — the OOS block stays closed. "
              "Nothing ran.")
        return
    for e in eligible:
        print(f"  eligible: {e['hypothesis']:34s} is {e['is_r']:+7.3f}R "
              f"wf {e['wf_r']:+7.3f}R (dd {e['wf_dd_pct']:.2f}%)")
    if spent_rows or token["spent"]:
        who = token.get("spent_for") or ", ".join(sorted(set(spent_rows)))
        print(f"REFUSED: the one-shot is already spent ({who}). The OOS block "
              f"is closed forever for the interior — see the frozen decision "
              f"in {oos_token_path().name}.")
        sys.exit(2)
    if args.dry_run or not args.cell:
        print("dry-run: nothing ran. Spending the shot requires an explicit "
              "--cell <hypothesis> from the eligible list.")
        return
    if args.cell and not args.reason:
        print("REFUSED: spending the shot requires --reason (recorded in the "
              "token, so the cell choice is auditable against the frozen bar).")
        sys.exit(2)
    if args.cell not in {e["hypothesis"] for e in eligible}:
        print(f"REFUSED: {args.cell} is not an eligible cell under the frozen bar.")
        sys.exit(2)
    chosen = next(e for e in eligible if e["hypothesis"] == args.cell)
    geom = chosen["geometry"]
    rec = run_experiment("oos", "V28_REVERSE_BOTH", geom)
    records = load_registry()      # re-read: never hold two rows for one experiment
    if find_record(records, rec["hypothesis"], "oos"):
        print(f"{rec['hypothesis']} oos row registered concurrently; refusing "
              f"to double-run the one-shot.")
        sys.exit(2)
    rec["experiment_id"] = next_id(records)
    rec["sweep_axis"] = "oos_oneshot"
    append_registry(rec)
    decision, reasons = oos_one_shot_decision(rec)
    token.update({"spent": True,
                  "spent_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "spent_for": rec["hypothesis"], "decision": decision,
                  "reason": args.reason,
                  "eligible_at_spend": [e["hypothesis"] for e in eligible],
                  "oos": {"n": rec["trades"], "pnl": rec["test_pnl"],
                          "r": rec["cumulative_r"],
                          "max_dd": rec["max_drawdown"]}})
    oos_token_path().write_text(json.dumps(token, indent=1))
    print(f"[oos] {rec['experiment_id']} {rec['hypothesis']:34s} "
          f"trades={rec['trades']:3d} pnl={rec['test_pnl']:+9.2f} "
          f"R={rec['cumulative_r']:+.3f} PF={rec['profit_factor']:.2f}")
    print(f"FROZEN DECISION: {decision}")
    for r_ in reasons:
        print(f"  - {r_}")
    print("The interior's OOS shot is spent. No re-run, no re-tuning against "
          "this window, ever.")


# --- family-level wf significance (protocol §9 amendment 4) -------------------

# Below this many DISTINCT pooled trades a family verdict is not allowed: the
# sweep cells share one window, so their trades are far from independent and a
# small pool would look decisive while carrying a handful of underlying signals.
FAMILY_MIN_TRADES = 100


def _distinct_wf_cells(records: list[dict], mode: str, window: str = "wf") -> list[dict]:
    """The mode's `window` rows, deduplicated to distinct trade sets, in registry order.

    The sweep re-runs one strategy under different exits, and byte-identical
    trade lists mean one hypothesis under two labels (measured on both windows:
    tp3/tp5/tp6 == the baseline). A family test that counted labels instead of
    trade sets would quadruple-count that one strategy, so identical
    (trades, test_pnl) signatures are grouped — and confirmed by comparing the
    full sorted trade lists, failing closed on a signature collision. The group's
    representative is the baseline-geometry row (the one without `sweep_axis`)
    when present, else the first registered; `_collapsed_duplicates` records how
    many labels it stands for.
    """
    groups: dict[tuple[int, float], list[dict]] = {}
    for rec in records:
        if rec.get("mode") != mode or rec.get("window") != window:
            continue
        if not rec.get("trades_pnl"):
            continue
        key = (rec["trades"], round(rec["test_pnl"], 2))
        grp = groups.setdefault(key, [])
        if grp and sorted(grp[0]["trades_pnl"]) != sorted(rec["trades_pnl"]):
            raise SystemExit(
                f"trade-set signature collision on {window} row "
                f"{rec.get('experiment_id')}: same (n, pnl) as "
                f"{grp[0].get('experiment_id')} but different trade lists")
        grp.append(rec)
    out = []
    for grp in groups.values():
        rep = dict(min(grp, key=lambda r: (1 if r.get("sweep_axis") else 0,
                                           r.get("experiment_id") or "")))
        rep["_collapsed_duplicates"] = len(grp) - 1
        out.append(rep)
    out.sort(key=lambda r: r.get("experiment_id") or "")
    return out


def permutation_diff_pvalue(a: list[float], b: list[float],
                            iterations: int = MC_ITERATIONS,
                            seed: int = MC_SEED) -> float:
    """One-sided permutation p-value for mean(a) > mean(b) under exchangeability.

    Unpaired on purpose: a paired comparison would need trade-by-trade
    correspondence the two pools do not have, and pairing on nothing would
    invent covariance. Honest limits, both directions: ignoring any positive
    family-vs-baseline covariance is conservative, but the trades WITHIN the
    family pool are not independent either (cells share one window and much of
    one signal stream), so the effective sample size is below `len(a)` and the
    p-value is approximate — read "p just under 0.05" as borderline, never as
    established. Deterministic via the house seed.
    """
    if not a or not b:
        return 1.0
    obs = sum(a) / len(a) - sum(b) / len(b)
    pool = a + b
    na = len(a)
    rng = random.Random(seed + 2)
    hits = 0
    for _ in range(iterations):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        diff = (sum(shuffled[:na]) / na
                - sum(shuffled[na:]) / (len(pool) - na))
        if diff >= obs:
            hits += 1
    return round(hits / iterations, 4)


def wf_family_significance(records: list[dict], mode: str = "V28_REVERSE_BOTH",
                           baseline_mode: str = "V28_ORIGINAL",
                           window: str = "wf") -> dict:
    """Family-level significance test on one HELD window (default wf).

    Per-cell verdicts answer "is this geometry good"; this answers the question
    actually posed by the sweep — does the MODE carry an edge on the window,
    beyond what the ORIGINAL mode did on the same window. Mechanically:

    1. dedupe the mode's window rows to distinct trade sets (`_distinct_wf_cells`);
    2. pool them into one per-trade family sample;
    3. bootstrap the family against zero and the ORIGINAL wf pool;
    4. permutation-test the family-vs-ORIGINAL difference in mean per trade
       (one-sided; unpaired, and approximate — see `permutation_diff_pvalue`;
       which is exactly why the verdict bar is blunt and multi-part rather
       than resting on one p-value).

    All figures are dollars per trade; the cells share a ~$100 mean risk, so
    dollars and R move together and no conversion is applied. Verdict bar
    (blunt, mirroring `robustness_pass`): pooled distinct trades >=
    FAMILY_MIN_TRADES, family bootstrap p05 > 0 and profitable_share >= 0.80,
    mean per trade strictly above ORIGINAL's, permutation p <= 0.05.
    Timestamp-free by design: same registry, byte-identical artifact.

    The OOS window is refused in code, unconditionally: the family test is a
    HELD-window instrument, and letting it read OOS would spend evidence the
    §9 amendment 3 one-shot rule reserves (and launder look-ahead into a
    verdict). If this refusal ever blocks a legitimate need, that is an
    amendment-grade protocol change, not a flag.
    """
    if window == "oos":
        raise SystemExit(
            "REFUSED: the OOS window is refused for family aggregation, "
            "unconditionally. The one-shot rule (protocol §9 amendment 3) "
            "owns that window; a family read here would spend it. Amending "
            "requires a recorded protocol change, not a flag.")
    cells = _distinct_wf_cells(records, mode, window)
    if not cells:
        raise SystemExit(f"no {window} trade data for mode {mode}")
    orig = next((r for r in records if r.get("mode") == baseline_mode
                 and r.get("window") == window and r.get("trades_pnl")), None)
    if orig is None:
        raise SystemExit(f"no {window} trade data for baseline mode {baseline_mode}")

    pool = [p for c in cells for p in c["trades_pnl"]]
    orig_tp = orig["trades_pnl"]
    fam_boot = bootstrap(pool)
    orig_boot = bootstrap(orig_tp)
    diff = sum(pool) / len(pool) - sum(orig_tp) / len(orig_tp)
    p_one = permutation_diff_pvalue(pool, orig_tp)

    per_cell = []
    for c in cells:
        per_cell.append({
            "experiment_id": c.get("experiment_id"),
            "hypothesis": c["hypothesis"],
            "sweep_axis": c.get("sweep_axis"),
            "trades": c["trades"],
            "money_implied_r": c.get("money_implied_r"),
            "collapsed_duplicates": c["_collapsed_duplicates"],
            "bootstrap_profitable_share": bootstrap(c["trades_pnl"])["profitable_share"],
        })

    reasons: list[str] = []
    if len(pool) < FAMILY_MIN_TRADES:
        reasons.append(f"pooled distinct trades {len(pool)} < {FAMILY_MIN_TRADES}")
    if fam_boot["p05"] <= 0:
        reasons.append("family bootstrap p05 <= 0")
    if fam_boot["profitable_share"] < 0.80:
        reasons.append("family bootstrap profitable_share < 0.80")
    if diff <= 0:
        reasons.append("family mean per trade <= ORIGINAL wf mean per trade")
    if p_one > 0.05:
        reasons.append(f"permutation p {p_one} > 0.05")

    return {
        "window": window,
        "mode": mode,
        "baseline_mode": baseline_mode,
        "wf_rows_read": sum(1 for r in records
                            if r.get("mode") == mode and r.get("window") == window
                            and r.get("trades_pnl")),
        "distinct_trade_sets": len(cells),
        "duplicates_collapsed": sum(c["_collapsed_duplicates"] for c in cells),
        "cells": per_cell,
        "pooled_trades": len(pool),
        "family": {"mean_per_trade": round(sum(pool) / len(pool), 4),
                   "bootstrap": fam_boot},
        "baseline": {"experiment_id": orig.get("experiment_id"),
                     "hypothesis": orig["hypothesis"],
                     "trades": orig["trades"],
                     "mean_per_trade": round(sum(orig_tp) / len(orig_tp), 4),
                     "bootstrap": orig_boot},
        "mean_diff_per_trade": round(diff, 4),
        "permutation_p_one_sided": p_one,
        "verdict": "FAMILY_EDGE_SUPPORTED" if not reasons else "FAMILY_EDGE_NOT_SUPPORTED",
        "reasons": reasons,
    }


def _family_artifact_path(window: str) -> str:
    """wf keeps the original name (cited in the protocol); other held windows
    get the window suffix so no run ever overwrites another's artifact."""
    return ("wf_family_significance.json" if window == "wf"
            else f"family_significance_{window}.json")


def cmd_wf_family(args: argparse.Namespace) -> None:
    if getattr(args, "leave_one_out", False):
        cmd_leave_one_out(args)
        return
    rep = wf_family_significance(load_registry(), mode=args.mode,
                                 baseline_mode=args.baseline,
                                 window=args.window)
    ART.mkdir(parents=True, exist_ok=True)
    out = ART / _family_artifact_path(args.window)
    out.write_text(json.dumps(rep, indent=1) + "\n")

    print(f"family significance: {rep['mode']} vs {rep['baseline_mode']} "
          f"(window {rep['window']})")
    print(f"  wf rows read: {rep['wf_rows_read']} -> "
          f"{rep['distinct_trade_sets']} distinct trade sets "
          f"({rep['duplicates_collapsed']} duplicate labels collapsed)")
    print(f"  pooled distinct trades: {rep['pooled_trades']}")
    for c in rep["cells"]:
        dup = f" (+{c['collapsed_duplicates']} label(s))" if c["collapsed_duplicates"] else ""
        print(f"    {c['experiment_id']}  {c['hypothesis']:<38s} n={c['trades']:3d} "
              f"mir={c['money_implied_r']:+7.3f} "
              f"boot_profit={c['bootstrap_profitable_share']:.3f}{dup}")
    f, b = rep["family"], rep["baseline"]
    print(f"  family  mean/trade {f['mean_per_trade']:+.4f}  "
          f"boot p05 {f['bootstrap']['p05']:+.2f}  "
          f"profitable {f['bootstrap']['profitable_share']:.3f}")
    print(f"  {rep['baseline_mode']} mean/trade {b['mean_per_trade']:+.4f}  "
          f"boot p05 {b['bootstrap']['p05']:+.2f}  "
          f"profitable {b['bootstrap']['profitable_share']:.3f}")
    print(f"  mean diff per trade {rep['mean_diff_per_trade']:+.4f}  "
          f"permutation p(1-sided) {rep['permutation_p_one_sided']}")
    print(f"  VERDICT: {rep['verdict']}")
    for reason in rep["reasons"]:
        print(f"  - {reason}")
    print(f"  artifact -> {out}")


def _sensitivity_path(window: str) -> str:
    """Held-window sensitivity runs share the suffix; OOS never reaches here
    (wf_family_significance refuses it before any artifact name is built)."""
    return f"family_sensitivity_{window}.json"


def cmd_leave_one_out(args: argparse.Namespace) -> None:
    """Diagnostic, not a gate: re-run the family aggregation on the same held
    window with exactly one distinct cell excluded, then with it re-added
    alone. Names no promotable configuration, keeps no OOS resource, and its
    only output is which cells carry the family verdict."""
    records = load_registry()
    full = wf_family_significance(records, mode=args.mode,
                                  baseline_mode=args.baseline,
                                  window=args.window)
    cells = full["cells"]
    by_hyp = {c["hypothesis"]: c for c in cells}
    rows: list[dict] = []
    for drop in cells:
        kept = [c for c in cells if c["hypothesis"] != drop["hypothesis"]]
        sub = [r for r in records if r.get("window") == args.window
               and r.get("mode") == args.mode
               and r.get("hypothesis") in {k["hypothesis"] for k in kept}]
        # the baseline rows travel with every subset — the aggregation needs
        # them for the contrast, but they are never part of the family pool
        sub += [r for r in records if r.get("window") == args.window
                and r.get("mode") == args.baseline]
        loo = wf_family_significance(sub, mode=args.mode,
                                     baseline_mode=args.baseline,
                                     window=args.window)
        ro = wf_family_significance([r for r in records
                                     if r.get("window") == args.window
                                     and r.get("mode") == args.mode
                                     and r.get("hypothesis") == drop["hypothesis"]]
                                    + [r for r in records
                                       if r.get("window") == args.window
                                       and r.get("mode") == args.baseline],
                                    mode=args.mode,
                                    baseline_mode=args.baseline,
                                    window=args.window)
        rows.append({
            "dropped": drop["hypothesis"],
            "loo_verdict": loo["verdict"],
            "loo_mean_per_trade": loo["family"]["mean_per_trade"],
            "loo_permutation_p": loo["permutation_p_one_sided"],
            "solo_verdict": ro["verdict"],
            "solo_mean_per_trade": ro["family"]["mean_per_trade"],
            "solo_permutation_p": ro["permutation_p_one_sided"],
        })
    rep = {"window": args.window, "mode": args.mode,
           "baseline_mode": args.baseline,
           "full_verdict": full["verdict"], "kind": "leave_one_cell_out",
           "full": {"mean_per_trade": full["family"]["mean_per_trade"],
                    "permutation_p": full["permutation_p_one_sided"]},
           "cells": rows}
    ART.mkdir(parents=True, exist_ok=True)
    out = ART / _sensitivity_path(args.window)
    out.write_text(json.dumps(rep, indent=1) + "\n")

    print(f"family sensitivity (leave one distinct cell out), window "
          f"{args.window}: {args.mode} vs {args.baseline}")
    print(f"  full family: verdict {full['verdict']}  "
          f"mean/trade {full['family']['mean_per_trade']:+.4f}  "
          f"p {full['permutation_p_one_sided']}")
    for row in rows:
        note = ""
        if row["loo_verdict"] != full["verdict"]:
            note = "  <- dropping this cell FLIPS the verdict"
        elif row["solo_verdict"] == full["verdict"]:
            note = "  <- cell alone still passes"
        print(f"    drop {row['dropped']:<38s} loo mean "
              f"{row['loo_mean_per_trade']:+7.3f} p {row['loo_permutation_p']:.3f} "
              f"[{row['loo_verdict']}] | solo mean "
              f"{row['solo_mean_per_trade']:+7.3f} p {row['solo_permutation_p']:.3f} "
              f"[{row['solo_verdict']}]{note}")
    print(f"  artifact -> {out}")


def _tag_segment(lines: list[str], tag: str) -> list[str]:
    """The journal lines belonging to one pass.

    A pass is bracketed by its `InpExperimentTag=<tag>` input dump and its
    `RESEARCH_RESULT tag=<tag>` line. Tags are unique per pass now, but an older
    record can carry a reused tag, so the newest complete pair wins — the same
    rule the RESEARCH_RESULT lookup uses.
    """
    ends = [i for i, l in enumerate(lines) if f"RESEARCH_RESULT tag={tag} " in l]
    if not ends:
        return []
    end = ends[-1]
    starts = [i for i, l in enumerate(lines)
              if f"InpExperimentTag={tag}" in l and i < end]
    if not starts:
        return []
    return lines[starts[-1]:end + 1]


def cmd_backfill(_: argparse.Namespace) -> None:
    """Resolve each record's `RESEARCH_RESULT` journal line after the run.

    The EA prints that line from OnTester(), i.e. at the very end of the pass,
    and the tester agent can flush the journal after `run_pass` has already
    returned. Rather than block every pass, resolve the lines once the journal
    has settled and patch the registry in place. A run tag identifies one pass,
    and when the same experiment is re-run the journal carries both lines — the
    newest one is the one that belongs to this record.

    The same pass also owns the record's mean-risk denominator, which lives
    either in its R_RECONCILE line or in its OPEN geometry. Both are resolved
    here, so a record can state dollars and R consistently even when it was
    produced by a build that only printed one of them.
    """
    records = load_registry()
    if not records:
        raise SystemExit("registry is empty")
    journal = ""
    for log in journal_paths():
        try:
            journal += log.read_bytes().decode("utf-16-le", "ignore")
        except OSError:
            continue
    journal_lines = journal.splitlines()

    # one row per (hypothesis, window): a concurrent run must not double-count
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for rec in records:
        key = (rec["hypothesis"], rec["window"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)

    filled = 0
    for rec in deduped:
        run_tag = rec.get("run_tag") or f"v28_{rec['window']}_{rec['hypothesis']}"
        rec["run_tag"] = run_tag
        # Take the LAST match, never the first: a tag repeats in the journal
        # whenever the same experiment is re-run, and the oldest line belongs to
        # a superseded build. `re.search` silently imported those numbers once
        # (defect-era R replaced post-fix R on all 32 records).
        matches = re.findall(r"RESEARCH_RESULT tag=" + re.escape(run_tag) + r" (.*)", journal)
        if not matches:
            continue
        kv = _kv(matches[-1])
        rec["research_line_present"] = True
        rec["research_line"] = ("RESEARCH_RESULT tag=" + run_tag + " " + matches[-1])[:400]
        rec["cumulative_r"] = float(kv.get("test_R", rec["cumulative_r"]))
        rec["win_rate_pct"] = float(str(kv.get("win_rate", "0")).rstrip("%") or 0.0)
        rec["sl_exits"] = int(kv.get("sl_exits", 0))
        rec["tp_exits"] = int(kv.get("tp_exits", 0))
        rec["timeout_exits"] = int(kv.get("timeout_exits", 0))
        # The EA prints R with 4 decimals, so compare at print precision.
        rec["r_matches_report"] = abs(rec["cumulative_r"] - rec["on_tester_result"]) <= 1e-3
        # Mean risk travels with the record: without it the R cannot be converted
        # back to dollars, and the promotion gate refuses to guess. Resolved from
        # this pass's own journal segment only, never another pass's.
        segment = _tag_segment(journal_lines, run_tag)
        mean_risk, risk_source = (mean_risk_from_segment(segment) if segment
                                  else (None, ""))
        if mean_risk:
            rec["mean_risk"] = round(mean_risk, 2)
            rec["risk_source"] = risk_source
            # Derive the implied R from the *stored* denominator, so the record's
            # own fields satisfy test_pnl == money_implied_r * mean_risk exactly.
            implied = money_implied_r(rec.get("test_pnl", 0.0), rec["mean_risk"])
            rec["money_implied_r"] = round(implied, 4) if implied is not None else None
        filled += 1

    ART.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text("".join(json.dumps(r_) + "\n" for r_ in deduped))
    print(f"backfilled {filled}/{len(deduped)} records from the journal "
          f"({len(records) - len(deduped)} duplicate row(s) dropped)")
    for rec in deduped:
        if not rec.get("research_line_present"):
            print(f"  unresolved: {rec['experiment_id']} {rec['run_tag']}")


def cmd_score(_: argparse.Namespace) -> None:
    records = load_registry()
    if not records:
        raise SystemExit("registry is empty — run a matrix first")
    hyps = sorted({r["hypothesis"] for r in records})
    # Both R measures are printed side by side. They differ whenever per-trade
    # risk is not constant, and only the money-implied one multiplies back to net.
    print(f"{'hypothesis':34s} {'role':4s} {'n':>4s} {'net USD':>9s} {'R(ratio)':>9s} "
          f"{'R(money)':>9s} {'meanRisk':>8s} {'PF':>5s} {'DD':>7s} {'MC>0':>5s} {'dropB3':>8s}")
    for hyp in hyps:
        for role in ("is", "wf", "oos"):
            rec = next((r for r in records if r["hypothesis"] == hyp and r["role"] == role), None)
            if not rec:
                continue
            rob = robustness(rec)
            money_r = rec.get("money_implied_r") if rec.get("money_implied_r") is not None \
                else money_implied_r(rec.get("test_pnl", 0.0), rec.get("mean_risk"))
            money_text = f"{money_r:+9.3f}" if money_r is not None else "      n/a"
            mean_risk = rec.get("mean_risk")
            risk_text = f"{mean_risk:8.2f}" if mean_risk else "     n/a"
            print(f"{hyp:34s} {role:4s} {rec['trades']:4d} {rec['test_pnl']:+9.2f} "
                  f"{rec['cumulative_r']:+9.3f} {money_text} {risk_text} "
                  f"{rec['profit_factor']:5.2f} "
                  f"{rec['max_drawdown']:7.2f} "
                  f"{rob['bootstrap']['profitable_share']:5.2f} "
                  f"{rob['drop_best_3']:+8.2f}")
        ok, reasons = promotion_gate(records, hyp)
        print(f"    -> promotion: {'ALLOWED' if ok else 'REFUSED'} "
              f"{'' if ok else '| ' + '; '.join(reasons)}")


def cmd_promote(args: argparse.Namespace) -> None:
    records = load_registry()
    ok, reasons = promotion_gate(records, args.hypothesis)
    if ok:
        print(f"{args.hypothesis}: promotion gate PASSED — cleared for paper-forward "
              f"testing. Live trading remains a separate, manual decision.")
        return
    print(f"{args.hypothesis}: promotion REFUSED")
    for reason in reasons:
        print(f"  - {reason}")


def cmd_export(_: argparse.Namespace) -> None:
    records = load_registry()
    if not records:
        raise SystemExit("registry is empty")
    ART.mkdir(parents=True, exist_ok=True)
    fields = [k for k in records[0] if k not in ("trades_pnl", "research_line")]
    out_csv = ART / "registry.csv"
    with out_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (ART / "registry.json").write_text(json.dumps(records, indent=1))
    print(f"exported {len(records)} records -> {out_csv} and registry.json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("equivalence", help="prove v28 mode 0 == v27 on one window").set_defaults(
        func=cmd_equivalence)

    m = sub.add_parser("matrix", help="run the 8 modes on identical windows")
    m.add_argument("--windows", nargs="+", default=["is90"], choices=sorted(WINDOWS))
    m.set_defaults(func=cmd_matrix)

    e = sub.add_parser("exit-sweep", help="staged exit/hold sweep on survivors")
    e.add_argument("--survivors", nargs="+", required=True, choices=sorted(MODES))
    e.add_argument("--window", default="is180", choices=sorted(WINDOWS))
    e.set_defaults(func=cmd_exit_sweep)

    sub.add_parser("backfill",
                   help="resolve RESEARCH_RESULT lines after a run and dedupe"
                   ).set_defaults(func=cmd_backfill)

    sub.add_parser("score", help="scorecard across the registry").set_defaults(func=cmd_score)

    p = sub.add_parser("promote", help="ask the promotion gate about a hypothesis")
    p.add_argument("--hypothesis", required=True)
    p.set_defaults(func=cmd_promote)

    sub.add_parser("export", help="write registry.csv / registry.json").set_defaults(func=cmd_export)

    o = sub.add_parser("oos-oneshot",
                       help="the interior's single frozen OOS run (pre-registered "
                       "gate; see protocol §9 amendment 3)")
    o.add_argument("--cell", default=None,
                   help="the eligible hypothesis to spend the shot on (omit for "
                        "an eligibility listing / dry-run)")
    o.add_argument("--dry-run", action="store_true",
                   help="list eligibility without running anything")
    o.add_argument("--reason", default=None,
                   help="why this cell (recorded in the spend token; required "
                        "with --cell)")
    o.set_defaults(func=cmd_oos_oneshot)

    fsub = sub.add_parser("wf-family",
                          help="family-level wf significance: one verdict for the "
                          "whole sweep interior, bootstrap + permutation vs the "
                          "baseline mode (protocol §9 amendment 4)")
    fsub.add_argument("--mode", default="V28_REVERSE_BOTH", choices=sorted(MODES))
    fsub.add_argument("--baseline", default="V28_ORIGINAL", choices=sorted(MODES))
    fsub.add_argument("--window", default="wf", choices=("wf", "is90", "is180"),
                      help="held window to aggregate (oos is refused in code)")
    fsub.add_argument("--leave-one-out", action="store_true",
                      help="diagnostic: drop each distinct cell in turn, then "
                           "run it alone, to show which cells carry the verdict")
    fsub.set_defaults(func=cmd_wf_family)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

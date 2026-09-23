#!/usr/bin/env python3
"""Size one live symbol against the Upcomers prop rules, verified by the broker.

WHAT THIS ANSWERS, IN ONE COMMAND: *if the strategy fired right now on this
symbol, would the trade be legal, and at what lot size?* It answers it with the
terminal's own arithmetic rather than with spec fields, and it reports the
arming state separately so "legal" is never mistaken for "armed".

Why it is not just a calculator. Three separate things can each forbid a trade,
and they fail in different ways:

* **The dollar basis can be wrong.** `trade_tick_value` and `contract_size`
  disagreed by 10x for XAUUSD on 2026-09-19. So the basis is *measured* here with
  `order_calc_profit`, and any spec field that contradicts the measurement is
  printed as a disagreement rather than quietly outvoted.
* **The rules can forbid it.** The 3% daily floor, the 6% trailing shield and the
  Best Day profit ceiling are each evaluated against live equity/balance/peak.
* **The minimum lot can make correct sizing impossible.** If the smallest volume
  the broker accepts risks more than the budget allows, the correct answer is to
  not trade, and this exits non-zero saying so.

TWO SIZES, ALWAYS NAMED. This tool sizes to the venue's DAILY LOSS LIMIT; the EA sizes
`InpRiskPercent` of account equity. On the U25 arm those were 0.11 lots and 0.01 lots for
the same stop width, and a report that printed one of them invited taking it for the
other. Both are now printed, labelled, with the arm's read from the preset the arming
record names (`--preset` overrides) — and the arm's line is the one that will be sent.

WHAT "NOT ARMED" IS NOT. The arming switch used to be fed into the legality check,
so an unarmed-but-legal configuration printed the single word `BLOCK` — next to a
`$0.00` Best Day allowance, and on an account whose only sin was having no profit
yet. Both readings were wrong, and both were this tool's own reporting:

* **Legality and arming are now two labelled verdicts, never one word.** The rules
  decide `legality`; the arming record decides `arming switch`. A legal trade on an
  unarmed system says exactly that and exits **4** — a code a pipeline can tell apart
  from a rule refusal (**1**).
* **The Best Day allowance never prints bare.** `$0.00` means "today's ceiling is
  reached" in one state and "no profit is banked yet, so the share is undefined" in
  another, and only the first is a refusal. The line names which (see
  `BEST_DAY_NO_PROFIT_YET` / `BEST_DAY_CAP_REACHED` in the execution layer).

The headline question is unchanged: *if the strategy fired right now on this symbol,
would the trade be legal, and at what lot size?*

Usage:
  python scripts/verify_sizing_live.py --symbol XAUUSD --stop-price 9.89
  python scripts/verify_sizing_live.py --symbol XAUUSD --stop-atr-mult 1.0
  python scripts/verify_sizing_live.py --symbol XAUUSD --preset path/to/x.set
  python scripts/verify_sizing_live.py --symbol XAUUSD --offline   # force the
                                                                  # terminal refusal

Read-only: it places no orders and imports no order-sending path. Exit codes:
0 = legal and armed, 1 = the rules refuse it, 2 = no stop distance given,
3 = the terminal could not be measured, 4 = legal but the arming switch is OFF.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from midas_prop.execution.prop_execution import (  # noqa: E402
    BEST_DAY_CAP_REACHED,
    BEST_DAY_HEADROOM,
    BEST_DAY_NO_PROFIT_YET,
    AccountState,
    ArmingGate,
    ContractSpec,
    GateCriteria,
    best_day_days_required,
    evaluate_trade,
    order_calc_profit_lots,
    size_like_ea,
    verify_against_broker,
)
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402
from set_chart_preset import parse_preset  # noqa: E402  (the certified preset parser)

ARTIFACT = ROOT / "artifacts" / "prop_sizing_verification.json"

#: Exit codes. `0` is placeable; `1` is the venue's rules refusing this trade; `4`
#: is legal-but-unarmed and is deliberately NOT `1`, because the two used to print
#: the same word and "the switch is off" was read as "the venue would refuse".
EXIT_PLACEABLE = 0
EXIT_RULES_REFUSE = 1
EXIT_NO_STOP = 2
EXIT_UNMEASURABLE = 3
EXIT_NOT_ARMED = 4


def verdict(legal: bool, armed: bool) -> str:
    """One word for (rules, arming) that cannot conflate them.

    ``legal`` comes from :func:`evaluate_trade` run WITHOUT an arming decision, so
    it means *the venue's own limits and the sizing arithmetic allow this trade*.
    Whether the system may actually send it is a second question with a second answer.
    """
    if not legal:
        return "BLOCKED"
    return "LEGAL_AND_ARMED" if armed else "LEGAL_BUT_NOT_ARMED"


def best_day_line(decision) -> str:
    """The allowance, and — the point — why it reads what it reads.

    Returns a sentence, never a bare number. `$0.00` on a flat account is not a
    refusal and must not be able to look like one sitting under a verdict.
    """
    allowance = decision.best_day_allowance_usd
    basis = decision.best_day_basis
    if basis == BEST_DAY_NO_PROFIT_YET:
        return ("remaining allowance $0.00 — NOT a refusal: no profit is banked "
                "yet, so the share is undefined at zero and the rule binds on the "
                "first profitable CLOSE, not on an entry")
    if basis == BEST_DAY_CAP_REACHED:
        return (f"remaining allowance $0.00 — today has reached its "
                f"${decision.day_profit_cap_usd:,.2f} ceiling, which IS a refusal "
                f"(no new entries today)")
    if basis != BEST_DAY_HEADROOM:
        raise ValueError(f"unknown Best Day basis {basis!r}")
    return (f"remaining allowance ${allowance:,.2f} of today's "
            f"${decision.day_profit_cap_usd:,.2f} ceiling")


def exit_code(legal: bool, armed: bool) -> int:
    """`1` only when the RULES refuse; `4` when nothing refuses but nothing may be sent."""
    if not legal:
        return EXIT_RULES_REFUSE
    return EXIT_PLACEABLE if armed else EXIT_NOT_ARMED


def refusal_lines(decision) -> list[str]:
    """What actually refused the trade, one line per reason, codes first."""
    out = [f"codes: {', '.join(decision.block_codes)}"] if decision.block_codes else []
    out.extend(decision.reasons)
    return out


def verdict_lines(decision, arming) -> list[str]:
    """The closing block: TWO labelled verdicts, and what to make of them.

    Pure so it can be pinned. The rule this exists to hold: a legal trade on an
    unarmed system must produce no `BLOCK` anywhere in its output, because nothing
    blocked it.
    """
    out = [f"legality        {'ALLOW' if decision.allowed else 'REFUSED'} — "
           + ("no venue rule refuses this trade at this size" if decision.allowed
              else "the venue's own limits refuse it:")]
    out += [f"                {line}" for line in refusal_lines(decision)]
    out.append(f"arming switch   {'ARMED' if arming.armed else 'OFF'}")
    out += [f"                {r}" for r in arming.reasons]
    out.append("")
    outcome = verdict(decision.allowed, arming.armed)
    if not decision.allowed:
        out.append(f"VERDICT: {outcome} ({exit_code(decision.allowed, arming.armed)})"
                   f" — the rules refuse this trade; it is not placeable at any size.")
    elif arming.armed:
        out.append(f"VERDICT: {outcome} ({exit_code(decision.allowed, arming.armed)})"
                   f" — legal and armed. This tool places nothing.")
    else:
        out.append(f"VERDICT: {outcome} ({exit_code(decision.allowed, arming.armed)})"
                   f" — NOTHING refuses this trade; the arming switch is what is")
        out.append("         off. A legal trade is not an armed system, and arming is a"
                   " record event")
        out.append("         (artifacts/live/armed.json), never an input edit.")
    return out


# --- the arm's own configured risk ----------------------------------------- #

#: The record that names the preset the arm runs. Its PRESENCE is what makes the arm's
#: configured risk knowable; its absence is reported, never guessed around.
ARM_RECORD = ROOT / "artifacts" / "live" / "armed.json"
PRESET_DIR = ROOT / "mql5" / "MIDASTOUCH"


def _rel(path: Path) -> str:
    """Repo-relative for readability, absolute when the path is outside the repo.

    `Path.relative_to` raises rather than degrading, and a caller passing a relative
    or temporary path is asking a legitimate question.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve_arm_preset(record: Path = ARM_RECORD, preset_dir: Path = PRESET_DIR,
                       override: str | None = None) -> tuple[Path | None, str]:
    """The preset the ARM runs, and where that answer came from.

    Returns ``(path, source)`` or ``(None, why_not)``. The arming record is the
    authority, because the preset it names IS the configuration the arm is meant to
    run — picking the paper preset instead would answer a question about a different
    configuration, which is the confusion this tool exists to avoid.
    """
    if override:
        p = Path(override)
        if not p.is_file():
            return None, f"--preset {override} does not exist"
        return p, "--preset"
    if not record.is_file():
        return None, (f"no arming record at {_rel(record)} names the preset "
                      f"the arm runs; pass --preset to say which one")
    try:
        rec = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{_rel(record)} is unreadable ({exc})"
    name = rec.get("preset")
    if not name:
        return None, f"{_rel(record)} names no preset"
    path = Path(preset_dir) / name
    if not path.is_file():
        return None, (f"the arming record names {name}, which is not in "
                      f"{_rel(Path(preset_dir))}")
    return path, f"named by {_rel(record)}"


def arm_risk_from_preset(vals: dict) -> tuple[tuple[float, float] | None, str]:
    """``(InpRiskPercent, InpMaxRiskPct)`` from a parsed preset, or ``(None, why)``.

    A preset whose risk inputs are missing is reported as unreadable rather than
    defaulted to the EA's repo defaults: the defaults are not what the arm runs.
    """
    out: list[float] = []
    for key in ("InpRiskPercent", "InpMaxRiskPct"):
        raw = vals.get(key)
        if raw is None:
            return None, f"{key} is not in the preset"
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return None, f"{key}={raw!r} is not a number"
        if v <= 0:
            return None, f"{key}={raw!r} is not positive"
        out.append(v)
    return (out[0], out[1]), ""


def sizing_lines(decision, ea, *, ea_source: str = "", ea_unavailable: str = "") -> list[str]:
    """The two sizes, each named, because they are answers to different questions.

    This tool sizes to the venue's DAILY LOSS LIMIT; the EA sizes to
    ``InpRiskPercent`` of equity. On 2026-09-21 those were 0.11 and 0.01 lots for the
    same stop width, and printing one number let the first be read as the size the arm
    would send. Either line may be absent, but neither can ever be unlabelled.
    """
    out: list[str] = []
    s = decision.sizing
    if s is not None and s.ok:
        out.append(f"size (this tool)  {s.lots:g} lots  risk ${s.risk_usd:,.2f}  "
                   f"budget ${s.budget_usd:,.2f}  ({s.budget_note})")
    else:
        out.append("size (this tool)  none — this tool's own sizing was refused "
                   "(see the reasons below)")

    if ea is None:
        out.append("size (the ARM)    UNAVAILABLE" + (f" — {ea_unavailable}"
                                                      if ea_unavailable else ""))
        return out
    if not ea.ok:
        out.append(f"size (the ARM)    REFUSED by the EA — {ea.note()}")
        return out

    out.append(f"size (the ARM)    {ea.lots:g} lots  risk ${ea.risk_usd:,.2f}  "
               f"budget ${ea.budget_usd:,.2f}"
               + (f"  (preset {ea_source})" if ea_source else ""))
    out.append(f"                  {ea.note()}")
    for w in ea.warnings:
        out.append(f"                  warn: {w}")
    out.append("                  different questions on purpose: this tool sizes to "
               "the venue's")
    out.append("                  daily loss limit, the EA sizes to InpRiskPercent of "
               "equity — the")
    out.append("                  arm's number is the one that will be sent.")
    return out


def decision_lines(decision) -> list[str]:
    """The decision's reasons and warnings — and NOT its sizing.

    The size and the Best Day allowance are printed above, each under its own label.
    Re-emitting them here (as ``TradeDecision.explain()`` does, correctly, for its own
    callers) is how one report ended up carrying the same dollars twice with only one
    of them labelled. Pinned: this function must never print a `lots` figure.
    """
    out = [f"decision        {'ALLOW' if decision.allowed else 'REFUSED'}"
           + (f" ({', '.join(decision.block_codes)})" if decision.block_codes else "")]
    out += [f"                BLOCKED: {r}" for r in decision.reasons]
    out += [f"                warn: {w}" for w in decision.warnings]
    return out


def _terminal():
    """Import MT5 and connect, or return (None, reason)."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None, "MetaTrader5 python module is not installed"
    if not mt5.initialize():
        return None, f"mt5.initialize() failed: code {mt5.last_error()}"
    return mt5, ""


def measure_basis(mt5, symbol: str, lot: float) -> tuple[float | None, dict]:
    """USD per 1.0 price-unit move on one lot, from the broker's own calculator.

    The +1.0 price move is deliberately large relative to a tick: a one-tick
    move on a minimum lot rounds to cents and would hide a 10x error, which is
    exactly the error this is here to catch.
    """
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None:
        return None, {"error": f"symbol {symbol} not found on this terminal"}
    if tick is None:
        return None, {"error": f"no tick for {symbol} (market closed?)"}

    price = float(tick.bid or tick.ask)
    raw = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, lot, price, price + 1.0)
    detail = {
        "price_used": price,
        "lot_used": lot,
        "order_calc_profit_raw": None if raw is None else float(raw),
        "volume_min": float(info.volume_min),
        "volume_max": float(info.volume_max),
        "volume_step": float(info.volume_step),
        "digits": int(info.digits),
        "trade_tick_size": float(info.trade_tick_size),
        "trade_tick_value": float(info.trade_tick_value),
        "trade_contract_size": float(info.trade_contract_size),
        "spread_points_now": int(info.spread),
        "trade_allowed": bool(info.trade_mode),
        "symbol_path": getattr(info, "path", ""),
        "symbol_description": getattr(info, "description", ""),
    }
    if raw is None:
        detail["error"] = (f"order_calc_profit returned None: {mt5.last_error()} "
                           f"-- not a basis, a measurement failure")
        return None, detail
    return order_calc_profit_lots(float(raw), price_move=1.0, lot_basis=lot), detail


def spec_implied_basis(detail: dict) -> float | None:
    """What the spec fields alone imply, for the disagreement report."""
    tick_size = detail.get("trade_tick_size") or 0.0
    tick_value = detail.get("trade_tick_value") or 0.0
    if tick_size <= 0 or tick_value <= 0:
        return None
    return tick_value / tick_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--stop-price", type=float, default=None,
                    help="stop distance in price units (e.g. 9.89 = 1 ATR M15)")
    ap.add_argument("--stop-atr-mult", type=float, default=None,
                    help="stop as a multiple of ATR, requires --atr-price")
    ap.add_argument("--atr-price", type=float, default=None,
                    help="ATR in price units, for --stop-atr-mult")
    ap.add_argument("--account-size", type=float, default=25_000.0)
    ap.add_argument("--safety-fraction", type=float, default=0.5)
    ap.add_argument("--equity", type=float, default=None,
                    help="override live equity (offline/dry analysis)")
    ap.add_argument("--balance", type=float, default=None)
    ap.add_argument("--today-profit", type=float, default=0.0)
    ap.add_argument("--other-day-profit", type=float, action="append", default=[],
                    help="repeat for each prior profitable day, for Best Day")
    ap.add_argument("--config-id", default="", help="the config the gate would arm")
    ap.add_argument("--preset", default=None,
                    help="the arm's preset, for the 'size the ARM would send' line. "
                         "Defaults to the preset named by the arming record.")
    ap.add_argument("--offline", action="store_true",
                    help="do not use the MT5 bridge at all; forces the "
                         "terminal-unavailable refusal (for machines with no "
                         "terminal, and for refusal-path checks)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rules = ThunderboltClassicRules(account_size=args.account_size)

    # --- stop distance ----------------------------------------------------- #
    stop = args.stop_price
    if stop is None and args.stop_atr_mult is not None and args.atr_price:
        stop = args.stop_atr_mult * args.atr_price
    if stop is None:
        print("refusing: give --stop-price, or --stop-atr-mult with --atr-price. "
              "Sizing without a stop distance is how a budget becomes a guess.",
              file=sys.stderr)
        return EXIT_NO_STOP

    report: dict = {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": args.symbol,
        "stop_distance_price": stop,
        "account_size": args.account_size,
        "safety_fraction": args.safety_fraction,
    }

    # --- live measurements -------------------------------------------------- #
    # NOTE --offline is not equivalent to an empty %APPDATA%. The MT5 python
    # bridge finds a RUNNING terminal independently of %APPDATA%, so pointing
    # APPDATA at an empty directory does NOT stop this script connecting --
    # measured 2026-09-19. --offline is the only way to force the refusal path.
    mt5, why = (None, "--offline was requested") if args.offline else _terminal()
    if mt5 is None:
        report["terminal"] = {"available": False, "reason": why}
        print(f"TERMINAL UNAVAILABLE: {why}", file=sys.stderr)
        print("Cannot verify sizing against the broker. Refusing to report a "
              "lot size from spec fields alone — that is the 10x error this "
              "script exists to catch.", file=sys.stderr)
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return EXIT_UNMEASURABLE

    try:
        acc = mt5.account_info()
        if acc is None:
            print(f"account_info() returned None: {mt5.last_error()}", file=sys.stderr)
            return EXIT_UNMEASURABLE
        equity = args.equity if args.equity is not None else float(acc.equity)
        balance = args.balance if args.balance is not None else float(acc.balance)
        report["account"] = {
            "login": int(acc.login), "server": acc.server, "currency": acc.currency,
            "equity": float(acc.equity), "balance": float(acc.balance),
            "leverage": int(acc.leverage), "margin_free": float(acc.margin_free),
        }

        info = mt5.symbol_info(args.symbol)
        min_lot = float(info.volume_min) if info is not None else 0.01
        basis_usd, detail = measure_basis(mt5, args.symbol, min_lot)
        report["basis_measurement"] = detail

        if basis_usd is None:
            report["verdict"] = "MEASUREMENT_FAILED"
            print(f"FAIL: could not measure a dollar basis for {args.symbol}", file=sys.stderr)
            ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return EXIT_UNMEASURABLE

        spec = ContractSpec(
            symbol=args.symbol,
            min_lot=min_lot,
            lot_step=float(info.volume_step),
            max_lot=float(info.volume_max),
            digits=int(info.digits),
            usd_per_unit_per_lot=basis_usd,
            basis="order_calc_profit",
            tick_value_field=float(info.trade_tick_value),
        )

        implied = spec_implied_basis(detail)
        if implied is not None:
            check = verify_against_broker(
                spec, broker_usd_per_unit_per_lot=implied)
            report["spec_vs_broker"] = {
                "spec_implied_usd_per_unit_per_lot": implied,
                "broker_measured_usd_per_unit_per_lot": basis_usd,
                "agrees": check.agrees,
                "factor": check.disagreement_factor,
                "detail": check.detail,
            }
    finally:
        mt5.shutdown()

    # --- rules -------------------------------------------------------------- #
    state = AccountState(
        equity=equity, balance=balance, peak_equity=max(equity, balance),
        today_profit=args.today_profit,
        other_days_profit=tuple(args.other_day_profit),
    )
    gate = ArmingGate(
        arm_path=ROOT / "artifacts" / "live" / "armed.json",
        validation_path=ROOT / "artifacts" / "live" / "validation_record.json",
        criteria=GateCriteria())
    arming = gate.evaluate()

    # Legality is the venue's rules and the sizing arithmetic, and NOTHING else.
    # The arming switch is a separate question with a separate verdict (below):
    # folding it in here is what made an unarmed-but-fine account print `BLOCK`.
    decision = evaluate_trade(
        rules, spec, state, stop_distance_price=stop,
        safety_fraction=args.safety_fraction, arming=None)

    report["spec"] = asdict(spec)
    report["state"] = asdict(state)
    report["legality"] = {
        "legal": decision.allowed,
        "block_codes": list(decision.block_codes),
        "reasons": list(decision.reasons),
        "warnings": list(decision.warnings),
        "sizing": asdict(decision.sizing) if decision.sizing else None,
    }
    report["best_day"] = {
        "allowance_usd": decision.best_day_allowance_usd,
        "day_ceiling_usd": decision.day_profit_cap_usd,
        "basis": decision.best_day_basis,
        "note": decision.best_day_note,
        "summary": best_day_line(decision),
    }
    report["arming"] = {"armed": arming.armed, "reasons": list(arming.reasons),
                        "record": str(ARM_RECORD)}

    # --- what the ARM would actually send ----------------------------------- #
    # A second, independent number: the EA's own arithmetic (InpRiskPercent of
    # equity), read from the preset the arming record names. Its whole job is to sit
    # beside the daily-limit size above, labelled, so neither can be taken for the
    # other -- they differ by ~10x on this account.
    arm_preset, arm_where = resolve_arm_preset(override=args.preset)
    ea = None
    ea_unavailable = ""
    arm_source = ""
    if arm_preset is None:
        ea_unavailable = arm_where
    else:
        preset_vals = parse_preset(str(arm_preset))
        risk_pair, why = arm_risk_from_preset(preset_vals)
        if risk_pair is None:
            ea_unavailable = f"{arm_preset.name}: {why}"
        else:
            ea = size_like_ea(
                spec, equity=equity, risk_percent=risk_pair[0],
                max_risk_pct=risk_pair[1], stop_distance_price=stop)
            live = str(preset_vals.get("InpLiveExecution", "")).strip().lower() in (
                "true", "1")
            arm_source = f"{arm_preset.name}, {arm_where}" + (
                "" if live else " — InpLiveExecution=false: the PAPER arm's size")
            report["arm_sizing"] = {
                "preset": str(arm_preset), "preset_source": arm_where,
                "live_execution": live, "arm_tag": preset_vals.get("InpArmTag", ""),
                "risk_percent": risk_pair[0], "max_risk_pct": risk_pair[1],
                "equity_basis": equity, "lots": ea.lots, "risk_usd": ea.risk_usd,
                "budget_usd": ea.budget_usd, "floored": ea.floored,
                "vetoed": ea.vetoed, "note": ea.note(),
                "warnings": list(ea.warnings)}
    if ea is None:
        report["arm_sizing"] = {
            "unavailable": ea_unavailable,
            "what_it_would_have_required": ("a file at artifacts/live/armed.json naming "
                                            "the preset the arm runs, or --preset")}
    report["rules"] = {
        "profit_target_usd": rules.profit_target_usd,
        "daily_loss_limit_usd": rules.daily_loss_limit_usd,
        "max_drawdown_usd": rules.max_drawdown_usd,
        "best_day_pct": rules.best_day_pct,
        "best_day_days_required": best_day_days_required(rules),
    }
    outcome = verdict(decision.allowed, arming.armed)
    report["verdict"] = outcome
    report["exit_code"] = exit_code(decision.allowed, arming.armed)

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"=== SIZING VERIFICATION — {args.symbol} @ "
              f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} ===")
        print(f"account      {report['account']['login']} @ "
              f"{report['account']['server']}  {report['account']['currency']}")
        print(f"                 equity ${equity:,.2f}  balance ${balance:,.2f}")
        print(f"measured basis  ${basis_usd:,.4f} per 1.0 price unit per 1.0 lot "
              f"(order_calc_profit, {min_lot:g} lot x 1.0 move = "
              f"{detail['order_calc_profit_raw']:,.2f})")
        if implied is not None:
            c = report["spec_vs_broker"]
            flag = "agrees" if c["agrees"] else f"DISAGREES {c['factor']:.2f}x"
            print(f"spec fields     imply ${implied:,.4f} -> {flag}")
            if not c["agrees"]:
                print(f"                {c['detail']}")
        print(f"stop distance   {stop:g} price units")
        print(f"daily limit     ${rules.daily_loss_limit_usd:,.2f}  "
              f"shield ${rules.max_drawdown_usd:,.2f}  (floor "
              f"${rules.drawdown_floor_usd(state.peak_equity):,.2f})")
        print(f"best-day        {rules.best_day_pct:g}% share cap; the "
              f"{rules.profit_target_pct:g}% target needs >= "
              f"{best_day_days_required(rules)} profitable days")
        print(f"                {best_day_line(decision)}")
        print()
        for line in sizing_lines(decision, ea, ea_source=arm_source,
                                 ea_unavailable=ea_unavailable):
            print(line)
        print()
        for line in decision_lines(decision):
            print(line)
        print()

        # --- two verdicts, each labelled, so neither can be read as the other -- #
        for line in verdict_lines(decision, arming):
            print(line)
        print(f"artifact -> {ARTIFACT}")

    # Non-zero when the trade is not placeable, so this can gate a pipeline --
    # with 1 (rules refuse) and 4 (legal, not armed) kept apart.
    return exit_code(decision.allowed, arming.armed)


if __name__ == "__main__":
    raise SystemExit(main())

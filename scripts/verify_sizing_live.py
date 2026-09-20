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

Usage:
  python scripts/verify_sizing_live.py --symbol XAUUSD --stop-price 9.89
  python scripts/verify_sizing_live.py --symbol XAUUSD --stop-atr-mult 1.0
  python scripts/verify_sizing_live.py --symbol XAUUSD --live-basis   # actually
                                                                    # place nothing

Read-only: it places no orders and imports no order-sending path.
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

from synthetic_trader.execution.prop_execution import (  # noqa: E402
    AccountState,
    ArmingGate,
    ContractSpec,
    GateCriteria,
    best_day_days_required,
    evaluate_trade,
    order_calc_profit_lots,
    verify_against_broker,
)
from synthetic_trader.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

ARTIFACT = ROOT / "artifacts" / "prop_sizing_verification.json"


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
        return 2

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
        return 3

    try:
        acc = mt5.account_info()
        if acc is None:
            print(f"account_info() returned None: {mt5.last_error()}", file=sys.stderr)
            return 3
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
            return 3

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

    decision = evaluate_trade(
        rules, spec, state, stop_distance_price=stop,
        safety_fraction=args.safety_fraction, arming=arming)

    report["spec"] = asdict(spec)
    report["state"] = asdict(state)
    report["decision"] = {
        "allowed": decision.allowed,
        "block_codes": list(decision.block_codes),
        "reasons": list(decision.reasons),
        "warnings": list(decision.warnings),
        "best_day_allowance_usd": decision.best_day_allowance_usd,
        "sizing": asdict(decision.sizing) if decision.sizing else None,
    }
    report["arming"] = {"armed": arming.armed, "reasons": list(arming.reasons)}
    report["rules"] = {
        "profit_target_usd": rules.profit_target_usd,
        "daily_loss_limit_usd": rules.daily_loss_limit_usd,
        "max_drawdown_usd": rules.max_drawdown_usd,
        "best_day_pct": rules.best_day_pct,
        "best_day_days_required": best_day_days_required(rules),
    }
    report["verdict"] = "LEGAL_BUT_NOT_ARMED" if decision.allowed else "BLOCKED"

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
        print(f"best-day        {rules.best_day_pct:g}% cap; needs >= "
              f"{best_day_days_required(rules)} profitable days; today's "
              f"remaining allowance ${decision.best_day_allowance_usd:,.2f}")
        print()
        print(decision.explain())
        print()
        if decision.allowed:
            print(f"VERDICT: LEGAL — but the arming switch is OFF.")
            print("         A legal trade is not an armed system. Arming needs a "
                  "PASS walk-forward record; see docs/PROP_EXECUTION_LAYER.md.")
        else:
            print("VERDICT: BLOCKED")
        print(f"artifact -> {ARTIFACT}")

    # Non-zero when the trade is not placeable, so this can gate a pipeline.
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())

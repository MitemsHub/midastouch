#!/usr/bin/env python3
"""Supervised paper trading: the execution layer, live prices, simulated fills.

WHAT THIS IS FOR. Every part of the execution layer — cost-aware sizing, the venue
rules, the day ledger's loss and profit stops, the arming gate — has been tested as
arithmetic. None of it has been exercised against a real market, because there is no
validated strategy to arm and the funded account should not be the test harness.
This closes that gap: it runs the whole layer on live Upcomers prices, fills
simulated positions with the SAME tie-breaking the research harness uses, and
persists its state so a restart resumes where it stopped.

WHAT IT DELIBERATELY DOES NOT DO. **It sends no orders.** There is no order-sending
path in this file, and none is imported; the only thing that moves is
`PaperAccount.balance`, which never leaves the state file. It also does not claim an
edge: the entry source is a placeholder (`--source random`, seeded so a run
reproduces) or an operator-supplied queue (`--source queue`). The point is to
exercise the plumbing daily, not to discover alpha.

THE ONE DESIGN DECISION WORTH ARGUING ABOUT. Paper mode runs **without requiring the
arming switch** — that is the entire point, since arming requires a PASS record and
nothing has one. But it is never allowed to *look* armed: the arming state is
printed on every run, written into the state file, and `--require-arming` turns the
gate back into a hard block so the same runner can be used as the live rehearsal the
day something does pass.

    python scripts/paper_trader.py --once                 # one supervised step
    python scripts/paper_trader.py --steps 200            # catch up over recent bars
    python scripts/paper_trader.py --once --dry-run       # decide, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from gold_walkforward import ATR_PERIOD, wilder_atr  # noqa: E402
from midas_prop.execution.paper_broker import (  # noqa: E402
    CostModel,
    PaperAccount,
    SimPosition,
)
from midas_prop.execution.prop_execution import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    AccountState,
    ArmingGate,
    ContractSpec,
    DailyStopConfig,
    GateCriteria,
    HaltReason,
    evaluate_trade,
    order_calc_profit_lots,
    resolve_day_ledger,
)
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

STATE_PATH = ROOT / "artifacts" / "live" / "paper_state.json"
LEDGER_PATH = ROOT / DEFAULT_LEDGER_PATH
QUEUE_PATH = ROOT / "artifacts" / "live" / "paper_signals.json"
M15_SEC = 900


def _utc(ts: int) -> str:
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds")


def _connect():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None, "MetaTrader5 python module is not installed"
    if not mt5.initialize():
        return None, f"mt5.initialize() failed: code {mt5.last_error()}"
    return mt5, ""


def _load_state() -> dict:
    if not STATE_PATH.is_file():
        return {"last_bar_ts": 0, "account": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"REFUSING: paper state at {STATE_PATH} is unreadable ({exc}). Starting "
            f"fresh would forget the open position and the day's realised P&L, which "
            f"is the failure this file exists to prevent. Repair or move it.")


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _queue_pop() -> list[dict]:
    """Candidate entries an emitter left for us. Absent queue means no signals."""
    if not QUEUE_PATH.is_file():
        return []
    try:
        raw = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"REFUSING: signal queue at {QUEUE_PATH} is unreadable "
                         f"({exc}); ignoring it would silently trade nothing.")
    return raw.get("signals", []) if isinstance(raw, dict) else list(raw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=400)
    ap.add_argument("--steps", type=int, default=1)
    ap.add_argument("--once", action="store_true", help="one supervised step")
    ap.add_argument("--source", choices=("random", "queue"), default="random")
    ap.add_argument("--seed", type=int, default=20260919)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--stop-atr-mult", type=float, default=2.0)
    ap.add_argument("--account-size", type=float, default=25_000.0)
    ap.add_argument("--safety-fraction", type=float, default=0.5)
    ap.add_argument("--require-arming", action="store_true",
                    help="treat the arming gate as a hard block (live rehearsal)")
    ap.add_argument("--dry-run", action="store_true", help="decide, write nothing")
    ap.add_argument("--seed-balance", type=float, default=25_000.0)
    args = ap.parse_args(argv)
    steps = 1 if args.once else max(1, args.steps)

    rules = ThunderboltClassicRules(account_size=args.account_size)
    stops = DailyStopConfig()

    print(f"=== PAPER TRADER (simulated fills, NO ORDERS SENT) — "
          f"{args.symbol} @ {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} ===")
    print(f"stop {args.stop_atr_mult:g} x ATR{ATR_PERIOD}   rr {args.rr:g}   "
          f"safety {args.safety_fraction:g}   source {args.source}")

    mt5, why = _connect()
    if mt5 is None:
        print(f"TERMINAL UNAVAILABLE: {why}", file=sys.stderr)
        print("Refusing: paper fills from a stale price is a fabricated result.",
              file=sys.stderr)
        return 3

    try:
        rates = mt5.copy_rates_from_pos(args.symbol, mt5.TIMEFRAME_M15, 0, args.bars)
        if rates is None or len(rates) < 60:
            print(f"no usable {args.symbol} M15 history "
                  f"({0 if rates is None else len(rates)} bars)", file=sys.stderr)
            return 3
        # Drop the forming bar: its high/low are not final, and filling a stop on
        # a bar that has not closed is how a paper account invents an edge.
        rates = rates[:-1]
        ts = [int(r["time"]) for r in rates]
        high = [float(r["high"]) for r in rates]
        low = [float(r["low"]) for r in rates]
        close = [float(r["close"]) for r in rates]
        open_ = [float(r["open"]) for r in rates]

        info = mt5.symbol_info(args.symbol)
        tick = mt5.symbol_info_tick(args.symbol)
        acc = mt5.account_info()
        if info is None or acc is None:
            print("symbol_info/account_info unavailable", file=sys.stderr)
            return 3

        # --- the dollar basis, measured, never assumed --------------------- #
        price = float(tick.bid or tick.ask) if tick else close[-1]
        lot = float(info.volume_min)
        raw = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, args.symbol, lot, price,
                                    price + 1.0)
        if raw is None:
            print(f"REFUSING: order_calc_profit returned None ({mt5.last_error()}); "
                  f"sizing on spec fields is the 10x error this layer exists to "
                  f"catch.", file=sys.stderr)
            return 3
        basis = order_calc_profit_lots(float(raw), price_move=1.0, lot_basis=lot)
        equity, balance = float(acc.equity), float(acc.balance)
        print(f"account {int(acc.login)} @ {acc.server}  equity ${equity:,.2f}  "
              f"balance ${balance:,.2f}")
        print(f"measured basis ${basis:,.4f}/unit/lot (order_calc_profit)   "
              f"min lot {lot:g}")
    finally:
        mt5.shutdown()

    atr = wilder_atr(high, low, close, ATR_PERIOD)

    # --- the day ledger, and the arming gate (reported, not bypassed) ------- #
    today = datetime.now(timezone.utc).date().isoformat()
    broker_today = 0.0  # no live positions exist; nothing realised by the venue
    ledger, notes = resolve_day_ledger(
        rules, ledger_path=LEDGER_PATH, today=today,
        broker_realised_usd=broker_today,
        starting_equity=equity, starting_balance=balance, stops=stops)
    for n in notes:
        print(f"  ledger: {n}")
    gate = ArmingGate(arm_path=ROOT / "artifacts" / "live" / "armed.json",
                      validation_path=ROOT / "artifacts" / "live" /
                      "validation_record.json",
                      criteria=GateCriteria())
    arming = gate.evaluate()
    print(f"  arming: {'ARMED' if arming.armed else 'OFF'} — "
          f"{arming.reasons[0] if arming.reasons else 'no reason given'}")
    per_trade = 0.5 * rules.daily_loss_limit_usd  # size_position default budget
    attempts = stops.attempts_allowed(rules, per_trade)
    print(f"  day stops: loss ${stops.loss_stop_usd(rules):,.2f}   "
          f"profit ${stops.profit_stop_for(rules):,.2f}   "
          f"halted={ledger.halted}")
    single_shot = attempts <= 1.05
    label = ("SINGLE-SHOT DAY - the stop is at or below one trade's risk, so the "
             "first loss ends the day" if single_shot else "ok")
    print(f"  attempts allowed: {attempts:.2f} full-size losing trades before the "
          f"day stops ({label})")
    if single_shot:
        print(f"    note: the venue limit would permit "
              f"{rules.daily_loss_limit_usd / per_trade:.2f}; set "
              f"DailyStopConfig(loss_stop_fraction=...) above "
              f"{per_trade / rules.daily_loss_limit_usd:.2f} to allow more than one "
              f"attempt, or accept a one-trade day deliberately.")

    # --- state ------------------------------------------------------------- #
    state = _load_state()
    if state.get("account"):
        account = PaperAccount.restore(state["account"],
                                       CostModel(usd_per_unit_per_lot=basis))
        print(f"  restored: balance ${account.balance:,.2f}, "
              f"{len(account.closed)} closed fills, "
              f"open={'yes' if account.position else 'no'}")
    else:
        account = PaperAccount(starting_balance=args.seed_balance,
                               cost_model=CostModel(usd_per_unit_per_lot=basis))
    if account.cost_model.usd_per_unit_per_lot != basis:
        account.cost_model = CostModel(usd_per_unit_per_lot=basis)

    spec = ContractSpec(symbol=args.symbol, min_lot=lot,
                        lot_step=float(info.volume_step),
                        max_lot=float(info.volume_max), digits=int(info.digits),
                        usd_per_unit_per_lot=basis, basis="order_calc_profit",
                        tick_value_field=float(info.trade_tick_value))

    # --- the step loop ------------------------------------------------------ #
    start = max(0, len(ts) - steps)
    last_bar = int(state.get("last_bar_ts", 0))
    rng = random.Random(args.seed)
    queue = _queue_pop() if args.source == "queue" else []
    decisions: list[dict] = []

    for i in range(start, len(ts)):
        if ts[i] <= last_bar and account.position is None:
            continue
        # 1. settle an open position on this bar, with the harness tie rule
        if account.position is not None:
            fill = account.on_bar(high=high[i], low=low[i], close=close[i],
                                  open_=open_[i], ts=ts[i], ts_utc=_utc(ts[i]))
            if fill is not None:
                print(f"  [{_utc(ts[i])}] CLOSE {fill.exit_reason:<10} "
                      f"{fill.lots:g} lots @ {fill.exit:,.2f}  "
                      f"net ${fill.net_usd:+,.2f} ({fill.net_r:+.2f}R)")
                decisions.append({"utc": _utc(ts[i]), "action": "close",
                                  "reason": fill.exit_reason,
                                  "net_usd": fill.net_usd, "net_r": fill.net_r})
                ledger.realised_usd += fill.net_usd
                # The same two stops the pre-trade gate enforces, applied to the
                # running result: once either is crossed, no further entry is
                # taken today.
                if not ledger.halted:
                    if ledger.realised_usd <= -stops.loss_stop_usd(rules):
                        ledger.halted = True
                        ledger.halt_reason = HaltReason.DAILY_LOSS_STOP
                        ledger.halted_at_utc = _utc(ts[i])
                        print(f"  [{_utc(ts[i])}] HALT: daily loss stop "
                              f"(${ledger.realised_usd:+,.2f})")
                    elif ledger.realised_usd >= stops.profit_stop_for(rules):
                        ledger.halted = True
                        ledger.halt_reason = HaltReason.DAY_PROFIT_STOP
                        ledger.halted_at_utc = _utc(ts[i])
                        print(f"  [{_utc(ts[i])}] HALT: day profit stop "
                              f"(${ledger.realised_usd:+,.2f})")
        # 2. consider an entry
        # NOTE no `i + 1 < len(ts)` guard here, unlike the backtest harness. The
        # harness needs a following bar because it must close the trade inside the
        # same pass; a live runner must NOT, because the real exit arrives on a
        # later bar and is resolved by the next supervised step. Requiring a
        # following bar made `--once` structurally unable to ever open a position.
        if account.position is None:
            a = float(atr[i])
            if a > 0:
                direction = 0
                if args.source == "queue" and queue:
                    direction = int(queue[0].get("direction", 0))
                elif args.source == "random":
                    rng.seed(args.seed + ts[i])
                    direction = rng.choice((1, -1))
                if direction:
                    stop_dist = args.stop_atr_mult * a
                    state_now = AccountState(
                        equity=account.equity(close[i]),
                        balance=account.balance,
                        peak_equity=max(account.balance, equity),
                        today_profit=ledger.realised_usd,
                        other_days_profit=())
                    decision = evaluate_trade(
                        rules, spec, state_now, stop_distance_price=stop_dist,
                        safety_fraction=args.safety_fraction,
                        arming=arming if args.require_arming else None,
                        ledger=ledger, daily_stops=stops)
                    codes = list(decision.block_codes)
                    if not args.require_arming:
                        codes = [c for c in codes if c != "not_armed"]
                    if decision.sizing and decision.sizing.ok and not codes:
                        entry = close[i]
                        pos = SimPosition(
                            direction=direction, lots=decision.sizing.lots,
                            entry=entry,
                            stop=entry - direction * stop_dist,
                            target=entry + direction * args.rr * stop_dist,
                            risk_usd=decision.sizing.risk_usd,
                            opened_utc=_utc(ts[i]), entry_bar_ts=ts[i])
                        account.open(pos)
                        ledger.entries += 1
                        if args.source == "queue" and queue:
                            queue.pop(0)
                        print(f"  [{_utc(ts[i])}] OPEN  {'long ' if direction > 0 else 'short'} "
                              f"{pos.lots:g} lots @ {entry:,.2f}  stop {pos.stop:,.2f}  "
                              f"target {pos.target:,.2f}  risk ${pos.risk_usd:,.2f}")
                        decisions.append({"utc": _utc(ts[i]), "action": "open",
                                          "direction": direction,
                                          "lots": pos.lots,
                                          "risk_usd": pos.risk_usd})
                    else:
                        why_blocked = decision.reasons[:1]
                        decisions.append({"utc": _utc(ts[i]), "action": "block",
                                          "codes": codes,
                                          "reason": why_blocked[0] if why_blocked
                                          else "sizing refused"})
        last_bar = max(last_bar, ts[i])

    # --- persist ------------------------------------------------------------ #
    summary = {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": args.symbol,
        "paper": True,
        "armed": arming.armed,
        "dry_run": args.dry_run,
        "measured_basis_usd_per_unit_per_lot": basis,
        "rules": {"daily_limit_usd": rules.daily_loss_limit_usd,
                  "loss_stop_usd": stops.loss_stop_usd(rules),
                  "profit_stop_usd": stops.profit_stop_for(rules)},
        "ledger": asdict(ledger),
        "account": account.snapshot(),
        "decisions": decisions,
        "runs": int(state.get("runs", 0)) + 1,
    }

    print()
    print(f"  balance ${account.balance:,.2f}   open "
          f"{'yes' if account.position else 'no'}   fills {len(account.closed)}   "
          f"realised today ${ledger.realised_usd:+,.2f}")
    print(f"  decisions this step: {len(decisions)} "
          f"({sum(1 for d in decisions if d['action'] == 'block')} blocked, "
          f"{sum(1 for d in decisions if d['action'] == 'open')} opened, "
          f"{sum(1 for d in decisions if d['action'] == 'close')} closed)")

    if args.dry_run:
        print("  --dry-run: nothing written. State and ledger left untouched.")
        return 0

    _save_json(STATE_PATH, {"last_bar_ts": last_bar, "account": account.snapshot(),
                            "runs": summary["runs"], "armed": arming.armed,
                            "summary": summary})
    ledger.save(LEDGER_PATH)
    print(f"  wrote {STATE_PATH}")
    print(f"  wrote {LEDGER_PATH} (day stop state survives a restart)")
    print("\nPAPER ONLY: no order was sent. Sizing, the day stops and the arming "
          "gate were exercised against live prices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

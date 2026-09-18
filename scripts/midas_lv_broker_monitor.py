#!/usr/bin/env python3
"""Broker-evidence-only LV monitor (VPS era, 2026-09-18).

While MT5 Virtual Hosting hosts the LV live EA, its ledger writes live on
the VPS — the LOCAL ledger is frozen and no local file can show what the
account is doing. The MT5 python API sees the ACCOUNT wherever the EA
executes, so this monitor polls and records:

  * equity / balance (any movement — including the 2026-09-18 12:25:59Z
    −$10.14 withdrawal that had NO trade attached);
  * open positions filtered to magic 7801601 (the LV arm) — direction,
    volume, entry, SL/TP, open epoch;
  * deals filtered to magic 7801601 (entries AND exits, profit attached);
  * account-level balance operations (type != BUY/SELL) regardless of
    magic — money movement is account evidence, not arm evidence.

Output: artifacts/midas_lv_broker_state.json — a snapshot consumed by
morning status [3b]. The monitor NEVER writes to the LV ledger (that file
is the EA's artifact; reconciliation is a separately registered step).
Pure state-building lives in build_state() so tests pin the attribution
rules without touching MT5.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts"
STATE_PATH = ART / "midas_lv_broker_state.json"
LV_MAGIC = 7801601
SYMBOL = "XAUUSDmicro"
DEAL_RING = 50
BALOP_RING = 20
DEAL_LOOKBACK_H = 24          # deals window per poll (dedup by ticket)
FRESH_S = 300                 # [3b] treats a snapshot older than this as stale


def build_state(acct, positions, deals, prev: dict, now_epoch: float,
                terminal=None) -> dict:
    """Pure snapshot builder. acct/positions/deals are attribute-bearing
    objects (mt5 types or test namespaces); prev is the prior snapshot.
    terminal is mt5.terminal_info() (or a test namespace) when available.

    Go-live sentinel (2026-09-18): terminal.trade_allowed is the global
    AutoTrading switch. When it is False the terminal refuses EVERY EA
    order silently — no journal line, no order error, nothing. The LV
    stand-down of 2026-09-18 08:36→17:39 UTC was exactly this. So the
    switch state is recorded on every snapshot (algo_trading) and a
    False is surfaced as a problem entry that morning status [3b] must
    show. None (API gave no terminal info) is recorded as None.

    Attribution rules (pinned by tests):
      * positions/deals enter ONLY with magic == LV_MAGIC;
      * balance operations (deal type not BUY/SELL) enter REGARDLESS of
        magic — they are account-level money movement;
      * deals are deduped by ticket against the prior ring;
      * first_fill_seen is set on the first ENTRY deal and never unset.
    """
    prev_deals = {d["ticket"] for d in prev.get("deals", [])}
    new_deals = []
    for d in deals:
        if getattr(d, "magic", 0) != LV_MAGIC:
            continue
        rec = {"ticket": int(getattr(d, "ticket", 0)),
               "entry": int(getattr(d, "entry", -1)),     # 0=IN, 1=OUT
               "type": int(getattr(d, "type", -1)),       # 0=BUY, 1=SELL
               "volume": float(getattr(d, "volume", 0.0)),
               "price": float(getattr(d, "price", 0.0) or 0.0),
               "profit": float(getattr(d, "profit", 0.0)),
               "commission": float(getattr(d, "commission", 0.0)),
               "position_id": int(getattr(d, "position_id", 0)),
               "epoch": float(getattr(d, "time", 0.0)),
               "comment": str(getattr(d, "comment", "") or "")}
        if rec["ticket"] in prev_deals:
            continue
        new_deals.append(rec)
    deals_ring = (prev.get("deals", []) + new_deals)[-DEAL_RING:]

    balops = list(prev.get("balance_ops", []))
    for d in deals:
        if int(getattr(d, "type", 0)) in (0, 1):
            continue                      # real trade deals, already handled
        rec = {"ticket": int(getattr(d, "ticket", 0)),
               "amount": float(getattr(d, "profit", 0.0)),
               "epoch": float(getattr(d, "time", 0.0)),
               "comment": str(getattr(d, "comment", "") or "")}
        if rec not in balops:
            balops.append(rec)
    balops = balops[-BALOP_RING:]

    positions_out = []
    for p in positions:
        if getattr(p, "magic", 0) != LV_MAGIC:
            continue
        positions_out.append({
            "ticket": int(getattr(p, "ticket", 0)),
            "dir": 1 if int(getattr(p, "type", 0)) == 0 else -1,
            "volume": float(getattr(p, "volume", 0.0)),
            "entry": float(getattr(p, "price_open", 0.0)),
            "sl": float(getattr(p, "sl", 0.0)),
            "tp": float(getattr(p, "tp", 0.0)),
            "epoch": float(getattr(p, "time", 0.0)),
            "comment": str(getattr(p, "comment", "") or "")})

    first_fill = prev.get("first_fill_seen")
    if first_fill is None and any(d["entry"] == 0 for d in deals_ring):
        first_fill = min(d["epoch"] for d in deals_ring if d["entry"] == 0)

    algo = None
    problems = []
    if terminal is not None:
        algo = bool(getattr(terminal, "trade_allowed", None))
        if algo is False:
            problems.append(
                "ALGOTRADING_OFF: terminal AutoTrading switch is disabled — "
                "MT5 refuses every EA order silently (2026-09-18 08:36-17:39Z "
                "stand-down class). Re-enable the toolbar AutoTrading button.")

    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ts_epoch": now_epoch,
            "account": int(getattr(acct, "login", 0)),
            "equity": float(getattr(acct, "equity", 0.0)),
            "balance": float(getattr(acct, "balance", 0.0)),
            "margin": float(getattr(acct, "margin", 0.0)),
            "algo_trading": algo,
            "positions": positions_out,
            "deals": deals_ring,
            "balance_ops": balops,
            "first_fill_seen": first_fill,
            "problems": problems}


def poll_once() -> dict:
    """Collect from the MT5 API and merge into the state file. Keeps the
    prior snapshot on any collection failure (problems recorded)."""
    import MetaTrader5 as mt5

    prev: dict = {}
    if STATE_PATH.exists():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = {}
    now_epoch = time.time()
    if not mt5.initialize():
        state = dict(prev)
        state.setdefault("problems", []).append(
            f"mt5.initialize failed at {datetime.now(timezone.utc):%H:%M:%S}Z")
        state["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["ts_epoch"] = now_epoch
        _save(state)
        return state
    try:
        acct = mt5.account_info()
        _ti = getattr(mt5, "terminal_info", None)
        terminal = _ti() if callable(_ti) else None
        positions = mt5.positions_get(symbol=SYMBOL) or []
        since = datetime.fromtimestamp(
            now_epoch - DEAL_LOOKBACK_H * 3600, tz=timezone.utc)
        until = datetime.fromtimestamp(now_epoch + 300, tz=timezone.utc)
        deals = mt5.history_deals_get(since, until) or []
        state = build_state(acct, positions, deals, prev, now_epoch,
                            terminal=terminal)
        _save(state)
        return state
    finally:
        mt5.shutdown()


def _save(state: dict) -> None:
    ART.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Broker-evidence LV monitor (VPS era)")
    ap.add_argument("--loop", type=int, default=0,
                    help="poll every N seconds instead of once")
    ap.add_argument("--once", action="store_true", help="single poll and exit")
    args = ap.parse_args()
    if args.loop or not args.once:
        interval = args.loop or 60
        while True:
            s = poll_once()
            print(json.dumps({"ts": s["ts"], "equity": s.get("equity"),
                              "algo_trading": s.get("algo_trading"),
                              "positions": len(s.get("positions", [])),
                              "deals_new": len(s.get("deals", [])),
                              "problems": s.get("problems")}), flush=True)
            time.sleep(interval)
    s = poll_once()
    print(json.dumps({"ts": s["ts"], "equity": s.get("equity"),
                      "algo_trading": s.get("algo_trading"),
                      "positions": len(s.get("positions", [])),
                      "problems": s.get("problems")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
sys.path.insert(0, str(REPO / "scripts"))

import mt5_ops as _ops                        # noqa: E402  (whose-deal-is-this, one rule)

ART = REPO / "artifacts"
STATE_PATH = ART / "midas_lv_broker_state.json"
LV_MAGIC = 7801601
SYMBOL = "XAUUSDmicro"
DEAL_RING = 50
BALOP_RING = 20
DEAL_LOOKBACK_H = 24          # deals window per poll (dedup by ticket)
FRESH_S = 300                 # [3b] treats a snapshot older than this as stale


def build_state(acct, positions, deals, prev: dict, now_epoch: float,
                terminal=None, vps_era: bool | None = None) -> dict:
    """Pure snapshot builder. acct/positions/deals are attribute-bearing
    objects (mt5 types or test namespaces); prev is the prior snapshot.
    terminal is mt5.terminal_info() (or a test namespace) when available.
    vps_era: whether MT5 Virtual Hosting hosts the LV surface (None =
    unknown → no era-conditional alerting).

    AutoTrading sentinel (2026-09-18, era-aware after the migration):
    terminal.trade_allowed is the LOCAL terminal's global AutoTrading
    switch, and its safe state depends on the era:
      * pre-VPS era: False silently refuses every EA order (the 08:36→17:39Z
        stand-down) → ALGOTRADING_OFF problem;
      * VPS era (2026-09-18 12:46Z migration): the LV EA executes on the
        VPS with its own switch, and a LOCAL switch left ON races the SAME
        signal — the 18:45:01Z netting double-entry hazard (the three
        retcode=10027 rejects were the only thing that prevented a merged
        0.2-lot position). True is the hazard → LOCAL_ALGOTRADING_ON_
        DURING_VPS problem; False is the registered-safe state.
    None (API gave no terminal info) is recorded as None, no alert.

    Attribution rules (pinned by tests):
      * positions/deals enter ONLY with magic == LV_MAGIC;
      * balance operations (deal type not BUY/SELL) enter REGARDLESS of
        magic — they are account-level money movement;
      * deals are deduped by ticket against the prior ring;
      * first_fill_seen is set on the first ENTRY deal and never unset.
    """
    prev_deals = {d["ticket"] for d in prev.get("deals", [])}
    new_deals = []
    # ATTRIBUTION BY POSITION (`mt5_ops.attribute_deal`, the one rule). Filtering on
    # `getattr(d, "magic", 0) != LV_MAGIC` lost the CLOSE of the arm's own position whenever the venue
    # stamped it with magic 0 — MEASURED 2026-09-22 on the gold arm, and this monitor reads the SAME
    # venue. A broker-evidence monitor that cannot see the close is evidence of a position that never
    # ended: `first_fill_seen` and the ring would both say "still open" for a trade the venue closed.
    ours_positions = _ops.our_positions_from_deals(deals, LV_MAGIC)
    by_position: list[int] = []
    for d in deals:
        how = _ops.attribute_deal(d, LV_MAGIC, ours_positions)
        if how is None:
            continue
        if how == _ops.DEAL_BY_POSITION:
            by_position.append(int(getattr(d, "ticket", 0)))
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
        if algo is False and not vps_era:
            problems.append(
                "ALGOTRADING_OFF: terminal AutoTrading switch is disabled — "
                "MT5 refuses every EA order silently (2026-09-18 08:36-17:39Z "
                "stand-down class). Re-enable the toolbar AutoTrading button.")
        elif algo is True and vps_era:
            problems.append(
                "LOCAL_ALGOTRADING_ON_DURING_VPS: the LV surface executes on "
                "the VPS; a local AutoTrading-ON instance races the same "
                "signal (2026-09-18 18:45Z netting double-entry hazard). "
                "Disable the local toolbar AutoTrading button.")

    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ts_epoch": now_epoch,
            "account": int(getattr(acct, "login", 0)),
            "equity": float(getattr(acct, "equity", 0.0)),
            "balance": float(getattr(acct, "balance", 0.0)),
            "margin": float(getattr(acct, "margin", 0.0)),
            "algo_trading": algo,
            "positions": positions_out,
            "deals": deals_ring,
            "deals_attributed_by_position": by_position,
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
        try:
            from midas_watchdog import vps_hosting_active
            vps_era = bool(vps_hosting_active())
        except Exception:
            vps_era = None
        state = build_state(acct, positions, deals, prev, now_epoch,
                            terminal=terminal, vps_era=vps_era)
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

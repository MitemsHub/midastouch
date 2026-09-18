#!/usr/bin/env python3
"""Blind 90-day A/B test of the two deployed V75 paper arms.

The script is deliberately read-only with respect to MT5: it calls only
``copy_rates_*`` and never sends orders. Both terminal feeds are captured,
compared bar-for-bar, and the test aborts if their historical price paths do
not agree. The existing certification harness then runs once per fixed arm:
TP 1.8 / magic 7788075 and TP 2.4 / magic 7788100. The post-fix run
uses the v26.36 standard-path micro-fit and the broker's captured V75 stop
floor in its explicit certification environment.

The test window ends at the latest closed M15 bar available from both
terminals and starts exactly 90 days earlier. Seven days of pre-window bars are
also captured as indicator/GARCH burn-in; only trades inside the registered
90-day window count in the reports.

Usage:
  python scripts/blind_test_two_terminals.py
  python scripts/blind_test_two_terminals.py --start 2026-06-07T00:00:00+00:00 \
      --end 2026-09-05T23:59:59+00:00
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "v75_blind90"
OUT = DEFAULT_OUT
SYMBOL = "Volatility 75 Index"
DEFAULT_A = Path(r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe")
DEFAULT_B = Path(r"C:\Users\USER\AppData\Local\MitemshubMT5_B\terminal64.exe")
WARMUP = timedelta(days=7)
TIME_COLUMNS = ("time", "open", "high", "low", "close", "tick_volume")


def parse_dt(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def connect(exe: Path):
    import MetaTrader5 as mt5

    if not exe.exists():
        raise RuntimeError(f"terminal executable not found: {exe}")
    if not mt5.initialize(path=str(exe)):
        raise RuntimeError(f"MT5 initialize failed for {exe}: {mt5.last_error()}")
    info = mt5.terminal_info()
    if info is None:
        mt5.shutdown()
        raise RuntimeError(f"MT5 terminal info unavailable for {exe}: {mt5.last_error()}")
    return mt5, info


def latest_closed_m15(exe: Path) -> tuple[datetime, dict]:
    mt5, info = connect(exe)
    try:
        rows = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 1, 1)
        if rows is None or len(rows) != 1:
            raise RuntimeError(f"no latest closed M15 bar: {mt5.last_error()}")
        ts = datetime.fromtimestamp(int(rows[0]["time"]), timezone.utc)
        return ts, {"path": info.path, "data_path": info.data_path,
                    "build": int(info.build), "server": getattr(mt5.account_info(), "server", None)}
    finally:
        mt5.shutdown()


def fetch(exe: Path, start: datetime, end: datetime) -> tuple[dict[str, np.ndarray], dict]:
    mt5, info = connect(exe)
    try:
        result: dict[str, np.ndarray] = {}
        for tf_name, tf in (("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)):
            rows = mt5.copy_rates_range(SYMBOL, tf, start, end)
            if rows is None or len(rows) == 0:
                raise RuntimeError(f"no {tf_name} history for {start}..{end}: {mt5.last_error()}")
            rows = np.sort(rows, order="time")
            times = rows["time"].astype("i8")
            keep = np.ones(len(rows), dtype=bool)
            keep[1:] = times[1:] != times[:-1]
            rows = rows[keep]
            result[tf_name] = rows
        return result, {"path": info.path, "data_path": info.data_path,
                        "build": int(info.build),
                        "server": getattr(mt5.account_info(), "server", None)}
    finally:
        mt5.shutdown()


def write_csv(path: Path, rows: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(TIME_COLUMNS)
        for row in rows:
            stamp = datetime.fromtimestamp(int(row["time"]), timezone.utc).isoformat()
            writer.writerow([stamp, row["open"], row["high"], row["low"], row["close"], row["tick_volume"]])


def compare(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> dict:
    result = {"ok": True, "timeframes": {}}
    for tf in ("M15", "H1"):
        left, right = a[tf], b[tf]
        fields = ("time", "open", "high", "low", "close")
        same_shape = left.shape == right.shape
        same = same_shape
        max_diff = {field: None for field in fields if field != "time"}
        if same_shape:
            same = np.array_equal(left["time"], right["time"])
            for field in max_diff:
                diff = np.abs(left[field].astype(float) - right[field].astype(float))
                max_diff[field] = float(diff.max()) if len(diff) else 0.0
                same = same and bool(np.all(diff == 0.0))
        result["timeframes"][tf] = {
            "same": same,
            "rows_a": int(len(left)),
            "rows_b": int(len(right)),
            "same_shape": same_shape,
            "max_abs_diff": max_diff,
        }
        result["ok"] = result["ok"] and same
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_arm(tag: str, tp: float, start: datetime, end: datetime) -> dict:
    env = os.environ.copy()
    env.update({
        "CERT_DATA_DIR": str(OUT),
        "CERT_SPREAD": "18.5",
        "CERT_USD_PER_UNIT_PER_LOT": "1.009",
        "CERT_MIN_LOT": "0.01",
        "CERT_LOT_STEP": "0.001",
        "CERT_MICRO_FIT_PCT": "1.5",
        "CERT_MIN_STOP": "107.70",
    })
    cmd = [sys.executable, str(ROOT / "scripts" / "certify_v75.py"),
           "--equity", "50", "--tp-mult", str(tp), "--tag", tag,
           "--start", start.isoformat(), "--end", end.isoformat()]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
    # certify_v75.py keeps its established reports in artifacts/v75_replay;
    # the isolated corpus directory is reserved for the captured input bars.
    report_path = ROOT / "artifacts" / "v75_replay" / f"cert_report_{tag}.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return {"tag": tag, "tp_mult": tp, "command": cmd, "exit_code": proc.returncode,
            "report": str(report_path),            "summary": summarize(report) if report else None,

            "stdout_tail": (proc.stdout + proc.stderr)[-4000:]}


def summarize(report: dict | None) -> dict | None:
    if report is None:
        return None
    keys = ("equity0", "equity_final", "n", "wins", "win_rate", "total_r",
            "total_pnl", "max_drawdown_pct", "worst_loss_streak", "max_risk_pct",
            "funnel", "by_strategy", "auto_disabled", "micro_fit_pct",
            "broker_min_stop")
    return {key: report.get(key) for key in keys}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a-exe", type=Path, default=DEFAULT_A)
    ap.add_argument("--b-exe", type=Path, default=DEFAULT_B)
    ap.add_argument("--start", type=parse_dt, default=None,
                    help="exact 90-day window start; default is common latest closed bar minus 90 days")
    ap.add_argument("--end", type=parse_dt, default=None,
                    help="window end; default is common latest closed M15 bar")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT,
                    help="isolated directory for the captured corpus and result")
    args = ap.parse_args()

    global OUT
    OUT = args.output_dir

    latest_a, meta_a = latest_closed_m15(args.a_exe)
    latest_b, meta_b = latest_closed_m15(args.b_exe)
    common_end = min(latest_a, latest_b)
    end = args.end or common_end
    start = args.start or (end - timedelta(days=90))
    if end - start != timedelta(days=90):
        raise SystemExit(f"window must be exactly 90 days, got {end - start}")
    capture_start = start - WARMUP

    print(f"two-terminal blind test: {SYMBOL}")
    print(f"window: {start.isoformat()} -> {end.isoformat()} (exactly 90 days)")
    print(f"burn-in: {capture_start.isoformat()} -> {start.isoformat()} (excluded from results)")
    print(f"terminal A latest closed M15: {latest_a.isoformat()}")
    print(f"terminal B latest closed M15: {latest_b.isoformat()}")
    if args.end is not None and end > common_end:
        raise SystemExit("requested end is newer than the latest closed bar common to both terminals")

    data_a, fetch_meta_a = fetch(args.a_exe, capture_start, end)
    data_b, fetch_meta_b = fetch(args.b_exe, capture_start, end)
    agreement = compare(data_a, data_b)
    print("feed agreement:", "PASS" if agreement["ok"] else "FAIL")
    for tf, row in agreement["timeframes"].items():
        print(f"  {tf}: {row['rows_a']} vs {row['rows_b']} rows, "
              f"same OHLC path={row['same']}")
    if not agreement["ok"]:
        raise SystemExit("aborting: terminal feeds differ; no honest shared-data A/B result")

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "m15.csv", data_a["M15"])
    write_csv(OUT / "h1.csv", data_a["H1"])
    metadata = {
        "schema": "mitemshub.blind-two-terminal.v1",
        "symbol": SYMBOL,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": 90},
        "burn_in": {"start": capture_start.isoformat(), "end": start.isoformat(), "days": 7},
        "terminals": {"A": {**meta_a, **fetch_meta_a}, "B": {**meta_b, **fetch_meta_b}},
        "feed_agreement": agreement,
        "source_files": {},
    }
    for name in ("m15.csv", "h1.csv"):
        path = OUT / name
        metadata["source_files"][name] = {"rows": sum(1 for _ in path.open(encoding="utf-8")) - 1,
                                           "sha256": sha256(path)}
    (OUT / "capture_metadata.json").write_text(json.dumps(metadata, indent=1), encoding="utf-8")
    print(f"captured shared corpus: {metadata['source_files']}")

    arms = {
        "A_tp18_magic_7788075": run_arm("blind90_v2636d_armA_tp18", 1.8, start, end),
        "B_tp24_magic_7788100": run_arm("blind90_v2636d_armB_tp24", 2.4, start, end),
    }
    result = {"metadata": str(OUT / "capture_metadata.json"), "arms": arms}
    (OUT / "blind_test_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for name, arm in arms.items():
        summary = arm["summary"] or {}
        print(f"{name}: exit={arm['exit_code']} trades={summary.get('n')} "
              f"WR={summary.get('win_rate')}% totalR={summary.get('total_r')} "
              f"equity=${summary.get('equity_final')} maxDD={summary.get('max_drawdown_pct')}%")
        if arm["exit_code"] != 0:
            print(arm["stdout_tail"])
    return 0 if all(arm["exit_code"] == 0 for arm in arms.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

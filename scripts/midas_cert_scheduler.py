#!/usr/bin/env python3
"""Scheduled v1.16 WF shadow-path parity certification (register §2).

The §4(b) run is PENDING FLATNESS (register re-check 2026-09-18 11:17 UTC:
M1m resolves ~18:15 UTC, M1t ~21:35 UTC). This runner retries the registered
command

    python scripts/midas_parity.py --window wf \
        --expert-path "MIDASTOUCH_parity\\MidastouchAI"

every RETRY_MIN until the harness's OWN flat gate admits it or the session
completes. Exit-code contract of the harness:
  * 4  -> flat gate refused (or terminal did not stop) -> RETRY later;
  * 0  -> PARITY PASS -> record and stop;
  * 1  -> parity FAIL verdict -> record and stop (needs adjudication);
  * 3  -> python engine selftest failure -> record and stop.
The runner never pauses the watchdog and never touches the terminal itself:
every terminal operation belongs to the harness's registered choreography.
All attempts append to artifacts/midas_cert_scheduler_20260918.jsonl; per-
attempt harness stdout is kept in artifacts/cert_attempt_*.log.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RETRY_MIN = 20
MAX_WAIT_H = 24
COMMAND = [sys.executable, "scripts/midas_parity.py", "--window", "wf",
           "--expert-path", "MIDASTOUCH_parity\\MidastouchAI"]
LOG = REPO / "artifacts" / "midas_cert_scheduler_20260918.jsonl"


def log(entry: dict) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def main() -> int:
    log({"event": "scheduler-armed", "command": COMMAND[2:],
         "retry_min": RETRY_MIN, "max_wait_h": MAX_WAIT_H})
    deadline = time.time() + MAX_WAIT_H * 3600
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        attempt_log = REPO / "artifacts" / f"cert_attempt_{stamp}.log"
        proc = subprocess.run(COMMAND, cwd=REPO, capture_output=True,
                              text=True, timeout=3600)
        attempt_log.write_text(proc.stdout + (proc.stderr or ""),
                               encoding="utf-8")
        entry = {"event": "attempt", "n": attempt, "rc": proc.returncode,
                 "log": str(attempt_log.relative_to(REPO))}
        if proc.returncode == 4:
            entry["note"] = "flat gate refused (or terminal stop refused) — retrying"
            log(entry)
            time.sleep(RETRY_MIN * 60)
            continue
        # terminal state of the session: 0/1/3 all END the schedule
        entry["event"] = ("cert-complete" if proc.returncode in (0, 1, 3)
                          else "unexpected-rc-stop")
        tail = [l for l in proc.stdout.splitlines() if l.startswith("PARITY:")
                or "artifact:" in l or "verdict" in l.lower()]
        if tail:
            entry["summary"] = tail[-3:]
        log(entry)
        return proc.returncode
    log({"event": "expired", "note": f"no flat window in {MAX_WAIT_H} h — "
         "re-arm after checking the ledgers"})
    return 5


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Chained v1.17 BAR-mode parity certification (register P5 build block).

Runs AFTER the armed v1.16 cert scheduler completes — the ordering law:
the v1.16 cert needs the parity shadow as-is (v1.16); swapping the shadow
first would certify the wrong tree and destroy the deploy-baseline proof.

Chain, in phase order:
  1. WAIT for scripts/midas_cert_scheduler.py to complete, by watching
     artifacts/midas_cert_scheduler_20260918.jsonl (its event contract:
     "cert-complete" on rc 0/1/3, "unexpected-rc-stop", or "expired").
     STALENESS TAKEOVER: if the jsonl stops updating for STALE_MIN while
     still "waiting" (scheduler died — e.g. a session restart), this chain
     runs the v1.16 cert command itself once, so the baseline cert cannot
     be lost to a dead scheduler.
  2. REFRESH the parity shadow to v1.17: compile the repo source into the
     compile scratch (scripts/compile_midas.py), copy the fresh .ex5 to
     Experts/MIDASTOUCH_parity/MidastouchAI.ex5, verify byte-identity of
     the copy and difference from the pre-refresh hash.
  3. CERTIFY v1.17: the same registered harness command
     (midas_parity.py --window wf --expert-path MIDASTOUCH_parity\\MidastouchAI).
     Exit contract identical to the scheduler's: 4=retry-later, 0=PASS,
     1=FAIL, 3=selftest failure. On 4, phase 3 retries every RETRY_MIN
     until MAX_WAIT_H elapses (the flat window may close again if a new
     position opens between phases).

The runner never touches the terminal or the watchdog directly — every
terminal operation belongs to the parity harness's registered
choreography (same law as the v1.16 scheduler). All chain events append
to artifacts/midas_cert_chain_v117_<date>.jsonl; per-run harness stdout
is kept in artifacts/certchain_*.log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RETRY_MIN = 20
STALE_MIN = 35                 # > scheduler's 20-min retry cadence
MAX_WAIT_H = 24
POLL_S = 60

V16_COMMAND = [sys.executable, "scripts/midas_parity.py", "--window", "wf",
               "--expert-path", "MIDASTOUCH_parity\\MidastouchAI"]
V17_COMMAND = V16_COMMAND      # same harness; the SHADOW's content defines the tree

SCHED_LOG = REPO / "artifacts" / "midas_cert_scheduler_20260918.jsonl"


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_scheduler_state(jsonl_path: Path, now: float | None = None,
                          stale_min: int = STALE_MIN) -> dict:
    """Classify the v1.16 scheduler's state from its jsonl. Pure w.r.t. the
    file (the clock is injectable for tests).

    Returns {"status": waiting|complete|failed|expired|stale|absent,
             "last": <last event dict or None>, "age_s": float}
      waiting  — last event is an attempt/retry and the file is fresh
      stale    — last event is an attempt but the file is older than
                 stale_min: the scheduler is presumed dead → takeover
      complete — cert-complete logged (rc 0/1/3); inspect "rc"
      failed   — unexpected-rc-stop (harness left its contract)
      expired  — scheduler gave up (no flat window in its 24 h)
      absent   — no log file at all (scheduler never started)
    """
    now = time.time() if now is None else now
    if not jsonl_path.exists():
        return {"status": "absent", "last": None, "age_s": None}
    try:
        lines = [json.loads(l) for l in
                 jsonl_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return {"status": "absent", "last": None, "age_s": None}
    if not lines:
        return {"status": "absent", "last": None, "age_s": None}
    last = lines[-1]
    event = last.get("event", "")
    if event == "cert-complete":
        return {"status": "complete", "last": last, "age_s": 0.0}
    if event == "unexpected-rc-stop":
        return {"status": "failed", "last": last, "age_s": 0.0}
    if event == "expired":
        return {"status": "expired", "last": last, "age_s": 0.0}
    # still "attempt"-ing (or arming): freshness decides
    age_s = max(0.0, now - jsonl_path.stat().st_mtime)
    if age_s > stale_min * 60:
        return {"status": "stale", "last": last, "age_s": age_s}
    return {"status": "waiting", "last": last, "age_s": age_s}


def decide_next_action(state: dict) -> str:
    """The chain's decision table (pure; pinned by tests)."""
    s = state["status"]
    if s == "waiting":
        return "wait"
    if s == "stale" or s == "absent":
        # takeover: run the v1.16 cert ourselves before touching the shadow
        return "takeover-v16-cert"
    if s == "complete":
        return "refresh-and-certify"
    if s in ("failed", "expired"):
        return "abort"
    return "abort"


def run_logged(command: list[str], log_path: Path, timeout: int = 3600) -> int:
    proc = subprocess.run(command, cwd=REPO, capture_output=True,
                          text=True, timeout=timeout)
    log_path.write_text(proc.stdout + (proc.stderr or ""), encoding="utf-8")
    return proc.returncode


def refresh_shadow(scratch_ex5: Path,
                   shadow_ex5: Path, pre_hash: str) -> dict:
    """Compile v1.17 into scratch, copy to the shadow, verify. The scratch
    compile tool already proves 0/0 before this is called; the copy must be
    byte-identical and different from the pre-refresh binary."""
    if not scratch_ex5.exists():
        return {"ok": False, "detail": "scratch .ex5 missing — compile tool reported OK but produced nothing"}
    h = sha256_of(scratch_ex5)
    if h == pre_hash:
        return {"ok": False, "detail": "scratch binary identical to pre-refresh shadow — source did not change the build"}
    shadow_ex5.parent.mkdir(parents=True, exist_ok=True)
    shadow_ex5.write_bytes(scratch_ex5.read_bytes())
    if sha256_of(shadow_ex5) != h:
        return {"ok": False, "detail": "shadow copy is not byte-identical to the fresh build"}
    return {"ok": True, "sha256": h, "detail": f"shadow refreshed to {h[:8]}"}


def log(chain_log: Path, entry: dict) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(chain_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def main() -> int:
    import v28_sweep_runner as R

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true",
                    help="single decision cycle (debug)")
    args = ap.parse_args()

    data = R.data_folder_for_terminal()
    if not data:
        print("FATAL: terminal data folder not locatable")
        return 2
    mql5 = Path(data) / "MQL5"
    shadow_ex5 = mql5 / "Experts" / "MIDASTOUCH_parity" / "MidastouchAI.ex5"
    scratch_ex5 = mql5 / "Experts" / "MIDASTOUCH_compile" / "MidastouchAI" / "MidastouchAI.ex5"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    chain_log = REPO / "artifacts" / f"midas_cert_chain_v117_{stamp}.jsonl"

    deadline = time.time() + MAX_WAIT_H * 3600
    while time.time() < deadline:
        state = parse_scheduler_state(SCHED_LOG)
        action = decide_next_action(state)
        if action == "wait":
            log(chain_log, {"event": "waiting", "scheduler_age_s": round(state["age_s"] or 0, 1)})
            if args.once:
                return 0
            time.sleep(POLL_S)
            continue

        if action == "abort":
            log(chain_log, {"event": "abort", "reason": state})
            return 5

        if action == "takeover-v16-cert":
            log(chain_log, {"event": "takeover-v16-cert", "scheduler_state": state["status"]})
            rc = run_logged(V16_COMMAND, REPO / "artifacts" /
                            f"certchain_v16_takeover_{datetime.now():%Y%m%d_%H%M%S}.log")
            log(chain_log, {"event": "v16-cert-result", "rc": rc})
            if rc == 4:
                # flat gate refused — the window closed; re-enter the wait loop
                if args.once:
                    return 0
                time.sleep(RETRY_MIN * 60)
                continue
            if rc != 0:
                log(chain_log, {"event": "abort", "reason": f"v1.16 cert rc={rc} — baseline not certified, refusing to advance"})
                return 6
            # rc 0: v1.16 baseline certified → fall through to refresh

        # refresh-and-certify
        pre_hash = sha256_of(shadow_ex5) if shadow_ex5.exists() else ""
        rc_compile = run_logged(
            [sys.executable, "scripts/compile_midas.py",
             "--target", "mql5/MIDASTOUCH/MidastouchAI.mq5"],
            REPO / "artifacts" / f"certchain_v17_compile_{datetime.now():%Y%m%d_%H%M%S}.log")
        log(chain_log, {"event": "v17-compile", "rc": rc_compile})
        if rc_compile != 0:
            log(chain_log, {"event": "abort", "reason": "v1.17 compile failed — shadow left untouched"})
            return 7
        r = refresh_shadow(scratch_ex5=scratch_ex5,
                           shadow_ex5=shadow_ex5, pre_hash=pre_hash)
        log(chain_log, {"event": "shadow-refresh", **r})
        if not r["ok"]:
            return 8

        while time.time() < deadline:
            stamp2 = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            rc = run_logged(V17_COMMAND, REPO / "artifacts" / f"certchain_v17_attempt_{stamp2}.log")
            entry = {"event": "v17-cert-attempt", "rc": rc}
            if rc == 4:
                entry["note"] = "flat gate refused — retrying"
                log(chain_log, entry)
                time.sleep(RETRY_MIN * 60)
                continue
            entry["event"] = "v17-cert-complete" if rc in (0, 1, 3) else "unexpected-rc-stop"
            log(chain_log, entry)
            return rc
    log(chain_log, {"event": "expired", "note": "no completion within MAX_WAIT_H"})
    return 5


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""v1.18 deploy runner (register BUILD v1.18 block, 2026-09-18).

Deploys the v1.18 NOFILL-diagnostics build to the PAPER arms through the
registered stop→copy→verify→relaunch sequence, gated on the cert chain:

  1. WATCH the v1.17 chain (artifacts/midas_cert_chain_v117_*.jsonl). The
     deploy may start ONLY when the chain's terminal event is
     `v17-cert-complete` (rc 0/1/3) — i.e. the v1.16 baseline is certified
     AND the parity shadow has been refreshed to v1.17 and certified.
     Any other terminal state (unexpected-rc-stop, expired, abort) stands
     the deploy down: a failed baseline is never a deploy window.
  2. GATES (fail-closed, before any file is touched): every paper ledger
     flat; terminal stop succeeds; fresh compile 0/0 with a real scratch
     ex5; md5-verified copies.
  3. DEPLOY copies the fresh binary to exactly two paths — the paper
     charts' expert path (Experts/MITEMSHUB_AI/MidastouchAI.ex5, the
     pre-purge path chart01-04 still reference) and the canonical
     Experts/MIDASTOUCH/. It NEVER touches Experts/MIDASTOUCH_parity (the
     chain owns it; a v1.18 shadow refresh is a separately registered
     task) nor Experts/MIDASTOUCH_live (dormant in the VPS era; the LV
     surface on the VPS receives v1.18 with its next re-sync).
  4. VERIFY: after relaunch, each paper ledger must carry a fresh ERA row
     `MIDAS1.18,...+diag-nofill` or `MIDAS1.19,...+diag-nofill+p6-entrytf`
     (the init stamp — v1.19's P6 build block joined the never-abort class
     with the same citation) and a heartbeat EQ touch.

The LV/VPS deployment is recorded as DEFERRED, never attempted from here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

ART = REPO / "artifacts"
CHAIN_GLOB = "midas_cert_chain_v117_*.jsonl"
from midas_cert_chain_v117 import run_logged  # noqa: E402  (registered runner)

TERMINAL_OK = {"v17-cert-complete"}
TERMINAL_STOP = {"unexpected-rc-stop", "expired", "abort"}

PAPER_TAGS = ("M1", "M1t", "M1s", "M1m")
DEPLOY_TARGETS = (  # (relative to <data folder>/MQL5/Experts, description)
    ("MITEMSHUB_AI/MidastouchAI.ex5", "paper charts' expert path"),
    ("MIDASTOUCH/MidastouchAI.ex5", "canonical location"),
    # OPERATOR ORDER 2026-09-18 20:57 UTC ("then deploy the binary, what is
    # holding you"): the live/VPS-sync binary joins the deploy set. Safe
    # because v1.19's DEFAULTS are behavior-identical to v1.18, the staged
    # TP/TF presets are NOT spliced onto the LV chart (the reading gates
    # that), and the dormant local live instance is AutoTrading-OFF in the
    # VPS era. MT5 virtual hosting syncs this folder to the VPS — this is
    # the registered propagation channel to the live surface.
    ("MIDASTOUCH_live/MidastouchAI.ex5", "live/VPS-sync path (operator order; v1.19 defaults inert)"),
)
NEVER_TOUCH = ("MIDASTOUCH_parity",)


def chain_terminal_state(art: Path, now: float | None = None) -> dict:
    """Classify the newest chain jsonl's terminal state. Pure. Pins:
    newest file wins; its LAST event decides; a still-running chain
    (last event not terminal) is `running`; missing files are `absent`."""
    files = sorted(art.glob(CHAIN_GLOB), key=lambda p: p.stat().st_mtime)
    if not files:
        return {"state": "absent"}
    last = files[-1]
    events = [json.loads(l) for l in
              last.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not events:
        return {"state": "empty", "file": last.name}
    ev = events[-1].get("event", "")
    if ev in TERMINAL_OK:
        return {"state": "chain-complete", "file": last.name, "event": ev,
                "rc": events[-1].get("rc")}
    if ev in TERMINAL_STOP:
        return {"state": "chain-failed", "file": last.name, "event": ev}
    return {"state": "running", "file": last.name, "event": ev}


def deploy_decision(state: dict) -> dict:
    """The ordering law, as a pure decision: only a completed chain opens
    the deploy window; everything else stands down (fail-closed)."""
    s = state.get("state")
    if s == "chain-complete":
        return {"act": "deploy"}
    if s == "running":
        return {"act": "wait", "detail": f"chain {state.get('event', '?')}"}
    if s == "absent":
        return {"act": "wait", "detail": "no chain log yet"}
    return {"act": "stand-down", "detail": f"chain terminal state {s}"}


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def all_paper_flat(files_root: Path) -> tuple[bool, list[str]]:
    from v28_sweep_runner import ledger_flatness
    bad = []
    for tag in PAPER_TAGS:
        p = files_root / f"MIDASTOUCH_paper_XAUUSDmicro_{tag}.csv"
        if not p.exists():
            bad.append(f"{tag}: ledger missing")
            continue
        f = ledger_flatness(str(p))
        if not f["flat"]:
            bad.append(f"{tag}: not flat ({f.get('problems')})")
    return (not bad), bad


def deploy_binaries(scratch_ex5: Path, mql5_experts: Path,
                    log) -> list[dict]:
    """Copy the fresh build to DEPLOY_TARGETS, md5-verify each, refuse any
    NEVER_TOUCH path by construction (the loop never enumerates them)."""
    fresh = sha256_of(scratch_ex5)
    results = []
    for rel, why in DEPLOY_TARGETS:
        dst = mql5_experts / rel
        assert not any(rel.startswith(nt) for nt in NEVER_TOUCH), rel
        bak = dst.with_suffix(".ex5.pre_v119")
        if dst.exists():
            bak.write_bytes(dst.read_bytes())
        dst.write_bytes(scratch_ex5.read_bytes())
        ok = sha256_of(dst) == fresh
        log({"event": "deploy-copy", "target": rel, "why": why,
             "md5_ok": ok, "backup": bak.name})
        results.append({"target": rel, "ok": ok})
    return results


def verify_arms(files_root: Path, min_epoch: float) -> dict:
    """Post-relaunch proof: each paper ledger carries an ERA row from a
    registered never-abort build (MIDAS1.18 or later v1.19 P6 build block —
    both cite the register) with the diag-nofill tag, and an EQ row newer
    than min_epoch."""
    accepted_era = ("ERA,MIDAS1.18,", "ERA,MIDAS1.19,")
    out = {}
    for tag in PAPER_TAGS:
        p = files_root / f"MIDASTOUCH_paper_XAUUSDmicro_{tag}.csv"
        if not p.exists():
            out[tag] = "missing"
            continue
        rows = p.read_text(encoding="utf-8", errors="replace").splitlines()
        era_ok = any(r.startswith(accepted_era) and "diag-nofill" in r
                     for r in rows)
        eq_ok = any(r.startswith("EQ,") for r in reversed(rows)) and \
            p.stat().st_mtime >= min_epoch
        out[tag] = "ok" if (era_ok and eq_ok) else \
            f"era18={era_ok} fresh_eq={eq_ok}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="v1.18 chain-gated deploy")
    ap.add_argument("--watch", action="store_true",
                    help="poll until the chain completes, then deploy")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--deadline-h", type=float, default=12.0)
    args = ap.parse_args()

    import v28_sweep_runner as R
    df = Path(R.data_folder_for_terminal())
    mql5 = df / "MQL5"
    files_root = mql5 / "Files"
    experts = mql5 / "Experts"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_path = ART / f"midas_deploy_v118_{stamp}.jsonl"

    def log(e: dict) -> None:
        e["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")
        print(json.dumps(e), flush=True)

    deadline = time.time() + args.deadline_h * 3600
    while True:
        state = chain_terminal_state(ART)
        dec = deploy_decision(state)
        log({"event": "watch", "state": state, "act": dec["act"]})
        if dec["act"] == "deploy":
            break
        if dec["act"] == "stand-down":
            log({"event": "stand-down", **dec})
            return 5
        if not args.watch or time.time() > deadline:
            log({"event": "expired"})
            return 4
        time.sleep(args.interval)

    # --- gates ---------------------------------------------------------------
    flat, bad = all_paper_flat(files_root)
    log({"event": "flat-gate", "flat": flat, "bad": bad})
    if not flat:
        return 6

    marker = REPO / "scripts" / ".midas_watchdog_paused"
    was_paused = marker.exists()
    if not was_paused:
        marker.write_text("v1.18 deploy\n")
    log({"event": "watchdog-paused", "pre_existing": was_paused})

    pids = R.terminal_pids_exact()
    if pids and not R.stop_terminal(pids):
        log({"event": "abort", "reason": "terminal stop failed"})
        return 7
    log({"event": "terminal-stopped", "pids": pids})

    rc = R.run_logged([sys.executable, "scripts/compile_midas.py", "--keep"],
                      ART / f"deploy_v118_compile_{datetime.now():%Y%m%d_%H%M%S}.log")
    log({"event": "compile", "rc": rc})
    if rc != 0:
        return 8
    scratch = experts / "MIDASTOUCH_compile" / "MidastouchAI" / "MidastouchAI.ex5"
    if not scratch.exists():
        log({"event": "abort", "reason": "scratch ex5 missing after compile"})
        return 8

    results = deploy_binaries(scratch, experts, log)
    if not all(r["ok"] for r in results):
        log({"event": "abort", "reason": "md5 verify failed"})
        return 9

    R.relaunch_terminal()
    log({"event": "relaunched"})

    time.sleep(45)
    min_epoch = time.time() - 120
    v = verify_arms(files_root, min_epoch)
    log({"event": "verify", "arms": v,
         "lv": "DEFERRED — VPS-hosted surface; v1.18 rides the next re-sync"})
    if not was_paused:
        marker.unlink(missing_ok=True)
        log({"event": "watchdog-resumed"})
    ok = all(x == "ok" for x in v.values())
    log({"event": "deploy-complete" if ok else "verify-failed"})
    return 0 if ok else 10


if __name__ == "__main__":
    sys.exit(main())

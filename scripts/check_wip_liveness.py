"""Telemetry-liveness gate for -AllowWip deployments (sync-mt5.ps1).

WHY. The 2026-09-13 incident: a routine sync deployed an uncommitted,
non-functional WIP engine (MitemshubAI v27.00) over the certified paper arms;
it printed its init banner and then emitted NOTHING (no bar processing, no
telemetry) while both arms froze for ~2 days. The sha256 manifest gate stops
that by accident; -AllowWip is still a bare human assertion. This checker
makes the assertion machine-checkable: a WIP source may deploy over the arms
only after it has PROVEN itself alive somewhere else.

WHAT COUNTS AS PROOF (pre-registered 2026-09-15, before any v27 validation):
  C1  the worktree source declares its version (#define APP_VERSION /
      #property version) - otherwise the journal cannot be bound to it;
  C2  evidence comes from a NON-ARM terminal only: any data folder whose
      charts carry an arm magic (7788075 / 7788100 / 7788125) is excluded -
      a WIP already sitting on an arm is the incident, not evidence;
  C3  byte binding: the staging terminal's deployed source (its
      Experts/<EA>/ copy) sha256-matches the worktree source, and its .ex5
      is not older than that source (the binary was built from these bytes);
  C4  journal: an init banner on the EA's own channel naming that version
      ("v<ver>" + started/initialized) in today's or yesterday's log;
  C5  the banner is >= one bar-grace old (16m MitemshubAI, 31m
      V75MacroEngine) - the EA had at least one bar interval to live;
  C6  at least one post-init journal line on the EA's channel (the inverse
      of the banner-then-silence signature the morning_status canary alerts);
  C7  telemetry: the EA's telemetry file was written AFTER the banner.

All seven must hold on at least one terminal.

MODES
  --collect  Run now against the running terminals and record the evidence
             artifact. Use while the WIP is running on a staging terminal
             (49E0 is reserved for this: tester/reserve-only, no arm magics).
             Staging flow: copy the WIP source into the staging terminal's
             Experts tree manually (do NOT sync - the gate would refuse),
             compile in place, attach to a chart, wait one bar interval,
             then: python scripts/check_wip_liveness.py --collect --src <src>
  --verify   (default) Re-check the recorded artifact against the CURRENT
             worktree bytes: verdict PASS, same EA, same version, same
             sha256, recorded within --max-age-hours (default 48). No
             terminal needs to be running. sync-mt5.ps1 -AllowWip calls
             this; a failed verify refuses the bypass fail-closed.

Writes artifacts/deploy_wip_liveness.json in both modes (FAIL attempts are
recorded too - the audit trail matters). Exit 0 = proven, 1 = not proven.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from morning_status import CANARY_GRACE_MIN, EA_FILES, TERM_ROOT, parse_mql5_log  # noqa: E402

SCHEMA = "mitemshub.artifact-spec.v1"
ARTIFACT = "deploy_wip_liveness"
ARM_MAGICS = ("7788075", "7788100", "7788125")   # paper arms - never evidence

# source basename (lowercase) -> EA family key used by EA_FILES/CANARY_GRACE_MIN
EA_FOR_SOURCE = {"mitemshubai.mq5": "MitemshubAI", "v75macroengine.mq5": "V75MacroEngine"}
# deployed source/binary location inside a terminal data folder, per EA family
DEPLOY_REL = {"MitemshubAI": ("Experts", "MITEMSHUB_AI", "MitemshubAI"),
              "V75MacroEngine": ("Experts", "V75MacroEngine", "V75MacroEngine")}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_version(src_text: str) -> str | None:
    """The version the source itself declares (last declaration wins)."""
    hits = re.findall(r'#define\s+APP_VERSION\s+"(\d+\.\d+)"', src_text)
    hits += re.findall(r'#property\s+version\s+"(\d+\.\d+)"', src_text)
    return hits[-1] if hits else None


def is_banner(msg: str, version: str) -> bool:
    return (bool(re.search(rf"\bv{re.escape(version)}\b", msg))
            and ("started" in msg or "initialized" in msg))


def ea_channel_lines(tdir: str, ea: str, now: datetime) -> list[tuple[datetime, str]]:
    """EA-channel journal lines from today's and yesterday's MQL5/Logs."""
    out: list[tuple[datetime, str]] = []
    for delta in (0, 1):
        day = (now - timedelta(days=delta)).date()
        log = os.path.join(tdir, "MQL5", "Logs", f"{day:%Y%m%d}.log")
        day0 = datetime(day.year, day.month, day.day)
        out += [(ts, msg) for ts, ch, msg in parse_mql5_log(log, day0)
                if ch.startswith(ea + " (")]
    return out


def charts_carry_arm_magic(tdir: str) -> str | None:
    """First arm magic found in any saved chart of this terminal (else None)."""
    import glob as _glob
    for chr_f in _glob.glob(os.path.join(tdir, "MQL5", "Profiles", "Charts", "*", "*.chr")):
        try:
            txt = open(chr_f, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        for magic in ARM_MAGICS:
            if re.search(rf"^InpMagic(?:Number)?={magic}$", txt, re.M):
                return magic
    return None


def evaluate_terminal(tdir: str, ea: str, version: str, src_sha: str,
                      now: datetime) -> tuple[bool, list[str], dict]:
    """All checks C2..C7 against one terminal. (C1 is checked by the caller.)"""
    reasons: list[str] = []
    grace_min = CANARY_GRACE_MIN.get(ea, 31)
    grace_s = grace_min * 60

    # C2 - a terminal already hosting an arm can never be the proof source
    magic = charts_carry_arm_magic(tdir)
    if magic:
        return False, [f"arm-hosting terminal excluded as evidence source (chart magic {magic})"], {}

    # C3 - byte binding: deployed source == worktree source, binary fresh
    stem = DEPLOY_REL[ea]
    dep_src = os.path.join(tdir, "MQL5", *stem[:-1], stem[-1] + ".mq5")
    dep_ex5 = os.path.join(tdir, "MQL5", *stem[:-1], stem[-1] + ".ex5")
    dep_rel = "\\".join(("MQL5",) + stem[:-1] + (stem[-1] + ".mq5",))
    if not os.path.exists(dep_src):
        return False, [f"no deployed source at {dep_rel}"], {}
    if sha256_file(dep_src) != src_sha:
        return False, ["deployed source does not sha256-match the worktree source "
                       "(the running build cannot be bound to these bytes)"], {}
    if not os.path.exists(dep_ex5):
        return False, ["deployed binary missing (.ex5) - nothing was built from the staged source"], {}
    if os.path.getmtime(dep_ex5) < os.path.getmtime(dep_src):
        return False, ["deployed binary is older than the deployed source - .ex5 is not built "
                       "from these bytes; recompile the staging terminal in place"], {}

    # C4 - version-bound init banner on the EA's own channel
    lines = ea_channel_lines(tdir, ea, now)
    banners = [ts for ts, msg in lines if is_banner(msg, version)]
    eligible = [ts for ts in banners if (now - ts).total_seconds() >= grace_s]
    if not eligible:
        if banners:
            age = (now - banners[-1]).total_seconds() / 60
            return False, [f"banner for v{version} is only {age:.0f}m old "
                           f"(< {grace_min}m grace - give it one bar interval, then re-collect)"], {}
        return False, [f"no init banner for v{version} on this terminal's journal "
                       "(today/yesterday, EA channel)"], {}
    banner_ts = max(eligible)

    # C6 - at least one post-init journal line (banner-then-silence = dead)
    post = [ts for ts, _ in lines if ts > banner_ts]
    if not post:
        return False, [f"init banner {banner_ts:%H:%M:%S} with NO journal processing after it "
                       "- the loaded-but-dead signature (v27, 2026-09-13)"], {}

    # C7 - telemetry written after the banner
    telem = os.path.join(tdir, "MQL5", "Files", EA_FILES[ea][1])
    if not os.path.exists(telem):
        return False, [f"no telemetry file ({EA_FILES[ea][1]})"], {}
    if os.path.getmtime(telem) <= banner_ts.timestamp():
        return False, [f"telemetry last written before the v{version} init banner "
                       "- no bar produced telemetry since init"], {}

    return True, [], {
        "terminal": os.path.basename(tdir.rstrip("\\/")),
        "banner_ts": f"{banner_ts:%Y-%m-%d %H:%M:%S}",
        "banner_age_min": round((now - banner_ts).total_seconds() / 60, 1),
        "post_init_journal_lines": len(post),
        "telemetry_age_min": round((now_epoch() - os.path.getmtime(telem)) / 60, 1),
        "grace_min": grace_min,
    }


def now_epoch() -> float:
    return datetime.now().timestamp()


def collect(src: str, evidence_path: str, term_root: str) -> int:
    now = datetime.now()
    try:
        src_text = open(src, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"FAIL: cannot read source: {e}")
        return 1
    version = extract_version(src_text)
    base = os.path.basename(src).lower()
    ea = EA_FOR_SOURCE.get(base)
    if version is None or ea is None:
        print(f"FAIL: cannot bind source to a version/EA "
              f"(version={version!r}, ea={ea!r}) - C1 failed")
        return 1
    src_sha = sha256_file(src)

    passing, failures = [], []
    for name in sorted(os.listdir(term_root)):
        tdir = os.path.join(term_root, name)
        if not os.path.isdir(tdir):
            continue
        ok, reasons, detail = evaluate_terminal(tdir, ea, version, src_sha, now)
        if ok:
            passing.append(detail)
        else:
            failures.append({"terminal": name, "reasons": reasons})

    verdict = "PASS" if passing else "FAIL"
    artifact = {
        "schema": SCHEMA, "artifact": ARTIFACT,
        "generated_at": f"{now:%Y-%m-%d %H:%M:%S}",
        "source_path": src, "source_sha256": src_sha,
        "ea": ea, "version_tag": version, "verdict": verdict,
        "terminals": passing, "failures": failures,
    }
    os.makedirs(os.path.dirname(evidence_path), exist_ok=True)
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")

    print(f"LIVENESS COLLECT [{ea} v{version}] sha {src_sha[:12]}... -> {verdict}")
    for d in passing:
        print(f"  PASS {d['terminal']}: banner {d['banner_ts']} ({d['banner_age_min']}m old), "
              f"{d['post_init_journal_lines']} post-init journal line(s), "
              f"telemetry {d['telemetry_age_min']}m ago")
    for f_ in failures:
        print(f"  fail {f_['terminal']}: {'; '.join(f_['reasons'])}")
    if verdict == "FAIL":
        print("No terminal proved this source alive. Stage it on a NON-ARM terminal "
              "(49E0), compile in place, wait one bar interval, re-collect.")
    return 0 if verdict == "PASS" else 1


def verify(src: str, evidence_path: str, max_age_hours: float) -> int:
    try:
        src_sha = sha256_file(src)
        version = extract_version(open(src, encoding="utf-8", errors="replace").read())
        ea = EA_FOR_SOURCE.get(os.path.basename(src).lower())
    except OSError as e:
        print(f"LIVENESS VERIFY FAIL: cannot read source: {e}")
        return 1
    if version is None or ea is None:
        print("LIVENESS VERIFY FAIL: source does not declare a bindable version (C1)")
        return 1
    try:
        ev = json.load(open(evidence_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"LIVENESS VERIFY FAIL: no readable evidence artifact ({evidence_path}): {e}")
        return 1

    problems = []
    if ev.get("artifact") != ARTIFACT or ev.get("schema") != SCHEMA:
        problems.append("not a deploy_wip_liveness artifact")
    if ev.get("verdict") != "PASS":
        problems.append(f"recorded verdict is {ev.get('verdict')!r}")
    if ev.get("ea") != ea:
        problems.append(f"evidence is for {ev.get('ea')!r}, not {ea!r}")
    if ev.get("version_tag") != version:
        problems.append(f"evidence version {ev.get('version_tag')!r} != source {version!r}")
    if ev.get("source_sha256") != src_sha:
        problems.append("source changed since validation (sha256 mismatch) - re-collect")
    try:
        gen = datetime.strptime(ev["generated_at"], "%Y-%m-%d %H:%M:%S")
        age_h = (datetime.now() - gen).total_seconds() / 3600
        if age_h > max_age_hours:
            problems.append(f"evidence is {age_h:.1f}h old (> {max_age_hours}h) - re-collect")
    except (KeyError, ValueError):
        problems.append("evidence has no valid generated_at timestamp")

    if problems:
        print("LIVENESS VERIFY FAIL: " + "; ".join(problems))
        return 1
    terms = ", ".join(t.get("terminal", "?") for t in ev.get("terminals", [])) or "?"
    print(f"LIVENESS VERIFY OK: {ea} v{version} sha {src_sha[:12]}... validated "
          f"{ev['generated_at']} on {terms}")
    return 0


def main(argv: list[str] | None = None) -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="worktree EA source to bind evidence to")
    ap.add_argument("--collect", action="store_true",
                    help="probe the running terminals and (re)write the evidence artifact")
    ap.add_argument("--evidence", default=os.path.join(repo_root, "artifacts", "deploy_wip_liveness.json"))
    ap.add_argument("--term-root", default=TERM_ROOT, help="override terminal root (tests)")
    ap.add_argument("--max-age-hours", type=float, default=48.0,
                    help="verify: reject evidence older than this (default 48)")
    args = ap.parse_args(argv)

    if args.collect:
        return collect(args.src, args.evidence, args.term_root)
    return verify(args.src, args.evidence, args.max_age_hours)


if __name__ == "__main__":
    sys.exit(main())

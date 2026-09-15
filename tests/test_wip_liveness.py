"""Unit tests for the -AllowWip telemetry-liveness gate (check_wip_liveness.py).

Builds synthetic terminal data folders (real journal line format, real chart
encoding, real file layout) and pins every pre-registered condition C1..C7 —
including the exact 2026-09-13 signature the gate exists to stop: a v27 WIP
that prints its init banner and then stays silent on an arm terminal.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import check_wip_liveness as cwl  # noqa: E402

WIP_SRC = ('#define APP_VERSION "27.00"\n'
           '#property version   APP_VERSION\n'
           'int OnInit() { Print("[v27.00] MITEMSHUB V75 MACRO started"); return 0; }\n')

CHAN = "MitemshubAI (Volatility 75 Index, M15)"
GRACE_MIN = 16  # CANARY_GRACE_MIN["MitemshubAI"]


def _journal_line(hhmmss: str, chan: str, msg: str) -> str:
    return f"PP\t0\t{hhmmss}.123\t{chan}\t{msg}\r\n"


@pytest.fixture
def env(tmp_path):
    """Worktree WIP source + a synthetic terminal root with one staging term."""
    src = tmp_path / "MitemshubAI.mq5"
    src.write_text(WIP_SRC, encoding="utf-8")
    term_root = tmp_path / "Terminals"
    term_root.mkdir()
    return {"src": str(src), "term_root": str(term_root), "evidence": str(tmp_path / "ev.json"),
            "tmp": tmp_path}


def write_journal(tdir: str, entries: list[tuple[datetime, str, str]]) -> None:
    """Write journal lines into the right day files (real layout: one log per day)."""
    by_day: dict = {}
    for ts, chan, msg in entries:
        by_day.setdefault(ts.date(), []).append(f"PP\t0\t{ts:%H:%M:%S}.123\t{chan}\t{msg}\r\n")
    for day, lines in by_day.items():
        log = os.path.join(tdir, "MQL5", "Logs", f"{day:%Y%m%d}.log")
        mode = "a" if os.path.exists(log) else "w"
        with open(log, mode, encoding="utf-16") as f:
            f.write("".join(lines))


def make_terminal(root: str, name: str, *, arm_magic: str | None = None) -> str:
    tdir = os.path.join(root, name)
    os.makedirs(os.path.join(tdir, "MQL5", "Logs"))
    os.makedirs(os.path.join(tdir, "MQL5", "Files"))
    os.makedirs(os.path.join(tdir, "MQL5", "Experts", "MITEMSHUB_AI"))
    os.makedirs(os.path.join(tdir, "MQL5", "Profiles", "Charts", "Default"))
    chr_f = os.path.join(tdir, "MQL5", "Profiles", "Charts", "Default", "chart01.chr")
    magic_line = f"InpMagic={arm_magic}\n" if arm_magic else "InpMagic=9999999\n"
    chr_f and open(chr_f, "w", encoding="utf-16").write(
        "<chart>\nsymbol=Volatility 75 Index\nexpert=MitemshubAI.ex5\n"
        + magic_line + "InpLiveExecution=false\n</chart>\n")
    return tdir


def stage_alive(tdir: str, src: str, *, banner_age_min: int = 120,
                post_lines: int = 3, telem: bool = True, now: datetime | None = None) -> None:
    """A fully alive WIP: matching source, fresh binary, banner + post lines + telemetry."""
    now = now or datetime.now()
    src_text = open(src, encoding="utf-8").read()
    dep_src = os.path.join(tdir, "MQL5", "Experts", "MITEMSHUB_AI", "MitemshubAI.mq5")
    dep_ex5 = os.path.join(tdir, "MQL5", "Experts", "MITEMSHUB_AI", "MitemshubAI.ex5")
    open(dep_src, "w", encoding="utf-8").write(src_text)
    open(dep_ex5, "wb").write(b"\x00binary")
    os.utime(dep_src, (now.timestamp(), now.timestamp()))
    os.utime(dep_ex5, (now.timestamp(), now.timestamp()))

    banner_dt = now - timedelta(minutes=banner_age_min)
    entries = [(banner_dt, CHAN,
                "[v27.00] MITEMSHUB V75 MACRO started | gate=M30 | macro=H4+H1")]
    for i in range(post_lines):
        entries.append((banner_dt + timedelta(minutes=15 * (i + 1)), CHAN,
                        "BAR M15: processed 120 ticks"))
    write_journal(tdir, entries)

    if telem:
        telem_f = os.path.join(tdir, "MQL5", "Files",
                               "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl")
        open(telem_f, "w", encoding="utf-8").write('{"type":"hb"}\n')
        t_ts = (banner_dt + timedelta(minutes=15)).timestamp()
        os.utime(telem_f, (t_ts, t_ts))


def run(env, *extra):
    argv = ["--src", env["src"], "--term-root", env["term_root"],
            "--evidence", env["evidence"], *extra]
    code = cwl.main(argv)
    ev = None
    if os.path.exists(env["evidence"]):
        ev = json.load(open(env["evidence"], encoding="utf-8"))
    return code, ev


def test_alive_wip_passes_and_records_sha(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    code, ev = run(env, "--collect")
    assert code == 0 and ev["verdict"] == "PASS"
    assert ev["version_tag"] == "27.00" and ev["ea"] == "MitemshubAI"
    assert ev["source_sha256"] == cwl.sha256_file(env["src"])
    assert ev["terminals"][0]["terminal"] == "STAGE49E0"
    assert ev["terminals"][0]["post_init_journal_lines"] == 3


def test_banner_then_silence_is_the_refused_signature(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"], post_lines=0, telem=False)
    code, ev = run(env, "--collect")
    assert code == 1 and ev["verdict"] == "FAIL"
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "loaded-but-dead" in reasons or "NO journal processing" in reasons


def test_arm_terminal_is_excluded_as_evidence(env):
    tdir = make_terminal(env["term_root"], "FB9A", arm_magic="7788075")
    stage_alive(tdir, env["src"])  # perfect evidence, wrong terminal
    make_terminal(env["term_root"], "EMPTY")  # no evidence anywhere else
    code, ev = run(env, "--collect")
    assert code == 1 and ev["verdict"] == "FAIL"
    fb = next(f for f in ev["failures"] if f["terminal"] == "FB9A")
    assert any("arm-hosting terminal excluded" in r and "7788075" in r for r in fb["reasons"])


def test_deployed_source_must_sha_match_worktree(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    # worktree changes AFTER staging: the running build can no longer be bound
    open(env["src"], "a", encoding="utf-8").write("// drift\n")
    code, ev = run(env, "--collect")
    assert code == 1
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "sha256-match" in reasons


def test_stale_binary_refuses(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    now = datetime.now()
    ex5 = os.path.join(tdir, "MQL5", "Experts", "MITEMSHUB_AI", "MitemshubAI.ex5")
    src_ts = now.timestamp() - 3600
    os.utime(ex5, (src_ts, src_ts))  # binary older than source
    code, ev = run(env, "--collect")
    assert code == 1
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "older than the deployed source" in reasons


def test_telemetry_must_postdate_banner(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    now = datetime.now()
    telem_f = os.path.join(tdir, "MQL5", "Files",
                           "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl")
    old = (now - timedelta(hours=5)).timestamp()  # predates the 2h-old banner
    os.utime(telem_f, (old, old))
    code, ev = run(env, "--collect")
    assert code == 1
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "before the v27.00 init banner" in reasons


def test_banner_inside_grace_asks_for_patience(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"], banner_age_min=5)  # < 16m grace
    code, ev = run(env, "--collect")
    assert code == 1
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "grace" in reasons


def test_wrong_version_banner_does_not_satisfy(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    now = datetime.now()
    # wipe the logs: the only banner this terminal ever printed is v26.35's
    import shutil
    shutil.rmtree(os.path.join(tdir, "MQL5", "Logs"))
    os.makedirs(os.path.join(tdir, "MQL5", "Logs"))
    b = now - timedelta(hours=2)
    write_journal(tdir, [
        (b, CHAN, "[v26.35] MITEMSHUB V75 MACRO started | gate=M30 | macro=H4+H1"),
        (b + timedelta(minutes=15), CHAN, "BAR M15: processed 120 ticks"),
    ])
    code, ev = run(env, "--collect")
    assert code == 1 and ev["verdict"] == "FAIL"
    reasons = " ".join(r for f in ev["failures"] for r in f["reasons"])
    assert "no init banner for v27.00" in reasons


def test_source_without_version_fails_c1(env):
    open(env["src"], "w", encoding="utf-8").write("int OnInit(){return 0;}\n")
    code, ev = run(env, "--collect")
    assert code == 1  # C1 fail never writes an artifact
    assert not os.path.exists(env["evidence"])


def test_verify_roundtrip_and_tampering(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    code, ev = run(env, "--collect")
    assert code == 0
    # same bytes -> verify passes without any terminal running
    assert cwl.main(["--src", env["src"], "--evidence", env["evidence"]]) == 0
    # source edited after validation -> refuse
    open(env["src"], "a", encoding="utf-8").write("// drifted\n")
    assert cwl.main(["--src", env["src"], "--evidence", env["evidence"]]) == 1
    # a FAIL verdict in the artifact never authorizes
    ev["verdict"] = "FAIL"
    json.dump(ev, open(env["evidence"], "w"))
    assert cwl.main(["--src", env["src"], "--evidence", env["evidence"]]) == 1


def test_verify_rejects_stale_evidence(env):
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    stage_alive(tdir, env["src"])
    code, ev = run(env, "--collect")
    assert code == 0
    ev["generated_at"] = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    json.dump(ev, open(env["evidence"], "w"))
    assert cwl.main(["--src", env["src"], "--evidence", env["evidence"]]) == 1
    assert cwl.main(["--src", env["src"], "--evidence", env["evidence"],
                     "--max-age-hours", "96"]) == 0


def test_v75_family_end_to_end(env, tmp_path):
    """Same gate covers the V75MacroEngine family (31m grace, own file names)."""
    src = tmp_path / "V75MacroEngine.mq5"
    src.write_text('#property version     "2.22"\n', encoding="utf-8")
    env["src"] = str(src)
    tdir = make_terminal(env["term_root"], "STAGE49E0")
    dep_dir = os.path.join(tdir, "MQL5", "Experts", "V75MacroEngine")
    os.makedirs(dep_dir, exist_ok=True)
    dep_src = os.path.join(dep_dir, "V75MacroEngine.mq5")
    open(dep_src, "w", encoding="utf-8").write(open(src, encoding="utf-8").read())
    open(os.path.join(dep_dir, "V75MacroEngine.ex5"), "wb").write(b"\x00")
    now = datetime.now()
    banner = now - timedelta(minutes=60)
    vchan = "V75MacroEngine (Volatility 75 Index, M30)"
    write_journal(tdir, [
        (banner, vchan, "V75 Macro Engine v2.22 initialized (LONG-ONLY, 2h timeout, PAPER)"),
        (banner + timedelta(minutes=30), vchan, "MACRO M30 bar"),
    ])
    telem_f = os.path.join(tdir, "MQL5", "Files",
                           "V75MacroEngine_paper_telemetry_Volatility_75_Index.jsonl")
    open(telem_f, "w").write('{"type":"hb"}\n')
    os.utime(telem_f, ((banner + timedelta(minutes=30)).timestamp(),) * 2)
    os.utime(dep_src, (now.timestamp(), now.timestamp()))
    os.utime(os.path.join(dep_dir, "V75MacroEngine.ex5"), (now.timestamp(), now.timestamp()))
    code, ev = run(env, "--collect")
    assert code == 0 and ev["verdict"] == "PASS" and ev["ea"] == "V75MacroEngine"
    assert ev["version_tag"] == "2.22"

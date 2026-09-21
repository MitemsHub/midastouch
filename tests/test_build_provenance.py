"""The deployed binary must be the one the source produced — and readiness must say so.

WHY THIS FILE EXISTS. A chart loads whatever `.ex5` sits in the Experts tree, and nothing
connects that file to the `.mq5` the pins describe. On 2026-09-20 the terminal held a
20:17 build while the 23:02 source compiled clean at a different size; the only symptom was
a byte count in a log line. Two properties follow, and both are pinned here:

  * `compile_midas.py --deploy` RECORDS the pair it produced (`source` hash and `ex5`
    hash), because the compiler is not bit-reproducible — two compiles of one unchanged
    source differ (measured: 94,780 B and 95,012 B) — so provenance can only ever be read
    back from the moment of the build, never re-derived afterwards;
  * `live_readiness.py` FAILS when the deployed binary predates, differs from, or cannot
    be traced to the source, and WARNS (never passes) when it cannot be checked at all.

The three-state answer is the point. A build whose provenance is unknown must not render
green: that is the same rule the readiness report already applies to a scheduled task it
could not query.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import compile_midas as cm  # noqa: E402
import live_readiness as lr  # noqa: E402


def _source(tmp_path: Path, text: str = "// MidastouchAI\n") -> Path:
    p = tmp_path / "MidastouchAI.mq5"
    p.write_text(text, encoding="utf-8")
    return p


def _binary(tmp_path: Path, name: str = "MidastouchAI.ex5",
            blob: bytes = b"\x00binary\xff") -> Path:
    p = tmp_path / "Experts" / "MIDASTOUCH" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return p


def _record(tmp_path: Path, source: Path, binary: Path,
            source_sha: str | None = None, ex5_sha: str | None = None) -> Path:
    rec = tmp_path / "midas_build.json"
    rec.write_text(json.dumps({"utc": "2026-09-21T00:00:00+00:00", "targets": {
        source.stem: {
            "source": str(source),
            "source_sha256": source_sha or cm.sha256_of(source),
            "ex5_sha256": ex5_sha or cm.sha256_of(binary),
            "deployed": [str(binary)],
        }}}), encoding="utf-8")
    return rec


# --- the record ----------------------------------------------------------------------

def test_the_record_is_written_only_for_verified_deploys(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "BUILD_RECORD", tmp_path / "midas_build.json")
    assert cm.write_build_record([{"target": "MidastouchAI.mq5", "ok": False,
                                   "deployed": [], "source": ""}]) is None
    assert not (tmp_path / "midas_build.json").exists(), \
        "an empty record would read as 'up to date'"


def test_the_record_carries_both_hashes_and_every_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "BUILD_RECORD", tmp_path / "midas_build.json")
    src = _source(tmp_path, "// one")
    ex5 = _binary(tmp_path)
    rec = cm.write_build_record([{
        "target": "MidastouchAI.mq5", "ok": True,
        "source": str(src), "source_sha256": cm.sha256_of(src),
        "ex5_sha256": cm.sha256_of(ex5),
        "deployed": [str(ex5), str(tmp_path / "repo" / "MidastouchAI.ex5")],
    }])
    data = json.loads(rec.read_text(encoding="utf-8"))
    entry = data["targets"]["MidastouchAI"]
    assert entry["source_sha256"] == cm.sha256_of(src)
    assert entry["ex5_sha256"] == cm.sha256_of(ex5)
    assert len(entry["deployed"]) == 2
    assert data["utc"].startswith("2026-")


def test_compile_one_returns_the_full_pair_not_only_the_short_fingerprint():
    """The 8-char fingerprint is for the console line; the record needs the whole hash."""
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    for key in ('"source": str(mq5) if ok else ""',
                '"source_sha256": sha256_of(mq5) if ok else ""',
                '"ex5_sha256": sha256_of(ex5) if ok and ex5.exists() else ""'):
        assert key in src, key


def test_main_writes_the_record_after_a_deploy():
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    body = src[src.index("def main()"):]
    assert "if args.deploy:" in body and "write_build_record(results)" in body


# --- the readiness leg ---------------------------------------------------------------

def test_a_recorded_pair_in_step_is_ok(tmp_path):
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    state, detail = lr.deployed_build_state(src, [ex5], _record(tmp_path, src, ex5))
    assert state == "ok" and str(src.stem) in detail


def test_a_source_edited_since_the_deploy_is_stale(tmp_path):
    """The case the leg exists for: the pins describe source that is not what runs."""
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    rec = _record(tmp_path, src, ex5)
    # No sleep here on purpose. This leg decides "stale" by comparing the recorded
    # source HASH against the file's hash (see `deployed_build_state`), so the verdict
    # does not depend on mtimes or on clock granularity at all. A `time.sleep(0.01)`
    # used to sit on this line: a wall-clock wait whose only possible contribution was
    # flakiness on a filesystem or VM where the write landed inside the same timestamp
    # tick. The assertion is about CONTENT, so the wait was never load-bearing.
    src.write_text("// edited after the deploy\n", encoding="utf-8")
    state, detail = lr.deployed_build_state(src, [ex5], rec)
    assert state == "stale" and "DIFFERENT source" in detail
    assert "compile_midas.py --deploy" in detail, "a refusal must name its remedy"


def test_a_replaced_binary_is_stale_even_when_the_source_is_untouched(tmp_path):
    """Timestamps cannot see this: the file is newer, and it is the wrong build."""
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    rec = _record(tmp_path, src, ex5)
    ex5.write_bytes(b"\x00someone else's build\xff")
    state, detail = lr.deployed_build_state(src, [ex5], rec)
    assert state == "stale" and "not the binary that was compiled" in detail


def test_a_missing_binary_is_stale_not_unconfirmed(tmp_path):
    """A chart would load nothing — that is a hard failure, not an unknown."""
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    rec = _record(tmp_path, src, ex5)
    ex5.unlink()
    state, detail = lr.deployed_build_state(src, [ex5], rec)
    assert state == "stale" and "no binary where a chart loads it" in detail


def test_a_missing_source_is_stale(tmp_path):
    state, _ = lr.deployed_build_state(tmp_path / "gone.mq5", [], None)
    assert state == "stale"


def test_no_record_with_a_newer_binary_warns_rather_than_passing(tmp_path):
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    os.utime(src, (time.time() - 600, time.time() - 600))
    state, detail = lr.deployed_build_state(src, [ex5], tmp_path / "absent.json")
    assert state == "unconfirmed", "newer is not proof: the compiler is not reproducible"
    assert "not proof" in detail


def test_no_record_with_a_binary_older_than_its_source_fails(tmp_path):
    src = _source(tmp_path)
    ex5 = _binary(tmp_path)
    os.utime(ex5, (time.time() - 3600, time.time() - 3600))
    state, detail = lr.deployed_build_state(src, [ex5], tmp_path / "absent.json")
    assert state == "stale" and "predates its source" in detail


def test_an_unreadable_record_is_unconfirmed_not_ok(tmp_path):
    src, ex5 = _source(tmp_path), _binary(tmp_path)
    rec = tmp_path / "midas_build.json"
    rec.write_text("{not json", encoding="utf-8")
    state, detail = lr.deployed_build_state(src, [ex5], rec)
    assert state == "unconfirmed" and "UNKNOWN" in detail


# --- what a VERIFY-ONLY run says -----------------------------------------------------
#
# MEASURED DEFECT, 2026-09-21. `compile_midas.py` without `--deploy` printed
# `NOT deployed — a chart still loads whatever is at <dest>` on every run. That sentence
# reports what the PROCESS did (it copied nothing) in the words of a report about the
# ARTIFACT (the deployed build is wrong). On this machine the same run that printed it
# also had a deployed binary in step with its source — so the alarm stood on a healthy
# state, and a reader learns to skip the one line that must never be skipped. The pins
# below hold the two facts apart, in both directions.

def _deployed_pair(tmp_path: Path, monkeypatch):
    """A source, the TWO copies a chart could load, and a record that matches them."""
    mq5 = _source(tmp_path)
    mql5_dir = tmp_path / "MQL5"
    copies = cm.deploy_paths(mq5, mql5_dir)
    for p in copies:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00binary\xff")
    monkeypatch.setattr(cm, "BUILD_RECORD", _record(tmp_path, mq5, copies[0]))
    return mq5, mql5_dir, copies


def test_a_verify_only_run_says_it_copied_nothing_without_an_alarm(tmp_path, monkeypatch):
    mq5, mql5_dir, _ = _deployed_pair(tmp_path, monkeypatch)
    text = "\n".join(cm.verify_only_lines(mq5, mql5_dir))
    assert "nothing was copied" in text, "the skip must be stated as a skip"
    assert "CURRENT" in text
    assert "STALE" not in text and "UNKNOWN" not in text, \
        "a deployed build in step with its source must not read as a defect"


def test_a_verify_only_run_still_names_a_stale_deployed_build(tmp_path, monkeypatch):
    """The alarm exists, and it fires on the fact it is for."""
    mq5, mql5_dir, _ = _deployed_pair(tmp_path, monkeypatch)
    mq5.write_text("// edited since the deploy\n", encoding="utf-8")
    text = "\n".join(cm.verify_only_lines(mq5, mql5_dir))
    assert "STALE" in text and "CURRENT" not in text
    assert "DIFFERENT source" in text, "the detail must say which two things differ"
    assert "live_readiness.py fails" in text, "and that the remedy is not optional"


def test_a_binary_replaced_after_the_deploy_is_stale_in_a_verify_only_run(tmp_path,
                                                                        monkeypatch):
    """Timestamps cannot see this one — the file is newer and it is the wrong build."""
    mq5, mql5_dir, copies = _deployed_pair(tmp_path, monkeypatch)
    copies[1].write_bytes(b"\x00someone else's build\xff")
    text = "\n".join(cm.verify_only_lines(mq5, mql5_dir))
    assert "STALE" in text and "not the binary that was compiled" in text


def test_an_uncheckable_build_is_UNKNOWN_and_never_renders_as_stale_or_current(
        tmp_path, monkeypatch):
    """No record: newer-than-source is not proof. Three states, one word each."""
    mq5, mql5_dir, _ = _deployed_pair(tmp_path, monkeypatch)
    monkeypatch.setattr(cm, "BUILD_RECORD", tmp_path / "absent.json")
    os.utime(mq5, (time.time() - 600, time.time() - 600))
    text = "\n".join(cm.verify_only_lines(mq5, mql5_dir))
    assert "UNKNOWN" in text and "STALE" not in text and "CURRENT" not in text
    assert "not a fault and not a pass" in text


def test_the_three_states_keep_three_distinct_words():
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    assert '{"ok": "CURRENT", "stale": "STALE", "unconfirmed": "UNKNOWN"}' in src


def test_the_verdict_is_readiness_own_and_not_a_second_opinion():
    """Two definitions of "stale" drift; the compiler must copy the gate's, not invent one."""
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    body = src[src.index("def verify_only_lines"):src.index("def compile_one")]
    assert "import live_readiness as lr" in body
    assert "lr.deployed_build_state(mq5, deploy_paths(mq5, mql5_dir)," in body
    assert "st_mtime" not in body, "no timestamp fallback of its own"


def test_the_run_stays_advisory_so_a_successful_compile_still_exits_zero():
    """The compile tool's exit code means "the compile worked"; readiness enforces the rest."""
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    assert "Advisory, not enforcing" in src
    body = src[src.index("if args.deploy:"):]
    assert "failed += 1" not in body, "a stale deploy must not change the exit code here"


def _emitted_strings(src_text: str) -> list[str]:
    """Every string constant the module can emit: comments and docstrings excluded.

    Structural rather than textual, because the first version of the pin below scanned
    lines containing `print(` — and a mutation that reassigned the whole list
    (`lines = [f"      NOT deployed …"]`) printed the retired sentence while walking
    straight through the scan (measured: it failed 4 other pins and passed that one).
    A guard that can be evaded by changing which expression holds the string is not a
    guard. The docstring exclusion is the other half: the comment recording WHY the
    sentence was wrong has to be allowed to quote it, or the documentation is punished
    for explaining the defect.
    """
    tree = ast.parse(src_text)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_the_old_sentence_that_named_neither_fact_correctly_is_gone():
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    offenders = [s for s in _emitted_strings(src) if "NOT deployed" in s]
    assert not offenders, offenders
    assert "for line in verify_only_lines(t, mql5_dir):" in src


def test_the_leg_is_wired_into_the_report_with_the_right_severity():
    """PASS on ok, FAIL when stale, WARN when unconfirmed — and it must check the copy a
    chart actually loads (the terminal's Experts tree), not only the repo's record."""
    src = (REPO / "scripts" / "live_readiness.py").read_text(encoding="utf-8")
    assert 'add("deployed EA build matches its source", build_state == "ok", build_detail,' in src
    assert 'blocking=(build_state == "stale")' in src
    assert 'term_data / "MQL5" / "Experts" / "MIDASTOUCH" / EA_EX5_NAME' in src
    assert 'build_state = "ok" if build_state == "stale" else "unconfirmed"' in src, \
        "an unchecked terminal copy must downgrade a clean build to WARN"
    assert 'report["build"]' in src

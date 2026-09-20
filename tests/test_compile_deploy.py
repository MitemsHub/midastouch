"""A verified compile that cannot be attached is not a deploy.

WHY THIS FILE EXISTS. On 2026-09-20 the terminal was running a **20:17** build while the
source compiled clean at 23:02 at a different size — because `scripts/compile_midas.py`
verified 0/0, printed the byte count, and then deleted the binary along with its scratch
folder. Nothing in the repo connected "the source compiles" to "the chart loads the thing
that compiled", so a chart could load an older EA than the one the pins describe, and the
only symptom was a size in a log line.

`--deploy` closes that by copying the verified `.ex5` to the two places that matter: the
repo copy (the record of what was built) and the terminal's own Experts tree (what a chart
actually loads). The registered, gated sequence for the paper arms remains
`scripts/midas_deploy_v118.py` — stop, copy, sha256-verify, relaunch, all gated on the
cert chain — and these tests keep the simple path from pretending to replace it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import compile_midas as cm  # noqa: E402

SOURCE = REPO / "mql5" / "MIDASTOUCH" / "MidastouchEA_does_not_exist.mq5"


def test_the_two_destinations_are_the_repo_and_the_terminal(tmp_path):
    mq5 = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
    mql5_dir = tmp_path / "MQL5"
    repo_copy, terminal_copy = cm.deploy_paths(mq5, mql5_dir)
    assert repo_copy == mq5.with_suffix(".ex5")
    # MT5 attaches from <data folder>\MQL5\Experts\<source folder>\ — the same folder name
    # the source lives in, which is what makes this derivable instead of remembered.
    assert terminal_copy == mql5_dir / "Experts" / "MIDASTOUCH" / "MidastouchAI.ex5"


def test_deploy_copies_the_verified_bytes_to_both(tmp_path):
    mq5 = tmp_path / "MIDASTOUCH" / "MidastouchAI.mq5"
    mq5.parent.mkdir(parents=True)
    mq5.write_text("// source", encoding="utf-8")
    ex5 = tmp_path / "scratch" / "MidastouchAI.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"\x00verified-binary\xff")
    mql5_dir = tmp_path / "data" / "MQL5"

    deployed = cm.deploy_ex5(ex5, mq5, mql5_dir)

    assert len(deployed) == 2
    for dest in deployed:
        assert Path(dest).read_bytes() == ex5.read_bytes(), dest
    assert (mql5_dir / "Experts" / "MIDASTOUCH" / "MidastouchAI.ex5").is_file()


def test_a_missing_source_never_deploys(tmp_path):
    """The failure shape must be explicit: `deployed: []`, not a missing key.

    A caller that reaches into the result for a deploy list must find an empty one when
    nothing was verified, so "no deploy happened" cannot be mistaken for "the key is new".
    """
    r = cm.compile_one(editor=Path("metaeditor64.exe"), mq5=SOURCE,
                       mql5_dir=tmp_path / "MQL5", deploy=True)
    assert r["ok"] is False and r["deployed"] == [] and r["fingerprint"] == ""
    assert "missing" in r["detail"]


def test_the_registered_deployer_is_still_named_as_the_gated_path():
    """Two deployers may not silently diverge: the simple one says what it is not."""
    doc = cm.__doc__ or ""
    assert "midas_deploy_v118.py" in doc, (
        "the manual --deploy must name the registered stop->copy->verify->relaunch "
        "sequence for the paper arms, or a reader will take it for the sanctioned deploy")
    assert "cert chain" in doc
    assert "--deploy" in doc


def test_the_deploy_step_runs_inside_the_compiles_lifetime():
    """A deploy placed after the scratch cleanup would copy nothing, ever.

    The scratch folder (holding the only produced binary) is removed in `finally` unless
    --keep is passed, so the copy has to happen before that. Pinned by position: the call
    to deploy_ex5 must precede the finally block's rmtree.
    """
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    call = src.index("deploy_ex5(ex5, mq5, mql5_dir) if ok and deploy")
    fingerprint = src.index("build_fingerprint(mq5, ex5) if ok else")
    cleanup = src.index("shutil.rmtree(scratch.parent / mq5.stem")
    assert call < cleanup and fingerprint < cleanup, (
        "deploy and fingerprint both read the scratch artifact, so both must run before "
        "the finally block deletes it — a later read raises instead of printing")
    # And main must PRINT the stored value rather than recomputing it after cleanup.
    assert 'fp = r.get("fingerprint") or ""' in src


def test_the_deploy_verifies_what_it_copied(tmp_path):
    """A copy that does not read back identical is a chart running an unknown build."""
    src = (REPO / "scripts" / "compile_midas.py").read_text(encoding="utf-8")
    body = src[src.index("def deploy_ex5("):src.index("def compile_one(")]
    assert "sha256_of(dest) != fresh" in body, \
        "deploy_ex5 must hash-compare each destination against the compiled artifact"
    assert "raise RuntimeError" in body

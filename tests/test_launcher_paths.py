"""A launcher may name only an interpreter and scripts that exist in THIS checkout.

WHY THIS FILE EXISTS. `tests/test_operator_docs.py` closed this class for documents:
an operator document may name only a script that exists, and may name a virtualenv
interpreter only while that venv exists. The launchers were never covered, and
measured on 2026-09-21 every one of the three defects below was live:

* `start_midas_watchdog.bat` -- the single entry point the "MIDAS Watchdog Autostart"
  scheduled task runs -- did `cd /d "...\\Projects\\Synthetic Indices Bot"` and then
  invoked that checkout's `.venv\\Scripts\\python.exe`. That venv does not exist, and
  this checkout has none either, so the task's real outcomes were "cmd cannot find the
  interpreter" or, where the sibling still holds a copy of the module, "the OTHER
  program's watchdog runs". On a VPS after a reboot that is an unguarded live arm.
* `scripts/_ps_deploy_ctl.ps1` and `scripts/_ps_monitor_ctl.ps1` hardcoded the same
  foreign checkout for both `$py` and `$repo`, while the scripts they manage live here.
  A control script pointed at another tree reports "0 running" about a program that is
  not this one -- which reads exactly like "nothing to see".
* `run-paper-pipeline-task.ps1` -- deleted with this file -- was the predecessor's
  weekly wrapper, naming `scripts/paper_pipeline.py`, which this repository does not
  contain.

The reason this is a *guard* and not a note in the health guide is the same reason the
doc check is mechanical: a launcher is read by the operating system, not by a human,
and a broken one fails silently in the one situation it was written for. So three
rules, applied to every committed `.bat`/`.cmd`/`.ps1` in the repo:

1. no absolute path to a checkout other than this one;
2. a `<venv>\\Scripts\\python.exe` reference is legal only while that venv exists
   *relative to this repository*, unless the file declares a fallback;
3. every `scripts/<name>.py` it names must exist here.

Rule 2 keeps the doc rule's escape hatch rather than banning venvs outright: create a
repo-local `.venv` and these references become legal again. The file never has to be
trusted, only checked.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Directories that are records, not the live surface. `archive/` holds retired bytes
#: and the CHANGELOG quotes history; neither is a launcher anyone runs today.
SKIP_DIRS = {"archive", ".git", ".venv", "__pycache__", "artifacts"}

LAUNCHER_SUFFIXES = (".bat", ".cmd", ".ps1")

#: Any absolute path into a checkout under `...\Projects\<name>`. The directory name is
#: captured so this repo's OWN name can be allowed and everything else refused. The
#: predecessor is known by two names (it staged a rename).
_ABS_PROJECT = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\r\n]*[\\/]+Desktop[\\/]+Projects[\\/]+([^\\/\"';)\r\n]+)", re.I)

#: A venv interpreter reference. The VENV DIRECTORY is captured whole (not the bare
#: `.venv`) so its existence can be tested the way the launcher itself resolves it.
#: `python` bare is always fine.
_VENV_INTERP = re.compile(r"([^\s\"']*(?:\.venv|venv|env))[\\/]Scripts[\\/]python\.exe", re.I)

#: Tokens a launcher uses for "my own directory" / "the repo root". They are substituted
#: before existence is tested, because `%~dp0.venv\...` is not a literal path.
_SELF_TOKENS = ("%~dp0", "$PSScriptRoot", "${PSScriptRoot}", "%HERE%", "$repo", "%repo%")

#: A script this repo is expected to contain.
_SCRIPT_REF = re.compile(r"scripts[\\/]([A-Za-z0-9_.\-]+\.py)")

#: How each language spells "use the system interpreter instead". Presence of one of
#: these in the same file makes a non-existent venv reference legal, because the file
#: is not depending on a venv that is not there.
_FALLBACK_MARKERS = ("set PY=python", '= "python"', "= 'python'", "get-command python",
                     "get-command py ", "join-path $repo \".venv")

#: A file may declare itself as never-run-here residue. It must then say so in the
#: first 12 lines (the operator-doc rule, applied to scripts), so the exemption cannot
#: be inherited silently by a file that becomes live again.
_RESIDUE_MARK = re.compile(r"NOT RUN HERE|RESIDUE|RETIRED|ARCHIVED", re.I)
_RESIDUE_BANNER_LINES = 12


def _launchers() -> list[Path]:
    out: list[Path] = []
    for p in sorted(REPO.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in LAUNCHER_SUFFIXES:
            continue
        rel = p.relative_to(REPO)
        if set(rel.parts) & SKIP_DIRS:
            continue
        out.append(p)
    return out


def _executable_lines(path: Path, text: str) -> str:
    """`text` with COMMENT lines removed.

    The rules are about what a launcher RUNS, not what it says. A file that documents
    the foreign path it used to point at -- which is how these fixes explain
    themselves -- must not be failed for the sentence describing its own repair. Only
    whole comment lines are dropped, so a trailing comment cannot hide a real path.
    """
    if path.suffix.lower() in (".bat", ".cmd"):
        marks = ("rem ", "rem\t", "::", "@rem ")
    else:
        marks = ("#",)
    keep = [ln for ln in text.splitlines()
            if not ln.lstrip().lower().startswith(marks)]
    return "\n".join(keep)


def _findings(path: Path, root: Path = REPO, own_name: str | None = None) -> dict[str, list[str]]:
    """The three rule violations in `path`, as {rule: [evidence]}.

    Parameterised by `root`/`own_name` so the fixture tests below can prove each rule
    fires on a synthetic tree rather than asserting on today's real files only.
    """
    own_name = own_name or root.name
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:_RESIDUE_BANNER_LINES])
    if _RESIDUE_MARK.search(head):
        return {"foreign": [], "interpreter": [], "scripts": []}
    text = _executable_lines(path, text)

    foreign, interpreter, scripts = [], [], []

    for m in _ABS_PROJECT.finditer(text):
        if m.group(1).lower() != own_name.lower():
            foreign.append(m.group(0))

    if not any(mark.lower() in text.lower() for mark in _FALLBACK_MARKERS):
        for m in _VENV_INTERP.finditer(text):
            prefix = m.group(1)
            for tok in _SELF_TOKENS:
                prefix = prefix.replace(tok, "")
            venv_dir = path.parent / prefix.strip("\\/")   # '%'/'$' forms already stripped
            if not (venv_dir / "Scripts" / "python.exe").exists():
                interpreter.append(m.group(0))

    for m in _SCRIPT_REF.finditer(text):
        if not (root / "scripts" / m.group(1)).is_file():
            scripts.append(m.group(0))

    return {"foreign": foreign, "interpreter": interpreter, "scripts": scripts}


# --------------------------------------------------------------------------- fixtures
# The detector is proven to fire before it is pointed at the live tree: a guard nobody
# has ever seen fail is a guard nobody knows works.

def _launcher(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_rule1_a_foreign_checkout_path_is_a_finding(tmp_path):
    p = _launcher(tmp_path, "x.bat",
                  'cd /d "C:\\Users\\U\\Desktop\\Projects\\Some Other Bot"\n')
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["foreign"] == [
        "C:\\Users\\U\\Desktop\\Projects\\Some Other Bot"]


def test_rule1_this_repo_s_own_name_is_not_s(tmp_path):
    p = _launcher(tmp_path, "x.bat",
                  'cd /d "C:\\Users\\U\\Desktop\\Projects\\MIDASTOUCH"\n')
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["foreign"] == []


def test_rule2_a_venv_that_does_not_exist_is_a_finding(tmp_path):
    p = _launcher(tmp_path, "x.bat",
                  'set PY="C:\\py\\.venv\\Scripts\\python.exe"\n')
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["interpreter"]


def test_rule2_a_declared_fallback_makes_the_same_reference_legal(tmp_path):
    p = _launcher(tmp_path, "x.bat",
                  'set PY=%~dp0.venv\\Scripts\\python.exe\n'
                  'if not exist "%PY%" set PY=python\n')
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["interpreter"] == []


def test_rule2_a_venv_that_does_exist_is_legal(tmp_path):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    p = _launcher(tmp_path, "x.bat", 'call ".venv\\Scripts\\python.exe" foo.py\n')
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["interpreter"] == []


def test_rule3_a_named_script_that_does_not_exist_is_a_finding(tmp_path):
    p = _launcher(tmp_path, "x.ps1", "& $py scripts/gone_missing.py\n")
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["scripts"] == [
        "scripts/gone_missing.py"]


def test_rule3_a_named_script_that_exists_is_legal(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "here.py").write_text("", encoding="utf-8")
    p = _launcher(tmp_path, "x.ps1", "& $py scripts/here.py\n")
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["scripts"] == []


def test_a_residue_banner_exempts_the_file_but_only_at_the_top(tmp_path):
    (tmp_path / "scripts").mkdir()
    banner = _launcher(tmp_path, "old.ps1",
                       "# RETIRED - kept as a record; NOT RUN HERE.\n& $py scripts/gone.py\n")
    assert _findings(banner, root=tmp_path, own_name="MIDASTOUCH")["scripts"] == []
    # The same marker buried far from the top does NOT exempt it: an exemption nobody
    # reads on opening the file is an exemption that outlives its reason.
    buried = "\n".join(["# filler"] * 20 + ["# RETIRED", "& $py scripts/gone.py"])
    p = _launcher(tmp_path, "buried.ps1", buried + "\n")
    assert _findings(p, root=tmp_path, own_name="MIDASTOUCH")["scripts"] == [
        "scripts/gone.py"]


# --------------------------------------------------------------------- the live tree

def test_the_repo_finds_at_least_one_launcher():
    """A scan that matches nothing would pass every rule vacuously."""
    assert len(_launchers()) >= 5


def test_no_committed_launcher_names_a_foreign_checkout_or_a_missing_tool():
    bad: list[str] = []
    for p in _launchers():
        found = _findings(p)
        for rule, hits in found.items():
            if hits:
                bad.append(f"{p.relative_to(REPO)}  [{rule}]  " + "; ".join(sorted(set(hits))))
    assert not bad, (
        "a committed launcher names something that does not resolve in this repository "
        "-- an interpreter that is not installed here, another checkout, or a script "
        "that no longer exists. A launcher is executed by the OS, not read by a human, "
        "so this fails silently in exactly the situation it was written for:\n  "
        + "\n  ".join(bad))


def test_the_watchdog_launcher_resolves_its_own_directory():
    """The autostart task's one entry point must not depend on where it is invoked from.

    This is the specific defect measured on 2026-09-21: the task runs the .bat with
    WorkingDirectory set to this repo, and the .bat then changed directory to another
    one. `%~dp0` is the fix and the assertion.
    """
    body = (REPO / "start_midas_watchdog.bat").read_text(encoding="utf-8")
    assert "%~dp0" in body, "the launcher must resolve the repo from its own location"
    assert "midas_watchdog.py" in body
    # Comments may explain the foreign checkout this used to point at; the executable
    # lines may not name it, and must not change directory anywhere.
    live = _executable_lines(REPO / "start_midas_watchdog.bat", body)
    assert "Synthetic Indices Bot" not in live
    assert "cd /d" not in live.lower()
    assert "pushd" in live.lower()


@pytest.mark.parametrize("task_script", ["scripts/register_midas_watchdog_task.ps1"])
def test_the_watchdog_task_still_points_at_that_one_launcher(task_script):
    """The registration script and the launcher must not drift apart: the task is
    registered against the .bat, so the .bat is what has to work."""
    src = (REPO / task_script).read_text(encoding="utf-8")
    assert "start_midas_watchdog.bat" in src

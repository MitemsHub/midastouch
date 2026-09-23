"""Is the supervisor's task one that runs whether or not anyone is signed in?

The XML fixtures below are the two shapes that matter, written from what Task Scheduler
actually emits: the task this machine had on 2026-09-22 (Interactive principal, no boot
trigger, no wake-to-run — it produced 54 passes in 25.3 h where 76 were due, with zero in
the 01:00-06:00 UTC hours) and the task this repository now registers. The detector is
pointed at both, so a reader that always says "unattended" fails the first one and a
reader that always says "no" fails the second.
"""
from __future__ import annotations

from types import SimpleNamespace

import unattended as un

NS = 'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"'

#: The shape measured on this machine 2026-09-22 13:52 local:
#: `MitemshubPaperSupervisor | state=Ready | logon=Interactive | runlevel=Limited`.
BEFORE = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" {NS}>
  <RegistrationInfo><Description>PAPER-ONLY supervisor</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-09-21T11:32:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition><Interval>PT20M</Interval><Duration>P3650D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>USER</UserId><LogonType>Interactive</LogonType>
      <RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
  </Settings>
</Task>
"""

AFTER = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" {NS}>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
    <TimeTrigger>
      <StartBoundary>2026-09-22T14:00:00</StartBoundary>
      <WakeToRun>true</WakeToRun>
      <Repetition><Interval>PT20M</Interval><Duration>P3650D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>USER</UserId><LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
</Task>
"""


def test_the_task_this_machine_had_fails_all_three_legs():
    p = un.task_posture(BEFORE)
    ok, reasons = un.unattended_verdict(p)
    assert ok is False
    assert p["logon_type"] == "Interactive"
    assert p["boot_trigger"] is False and p["wake_to_run"] is False
    assert len(reasons) == 3, reasons
    assert any("only while a user is signed in" in r for r in reasons)
    assert any("BootTrigger" in r for r in reasons)
    assert any("WakeToRun" in r for r in reasons)


def test_the_task_this_repo_registers_passes():
    p = un.task_posture(AFTER)
    ok, reasons = un.unattended_verdict(p)
    assert ok is True, reasons
    assert p["logon_type"] == "S4U"
    assert p["boot_trigger"] and p["wake_to_run"]
    assert p["repetition_interval_min"] == 20.0
    assert "boot" in p["triggers"]


def test_a_logon_only_trigger_is_not_a_boot_trigger():
    """The `MIDAS Watchdog Autostart` shape: correct logon type, wrong trigger."""
    xml = AFTER.replace("<BootTrigger><Enabled>true</Enabled></BootTrigger>", "")
    xml = xml.replace("<LogonType>S4U</LogonType>", "<LogonType>Interactive</LogonType>")
    xml = xml.replace("<WakeToRun>true</WakeToRun>", "")
    xml = xml.replace("<Triggers>", "<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger>")
    ok, reasons = un.unattended_verdict(un.task_posture(xml))
    assert ok is False and len(reasons) == 3


def test_an_unparseable_task_is_unconfirmed_not_unattended():
    ok, reasons = un.unattended_verdict(un.task_posture("<Task>not closed"))
    assert ok is False and reasons and "unreadable" in reasons[0]


def test_a_non_ascii_stamp_duration_is_none_never_zero():
    """`PT0S` is a real duration (no time limit); an unparsed one is not 0 minutes."""
    assert un.parse_iso_duration_min("PT0S") == 0.0
    assert un.parse_iso_duration_min("P3650D") == 3650 * 1440
    assert un.parse_iso_duration_min("PT20M") == 20.0
    assert un.parse_iso_duration_min("nonsense") is None
    assert un.task_posture(AFTER)["execution_time_limit"] == "PT0S"


def test_reading_an_unregistered_task_is_a_reason_not_a_crash():
    def runner(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="",
                               stderr="ERROR: The system cannot find the file specified.")
    posture, err = un.read_task_posture("MIDASTOUCH Arm Supervisor", runner=runner)
    assert posture is None and err == "not registered"
    ok, detail = un.verify_task("MIDASTOUCH Arm Supervisor", runner=runner)
    assert ok is False and "not registered" in detail and "-Apply" in detail


def test_absent_and_unanswerable_are_told_apart():
    """The two must not collapse: one means the task is gone, the other that the answer
    is unknown, and a report that renders the second as the first is a false report."""
    def missing(cmd, **kw):            # the real stderr shape measured 2026-09-22
        return SimpleNamespace(returncode=1, stdout="",
                               stderr="\n + FullyQualifiedErrorId : HRESULT "
                                      "0x80070002,Export-ScheduledTask")
    assert un.read_task_posture("x", runner=missing)[1] == "not registered"

    def denied(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="", stderr="Access is denied.")
    assert un.read_task_posture("x", runner=denied)[1] == "Access is denied."


def test_verify_task_reports_the_scheduler_own_answer():
    def runner(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout=AFTER, stderr="")
    ok, detail = un.verify_task("MIDASTOUCH Arm Supervisor", runner=runner)
    assert ok and "S4U" in detail and "wake-to-run=on" in detail

    def bad(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout=BEFORE, stderr="")
    ok, detail = un.verify_task("MitemshubPaperSupervisor", runner=bad)
    assert ok is False and "only while a user is signed in" in detail


def test_the_installer_registers_the_shape_this_reader_accepts():
    """The installer and the reader must not drift: one writes the task, one verifies it.

    The installer registers from TASK XML, not from the cmdlets, and that is pinned here
    because of a measured defect: on this machine the ScheduledTasks module's trigger
    objects expose exactly {Enabled, EndBoundary, ExecutionTimeLimit, Id, Repetition,
    StartBoundary, RandomDelay} - no WakeToRun - so `$trigger.WakeToRun = $true` threw,
    the error was non-terminating, and the first version of this installer went on to print
    "Registered" over a task it had never created.
    """
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scripts", "install_paper_task.ps1"), encoding="utf-8").read()
    assert "<LogonType>S4U</LogonType>" in src
    assert "<BootTrigger>" in src
    assert "<WakeToRun>true</WakeToRun>" in src
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in src
    # The XML path is now a CHAIN of progressively smaller definitions (see the order test below):
    # this scheduler refused the documented <Settings> block outright, and the fallback cmdlet
    # path cannot express WakeToRun. What must hold is that the XML form is tried FIRST, more than
    # once, with the wake flag in every variant.
    assert "Register-ScheduledTask -TaskName $TaskName -Xml $v.xml -Force -ErrorAction Stop" in src
    assert "foreach ($v in $variants)" in src and "$variants += @{ label = 'as written'" in src
    for must_keep in ("<WakeToRun>true</WakeToRun>", "<LogonType>S4U</LogonType>", "<BootTrigger>",
                      "<Repetition>"):
        assert must_keep in src, must_keep
        assert must_keep not in "\n".join(
            ln for ln in src.splitlines() if "re =" in ln), (
            f"{must_keep} must never be one of the droppable nodes")
    # The shape that CANNOT express wake-to-run must not come back.
    assert "$repeat.WakeToRun" not in src
    assert "-LogonType Interactive" not in src
    assert "-Unregister" in src
    # A registration that produced no task must never be reported as success, and the
    # legacy task must not be touched on that path.
    assert "REFUSING to report success" in src
    assert src.index("$made = Get-ScheduledTask -TaskName $TaskName") < \
        src.index("Unregister-ScheduledTask -TaskName $LegacyTaskName")
    assert src.index("Register-ScheduledTask -TaskName $TaskName") < \
        src.index("Unregister-ScheduledTask -TaskName $LegacyTaskName")
    # Both, on request, for an arm whose only recovery path is being changed.
    assert "-KeepLegacy" in src


def test_the_installers_settings_children_are_in_the_schedulers_required_order():
    """MEASURED 2026-09-22 on the first real `-Apply` on this machine: with the <Settings> children
    in an order that merely looked sensible, the scheduler REFUSED the XML -- "The task XML
    contains an unexpected node ... (32,7):UseUnifiedSchedulingEngine" -- and the installer fell
    back to the cmdlet path, which cannot express WakeToRun. The task then existed, ran on its
    cadence, and would have stayed silent on a sleeping host: the one leg this installer exists for
    was the one silently lost, and the only reason it was noticed is that the installer reads the
    scheduler's XML back and refuses to call the result a pass.

    The schema's order is pinned here so a later edit cannot quietly hand WakeToRun back to the
    fallback. Element ORDER is the whole assertion: every one of these names was already present in
    the broken version, which is why presence-only checks (above) could not catch it.
    """
    import os
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scripts", "install_paper_task.ps1"), encoding="utf-8").read()
    settings = re.search(r"\n  <Settings>(.*?)\n  </Settings>", src, re.S)
    assert settings, "the installer must register from task XML"
    body = settings.group(1)
    # IdleSettings nests children; keep only the <Settings> level (4-space indent in the template)
    order = re.findall(r"\n    <([A-Za-z]+)[ >]", body)
    required = ["AllowStartOnDemand", "MultipleInstancesPolicy", "WakeToRun", "Enabled",
                "IdleSettings", "ExecutionTimeLimit", "UseUnifiedSchedulingEngine"]
    for name in required:
        assert name in order, f"{name} missing from <Settings>"
    assert order.index("AllowStartOnDemand") == 0, "AllowStartOnDemand must come first"
    assert order.index("WakeToRun") < order.index("ExecutionTimeLimit") < \
        order.index("UseUnifiedSchedulingEngine"), "schema order, or the XML is refused outright"
    assert order.index("IdleSettings") < order.index("ExecutionTimeLimit"), \
        "IdleSettings precedes ExecutionTimeLimit in the schema"
    assert order.index("Enabled") < order.index("IdleSettings"), "Enabled precedes IdleSettings"
    # and the installer must never claim success when the scheduler refused the XML
    assert "wake-to-run is NOT set on this task" in src
    assert "REFUSING to report success" in src

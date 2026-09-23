"""Can this host hold supervision through a night?

The fixtures are the REAL `powercfg` output measured on this machine 2026-09-22, because
the question is not what the parser does with clean data — it is whether this program can
tell "the schedule will run" from "the schedule will evaporate when the lid shuts". It
could not: 54 passes in 25.3 h where 76 were due, with zero in the 01:00-06:00 UTC hours,
while `Sleep after` read `never` on AC and everyone involved believed the machine stayed
awake.
"""
from __future__ import annotations

from types import SimpleNamespace

import host_power as hp

#: `powercfg -a` on this host: the ONLY standby state is Modern Standby. There is no S3,
#: so there is no classic "sleep" for a wake timer to interrupt.
AVAILABLE = """The following sleep states are available on this system:
    Standby (S0 Low Power Idle) Network Connected
    Hibernate
    Fast Startup

The following sleep states are not available on this system:
    Standby (S1)
        The system firmware does not support this standby state.
    Standby (S3)
        This standby state is disabled when S0 low power idle is supported.
    Hybrid Sleep
        Standby (S3) is not available.
"""

#: `powercfg -query SCHEME_CURRENT SUB_SLEEP` on this host, trimmed to the settings under
#: test. Sleep/hibernate never on AC; wake timers DISABLED on both.
QUERY = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Current AC Power Setting Index: 0x00000000
      Current DC Power Setting Index: 0x00000000
    Power Setting GUID: 9d7815a6-7ee4-497e-8888-515a05f02364  (Hibernate after)
      GUID Alias: HIBERNATEIDLE
      Current AC Power Setting Index: 0x00000000
      Current DC Power Setting Index: 0x7fffffff
    Power Setting GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (Allow wake timers)
      GUID Alias: RTCWAKE
      Possible Setting Index: 000
      Possible Setting Friendly Name: Disable
      Current AC Power Setting Index: 0x00000000
      Current DC Power Setting Index: 0x00000000
"""

#: `powercfg -query SCHEME_CURRENT SUB_BUTTONS LIDACTION` — the setting is simply not
#: exposed on this build, which is itself the finding: the lid policy cannot be read.
LID_HIDDEN = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
"""

LASTWAKE = """Wake History Count - 1
Wake History [0]
  Wake Source Count - 0
"""

#: A server-shaped host: S3 (no Modern Standby), wake timers enabled, never sleeps.
SERVER_QUERY = QUERY.replace("GUID Alias: RTCWAKE\n      Possible Setting Index: 000\n"
                            "      Possible Setting Friendly Name: Disable\n"
                            "      Current AC Power Setting Index: 0x00000000",
                            "GUID Alias: RTCWAKE\n"
                            "      Current AC Power Setting Index: 0x00000001")
SERVER_AVAILABLE = ("The following sleep states are available on this system:\n"
                    "    Standby (S3)\n    Hibernate\n")


def test_this_laptop_cannot_be_certified_for_unattended_supervision():
    p = hp.posture_from(AVAILABLE, QUERY, LID_HIDDEN, LASTWAKE)
    assert p["s0_low_power_idle"] is True
    assert p["wake_timers_ac"] == 0 and p["wake_timers"] == "Disable"
    assert p["sleep_after_ac_s"] == 0            # "never" — and it did not help
    assert p["lid_action_ac"] is None            # not exposed on this build
    assert p["suitable"] is False
    assert len(p["problems"]) == 2, p["problems"]
    assert any("wake timers" in x for x in p["problems"])
    assert any("S0 Low Power Idle" in x for x in p["problems"])
    assert any("not exposed" in x for x in p["problems"])


def test_a_server_shaped_host_passes():
    p = hp.posture_from(SERVER_AVAILABLE, SERVER_QUERY, "", LASTWAKE)
    assert p["s0_low_power_idle"] is False
    assert p["wake_timers_ac"] == 1 and p["wake_timers"] == "Enable"
    assert p["suitable"] is True and p["problems"] == []


def test_a_standby_timer_that_is_not_never_is_a_problem():
    p = hp.posture_from(SERVER_AVAILABLE,
                        SERVER_QUERY.replace("GUID Alias: STANDBYIDLE\n"
                                             "      Minimum Possible Setting: 0x00000000\n"
                                             "      Current AC Power Setting Index: 0x00000000",
                                             "GUID Alias: STANDBYIDLE\n"
                                             "      Current AC Power Setting Index: 0x00000384"),
                        "", "")
    assert p["sleep_after_ac_s"] == 900
    assert p["suitable"] is False
    assert any("Sleep after" in x for x in p["problems"])


def test_the_query_reader_keeps_absent_settings_absent():
    """A value this program could not read must not be defaulted into a pass."""
    assert hp.parse_query(QUERY)["RTCWAKE"] == 0
    assert "LIDACTION" not in hp.parse_query(LID_HIDDEN)
    assert "NOTHING_HERE" not in hp.parse_query("")


def test_read_posture_uses_the_four_read_only_probes():
    seen: list[list[str]] = []

    def runner(cmd, **kw):
        seen.append(list(cmd))
        out = {"-a": AVAILABLE}.get(cmd[1], "")
        if cmd[1:3] == ["-query", "SCHEME_CURRENT"] and "SUB_SLEEP" in cmd:
            out = QUERY
        if "LIDACTION" in cmd:
            out = LID_HIDDEN
        if cmd[1] == "-lastwake":
            out = LASTWAKE
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    posture, err = hp.read_posture(runner=runner)
    assert err == "" and posture is not None
    assert posture["suitable"] is False
    assert all(c and c[0] == "powercfg" for c in seen)
    assert any("LIDACTION" in c for c in seen)


def test_unavailable_powercfg_is_unconfirmed_never_suitable():
    import subprocess

    def runner(cmd, **kw):
        raise FileNotFoundError("powercfg not found")

    posture, err = hp.read_posture(runner=runner)
    assert posture is None and "powercfg unavailable" in err
    del subprocess


def test_the_fix_is_printed_never_applied():
    """Rewriting a machine's power policy is the operator's act, not this program's."""
    cmds = hp.fix_commands()
    assert any("RTCWAKE 1" in c for c in cmds)
    assert any("STANDBYIDLE 0" in c for c in cmds)
    src = open(hp.__file__, encoding="utf-8").read()
    assert "subprocess" in src
    for forbidden in ("setacvalueindex", ):
        # Only ever as a printed string, never as an executed argument list.
        assert f'["powercfg", "-set' not in src and f"'powercfg', '-set" not in src
        assert forbidden in src

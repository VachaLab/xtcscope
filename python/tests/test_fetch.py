"""Fetching the frames and opening the viewer (steps 8-11), with a fake agent."""

import os
import signal
import tempfile
import threading
import time
from pathlib import Path

from conftest import FAKE_XTC
from xtcscope.cli import main
from xtcscope.errors import EXIT_AGENT, EXIT_INTERRUPTED, EXIT_SSH, EXIT_VIEWER


def run_full(*extra):
    """Run xtcscope without --dry-run, with the fake viamd as the viewer."""
    return main(["--viewer", "viamd", *extra])


def temp_dirs():
    """The script's temporary directories that currently exist."""
    return set(Path(tempfile.gettempdir()).glob("xtcscope-*"))


def test_full_run(fake_job, capsys):
    """Frames are fetched over the master connection, which is closed before the
    viewer opens the GRO and the complete XTC; everything is removed afterwards."""
    before = temp_dirs()
    assert run_full("-n", "7") == 0

    calls = fake_job.calls()
    kinds = [c[0] for c in calls]
    assert kinds.count("agent") == 1 and kinds.count("viewer") == 1
    agent = next(c for c in calls if c[0] == "agent")
    assert agent[1:] == ["extract", "--xtc", str(fake_job.work / "md.xtc"), "--frames", "7"]

    viewer = next(c for c in calls if c[0] == "viewer")
    gro, xtc, size, same = viewer[1:]
    assert gro == str(fake_job.input / "conf.gro")
    assert xtc.endswith("/md.last7.xtc")
    assert size == len(FAKE_XTC) and same, "the viewer got the complete file"

    exit_index = next(i for i, c in enumerate(calls) if c[0] == "ssh" and "exit" in c)
    assert exit_index < kinds.index("viewer"), "connection closed before the viewer"
    assert sum(c[0] == "ssh" and "-M" in c for c in calls) == 1
    assert temp_dirs() == before, "temporary directory removed"
    assert list(fake_job.sockets.iterdir()) == [], "no control socket left"
    err = capsys.readouterr().err
    assert "Fetching 10 frames (0-18 ps, 1.0 kB) from md.xtc" in err
    assert "Opening conf.gro and md.last7.xtc in viamd" in err


def test_warnings_are_shown(fake_job, monkeypatch, capsys):
    """Agent warnings become WARN lines; the run still succeeds."""
    monkeypatch.setenv("FAKE_AGENT_MODE", "warn")
    assert run_full() == 0
    assert "WARN    unexpected data after the last frame (trailing_data)" in capsys.readouterr().err


def test_other_stderr_lines_are_ignored(fake_job, monkeypatch, capsys):
    """Non-JSON lines on stderr (from ssh, say) don't disturb a successful run."""
    monkeypatch.setenv("FAKE_AGENT_MODE", "noise")
    assert run_full() == 0


def test_agent_error(fake_job, monkeypatch, capsys):
    """An error event from the agent is exit 8 with its message; no viewer."""
    monkeypatch.setenv("FAKE_AGENT_MODE", "error")
    assert run_full() == EXIT_AGENT
    assert "the first frame's header is invalid (xtc_invalid)" in capsys.readouterr().err
    assert not any(c[0] == "viewer" for c in fake_job.calls())


def test_agent_not_installed(fake_job, capsys):
    """A missing agent (nice exits 127) says to run the installer."""
    fake_job.agent.unlink()
    assert run_full() == EXIT_AGENT
    assert "xtcscope-agent is not installed on node42" in capsys.readouterr().err


def test_agent_crash(fake_job, monkeypatch, capsys):
    """An agent that dies without an event: exit 8 with what it printed."""
    monkeypatch.setenv("FAKE_AGENT_MODE", "crash")
    assert run_full() == EXIT_AGENT
    err = capsys.readouterr().err
    assert "exited with 139" in err and "Segmentation fault" in err


def test_incomplete_file(fake_job, monkeypatch, capsys):
    """A file shorter than the agent announced is exit 8; no viewer."""
    monkeypatch.setenv("FAKE_AGENT_MODE", "short")
    assert run_full() == EXIT_AGENT
    assert "incomplete" in capsys.readouterr().err
    assert not any(c[0] == "viewer" for c in fake_job.calls())


def test_connection_lost_during_fetch(fake_job, monkeypatch):
    """ssh failing during the extract is exit 7."""
    monkeypatch.setenv("FAKE_SSH_DROP", "1")
    assert run_full() == EXIT_SSH


def test_viewer_cannot_start(fake_job, capsys):
    """A viewer that exists but can't be executed is exit 9."""
    viewer = fake_job.root / "bin" / "broken-viewer"
    viewer.write_text("#!/nonexistent/interpreter\n")
    viewer.chmod(0o755)
    # an absolute path: given a bare name, exec would skip the broken file
    # and run the next viewer of that name on PATH, if there is one
    assert main(["--viewer", str(viewer)]) == EXIT_VIEWER
    assert "Could not start the viewer" in capsys.readouterr().err


def test_viewer_exit_code_is_only_a_warning(fake_job, monkeypatch, capsys):
    """A viewer exiting non-zero is reported, but the run counts as done."""
    monkeypatch.setenv("FAKE_VIEWER_EXIT", "3")
    assert run_full() == 0
    assert "The viewer exited with code 3" in capsys.readouterr().err


def test_ctrl_c_during_fetch(fake_job, monkeypatch):
    """Ctrl-C while the agent runs: the agent is stopped, exit 130, nothing left."""
    pid_file = fake_job.root / "agent.pid"
    monkeypatch.setenv("FAKE_AGENT_MODE", "sleep")
    monkeypatch.setenv("FAKE_AGENT_PID", str(pid_file))
    before = temp_dirs()

    def interrupt():
        """Send SIGINT to this process once the agent is running."""
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=interrupt, daemon=True).start()
    started = time.monotonic()
    assert run_full() == EXIT_INTERRUPTED
    assert time.monotonic() - started < 10

    agent_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(agent_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the agent is still running")
    assert temp_dirs() == before
    assert not any(c[0] == "viewer" for c in fake_job.calls())

"""--remote: the backend runs as `xtcscope _backend` on a fake host, the viewer here."""

import json
import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from conftest import FAKE_AGENT, FAKE_XTC, write_executable
from xtcscope.agent import FetchPlan, fetch_frames
from xtcscope.cli import main
from xtcscope.errors import (
    EXIT_AGENT,
    EXIT_BACKEND,
    EXIT_INTERRUPTED,
    EXIT_NO_FILE,
    EXIT_NO_JOB,
    EXIT_SSH,
    XtcscopeError,
)

STUBS = Path(__file__).resolve().parent / "stubs"
HOST = "desk7"

# xtcscope "installed" on the fake host: the package from this checkout, with the
# qq stand-in ahead of the real qq, and a version or protocol overridden on request
REMOTE_XTCSCOPE = """\
#!{python}
import os, sys
sys.path.insert(0, {stubs!r})
import xtcscope, xtcscope.errors
if os.environ.get("FAKE_REMOTE_VERSION"):
    xtcscope.__version__ = os.environ["FAKE_REMOTE_VERSION"]
if os.environ.get("FAKE_REMOTE_PROTOCOL"):
    xtcscope.errors.PROTOCOL = int(os.environ["FAKE_REMOTE_PROTOCOL"])
from xtcscope.cli import main
sys.exit(main())
"""


@pytest.fixture
def remote(fake_job, monkeypatch):
    """
    The fake host "desk7", with xtcscope and an agent in its own home.

    The frontend runs in this process; the backend runs in subprocesses "on"
    desk7 (the fake ssh gives it desk7's $HOME) and reaches node42 by itself.
    Returns desk7's home.
    """
    home = fake_job.root / "desk7-home"
    script = home / "xtcscope" / "xtcscope"
    script.parent.mkdir(parents=True)
    script.write_text(REMOTE_XTCSCOPE.format(python=sys.executable, stubs=str(STUBS)))
    script.chmod(0o755)
    write_executable(home / "xtcscope" / "xtcscope-agent", FAKE_AGENT)
    hosts = {"node42": str(fake_job.home), HOST: str(home)}
    monkeypatch.setenv("FAKE_HOSTS", json.dumps(hosts))
    monkeypatch.setenv("FAKE_QQ_JOB", str(fake_job.describe()))
    return home


def run_remote(*extra: str) -> int:
    """Run xtcscope --remote desk7 for job 123.pbs, with the fake viamd as the viewer."""
    return main(["--remote", HOST, "123.pbs", "--viewer", "viamd", *extra])


def masters(fake_job, host: str) -> int:
    """How many master connections were opened to `host`."""
    return sum("-M" in c for c in fake_job.ssh_calls(host))


def temp_dirs() -> set[Path]:
    """The frontend's temporary directories that currently exist."""
    return set(Path(tempfile.gettempdir()).glob("xtcscope-*"))


def test_full_run_through_the_node(remote, fake_job, capsys):
    """desk7 resolves the job and reaches node42; the GRO and frames come here."""
    before = temp_dirs()
    assert run_remote("-n", "4") == 0

    calls = fake_job.calls()
    assert masters(fake_job, HOST) == 1, "one authentication to the host"
    assert masters(fake_job, "node42") == 1, "the host connects to the node"
    agent = next(c for c in calls if c[0] == "agent")
    assert agent[1:] == ["extract", "--xtc", str(fake_job.work / "md.xtc"), "--frames", "4"]

    viewer_index, viewer = next((i, c) for i, c in enumerate(calls) if c[0] == "viewer")
    gro, xtc = viewer[1], viewer[2]
    assert gro != str(fake_job.input / "conf.gro") and gro.endswith("/conf.gro"), "a copy"
    assert xtc.endswith("/md.last4.xtc") and viewer[-2:] == [len(FAKE_XTC), True]

    closing = [i for i, c in enumerate(calls) if c[0] == "ssh" and "exit" in c]
    assert closing and max(closing) < viewer_index, "connections closed before the viewer"
    assert any("_backend close" in c[-1] for c in fake_job.ssh_calls(HOST))
    assert list(fake_job.sockets.iterdir()) == [], "no control socket left"
    assert temp_dirs() == before

    err = capsys.readouterr().err
    assert "INFO    Connecting to desk7" in err
    assert "INFO    [desk7] Job 123.pbs (mdrun) runs on node42" in err
    assert "INFO    [desk7] Reading the working directory through node42" in err
    assert "INFO    Copying conf.gro from desk7" in err


def test_shared_storage_on_the_host(remote, fake_job):
    """A working directory the host reads directly: nothing connects to the node."""
    fake_job.describe(shared=True)
    assert run_remote() == 0
    assert fake_job.ssh_calls("node42") == []
    viewer = next(c for c in fake_job.calls() if c[0] == "viewer")
    assert viewer[-2:] == [len(FAKE_XTC), True]


def test_xtcscope_missing_on_the_host(remote, capsys):
    """No xtcscope on the host is exit 10, saying where to install it."""
    (remote / "xtcscope" / "xtcscope").unlink()
    assert run_remote() == EXIT_BACKEND
    assert "xtcscope is not installed on desk7; install it there first." in capsys.readouterr().err


def test_protocol_mismatch(remote, monkeypatch, capsys):
    """Another protocol on the host is exit 10, naming both versions."""
    monkeypatch.setenv("FAKE_REMOTE_PROTOCOL", "2")
    monkeypatch.setenv("FAKE_REMOTE_VERSION", "0.3.0")
    assert run_remote() == EXIT_BACKEND
    err = capsys.readouterr().err
    assert "xtcscope on desk7 (0.3.0) speaks backend protocol 2" in err
    assert "install the same version on both machines" in err


def test_version_mismatch_with_the_same_protocol(remote, monkeypatch, capsys):
    """A different version that speaks the same protocol only warns."""
    monkeypatch.setenv("FAKE_REMOTE_VERSION", "0.2.9")
    assert run_remote() == 0
    assert "WARN    xtcscope on desk7 is 0.2.9, this one is" in capsys.readouterr().err


def test_errors_on_the_host_keep_their_exit_codes(remote, fake_job, capsys):
    """A failure on the host exits as it would locally, its message tagged with the host."""
    assert main(["--remote", HOST, "999.pbs", "--viewer", "viamd"]) == EXIT_NO_JOB

    fake_job.describe(input_dir=str(fake_job.root / "gone"))
    assert run_remote() == EXIT_NO_FILE
    assert "ERROR   [desk7] Input directory" in capsys.readouterr().err


def test_agent_missing_on_the_host(remote, fake_job, capsys):
    """Direct access on a host without an agent is exit 8, from the host."""
    fake_job.describe(shared=True)
    (remote / "xtcscope" / "xtcscope-agent").unlink()
    assert run_remote() == EXIT_AGENT
    assert "[desk7] xtcscope-agent is not installed on this machine" in capsys.readouterr().err


def test_host_unreachable(remote, monkeypatch, capsys):
    """A failed connection to the host is exit 7 with ssh's reason."""
    monkeypatch.setenv("FAKE_SSH_FAIL", HOST)
    assert run_remote() == EXIT_SSH
    assert "Could not connect to desk7: ssh: connect to host desk7" in capsys.readouterr().err


def test_connection_to_the_node_lost(remote, monkeypatch, capsys):
    """The host losing the node during the fetch is exit 7, naming the node."""
    monkeypatch.setenv("FAKE_SSH_DROP", "1")
    assert run_remote() == EXIT_SSH
    assert "Lost the connection to node42" in capsys.readouterr().err


def test_needs_a_job_id(remote):
    """--remote without a job ID is a usage error."""
    with pytest.raises(SystemExit) as exc:
        main(["--remote", HOST, "--viewer", "viamd"])
    assert exc.value.code == 2


def test_dry_run(remote, fake_job, capsys):
    """--dry-run names the host, prints the nested command, fetches nothing."""
    assert run_remote("--dry-run") == 0
    out = capsys.readouterr().out
    assert "backend  desk7" in out
    assert f"gro      desk7:{fake_job.input / 'conf.gro'} (48213 atoms)" in out
    extract = next(line for line in out.splitlines() if line.startswith("extract"))
    assert "_backend fetch" in extract and "--node node42" in extract
    assert not any(c[0] == "agent" for c in fake_job.calls())
    assert list(fake_job.sockets.iterdir()) == []


def test_debug_lines_from_the_host(remote, capsys):
    """--debug is passed on, and the host's DEBUG lines come back tagged."""
    assert run_remote("--debug") == 0
    assert "DEBUG   [desk7] $ ssh" in capsys.readouterr().err


def test_ctrl_c_during_a_remote_fetch(remote, fake_job, monkeypatch):
    """Ctrl-C while the agent runs on the node: it is stopped, exit 130, nothing left."""
    pid_file = fake_job.root / "agent.pid"
    monkeypatch.setenv("FAKE_AGENT_MODE", "sleep")
    monkeypatch.setenv("FAKE_AGENT_PID", str(pid_file))

    def interrupt():
        """Send SIGINT to this process once the agent is running."""
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=interrupt, daemon=True).start()
    assert run_remote() == EXIT_INTERRUPTED

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
    assert list(fake_job.sockets.iterdir()) == []


def test_backend_failure_in_fetch_keeps_its_exit_code(tmp_path):
    """A backend error event from fetch is raised with the exit code it carries."""
    event = {"event": "error", "code": "backend", "message": "Could not connect", "exit_code": 7}
    script = f"import json, sys; print(json.dumps({event!r}), file=sys.stderr); sys.exit(7)"
    plan = FetchPlan([sys.executable, "-c", script], "node42", 255)
    with pytest.raises(XtcscopeError) as exc:
        fetch_frames(plan, "md.xtc", tmp_path / "out.xtc")
    assert exc.value.exit_code == EXIT_SSH
    assert str(exc.value) == "Could not connect"

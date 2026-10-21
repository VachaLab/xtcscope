"""Direct access: the working directory is read on this machine, with no SSH at all."""

import shlex

from conftest import FAKE_XTC
from xtcscope.cli import main
from xtcscope.errors import EXIT_AGENT, EXIT_NO_WORK_DIR


def run_full(*extra):
    """Run xtcscope without --dry-run, with the fake viamd as the viewer."""
    return main(["--viewer", "viamd", *extra])


def test_shared_storage_is_read_directly(fake_job, capsys):
    """A shared working directory: the local agent runs, no ssh call is made."""
    fake_job.shared = True
    assert run_full("-n", "5") == 0

    calls = fake_job.calls()
    assert fake_job.ssh_calls() == []
    agent = next(c for c in calls if c[0] == "agent")
    assert agent[1:] == ["extract", "--xtc", str(fake_job.work / "md.xtc"), "--frames", "5"]
    viewer = next(c for c in calls if c[0] == "viewer")
    assert viewer[-2:] == [len(FAKE_XTC), True], "the viewer got the complete file"

    err = capsys.readouterr().err
    assert "Reading the working directory directly (shared storage)" in err


def test_job_on_this_machine_is_read_directly(fake_job, capsys):
    """The job's main node is this machine: no ssh, even without shared storage."""
    fake_job.local_names = ("node42.example.cz", "node42")
    assert run_full() == 0
    assert fake_job.ssh_calls() == []
    err = capsys.readouterr().err
    assert "Reading the working directory directly (the job runs on this machine)" in err


def test_node_access_is_the_default(fake_job, capsys):
    """Neither shared nor local: the 0.1 behaviour, through the node."""
    assert run_full() == 0
    assert sum("-M" in c for c in fake_job.ssh_calls()) == 1
    assert "Reading the working directory through node42" in capsys.readouterr().err


def test_access_node_overrides_a_local_job(fake_job, capsys):
    """--access node connects to the node even when the job runs here."""
    fake_job.local_names = ("node42",)
    assert run_full("--access", "node") == 0
    assert sum("-M" in c for c in fake_job.ssh_calls()) == 1
    assert "through node42 (--access node)" in capsys.readouterr().err


def test_access_direct_overrides_the_rule(fake_job, capsys):
    """--access direct reads a directory that is neither shared nor local."""
    assert run_full("--access", "direct") == 0
    assert fake_job.ssh_calls() == []
    assert "directly (--access direct)" in capsys.readouterr().err


def test_access_direct_without_the_directory(fake_job, capsys):
    """--access direct with no working directory here is exit 4, before any connection."""
    (fake_job.work / "md.xtc").unlink()
    fake_job.work.rmdir()
    assert run_full("--access", "direct") == EXIT_NO_WORK_DIR
    assert fake_job.calls() == []
    assert "is not readable on this machine" in capsys.readouterr().err


def test_missing_local_agent(fake_job, capsys):
    """Direct access without a local agent is exit 8, naming where it was looked for."""
    fake_job.shared = True
    fake_job.agent.unlink()
    assert run_full() == EXIT_AGENT
    err = capsys.readouterr().err
    assert "xtcscope-agent is not installed on this machine" in err
    assert str(fake_job.agent) in err


def test_agent_override(fake_job, monkeypatch, tmp_path):
    """$XTCSCOPE_AGENT points direct access at another agent."""
    fake_job.shared = True
    moved = tmp_path / "elsewhere" / "agent"
    moved.parent.mkdir()
    fake_job.agent.rename(moved)
    monkeypatch.setenv("XTCSCOPE_AGENT", str(moved))
    assert run_full() == 0


def test_dry_run_shows_the_access(fake_job, capsys):
    """--dry-run names the backend and the access, and prints a local extract command."""
    fake_job.shared = True
    assert main(["--dry-run", "--viewer", "viamd"]) == 0
    out = capsys.readouterr().out
    assert "backend  this machine" in out
    assert "access   direct (shared storage)" in out
    extract = next(line for line in out.splitlines() if line.startswith("extract"))
    words = shlex.split(extract)
    assert words[1:3] == ["bash", "-c"]
    assert words[3].startswith(f"nice -n 19 ionice -c3 {fake_job.agent} extract ")
    assert fake_job.calls() == []


def test_missing_requested_file_names_the_local_directory(fake_job, capsys):
    """With direct access, messages name the directory without a node prefix."""
    fake_job.shared = True
    assert run_full("--xtc", "run/md.xtc") != 0
    assert f"There is no run/md.xtc in {fake_job.work}." in capsys.readouterr().err

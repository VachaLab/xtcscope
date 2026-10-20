"""The whole flow up to --dry-run, with a fake `ssh` and qq replaced by a stub.

The fake ssh runs remote commands in a local bash, so the listing command is
exercised for real, and logs every invocation for the assertions.
"""

import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

FAKE_SSH = textwrap.dedent(
    """\
    #!{python}
    import json, os, subprocess, sys
    args = sys.argv[1:]
    with open(os.environ["FAKE_SSH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    if os.environ.get("FAKE_SSH_FAIL") and "-M" in args:
        print("ssh: connect to host node42: Connection refused", file=sys.stderr)
        sys.exit(255)
    if "-M" in args or "-O" in args:
        sys.exit(0)
    # ssh -S <ctl> <node> <command>
    sys.exit(subprocess.run(["bash", "-c", args[-1]]).returncode)
    """
)


@pytest.fixture
def setup(xtcscope, tmp_path, monkeypatch):
    """A fake job: input dir with GRO files, work dir with XTCs, fake ssh and viewer."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text(FAKE_SSH.format(python=sys.executable))
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    viewer = bin_dir / "viamd"
    viewer.write_text("#!/bin/sh\n")
    viewer.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    log = tmp_path / "ssh.log"
    monkeypatch.setenv("FAKE_SSH_LOG", str(log))

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "conf.gro").write_text("title\n48213\n")
    work_dir = tmp_path / "scratch"
    work_dir.mkdir()
    (work_dir / "md.xtc").write_bytes(bytes.fromhex("000007cb0000bc55") + b"\0" * 100)

    job = xtcscope.Job("123.pbs", "mdrun", "node42", work_dir, input_dir)
    monkeypatch.setattr(xtcscope, "find_job", lambda job_id: job)
    monkeypatch.setattr(xtcscope, "ssh_timeout", lambda: 60)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    return {"input": input_dir, "work": work_dir, "log": log}


def ssh_calls(setup):
    """The argument lists the fake ssh was called with."""
    return [json.loads(line) for line in setup["log"].read_text().splitlines()]


def test_dry_run_prints_the_plan(xtcscope, setup, capsys):
    """Dry run: files chosen, commands printed, one master connection, then closed."""
    code = xtcscope.main(["--dry-run", "--viewer", "viamd", "-n", "5"])
    out = capsys.readouterr().out
    assert code == 0
    assert "node     node42" in out
    assert f"gro      {setup['input'] / 'conf.gro'} (48213 atoms)" in out
    assert f"xtc      {setup['work'] / 'md.xtc'} (48213 atoms)" in out
    assert "extract --xtc" in out and "--frames 5" in out
    assert "md.last5.xtc" in out
    assert "view     viamd " in out

    calls = ssh_calls(setup)
    assert sum("-M" in c for c in calls) == 1, "exactly one authenticating connection"
    master = next(c for c in calls if "-M" in c)
    assert "ConnectTimeout=60" in master and master[-1] == "node42"
    assert calls[-1][-3:] == ["-O", "exit", "node42"], "master connection closed"


def test_atom_count_mismatch(xtcscope, setup, capsys):
    """Different atom counts stop the run with exit 6 and a hint."""
    (setup["input"] / "conf.gro").write_text("title\n1000\n")
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_MISMATCH
    assert "compressed-x-grps" in capsys.readouterr().err


def test_input_dir_not_accessible(xtcscope, setup, monkeypatch):
    """A missing input directory is exit 5, before any SSH connection."""
    import shutil

    shutil.rmtree(setup["input"])
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_NO_FILE
    assert not setup["log"].exists()


def test_work_dir_not_accessible(xtcscope, setup):
    """A working directory that is gone on the node is exit 4."""
    import shutil

    shutil.rmtree(setup["work"])
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_NO_WORK_DIR


def test_ssh_failure(xtcscope, setup, monkeypatch, capsys):
    """A failed connection is exit 7 with ssh's own reason."""
    monkeypatch.setenv("FAKE_SSH_FAIL", "1")
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_SSH
    assert "Connection refused" in capsys.readouterr().err


def test_several_xtc_files_need_a_choice(xtcscope, setup, capsys):
    """Without a terminal, several XTC files need --xtc; with it, the run proceeds."""
    (setup["work"] / "other.xtc").write_bytes(bytes.fromhex("000007cb0000bc55"))
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_NO_FILE
    assert xtcscope.main(["--dry-run", "--viewer", "viamd", "--xtc", "md.xtc"]) == 0


def test_temporary_directory_is_removed(xtcscope, setup, capsys):
    """The run leaves no temporary directory behind."""
    import tempfile

    before = set(Path(tempfile.gettempdir()).glob("xtcscope-*"))
    xtcscope.main(["--dry-run", "--viewer", "viamd"])
    assert set(Path(tempfile.gettempdir()).glob("xtcscope-*")) == before


def test_viewer_from_environment(xtcscope, setup, monkeypatch, capsys):
    """XTCSCOPE_VIEWER sets the default viewer."""
    monkeypatch.setenv("XTCSCOPE_VIEWER", "viamd")
    assert xtcscope.main(["--dry-run"]) == 0
    assert "view     viamd " in capsys.readouterr().out


def test_bad_arguments(xtcscope):
    """Paths, wrong suffixes and -n 0 are argparse errors (exit 2)."""
    for argv in (["--gro", "dir/conf.gro"], ["--xtc", "md.trr"], ["-n", "0"]):
        with pytest.raises(SystemExit) as exc:
            xtcscope.main(argv)
        assert exc.value.code == 2

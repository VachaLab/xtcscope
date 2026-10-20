"""The flow up to --dry-run: job, files, one SSH connection, checks."""

import shutil
import tempfile
from pathlib import Path

import pytest


def ssh_calls(job):
    """The argument lists the fake ssh was called with."""
    return [c[1:] for c in job.calls() if c[0] == "ssh"]


def test_dry_run_prints_the_plan(xtcscope, fake_job, capsys):
    """Dry run: files chosen, commands printed, one master connection, then closed."""
    code = xtcscope.main(["--dry-run", "--viewer", "viamd", "-n", "5"])
    out = capsys.readouterr().out
    assert code == 0
    assert "node     node42" in out
    assert f"gro      {fake_job.input / 'conf.gro'} (48213 atoms)" in out
    assert f"xtc      {fake_job.work / 'md.xtc'} (48213 atoms)" in out
    assert "extract --xtc" in out and "--frames 5" in out
    assert "md.last5.xtc" in out
    assert "view     viamd " in out

    calls = ssh_calls(fake_job)
    assert sum("-M" in c for c in calls) == 1, "exactly one authenticating connection"
    master = next(c for c in calls if "-M" in c)
    assert "ConnectTimeout=60" in master and master[-1] == "node42"
    assert calls[-1][-3:] == ["-O", "exit", "node42"], "master connection closed"
    assert not any(c[0] == "agent" for c in fake_job.calls()), "nothing extracted"


def test_atom_count_mismatch(xtcscope, fake_job, capsys):
    """Different atom counts stop the run with exit 6 and a hint."""
    (fake_job.input / "conf.gro").write_text("title\n1000\n")
    assert xtcscope.main(["--viewer", "viamd"]) == xtcscope.EXIT_MISMATCH
    assert "compressed-x-grps" in capsys.readouterr().err
    assert not any(c[0] == "agent" for c in fake_job.calls())


def test_input_dir_not_accessible(xtcscope, fake_job):
    """A missing input directory is exit 5, before any SSH connection."""
    shutil.rmtree(fake_job.input)
    assert xtcscope.main(["--viewer", "viamd"]) == xtcscope.EXIT_NO_FILE
    assert fake_job.calls() == []


def test_work_dir_not_accessible(xtcscope, fake_job):
    """A working directory that is gone on the node is exit 4."""
    shutil.rmtree(fake_job.work)
    assert xtcscope.main(["--viewer", "viamd"]) == xtcscope.EXIT_NO_WORK_DIR


def test_ssh_failure(xtcscope, fake_job, monkeypatch, capsys):
    """A failed connection is exit 7 with ssh's own reason."""
    monkeypatch.setenv("FAKE_SSH_FAIL", "1")
    assert xtcscope.main(["--viewer", "viamd"]) == xtcscope.EXIT_SSH
    assert "Connection refused" in capsys.readouterr().err


def test_several_xtc_files_need_a_choice(xtcscope, fake_job, capsys):
    """Without a terminal, several XTC files need --xtc; with it, the run proceeds."""
    (fake_job.work / "other.xtc").write_bytes(bytes.fromhex("000007cb0000bc55"))
    assert xtcscope.main(["--dry-run", "--viewer", "viamd"]) == xtcscope.EXIT_NO_FILE
    assert xtcscope.main(["--dry-run", "--viewer", "viamd", "--xtc", "md.xtc"]) == 0


def test_temporary_directory_is_removed(xtcscope, fake_job, capsys):
    """A dry run leaves no temporary directory behind."""
    before = set(Path(tempfile.gettempdir()).glob("xtcscope-*"))
    xtcscope.main(["--dry-run", "--viewer", "viamd"])
    assert set(Path(tempfile.gettempdir()).glob("xtcscope-*")) == before


def test_viewer_from_environment(xtcscope, fake_job, monkeypatch, capsys):
    """XTCSCOPE_VIEWER sets the default viewer."""
    monkeypatch.setenv("XTCSCOPE_VIEWER", "viamd")
    assert xtcscope.main(["--dry-run"]) == 0
    assert "view     viamd " in capsys.readouterr().out


def test_bad_arguments(xtcscope):
    """Wrong suffixes and -n 0 are argparse errors (exit 2)."""
    for argv in (["--gro", "dir/conf.top"], ["--xtc", "md.trr"], ["-n", "0"]):
        with pytest.raises(SystemExit) as exc:
            xtcscope.main(argv)
        assert exc.value.code == 2


def test_paths_relative_to_the_job_directories(xtcscope, fake_job, capsys):
    """--gro is relative to the input directory, --xtc to the working directory."""
    (fake_job.input / "eq").mkdir()
    (fake_job.input / "conf.gro").rename(fake_job.input / "eq" / "conf.gro")
    (fake_job.work / "run").mkdir()
    (fake_job.work / "md.xtc").rename(fake_job.work / "run" / "md.xtc")
    argv = ["--dry-run", "--viewer", "viamd", "--gro", "eq/conf.gro", "--xtc", "run/md.xtc"]
    assert xtcscope.main(argv) == 0
    out = capsys.readouterr().out
    assert f"gro      {fake_job.input / 'eq' / 'conf.gro'} (48213 atoms)" in out
    assert f"xtc      {fake_job.work / 'run' / 'md.xtc'} (48213 atoms)" in out
    assert "/md.last10.xtc" in out and "/run/md.last10.xtc" not in out


def test_absolute_paths(xtcscope, fake_job, capsys):
    """Absolute paths are used as they are."""
    gro = fake_job.input / "conf.gro"
    xtc = fake_job.work / "md.xtc"
    argv = ["--dry-run", "--viewer", "viamd", "--gro", str(gro), "--xtc", str(xtc)]
    assert xtcscope.main(argv) == 0
    out = capsys.readouterr().out
    assert f"gro      {gro} (48213 atoms)" in out and f"xtc      {xtc} (48213 atoms)" in out


def test_missing_requested_path(xtcscope, fake_job, capsys):
    """A requested path that does not exist is exit 5, naming the directory."""
    argv = ["--dry-run", "--viewer", "viamd", "--xtc", "run/md.xtc"]
    assert xtcscope.main(argv) == xtcscope.EXIT_NO_FILE
    assert f"There is no run/md.xtc in node42:{fake_job.work}" in capsys.readouterr().err

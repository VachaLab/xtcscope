"""Pure helpers: GRO and XTC listings, file selection, commands."""

import shlex
from pathlib import Path

import pytest


def test_gro_atom_count(xtcscope, tmp_path):
    """The atom count comes from line 2, surrounding spaces allowed."""
    gro = tmp_path / "conf.gro"
    gro.write_text("Title line\n  48213\n    1SOL     OW    1   0.1   0.2   0.3\n")
    assert xtcscope.read_gro_atom_count(gro) == 48213


@pytest.mark.parametrize("content", ["only a title\n", "title\nnot-a-number\n", ""])
def test_gro_atom_count_invalid(xtcscope, tmp_path, content):
    """A GRO without an atom count on line 2 is a mismatch-class error (exit 6)."""
    gro = tmp_path / "bad.gro"
    gro.write_text(content)
    with pytest.raises(xtcscope.XtcscopeError) as exc:
        xtcscope.read_gro_atom_count(gro)
    assert exc.value.exit_code == xtcscope.EXIT_MISMATCH


def test_list_gro_files(xtcscope, tmp_path):
    """GRO files are listed newest first; invalid ones are marked, not dropped."""
    import os

    (tmp_path / "old.gro").write_text("t\n3\n")
    (tmp_path / "new.gro").write_text("t\n5\n")
    (tmp_path / "bad.gro").write_text("t\n")
    (tmp_path / "other.txt").write_text("x")
    os.utime(tmp_path / "old.gro", (1000, 1000))
    os.utime(tmp_path / "new.gro", (3000, 3000))
    os.utime(tmp_path / "bad.gro", (2000, 2000))
    files = xtcscope.list_gro_files(tmp_path)
    assert [f.name for f in files] == ["new.gro", "bad.gro", "old.gro"]
    assert [f.natoms for f in files] == [5, None, 3]
    assert files[1].problem == "not a valid GRO file"


def test_parse_xtc_listing(xtcscope):
    """Name, size, mtime and the magic/natoms bytes are parsed; problems marked."""
    text = (
        "md.xtc\t1000\t200\t000007cb0000bc55\n"  # magic 1995, 48213 atoms
        "big.xtc\t5000\t300\t000007e700000064\n"  # magic 2023, 100 atoms
        "empty.xtc\t0\t100\t\n"
        "short.xtc\t3\t150\t0000\n"
        "junk.xtc\t20\t50\t48656c6c6f20776f\n"
        "garbage line without tabs\n"
    )
    files = xtcscope.parse_xtc_listing(text)
    assert [f.name for f in files] == ["big.xtc", "md.xtc", "short.xtc", "empty.xtc", "junk.xtc"]
    by_name = {f.name: f for f in files}
    assert by_name["md.xtc"].natoms == 48213 and by_name["md.xtc"].problem is None
    assert by_name["big.xtc"].natoms == 100
    assert by_name["md.xtc"].size == 1000
    assert by_name["empty.xtc"].problem == "empty"
    assert by_name["short.xtc"].problem == "empty"
    assert by_name["junk.xtc"].problem == "not an XTC file"


def test_xtc_listing_command_quotes_the_directory(xtcscope):
    """A working directory with spaces and quotes stays one shell word."""
    command = xtcscope.xtc_listing_command(Path("/scratch/my job's dir"))
    assert command.startswith("cd -- '/scratch/my job'\"'\"'s dir' && ")
    assert "od -An -v -tx1 -N8" in command


def test_xtc_listing_command_runs_in_a_shell(xtcscope, tmp_path):
    """The listing command really works in bash on real files."""
    import subprocess

    work = tmp_path / "work dir"
    work.mkdir()
    (work / "md.xtc").write_bytes(bytes.fromhex("000007cb0000bc55") + b"\0" * 10)
    (work / "empty.xtc").write_bytes(b"")
    (work / "notes.txt").write_text("x")
    out = subprocess.run(
        ["bash", "-c", xtcscope.xtc_listing_command(work)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = {f.name: f for f in xtcscope.parse_xtc_listing(out)}
    assert set(files) == {"md.xtc", "empty.xtc"}
    assert files["md.xtc"].natoms == 48213 and files["md.xtc"].size == 18
    assert files["empty.xtc"].problem == "empty"


def test_extract_command(xtcscope):
    """$HOME stays unquoted for the remote shell; the path is quoted."""
    command = xtcscope.extract_command(Path("/scratch/a b/md.xtc"), 7)
    assert command.startswith('nice -n 19 ionice -c3 "$HOME/xtcscope/xtcscope-agent" extract ')
    assert shlex.split(command)[-4:] == ["--xtc", "/scratch/a b/md.xtc", "--frames", "7"]


def test_extracted_name(xtcscope):
    """The local copy is named after the XTC and the frame count."""
    assert xtcscope.extracted_name("md.xtc", 10) == "md.last10.xtc"


def test_viewer_argv(xtcscope, tmp_path, monkeypatch):
    """The viewer command may carry options; GRO then XTC are appended."""
    fake = tmp_path / "vmd"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    words = xtcscope.viewer_words("vmd -nt")
    argv = xtcscope.viewer_argv(words, Path("/in/conf.gro"), Path("/tmp/x/md.last10.xtc"))
    assert argv == ["vmd", "-nt", "/in/conf.gro", "/tmp/x/md.last10.xtc"]


def test_missing_viewer(xtcscope, monkeypatch, tmp_path):
    """A viewer that is not on PATH fails early with exit 9."""
    monkeypatch.setenv("PATH", str(tmp_path))
    for viewer in ("viamd", ""):
        with pytest.raises(xtcscope.XtcscopeError) as exc:
            xtcscope.viewer_words(viewer)
        assert exc.value.exit_code == xtcscope.EXIT_VIEWER


def test_human_size(xtcscope):
    """Sizes are shown in decimal units."""
    assert xtcscope.human_size(512) == "512 B"
    assert xtcscope.human_size(1_500_000) == "1.5 MB"


def test_format_ps(xtcscope):
    """Times are shown without float32 noise or trailing zeros."""
    assert xtcscope.format_ps(700.00006) == "700"
    assert xtcscope.format_ps(0.5) == "0.5"
    assert xtcscope.format_ps(1_000_000.0) == "1000000"
    assert xtcscope.format_ps(12.3456) == "12.346"


def test_list_gro_files_requested_path(xtcscope, tmp_path):
    """A requested path is listed alone, relative to the directory or absolute."""
    (tmp_path / "eq").mkdir()
    (tmp_path / "eq" / "conf.gro").write_text("t\n7\n")
    (tmp_path / "other.gro").write_text("t\n3\n")
    [only] = xtcscope.list_gro_files(tmp_path, "eq/conf.gro")
    assert only.name == "eq/conf.gro" and only.natoms == 7
    absolute = str(tmp_path / "eq" / "conf.gro")
    assert [c.name for c in xtcscope.list_gro_files(Path("/nonexistent"), absolute)] == [absolute]
    assert xtcscope.list_gro_files(tmp_path, "eq/missing.gro") == []


def test_xtc_listing_command_requested_path(xtcscope, tmp_path):
    """A requested path is listed alone, relative to the working directory."""
    import subprocess

    work = tmp_path / "work"
    (work / "run dir").mkdir(parents=True)
    (work / "run dir" / "md.xtc").write_bytes(bytes.fromhex("000007cb0000bc55"))
    (work / "top.xtc").write_bytes(bytes.fromhex("000007cb0000bc55"))

    def listed(requested):
        """Names listed by the command for `requested`."""
        command = xtcscope.xtc_listing_command(work, requested)
        out = subprocess.run(["bash", "-c", command], capture_output=True, text=True).stdout
        return [c.name for c in xtcscope.parse_xtc_listing(out)]

    assert listed("run dir/md.xtc") == ["run dir/md.xtc"]
    assert listed(str(work / "top.xtc")) == [str(work / "top.xtc")]
    assert listed("run dir/missing.xtc") == []
    assert listed("*.xtc") == [], "a requested name is not a glob"


def test_extracted_name_drops_directories(xtcscope):
    """The local copy is named after the file alone."""
    assert xtcscope.extracted_name("run/md.xtc", 10) == "md.last10.xtc"

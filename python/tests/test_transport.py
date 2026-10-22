"""Runners and the private socket directory."""

import os
import stat

import pytest

from xtcscope.errors import XtcscopeError
from xtcscope.transport import LocalRunner, new_run_id, socket_dir


def test_socket_dir_is_private(tmp_path, monkeypatch):
    """The socket directory is created under $XDG_RUNTIME_DIR with mode 0700."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = socket_dir()
    assert path == tmp_path / "xtcscope"
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert socket_dir() == path, "an existing private directory is reused"


def test_socket_dir_without_xdg(tmp_path, monkeypatch):
    """Without $XDG_RUNTIME_DIR, the directory is xtcscope-<uid> in the temp directory."""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", None)
    assert socket_dir() == tmp_path / f"xtcscope-{os.getuid()}"


def test_socket_dir_others_can_read(tmp_path, monkeypatch):
    """A directory others can access is refused."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "xtcscope").mkdir(mode=0o755)
    (tmp_path / "xtcscope").chmod(0o755)
    with pytest.raises(XtcscopeError, match="only you can access"):
        socket_dir()


def test_socket_dir_symlink(tmp_path, monkeypatch):
    """A symlink in place of the directory is refused, wherever it points."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "elsewhere").mkdir(mode=0o700)
    (tmp_path / "xtcscope").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(XtcscopeError):
        socket_dir()


def test_run_ids():
    """Run ids are 8 hex characters and differ between runs."""
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) == 8 and int(i, 16) >= 0 for i in ids)


def test_local_runner():
    """The local runner runs shell commands through bash; there is no connection to lose."""
    runner = LocalRunner()
    assert runner.argv("echo hi") == ["bash", "-c", "echo hi"]
    assert runner.run("echo hi").stdout == "hi\n"
    assert runner.lost_code is None

"""The frozen build hands its children the user's LD_LIBRARY_PATH, not its own."""

import os
import sys

import pytest

from xtcscope.runtime import restore_library_path


@pytest.fixture
def frozen(monkeypatch):
    """Pretend to run as a PyInstaller build."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_unset_when_the_user_had_none(frozen, monkeypatch):
    """Without a value of the user's, the bootloader's is removed."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/xtcscope/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    restore_library_path()
    assert "LD_LIBRARY_PATH" not in os.environ


def test_the_users_value_comes_back(frozen, monkeypatch):
    """The user's own value, kept in LD_LIBRARY_PATH_ORIG, is restored."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/xtcscope/_internal:/opt/vmd/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/vmd/lib")
    restore_library_path()
    assert os.environ["LD_LIBRARY_PATH"] == "/opt/vmd/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in os.environ


def test_nothing_changes_outside_a_frozen_build(monkeypatch):
    """Run from source, the environment is left alone."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/vmd/lib")
    restore_library_path()
    assert os.environ["LD_LIBRARY_PATH"] == "/opt/vmd/lib"

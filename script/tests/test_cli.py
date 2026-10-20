"""Command-line basics of the xtcscope script."""

import os

import pytest
from conftest import SCRIPT


def test_script_is_executable():
    """The script keeps its executable bit."""
    assert os.access(SCRIPT, os.X_OK)


def test_help_exits_zero(xtcscope, capsys):
    """--help prints usage and exits 0."""
    with pytest.raises(SystemExit) as exc:
        xtcscope.main(["--help"])
    assert exc.value.code == 0
    assert "usage: xtcscope" in capsys.readouterr().out


def test_version_unreleased(xtcscope, capsys):
    """An unreleased copy calls itself a development version."""
    with pytest.raises(SystemExit) as exc:
        xtcscope.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "xtcscope development version"


def test_version_released(xtcscope, capsys, monkeypatch):
    """A released copy prints its version."""
    monkeypatch.setattr(xtcscope, "__version__", "0.1.0")
    with pytest.raises(SystemExit):
        xtcscope.main(["--version"])
    assert capsys.readouterr().out.strip() == "xtcscope 0.1.0"


def test_unknown_option_exits_two(xtcscope):
    """Unknown options exit 2, like any argparse error."""
    with pytest.raises(SystemExit) as exc:
        xtcscope.main(["--no-such-option"])
    assert exc.value.code == 2

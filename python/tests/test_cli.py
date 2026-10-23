"""Command-line basics of xtcscope."""

import subprocess
import sys

import pytest

from xtcscope import __version__
from xtcscope.cli import main


def test_help_exits_zero(capsys):
    """--help prints usage and exits 0."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: xtcscope" in capsys.readouterr().out


def test_version(capsys):
    """--version prints the package version."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"xtcscope {__version__}"


def test_python_m_entry_point():
    """`python -m xtcscope` runs the same entry point as the PyInstaller build."""
    result = subprocess.run(
        [sys.executable, "-m", "xtcscope", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"xtcscope {__version__}"


def test_unknown_option_exits_two():
    """Unknown options exit 2, like any argparse error."""
    with pytest.raises(SystemExit) as exc:
        main(["--no-such-option"])
    assert exc.value.code == 2

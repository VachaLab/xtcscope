"""Load the extensionless `xtcscope` script as an importable module for tests."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "xtcscope"


def load_script():
    """Import `script/xtcscope` (which has no .py suffix) as a fresh module."""
    loader = importlib.machinery.SourceFileLoader("xtcscope_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def xtcscope():
    """The xtcscope script, freshly imported for each test."""
    return load_script()

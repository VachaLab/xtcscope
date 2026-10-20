"""Load the extensionless `xtcscope` script as an importable module for tests."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "xtcscope"


def load_script():
    loader = importlib.machinery.SourceFileLoader("xtcscope_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def xtcscope():
    return load_script()

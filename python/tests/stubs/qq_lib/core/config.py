"""Stand-in for qq_lib.core.config."""

from types import SimpleNamespace

CFG = SimpleNamespace(timeouts=SimpleNamespace(ssh=60))

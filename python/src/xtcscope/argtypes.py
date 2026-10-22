"""argparse types shared by the command line and the `_backend` commands."""

import argparse
import re
from collections.abc import Callable

# run ids name control sockets, so they are kept to plain hex
RUN_ID = re.compile(r"[0-9a-f]{8}")


def frames_count(value: str) -> int:
    """argparse type for -n: an integer of at least 1."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number of frames: '{value}'") from None
    if number < 1:
        raise argparse.ArgumentTypeError("the number of frames must be at least 1")
    return number


def file_path(suffix: str) -> Callable[[str], str]:
    """
    argparse type for --gro/--xtc: a file path with the given suffix.

    The path stays as given; it is resolved later against the job's input or
    working directory (an absolute path stays absolute).
    """

    def check(value: str) -> str:
        """Reject wrong suffixes."""
        if not value.endswith(suffix):
            raise argparse.ArgumentTypeError(f"'{value}' does not end in {suffix}")
        return value

    return check


def run_id(value: str) -> str:
    """argparse type for --run: 8 lowercase hex characters."""
    if not RUN_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(f"invalid run id: '{value}' (8 hex characters)")
    return value

"""Messages for the user, all on stderr."""

import sys

# set by --debug, through `set_debug`
_debug = False


def set_debug(enabled: bool) -> None:
    """Turn DEBUG lines on or off."""
    global _debug
    _debug = enabled


def info(message: str) -> None:
    """Print an INFO line on stderr."""
    print(f"INFO    {message}", file=sys.stderr)


def warn(message: str) -> None:
    """Print a WARN line on stderr."""
    print(f"WARN    {message}", file=sys.stderr)


def error(message: str) -> None:
    """Print an ERROR line on stderr."""
    print(f"ERROR   {message}", file=sys.stderr)


def debug(message: str) -> None:
    """Print a DEBUG line on stderr when --debug is given."""
    if _debug:
        print(f"DEBUG   {message}", file=sys.stderr)

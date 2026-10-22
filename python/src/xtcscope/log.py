"""Messages for the user, all on stderr."""

import sys

# set by --debug, through `set_debug`
_debug = False


def set_debug(enabled: bool) -> None:
    """Turn DEBUG lines on or off."""
    global _debug
    _debug = enabled


def debug_enabled() -> bool:
    """Whether --debug was given."""
    return _debug


def relay(level: str, host: str, message: str) -> None:
    """Print a message that came from xtcscope on `host`, tagged with its name."""
    print(f"{level:<8}[{host}] {message}", file=sys.stderr)


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

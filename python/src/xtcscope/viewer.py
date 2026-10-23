"""The molecular viewer: checking its command, building its argv, running it."""

import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from xtcscope.errors import EXIT_VIEWER, XtcscopeError
from xtcscope.log import debug, warn


def viewer_words(viewer: str) -> list[str]:
    """Split the viewer command (e.g. "vmd -nt") and check that it can be run."""
    words = shlex.split(viewer)
    if not words:
        raise XtcscopeError("The viewer command is empty.", EXIT_VIEWER)

    if shutil.which(words[0]) is None:
        raise XtcscopeError(
            f"Viewer '{words[0]}' was not found; active the module "
            "or set the path with --viewer or XTCSCOPE_VIEWER.",
            EXIT_VIEWER,
        )

    return words


def viewer_argv(words: Sequence[str], gro: Path, xtc: Path) -> list[str]:
    """The command that opens a GRO and an XTC: `<viewer> <gro> <xtc>`."""
    return [*words, str(gro), str(xtc)]


def launch_viewer(argv: Sequence[str]) -> None:
    """Run the viewer and wait until it exits; a non-zero exit is only a warning."""
    debug(f"$ {shlex.join(argv)}")
    try:
        result = subprocess.run(argv)
    except OSError as err:
        raise XtcscopeError(f"Could not start the viewer '{argv[0]}': {err}", EXIT_VIEWER) from err

    if result.returncode != 0:
        warn(f"The viewer exited with code {result.returncode}.")

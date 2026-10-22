"""Command line: options, the entry point, exit codes and signals."""

import argparse
import os
import signal
import sys

from xtcscope import __version__
from xtcscope.argtypes import file_path, frames_count
from xtcscope.backend import BACKEND_COMMAND, backend_main
from xtcscope.errors import EXIT_INTERRUPTED, XtcscopeError
from xtcscope.frontend import run
from xtcscope.job import ACCESS_AUTO, ACCESS_MODES
from xtcscope.log import error, set_debug

# frames fetched when -n is not given
DEFAULT_FRAMES = 10
# viewer used when neither --viewer nor XTCSCOPE_VIEWER is set
DEFAULT_VIEWER = "vmd"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="xtcscope",
        description="View the last frames of a running GROMACS job.",
    )
    parser.add_argument(
        "job_id",
        nargs="?",
        help="Job ID. Default: the newest qq job in the current directory.",
    )
    parser.add_argument(
        "--viewer",
        default=os.environ.get("XTCSCOPE_VIEWER", DEFAULT_VIEWER),
        help=(
            "Command that opens '<gro> <xtc>', e.g. vmd, vmd2, viamd or 'vmd -nt'. "
            f"Default: $XTCSCOPE_VIEWER, or {DEFAULT_VIEWER}."
        ),
    )
    parser.add_argument(
        "--access",
        choices=ACCESS_MODES,
        default=ACCESS_AUTO,
        help=(
            "How to read the job's working directory: directly on this machine, or through "
            "the job's main node over SSH. auto reads it directly when it exists here and is "
            "shared storage or the job runs on this machine. Default: auto."
        ),
    )
    parser.add_argument(
        "--gro",
        type=file_path(".gro"),
        metavar="PATH",
        help=(
            "GRO file, relative to the job's input directory (or absolute). "
            "Default: the only one in the input directory, or ask."
        ),
    )
    parser.add_argument(
        "--xtc",
        type=file_path(".xtc"),
        metavar="PATH",
        help=(
            "XTC file, relative to the job's working directory (or absolute). "
            "Default: the only one in the working directory, or ask."
        ),
    )
    parser.add_argument(
        "-n",
        "--frames",
        type=frames_count,
        default=DEFAULT_FRAMES,
        metavar="N",
        help=f"Number of frames from the end of the XTC. Default: {DEFAULT_FRAMES}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Choose the files and check them, then print the commands instead of running them.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print every command and every agent event."
    )
    parser.add_argument("--version", action="version", version=f"xtcscope {__version__}")
    return parser


def raise_interrupt(signum, frame) -> None:
    """Turn SIGTERM into KeyboardInterrupt, so it takes the Ctrl-C path."""
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    """Entry point: `xtcscope ...`, or `xtcscope _backend ...`. Returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    previous = signal.signal(signal.SIGTERM, raise_interrupt)

    try:
        if argv[:1] == [BACKEND_COMMAND]:
            return backend_main(argv[1:])

        args = build_parser().parse_args(argv)
        set_debug(args.debug)
        return run(args)
    except XtcscopeError as err:
        error(str(err))
        return err.exit_code
    except KeyboardInterrupt:
        error("Interrupted.")
        return EXIT_INTERRUPTED
    finally:
        signal.signal(signal.SIGTERM, previous)

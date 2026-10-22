"""GRO and XTC files: listing them, reading atom counts, formatting their details."""

import shlex
from dataclasses import dataclass
from pathlib import Path

from xtcscope.errors import EXIT_MISMATCH, EXIT_NO_WORK_DIR, EXIT_SSH, XtcscopeError
from xtcscope.transport import Runner

# XTC magic numbers the agent understands
XTC_MAGICS = (1995, 2023)


@dataclass(frozen=True)
class Candidate:
    """A GRO or XTC file that could be chosen."""

    # the file name, or the path as given with --gro/--xtc
    name: str
    size: int
    mtime: float
    natoms: int | None
    # why the file can't be chosen, or None if it can
    problem: str | None = None


def read_gro_atom_count(path: Path) -> int:
    """Return the atom count from line 2 of a GRO file."""
    try:
        with path.open() as handle:
            handle.readline()
            line = handle.readline()
    except OSError as err:
        raise XtcscopeError(f"Could not read '{path}': {err.strerror}.", EXIT_MISMATCH) from err

    try:
        return int(line.split()[0])
    except (IndexError, ValueError) as err:
        raise XtcscopeError(
            f"'{path}' is not a valid GRO file: line 2 does not hold an atom count.",
            EXIT_MISMATCH,
        ) from err


def list_gro_files(directory: Path, requested: str | None = None) -> list[Candidate]:
    """
    List the GRO files in a local directory, newest first.

    With `requested` (a path relative to `directory`, or absolute), only that
    file is listed, if it exists.
    """
    if requested is not None:
        named = [(requested, directory / requested)]
    else:
        named = [(path.name, path) for path in directory.glob("*.gro")]

    candidates = []
    for name, path in named:
        if not path.is_file():
            continue

        stat = path.stat()
        try:
            natoms, problem = read_gro_atom_count(path), None
        except XtcscopeError:
            natoms, problem = None, "not a valid GRO file"
        candidates.append(Candidate(name, stat.st_size, stat.st_mtime, natoms, problem))

    return sorted(candidates, key=lambda c: c.mtime, reverse=True)


def xtc_listing_command(work_dir: Path, requested: str | None = None) -> str:
    """
    Shell command that prints name, size, mtime and the first 8 bytes of each XTC.

    With `requested` (a path relative to `work_dir`, or absolute), only that
    file is listed, if it exists.
    """
    files = "*.xtc" if requested is None else shlex.quote(requested)
    return (
        f"cd -- {shlex.quote(str(work_dir))} && "
        f'for f in {files}; do [ -f "$f" ] || continue; '
        "printf '%s\\t%s\\t%s\\t%s\\n' \"$f\" "
        '"$(stat -c %s -- "$f")" "$(stat -c %Y -- "$f")" '
        '"$(od -An -v -tx1 -N8 -- "$f" | tr -d \' \\n\')"; done'
    )


def parse_xtc_listing(text: str) -> list[Candidate]:
    """Parse the output of `xtc_listing_command`, newest first."""
    candidates = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue

        name, size, mtime, head = parts
        natoms, problem = None, None
        if len(head) < 16:
            problem = "empty"
        else:
            magic = int(head[0:8], 16)
            if magic not in XTC_MAGICS:
                problem = "not an XTC file"
            else:
                natoms = int(head[8:16], 16)

        candidates.append(Candidate(name, int(size), float(mtime), natoms, problem))

    return sorted(candidates, key=lambda c: c.mtime, reverse=True)


def list_xtc_files(runner: Runner, work_dir: Path, requested: str | None = None) -> list[Candidate]:
    """
    List the XTC files in the job's working directory, where `runner` runs commands.

    With `requested`, only that file (relative to `work_dir`, or absolute) is listed.
    """
    result = runner.run(xtc_listing_command(work_dir, requested))
    if result.returncode == runner.lost_code:
        raise XtcscopeError(
            f"Lost the connection to {runner.label}: {result.stderr.strip()}", EXIT_SSH
        )

    if result.returncode != 0:
        raise XtcscopeError(
            f"Working directory {work_dir} is not accessible on {runner.label}.",
            EXIT_NO_WORK_DIR,
        )

    return parse_xtc_listing(result.stdout)


def format_ps(time_ps: float) -> str:
    """Format a time in ps without single-precision noise, e.g. 700.00006 -> 700."""
    return f"{time_ps:.3f}".rstrip("0").rstrip(".")


def human_size(size: int) -> str:
    """Format a byte count, e.g. 1.5 MB."""
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000

    return f"{value:.1f} TB"

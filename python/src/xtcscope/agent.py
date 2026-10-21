"""xtcscope-agent: the command that extracts the frames, and reading its output."""

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from xtcscope.errors import EXIT_AGENT, EXIT_SSH, XtcscopeError
from xtcscope.files import format_ps, human_size
from xtcscope.log import debug, info, warn
from xtcscope.transport import COMMAND_NOT_FOUND, Runner

# the agent on the node; $HOME is expanded by the remote shell
AGENT = '"$HOME/xtcscope/xtcscope-agent"'
# overrides where the agent for direct access is looked for (development, tests)
AGENT_ENV = "XTCSCOPE_AGENT"


def local_agent_path() -> Path:
    """
    The agent to run on this machine for direct access.

    $XTCSCOPE_AGENT if set; next to the executable in a PyInstaller build,
    where the installer puts it; otherwise ~/xtcscope/xtcscope-agent.
    """
    if override := os.environ.get(AGENT_ENV):
        return Path(override)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "xtcscope-agent"

    return Path.home() / "xtcscope" / "xtcscope-agent"


def find_local_agent() -> str:
    """The local agent as a shell word, for `extract_command`; exit 8 if it is missing."""
    path = local_agent_path()
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise XtcscopeError(
            f"xtcscope-agent is not installed on this machine ({path}); run the installer.",
            EXIT_AGENT,
        )

    return shlex.quote(str(path))


def extract_command(xtc: Path, frames: int, agent: str = AGENT) -> str:
    """Shell command that writes the last `frames` frames of `xtc` to stdout."""
    return f"nice -n 19 ionice -c3 {agent} extract --xtc {shlex.quote(str(xtc))} --frames {frames}"


def extracted_name(xtc_name: str, frames: int) -> str:
    """Local file name for the extracted frames, e.g. run/md.xtc -> md.last10.xtc."""
    xtc_name = Path(xtc_name).name
    stem = xtc_name[:-4] if xtc_name.endswith(".xtc") else xtc_name
    return f"{stem}.last{frames}.xtc"


@dataclass(frozen=True)
class Fetched:
    """What the agent reported about the frames it copied."""

    frames: int
    first_time_ps: float
    last_time_ps: float
    bytes: int


def parse_event(line: str) -> dict | None:
    """Parse one stderr line of the agent; None if it is not an agent event."""
    try:
        event = json.loads(line)
    except ValueError:
        return None

    if isinstance(event, dict) and isinstance(event.get("event"), str):
        return event

    return None


def fetch_frames(runner: Runner, command: str, xtc_name: str, destination: Path) -> Fetched:
    """
    Run the agent's extract `command` through `runner`, saving its stdout to `destination`.

    Warnings are shown as they arrive. The result is checked: the agent must
    exit 0, report `located` and `done`, and the file must have exactly the
    size both events report.
    """
    argv = runner.argv(command)
    debug(f"$ {shlex.join(argv)} > {destination}")
    located = done = failure = None
    other_lines: list[str] = []
    started = time.monotonic()

    with destination.open("wb") as out:
        process = subprocess.Popen(argv, stdout=out, stderr=subprocess.PIPE, text=True)
        assert process.stderr is not None  # always set, since stderr=PIPE

        try:
            for line in process.stderr:
                event = parse_event(line)
                if event is None:
                    other_lines.append(line.rstrip("\n"))
                    debug(f"stderr: {line.rstrip()}")
                    continue

                debug(f"agent: {line.rstrip()}")
                kind = event["event"]

                if kind == "warning":
                    warn(f"{event.get('message')} ({event.get('code')})")
                elif kind == "located":
                    located = event
                    first = format_ps(event["first_time_ps"])
                    last = format_ps(event["last_time_ps"])
                    size = human_size(event["bytes"])
                    info(
                        f"Fetching {event['frames']} frames "
                        f"({first}-{last} ps, {size}) from {Path(xtc_name).name}"
                    )
                elif kind == "done":
                    done = event
                elif kind == "error":
                    failure = event

            code = process.wait()
        except BaseException:
            # Ctrl-C or SIGTERM: closing its stdout makes the agent exit on its next write
            process.terminate()
            process.wait()
            raise

    size = destination.stat().st_size

    if failure is not None:
        raise XtcscopeError(
            f"The agent on {runner.label} failed: {failure.get('message')} ({failure.get('code')})",
            EXIT_AGENT,
        )

    if code == COMMAND_NOT_FOUND and any("xtcscope-agent" in line for line in other_lines):
        raise XtcscopeError(
            f"xtcscope-agent is not installed on {runner.label}; run the installer.", EXIT_AGENT
        )

    if runner.connection_lost(code):
        raise XtcscopeError(f"Lost the connection to {runner.label}.", EXIT_SSH)

    if code != 0:
        detail = "; ".join(other_lines[-3:]) or "no message"
        raise XtcscopeError(f"The agent on {runner.label} exited with {code}: {detail}", EXIT_AGENT)

    if located is None or done is None:
        raise XtcscopeError(f"The agent on {runner.label} did not report its work.", EXIT_AGENT)

    if not (size == located["bytes"] == done["bytes"]):
        raise XtcscopeError(
            f"The fetched file is incomplete: {size} bytes, expected {located['bytes']}.",
            EXIT_AGENT,
        )

    debug(f"fetched {size} bytes in {time.monotonic() - started:.2f} s")
    return Fetched(
        frames=located["frames"],
        first_time_ps=located["first_time_ps"],
        last_time_ps=located["last_time_ps"],
        bytes=size,
    )

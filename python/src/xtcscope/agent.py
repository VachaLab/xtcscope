"""xtcscope-agent: the command that extracts the frames, and reading its output."""

import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from xtcscope.errors import EXIT_AGENT, EXIT_SSH, XtcscopeError
from xtcscope.files import format_ps, human_size
from xtcscope.log import debug, info, warn
from xtcscope.transport import COMMAND_NOT_FOUND, SSH_FAILED, Remote

# the agent on the node; $HOME is expanded by the remote shell
AGENT = '"$HOME/xtcscope/xtcscope-agent"'


def extract_command(xtc: Path, frames: int) -> str:
    """Remote command that writes the last `frames` frames of `xtc` to stdout."""
    return f"nice -n 19 ionice -c3 {AGENT} extract --xtc {shlex.quote(str(xtc))} --frames {frames}"


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


def fetch_frames(remote: Remote, xtc: Path, frames: int, destination: Path) -> Fetched:
    """
    Run the agent over the master connection, saving its stdout to `destination`.

    Warnings are shown as they arrive. The result is checked: the agent must
    exit 0, report `located` and `done`, and the file must have exactly the
    size both events report.
    """
    command = remote.command(extract_command(xtc, frames))
    debug(f"$ {shlex.join(command)} > {destination}")
    located = done = failure = None
    other_lines: list[str] = []
    started = time.monotonic()

    with destination.open("wb") as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.PIPE, text=True)
        assert process.stderr is not None  # always set, since stderr=PIPE

        try:
            for line in process.stderr:
                event = parse_event(line)
                if event is None:
                    other_lines.append(line.rstrip("\n"))
                    debug(f"remote: {line.rstrip()}")
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
                        f"({first}-{last} ps, {size}) from {xtc.name}"
                    )
                elif kind == "done":
                    done = event
                elif kind == "error":
                    failure = event

            code = process.wait()
        except BaseException:
            # Ctrl-C or SIGTERM: closing SSH makes the agent exit on its next write
            process.terminate()
            process.wait()
            raise

    size = destination.stat().st_size

    if failure is not None:
        raise XtcscopeError(
            f"The agent on {remote.node} failed: {failure.get('message')} ({failure.get('code')})",
            EXIT_AGENT,
        )

    if code == COMMAND_NOT_FOUND and any("xtcscope-agent" in line for line in other_lines):
        raise XtcscopeError(
            f"xtcscope-agent is not installed on {remote.node}; run the installer.", EXIT_AGENT
        )

    if code == SSH_FAILED:
        raise XtcscopeError(f"Lost the connection to {remote.node}.", EXIT_SSH)

    if code != 0:
        detail = "; ".join(other_lines[-3:]) or "no message"
        raise XtcscopeError(f"The agent on {remote.node} exited with {code}: {detail}", EXIT_AGENT)

    if located is None or done is None:
        raise XtcscopeError(f"The agent on {remote.node} did not report its work.", EXIT_AGENT)

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

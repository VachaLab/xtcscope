"""
The frontend side of --remote: the backend runs as `xtcscope _backend` on another host.

One SSH master connection to the host carries every command: `inspect`, `gro`,
`fetch` and `close`. The host reaches the job's node by itself; nothing is
forwarded from here.
"""

import json
import re
import shlex
import subprocess
from pathlib import Path

from xtcscope import __version__
from xtcscope.agent import FetchPlan
from xtcscope.backend import BACKEND_COMMAND, Inspection
from xtcscope.errors import (
    EXIT_BACKEND,
    EXIT_BUG,
    EXIT_INTERRUPTED,
    EXIT_SSH,
    EXIT_USAGE,
    PROTOCOL,
    XtcscopeError,
)
from xtcscope.job import ACCESS_NODE
from xtcscope.log import debug, debug_enabled, info, relay, warn
from xtcscope.transport import (
    COMMAND_NOT_FOUND,
    REMOTE_PERSIST,
    SSH_FAILED,
    SshRunner,
    remote_ssh_options,
    socket_dir,
)

# xtcscope on the remote host, by full path: a non-interactive session may not
# have the PATH block from .bashrc; $HOME is expanded by the remote shell
REMOTE_XTCSCOPE = '"$HOME/xtcscope/xtcscope"'
# a message line from xtcscope, e.g. "INFO    Job 123 ..."
LOG_LINE = re.compile(r"(INFO|WARN|ERROR|DEBUG) +(.*)")
# exit codes the backend can return on purpose; others mean something broke
BACKEND_EXIT_CODES = set(range(EXIT_BUG, EXIT_BACKEND + 1)) | {EXIT_INTERRUPTED}


class RemoteBackend:
    """The backend on `host`, reached over one SSH master connection."""

    def __init__(self, host: str, run: str):
        """A backend on `host` (anything ssh accepts, e.g. an alias from ~/.ssh/config)."""
        self.label = host
        self.run = run
        self.runner = SshRunner(
            host, socket_dir() / f"{run}-remote", remote_ssh_options, REMOTE_PERSIST
        )
        # set by inspect: the node whose connection `close` ends on the host
        self.node: str | None = None
        self.connected = False

    def location(self, path: Path) -> str:
        """How messages name a path on the host, e.g. desktop7:/storage/..."""
        return f"{self.label}:{path}"

    def command(self, subcommand: str, *args: str) -> str:
        """The shell command that runs `xtcscope _backend <subcommand>` on the host."""
        words = [BACKEND_COMMAND, subcommand, "--protocol", str(PROTOCOL), "--run", self.run]
        if debug_enabled():
            words.append("--debug")

        return f"{REMOTE_XTCSCOPE} {shlex.join([*words, *args])}"

    def call(self, subcommand: str, *args: str) -> tuple[subprocess.CompletedProcess, list[str]]:
        """
        Run a backend command on the host; returns its result and its ERROR messages.

        The backend's INFO, WARN and DEBUG lines are shown as they would be
        locally, tagged with the host's name. A lost connection is exit 7, and
        a missing xtcscope on the host is exit 10.
        """
        self.runner.open()
        argv = self.runner.argv(self.command(subcommand, *args))
        debug(f"$ {shlex.join(argv)}")
        result = subprocess.run(argv, capture_output=True)

        errors: list[str] = []
        others: list[str] = []
        for line in result.stderr.decode(errors="replace").splitlines():
            match = LOG_LINE.fullmatch(line)
            if match is None:
                others.append(line)
                debug(f"{self.label}: {line}")
            elif match[1] == "ERROR":
                errors.append(match[2])
            else:
                relay(match[1], self.label, match[2])

        if result.returncode == SSH_FAILED:
            detail = f": {others[-1]}" if others else "."
            raise XtcscopeError(f"Lost the connection to {self.label}{detail}", EXIT_SSH)

        if result.returncode == COMMAND_NOT_FOUND and any("xtcscope" in line for line in others):
            raise XtcscopeError(
                f"xtcscope is not installed on {self.label}; install it there first.",
                EXIT_BACKEND,
            )

        return result, errors

    def answer(self, result: subprocess.CompletedProcess) -> dict:
        """The JSON document `inspect` printed, checked for the protocol; exit 10 if unusable."""
        try:
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
        except ValueError:
            raise XtcscopeError(
                f"xtcscope on {self.label} gave no valid answer (exit {result.returncode}).",
                EXIT_BACKEND,
            ) from None

        if data.get("protocol") != PROTOCOL:
            theirs = data.get("version", "of unknown version")
            raise XtcscopeError(
                f"xtcscope on {self.label} ({theirs}) speaks backend protocol "
                f"{data.get('protocol')}, this one ({__version__}) speaks {PROTOCOL}; "
                "install the same version on both machines.",
                EXIT_BACKEND,
            )

        return data

    def inspect(
        self, job_id: str | None, gro: str | None, xtc: str | None, access: str
    ) -> Inspection:
        """Connect to the host, then resolve the job and list its files there."""
        if job_id is None:
            raise XtcscopeError("--remote needs a job ID.", EXIT_USAGE)

        info(f"Connecting to {self.label}")
        self.connected = True
        self.runner.open()

        args = [job_id, "--access", access]
        if gro is not None:
            args += ["--gro", gro]
        if xtc is not None:
            args += ["--xtc", xtc]
        result, _ = self.call("inspect", *args)
        data = self.answer(result)

        if "error" in data:
            failure = data["error"]
            exit_code = failure.get("exit_code", EXIT_BACKEND)
            raise XtcscopeError(f"[{self.label}] {failure.get('message')}", exit_code)

        try:
            inspection = Inspection.from_json(data)
        except (KeyError, TypeError, ValueError) as err:
            raise XtcscopeError(
                f"xtcscope on {self.label} gave an incomplete answer: {err}", EXIT_BACKEND
            ) from err

        if inspection.version != __version__:
            warn(f"xtcscope on {self.label} is {inspection.version}, this one is {__version__}.")

        self.node = inspection.job.node
        return inspection

    def gro_file(self, inspection: Inspection, name: str, tmp_dir: Path) -> Path:
        """Copy the chosen GRO from the host into `tmp_dir`, keeping its file name."""
        source = inspection.job.input_dir / name
        local = tmp_dir / Path(name).name
        info(f"Copying {local.name} from {self.label}")

        result, errors = self.call("gro", str(source))
        if result.returncode != 0:
            message = errors[-1] if errors else f"could not copy {source}"
            exit_code = result.returncode
            raise XtcscopeError(
                f"[{self.label}] {message}",
                exit_code if exit_code in BACKEND_EXIT_CODES else EXIT_BACKEND,
            )

        local.write_bytes(result.stdout)
        return local

    def fetch_plan(self, inspection: Inspection, xtc: Path, frames: int) -> FetchPlan:
        """The ssh command that runs `_backend fetch` on the host and streams the frames here."""
        self.runner.open()
        job, access = inspection.job, inspection.access
        args = ["--access", access.mode, "--node", job.node, "--xtc", str(xtc)]
        argv = self.runner.argv(self.command("fetch", *args, "--frames", str(frames)))

        # errors name where the agent runs: the node, or the host itself
        label = job.node if access.mode == ACCESS_NODE else self.label
        return FetchPlan(argv, label, SSH_FAILED)

    def close(self) -> None:
        """End the node connection on the host, then the connection to the host."""
        if not self.connected:
            return
        self.connected = False

        if self.node is not None and self.runner.is_alive():
            try:
                self.call("close", "--node", self.node)
            except XtcscopeError as err:
                debug(f"closing the node connection on {self.label} failed: {err}")
        self.runner.close()

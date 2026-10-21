"""Running shell commands: on this machine, or on a node over an SSH master connection."""

import shlex
import subprocess
from pathlib import Path
from typing import Protocol, Self

from xtcscope.errors import EXIT_SSH, XtcscopeError
from xtcscope.log import debug

# exit status of ssh itself when the connection fails
SSH_FAILED = 255
# exit status of a shell (or nice) when a command does not exist
COMMAND_NOT_FOUND = 127


class Runner(Protocol):
    """Runs shell commands somewhere: here or on a node."""

    # where the commands run, for messages: "this machine" or a node name
    label: str

    def argv(self, command: str) -> list[str]:
        """The local command that runs the shell command `command`."""
        ...

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command and capture its output as text."""
        ...

    def connection_lost(self, returncode: int) -> bool:
        """Whether `returncode` means the connection failed, not the command."""
        ...

    def __enter__(self) -> Self:
        """Get ready to run commands."""
        ...

    def __exit__(self, *exc) -> None:
        """Release what `__enter__` acquired."""
        ...


class LocalRunner:
    """Runs shell commands on this machine, through bash."""

    label = "this machine"

    def argv(self, command: str) -> list[str]:
        """The local command that runs the shell command `command`."""
        return ["bash", "-c", command]

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command and capture its output as text."""
        argv = self.argv(command)
        debug(f"$ {shlex.join(argv)}")

        return subprocess.run(argv, capture_output=True, text=True)

    def connection_lost(self, returncode: int) -> bool:
        """There is no connection to lose."""
        return False

    def __enter__(self) -> Self:
        """Nothing to prepare."""
        return self

    def __exit__(self, *exc) -> None:
        """Nothing to release."""


def node_ssh_options(timeout: int) -> list[str]:
    """Options for the master connection to a node, as qq uses them, plus keep-alives."""
    return [
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "GSSAPIAuthentication=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "ServerAliveInterval=15",
    ]


class SshRunner:
    """Runs shell commands on a node over one SSH master connection."""

    def __init__(self, node: str, tmp_dir: Path, timeout: int):
        """Prepare a connection to `node`; its control socket lives in `tmp_dir`."""
        self.label = node
        self.node = node
        self.control = tmp_dir / "ctl"
        self.timeout = timeout
        self.is_open = False

    def open(self) -> None:
        """Open the master connection; one authentication for the whole run."""
        command = [
            "ssh",
            *node_ssh_options(self.timeout),
            "-M",
            "-S",
            str(self.control),
            "-f",
            "-N",
            self.node,
        ]

        debug(f"$ {shlex.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            reason = f": {detail[-1]}" if detail else ""
            raise XtcscopeError(f"Could not connect to {self.node}{reason}", EXIT_SSH)

        self.is_open = True

    def argv(self, command: str) -> list[str]:
        """The local command that runs `command` on the node over the master connection."""
        return ["ssh", "-S", str(self.control), self.node, command]

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command on the node and capture its output as text."""
        argv = self.argv(command)
        debug(f"$ {shlex.join(argv)}")

        return subprocess.run(argv, capture_output=True, text=True)

    def connection_lost(self, returncode: int) -> bool:
        """Whether ssh itself failed, rather than the command on the node."""
        return returncode == SSH_FAILED

    def close(self) -> None:
        """Close the master connection; errors are ignored."""
        if not self.is_open:
            return

        command = ["ssh", "-S", str(self.control), "-O", "exit", self.node]
        debug(f"$ {shlex.join(command)}")
        subprocess.run(command, capture_output=True)
        self.is_open = False

    def __enter__(self) -> Self:
        """Open the connection."""
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        """Close the connection."""
        self.close()

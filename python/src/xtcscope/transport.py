"""SSH: one master connection to a node, reused by every remote command."""

import shlex
import subprocess
from pathlib import Path

from xtcscope.errors import EXIT_SSH, XtcscopeError
from xtcscope.log import debug

# exit status of ssh itself when the connection fails
SSH_FAILED = 255
# exit status of the remote shell (or nice) when a command does not exist
COMMAND_NOT_FOUND = 127


def ssh_options(timeout: int) -> list[str]:
    """Options for the master connection, as qq uses them, plus keep-alives."""
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


class Remote:
    """One SSH master connection to a node, reused by every remote command."""

    def __init__(self, node: str, tmp_dir: Path, timeout: int):
        """Prepare a connection to `node`; its control socket lives in `tmp_dir`."""
        self.node = node
        self.control = tmp_dir / "ctl"
        self.timeout = timeout
        self.is_open = False

    def open(self) -> None:
        """Open the master connection; one authentication for the whole run."""
        command = [
            "ssh",
            *ssh_options(self.timeout),
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

    def command(self, remote_command: str) -> list[str]:
        """The local command that runs `remote_command` over the master connection."""
        return ["ssh", "-S", str(self.control), self.node, remote_command]

    def run(self, remote_command: str) -> subprocess.CompletedProcess:
        """Run a remote command and capture its output as text."""
        command = self.command(remote_command)
        debug(f"$ {shlex.join(command)}")

        return subprocess.run(command, capture_output=True, text=True)

    def close(self) -> None:
        """Close the master connection; errors are ignored."""
        if not self.is_open:
            return

        command = ["ssh", "-S", str(self.control), "-O", "exit", self.node]
        debug(f"$ {shlex.join(command)}")
        subprocess.run(command, capture_output=True)
        self.is_open = False

    def __enter__(self) -> "Remote":
        """Open the connection."""
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        """Close the connection."""
        self.close()

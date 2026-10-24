"""Running shell commands: on this machine, or on a node over an SSH master connection."""

import os
import secrets
import shlex
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from xtcscope.errors import EXIT_SSH, XtcscopeError
from xtcscope.log import debug

# exit status of ssh itself when the connection fails
SSH_FAILED = 255
# exit status of a shell (or nice) when a command does not exist
COMMAND_NOT_FOUND = 127
# seconds an idle node connection outlives the process that opened it, so that
# `_backend fetch` can reuse the connection `_backend inspect` opened
NODE_PERSIST = 120
# seconds an idle connection to a --remote host survives; long enough to choose
# a file at a prompt, after which the next command reconnects (and may prompt)
REMOTE_PERSIST = 600


class Runner(Protocol):
    """Runs shell commands somewhere: here or on a node."""

    # where the commands run, for messages: "this machine" or a node name
    label: str

    @property
    def lost_code(self) -> int | None:
        """Exit status that means the connection failed, not the command; None without one."""
        ...

    def open(self) -> None:
        """Get ready to run commands; reuse what is already there."""
        ...

    def argv(self, command: str) -> list[str]:
        """The local command that runs the shell command `command`."""
        ...

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command and capture its output as text."""
        ...

    def close(self) -> None:
        """Release what `open` acquired; errors are ignored."""
        ...


class LocalRunner:
    """Runs shell commands on this machine, through bash."""

    label = "this machine"
    lost_code = None

    def open(self) -> None:
        """Nothing to prepare."""

    def argv(self, command: str) -> list[str]:
        """The local command that runs the shell command `command`."""
        return ["bash", "-c", command]

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command and capture its output as text."""
        argv = self.argv(command)
        debug(f"$ {shlex.join(argv)}")

        return subprocess.run(argv, capture_output=True, text=True)

    def close(self) -> None:
        """Nothing to release."""


def socket_dir() -> Path:
    """
    The private directory for SSH control sockets, created if needed.

    $XDG_RUNTIME_DIR/xtcscope if that variable is set, else /tmp/xtcscope-<uid>,
    with mode 0700. A directory that is not ours alone is refused.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        path = Path(base) / "xtcscope"
    else:
        path = Path(tempfile.gettempdir()) / f"xtcscope-{os.getuid()}"

    try:
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
    except OSError as err:
        raise XtcscopeError(f"Could not create {path}: {err.strerror}.", EXIT_SSH) from err

    private = stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
    if not private or info.st_mode & 0o077:
        raise XtcscopeError(
            f"{path} must be a directory only you can access; remove it and try again.", EXIT_SSH
        )

    return path


def new_run_id() -> str:
    """A fresh run id: 8 hex characters naming this run's control sockets."""
    return secrets.token_hex(4)


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


def remote_ssh_options() -> list[str]:
    """
    Options for the master connection to a --remote host: keep-alives only.

    Everything else comes from the user's ~/.ssh/config (aliases, users, keys,
    ProxyJump, host keys), and password, passphrase and host-key prompts appear
    on the terminal: ssh reads them from /dev/tty even when stderr is captured.
    """
    return ["-o", "ServerAliveInterval=15"]


class SshRunner:
    """
    Runs shell commands on one host over an SSH master connection.

    The master outlives this object for `persist` seconds of idleness, so
    another process can reuse it through the same control socket, and a
    process that dies without closing it leaves nothing behind for long.
    """

    lost_code = SSH_FAILED

    def __init__(
        self, destination: str, control: Path, options: Callable[[], list[str]], persist: int
    ):
        """Prepare a connection to `destination` through the control socket `control`."""
        self.label = destination
        self.destination = destination
        self.control = control
        # called only when a new connection is opened (the node options import qq)
        self.options = options
        self.persist = persist

    def is_alive(self) -> bool:
        """Whether a master connection answers on the control socket."""
        if not self.control.exists():
            return False

        command = ["ssh", "-S", str(self.control), "-O", "check", self.destination]
        debug(f"$ {shlex.join(command)}")
        return subprocess.run(command, capture_output=True).returncode == 0

    def open(self) -> None:
        """Reuse a live master connection, or open one: one authentication per run."""
        if self.is_alive():
            return

        # a socket left by a master that has exited would stop a new one from starting
        self.control.unlink(missing_ok=True)
        command = [
            "ssh",
            *self.options(),
            "-o",
            f"ControlPersist={self.persist}",
            "-M",
            "-S",
            str(self.control),
            "-f",
            "-N",
            self.destination,
        ]

        debug(f"$ {shlex.join(command)}")
        # stderr goes to a file, not a pipe: the backgrounded master (-f) of an older
        # OpenSSH, or a helper it starts, can keep stderr open, and waiting for the end
        # of a pipe would then last as long as the master does
        with tempfile.TemporaryFile(mode="w+") as errors:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=errors)
            errors.seek(0)
            detail = errors.read().strip().splitlines()

        if result.returncode != 0:
            reason = f": {detail[-1]}" if detail else ""
            raise XtcscopeError(f"Could not connect to {self.destination}{reason}", EXIT_SSH)

    def argv(self, command: str) -> list[str]:
        """The local command that runs `command` on the host over the master connection."""
        return ["ssh", "-S", str(self.control), self.destination, command]

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run a shell command on the host and capture its output as text."""
        argv = self.argv(command)
        debug(f"$ {shlex.join(argv)}")

        return subprocess.run(argv, capture_output=True, text=True)

    def close(self) -> None:
        """Close the master connection, whoever opened it; errors are ignored."""
        if not self.control.exists():
            return

        command = ["ssh", "-S", str(self.control), "-O", "exit", self.destination]
        debug(f"$ {shlex.join(command)}")
        subprocess.run(command, capture_output=True)

"""The qq job: finding it, and deciding how to reach its working directory."""

import os
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from xtcscope.errors import EXIT_NO_JOB, EXIT_NO_WORK_DIR, XtcscopeError

# values of --access
ACCESS_AUTO = "auto"
ACCESS_DIRECT = "direct"
ACCESS_NODE = "node"
ACCESS_MODES = (ACCESS_AUTO, ACCESS_DIRECT, ACCESS_NODE)


@dataclass(frozen=True)
class Job:
    """What xtcscope needs to know about a qq job."""

    job_id: str
    name: str
    node: str
    work_dir: Path
    input_dir: Path
    # qq's name for the batch system, e.g. "PBS"
    batch_system: str


@dataclass(frozen=True)
class Access:
    """How the working directory is reached: `direct` (here) or `node` (over SSH)."""

    mode: str
    # why, for messages; None for the plain fallback to the node
    reason: str | None = None

    def describe(self, node: str) -> str:
        """The end of the INFO line, e.g. "through node42" or "directly (shared storage)"."""
        if self.mode == ACCESS_DIRECT:
            return f"directly ({self.reason})"

        suffix = f" ({self.reason})" if self.reason else ""
        return f"through {node}{suffix}"

    def summary(self, node: str) -> str:
        """The --dry-run line, e.g. "node via node42" or "direct (shared storage)"."""
        if self.mode == ACCESS_DIRECT:
            return f"direct ({self.reason})"

        suffix = f" ({self.reason})" if self.reason else ""
        return f"node via {node}{suffix}"


def find_job(job_id: str | None) -> Job:
    """Resolve the job (by ID, or the newest one in the current directory) via qq."""
    # imported here: qq is slow to import, and --help, --version and the tests don't need it
    from qq_lib.core.common import get_info_files
    from qq_lib.core.navigator import Navigator
    from qq_lib.info import Informer

    try:
        if job_id is not None:
            informer = Informer.from_job_id(job_id)
        else:
            files = get_info_files(Path())
            if not files:
                raise XtcscopeError("No job detected in the current directory.", EXIT_NO_JOB)
            informer = Informer.from_file(files[-1])
    except XtcscopeError:
        raise
    except Exception as err:
        raise XtcscopeError(f"Could not find job '{job_id}': {err}", EXIT_NO_JOB) from err

    found_id = informer.info.job_id
    navigator = Navigator.from_informer(informer)
    if not navigator.has_destination():
        raise XtcscopeError(f"Job {found_id} does not have a working directory.", EXIT_NO_WORK_DIR)

    node, work_dir = navigator.get_main_node(), navigator.get_work_dir()

    # we check that node and work dir are not None with navigator.has_destination() above
    assert node is not None
    assert work_dir is not None
    return Job(
        job_id=found_id,
        name=informer.info.job_name,
        node=node,
        work_dir=work_dir,
        input_dir=informer.info.input_dir,
        batch_system=informer.batch_system.env_name(),
    )


def ssh_timeout() -> int:
    """qq's SSH timeout in seconds."""
    from qq_lib.core.config import CFG

    return CFG.timeouts.ssh


def work_dir_is_shared(batch_system: str, work_dir: Path) -> bool:
    """Whether qq's batch system considers `work_dir` to be on shared storage."""
    # importing qq_lib.batch registers every batch system, so from_str can find it
    from qq_lib.batch.interface import BatchInterface

    return BatchInterface.from_str(batch_system).is_shared(work_dir)


def local_host_names() -> tuple[str, ...]:
    """The names of this machine, to compare with the job's main node."""
    return socket.getfqdn(), socket.gethostname()


def short_name(host: str) -> str:
    """The host name up to the first dot: node42.example.cz -> node42."""
    return host.split(".", 1)[0]


def is_this_host(node: str, local_names: Sequence[str]) -> bool:
    """Whether `node` is this machine: the same full name, or the same short name."""
    names = [name for name in local_names if name]
    return node in names or short_name(node) in {short_name(name) for name in names}


def is_readable_dir(path: Path) -> bool:
    """Whether `path` is a directory this process can list and enter."""
    return path.is_dir() and os.access(path, os.R_OK | os.X_OK)


def decide_access(
    job: Job,
    requested: str,
    is_shared: Callable[[Path], bool],
    local_names: Sequence[str],
) -> Access:
    """
    Decide how to reach the job's working directory (see the spec's access rule).

    With `requested` = auto, the first matching step wins: the directory does not
    exist here -> node; the job runs on this machine -> direct; the batch system
    calls it shared -> direct; otherwise -> node. The existence check comes first
    because PBS's `is_shared` reports a path that does not exist as shared.
    """
    if requested == ACCESS_NODE:
        return Access(ACCESS_NODE, "--access node")

    if requested == ACCESS_DIRECT:
        if not is_readable_dir(job.work_dir):
            raise XtcscopeError(
                f"Working directory {job.work_dir} is not readable on this machine.",
                EXIT_NO_WORK_DIR,
            )
        return Access(ACCESS_DIRECT, "--access direct")

    if not job.work_dir.is_dir():
        return Access(ACCESS_NODE)

    if is_this_host(job.node, local_names):
        return Access(ACCESS_DIRECT, "the job runs on this machine")

    if is_shared(job.work_dir):
        return Access(ACCESS_DIRECT, "shared storage")

    return Access(ACCESS_NODE)

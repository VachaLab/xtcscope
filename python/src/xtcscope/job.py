"""The qq job: finding it and what xtcscope needs to know about it."""

from dataclasses import dataclass
from pathlib import Path

from xtcscope.errors import EXIT_NO_JOB, EXIT_NO_WORK_DIR, XtcscopeError


@dataclass(frozen=True)
class Job:
    """What xtcscope needs to know about a qq job."""

    job_id: str
    name: str
    node: str
    work_dir: Path
    input_dir: Path


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
    )


def ssh_timeout() -> int:
    """qq's SSH timeout in seconds."""
    from qq_lib.core.config import CFG

    return CFG.timeouts.ssh

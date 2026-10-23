"""
The backend: resolving the job, listing its files and planning the extraction.

The frontend calls it in-process through `LocalBackend`. The same functions
answer the `xtcscope _backend` commands, which `--remote` runs on another machine.
"""

import argparse
import json
import os
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from xtcscope import __version__
from xtcscope.agent import AGENT, FetchPlan, extract_command, find_local_agent
from xtcscope.argtypes import file_path, frames_count, run_id
from xtcscope.errors import (
    EXIT_AGENT,
    EXIT_BACKEND,
    EXIT_MISMATCH,
    EXIT_NO_FILE,
    EXIT_OK,
    PROTOCOL,
    XtcscopeError,
)
from xtcscope.files import Candidate, list_gro_files, list_xtc_files
from xtcscope.job import (
    ACCESS_AUTO,
    ACCESS_DIRECT,
    ACCESS_MODES,
    ACCESS_NODE,
    Access,
    Job,
    decide_access,
    find_job,
    local_host_names,
    ssh_timeout,
    work_dir_is_shared,
)
from xtcscope.log import error, info, set_debug
from xtcscope.transport import (
    NODE_PERSIST,
    LocalRunner,
    Runner,
    SshRunner,
    node_ssh_options,
    socket_dir,
)

# the first argument that selects the backend commands
BACKEND_COMMAND = "_backend"


@dataclass(frozen=True)
class Inspection:
    """What `inspect` found: the job, how its working directory is read, the files."""

    # xtcscope version and host name of the backend that inspected the job
    version: str
    host: str
    job: Job
    access: Access
    gro: list[Candidate]
    xtc: list[Candidate]

    def to_json(self) -> dict[str, Any]:
        """The JSON document `_backend inspect` prints, without the protocol field."""
        job = asdict(self.job)
        job["work_dir"] = str(self.job.work_dir)
        job["input_dir"] = str(self.job.input_dir)
        return {
            "version": self.version,
            "host": self.host,
            "job": job,
            "access": asdict(self.access),
            "gro": [asdict(c) for c in self.gro],
            "xtc": [asdict(c) for c in self.xtc],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Inspection":
        """Rebuild an inspection from `to_json` output; KeyError or TypeError if malformed."""
        job = dict(data["job"])
        job["work_dir"] = Path(job["work_dir"])
        job["input_dir"] = Path(job["input_dir"])
        return cls(
            version=data["version"],
            host=data["host"],
            job=Job(**job),
            access=Access(**data["access"]),
            gro=[Candidate(**c) for c in data["gro"]],
            xtc=[Candidate(**c) for c in data["xtc"]],
        )


def node_runner(node: str, run: str) -> SshRunner:
    """The runner for `node`, with this run's control socket."""

    def options() -> list[str]:
        """The node options; qq's timeout is read only when a connection is opened."""
        return node_ssh_options(ssh_timeout())

    return SshRunner(node, socket_dir() / f"{run}-node", options, NODE_PERSIST)


def runner_for(mode: str, node: str, run: str) -> Runner:
    """The runner for an access mode: here for direct, the node otherwise."""
    return LocalRunner() if mode == ACCESS_DIRECT else node_runner(node, run)


def inspect(
    job_id: str | None, gro: str | None, xtc: str | None, access_mode: str, run: str
) -> tuple[Inspection, Runner]:
    """
    Resolve the job, decide the access, and list its GRO and XTC files.

    Returns the inspection and the runner that listed the XTC files, still open:
    the caller closes it, or leaves a node connection to expire (`_backend`).
    """
    job = find_job(job_id)
    info(f"Job {job.job_id} ({job.name}) runs on {job.node} in {job.work_dir}")

    access = decide_access(
        job,
        access_mode,
        is_shared=partial(work_dir_is_shared, job.batch_system),
        local_names=local_host_names(),
    )

    info(f"Reading the working directory {access.describe(job.node)}")
    if access.mode == ACCESS_DIRECT:
        find_local_agent()

    # the GRO comes from the input directory, before anything connects
    if not job.input_dir.is_dir():
        raise XtcscopeError(
            f"Input directory {job.input_dir} is not accessible from this machine.",
            EXIT_NO_FILE,
        )

    gro_files = list_gro_files(job.input_dir, gro)

    runner = runner_for(access.mode, job.node, run)
    runner.open()
    try:
        xtc_files = list_xtc_files(runner, job.work_dir, xtc)
    except BaseException:
        runner.close()
        raise

    inspection = Inspection(
        version=__version__,
        host=socket.getfqdn(),
        job=job,
        access=access,
        gro=gro_files,
        xtc=xtc_files,
    )

    return inspection, runner


def fetch_plan(mode: str, xtc: Path, frames: int, runner: Runner) -> FetchPlan:
    """The command that streams the last `frames` frames of `xtc`, through `runner`."""
    if mode == ACCESS_DIRECT:
        command = extract_command(xtc, frames, find_local_agent())
    else:
        # reopens the node connection if it expired since `inspect`
        runner.open()
        command = extract_command(xtc, frames, AGENT)

    return FetchPlan(runner.argv(command), runner.label, runner.lost_code)


class Backend(Protocol):
    """What the frontend needs from a backend, here or on another machine."""

    # where the backend runs, for messages and --dry-run
    label: str

    def location(self, path: Path) -> str:
        """How messages name a path where the backend runs."""
        ...

    def inspect(
        self, job_id: str | None, gro: str | None, xtc: str | None, access: str
    ) -> Inspection:
        """Resolve the job and list its files."""
        ...

    def gro_file(self, inspection: Inspection, name: str, tmp_dir: Path) -> Path:
        """A local path to the chosen GRO file."""
        ...

    def fetch_plan(self, inspection: Inspection, xtc: Path, frames: int) -> FetchPlan:
        """The command that streams the frames to this machine."""
        ...

    def close(self) -> None:
        """Release every connection; safe to call more than once."""
        ...


class LocalBackend:
    """The backend in this process: no protocol, and the GRO is used where it is."""

    label = "this machine"

    def location(self, path: Path) -> str:
        """A path on this machine, as it is."""
        return str(path)

    def __init__(self, run: str):
        """A backend whose connections are named after the run id `run`."""
        self.run = run
        self.runner: Runner | None = None

    def inspect(
        self, job_id: str | None, gro: str | None, xtc: str | None, access: str
    ) -> Inspection:
        """Resolve the job and list its files, keeping the connection for the fetch."""
        inspection, self.runner = inspect(job_id, gro, xtc, access, self.run)
        return inspection

    def gro_file(self, inspection: Inspection, name: str, tmp_dir: Path) -> Path:
        """The GRO in the input directory; this machine can read it."""
        _ = tmp_dir
        return inspection.job.input_dir / name

    def fetch_plan(self, inspection: Inspection, xtc: Path, frames: int) -> FetchPlan:
        """The extract command, through the connection `inspect` opened."""
        assert self.runner is not None, "inspect comes first"
        return fetch_plan(inspection.access.mode, xtc, frames, self.runner)

    def close(self) -> None:
        """Close the node connection, if there is one."""
        if self.runner is not None:
            self.runner.close()
            self.runner = None


def build_backend_parser() -> argparse.ArgumentParser:
    """The parser for `xtcscope _backend <command>`."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--protocol", type=int, required=True, help="Protocol of the caller.")
    common.add_argument("--run", type=run_id, required=True, help="Run id (8 hex characters).")
    common.add_argument("--debug", action="store_true", help="Print DEBUG lines on stderr.")

    parser = argparse.ArgumentParser(
        prog=f"xtcscope {BACKEND_COMMAND}",
        description="Internal commands that xtcscope --remote runs on the remote host.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser(
        "inspect", parents=[common], help="Print the job, its access and its files as JSON."
    )
    inspect_parser.add_argument("job_id")
    inspect_parser.add_argument("--gro", type=file_path(".gro"))
    inspect_parser.add_argument("--xtc", type=file_path(".xtc"))
    inspect_parser.add_argument("--access", choices=ACCESS_MODES, default=ACCESS_AUTO)

    gro_parser = commands.add_parser("gro", parents=[common], help="Write a GRO file to stdout.")
    gro_parser.add_argument("path", type=file_path(".gro"))

    fetch_parser = commands.add_parser(
        "fetch", parents=[common], help="Stream the last frames of an XTC to stdout."
    )
    fetch_parser.add_argument("--access", choices=(ACCESS_DIRECT, ACCESS_NODE), required=True)
    fetch_parser.add_argument("--node", required=True)
    fetch_parser.add_argument("--xtc", type=file_path(".xtc"), required=True)
    fetch_parser.add_argument("--frames", type=frames_count, required=True)

    close_parser = commands.add_parser(
        "close", parents=[common], help="Close this run's node connection."
    )
    close_parser.add_argument("--node", required=True)

    return parser


def check_protocol(caller: int) -> None:
    """Refuse a caller that speaks another protocol (exit 10)."""
    if caller != PROTOCOL:
        raise XtcscopeError(
            f"Backend protocol mismatch: xtcscope {__version__} on {socket.getfqdn()} "
            f"speaks protocol {PROTOCOL}, the caller speaks {caller}.",
            EXIT_BACKEND,
        )


def print_json(document: dict[str, Any]) -> None:
    """Print one JSON document on stdout, with the protocol field first."""
    print(json.dumps({"protocol": PROTOCOL, **document}), flush=True)


def backend_inspect(args: argparse.Namespace) -> int:
    """`_backend inspect`: the inspection as JSON; the node connection is left to expire."""
    inspection, _ = inspect(args.job_id, args.gro, args.xtc, args.access, args.run)
    print_json(inspection.to_json())
    return EXIT_OK


def backend_gro(args: argparse.Namespace) -> int:
    """`_backend gro`: the GRO file's bytes on stdout."""
    try:
        with open(args.path, "rb") as source:
            shutil.copyfileobj(source, sys.stdout.buffer)
    except OSError as err:
        raise XtcscopeError(
            f"Could not read '{args.path}': {err.strerror}.", EXIT_MISMATCH
        ) from err

    sys.stdout.buffer.flush()
    return EXIT_OK


def backend_fetch(args: argparse.Namespace) -> int:
    """`_backend fetch`: replace this process with the extraction, so its output passes through."""
    runner = runner_for(args.access, args.node, args.run)
    plan = fetch_plan(args.access, Path(args.xtc), args.frames, runner)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(plan.argv[0], plan.argv)


def backend_close(args: argparse.Namespace) -> int:
    """`_backend close`: close this run's node connection, if it is still open."""
    node_runner(args.node, args.run).close()
    return EXIT_OK


COMMANDS = {
    "inspect": backend_inspect,
    "gro": backend_gro,
    "fetch": backend_fetch,
    "close": backend_close,
}


def report_failure(command: str, err: XtcscopeError) -> None:
    """
    Report a failed command in the form its caller reads.

    `inspect` answers with a JSON error document on stdout; `fetch` with an
    agent-style error event on stderr, which the frontend already parses; the
    others with an ERROR line.
    """
    if command == "inspect":
        print_json(
            {"version": __version__, "error": {"message": str(err), "exit_code": err.exit_code}}
        )
    elif command == "fetch":
        code = "agent_missing" if err.exit_code == EXIT_AGENT else "backend"
        event = {"event": "error", "code": code, "message": str(err), "exit_code": err.exit_code}
        print(json.dumps(event), file=sys.stderr, flush=True)
    else:
        error(str(err))


def backend_main(argv: list[str]) -> int:
    """Run one `_backend` command; returns its exit code."""
    args = build_backend_parser().parse_args(argv)
    set_debug(args.debug)

    try:
        check_protocol(args.protocol)
        return COMMANDS[args.command](args)
    except XtcscopeError as err:
        report_failure(args.command, err)
        return err.exit_code

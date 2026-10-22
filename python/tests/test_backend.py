"""The `xtcscope _backend` commands, run as separate processes, as --remote will run them."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FAKE_XTC
from xtcscope.backend import Inspection
from xtcscope.errors import EXIT_AGENT, EXIT_BACKEND, EXIT_NO_FILE, EXIT_NO_JOB, PROTOCOL
from xtcscope.files import Candidate
from xtcscope.job import Access, Job

STUBS = Path(__file__).resolve().parent / "stubs"
RUN = "abcd1234"


class Backend:
    """
    Runs `xtcscope _backend ...` in a subprocess against the fake job.

    qq is replaced by the file-based stub in tests/stubs, which serves the
    job description written by `describe`; ssh, the agent and $HOME come from
    the `fake_job` fixture.
    """

    def __init__(self, fake_job):
        """Describe the fake job with the default details."""
        self.fake_job = fake_job
        self.description = fake_job.describe()

    def describe(self, **changes) -> None:
        """Change what the stub serves; `changes` override the defaults."""
        self.fake_job.describe(**changes)

    def __call__(self, *args: str, protocol: int = PROTOCOL) -> subprocess.CompletedProcess:
        """Run one backend command; stdout as bytes, stderr as text."""
        env = os.environ | {"PYTHONPATH": str(STUBS), "FAKE_QQ_JOB": str(self.description)}
        command, *rest = args
        argv = [sys.executable, "-m", "xtcscope", "_backend", command]
        argv += ["--protocol", str(protocol), "--run", RUN, *rest]
        result = subprocess.run(argv, capture_output=True, env=env)
        return subprocess.CompletedProcess(
            argv, result.returncode, result.stdout, result.stderr.decode()
        )


@pytest.fixture
def backend(fake_job) -> Backend:
    """A runner for `_backend` commands against the fake job."""
    return Backend(fake_job)


def masters(fake_job) -> int:
    """How many master connections were opened."""
    return sum("-M" in c for c in fake_job.ssh_calls())


def test_inspect_through_the_node(backend, fake_job):
    """inspect prints one JSON document and leaves the node connection open."""
    result = backend("inspect", "123.pbs")
    assert result.returncode == 0, result.stderr

    answer = json.loads(result.stdout)
    assert answer["protocol"] == PROTOCOL
    inspection = Inspection.from_json(answer)
    assert inspection.job.node == "node42"
    assert inspection.job.work_dir == fake_job.work
    assert inspection.access == Access("node")
    assert [(c.name, c.natoms) for c in inspection.gro] == [("conf.gro", 48213)]
    assert [(c.name, c.natoms) for c in inspection.xtc] == [("md.xtc", 48213)]

    assert masters(fake_job) == 1
    assert (fake_job.sockets / f"{RUN}-node").exists(), "left open for fetch"
    assert "Reading the working directory through node42" in result.stderr


def test_inspect_stdout_is_only_json_with_debug(backend):
    """--debug lines go to stderr; stdout stays one JSON document."""
    result = backend("inspect", "123.pbs", "--debug")
    assert result.returncode == 0
    json.loads(result.stdout)
    assert "DEBUG" in result.stderr


def test_inspect_shared_storage(backend, fake_job):
    """A shared working directory is inspected without any ssh call."""
    backend.describe(shared=True)
    result = backend("inspect", "123.pbs")
    assert json.loads(result.stdout)["access"] == {"mode": "direct", "reason": "shared storage"}
    assert fake_job.ssh_calls() == []


def test_inspect_errors_are_json(backend, fake_job):
    """A failure is a JSON error document with the usual exit code."""
    result = backend("inspect", "999.pbs")
    assert result.returncode == EXIT_NO_JOB
    answer = json.loads(result.stdout)
    assert answer["error"]["exit_code"] == EXIT_NO_JOB
    assert "999.pbs" in answer["error"]["message"]

    backend.describe(input_dir=str(fake_job.root / "gone"))
    result = backend("inspect", "123.pbs")
    assert result.returncode == EXIT_NO_FILE
    assert json.loads(result.stdout)["error"]["exit_code"] == EXIT_NO_FILE


def test_protocol_mismatch(backend, fake_job):
    """Another protocol is refused with exit 10, before anything is looked up."""
    result = backend("inspect", "123.pbs", protocol=PROTOCOL + 1)
    assert result.returncode == EXIT_BACKEND
    answer = json.loads(result.stdout)
    assert answer["error"]["exit_code"] == EXIT_BACKEND
    assert "protocol" in answer["error"]["message"]
    assert fake_job.calls() == []

    result = backend("close", "--node", "node42", protocol=PROTOCOL + 1)
    assert result.returncode == EXIT_BACKEND
    assert "protocol mismatch" in result.stderr


def test_bad_run_id(backend):
    """Run ids name sockets, so anything but 8 hex characters is a usage error."""
    env = os.environ | {"PYTHONPATH": str(STUBS)}
    argv = [sys.executable, "-m", "xtcscope", "_backend", "close"]
    argv += ["--protocol", "1", "--run", "../../x", "--node", "n"]
    assert subprocess.run(argv, capture_output=True, env=env).returncode == 2


def test_gro(backend, fake_job):
    """gro writes the file's bytes to stdout."""
    gro = fake_job.input / "conf.gro"
    result = backend("gro", str(gro))
    assert result.returncode == 0
    assert result.stdout == gro.read_bytes()


def test_gro_unreadable(backend, fake_job):
    """A missing GRO is exit 6 with an ERROR line."""
    result = backend("gro", str(fake_job.input / "missing.gro"))
    assert result.returncode == 6
    assert "Could not read" in result.stderr


def fetch(backend, access: str, fake_job):
    """Run `_backend fetch` for the fake XTC, 7 frames."""
    xtc = str(fake_job.work / "md.xtc")
    return backend("fetch", "--access", access, "--node", "node42", "--xtc", xtc, "--frames", "7")


def test_fetch_reuses_the_node_connection(backend, fake_job):
    """fetch streams the agent's output and reuses the connection inspect opened."""
    backend("inspect", "123.pbs")
    result = fetch(backend, "node", fake_job)
    assert result.returncode == 0, result.stderr
    assert result.stdout == FAKE_XTC
    events = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert [e["event"] for e in events] == ["located", "done"]
    assert masters(fake_job) == 1


def test_fetch_reconnects_after_expiry(backend, fake_job):
    """A node connection that expired since inspect is opened again."""
    backend("inspect", "123.pbs")
    (fake_job.sockets / f"{RUN}-node").unlink()
    result = fetch(backend, "node", fake_job)
    assert result.returncode == 0
    assert result.stdout == FAKE_XTC
    assert masters(fake_job) == 2


def test_fetch_direct(backend, fake_job):
    """Direct access runs the local agent, with no ssh."""
    result = fetch(backend, "direct", fake_job)
    assert result.returncode == 0
    assert result.stdout == FAKE_XTC
    assert fake_job.ssh_calls() == []


def test_fetch_direct_without_an_agent(backend, fake_job):
    """A missing local agent is an agent-style error event and exit 8."""
    fake_job.agent.unlink()
    result = fetch(backend, "direct", fake_job)
    assert result.returncode == EXIT_AGENT
    event = json.loads(result.stderr.strip().splitlines()[-1])
    assert event["event"] == "error" and event["code"] == "agent_missing"


def test_close(backend, fake_job):
    """close ends the run's node connection; without one it does nothing."""
    backend("inspect", "123.pbs")
    result = backend("close", "--node", "node42")
    assert result.returncode == 0
    assert not (fake_job.sockets / f"{RUN}-node").exists()

    before = len(fake_job.ssh_calls())
    assert backend("close", "--node", "node42").returncode == 0
    assert len(fake_job.ssh_calls()) == before


def test_inspection_round_trip(tmp_path):
    """to_json and from_json are inverses, through real JSON text."""
    inspection = Inspection(
        version="0.2.0",
        host="desktop.example.cz",
        job=Job("1.pbs", "md", "node42", tmp_path / "w", tmp_path / "i", "PBS"),
        access=Access("direct", "shared storage"),
        gro=[Candidate("conf.gro", 10, 1.5, 3)],
        xtc=[Candidate("md.xtc", 0, 2.0, None, "empty")],
    )
    assert Inspection.from_json(json.loads(json.dumps(inspection.to_json()))) == inspection

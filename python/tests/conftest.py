"""Shared fixtures: a fake job with fake ssh, agent and viewer."""

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from xtcscope.job import Job

# bytes the fake agent "extracts": an XTC header for 48213 atoms, then filler
FAKE_XTC = bytes.fromhex("000007cb0000bc55") + bytes(range(256)) * 4

# logs its arguments; the master connection and -O exit just succeed; a remote
# command replaces this process with bash, so terminating ssh stops the agent
FAKE_SSH = """\
#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["ssh", *args]) + "\\n")
if os.environ.get("FAKE_SSH_FAIL") and "-M" in args:
    print("ssh: connect to host node42: Connection refused", file=sys.stderr)
    sys.exit(255)
if "-M" in args or "-O" in args:
    sys.exit(0)
if os.environ.get("FAKE_SSH_DROP") and "extract" in args[-1]:
    print("Connection to node42 closed by remote host.", file=sys.stderr)
    sys.exit(255)
os.execvp("bash", ["bash", "-c", args[-1]])
"""

# behaves like `xtcscope-agent extract` according to FAKE_AGENT_MODE
FAKE_AGENT = """\
#!{python}
import json, os, sys, time
mode = os.environ.get("FAKE_AGENT_MODE", "ok")
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["agent", *sys.argv[1:]]) + "\\n")
data = bytes.fromhex(os.environ["FAKE_XTC_HEX"])
def event(**fields):
    print(json.dumps(fields), file=sys.stderr, flush=True)
if mode == "error":
    event(event="error", code="xtc_invalid", message="the first frame's header is invalid")
    sys.exit(1)
if mode == "crash":
    print("Segmentation fault", file=sys.stderr)
    sys.exit(139)
if mode == "sleep":
    with open(os.environ["FAKE_AGENT_PID"], "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
if mode == "noise":
    print("Warning: Permanently added 'node42' to the list of known hosts.", file=sys.stderr)
if mode == "warn":
    event(event="warning", code="trailing_data", message="unexpected data after the last frame")
claimed = len(data) + (100 if mode == "short" else 0)
event(event="located", version="0.1.0", magic=1995, natoms=48213, frames=10,
      first_step=0, last_step=9000, first_time_ps=0.0, last_time_ps=18.0, bytes=claimed)
sys.stdout.buffer.write(data)
sys.stdout.flush()
event(event="done", bytes=claimed)
"""

# records its arguments and the size of the XTC it was given
FAKE_VIEWER = """\
#!{python}
import json, os, sys
xtc = sys.argv[-1]
size = os.path.getsize(xtc) if os.path.exists(xtc) else None
same = open(xtc, "rb").read() == bytes.fromhex(os.environ["FAKE_XTC_HEX"]) if size else False
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["viewer", *sys.argv[1:], size, same]) + "\\n")
sys.exit(int(os.environ.get("FAKE_VIEWER_EXIT", "0")))
"""


def write_executable(path: Path, template: str) -> None:
    """Write a Python script from `template` and make it executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(template).format(python=sys.executable))
    path.chmod(0o755)


class FakeJob:
    """Paths and helpers of the fake job environment."""

    def __init__(self, root: Path):
        """Lay out the fake job under `root`."""
        self.root = root
        self.input = root / "input"
        self.work = root / "scratch"
        self.home = root / "home"
        self.log = root / "calls.log"
        self.agent = self.home / "xtcscope" / "xtcscope-agent"

    def calls(self) -> list[list]:
        """Every logged call, in order: ["ssh", ...], ["agent", ...], ["viewer", ...]."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def fake_job(tmp_path, monkeypatch):
    """
    A job on "node42": GRO in the input directory, XTC in the working directory,
    with fake ssh, agent (in $HOME on the "node") and viewer, and qq stubbed out.
    """
    job = FakeJob(tmp_path)
    write_executable(tmp_path / "bin" / "ssh", FAKE_SSH)
    write_executable(tmp_path / "bin" / "viamd", FAKE_VIEWER)
    write_executable(job.agent, FAKE_AGENT)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(job.home))
    monkeypatch.setenv("FAKE_LOG", str(job.log))
    monkeypatch.setenv("FAKE_XTC_HEX", FAKE_XTC.hex())
    monkeypatch.delenv("XTCSCOPE_VIEWER", raising=False)

    job.input.mkdir()
    (job.input / "conf.gro").write_text("title\n48213\n")
    job.work.mkdir()
    (job.work / "md.xtc").write_bytes(FAKE_XTC)

    # replaced where the flow looks them up, so qq is never imported
    stub = Job("123.pbs", "mdrun", "node42", job.work, job.input)
    monkeypatch.setattr("xtcscope.frontend.find_job", lambda job_id: stub)
    monkeypatch.setattr("xtcscope.frontend.ssh_timeout", lambda: 60)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    return job

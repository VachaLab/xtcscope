"""The access rule: read the working directory directly, or through the node."""

from pathlib import Path

import pytest

from xtcscope.errors import EXIT_NO_WORK_DIR, XtcscopeError
from xtcscope.job import Access, Job, decide_access, is_this_host

HERE = ("desktop.example.cz", "desktop")


def make_job(work_dir: Path, node: str = "node42") -> Job:
    """A job on `node` with the given working directory."""
    return Job("123.pbs", "md", node, work_dir, work_dir.parent, "PBS")


def decide(job: Job, requested: str = "auto", shared: bool = False) -> Access:
    """Run the rule with a fixed answer from `is_shared` and this machine's names."""
    return decide_access(job, requested, is_shared=lambda path: shared, local_names=HERE)


@pytest.mark.parametrize(
    ("exists", "node", "shared", "expected"),
    [
        (False, "node42", False, Access("node")),
        (False, "node42", True, Access("node")),
        (False, "desktop", True, Access("node")),
        (True, "node42", False, Access("node")),
        (True, "node42", True, Access("direct", "shared storage")),
        (True, "desktop", False, Access("direct", "the job runs on this machine")),
        (True, "desktop", True, Access("direct", "the job runs on this machine")),
    ],
)
def test_auto(tmp_path, exists, node, shared, expected):
    """The first matching step wins; nothing is direct unless the directory exists here."""
    work = tmp_path / "work"
    if exists:
        work.mkdir()
    assert decide(make_job(work, node), shared=shared) == expected


def test_shared_is_not_asked_about_a_missing_directory(tmp_path):
    """PBS's is_shared calls a missing path shared, so it must not be asked at all."""
    asked = []

    def is_shared(path):
        """Record the question."""
        asked.append(path)
        return True

    access = decide_access(make_job(tmp_path / "gone"), "auto", is_shared, HERE)
    assert access == Access("node") and asked == []


def test_override_node(tmp_path):
    """--access node goes through the node even for a job on this machine."""
    access = decide(make_job(tmp_path, node="desktop"), "node", shared=True)
    assert access == Access("node", "--access node")


def test_override_direct(tmp_path):
    """--access direct reads a readable directory directly, shared or not."""
    access = decide(make_job(tmp_path), "direct")
    assert access == Access("direct", "--access direct")


def test_override_direct_needs_the_directory(tmp_path):
    """--access direct without the directory here is exit 4."""
    with pytest.raises(XtcscopeError) as exc:
        decide(make_job(tmp_path / "gone"), "direct")
    assert exc.value.exit_code == EXIT_NO_WORK_DIR
    assert "is not readable on this machine" in str(exc.value)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("desktop.example.cz", True),
        ("desktop", True),
        ("desktop.other.org", True),
        ("node42", False),
        ("node42.example.cz", False),
        ("desk", False),
    ],
)
def test_host_names(node, expected):
    """A node is this machine by full name or by short name."""
    assert is_this_host(node, HERE) is expected


def test_empty_local_names_match_nothing():
    """An empty host name (e.g. getfqdn failing) never matches."""
    assert not is_this_host("node42", ("", ""))


def test_messages():
    """The INFO and --dry-run wording for each kind of access."""
    assert Access("node").describe("node42") == "through node42"
    assert Access("node", "--access node").describe("node42") == "through node42 (--access node)"
    assert Access("direct", "shared storage").describe("node42") == "directly (shared storage)"
    assert Access("node").summary("node42") == "node via node42"
    assert Access("direct", "shared storage").summary("node42") == "direct (shared storage)"

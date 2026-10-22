"""Stand-in for qq_lib.info."""

from pathlib import Path
from types import SimpleNamespace

from qq_lib import fake_job


class Informer:
    """The fake job's details, as qq's Informer exposes them."""

    def __init__(self, job: dict):
        """Wrap the fake job."""
        self.job = job
        self.info = SimpleNamespace(
            job_id=job["job_id"], job_name=job["name"], input_dir=Path(job["input_dir"])
        )
        self.batch_system = SimpleNamespace(env_name=lambda: job["batch_system"])

    @classmethod
    def from_job_id(cls, job_id: str) -> "Informer":
        """The informer for `job_id`; only the fake job exists."""
        job = fake_job()
        if job_id != job["job_id"]:
            raise RuntimeError(f"Job '{job_id}' does not exist")
        return cls(job)

    @classmethod
    def from_file(cls, file: Path) -> "Informer":
        """The informer for an info file; every file describes the fake job."""
        return cls(fake_job())

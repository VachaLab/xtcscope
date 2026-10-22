"""Stand-in for qq_lib.core.navigator."""

from pathlib import Path


class Navigator:
    """The job's main node and working directory."""

    def __init__(self, job: dict):
        """Keep the fake job."""
        self.job = job

    @classmethod
    def from_informer(cls, informer) -> "Navigator":
        """The navigator for an informer's job."""
        return cls(informer.job)

    def has_destination(self) -> bool:
        """Whether the job has a node and a working directory."""
        return bool(self.job.get("node") and self.job.get("work_dir"))

    def get_main_node(self) -> str | None:
        """The main node."""
        return self.job.get("node")

    def get_work_dir(self) -> Path | None:
        """The working directory."""
        return Path(self.job["work_dir"]) if self.job.get("work_dir") else None

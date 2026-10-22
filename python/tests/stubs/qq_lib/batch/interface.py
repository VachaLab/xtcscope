"""Stand-in for qq_lib.batch.interface."""

from pathlib import Path

from qq_lib import fake_job


class BatchInterface:
    """A batch system whose storage is shared when the fake job says so."""

    @classmethod
    def from_str(cls, name: str) -> type["BatchInterface"]:
        """Every name gives this class."""
        return cls

    @classmethod
    def is_shared(cls, directory: Path) -> bool:
        """The fake job's `shared` flag."""
        return bool(fake_job().get("shared", False))

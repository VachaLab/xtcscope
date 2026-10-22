"""Stand-in for qq_lib.core.common."""

from pathlib import Path


def get_info_files(directory: Path) -> list[Path]:
    """The qq info files in `directory`."""
    return sorted(directory.glob("*.qqinfo"))

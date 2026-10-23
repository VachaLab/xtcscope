"""The process environment of a PyInstaller build."""

import os
import sys


def restore_library_path() -> None:
    """
    Undo the PyInstaller bootloader's LD_LIBRARY_PATH for the programs xtcscope starts.

    In a frozen build the bootloader points LD_LIBRARY_PATH at the bundle's
    _internal/ directory and keeps the user's value in LD_LIBRARY_PATH_ORIG.
    Every child (ssh, bash, the agent, the viewer) would inherit it and could
    load the bundle's libraries instead of the system's, which can break ssh's
    Kerberos (GSSAPI) authentication or a viewer. xtcscope itself is already
    loaded, so restoring the variable changes only what the children see.
    """
    if not getattr(sys, "frozen", False):
        return

    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original

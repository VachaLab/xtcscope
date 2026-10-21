# Changelog

## Unreleased

- xtcscope is now a Python package (`python/`) released as a PyInstaller bundle, built in a manylinux_2_28 container: uv is no longer needed on the machines it runs on. The behaviour is unchanged.
- The release tarball holds the `xtcscope` executable with its `_internal/` runtime; the installer checks for it.
- The release workflow checks that the tag matches both `agent/Cargo.toml` and `python/src/xtcscope/__init__.py`, and checks the bundle's glibc floor (2.28).

## v0.1.0

First release.

- `xtcscope` script: finds a qq job (by ID, or the newest in the current directory), takes the GRO from its input directory and the XTC from its working directory (asking when there are several), checks that their atom counts match, copies the last N frames (default 10) from the compute node through one SSH connection, and opens them in a viewer: VMD 1.9, VMD 2, ViaMD or any program that opens `<command> <gro> <xtc>` (`--viewer`, `XTCSCOPE_VIEWER`). `--dry-run` and `--debug` for checking what it does.
- `xtcscope-agent`: finds the last complete frames of an XTC by scanning backwards from the end, skipping a frame mdrun is still writing, with a forward-scan fallback and warnings for damaged files; copies their bytes unchanged (`extract`); `inspect` for debugging. A static x86_64 binary.
- Installers for Robox (desktop and cluster homes) and a release workflow that builds and attaches everything to a published GitHub release.

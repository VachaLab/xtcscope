# Changelog

## v0.1.0

First release.

- `xtcscope` script: finds a qq job (by ID, or the newest in the current directory), takes the GRO from its input directory and the XTC from its working directory (asking when there are several), checks that their atom counts match, copies the last N frames (default 10) from the compute node through one SSH connection, and opens them in a viewer: VMD 1.9, VMD 2, ViaMD or any program that opens `<command> <gro> <xtc>` (`--viewer`, `XTCSCOPE_VIEWER`). `--dry-run` and `--debug` for checking what it does.
- `xtcscope-agent`: finds the last complete frames of an XTC by scanning backwards from the end, skipping a frame mdrun is still writing, with a forward-scan fallback and warnings for damaged files; copies their bytes unchanged (`extract`); `inspect` for debugging. A static x86_64 binary.
- Installers for Robox (desktop and cluster homes) that never edit startup files, and a release workflow that builds and attaches everything to a published GitHub release.

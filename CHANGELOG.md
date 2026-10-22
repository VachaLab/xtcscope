# Changelog

## Unreleased

## v0.2.0

- `--remote HOST`: look up the job and extract its frames on `HOST` (any destination `ssh` accepts, such as an alias from `~/.ssh/config`), and view them here, e.g. from a laptop at home. One SSH connection carries the whole run, so a password is asked for at most once. Both machines need the same release: a different version is a warning, an incompatible one exit 10.
- The working directory is read directly, without SSH to the compute node, when it exists where the job is looked up and is either shared storage or belongs to a job running on that machine. `--access auto|direct|node` overrides the choice.
- Installers for Metacentrum, Sokar, Karolina and LUMI, and `xtcscope-desktop-install.sh` for a machine without a batch system. Every installer adds `xtcscope` to `PATH` in `.bashrc`.
- xtcscope ships as a self-contained bundle (PyInstaller, glibc 2.28 or newer): uv is no longer needed.
- New exit code 10: xtcscope on the `--remote` host failed. Exit codes 4 and 7 also cover `--access direct` and the `--remote` host.
- An interrupted run leaves no SSH connection open for more than a few minutes.
- The agent no longer contains an XTC decoder (molly is only used by its tests), and `inspect --decode` is gone. Its output is unchanged.

## v0.1.0

First release.

- `xtcscope` script: finds a qq job (by ID, or the newest in the current directory), takes the GRO from its input directory and the XTC from its working directory (asking when there are several), checks that their atom counts match, copies the last N frames (default 10) from the compute node through one SSH connection, and opens them in a viewer: VMD 1.9, VMD 2, ViaMD or any program that opens `<command> <gro> <xtc>` (`--viewer`, `XTCSCOPE_VIEWER`). `--dry-run` and `--debug` for checking what it does.
- `xtcscope-agent`: finds the last complete frames of an XTC by scanning backwards from the end, skipping a frame mdrun is still writing, with a forward-scan fallback and warnings for damaged files; copies their bytes unchanged (`extract`); `inspect` for debugging. A static x86_64 binary.
- Installers for Robox (desktop and cluster homes) and a release workflow that builds and attaches everything to a published GitHub release.

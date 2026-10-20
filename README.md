# xtcscope

View the last frames of a running GROMACS job in VMD 1.9, VMD 2, ViaMD or any
viewer that opens `<command> <gro> <xtc>`, even when the trajectory sits on the
compute node's local scratch.

A small agent on the compute node finds the last complete frames of the XTC and
copies their bytes, unchanged, through SSH into a temporary file on your desktop;
the viewer opens that file like any trajectory. Only compressed coordinates cross
the network.

> **Status:** feature-complete for v0.1 (milestone 5); documentation and the
> first release follow.

## Installing on Robox

Install or update the latest release on your desktop and the compute nodes:

```
bash <(curl -fsSL https://github.com/VachaLab/xtcscope/releases/latest/download/xtcscope-robox-install.sh)
```

Pre-releases are never "latest"; install one with its own URL,
`https://github.com/VachaLab/xtcscope/releases/download/<tag>/xtcscope-robox-install.sh`.

It installs `xtcscope/` (the `xtcscope` script, the `xtcscope-agent` binary and
`VERSION`) into `$HOME` and into `/storage/brno14-ceitec/home/$USER`. Running it
again with the same version changes nothing. It never edits `.bashrc` or other
startup files: run `~/xtcscope/xtcscope` by its full path, or add an alias.

The installer refuses to touch an existing `~/xtcscope` that is not an
installation, so don't clone this repository to `~/xtcscope`.

## Usage

```
~/xtcscope/xtcscope [JOB_ID] [--viewer CMD] [--gro NAME] [--xtc NAME] [-n N] [--dry-run]
```

Without a job ID, the newest qq job in the current directory is used. The GRO
is taken from the job's input directory and the XTC from its working directory;
if there are several, you are asked to choose. The last N frames (default 10)
are copied into a temporary directory and opened in the viewer; they are deleted
when the viewer exits.

The viewer is `vmd` unless `--viewer` or the `XTCSCOPE_VIEWER` environment
variable says otherwise, e.g. `export XTCSCOPE_VIEWER=viamd` or
`--viewer "vmd -nt"`. Any program that opens `<command> <gro> <xtc>` works.

`--dry-run` shows what would be fetched and opened without doing it; `--debug`
prints every command and every message from the agent.

## Repository layout

```
script/xtcscope     desktop script (Python, run with uv)
script/tests/       pytest tests for the script
agent/              xtcscope-agent (Rust)
install/            installers and their tests
.github/workflows/  CI and release
```

## Development

Agent:

```
cd agent
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Try the frame location on a trajectory:

```
cargo run --release -- inspect --xtc traj.xtc -n 10 --decode
```

Extract the last frames by hand (on the compute node, or over SSH):

```
xtcscope-agent extract --xtc traj.xtc -n 10 > last.xtc
ssh <node> '$HOME/xtcscope/xtcscope-agent extract --xtc /scratch/.../traj.xtc -n 10' > last.xtc
vmd conf.gro last.xtc
```

`extract` writes the XTC data to stdout and JSON events (`located`, warnings,
`done`, errors) to stderr. It refuses to write to a terminal.

Script (its tests need neither qq nor a cluster; `--dry-run` needs both):

```
uvx ruff check .
uvx ruff format --check .
uvx --python 3.13 pytest
script/xtcscope --help      # first run fetches qq through uv
```

Installers:

```
shellcheck install/*.sh install/tests/*.sh
bash install/tests/run.sh
```

## Releasing

1. Set `version` in `agent/Cargo.toml` (e.g. `0.1.0`, or `0.1.0-alpha.1` for a
   pre-release), run `cargo build` in `agent/` to update `Cargo.lock`, commit and
   push.
2. On GitHub, draft a new release with a new tag `v<version>` on that commit,
   tick "Set as a pre-release" for versions with a suffix, and publish it.

Publishing triggers the release workflow. It fails unless the tag matches
`agent/Cargo.toml`. It builds a static `x86_64-unknown-linux-musl` agent, fills
the version and repository into the script and installers, smoke-tests the
installer, attaches the tarball, both installers and `sha256sums.txt` to the
release. Re-running the workflow replaces the attached files.

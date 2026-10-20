# xtcscope

View the last frames of a running GROMACS job in VMD, even when the trajectory
sits on the compute node's local scratch.

A small agent on the compute node finds the last complete frames of the XTC and
copies their bytes, unchanged, through SSH into a temporary file on your desktop;
VMD opens that file like any trajectory. Only compressed coordinates cross the
network.

> **Status:** under development (milestone 3: releases and installers). Not
> usable end to end yet.

## Installation (robox)

Each GitHub release has an installer for your desktop and the compute nodes:

```
bash <(curl -fsSL https://github.com/<owner>/<repo>/releases/download/vX.Y.Z/xtcscope-robox-install.sh)
```

It installs `xtcscope/` (the `xtcscope` script, the `xtcscope-agent` binary and
`VERSION`) into `$HOME` and into `/storage/brno14-ceitec/home/$USER`. Running it
again with the same version changes nothing. It never edits `.bashrc` or other
startup files: run `~/xtcscope/xtcscope` by its full path, or add an alias.

The installer refuses to touch an existing `~/xtcscope` that is not an
installation, so don't clone this repository to `~/xtcscope`.

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
vmd -gro conf.gro -xtc last.xtc
```

`extract` writes the XTC data to stdout and JSON events (`located`, warnings,
`done`, errors) to stderr. It refuses to write to a terminal.

Script:

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
   pre-release) and run `cargo build` in `agent/` to update `Cargo.lock`.
2. Commit, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.

The release workflow fails unless the tag matches `agent/Cargo.toml`. It builds a
static `x86_64-unknown-linux-musl` agent, fills the version and repository into
the script and installers, smoke-tests the installer, and publishes the tarball,
both installers and `sha256sums.txt`. Versions with a suffix are published as
pre-releases.

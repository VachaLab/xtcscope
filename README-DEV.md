# xtcscope: development

## Repository layout

```
script/xtcscope     desktop script (Python, run with uv)
script/tests/       pytest tests for the script (no qq or cluster needed)
agent/              xtcscope-agent (Rust)
agent/tests/        integration tests; XTC fixtures generated with molly
install/            installers and their tests
.github/workflows/  CI and release
```

## Rust agent

```bash
cd agent
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Try the frame location on a trajectory:

```bash
cargo run --release -- inspect --xtc traj.xtc -n 10 --decode
```

Extract the last frames by hand (on the compute node, or over SSH):

```bash
xtcscope-agent extract --xtc traj.xtc -n 10 > last.xtc
ssh <node> '$HOME/xtcscope/xtcscope-agent extract --xtc /scratch/.../traj.xtc -n 10' > last.xtc
vmd conf.gro last.xtc
```

`extract` writes the XTC data to stdout and JSON events (`located`, warnings, `done`, errors) to stderr.

A static binary for the nodes, as the release builds it:

```bash
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
```

## Python script

The tests need neither qq nor a cluster: qq is replaced by a stub, and fake `ssh`, agent and viewer programs are put on `PATH`. `--dry-run` against a real job needs both.

```bash
uvx ruff check .
uvx ruff format --check .
uvx --python 3.13 pytest
script/xtcscope --help      # first run fetches qq through uv
```

## Installers

```bash
shellcheck install/*.sh install/tests/*.sh
bash install/tests/run.sh
```

## Releasing

1. Set `version` in `agent/Cargo.toml` (e.g. `0.1.0`, or `0.1.0-alpha.1` for a pre-release), run `cargo build` in `agent/` to update `Cargo.lock`, move the CHANGELOG's "Unreleased" entries under the new version, commit and push.
2. On GitHub, draft a new release with a new tag `v<version>` on that commit, and publish it.

Publishing triggers the release workflow. It fails unless the tag matches `agent/Cargo.toml`. It builds a static `x86_64-unknown-linux-musl` agent, fills the version and repository into the script and installers, smoke-tests the installer, and attaches the tarball, both installers and `sha256sums.txt` to the release. Re-running the workflow replaces the attached files.

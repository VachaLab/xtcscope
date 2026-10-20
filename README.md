# xtcscope

View the last frames of a running GROMACS job in VMD, even when the trajectory
sits on the compute node's local scratch.

A small agent on the compute node reads the XTC and serves its frames over the
IMD protocol; an SSH tunnel carries them to VMD on your desktop, which renders
them locally. Only coordinates cross the network.

> **Status:** under development (milestone 0: repository skeleton). Not usable yet.

## Repository layout

```
script/xtcscope     desktop script (Python, run with uv)
script/tests/       pytest tests for the script
agent/              xtcscope-agent (Rust)
install/            installation scripts (milestone 3)
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

Script:

```
uvx ruff check .
uvx ruff format --check .
uvx --python 3.13 pytest
script/xtcscope --help      # first run fetches qq through uv
```

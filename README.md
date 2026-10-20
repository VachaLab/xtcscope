# xtcscope

View the last frames of a running GROMACS job in VMD, even when the trajectory
sits on the compute node's local scratch.

A small agent on the compute node finds the last complete frames of the XTC and
copies their bytes, unchanged, through SSH into a temporary file on your desktop;
VMD opens that file like any trajectory. Only compressed coordinates cross the
network.

> **Status:** under development (milestone 2: the agent extracts the last frames
> as an XTC file). Not usable end to end yet.

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

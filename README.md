# xtcscope

View the last frames of a running GROMACS job in VMD, even when the trajectory
sits on the compute node's local scratch.

A small agent on the compute node reads the XTC and serves its frames over the
IMD protocol; an SSH tunnel carries them to VMD on your desktop, which renders
them locally. Only coordinates cross the network.

> **Status:** under development (milestone 2: the agent serves frames to VMD over
> IMDv2). Not usable end to end yet.

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

Serve frames to a local VMD (VMD connects over TCP, the agent listens on a Unix
socket, so `socat` bridges the two):

```
cargo run --release -- serve --xtc traj.xtc --socket /tmp/xtcscope-test.sock -n 10
socat TCP-LISTEN:8888,bind=127.0.0.1 UNIX-CONNECT:/tmp/xtcscope-test.sock
```

then in VMD's Tk console:

```
mol new conf.gro type gro waitfor all
imd keep 1
imd connect localhost 8888
```

The agent exits when VMD disconnects (`imd detach`), on Ctrl-C, or when its
stdin closes.

Script:

```
uvx ruff check .
uvx ruff format --check .
uvx --python 3.13 pytest
script/xtcscope --help      # first run fetches qq through uv
```

# xtcscope: development

## Repository layout

```
python/                 the xtcscope command (Python package, uv project)
python/src/xtcscope/    the package; __init__.py holds the version
python/tests/           pytest tests (no qq or cluster needed)
python/xtcscope.spec    PyInstaller spec
python/build-bundle.sh  builds and checks the PyInstaller bundle
agent/                  xtcscope-agent (Rust)
agent/tests/            integration tests; XTC fixtures generated with molly
install/                installers and their tests
.github/workflows/      CI and release
```

Modules of the package:

| Module | Contents |
| --- | --- |
| `cli.py` | options, `main()`, exit handling, signals; hands `_backend` to `backend.py` |
| `frontend.py` | `run()`: the flow from arguments to the closed viewer, through a backend |
| `backend.py` | resolving the job, listing its files, planning the extraction (`LocalBackend`); the `_backend` commands |
| `job.py` | finding the job through qq; the access rule (direct or through the node) |
| `files.py` | GRO and XTC listings, atom counts, size and time formatting |
| `choose.py` | choosing a file: requested, the only one, or by asking |
| `transport.py` | running commands here (`LocalRunner`) or on a node over SSH (`SshRunner`); the control-socket directory |
| `agent.py` | the extract command and reading the agent's output |
| `viewer.py` | checking and running the viewer |
| `errors.py`, `log.py` | exit codes, `XtcscopeError`, the backend protocol version, messages |
| `argtypes.py` | argparse types shared by both command lines |

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

## Python package

Everything runs from `python/`. The tests need neither qq nor a cluster: the job lookup is replaced by a stub, and fake `ssh`, agent and viewer programs are put on `PATH`. Tests that run `xtcscope _backend` in a subprocess put `tests/stubs` on `PYTHONPATH`, where a small stand-in for `qq_lib` serves the job described in `$FAKE_QQ_JOB`. `--dry-run` against a real job needs both.

The backend commands can be tried by hand on a machine with qq (`--run` is any 8 hex characters):

```bash
xtcscope _backend inspect --protocol 1 --run abcd1234 <job_id>
xtcscope _backend close --protocol 1 --run abcd1234 --node <node>
```

```bash
cd python
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
uv run xtcscope --help      # or: uv run python -m xtcscope --help
```

The bundle, as CI and the release build it (in the `quay.io/pypa/manylinux_2_28_x86_64` container there):

```bash
python/build-bundle.sh      # result in python/dist/xtcscope/
```

It uses a uv-managed Python, so a local build has the same glibc floor as a release. It fails if anything in the bundle needs a glibc newer than 2.28, if `--version` is wrong, or if the frozen build cannot import qq.

## Installers

```bash
shellcheck install/*.sh install/tests/*.sh python/build-bundle.sh
bash install/tests/run.sh
```

## Releasing

1. Set the same version in `agent/Cargo.toml` and in `python/src/xtcscope/__init__.py` (e.g. `0.2.0`, or `0.2.0-alpha.1` for a pre-release). Run `cargo build` in `agent/` and `uv lock` in `python/` to update the lock files, move the CHANGELOG's "Unreleased" entries under the new version, commit and push.
2. On GitHub, draft a new release with a new tag `v<version>` on that commit, and publish it.

Publishing triggers the release workflow. It fails unless the tag matches both versions. It builds a static `x86_64-unknown-linux-musl` agent and the PyInstaller bundle (with `build-bundle.sh`, in the manylinux container) in parallel, puts both into the tarball, fills the version and repository into the installers, smoke-tests the installer, and attaches the tarball, every installer and `sha256sums.txt` to the release. Re-running the workflow replaces the attached files.

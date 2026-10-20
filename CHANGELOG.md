# Changelog

## Unreleased

- Script: find the job with qq (by ID, or the newest in the current directory),
  check its working directory, open one SSH master connection, choose the GRO
  from the input directory and the XTC from the working directory (listed over
  SSH with atom counts; ask when there are several), check that the atom counts
  match; `--dry-run` prints the extract and viewer commands. Any viewer that
  opens `<command> <gro> <xtc>`: `--viewer` or `XTCSCOPE_VIEWER`, default `vmd`.
- Releases: publishing a GitHub release runs `release.yml`, which checks the
  tag against `agent/Cargo.toml`, builds a static musl agent, fills version and
  repository into the script and installers, smoke-tests the installer, and
  attaches the files with checksums to the release.
- Installers: `xtcscope-install.sh <home> <url>` and `xtcscope-robox-install.sh`
  (desktop and cluster homes); same version left alone, no startup files edited,
  an existing non-installation `~/xtcscope` refused; tests in `install/tests`.
- Agent: `extract` subcommand writing the last N complete frames to stdout as
  a valid XTC file (bytes copied unchanged, nothing decoded), with `located`,
  `done`, warning and error events as JSON lines on stderr; refuses to write to
  a terminal. Replaces the IMD server of the first milestone 2 attempt, which
  lost frames in VMD and could not carry the box.
- Agent: locate the last N complete frames of an XTC by scanning backwards from
  the end, with a forward-scan fallback and `scan_fallback`, `scan_stopped` and
  `trailing_data` warnings; decode them with molly 0.7.0; `inspect` subcommand
  printing the located frames as JSON lines (`--decode` to also decode them).
- Repository skeleton: agent answering `--version`, script stub answering
  `--help` and `--version`, CI for Rust, Python and shell.

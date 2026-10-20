# Changelog

## Unreleased

- Agent: locate the last N complete frames of an XTC by scanning backwards from
  the end, with a forward-scan fallback and `scan_fallback`, `scan_stopped` and
  `trailing_data` warnings; decode them with molly 0.7.0; `inspect` subcommand
  printing the located frames as JSON lines (`--decode` to also decode them).
- Repository skeleton: agent answering `--version`, script stub answering
  `--help` and `--version`, CI for Rust, Python and shell.

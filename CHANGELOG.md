# Changelog

## Unreleased

- Agent: `serve` subcommand streaming the last N frames to one IMDv2 client
  (VMD 1.9) on a Unix socket created with mode 0600 and removed on exit;
  handshake, Go, Coordinates in Å; Pause (toggle), Disconnect, Kill and
  MD-communication handling; `ready`, `connected`, `done`, `disconnected` and
  `error` events; shutdown on stdin EOF, SIGHUP, SIGINT and SIGTERM.
- Agent: locate the last N complete frames of an XTC by scanning backwards from
  the end, with a forward-scan fallback and `scan_fallback`, `scan_stopped` and
  `trailing_data` warnings; decode them with molly 0.7.0; `inspect` subcommand
  printing the located frames as JSON lines (`--decode` to also decode them).
- Repository skeleton: agent answering `--version`, script stub answering
  `--help` and `--version`, CI for Rust, Python and shell.

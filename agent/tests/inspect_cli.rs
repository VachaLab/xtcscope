//! The `inspect` subcommand, run as a process.

mod common;

use std::io::Write;
use std::process::{Command, Output};

use common::{make_xtc, reference};
use molly::Magic;
use serde_json::Value;

/// Run the agent binary with `args`.
fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_xtcscope-agent"))
        .args(args)
        .output()
        .unwrap()
}

/// Parse the JSON lines the agent printed on stdout.
fn events(output: &Output) -> Vec<Value> {
    String::from_utf8(output.stdout.clone())
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

/// Write `data` to a temporary `.xtc` file.
fn temp_xtc(data: &[u8]) -> tempfile::NamedTempFile {
    let mut file = tempfile::Builder::new().suffix(".xtc").tempfile().unwrap();
    file.write_all(data).unwrap();
    file.flush().unwrap();
    file
}

/// `inspect` prints one frame event per located frame.
#[test]
fn lists_the_last_frames() {
    let data = make_xtc(Magic::Xtc1995, 200, 25);
    let (offsets, _) = reference(&data);
    let file = temp_xtc(&data);
    let output = run(&["inspect", "--xtc", file.path().to_str().unwrap(), "-n", "3"]);
    assert!(output.status.success());
    let events = events(&output);
    assert_eq!(events.len(), 3);
    for (event, i) in events.iter().zip(22..25) {
        assert_eq!(event["event"], "frame");
        assert_eq!(event["offset"], offsets[i]);
        assert_eq!(event["step"], i as u64 * 1000);
        assert_eq!(event["time_ps"], i as f64 * 2.0);
        assert!(event.get("natoms").is_none());
    }
}

/// `--decode` adds the atom count and the first position.
#[test]
fn decode_adds_atoms_and_first_position() {
    let data = make_xtc(Magic::Xtc2023, 200, 4);
    let file = temp_xtc(&data);
    let output = run(&[
        "inspect",
        "--xtc",
        file.path().to_str().unwrap(),
        "--decode",
    ]);
    assert!(output.status.success());
    let events = events(&output);
    assert_eq!(events.len(), 4);
    for event in &events {
        assert_eq!(event["natoms"], 200);
        assert_eq!(event["first_position_nm"].as_array().unwrap().len(), 3);
    }
}

/// Warnings precede the frames and are logged on stderr too.
#[test]
fn warnings_come_first_and_go_to_stderr_too() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 25);
    let (offsets, _) = reference(&data);
    let bad = offsets[10] as usize;
    data[bad..bad + 4].copy_from_slice(&[0, 0, 0, 0]);
    let file = temp_xtc(&data);
    let output = run(&[
        "inspect",
        "--xtc",
        file.path().to_str().unwrap(),
        "-n",
        "20",
    ]);
    assert!(output.status.success());
    let events = events(&output);
    assert_eq!(events[0]["event"], "warning");
    assert_eq!(events[0]["code"], "scan_fallback");
    assert_eq!(events[1]["event"], "warning");
    assert_eq!(events[1]["code"], "scan_stopped");
    assert_eq!(events.len(), 2 + 14);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("warning (scan_fallback)"));
}

/// Errors print one error event and exit 1.
#[test]
fn errors_exit_one_with_an_error_event() {
    let text = temp_xtc(&b"definitely not an xtc file\n".repeat(5));
    for (path, code) in [
        (text.path().to_str().unwrap(), "xtc_invalid"),
        ("/nonexistent/traj.xtc", "xtc_open"),
    ] {
        let output = run(&["inspect", "--xtc", path]);
        assert_eq!(output.status.code(), Some(1));
        let events = events(&output);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["event"], "error");
        assert_eq!(events[0]["code"], code);
    }
}

/// Without arguments, usage is printed and the exit code is 2.
#[test]
fn no_arguments_prints_help_and_fails() {
    let output = run(&[]);
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("Usage"));
}

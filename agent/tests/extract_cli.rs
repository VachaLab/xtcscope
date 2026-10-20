//! The `extract` subcommand, run as a process: XTC bytes on stdout, JSON
//! events on stderr.

mod common;

use std::io::{Read, Write};
use std::process::{Command, Output, Stdio};

use common::{make_xtc, reference};
use molly::{Magic, XTCReader};
use serde_json::Value;

/// Write `data` to a temporary `.xtc` file.
fn temp_xtc(data: &[u8]) -> tempfile::NamedTempFile {
    let mut file = tempfile::Builder::new().suffix(".xtc").tempfile().unwrap();
    file.write_all(data).unwrap();
    file.flush().unwrap();
    file
}

/// Run `extract` on `data` with extra arguments; stdout and stderr are captured.
fn extract(data: &[u8], extra: &[&str]) -> Output {
    let file = temp_xtc(data);
    Command::new(env!("CARGO_BIN_EXE_xtcscope-agent"))
        .arg("extract")
        .arg("--xtc")
        .arg(file.path())
        .args(extra)
        .output()
        .unwrap()
}

/// The JSON events the agent wrote on stderr.
fn events(output: &Output) -> Vec<Value> {
    String::from_utf8(output.stderr.clone())
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

/// Read every frame of an in-memory XTC with molly.
fn read_back(bytes: &[u8]) -> Vec<molly::Frame> {
    let mut file = tempfile::NamedTempFile::new().unwrap();
    file.write_all(bytes).unwrap();
    file.flush().unwrap();
    XTCReader::open(file.path())
        .unwrap()
        .read_all_frames()
        .unwrap()
        .into_vec()
}

/// The output is exactly the bytes of the last N frames, and molly reads it
/// back with the same steps, times and positions.
#[test]
fn writes_the_last_frames_as_a_valid_xtc() {
    for magic in [Magic::Xtc1995, Magic::Xtc2023] {
        let data = make_xtc(magic, 200, 25);
        let (offsets, ref_frames) = reference(&data);
        let output = extract(&data, &["-n", "10"]);
        assert!(output.status.success(), "magic {magic:?}");

        let start = offsets[15] as usize;
        assert_eq!(output.stdout, &data[start..], "magic {magic:?}");
        assert_eq!(read_back(&output.stdout), ref_frames[15..].to_vec());

        let events = events(&output);
        assert_eq!(events.len(), 2);
        let located = &events[0];
        assert_eq!(located["event"], "located");
        assert_eq!(located["version"], env!("CARGO_PKG_VERSION"));
        assert_eq!(located["magic"], magic as i32);
        assert_eq!(located["natoms"], 200);
        assert_eq!(located["frames"], 10);
        assert_eq!(located["first_step"], 15_000);
        assert_eq!(located["last_step"], 24_000);
        assert_eq!(located["first_time_ps"], 30.0);
        assert_eq!(located["last_time_ps"], 48.0);
        assert_eq!(located["bytes"], output.stdout.len());
        assert_eq!(events[1]["event"], "done");
        assert_eq!(events[1]["bytes"], output.stdout.len());
    }
}

/// A file with fewer frames than requested is copied whole.
#[test]
fn copies_everything_when_the_file_has_fewer_frames() {
    let data = make_xtc(Magic::Xtc1995, 5, 3);
    let output = extract(&data, &["-n", "10"]);
    assert!(output.status.success());
    assert_eq!(output.stdout, data);
    assert_eq!(events(&output)[0]["frames"], 3);
}

/// The frame mdrun is still writing is left out.
#[test]
fn half_written_last_frame_is_left_out() {
    let data = make_xtc(Magic::Xtc1995, 200, 12);
    let (offsets, ref_frames) = reference(&data);
    let cut = offsets[11] as usize + 50;
    let output = extract(&data[..cut], &["-n", "10"]);
    assert!(output.status.success());
    assert_eq!(
        output.stdout,
        &data[offsets[1] as usize..offsets[11] as usize]
    );
    assert_eq!(read_back(&output.stdout), ref_frames[1..11].to_vec());
}

/// Trailing garbage is not copied, and the warning arrives before `located`.
#[test]
fn trailing_garbage_is_left_out_with_a_warning() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 5);
    let clean_len = data.len();
    data.extend(std::iter::repeat_n(0xAB, 100));
    let output = extract(&data, &[]);
    assert!(output.status.success());
    assert_eq!(output.stdout, &data[..clean_len]);
    let events = events(&output);
    assert_eq!(events[0]["event"], "warning");
    assert_eq!(events[0]["code"], "trailing_data");
    assert_eq!(events[1]["event"], "located");
    assert_eq!(events[2]["event"], "done");
}

/// After damage mid-file, the frames after the damage are a valid XTC.
#[test]
fn frames_after_damage_form_a_valid_file() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 25);
    let (offsets, ref_frames) = reference(&data);
    let bad = offsets[10] as usize;
    data[bad..bad + 4].copy_from_slice(&[0, 0, 0, 0]);
    let output = extract(&data, &["-n", "20"]);
    assert!(output.status.success());
    assert_eq!(read_back(&output.stdout), ref_frames[11..].to_vec());
    let codes: Vec<_> = events(&output)
        .iter()
        .filter(|e| e["event"] == "warning")
        .map(|e| e["code"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(codes, ["scan_fallback", "scan_stopped"]);
}

/// Errors write one JSON error event, nothing on stdout, and exit 1.
#[test]
fn errors_exit_one_with_an_error_event() {
    let output = extract(&b"definitely not an xtc file\n".repeat(5), &[]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    let first = events(&output);
    assert_eq!(first.len(), 1);
    assert_eq!(first[0]["event"], "error");
    assert_eq!(first[0]["code"], "xtc_invalid");

    let output = Command::new(env!("CARGO_BIN_EXE_xtcscope-agent"))
        .args(["extract", "--xtc", "/nonexistent/traj.xtc"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(events(&output)[0]["code"], "xtc_open");

    let output = extract(&[], &[]);
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(events(&output)[0]["code"], "xtc_empty");
}

/// A reader that goes away (SSH closed) makes the agent fail with `io`,
/// without a panic.
#[test]
fn closed_stdout_is_an_io_error() {
    // Far more than a pipe buffer holds.
    let data = make_xtc(Magic::Xtc1995, 2000, 200);
    assert!(data.len() > 1 << 20);
    let file = temp_xtc(&data);
    let mut child = Command::new(env!("CARGO_BIN_EXE_xtcscope-agent"))
        .arg("extract")
        .arg("--xtc")
        .arg(file.path())
        .args(["-n", "200"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdout = child.stdout.take().unwrap();
    let mut first = [0u8; 16];
    stdout.read_exact(&mut first).unwrap();
    drop(stdout);
    let mut stderr = String::new();
    child
        .stderr
        .take()
        .unwrap()
        .read_to_string(&mut stderr)
        .unwrap();
    let status = child.wait().unwrap();
    assert_eq!(status.code(), Some(1));
    let last: Value = serde_json::from_str(stderr.lines().last().unwrap()).unwrap();
    assert_eq!(last["event"], "error");
    assert_eq!(last["code"], "io");
    assert!(!stderr.contains("panicked"));
}

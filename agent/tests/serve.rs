//! The `serve` subcommand end to end: a test client speaks IMDv2 to the agent
//! over its Unix socket while the test reads the control events.

mod common;

use std::io::{BufRead, BufReader, ErrorKind, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::mpsc::{Receiver, RecvTimeoutError, channel};
use std::time::{Duration, Instant};

use common::{make_xtc, reference};
use molly::Magic;
use serde_json::Value;

/// How long to wait for any single event before failing a test.
const TIMEOUT: Duration = Duration::from_secs(10);

/// A running agent, its control events and its working directory.
struct Agent {
    child: Child,
    events: Receiver<Value>,
    stdin: Option<ChildStdin>,
    socket: PathBuf,
    _dir: tempfile::TempDir,
}

impl Agent {
    /// Write `data` as an XTC file and start `serve` on it with `extra` arguments.
    ///
    /// Frames are sent without pacing unless `extra` sets `--frame-interval`.
    fn start(data: &[u8], extra: &[&str]) -> Agent {
        let dir = tempfile::tempdir().unwrap();
        let xtc = dir.path().join("traj.xtc");
        std::fs::write(&xtc, data).unwrap();
        let socket = dir.path().join("agent.sock");
        Self::start_with(dir, &xtc, socket, extra)
    }

    /// Start `serve` on an existing file and socket path inside `dir`.
    fn start_with(
        dir: tempfile::TempDir,
        xtc: &std::path::Path,
        socket: PathBuf,
        extra: &[&str],
    ) -> Agent {
        let mut child = Command::new(env!("CARGO_BIN_EXE_xtcscope-agent"))
            .arg("serve")
            .arg("--xtc")
            .arg(xtc)
            .arg("--socket")
            .arg(&socket)
            .args(extra)
            .args(if extra.contains(&"--frame-interval") {
                &[][..]
            } else {
                &["--frame-interval", "0"][..]
            })
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                let value: Value = serde_json::from_str(&line).unwrap();
                if tx.send(value).is_err() {
                    break;
                }
            }
        });
        let stdin = child.stdin.take();
        Agent {
            child,
            events: rx,
            stdin,
            socket,
            _dir: dir,
        }
    }

    /// The next control event; panics after `TIMEOUT`.
    fn next_event(&self) -> Value {
        match self.events.recv_timeout(TIMEOUT) {
            Ok(value) => value,
            Err(RecvTimeoutError::Timeout) => panic!("no event within {TIMEOUT:?}"),
            Err(RecvTimeoutError::Disconnected) => panic!("agent closed stdout"),
        }
    }

    /// The next event, which must be named `name`.
    fn expect(&self, name: &str) -> Value {
        let event = self.next_event();
        assert_eq!(event["event"], name, "unexpected event {event}");
        event
    }

    /// Connect a client to the agent's socket.
    fn connect(&self) -> UnixStream {
        let stream = UnixStream::connect(&self.socket).unwrap();
        stream.set_read_timeout(Some(TIMEOUT)).unwrap();
        stream
    }

    /// Wait for the agent to exit; panics after `TIMEOUT`.
    fn wait_exit(&mut self) -> ExitStatus {
        let deadline = Instant::now() + TIMEOUT;
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                return status;
            }
            assert!(Instant::now() < deadline, "agent did not exit");
            std::thread::sleep(Duration::from_millis(20));
        }
    }
}

impl Drop for Agent {
    /// Never leave an agent running after a failed test.
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Append an IMD header (both fields big-endian) to `buf`.
fn header(buf: &mut Vec<u8>, ty: i32, value: i32) {
    buf.extend(ty.to_be_bytes());
    buf.extend(value.to_be_bytes());
}

/// Send one header-only message.
fn send(stream: &mut UnixStream, ty: i32, value: i32) {
    let mut buf = Vec::new();
    header(&mut buf, ty, value);
    stream.write_all(&buf).unwrap();
}

/// Read the handshake and check it announces IMDv2.
fn read_handshake(stream: &mut UnixStream) {
    let mut bytes = [0u8; 8];
    stream.read_exact(&mut bytes).unwrap();
    assert_eq!(&bytes[..4], &4i32.to_be_bytes(), "handshake type");
    assert_eq!(&bytes[4..], &2i32.to_ne_bytes(), "version, native order");
}

/// Read one Coordinates message and return its values (Å).
fn read_coordinates(stream: &mut UnixStream, natoms: usize) -> Vec<f32> {
    let mut head = [0u8; 8];
    stream.read_exact(&mut head).unwrap();
    assert_eq!(&head[..4], &2i32.to_be_bytes(), "coordinates type");
    assert_eq!(&head[4..], &(natoms as i32).to_be_bytes(), "atom count");
    let mut body = vec![0u8; natoms * 12];
    stream.read_exact(&mut body).unwrap();
    body.chunks_exact(4)
        .map(|c| f32::from_ne_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

/// Positions of a reference frame converted to Å, as the agent sends them.
fn angstrom(frame: &molly::Frame) -> Vec<f32> {
    frame.positions.iter().map(|x| x * 10.0).collect()
}

/// The full happy path: ready, handshake, frames, done, disconnect.
#[test]
fn streams_the_last_frames_then_disconnects() {
    let data = make_xtc(Magic::Xtc1995, 200, 25);
    let (_, ref_frames) = reference(&data);
    let mut agent = Agent::start(&data, &["-n", "5"]);

    let ready = agent.expect("ready");
    assert_eq!(ready["natoms"], 200);
    assert_eq!(ready["frames_sent"], 5);
    assert_eq!(ready["first_step"], 20_000);
    assert_eq!(ready["last_step"], 24_000);
    assert_eq!(ready["first_time_ps"], 40.0);
    assert_eq!(ready["last_time_ps"], 48.0);
    assert_eq!(ready["imd_version"], 2);
    assert_eq!(ready["version"], env!("CARGO_PKG_VERSION"));

    let mode = std::fs::metadata(&agent.socket)
        .unwrap()
        .permissions()
        .mode();
    assert_eq!(mode & 0o777, 0o600, "socket mode");

    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0); // Go
    agent.expect("connected");
    for (i, frame) in ref_frames[20..].iter().enumerate() {
        assert_eq!(
            read_coordinates(&mut client, 200),
            angstrom(frame),
            "frame {i}"
        );
    }
    assert_eq!(agent.expect("done")["frames"], 5);

    send(&mut client, 0, 0); // Disconnect
    assert_eq!(agent.expect("disconnected")["reason"], "client");
    assert!(agent.wait_exit().success());
    assert!(!agent.socket.exists(), "socket removed");
}

/// A file with fewer frames than requested sends all of them.
#[test]
fn sends_all_frames_when_the_file_has_fewer() {
    let data = make_xtc(Magic::Xtc2023, 5, 3);
    let agent = Agent::start(&data, &["-n", "10"]);
    let ready = agent.expect("ready");
    assert_eq!(ready["frames_sent"], 3);
    assert_eq!(ready["natoms"], 5);
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    for _ in 0..3 {
        read_coordinates(&mut client, 5);
    }
    agent.expect("connected");
    assert_eq!(agent.expect("done")["frames"], 3);
}

/// An existing socket path is refused and left untouched.
#[test]
fn existing_socket_path_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let xtc = dir.path().join("traj.xtc");
    std::fs::write(&xtc, make_xtc(Magic::Xtc1995, 200, 3)).unwrap();
    let socket = dir.path().join("taken");
    std::fs::write(&socket, b"keep me").unwrap();
    let mut agent = Agent::start_with(dir, &xtc, socket.clone(), &[]);
    let error = agent.expect("error");
    assert_eq!(error["code"], "socket_exists");
    assert_eq!(agent.wait_exit().code(), Some(1));
    assert_eq!(std::fs::read(&socket).unwrap(), b"keep me");
}

/// Closing stdin (the SSH session ended) shuts the agent down cleanly.
#[test]
fn stdin_closing_shuts_down() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    drop(agent.stdin.take());
    assert_eq!(agent.expect("disconnected")["reason"], "stdin");
    assert!(agent.wait_exit().success());
    assert!(!agent.socket.exists(), "socket removed");
}

/// SIGTERM shuts the agent down cleanly.
#[test]
fn sigterm_shuts_down() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    // SAFETY: sending a signal to our own child process.
    unsafe { libc::kill(agent.child.id() as libc::pid_t, libc::SIGTERM) };
    assert_eq!(agent.expect("disconnected")["reason"], "signal");
    assert!(agent.wait_exit().success());
    assert!(!agent.socket.exists(), "socket removed");
}

/// No client within `--accept-timeout` is an error, and the socket goes away.
#[test]
fn accept_timeout() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &["--accept-timeout", "1"]);
    agent.expect("ready");
    assert_eq!(agent.expect("error")["code"], "accept_timeout");
    assert_eq!(agent.wait_exit().code(), Some(1));
    assert!(!agent.socket.exists(), "socket removed");
}

/// A client that never sends Go is dropped after the handshake timeout.
#[test]
fn handshake_timeout() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    assert_eq!(agent.expect("error")["code"], "handshake_timeout");
    assert_eq!(agent.wait_exit().code(), Some(1));
}

/// Pause stops the stream and a second Pause (v2 toggle) resumes it.
#[test]
fn pause_toggles_sending() {
    let data = make_xtc(Magic::Xtc1995, 200, 5);
    let agent = Agent::start(&data, &["-n", "5"]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    let mut buf = Vec::new();
    header(&mut buf, 3, 0); // Go
    header(&mut buf, 7, 0); // Pause, before the first frame
    client.write_all(&buf).unwrap();
    agent.expect("connected");

    client
        .set_read_timeout(Some(Duration::from_millis(300)))
        .unwrap();
    let mut byte = [0u8; 1];
    let err = client.read(&mut byte).unwrap_err();
    assert!(
        matches!(err.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut),
        "no data while paused, got {err:?}"
    );

    client.set_read_timeout(Some(TIMEOUT)).unwrap();
    send(&mut client, 7, 0); // Pause again: resume
    for _ in 0..5 {
        read_coordinates(&mut client, 200);
    }
    assert_eq!(agent.expect("done")["frames"], 5);
}

/// Forces sent by the client are skipped without losing track of the stream.
#[test]
fn md_communication_body_is_discarded() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    let mut buf = Vec::new();
    header(&mut buf, 3, 0); // Go
    header(&mut buf, 6, 2); // MD communication for 2 atoms
    buf.extend(0i32.to_ne_bytes());
    buf.extend(1i32.to_ne_bytes());
    buf.extend([0u8; 24]); // 6 forces
    client.write_all(&buf).unwrap();
    for _ in 0..3 {
        read_coordinates(&mut client, 200);
    }
    agent.expect("connected");
    agent.expect("done");
    send(&mut client, 0, 0);
    assert_eq!(agent.expect("disconnected")["reason"], "client");
    assert!(agent.wait_exit().success());
}

/// Kill ends the session (it never touches anything else).
#[test]
fn kill_ends_the_session() {
    let data = make_xtc(Magic::Xtc1995, 200, 2);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    for _ in 0..2 {
        read_coordinates(&mut client, 200);
    }
    send(&mut client, 5, 0); // Kill
    agent.expect("connected");
    agent.expect("done");
    assert_eq!(agent.expect("disconnected")["reason"], "kill");
    assert!(agent.wait_exit().success());
}

/// A client that closes the connection after the frames ends the session.
#[test]
fn client_closing_the_connection_ends_the_session() {
    let data = make_xtc(Magic::Xtc1995, 200, 2);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    for _ in 0..2 {
        read_coordinates(&mut client, 200);
    }
    agent.expect("connected");
    agent.expect("done");
    drop(client);
    assert_eq!(agent.expect("disconnected")["reason"], "client");
    assert!(agent.wait_exit().success());
}

/// A client that goes away mid-stream ends the session without an error.
#[test]
fn client_vanishing_mid_stream_is_a_disconnect() {
    // 25 frames of 2000 atoms are far more than a socket buffer holds.
    let data = make_xtc(Magic::Xtc1995, 2000, 25);
    let mut agent = Agent::start(&data, &["-n", "25"]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    read_coordinates(&mut client, 2000);
    drop(client);
    agent.expect("connected");
    assert_eq!(agent.expect("disconnected")["reason"], "client");
    assert!(agent.wait_exit().success());
}

/// An unknown message type can't be skipped safely, so it ends with an error.
#[test]
fn unknown_message_type_is_an_error() {
    let data = make_xtc(Magic::Xtc1995, 200, 1);
    let mut agent = Agent::start(&data, &[]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    read_coordinates(&mut client, 200);
    agent.expect("connected");
    agent.expect("done");
    send(&mut client, 99, 0);
    assert_eq!(agent.expect("error")["code"], "io");
    assert_eq!(agent.wait_exit().code(), Some(1));
}

/// An unreadable trajectory fails before any socket is created.
#[test]
fn invalid_xtc_fails_before_listening() {
    let mut agent = Agent::start(&b"not an xtc file at all\n".repeat(5), &[]);
    assert_eq!(agent.expect("error")["code"], "xtc_invalid");
    assert_eq!(agent.wait_exit().code(), Some(1));
    assert!(!agent.socket.exists());
}

/// Frames are spaced by `--frame-interval`, so VMD can store each one.
#[test]
fn frames_are_paced() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let agent = Agent::start(&data, &["--frame-interval", "300"]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    read_coordinates(&mut client, 200);
    let first = Instant::now();
    read_coordinates(&mut client, 200);
    read_coordinates(&mut client, 200);
    let spread = first.elapsed();
    assert!(
        spread >= Duration::from_millis(550),
        "frames too close: {spread:?}"
    );
    agent.expect("connected");
    agent.expect("done");
}

/// A Disconnect during the pause between frames ends the session at once.
#[test]
fn disconnect_during_the_pause_is_handled_promptly() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let mut agent = Agent::start(&data, &["--frame-interval", "5000"]);
    agent.expect("ready");
    let mut client = agent.connect();
    read_handshake(&mut client);
    send(&mut client, 3, 0);
    read_coordinates(&mut client, 200);
    agent.expect("connected");
    let sent = Instant::now();
    send(&mut client, 0, 0);
    assert_eq!(agent.expect("disconnected")["reason"], "client");
    assert!(
        sent.elapsed() < Duration::from_secs(2),
        "took {:?}",
        sent.elapsed()
    );
    assert!(agent.wait_exit().success());
}

//! Control protocol: JSON objects, one per line, flushed after each.
//!
//! `extract` writes its events to stderr, because stdout carries the XTC data;
//! the `xtcscope` script parses them. `inspect` prints its events to stdout and
//! repeats warnings and errors on stderr in readable form.

use std::io::Write;

use serde::Serialize;

/// An event for the `xtcscope` script or a person running `inspect`.
#[derive(Debug, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event<'a> {
    /// Frames found, before any data is written (`extract`).
    Located {
        /// Agent version.
        version: &'a str,
        /// XTC magic number of the file (1995 or 2023).
        magic: i32,
        /// Atoms per frame.
        natoms: usize,
        /// Number of frames that will be written.
        frames: usize,
        /// Step of the oldest frame.
        first_step: u32,
        /// Step of the newest frame.
        last_step: u32,
        /// Time of the oldest frame, ps.
        first_time_ps: f32,
        /// Time of the newest frame, ps.
        last_time_ps: f32,
        /// Number of bytes that will be written to stdout.
        bytes: u64,
    },
    /// Every byte written and flushed (`extract`).
    Done {
        /// Number of bytes written.
        bytes: u64,
    },
    /// A located frame (`inspect`).
    Frame {
        /// Byte offset of the frame in the file.
        offset: u64,
        /// Simulation step.
        step: u32,
        /// Simulation time, ps.
        time_ps: f32,
        /// Only with `inspect --decode`.
        #[serde(skip_serializing_if = "Option::is_none")]
        natoms: Option<usize>,
        /// Only with `inspect --decode`: the first atom's position, nm.
        #[serde(skip_serializing_if = "Option::is_none")]
        first_position_nm: Option<[f32; 3]>,
    },
    /// Something the user should know about; the agent carries on.
    Warning {
        /// Machine-readable code.
        code: &'a str,
        /// Explanation for the user.
        message: &'a str,
    },
    /// A fatal error; the agent exits 1 after sending it.
    Error {
        /// Machine-readable code.
        code: &'a str,
        /// Explanation for the user.
        message: &'a str,
    },
}

/// Serialize an event as one line of JSON.
fn to_line(event: &Event<'_>) -> String {
    serde_json::to_string(event).expect("events always serialize")
}

/// Print an event on stdout (`inspect`); warnings and errors are repeated on
/// stderr in readable form.
///
/// A closed stdout is ignored.
pub fn emit(event: &Event<'_>) {
    match event {
        Event::Warning { code, message } => {
            eprintln!("xtcscope-agent: warning ({code}): {message}");
        }
        Event::Error { code, message } => {
            eprintln!("xtcscope-agent: error ({code}): {message}");
        }
        _ => {}
    }
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{}", to_line(event));
    let _ = out.flush();
}

/// Write an event to stderr as JSON only (`extract`, whose stdout is data).
///
/// A closed stderr is ignored.
pub fn report(event: &Event<'_>) {
    let mut err = std::io::stderr().lock();
    let _ = writeln!(err, "{}", to_line(event));
    let _ = err.flush();
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Events serialize with an `event` tag and snake_case names.
    #[test]
    fn event_json_shape() {
        assert_eq!(
            to_line(&Event::Done { bytes: 42 }),
            r#"{"event":"done","bytes":42}"#
        );
        assert_eq!(
            to_line(&Event::Error {
                code: "io",
                message: "x"
            }),
            r#"{"event":"error","code":"io","message":"x"}"#
        );
    }
}

//! Control protocol: one JSON object per line on stdout, flushed after each.
//!
//! The `xtcscope` script reads these events. Warnings and errors are also
//! logged on stderr for people.

use std::io::Write;

use serde::Serialize;

/// An event sent to the `xtcscope` script.
#[derive(Debug, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event<'a> {
    /// Frames located and socket listening (`serve`).
    Ready {
        /// Agent version.
        version: &'a str,
        /// Atoms per frame.
        natoms: usize,
        /// Number of frames that will be sent.
        frames_sent: usize,
        /// Step of the oldest frame sent.
        first_step: u32,
        /// Step of the newest frame sent.
        last_step: u32,
        /// Time of the oldest frame sent, ps.
        first_time_ps: f32,
        /// Time of the newest frame sent, ps.
        last_time_ps: f32,
        /// IMD protocol version spoken.
        imd_version: i32,
    },
    /// Client accepted and Go received (`serve`).
    Connected,
    /// Last frame written to the socket (`serve`).
    Done {
        /// Number of frames sent.
        frames: usize,
    },
    /// Session over (`serve`): `client`, `kill`, `stdin` or `signal`.
    Disconnected {
        /// Why the session ended.
        reason: &'a str,
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

/// Write an event to stdout (and warnings and errors to stderr too).
///
/// A closed stdout is ignored: the script is gone and the agent will notice
/// through stdin.
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
    let line = serde_json::to_string(event).expect("events always serialize");
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{line}");
    let _ = out.flush();
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Events serialize with an `event` tag and snake_case names.
    #[test]
    fn event_json_shape() {
        let json = serde_json::to_string(&Event::Disconnected { reason: "stdin" }).unwrap();
        assert_eq!(json, r#"{"event":"disconnected","reason":"stdin"}"#);
        let json = serde_json::to_string(&Event::Connected).unwrap();
        assert_eq!(json, r#"{"event":"connected"}"#);
    }
}

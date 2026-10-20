//! Control protocol: one JSON object per line on stdout, flushed after each.
//!
//! Warnings and errors are also logged on stderr for people.

use std::io::Write;

use serde::Serialize;

/// An event sent to the `xtcscope` script.
#[derive(Debug, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event<'a> {
    /// A located frame (`inspect` only).
    Frame {
        offset: u64,
        step: u32,
        time_ps: f32,
        /// Only with `inspect --decode`.
        #[serde(skip_serializing_if = "Option::is_none")]
        natoms: Option<usize>,
        /// Only with `inspect --decode`: the first atom's position, nm.
        #[serde(skip_serializing_if = "Option::is_none")]
        first_position_nm: Option<[f32; 3]>,
    },
    Warning {
        code: &'a str,
        message: &'a str,
    },
    Error {
        code: &'a str,
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
        Event::Frame { .. } => {}
    }
    let line = serde_json::to_string(event).expect("events always serialize");
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{line}");
    let _ = out.flush();
}

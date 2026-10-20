//! xtcscope-agent: copies the last frames of a GROMACS XTC trajectory.
//!
//! `extract` writes the last complete frames to stdout as a valid XTC file;
//! `inspect` only lists (and optionally decodes) them, for debugging.

use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{Parser, Subcommand};

use xtcscope_agent::control::{Event, emit, report};
use xtcscope_agent::xtc::{Frame, FrameSource, XtcSource, byte_range, copy_frames, open_located};

/// Copies the last frames of a GROMACS XTC trajectory.
///
/// Normally run by the `xtcscope` script over SSH, not by hand.
#[derive(Debug, Parser)]
#[command(
    name = "xtcscope-agent",
    version,
    about,
    long_about = None,
    arg_required_else_help = true
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Write the last complete frames of an XTC file to stdout, as an XTC file.
    ///
    /// Events (located, warnings, done, errors) go to stderr as JSON lines.
    Extract {
        /// Path to the XTC file.
        #[arg(long)]
        xtc: PathBuf,
        /// Number of frames from the end; all frames if the file has fewer.
        #[arg(long, short = 'n', default_value_t = 10,
              value_parser = clap::value_parser!(u32).range(1..))]
        frames: u32,
    },
    /// Locate the last frames of an XTC file and print them as JSON lines
    /// (for testing and debugging).
    Inspect {
        /// Path to the XTC file.
        #[arg(long)]
        xtc: PathBuf,
        /// Number of frames from the end; all frames if the file has fewer.
        #[arg(long, short = 'n', default_value_t = 10,
              value_parser = clap::value_parser!(u32).range(1..))]
        frames: u32,
        /// Also decode each frame and report its atom count and first position.
        #[arg(long)]
        decode: bool,
    },
}

/// Parse the command line and run the chosen subcommand.
fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.command {
        Command::Extract { xtc, frames } => extract(&xtc, frames as usize),
        Command::Inspect {
            xtc,
            frames,
            decode,
        } => inspect(&xtc, frames as usize, decode),
    }
}

/// Report a fatal error on stderr as JSON (`extract`) and return exit code 1.
fn fail_report(code: &str, message: &str) -> ExitCode {
    report(&Event::Error { code, message });
    ExitCode::from(1)
}

/// Print a fatal error on stdout (`inspect`) and return exit code 1.
fn fail_emit(code: &str, message: &str) -> ExitCode {
    emit(&Event::Error { code, message });
    ExitCode::from(1)
}

/// The `extract` subcommand: locate the last frames and copy their bytes to stdout.
fn extract(path: &Path, n: usize) -> ExitCode {
    let stdout = std::io::stdout();
    if stdout.is_terminal() {
        return fail_report(
            "stdout_is_terminal",
            "refusing to write binary XTC data to a terminal; redirect stdout to a file",
        );
    }
    let (file, located) = match open_located(path, n) {
        Ok(opened) => opened,
        Err(err) => return fail_report(err.code(), &err.to_string()),
    };
    for warning in &located.warnings {
        report(&Event::Warning {
            code: warning.code,
            message: &warning.message,
        });
    }
    let frames = &located.frames;
    let (start, end) = byte_range(frames).expect("located frames are never empty");
    let (first, last) = (frames[0], frames[frames.len() - 1]);
    report(&Event::Located {
        version: env!("CARGO_PKG_VERSION"),
        magic: located.magic,
        natoms: located.natoms,
        frames: frames.len(),
        first_step: first.step,
        last_step: last.step,
        first_time_ps: first.time_ps,
        last_time_ps: last.time_ps,
        bytes: end - start,
    });

    let mut out = stdout.lock();
    let copied = copy_frames(&file, frames, &mut out).and_then(|bytes| {
        out.flush()?;
        Ok(bytes)
    });
    match copied {
        Ok(bytes) => {
            report(&Event::Done { bytes });
            ExitCode::SUCCESS
        }
        Err(err) => fail_report("io", &format!("could not copy the frames: {err}")),
    }
}

/// The `inspect` subcommand: print warnings, then one `frame` event per frame.
fn inspect(path: &Path, n: usize, decode: bool) -> ExitCode {
    let mut source = match XtcSource::open(path, n) {
        Ok(source) => source,
        Err(err) => return fail_emit(err.code(), &err.to_string()),
    };
    for warning in source.warnings() {
        emit(&Event::Warning {
            code: warning.code,
            message: &warning.message,
        });
    }
    let infos = source.frames().to_vec();
    let mut frame = Frame::default();
    for (i, info) in infos.iter().enumerate() {
        let (natoms, first_position_nm) = if decode {
            if let Err(err) = source.read(i, &mut frame) {
                return fail_emit("xtc_invalid", &format!("{err:#}"));
            }
            let p = &frame.positions_nm;
            (Some(source.natoms()), Some([p[0], p[1], p[2]]))
        } else {
            (None, None)
        };
        emit(&Event::Frame {
            offset: info.offset,
            step: info.step,
            time_ps: info.time_ps,
            natoms,
            first_position_nm,
        });
    }
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    /// clap accepts the command definition.
    #[test]
    fn cli_definition_is_valid() {
        Cli::command().debug_assert();
    }

    /// `--version` is handled by clap.
    #[test]
    fn version_flag_is_recognised() {
        let err = Cli::try_parse_from(["xtcscope-agent", "--version"]).unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::DisplayVersion);
    }

    /// The reported version is the one in Cargo.toml.
    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(
            Cli::command().get_version(),
            Some(env!("CARGO_PKG_VERSION"))
        );
    }

    /// `-n 0` is rejected by both subcommands.
    #[test]
    fn zero_frames_are_rejected() {
        for sub in ["inspect", "extract"] {
            let err =
                Cli::try_parse_from(["xtcscope-agent", sub, "--xtc", "x", "-n", "0"]).unwrap_err();
            assert_eq!(err.kind(), clap::error::ErrorKind::ValueValidation);
        }
    }
}

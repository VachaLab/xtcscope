//! xtcscope-agent: serves the last frames of a GROMACS XTC trajectory over IMD.
//!
//! Milestone 1: `inspect` locates (and optionally decodes) the last frames.

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};

use xtcscope_agent::control::{Event, emit};
use xtcscope_agent::xtc::{Frame, FrameSource, XtcSource};

/// Serves the last frames of a GROMACS XTC trajectory over IMD.
///
/// Normally started by the `xtcscope` script over SSH, not by hand.
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

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.command {
        Command::Inspect {
            xtc,
            frames,
            decode,
        } => inspect(&xtc, frames as usize, decode),
    }
}

fn fail(code: &str, message: &str) -> ExitCode {
    emit(&Event::Error { code, message });
    ExitCode::from(1)
}

fn inspect(path: &std::path::Path, n: usize, decode: bool) -> ExitCode {
    let mut source = match XtcSource::open(path, n) {
        Ok(source) => source,
        Err(err) => return fail(err.code(), &err.to_string()),
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
                return fail("xtc_invalid", &format!("{err:#}"));
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

    #[test]
    fn cli_definition_is_valid() {
        Cli::command().debug_assert();
    }

    #[test]
    fn version_flag_is_recognised() {
        let err = Cli::try_parse_from(["xtcscope-agent", "--version"]).unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::DisplayVersion);
    }

    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(
            Cli::command().get_version(),
            Some(env!("CARGO_PKG_VERSION"))
        );
    }

    #[test]
    fn inspect_rejects_zero_frames() {
        let err = Cli::try_parse_from(["xtcscope-agent", "inspect", "--xtc", "x", "-n", "0"])
            .unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::ValueValidation);
    }
}

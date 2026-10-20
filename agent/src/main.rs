//! xtcscope-agent: serves the last frames of a GROMACS XTC trajectory over IMD.
//!
//! `serve` streams the last frames to one IMD client on a Unix socket;
//! `inspect` only locates (and optionally decodes) them, for debugging.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use clap::{Parser, Subcommand};
use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
use signal_hook::iterator::Signals;

use xtcscope_agent::control::{Event, emit};
use xtcscope_agent::filter::All;
use xtcscope_agent::imd::{
    ImdVersion, SessionEvent, accept, bind, remove_socket_file, run_session,
};
use xtcscope_agent::xtc::{Frame, FrameSource, XtcSource};

/// How long the client has to accept the handshake. The IMDv3 text suggests
/// 1 s; 5 s leaves room for latency through the SSH tunnel.
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);

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
    /// Stream the last frames of an XTC file to one IMD client on a Unix socket.
    ///
    /// Exits when the client disconnects, when stdin closes, or on SIGHUP,
    /// SIGINT or SIGTERM.
    Serve {
        /// Path to the XTC file.
        #[arg(long)]
        xtc: PathBuf,
        /// Path of the Unix socket to create; it must not exist.
        #[arg(long)]
        socket: PathBuf,
        /// Number of frames from the end; all frames if the file has fewer.
        #[arg(long, short = 'n', default_value_t = 10,
              value_parser = clap::value_parser!(u32).range(1..))]
        frames: u32,
        /// IMD protocol version.
        #[arg(long, default_value = "2", value_parser = parse_imd_version)]
        imd_version: ImdVersion,
        /// Seconds to wait for a client before giving up.
        #[arg(long, default_value_t = 120,
              value_parser = clap::value_parser!(u64).range(1..))]
        accept_timeout: u64,
        /// Milliseconds to wait after each frame. VMD keeps only the latest
        /// frame it received and stores it once per redraw, so frames sent
        /// faster than VMD redraws are lost; raise this for large systems.
        #[arg(long, default_value_t = 250,
              value_parser = clap::value_parser!(u64).range(0..=60_000))]
        frame_interval: u64,
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

/// Parse `--imd-version`. Version 3 arrives in a later milestone.
fn parse_imd_version(value: &str) -> Result<ImdVersion, String> {
    match value {
        "2" => Ok(ImdVersion::V2),
        "3" => Err("IMD version 3 is not supported yet".to_string()),
        _ => Err("must be 2 or 3".to_string()),
    }
}

/// Parse the command line and run the chosen subcommand.
fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.command {
        Command::Serve {
            xtc,
            socket,
            frames,
            imd_version,
            accept_timeout,
            frame_interval,
        } => serve(
            &xtc,
            &socket,
            frames as usize,
            imd_version,
            Duration::from_secs(accept_timeout),
            Duration::from_millis(frame_interval),
        ),
        Command::Inspect {
            xtc,
            frames,
            decode,
        } => inspect(&xtc, frames as usize, decode),
    }
}

/// Report a fatal error and return exit code 1.
fn fail(code: &str, message: &str) -> ExitCode {
    emit(&Event::Error { code, message });
    ExitCode::from(1)
}

/// Remove the socket, report why the session ended, and exit 0.
///
/// Called from the watcher threads; `process::exit` skips destructors, so the
/// socket file is removed explicitly.
fn shutdown(reason: &str) -> ! {
    remove_socket_file();
    emit(&Event::Disconnected { reason });
    std::process::exit(0)
}

/// Start the threads that end the process when stdin closes or a termination
/// signal arrives.
fn start_shutdown_watchers() {
    std::thread::spawn(|| {
        let mut stdin = std::io::stdin();
        let mut buf = [0u8; 256];
        loop {
            match stdin.read(&mut buf) {
                Ok(0) => break,
                Ok(_) => continue,
                Err(err) if err.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            }
        }
        shutdown("stdin");
    });
    match Signals::new([SIGHUP, SIGINT, SIGTERM]) {
        Ok(mut signals) => {
            std::thread::spawn(move || {
                if signals.forever().next().is_some() {
                    shutdown("signal");
                }
            });
        }
        Err(err) => eprintln!("xtcscope-agent: could not install signal handlers: {err}"),
    }
}

/// Emit the warnings produced while locating frames.
fn emit_warnings(source: &XtcSource) {
    for warning in source.warnings() {
        emit(&Event::Warning {
            code: warning.code,
            message: &warning.message,
        });
    }
}

/// The `serve` subcommand: locate frames, listen, serve one client.
fn serve(
    xtc: &Path,
    socket: &Path,
    n: usize,
    version: ImdVersion,
    accept_timeout: Duration,
    frame_interval: Duration,
) -> ExitCode {
    start_shutdown_watchers();

    let mut source = match XtcSource::open(xtc, n) {
        Ok(source) => source,
        Err(err) => return fail(err.code(), &err.to_string()),
    };
    emit_warnings(&source);

    let (listener, _guard) = match bind(socket) {
        Ok(bound) => bound,
        Err(err) => return fail(err.code(), &err.to_string()),
    };

    let frames = source.frames();
    let (first, last) = (frames[0], frames[frames.len() - 1]);
    emit(&Event::Ready {
        version: env!("CARGO_PKG_VERSION"),
        natoms: source.natoms(),
        frames_sent: frames.len(),
        first_step: first.step,
        last_step: last.step,
        first_time_ps: first.time_ps,
        last_time_ps: last.time_ps,
        imd_version: version.number(),
    });

    let stream = match accept(&listener, accept_timeout) {
        Ok(stream) => stream,
        Err(err) => return fail(err.code(), &err.to_string()),
    };
    // Nobody else may connect.
    drop(listener);

    let mut on_event = |event: SessionEvent| match event {
        SessionEvent::Connected => emit(&Event::Connected),
        SessionEvent::Done { frames } => emit(&Event::Done { frames }),
        SessionEvent::Note(message) => eprintln!("xtcscope-agent: {message}"),
    };
    match run_session(
        stream,
        version,
        &mut source,
        &All,
        HANDSHAKE_TIMEOUT,
        frame_interval,
        &mut on_event,
    ) {
        Ok(reason) => {
            emit(&Event::Disconnected {
                reason: reason.as_str(),
            });
            ExitCode::SUCCESS
        }
        Err(err) => fail(err.code(), &err.to_string()),
    }
}

/// The `inspect` subcommand: print warnings, then one `frame` event per frame.
fn inspect(path: &Path, n: usize, decode: bool) -> ExitCode {
    let mut source = match XtcSource::open(path, n) {
        Ok(source) => source,
        Err(err) => return fail(err.code(), &err.to_string()),
    };
    emit_warnings(&source);
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

    /// `-n 0` is rejected.
    #[test]
    fn inspect_rejects_zero_frames() {
        let err = Cli::try_parse_from(["xtcscope-agent", "inspect", "--xtc", "x", "-n", "0"])
            .unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::ValueValidation);
    }

    /// Only IMD version 2 is accepted for now.
    #[test]
    fn imd_version_parsing() {
        assert_eq!(parse_imd_version("2"), Ok(ImdVersion::V2));
        assert!(parse_imd_version("3").is_err());
        assert!(parse_imd_version("1").is_err());
    }
}

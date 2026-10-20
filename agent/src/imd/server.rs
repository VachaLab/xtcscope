//! The IMD server: one client on a Unix socket, frames sent oldest first.
//!
//! The agent plays the simulation engine: it listens, the receiver (VMD)
//! connects. After the last frame the connection stays open and idle until the
//! client disconnects, so VMD doesn't report a dropped simulation.

use std::fmt;
use std::io::{self, ErrorKind, Read, Write};
use std::os::fd::{AsRawFd, RawFd};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use super::packet::{ClientMessage, HEADER_SIZE, Header, ImdVersion, encode_handshake};
use crate::filter::AtomFilter;
use crate::xtc::{Frame, FrameSource};

/// Socket file created by this process, removed on every exit path.
static SOCKET_PATH: Mutex<Option<PathBuf>> = Mutex::new(None);

/// Remove the socket file if this process created one.
///
/// Safe to call from any thread and more than once; used by the shutdown path,
/// which exits without running destructors.
pub fn remove_socket_file() {
    let path = match SOCKET_PATH.lock() {
        Ok(mut guard) => guard.take(),
        Err(poisoned) => poisoned.into_inner().take(),
    };
    if let Some(path) = path {
        let _ = std::fs::remove_file(path);
    }
}

/// Removes the socket file when dropped.
#[derive(Debug)]
pub struct SocketGuard(());

impl Drop for SocketGuard {
    /// Remove the socket file.
    fn drop(&mut self) {
        remove_socket_file();
    }
}

/// Why serving failed.
#[derive(Debug)]
pub enum ServeError {
    /// The socket path already exists; it is left untouched.
    SocketExists(PathBuf),
    /// Creating the socket failed.
    SocketBind(String),
    /// No client connected in time (seconds).
    AcceptTimeout(u64),
    /// The client didn't send Go in time.
    HandshakeTimeout,
    /// The client broke the protocol.
    Protocol(String),
    /// A socket error.
    Io(io::Error),
    /// A frame could not be decoded.
    Source(anyhow::Error),
}

impl ServeError {
    /// The error code used in the control protocol.
    pub fn code(&self) -> &'static str {
        match self {
            ServeError::SocketExists(_) => "socket_exists",
            ServeError::SocketBind(_) => "socket_bind",
            ServeError::AcceptTimeout(_) => "accept_timeout",
            ServeError::HandshakeTimeout => "handshake_timeout",
            ServeError::Protocol(_) | ServeError::Io(_) => "io",
            ServeError::Source(_) => "xtc_invalid",
        }
    }
}

impl fmt::Display for ServeError {
    /// The human-readable message.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ServeError::SocketExists(path) => {
                write!(f, "socket path {} already exists", path.display())
            }
            ServeError::SocketBind(msg) => write!(f, "could not create the socket: {msg}"),
            ServeError::AcceptTimeout(secs) => {
                write!(f, "no client connected within {secs} s")
            }
            ServeError::HandshakeTimeout => {
                write!(f, "the client did not accept the handshake in time")
            }
            ServeError::Protocol(msg) => write!(f, "IMD protocol error: {msg}"),
            ServeError::Io(err) => write!(f, "socket error: {err}"),
            ServeError::Source(err) => write!(f, "{err:#}"),
        }
    }
}

impl std::error::Error for ServeError {}

impl From<io::Error> for ServeError {
    /// Wrap a socket error.
    fn from(err: io::Error) -> Self {
        ServeError::Io(err)
    }
}

/// Create the Unix socket at `path` with mode 0600.
///
/// An existing path is refused rather than replaced: the agent never removes a
/// file it didn't create.
pub fn bind(path: &Path) -> Result<(UnixListener, SocketGuard), ServeError> {
    if path.symlink_metadata().is_ok() {
        return Err(ServeError::SocketExists(path.to_path_buf()));
    }
    // SAFETY: umask only changes the process file-creation mask; it is
    // restored right after the bind, and no other thread creates files.
    let old = unsafe { libc::umask(0o177) };
    let result = UnixListener::bind(path);
    // SAFETY: as above.
    unsafe { libc::umask(old) };
    let listener =
        result.map_err(|err| ServeError::SocketBind(format!("{}: {err}", path.display())))?;
    match SOCKET_PATH.lock() {
        Ok(mut guard) => *guard = Some(path.to_path_buf()),
        Err(poisoned) => *poisoned.into_inner() = Some(path.to_path_buf()),
    }
    Ok((listener, SocketGuard(())))
}

/// Wait until `fd` is readable (or closed) or `timeout` passes.
///
/// `None` waits forever. Returns whether the descriptor is ready.
fn wait_readable(fd: RawFd, timeout: Option<Duration>) -> io::Result<bool> {
    let millis = timeout.map_or(-1, |d| d.as_millis().min(i32::MAX as u128) as i32);
    let mut pfd = libc::pollfd {
        fd,
        events: libc::POLLIN,
        revents: 0,
    };
    loop {
        // SAFETY: `pfd` is a valid pollfd and the count is 1.
        let rc = unsafe { libc::poll(&mut pfd, 1, millis) };
        if rc < 0 {
            let err = io::Error::last_os_error();
            if err.kind() == ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        return Ok(rc > 0);
    }
}

/// Accept one client, waiting at most `timeout`.
pub fn accept(listener: &UnixListener, timeout: Duration) -> Result<UnixStream, ServeError> {
    if !wait_readable(listener.as_raw_fd(), Some(timeout))? {
        return Err(ServeError::AcceptTimeout(timeout.as_secs()));
    }
    let (stream, _) = listener.accept()?;
    stream.set_nonblocking(false)?;
    Ok(stream)
}

/// Why a session ended normally.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EndReason {
    /// The client disconnected or closed the connection.
    Client,
    /// The client sent Kill.
    Kill,
}

impl EndReason {
    /// The `reason` reported in the `disconnected` event.
    pub fn as_str(self) -> &'static str {
        match self {
            EndReason::Client => "client",
            EndReason::Kill => "kill",
        }
    }
}

/// Progress reported by a session, so the server itself never prints.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionEvent {
    /// The client accepted the handshake.
    Connected,
    /// The last frame was written to the socket.
    Done {
        /// Number of frames sent.
        frames: usize,
    },
    /// Something worth a line in the log.
    Note(String),
}

/// Whether a socket error means the client went away.
fn is_disconnect(err: &io::Error) -> bool {
    matches!(
        err.kind(),
        ErrorKind::BrokenPipe
            | ErrorKind::ConnectionReset
            | ErrorKind::ConnectionAborted
            | ErrorKind::UnexpectedEof
    )
}

/// State of one client connection.
struct Session<'a> {
    /// The connection to the client.
    stream: UnixStream,
    /// Protocol version spoken.
    version: ImdVersion,
    /// Whether the client paused the stream.
    paused: bool,
    /// Where progress is reported.
    events: &'a mut dyn FnMut(SessionEvent),
}

impl Session<'_> {
    /// Send the handshake and wait up to `timeout` for Go.
    fn handshake(&mut self, timeout: Duration) -> Result<(), ServeError> {
        let mut buf = Vec::with_capacity(HEADER_SIZE);
        encode_handshake(&mut buf, self.version);
        self.stream.write_all(&buf)?;
        self.stream.set_read_timeout(Some(timeout))?;
        let mut header = [0u8; HEADER_SIZE];
        match self.stream.read_exact(&mut header) {
            Ok(()) => {}
            Err(err) if matches!(err.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                return Err(ServeError::HandshakeTimeout);
            }
            Err(err) if is_disconnect(&err) => {
                return Err(ServeError::Protocol(
                    "the client closed the connection before accepting the handshake".to_string(),
                ));
            }
            Err(err) => return Err(err.into()),
        }
        self.stream.set_read_timeout(None)?;
        let header = Header::decode(&header);
        match ClientMessage::from_header(header) {
            Ok((ClientMessage::Go, _)) => Ok(()),
            _ => Err(ServeError::Protocol(format!(
                "expected Go after the handshake, got message type {}",
                header.ty
            ))),
        }
    }

    /// Read one client message, blocking, and act on it.
    ///
    /// Returns `Some(reason)` when the session is over.
    fn read_message(&mut self) -> Result<Option<EndReason>, ServeError> {
        let mut bytes = [0u8; HEADER_SIZE];
        match self.stream.read_exact(&mut bytes) {
            Ok(()) => {}
            Err(err) if is_disconnect(&err) => return Ok(Some(EndReason::Client)),
            Err(err) => return Err(err.into()),
        }
        let header = Header::decode(&bytes);
        let (message, body) = ClientMessage::from_header(header).map_err(|ty| {
            ServeError::Protocol(format!("unknown message type {ty} from the client"))
        })?;
        if body > 0 {
            let skipped = io::copy(&mut (&self.stream).take(body as u64), &mut io::sink())?;
            if skipped < body as u64 {
                return Ok(Some(EndReason::Client));
            }
        }
        match message {
            ClientMessage::Disconnect => return Ok(Some(EndReason::Client)),
            ClientMessage::Kill => return Ok(Some(EndReason::Kill)),
            ClientMessage::Pause => {
                // v2: Pause toggles.
                self.paused = !self.paused;
                let state = if self.paused { "paused" } else { "resumed" };
                (self.events)(SessionEvent::Note(format!("client {state} the stream")));
            }
            ClientMessage::Resume => {
                (self.events)(SessionEvent::Note(
                    "ignoring Resume (not part of IMDv2)".to_string(),
                ));
            }
            ClientMessage::MdComm { natoms } => {
                (self.events)(SessionEvent::Note(format!(
                    "ignoring forces for {natoms} atoms from the client"
                )));
            }
            other => {
                (self.events)(SessionEvent::Note(format!(
                    "ignoring {other:?} from the client"
                )));
            }
        }
        Ok(None)
    }

    /// Handle every message already waiting, without blocking.
    fn drain_messages(&mut self) -> Result<Option<EndReason>, ServeError> {
        while wait_readable(self.stream.as_raw_fd(), Some(Duration::ZERO))? {
            if let Some(end) = self.read_message()? {
                return Ok(Some(end));
            }
        }
        Ok(None)
    }
}

/// Serve one connected client: handshake, all frames of `source`, then wait
/// until the client disconnects.
pub fn run_session(
    stream: UnixStream,
    version: ImdVersion,
    source: &mut dyn FrameSource,
    filter: &dyn AtomFilter,
    handshake_timeout: Duration,
    events: &mut dyn FnMut(SessionEvent),
) -> Result<EndReason, ServeError> {
    let mut session = Session {
        stream,
        version,
        paused: false,
        events,
    };
    session.handshake(handshake_timeout)?;
    (session.events)(SessionEvent::Connected);

    let mut frame = Frame::default();
    let mut filtered = Frame::default();
    let mut buf = Vec::new();
    for i in 0..source.len() {
        if let Some(end) = session.drain_messages()? {
            return Ok(end);
        }
        while session.paused {
            if let Some(end) = session.read_message()? {
                return Ok(end);
            }
        }
        source.read(i, &mut frame).map_err(ServeError::Source)?;
        filter.apply(&frame, &mut filtered);
        buf.clear();
        version.encode_frame(&filtered, &mut buf);
        match session.stream.write_all(&buf) {
            Ok(()) => {}
            Err(err) if is_disconnect(&err) => return Ok(EndReason::Client),
            Err(err) => return Err(err.into()),
        }
    }
    (session.events)(SessionEvent::Done {
        frames: source.len(),
    });

    loop {
        if let Some(end) = session.read_message()? {
            return Ok(end);
        }
    }
}

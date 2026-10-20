//! Opening an XTC file and locating its last frames.

use std::fmt;
use std::fs::File;
use std::path::Path;

use super::index::{LocateError, Located, locate_last_frames};

/// Why an XTC file could not be opened or its frames located.
#[derive(Debug)]
pub enum OpenError {
    /// The file could not be opened or its size read.
    Open(String),
    /// No frames could be located.
    Locate(LocateError),
}

impl OpenError {
    /// The error code used in the control protocol.
    pub fn code(&self) -> &'static str {
        match self {
            OpenError::Open(_) => "xtc_open",
            OpenError::Locate(err) => err.code(),
        }
    }
}

impl fmt::Display for OpenError {
    /// The human-readable message.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            OpenError::Open(msg) => write!(f, "could not open the XTC file: {msg}"),
            OpenError::Locate(err) => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for OpenError {}

/// Open the XTC file at `path` and locate its last `n` complete frames.
///
/// The file length is taken once, here; data written later is ignored.
pub fn open_located(path: &Path, n: usize) -> Result<(File, Located), OpenError> {
    let file = File::open(path).map_err(|err| OpenError::Open(err.to_string()))?;
    let len = file
        .metadata()
        .map_err(|err| OpenError::Open(err.to_string()))?
        .len();
    let located = locate_last_frames(&file, len, n).map_err(OpenError::Locate)?;
    Ok((file, located))
}

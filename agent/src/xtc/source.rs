//! Decoding the located frames with molly.

use std::fs::File;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;

use anyhow::{Context, anyhow, bail};
use molly::XTCReader;
use molly::selection::AtomSelection;

use super::index::{FrameInfo, LocateError, Located, Warning, locate_last_frames};

/// One decoded frame, in the units stored in the XTC (nm, ps).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Frame {
    pub step: i64,
    pub time_ps: f64,
    /// Box vectors A, B, C in nm, as stored in the XTC.
    pub box_nm: [f32; 9],
    /// x1 y1 z1 x2 y2 z2 ... in nm; length 3 * natoms.
    pub positions_nm: Vec<f32>,
}

/// A fixed sequence of frames to send.
pub trait FrameSource {
    fn natoms(&self) -> usize;
    /// Number of frames selected for sending.
    fn len(&self) -> usize;
    fn is_empty(&self) -> bool {
        self.len() == 0
    }
    /// Decode frame `i` (0 = oldest) into `out`.
    fn read(&mut self, i: usize, out: &mut Frame) -> anyhow::Result<()>;
}

/// The last N complete frames of an XTC file.
pub struct XtcSource {
    reader: XTCReader<File>,
    located: Located,
    scratch: molly::Frame,
}

impl XtcSource {
    /// Locate the last `n` complete frames of the file at `path`.
    ///
    /// The file length is taken once, here; data written later is ignored.
    pub fn open(path: &Path, n: usize) -> Result<Self, OpenError> {
        let file = File::open(path).map_err(|err| OpenError::Open(err.to_string()))?;
        let len = file
            .metadata()
            .map_err(|err| OpenError::Open(err.to_string()))?
            .len();
        let located = locate_last_frames(&file, len, n).map_err(OpenError::Locate)?;
        Ok(XtcSource {
            reader: XTCReader::new(file),
            located,
            scratch: molly::Frame::default(),
        })
    }

    /// Frames located, oldest first.
    pub fn frames(&self) -> &[FrameInfo] {
        &self.located.frames
    }

    /// Warnings produced while locating the frames.
    pub fn warnings(&self) -> &[Warning] {
        &self.located.warnings
    }

    /// The XTC magic number of the file (1995 or 2023).
    pub fn magic(&self) -> i32 {
        self.located.magic
    }
}

impl FrameSource for XtcSource {
    fn natoms(&self) -> usize {
        self.located.natoms
    }

    fn len(&self) -> usize {
        self.located.frames.len()
    }

    fn read(&mut self, i: usize, out: &mut Frame) -> anyhow::Result<()> {
        let info = *self
            .located
            .frames
            .get(i)
            .ok_or_else(|| anyhow!("frame index {i} out of range"))?;
        let reader = &mut self.reader;
        let scratch = &mut self.scratch;
        // molly validates with assertions; a panic must become an error event,
        // not a silent crash.
        let result = catch_unwind(AssertUnwindSafe(|| {
            reader.read_frame_at_offset::<false>(scratch, info.offset, &AtomSelection::All)
        }));
        match result {
            Ok(Ok(())) => {}
            Ok(Err(err)) => {
                return Err(err)
                    .with_context(|| format!("could not decode frame at offset {}", info.offset));
            }
            Err(_) => bail!(
                "could not decode frame at offset {}: the decoder panicked",
                info.offset
            ),
        }
        let natoms = self.located.natoms;
        if scratch.positions.len() != 3 * natoms {
            bail!(
                "frame at offset {} decoded to {} positions, expected {}",
                info.offset,
                scratch.positions.len() / 3,
                natoms
            );
        }
        out.step = i64::from(scratch.step);
        out.time_ps = f64::from(scratch.time);
        out.box_nm = scratch.boxvec;
        out.positions_nm.clear();
        out.positions_nm.extend_from_slice(&scratch.positions);
        Ok(())
    }
}

/// Why an XTC file could not be opened for streaming.
#[derive(Debug)]
pub enum OpenError {
    /// The file could not be opened or its size read.
    Open(String),
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

impl std::fmt::Display for OpenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OpenError::Open(msg) => write!(f, "could not open the XTC file: {msg}"),
            OpenError::Locate(err) => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for OpenError {}

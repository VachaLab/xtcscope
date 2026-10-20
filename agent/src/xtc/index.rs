//! Locating the last complete frames of an XTC file.
//!
//! The file is scanned backwards from its end, so the cost depends on the number
//! of frames requested, not on the length of the trajectory. If the backward scan
//! cannot chain frames together, a forward scan from the start is used instead,
//! and a warning says so.
//!
//! All XTC fields are XDR (big-endian). Frame layout, offsets relative to the
//! frame start:
//!
//! | Offset    | Bytes  | Field                                       |
//! |-----------|--------|---------------------------------------------|
//! | 0         | 4      | magic, i32: 1995 or 2023                    |
//! | 4         | 4      | natoms                                      |
//! | 8         | 4      | step                                        |
//! | 12        | 4      | time, f32, ps                               |
//! | 16        | 36     | box, f32[9], nm                             |
//! | 52        | 4      | natoms again                                |
//! | 56        | 4      | precision, f32 (only if natoms > 9)         |
//! | 60        | 12     | minint, i32[3]                              |
//! | 72        | 12     | maxint, i32[3]                              |
//! | 84        | 4      | smallidx                                    |
//! | 88        | 4 or 8 | nbytes: u32 (magic 1995), u64 (magic 2023)  |
//! | 92 or 96  | nbytes | compressed data, padded to a multiple of 4  |
//!
//! With natoms <= 9 the coordinates are raw `f32[3 * natoms]` from offset 56.

use std::collections::VecDeque;
use std::fmt;
use std::fs::File;
use std::io;
use std::os::unix::fs::FileExt;

/// Magic number of classic XTC files.
pub const MAGIC_1995: i32 = 1995;
/// Magic number of XTC files with a 64-bit compressed-size field.
pub const MAGIC_2023: i32 = 2023;

/// Bytes from the magic number up to and including the repeated natoms.
const HEADER_SIZE: u64 = 56;
/// The most bytes needed to know a frame's size.
const MAX_PROBE: usize = 96;
/// Block size for reading backwards.
const BLOCK: u64 = 1 << 20;

/// Positional reads, implemented for files and for in-memory buffers (tests).
pub trait ReadAt {
    fn read_at(&self, buf: &mut [u8], offset: u64) -> io::Result<usize>;
}

impl ReadAt for File {
    fn read_at(&self, buf: &mut [u8], offset: u64) -> io::Result<usize> {
        FileExt::read_at(self, buf, offset)
    }
}

impl ReadAt for [u8] {
    fn read_at(&self, buf: &mut [u8], offset: u64) -> io::Result<usize> {
        let start = usize::try_from(offset)
            .unwrap_or(usize::MAX)
            .min(self.len());
        let n = buf.len().min(self.len() - start);
        buf[..n].copy_from_slice(&self[start..start + n]);
        Ok(n)
    }
}

fn read_full<R: ReadAt + ?Sized>(r: &R, buf: &mut [u8], offset: u64) -> io::Result<()> {
    let mut done = 0;
    while done < buf.len() {
        let n = r.read_at(&mut buf[done..], offset + done as u64)?;
        if n == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                format!(
                    "file ended early while reading at offset {}",
                    offset + done as u64
                ),
            ));
        }
        done += n;
    }
    Ok(())
}

/// A complete frame found in the file.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FrameInfo {
    /// Byte offset of the frame's first byte.
    pub offset: u64,
    /// Size of the frame in bytes, including padding.
    pub size: u64,
    pub step: u32,
    pub time_ps: f32,
}

/// Something the user should know about, though the work continues.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Warning {
    pub code: &'static str,
    pub message: String,
}

/// The result of locating frames.
#[derive(Debug)]
pub struct Located {
    pub magic: i32,
    pub natoms: usize,
    /// The located frames, oldest first. Never empty.
    pub frames: Vec<FrameInfo>,
    pub warnings: Vec<Warning>,
}

/// Why no frames could be located.
#[derive(Debug)]
pub enum LocateError {
    /// The file holds no complete frame.
    Empty(String),
    /// The file is not a valid XTC file.
    Invalid(String),
    Io(io::Error),
}

impl LocateError {
    /// The error code used in the control protocol.
    pub fn code(&self) -> &'static str {
        match self {
            LocateError::Empty(_) => "xtc_empty",
            LocateError::Invalid(_) => "xtc_invalid",
            LocateError::Io(_) => "io",
        }
    }
}

impl fmt::Display for LocateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LocateError::Empty(msg) | LocateError::Invalid(msg) => f.write_str(msg),
            LocateError::Io(err) => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for LocateError {}

impl From<io::Error> for LocateError {
    fn from(err: io::Error) -> Self {
        LocateError::Io(err)
    }
}

/// Result of looking for a frame at one offset.
#[derive(Debug, Clone, Copy, PartialEq)]
enum Probe {
    /// A complete, plausible frame.
    Frame(FrameInfo),
    /// Starts like a header, but the frame does not fit in the file (yet).
    Incomplete,
    /// Not a frame header.
    NotHeader,
}

fn be_u32(b: &[u8]) -> u32 {
    u32::from_be_bytes([b[0], b[1], b[2], b[3]])
}

fn be_i32(b: &[u8]) -> i32 {
    i32::from_be_bytes([b[0], b[1], b[2], b[3]])
}

fn be_f32(b: &[u8]) -> f32 {
    f32::from_be_bytes([b[0], b[1], b[2], b[3]])
}

fn be_u64(b: &[u8]) -> u64 {
    u64::from_be_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]])
}

fn pad4(n: u64) -> u64 {
    (4 - n % 4) % 4
}

/// What every frame header in one file starts with.
struct Layout {
    magic: i32,
    natoms: u32,
    /// magic and natoms, big-endian: the first 8 bytes of every header.
    pattern: [u8; 8],
}

impl Layout {
    fn new(magic: i32, natoms: u32) -> Self {
        let mut pattern = [0u8; 8];
        pattern[..4].copy_from_slice(&magic.to_be_bytes());
        pattern[4..].copy_from_slice(&natoms.to_be_bytes());
        Layout {
            magic,
            natoms,
            pattern,
        }
    }

    /// An upper bound for the compressed size of one frame. XTC compression of
    /// three 32-bit integers per atom never needs more than a few bits beyond
    /// them, so 16 bytes per atom plus slack is far above any real frame.
    fn max_nbytes(&self) -> u64 {
        u64::from(self.natoms) * 16 + 4096
    }

    /// Look for a frame at offset `p` in a file of `len` bytes.
    fn probe<R: ReadAt + ?Sized>(&self, r: &R, len: u64, p: u64) -> io::Result<Probe> {
        if p >= len {
            return Ok(Probe::Incomplete);
        }
        let avail = len - p;
        let take = avail.min(MAX_PROBE as u64) as usize;
        let mut storage = [0u8; MAX_PROBE];
        let buf = &mut storage[..take];
        read_full(r, buf, p)?;

        if take < 8 {
            return Ok(Probe::Incomplete);
        }
        if buf[..8] != self.pattern {
            return Ok(Probe::NotHeader);
        }
        if take < HEADER_SIZE as usize {
            return Ok(Probe::Incomplete);
        }
        if be_u32(&buf[52..56]) != self.natoms {
            return Ok(Probe::NotHeader);
        }
        let step = be_u32(&buf[8..12]);
        let time_ps = be_f32(&buf[12..16]);

        let size = if self.natoms <= 9 {
            HEADER_SIZE + 12 * u64::from(self.natoms)
        } else {
            let width: usize = if self.magic == MAGIC_2023 { 8 } else { 4 };
            if take < 88 + width {
                return Ok(Probe::Incomplete);
            }
            let precision = be_f32(&buf[56..60]);
            if !(precision.is_finite() && precision > 0.0) {
                return Ok(Probe::NotHeader);
            }
            for i in 0..3 {
                let lo = be_i32(&buf[60 + 4 * i..]);
                let hi = be_i32(&buf[72 + 4 * i..]);
                if lo > hi {
                    return Ok(Probe::NotHeader);
                }
            }
            let nbytes = if width == 8 {
                be_u64(&buf[88..96])
            } else {
                u64::from(be_u32(&buf[88..92]))
            };
            if nbytes == 0 || nbytes > self.max_nbytes() {
                return Ok(Probe::NotHeader);
            }
            88 + width as u64 + nbytes + pad4(nbytes)
        };

        if size > avail {
            return Ok(Probe::Incomplete);
        }
        Ok(Probe::Frame(FrameInfo {
            offset: p,
            size,
            step,
            time_ps,
        }))
    }

    /// Whether what follows a frame ending at `end` is consistent with that
    /// frame being the last complete one: nothing, too little to tell, or the
    /// start of another header (the frame still being written).
    fn tail_ok<R: ReadAt + ?Sized>(&self, r: &R, len: u64, end: u64) -> io::Result<bool> {
        let rest = len - end;
        if rest < 8 {
            return Ok(true);
        }
        let mut b = [0u8; 8];
        read_full(r, &mut b, end)?;
        Ok(b == self.pattern)
    }
}

/// Offsets that start with the header pattern, visited from the end of the
/// file towards its start. Only offsets divisible by 4 are considered, because
/// every XTC field and padded block is a multiple of 4 bytes.
struct Candidates<'a, R: ?Sized> {
    r: &'a R,
    len: u64,
    pattern: [u8; 8],
    /// Offsets below this one are still to be searched.
    upper: u64,
    /// Matches in the current block, ascending; `pop` yields the highest.
    pending: Vec<u64>,
    buf: Vec<u8>,
}

impl<'a, R: ReadAt + ?Sized> Candidates<'a, R> {
    fn new(r: &'a R, len: u64, pattern: [u8; 8]) -> Self {
        Candidates {
            r,
            len,
            pattern,
            upper: len,
            pending: Vec::new(),
            buf: Vec::new(),
        }
    }

    fn next(&mut self) -> io::Result<Option<u64>> {
        loop {
            if let Some(p) = self.pending.pop() {
                return Ok(Some(p));
            }
            if self.upper == 0 {
                return Ok(None);
            }
            let start = self.upper.saturating_sub(BLOCK) & !3;
            // 7 bytes of overlap so a pattern crossing the block boundary is seen.
            let read_end = (self.upper + 7).min(self.len);
            self.buf.resize((read_end - start) as usize, 0);
            read_full(self.r, &mut self.buf, start)?;
            let mut p = start;
            while p < self.upper && p + 8 <= read_end {
                let i = (p - start) as usize;
                if self.buf[i..i + 8] == self.pattern {
                    self.pending.push(p);
                }
                p += 4;
            }
            self.upper = start;
        }
    }
}

/// Read and check the first frame; it defines magic and natoms for the file.
fn anchor<R: ReadAt + ?Sized>(r: &R, len: u64) -> Result<Layout, LocateError> {
    if len < 8 {
        return Err(LocateError::Empty(format!(
            "the file holds no complete frame ({len} bytes)"
        )));
    }
    let mut head = [0u8; 8];
    read_full(r, &mut head, 0)?;
    let magic = be_i32(&head[..4]);
    if magic != MAGIC_1995 && magic != MAGIC_2023 {
        return Err(LocateError::Invalid(format!(
            "not an XTC file: magic number {magic} at offset 0 (expected {MAGIC_1995} or {MAGIC_2023})"
        )));
    }
    let natoms = be_u32(&head[4..8]);
    if natoms == 0 || natoms > i32::MAX as u32 {
        return Err(LocateError::Invalid(format!(
            "not an XTC file: implausible atom count {natoms} in the first frame"
        )));
    }
    let layout = Layout::new(magic, natoms);
    match layout.probe(r, len, 0)? {
        Probe::Frame(_) => Ok(layout),
        Probe::Incomplete => Err(LocateError::Empty(
            "the file holds no complete frame yet".to_string(),
        )),
        Probe::NotHeader => Err(LocateError::Invalid(
            "the first frame's header is invalid".to_string(),
        )),
    }
}

struct Forward {
    /// The last frames found, oldest first, at most `n`.
    frames: Vec<FrameInfo>,
    /// Offset of the invalid frame that ended the scan, if any.
    stopped_at: Option<u64>,
}

/// Walk the file from its start, header to header.
fn forward_scan<R: ReadAt + ?Sized>(
    r: &R,
    len: u64,
    layout: &Layout,
    n: usize,
) -> io::Result<Forward> {
    let mut tail: VecDeque<FrameInfo> = VecDeque::with_capacity(n);
    let mut p = 0;
    let stopped_at = loop {
        if p >= len {
            break None;
        }
        match layout.probe(r, len, p)? {
            Probe::Frame(f) => {
                if tail.len() == n {
                    tail.pop_front();
                }
                tail.push_back(f);
                p += f.size;
            }
            // The frame mdrun is still writing, or a few trailing bytes.
            Probe::Incomplete => break None,
            Probe::NotHeader => break Some(p),
        }
    };
    Ok(Forward {
        frames: tail.into(),
        stopped_at,
    })
}

/// Locate the last `n` complete frames (fewer if the file holds fewer).
///
/// `len` is the file length to consider; anything beyond it is ignored.
pub fn locate_last_frames<R: ReadAt + ?Sized>(
    r: &R,
    len: u64,
    n: usize,
) -> Result<Located, LocateError> {
    assert!(n >= 1, "at least one frame must be requested");
    let layout = anchor(r, len)?;
    let mut candidates = Candidates::new(r, len, layout.pattern);

    // Newest first while scanning backwards.
    let mut found: Vec<FrameInfo> = Vec::new();
    let mut warnings: Vec<Warning> = Vec::new();

    // The last complete frame: the highest plausible frame that fits in the
    // file and is followed by nothing, too little to tell, or another header.
    let mut rejected_for_tail: Option<FrameInfo> = None;
    while let Some(p) = candidates.next()? {
        if let Probe::Frame(f) = layout.probe(r, len, p)? {
            if layout.tail_ok(r, len, p + f.size)? {
                found.push(f);
                break;
            }
            rejected_for_tail.get_or_insert(f);
        }
    }

    // A valid frame followed by something that is not a header, and directly
    // preceded by the frame just accepted, is the real last frame: the file
    // has unexpected data at its end. Keep the frame, and say so.
    if let (Some(last), Some(rejected)) = (found.first().copied(), rejected_for_tail)
        && last.offset + last.size == rejected.offset
    {
        found.insert(0, rejected);
        let ignored = len - (rejected.offset + rejected.size);
        warnings.push(Warning {
            code: "trailing_data",
            message: format!(
                "unexpected data after the frame at offset {} (step {}, t = {} ps); \
                 the last {ignored} bytes of the file are ignored",
                rejected.offset, rejected.step, rejected.time_ps
            ),
        });
    }

    // Earlier frames: each must end exactly where the next accepted one starts.
    let mut broken_at: Option<u64> = None;
    if let Some(earliest) = found.last().copied() {
        let mut q = earliest.offset;
        while found.len() < n && q > 0 {
            let mut previous = None;
            while let Some(p) = candidates.next()? {
                if let Probe::Frame(f) = layout.probe(r, len, p)?
                    && p + f.size == q
                {
                    previous = Some(f);
                    break;
                }
            }
            match previous {
                Some(f) => {
                    q = f.offset;
                    found.push(f);
                }
                None => {
                    broken_at = Some(q);
                    break;
                }
            }
        }
    }

    let natoms = layout.natoms as usize;
    found.truncate(n);
    if !found.is_empty() && broken_at.is_none() {
        found.reverse();
        return Ok(Located {
            magic: layout.magic,
            natoms,
            frames: found,
            warnings,
        });
    }

    // Fallback: the backward scan could not chain frames.
    let reason = match broken_at {
        Some(q) => format!("no frame ends at offset {q}"),
        None => "the last complete frame could not be identified".to_string(),
    };
    warnings.push(Warning {
        code: "scan_fallback",
        message: format!(
            "backward scan failed ({reason}); the file was scanned from the start instead"
        ),
    });

    let forward = forward_scan(r, len, &layout, n)?;
    let frames = match forward.stopped_at {
        None => forward.frames,
        Some(bad) => {
            // Frames the backward scan found after the damage are newer than
            // anything the forward scan can reach, so prefer them.
            let earliest_backward = found.last().map(|f| f.offset);
            match earliest_backward {
                Some(earliest) if bad < earliest => {
                    found.reverse();
                    warnings.push(Warning {
                        code: "scan_stopped",
                        message: format!(
                            "the file is damaged at offset {bad}; frames before offset {earliest} \
                             could not be located, so only the {} newest frame(s) after the damage are sent",
                            found.len()
                        ),
                    });
                    found
                }
                _ => {
                    let message = match forward.frames.last() {
                        Some(f) => format!(
                            "invalid frame at offset {bad}; everything after it is ignored, so the \
                             newest frame sent is step {} at t = {} ps, which may not be the newest \
                             in the file",
                            f.step, f.time_ps
                        ),
                        None => format!("invalid frame at offset {bad}"),
                    };
                    warnings.push(Warning {
                        code: "scan_stopped",
                        message,
                    });
                    forward.frames
                }
            }
        }
    };

    if frames.is_empty() {
        return Err(LocateError::Empty(
            "the file holds no complete frame".to_string(),
        ));
    }
    Ok(Located {
        magic: layout.magic,
        natoms,
        frames,
        warnings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn header(magic: i32, natoms: u32, nbytes: u64) -> Vec<u8> {
        let mut b = Vec::new();
        b.extend(magic.to_be_bytes());
        b.extend(natoms.to_be_bytes());
        b.extend(7u32.to_be_bytes()); // step
        b.extend(1.5f32.to_be_bytes()); // time
        b.extend([0u8; 36]); // box
        b.extend(natoms.to_be_bytes());
        b.extend(1000f32.to_be_bytes()); // precision
        b.extend([0u8; 12]); // minint
        b.extend([0u8; 12]); // maxint
        b.extend(0i32.to_be_bytes()); // smallidx
        if magic == MAGIC_2023 {
            b.extend(nbytes.to_be_bytes());
        } else {
            b.extend((nbytes as u32).to_be_bytes());
        }
        b
    }

    #[test]
    fn probe_sizes_compressed_frames() {
        for (magic, base) in [(MAGIC_1995, 92u64), (MAGIC_2023, 96u64)] {
            let layout = Layout::new(magic, 100);
            let mut data = header(magic, 100, 10);
            data.resize(data.len() + 12, 0); // 10 bytes + 2 padding
            match layout.probe(&data[..], data.len() as u64, 0).unwrap() {
                Probe::Frame(f) => assert_eq!(f.size, base + 12),
                other => panic!("unexpected {other:?}"),
            }
            // One byte short: incomplete, not invalid.
            let len = data.len() as u64 - 1;
            assert_eq!(layout.probe(&data[..], len, 0).unwrap(), Probe::Incomplete);
        }
    }

    #[test]
    fn probe_rejects_mismatched_repeat_and_bad_ranges() {
        let layout = Layout::new(MAGIC_1995, 100);
        let mut data = header(MAGIC_1995, 100, 8);
        data.resize(data.len() + 8, 0);
        let len = data.len() as u64;
        let mut repeat = data.clone();
        repeat[52..56].copy_from_slice(&99u32.to_be_bytes());
        assert_eq!(layout.probe(&repeat[..], len, 0).unwrap(), Probe::NotHeader);
        let mut range = data.clone();
        range[60..64].copy_from_slice(&5i32.to_be_bytes()); // minint > maxint
        assert_eq!(layout.probe(&range[..], len, 0).unwrap(), Probe::NotHeader);
        let mut huge = data.clone();
        huge[88..92].copy_from_slice(&u32::MAX.to_be_bytes());
        assert_eq!(layout.probe(&huge[..], len, 0).unwrap(), Probe::NotHeader);
    }

    #[test]
    fn candidates_only_aligned_and_across_blocks() {
        let pattern = Layout::new(MAGIC_1995, 3).pattern;
        let size = (BLOCK as usize) * 2 + 100;
        let mut data = vec![0u8; size];
        // Aligned, straddling the first block boundary seen from the end.
        let straddle = size as u64 - BLOCK - 4;
        let straddle = straddle & !3;
        for p in [0u64, 8, straddle, size as u64 - 8] {
            data[p as usize..p as usize + 8].copy_from_slice(&pattern);
        }
        // Unaligned copy must be ignored.
        data[1001..1009].copy_from_slice(&pattern);
        let mut c = Candidates::new(&data[..], size as u64, pattern);
        let mut got = Vec::new();
        while let Some(p) = c.next().unwrap() {
            got.push(p);
        }
        let mut want = vec![size as u64 - 8, straddle, 8, 0];
        want.dedup();
        assert_eq!(got, want);
    }
}

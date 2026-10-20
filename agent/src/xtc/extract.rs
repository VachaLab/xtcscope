//! Copying located frames, unchanged, to a writer.
//!
//! XTC frames are self-contained, so the bytes of consecutive complete frames
//! form a valid XTC file on their own. Nothing is decoded.

use std::io::{self, Write};

use super::index::{FrameInfo, ReadAt, read_full};

/// Size of the copy buffer.
const CHUNK: u64 = 1 << 20;

/// The byte range `(start, end)` covered by `frames`, oldest first.
///
/// Returns `None` for an empty slice.
pub fn byte_range(frames: &[FrameInfo]) -> Option<(u64, u64)> {
    let first = frames.first()?;
    let last = frames.last()?;
    Some((first.offset, last.offset + last.size))
}

/// Copy the bytes of `frames` from `r` to `out` and return how many were written.
///
/// The frames must be contiguous and oldest first, as `locate_last_frames`
/// returns them; otherwise nothing is written and an `InvalidInput` error is
/// returned. `out` is not flushed.
pub fn copy_frames<R: ReadAt + ?Sized, W: Write>(
    r: &R,
    frames: &[FrameInfo],
    out: &mut W,
) -> io::Result<u64> {
    for pair in frames.windows(2) {
        if pair[0].offset + pair[0].size != pair[1].offset {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "frames at offsets {} and {} are not contiguous",
                    pair[0].offset, pair[1].offset
                ),
            ));
        }
    }
    let Some((start, end)) = byte_range(frames) else {
        return Ok(0);
    };
    let mut buf = vec![0u8; CHUNK.min(end - start) as usize];
    let mut pos = start;
    while pos < end {
        let n = CHUNK.min(end - pos) as usize;
        read_full(r, &mut buf[..n], pos)?;
        out.write_all(&buf[..n])?;
        pos += n as u64;
    }
    Ok(end - start)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A frame of `size` bytes at `offset`.
    fn frame(offset: u64, size: u64) -> FrameInfo {
        FrameInfo {
            offset,
            size,
            step: 0,
            time_ps: 0.0,
        }
    }

    /// Distinct, position-dependent bytes.
    fn data(len: usize) -> Vec<u8> {
        (0..len).map(|i| (i % 251) as u8).collect()
    }

    /// Contiguous frames are copied as one exact byte range.
    #[test]
    fn copies_the_exact_range() {
        let input = data(1000);
        let frames = [frame(100, 200), frame(300, 150), frame(450, 50)];
        let mut out = Vec::new();
        let n = copy_frames(&input[..], &frames, &mut out).unwrap();
        assert_eq!(n, 400);
        assert_eq!(out, &input[100..500]);
        assert_eq!(byte_range(&frames), Some((100, 500)));
    }

    /// Ranges larger than the buffer are copied in several chunks.
    #[test]
    fn copies_across_chunks() {
        let input = data(3 * CHUNK as usize + 123);
        let frames = [frame(7, CHUNK + 1), frame(CHUNK + 8, 2 * CHUNK)];
        let mut out = Vec::new();
        let n = copy_frames(&input[..], &frames, &mut out).unwrap();
        assert_eq!(n, 3 * CHUNK + 1);
        assert_eq!(out, &input[7..7 + 3 * CHUNK as usize + 1]);
    }

    /// Gaps between frames are refused before anything is written.
    #[test]
    fn refuses_non_contiguous_frames() {
        let input = data(100);
        let mut out = Vec::new();
        let err = copy_frames(&input[..], &[frame(0, 10), frame(20, 10)], &mut out).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert!(out.is_empty());
    }

    /// No frames, no bytes.
    #[test]
    fn empty_selection_copies_nothing() {
        let mut out = Vec::new();
        assert_eq!(copy_frames(&data(10)[..], &[], &mut out).unwrap(), 0);
        assert_eq!(byte_range(&[]), None);
    }

    /// A range past the end of the data is an error, not a short copy.
    #[test]
    fn short_data_is_an_error() {
        let mut out = Vec::new();
        let err = copy_frames(&data(10)[..], &[frame(0, 20)], &mut out).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::UnexpectedEof);
    }
}

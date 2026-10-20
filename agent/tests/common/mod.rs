//! Test fixtures: XTC files generated with molly's writer.

#![allow(dead_code)]

use std::io::Cursor;

use molly::{Magic, XTCReader, XTCWriter};

/// Deterministic pseudo-random coordinates in [0.5, 4.5) nm.
pub fn coords(natoms: usize, frame: usize) -> Vec<f32> {
    let mut state: u64 = 0x9E37_79B9_7F4A_7C15 ^ ((frame as u64 + 1) * 0x1000_0001);
    (0..natoms * 3)
        .map(|_| {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            0.5 + 4.0 * ((state >> 40) as f32 / (1u64 << 24) as f32)
        })
        .collect()
}

pub fn molly_frame(natoms: usize, i: usize) -> molly::Frame {
    molly::Frame {
        step: (i * 1000) as u32,
        time: i as f32 * 2.0,
        boxvec: [5.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 5.0],
        precision: 1000.0,
        positions: coords(natoms, i),
    }
}

/// An XTC file with `nframes` frames of `natoms` atoms.
pub fn make_xtc(magic: Magic, natoms: usize, nframes: usize) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut writer = XTCWriter::new_with_magic(&mut buf, magic);
        for i in 0..nframes {
            writer.write_frame(&molly_frame(natoms, i)).unwrap();
        }
    }
    buf
}

/// Frame start offsets and decoded frames, read front to back with molly.
pub fn reference(data: &[u8]) -> (Vec<u64>, Vec<molly::Frame>) {
    let mut reader = XTCReader::new(Cursor::new(data));
    let mut offsets = Vec::new();
    let mut frames = Vec::new();
    loop {
        let start = reader.file.position();
        if start as usize >= data.len() {
            break;
        }
        let mut frame = molly::Frame::default();
        match reader.read_frame(&mut frame) {
            Ok(()) => {
                offsets.push(start);
                frames.push(frame);
            }
            Err(_) => break,
        }
    }
    (offsets, frames)
}

/// A frame header with zeroed box and ranges, for planting fake headers.
pub fn fake_header(magic: Magic, natoms: u32, nbytes: u64) -> Vec<u8> {
    let magic = magic as i32;
    let mut b = Vec::new();
    b.extend(magic.to_be_bytes());
    b.extend(natoms.to_be_bytes());
    b.extend(123u32.to_be_bytes());
    b.extend(9.0f32.to_be_bytes());
    b.extend([0u8; 36]);
    b.extend(natoms.to_be_bytes());
    b.extend(1000f32.to_be_bytes());
    b.extend([0u8; 24]);
    b.extend(0i32.to_be_bytes());
    if magic == 2023 {
        b.extend(nbytes.to_be_bytes());
    } else {
        b.extend((nbytes as u32).to_be_bytes());
    }
    b
}

pub const MAGICS: [Magic; 2] = [Magic::Xtc1995, Magic::Xtc2023];

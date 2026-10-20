//! Locating the last frames: backward scan, partial frames, planted headers,
//! fallback and errors.

mod common;

use common::{MAGICS, fake_header, make_xtc, reference};
use molly::Magic;
use xtcscope_agent::xtc::{LocateError, Located, locate_last_frames};

fn locate(data: &[u8], n: usize) -> Result<Located, LocateError> {
    locate_last_frames(data, data.len() as u64, n)
}

fn offsets(located: &Located) -> Vec<u64> {
    located.frames.iter().map(|f| f.offset).collect()
}

fn codes(located: &Located) -> Vec<&'static str> {
    located.warnings.iter().map(|w| w.code).collect()
}

fn tail(v: &[u64], n: usize) -> Vec<u64> {
    v[v.len().saturating_sub(n)..].to_vec()
}

#[test]
fn clean_files_match_molly() {
    for magic in MAGICS {
        for natoms in [1, 5, 9, 10, 200, 2000] {
            let data = make_xtc(magic, natoms, 25);
            let (ref_offsets, ref_frames) = reference(&data);
            assert_eq!(ref_offsets.len(), 25);
            for n in [1, 10, 25, 100] {
                let located = locate(&data, n).unwrap();
                let ctx = format!("magic {magic:?}, natoms {natoms}, n {n}");
                assert_eq!(offsets(&located), tail(&ref_offsets, n), "{ctx}");
                assert!(located.warnings.is_empty(), "{ctx}");
                assert_eq!(located.natoms, natoms, "{ctx}");
                assert_eq!(located.magic, magic as i32, "{ctx}");
                let first = ref_frames.len() - located.frames.len();
                for (f, r) in located.frames.iter().zip(&ref_frames[first..]) {
                    assert_eq!(f.step, r.step, "{ctx}");
                    assert_eq!(f.time_ps, r.time, "{ctx}");
                }
            }
        }
    }
}

#[test]
fn partial_last_frame_at_every_byte() {
    for magic in MAGICS {
        for natoms in [5, 200] {
            let data = make_xtc(magic, natoms, 25);
            let (ref_offsets, _) = reference(&data);
            let last = ref_offsets[24] as usize;
            let want = ref_offsets[14..24].to_vec();
            for cut in last..data.len() {
                let located = locate(&data[..cut], 10)
                    .unwrap_or_else(|e| panic!("cut {cut}, magic {magic:?}, natoms {natoms}: {e}"));
                assert_eq!(offsets(&located), want, "cut {cut}");
                assert!(located.warnings.is_empty(), "cut {cut}");
            }
        }
    }
}

#[test]
fn planted_patterns_are_never_accepted() {
    for magic in MAGICS {
        let natoms = 200u32;
        let mut data = make_xtc(magic, natoms as usize, 25);
        let (ref_offsets, _) = reference(&data);
        let mut pattern = Vec::new();
        pattern.extend((magic as i32).to_be_bytes());
        pattern.extend(natoms.to_be_bytes());
        for k in [3usize, 12, 20, 24] {
            let start = ref_offsets[k] as usize;
            // Aligned and unaligned bare patterns inside the compressed data.
            data[start + 120..start + 128].copy_from_slice(&pattern);
            data[start + 141..start + 149].copy_from_slice(&pattern);
            // A full fake header whose frame does not end at the next frame.
            let fake = fake_header(magic, natoms, 40);
            data[start + 200..start + 200 + fake.len()].copy_from_slice(&fake);
        }
        let located = locate(&data, 25).unwrap();
        assert_eq!(offsets(&located), ref_offsets, "magic {magic:?}");
        assert!(located.warnings.is_empty(), "magic {magic:?}");
    }
}

#[test]
fn fake_header_that_fools_the_chain_falls_back_correctly() {
    for magic in MAGICS {
        let natoms = 200u32;
        let mut data = make_xtc(magic, natoms as usize, 25);
        let (ref_offsets, _) = reference(&data);
        let k = 10;
        let p = ref_offsets[k] as usize + 200;
        let base = if magic == Magic::Xtc2023 { 96 } else { 92 };
        // Chosen so the fake frame ends exactly where frame k+1 starts.
        let nbytes = ref_offsets[k + 1] - p as u64 - base;
        let fake = fake_header(magic, natoms, nbytes);
        data[p..p + fake.len()].copy_from_slice(&fake);
        let located = locate(&data, 25).unwrap();
        assert_eq!(offsets(&located), ref_offsets, "magic {magic:?}");
        assert_eq!(codes(&located), ["scan_fallback"], "magic {magic:?}");
    }
}

#[test]
fn broken_chain_in_the_middle_sends_frames_after_the_damage() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 25);
    let (ref_offsets, _) = reference(&data);
    let bad = ref_offsets[10] as usize;
    data[bad..bad + 4].copy_from_slice(&[0, 0, 0, 0]);
    let located = locate(&data, 20).unwrap();
    assert_eq!(offsets(&located), ref_offsets[11..].to_vec());
    assert_eq!(codes(&located), ["scan_fallback", "scan_stopped"]);
}

#[test]
fn damage_near_the_end_warns() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 25);
    let (ref_offsets, _) = reference(&data);
    let bad = ref_offsets[23] as usize;
    data[bad..bad + 4].copy_from_slice(&[0, 0, 0, 0]);
    let located = locate(&data, 10).unwrap();
    assert_eq!(offsets(&located), vec![ref_offsets[24]]);
    assert_eq!(codes(&located), ["scan_fallback", "scan_stopped"]);
}

#[test]
fn damaged_first_frames_use_forward_scan_result() {
    // Damage right after frame 0: the backward chain cannot reach the start,
    // and the forward scan stops after frame 0. The frames after the damage
    // are newer, so they are the ones sent.
    let mut data = make_xtc(Magic::Xtc1995, 200, 5);
    let (ref_offsets, _) = reference(&data);
    let bad = ref_offsets[1] as usize;
    data[bad..bad + 4].copy_from_slice(&[0, 0, 0, 0]);
    let located = locate(&data, 10).unwrap();
    assert_eq!(offsets(&located), ref_offsets[2..].to_vec());
    assert_eq!(codes(&located), ["scan_fallback", "scan_stopped"]);
}

#[test]
fn trailing_garbage_keeps_the_last_frame_and_warns() {
    let mut data = make_xtc(Magic::Xtc1995, 200, 25);
    let (ref_offsets, _) = reference(&data);
    data.extend(std::iter::repeat_n(0xAB, 100));
    let located = locate(&data, 10).unwrap();
    assert_eq!(offsets(&located), ref_offsets[15..].to_vec());
    assert_eq!(codes(&located), ["trailing_data"]);
}

#[test]
fn single_frame_file() {
    let data = make_xtc(Magic::Xtc1995, 200, 1);
    let located = locate(&data, 10).unwrap();
    assert_eq!(offsets(&located), vec![0]);
    assert!(located.warnings.is_empty());
}

#[test]
fn empty_and_too_short_files_are_empty() {
    let data = make_xtc(Magic::Xtc1995, 200, 3);
    let (ref_offsets, _) = reference(&data);
    for cut in [0usize, 4, 8, 30, 56, 90, ref_offsets[1] as usize - 1] {
        match locate(&data[..cut], 10) {
            Err(err @ LocateError::Empty(_)) => assert_eq!(err.code(), "xtc_empty"),
            other => panic!("cut {cut}: expected Empty, got {other:?}"),
        }
    }
}

#[test]
fn non_xtc_files_are_invalid() {
    let text = b"This is not an XTC file at all, just some text.\n".repeat(10);
    match locate(&text, 10) {
        Err(err @ LocateError::Invalid(_)) => assert_eq!(err.code(), "xtc_invalid"),
        other => panic!("expected Invalid, got {other:?}"),
    }
    // Right magic and natoms, but the repeated natoms disagrees.
    let mut data = make_xtc(Magic::Xtc1995, 200, 3);
    data[52..56].copy_from_slice(&199u32.to_be_bytes());
    assert!(matches!(locate(&data, 10), Err(LocateError::Invalid(_))));
}

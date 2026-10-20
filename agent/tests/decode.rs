//! Decoding located frames with molly through `XtcSource`.

mod common;

use std::io::Write;

use common::{MAGICS, coords, make_xtc, reference};
use molly::Magic;
use xtcscope_agent::xtc::{Frame, FrameSource, XtcSource};

fn write_temp(data: &[u8]) -> tempfile::NamedTempFile {
    let mut file = tempfile::NamedTempFile::new().unwrap();
    file.write_all(data).unwrap();
    file.flush().unwrap();
    file
}

#[test]
fn decoded_frames_match_molly_and_the_input() {
    for magic in MAGICS {
        for natoms in [5, 2000] {
            let data = make_xtc(magic, natoms, 25);
            let (_, ref_frames) = reference(&data);
            let file = write_temp(&data);
            let mut source = XtcSource::open(file.path(), 10).unwrap();
            assert_eq!(source.len(), 10);
            assert_eq!(source.natoms(), natoms);
            assert_eq!(source.magic(), magic as i32);
            let mut frame = Frame::default();
            for i in 0..source.len() {
                source.read(i, &mut frame).unwrap();
                let r = &ref_frames[15 + i];
                assert_eq!(frame.step, i64::from(r.step));
                assert_eq!(frame.time_ps, f64::from(r.time));
                assert_eq!(frame.box_nm, r.boxvec);
                assert_eq!(frame.positions_nm, r.positions);
                // And within XTC precision of what was written.
                for (got, want) in frame.positions_nm.iter().zip(coords(natoms, 15 + i)) {
                    assert!((got - want).abs() < 1e-3, "{got} vs {want}");
                }
            }
        }
    }
}

#[test]
fn file_written_after_open_is_ignored() {
    let data = make_xtc(Magic::Xtc1995, 200, 5);
    let mut file = write_temp(&data);
    let mut source = XtcSource::open(file.path(), 10).unwrap();
    // mdrun appends more frames after the agent started.
    file.write_all(&make_xtc(Magic::Xtc1995, 200, 3)).unwrap();
    file.flush().unwrap();
    assert_eq!(source.len(), 5);
    let mut frame = Frame::default();
    source.read(4, &mut frame).unwrap();
    assert_eq!(frame.step, 4000);
}

#[test]
fn corrupted_frame_data_never_panics() {
    let mut data = make_xtc(Magic::Xtc1995, 2000, 3);
    let (offsets, _) = reference(&data);
    let start = offsets[2] as usize + 200;
    let end = data.len() - 8;
    for b in &mut data[start..end] {
        *b = 0xFF;
    }
    let file = write_temp(&data);
    let mut source = XtcSource::open(file.path(), 10).unwrap();
    let mut frame = Frame::default();
    // Whatever molly makes of it, the call returns instead of unwinding.
    let _ = source.read(2, &mut frame);
}

#[test]
fn open_reports_error_codes() {
    let missing = XtcSource::open(std::path::Path::new("/nonexistent/traj.xtc"), 10)
        .err()
        .unwrap();
    assert_eq!(missing.code(), "xtc_open");

    let empty = write_temp(&[]);
    let err = XtcSource::open(empty.path(), 10).err().unwrap();
    assert_eq!(err.code(), "xtc_empty");

    let text = write_temp(&b"not an xtc file, definitely not\n".repeat(4));
    let err = XtcSource::open(text.path(), 10).err().unwrap();
    assert_eq!(err.code(), "xtc_invalid");
}

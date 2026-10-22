//! Reading XTC trajectories: locating the last frames and copying their bytes.

pub mod extract;
pub mod index;
pub mod open;

pub use extract::{byte_range, copy_frames};
pub use index::{FrameInfo, LocateError, Located, ReadAt, Warning, locate_last_frames};
pub use open::{OpenError, open_located};

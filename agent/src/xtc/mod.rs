//! Reading XTC trajectories: locating the last frames, copying and decoding them.

pub mod extract;
pub mod index;
pub mod open;
pub mod source;

pub use extract::{byte_range, copy_frames};
pub use index::{FrameInfo, LocateError, Located, ReadAt, Warning, locate_last_frames};
pub use open::{OpenError, open_located};
pub use source::{Frame, FrameSource, XtcSource};

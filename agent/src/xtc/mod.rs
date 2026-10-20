//! Reading XTC trajectories: locating the last frames and decoding them.

pub mod index;
pub mod source;

pub use index::{FrameInfo, LocateError, Located, ReadAt, Warning, locate_last_frames};
pub use source::{Frame, FrameSource, OpenError, XtcSource};

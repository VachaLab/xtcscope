//! The IMD protocol: wire format and the single-client server.

pub mod packet;
pub mod server;

pub use packet::ImdVersion;
pub use server::{
    EndReason, ServeError, SessionEvent, accept, bind, remove_socket_file, run_session,
};

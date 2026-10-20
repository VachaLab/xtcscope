//! IMD wire format: 8-byte headers and message bodies.
//!
//! Every message starts with a header of two i32 fields, `type` and `value`,
//! both big-endian. The one exception is the handshake, whose `value` (the
//! protocol version) is sent in native byte order so the receiver can detect
//! the sender's byte order. Bodies use native byte order.
//!
//! See <https://imdclient.readthedocs.io/en/latest/protocol_v3.html>, which
//! also documents v2.

use crate::xtc::Frame;

/// Size of every message header in bytes.
pub const HEADER_SIZE: usize = 8;

/// XTC stores nm; IMD sends Å.
pub const NM_TO_ANGSTROM: f32 = 10.0;

/// IMD message types.
pub mod ty {
    /// Client asks the server to close the connection.
    pub const DISCONNECT: i32 = 0;
    /// Energy block (never sent by the agent).
    pub const ENERGIES: i32 = 1;
    /// Coordinates of all atoms, `value` = atom count.
    pub const COORDINATES: i32 = 2;
    /// Client accepts the handshake.
    pub const GO: i32 = 3;
    /// First message from the server, `value` = protocol version.
    pub const HANDSHAKE: i32 = 4;
    /// Client asks the engine to stop (the agent only disconnects).
    pub const KILL: i32 = 5;
    /// Forces from the client, `value` = number of atoms.
    pub const MD_COMM: i32 = 6;
    /// Pause (v2: toggle; v3: set).
    pub const PAUSE: i32 = 7;
    /// Client asks for a different transmission rate.
    pub const TRANSMISSION_RATE: i32 = 8;
    /// Error notice, no body.
    pub const IO_ERROR: i32 = 9;
    /// v3: which data each frame carries.
    pub const SESSION_INFO: i32 = 10;
    /// v3: resume after pause.
    pub const RESUME: i32 = 11;
    /// v3: time packet.
    pub const TIME: i32 = 12;
    /// v3: box packet.
    pub const BOX: i32 = 13;
    /// v3: velocities.
    pub const VELOCITIES: i32 = 14;
    /// v3: forces.
    pub const FORCES: i32 = 15;
    /// v3: blocking or non-blocking wait for clients.
    pub const WAIT: i32 = 16;
}

/// IMD protocol version spoken by the agent.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImdVersion {
    /// IMDv2, as spoken by VMD 1.9.
    V2,
}

impl ImdVersion {
    /// The version number sent in the handshake.
    pub fn number(self) -> i32 {
        match self {
            ImdVersion::V2 => 2,
        }
    }

    /// Append everything sent for one frame to `buf`.
    pub fn encode_frame(self, frame: &Frame, buf: &mut Vec<u8>) {
        match self {
            ImdVersion::V2 => encode_coordinates(&frame.positions_nm, buf),
        }
    }
}

/// Append a header with both fields big-endian.
pub fn encode_header(buf: &mut Vec<u8>, ty: i32, value: i32) {
    buf.extend_from_slice(&ty.to_be_bytes());
    buf.extend_from_slice(&value.to_be_bytes());
}

/// Append the handshake: type big-endian, version in native byte order.
pub fn encode_handshake(buf: &mut Vec<u8>, version: ImdVersion) {
    buf.extend_from_slice(&ty::HANDSHAKE.to_be_bytes());
    buf.extend_from_slice(&version.number().to_ne_bytes());
}

/// Append a Coordinates message; positions are given in nm and sent in Å.
pub fn encode_coordinates(positions_nm: &[f32], buf: &mut Vec<u8>) {
    let natoms = positions_nm.len() / 3;
    let natoms = i32::try_from(natoms).expect("atom count fits in i32");
    encode_header(buf, ty::COORDINATES, natoms);
    buf.reserve(positions_nm.len() * 4);
    for &x in positions_nm {
        buf.extend_from_slice(&(x * NM_TO_ANGSTROM).to_ne_bytes());
    }
}

/// A decoded message header.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Header {
    /// Message type, see [`ty`].
    pub ty: i32,
    /// Type-dependent value (a count, a version, a flag, or unused).
    pub value: i32,
}

impl Header {
    /// Decode a header whose fields are both big-endian.
    pub fn decode(bytes: &[u8; HEADER_SIZE]) -> Self {
        Header {
            ty: i32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]),
            value: i32::from_be_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]),
        }
    }
}

/// A message received from the client.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClientMessage {
    /// Close the connection.
    Disconnect,
    /// Accept the handshake.
    Go,
    /// Stop the simulation; the agent treats it as Disconnect.
    Kill,
    /// Pause sending.
    Pause,
    /// Resume sending (v3).
    Resume,
    /// New transmission rate; ignored.
    TransmissionRate(i32),
    /// Blocking flag (v3); ignored.
    Wait(i32),
    /// Error notice; ignored.
    IoError,
    /// Forces for `natoms` atoms; the body is discarded.
    MdComm {
        /// Number of atoms the forces apply to.
        natoms: usize,
    },
}

impl ClientMessage {
    /// Interpret a header from the client.
    ///
    /// Returns the message and the number of body bytes that follow it, or
    /// `Err(type)` for a type a client never sends; its body size is unknown,
    /// so the stream can't be followed after it.
    pub fn from_header(header: Header) -> Result<(ClientMessage, usize), i32> {
        let message = match header.ty {
            ty::DISCONNECT => ClientMessage::Disconnect,
            ty::GO => ClientMessage::Go,
            ty::KILL => ClientMessage::Kill,
            ty::PAUSE => ClientMessage::Pause,
            ty::RESUME => ClientMessage::Resume,
            ty::TRANSMISSION_RATE => ClientMessage::TransmissionRate(header.value),
            ty::WAIT => ClientMessage::Wait(header.value),
            ty::IO_ERROR => ClientMessage::IoError,
            ty::MD_COMM => {
                let natoms = usize::try_from(header.value).map_err(|_| header.ty)?;
                // i32 indices, then f32[3] forces per atom.
                return Ok((ClientMessage::MdComm { natoms }, natoms * (4 + 12)));
            }
            other => return Err(other),
        };
        Ok((message, 0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The handshake's type is big-endian and its version native-endian.
    #[test]
    fn handshake_bytes() {
        let mut buf = Vec::new();
        encode_handshake(&mut buf, ImdVersion::V2);
        assert_eq!(&buf[..4], &[0, 0, 0, 4]);
        assert_eq!(&buf[4..], &2i32.to_ne_bytes());
    }

    /// Coordinates: big-endian header with the atom count, native f32 in Å.
    #[test]
    fn coordinates_bytes() {
        let mut buf = Vec::new();
        encode_coordinates(&[0.1, 0.2, 0.3, 1.0, 2.0, 3.0], &mut buf);
        assert_eq!(&buf[..8], &[0, 0, 0, 2, 0, 0, 0, 2]);
        let values: Vec<f32> = buf[8..]
            .chunks_exact(4)
            .map(|c| f32::from_ne_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        assert_eq!(values, vec![1.0, 2.0, 3.0, 10.0, 20.0, 30.0]);
    }

    /// A v2 frame is exactly one Coordinates message.
    #[test]
    fn v2_frame_is_coordinates_only() {
        let frame = Frame {
            positions_nm: vec![1.0; 30],
            ..Frame::default()
        };
        let mut buf = Vec::new();
        ImdVersion::V2.encode_frame(&frame, &mut buf);
        assert_eq!(buf.len(), HEADER_SIZE + 30 * 4);
        assert_eq!(&buf[..8], &[0, 0, 0, 2, 0, 0, 0, 10]);
    }

    /// Headers decode big-endian.
    #[test]
    fn header_decode() {
        let h = Header::decode(&[0, 0, 0, 7, 0, 0, 1, 0]);
        assert_eq!(h, Header { ty: 7, value: 256 });
    }

    /// Client messages map to body sizes; unknown types are rejected.
    #[test]
    fn client_messages() {
        let msg = |ty, value| ClientMessage::from_header(Header { ty, value });
        assert_eq!(msg(ty::GO, 0), Ok((ClientMessage::Go, 0)));
        assert_eq!(msg(ty::PAUSE, 0), Ok((ClientMessage::Pause, 0)));
        assert_eq!(
            msg(ty::MD_COMM, 3),
            Ok((ClientMessage::MdComm { natoms: 3 }, 48))
        );
        assert_eq!(msg(ty::MD_COMM, -1), Err(ty::MD_COMM));
        assert_eq!(msg(ty::COORDINATES, 10), Err(ty::COORDINATES));
        assert_eq!(msg(99, 0), Err(99));
    }
}

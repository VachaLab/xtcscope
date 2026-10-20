//! Atom selection applied to frames before they are sent.
//!
//! v0.1 sends every atom. A later selection (for example "everything except
//! water") only needs a new [`AtomFilter`]; the structure loaded in VMD must
//! then contain the same atoms.

use crate::xtc::Frame;

/// Selects which atoms of a frame are sent.
pub trait AtomFilter {
    /// Number of atoms left after filtering a frame of `natoms_in` atoms.
    fn natoms_out(&self, natoms_in: usize) -> usize;
    /// Write the filtered copy of `input` into `out`, reusing its allocation.
    fn apply(&self, input: &Frame, out: &mut Frame);
}

/// Keeps every atom.
#[derive(Debug, Clone, Copy, Default)]
pub struct All;

impl AtomFilter for All {
    /// All atoms are kept.
    fn natoms_out(&self, natoms_in: usize) -> usize {
        natoms_in
    }

    /// Copy the frame unchanged.
    fn apply(&self, input: &Frame, out: &mut Frame) {
        out.clone_from(input);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `All` keeps the atom count and copies the frame exactly.
    #[test]
    fn all_copies_everything() {
        let input = Frame {
            step: 5,
            time_ps: 1.5,
            box_nm: [1.0; 9],
            positions_nm: vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        };
        let mut out = Frame::default();
        All.apply(&input, &mut out);
        assert_eq!(out, input);
        assert_eq!(All.natoms_out(2), 2);
    }
}

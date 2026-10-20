//! xtcscope-agent: serves the last frames of a GROMACS XTC trajectory over IMD.
//!
//! Milestone 0: only the command-line skeleton (`--version`, `--help`).

use clap::Parser;

/// Serves the last frames of a GROMACS XTC trajectory over IMD.
///
/// Normally started by the `xtcscope` script over SSH, not by hand.
#[derive(Debug, Parser)]
#[command(name = "xtcscope-agent", version, about, long_about = None)]
struct Cli {}

fn main() {
    let _cli = Cli::parse();
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn cli_definition_is_valid() {
        Cli::command().debug_assert();
    }

    #[test]
    fn version_flag_is_recognised() {
        let err = Cli::try_parse_from(["xtcscope-agent", "--version"]).unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::DisplayVersion);
    }

    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(
            Cli::command().get_version(),
            Some(env!("CARGO_PKG_VERSION"))
        );
    }
}

#!/bin/bash
# Installs xtcscope on LUMI.
#
# Each target home gets an xtcscope/ directory with the xtcscope executable and
# its _internal/ runtime, the xtcscope-agent binary and a VERSION file. The
# directory is also added to PATH through a block in that home's .bashrc,
# managed by xtcscope. Running the installer again updates the block only when
# it changed. Open a new terminal (or run `source ~/.bashrc`) to start using
# xtcscope.
#
# For testing, XTCSCOPE_RELEASE_BASE overrides the URL the release files are
# downloaded from (e.g. file:///tmp/fake-release), and XTCSCOPE_TARGET_HOMES
# (space-separated) replaces the list of target homes.

set -euo pipefail

# filled in by the release workflow
XTCSCOPE_VERSION="v__VERSION__"
XTCSCOPE_REPO="__REPO__"

# the name in this installer's messages
NAME="xtcscope lumi installer"

# >>> target homes
# home directories to install into: this machine's
TARGET_HOMES=(
    "${HOME}"
)
# <<< target homes

if [[ -n "${XTCSCOPE_TARGET_HOMES:-}" ]]; then
    read -r -a TARGET_HOMES <<< "$XTCSCOPE_TARGET_HOMES"
fi

# print an informational line
info() {
    echo "INFO    [${NAME}] $*"
}

# print a warning line
warn() {
    echo "WARN    [${NAME}] $*"
}

# print an error line and exit 1
die() {
    echo "ERROR   [${NAME}] $*" >&2
    exit 1
}

if [[ -n "${XTCSCOPE_RELEASE_BASE:-}" ]]; then
    RELEASE_BASE="$XTCSCOPE_RELEASE_BASE"
elif [[ "$XTCSCOPE_VERSION" == *__* || "$XTCSCOPE_REPO" == *__* ]]; then
    die "This is an unreleased copy of the installer. Download it from a GitHub release, or set XTCSCOPE_RELEASE_BASE."
else
    RELEASE_BASE="https://github.com/${XTCSCOPE_REPO}/releases/download/${XTCSCOPE_VERSION}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
INSTALLER="${TMP_DIR}/xtcscope-install.sh"

info "Downloading the installer from ${RELEASE_BASE} ..."
curl -fsSL -o "$INSTALLER" "${RELEASE_BASE}/xtcscope-install.sh" \
    || die "Could not download ${RELEASE_BASE}/xtcscope-install.sh."
chmod +x "$INSTALLER"

MISSING_HOMES=()
FAILED_HOMES=()
DONE_HOMES=()

for HOME_DIR in "${TARGET_HOMES[@]}"; do
    echo "--------------------------------------------"
    if [[ ! -d "$HOME_DIR" ]]; then
        warn "Skipping ${HOME_DIR} (directory not found)."
        MISSING_HOMES+=("$HOME_DIR")
        continue
    fi
    # the same directory can appear twice, e.g. $HOME and its storage path on the cluster
    REAL_DIR="$(cd "$HOME_DIR" && pwd -P)"
    if [[ " ${DONE_HOMES[*]-} " == *" ${REAL_DIR} "* ]]; then
        info "Skipping ${HOME_DIR} (same directory as an earlier target)."
        continue
    fi
    DONE_HOMES+=("$REAL_DIR")
    if ! "$INSTALLER" "$HOME_DIR" "${RELEASE_BASE}/xtcscope-release.tar.gz"; then
        FAILED_HOMES+=("$HOME_DIR")
    fi
done

echo "--------------------------------------------"
for MISSING in "${MISSING_HOMES[@]+"${MISSING_HOMES[@]}"}"; do
    warn "Not installed (directory not found): ${MISSING}"
done
for FAILED in "${FAILED_HOMES[@]+"${FAILED_HOMES[@]}"}"; do
    warn "Installation failed: ${FAILED}"
done

if [[ ${#FAILED_HOMES[@]} -gt 0 ]]; then
    exit 1
fi
info "Done. Open a new terminal (or run 'source ~/.bashrc') and run xtcscope."

#!/bin/bash
# Installs xtcscope on your desktop and on the compute nodes of the robox cluster.
#
# Each target home gets an xtcscope/ directory with the xtcscope script, the
# xtcscope-agent binary and a VERSION file. Shell startup files are never
# modified: run the script by its full path, ~/xtcscope/xtcscope, or define an
# alias yourself.
#
# For testing, XTCSCOPE_RELEASE_BASE overrides the URL the release files are
# downloaded from (e.g. file:///tmp/fake-release).

set -euo pipefail

# Filled in by the release workflow.
XTCSCOPE_VERSION="v__VERSION__"
XTCSCOPE_REPO="__REPO__"

# USER is not set in every shell (e.g. some non-login sessions).
USER_NAME="${USER:-$(id -un)}"

# Home directories to install into: this machine's, then the cluster's.
TARGET_HOMES=(
    "${HOME}"
    "/storage/brno14-ceitec/home/${USER_NAME}"
)

# Print an informational line.
info() {
    echo "INFO    [xtcscope robox installer] $*"
}

# Print a warning line.
warn() {
    echo "WARN    [xtcscope robox installer] $*"
}

# Print an error line and exit 1.
die() {
    echo "ERROR   [xtcscope robox installer] $*" >&2
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
    # The same directory can appear twice, e.g. when run on the cluster itself.
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

if ! command -v uv >/dev/null 2>&1; then
    warn "uv was not found on this machine; the xtcscope script needs it: https://docs.astral.sh/uv"
fi

if [[ ${#FAILED_HOMES[@]} -gt 0 ]]; then
    exit 1
fi
info "Done. Run ${HOME}/xtcscope/xtcscope to start."

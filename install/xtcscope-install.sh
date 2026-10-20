#!/bin/bash
# Installs xtcscope from a release tarball into <target_home>/xtcscope.
#
# Usage: xtcscope-install.sh <target_home> <release_url>
#
# The release tarball contains a single directory, xtcscope/, holding the
# xtcscope script, the xtcscope-agent binary and a VERSION file. An existing
# installation with the same VERSION is left alone; an older or newer one is
# replaced. A directory at <target_home>/xtcscope that is not an xtcscope
# installation (for example a git checkout) is never touched.
#
# Shell startup files (.bashrc, .profile, ...) are never modified.

set -euo pipefail

# Print an informational line.
info() {
    echo "INFO    [xtcscope installer] $*"
}

# Print an error line and exit 1.
die() {
    echo "ERROR   [xtcscope installer] $*" >&2
    exit 1
}

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <target_home> <release_url>" >&2
    exit 1
fi

TARGET_HOME="$1"
RELEASE_URL="$2"
INSTALL_DIR="${TARGET_HOME}/xtcscope"

[[ -d "$TARGET_HOME" ]] || die "Target home directory '${TARGET_HOME}' does not exist."

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

info "Downloading ${RELEASE_URL} ..."
curl -fsSL -o "${TMP_DIR}/release.tar.gz" "$RELEASE_URL" \
    || die "Could not download ${RELEASE_URL}."
tar -xzf "${TMP_DIR}/release.tar.gz" -C "$TMP_DIR" \
    || die "Could not extract the release tarball."

SOURCE_DIR="${TMP_DIR}/xtcscope"
for file in VERSION xtcscope xtcscope-agent; do
    [[ -f "${SOURCE_DIR}/${file}" ]] || die "The release tarball has no xtcscope/${file}."
done
NEW_VERSION="$(cat "${SOURCE_DIR}/VERSION")"

if [[ -e "$INSTALL_DIR" ]]; then
    # Only replace something that looks like an xtcscope installation.
    if [[ ! -f "${INSTALL_DIR}/VERSION" || ! -f "${INSTALL_DIR}/xtcscope-agent" ]]; then
        die "'${INSTALL_DIR}' exists but is not an xtcscope installation; move it away and run the installer again."
    fi
    OLD_VERSION="$(cat "${INSTALL_DIR}/VERSION")"
    if [[ "$OLD_VERSION" == "$NEW_VERSION" ]]; then
        info "[${TARGET_HOME}] xtcscope ${NEW_VERSION} is up to date."
        exit 0
    fi
    info "[${TARGET_HOME}] Replacing xtcscope ${OLD_VERSION} with ${NEW_VERSION} ..."
else
    info "[${TARGET_HOME}] Installing xtcscope ${NEW_VERSION} ..."
fi

# Copy next to the target first, so a failed copy never leaves a half-installed directory.
STAGING_DIR="${INSTALL_DIR}.new.$$"
rm -rf "$STAGING_DIR"
cp -r "$SOURCE_DIR" "$STAGING_DIR"
chmod 755 "${STAGING_DIR}/xtcscope" "${STAGING_DIR}/xtcscope-agent"
rm -rf "$INSTALL_DIR"
mv "$STAGING_DIR" "$INSTALL_DIR"

info "[${TARGET_HOME}] Installed xtcscope ${NEW_VERSION} into ${INSTALL_DIR}."

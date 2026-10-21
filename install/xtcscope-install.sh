#!/bin/bash
# Installs xtcscope from a release tarball into <target_home>/xtcscope
# and adds that directory to PATH in <target_home>/.bashrc.
#
# Usage: xtcscope-install.sh <target_home> <release_url>
#
# The release tarball contains a single directory, xtcscope/, holding the
# xtcscope executable with its _internal/ runtime (a PyInstaller bundle), the
# xtcscope-agent binary and a VERSION file. An existing
# installation with the same VERSION is left alone; an older or newer one is
# replaced. A directory at <target_home>/xtcscope that is not an xtcscope
# installation (for example a git checkout) is never touched.
#
# The PATH entry lives in a block delimited by "managed by xtcscope" markers.
# The block is added once, replaced in place when its content changes, and
# left alone otherwise, so running the installer again changes nothing.

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

# -------------------
# Usage & parameters
# -------------------
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <target_home> <release_url>" >&2
    exit 1
fi

TARGET_HOME="$1"
RELEASE_URL="$2"
INSTALL_DIR="${TARGET_HOME}/xtcscope"
BASHRC="${TARGET_HOME}/.bashrc"

[[ -d "$TARGET_HOME" ]] || die "Target home directory '${TARGET_HOME}' does not exist."

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# -------------------
# Download & extract
# -------------------
info "Downloading ${RELEASE_URL} ..."
curl -fsSL -o "${TMP_DIR}/release.tar.gz" "$RELEASE_URL" \
    || die "Could not download ${RELEASE_URL}."
tar -xzf "${TMP_DIR}/release.tar.gz" -C "$TMP_DIR" \
    || die "Could not extract the release tarball."

SOURCE_DIR="${TMP_DIR}/xtcscope"
for file in VERSION xtcscope xtcscope-agent; do
    [[ -f "${SOURCE_DIR}/${file}" ]] || die "The release tarball has no xtcscope/${file}."
done
[[ -d "${SOURCE_DIR}/_internal" ]] || die "The release tarball has no xtcscope/_internal/."
NEW_VERSION="$(cat "${SOURCE_DIR}/VERSION")"

# --------------------------------
# Install xtcscope into target home
# --------------------------------

# Copy the release into INSTALL_DIR. The copy goes next to the target first,
# so a failed copy never leaves a half-installed directory.
install_release() {
    local staging_dir="${INSTALL_DIR}.new.$$"
    rm -rf "$staging_dir"
    cp -r "$SOURCE_DIR" "$staging_dir"
    chmod 755 "${staging_dir}/xtcscope" "${staging_dir}/xtcscope-agent"
    rm -rf "$INSTALL_DIR"
    mv "$staging_dir" "$INSTALL_DIR"
}

if [[ -e "$INSTALL_DIR" ]]; then
    # Only replace something that looks like an xtcscope installation.
    if [[ ! -f "${INSTALL_DIR}/VERSION" || ! -f "${INSTALL_DIR}/xtcscope-agent" ]]; then
        die "'${INSTALL_DIR}' exists but is not an xtcscope installation; move it away and run the installer again."
    fi
    OLD_VERSION="$(cat "${INSTALL_DIR}/VERSION")"
    if [[ "$OLD_VERSION" == "$NEW_VERSION" ]]; then
        info "[${TARGET_HOME}] xtcscope ${NEW_VERSION} is up to date."
    else
        info "[${TARGET_HOME}] Replacing xtcscope ${OLD_VERSION} with ${NEW_VERSION} ..."
        install_release
        info "[${TARGET_HOME}] Installed xtcscope ${NEW_VERSION} into ${INSTALL_DIR}."
    fi
else
    info "[${TARGET_HOME}] Installing xtcscope ${NEW_VERSION} ..."
    install_release
    info "[${TARGET_HOME}] Installed xtcscope ${NEW_VERSION} into ${INSTALL_DIR}."
fi

# -----------------------------
# Update .bashrc in target home
# -----------------------------
BLOCK_START_RE="^# >>> This block is managed by xtcscope"
BLOCK_END_RE="^# <<< This block is managed by xtcscope"

# Print the PATH block for this version and installation directory.
generate_xtcscope_block() {
    cat <<EOF
# >>> This block is managed by xtcscope (v${NEW_VERSION}) >>>
# This makes xtcscope available for you on any computer using this directory as its HOME.
if [[ ":\$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    export PATH="\$PATH:${INSTALL_DIR}"
fi
# <<< This block is managed by xtcscope (v${NEW_VERSION}) <<<
EOF
}

# Print the xtcscope block currently in the file, or nothing.
current_xtcscope_block() {
    awk -v start_re="$BLOCK_START_RE" -v end_re="$BLOCK_END_RE" '
        $0 ~ start_re { in_block = 1 }
        in_block { print }
        $0 ~ end_re { in_block = 0 }
    ' "$1"
}

# Add the xtcscope block to the file, or replace an outdated one in place.
update_bashrc_block() {
    local file="$1"
    local new_block="${TMP_DIR}/block"
    generate_xtcscope_block > "$new_block"

    if ! grep -qE "$BLOCK_START_RE" "$file"; then
        info "[${TARGET_HOME}] Adding xtcscope to PATH in ${file}."
        { echo ""; cat "$new_block"; } >> "$file"
        return
    fi

    if [[ "$(current_xtcscope_block "$file")" == "$(cat "$new_block")" ]]; then
        info "[${TARGET_HOME}] xtcscope is already in PATH in ${file}."
        return
    fi

    info "[${TARGET_HOME}] Updating the xtcscope block in ${file}."
    awk -v start_re="$BLOCK_START_RE" -v end_re="$BLOCK_END_RE" -v block="$new_block" '
        $0 ~ start_re {
            in_block = 1
            if (!done) {
                while ((getline line < block) > 0) print line
                done = 1
            }
        }
        !in_block { print }
        $0 ~ end_re { in_block = 0 }
    ' "$file" > "${TMP_DIR}/bashrc"
    # Write through the existing file, so a symlinked .bashrc stays a symlink.
    cat "${TMP_DIR}/bashrc" > "$file"
}

touch "$BASHRC"
update_bashrc_block "$BASHRC"

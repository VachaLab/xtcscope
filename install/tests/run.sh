#!/bin/bash
# Tests for the installers, against fake releases on the local disk.
#
# Usage: install/tests/run.sh
# Needs bash, curl (for file:// URLs) and tar. Exits 1 on the first failure.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASSED=0

# Report a failed check and stop.
fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# Report a passed test.
pass() {
    PASSED=$((PASSED + 1))
    echo "ok   $*"
}

# Build a fake release of version $1 in directory $2: tarball plus installer.
make_release() {
    local version="$1" dir="$2"
    mkdir -p "${dir}/src/xtcscope"
    printf '#!/bin/sh\necho "xtcscope %s"\n' "$version" > "${dir}/src/xtcscope/xtcscope"
    printf '#!/bin/sh\necho "xtcscope-agent %s"\n' "$version" > "${dir}/src/xtcscope/xtcscope-agent"
    echo "$version" > "${dir}/src/xtcscope/VERSION"
    chmod 644 "${dir}/src/xtcscope/xtcscope" "${dir}/src/xtcscope/xtcscope-agent"
    tar -C "${dir}/src" -czf "${dir}/xtcscope-release.tar.gz" xtcscope
    cp "${INSTALL_DIR}/xtcscope-install.sh" "${dir}/"
}

# A fresh, empty home directory with a .bashrc to watch.
new_home() {
    local home
    home="$(mktemp -d "${WORK}/home.XXXXXX")"
    echo "# my bashrc" > "${home}/.bashrc"
    echo "$home"
}

GENERIC="${INSTALL_DIR}/xtcscope-install.sh"
ROBOX="${INSTALL_DIR}/xtcscope-robox-install.sh"
make_release "0.1.0" "${WORK}/r1"
make_release "0.2.0" "${WORK}/r2"

# --- generic installer -------------------------------------------------------

HOME_A="$(new_home)"
"$GENERIC" "$HOME_A" "file://${WORK}/r1/xtcscope-release.tar.gz" > "${WORK}/out" \
    || fail "fresh install exited non-zero"
[[ "$(cat "${HOME_A}/xtcscope/VERSION")" == "0.1.0" ]] || fail "VERSION not installed"
[[ -x "${HOME_A}/xtcscope/xtcscope" && -x "${HOME_A}/xtcscope/xtcscope-agent" ]] \
    || fail "executables are not executable"
[[ "$("${HOME_A}/xtcscope/xtcscope-agent")" == "xtcscope-agent 0.1.0" ]] || fail "agent not runnable"
grep -q "^# my bashrc$" "${HOME_A}/.bashrc" || fail ".bashrc lost its content"
[[ "$(grep -c "managed by xtcscope" "${HOME_A}/.bashrc")" == 2 ]] || fail "PATH block not added"
grep -qF "export PATH=\"\$PATH:${HOME_A}/xtcscope\"" "${HOME_A}/.bashrc" || fail "PATH block has the wrong directory"
[[ ! -e "${HOME_A}/.profile" && ! -e "${HOME_A}/.bash_profile" ]] || fail "a profile file was created"
pass "fresh install, executables set, PATH block added, no profile files created"

touch -d '2001-01-01' "${HOME_A}/xtcscope/xtcscope-agent"
cp "${HOME_A}/.bashrc" "${WORK}/bashrc.before"
"$GENERIC" "$HOME_A" "file://${WORK}/r1/xtcscope-release.tar.gz" > "${WORK}/out" \
    || fail "re-install exited non-zero"
grep -q "up to date" "${WORK}/out" || fail "re-install did not report 'up to date'"
[[ "$(stat -c %Y "${HOME_A}/xtcscope/xtcscope-agent")" == "$(date -d '2001-01-01' +%s)" ]] \
    || fail "re-install replaced files"
cmp -s "${WORK}/bashrc.before" "${HOME_A}/.bashrc" || fail "re-install changed .bashrc"
pass "same version is left alone, .bashrc unchanged"

"$GENERIC" "$HOME_A" "file://${WORK}/r2/xtcscope-release.tar.gz" > "${WORK}/out" \
    || fail "upgrade exited non-zero"
[[ "$(cat "${HOME_A}/xtcscope/VERSION")" == "0.2.0" ]] || fail "upgrade did not replace VERSION"
grep -q "Replacing xtcscope 0.1.0 with 0.2.0" "${WORK}/out" || fail "upgrade message missing"
[[ -z "$(find "$HOME_A" -maxdepth 1 -name 'xtcscope.new.*')" ]] || fail "staging directory left behind"
[[ "$(grep -c "managed by xtcscope (v0.2.0)" "${HOME_A}/.bashrc")" == 2 ]] || fail "PATH block not updated"
[[ "$(grep -c "managed by xtcscope" "${HOME_A}/.bashrc")" == 2 ]] || fail "old PATH block left behind"
pass "a different version replaces the installation and its PATH block"

HOME_B="$(new_home)"
mkdir -p "${HOME_B}/xtcscope/.git"
echo "precious" > "${HOME_B}/xtcscope/README.md"
if "$GENERIC" "$HOME_B" "file://${WORK}/r1/xtcscope-release.tar.gz" > "${WORK}/out" 2>&1; then
    fail "installer overwrote a directory that is not an installation"
fi
[[ "$(cat "${HOME_B}/xtcscope/README.md")" == "precious" ]] || fail "foreign directory was modified"
[[ "$(cat "${HOME_B}/.bashrc")" == "# my bashrc" ]] || fail ".bashrc modified although the installation was refused"
grep -q "is not an xtcscope installation" "${WORK}/out" || fail "refusal message missing"
pass "a foreign ~/xtcscope (e.g. a git checkout) is refused and untouched"

if "$GENERIC" "${WORK}/no-such-home" "file://${WORK}/r1/xtcscope-release.tar.gz" > /dev/null 2>&1; then
    fail "missing target home did not fail"
fi
if "$GENERIC" "$HOME_A" "file://${WORK}/no-such.tar.gz" > /dev/null 2>&1; then
    fail "missing tarball did not fail"
fi
[[ "$(cat "${HOME_A}/xtcscope/VERSION")" == "0.2.0" ]] || fail "failed download changed the installation"
pass "missing home and failed download are errors and change nothing"

# --- robox wrapper ------------------------------------------------------------

HOME_C="$(new_home)"
if HOME="$HOME_C" "$ROBOX" > "${WORK}/out" 2>&1; then
    fail "unreleased wrapper ran without XTCSCOPE_RELEASE_BASE"
fi
grep -q "unreleased copy" "${WORK}/out" || fail "unreleased-copy message missing"
pass "unreleased wrapper refuses to guess a release URL"

HOME="$HOME_C" USER="nobody-$$" XTCSCOPE_RELEASE_BASE="file://${WORK}/r1" "$ROBOX" > "${WORK}/out" 2>&1 \
    || fail "wrapper exited non-zero: $(cat "${WORK}/out")"
[[ "$(cat "${HOME_C}/xtcscope/VERSION")" == "0.1.0" ]] || fail "wrapper did not install into HOME"
grep -q "Not installed (directory not found): /storage/brno14-ceitec/home/nobody-$$" "${WORK}/out" \
    || fail "missing cluster home not reported"
grep -q "Run ${HOME_C}/xtcscope/xtcscope to start." "${WORK}/out" || fail "final hint missing"
grep -q "managed by xtcscope" "${HOME_C}/.bashrc" || fail "wrapper did not add the PATH block"
pass "wrapper installs into HOME and reports the missing cluster home"

HOME="$HOME_C" USER="nobody-$$" XTCSCOPE_RELEASE_BASE="file://${WORK}/r1" "$ROBOX" > "${WORK}/out" 2>&1 \
    || fail "wrapper re-run exited non-zero"
grep -q "up to date" "${WORK}/out" || fail "wrapper re-run did not report 'up to date'"
pass "wrapper re-run reports up to date"

HOME_D="$(new_home)"
mkdir -p "${HOME_D}/xtcscope"
if HOME="$HOME_D" USER="nobody-$$" XTCSCOPE_RELEASE_BASE="file://${WORK}/r1" "$ROBOX" > "${WORK}/out" 2>&1; then
    fail "wrapper exited 0 although an installation failed"
fi
grep -q "Installation failed: ${HOME_D}" "${WORK}/out" || fail "failed home not reported"
pass "wrapper exits 1 and names the home when an installation fails"

echo "All ${PASSED} installer tests passed."

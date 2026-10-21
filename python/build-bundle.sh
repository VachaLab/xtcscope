#!/bin/bash
# Builds the PyInstaller bundle in dist/xtcscope/ and checks it.
#
# Usage: python/build-bundle.sh [expected_version]
#
# Run it from anywhere; it works in the python/ directory. CI and the release
# workflow run it in the quay.io/pypa/manylinux_2_28_x86_64 container, so the
# bundle runs on any Linux with glibc 2.28 or newer.
#
# Checks, in order:
#   1. No binary or library in the bundle needs a glibc newer than MAX_GLIBC
#      (default 2.28; set MAX_GLIBC=none to skip, e.g. for a local build).
#   2. `xtcscope --version` prints the expected version (default: the version
#      in src/xtcscope/__init__.py).
#   3. The frozen build imports qq: asking for a job on a machine without a
#      batch system must fail with exit 3, not with a missing module.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

MAX_GLIBC="${MAX_GLIBC:-2.28}"
SOURCE_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/xtcscope/__init__.py)"
EXPECTED_VERSION="${1:-$SOURCE_VERSION}"
BUNDLE="dist/xtcscope"

# print an informational line
info() {
    echo "INFO    [build-bundle] $*"
}

# print an error line and exit 1
die() {
    echo "ERROR   [build-bundle] $*" >&2
    exit 1
}

# a uv-managed Python (python-build-standalone) needs only an old glibc; a
# system Python, as on a recent Ubuntu, would raise the bundle's glibc floor
export UV_MANAGED_PYTHON=1

info "Installing Python and dependencies ..."
uv python install 3.13
uv sync --frozen --all-groups

info "Building ${BUNDLE} ..."
uv run pyinstaller --noconfirm --clean xtcscope.spec

if [[ "$MAX_GLIBC" != "none" ]]; then
    command -v objdump >/dev/null || die "objdump is needed for the glibc check (binutils)."
    found="$(find "$BUNDLE" -type f \( -name '*.so*' -o -perm -u+x \) -print0 |
        xargs -0 -r objdump -T 2>/dev/null |
        grep -F '*UND*' |
        grep -o 'GLIBC_[0-9.]*' | sed 's/GLIBC_//' | sort -uV | tail -1 || true)"
    info "Highest glibc requirement: ${found:-none}"
    highest="$(printf '%s\n%s\n' "$found" "$MAX_GLIBC" | sort -V | tail -1)"
    [[ "$highest" == "$MAX_GLIBC" ]] \
        || die "The bundle requires glibc ${found}, above the ${MAX_GLIBC} floor."
fi

version_output="$("${BUNDLE}/xtcscope" --version)"
[[ "$version_output" == "xtcscope ${EXPECTED_VERSION}" ]] \
    || die "--version printed '${version_output}', expected 'xtcscope ${EXPECTED_VERSION}'."
info "Version: ${version_output}"

set +e
job_output="$(env -u QQ_BATCH_SYSTEM PATH=/usr/bin:/bin "${BUNDLE}/xtcscope" 1 --viewer true 2>&1)"
job_status=$?
set -e
[[ $job_status -eq 3 && "$job_output" == *"Could not find job"* ]] \
    || die "Expected exit 3 asking for a job without a batch system, got ${job_status}: ${job_output}"
info "qq is importable in the frozen build."

info "Bundle ready in python/${BUNDLE} ($(du -sh "$BUNDLE" | cut -f1))."

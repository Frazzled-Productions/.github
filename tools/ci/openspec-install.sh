#!/usr/bin/env bash
#
# openspec-install.sh <dest-dir>: install the pinned OpenSpec release for this runner into <dest-dir>,
# after checking the tarball's SHA-256, and put <dest-dir> first on the job's PATH. Used by every shared
# OpenSpec workflow, on hosted Linux and on the Mac runners (ops #363). No sudo, and no fallback to
# another openspec: a silent fallback would let the version differ between runners.
#
# This is the only place that names the version. To move it, change the three pins below, taking the
# checksums from the release's SHA256SUMS. OPENSPEC_BASE_URL overrides the download URL, for tests.
# Tests: tools/ci/test-openspec-install.sh.

set -euo pipefail

version=1.16.0
sum_linux=f27fb2ff5c6c4aafb207cb0b797189215adb3a1150d4b4600a2d6a0b6e192ae1
sum_darwin=51e9298489a86718e32433ddffbb6d4a29ee9da992bf3bcfaa29a664ec7b4cc2

dest="${1:?usage: openspec-install.sh <dest-dir>}"
base="${OPENSPEC_BASE_URL:-https://github.com/Fission-AI/OpenSpec/releases/download}"

case "${RUNNER_OS:-}/${RUNNER_ARCH:-}" in
  Linux/X64) platform=linux-x64; sum="$sum_linux" ;;
  macOS/ARM64) platform=darwin-arm64; sum="$sum_darwin" ;;
  *)
    echo "::error::No pinned openspec binary for ${RUNNER_OS:-unknown OS} ${RUNNER_ARCH:-unknown architecture}; only Linux X64 and macOS ARM64 are pinned."
    exit 1
    ;;
esac

mkdir -p "$dest"
work="$(mktemp -d "${dest%/}/openspec-download.XXXXXX")"
trap 'rm -rf "$work"' EXIT
tarball="openspec-${platform}.tar.gz"
curl -sSfL "${base}/v${version}/${tarball}" -o "${work}/${tarball}" \
  || { echo "::error::The openspec ${version} download failed: ${base}/v${version}/${tarball}"; exit 1; }
(cd "$work" && echo "${sum}  ${tarball}" | shasum -a 256 -c -)
tar -xzf "${work}/${tarball}" -C "$work" openspec
mv "${work}/openspec" "${dest%/}/openspec"
"${dest%/}/openspec" --version
echo "${dest%/}" >> "${GITHUB_PATH:?GITHUB_PATH is not set}"

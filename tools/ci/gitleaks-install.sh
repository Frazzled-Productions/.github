#!/usr/bin/env bash
#
# gitleaks-install.sh <version> <sha256-linux-x64> <sha256-darwin-arm64> <dest-dir>: install the pinned
# gitleaks release for this runner into <dest-dir>, after checking the tarball's SHA-256. Used by
# secret-scan.yml (ops #345), so one shared scan runs on hosted Linux and on the light runners on the
# Mac. No sudo: <dest-dir> is the job's temp folder.
#
# The platform comes from RUNNER_OS and RUNNER_ARCH: Linux X64 takes linux_x64, macOS ARM64 takes
# darwin_arm64, anything else fails naming it (there is no pinned checksum for it). GITLEAKS_BASE_URL
# overrides the release download URL, for tests. Tests: tools/ci/test-gitleaks-install.sh.

set -euo pipefail

version="${1:?usage: gitleaks-install.sh <version> <sha256-linux-x64> <sha256-darwin-arm64> <dest-dir>}"
sum_linux="${2:?missing the linux_x64 checksum}"
sum_darwin="${3:?missing the darwin_arm64 checksum}"
dest="${4:?missing the destination folder}"
base="${GITLEAKS_BASE_URL:-https://github.com/gitleaks/gitleaks/releases/download}"

case "${RUNNER_OS:-}/${RUNNER_ARCH:-}" in
  Linux/X64) platform=linux_x64; sum="$sum_linux" ;;
  macOS/ARM64) platform=darwin_arm64; sum="$sum_darwin" ;;
  *)
    echo "::error::No pinned gitleaks binary for ${RUNNER_OS:-unknown OS} ${RUNNER_ARCH:-unknown architecture}; only Linux X64 and macOS ARM64 are pinned."
    exit 1
    ;;
esac

work="$(mktemp -d "${dest%/}/gitleaks-download.XXXXXX")"
trap 'rm -rf "$work"' EXIT
tarball="gitleaks_${version}_${platform}.tar.gz"
curl -sSfL "${base}/v${version}/${tarball}" -o "${work}/${tarball}"
(cd "$work" && echo "${sum}  ${tarball}" | shasum -a 256 -c -)
tar -xzf "${work}/${tarball}" -C "$work" gitleaks
mv "${work}/gitleaks" "${dest%/}/gitleaks"
"${dest%/}/gitleaks" version

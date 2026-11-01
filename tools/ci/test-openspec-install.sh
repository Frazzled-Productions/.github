#!/usr/bin/env bash
# test-openspec-install.sh: the shared workflows install the pinned OpenSpec binary for the runner, check
# its checksum first, need no sudo, and never fall back to another openspec (ops #363).
#
# Serves fixture tarballs from a file:// URL, so no network is used. The script's pinned version and
# checksums are swapped for the fixture's in a temporary copy.
#
#   tools/ci/test-openspec-install.sh
#   OPENSPEC_INSTALL=/path/to/copy.sh <this>

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${OPENSPEC_INSTALL:-$HERE/openspec-install.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/openspecinstall.XXXXXX")"
trap 'rm -rf "$T"' EXIT
V=9.9.9
mkdir -p "$T/releases/v$V" "$T/empty"
sum() { shasum -a 256 "$1" | awk '{ print $1 }'; }
for plat in linux-x64 darwin-arm64; do
  mkdir -p "$T/build-$plat"
  printf '#!/bin/sh\necho "fake openspec %s"\n' "$plat" > "$T/build-$plat/openspec"
  chmod +x "$T/build-$plat/openspec"
  tar -czf "$T/releases/v$V/openspec-$plat.tar.gz" -C "$T/build-$plat" openspec
done
LINUX_SUM=$(sum "$T/releases/v$V/openspec-linux-x64.tar.gz")
DARWIN_SUM=$(sum "$T/releases/v$V/openspec-darwin-arm64.tar.gz")

# pin <file> <version> <linux-sum> <darwin-sum>: a copy of the script with these pins.
pin() {
  [ -f "$SCRIPT" ] || return 1
  sed -e "s/^version=.*/version=$2/" -e "s/^sum_linux=.*/sum_linux=$3/" -e "s/^sum_darwin=.*/sum_darwin=$4/" "$SCRIPT" > "$1"
}
pin "$T/good.sh" "$V" "$LINUX_SUM" "$DARWIN_SUM"
pin "$T/wrong.sh" "$V" "$DARWIN_SUM" "$DARWIN_SUM"

# run <script> <os> <arch> <base-url>: sets RC, OUT, DEST and GPATH.
run() {
  DEST="$(mktemp -d "$T/dest.XXXXXX")"
  GPATH="$T/github-path.$RANDOM"
  : > "$GPATH"
  OUT=$(RUNNER_OS="$2" RUNNER_ARCH="$3" OPENSPEC_BASE_URL="$4" GITHUB_PATH="$GPATH" bash "$1" "$DEST/bin" 2>&1)
  RC=$?
}

echo "openspec-install.sh against: $SCRIPT"
run "$T/good.sh" Linux X64 "file://$T/releases"
if [ "$RC" -eq 0 ] && [ "$("$DEST/bin/openspec")" = "fake openspec linux-x64" ]; then
  ok "Linux X64 installs linux-x64 after checking its checksum"
else bad "Linux X64: rc $RC: $OUT"; fi
if [ "$(cat "$GPATH")" = "$DEST/bin" ]; then ok "the install folder goes on the job's PATH"
else bad "GITHUB_PATH holds: $(cat "$GPATH")"; fi
if [ "$(ls -A "$DEST/bin")" = "openspec" ]; then ok "only the binary is left behind"
else bad "left behind: $(ls -A "$DEST/bin")"; fi
run "$T/good.sh" macOS ARM64 "file://$T/releases"
if [ "$RC" -eq 0 ] && [ "$("$DEST/bin/openspec")" = "fake openspec darwin-arm64" ]; then
  ok "macOS ARM64 installs darwin-arm64 after checking its own checksum"
else bad "macOS ARM64: rc $RC: $OUT"; fi
run "$T/good.sh" Linux ARM64 "file://$T/releases"
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "Linux ARM64" && [ ! -e "$DEST/bin/openspec" ]; then
  ok "Linux ARM64 fails naming the platform"
else bad "Linux ARM64: rc $RC: $OUT"; fi
run "$T/wrong.sh" Linux X64 "file://$T/releases"
if [ "$RC" -ne 0 ] && [ ! -e "$DEST/bin/openspec" ]; then ok "a wrong checksum fails and installs nothing"
else bad "wrong checksum: rc $RC: $OUT"; fi
run "$T/good.sh" Linux X64 "file://$T/empty"
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "download" && [ ! -e "$DEST/bin/openspec" ] && [ ! -s "$GPATH" ]; then
  ok "a failed download names it, installs nothing and leaves PATH alone"
else bad "failed download: rc $RC: $OUT"; fi
if grep -vE '^[[:space:]]*#' "$SCRIPT" | grep -qw sudo; then bad "the installer uses sudo"; else ok "no sudo"; fi
if grep -vE '^[[:space:]]*#' "$SCRIPT" | grep -qE 'brew|command -v'; then bad "the installer looks for another openspec"
else ok "no fallback to another openspec"; fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"

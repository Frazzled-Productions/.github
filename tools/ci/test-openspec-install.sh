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
  printf '#!/bin/sh\n: > "%s/ran-unverified"\necho "fake openspec %s"\n' "$T" "$plat" > "$T/build-$plat/openspec"
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

# A tar that records it ran, and a decoy openspec the installer must never use.
mkdir -p "$T/stubs"
printf '#!/bin/sh\n: > "%s/tar-ran"\nexec "%s" "$@"\n' "$T" "$(command -v tar)" > "$T/stubs/tar"
printf '#!/bin/sh\n: > "%s/decoy-ran"\necho 0.0.0\n' "$T" > "$T/stubs/openspec"
chmod +x "$T/stubs/tar" "$T/stubs/openspec"

# run <script> <os> <arch> <base-url>: sets RC, OUT, DEST and GPATH.
run() {
  DEST="$(mktemp -d "$T/dest.XXXXXX")"
  GPATH="$T/github-path.$RANDOM"
  : > "$GPATH"
  OUT=$(RUNNER_OS="$2" RUNNER_ARCH="$3" OPENSPEC_BASE_URL="$4" GITHUB_PATH="$GPATH" \
    PATH="$T/stubs:$PATH" bash "$1" "$DEST/bin" 2>&1)
  RC=$?
}

echo "openspec-install.sh against: $SCRIPT"
run "$T/good.sh" Linux X64 "file://$T/releases"
if [ "$RC" -eq 0 ] && [ "$("$DEST/bin/openspec")" = "fake openspec linux-x64" ]; then
  ok "Linux X64 installs linux-x64 after checking its checksum"
else bad "Linux X64: rc $RC: $OUT"; fi
if [ "$(cat "$GPATH")" = "$DEST/bin" ]; then ok "the install folder goes on the job's PATH"
else bad "GITHUB_PATH holds: $(cat "$GPATH")"; fi
if [ "$(find "$DEST/bin" -mindepth 1 -maxdepth 1 -exec basename {} \; | sort | tr '\n' ' ')" = "openspec openspec-binary " ]; then ok "only the wrapper and binary are left behind"
else bad "left behind: $(ls -A "$DEST/bin")"; fi
mkdir -p "$T/pr"; printf 'preload = ["./p.js"]\n' > "$T/pr/bunfig.toml"
rm -f "$T/ran-unverified"
if (cd "$T/pr" && "$DEST/bin/openspec" validate >"$T/refused" 2>&1); then bad "ran with a bunfig.toml present"
elif [ -e "$T/ran-unverified" ]; then bad "the binary started with a bunfig.toml present"
elif grep -q "bunfig.toml" "$T/refused"; then ok "a bunfig.toml in the working folder is refused before the binary starts"
else bad "refusal did not name bunfig.toml: $(cat "$T/refused")"; fi
ln -s nowhere "$T/pr/link"; rm "$T/pr/bunfig.toml"; mv "$T/pr/link" "$T/pr/bunfig.toml"
if (cd "$T/pr" && "$DEST/bin/openspec" validate >/dev/null 2>&1); then bad "ran with a dangling bunfig.toml link"
else ok "a dangling bunfig.toml link is refused"; fi
if (cd "$T/empty" && [ "$("$DEST/bin/openspec" x)" = "fake openspec linux-x64" ]); then ok "with no bunfig.toml the wrapper runs the binary"
else bad "the wrapper did not run the binary"; fi
run "$T/good.sh" macOS ARM64 "file://$T/releases"
if [ "$RC" -eq 0 ] && [ "$("$DEST/bin/openspec")" = "fake openspec darwin-arm64" ]; then
  ok "macOS ARM64 installs darwin-arm64 after checking its own checksum"
else bad "macOS ARM64: rc $RC: $OUT"; fi
run "$T/good.sh" Linux ARM64 "file://$T/releases"
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "Linux ARM64" && [ ! -e "$DEST/bin/openspec" ]; then
  ok "Linux ARM64 fails naming the platform"
else bad "Linux ARM64: rc $RC: $OUT"; fi
for row in "macOS:X64" ":"; do
  os="${row%:*}"; arch="${row#*:}"
  run "$T/good.sh" "$os" "$arch" "file://$T/releases"
  if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "No pinned openspec" && [ ! -e "$DEST/bin/openspec" ]; then
    ok "platform '${os:-unset}' fails with no install"
  else bad "platform '${os:-unset}': rc $RC: $OUT"; fi
done
rm -f "$T/tar-ran" "$T/ran-unverified"
run "$T/wrong.sh" Linux X64 "file://$T/releases"
if [ "$RC" -ne 0 ] && [ ! -e "$DEST/bin/openspec" ] && printf '%s' "$OUT" | grep -q "::error::"; then
  ok "a wrong checksum fails with an error line and installs nothing"
else bad "wrong checksum: rc $RC: $OUT"; fi
if [ ! -e "$T/tar-ran" ] && [ ! -e "$T/ran-unverified" ]; then ok "a wrong checksum stops before unpacking or running anything"
else bad "unpacked or ran before the checksum check"; fi
rm -f "$T/decoy-ran"
run "$T/good.sh" Linux X64 "file://$T/empty"
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "download" && [ ! -e "$DEST/bin/openspec" ] && [ ! -s "$GPATH" ]; then
  ok "a failed download names it, installs nothing and leaves PATH alone"
else bad "failed download: rc $RC: $OUT"; fi
if [ ! -e "$T/decoy-ran" ]; then ok "a failed download never touches another openspec on PATH"
else bad "the installer ran the decoy openspec"; fi
if grep -vE '^[[:space:]]*#' "$SCRIPT" | grep -qw sudo; then bad "the installer uses sudo"; else ok "no sudo"; fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"

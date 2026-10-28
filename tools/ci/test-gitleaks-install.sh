#!/usr/bin/env bash
# test-gitleaks-install.sh: the secret scan installs the pinned gitleaks for the runner's OS and
# architecture, checks its checksum, needs no sudo, and scans HEAD's history only (ops #345, D2 and
# task 1.8).
#
# Part 1 serves fixture release tarballs from a file:// URL, so no network is used. Part 2 runs only
# when a real `gitleaks` is on PATH (the self-test installs one through the script first): a fixture
# repository whose fake token exists only on refs/remotes/pull/1/merge must pass the HEAD-only scan
# and fail a scan of every ref. The token is generated at run time, so this file holds none.
#
#   tools/ci/test-gitleaks-install.sh
#   GITLEAKS_INSTALL=/path/to/copy.sh <this>

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${GITLEAKS_INSTALL:-$HERE/gitleaks-install.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/gitleaksinstall.XXXXXX")"
trap 'rm -rf "$T"' EXIT
V=9.9.9
mkdir -p "$T/releases/v$V"
sum() { shasum -a 256 "$1" | awk '{ print $1 }'; }
for plat in linux_x64 darwin_arm64; do
  mkdir -p "$T/build-$plat"
  printf '#!/bin/sh\necho "fake gitleaks %s"\n' "$plat" > "$T/build-$plat/gitleaks"
  chmod +x "$T/build-$plat/gitleaks"
  tar -czf "$T/releases/v$V/gitleaks_${V}_${plat}.tar.gz" -C "$T/build-$plat" gitleaks
done
LINUX_SUM=$(sum "$T/releases/v$V/gitleaks_${V}_linux_x64.tar.gz")
DARWIN_SUM=$(sum "$T/releases/v$V/gitleaks_${V}_darwin_arm64.tar.gz")

# install <os> <arch> <linux-sum> <darwin-sum>: sets RC, OUT and DEST.
install() {
  DEST="$(mktemp -d "$T/dest.XXXXXX")"
  OUT=$(RUNNER_OS="$1" RUNNER_ARCH="$2" GITLEAKS_BASE_URL="file://$T/releases" \
    bash "$SCRIPT" "$V" "$3" "$4" "$DEST" 2>&1)
  RC=$?
}

echo "gitleaks-install.sh against: $SCRIPT"
install Linux X64 "$LINUX_SUM" "$DARWIN_SUM"
if [ "$RC" -eq 0 ] && [ "$("$DEST/gitleaks")" = "fake gitleaks linux_x64" ]; then
  ok "Linux X64 installs linux_x64 after checking its checksum"
else bad "Linux X64: rc $RC: $OUT"; fi
install macOS ARM64 "$LINUX_SUM" "$DARWIN_SUM"
if [ "$RC" -eq 0 ] && [ "$("$DEST/gitleaks")" = "fake gitleaks darwin_arm64" ]; then
  ok "macOS ARM64 installs darwin_arm64 after checking its own checksum"
else bad "macOS ARM64: rc $RC: $OUT"; fi
install Linux ARM64 "$LINUX_SUM" "$DARWIN_SUM"
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q "Linux ARM64" && [ ! -e "$DEST/gitleaks" ]; then
  ok "Linux ARM64 fails naming the platform"
else bad "Linux ARM64: rc $RC: $OUT"; fi
install macOS ARM64 "$LINUX_SUM" "$LINUX_SUM"
if [ "$RC" -ne 0 ] && [ ! -e "$DEST/gitleaks" ]; then ok "a wrong checksum fails and installs nothing"
else bad "wrong checksum: rc $RC: $OUT"; fi
if grep -vE '^[[:space:]]*#' "$SCRIPT" | grep -qw sudo; then bad "the installer uses sudo"; else ok "no sudo"; fi

if command -v gitleaks >/dev/null 2>&1; then
  R="$T/repo"
  git init -q -b main "$R"
  git -C "$R" config user.email test@example.com; git -C "$R" config user.name Test
  echo clean > "$R/README"; git -C "$R" add .; git -C "$R" commit -q -m clean
  git -C "$R" checkout -q -b stale
  token="gh""p_$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 36)"
  printf 'token = "%s"\n' "$token" > "$R/config.txt"
  git -C "$R" add .; git -C "$R" commit -q -m "stale PR merge"
  git -C "$R" update-ref refs/remotes/pull/1/merge HEAD
  git -C "$R" checkout -q main; git -C "$R" branch -q -D stale
  if (cd "$R" && gitleaks git . --redact --log-opts="HEAD" >/dev/null 2>&1); then
    ok "HEAD-only scan ignores a secret on a stale refs/remotes/pull/1/merge"
  else bad "HEAD-only scan reported the stale ref's secret"; fi
  if (cd "$R" && gitleaks git . --redact --log-opts="--all" >/dev/null 2>&1); then
    bad "a scan of every ref missed the fixture secret (fixture not detected)"
  else ok "a scan of every ref finds it (the fixture is a real detection)"; fi
else
  echo "  (no gitleaks on PATH: HEAD-only scan check skipped)"
fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"

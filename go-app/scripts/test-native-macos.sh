#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
work="$(mktemp -d "${TMPDIR:-/tmp}/fte-native-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
clang -mmacosx-version-min=13.0 -framework Cocoa scripts/test-native-macos.m -o "$work/test-native"
"$work/test-native"

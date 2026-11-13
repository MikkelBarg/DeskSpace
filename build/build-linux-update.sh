#!/usr/bin/env bash
# Builds dist/deskspace-linux-<version>.tar.gz: what DeskSpace's own updater installs on Linux.
#
# Attach it to the GitHub release (next to the Windows setup and the .deb). A copy installed with
# build/install-linux.sh finds it there, checks it against GitHub's SHA-256 and installs it by itself.
# It holds the app and the scripts and library list it needs, inside a deskspace-<version>/ folder.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)".*/\1/p' "$ROOT/fences/common.py")"
NAME="deskspace-${VERSION}"
STAGE="$ROOT/dist/linux-update/$NAME"
OUTPUT="$ROOT/dist/deskspace-linux-${VERSION}.tar.gz"

rm -rf "$ROOT/dist/linux-update" "$OUTPUT"
mkdir -p "$STAGE/build"
cp "$ROOT/deskspace.pyw" "$STAGE/"
cp -r "$ROOT/fences" "$STAGE/"
cp "$ROOT/build/requirements-linux.txt" "$ROOT/build/install-linux.sh" "$STAGE/build/"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
tar -czf "$OUTPUT" --owner=0 --group=0 --sort=name -C "$ROOT/dist/linux-update" "$NAME"
echo "Built $OUTPUT ($(du -h "$OUTPUT" | cut -f1)), SHA-256 $(sha256sum "$OUTPUT" | cut -d' ' -f1)"

#!/bin/sh
# Builds the program's own Tailscale, tailscale and tailscaled, from the open
# source: a fixed stable version, built with Go, for the system this runs on
# or the one named. What it builds for this system lands in dist/tailscale/,
# where the packaging picks it up (deploy/exe-ai-terminal.spec).
#
#     deploy/build_tailscale.sh [darwin|windows] [arm64|amd64]
#
# The licence text of the version built is copied beside the programs; the
# same text stands in THIRD_PARTY_NOTICES.md.

set -eu

# The one version, here and nowhere else. A newer one is a decision taken
# together with a test against it, never a side effect of building.
VERSION="1.104.1"

OS="${1:-$(go env GOOS)}"
ARCH="${2:-$(go env GOARCH)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The system this runs on builds into dist/tailscale, where the packaging picks
# it up; another system's build is built for a machine that packages it, and
# lands beside it.
OUT="$ROOT/dist/tailscale"
HOST_BUILD=1
{ [ "$OS" = "$(go env GOHOSTOS)" ] && [ "$ARCH" = "$(go env GOHOSTARCH)" ]; } || HOST_BUILD=0
[ "$HOST_BUILD" = 1 ] || OUT="$ROOT/dist/tailscale-$OS-$ARCH"
SUFFIX=""
[ "$OS" = "windows" ] && SUFFIX=".exe"

mkdir -p "$OUT"
# The version stamp is what a build from a checkout would carry; a module
# build has none, and the program would then call itself an error.
LDFLAGS="-X tailscale.com/version.longStamp=$VERSION -X tailscale.com/version.shortStamp=$VERSION"
PACKAGES="tailscale.com/cmd/tailscale@v$VERSION tailscale.com/cmd/tailscaled@v$VERSION"
if [ "$HOST_BUILD" = 1 ]; then
    BUILT="$OUT.tmp"
    GOOS="$OS" GOARCH="$ARCH" GOBIN="$BUILT" go install -trimpath -ldflags "$LDFLAGS" $PACKAGES
else
    # go install refuses a cross build into GOBIN: it lands in a folder of its
    # own below the bin folder of GOPATH, and is taken from there.
    GOOS="$OS" GOARCH="$ARCH" go install -trimpath -ldflags "$LDFLAGS" $PACKAGES
    BUILT="$(go env GOPATH)/bin/${OS}_${ARCH}"
fi
cp "$BUILT/tailscale$SUFFIX" "$BUILT/tailscaled$SUFFIX" "$OUT/"
chmod 755 "$OUT/tailscale$SUFFIX" "$OUT/tailscaled$SUFFIX"
# Only what was built is taken away: a folder below GOPATH may hold more.
if [ "$HOST_BUILD" = 1 ]; then
    rm -r "$BUILT"
else
    rm -f "$BUILT/tailscale$SUFFIX" "$BUILT/tailscaled$SUFFIX"
    rmdir "$BUILT" 2>/dev/null || true
fi

DIR="$(go list -m -f '{{.Dir}}' "tailscale.com@v$VERSION")"
cp -f "$DIR/LICENSE" "$OUT/LICENSE.tailscale.txt"
chmod 644 "$OUT/LICENSE.tailscale.txt"
echo "$VERSION" > "$OUT/VERSION"
echo "Built Tailscale $VERSION for $OS/$ARCH into $OUT"

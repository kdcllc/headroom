#!/bin/sh
# Stamp a build version into the app and debian/changelog (used by the release workflow).
#   scripts/set-version.sh 0.1.0+r12 "Merged PR #34: Add Brave flatpak paths"
set -eu
cd "$(dirname "$0")/.."
VERSION=${1:?usage: set-version.sh VERSION [MESSAGE]}
MESSAGE=$(printf '%s' "${2:-Automated release build.}" | tr '\n\r\t' '   ' | cut -c1-200)
case "$VERSION" in
    [0-9]*) ;;
    *) echo "version must start with a digit: $VERSION" >&2; exit 2 ;;
esac
case "$VERSION" in
    *[!0-9A-Za-z.+~-]*) echo "invalid Debian version: $VERSION" >&2; exit 2 ;;
esac
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" headroom/__init__.py
{
    printf 'headroom (%s) jammy; urgency=medium\n\n' "$VERSION"
    printf '  * %s\n\n' "$MESSAGE"
    printf ' -- kdcllc <info@kingdavidconsulting.com>  %s\n\n' "$(date -R)"
    cat debian/changelog
} > debian/changelog.new
mv debian/changelog.new debian/changelog
echo "version set to $VERSION"

#!/bin/sh
# Build the .deb with plain dpkg-deb (no debhelper needed). The canonical build is
# `make deb` (dpkg-buildpackage); this produces the same file layout as debian/install.
set -eu
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' headroom/__init__.py)
OUT=${1:-dist}
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/headroom"
install -d "$PKG/DEBIAN" "$PKG/usr/lib/python3/dist-packages" "$PKG/usr/share/headroom" \
    "$PKG/usr/bin" "$PKG/usr/libexec/headroom" "$PKG/usr/share/applications" \
    "$PKG/usr/share/metainfo" "$PKG/usr/share/polkit-1/actions" \
    "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/usr/share/doc/headroom"
cp -r headroom "$PKG/usr/lib/python3/dist-packages/"
find "$PKG/usr/lib/python3/dist-packages" -name '__pycache__' -prune -exec rm -rf {} +
cp -r data/cleaners "$PKG/usr/share/headroom/"
install -m 0755 data/headroom "$PKG/usr/bin/headroom"
install -m 0755 helper/headroom-helper "$PKG/usr/libexec/headroom/headroom-helper"
install -m 0644 data/io.github.kdcllc.Headroom.desktop "$PKG/usr/share/applications/"
install -m 0644 data/io.github.kdcllc.Headroom.metainfo.xml "$PKG/usr/share/metainfo/"
install -m 0644 data/io.github.kdcllc.Headroom.policy "$PKG/usr/share/polkit-1/actions/"
install -m 0644 data/io.github.kdcllc.Headroom.svg "$PKG/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 debian/copyright "$PKG/usr/share/doc/headroom/copyright"
gzip -9n -c debian/changelog > "$PKG/usr/share/doc/headroom/changelog.gz"
if [ -d build/locale ]; then
    install -d "$PKG/usr/share"
    cp -r build/locale "$PKG/usr/share/"
fi
find "$PKG" -type d -exec chmod 0755 {} +
find "$PKG/usr" -type f ! -perm -u+x -exec chmod 0644 {} +
SIZE=$(du -sk "$PKG/usr" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: headroom
Version: $VERSION
Architecture: all
Maintainer: kdcllc <info@kingdavidconsulting.com>
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi (>= 3.42), gir1.2-gtk-4.0 (>= 4.6), gir1.2-adw-1 (>= 1.1), policykit-1
Recommends: flatpak, docker.io | docker-ce
Suggests: baobab
Section: utils
Priority: optional
Homepage: https://github.com/kdcllc/headroom
Description: safe disk-space cleaner for Ubuntu 22.04 (GTK4/libadwaita)
 Scans caches, logs, old snap revisions, Docker leftovers, the Trash and large
 files, previews exactly what will be removed and cleans only what you select.
 Root-only actions run through a polkit helper with a fixed action list.
CTRL
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    py3compile -p headroom /usr/lib/python3/dist-packages/headroom 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
POST
cat > "$PKG/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
py3clean -p headroom 2>/dev/null || find /usr/lib/python3/dist-packages/headroom -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
PRE
chmod 0755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"
mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/headroom_${VERSION}_all.deb"
echo "built $OUT/headroom_${VERSION}_all.deb"

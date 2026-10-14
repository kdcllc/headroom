#!/bin/sh
# Install Headroom runtime (and, with --dev, development) dependencies on Ubuntu 22.04.
set -eu
sudo apt update
sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    libadwaita-1-0 gir1.2-glib-2.0 policykit-1 desktop-file-utils
if [ "${1:-}" = "--dev" ]; then
    sudo apt install -y python3-pytest xvfb gettext dpkg-dev debhelper dh-python lintian \
        appstream imagemagick
    echo "Optional: pipx install ruff   (or: uv tool install ruff)"
fi
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print('GTK', Gtk.get_major_version(), Gtk.get_minor_version(), '/ Adw', Adw.get_major_version(), Adw.get_minor_version())"

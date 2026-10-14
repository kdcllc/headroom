"""Drive the real GTK app in-process (used by UI tests and screenshot scripts)."""

import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib  # noqa: E402


def iterate_until(cond, timeout=30.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.01)
    return False


def pump(seconds=0.3):
    iterate_until(lambda: False, seconds)


def seed_home(home):
    """Create a plausible developer HOME with caches of several kinds."""
    def w(rel, size=4096):
        p = os.path.join(home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x" * size)
    w(".config/Cursor/Cache/Cache_Data/data_1", 3_000_000)
    w(".config/Cursor/CachedData/aaa/f", 2_000_000)
    w(".config/Cursor/CachedData/bbb/f", 1_000)
    w(".config/Cursor/User/globalStorage/state.vscdb", 5_000_000)
    w(".config/Cursor/User/settings.json", 100)
    w(".config/Code/GPUCache/data_0", 1_500_000)
    w(".config/Code/Backups/123/file", 2_000)
    w(".cache/thumbnails/normal/a.png", 800_000)
    w(".cache/pip/http/abc", 4_000_000)
    w(".cache/someapp/blob", 600_000)
    w(".cache/mozilla/firefox/abc.default-release/cache2/entries/x", 2_500_000)
    w(".local/share/Trash/files/old.iso", 1_200_000)
    w(".local/share/Trash/info/old.iso.trashinfo", 60)
    w("Downloads/ubuntu-22.04.iso", 3_000_000)
    w("Downloads/tool.AppImage", 900_000)
    w(".xsession-errors", 50_000)


def make_app(config):
    from headroom.app import HeadroomApplication
    app = HeadroomApplication(config)
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    app.activate()
    iterate_until(lambda: app.window is not None and app.window.get_mapped(), 15)
    return app


def screenshot(widget, path):
    """Grab the X display (Xvfb) with ImageMagick; GskRenderNode is not usable from PyGObject 3.42."""
    import shutil
    import subprocess
    pump(0.2)
    if not shutil.which("import") or not os.environ.get("DISPLAY"):
        return False
    subprocess.run(["import", "-window", "root", path], check=False, timeout=20)
    return os.path.exists(path)

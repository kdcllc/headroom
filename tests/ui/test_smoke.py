"""GUI smoke tests: run with  xvfb-run -a python3 -m pytest tests/ui  (GDK_BACKEND=x11)."""

import os

import pytest

gi = pytest.importorskip("gi")
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    pytest.skip("no display (run under xvfb-run)", allow_module_level=True)
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except ValueError:
    pytest.skip("GTK 4 / libadwaita typelibs missing", allow_module_level=True)

from gi.repository import Gtk  # noqa: E402

from tests.ui.harness import iterate_until, make_app, pump, seed_home  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    home = tmp_path_factory.mktemp("home")
    mp.setenv("HOME", str(home))
    for v in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        mp.delenv(v, raising=False)
    from headroom.core import commands
    # keep the test inside the fake HOME: no docker/journal/snap probes, no tool commands
    mp.setattr(commands, "probe", lambda *a, **k: commands.Probe(None))
    mp.setattr(commands, "docker_accessible", lambda: False)
    mp.setattr(commands, "which", lambda tool: None)
    seed_home(str(home))
    from headroom.core.config import Config
    cfg = Config.load()
    a = make_app(cfg)
    a.home = str(home)
    yield a
    a.window.shutdown()
    a.window.destroy()
    pump(0.2)
    mp.undo()


def _dialogs():
    return [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog) and w.get_visible()]


def test_version_check():
    from headroom.app import MIN_ADW, MIN_GTK, toolkit_versions
    gtk_v, adw_v = toolkit_versions()
    assert gtk_v >= MIN_GTK and adw_v >= MIN_ADW


def test_launch_and_scan(app):
    win = app.window
    assert win.get_mapped()
    assert win.config["dry_run"] is True  # first run defaults to dry run
    win.start_scan()
    assert iterate_until(lambda: not win.scanning, 60)
    pump(0.3)
    keys = set(win.results)
    assert {"cursor.cache", "vscode.cache", "thumbnails.cache", "trash.home"} <= keys
    assert "cursor.global_storage_info" in keys  # report-only row
    assert not win.results["cursor.global_storage_info"].selectable
    page = win.pages["Code Editors"]
    assert "cursor" in page.app_rows and page.app_rows["cursor"].get_visible()
    assert win.total_label.get_label().startswith("Would free")
    # Safe items pre-selected; Caution never; Advanced hidden
    for key in win.selected:
        assert win.results[key].rating == "safe"
    assert "trash.home" not in win.selected
    assert "vscode.backups" not in win.results or not page.app_rows["vscode"].rows["vscode.backups"].get_visible()


def test_preview_and_cancel_confirmation(app):
    win = app.window
    win._guard = lambda results, then: then(set())
    file_keys = [k for k, r in win.results.items() if r.entries and r.rating == "safe"]
    win.set_selected(list(win.selected), False)
    win.set_selected(file_keys, True)
    win.on_preview()
    pump(0.5)
    preview = win._preview
    assert preview.get_visible()
    assert preview.store.get_n_items() > 0
    paths = {item.row.path for item in preview.store}
    assert any(p.endswith("Cache_Data") for p in paths)
    preview.close()
    pump(0.2)

    before = sorted(os.path.join(dp, f) for dp, _d, fs in os.walk(app.home) for f in fs)
    win.on_clean()
    pump(0.4)
    dlgs = _dialogs()
    assert len(dlgs) == 1
    assert dlgs[0].get_widget_for_response(Gtk.ResponseType.CANCEL) is not None
    dlgs[0].response(Gtk.ResponseType.CANCEL)
    pump(0.3)
    assert not win.cleaning
    after = sorted(os.path.join(dp, f) for dp, _d, fs in os.walk(app.home) for f in fs)
    assert [p for p in after if "headroom" not in p] == [p for p in before if "headroom" not in p]


def test_callbacks_ran_on_main_thread(app):
    from headroom.ui import util
    assert util.callback_threads, "no worker callbacks recorded"
    assert all(util.callback_threads)


def test_finder_downloads(app):
    win = app.window
    win.show_page("downloads")
    fp = win.finders["downloads"]
    assert iterate_until(lambda: not fp.busy and fp.found, 15)
    names = {os.path.basename(f.path) for f in fp.found}
    assert {"ubuntu-22.04.iso", "tool.AppImage"} <= names

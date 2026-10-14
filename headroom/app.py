"""Adw.Application: version check, actions, CSS, single instance."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from .core.config import Config  # noqa: E402
from .i18n import _  # noqa: E402

MIN_GTK = (4, 6)
MIN_ADW = (1, 1)


def toolkit_versions() -> tuple[tuple[int, int], tuple[int, int]]:
    return ((Gtk.get_major_version(), Gtk.get_minor_version()),
            (Adw.get_major_version(), Adw.get_minor_version()))


class HeadroomApplication(Adw.Application):
    def __init__(self, config: Config | None = None):
        # fixed id + default flags = single instance (a 2nd launch activates the 1st)
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name(_("Headroom"))
        self.config = config
        self.window = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "ui", "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, cb, accels in (("preferences", self.on_preferences, ["<Primary>comma"]),
                                 ("about", self.on_about, []),
                                 ("quit", lambda *_a: self.quit(), ["<Primary>q"])):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        self.set_accels_for_action("win.scan", ["F5", "<Primary>r"])

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        gtk_v, adw_v = toolkit_versions()
        if gtk_v < MIN_GTK or adw_v < MIN_ADW:
            dlg = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                text=_("Unsupported GTK or libadwaita version"),
                secondary_text=_("Headroom needs GTK ≥ 4.6 and libadwaita ≥ 1.1 "
                                 "(found GTK {gtk} and libadwaita {adw}).").format(
                    gtk=".".join(map(str, gtk_v)), adw=".".join(map(str, adw_v))))
            dlg.set_application(self)
            dlg.connect("response", lambda d, _r: self.quit())
            dlg.present()
            return
        from .ui.window import MainWindow
        if self.config is None:
            self.config = Config.load()
        self.window = MainWindow(self, self.config)
        self.window.connect("close-request", self._on_close)
        self.window.present()

    def _on_close(self, win) -> bool:
        if win.cleaning:
            win.toast(_("Cleaning is in progress — cancel it first"))
            return True
        win.shutdown()
        return False

    def on_preferences(self, *_a) -> None:
        if self.window is None:
            return
        from .ui.preferences import PreferencesWindow
        PreferencesWindow(self.window, self.config, self.window.on_preferences_changed).present()

    def on_about(self, *_a) -> None:
        about = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about.set_program_name(_("Headroom"))
        about.set_logo_icon_name(APP_ID)
        about.set_version(__version__)
        about.set_comments(_("Free up disk space safely on Ubuntu 22.04"))
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_authors(["kdcllc <info@kingdavidconsulting.com>"])
        about.set_copyright("© 2026 kdcllc")
        gtk_v, adw_v = toolkit_versions()
        about.set_system_information(f"GTK {'.'.join(map(str, gtk_v))}, libadwaita {'.'.join(map(str, adw_v))}")
        about.present()

"""Preferences (Adw.PreferencesWindow)."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..core.config import BOUNDS, Config
from ..i18n import _
from .util import esc, icon_button


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, config: Config, on_changed: Callable[[], None]):
        super().__init__(transient_for=parent, modal=True)
        self.config = config
        self.on_changed = on_changed
        self._native = None
        self.set_search_enabled(False)

        page = Adw.PreferencesPage(title=_("General"), icon_name="preferences-system-symbolic")
        self.add(page)

        g = Adw.PreferencesGroup(title=_("Behaviour"))
        page.add(g)
        g.add(self._switch(_("Show advanced items"),
                           _("Items with possible data loss; never pre-selected"), "show_advanced"))
        g.add(self._switch(_("Start in dry-run mode"),
                           _("The whole flow runs but nothing is deleted"), "dry_run"))
        row = Adw.ActionRow(title=esc(_("Move user files to Trash")))
        row.set_subtitle(esc(_("For Downloads, large files and project junk. Off = delete permanently.")))
        sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=config["user_file_method"] == "trash")
        sw.connect("notify::active", lambda s, _p: self._set("user_file_method",
                                                              "trash" if s.get_active() else "delete"))
        row.add_suffix(sw)
        row.set_activatable_widget(sw)
        g.add(row)

        g = Adw.PreferencesGroup(title=_("Thresholds"))
        page.add(g)
        g.add(self._spin(_("Large file threshold (MB)"), "large_file_threshold_mb", 10))
        g.add(self._spin(_("Stale workspace age (days)"),
                         "workspace_stale_days", 5, _("workspaceStorage entries unused this long are offered")))
        g.add(self._spin(_("Local history age (days)"), "history_days", 5))
        g.add(self._spin(_("Project junk untouched for (days)"), "project_junk_days", 5))

        g = Adw.PreferencesGroup(title=_("System"),
                                 description=_("Applied by the system helper; asks for your password."))
        page.add(g)
        g.add(self._spin(_("Journal size limit (MB)"), "journal_size_mb", 50))
        g.add(self._spin(_("Journal age limit (days)"), "journal_days", 1))
        g.add(self._spin(_("Snap revisions to keep"), "snap_retain", 1))
        g.add(self._spin(_("/tmp file age (days)"), "tmp_days", 1))
        g.add(self._spin(_("/var/tmp file age (days)"), "var_tmp_days", 1))

        page2 = Adw.PreferencesPage(title=_("Paths"), icon_name="folder-symbolic")
        self.add(page2)
        self.excluded_group = self._path_group(page2, _("Excluded paths"),
                                               _("Never cleaned, never listed by finders."), "excluded_paths")
        self.roots_group = self._path_group(page2, _("Project roots"),
                                            _("Searched by the project-junk finder."), "project_roots")
        self.connect("close-request", lambda *_a: (self.on_changed(), False)[1])

    # -- helpers -------------------------------------------------------------------
    def _set(self, key, value) -> None:
        self.config.set(key, value)
        try:
            self.config.save()
        except OSError:
            pass

    def _switch(self, title: str, subtitle: str, key: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=esc(title))
        row.set_subtitle(esc(subtitle))
        sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=bool(self.config[key]))
        sw.connect("notify::active", lambda s, _p: self._set(key, s.get_active()))
        row.add_suffix(sw)
        row.set_activatable_widget(sw)
        return row

    def _spin(self, title: str, key: str, step: int, subtitle: str = "") -> Adw.ActionRow:
        lo, hi = BOUNDS[key]
        row = Adw.ActionRow(title=esc(title))
        if subtitle:
            row.set_subtitle(esc(subtitle))
        spin = Gtk.SpinButton.new_with_range(lo, hi, step)
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_value(self.config[key])
        spin.update_property([Gtk.AccessibleProperty.LABEL], [title])
        spin.connect("value-changed", lambda s: self._set(key, int(s.get_value())))
        row.add_suffix(spin)
        return row

    def _path_group(self, page, title, description, key) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title, description=description)
        add = icon_button("list-add-symbolic", _("Add folder…"))
        add.add_css_class("flat")
        add.connect("clicked", lambda *_a: self._choose_folder(key, group))
        group.set_header_suffix(add)
        group._rows = []
        page.add(group)
        self._fill_paths(group, key)
        return group

    def _fill_paths(self, group, key) -> None:
        for row in group._rows:
            group.remove(row)
        group._rows = []
        for path in self.config[key]:
            row = Adw.ActionRow(title=esc(path))
            rm = icon_button("user-trash-symbolic", _("Remove {path}").format(path=path),
                             valign=Gtk.Align.CENTER)
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, p=path: self._remove_path(key, p, group))
            row.add_suffix(rm)
            group.add(row)
            group._rows.append(row)

    def _remove_path(self, key, path, group) -> None:
        self._set(key, [p for p in self.config[key] if p != path])
        self._fill_paths(group, key)

    def _choose_folder(self, key, group) -> None:
        native = Gtk.FileChooserNative(title=_("Choose a folder"), transient_for=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER,
                                       accept_label=_("Add"))

        def on_response(n, response):
            if response == Gtk.ResponseType.ACCEPT and n.get_file():
                path = n.get_file().get_path()
                if path and path not in self.config[key]:
                    self._set(key, [*self.config[key], path])
                    self._fill_paths(group, key)
            self._native = None
        native.connect("response", on_response)
        self._native = native
        native.show()

"""Downloads, Large files and Project junk finder pages (user content: Trash by default)."""

from __future__ import annotations

import os
import shutil
import threading
import time
from typing import TYPE_CHECKING

from gi.repository import Gio, GObject, Gtk, Pango

from ..core import largefiles, paths, planner
from ..core.scanner import Cancelled
from ..i18n import _
from .confirm import confirm_clean
from .util import fmt_age, fmt_size, idle

if TYPE_CHECKING:
    from .window import MainWindow

MODES = {
    "downloads": (_("Downloads"), _("Files in your Downloads folder. Moved to the Trash by default.")),
    "large": (_("Large Files"), _("Files in your home folder above the size threshold (Preferences). "
                                  "Other drives, the Trash and protected folders are skipped.")),
    "junk": (_("Project Junk"), _("Rebuildable folders inside your projects: node_modules, Rust target, "
                                  ".venv, build/dist, __pycache__ and similar, untouched for a while.")),
}

QUICK_FILTERS = [
    ("all", _("All"), lambda f, now: True),
    ("iso", "ISO", lambda f, now: f.path.lower().endswith(".iso")),
    ("appimage", "AppImage", lambda f, now: f.path.lower().endswith(".appimage")),
    ("deb", ".deb", lambda f, now: f.path.lower().endswith(".deb")),
    ("archive", _("Archives"), lambda f, now: f.category == "Archive"),
    ("30", _("> 30 days"), lambda f, now: now - f.mtime > 30 * 86400),
    ("90", _("> 90 days"), lambda f, now: now - f.mtime > 90 * 86400),
]


class FoundItem(GObject.Object):
    __gtype_name__ = "HeadroomFoundItem"

    def __init__(self, found: largefiles.Found):
        super().__init__()
        self.found = found
        self.checked = False


def _cmp(a, b) -> int:
    return (a > b) - (a < b)


class FinderPage(Gtk.Box):
    def __init__(self, window: MainWindow, mode: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{m}")(12)
        self.window = window
        self.mode = mode
        self.cancel = threading.Event()
        self.busy = False
        self.filter_id = "all"
        self.found: list[largefiles.Found] = []
        self.roots: list[str] = []

        title, desc = MODES[mode]
        head = Gtk.Box(spacing=12)
        t = Gtk.Label(label=title, xalign=0, hexpand=True)
        t.add_css_class("title-2")
        head.append(t)
        self.spinner = Gtk.Spinner()
        head.append(self.spinner)
        self.find_btn = Gtk.Button(label=_("Find") if mode != "downloads" else _("Refresh"))
        self.find_btn.add_css_class("suggested-action")
        self.find_btn.connect("clicked", lambda *_a: self.start())
        head.append(self.find_btn)
        if shutil.which("baobab"):
            b = Gtk.Button(label=_("Disk Usage Analyzer"))
            b.set_tooltip_text(_("Open the folder in Disk Usage Analyzer (baobab)"))
            b.connect("clicked", lambda *_a: self._baobab())
            head.append(b)
        self.append(head)
        d = Gtk.Label(label=desc, xalign=0, wrap=True)
        d.add_css_class("dim-label")
        self.append(d)

        if mode == "downloads":
            filters = Gtk.Box(spacing=0)
            filters.add_css_class("linked")
            group = None
            for fid, label, _fn in QUICK_FILTERS:
                tb = Gtk.ToggleButton(label=label)
                if group is None:
                    group = tb
                    tb.set_active(True)
                else:
                    tb.set_group(group)
                tb.connect("toggled", self._on_quick_filter, fid)
                filters.append(tb)
            self.append(filters)

        self.store = Gio.ListStore(item_type=FoundItem)
        self.filter = Gtk.CustomFilter.new(self._match, None)
        filtered = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.sorted = Gtk.SortListModel(model=filtered)
        self.view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.sorted), show_row_separators=True)
        self.view.add_css_class("data-table")
        self.sorted.set_sorter(self.view.get_sorter())
        self._columns()
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.view)
        self.append(scroller)

        bar = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        bar.append(self.status)
        self.open_btn = Gtk.Button(label=_("Open folder"))
        self.open_btn.connect("clicked", lambda *_a: self._open_folder())
        bar.append(self.open_btn)
        self.delete_btn = Gtk.Button(label=_("Delete permanently…"))
        self.delete_btn.add_css_class("destructive-action")
        self.delete_btn.connect("clicked", lambda *_a: self._remove("delete"))
        bar.append(self.delete_btn)
        self.trash_btn = Gtk.Button(label=_("Move to Trash"))
        self.trash_btn.add_css_class("suggested-action")
        self.trash_btn.connect("clicked", lambda *_a: self._remove("trash"))
        bar.append(self.trash_btn)
        self.append(bar)
        self._update_status()

    # -- columns --------------------------------------------------------------
    def _columns(self) -> None:
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            cb = Gtk.CheckButton()
            cb.update_property([Gtk.AccessibleProperty.LABEL], [_("Select")])
            li.set_child(cb)

        def bind(_f, li):
            cb, item = li.get_child(), li.get_item()
            cb.set_active(item.checked)
            cb._h = cb.connect("toggled", self._on_check, item)

        def unbind(_f, li):
            cb = li.get_child()
            if getattr(cb, "_h", None):
                cb.disconnect(cb._h)
                cb._h = None

        f.connect("setup", setup)
        f.connect("bind", bind)
        f.connect("unbind", unbind)
        self.view.append_column(Gtk.ColumnViewColumn(title="", factory=f))

        def col(title, text, key, expand=False, xalign=0.0, mono=False):
            fac = Gtk.SignalListItemFactory()

            def s(_f, li):
                lbl = Gtk.Label(xalign=xalign, ellipsize=Pango.EllipsizeMode.MIDDLE)
                if mono:
                    lbl.add_css_class("mono")
                li.set_child(lbl)

            def b(_f, li):
                value = text(li.get_item().found)
                li.get_child().set_label(value)
                li.get_child().set_tooltip_text(value if mono else None)
            fac.connect("setup", s)
            fac.connect("bind", b)
            c = Gtk.ColumnViewColumn(title=title, factory=fac)
            c.set_expand(expand)
            c.set_resizable(True)
            c.set_sorter(Gtk.CustomSorter.new(lambda a, b2, _d: _cmp(key(a.found), key(b2.found)), None))
            self.view.append_column(c)
            return c

        home = paths.home()
        col(_("Name"), lambda f: os.path.basename(f.path), lambda f: os.path.basename(f.path).lower(), expand=True)
        size_col = col(_("Size"), lambda f: fmt_size(f.size), lambda f: f.size, xalign=1)
        col(_("Modified"), lambda f: fmt_age(f.mtime), lambda f: f.mtime)
        col(_("Type"), lambda f: f.category, lambda f: f.category)
        col(_("Folder"), lambda f: os.path.dirname(f.path).replace(home, "~", 1),
            lambda f: f.path, expand=True, mono=True)
        self.view.sort_by_column(size_col, Gtk.SortType.DESCENDING)

    # -- search ------------------------------------------------------------------
    def start(self) -> None:
        if self.busy:
            self.cancel.set()
            return
        cfg = self.window.config
        excluded = list(cfg["excluded_paths"])
        if self.mode == "large":
            self.roots = [paths.home()]
        elif self.mode == "junk":
            self.roots = [os.path.abspath(paths.expand(r)) for r in cfg["project_roots"]] or [paths.home()]
        else:
            self.roots = [paths.downloads_dir()]
        self.policy = largefiles.finder_policy(self.roots, excluded)
        self.cancel = threading.Event()
        self.busy = True
        self.spinner.start()
        self.find_btn.set_label(_("Stop"))
        self.store.remove_all()
        self.status.set_label(_("Searching…"))
        threshold = int(cfg["large_file_threshold_mb"]) * 1024 * 1024
        junk_days = int(cfg["project_junk_days"])
        cancel = self.cancel

        def progress(where: str, n: int) -> None:
            idle(self.status.set_label, _("Searching {path}… {n} found").format(path=where, n=n))

        def work():
            try:
                if self.mode == "large":
                    found = largefiles.find_large_files(self.roots, threshold, self.policy, cancel=cancel,
                                                        progress=progress, excluded=excluded)
                elif self.mode == "junk":
                    found = largefiles.find_project_junk(self.roots, self.policy, min_age_days=junk_days,
                                                         cancel=cancel, progress=progress)
                else:
                    found = largefiles.list_downloads(self.policy, cancel=cancel)
            except Cancelled:
                found = None
            idle(self._done, found)
        self.window.submit(work)

    def _done(self, found) -> None:
        self.busy = False
        self.spinner.stop()
        self.find_btn.set_label(_("Find") if self.mode != "downloads" else _("Refresh"))
        if found is None:
            self.status.set_label(_("Stopped."))
            return
        self.found = found
        self.store.remove_all()
        for f in found:
            self.store.append(FoundItem(f))
        self._update_status()

    def _match(self, item, _d=None) -> bool:
        fn = dict((fid, f) for fid, _l, f in QUICK_FILTERS)[self.filter_id]
        return fn(item.found, time.time())

    def _on_quick_filter(self, tb, fid) -> None:
        if tb.get_active():
            self.filter_id = fid
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self._update_status()

    def _on_check(self, cb, item) -> None:
        item.checked = cb.get_active()
        self._update_status()

    def checked(self) -> list[largefiles.Found]:
        return [it.found for it in self.store if it.checked and self._match(it)]

    def _update_status(self) -> None:
        sel = self.checked()
        total = sum(f.size for f in self.found)
        if sel:
            self.status.set_label(_("{n} selected · {size}").format(n=len(sel), size=fmt_size(sum(f.size for f in sel))))
        elif self.found:
            self.status.set_label(_("{n} found · {size}").format(n=len(self.found), size=fmt_size(total)))
        else:
            self.status.set_label(_("Press Find to search.") if self.mode != "downloads" else
                                  _("Press Refresh to list your Downloads folder."))
        has = bool(sel) and not self.window.cleaning
        self.trash_btn.set_sensitive(has)
        self.delete_btn.set_sensitive(has)
        self.open_btn.set_sensitive(len(sel) == 1)

    # -- actions ------------------------------------------------------------------
    def _open_folder(self) -> None:
        sel = self.checked()
        if sel:
            uri = Gio.File.new_for_path(os.path.dirname(sel[0].path)).get_uri()
            Gio.AppInfo.launch_default_for_uri(uri, None)

    def _baobab(self) -> None:
        sel = self.checked()
        target = sel[0].path if sel and os.path.isdir(sel[0].path) else (self.roots[0] if self.roots else paths.home())
        self.window.launch(["baobab", target])

    def _remove(self, method: str) -> None:
        sel = self.checked()
        if not sel:
            return
        results = largefiles.to_results(sel, method, MODES[self.mode][0])
        plan = planner.build_plan(results, dry_run=self.window.config["dry_run"])

        def run() -> None:
            self.window.clean_plan(plan, policy=self.policy, after=self._after_clean)
        if method == "trash":
            run()  # reversible: Undo toast afterwards
        else:
            confirm_clean(self.window, plan, run)

    def _after_clean(self, report) -> None:
        gone: set[str] = set()
        for it in list(self.store):
            if it.checked and not os.path.lexists(it.found.path):
                gone.add(it.found.path)
        self.found = [f for f in self.found if f.path not in gone]
        for i in reversed(range(self.store.get_n_items())):
            if self.store.get_item(i).found.path in gone:
                self.store.remove(i)
        self._update_status()

"""Preview: the exact list of files/dirs/commands a clean would act on."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from gi.repository import Gio, GObject, Gtk, Pango

from ..core import planner
from ..core.models import CleanPlan
from ..i18n import _
from .util import fmt_size

LIMIT = planner.PREVIEW_LIMIT


class PreviewItem(GObject.Object):
    __gtype_name__ = "HeadroomPreviewItem"

    def __init__(self, row: planner.PreviewRow, included: bool):
        super().__init__()
        self.row = row
        self.included = included


def _label_factory(get_text: Callable[[PreviewItem], str], *, mono: bool = False, xalign: float = 0,
                   ellipsize: Pango.EllipsizeMode = Pango.EllipsizeMode.END) -> Gtk.SignalListItemFactory:
    f = Gtk.SignalListItemFactory()

    def setup(_f, li):
        lbl = Gtk.Label(xalign=xalign, ellipsize=ellipsize)
        if mono:
            lbl.add_css_class("mono")
        li.set_child(lbl)

    def bind(_f, li):
        item = li.get_item()
        text = get_text(item)
        lbl = li.get_child()
        lbl.set_label(text)
        lbl.set_tooltip_text(text if mono else None)

    f.connect("setup", setup)
    f.connect("bind", bind)
    return f


def _cmp(a, b) -> int:
    return (a > b) - (a < b)


class PreviewDialog(Gtk.Window):
    def __init__(self, parent: Gtk.Window, plan: CleanPlan, excluded: set[str],
                 on_close: Callable[[set[str]], None], on_clean: Callable[[], None] | None = None):
        super().__init__(transient_for=parent, modal=True, title=_("Preview"),
                         default_width=1000, default_height=640)
        self.plan = plan
        self.excluded = set(excluded)
        self.on_close = on_close
        self.on_clean = on_clean
        self._native = None
        self.query = ""

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        export = Gtk.Button(label=_("Export list…"))
        export.connect("clicked", self._on_export)
        header.pack_start(export)
        if on_clean:
            clean = Gtk.Button(label=_("Simulate…") if plan.dry_run else _("Clean…"))
            clean.add_css_class("suggested-action" if plan.dry_run else "destructive-action")
            clean.connect("clicked", self._on_clean)
            header.pack_end(clean)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(12)
        self.set_child(box)

        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_label(_("Nothing has been changed yet. These are exactly the files, folders and commands "
                          "that “Clean” will act on. Untick a row to exclude it (remembered for next time)."))
        box.append(intro)
        self.search = Gtk.SearchEntry(placeholder_text=_("Filter by path or item"))
        self.search.connect("search-changed", self._on_search)
        box.append(self.search)

        rows = planner.preview_rows(plan)
        rows.sort(key=lambda r: (r.group, -r.size))
        self.total_rows = len(rows)
        shown, hidden = rows[:LIMIT], rows[LIMIT:]
        self.store = Gio.ListStore(item_type=PreviewItem)
        for r in shown:
            self.store.append(PreviewItem(r, r.path not in self.excluded))

        self.filter = Gtk.CustomFilter.new(self._match, None)
        filtered = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.sorted = Gtk.SortListModel(model=filtered)
        self.view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.sorted), show_row_separators=True)
        self.view.add_css_class("data-table")
        self.sorted.set_sorter(self.view.get_sorter())
        self._add_columns()
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.view)
        box.append(scroller)

        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("dim-label")
        box.append(self.summary)
        if hidden:
            more = Gtk.Label(xalign=0, label=_("…and {n} more ({size}) not listed").format(
                n=len(hidden), size=fmt_size(sum(r.size for r in hidden))))
            box.append(more)
        self._update_summary()
        self.connect("close-request", self._on_close_request)

    # -- columns -------------------------------------------------------------
    def _add_columns(self) -> None:
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            cb = Gtk.CheckButton()
            cb.update_property([Gtk.AccessibleProperty.LABEL], [_("Include")])
            li.set_child(cb)

        def bind(_f, li):
            cb = li.get_child()
            item = li.get_item()
            cb.set_active(item.included)
            exclusive = item.row.kind in ("command", "root")
            cb.set_sensitive(not exclusive)
            cb.set_tooltip_text(_("Deselect the item in the main list to skip a command") if exclusive else None)
            cb._handler = cb.connect("toggled", self._on_toggle, item)

        def unbind(_f, li):
            cb = li.get_child()
            if getattr(cb, "_handler", None):
                cb.disconnect(cb._handler)
                cb._handler = None

        f.connect("setup", setup)
        f.connect("bind", bind)
        f.connect("unbind", unbind)
        self.view.append_column(Gtk.ColumnViewColumn(title="", factory=f))

        def col(title, getter, key, *, expand=False, mono=False, xalign=0.0, width=None):
            c = Gtk.ColumnViewColumn(title=title, factory=_label_factory(
                getter, mono=mono, xalign=xalign,
                ellipsize=Pango.EllipsizeMode.MIDDLE if mono else Pango.EllipsizeMode.END))
            c.set_expand(expand)
            c.set_resizable(True)
            if width:
                c.set_fixed_width(width)
            c.set_sorter(Gtk.CustomSorter.new(lambda a, b, _d: _cmp(key(a), key(b)), None))
            self.view.append_column(c)
            return c

        col(_("Item"), lambda i: i.row.group, lambda i: i.row.group, width=240)
        col(_("Path or command"), lambda i: i.row.path, lambda i: i.row.path, expand=True, mono=True)
        col(_("Size"), lambda i: fmt_size(i.row.size), lambda i: i.row.size, xalign=1)
        col(_("Type"), lambda i: i.row.kind, lambda i: i.row.kind)
        col(_("Modified"), lambda i: time.strftime("%Y-%m-%d", time.localtime(i.row.mtime)) if i.row.mtime else "—",
            lambda i: i.row.mtime)

    # -- behaviour ---------------------------------------------------------------
    def _match(self, item, _data=None) -> bool:
        if not self.query:
            return True
        q = self.query.lower()
        return q in item.row.path.lower() or q in item.row.group.lower()

    def _on_search(self, entry) -> None:
        self.query = entry.get_text().strip()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_toggle(self, cb, item) -> None:
        item.included = cb.get_active()
        if item.included:
            self.excluded.discard(item.row.path)
        else:
            self.excluded.add(item.row.path)
        self._update_summary()

    def _update_summary(self) -> None:
        excl = [it for it in self.store if not it.included]
        size = sum(it.row.size for it in self.store if it.included and it.row.kind not in ("command", "root"))
        size += sum(i.result.size for i in self.plan.items if not i.entries)
        self.summary.set_label(_("{n} rows · {size} · {x} excluded").format(
            n=self.total_rows, size=fmt_size(size), x=len(excl)))

    def current_plan_text(self) -> str:
        from ..core.models import CleanPlan, PlanItem
        items = []
        for it in self.plan.items:
            entries = [e for e in it.entries if e.path not in self.excluded]
            items.append(PlanItem(it.result, entries, it.commands, it.root_actions))
        return planner.export_text(CleanPlan(items, self.plan.dry_run))

    def _on_export(self, *_a) -> None:
        native = Gtk.FileChooserNative(title=_("Export list"), transient_for=self,
                                       action=Gtk.FileChooserAction.SAVE, accept_label=_("Export"))
        native.set_current_name("headroom-preview.tsv")

        def on_response(n, response):
            if response == Gtk.ResponseType.ACCEPT:
                path = n.get_file().get_path()
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(self.current_plan_text())
                except OSError as exc:
                    from .util import show_error
                    show_error(self, _("Could not export the list"), str(exc))
            self._native = None
        native.connect("response", on_response)
        self._native = native  # keep a reference while it is shown
        native.show()

    def _finish(self) -> None:
        cb = self.on_close
        self.on_close = None
        if cb:
            cb(self.excluded)

    def _on_close_request(self, *_a) -> bool:
        self._finish()
        return False

    def _on_clean(self, *_a) -> None:
        self._finish()
        on_clean = self.on_clean
        self.destroy()
        if on_clean:
            on_clean()


def export_path_default() -> str:
    return os.path.join(os.path.expanduser("~"), "headroom-preview.tsv")

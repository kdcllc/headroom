"""Overview: disk usage bars, top reclaimable items, quick selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from ..core import paths
from ..i18n import _
from .util import clear_box, esc, fmt_size, rating_badge

if TYPE_CHECKING:
    from .window import MainWindow


class OverviewPage(Gtk.ScrolledWindow):
    def __init__(self, window: MainWindow):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        clamp = Adw.Clamp(maximum_size=900)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(18)
        clamp.set_child(box)
        self.set_child(clamp)

        title = Gtk.Label(label=_("Disk usage"), xalign=0)
        title.add_css_class("title-2")
        box.append(title)
        disks = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        disks.add_css_class("boxed-list")
        self.bars = {}
        for label, path in ((_("System (/)"), "/"), (_("Home"), paths.home())):
            row = Adw.ActionRow(title=esc(label))
            row.set_subtitle(esc(path))
            bar = Gtk.LevelBar(min_value=0, max_value=1, hexpand=True, valign=Gtk.Align.CENTER)
            bar.set_size_request(260, -1)
            bar.add_offset_value("low", 0.80)
            bar.add_offset_value("high", 0.92)
            bar.add_offset_value("full", 1.0)
            text = Gtk.Label(xalign=1)
            text.add_css_class("size-label")
            row.add_suffix(bar)
            row.add_suffix(text)
            disks.append(row)
            self.bars[path] = (bar, text, row)
        box.append(disks)

        actions = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.select_safe = Gtk.Button(label=_("Select all Safe items"))
        self.select_safe.add_css_class("pill")
        self.select_safe.add_css_class("suggested-action")
        self.select_safe.connect("clicked", lambda *_a: window.select_all_safe())
        actions.append(self.select_safe)
        self.root_scan = Gtk.Button(label=_("Scan system items (requires password)"))
        self.root_scan.add_css_class("pill")
        self.root_scan.set_tooltip_text(_("Measure items only root can read, such as /var/lib/snapd/cache"))
        self.root_scan.connect("clicked", lambda *_a: window.scan_root_sizes())
        actions.append(self.root_scan)
        box.append(actions)

        self.top_title = Gtk.Label(label=_("Largest reclaimable items"), xalign=0)
        self.top_title.add_css_class("title-2")
        box.append(self.top_title)
        self.top = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.top.add_css_class("boxed-list")
        box.append(self.top)
        self.hint = Adw.StatusPage(icon_name="edit-find-symbolic", title=_("Nothing scanned yet"),
                                   description=_("Press Scan to measure caches, logs and leftovers."))
        box.append(self.hint)
        self.refresh_disks()
        self.update([])

    def refresh_disks(self) -> None:
        for path, (bar, text, row) in self.bars.items():
            usage = paths.disk_usage(path)
            if not usage:
                continue
            used, total = usage
            bar.set_value(used / total if total else 0)
            text.set_label(_("{used} of {total}").format(used=fmt_size(used), total=fmt_size(total)))
            free = total - used
            row.set_subtitle(esc(_("{path} · {free} free").format(path=path, free=fmt_size(free))))

    def update(self, results) -> None:
        clear_box(self.top)
        show_adv = self.window.config["show_advanced"]
        rows = [r for r in results if not r.option.report_only and r.size_known and r.size > 0
                and (show_adv or r.rating != "advanced")]
        rows.sort(key=lambda r: r.size, reverse=True)
        for r in rows[:10]:
            row = Adw.ActionRow(title=esc(r.label))
            row.set_subtitle(esc(f"{r.cleaner.category} › {r.cleaner.label}"))
            size = Gtk.Label(label=fmt_size(r.size, r.size_known, r.approximate), xalign=1)
            size.add_css_class("size-label")
            row.add_suffix(size)
            row.add_suffix(rating_badge(r.rating))
            go = Gtk.Button(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER)
            go.add_css_class("flat")
            go.set_tooltip_text(_("Show in {cat}").format(cat=r.cleaner.category))
            go.connect("clicked", lambda _b, cat=r.cleaner.category: self.window.show_page(cat))
            row.add_suffix(go)
            row.set_activatable_widget(go)
            self.top.append(row)
        has = bool(rows)
        self.top.set_visible(has)
        self.top_title.set_visible(has)
        self.hint.set_visible(not has)
        if self.window.scanned_once and not has:
            self.hint.set_title(_("Nothing to clean"))
            self.hint.set_description(_("No reclaimable data was found."))
        self.root_scan.set_visible(self.window.helper_available)

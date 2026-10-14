"""Category page: one expander per app, one row per cleanable option."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk, Pango

from ..core.models import CleanerDef, ScanResult, total_size
from ..i18n import _
from .util import esc, fmt_age, fmt_size, rating_badge

if TYPE_CHECKING:
    from .window import MainWindow


def describe_location(r: ScanResult, limit: int = 2) -> str:
    """Short location summary for a row subtitle (plain text)."""
    if r.detail and r.option.split:
        return r.detail
    if r.commands:
        return " ".join(r.commands[0])
    if r.root_actions and not r.entries:
        return _("system action: {id}").format(id=r.root_actions[0]["id"])
    parents: list[str] = []
    for e in r.entries:
        p = os.path.dirname(e.path) if r.option.targets and r.option.targets[0].mode == "contents" else e.path
        p = p.replace(os.path.expanduser("~"), "~", 1)
        if p not in parents:
            parents.append(p)
    if not parents:
        pats = [t.path.replace(os.path.expanduser("~"), "~", 1) for t in r.option.targets]
        parents = pats or [p.replace(os.path.expanduser("~"), "~", 1) for p in r.option.probe_paths]
    more = len(parents) - limit
    text = ", ".join(parents[:limit])
    if more > 0:
        text += " " + _("+{n} more").format(n=more)
    return text


def info_text(r: ScanResult) -> str:
    """Markup for the info popover: exact paths/commands and rating reason."""
    reason = {
        "safe": _("Safe: a regenerable cache that the application rebuilds automatically."),
        "caution": _("Caution: visible side effects such as re-downloads, lost UI state or extension data."),
        "advanced": _("Advanced: possible data loss or system impact. Read the description carefully."),
    }[r.rating]
    lines = [f"<b>{esc(r.cleaner.label)} › {esc(r.label)}</b>", esc(r.option.description), "",
             f"<i>{esc(reason)}</i>", ""]
    if r.unavailable:
        lines += [f"<b>{esc(_('Not available:'))}</b> {esc(r.unavailable)}", ""]
    if r.commands:
        lines.append(f"<b>{esc(_('Command'))}</b>")
        lines += [f"<tt>{esc(' '.join(a))}</tt>" for a in r.commands]
    if r.root_actions:
        lines.append(f"<b>{esc(_('System action (asks for your password)'))}</b>")
        for a in r.root_actions:
            params = " ".join(f"{k}={v}" for k, v in a.items() if k != "id")
            lines.append(f"<tt>{esc(a['id'])} {esc(params)}</tt>")
    if r.option.targets:
        lines.append(f"<b>{esc(_('Locations'))}</b>")
        for t in r.option.targets[:12]:
            mode = {"contents": _("contents of"), "glob": _("matches of"), "dir": _("folder"),
                    "truncate": _("empty file"), "file": _("file")}.get(t.mode, t.mode)
            lines.append(f"{esc(mode)} <tt>{esc(t.path)}</tt>")
        if len(r.option.targets) > 12:
            lines.append(esc(_("…and {n} more").format(n=len(r.option.targets) - 12)))
    if r.option.probe_paths and r.option.report_only:
        lines += [f"<tt>{esc(p)}</tt>" for p in r.option.probe_paths]
    if r.entries:
        lines += ["", esc(_("{n} items, {files} files, {size} on disk ({apparent} apparent), newest {age}").format(
            n=len(r.entries), files=r.count, size=fmt_size(r.size),
            apparent=fmt_size(r.apparent), age=fmt_age(r.mtime)))]
    if r.option.requires_app_closed:
        lines.append(esc(_("The application must be closed.")))
    return "\n".join(lines)


class OptionRow(Adw.ActionRow):
    def __init__(self, window: MainWindow, result: ScanResult):
        super().__init__()
        self.window = window
        self.result = result
        self._updating = False
        self.set_subtitle_lines(3)
        self.check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        self.check.connect("toggled", self._on_toggled)
        self.add_prefix(self.check)
        self.set_activatable_widget(self.check)

        self.size_label = Gtk.Label(xalign=1, valign=Gtk.Align.CENTER)
        self.size_label.add_css_class("size-label")
        self.add_suffix(self.size_label)
        self.badge = rating_badge(result.rating)
        self.add_suffix(self.badge)
        self.lock = Gtk.Image(icon_name="changes-prevent-symbolic", valign=Gtk.Align.CENTER)
        self.lock.set_tooltip_text(_("Needs administrator rights (one password prompt per clean)"))
        self.add_suffix(self.lock)

        self.info = Gtk.MenuButton(icon_name="dialog-information-symbolic", valign=Gtk.Align.CENTER)
        self.info.add_css_class("flat")
        self.info.set_tooltip_text(_("Details"))
        self.info.update_property([Gtk.AccessibleProperty.LABEL], [_("Details")])
        pop = Gtk.Popover()
        self.info_label = Gtk.Label(wrap=True, selectable=True, xalign=0, max_width_chars=60)
        self.info_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.info_label.set_margin_top(6)
        self.info_label.set_margin_bottom(6)
        self.info_label.set_margin_start(6)
        self.info_label.set_margin_end(6)
        scroller = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=420,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.info_label)
        pop.set_child(scroller)
        self.info.set_popover(pop)
        self.add_suffix(self.info)

        self.extra_button: Gtk.Button | None = None
        if result.option.id == "timeshift.info" and window.has_tool("timeshift-launcher"):
            self.extra_button = Gtk.Button(label=_("Open Timeshift"), valign=Gtk.Align.CENTER)
            self.extra_button.connect("clicked", lambda *_a: window.launch(["timeshift-launcher"]))
            self.add_suffix(self.extra_button)
        self.update(result)

    def update(self, result: ScanResult) -> None:
        self.result = result
        r = result
        self.set_title(esc(r.label))
        desc = r.option.description
        if r.unavailable:
            desc = f"{r.unavailable}"
        sub = f"{esc(desc)}\n<small><tt>{esc(describe_location(r))}</tt></small>"
        self.set_subtitle(sub)
        if r.option.note == "setting":
            self.size_label.set_label(_("setting"))
        elif r.option.report_only:
            self.size_label.set_label(fmt_size(r.size, r.size_known, r.approximate))
        else:
            self.size_label.set_label(fmt_size(r.size, r.size_known, r.approximate))
        self.size_label.set_tooltip_text(
            _("Apparent size: {s}").format(s=fmt_size(r.apparent)) if r.apparent else None)
        self.lock.set_visible(bool(r.root_actions) or r.option.root)
        self.info_label.set_markup(info_text(r))
        self.check.set_sensitive(r.selectable)
        self.check.set_visible(not r.option.report_only)
        self.sync_check()

    def sync_check(self) -> None:
        self._updating = True
        self.check.set_active(self.result.key in self.window.selected)
        self._updating = False

    def _on_toggled(self, check: Gtk.CheckButton) -> None:
        if self._updating:
            return
        self.window.set_selected([self.result.key], check.get_active())


class AppRow(Adw.ExpanderRow):
    def __init__(self, window: MainWindow, cleaner: CleanerDef):
        super().__init__()
        self.window = window
        self.cleaner = cleaner
        self.rows: dict[str, OptionRow] = {}
        self.running = False
        self._updating = False
        self.set_title(esc(cleaner.label))
        self.check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        self.check.set_tooltip_text(_("Select all items of {app}").format(app=cleaner.label))
        self.check.connect("toggled", self._on_toggled)
        self.add_prefix(self.check)
        self.warn = Gtk.Image(icon_name="dialog-warning-symbolic", valign=Gtk.Align.CENTER)
        self.warn.add_css_class("running-warning")
        self.warn.set_tooltip_text(_("{app} is running. Close it before cleaning its caches.").format(
            app=cleaner.label))
        self.warn.set_visible(False)
        self.add_action(self.warn)
        self.total = 0

    def set_results(self, results: list[ScanResult], running: bool) -> None:
        self.running = running
        self.warn.set_visible(running)
        keep = {r.key for r in results}
        for key in list(self.rows):
            if key not in keep:
                self.remove(self.rows.pop(key))
        for r in sorted(results, key=lambda r: (-r.size, r.label)):
            if r.key in self.rows:
                self.rows[r.key].update(r)
            else:
                row = OptionRow(self.window, r)
                self.rows[r.key] = row
                self.add_row(row)
        self.refresh()

    def visible_rows(self) -> list[OptionRow]:
        return [row for row in self.rows.values() if row.get_visible()]

    def refresh(self) -> None:
        show_adv = self.window.config["show_advanced"]
        for row in self.rows.values():
            row.set_visible(show_adv or row.result.rating != "advanced")
            row.sync_check()
        visible = self.visible_rows()
        self.set_visible(bool(visible))
        self.total = total_size(r.result for r in visible)
        sel = [r for r in visible if r.result.key in self.window.selected]
        sel_size = total_size(r.result for r in sel)
        parts = [_("{size} reclaimable").format(size=fmt_size(self.total))]
        if sel:
            parts.append(_("{size} selected").format(size=fmt_size(sel_size)))
        if self.running:
            parts.append(_("running"))
        self.set_subtitle(esc(" · ".join(parts)))
        selectable = [r for r in visible if r.result.selectable]
        self._updating = True
        self.check.set_sensitive(bool(selectable))
        n = sum(1 for r in selectable if r.result.key in self.window.selected)
        self.check.set_active(bool(selectable) and n == len(selectable))
        self.check.set_inconsistent(0 < n < len(selectable))
        self._updating = False

    def _on_toggled(self, check: Gtk.CheckButton) -> None:
        if self._updating:
            return
        keys = [r.result.key for r in self.visible_rows() if r.result.selectable]
        # an inconsistent box becomes fully selected on click
        self.window.set_selected(keys, check.get_active() or check.get_inconsistent())


class CategoryPage(Gtk.Box):
    def __init__(self, window: MainWindow, category: str, description: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.category = category
        self.app_rows: dict[str, AppRow] = {}

        self.stack = Gtk.Stack()
        self.append(self.stack)
        self.stack.set_vexpand(True)

        self.empty = Adw.StatusPage(icon_name="edit-find-symbolic", title=category,
                                    description=_("Press Scan to look for cleanable data."))
        self.stack.add_named(self.empty, "empty")

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=1000, tightening_threshold=700)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(12)
        box.set_margin_end(12)
        header = Gtk.Box(spacing=12)
        title = Gtk.Label(label=category, xalign=0, hexpand=True)
        title.add_css_class("title-2")
        header.append(title)
        self.extra_header = Gtk.Box(spacing=6)
        header.append(self.extra_header)
        box.append(header)
        if description:
            d = Gtk.Label(label=description, xalign=0, wrap=True)
            d.add_css_class("dim-label")
            box.append(d)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_sort_func(lambda a, b: (b.total > a.total) - (b.total < a.total))
        box.append(self.listbox)
        clamp.set_child(box)
        scroller.set_child(clamp)
        self.stack.add_named(scroller, "list")

    def set_cleaner(self, cleaner: CleanerDef, results: list[ScanResult], running: bool) -> None:
        row = self.app_rows.get(cleaner.id)
        if row is None:
            if not results:
                return
            row = AppRow(self.window, cleaner)
            self.app_rows[cleaner.id] = row
            self.listbox.append(row)
        row.set_results(results, running)
        self.listbox.invalidate_sort()
        self._update_stack()

    def refresh(self) -> None:
        for row in self.app_rows.values():
            row.refresh()
        self.listbox.invalidate_sort()
        self._update_stack()

    def _update_stack(self) -> None:
        has = any(r.get_visible() for r in self.app_rows.values())
        self.stack.set_visible_child_name("list" if has else "empty")
        if not has and self.window.scanned_once:
            self.empty.set_icon_name("emblem-ok-symbolic")
            self.empty.set_description(_("Nothing to clean here."))

    def clear(self) -> None:
        for row in self.app_rows.values():
            self.listbox.remove(row)
        self.app_rows.clear()
        self._update_stack()

    @property
    def total(self) -> int:
        return sum(r.total for r in self.app_rows.values() if r.get_visible())

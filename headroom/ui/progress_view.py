"""Progress page during a clean and the result page afterwards."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk, Pango

from ..core.models import CleanReport, ItemResult
from ..i18n import _
from .util import clear_box, esc, fmt_size

STATUS_ICON = {"ok": "✓", "dry-run": "✓", "partial": "⚠", "skipped": "⚠", "failed": "✗"}


class ProgressView(Gtk.Box):
    def __init__(self, on_cancel: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{m}")(24)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("title-2")
        self.append(self.title)
        self.bar = Gtk.ProgressBar(show_text=True)
        self.append(self.bar)
        self.current = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.current.add_css_class("dim-label")
        self.current.add_css_class("mono")
        self.append(self.current)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log.add_css_class("log-view")
        scroller.set_child(self.log)
        self.scroller = scroller
        self.append(scroller)
        self.cancel = Gtk.Button(label=_("Cancel"), halign=Gtk.Align.END)
        self.cancel.set_tooltip_text(_("Stop after the current item"))
        self.cancel.connect("clicked", lambda *_a: self._cancel(on_cancel))
        self.append(self.cancel)

    def _cancel(self, on_cancel) -> None:
        self.cancel.set_sensitive(False)
        self.cancel.set_label(_("Cancelling…"))
        on_cancel()

    def start(self, dry_run: bool, total: int) -> None:
        self.title.set_label(_("Simulating clean (dry run)…") if dry_run else _("Cleaning…"))
        self.bar.set_fraction(0)
        self.bar.set_text(_("0 of {total}").format(total=fmt_size(total)))
        self.current.set_label("")
        self.log.get_buffer().set_text("")
        self.cancel.set_sensitive(True)
        self.cancel.set_label(_("Cancel"))

    def progress(self, done: int, total: int, current: str) -> None:
        self.bar.set_fraction(min(1.0, done / total) if total else 0)
        self.bar.set_text(_("{done} of {total}").format(done=fmt_size(done), total=fmt_size(total)))
        if current:
            self.current.set_label(current)

    def append_line(self, text: str) -> None:
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper())

    def add_result(self, r: ItemResult) -> None:
        extra = f" — {r.messages[0]}" if r.messages else ""
        self.append_line(f"{STATUS_ICON.get(r.status, '?')} {r.label}: {fmt_size(r.freed)}{extra}")


class ResultView(Gtk.Box):
    """Wraps an Adw.StatusPage (a final type in libadwaita 1.1, so not subclassed)."""

    def __init__(self, on_back: Callable[[], None], on_view_log: Callable[[str | None], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.page = Adw.StatusPage(vexpand=True)
        self.append(self.page)
        self.on_view_log = on_view_log
        self.report: CleanReport | None = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp = Adw.Clamp(maximum_size=700)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        clamp.set_child(self.list)
        box.append(clamp)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        log_btn = Gtk.Button(label=_("View log"))
        log_btn.add_css_class("pill")
        log_btn.connect("clicked", lambda *_a: on_view_log(self.report.log_path if self.report else None))
        back = Gtk.Button(label=_("Done"))
        back.add_css_class("pill")
        back.add_css_class("suggested-action")
        back.connect("clicked", lambda *_a: on_back())
        buttons.append(log_btn)
        buttons.append(back)
        box.append(buttons)
        self.page.set_child(box)

    def show(self, report: CleanReport) -> None:
        self.report = report
        if report.dry_run:
            self.page.set_icon_name("system-run-symbolic")
            self.page.set_title(_("Would free {size}").format(size=fmt_size(report.freed)))
            self.page.set_description(_("Dry run: nothing was changed. Turn off “Dry run” in the header bar to clean for real."))
        else:
            ok = all(i.status == "ok" for i in report.items)
            self.page.set_icon_name("emblem-ok-symbolic" if ok else "dialog-warning-symbolic")
            self.page.set_title(_("Freed {size}").format(size=fmt_size(report.freed)))
            desc = _("Sum of removed items: {items}. Free space change on disk: {delta}.").format(
                items=fmt_size(report.freed), delta=fmt_size(report.statvfs_delta))
            if report.cancelled:
                desc += " " + _("Cancelled before all items were processed.")
            desc += " " + _("Permanent deletions cannot be undone.")
            self.page.set_description(desc)
        clear_box(self.list)
        for r in report.items:
            row = Adw.ActionRow(title=esc(f"{STATUS_ICON.get(r.status, '?')}  {r.label}"))
            detail = {"ok": _("done"), "dry-run": _("simulated"), "partial": _("partly done"),
                      "failed": _("failed"), "skipped": _("skipped")}.get(r.status, r.status)
            if r.messages:
                detail += " — " + "; ".join(r.messages[:3])
            row.set_subtitle(esc(detail))
            row.set_subtitle_lines(4)
            size = Gtk.Label(label=fmt_size(r.freed))
            size.add_css_class("size-label")
            row.add_suffix(size)
            self.list.append(row)
        self.list.set_visible(bool(report.items))

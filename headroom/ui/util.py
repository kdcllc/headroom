"""Small UI helpers shared by all views."""

from __future__ import annotations

import threading
import time

from gi.repository import GLib, Gtk

from ..i18n import _

RATING_LABELS = {"safe": _("Safe"), "caution": _("Caution"), "advanced": _("Advanced")}

# Records whether UI callbacks ran on the main thread (checked by UI tests).
callback_threads: list[bool] = []


def idle(fn, *args):
    """Schedule ``fn(*args)`` on the GTK main loop (safe from any thread)."""
    def run():
        callback_threads.append(threading.current_thread() is threading.main_thread())
        fn(*args)
        return GLib.SOURCE_REMOVE
    # DEFAULT, not DEFAULT_IDLE: with software GL (VMs, Xvfb) redraws of a running spinner can keep
    # the loop busy forever, starving idle-priority sources so a scan never reports completion
    GLib.idle_add(run, priority=GLib.PRIORITY_DEFAULT)


class Throttle:
    """Rate-limit progress updates from workers to ~10 per second."""

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def ready(self, force: bool = False) -> bool:
        now = time.monotonic()
        with self._lock:
            if force or now - self._last >= self.interval:
                self._last = now
                return True
        return False


def fmt_size(n: int | None, known: bool = True, approximate: bool = False) -> str:
    if n is None or not known:
        return "—"
    s = GLib.format_size(max(0, int(n)))
    return f"~{s}" if approximate else s


def esc(text: str | None) -> str:
    """Escape text for widgets that always parse markup (Adw 1.1 rows)."""
    return GLib.markup_escape_text(text or "")


def fmt_age(mtime: float) -> str:
    if not mtime:
        return "—"
    days = (time.time() - mtime) / 86400
    if days < 1:
        return _("today")
    if days < 2:
        return _("yesterday")
    if days < 60:
        return _("{n} days ago").format(n=int(days))
    if days < 730:
        return _("{n} months ago").format(n=int(days / 30))
    return _("{n} years ago").format(n=int(days / 365))


def rating_badge(rating: str) -> Gtk.Label:
    lbl = Gtk.Label(label=RATING_LABELS.get(rating, rating))
    lbl.add_css_class("badge")
    lbl.add_css_class(rating)
    lbl.set_valign(Gtk.Align.CENTER)
    lbl.set_tooltip_text({
        "safe": _("Regenerable cache: rebuilt automatically"),
        "caution": _("Visible side effects: re-downloads, lost UI state or extension data"),
        "advanced": _("Possible data loss or system impact"),
    }.get(rating, ""))
    return lbl


def icon_button(icon: str, tooltip: str, **kw) -> Gtk.Button:
    b = Gtk.Button(icon_name=icon, **kw)
    b.set_tooltip_text(tooltip)
    b.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    return b


def show_error(parent: Gtk.Window | None, title: str, body: str) -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
                            buttons=Gtk.ButtonsType.CLOSE, text=title, secondary_text=body)
    dlg.connect("response", lambda d, r: d.destroy())
    dlg.present()


def clear_box(box: Gtk.Widget) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt

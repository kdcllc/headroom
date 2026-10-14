"""Confirmation dialogs whose strength scales with risk, and the running-app guard."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gtk

from ..core.models import CleanPlan
from ..i18n import _, ngettext
from .util import fmt_size

CONFIRM_WORD = "DELETE"


def confirm_clean(parent: Gtk.Window, plan: CleanPlan, on_confirm: Callable[[], None]) -> Gtk.MessageDialog:
    """Gtk.MessageDialog; Cancel is the default. Caution needs a checkbox,
    Advanced also needs typing DELETE; options may add their own checkbox."""
    counts = plan.ratings()
    size = fmt_size(plan.size)
    if plan.dry_run:
        heading = _("Simulate cleaning {size}?").format(size=size)
    else:
        heading = _("Permanently delete {size}?").format(size=size)
    lines = []
    for rating, label in (("safe", _("Safe")), ("caution", _("Caution")), ("advanced", _("Advanced"))):
        if counts[rating]:
            lines.append(ngettext("{n} {label} item", "{n} {label} items", counts[rating]).format(
                n=counts[rating], label=label))
    body = ", ".join(lines) + "."
    if plan.dry_run:
        body += "\n" + _("Dry run is on: nothing will be changed, every action is only logged.")
    elif plan.needs_root:
        body += "\n" + _("System items are included: you will be asked for your password once.")
    trash_items = sum(1 for i in plan.items for e in i.entries if e.action == "trash")
    if trash_items and not plan.dry_run:
        body += "\n" + _("{n} user files will be moved to the Trash.").format(n=trash_items)
    if not plan.dry_run:
        body += "\n" + _("Deleted caches cannot be restored.")

    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                            buttons=Gtk.ButtonsType.NONE, text=heading, secondary_text=body)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    go = dlg.add_button(_("Simulate") if plan.dry_run else _("Delete"), Gtk.ResponseType.ACCEPT)
    if not plan.dry_run:
        go.add_css_class("destructive-action")
    dlg.set_default_response(Gtk.ResponseType.CANCEL)

    area = dlg.get_message_area()
    requirements: list[Callable[[], bool]] = []

    def update(*_a) -> None:
        go.set_sensitive(all(req() for req in requirements))

    if counts["caution"] or counts["advanced"]:
        cb = Gtk.CheckButton(label=_("I understand these items will be rebuilt/re-downloaded or reset state"))
        cb.connect("toggled", update)
        area.append(cb)
        requirements.append(cb.get_active)
    seen = set()
    for item in plan.items:
        text = item.result.option.extra_confirmation
        if text and text not in seen:
            seen.add(text)
            cb = Gtk.CheckButton(label=text)
            cb.connect("toggled", update)
            area.append(cb)
            requirements.append(cb.get_active)
    if counts["advanced"]:
        hint = Gtk.Label(label=_("Advanced items selected. Type {word} to confirm.").format(word=CONFIRM_WORD),
                         xalign=0, wrap=True)
        area.append(hint)
        entry = Gtk.Entry(placeholder_text=CONFIRM_WORD)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Confirmation word")])
        entry.connect("changed", update)
        area.append(entry)
        requirements.append(lambda: entry.get_text().strip() == CONFIRM_WORD)
    update()

    def on_response(d, response):
        d.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            on_confirm()

    dlg.connect("response", on_response)
    dlg.present()
    return dlg


RETRY, SKIP = 1, 2


def running_guard(parent: Gtk.Window, apps: list[str], on_result: Callable[[str], None]) -> Gtk.MessageDialog:
    """Ask to close running apps. Calls on_result('retry'|'skip'|'cancel'). Never kills."""
    names = ", ".join(apps)
    dlg = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.NONE,
        text=ngettext("{apps} is running", "{apps} are running", len(apps)).format(apps=names),
        secondary_text=_("Its caches may be in use. Close {apps} and click Retry, or skip its items.").format(
            apps=names))
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("Skip these items"), SKIP)
    retry = dlg.add_button(_("Retry"), RETRY)
    retry.add_css_class("suggested-action")
    dlg.set_default_response(RETRY)

    def on_response(d, response):
        d.destroy()
        on_result({RETRY: "retry", SKIP: "skip"}.get(response, "cancel"))

    dlg.connect("response", on_response)
    dlg.present()
    return dlg


def ask(parent: Gtk.Window, heading: str, body: str, accept: str, on_accept: Callable[[], None],
        destructive: bool = True) -> Gtk.MessageDialog:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=heading, secondary_text=body)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    b = dlg.add_button(accept, Gtk.ResponseType.ACCEPT)
    if destructive:
        b.add_css_class("destructive-action")
    dlg.set_default_response(Gtk.ResponseType.CANCEL)

    def on_response(d, response):
        d.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            on_accept()
    dlg.connect("response", on_response)
    dlg.present()
    return dlg

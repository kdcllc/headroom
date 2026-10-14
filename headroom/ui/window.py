"""Main window: header bar, sidebar, category pages, action bar, clean flow."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from ..core import paths, planner, privileged, procs, registry, scanner, trash
from ..core.config import Config
from ..core.deleter import Deleter
from ..core.log import CleanLog, latest_log, read_log
from ..core.models import CleanPlan, CleanReport, ScanResult, total_size
from ..i18n import _, ngettext
from .category_view import CategoryPage
from .confirm import ask, confirm_clean, running_guard
from .largefiles_view import FinderPage
from .overview import OverviewPage
from .preview_dialog import PreviewDialog
from .progress_view import ProgressView, ResultView
from .util import Throttle, esc, fmt_size, icon_button, idle, show_error

CATEGORY_INFO = {
    "Code Editors": ("text-editor-symbolic", _("Code Editors"),
                     _("Caches of Cursor and the Visual Studio Code family. Settings, keybindings, snippets and the global state database are never touched.")),
    "Electron Apps": ("application-x-executable-symbolic", _("Electron Apps"),
                      _("Chromium cache folders of Electron apps. Local Storage, IndexedDB, cookies and app data are never offered.")),
    "Browsers": ("web-browser-symbolic", _("Browsers"),
                 _("Browser caches only. History, cookies, sessions, passwords and profiles are never touched.")),
    "Developer Caches": ("applications-engineering-symbolic", _("Developer Caches"),
                         _("Package-manager and toolchain caches. The tool's own clean command is used when it is installed.")),
    "User Caches": ("folder-symbolic", _("User Caches"),
                    _("Thumbnails, shader and font caches, and other folders in ~/.cache.")),
    "System": ("computer-symbolic", _("System"),
               _("Root-level items, cleaned by the system helper after one password prompt.")),
    "Docker": ("network-server-symbolic", _("Docker"),
               _("Docker build cache, images, containers and volumes via the docker CLI. /var/lib/docker is never touched directly.")),
    "Snaps & Flatpak": ("package-x-generic-symbolic", _("Snaps & Flatpak"),
                        _("Disabled snap revisions and unused Flatpak runtimes.")),
    "Trash & Desktop": ("user-trash-symbolic", _("Trash & Desktop"),
                        _("Trash, session logs, recent-files list and desktop metadata.")),
}
SIDEBAR = (["overview"] + list(CATEGORY_INFO) + ["downloads", "large", "junk"])
FINDER_INFO = {"downloads": ("folder-download-symbolic", _("Downloads")),
               "large": ("drive-harddisk-symbolic", _("Large Files")),
               "junk": ("folder-templates-symbolic", _("Project Junk"))}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, config: Config):
        super().__init__(application=app, title=_("Headroom"))
        self.set_default_size(1150, 780)
        self.set_size_request(900, 600)
        self.config = config
        self.registry: registry.Registry | None = None
        self.policy = paths.SafetyPolicy(user_excluded=list(config["excluded_paths"]))
        self.results: dict[str, ScanResult] = {}
        self.by_cleaner: dict[str, list[ScanResult]] = {}
        self.running: dict[str, bool] = {}
        self.selected: set[str] = set()
        self.seen_keys: set[str] = set()
        self.root_sizes: dict[str, int] = {}
        self.scanning = False
        self.cleaning = False
        self.scanned_once = False
        self.helper_available = privileged.helper_installed()
        # background work (scan, finders, clean); workers never touch GTK objects
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="headroom")
        self.scan_cancel = threading.Event()
        self.clean_cancel = threading.Event()
        self.last_trashed: list[tuple[str, str]] = []
        self._return_page = "overview"
        self._skip_cleaners: set[str] = set()

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toasts.set_child(outer)
        outer.append(self._build_header())

        self.leaflet = Adw.Leaflet(vexpand=True, can_navigate_back=True)
        self.leaflet.connect("notify::folded", self._on_folded)
        self.leaflet.connect("notify::visible-child", self._on_folded)
        outer.append(self.leaflet)
        self.sidebar_box = self._build_sidebar()
        self.leaflet.append(self.sidebar_box)
        sep = self.leaflet.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        sep.set_navigatable(False)
        self.content = Gtk.Stack(hexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.leaflet.append(self.content)
        self.leaflet.set_visible_child(self.content)

        self.overview = OverviewPage(self)
        self.content.add_named(self.overview, "overview")
        self.pages: dict[str, CategoryPage] = {}
        for cat, (_icon, label, desc) in CATEGORY_INFO.items():
            page = CategoryPage(self, label, desc)
            self.pages[cat] = page
            self.content.add_named(page, cat)
        if not self.helper_available:
            self.pages["System"].extra_header.append(Gtk.Image(icon_name="dialog-information-symbolic"))
            self.pages["System"].extra_header.set_tooltip_text(privileged_note())
        self.finders: dict[str, FinderPage] = {}
        for mode in ("downloads", "large", "junk"):
            fp = FinderPage(self, mode)
            self.finders[mode] = fp
            self.content.add_named(fp, mode)
        self.progress = ProgressView(on_cancel=self.clean_cancel.set)
        self.content.add_named(self.progress, "progress")
        self.result_view = ResultView(on_back=self._leave_result, on_view_log=self.view_log)
        self.content.add_named(self.result_view, "result")

        outer.append(self._build_action_bar())
        self._install_actions()
        self.update_totals()
        if self.config.get("first_run"):
            self.config.set("first_run", False)
            self._save_config()

    # ------------------------------------------------------------------ build
    def _build_header(self) -> Adw.HeaderBar:
        hb = Adw.HeaderBar()
        self.back_btn = icon_button("go-previous-symbolic", _("Back"))
        self.back_btn.connect("clicked", lambda *_a: self.leaflet.navigate(Adw.NavigationDirection.BACK))
        self.back_btn.set_visible(False)
        hb.pack_start(self.back_btn)
        self.scan_btn = Gtk.Button(label=_("Scan"))
        self.scan_btn.add_css_class("suggested-action")
        self.scan_btn.set_tooltip_text(_("Scan for cleanable data (F5)"))
        self.scan_btn.connect("clicked", lambda *_a: self.start_scan())
        hb.pack_start(self.scan_btn)
        self.spinner = Gtk.Spinner()
        self.spinner.set_tooltip_text(_("Scanning…"))
        hb.pack_start(self.spinner)

        menu = Gio.Menu()
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("View Log"), "win.view-log")
        menu.append(_("About Headroom"), "app.about")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        mb.set_tooltip_text(_("Main menu"))
        mb.update_property([Gtk.AccessibleProperty.LABEL], [_("Main menu")])
        hb.pack_end(mb)
        self.dry_toggle = Gtk.ToggleButton(label=_("Dry run"), active=bool(self.config["dry_run"]))
        self.dry_toggle.set_tooltip_text(_("When on, the whole flow runs but nothing is deleted"))
        self.dry_toggle.connect("toggled", self._on_dry_toggled)
        hb.pack_end(self.dry_toggle)
        self.dry_pill = Gtk.Label(label=_("DRY RUN"), valign=Gtk.Align.CENTER)
        self.dry_pill.add_css_class("dry-run-pill")
        hb.pack_end(self.dry_pill)
        self.dry_pill.set_visible(self.config["dry_run"])
        title = Gtk.Label(label=_("Headroom"))
        title.add_css_class("title")
        hb.set_title_widget(title)
        return hb

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box.set_size_request(230, -1)
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar_sizes: dict[str, Gtk.Label] = {}
        self.sidebar_rows: dict[str, Gtk.ListBoxRow] = {}
        for key in SIDEBAR:
            if key == "overview":
                icon, label = "view-grid-symbolic", _("Overview")
            elif key in CATEGORY_INFO:
                icon, label = CATEGORY_INFO[key][0], CATEGORY_INFO[key][1]
            else:
                icon, label = FINDER_INFO[key]
            row = Gtk.ListBoxRow()
            row.page = key
            b = Gtk.Box(spacing=10)
            for m in ("top", "bottom"):
                getattr(b, f"set_margin_{m}")(4)
            b.append(Gtk.Image(icon_name=icon))
            lbl = Gtk.Label(label=label, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            b.append(lbl)
            size = Gtk.Label(xalign=1)
            size.add_css_class("dim-label")
            size.add_css_class("sidebar-size")
            b.append(size)
            row.set_child(b)
            self.sidebar.append(row)
            self.sidebar_sizes[key] = size
            self.sidebar_rows[key] = row
        def header(row, before):
            if before is not None and row.page in ("Code Editors", "downloads"):
                if row.get_header() is None:
                    sep = Gtk.Separator()
                    sep.set_margin_top(6)
                    sep.set_margin_bottom(6)
                    row.set_header(sep)
            else:
                row.set_header(None)
        self.sidebar.set_header_func(header)
        self.sidebar.connect("row-activated", lambda _lb, row: self.show_page(row.page))
        self.sidebar.select_row(self.sidebar_rows["overview"])
        box.set_child(self.sidebar)
        return box

    def _build_action_bar(self) -> Gtk.ActionBar:
        bar = Gtk.ActionBar()
        self.total_label = Gtk.Label(xalign=0)
        self.total_label.add_css_class("selection-total")
        bar.pack_start(self.total_label)
        self.clean_btn = Gtk.Button(label=_("Clean…"))
        self.clean_btn.add_css_class("destructive-action")
        self.clean_btn.connect("clicked", lambda *_a: self.on_clean())
        bar.pack_end(self.clean_btn)
        self.preview_btn = Gtk.Button(label=_("Preview…"))
        self.preview_btn.connect("clicked", lambda *_a: self.on_preview())
        bar.pack_end(self.preview_btn)
        self.select_none_btn = Gtk.Button(label=_("Select none"))
        self.select_none_btn.add_css_class("flat")
        self.select_none_btn.connect("clicked", lambda *_a: self.set_selected(list(self.selected), False))
        bar.pack_end(self.select_none_btn)
        self.action_bar = bar
        return bar

    def _install_actions(self) -> None:
        for name, cb in (("view-log", lambda *_a: self.view_log(None)),
                         ("undo-trash", lambda *_a: self.undo_trash()),
                         ("scan", lambda *_a: self.start_scan())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

    # --------------------------------------------------------------- navigation
    def show_page(self, key: str) -> None:
        if self.cleaning:
            return
        self.content.set_visible_child_name(key)
        row = self.sidebar_rows.get(key)
        if row is not None and self.sidebar.get_selected_row() is not row:
            self.sidebar.select_row(row)
        if self.leaflet.get_folded():
            self.leaflet.set_visible_child(self.content)
        if key in self.finders and key == "downloads" and not self.finders[key].found and not self.finders[key].busy:
            self.finders[key].start()

    def _on_folded(self, *_a) -> None:
        self.back_btn.set_visible(self.leaflet.get_folded()
                                  and self.leaflet.get_visible_child() is self.content)

    # ---------------------------------------------------------------- selection
    def visible_result(self, r: ScanResult) -> bool:
        return self.config["show_advanced"] or r.rating != "advanced"

    def set_selected(self, keys: list[str], value: bool) -> None:
        touched = set()
        for key in keys:
            r = self.results.get(key)
            if r is None:
                continue
            if value and (not r.selectable or not self.visible_result(r)):
                continue
            (self.selected.add if value else self.selected.discard)(key)
            touched.add(r.cleaner.id)
        for cid in touched:
            for page in self.pages.values():
                row = page.app_rows.get(cid)
                if row is not None:
                    row.refresh()
        self.update_totals()

    def select_all_safe(self) -> None:
        keys = [k for k, r in self.results.items()
                if r.rating == "safe" and r.selectable and not self.running.get(r.cleaner.id)]
        self.set_selected(keys, True)
        self.toast(ngettext("{n} Safe item selected", "{n} Safe items selected", len(keys)).format(n=len(keys)))

    def selected_results(self) -> list[ScanResult]:
        return [self.results[k] for k in sorted(self.selected)
                if k in self.results and self.visible_result(self.results[k])]

    def update_totals(self) -> None:
        sel = self.selected_results()
        size = total_size(sel)
        verb = _("Would free") if self.config["dry_run"] else _("Selected")
        self.total_label.set_label(ngettext("{verb}: {n} item · {size}", "{verb}: {n} items · {size}",
                                            len(sel)).format(verb=verb, n=len(sel), size=fmt_size(size)))
        busy = self.scanning or self.cleaning
        self.clean_btn.set_sensitive(bool(sel) and not busy)
        self.preview_btn.set_sensitive(bool(sel) and not busy)
        self.select_none_btn.set_sensitive(bool(sel) and not self.cleaning)
        self.scan_btn.set_sensitive(not self.cleaning)
        self.scan_btn.set_label(_("Stop") if self.scanning else _("Scan"))
        self.clean_btn.set_label(_("Simulate…") if self.config["dry_run"] else _("Clean…"))
        for cat, page in self.pages.items():
            total = page.total
            self.sidebar_sizes[cat].set_label(fmt_size(total) if total else "")

    def _on_dry_toggled(self, btn: Gtk.ToggleButton) -> None:
        self.config.set("dry_run", btn.get_active())
        self._save_config()
        self.dry_pill.set_visible(btn.get_active())
        self.update_totals()

    # -------------------------------------------------------------------- scan
    def submit(self, fn: Callable[[], None]) -> None:
        def wrapped():
            try:
                fn()
            except Exception as exc:  # never lose a worker error silently
                import traceback
                traceback.print_exc()
                idle(show_error, self, _("Unexpected error"), str(exc))
        self.executor.submit(wrapped)

    def start_scan(self) -> None:
        if self.cleaning:
            return
        if self.scanning:
            self.scan_cancel.set()
            return
        self.scanning = True
        self.scan_cancel = threading.Event()
        self.spinner.start()
        self.update_totals()
        cancel = self.scan_cancel
        config = dict(self.config)
        root_sizes = dict(self.root_sizes)
        helper = self.helper_available
        throttle = Throttle()

        def work():
            policy = paths.SafetyPolicy(user_excluded=list(config["excluded_paths"]))
            reg = registry.load_registry(policy=policy)
            idle(self._on_registry, reg)
            ctx = scanner.ScanContext(policy=reg.policy, config=config, cancel=cancel,
                                      helper_available=helper, root_sizes=root_sizes)

            def on_cleaner(c, results, running):
                idle(self._on_cleaner, c, results, running)

            def progress(label, n, total):
                if throttle.ready(n == total):
                    idle(self._on_scan_progress, label, n, total)
            scanner.scan(reg, ctx, on_cleaner=on_cleaner, progress=progress, max_workers=3)
            idle(self._on_scan_done, cancel.is_set())
        self.submit(work)

    def _on_registry(self, reg: registry.Registry) -> None:
        self.registry = reg
        self.policy = reg.policy
        if reg.errors:
            self.toast(_("{n} cleaner definition(s) were skipped — see the terminal").format(n=len(reg.errors)))
            for e in reg.errors:
                print("headroom: registry:", e)

    def _on_scan_progress(self, label: str, n: int, total: int) -> None:
        self.spinner.set_tooltip_text(_("Scanning {label} ({n}/{total})").format(label=label, n=n, total=total))

    def _on_cleaner(self, c, results: list[ScanResult], running: bool) -> None:
        old = self.by_cleaner.get(c.id, [])
        new_keys = {r.key for r in results}
        for r in old:
            if r.key not in new_keys:
                self.results.pop(r.key, None)
                self.selected.discard(r.key)
        self.by_cleaner[c.id] = results
        self.running[c.id] = running
        for r in results:
            self.results[r.key] = r
            if r.key not in self.seen_keys:
                self.seen_keys.add(r.key)
                # pre-select only Safe items whose app is not running
                if r.rating == "safe" and r.selectable and not running and r.size_known:
                    self.selected.add(r.key)
            if not r.selectable:
                self.selected.discard(r.key)
        page = self.pages.get(c.category)
        if page is not None:
            page.set_cleaner(c, results, running)
        self.update_totals()

    def _on_scan_done(self, cancelled: bool) -> None:
        self.scanning = False
        self.scanned_once = True
        self.spinner.stop()
        self.spinner.set_tooltip_text(_("Scanning…"))
        for page in self.pages.values():
            page.refresh()
        self.overview.refresh_disks()
        self.overview.update(list(self.results.values()))
        self.update_totals()
        total = sum(p.total for p in self.pages.values())
        self.toast(_("Scan stopped") if cancelled else
                   _("Scan complete: {size} reclaimable").format(size=fmt_size(total)))

    def refresh_visibility(self) -> None:
        for key in list(self.selected):
            r = self.results.get(key)
            if r is not None and not self.visible_result(r):
                self.selected.discard(key)
        for page in self.pages.values():
            page.refresh()
        self.overview.update(list(self.results.values()))
        self.update_totals()

    def scan_root_sizes(self) -> None:
        if self.scanning or self.cleaning:
            return

        def work():
            try:
                sizes = privileged.scan_sizes()
            except privileged.HelperError as exc:
                idle(self.toast, str(exc))
                return
            idle(self._on_root_sizes, sizes)
        self.submit(work)

    def _on_root_sizes(self, sizes: dict[str, int]) -> None:
        self.root_sizes = sizes
        self.toast(_("System items measured"))
        self.start_scan()

    # ----------------------------------------------------------- guard & plan
    def _guard(self, results: list[ScanResult], then: Callable[[set[str]], None]) -> None:
        """Running-app guard: Retry / Skip / Cancel. Never kills processes."""
        need = {r.cleaner.id: r.cleaner for r in results if r.option.requires_app_closed}
        if not need:
            then(set())
            return
        proc_list = list(procs.iter_procs())  # is_running filters by user per cleaner
        running = [c for c in need.values() if procs.is_running(c.running, procs=proc_list)]
        if not running:
            then(set())
            return

        def on_result(choice: str) -> None:
            if choice == "retry":
                self._guard(results, then)
            elif choice == "skip":
                then({c.id for c in running})
        running_guard(self, [c.label for c in running], on_result)

    def _build_plan(self, skip: set[str]) -> CleanPlan:
        return planner.build_plan(self.selected_results(), dry_run=bool(self.config["dry_run"]),
                                  excludes=self.config["preview_excludes"], skip_cleaners=skip)

    def on_preview(self) -> None:
        sel = self.selected_results()

        def go(skip: set[str]) -> None:
            plan = self._build_plan(skip)
            if not plan.items:
                self.toast(_("Nothing to preview"))
                return

            def closed(excluded: set[str]) -> None:
                self.config.set("preview_excludes", sorted(excluded))
                self._save_config()

            self._preview = PreviewDialog(self, plan, set(self.config["preview_excludes"]), closed,
                                          on_clean=lambda: self._confirm_and_clean(skip))
            self._preview.present()
        self._guard(sel, go)

    def on_clean(self) -> None:
        self._guard(self.selected_results(), self._confirm_and_clean)

    def _confirm_and_clean(self, skip: set[str]) -> None:
        plan = self._build_plan(skip)
        if not plan.items:
            self.toast(_("Nothing to clean"))
            return
        confirm_clean(self, plan, lambda: self.clean_plan(plan, rescan=True))

    # ------------------------------------------------------------------- clean
    def clean_plan(self, plan: CleanPlan, policy: paths.SafetyPolicy | None = None,
                   after: Callable[[CleanReport], None] | None = None, rescan: bool = False) -> None:
        """Run an already-confirmed plan on a worker and show progress."""
        if self.cleaning or self.scanning:
            self.toast(_("Wait for the current scan to finish"))
            return
        self.cleaning = True
        self.clean_cancel.clear()
        self._return_page = self.content.get_visible_child_name() or "overview"
        self.sidebar.set_sensitive(False)
        self.progress.start(plan.dry_run, plan.size)
        self.content.set_visible_child_name("progress")
        self.update_totals()
        use_policy = policy or self.policy

        def work():
            log = CleanLog()
            d = Deleter(use_policy, dry_run=plan.dry_run, log=log, cancel=self.clean_cancel,
                        progress=lambda done, total, cur: idle(self.progress.progress, done, total, cur))
            try:
                report = d.run(plan, on_item=lambda r: idle(self.progress.add_result, r))
            finally:
                log.close()
            idle(self._on_clean_done, report, plan, after, rescan, use_policy)
        self.submit(work)

    def _on_clean_done(self, report: CleanReport, plan: CleanPlan, after, rescan: bool, policy) -> None:
        self.cleaning = False
        self.sidebar.set_sensitive(True)
        self.result_view.show(report)
        self.content.set_visible_child_name("result")
        self.overview.refresh_disks()
        if report.trashed:
            self.last_trashed = list(report.trashed)
        self._last_report = report
        if after:
            after(report)
        if report.trash_failed and not report.dry_run:
            self._offer_delete_instead(report, policy, after)
        if rescan and not report.dry_run:
            self._rescan_cleaners({i.result.cleaner.id for i in plan.items})
        self.update_totals()

    def _offer_delete_instead(self, report: CleanReport, policy, after) -> None:
        entries = report.trash_failed
        size = sum(e.size for e in entries)

        def go():
            from ..core.models import CleanerDef, CleanPlan, Option, PlanItem
            opt = Option(id="finder.delete_fallback", label=_("Permanent delete"), description="",
                         rating="caution")
            c = CleanerDef(id="finder", label=_("Files that could not be trashed"), category="Finder",
                           options=[opt])
            res = ScanResult(key="trash-fallback", option=opt, cleaner=c, label=c.label, size=size)
            for e in entries:
                e.action = "delete"
            self.clean_plan(CleanPlan([PlanItem(res, entries, [], [])], dry_run=False), policy, after)
        ask(self, ngettext("{n} item could not be moved to the Trash",
                           "{n} items could not be moved to the Trash", len(entries)).format(n=len(entries)),
            _("This happens on some removable drives. Delete {size} permanently instead?").format(
                size=fmt_size(size)),
            _("Delete Permanently"), go)

    def _rescan_cleaners(self, cleaner_ids: set[str]) -> None:
        reg = self.registry
        if reg is None:
            return
        config = dict(self.config)
        helper = self.helper_available

        def work():
            ctx = scanner.ScanContext(policy=reg.policy, config=config, helper_available=helper,
                                      known_dirs=reg.known_static_dirs())
            run = scanner.running_map(reg)
            for c in reg.cleaners:
                if c.id not in cleaner_ids:
                    continue
                results = []
                for o in c.options:
                    try:
                        results.extend(scanner.scan_option(o, c, ctx))
                    except Exception:
                        pass
                idle(self._on_cleaner, c, results, run.get(c.id, False))
            idle(self.overview.update, list(self.results.values()))
        self.submit(work)

    def _leave_result(self) -> None:
        self.show_page(self._return_page if self._return_page not in ("progress", "result") else "overview")
        report = getattr(self, "_last_report", None)
        if report is None:
            return
        if report.dry_run:
            self.toast(_("Dry run: would free {size}").format(size=fmt_size(report.freed)))
        elif report.trashed:
            toast = Adw.Toast(title=esc(ngettext("Moved {n} item to Trash", "Moved {n} items to Trash",
                                                 len(report.trashed)).format(n=len(report.trashed))))
            toast.set_button_label(_("Undo"))
            toast.set_action_name("win.undo-trash")
            toast.set_timeout(10)
            self.toasts.add_toast(toast)
        else:
            self.toast(_("Freed {size} — permanent deletions cannot be undone").format(
                size=fmt_size(report.freed)))

    def undo_trash(self) -> None:
        restored = 0
        errors = []
        for original, trashed in self.last_trashed:
            try:
                trash.restore(trashed)
                restored += 1
            except OSError as exc:
                errors.append(f"{original}: {exc}")
        self.last_trashed = []
        self.toast(ngettext("Restored {n} item", "Restored {n} items", restored).format(n=restored))
        if errors:
            show_error(self, _("Some items could not be restored"), "\n".join(errors[:10]))
        for fp in self.finders.values():
            if fp.found:
                fp.start()

    # -------------------------------------------------------------------- misc
    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=esc(text)))

    def _save_config(self) -> None:
        try:
            self.config.save()
        except OSError as exc:
            print("headroom: could not save config:", exc)

    def has_tool(self, name: str) -> bool:
        return shutil.which(name) is not None

    def launch(self, argv: list[str]) -> None:
        try:
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            show_error(self, _("Could not start {app}").format(app=argv[0]), exc.message)

    def on_preferences_changed(self) -> None:
        self.dry_toggle.set_active(bool(self.config["dry_run"]))
        self.policy.user_excluded = list(self.config["excluded_paths"])
        self.policy.invalidate()
        self.refresh_visibility()

    def view_log(self, path: str | None) -> None:
        path = path or latest_log()
        win = Gtk.Window(transient_for=self, modal=False, title=_("Clean log"),
                         default_width=900, default_height=560)
        scroller = Gtk.ScrolledWindow()
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.add_css_class("log-view")
        if not path:
            text = _("No clean has been run yet.")
        else:
            lines = [path, ""]
            for rec in read_log(path):
                what = rec.get("path") or " ".join(rec.get("argv") or []) or ""
                err = f"  ! {rec['error']}" if rec.get("error") else ""
                lines.append(f"{rec.get('ts', '')}  {rec.get('result', ''):8} {rec.get('option', ''):32} "
                             f"{fmt_size(rec.get('bytes', 0)):>10}  {what}{err}")
            text = "\n".join(lines)
        tv.get_buffer().set_text(text)
        scroller.set_child(tv)
        win.set_child(scroller)
        win.present()

    def shutdown(self) -> None:
        self.scan_cancel.set()
        self.clean_cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)


def privileged_note() -> str:
    return _("System items need the helper: install the .deb (or run `sudo make install-helper`) "
             "to enable system cleaning.")

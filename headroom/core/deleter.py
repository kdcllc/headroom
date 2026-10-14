"""Execute a :class:`CleanPlan`: delete / trash / truncate, run commands,
hand root actions to the privileged helper. Honors dry-run and cancellation.

Every entry is re-validated right before it is touched (re-``lstat``,
allow/deny re-check, same inode and filesystem as at scan time) to close the
time-of-check/time-of-use window. Removal works relative to a verified
parent directory file descriptor and never follows symlinks.
"""

from __future__ import annotations

import os
import shutil
import stat
import threading
import time
from collections.abc import Callable
from typing import Any

from . import commands, paths, privileged, trash
from .log import CleanLog
from .models import CleanPlan, CleanReport, Entry, ItemResult, PlanItem

XBEL_EMPTY = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<xbel version="1.0"\n'
              '      xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"\n'
              '      xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info"\n'
              '>\n</xbel>\n')

ProgressFn = Callable[[int, int, str], None]


class SafetyError(Exception):
    pass


def assert_rmtree_safe() -> None:
    """Startup check required by the spec (we use our own fd-based remover,
    but refuse to run on a platform where even shutil.rmtree is unsafe)."""
    if not shutil.rmtree.avoids_symlink_attacks:
        raise SafetyError("shutil.rmtree is not symlink-attack safe on this platform")


class _Stats:
    __slots__ = ("freed", "deleted", "errors", "messages")

    def __init__(self) -> None:
        self.freed = 0
        self.deleted = 0
        self.errors = 0
        self.messages: list[str] = []

    def error(self, msg: str) -> None:
        self.errors += 1
        if len(self.messages) < 20:
            self.messages.append(msg)


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _freed_by(st: os.stat_result) -> int:
    # removing one of several hard links frees nothing
    if stat.S_ISDIR(st.st_mode) or st.st_nlink <= 1:
        return st.st_blocks * 512
    return 0


def _rm_at(pfd: int, name: str, dev: int, stats: _Stats, depth: int = 0) -> bool:
    """Remove *name* inside directory fd *pfd*. Never follows symlinks."""
    try:
        st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError as exc:
        stats.error(f"{name}: {exc.strerror}")
        return False
    if not stat.S_ISDIR(st.st_mode):
        try:
            os.unlink(name, dir_fd=pfd)
        except FileNotFoundError:
            return True
        except OSError as exc:
            stats.error(f"{name}: {exc.strerror}")
            return False
        stats.freed += _freed_by(st)
        stats.deleted += 1
        return True
    if st.st_dev != dev:
        stats.error(f"{name}: on another filesystem, skipped")
        return False
    if depth > 400:
        stats.error(f"{name}: tree too deep")
        return False
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=pfd)
    except OSError as exc:
        stats.error(f"{name}: {exc.strerror}")
        return False
    ok = True
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            stats.error(f"{name}: changed while deleting")
            return False
        with os.scandir(fd) as it:
            names = [e.name for e in it]
        for child in names:
            ok = _rm_at(fd, child, dev, stats, depth + 1) and ok
    except OSError as exc:
        stats.error(f"{name}: {exc.strerror}")
        ok = False
    finally:
        os.close(fd)
    if not ok:
        return False
    try:
        os.rmdir(name, dir_fd=pfd)
    except OSError as exc:
        stats.error(f"{name}: {exc.strerror}")
        return False
    stats.freed += st.st_blocks * 512
    return True


class Deleter:
    def __init__(self, policy: paths.SafetyPolicy, *, dry_run: bool = True,
                 log: CleanLog | None = None, cancel: threading.Event | None = None,
                 progress: ProgressFn | None = None,
                 trash_func: Callable[[str], str | None] | None = None,
                 root_runner: Callable[..., list[dict[str, Any]]] | None = None,
                 run_command: Callable[..., commands.CommandResult] | None = None):
        self.policy = policy
        self.dry_run = dry_run
        self.log = log
        self.cancel = cancel or threading.Event()
        self.progress = progress
        self.trash_func = trash_func or trash.trash
        self.root_runner = root_runner or privileged.run_plan
        self.run_command = run_command or commands.run
        self._done = 0
        self._total = 0
        self._last_progress = 0.0

    # -- progress / logging ---------------------------------------------------
    def _report(self, current: str, force: bool = False) -> None:
        if not self.progress:
            return
        now = time.monotonic()
        if force or now - self._last_progress >= 0.1:  # ~10 updates/s
            self._last_progress = now
            self.progress(self._done, self._total, current)

    def _log(self, option_id: str, result: str, **kw: Any) -> None:
        if self.log:
            self.log.write(option_id, result, **kw)

    # -- validation -------------------------------------------------------------
    def validate(self, e: Entry) -> tuple[os.stat_result | None, str]:
        """Re-check an entry right before acting on it."""
        verdict = self.policy.check(e.path)
        if not verdict:
            return None, verdict.reason
        if not paths.is_within(e.path, e.root):
            return None, "no longer inside its cleaning root"
        try:
            st = os.lstat(e.path)
        except FileNotFoundError:
            return None, "already gone"
        except OSError as exc:
            return None, exc.strerror or str(exc)
        kind = ("link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode)
                else "file" if stat.S_ISREG(st.st_mode) else "other")
        if kind != e.kind:
            return None, f"changed since scan (was {e.kind}, now {kind})"
        if e.ino and e.kind == "dir" and (st.st_dev, st.st_ino) != (e.dev, e.ino):
            return None, "replaced since scan"
        if kind == "other":
            return None, "not a regular file or directory"
        try:
            root_dev = os.lstat(os.path.realpath(e.root)).st_dev
        except OSError:
            root_dev = st.st_dev
        if st.st_dev != root_dev and not e.root.startswith("/media/"):
            return None, "on another filesystem than its cleaning root"
        return st, ""

    def _open_parent(self, e: Entry) -> int:
        parent = os.path.dirname(os.path.abspath(e.path))
        pfd = os.open(parent, _DIR_FLAGS)
        # authoritative location of what we actually opened
        real = os.readlink(f"/proc/self/fd/{pfd}")
        root_real = os.path.realpath(e.root)
        if paths.resolved_candidate(e.path) == root_real:
            ok = real == os.path.dirname(root_real)  # a file allow-root, e.g. ~/.xsession-errors
        else:
            ok = paths.is_within(real, root_real)
        if not ok:
            os.close(pfd)
            raise SafetyError(f"parent of {e.path} resolved outside its root ({real})")
        return pfd

    # -- actions --------------------------------------------------------------------
    def _delete_entry(self, e: Entry, item: PlanItem, stats: _Stats) -> None:
        oid = item.result.option.id
        st, reason = self.validate(e)
        if st is None:
            if reason == "already gone":
                self._log(oid, "skipped", path=e.path, error=reason)
                return
            stats.error(f"{e.path}: {reason}")
            self._log(oid, "refused", path=e.path, error=reason)
            return
        if self.dry_run:
            stats.freed += e.size
            stats.deleted += e.count
            self._log(oid, "dry-run", path=e.path, bytes_=e.size, action=e.action)
            return
        before_err = stats.errors
        before_freed = stats.freed
        try:
            if e.action == "trash":
                self._trash(e, item, stats)
            elif e.action == "truncate":
                self._truncate(e, st, stats, b"")
            elif e.action == "reset_xbel":
                self._truncate(e, st, stats, XBEL_EMPTY.encode())
            else:
                pfd = self._open_parent(e)
                try:
                    _rm_at(pfd, os.path.basename(e.path), st.st_dev, stats)
                finally:
                    os.close(pfd)
                for comp in e.companions:
                    ce = Entry(path=comp, root=e.root, kind="file")
                    cst, _ = self.validate(ce)
                    if cst is not None:
                        cfd = self._open_parent(ce)
                        try:
                            _rm_at(cfd, os.path.basename(comp), cst.st_dev, stats)
                        finally:
                            os.close(cfd)
        except trash.TrashError as exc:
            stats.error(f"{e.path}: {exc}")
            self.report.trash_failed.append(e)
        except (OSError, SafetyError) as exc:
            stats.error(f"{e.path}: {exc}")
        ok = stats.errors == before_err
        self._log(oid, "ok" if ok else "error", path=e.path, bytes_=stats.freed - before_freed,
                  action=e.action, error=None if ok else "; ".join(stats.messages[-3:]))

    def _truncate(self, e: Entry, st: os.stat_result, stats: _Stats, content: bytes) -> None:
        if not stat.S_ISREG(st.st_mode):
            raise SafetyError("truncate target is not a regular file")
        pfd = self._open_parent(e)
        try:
            fd = os.open(os.path.basename(e.path), os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                         | getattr(os, "O_CLOEXEC", 0), dir_fd=pfd)
        finally:
            os.close(pfd)
        try:
            fst = os.fstat(fd)
            if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode):
                raise SafetyError("file changed before truncation")
            os.ftruncate(fd, 0)
            if content:
                os.write(fd, content)
            stats.freed += max(0, st.st_blocks * 512 - len(content))
            stats.deleted += 1
        finally:
            os.close(fd)

    def _trash(self, e: Entry, item: PlanItem, stats: _Stats) -> None:
        dest = self.trash_func(e.path)
        stats.freed += e.size
        stats.deleted += 1
        if dest:
            self.report.trashed.append((e.path, dest))

    # -- main -------------------------------------------------------------------------
    def run(self, plan: CleanPlan, *, on_item: Callable[[ItemResult], None] | None = None) -> CleanReport:
        self.dry_run = plan.dry_run or self.dry_run
        self.policy.invalidate()
        self.report = CleanReport(dry_run=self.dry_run)
        self.report.log_path = self.log.path if self.log else None
        self.report.statvfs_before = free_space(plan)
        self._total = max(plan.size, 1)
        self._done = 0
        self._log("_run", "start", dry_run=self.dry_run, items=len(plan.items), bytes_=plan.size)

        root_items: list[PlanItem] = []
        for item in plan.items:
            if self.cancel.is_set():
                self.report.cancelled = True
                break
            if item.root_actions:
                root_items.append(item)
                continue
            res = self._run_user_item(item)
            self.report.items.append(res)
            if on_item:
                on_item(res)

        if root_items and not self.cancel.is_set():
            for res in self._run_root_items(root_items):
                self.report.items.append(res)
                if on_item:
                    on_item(res)
        elif root_items:
            self.report.cancelled = True

        self.report.statvfs_after = free_space(plan)
        self._log("_run", "end", bytes_=self.report.freed, cancelled=self.report.cancelled)
        self._report("", force=True)
        return self.report

    def _run_user_item(self, item: PlanItem) -> ItemResult:
        r = item.result
        stats = _Stats()
        self._report(r.label, force=True)
        for argv in item.commands:
            self._report(" ".join(argv), force=True)
            if self.dry_run:
                self._log(r.option.id, "dry-run", argv=argv, bytes_=r.size)
                continue
            cr = self.run_command(argv, timeout=commands.COMMANDS[r.option.command].timeout
                                  if r.option.command in commands.COMMANDS else 600)
            if not cr.ok and not (r.option.command == "gradle.stop"):
                stats.error(f"{os.path.basename(argv[0])} exited {cr.returncode}: "
                            f"{(cr.stderr or cr.stdout).strip()[-300:]}")
            self._log(r.option.id, "ok" if cr.ok else "error", argv=argv,
                      bytes_=r.size if cr.ok else 0, error=None if cr.ok else cr.stderr[-500:])
        if item.commands and not item.entries:
            # the tool reports nothing structured; estimate from the scanned size
            stats.freed += r.size if stats.errors == 0 else 0
        for e in item.entries:
            self._report(e.path)
            self._delete_entry(e, item, stats)
            self._done += e.size
        if not item.entries:
            self._done += item.size
        status = "dry-run" if self.dry_run else (
            "ok" if stats.errors == 0 else "partial" if stats.deleted else "failed")
        return ItemResult(key=r.key, label=f"{r.cleaner.label} › {r.label}", status=status, freed=stats.freed,
                          deleted=stats.deleted, errors=stats.errors, messages=stats.messages)

    def _run_root_items(self, items: list[PlanItem]) -> list[ItemResult]:
        actions = [a for it in items for a in it.root_actions]
        self._report("Waiting for authentication…", force=True)
        if self.dry_run:
            for it in items:
                for a in it.root_actions:
                    self._log(it.result.option.id, "dry-run", argv=["pkexec", privileged.HELPER_PATH,
                              "--plan-stdin"], action=a, bytes_=it.size)
            return [ItemResult(key=it.result.key, label=f"{it.result.cleaner.label} › {it.result.label}", status="dry-run",
                               freed=it.size) for it in items]
        try:
            lines = self.root_runner(actions)
        except privileged.HelperError as exc:
            for it in items:
                self._log(it.result.option.id, "error", error=str(exc))
            return [ItemResult(key=it.result.key, label=it.result.label, status="failed",
                               errors=1, messages=[str(exc)]) for it in items]
        by_id = {}
        for line in lines:
            by_id.setdefault(line.get("id"), []).append(line)
            self._log(f"root:{line.get('id')}", "ok" if line.get("ok") else "error",
                      bytes_=int(line.get("freed_bytes") or 0), error=line.get("stderr_tail"),
                      helper=line)
        out = []
        for it in items:
            res = ItemResult(key=it.result.key, label=f"{it.result.cleaner.label} › {it.result.label}")
            for a in it.root_actions:
                got = by_id.get(a["id"], [])
                if not got:
                    res.errors += 1
                    res.messages.append(f"{a['id']}: no result from helper")
                for line in got:
                    res.freed += int(line.get("freed_bytes") or 0)
                    if not line.get("ok"):
                        res.errors += 1
                        res.messages.append(f"{a['id']}: {line.get('error') or line.get('stderr_tail') or 'failed'}")
            res.status = "ok" if res.errors == 0 else "failed"
            self._done += it.size
            out.append(res)
        return out


def free_space(plan: CleanPlan | None = None) -> dict[str, int]:
    """Free bytes per filesystem touched by the plan (keyed by a path on it)."""
    candidates = ["/", paths.home()]
    if plan:
        for it in plan.items:
            for e in it.entries[:1]:
                candidates.append(e.root)
    out: dict[str, int] = {}
    devs = set()
    for c in candidates:
        try:
            dev = os.stat(c).st_dev
            if dev in devs:
                continue
            devs.add(dev)
            st = os.statvfs(c)
            out[c] = st.f_bavail * st.f_frsize
        except OSError:
            pass
    return out

"""Read-only scanning: du-style sizing and target expansion.

Sizes are real disk usage (``st_blocks * 512`` from ``lstat``), de-duplicated
by ``(st_dev, st_ino)``. Symlinks are never followed and other filesystems
are never entered.
"""

from __future__ import annotations

import fnmatch
import os
import stat
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from . import commands, paths, procs, selectors
from .models import CleanerDef, Entry, Option, ScanResult, Target
from .registry import Registry

MAX_WORKERS = 4


class Cancelled(Exception):
    pass


@dataclass
class Usage:
    disk: int = 0
    apparent: int = 0
    count: int = 0
    newest: float = 0.0
    errors: int = 0


def du(path: str, *, seen: set[tuple[int, int]] | None = None, dev: int | None = None,
       cancel: threading.Event | None = None) -> Usage:
    """Disk usage of *path* (file or tree). Never follows symlinks or crosses devices."""
    u = Usage()
    seen = seen if seen is not None else set()
    try:
        st = os.lstat(path)
    except OSError:
        u.errors += 1
        return u
    if dev is None:
        dev = st.st_dev
    if st.st_dev != dev:
        return u
    _account(u, st, seen)
    if not stat.S_ISDIR(st.st_mode):
        return u
    stack = [path]
    n = 0
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            u.errors += 1
            continue
        with it:
            for e in it:
                n += 1
                if cancel is not None and n % 512 == 0 and cancel.is_set():
                    raise Cancelled()
                try:
                    est = e.stat(follow_symlinks=False)
                except OSError:
                    u.errors += 1
                    continue
                if est.st_dev != dev:
                    continue  # mount point below us: don't cross
                _account(u, est, seen)
                if stat.S_ISDIR(est.st_mode):
                    stack.append(e.path)
    return u


def _account(u: Usage, st: os.stat_result, seen: set[tuple[int, int]]) -> None:
    key = (st.st_dev, st.st_ino)
    u.newest = max(u.newest, st.st_mtime)
    if key in seen:
        return
    seen.add(key)
    u.disk += st.st_blocks * 512
    u.apparent += st.st_size
    if not stat.S_ISDIR(st.st_mode):
        u.count += 1


# --------------------------------------------------------------------------
# glob without following symlinks
# --------------------------------------------------------------------------

def _match(name: str, pat: str) -> bool:
    if name.startswith(".") and not pat.startswith("."):
        return False
    return fnmatch.fnmatchcase(name, pat)


def safe_glob(pattern: str, policy: paths.SafetyPolicy | None = None) -> list[str]:
    """Expand a glob pattern without following symlinks for wildcard parts.

    Literal components may be symlinks (``~/snap/x/current``) only when they
    resolve inside the same allow root; the result then uses the resolved path.
    ``**`` matches zero or more directories.
    """
    if not os.path.isabs(pattern):
        return []
    parts = [p for p in pattern.split("/") if p]
    results: list[str] = []

    def walk(base: str, idx: int) -> None:
        if idx == len(parts):
            results.append(base)
            return
        part = parts[idx]
        if part == "**":
            walk(base, idx + 1)
            try:
                with os.scandir(base) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            walk(e.path, idx)
            except OSError:
                pass
            return
        if not paths.has_glob(part):
            nxt = os.path.join(base, part)
            try:
                st = os.lstat(nxt)
            except OSError:
                return
            if stat.S_ISLNK(st.st_mode):
                if idx == len(parts) - 1:
                    results.append(nxt)  # final component: caller decides (refused)
                    return
                if policy is None:
                    return
                real = os.path.realpath(nxt)
                root = policy.root_for(nxt)
                if root is None or not paths.is_within(real, root) or policy.is_denied(real):
                    return
                walk(real, idx + 1)
                return
            walk(nxt, idx + 1)
            return
        try:
            with os.scandir(base) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        last = idx == len(parts) - 1
        for e in entries:
            if not _match(e.name, part):
                continue
            if last:
                results.append(e.path)
            elif e.is_dir(follow_symlinks=False):
                walk(e.path, idx + 1)

    walk("/", 0)
    return list(dict.fromkeys(results))


# --------------------------------------------------------------------------
# scanning options
# --------------------------------------------------------------------------

@dataclass
class ScanContext:
    policy: paths.SafetyPolicy
    config: dict[str, Any] = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    helper_available: bool = False
    known_dirs: set[str] = field(default_factory=set)
    now: float = field(default_factory=time.time)
    run_probes: bool = True
    root_sizes: dict[str, int] = field(default_factory=dict)  # from helper --scan


def _excluded(path: str, base: str, patterns: Iterable[str]) -> bool:
    name = os.path.basename(path)
    rel = os.path.relpath(path, base)
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(rel, p) for p in patterns)


def _children(d: str) -> list[str]:
    try:
        with os.scandir(d) as it:
            return sorted(e.path for e in it)
    except OSError:
        return []


def _resolve_base(path: str, policy: paths.SafetyPolicy) -> str | None:
    """A matched target directory/file, accepted only if it is safe.

    A target that is itself a symlink is refused (we would otherwise clean
    wherever it points).
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return None
    if policy.is_denied(path) and not path.endswith("state.vscdb.backup"):
        return None
    if policy.root_for(path) is None and not policy.check(path):
        return None
    return paths.resolved_candidate(path)


def collect_target(target: Target, option: Option, ctx: ScanContext) -> list[Entry]:
    """Expand one target into sized entries."""
    policy = ctx.policy
    action = {"trash": "trash", "truncate": "truncate", "reset_xbel": "reset_xbel"}.get(
        option.method, "delete")
    groups: list[tuple[str, list[str]]] = []   # (base dir, candidate paths)
    for match in safe_glob(target.path, policy):
        base = _resolve_base(match, policy)
        if base is None:
            continue
        if target.mode == "contents":
            try:
                if not stat.S_ISDIR(os.lstat(base).st_mode):
                    continue
            except OSError:
                continue
            groups.append((base, _children(base)))
        else:
            groups.append((os.path.dirname(base), [base]))

    env = selectors.SelectorEnv(ctx.config, now=ctx.now)
    entries: list[Entry] = []
    for base, cands in groups:
        cands = [c for c in cands if not _excluded(c, base, target.exclude)]
        if option.exclude_known:
            cands = [c for c in cands if os.path.realpath(c) not in ctx.known_dirs]
        labelled: list[tuple[str, str | None]]
        if target.selector:
            labelled = selectors.SELECTORS[target.selector](cands, target.selector_args, env)
        else:
            labelled = [(c, None) for c in cands]
        group: list[Entry] = []
        for path, label in labelled:
            if ctx.cancel.is_set():
                raise Cancelled()
            verdict = policy.check(path)
            if not verdict:
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if target.mode == "dir" and not stat.S_ISDIR(st.st_mode):
                continue
            if target.mode in ("file", "truncate") and not stat.S_ISREG(st.st_mode):
                continue
            if target.mode == "truncate" and st.st_size == 0:
                continue  # already empty
            kind = ("link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode)
                    else "file" if stat.S_ISREG(st.st_mode) else "other")
            if kind == "other":
                continue  # sockets, fifos, devices are never touched
            u = du(path, cancel=ctx.cancel)
            e_action = "truncate" if target.mode == "truncate" else action
            companions = []
            if target.companions:
                info = os.path.join(os.path.dirname(os.path.dirname(path)), "info",
                                    os.path.basename(path) + ".trashinfo")
                if os.path.lexists(info):
                    companions.append(info)
            group.append(Entry(
                path=path, root=policy.root_for(path) or os.path.dirname(path), kind=kind,
                size=u.disk, apparent=u.apparent, count=max(u.count, 1),
                mtime=u.newest or st.st_mtime, action=e_action, label=label,
                companions=companions, dev=st.st_dev, ino=st.st_ino,
            ))
        if target.min_age_days is not None:
            days = target.min_age_days
            if isinstance(days, str) and days.startswith("$"):
                days = ctx.config.get(days[1:], 90)
            cutoff = ctx.now - float(days) * 86400
            group = [e for e in group if e.mtime < cutoff]
        if target.keep_newest_n:
            group.sort(key=lambda e: e.mtime, reverse=True)
            group = group[int(target.keep_newest_n):]
        entries.extend(group)
    return entries


def _dedupe(entries: list[Entry]) -> list[Entry]:
    seen = set()
    out = []
    for e in entries:
        key = paths.resolved_candidate(e.path)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _resolve_params(action: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    out = {"id": action["id"]}
    for k, v in (action.get("params") or {}).items():
        if isinstance(v, str) and v.startswith("$"):
            v = config.get(v[1:])
        if v is not None:
            out[k] = v
    return out


def scan_option(option: Option, cleaner: CleanerDef, ctx: ScanContext) -> list[ScanResult]:
    entries: list[Entry] = []
    for t in option.targets:
        entries.extend(collect_target(t, option, ctx))
    entries = _dedupe(entries)

    base = ScanResult(key=option.id, option=option, cleaner=cleaner, label=option.label)
    # unprivileged tool command preferred when the tool is installed
    if option.command:
        argv = commands.resolve(option.command)
        if argv:
            base.commands = [argv]
        elif option.root_fallback:
            if ctx.helper_available:
                base.root_actions = [_resolve_params(option.root_fallback, ctx.config)]
            else:
                base.unavailable = HELPER_MISSING
        elif option.command_only or not entries:
            base.unavailable = f"{commands.COMMANDS[option.command].tools[0]} is not installed"
    if option.root_action:
        base.root_actions = [_resolve_params(option.root_action, ctx.config)]
        if not ctx.helper_available:
            base.unavailable = HELPER_MISSING

    if option.root or option.probe or option.probe_paths:
        _size_probe(base, option, ctx)
        if option.targets:
            base.entries = entries
        if option.report_only:
            return [base] if (base.size or not base.size_known) else []
        return [base] if (base.size or not base.size_known or base.root_actions or base.commands) else []

    if option.split:
        out = []
        for e in entries:
            r = ScanResult(key=f"{option.id}:{os.path.basename(e.path)}", option=option,
                           cleaner=cleaner, label=e.label or os.path.basename(e.path),
                           entries=[e], size=e.size, apparent=e.apparent, count=e.count,
                           mtime=e.mtime, detail=e.path)
            out.append(r)
        return out

    base.entries = entries
    base.size = sum(e.size for e in entries)
    base.apparent = sum(e.apparent for e in entries)
    base.count = sum(e.count for e in entries)
    base.mtime = max((e.mtime for e in entries), default=0.0)
    if len(entries) == 1 and entries[0].label:
        base.detail = entries[0].label
    if not entries and not (option.report_only and base.size):
        return []
    return [base]


HELPER_MISSING = ("Install the .deb (or run `sudo make install-helper`) "
                  "to enable system cleaning")


def _size_probe(result: ScanResult, option: Option, ctx: ScanContext) -> None:
    if option.root_action and option.root_action["id"] in ctx.root_sizes:
        result.size = ctx.root_sizes[option.root_action["id"]]
        return
    if option.probe and ctx.run_probes:
        p = commands.probe(option.probe, ctx.config)
        if p.size is None:
            result.size_known = False
        else:
            result.size = p.size
            result.approximate = p.approximate
        result.detail = p.detail
        return
    if option.probe_paths:
        seen: set[tuple[int, int]] = set()
        total = 0
        known = True
        for pattern in option.probe_paths:
            matches = safe_glob(pattern) if paths.has_glob(pattern) else [pattern]
            if paths.has_glob(pattern) and not matches:
                parent = paths.static_prefix(pattern)
                if os.path.isdir(parent) and not os.access(parent, os.R_OK | os.X_OK):
                    known = False
            for m in matches:
                if not os.path.lexists(m):
                    continue
                u = du(m, seen=seen, cancel=ctx.cancel)
                total += u.disk
                if u.errors:
                    known = False
        result.size = total
        result.size_known = known
        return
    result.size_known = False


# --------------------------------------------------------------------------
# the scanner
# --------------------------------------------------------------------------

ProgressFn = Callable[[str, int, int], None]
ResultFn = Callable[[CleanerDef, list[ScanResult], bool], None]


def scan(registry: Registry, ctx: ScanContext, *, progress: ProgressFn | None = None,
         on_cleaner: ResultFn | None = None, proc_root: str = "/proc",
         max_workers: int = MAX_WORKERS) -> dict[str, list[ScanResult]]:
    """Scan every cleaner in a thread pool. Returns {cleaner id: results}.

    *on_cleaner* is called from worker threads; UI code must marshal it to
    the main loop itself (``GLib.idle_add``).
    """
    ctx.known_dirs = registry.known_static_dirs()
    proc_list = list(procs.iter_procs(proc_root))  # all users; is_running filters per spec
    cleaners = list(registry.cleaners)
    total = len(cleaners)
    done = 0
    lock = threading.Lock()
    out: dict[str, list[ScanResult]] = {}

    def work(c: CleanerDef) -> None:
        nonlocal done
        results: list[ScanResult] = []
        if not ctx.cancel.is_set():
            for o in c.options:
                if ctx.cancel.is_set():
                    break
                try:
                    results.extend(scan_option(o, c, ctx))
                except Cancelled:
                    break
                except Exception as exc:  # one broken option never aborts the scan
                    r = ScanResult(key=o.id, option=o, cleaner=c, label=o.label,
                                   unavailable=f"scan error: {exc}", size_known=False)
                    results.append(r)
        running = procs.is_running(c.running, procs=proc_list)
        with lock:
            out[c.id] = results
            done += 1
            n = done
        if on_cleaner:
            on_cleaner(c, results, running)
        if progress:
            progress(c.label, n, total)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scan") as pool:
        list(pool.map(work, cleaners))
    return out


def running_map(registry: Registry, proc_root: str = "/proc") -> dict[str, bool]:
    proc_list = list(procs.iter_procs(proc_root))
    return {c.id: procs.is_running(c.running, procs=proc_list) for c in registry.cleaners}

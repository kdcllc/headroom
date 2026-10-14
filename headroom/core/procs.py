"""Running-application detection by reading /proc (no psutil)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import RunningSpec


@dataclass
class ProcInfo:
    pid: int
    comm: str
    exe: str
    argv: list[str]
    cgroup: str
    uid: int


def iter_procs(proc_root: str = "/proc", uid: int | None = None):
    """Yield :class:`ProcInfo` for processes (optionally only those of *uid*)."""
    try:
        names = os.listdir(proc_root)
    except OSError:
        return
    for name in names:
        if not name.isdigit():
            continue
        base = os.path.join(proc_root, name)
        try:
            st_uid = os.stat(base).st_uid
        except OSError:
            continue
        if uid is not None and st_uid != uid:
            continue
        comm = _read(os.path.join(base, "comm")).strip()
        try:
            exe = os.readlink(os.path.join(base, "exe"))
        except OSError:
            exe = ""
        raw = _read(os.path.join(base, "cmdline"))
        argv = [a for a in raw.split("\0") if a]
        cgroup = _read(os.path.join(base, "cgroup"))
        yield ProcInfo(int(name), comm, exe, argv, cgroup, st_uid)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(65536)
    except OSError:
        return ""


def _matches(p: ProcInfo, spec: RunningSpec) -> bool:
    names = {n.lower() for n in spec.process_names}
    if names:
        exe_base = os.path.basename(p.exe.replace(" (deleted)", "")).lower()
        arg0 = os.path.basename(p.argv[0]).lower() if p.argv else ""
        # comm is truncated to 15 chars by the kernel
        if (p.comm.lower() in names or exe_base in names or arg0 in names
                or any(len(n) > 15 and n[:15] == p.comm.lower() for n in names)):
            return True
    for snap in spec.snap_names:
        if p.exe.startswith(f"/snap/{snap}/") or f"/snap.{snap}." in p.cgroup \
                or f"snap.{snap}." in p.cgroup:
            return True
    for app_id in spec.flatpak_ids:
        if f"app-flatpak-{app_id}-" in p.cgroup:
            return True
        if p.argv and os.path.basename(p.argv[0]) == "bwrap" and app_id in p.argv:
            return True
        if any(a in (f"--app={app_id}", app_id) for a in p.argv[1:3]) and "flatpak" in p.comm:
            return True
    return False


def is_running(spec: RunningSpec, proc_root: str = "/proc", uid: int | None = None,
               procs: list[ProcInfo] | None = None) -> bool:
    if not (spec.process_names or spec.snap_names or spec.flatpak_ids or spec.singleton_lock):
        return False
    me = os.getuid() if uid is None else uid
    if procs is None:
        procs = list(iter_procs(proc_root, None if spec.any_user else me))
    if any(_matches(p, spec) for p in procs if spec.any_user or p.uid == me):
        return True
    if spec.singleton_lock:
        # Chromium SingletonLock is a symlink "<host>-<pid>"; stale if pid is gone
        try:
            target = os.readlink(os.path.expanduser(spec.singleton_lock))
            pid = target.rsplit("-", 1)[-1]
            if pid.isdigit() and os.path.isdir(os.path.join(proc_root, pid)):
                return True
        except OSError:
            pass
    return False


def open_files(proc_root: str = "/proc") -> set[tuple[int, int]]:
    """(st_dev, st_ino) of every file currently open by a readable process."""
    out: set[tuple[int, int]] = set()
    try:
        names = os.listdir(proc_root)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        fd_dir = os.path.join(proc_root, name, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                st = os.stat(os.path.join(fd_dir, fd))
                out.add((st.st_dev, st.st_ino))
            except OSError:
                pass
    return out

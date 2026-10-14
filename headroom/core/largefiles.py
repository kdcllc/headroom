"""Large-file finder, project-junk finder and Downloads listing.

Results are user content: the default action is Trash. Walks never follow
symlinks, never cross filesystems and skip protected paths.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import paths
from .scanner import Cancelled, du

ARCHIVE_EXT = (".zip", ".tar", ".tgz", ".gz", ".xz", ".bz2", ".zst", ".7z", ".rar", ".tar.gz")

JUNK_DIRS = {
    "node_modules": None,
    "target": "CACHEDIR.TAG",           # Rust: only with CACHEDIR.TAG inside
    ".venv": None,
    "venv": "pyvenv.cfg",
    "__pycache__": None,
    ".gradle": None,
    ".next": None,
    ".turbo": None,
    ".parcel-cache": None,
    "build": "sibling-manifest",
    "dist": "sibling-manifest",
}
MANIFESTS = ("package.json", "pyproject.toml", "Cargo.toml", "setup.py")


@dataclass
class Found:
    path: str
    root: str
    size: int
    apparent: int
    mtime: float
    kind: str               # file | dir
    category: str = ""      # e.g. node_modules, iso, AppImage
    project: str = ""
    extra: dict = field(default_factory=dict)


def _skip_dirs(home: str) -> set[str]:
    return {os.path.join(home, ".local/share/Trash"), "/proc", "/sys", "/dev", "/run"}


def find_large_files(roots: list[str], threshold: int, policy: paths.SafetyPolicy, *,
                     cancel: threading.Event | None = None,
                     progress: Callable[[str, int], None] | None = None,
                     excluded: list[str] | None = None) -> list[Found]:
    cancel = cancel or threading.Event()
    skip = _skip_dirs(policy.home) | {os.path.abspath(paths.expand(e)) for e in excluded or []}
    out: list[Found] = []
    seen: set[tuple[int, int]] = set()
    n = 0
    for root in roots:
        root = os.path.abspath(paths.expand(root))
        try:
            dev = os.lstat(root).st_dev
        except OSError:
            continue
        stack = [root]
        while stack:
            d = stack.pop()
            if d in skip or policy.is_denied(d) and d != root and d != policy.home:
                continue
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    n += 1
                    if n % 1000 == 0:
                        if cancel.is_set():
                            raise Cancelled()
                        if progress:
                            progress(d, len(out))
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_dev != dev:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if e.path not in skip:
                            stack.append(e.path)
                    elif stat.S_ISREG(st.st_mode):
                        size = st.st_blocks * 512
                        key = (st.st_dev, st.st_ino)
                        if size >= threshold and key not in seen and not policy.is_denied(e.path):
                            seen.add(key)
                            out.append(Found(e.path, root, size, st.st_size, st.st_mtime, "file",
                                             category=file_category(e.name)))
    out.sort(key=lambda f: f.size, reverse=True)
    return out


def file_category(name: str) -> str:
    low = name.lower()
    if low.endswith(".iso"):
        return "ISO image"
    if low.endswith(".appimage"):
        return "AppImage"
    if low.endswith(".deb"):
        return "Debian package"
    if low.endswith(ARCHIVE_EXT):
        return "Archive"
    if low.endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")):
        return "Video"
    if low.endswith((".qcow2", ".vdi", ".vmdk", ".img", ".vhd", ".vhdx")):
        return "Disk image"
    return "File"


def _is_junk(path: str, name: str) -> bool:
    rule = JUNK_DIRS.get(name, False)
    if rule is False:
        return False
    if rule is None:
        return True
    if rule == "sibling-manifest":
        parent = os.path.dirname(path)
        return any(os.path.isfile(os.path.join(parent, m)) for m in MANIFESTS)
    return os.path.isfile(os.path.join(path, rule))


def find_project_junk(roots: list[str], policy: paths.SafetyPolicy, *, max_depth: int = 6,
                      min_age_days: float = 30, cancel: threading.Event | None = None,
                      progress: Callable[[str, int], None] | None = None,
                      now: float | None = None) -> list[Found]:
    cancel = cancel or threading.Event()
    now = now or time.time()
    out: list[Found] = []
    for root in roots:
        root = os.path.abspath(paths.expand(root))
        try:
            dev = os.lstat(root).st_dev
        except OSError:
            continue
        skip = _skip_dirs(policy.home)
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            if cancel.is_set():
                raise Cancelled()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                children = list(it)
            for e in children:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISDIR(st.st_mode) or st.st_dev != dev or e.path in skip:
                    continue
                if policy.is_denied(e.path):
                    continue
                if _is_junk(e.path, e.name):
                    u = du(e.path, cancel=cancel)
                    age = (now - (u.newest or st.st_mtime)) / 86400
                    if age >= min_age_days:
                        out.append(Found(e.path, root, u.disk, u.apparent, u.newest or st.st_mtime,
                                         "dir", category=e.name, project=os.path.dirname(e.path)))
                    if progress:
                        progress(e.path, len(out))
                    continue  # never descend into junk
                if e.name.startswith(".") and e.name not in (".config",):
                    # hidden dirs (caches, VCS) are covered by the cleaners
                    continue
                if depth + 1 < max_depth:
                    stack.append((e.path, depth + 1))
    out.sort(key=lambda f: f.size, reverse=True)
    return out


def list_downloads(policy: paths.SafetyPolicy, cancel: threading.Event | None = None) -> list[Found]:
    d = paths.downloads_dir()
    out = []
    try:
        entries = list(os.scandir(d))
    except OSError:
        return out
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode):
            continue
        if stat.S_ISDIR(st.st_mode):
            u = du(e.path, cancel=cancel)
            out.append(Found(e.path, d, u.disk, u.apparent, u.newest or st.st_mtime, "dir",
                             category="Folder"))
        elif stat.S_ISREG(st.st_mode):
            out.append(Found(e.path, d, st.st_blocks * 512, st.st_size, st.st_mtime, "file",
                             category=file_category(e.name)))
    out.sort(key=lambda f: f.size, reverse=True)
    return out


def finder_policy(roots: list[str], excluded: list[str] | None = None) -> paths.SafetyPolicy:
    """A policy whose extra allow roots are the finder roots (finder results only)."""
    return paths.SafetyPolicy(extra_roots=[os.path.abspath(paths.expand(r)) for r in roots],
                              user_excluded=list(excluded or []))


def to_results(items: list[Found], method: str, label: str) -> list:
    """Turn finder hits into ScanResults the planner/deleter understand."""
    from .models import CleanerDef, Entry, Option, ScanResult
    opt = Option(id=f"finder.{label.lower().replace(' ', '_')}", label=label, description="",
                 rating="caution", method=method)
    cleaner = CleanerDef(id="finder", label=label, category="Finder", options=[opt])
    out = []
    for f in items:
        try:
            st = os.lstat(f.path)
        except OSError:
            continue
        kind = ("link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode)
                else "file" if stat.S_ISREG(st.st_mode) else "other")
        e = Entry(path=f.path, root=f.root, kind=kind, size=f.size, apparent=f.apparent, count=1,
                  mtime=f.mtime, action="trash" if method == "trash" else "delete",
                  dev=st.st_dev, ino=st.st_ino)
        out.append(ScanResult(key=f.path, option=opt, cleaner=cleaner, label=os.path.basename(f.path),
                              entries=[e], size=f.size, apparent=f.apparent, count=1, mtime=f.mtime))
    return out

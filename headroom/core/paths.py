"""Path resolution and the safety boundary (allow-list, deny-list, is_within).

Every path the app may delete passes through :class:`SafetyPolicy.check`.
The deny-list always wins; the allow-list is a closed set of roots.
"""

from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass, field

GLOB_CHARS = set("*?[")


def home() -> str:
    """Current user's home, honouring $HOME (tests monkeypatch it)."""
    return os.path.realpath(os.path.expanduser("~"))


def xdg(name: str, default_rel: str) -> str:
    value = os.environ.get(name)
    if value and os.path.isabs(value):
        return value
    return os.path.join(home(), default_rel)


def xdg_config_home() -> str:
    return xdg("XDG_CONFIG_HOME", ".config")


def xdg_cache_home() -> str:
    return xdg("XDG_CACHE_HOME", ".cache")


def xdg_state_home() -> str:
    return xdg("XDG_STATE_HOME", ".local/state")


def xdg_data_home() -> str:
    return xdg("XDG_DATA_HOME", ".local/share")


def downloads_dir() -> str:
    """$(xdg-user-dir DOWNLOAD) without spawning a process."""
    cfg = os.path.join(xdg_config_home(), "user-dirs.dirs")
    try:
        with open(cfg, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("XDG_DOWNLOAD_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    value = value.replace("$HOME", home())
                    if os.path.isabs(value) and os.path.realpath(value) != home():
                        return value
    except OSError:
        pass
    return os.path.join(home(), "Downloads")


def expand(path: str) -> str:
    """Expand a leading ``~`` against the (possibly monkeypatched) home."""
    if path == "~":
        return home()
    if path.startswith("~/"):
        return os.path.join(home(), path[2:])
    return path


def has_glob(path: str) -> bool:
    return any(c in GLOB_CHARS for c in path)


def static_prefix(pattern: str) -> str:
    """Longest leading part of a pattern with no glob characters."""
    parts = pattern.split("/")
    out = []
    for p in parts:
        if has_glob(p):
            break
        out.append(p)
    prefix = "/".join(out)
    return prefix or "/"


def is_within(candidate: str, root: str) -> bool:
    """True if *candidate* lies inside (or equals) *root*.

    The root is fully resolved with ``realpath``. For the candidate only the
    parent directory is resolved, so a candidate that is itself a symlink is
    judged by where the link lives, not where it points (we only ever unlink
    links). A candidate whose parent resolves outside the root is refused.
    """
    if not candidate or not root:
        return False
    root_real = os.path.realpath(root)
    cand = os.path.abspath(candidate)
    parent, name = os.path.split(cand)
    if name in ("", ".", ".."):
        cand_real = os.path.realpath(cand)
    else:
        cand_real = os.path.join(os.path.realpath(parent), name)
    try:
        return os.path.commonpath([root_real, cand_real]) == root_real
    except ValueError:
        return False


def resolved_candidate(candidate: str) -> str:
    cand = os.path.abspath(candidate)
    parent, name = os.path.split(cand)
    return os.path.join(os.path.realpath(parent), name)


# --------------------------------------------------------------------------
# Allow-list / deny-list
# --------------------------------------------------------------------------

# Relative to $HOME. Deletion is possible only below one of these (or below
# an app root registered from the cleaner registry, or an explicit extra root).
HOME_ALLOW_ROOTS = [
    ".cache",
    ".var/app",
    "snap",
    ".local/share/Trash",
    ".local/share/flatpak",
    ".local/share/gvfs-metadata",
    ".local/share/pnpm",
    ".local/share/NuGet",
    ".local/share/JetBrains",
    ".local/share/gem",
    ".local/share/unity3d",
    ".local/share/recently-used.xbel",
    ".npm",
    ".yarn/berry/cache",
    ".nvm/.cache",
    "go/pkg/mod",
    ".cargo/registry",
    ".cargo/git",
    ".gradle/caches",
    ".gradle/daemon",
    ".gradle/wrapper/dists",
    ".m2/repository",
    ".nuget/packages",
    "anaconda3/pkgs",
    "miniconda3/pkgs",
    "miniforge3/pkgs",
    "mambaforge/pkgs",
    ".conda/pkgs",
    ".android/cache",
    ".android/avd",
    "Android/Sdk/system-images",
    ".gem",
    ".bundle/cache",
    ".cursor/extensions",
    ".cursor-server",
    ".vscode/extensions",
    ".vscode-insiders/extensions",
    ".vscode-oss/extensions",
    ".vscode-server",
    ".vscode-server-insiders",
    ".config/JetBrains",
    "Applications",
    ".xsession-errors",
    ".xsession-errors.old",
]

# Files directly in $HOME matching these patterns are allowed (regular files only).
HOME_FILE_PATTERNS = ["core", "core.*"]

# Absolute roots the unprivileged app may touch (with extra checks in selectors).
SYSTEM_USER_ROOTS = ["/tmp/cursor-sandbox-cache"]

# Relative to $HOME; a candidate equal to or below any of these is refused.
HOME_DENY = [
    "",  # $HOME itself
    ".ssh",
    ".gnupg",
    ".local/share/keyrings",
    ".mozilla",
    "snap/firefox/common/.mozilla",
    ".vscode-shared",
    ".vscode-insiders-shared",
    ".vscode-oss-shared",
    ".cursor-shared",
    ".password-store",
    "Documents",
    "Pictures",
    "Desktop",
    ".config/headroom",
    ".local/state/headroom",
]

# Glob patterns relative to $HOME (fnmatch: '*' also matches '/').
HOME_DENY_GLOBS = [
    "*/User/settings.json",
    "*/User/keybindings.json",
    "*/User/snippets",
    "*/User/profiles",
    "*/User/globalStorage",
]

# Explicit exceptions to HOME_DENY_GLOBS (exact basename under a denied dir).
DENY_EXCEPTIONS = ["*/User/globalStorage/state.vscdb.backup"]

SYSTEM_DENY = [
    "/",
    "/etc",
    "/usr",
    "/boot",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var/lib/dpkg",
    "/var/lib/docker",
    "/var/cache/debconf",
    "/proc",
    "/sys",
    "/dev",
    "/run",
]


@dataclass
class Verdict:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class SafetyPolicy:
    """The allow/deny boundary for one user session."""

    home: str = field(default_factory=home)
    extra_roots: list[str] = field(default_factory=list)
    app_roots: list[str] = field(default_factory=list)
    user_excluded: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.home = os.path.realpath(self.home)
        self._roots_cache: list[str] | None = None
        self._real_cache: list[str] | None = None

    # -- roots -------------------------------------------------------------
    def allow_roots(self) -> list[str]:
        if self._roots_cache is None:
            self._roots_cache = self._compute_roots()
        return list(self._roots_cache)

    def _real_roots(self) -> list[str]:
        if self._real_cache is None:
            self._real_cache = [os.path.realpath(r) for r in self.allow_roots()]
        return self._real_cache

    def invalidate(self) -> None:
        """Forget cached roots (call before every clean run)."""
        self._roots_cache = None
        self._real_cache = None

    def _compute_roots(self) -> list[str]:
        roots = [os.path.join(self.home, r) for r in HOME_ALLOW_ROOTS]
        roots.append(downloads_dir())
        roots.extend(SYSTEM_USER_ROOTS)
        roots.extend(self.app_roots)
        roots.extend(self.extra_roots)
        roots.extend(self._removable_trash_roots())
        return roots

    def _removable_trash_roots(self) -> list[str]:
        uid = os.getuid()
        user = os.environ.get("USER") or os.path.basename(self.home)
        out = []
        base = os.path.join("/media", user)
        try:
            with os.scandir(base) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        out.append(os.path.join(e.path, f".Trash-{uid}"))
                        out.append(os.path.join(e.path, ".Trash", str(uid)))
        except OSError:
            pass
        return out

    def register_app_root(self, path: str) -> None:
        path = os.path.abspath(path)
        if path not in self.app_roots and not self.is_denied(path):
            self.app_roots.append(path)
            self.invalidate()

    def root_for(self, candidate: str, roots: list[str] | None = None) -> str | None:
        """Most specific allow root containing *candidate*, if any."""
        reals = [os.path.realpath(r) for r in roots] if roots is not None else self._real_roots()
        cand = resolved_candidate(candidate)
        best = None
        for rr in reals:
            if cand == rr or cand.startswith(rr.rstrip("/") + "/"):
                if best is None or len(rr) > len(best):
                    best = rr
        return best

    # -- deny --------------------------------------------------------------
    def is_denied(self, candidate: str) -> bool:
        for path in {os.path.abspath(candidate), resolved_candidate(candidate)}:
            if self._denied_literal(path):
                return True
        return False

    def _denied_literal(self, path: str) -> bool:
        for d in SYSTEM_DENY:
            if path == d:
                return True
            if d != "/" and (path + "/").startswith(d + "/"):
                return True
        for rel in HOME_DENY:
            d = os.path.join(self.home, rel) if rel else self.home
            if path == d or (rel and (path + "/").startswith(d + "/")):
                return True
        for ex in self.user_excluded:
            ex = os.path.abspath(expand(ex))
            if path == ex or (path + "/").startswith(ex + "/"):
                return True
        if (path + "/").startswith(self.home + "/"):
            rel = os.path.relpath(path, self.home)
            if any(fnmatch.fnmatchcase(rel, p) for p in DENY_EXCEPTIONS):
                return False
            # check rel and every ancestor against the glob deny patterns
            parts = rel.split("/")
            for i in range(1, len(parts) + 1):
                sub = "/".join(parts[:i])
                if any(fnmatch.fnmatchcase(sub, p) for p in HOME_DENY_GLOBS):
                    return True
        return False

    # -- the main check ------------------------------------------------------
    def check(self, candidate: str, roots: list[str] | None = None) -> Verdict:
        """Decide whether *candidate* may be deleted right now.

        Checks (in order): absolute path, deny-list (wins), not a mount
        point, inside an allow root, not the allow root itself.
        """
        if not candidate or not os.path.isabs(candidate):
            return Verdict(False, "not an absolute path")
        cand = os.path.normpath(candidate)
        if self.is_denied(cand):
            return Verdict(False, "protected path (deny-list)")
        try:
            if os.path.ismount(cand):
                return Verdict(False, "mount point")
        except OSError:
            pass
        allow = roots if roots is not None else self.allow_roots()
        root = self.root_for(cand, allow)
        if root is None:
            if self._home_file_allowed(cand):
                return Verdict(True)
            return Verdict(False, "outside the allowed cleaning roots")
        if resolved_candidate(cand) == root:
            try:
                st = os.lstat(cand)
            except OSError:
                return Verdict(False, "vanished")
            if stat.S_ISDIR(st.st_mode):
                return Verdict(False, "refusing to remove an allow-list root itself")
        return Verdict(True)

    def _home_file_allowed(self, cand: str) -> bool:
        parent, name = os.path.split(cand)
        if os.path.realpath(parent) != self.home:
            return False
        if not any(fnmatch.fnmatchcase(name, p) for p in HOME_FILE_PATTERNS):
            return False
        try:
            return stat.S_ISREG(os.lstat(cand).st_mode)
        except OSError:
            return False


def disk_usage(path: str) -> tuple[int, int] | None:
    """(used, total) bytes for the filesystem holding *path*."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    return used, max(total, used + free)

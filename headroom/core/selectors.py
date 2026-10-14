"""Named selectors that refine candidate entries for special locations.

Each selector receives the candidate paths (already inside an allow root,
not yet sized) and returns ``(path, label)`` pairs to keep. They read
metadata only; nothing here deletes.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse

Candidate = tuple[str, "str | None"]
SelectorFn = Callable[[list[str], dict[str, Any], "SelectorEnv"], list[Candidate]]


class SelectorEnv:
    """What a selector may know about the environment (config values, uid)."""

    def __init__(self, config: dict[str, Any] | None = None, uid: int | None = None,
                 now: float | None = None):
        self.config = config or {}
        self.uid = os.getuid() if uid is None else uid
        self.now = time.time() if now is None else now

    def arg(self, args: dict[str, Any], name: str, default: Any) -> Any:
        """Resolve an argument, where "$key" refers to a config value."""
        value = args.get(name, default)
        if isinstance(value, str) and value.startswith("$"):
            return self.config.get(value[1:], default)
        return value


# --------------------------------------------------------------------------
# workspaceStorage
# --------------------------------------------------------------------------

def workspace_target(ws_dir: str) -> tuple[str, str | None]:
    """Classify a workspaceStorage/<hash> dir.

    Returns ``(state, label)`` where state is ``exists``, ``missing``,
    ``unknown`` (remote / unparsable / no workspace.json).
    """
    path = os.path.join(ws_dir, "workspace.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "unknown", None
    uri = data.get("folder") or data.get("workspace") or data.get("configuration")
    if not isinstance(uri, str):
        return "unknown", None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return "unknown", uri
    local = unquote(parsed.path)
    if not local:
        return "unknown", uri
    return ("exists" if os.path.exists(local) else "missing"), local


def _mtime(path: str) -> float:
    try:
        return os.lstat(path).st_mtime
    except OSError:
        return 0.0


def _newest_mtime_shallow(path: str) -> float:
    newest = _mtime(path)
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return newest


def sel_stale_workspace(paths: list[str], args: dict[str, Any], env: SelectorEnv) -> list[Candidate]:
    """Stale = local folder no longer exists, or untouched for N days.

    Remote (``vscode-remote://``) and unparsable entries are ``unknown`` and
    never offered as stale.
    """
    days = float(env.arg(args, "days", 90))
    out: list[Candidate] = []
    for p in paths:
        if not os.path.isdir(p) or os.path.islink(p):
            continue
        state, label = workspace_target(p)
        if state == "unknown":
            continue
        age_days = (env.now - _newest_mtime_shallow(p)) / 86400
        if state == "missing":
            out.append((p, f"{label} (folder no longer exists)"))
        elif age_days > days:
            out.append((p, f"{label} (unused for {int(age_days)} days)"))
    return out


def sel_workspace_all(paths: list[str], args: dict[str, Any], env: SelectorEnv) -> list[Candidate]:
    out: list[Candidate] = []
    for p in paths:
        state, label = workspace_target(p)
        out.append((p, label or os.path.basename(p)))
    return out


# --------------------------------------------------------------------------
# extensions: superseded versions
# --------------------------------------------------------------------------

_EXT_RE = re.compile(
    r"^(?P<id>[A-Za-z0-9][\w-]*\.[\w.-]+?)-(?P<ver>\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?)$"
)
_PLATFORMS = ("linux-x64", "linux-arm64", "linux-armhf", "alpine-x64", "alpine-arm64",
              "universal", "web", "win32-x64", "darwin-x64", "darwin-arm64")


def parse_extension_dir(name: str) -> tuple[str, tuple[int, ...]] | None:
    """``ms-python.python-2024.2.1-linux-x64`` -> (``ms-python.python``, (2024, 2, 1))."""
    base = name
    for plat in _PLATFORMS:
        if base.endswith("-" + plat):
            base = base[: -len(plat) - 1]
            break
    m = _EXT_RE.match(base)
    if not m:
        return None
    core = re.match(r"\d+(?:\.\d+)*", m.group("ver"))
    nums = tuple(int(x) for x in core.group(0).split(".")) if core else (0,)
    return m.group("id").lower(), nums


def referenced_extensions(ext_root: str) -> set[str]:
    """Dir names referenced from extensions.json (plus anything not in .obsolete)."""
    refs: set[str] = set()
    try:
        with open(os.path.join(ext_root, "extensions.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return refs
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            rel = item.get("relativeLocation")
            if isinstance(rel, str):
                refs.add(rel)
            loc = item.get("location")
            if isinstance(loc, dict):
                p = loc.get("path") or loc.get("fsPath")
                if isinstance(p, str):
                    refs.add(os.path.basename(p.rstrip("/")))
    return refs


def obsolete_extensions(ext_root: str) -> set[str]:
    try:
        with open(os.path.join(ext_root, ".obsolete"), encoding="utf-8") as fh:
            data = json.load(fh)
        return {k for k, v in data.items() if v} if isinstance(data, dict) else set()
    except (OSError, ValueError):
        return set()


def sel_superseded_extensions(paths: list[str], args: dict[str, Any], env: SelectorEnv) -> list[Candidate]:
    """Older versions of an extension when a newer one is installed.

    A version referenced by extensions.json is never offered; versions VS
    Code itself marked in ``.obsolete`` are always offered.
    """
    by_root: dict[str, list[str]] = {}
    for p in paths:
        by_root.setdefault(os.path.dirname(p), []).append(p)
    out: list[Candidate] = []
    for root, items in by_root.items():
        refs = referenced_extensions(root)
        obsolete = obsolete_extensions(root)
        groups: dict[str, list[tuple[tuple[int, ...], str]]] = {}
        for p in items:
            name = os.path.basename(p)
            if not os.path.isdir(p) or os.path.islink(p):
                continue
            if name in obsolete and name not in refs:
                out.append((p, f"{name} (marked obsolete)"))
                continue
            parsed = parse_extension_dir(name)
            if parsed:
                groups.setdefault(parsed[0], []).append((parsed[1], p))
        for ext_id, versions in groups.items():
            if len(versions) < 2:
                continue
            versions.sort()
            newest = versions[-1][0]
            for ver, p in versions:
                name = os.path.basename(p)
                if ver < newest and name not in refs and name not in obsolete:
                    out.append((p, f"{ext_id} {'.'.join(map(str, ver))} (superseded)"))
    return out


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def is_elf_core(path: str) -> bool:
    """True for an ELF file whose e_type is ET_CORE (4)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(18)
    except OSError:
        return False
    if len(head) < 18 or head[:4] != b"\x7fELF":
        return False
    order = "little" if head[5] == 1 else "big"
    return int.from_bytes(head[16:18], order) == 4


def sel_elf_core(paths, args, env):
    return [(p, None) for p in paths if os.path.isfile(p) and not os.path.islink(p) and is_elf_core(p)]


def sel_owned_by_uid(paths, args, env):
    out = []
    for p in paths:
        try:
            if os.lstat(p).st_uid == env.uid:
                out.append((p, None))
        except OSError:
            pass
    return out


def sel_snap_old_revisions(paths, args, env):
    """~/snap/<name>/<rev> dirs other than the one ``current`` points at."""
    out = []
    for p in paths:
        name = os.path.basename(p)
        if not name.isdigit() or os.path.islink(p):
            continue
        try:
            current = os.readlink(os.path.join(os.path.dirname(p), "current"))
        except OSError:
            continue
        if os.path.basename(current.rstrip("/")) != name:
            out.append((p, f"revision {name} (not current)"))
    return out


_VER_SPLIT = re.compile(r"^(?P<product>[A-Za-z][A-Za-z-]*?)(?P<ver>\d+(?:\.\d+)*)$")


def sel_versions(paths, args, env):
    """Group ``<Product><version>`` dirs (JetBrains); keep=old|current."""
    which = args.get("keep", "old")
    groups: dict[str, list[tuple[tuple[int, ...], str]]] = {}
    for p in paths:
        m = _VER_SPLIT.match(os.path.basename(p))
        if not m or not os.path.isdir(p) or os.path.islink(p):
            continue
        ver = tuple(int(x) for x in m.group("ver").split("."))
        groups.setdefault(m.group("product"), []).append((ver, p))
    out = []
    for product, items in groups.items():
        items.sort()
        newest = items[-1]
        if which == "current":
            out.append((newest[1], f"{product} {'.'.join(map(str, newest[0]))} (current)"))
        else:
            out.extend((p, f"{product} {'.'.join(map(str, v))} (older version)")
                       for v, p in items[:-1])
    return out


def sel_hf_models(paths, args, env):
    """Label ``models--org--name`` dirs as ``org/name``."""
    out = []
    for p in paths:
        name = os.path.basename(p)
        for prefix in ("models--", "datasets--", "spaces--"):
            if name.startswith(prefix):
                out.append((p, f"{prefix[:-3]}: {name[len(prefix):].replace('--', '/')}"))
                break
    return out


def sel_dirs_only(paths, args, env):
    return [(p, None) for p in paths if os.path.isdir(p) and not os.path.islink(p)]


SELECTORS: dict[str, SelectorFn] = {
    "stale_workspace": sel_stale_workspace,
    "workspace_all": sel_workspace_all,
    "superseded_extensions": sel_superseded_extensions,
    "elf_core": sel_elf_core,
    "owned_by_uid": sel_owned_by_uid,
    "snap_old_revisions": sel_snap_old_revisions,
    "versions": sel_versions,
    "hf_models": sel_hf_models,
    "dirs_only": sel_dirs_only,
}

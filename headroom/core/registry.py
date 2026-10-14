"""Load and validate cleaner definitions (data/cleaners/*.json).

Definitions are declarative (like BleachBit's CleanerML). A definition may
use a template from ``data/cleaners/_templates``; ``{var}`` placeholders in
ids and paths are expanded, and a list-valued var multiplies the targets
that use it (e.g. one VS Code definition covering deb, snap and Flatpak).
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from . import commands, paths, selectors
from .models import METHODS, MODES, RATINGS, CleanerDef, Option, RunningSpec, Target

CATEGORIES = [
    "Code Editors",
    "Electron Apps",
    "Browsers",
    "Developer Caches",
    "User Caches",
    "System",
    "Docker",
    "Snaps & Flatpak",
    "Trash & Desktop",
]

# root action ids the helper implements (kept in sync with helper; tested)
ROOT_ACTIONS = {
    "apt.clean", "apt.autoclean", "apt.autoremove", "apt.lists",
    "journal.vacuum", "journal.cap", "logs.rotated", "logs.truncate_large",
    "snap.disabled", "snap.retain", "snap.cache",
    "crash.var", "crash.coredump", "tmp.var", "tmp.tmp",
    "cache.man", "cache.fontconfig", "flatpak.system_unused",
    "docker.builder", "docker.system", "docker.images_all", "docker.volumes",
}
PROBES = {"journal", "snap_disabled", "apt_autoremove", "flatpak_user_unused",
          "flatpak_system_unused"}
ELECTRON_MARKERS = ("Cache", "Code Cache", "GPUCache", "Local Storage")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
_VAR_RE = re.compile(r"\{(\w+)\}")


class RegistryError(ValueError):
    pass


def default_data_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(here, "data", "cleaners"),
                 os.path.join(os.path.dirname(here), "data", "cleaners"),
                 "/usr/share/headroom/cleaners"):
        if os.path.isdir(cand):
            return cand
    return os.path.join(os.path.dirname(here), "data", "cleaners")


def builtin_vars() -> dict[str, list[str]]:
    h = paths.home()
    hf_home = os.environ.get("HF_HOME") or os.path.join(paths.xdg_cache_home(), "huggingface")
    hf_hub = os.environ.get("HF_HUB_CACHE") or os.path.join(hf_home, "hub")
    gopath = os.environ.get("GOPATH", os.path.join(h, "go")).split(":")[0]
    return {
        "home": [h],
        "uid": [str(os.getuid())],
        "user": [os.environ.get("USER") or os.path.basename(h)],
        "hf_home": [hf_home],
        "hf_hub": [hf_hub],
        "gocache": [os.environ.get("GOCACHE") or os.path.join(paths.xdg_cache_home(), "go-build")],
        "gomodcache": [os.environ.get("GOMODCACHE") or os.path.join(gopath, "pkg", "mod")],
        "downloads": [paths.downloads_dir()],
    }


def _expand_str(s: str, values: dict[str, str]) -> str:
    return _VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)), s)


def expand_pattern(pattern: str, variables: dict[str, list[str]]) -> list[str]:
    """Expand ``{var}`` placeholders; list values produce one pattern each."""
    names = list(dict.fromkeys(_VAR_RE.findall(pattern)))
    if not names:
        return [paths.expand(pattern)]
    if any(not variables.get(n) for n in names):
        return []
    out = []
    for combo in itertools.product(*(variables[n] for n in names)):
        out.append(paths.expand(_expand_str(pattern, dict(zip(names, combo, strict=True)))))
    return list(dict.fromkeys(out))


@dataclass
class Registry:
    cleaners: list[CleanerDef] = field(default_factory=list)
    policy: paths.SafetyPolicy = field(default_factory=paths.SafetyPolicy)
    errors: list[str] = field(default_factory=list)
    config_roots: set[str] = field(default_factory=set)

    def options(self) -> list[Option]:
        return [o for c in self.cleaners for o in c.options]

    def option(self, option_id: str) -> Option | None:
        for o in self.options():
            if o.id == option_id:
                return o
        return None

    def cleaner(self, cleaner_id: str) -> CleanerDef | None:
        for c in self.cleaners:
            if c.id == cleaner_id:
                return c
        return None

    def known_static_dirs(self) -> set[str]:
        """Real paths of every fixed directory some definition targets."""
        out = set()
        for o in self.options():
            if o.exclude_known:
                continue
            for t in o.targets:
                prefix = paths.static_prefix(t.path)
                out.add(os.path.realpath(prefix))
        return out


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RegistryError(msg)


def _validate_target_path(path: str, policy: paths.SafetyPolicy, *, custom: bool,
                          registry: Registry) -> None:
    _require(os.path.isabs(path), f"target path must be absolute or start with ~/: {path}")
    _require(".." not in path.split("/"), f"'..' not allowed in path: {path}")
    prefix = paths.static_prefix(path)
    h = policy.home
    if "**" in path:
        cache = os.path.join(h, ".cache")
        _require(paths.is_within(prefix, cache) or "/cache/" in prefix + "/",
                 f"'**' is only allowed under a cache root: {path}")
    if os.path.dirname(path) == h and os.path.basename(path) in paths.HOME_FILE_PATTERNS + ["core*"]:
        return  # ~/core dumps: each match is re-checked (regular file in $HOME, ELF core)
    if policy.is_denied(prefix) and not prefix.endswith("state.vscdb.backup"):
        raise RegistryError(f"target is on the deny-list: {path}")
    if custom:
        _require(paths.is_within(prefix, h) and os.path.realpath(prefix) != h,
                 f"custom cleaners may only target paths under $HOME: {path}")
        _require(prefix.count("/") > h.count("/") + 0, f"path too broad: {path}")
        policy.register_app_root(prefix)
        return
    if policy.root_for(prefix) is not None:
        return
    if path.startswith("/media/") and "/.Trash" in path:
        return  # removable-drive trash: matches must fall under policy's trash roots
    config = os.path.join(h, ".config")
    rel = os.path.relpath(prefix, config)
    if not rel.startswith("..") and rel != "." and "/" not in rel.split("/", 1)[0]:
        app_dir = os.path.join(config, rel.split("/", 1)[0])
        _require(app_dir != config, f"cannot target ~/.config itself: {path}")
        policy.register_app_root(app_dir)
        registry.config_roots.add(os.path.realpath(app_dir))
        return
    raise RegistryError(f"target outside the allow-list: {path}")


def _parse_option(raw: dict[str, Any], cleaner_id: str, variables: dict[str, list[str]],
                  policy: paths.SafetyPolicy, custom: bool, registry: Registry) -> Option | None:
    _require(isinstance(raw, dict), "option must be an object")
    oid = _expand_str(str(raw.get("id", "")), {"id": cleaner_id})
    _require(bool(_ID_RE.match(oid)), f"bad option id: {oid!r}")
    rating = raw.get("rating")
    _require(rating in RATINGS, f"{oid}: unknown rating {rating!r}")
    method = raw.get("method", "delete")
    _require(method in METHODS, f"{oid}: unknown method {method!r}")
    root = bool(raw.get("root", False))
    if custom:
        _require(rating != "safe", f"{oid}: custom cleaners must be rated caution or advanced")
        _require(method in ("delete", "trash"), f"{oid}: custom cleaners may only delete or trash")
        _require(not root and not raw.get("command") and not raw.get("root_action"),
                 f"{oid}: custom cleaners cannot run commands or root actions")

    targets: list[Target] = []
    for t in raw.get("targets", []):
        _require(isinstance(t, dict), f"{oid}: target must be an object")
        mode = t.get("mode")
        _require(mode in MODES, f"{oid}: unknown mode {mode!r}")
        sel = t.get("selector")
        _require(sel is None or sel in selectors.SELECTORS, f"{oid}: unknown selector {sel!r}")
        _require(isinstance(t.get("path"), str), f"{oid}: target needs a path")
        for p in expand_pattern(t["path"], variables):
            _validate_target_path(p, policy, custom=custom, registry=registry)
            targets.append(Target(
                mode=mode, path=p,
                exclude=list(t.get("exclude", raw.get("exclude", []))),
                min_age_days=t.get("min_age_days", raw.get("min_age_days")),
                keep_newest_n=t.get("keep_newest_n", raw.get("keep_newest_n")),
                selector=sel, selector_args=dict(t.get("selector_args", {})),
                companions=bool(t.get("companions", False)),
            ))

    command = raw.get("command")
    if command is not None:
        _require(command in commands.COMMANDS, f"{oid}: command not in allow-list: {command}")
    ra = raw.get("root_action")
    rf = raw.get("root_fallback")
    for action in (ra, rf):
        if action is not None:
            _require(isinstance(action, dict) and action.get("id") in ROOT_ACTIONS,
                     f"{oid}: unknown root action {action!r}")
    if ra is not None:
        _require(root and method == "root_action", f"{oid}: root_action needs root=true, method=root_action")
    if root:
        _require(ra is not None or method == "report", f"{oid}: root option without root_action")
    probe = raw.get("probe")
    if probe is not None:
        _require(probe in PROBES or probe.startswith("docker_df:"), f"{oid}: unknown probe {probe}")
    probe_paths = [p for pat in raw.get("probe_paths", []) for p in expand_pattern(pat, variables)]
    if root or probe_paths:
        _require(not targets, f"{oid}: root options use probe_paths, not targets")

    if not targets and not command and not ra and method != "report":
        return None  # every target used a var this definition doesn't have
    return Option(
        id=oid, label=str(raw.get("label", oid)), description=str(raw.get("description", "")),
        rating=rating, root=root, requires_app_closed=bool(raw.get("requires_app_closed", False)),
        targets=targets, method=method, command=command,
        command_only=bool(raw.get("command_only", False)),
        root_action=copy.deepcopy(ra), root_fallback=copy.deepcopy(rf), probe=probe,
        probe_paths=probe_paths, split=bool(raw.get("split", False)),
        report_only=bool(raw.get("report_only", False)) or method == "report",
        extra_confirmation=raw.get("extra_confirmation"), note=raw.get("note"),
        exclude_known=bool(raw.get("exclude_known", False)), cleaner_id=cleaner_id,
        overlap=raw.get("overlap"),
    )


def parse_cleaner(raw: dict[str, Any], templates: dict[str, dict[str, Any]],
                  policy: paths.SafetyPolicy, registry: Registry, *, source: str = "",
                  custom: bool = False) -> CleanerDef:
    _require(isinstance(raw, dict), "definition must be a JSON object")
    cid = raw.get("id")
    _require(isinstance(cid, str) and bool(_ID_RE.match(cid)), f"bad cleaner id: {cid!r}")
    category = raw.get("category")
    if custom:
        category = category if category in CATEGORIES else "User Caches"
    _require(category in CATEGORIES, f"{cid}: unknown category {category!r}")

    variables = builtin_vars()
    for k, v in raw.get("vars", {}).items():
        variables[k] = [v] if isinstance(v, str) else [str(x) for x in v]
    raw_options = []
    tname = raw.get("template")
    if tname:
        _require(not custom, f"{cid}: custom cleaners cannot use templates")
        _require(tname in templates, f"{cid}: unknown template {tname!r}")
        omit = set(raw.get("omit", []))
        raw_options.extend(o for o in templates[tname]["options"]
                           if o.get("id", "").replace("{id}.", "") not in omit)
    raw_options.extend(raw.get("options", []))
    _require(bool(raw_options), f"{cid}: no options")

    options = []
    for ro in raw_options:
        opt = _parse_option(ro, cid, variables, policy, custom, registry)
        if opt is not None:
            options.append(opt)

    run = raw.get("running", {}) or {}
    running = RunningSpec(
        process_names=[str(x) for x in run.get("process_names", [])],
        singleton_lock=paths.expand(run["singleton_lock"]) if run.get("singleton_lock") else None,
        snap_names=[str(x) for x in run.get("snap_names", [])],
        flatpak_ids=[str(x) for x in run.get("flatpak_ids", [])],
        any_user=category == "System",
    )
    for root in variables.get("config", []) + variables.get("root", []):
        registry.config_roots.add(os.path.realpath(paths.expand(root)))
    return CleanerDef(id=cid, label=str(raw.get("label", cid)), category=category,
                      options=options, running=running, source=source, custom=custom)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_templates(data_dir: str) -> dict[str, dict[str, Any]]:
    tdir = os.path.join(data_dir, "_templates")
    out = {}
    if os.path.isdir(tdir):
        for name in sorted(os.listdir(tdir)):
            if name.endswith(".json"):
                t = _load_json(os.path.join(tdir, name))
                out[t["template"]] = t
    return out


def load_registry(data_dir: str | None = None, custom_dir: str | None = None,
                  policy: paths.SafetyPolicy | None = None, discover: bool = True,
                  strict: bool = False) -> Registry:
    """Load built-in + custom definitions. Invalid files are reported in
    ``registry.errors`` (or raised when *strict*)."""
    data_dir = data_dir or default_data_dir()
    reg = Registry(policy=policy or paths.SafetyPolicy())
    templates = load_templates(data_dir)
    seen_ids: set[str] = set()

    def add(path: str, custom: bool) -> None:
        try:
            raw = _load_json(path)
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                c = parse_cleaner(item, templates, reg.policy, reg, source=path, custom=custom)
                _require(c.id not in {x.id for x in reg.cleaners}, f"duplicate cleaner id {c.id}")
                for o in c.options:
                    _require(o.id not in seen_ids, f"duplicate option id {o.id}")
                for o in c.options:
                    seen_ids.add(o.id)
                reg.cleaners.append(c)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = f"{os.path.basename(path)}: {exc}"
            if strict:
                raise RegistryError(msg) from exc
            reg.errors.append(msg)

    for name in sorted(os.listdir(data_dir)):
        if name.endswith(".json"):
            add(os.path.join(data_dir, name), False)
    custom_dir = custom_dir if custom_dir is not None else _default_custom_dir()
    if custom_dir and os.path.isdir(custom_dir):
        for name in sorted(os.listdir(custom_dir)):
            if name.endswith(".json"):
                add(os.path.join(custom_dir, name), True)
    if discover and "chromium_app" in templates:
        for c in discover_electron(reg, templates):
            reg.cleaners.append(c)
    return reg


def _default_custom_dir() -> str:
    from .config import custom_cleaners_dir
    return custom_cleaners_dir()


# --------------------------------------------------------------------------
# Electron auto-discovery
# --------------------------------------------------------------------------

def _looks_electron(path: str) -> bool:
    try:
        names = set(os.listdir(path))
    except OSError:
        return False
    return sum(1 for m in ELECTRON_MARKERS if m in names) >= 2


def electron_candidates(home: str) -> list[str]:
    out = []
    bases = [os.path.join(home, ".config")]
    snap = os.path.join(home, "snap")
    var = os.path.join(home, ".var", "app")
    for base_root, sub in ((snap, "current/.config"), (var, "config")):
        try:
            with os.scandir(base_root) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        bases.append(os.path.join(e.path, sub))
        except OSError:
            pass
    for base in bases:
        try:
            with os.scandir(base) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False) and _looks_electron(e.path):
                        out.append(e.path)
        except OSError:
            pass
    return out


def discover_electron(reg: Registry, templates: dict[str, dict[str, Any]]) -> list[CleanerDef]:
    known = set(reg.config_roots)
    out = []
    used_ids = {c.id for c in reg.cleaners}
    for path in electron_candidates(reg.policy.home):
        real = os.path.realpath(path)
        if real in known or any(paths.is_within(real, k) for k in known):
            continue
        known.add(real)
        name = os.path.basename(path)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
        cid = f"electron-{slug}"
        n = 2
        while cid in used_ids:
            cid = f"electron-{slug}-{n}"
            n += 1
        used_ids.add(cid)
        raw = {"id": cid, "label": f"{name} (auto-detected)", "category": "Electron Apps",
               "template": "chromium_app", "vars": {"root": [path]},
               "running": {"process_names": [name, name.lower()]}}
        try:
            out.append(parse_cleaner(raw, templates, reg.policy, reg, source="auto-discovery"))
        except RegistryError as exc:
            reg.errors.append(f"auto-discovery {path}: {exc}")
    return out

"""Plain dataclasses shared by core and UI. No toolkit imports here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RATINGS = ("safe", "caution", "advanced")
RATING_ORDER = {r: i for i, r in enumerate(RATINGS)}
MODES = ("contents", "glob", "dir", "truncate", "file")
METHODS = ("delete", "trash", "truncate", "reset_xbel", "command", "root_action", "report")


@dataclass
class Target:
    mode: str
    path: str                      # pattern, '~' already expanded
    exclude: list[str] = field(default_factory=list)
    min_age_days: float | None = None
    keep_newest_n: int | None = None
    selector: str | None = None    # named special selector (see selectors.py)
    selector_args: dict[str, Any] = field(default_factory=dict)
    companions: bool = False       # Trash: also delete matching info/*.trashinfo


@dataclass
class Option:
    id: str
    label: str
    description: str
    rating: str
    root: bool = False
    requires_app_closed: bool = False
    targets: list[Target] = field(default_factory=list)
    method: str = "delete"
    command: str | None = None         # commands.py allow-list id (preferred if tool exists)
    command_only: bool = False         # never fall back to deleting targets
    root_action: dict[str, Any] | None = None  # {"id": ..., "params": {...}}
    root_fallback: dict[str, Any] | None = None  # used if command unavailable
    probe: str | None = None           # size probe id (commands.py) for command/root items
    probe_paths: list[str] = field(default_factory=list)  # read-only sizing for root items
    split: bool = False                # one result row per entry
    report_only: bool = False
    extra_confirmation: str | None = None
    note: str | None = None            # shown in the info popover
    exclude_known: bool = False        # generic ~/.cache/* rows
    overlap: str | None = None         # options measuring the same bytes; totals count the max
    cleaner_id: str = ""


@dataclass
class RunningSpec:
    process_names: list[str] = field(default_factory=list)
    singleton_lock: str | None = None
    snap_names: list[str] = field(default_factory=list)
    flatpak_ids: list[str] = field(default_factory=list)
    any_user: bool = False   # system cleaners: apt/dpkg run as root, not as the user


@dataclass
class CleanerDef:
    id: str
    label: str
    category: str
    options: list[Option]
    running: RunningSpec = field(default_factory=RunningSpec)
    source: str = ""
    custom: bool = False


@dataclass
class Entry:
    """One concrete thing to remove (file, dir, link) or modify."""

    path: str
    root: str                      # allow root it was found under (re-validated at delete time)
    kind: str = "file"             # file | dir | link | other
    size: int = 0                  # bytes on disk (st_blocks * 512, de-duplicated)
    apparent: int = 0
    count: int = 1
    mtime: float = 0.0             # newest mtime inside
    action: str = "delete"         # delete | trash | truncate | reset_xbel
    label: str | None = None
    companions: list[str] = field(default_factory=list)
    dev: int = 0
    ino: int = 0


@dataclass
class ScanResult:
    key: str                       # unique row key (option id, or option id + ':' + name)
    option: Option
    cleaner: CleanerDef
    label: str
    entries: list[Entry] = field(default_factory=list)
    size: int = 0
    apparent: int = 0
    count: int = 0
    mtime: float = 0.0
    size_known: bool = True
    approximate: bool = False
    commands: list[list[str]] = field(default_factory=list)
    root_actions: list[dict[str, Any]] = field(default_factory=list)
    unavailable: str | None = None     # reason the row cannot be cleaned
    errors: int = 0
    detail: str | None = None          # extra subtitle text (e.g. decoded workspace path)

    @property
    def rating(self) -> str:
        return self.option.rating

    @property
    def selectable(self) -> bool:
        if self.option.report_only or self.unavailable:
            return False
        return bool(self.entries or self.commands or self.root_actions)


def total_size(results) -> int:
    """Sum of sizes where options in the same ``overlap`` group count once (max)."""
    total = 0
    groups: dict[tuple[str, str], int] = {}
    for r in results:
        if r.option.report_only or not r.size_known:
            continue
        if r.option.overlap:
            k = (r.cleaner.id, r.option.overlap)
            groups[k] = max(groups.get(k, 0), r.size)
        else:
            total += r.size
    return total + sum(groups.values())


@dataclass
class PlanItem:
    result: ScanResult
    entries: list[Entry]
    commands: list[list[str]]
    root_actions: list[dict[str, Any]]

    @property
    def size(self) -> int:
        if self.entries:
            return sum(e.size for e in self.entries)
        return self.result.size


@dataclass
class CleanPlan:
    items: list[PlanItem]
    dry_run: bool = True

    @property
    def size(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def needs_root(self) -> bool:
        return any(i.root_actions for i in self.items)

    def ratings(self) -> dict[str, int]:
        out = {r: 0 for r in RATINGS}
        for i in self.items:
            out[i.result.rating] += 1
        return out


@dataclass
class ItemResult:
    key: str
    label: str
    status: str = "ok"             # ok | partial | failed | skipped | dry-run
    freed: int = 0
    deleted: int = 0
    errors: int = 0
    messages: list[str] = field(default_factory=list)


@dataclass
class CleanReport:
    items: list[ItemResult] = field(default_factory=list)
    dry_run: bool = True
    cancelled: bool = False
    statvfs_before: dict[str, int] = field(default_factory=dict)
    statvfs_after: dict[str, int] = field(default_factory=dict)
    log_path: str | None = None
    trashed: list[tuple[str, str]] = field(default_factory=list)  # (original, trash files/ path)
    trash_failed: list[Entry] = field(default_factory=list)       # ask before deleting instead

    @property
    def freed(self) -> int:
        return sum(i.freed for i in self.items)

    @property
    def statvfs_delta(self) -> int:
        delta = 0
        for k, before in self.statvfs_before.items():
            after = self.statvfs_after.get(k)
            if after is not None:
                delta += max(0, after - before)
        return delta

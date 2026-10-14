"""Turn selected scan results into a CleanPlan; preview rows and export."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterable
from dataclasses import dataclass

from .models import CleanPlan, PlanItem, ScanResult

PREVIEW_LIMIT = 5000


def build_plan(results: Iterable[ScanResult], *, dry_run: bool,
               excludes: Iterable[str] = (), skip_cleaners: Iterable[str] = ()) -> CleanPlan:
    """Plan for the given (selected) results.

    *excludes*: paths the user unticked in the preview. *skip_cleaners*:
    cleaner ids whose app is running and the user chose "Skip".
    """
    ex = {os.path.abspath(p) for p in excludes}
    skip = set(skip_cleaners)
    items = []
    for r in results:
        if not r.selectable:
            continue
        if r.option.requires_app_closed and r.cleaner.id in skip:
            continue
        cmds = [list(a) for a in r.commands]
        if cmds and not _then_delete(r):
            entries = []
        else:
            entries = [e for e in r.entries if os.path.abspath(e.path) not in ex]
        if not (entries or cmds or r.root_actions):
            continue
        items.append(PlanItem(result=r, entries=entries, commands=cmds,
                              root_actions=[dict(a) for a in r.root_actions]))
    return CleanPlan(items=items, dry_run=dry_run)


def _then_delete(r: ScanResult) -> bool:
    from .commands import COMMANDS
    spec = COMMANDS.get(r.option.command or "")
    return bool(spec and spec.then_delete)


@dataclass
class PreviewRow:
    group: str           # option label
    key: str
    kind: str            # file | dir | link | command | root
    path: str            # path, argv or action description
    size: int
    mtime: float
    rating: str


def preview_rows(plan: CleanPlan) -> list[PreviewRow]:
    rows: list[PreviewRow] = []
    for it in plan.items:
        r = it.result
        group = f"{r.cleaner.label} › {r.label}"
        for argv in it.commands:
            rows.append(PreviewRow(group, r.key, "command", " ".join(argv), r.size, 0, r.rating))
        for a in it.root_actions:
            params = " ".join(f"{k}={v}" for k, v in a.items() if k != "id")
            rows.append(PreviewRow(group, r.key, "root", f"[root] {a['id']} {params}".strip(),
                                   r.size, 0, r.rating))
        for e in it.entries:
            rows.append(PreviewRow(group, r.key, e.kind if e.action == "delete" else e.action,
                                   e.path, e.size, e.mtime, r.rating))
    return rows


def export_text(plan: CleanPlan) -> str:
    """Exact list of what Clean will act on (one row per path/command)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["option", "kind", "path_or_command", "bytes"])
    for row in preview_rows(plan):
        w.writerow([row.key, row.kind, row.path, row.size])
    return buf.getvalue()

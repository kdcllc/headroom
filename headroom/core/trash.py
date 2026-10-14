"""freedesktop.org Trash: move to trash (Gio when available) and restore."""

from __future__ import annotations

import os
import time
import urllib.parse

from . import paths


class TrashError(OSError):
    pass


def home_trash() -> str:
    return os.path.join(paths.xdg_data_home(), "Trash")


def _encode(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def _trash_home(path: str) -> str:
    """Spec-compliant move into the home trash; returns the files/ path."""
    trash = home_trash()
    files = os.path.join(trash, "files")
    info = os.path.join(trash, "info")
    os.makedirs(files, mode=0o700, exist_ok=True)
    os.makedirs(info, mode=0o700, exist_ok=True)
    if os.lstat(path).st_dev != os.lstat(files).st_dev:
        raise TrashError(f"{path} is on another filesystem than the home trash")
    base = os.path.basename(path.rstrip("/"))
    name = base
    n = 1
    while True:
        info_path = os.path.join(info, name + ".trashinfo")
        try:
            fd = os.open(info_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
            stem, ext = os.path.splitext(base)
            name = f"{stem}.{n}{ext}"
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("[Trash Info]\n")
        fh.write(f"Path={_encode(os.path.abspath(path))}\n")
        fh.write(f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    dest = os.path.join(files, name)
    try:
        os.rename(path, dest)
    except OSError:
        os.unlink(info_path)
        raise
    return dest


def find_trashed(original: str) -> str | None:
    """files/ path of the most recent home-trash item for *original*."""
    info = os.path.join(home_trash(), "info")
    best = None
    best_date = ""
    want = os.path.abspath(original)
    try:
        names = os.listdir(info)
    except OSError:
        return None
    for name in names:
        if not name.endswith(".trashinfo"):
            continue
        data = read_trashinfo(os.path.join(info, name))
        if data.get("Path") == want and data.get("DeletionDate", "") >= best_date:
            best_date = data.get("DeletionDate", "")
            best = os.path.join(home_trash(), "files", name[: -len(".trashinfo")])
    return best


def read_trashinfo(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k] = urllib.parse.unquote(v) if k == "Path" else v
    except OSError:
        pass
    return out


def trash(path: str, use_gio: bool = True) -> str | None:
    """Move *path* to the trash. Returns the trashed location when known.

    Raises :class:`TrashError` if trashing is impossible (the caller must
    ask before falling back to a permanent delete).
    """
    if use_gio:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError):
            Gio = None  # noqa: N806
        if Gio is not None:
            try:
                Gio.File.new_for_path(path).trash(None)
            except GLib.Error as exc:
                raise TrashError(exc.message) from exc
            return find_trashed(path)
    try:
        return _trash_home(path)
    except TrashError:
        raise
    except OSError as exc:
        raise TrashError(str(exc)) from exc


def restore(trashed_files_path: str) -> str:
    """Undo: move a home-trash item back to its ``Path=``. Returns that path."""
    name = os.path.basename(trashed_files_path)
    info_path = os.path.join(os.path.dirname(os.path.dirname(trashed_files_path)),
                             "info", name + ".trashinfo")
    original = read_trashinfo(info_path).get("Path")
    if not original or not os.path.isabs(original):
        raise TrashError("trash info has no original path")
    if os.path.lexists(original):
        raise TrashError(f"{original} already exists")
    os.makedirs(os.path.dirname(original), exist_ok=True)
    os.rename(trashed_files_path, original)
    try:
        os.unlink(info_path)
    except OSError:
        pass
    return original

"""User configuration in ~/.config/headroom/config.json."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "first_run": True,
    "dry_run": True,
    "show_advanced": False,
    "large_file_threshold_mb": 500,
    "workspace_stale_days": 90,
    "history_days": 90,
    "journal_size_mb": 200,
    "journal_days": 14,
    "snap_retain": 2,
    "tmp_days": 10,
    "var_tmp_days": 30,
    "project_junk_days": 30,
    "user_file_method": "trash",      # trash | delete
    "excluded_paths": [],
    "project_roots": ["~"],
    "preview_excludes": [],
    "docker_builder_all": False,
}

BOUNDS = {
    "large_file_threshold_mb": (10, 1_000_000),
    "workspace_stale_days": (1, 3650),
    "history_days": (1, 3650),
    "journal_size_mb": (50, 100_000),
    "journal_days": (1, 3650),
    "snap_retain": (2, 20),
    "tmp_days": (1, 365),
    "var_tmp_days": (7, 365),
    "project_junk_days": (0, 3650),
}


def config_dir() -> str:
    return os.path.join(paths.xdg_config_home(), "headroom")


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def custom_cleaners_dir() -> str:
    return os.path.join(config_dir(), "cleaners.d")


class Config(dict):
    """A dict with defaults, validation and atomic save."""

    def __init__(self, data: dict[str, Any] | None = None, path: str | None = None):
        super().__init__(DEFAULTS)
        self.path = path or config_path()
        if data:
            self.update(self._sanitize(data))

    @classmethod
    def load(cls, path: str | None = None) -> Config:
        path = path or config_path()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        return cls(data, path)

    @staticmethod
    def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for key, default in DEFAULTS.items():
            if key not in data:
                continue
            value = data[key]
            if isinstance(default, bool):
                if isinstance(value, bool):
                    out[key] = value
            elif isinstance(default, int):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    lo, hi = BOUNDS.get(key, (-(2**31), 2**31))
                    out[key] = int(min(max(value, lo), hi))
            elif isinstance(default, list):
                if isinstance(value, list):
                    out[key] = [v for v in value if isinstance(v, str)]
            elif isinstance(default, str):
                if key == "user_file_method" and value not in ("trash", "delete"):
                    continue
                if isinstance(value, str):
                    out[key] = value
        return out

    def set(self, key: str, value: Any) -> None:
        self.update(self._sanitize({key: value}))

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".config-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

"""Append-only JSONL clean logs in $XDG_STATE_HOME/headroom/."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from . import paths

KEEP_LOGS = 30


def log_dir() -> str:
    return os.path.join(paths.xdg_state_home(), "headroom")


class CleanLog:
    """One log file per clean run; thread-safe append of one record per line."""

    def __init__(self, directory: str | None = None, keep: int = KEEP_LOGS):
        self.directory = directory or log_dir()
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self.directory, f"clean-{stamp}.jsonl")
        n = 1
        while os.path.exists(path):
            path = os.path.join(self.directory, f"clean-{stamp}-{n}.jsonl")
            n += 1
        self.path = path
        self._lock = threading.Lock()
        # O_APPEND | O_EXCL: never overwrite an existing log
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self._fh = os.fdopen(fd, "a", encoding="utf-8")
        prune_logs(self.directory, keep)

    def write(self, option_id: str, result: str, *, path: str | None = None,
              argv: list[str] | None = None, bytes_: int = 0, error: str | None = None,
              **extra: Any) -> None:
        rec: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "option": option_id,
            "result": result,
            "bytes": bytes_,
        }
        if path is not None:
            rec["path"] = path
        if argv is not None:
            rec["argv"] = argv
        if error:
            rec["error"] = error
        rec.update(extra)
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()


def prune_logs(directory: str, keep: int = KEEP_LOGS) -> None:
    try:
        logs = sorted(f for f in os.listdir(directory)
                      if f.startswith("clean-") and f.endswith(".jsonl"))
    except OSError:
        return
    for name in logs[:-keep] if keep > 0 else logs:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


def read_log(path: str) -> list[dict[str, Any]]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def latest_log() -> str | None:
    d = log_dir()
    try:
        logs = sorted(f for f in os.listdir(d) if f.startswith("clean-") and f.endswith(".jsonl"))
    except OSError:
        return None
    return os.path.join(d, logs[-1]) if logs else None

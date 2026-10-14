"""Talk to the root helper through pkexec (one authentication per run).

The plan sent to the helper contains only action IDs and bounded numbers;
the helper re-validates everything against its own hard-coded table.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from typing import Any

HELPER_PATH = "/usr/libexec/headroom/headroom-helper"
PKEXEC = "/usr/bin/pkexec"
TIMEOUT = 3600


class HelperError(Exception):
    pass


class AuthCancelled(HelperError):
    pass


def helper_installed(path: str = HELPER_PATH) -> bool:
    """True only for a root-owned helper that no other user can modify.

    We never pkexec a user-writable script (dev checkouts are refused).
    """
    try:
        st = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        return False
    d = os.path.dirname(path)
    while True:
        try:
            dst = os.stat(d)
        except OSError:
            return False
        if dst.st_uid != 0 or dst.st_mode & 0o022:
            return False
        if d == "/":
            break
        d = os.path.dirname(d)
    return os.path.exists(PKEXEC)


def build_plan(actions: list[dict[str, Any]]) -> str:
    clean = []
    for a in actions:
        item = {"id": str(a["id"])}
        for k, v in a.items():
            if k != "id" and isinstance(v, (int, bool)):
                item[k] = v
        clean.append(item)
    return json.dumps({"actions": clean})


def _parse_lines(out: str) -> list[dict[str, Any]]:
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            lines.append(json.loads(line))
        except ValueError:
            pass
    return lines


def _invoke(args: list[str], stdin: str | None) -> subprocess.CompletedProcess:
    if not helper_installed():
        raise HelperError("system helper is not installed")
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY"):
        if k in os.environ:
            env[k] = os.environ[k]
    try:
        cp = subprocess.run([PKEXEC, HELPER_PATH, *args], input=stdin, capture_output=True,
                            text=True, timeout=TIMEOUT, shell=False, env=env, check=False)
    except subprocess.TimeoutExpired as exc:
        raise HelperError("system helper timed out") from exc
    if cp.returncode == 126:
        raise AuthCancelled("authentication was cancelled")
    if cp.returncode == 127:
        raise AuthCancelled("not authorized")
    return cp


def run_plan(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run root actions; returns one dict per action (id, ok, freed_bytes, stderr_tail)."""
    cp = _invoke(["--plan-stdin"], build_plan(actions))
    lines = _parse_lines(cp.stdout)
    if cp.returncode not in (0, 1) and not lines:
        raise HelperError(f"helper failed ({cp.returncode}): {cp.stderr.strip()[-300:]}")
    return lines


def scan_sizes() -> dict[str, int]:
    """Sizes of root-only items (helper ``--scan``)."""
    cp = _invoke(["--scan"], None)
    out = {}
    for line in _parse_lines(cp.stdout):
        if "id" in line and isinstance(line.get("size_bytes"), int):
            out[line["id"]] = line["size_bytes"]
    return out

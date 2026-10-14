"""Parsers for the text output of system tools (always run with LANG=C)."""

from __future__ import annotations

import json
import re

_DEC_UNITS = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "pb": 1000**5}
_BIN_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4, "p": 1024**5}


def parse_docker_size(text: str) -> int:
    """``14.68GB (86%)`` -> bytes (docker uses decimal SI units)."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGTP]?B)", text or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _DEC_UNITS[m.group(2).lower()])


def parse_docker_df(output: str) -> dict[str, dict[str, int]]:
    """``docker system df --format '{{json .}}'`` -> {Type: {size, reclaimable, count, active}}."""
    out: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("Type")
        if not kind:
            continue
        out[kind] = {
            "size": parse_docker_size(row.get("Size", "")),
            "reclaimable": parse_docker_size(row.get("Reclaimable", "")),
            "count": int(row.get("TotalCount") or 0),
            "active": int(row.get("Active") or 0),
        }
    return out


def parse_journal_usage(output: str) -> int:
    """``Archived and active journals take up 4.0G in the file system.`` -> bytes."""
    m = re.search(r"take up\s+([\d.]+)\s*([BKMGTP])", output or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _BIN_UNITS[m.group(2).lower()])


def parse_snap_list(output: str) -> list[dict[str, str]]:
    """``snap list --all --color=never --unicode=never`` -> rows."""
    rows = []
    lines = (output or "").splitlines()
    for line in lines[1:] if lines and lines[0].startswith("Name") else lines:
        f = line.split()
        if len(f) < 6:
            continue
        rows.append({"name": f[0], "version": f[1], "rev": f[2], "tracking": f[3],
                     "publisher": f[4], "notes": f[-1]})
    return rows


def disabled_snaps(output: str) -> list[tuple[str, str]]:
    """(name, revision) pairs whose Notes column contains ``disabled``."""
    out = []
    for row in parse_snap_list(output):
        notes = row["notes"].split(",")
        if "disabled" in notes and row["rev"].isdigit():
            out.append((row["name"], row["rev"]))
    return out


def parse_apt_simulation(output: str) -> list[str]:
    """Package names from ``apt-get -s autoremove --purge`` (``Remv``/``Purg`` lines)."""
    pkgs = []
    for line in (output or "").splitlines():
        m = re.match(r"^(Remv|Purg)\s+(\S+)", line)
        if m:
            name = m.group(2)
            if name not in pkgs:
                pkgs.append(name)
    return pkgs


def running_kernel_packages(uname_r: str) -> set[str]:
    return {f"{p}-{uname_r}" for p in (
        "linux-image", "linux-image-unsigned", "linux-modules", "linux-modules-extra",
        "linux-headers", "linux-objects-nvidia", "linux-signatures-nvidia")}


def parse_installed_sizes(output: str) -> int:
    """Sum of ``dpkg-query -W -f='${Installed-Size}\\n'`` (KiB) -> bytes."""
    total = 0
    for line in (output or "").split():
        if line.isdigit():
            total += int(line) * 1024
    return total


def parse_glib_size(text: str) -> int:
    """``553.7 MB`` / ``1.0 GB`` / ``12 bytes`` (GLib decimal units) -> bytes."""
    m = re.match(r"\s*([\d.,]+)\s*(bytes|[kKMGTP]?B)\b", text or "")
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    if unit == "bytes":
        return int(num)
    return int(num * _DEC_UNITS[unit.lower()])


def parse_flatpak_runtimes(output: str) -> list[tuple[str, str, int]]:
    """``flatpak list --runtime --columns=application,branch,size`` -> (id, branch, bytes)."""
    rows = []
    for line in (output or "").splitlines():
        f = [c.strip() for c in line.split("\t")]
        if len(f) < 3 or f[0].lower() in ("application id", "application"):
            continue
        rows.append((f[0], f[1], parse_glib_size(f[2])))
    return rows


def parse_flatpak_app_runtimes(output: str) -> set[tuple[str, str]]:
    """``flatpak list --app --columns=runtime`` -> {(runtime id, branch)}."""
    used = set()
    for line in (output or "").splitlines():
        ref = line.strip()
        parts = ref.split("/")
        if len(parts) == 3:
            used.add((parts[0], parts[2]))
    return used


def estimate_unused_flatpak(runtimes_out: str, apps_out: str) -> tuple[int, list[str]]:
    """Best-effort size of runtimes no app depends on (approximate)."""
    used = parse_flatpak_app_runtimes(apps_out)
    used_ids = {u[0] for u in used}
    total = 0
    names = []
    for rid, branch, size in parse_flatpak_runtimes(runtimes_out):
        if (rid, branch) in used:
            continue
        # extensions of a used runtime (…Platform.Locale, …Platform.GL.default) stay
        if any(rid.startswith(u + ".") for u in used_ids):
            continue
        total += size
        names.append(f"{rid}//{branch}")
    return total, names

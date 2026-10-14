"""Fixed allow-list of unprivileged tool commands and size probes.

Every subprocess runs with an argv list, ``shell=False``, a timeout and
``LANG=C``. Command ids come from cleaner definitions; anything not in
:data:`COMMANDS` is rejected at registry load.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

from . import parsers

SAFE_ENV_KEYS = ("HOME", "USER", "LOGNAME", "PATH", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
                 "XDG_CONFIG_HOME", "XDG_DATA_HOME", "HF_HOME", "HF_HUB_CACHE",
                 "GOPATH", "GOCACHE", "GOMODCACHE", "CONDA_EXE", "NVM_DIR", "DOCKER_HOST")


def tool_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    extra = [os.path.expanduser(p) for p in ("~/.local/bin", "~/.cargo/bin", "~/go/bin")]
    env["PATH"] = ":".join([env["PATH"], *extra])
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    return env


@dataclass(frozen=True)
class CommandSpec:
    tools: tuple[str, ...]          # first one found on PATH is used as argv[0]
    args: tuple[str, ...]
    timeout: int = 600
    then_delete: bool = False       # run, then also delete the option's targets
    needs_docker: bool = False
    extra_tools: tuple[str, ...] = field(default=())  # conda: also try these install dirs


COMMANDS: dict[str, CommandSpec] = {
    "pip.purge": CommandSpec(("pip3", "pip"), ("cache", "purge")),
    "uv.clean": CommandSpec(("uv",), ("cache", "clean")),
    "npm.clean": CommandSpec(("npm",), ("cache", "clean", "--force")),
    "yarn.clean": CommandSpec(("yarn",), ("cache", "clean")),
    "yarn.clean_mirror": CommandSpec(("yarn",), ("cache", "clean", "--mirror")),
    "pnpm.prune": CommandSpec(("pnpm",), ("store", "prune")),
    "go.cache": CommandSpec(("go",), ("clean", "-cache")),
    "go.modcache": CommandSpec(("go",), ("clean", "-modcache")),
    "gradle.stop": CommandSpec(("gradle",), ("--stop",), timeout=60, then_delete=True),
    "dotnet.nuget": CommandSpec(("dotnet",), ("nuget", "locals", "all", "--clear")),
    "conda.clean": CommandSpec(("conda", "mamba"), ("clean", "--all", "-y"),
                               extra_tools=("~/miniforge3/bin/conda", "~/miniconda3/bin/conda",
                                            "~/anaconda3/bin/conda", "~/mambaforge/bin/conda")),
    "composer.clear": CommandSpec(("composer",), ("clear-cache",)),
    "gem.cleanup": CommandSpec(("gem",), ("cleanup",)),
    "brew.cleanup": CommandSpec(("brew",), ("cleanup", "--prune=all"),
                                extra_tools=("/home/linuxbrew/.linuxbrew/bin/brew",)),
    "flatpak.user_unused": CommandSpec(("flatpak",), ("uninstall", "--user", "--unused", "-y")),
    "docker.builder": CommandSpec(("docker",), ("builder", "prune", "-f"), needs_docker=True),
    "docker.builder_all": CommandSpec(("docker",), ("builder", "prune", "-f", "--all"),
                                      needs_docker=True),
    "docker.system": CommandSpec(("docker",), ("system", "prune", "-f"), needs_docker=True),
    "docker.images_all": CommandSpec(("docker",), ("image", "prune", "-a", "-f"), needs_docker=True),
    "docker.volumes": CommandSpec(("docker",), ("volume", "prune", "-f"), needs_docker=True),
    "docker.volumes_all": CommandSpec(("docker",), ("volume", "prune", "-a", "-f"), needs_docker=True),
}


def which(tool: str) -> str | None:
    if tool.startswith("~/") or tool.startswith("/"):
        path = os.path.expanduser(tool)
        return path if os.path.isfile(path) and os.access(path, os.X_OK) else None
    return shutil.which(tool, path=tool_env()["PATH"])


def docker_accessible() -> bool:
    """True if the user can talk to the Docker daemon without root."""
    if os.environ.get("DOCKER_HOST"):
        return which("docker") is not None
    sock = "/var/run/docker.sock"
    return which("docker") is not None and os.path.exists(sock) and os.access(sock, os.R_OK | os.W_OK)


def resolve(command_id: str) -> list[str] | None:
    """Exact argv for an allow-listed command, or None if the tool is missing."""
    spec = COMMANDS.get(command_id)
    if spec is None:
        raise KeyError(f"command not in allow-list: {command_id}")
    if spec.needs_docker and not docker_accessible():
        return None
    for tool in (*spec.tools, *spec.extra_tools):
        path = which(tool)
        if path:
            return [path, *spec.args]
    return None


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run(argv: list[str], timeout: int = 600, input_text: str | None = None,
        env: dict[str, str] | None = None) -> CommandResult:
    """Run a command safely: argv list, no shell, timeout, LANG=C."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a non-empty list of strings")
    try:
        cp = subprocess.run(argv, input=input_text, capture_output=True, text=True,
                            timeout=timeout, shell=False, env=env or tool_env(), check=False)
        return CommandResult(argv, cp.returncode, cp.stdout, cp.stderr)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return CommandResult(argv, -1, out, "timed out", timed_out=True)
    except OSError as exc:
        return CommandResult(argv, -1, "", str(exc))


# --------------------------------------------------------------------------
# size probes for command / root items (read-only)
# --------------------------------------------------------------------------

@dataclass
class Probe:
    size: int | None
    approximate: bool = False
    detail: str | None = None


def _docker_df() -> dict[str, dict[str, int]] | None:
    if not docker_accessible():
        return None
    r = run([which("docker") or "docker", "system", "df", "--format", "{{json .}}"], timeout=60)
    return parsers.parse_docker_df(r.stdout) if r.ok else None


def probe(probe_id: str, config: dict | None = None) -> Probe:
    config = config or {}
    if probe_id.startswith("docker_df:"):
        df = _docker_df()
        if df is None:
            return Probe(None, detail="Docker not accessible without root")
        kinds = probe_id.split(":", 1)[1].split("+")
        total = sum(df.get(k, {}).get("reclaimable", 0) for k in kinds)
        return Probe(total, approximate=len(kinds) > 1)
    if probe_id == "journal":
        jc = which("journalctl")
        if not jc:
            return Probe(None)
        r = run([jc, "--disk-usage"], timeout=30)
        usage = parsers.parse_journal_usage(r.stdout + r.stderr)
        keep = int(config.get("journal_size_mb", 200)) * 1024 * 1024
        if not usage:
            return Probe(None, detail="journal size needs root")
        return Probe(max(0, usage - keep), approximate=True,
                     detail=f"journal uses {usage // (1024 * 1024)} MiB")
    if probe_id == "snap_disabled":
        snap = which("snap")
        if not snap:
            return Probe(None, detail="snapd not installed")
        r = run([snap, "list", "--all", "--color=never", "--unicode=never"], timeout=60)
        total = 0
        names = []
        for name, rev in parsers.disabled_snaps(r.stdout):
            names.append(f"{name} r{rev}")
            try:
                st = os.lstat(f"/var/lib/snapd/snaps/{name}_{rev}.snap")
                total += st.st_blocks * 512
            except OSError:
                pass
        return Probe(total, detail=", ".join(names) or None)
    if probe_id == "apt_autoremove":
        apt = which("apt-get")
        if not apt:
            return Probe(None)
        r = run([apt, "-s", "autoremove", "--purge"], timeout=120)
        pkgs = parsers.parse_apt_simulation(r.stdout)
        if not pkgs:
            return Probe(0)
        q = run(["dpkg-query", "-W", "-f=${Installed-Size}\n", *pkgs], timeout=60)
        return Probe(parsers.parse_installed_sizes(q.stdout), detail=" ".join(pkgs))
    if probe_id in ("flatpak_user_unused", "flatpak_system_unused"):
        fp = which("flatpak")
        if not fp:
            return Probe(None, detail="flatpak not installed")
        scope = "--user" if probe_id == "flatpak_user_unused" else "--system"
        rts = run([fp, "list", scope, "--runtime", "--columns=application,branch,size"], timeout=60)
        apps = run([fp, "list", "--app", "--columns=runtime"], timeout=60)
        size, names = parsers.estimate_unused_flatpak(rts.stdout, apps.stdout)
        return Probe(size, approximate=True, detail=", ".join(names) or None)
    return Probe(None)

"""procs, config, log, planner, largefiles, commands, privileged."""

import json
import os
import time

import pytest

from headroom.core import commands, config, largefiles, log, planner, privileged, procs
from headroom.core.models import CleanerDef, Entry, Option, RunningSpec, ScanResult
from headroom.core.paths import SafetyPolicy

from .conftest import write


# ---------------------------------------------------------------- procs
def _proc(root, pid, comm, exe="", cmdline=(), cgroup="0::/user.slice\n"):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "comm").write_text(comm + "\n")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in cmdline) + b"\0")
    (d / "cgroup").write_text(cgroup)
    if exe:
        os.symlink(exe, d / "exe")


@pytest.fixture
def fake_proc(tmp_path):
    root = tmp_path / "proc"
    _proc(root, 100, "cursor", "/tmp/.mount_Cursor/cursor", ["/tmp/.mount_Cursor/cursor", "--type=renderer"])
    _proc(root, 200, "firefox", "/snap/firefox/4173/usr/lib/firefox/firefox", ["/snap/firefox/current/usr/lib/firefox/firefox"],
          cgroup="0::/user.slice/user-1000.slice/user@1000.service/app.slice/snap.firefox.firefox-1234.scope\n")
    _proc(root, 300, "bwrap", "/usr/bin/bwrap", ["bwrap", "--args", "40", "--", "spotify"],
          cgroup="0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-flatpak-com.spotify.Client-999.scope\n")
    _proc(root, 400, "code-insiders", "/snap/code-insiders/2593/usr/share/code-insiders/code-insiders",
          ["/snap/code-insiders/2593/usr/share/code-insiders/code-insiders"])
    (root / "self").mkdir()
    return root


def test_running_detection(fake_proc):
    plist = list(procs.iter_procs(str(fake_proc)))
    assert len(plist) == 4
    assert procs.is_running(RunningSpec(process_names=["cursor", "Cursor"]), procs=plist)
    assert procs.is_running(RunningSpec(snap_names=["firefox"]), procs=plist)
    assert procs.is_running(RunningSpec(flatpak_ids=["com.spotify.Client"]), procs=plist)
    assert procs.is_running(RunningSpec(process_names=["code-insiders"]), procs=plist)
    assert not procs.is_running(RunningSpec(process_names=["code"], snap_names=["code"]), procs=plist)
    assert not procs.is_running(RunningSpec(process_names=["slack"]), procs=plist)
    assert not procs.is_running(RunningSpec(), procs=plist)


def test_other_users_processes(fake_proc):
    plist = list(procs.iter_procs(str(fake_proc)))
    for p in plist:
        if p.comm == "cursor":
            p.uid = os.getuid() + 1  # someone else's Cursor
    assert not procs.is_running(RunningSpec(process_names=["cursor"]), procs=plist)
    # system cleaners (apt/dpkg run as root) look at every user's processes
    assert procs.is_running(RunningSpec(process_names=["cursor"], any_user=True), procs=plist)


def test_singleton_lock(tmp_path, fake_proc):
    lock = tmp_path / "SingletonLock"
    os.symlink("myhost-100", lock)
    assert procs.is_running(RunningSpec(singleton_lock=str(lock)), proc_root=str(fake_proc), procs=[])
    os.unlink(lock)
    os.symlink("myhost-99999", lock)
    assert not procs.is_running(RunningSpec(singleton_lock=str(lock)), proc_root=str(fake_proc), procs=[])


# ---------------------------------------------------------------- config
def test_config_sanitizes(home):
    p = os.path.join(config.config_dir(), "config.json")
    write(p, json.dumps({"snap_retain": 99, "journal_size_mb": "lots", "show_advanced": "yes",
                         "user_file_method": "shred", "excluded_paths": ["~/x", 3], "bogus": 1}))
    c = config.Config.load()
    assert c["snap_retain"] == 20
    assert c["journal_size_mb"] == 200
    assert c["show_advanced"] is False
    assert c["user_file_method"] == "trash"
    assert c["excluded_paths"] == ["~/x"]
    assert "bogus" not in c
    c.set("dry_run", False)
    c.save()
    assert config.Config.load()["dry_run"] is False


def test_config_defaults_dry_run_first(home):
    c = config.Config.load()
    assert c["dry_run"] is True and c["first_run"] is True


# ---------------------------------------------------------------- log
def test_log_rotation(home):
    d = log.log_dir()
    os.makedirs(d)
    for i in range(35):
        write(os.path.join(d, f"clean-20240101-0000{i:02d}.jsonl"), "{}\n")
    lg = log.CleanLog()
    lg.write("x", "ok", path="/a", bytes_=3)
    lg.close()
    files = sorted(f for f in os.listdir(d) if f.endswith(".jsonl"))
    assert len(files) == 30
    assert lg.path.endswith(files[-1])
    rec = log.read_log(lg.path)[0]
    assert rec["option"] == "x" and rec["bytes"] == 3 and rec["path"] == "/a"
    assert oct(os.stat(lg.path).st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------- planner
def _row(key, rating="safe", cleaner="app", requires_closed=False, entries=None, **kw):
    opt = Option(id=key, label=key, description="", rating=rating, requires_app_closed=requires_closed)
    c = CleanerDef(id=cleaner, label=cleaner, category="User Caches", options=[opt])
    return ScanResult(key=key, option=opt, cleaner=c, label=key, entries=entries or [], **kw)


def test_planner_excludes_and_skips(tmp_path):
    e1 = Entry(path=str(tmp_path / "a"), root=str(tmp_path), size=10)
    e2 = Entry(path=str(tmp_path / "b"), root=str(tmp_path), size=20)
    r1 = _row("one", entries=[e1, e2], size=30)
    r2 = _row("two", cleaner="cursor", requires_closed=True, entries=[e1], size=10)
    report = _row("three", entries=[e1], size=10)
    report.option.report_only = True
    plan = planner.build_plan([r1, r2, report], dry_run=False, excludes=[str(tmp_path / "a")],
                              skip_cleaners=["cursor"])
    assert [i.result.key for i in plan.items] == ["one"]
    assert [e.path for e in plan.items[0].entries] == [str(tmp_path / "b")]
    assert plan.size == 20
    text = planner.export_text(plan)
    assert text.splitlines()[1].split("\t") == ["one", "file", str(tmp_path / "b"), "20"]


def test_planner_command_replaces_entries(tmp_path):
    e = Entry(path=str(tmp_path / "a"), root=str(tmp_path), size=10)
    r = _row("pip.cache", entries=[e], commands=[["/usr/bin/pip3", "cache", "purge"]], size=10)
    r.option.command = "pip.purge"
    plan = planner.build_plan([r], dry_run=False)
    assert plan.items[0].entries == [] and plan.items[0].commands
    rows = planner.preview_rows(plan)
    assert rows[0].kind == "command" and rows[0].path == "/usr/bin/pip3 cache purge"


def test_plan_ratings_and_root(tmp_path):
    r = _row("x", rating="caution", root_actions=[{"id": "apt.clean"}], size=5)
    plan = planner.build_plan([r], dry_run=True)
    assert plan.needs_root and plan.ratings()["caution"] == 1


# ---------------------------------------------------------------- largefiles
def test_large_files(home):
    big = home / "videos" / "movie.mkv"
    write(big, b"x" * (2 * 1024 * 1024))
    write(home / "Documents" / "big.pdf", b"x" * (2 * 1024 * 1024))
    write(home / ".local/share/Trash/files/big", b"x" * (2 * 1024 * 1024))
    write(home / "small", b"x")
    os.symlink(big, home / "link-to-movie")
    pol = SafetyPolicy(extra_roots=[str(home)])
    found = largefiles.find_large_files([str(home)], 1024 * 1024, pol)
    assert [f.path for f in found] == [str(big)]
    assert found[0].category == "Video"


def test_project_junk(home):
    now = time.time()
    old = now - 100 * 86400
    write(home / "proj/a/package.json", "{}")
    write(home / "proj/a/node_modules/x/index.js", b"x" * 5000, mtime=old)
    os.utime(home / "proj/a/node_modules/x", (old, old))
    os.utime(home / "proj/a/node_modules", (old, old))
    write(home / "proj/b/target/CACHEDIR.TAG", "Signature", mtime=old)
    os.utime(home / "proj/b/target", (old, old))
    write(home / "proj/c/target/notcache", "x", mtime=old)   # no CACHEDIR.TAG -> not junk
    write(home / "proj/d/build/out", "x", mtime=old)         # no sibling manifest -> not junk
    write(home / "proj/e/node_modules/new.js", "x")          # too recent
    pol = SafetyPolicy(extra_roots=[str(home / "proj")])
    found = largefiles.find_project_junk([str(home / "proj")], pol, min_age_days=30, now=now)
    got = {os.path.relpath(f.path, home / "proj") for f in found}
    assert got == {"a/node_modules", "b/target"}


def test_downloads_listing(home):
    write(home / "Downloads/ubuntu.iso", b"x" * 1000)
    write(home / "Downloads/folder/a", b"x")
    pol = SafetyPolicy()
    cats = {os.path.basename(f.path): f.category for f in largefiles.list_downloads(pol)}
    assert cats == {"ubuntu.iso": "ISO image", "folder": "Folder"}


# ---------------------------------------------------------------- commands
def test_commands_allow_list():
    with pytest.raises(KeyError):
        commands.resolve("rm.everything")
    for spec in commands.COMMANDS.values():
        assert all(isinstance(a, str) for a in spec.args)
        assert "--force-pkgs-dirs" not in spec.args


def test_run_rejects_strings():
    with pytest.raises(ValueError):
        commands.run("echo hi")  # type: ignore[arg-type]
    r = commands.run(["/bin/echo", "hi"], timeout=5)
    assert r.ok and r.stdout.strip() == "hi"
    r = commands.run(["/bin/sh", "-c", "echo $LANG"], timeout=5)
    assert r.stdout.strip() == "C"


# ---------------------------------------------------------------- privileged
def test_helper_installed_refuses_user_writable(tmp_path):
    p = tmp_path / "helper"
    p.write_text("#!/bin/sh\n")
    os.chmod(p, 0o755)
    assert not privileged.helper_installed(str(p))  # not root-owned


def test_build_plan_drops_non_numeric():
    plan = json.loads(privileged.build_plan([{"id": "journal.vacuum", "size_mb": 200, "path": "/etc"}]))
    assert plan == {"actions": [{"id": "journal.vacuum", "size_mb": 200}]}

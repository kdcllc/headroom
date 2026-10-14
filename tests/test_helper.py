import importlib.machinery
import importlib.util
import io
import json
import os
import time

import pytest

from .conftest import fixture_text, write

HELPER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "helper", "headroom-helper")


@pytest.fixture
def helper(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("jc_helper", HELPER)
    spec = importlib.util.spec_from_loader("jc_helper", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    calls = []

    def fake_run(argv, timeout=1800, extra_env=None):
        calls.append(argv)
        return 0, "", ""
    monkeypatch.setattr(mod, "run", fake_run)
    mod.calls = calls
    return mod


def test_helper_is_stdlib_only():
    import ast
    import sys
    src = open(HELPER).read()
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert "shell=True" not in src


@pytest.mark.parametrize("plan,msg", [
    ({"actions": [{"id": "rm -rf /"}]}, "unknown action"),
    ({"actions": [{"id": "apt.clean; reboot"}]}, "unknown action"),
    ({"actions": [{"id": "apt.clean", "path": "/etc"}]}, "unexpected parameter"),
    ({"actions": [{"id": "journal.vacuum", "size_mb": 1}]}, "out of range"),
    ({"actions": [{"id": "journal.vacuum", "size_mb": 10**9}]}, "out of range"),
    ({"actions": [{"id": "journal.vacuum", "size_mb": "200; rm -rf /"}]}, "must be an integer"),
    ({"actions": [{"id": "journal.vacuum", "size_mb": True}]}, "must be an integer"),
    ({"actions": [{"id": "snap.retain", "value": 1}]}, "out of range"),
    ({"actions": [{"id": "docker.volumes", "all": 1}]}, "must be a boolean"),
    ({"actions": [{"id": "apt.clean"}, {"id": "apt.clean"}]}, "duplicate"),
    ({"actions": []}, "non-empty"),
    ({"actions": [{"id": "apt.clean"}], "extra": "/bin/sh"}, "only 'actions'"),
    ({"actions": [{"id": "crash.var"}] * 40}, "non-empty"),
    (["apt.clean"], "only 'actions'"),
    ({"actions": ["apt.clean"]}, "string id"),
])
def test_validate_rejects(helper, plan, msg):
    with pytest.raises(helper.PlanError, match=msg):
        helper.validate_plan(plan)


def test_validate_defaults(helper):
    plan = helper.validate_plan({"actions": [{"id": "journal.vacuum", "size_mb": 300},
                                             {"id": "apt.clean"}]})
    assert plan == [("journal.vacuum", {"size_mb": 300, "days": 14}), ("apt.clean", {})]


def test_main_requires_root(helper, monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert helper.main(["--plan-stdin"]) == 2
    assert helper.main(["--bogus"]) == 2


def test_main_rejects_bad_plan_before_running(helper, monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chdir", lambda p: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"actions": [{"id": "x"}]})))
    assert helper.main(["--plan-stdin"]) == 2
    assert helper.calls == []
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_main_runs_plan_with_fixed_argv(helper, monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chdir", lambda p: None)
    monkeypatch.setattr(helper, "APT_ARCHIVES", "/nonexistent")
    plan = {"actions": [{"id": "apt.clean"}, {"id": "snap.retain", "value": 3},
                        {"id": "journal.vacuum", "size_mb": 250, "days": 7}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(plan)))
    assert helper.main(["--plan-stdin"]) == 0
    assert ["apt-get", "clean"] in helper.calls
    assert ["snap", "set", "system", "refresh.retain=3"] in helper.calls
    assert ["journalctl", "--vacuum-size=250M"] in helper.calls
    assert ["journalctl", "--vacuum-time=7d"] in helper.calls
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x["id"] for x in lines] == ["apt.clean", "snap.retain", "journal.vacuum"]
    assert all(set(x) >= {"id", "ok", "freed_bytes", "stderr_tail"} for x in lines)


def test_autoremove_refuses_running_kernel(helper, monkeypatch):
    sim = fixture_text("apt_autoremove_kernels.txt")
    monkeypatch.setattr(helper, "run", lambda argv, **k: (0, sim, "") if "-s" in argv else (0, "", ""))
    monkeypatch.setattr(os, "uname", lambda: os.uname_result(("Linux", "h", "5.15.0-88-generic", "", "x86_64")))
    r = helper.act_apt_autoremove({})
    assert not r["ok"] and "running kernel" in r["stderr_tail"]


def test_autoremove_runs_when_safe(helper, monkeypatch):
    sim = fixture_text("apt_autoremove_kernels.txt")
    calls = []

    def run(argv, **k):
        calls.append(argv)
        if "-s" in argv:
            return 0, sim, ""
        if argv[0] == "dpkg-query":
            return 0, "1000\n2000\n", ""
        return 0, "", ""
    monkeypatch.setattr(helper, "run", run)
    monkeypatch.setattr(os, "uname", lambda: os.uname_result(("Linux", "h", "5.15.0-91-generic", "", "x86_64")))
    r = helper.act_apt_autoremove({})
    assert r["ok"] and r["freed_bytes"] == 3000 * 1024
    assert calls[-1] == ["apt-get", "-y", "autoremove", "--purge"]


def test_snap_disabled(helper, monkeypatch, tmp_path):
    out = fixture_text("snap_list_all.txt")
    calls = []

    def run(argv, **k):
        calls.append(argv)
        return (0, out, "") if argv[:2] == ["snap", "list"] else (0, "", "")
    monkeypatch.setattr(helper, "run", run)
    monkeypatch.setattr(helper, "SNAPS_DIR", str(tmp_path))
    write(tmp_path / "brave_692.snap", b"x" * 8192)
    r = helper.act_snap_disabled({})
    assert ["snap", "remove", "brave", "--revision=692"] in calls
    assert r["ok"] and r["freed_bytes"] >= 8192
    assert all(c[0] == "snap" for c in calls)


def test_tmp_cleaning_is_safe(helper, monkeypatch, tmp_path):
    root = tmp_path / "tmp"
    old = time.time() - 40 * 86400
    write(root / "old.txt", b"x" * 100, mtime=old)
    write(root / "new.txt", b"x" * 100)
    write(root / "sub" / "old2", b"x", mtime=old)
    write(root / "systemd-private-abc" / "old", b"x", mtime=old)
    write(root / ".X11-unix" / "X0", b"x", mtime=old)
    outside = tmp_path / "precious"
    write(outside / "old", b"keep", mtime=old)
    os.symlink(outside, root / "evil-link")
    os.utime(root / "sub", (old, old))
    monkeypatch.setattr(helper, "TMP", str(root))
    monkeypatch.setattr(helper, "open_files", lambda: set())
    r = helper.act_tmp_tmp({"days": 10})
    assert r["ok"]
    assert not (root / "old.txt").exists()
    assert (root / "new.txt").exists()
    assert not (root / "sub").exists()  # emptied old dir removed
    assert (root / "systemd-private-abc" / "old").exists()
    assert (root / ".X11-unix" / "X0").exists()
    assert (outside / "old").read_bytes() == b"keep"
    assert os.path.islink(root / "evil-link")


def test_tmp_skips_open_files(helper, monkeypatch, tmp_path):
    root = tmp_path / "tmp"
    old = time.time() - 40 * 86400
    p = write(root / "inuse", b"x", mtime=old)
    st = os.stat(p)
    monkeypatch.setattr(helper, "TMP", str(root))
    monkeypatch.setattr(helper, "open_files", lambda: {(st.st_dev, st.st_ino)})
    helper.act_tmp_tmp({"days": 10})
    assert os.path.exists(p)


def test_logs_rotated_skips_journal_and_live(helper, monkeypatch, tmp_path):
    log = tmp_path / "log"
    for name in ("syslog", "syslog.1", "syslog.2.gz", "apt/history.log.1.gz", "kern.log.old",
                 "journal/abc/system@x.journal~", "journal/abc/user.gz"):
        write(log / name, b"x" * 100)
    monkeypatch.setattr(helper, "VAR_LOG", str(log))
    r = helper.act_logs_rotated({})
    assert r["ok"] and r["files"] == 4
    assert (log / "syslog").exists()
    assert (log / "journal/abc/user.gz").exists()
    assert not (log / "syslog.2.gz").exists()


def test_truncate_large_never_deletes(helper, monkeypatch, tmp_path):
    log = tmp_path / "log"
    big = log / "runaway.log"
    write(big, b"x")
    with open(big, "r+b") as fh:
        fh.truncate(600 * 1024 * 1024)
    write(log / "small.log", b"x" * 10)
    monkeypatch.setattr(helper, "VAR_LOG", str(log))
    r = helper.act_logs_truncate_large({"threshold_mb": 500})
    assert r["ok"]
    assert big.exists() and big.stat().st_size == 0
    assert (log / "small.log").stat().st_size == 10


def test_clean_children_keep_and_symlink(helper, monkeypatch, tmp_path):
    lists = tmp_path / "lists"
    write(lists / "lock", b"")
    write(lists / "partial" / "x", b"x")
    write(lists / "archive.ubuntu.com_dists_jammy_InRelease", b"x" * 100)
    outside = tmp_path / "outside"
    write(outside / "f", b"keep")
    os.symlink(outside, lists / "link")
    monkeypatch.setattr(helper, "APT_LISTS", str(lists))
    helper.act_apt_lists({})
    assert sorted(os.listdir(lists)) == ["link", "lock", "partial"]
    assert (outside / "f").exists()
    assert ["apt-get", "update"] in helper.calls


def test_open_root_refuses_symlinked_component(helper, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "link")
    with pytest.raises(OSError):
        helper.open_root(str(tmp_path / "link"))


def test_docker_actions_argv(helper):
    helper.have = lambda tool: True
    helper.act_docker_builder({"all": True, "until_hours": 168})
    helper.act_docker_volumes({"all": False})
    assert ["docker", "builder", "prune", "-f", "--all", "--filter", "until=168h"] in helper.calls
    assert ["docker", "volume", "prune", "-f"] in helper.calls
    assert helper.parse_docker_reclaimed(fixture_text("docker_prune.txt")) == 1_234_000_000


def test_parsers_agree_with_core(helper):
    from headroom.core import parsers
    for name in ("snap_list_all.txt",):
        assert helper.parse_disabled_snaps(fixture_text(name)) == parsers.disabled_snaps(fixture_text(name))
    j = fixture_text("journalctl_disk_usage.txt")
    assert helper.parse_journal_usage(j) == parsers.parse_journal_usage(j)
    a = fixture_text("apt_autoremove_kernels.txt")
    assert helper.parse_apt_removals(a) == parsers.parse_apt_simulation(a)


def test_execute_continues_after_failure(helper, monkeypatch, capsys):
    def boom(p):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(helper.ACTIONS, "crash.var", boom)
    monkeypatch.setattr(helper, "APT_ARCHIVES", "/nonexistent")
    lines = helper.execute([("crash.var", {}), ("apt.clean", {})])
    assert [line["ok"] for line in lines] == [False, True]

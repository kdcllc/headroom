import os
import shutil
import stat

import pytest

from headroom.core import deleter as deleter_mod
from headroom.core import planner, trash
from headroom.core.deleter import XBEL_EMPTY, Deleter
from headroom.core.log import CleanLog, read_log
from headroom.core.models import CleanerDef, Option, ScanResult, Target
from headroom.core.scanner import ScanContext, scan_option

from .conftest import snapshot, write


def _scan(policy, targets, method="delete", **kw):
    opt = Option(id="t.opt", label="T", description="", rating="safe", targets=targets,
                 method=method, **kw)
    c = CleanerDef(id="t", label="T", category="User Caches", options=[opt])
    rows = scan_option(opt, c, ScanContext(policy=policy))
    return rows


def _plan(rows, dry_run=False, **kw):
    return planner.build_plan(rows, dry_run=dry_run, **kw)


def test_rmtree_safety_assert():
    deleter_mod.assert_rmtree_safe()


def test_symlink_to_documents_inside_cache(home, policy, tmp_path):
    docs = home / "Documents"
    write(docs / "thesis.odt", b"precious")
    write(home / ".cache/app/junk/f", b"x" * 5000)
    os.symlink(docs, home / ".cache/app/docs")
    os.symlink(docs / "thesis.odt", home / ".cache/app/junk/thesis-link")
    before = snapshot(docs)
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert snapshot(docs) == before
    assert (docs / "thesis.odt").read_bytes() == b"precious"
    assert os.listdir(home / ".cache/app") == []
    assert rep.items[0].status == "ok"


def test_race_dir_swapped_for_symlink(home, policy):
    """Between scan and delete a cache dir is replaced by a symlink to ~/Documents."""
    docs = home / "Documents"
    write(docs / "a.txt", b"keep")
    write(home / ".cache/app/sub/f", b"x" * 5000)
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    shutil.rmtree(home / ".cache/app/sub")
    os.symlink(docs, home / ".cache/app/sub")
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert (docs / "a.txt").read_bytes() == b"keep"
    assert rep.items[0].errors == 1
    assert "changed since scan" in rep.items[0].messages[0]


def test_race_parent_swapped_for_symlink(home, policy, tmp_path):
    """The *parent* of an entry is swapped for a symlink to ~/Documents."""
    docs = home / "Documents"
    write(docs / "f", b"keep")
    write(home / ".cache/app/f", b"x" * 100)
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    shutil.rmtree(home / ".cache/app")
    os.symlink(docs, home / ".cache/app")
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert (docs / "f").read_bytes() == b"keep"
    assert rep.items[0].errors == 1


def test_dry_run_changes_nothing(home, policy):
    write(home / ".cache/app/a/b/c", b"x" * 20000)
    write(home / ".cache/app/d", b"x" * 20000)
    write(home / ".xsession-errors", b"log" * 1000)
    rows = _scan(policy, [Target("contents", str(home / ".cache/app")),
                          Target("truncate", str(home / ".xsession-errors"))])
    before = snapshot(home)
    log = CleanLog(str(home.parent / "logs"))
    rep = Deleter(policy, dry_run=True, log=log).run(_plan(rows, dry_run=True))
    log.close()
    assert snapshot(home) == before
    assert rep.dry_run and rep.freed > 0
    assert all(i.status == "dry-run" for i in rep.items)
    recs = read_log(log.path)
    assert {r["result"] for r in recs if r["option"] == "t.opt"} == {"dry-run"}


def test_dry_run_runs_no_commands_and_no_helper(home, policy):
    calls = []
    opt = Option(id="c.opt", label="C", description="", rating="safe", command="npm.clean")
    c = CleanerDef(id="c", label="C", category="Developer Caches", options=[opt])
    r1 = ScanResult(key="c.opt", option=opt, cleaner=c, label="C", commands=[["/usr/bin/npm", "cache", "clean", "--force"]], size=10)
    ropt = Option(id="r.opt", label="R", description="", rating="safe", root=True, method="root_action",
                  root_action={"id": "apt.clean"})
    r2 = ScanResult(key="r.opt", option=ropt, cleaner=c, label="R", root_actions=[{"id": "apt.clean"}], size=10)
    d = Deleter(policy, dry_run=True, run_command=lambda *a, **k: calls.append(a),
                root_runner=lambda *a, **k: calls.append(a))
    rep = d.run(_plan([r1, r2], dry_run=True))
    assert calls == []
    assert [i.status for i in rep.items] == ["dry-run", "dry-run"]


def test_truncate_and_delete_old(home, policy):
    write(home / ".xsession-errors", b"x" * 50000)
    write(home / ".xsession-errors.old", b"x" * 50000)
    rows = _scan(policy, [Target("truncate", str(home / ".xsession-errors")),
                          Target("file", str(home / ".xsession-errors.old"))])
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert rep.items[0].status == "ok"
    assert os.path.getsize(home / ".xsession-errors") == 0
    assert not os.path.exists(home / ".xsession-errors.old")


def test_reset_xbel(home, policy):
    p = home / ".local/share/recently-used.xbel"
    write(p, "<xbel>" + "x" * 5000 + "</xbel>")
    rows = _scan(policy, [Target("file", str(p))], method="reset_xbel")
    Deleter(policy, dry_run=False).run(_plan(rows))
    assert p.read_text() == XBEL_EMPTY


def test_trash_and_restore(home, policy, monkeypatch):
    dl = home / "Downloads"
    write(dl / "ubuntu.iso", b"x" * 10000)
    rows = _scan(policy, [Target("glob", str(dl / "*.iso"))], method="trash")
    rep = Deleter(policy, dry_run=False, trash_func=lambda p: trash.trash(p, use_gio=False)).run(_plan(rows))
    assert not (dl / "ubuntu.iso").exists()
    assert len(rep.trashed) == 1
    original, trashed = rep.trashed[0]
    assert os.path.exists(trashed)
    info = home / ".local/share/Trash/info/ubuntu.iso.trashinfo"
    assert trash.read_trashinfo(str(info))["Path"] == str(dl / "ubuntu.iso")
    trash.restore(trashed)
    assert (dl / "ubuntu.iso").exists()
    assert not info.exists()


def test_trash_failure_reports_error(home, policy):
    write(home / "Downloads/a.deb", b"x")
    rows = _scan(policy, [Target("glob", str(home / "Downloads/*.deb"))], method="trash")

    def fail(p):
        raise trash.TrashError("no trash on this volume")
    rep = Deleter(policy, dry_run=False, trash_func=fail).run(_plan(rows))
    assert (home / "Downloads/a.deb").exists()
    assert rep.items[0].status == "failed"


def test_home_trash_with_companions(home, policy):
    t = home / ".local/share/Trash"
    write(t / "files/old.txt", b"x" * 3000)
    write(t / "info/old.txt.trashinfo", "[Trash Info]\nPath=/x\n")
    write(t / "info/other.trashinfo", "[Trash Info]\nPath=/y\n")
    rows = _scan(policy, [Target("contents", str(t / "files"), companions=True)])
    Deleter(policy, dry_run=False).run(_plan(rows))
    assert os.listdir(t / "files") == []
    assert os.listdir(t / "info") == ["other.trashinfo"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_permission_errors_continue(home, policy):
    write(home / ".cache/app/locked/f", b"x" * 100)
    write(home / ".cache/app/free", b"x" * 100)
    os.chmod(home / ".cache/app/locked", stat.S_IRUSR | stat.S_IXUSR)
    try:
        rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
        rep = Deleter(policy, dry_run=False).run(_plan(rows))
        assert not (home / ".cache/app/free").exists()
        assert rep.items[0].status == "partial"
        assert rep.items[0].errors >= 1
    finally:
        os.chmod(home / ".cache/app/locked", 0o755)


def test_vanished_entry_is_skipped_not_error(home, policy):
    write(home / ".cache/app/f", b"x")
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    os.unlink(home / ".cache/app/f")
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert rep.items[0].errors == 0


def test_hard_link_frees_nothing(home, policy):
    write(home / ".cache/app/a", b"x" * 100000)
    os.link(home / ".cache/app/a", home / "shared-copy")
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    rep = Deleter(policy, dry_run=False).run(_plan(rows))
    assert rep.items[0].freed == 0
    assert (home / "shared-copy").exists()


def test_cancel_stops_after_current_item(home, policy):
    write(home / ".cache/a/f")
    write(home / ".cache/b/f")
    opt1 = _scan(policy, [Target("dir", str(home / ".cache/a"))])
    opt2 = _scan(policy, [Target("dir", str(home / ".cache/b"))])
    opt2[0].key = "second"
    d = Deleter(policy, dry_run=False)
    d.run  # noqa: B018
    rep = d.run(_plan(opt1 + opt2), on_item=lambda r: d.cancel.set())
    assert rep.cancelled
    assert not (home / ".cache/a").exists()
    assert (home / ".cache/b").exists()


def test_preview_export_matches_log(home, policy):
    """Definition of done: the log lists exactly what the preview export listed."""
    write(home / ".cache/app/x", b"x" * 1000)
    write(home / ".cache/app/y/z", b"x" * 1000)
    rows = _scan(policy, [Target("contents", str(home / ".cache/app"))])
    plan = _plan(rows)
    exported = {line.split("\t")[2] for line in planner.export_text(plan).splitlines()[1:]}
    log = CleanLog(str(home.parent / "logs"))
    Deleter(policy, dry_run=False, log=log).run(plan)
    log.close()
    logged = {r["path"] for r in read_log(log.path) if r.get("path") and r["result"] == "ok"}
    assert exported == logged


def test_root_items_batched_into_one_call(home, policy):
    opt = Option(id="r", label="R", description="", rating="safe", root=True, method="root_action")
    c = CleanerDef(id="sys", label="S", category="System", options=[opt])
    rows = [ScanResult(key=f"r{i}", option=opt, cleaner=c, label=f"R{i}", root_actions=[{"id": aid}], size=5)
            for i, aid in enumerate(["apt.clean", "crash.var"])]
    calls = []

    def runner(actions):
        calls.append(actions)
        return [{"id": a["id"], "ok": True, "freed_bytes": 7} for a in actions]
    rep = Deleter(policy, dry_run=False, root_runner=runner).run(_plan(rows))
    assert len(calls) == 1 and [a["id"] for a in calls[0]] == ["apt.clean", "crash.var"]
    assert rep.freed == 14

import os
import time

from headroom.core import scanner
from headroom.core.models import CleanerDef, Option, Target
from headroom.core.scanner import ScanContext, collect_target, du, safe_glob, scan_option

from .conftest import write


def _opt(targets, **kw):
    return Option(id="t.opt", label="T", description="", rating="safe", targets=targets, **kw)


def test_du_sparse_file_uses_blocks(tmp_path):
    p = tmp_path / "sparse"
    with open(p, "wb") as fh:
        fh.truncate(100 * 1024 * 1024)
    u = du(str(p))
    assert u.apparent == 100 * 1024 * 1024
    assert u.disk < 1024 * 1024


def test_du_hard_links_counted_once(tmp_path):
    write(tmp_path / "d" / "a", b"x" * 100000)
    os.link(tmp_path / "d" / "a", tmp_path / "d" / "b")
    single = du(str(tmp_path / "d" / "a")).disk
    u = du(str(tmp_path / "d"))
    assert u.count == 1
    assert u.disk == single + os.lstat(tmp_path / "d").st_blocks * 512


def test_du_does_not_follow_symlinks(tmp_path):
    write(tmp_path / "big" / "f", b"x" * 1_000_000)
    (tmp_path / "d").mkdir()
    os.symlink(tmp_path / "big", tmp_path / "d" / "link")
    u = du(str(tmp_path / "d"))
    assert u.disk < 100_000


def test_du_cross_device_skipped(tmp_path, monkeypatch):
    write(tmp_path / "d" / "same" / "f", b"x" * 50000)
    write(tmp_path / "d" / "mnt" / "f", b"x" * 500000)
    real_scandir = os.scandir

    class FakeEntry:
        def __init__(self, e):
            self._e = e
            self.path = e.path
            self.name = e.name

        def stat(self, follow_symlinks=False):
            st = self._e.stat(follow_symlinks=False)
            if self.name == "mnt":
                vals = list(st)
                vals[2] = st.st_dev + 1  # st_dev
                return os.stat_result(vals)
            return st

    class FakeIt:
        def __init__(self, p):
            self._it = real_scandir(p)

        def __enter__(self):
            return self

        def __iter__(self):
            return (FakeEntry(e) for e in self._it)

        def __exit__(self, *a):
            self._it.close()

    monkeypatch.setattr(scanner.os, "scandir", lambda p: FakeIt(p))
    u = du(str(tmp_path / "d"))
    assert u.disk < 400000


def test_safe_glob_does_not_follow_wildcard_symlinks(home, policy, tmp_path):
    write(home / ".cache/mozilla/firefox/real.default/cache2/x")
    outside = tmp_path / "outside" / "cache2"
    write(outside / "precious")
    os.symlink(tmp_path / "outside", home / ".cache/mozilla/firefox/evil")
    got = safe_glob(str(home / ".cache/mozilla/firefox/*/cache2"), policy)
    assert got == [str(home / ".cache/mozilla/firefox/real.default/cache2")]


def test_safe_glob_literal_current_symlink_inside_root(home, policy):
    write(home / "snap/slack/42/.config/Slack/Cache/f")
    os.symlink("42", home / "snap/slack/current")
    got = safe_glob(str(home / "snap/slack/current/.config/Slack/Cache"), policy)
    assert got == [str(home / "snap/slack/42/.config/Slack/Cache")]


def test_safe_glob_doublestar(home):
    write(home / ".cache/a/b/c/x.log")
    write(home / ".cache/x.log")
    got = sorted(safe_glob(str(home / ".cache/**/*.log")))
    assert got == [str(home / ".cache/a/b/c/x.log"), str(home / ".cache/x.log")]


def test_contents_target_symlink_root_refused(home, policy, tmp_path):
    """A cache root that is itself a symlink outside the allow-list is refused."""
    docs = home / "Documents"
    write(docs / "thesis.odt")
    (home / ".cache").mkdir()
    os.symlink(docs, home / ".cache" / "evilapp")
    ctx = ScanContext(policy=policy)
    entries = collect_target(Target("contents", str(home / ".cache/evilapp")), _opt([]), ctx)
    assert entries == []


def test_contents_entries_and_symlink_child(home, policy):
    write(home / ".cache/app/a", b"x" * 5000)
    write(home / "Documents/keep.txt")
    os.symlink(home / "Documents", home / ".cache/app/docs-link")
    ctx = ScanContext(policy=policy)
    entries = collect_target(Target("contents", str(home / ".cache/app")), _opt([]), ctx)
    kinds = {os.path.basename(e.path): e.kind for e in entries}
    assert kinds == {"a": "file", "docs-link": "link"}


def test_keep_newest_n(home, policy):
    base = home / ".config/Cursor/CachedData"
    now = time.time()
    for i, name in enumerate(["old", "mid", "new"]):
        write(base / name / "f", mtime=now - (3 - i) * 86400)
        os.utime(base / name, (now - (3 - i) * 86400,) * 2)
    policy.register_app_root(str(home / ".config/Cursor"))
    ctx = ScanContext(policy=policy)
    entries = collect_target(Target("contents", str(base), keep_newest_n=1), _opt([]), ctx)
    assert sorted(os.path.basename(e.path) for e in entries) == ["mid", "old"]


def test_min_age(home, policy):
    base = home / ".cache/hist"
    now = time.time()
    write(base / "old" / "f", mtime=now - 200 * 86400)
    os.utime(base / "old", (now - 200 * 86400,) * 2)
    write(base / "new" / "f")
    ctx = ScanContext(policy=policy, config={"history_days": 90})
    entries = collect_target(Target("contents", str(base), min_age_days="$history_days"), _opt([]), ctx)
    assert [os.path.basename(e.path) for e in entries] == ["old"]


def test_exclude_patterns(home, policy):
    write(home / ".cache/a/keep.lock")
    write(home / ".cache/a/drop")
    ctx = ScanContext(policy=policy)
    entries = collect_target(Target("contents", str(home / ".cache/a"), exclude=["*.lock"]), _opt([]), ctx)
    assert [os.path.basename(e.path) for e in entries] == ["drop"]


def test_sockets_never_entries(home, policy):
    import socket
    (home / ".cache/s").mkdir(parents=True)
    sock_path = str(home / ".cache/s/sock")
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(sock_path)
        ctx = ScanContext(policy=policy)
        entries = collect_target(Target("contents", str(home / ".cache/s")), _opt([]), ctx)
        assert entries == []
    finally:
        s.close()


def test_split_and_scan_option(home, policy):
    write(home / ".cache/one/f", b"x" * 9000)
    write(home / ".cache/two/f", b"x" * 9000)
    opt = _opt([Target("contents", str(home / ".cache"))], split=True)
    c = CleanerDef(id="t", label="T", category="User Caches", options=[opt])
    rows = scan_option(opt, c, ScanContext(policy=policy))
    assert sorted(r.key for r in rows) == ["t.opt:one", "t.opt:two"]
    assert all(r.size > 0 for r in rows)


def test_full_scan_on_fake_home(home):
    from headroom.core.registry import default_data_dir, load_registry
    write(home / ".config/Cursor/Cache/Cache_Data/data_1", b"x" * 20000)
    write(home / ".config/Cursor/User/globalStorage/state.vscdb", b"x" * 20000)
    write(home / ".cache/thumbnails/normal/a.png", b"x" * 20000)
    reg = load_registry(default_data_dir(), custom_dir="", discover=True, strict=True)
    ctx = ScanContext(policy=reg.policy, run_probes=False)
    results = scanner.scan(reg, ctx)
    keys = {r.key for rs in results.values() for r in rs}
    assert "cursor.cache" in keys
    assert "thumbnails.cache" in keys
    info = [r for r in results["cursor"] if r.key == "cursor.global_storage_info"][0]
    assert info.option.report_only and not info.selectable and info.size > 0
    # the live state DB is never an entry anywhere
    for rs in results.values():
        for r in rs:
            for e in r.entries:
                assert not e.path.endswith("state.vscdb")

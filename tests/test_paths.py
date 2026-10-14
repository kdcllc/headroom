import os

from headroom.core import paths
from headroom.core.paths import SafetyPolicy, is_within

from .conftest import write


def test_is_within_prefix_lookalike(home):
    cache = home / ".cache"
    evil = home / ".cache-evil"
    cache.mkdir()
    evil.mkdir()
    assert is_within(str(cache / "x"), str(cache))
    assert is_within(str(cache), str(cache))
    assert not is_within(str(evil / "x"), str(cache))
    assert not is_within(str(evil), str(cache))


def test_is_within_parent_symlink_outside_refused(home, tmp_path):
    cache = home / ".cache"
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, cache / "link")
    # candidate's *parent* resolves outside the root -> refused
    assert not is_within(str(cache / "link" / "file"), str(cache))
    # the link itself lives inside the root (we would only unlink it)
    assert is_within(str(cache / "link"), str(cache))


def test_is_within_root_is_resolved(home, tmp_path):
    real = tmp_path / "realcache"
    real.mkdir()
    os.symlink(real, home / ".cache")
    assert is_within(str(real / "x"), str(home / ".cache"))


def test_is_within_dotdot(home):
    cache = home / ".cache"
    cache.mkdir()
    assert not is_within(str(cache) + "/../.ssh/id_rsa", str(cache))


def test_deny_list_wins_over_allow(home):
    pol = SafetyPolicy(extra_roots=[str(home)])
    (home / ".ssh").mkdir()
    write(home / ".ssh" / "id_rsa")
    assert not pol.check(str(home / ".ssh" / "id_rsa"))
    assert not pol.check(str(home / ".ssh"))
    assert not pol.check(str(home / "Documents" / "a.txt"))
    assert not pol.check(str(home))
    assert not pol.check("/")
    assert not pol.check("/etc/passwd")
    assert not pol.check("/usr/lib/x")
    assert not pol.check("/var/lib/dpkg/status")
    assert not pol.check("/var/lib/docker/overlay2")


def test_deny_editor_user_config(policy, home):
    base = home / ".config" / "Code" / "User"
    for name in ("settings.json", "keybindings.json", "snippets", "profiles", "globalStorage"):
        assert policy.is_denied(str(base / name)), name
    assert policy.is_denied(str(base / "globalStorage" / "state.vscdb"))
    assert policy.is_denied(str(base / "snippets" / "py.json"))
    # explicit exception
    assert not policy.is_denied(str(base / "globalStorage" / "state.vscdb.backup"))
    # workspaceStorage is not denied
    assert not policy.is_denied(str(base / "workspaceStorage" / "abc"))
    # snap layout too
    snapbase = home / "snap/code/123/.config/Code/User"
    assert policy.is_denied(str(snapbase / "settings.json"))


def test_deny_firefox_profiles_and_shared(policy, home):
    assert policy.is_denied(str(home / ".mozilla/firefox/abc.default/places.sqlite"))
    assert policy.is_denied(str(home / "snap/firefox/common/.mozilla/firefox/x"))
    assert policy.is_denied(str(home / ".vscode-shared/x"))
    assert policy.is_denied(str(home / ".local/share/keyrings/login.keyring"))
    assert not policy.is_denied(str(home / "snap/firefox/common/.cache/mozilla/firefox/x/cache2"))


def test_check_allow_roots(policy, home):
    write(home / ".cache" / "foo" / "bar")
    assert policy.check(str(home / ".cache" / "foo"))
    # an allow root itself (a directory) is never removed
    v = policy.check(str(home / ".cache"))
    assert not v and "root" in v.reason
    # outside every root
    write(home / "projects" / "x")
    assert not policy.check(str(home / "projects" / "x"))
    assert not policy.check("relative/path")


def test_check_mount_point_refused(policy, home, monkeypatch):
    target = home / ".cache" / "mnt"
    target.mkdir(parents=True)
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(target))
    v = policy.check(str(target))
    assert not v and v.reason == "mount point"


def test_home_core_files(policy, home):
    write(home / "core.1234")
    os.mkdir(home / "core.dir")
    assert policy.check(str(home / "core.1234"))
    assert not policy.check(str(home / "core.dir"))
    write(home / "notes.txt")
    assert not policy.check(str(home / "notes.txt"))


def test_app_roots_registration(policy, home):
    app = home / ".config" / "Slack"
    write(app / "Cache" / "f")
    assert not policy.check(str(app / "Cache" / "f"))
    policy.register_app_root(str(app))
    assert policy.check(str(app / "Cache" / "f"))
    # registering a denied path does nothing
    policy.register_app_root(str(home / ".ssh"))
    assert str(home / ".ssh") not in policy.app_roots


def test_user_excluded(home):
    pol = SafetyPolicy(user_excluded=["~/.cache/keep"])
    write(home / ".cache/keep/a")
    write(home / ".cache/other/a")
    assert not pol.check(str(home / ".cache/keep/a"))
    assert pol.check(str(home / ".cache/other/a"))


def test_downloads_dir_from_user_dirs(home):
    write(home / ".config" / "user-dirs.dirs", 'XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
    assert paths.downloads_dir() == str(home / "Telechargements")


def test_static_prefix():
    assert paths.static_prefix("/a/b/*/c") == "/a/b"
    assert paths.static_prefix("/a/b") == "/a/b"
    assert paths.static_prefix("/*") == "/"

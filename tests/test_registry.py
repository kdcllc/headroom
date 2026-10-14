import json
import os

import pytest

from headroom.core import registry
from headroom.core.registry import RegistryError, load_registry

from .conftest import write

DATA = registry.default_data_dir()


def _write_def(d, name, obj):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj))


def _minimal(**over):
    opt = {"id": "x.cache", "label": "X", "description": "", "rating": "safe",
           "targets": [{"mode": "contents", "path": "~/.cache/x"}]}
    opt.update(over.pop("option", {}))
    d = {"id": "x", "label": "X", "category": "User Caches", "options": [opt]}
    d.update(over)
    return d


def test_builtin_registry_loads_strict(home):
    reg = load_registry(DATA, custom_dir="", strict=True, discover=False)
    assert not reg.errors
    ids = [o.id for o in reg.options()]
    assert len(ids) == len(set(ids))
    # spot-check §4 coverage
    for oid in ("cursor.cached_data", "cursor.workspace_stale", "vscode.cache",
                "vscode-insiders.old_extensions", "firefox.cache", "chrome.cache",
                "apt.clean", "journal.vacuum", "snap.disabled", "docker.volumes",
                "trash.home", "go.modcache", "huggingface.models", "cursor.global_storage_backup"):
        assert oid in ids, oid
    cats = {c.category for c in reg.cleaners}
    assert cats <= set(registry.CATEGORIES)


def test_template_expands_list_vars(home):
    reg = load_registry(DATA, custom_dir="", strict=True, discover=False)
    cache = reg.option("vscode.cache")
    roots = {t.path.split("/Cache")[0] for t in cache.targets if t.path.endswith("/Cache")}
    assert str(home / ".config/Code") in roots
    assert str(home / "snap/code/current/.config/Code") in roots
    assert str(home / ".var/app/com.visualstudio.code/config/Code") in roots
    # VSCodium has no remote server -> server options dropped
    assert reg.option("vscodium.server_bin") is None


def test_never_targets_state_vscdb(home):
    reg = load_registry(DATA, custom_dir="", strict=True, discover=False)
    for o in reg.options():
        for t in o.targets:
            assert not t.path.endswith("state.vscdb"), o.id
            assert "settings.json" not in t.path


def test_bad_json(home, tmp_path):
    d = tmp_path / "defs"
    _write_def(d, "bad.json", "{ not json")
    reg = load_registry(str(d), custom_dir="", discover=False)
    assert reg.errors and "bad.json" in reg.errors[0]
    with pytest.raises(RegistryError):
        load_registry(str(d), custom_dir="", discover=False, strict=True)


@pytest.mark.parametrize("over,msg", [
    ({"option": {"rating": "yolo"}}, "unknown rating"),
    ({"option": {"method": "shred"}}, "unknown method"),
    ({"option": {"targets": [{"mode": "nuke", "path": "~/.cache/x"}]}}, "unknown mode"),
    ({"option": {"targets": [{"mode": "contents", "path": "~/projects"}]}}, "outside the allow-list"),
    ({"option": {"targets": [{"mode": "contents", "path": "~/.ssh"}]}}, "deny-list"),
    ({"option": {"targets": [{"mode": "contents", "path": "/etc"}]}}, "deny-list"),
    ({"option": {"targets": [{"mode": "contents", "path": "~/.cache/../.ssh"}]}}, "'..'"),
    ({"option": {"targets": [{"mode": "glob", "path": "~/.local/share/**/x"}]}}, r"'\*\*'"),
    ({"option": {"command": "rm -rf /"}}, "allow-list"),
    ({"option": {"root": True, "method": "root_action", "root_action": {"id": "shell"},
                 "targets": []}}, "unknown root action"),
    ({"option": {"targets": [{"mode": "contents", "path": "~/.cache/x", "selector": "evil"}]}},
     "unknown selector"),
    ({"category": "Nope"}, "unknown category"),
    ({"id": "Bad Id!"}, "bad cleaner id"),
])
def test_validation_rejects(home, tmp_path, over, msg):
    d = tmp_path / "defs"
    _write_def(d, "x.json", _minimal(**over))
    with pytest.raises(RegistryError, match=msg):
        load_registry(str(d), custom_dir="", discover=False, strict=True)


def test_config_app_root_registered(home, tmp_path):
    d = tmp_path / "defs"
    _write_def(d, "x.json", _minimal(option={"targets": [{"mode": "contents", "path": "~/.config/FooApp/Cache"}]}))
    reg = load_registry(str(d), custom_dir="", discover=False, strict=True)
    assert str(home / ".config/FooApp") in reg.policy.app_roots
    assert not reg.policy.check(str(home / ".config/OtherApp/Cache/x"))


def test_custom_definitions_restricted(home, tmp_path):
    builtin = tmp_path / "defs"
    _write_def(builtin, "x.json", _minimal())
    custom = tmp_path / "custom"
    ok = _minimal(id="mine", option={"id": "mine.junk", "rating": "caution",
                                     "targets": [{"mode": "contents", "path": "~/myapp/cache"}]})
    _write_def(custom, "ok.json", ok)
    safe = _minimal(id="mine2", option={"id": "mine2.junk", "rating": "safe",
                                        "targets": [{"mode": "contents", "path": "~/other/cache"}]})
    _write_def(custom, "safe.json", safe)
    outside = _minimal(id="mine3", option={"id": "mine3.junk", "rating": "caution",
                                           "targets": [{"mode": "contents", "path": "/opt/x"}]})
    _write_def(custom, "outside.json", outside)
    cmd = _minimal(id="mine4", option={"id": "mine4.junk", "rating": "caution",
                                       "command": "npm.clean"})
    _write_def(custom, "cmd.json", cmd)
    reg = load_registry(str(builtin), custom_dir=str(custom), discover=False)
    assert reg.cleaner("mine") is not None and reg.cleaner("mine").custom
    assert reg.cleaner("mine2") is None and reg.cleaner("mine3") is None and reg.cleaner("mine4") is None
    assert len(reg.errors) == 3
    assert any("caution or advanced" in e for e in reg.errors)
    assert any("under $HOME" in e for e in reg.errors)


def test_duplicate_option_ids(home, tmp_path):
    d = tmp_path / "defs"
    _write_def(d, "a.json", _minimal())
    _write_def(d, "b.json", _minimal(id="y"))
    reg = load_registry(str(d), custom_dir="", discover=False)
    assert any("duplicate option id" in e for e in reg.errors)


def test_electron_autodiscovery(home):
    for sub in ("Cache", "GPUCache", "Local Storage"):
        (home / ".config" / "WeirdApp" / sub).mkdir(parents=True)
    write(home / ".config" / "WeirdApp" / "Cache" / "data_0")
    (home / ".config" / "NotElectron" / "Cache").mkdir(parents=True)
    for sub in ("Cache", "Code Cache"):  # already covered by the Slack definition
        (home / ".config" / "Slack" / sub).mkdir(parents=True)
    reg = load_registry(DATA, custom_dir="", discover=True, strict=True)
    auto = [c for c in reg.cleaners if c.source == "auto-discovery"]
    assert [c.id for c in auto] == ["electron-weirdapp"]
    opts = {o.id for o in auto[0].options}
    assert opts == {"electron-weirdapp.cache", "electron-weirdapp.logs"}
    # never Local Storage
    assert not any("Local Storage" in t.path for o in auto[0].options for t in o.targets)


def test_root_actions_match_helper():
    import importlib.machinery
    import importlib.util
    path = os.path.join(os.path.dirname(DATA), "..", "helper", "headroom-helper")
    loader = importlib.machinery.SourceFileLoader("helper_mod", os.path.abspath(path))
    spec = importlib.util.spec_from_loader("helper_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    assert set(mod.ACTIONS) == registry.ROOT_ACTIONS

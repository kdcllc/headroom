import json
import os
import time

from headroom.core import selectors
from headroom.core.selectors import SelectorEnv

from .conftest import write


def _ws(base, name, data, age_days=0):
    d = base / name
    write(d / "workspace.json", json.dumps(data))
    t = time.time() - age_days * 86400
    os.utime(d / "workspace.json", (t, t))
    os.utime(d, (t, t))
    return str(d)


def test_stale_workspace(tmp_path):
    ws = tmp_path / "workspaceStorage"
    exists = tmp_path / "proj"
    exists.mkdir()
    a = _ws(ws, "a", {"folder": f"file://{exists}"})
    b = _ws(ws, "b", {"folder": "file:///nonexistent/gone%20folder"})
    c = _ws(ws, "c", {"folder": "vscode-remote://ssh-remote%2Bhost/home/x"}, age_days=400)
    d = _ws(ws, "d", {"folder": f"file://{exists}"}, age_days=200)
    e = str(ws / "e")
    os.makedirs(e)  # no workspace.json -> unknown
    got = dict(selectors.sel_stale_workspace([a, b, c, d, e], {"days": 90}, SelectorEnv()))
    assert set(got) == {b, d}
    assert got[b].startswith("/nonexistent/gone folder")
    assert "no longer exists" in got[b]
    assert "unused for" in got[d]
    assert selectors.workspace_target(c)[0] == "unknown"


def test_stale_workspace_config_days(tmp_path):
    ws = tmp_path / "ws"
    exists = tmp_path / "p"
    exists.mkdir()
    a = _ws(ws, "a", {"folder": f"file://{exists}"}, age_days=40)
    env = SelectorEnv({"workspace_stale_days": 30})
    assert selectors.sel_stale_workspace([a], {"days": "$workspace_stale_days"}, env)
    env = SelectorEnv({"workspace_stale_days": 60})
    assert not selectors.sel_stale_workspace([a], {"days": "$workspace_stale_days"}, env)


def test_parse_extension_dir():
    assert selectors.parse_extension_dir("ms-python.python-2024.2.1") == ("ms-python.python", (2024, 2, 1))
    assert selectors.parse_extension_dir("ms-python.python-2024.2.1-linux-x64") == ("ms-python.python", (2024, 2, 1))
    assert selectors.parse_extension_dir("GitHub.copilot-chat-0.12.0") == ("github.copilot-chat", (0, 12, 0))
    assert selectors.parse_extension_dir("extensions.json") is None


def test_superseded_extensions(tmp_path):
    ext = tmp_path / "extensions"
    for name in ("ms-python.python-2024.1.0", "ms-python.python-2024.2.1",
                 "esbenp.prettier-vscode-9.0.0", "esbenp.prettier-vscode-10.1.0",
                 "foo.bar-1.0.0", "foo.bar-2.0.0", "solo.ext-1.0.0", "old.thing-1.0.0"):
        (ext / name).mkdir(parents=True)
    # prettier 9.0.0 is still referenced (e.g. pinned in another profile) -> kept
    write(ext / "extensions.json", json.dumps([
        {"identifier": {"id": "ms-python.python"}, "relativeLocation": "ms-python.python-2024.2.1"},
        {"identifier": {"id": "esbenp.prettier-vscode"}, "relativeLocation": "esbenp.prettier-vscode-9.0.0"},
        {"identifier": {"id": "foo.bar"}, "location": {"path": str(ext / "foo.bar-2.0.0")}},
    ]))
    write(ext / ".obsolete", json.dumps({"old.thing-1.0.0": True}))
    cands = [str(p) for p in ext.iterdir()]
    got = {os.path.basename(p) for p, _ in selectors.sel_superseded_extensions(cands, {}, SelectorEnv())}
    assert got == {"ms-python.python-2024.1.0", "foo.bar-1.0.0", "old.thing-1.0.0"}


def test_versions_selector(tmp_path):
    base = tmp_path / "JetBrains"
    for n in ("PyCharm2023.2", "PyCharm2024.1", "IntelliJIdea2023.3", "Toolbox"):
        (base / n).mkdir(parents=True)
    cands = [str(p) for p in base.iterdir()]
    old = {os.path.basename(p) for p, _ in selectors.sel_versions(cands, {"keep": "old"}, SelectorEnv())}
    cur = {os.path.basename(p) for p, _ in selectors.sel_versions(cands, {"keep": "current"}, SelectorEnv())}
    assert old == {"PyCharm2023.2"}
    assert cur == {"PyCharm2024.1", "IntelliJIdea2023.3"}


def test_elf_core(tmp_path):
    core = tmp_path / "core.1"
    # ELF64 little-endian header with e_type = ET_CORE (4)
    core.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x04\x00" + b"\x00" * 46)
    exe = tmp_path / "core.2"
    exe.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x02\x00" + b"\x00" * 46)
    txt = tmp_path / "core"
    txt.write_text("my notes about the core of the problem")
    got = [p for p, _ in selectors.sel_elf_core([str(core), str(exe), str(txt)], {}, SelectorEnv())]
    assert got == [str(core)]


def test_snap_old_revisions(tmp_path):
    base = tmp_path / "snap" / "code"
    for n in ("150", "151", "common"):
        (base / n).mkdir(parents=True)
    os.symlink("151", base / "current")
    cands = [str(p) for p in base.iterdir()]
    got = [os.path.basename(p) for p, _ in selectors.sel_snap_old_revisions(cands, {}, SelectorEnv())]
    assert got == ["150"]


def test_owned_by_uid(tmp_path):
    p = tmp_path / "f"
    p.write_text("x")
    assert selectors.sel_owned_by_uid([str(p)], {}, SelectorEnv(uid=os.getuid()))
    assert not selectors.sel_owned_by_uid([str(p)], {}, SelectorEnv(uid=os.getuid() + 1))


def test_hf_labels(tmp_path):
    (tmp_path / "models--org--name").mkdir()
    (tmp_path / "version.txt").write_text("1")
    got = selectors.sel_hf_models([str(tmp_path / "models--org--name"), str(tmp_path / "version.txt")],
                                  {}, SelectorEnv())
    assert got == [(str(tmp_path / "models--org--name"), "model: org/name")]

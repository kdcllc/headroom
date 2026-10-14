"""Shared fixtures: an isolated fake $HOME for every test."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home" / "user"
    h.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USER", "user")
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "HF_HOME", "HF_HUB_CACHE", "GOPATH", "GOCACHE", "GOMODCACHE"):
        monkeypatch.delenv(var, raising=False)
    return h


@pytest.fixture
def policy(home):
    from headroom.core.paths import SafetyPolicy
    return SafetyPolicy()


def fixture_text(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def write(path, data=b"x" * 10, mtime=None):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode())
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def snapshot(root):
    """{relpath: (type, size, link target)} for every entry below root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            link = os.readlink(p) if os.path.islink(p) else None
            out[os.path.relpath(p, root)] = (st.st_mode, st.st_size, link, st.st_mtime)
    return out

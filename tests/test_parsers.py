from headroom.core import parsers

from .conftest import fixture_text


def test_snap_list_disabled():
    out = fixture_text("snap_list_all.txt")
    rows = parsers.parse_snap_list(out)
    assert rows and rows[0]["name"] == "bare"
    dis = parsers.disabled_snaps(out)
    assert ("brave", "692") in dis
    assert ("code-insiders", "2592") in dis  # notes "disabled,classic"
    assert all(rev.isdigit() for _, rev in dis)
    active = {(r["name"], r["rev"]) for r in rows if "disabled" not in r["notes"]}
    assert not active & set(dis)


def test_snap_list_synthetic():
    out = ("Name      Version    Rev    Tracking       Publisher   Notes\n"
           "core20    20240111   2182   latest/stable  canonical✓  base,disabled\n"
           "core20    20240416   2264   latest/stable  canonical✓  base\n"
           "firefox   125.0      4173   latest/stable  mozilla✓    disabled\n")
    assert parsers.disabled_snaps(out) == [("core20", "2182"), ("firefox", "4173")]


def test_apt_simulation():
    assert parsers.parse_apt_simulation(fixture_text("apt_autoremove.txt")) == []
    pkgs = parsers.parse_apt_simulation(fixture_text("apt_autoremove_kernels.txt"))
    assert "linux-image-5.15.0-88-generic" in pkgs and "libfoo1:amd64" in pkgs
    assert len(pkgs) == 6
    assert not set(pkgs) & parsers.running_kernel_packages("5.15.0-91-generic")
    assert set(pkgs) & parsers.running_kernel_packages("5.15.0-88-generic")


def test_installed_sizes():
    assert parsers.parse_installed_sizes("100\n250\n\n") == 350 * 1024


def test_journal_usage():
    assert parsers.parse_journal_usage(fixture_text("journalctl_disk_usage.txt")) == int(4.0 * 1024**3)
    assert parsers.parse_journal_usage("Archived and active journals take up 512.0M in the file system.") == 512 * 1024**2
    assert parsers.parse_journal_usage("No journal files were found.") == 0


def test_docker_df():
    df = parsers.parse_docker_df(fixture_text("docker_system_df.jsonl"))
    assert set(df) == {"Images", "Containers", "Local Volumes", "Build Cache"}
    assert df["Images"]["reclaimable"] == int(14.68e9)
    assert df["Containers"]["reclaimable"] == 0
    assert df["Build Cache"]["count"] == 348
    assert parsers.parse_docker_size("512kB") == 512000
    assert parsers.parse_docker_size("garbage") == 0


def test_flatpak_lists():
    rts = parsers.parse_flatpak_runtimes(fixture_text("flatpak_runtimes.txt"))
    assert ("org.gnome.Platform", "42", 1_000_000_000) in rts
    size, names = parsers.estimate_unused_flatpak(fixture_text("flatpak_runtimes.txt"),
                                                  fixture_text("flatpak_app_runtimes.txt"))
    assert names == ["org.kde.Platform//5.15-22.08"]
    assert size == 1_200_000_000
    assert parsers.parse_glib_size("12 bytes") == 12

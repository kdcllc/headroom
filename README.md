# Headroom

A native GTK4 / libadwaita disk-space cleaner for **Ubuntu 22.04 LTS (Jammy)**. It scans editor, Electron and browser caches, developer package caches, logs, old snap revisions, Docker leftovers, the Trash and large files. It shows the real on-disk size of each item, previews exactly what would be removed, and cleans only what you select. Root-only actions go through one polkit prompt and a small helper that accepts only a fixed list of action IDs.

> **Dry run is on by default.** The whole flow (scan → select → preview → confirm → progress → result) runs without changing anything until you switch off **Dry run** in the header bar.

## Defaults chosen for this build

| Decision | Value |
|---|---|
| Application ID (D-Bus, `.desktop`, icon, polkit prefix) | `io.github.kdcllc.Headroom` |
| Polkit action | `io.github.kdcllc.Headroom.run-helper` (`auth_admin_keep` for active sessions, `no` otherwise) |
| Maintainer | kdcllc &lt;info@kingdavidconsulting.com&gt; |
| License | GPL-3.0-or-later |
| Helper path | `/usr/libexec/headroom/headroom-helper` (root:root 0755) |
| Config / logs | `~/.config/headroom/config.json`, `$XDG_STATE_HOME/headroom/clean-*.jsonl` (last 30 kept) |
| Default limits | large files ≥ 500 MB · stale workspaces 90 days · journal 200 MB / 14 days · keep 2 snap revisions · `/tmp` 10 days · `/var/tmp` 30 days |
| User files (Downloads, large files, project junk) | moved to Trash; permanent delete is a separate, confirmed action |

## Install

### Dependencies (apt only, no PPAs, no pip)

```sh
sudo apt update && sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    gir1.2-adw-1 libadwaita-1-0 gir1.2-glib-2.0 policykit-1 desktop-file-utils
```

(`scripts/install-deps.sh` does the same; `scripts/install-deps.sh --dev` adds `python3-pytest xvfb gettext dpkg-dev debhelper dh-python lintian appstream imagemagick`.)

Check the toolkit:

```sh
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print(Gtk.get_major_version(), Gtk.get_minor_version(), Adw.get_major_version(), Adw.get_minor_version())"
# expected: 4 6 1 1
```

### From a GitHub Release (recommended: enables system cleaning)

Every pull request merged into `master` publishes a release with the `.deb` attached (see [Releases](#releases)):

```sh
wget https://github.com/kdcllc/headroom/releases/latest/download/headroom_latest_all.deb
sudo apt install ./headroom_latest_all.deb
```

### From the .deb built locally

```sh
scripts/build-deb.sh dist              # dpkg-deb build, needs only dpkg (verified here)
# or, with debhelper + dh-python installed:
make deb                               # dpkg-buildpackage -us -uc -b  -> ../headroom_0.1.0_all.deb
sudo apt install ./dist/headroom_0.1.0_all.deb
```

Then start **Headroom** from the app grid, or run `headroom`.

### Per-user install (no root, no system cleaning)

```sh
make install-user        # ~/.local/lib/headroom, ~/.local/bin/headroom, .desktop + icon
make uninstall-user
```

### Run from the checkout

```sh
scripts/run-dev.sh       # = /usr/bin/python3 -m headroom
sudo make install-helper # optional: root-owned helper + polkit policy for testing system items
```

If the helper is not installed, system items show the message *“Install the .deb (or run `sudo make install-helper`) to enable system cleaning”*. The app never runs `pkexec` on a script you can write to.

## Stack (verified on this Ubuntu 22.04.5 machine)

| Component | Version found |
|---|---|
| Python (system) | 3.10.12 |
| python3-gi | 3.42.1 |
| GTK (gir1.2-gtk-4.0) | 4.6.9 |
| libadwaita (gir1.2-adw-1) | 1.1.7 |

The app uses only the standard library plus GI; running processes are found by reading `/proc`. At startup it shows an error dialog if GTK < 4.6 or libadwaita < 1.1. Every widget was checked against the installed 4.6/1.1 typelibs. Two facts from that check shaped the code:
- In libadwaita 1.1, row titles and subtitles are always parsed as Pango markup (there is no `use-markup` property yet), so all row text is escaped.
- `Adw.Toast` has no `button-clicked` signal in 1.1, so Undo uses an action (`win.undo-trash`).

## Using it

1. **Scan** (F5). Scanning runs on worker threads, and rows appear per app as each app finishes.
2. Browse the sidebar categories. Each app row has a three-state checkbox; each option row shows its size, rating badge, a lock icon if it needs root, and an ⓘ popover with the exact paths or commands and the reason for the rating.
3. After a scan, only **Safe** items whose app is not running are pre-selected. **Caution** items are never pre-selected. **Advanced** items are hidden unless *Preferences → Show advanced items* is on.
4. **Preview…** lists every path, its size, type and date, plus the exact argv of any command. You can search it, untick rows (remembered for next time) and export it with *Export list…*.
5. **Clean…** opens a confirmation that scales with risk:
   - **Caution** items add a required checkbox.
   - **Advanced** items also require typing `DELETE`.
   - Some options (Backups, Docker volumes) add their own checkbox.
   - Cancel is the default button.
6. If an affected app is running, you choose *Retry* or *Skip these items*. The app never kills processes.
7. The progress page has a Cancel button that stops after the current item. The result page shows both the sum of item sizes and the change in free space, plus ✓/⚠/✗ per item and **View log**. Trashed files get an **Undo** toast.
8. **Scan system items (requires password)** on the Overview measures root-only locations. The app never asks for a password at startup.

## Ratings

- **Safe**: a regenerable cache; the owning app rebuilds it.
- **Caution**: visible side effects, such as re-downloads, lost UI state or extension data, or Docker images.
- **Advanced**: possible data loss or system impact, such as all workspace storage, unsaved-editor Backups, Docker volumes, APT lists, or truncating live logs.

The full list of every cleaner, path, method and rating is generated from the registry: **[docs/CLEANERS.md](docs/CLEANERS.md)** (`make docs` regenerates it).

## Safety model

- **Allow-list roots.** Deletion is possible only below known cache roots: `~/.cache`, `~/.var/app`, `~/snap`, known `~/.config/<App>` folders, the developer-cache roots, Downloads and the Trash. User-selected project roots are added for finder results only. `is_within()` resolves the root with `realpath` and uses `commonpath`; a candidate whose parent resolves outside its root is refused.
- **Deny-list wins** over everything: `$HOME`, `~/.ssh`, `~/.gnupg`, keyrings, Firefox profiles, editor `settings.json` / `keybindings.json` / `snippets` / `profiles` / `globalStorage` (only `state.vscdb.backup` is offered), `~/.vscode-shared`, `~/Documents`, `~/Pictures`, `~/Desktop`, `/etc`, `/usr`, `/boot`, `/var/lib/dpkg`, `/var/lib/docker`, `/var/cache/debconf`, and every mount point.
- **No symlink following.** Scanning uses `scandir(follow_symlinks=False)` and a custom glob that never follows symlinks for wildcard parts. Removal works relative to a parent directory fd opened with `O_NOFOLLOW`; its real location is checked through `/proc/self/fd`. Symlinks are unlinked, never followed. Removal never crosses filesystems (`st_dev`).
- **Re-validation at delete time.** Each entry is re-`lstat`ed and re-checked against the allow/deny lists. An entry is skipped if its type changed since the scan (for example, a directory swapped for a symlink) or if a directory's inode changed.
- **Real sizes**: `st_blocks × 512`, with hard links counted once; the apparent size is shown in a tooltip. Removing one of several hard links counts as 0 bytes freed.
- **One error never aborts a run.** Each failure is counted, logged and shown per item.
- **No shell anywhere.** Every subprocess call uses argv lists, `shell=False`, a timeout and `LANG=C`.
- **Root helper** (stdlib only). It accepts `{"actions":[{"id":…, <bounded ints/bools>}]}` and nothing else: no paths and no strings beyond the IDs. It uses a fixed `PATH`, fd-based removal for `/tmp` and `/var/tmp` (files open by any process and files modified in the last 24 h are skipped), and emits one JSON line per action. All selected root actions run in **one** pkexec call.
- **Logs**: one JSONL record per path or command (timestamp, option, path/argv, bytes, result, error), with helper output merged in.
- **Single instance**: a fixed application ID. Clean is disabled while a scan runs, and vice versa.

## Adding a custom cleaner

Drop a JSON file into `~/.config/headroom/cleaners.d/`. Custom cleaners may target **only paths under `$HOME`** (still subject to the deny-list), must be rated `caution` or `advanced`, and may only `delete` or `trash`: no commands, no root actions, no templates.

```json
{
  "id": "myapp",
  "label": "My App",
  "category": "User Caches",
  "running": {"process_names": ["myapp"]},
  "options": [
    {
      "id": "myapp.cache",
      "label": "Render cache",
      "description": "Thumbnails My App rebuilds on start.",
      "rating": "caution",
      "requires_app_closed": true,
      "targets": [{"mode": "contents", "path": "~/myapp/render-cache", "min_age_days": 7}]
    }
  ]
}
```

The schema:
- **Target `mode`**: `contents` (children of a directory), `glob` (`**` only under a cache root), `dir`, `file`, or `truncate`.
- **Optional filters**: `exclude` (globs), `min_age_days`, `keep_newest_n`, and named `selector`s: `stale_workspace`, `superseded_extensions`, `versions`, `elf_core`, `owned_by_uid`, `snap_old_revisions`, `hf_models`.
- **Option fields**: `split: true` gives one row per entry; `overlap` groups options that measure the same bytes, so totals count them once.

Invalid files are skipped and reported in the terminal.

## Architecture

```
headroom/
  __main__.py, app.py, i18n.py
  core/   (toolkit-free; all unit-tested with plain pytest)
    paths.py      allow/deny lists, is_within, SafetyPolicy
    registry.py   JSON loading, templates, validation, Electron auto-discovery
    scanner.py    du-style sizing, symlink-safe glob, option -> rows (thread pool)
    selectors.py  stale workspaces, superseded extensions, versions, ELF core, …
    deleter.py    fd-based delete / trash / truncate, dry-run, cancel, report
    planner.py    selection -> CleanPlan, preview rows, export
    commands.py   allow-listed tool commands + size probes
    privileged.py pkexec bridge (one prompt), helper ownership check
    parsers.py    snap / apt / journalctl / docker / flatpak output parsers
    procs.py      running-app detection from /proc (comm, exe, cmdline, cgroup, SingletonLock)
    largefiles.py large files, project junk, Downloads
    trash.py      freedesktop Trash (Gio when available) + restore
    config.py, log.py, models.py
  ui/     window, category_view, overview, preview_dialog, confirm, progress_view,
          largefiles_view, preferences, util, style.css
helper/headroom-helper     root helper (stdlib only)
data/cleaners/*.json            the registry (+ _templates/)
```

Threading: workers never touch GTK. Results go to the main loop with `GLib.idle_add(…)` returning `GLib.SOURCE_REMOVE`. Progress updates are throttled to about 10 per second, and cancellation uses a `threading.Event`.

## Development

```sh
make venv        # uv venv on /usr/bin/python3 with --system-site-packages (sees apt's gi) + pytest, ruff
make test        # 132 unit tests (no GTK needed)
make test-ui     # GUI smoke tests under xvfb (GDK_BACKEND=x11)
make lint        # ruff + desktop-file-validate + appstreamcli
make docs        # regenerate docs/CLEANERS.md
make pot         # needs gettext: xgettext -> po/headroom.pot
```

CI (`.github/workflows/ci.yml`) runs on `ubuntu-22.04`. It installs the apt dependencies above, runs ruff, the unit tests and the GUI tests under xvfb, builds the `.deb` with `dpkg-buildpackage` and runs lintian.

## Releases

`.github/workflows/release.yml` runs when a pull request is **merged** into `master`; PRs closed without merging are ignored. You can also start it by hand (*Actions → Release → Run workflow*).

1. It reruns the full CI workflow on the merge commit. If any check fails, nothing is published.
2. It stamps the version `<__version__>+r<run number>` (e.g. `0.1.0+r7`) into `headroom/__init__.py` and `debian/changelog` with `scripts/set-version.sh`. Each merge gets a unique version that `apt` sees as an upgrade.
3. It builds the package with `dpkg-buildpackage` and creates the GitHub Release `v0.1.0-r7` on that commit, with these assets:
   - `headroom_<version>_all.deb`
   - `headroom_latest_all.deb`, a stable name for the `releases/latest/download/` link
   - `SHA256SUMS`

   The release notes show the PR title plus GitHub's generated changelog.

For a feature release, bump `__version__` in `headroom/__init__.py` in the PR (e.g. to `0.2.0`); the next merge publishes `0.2.0+rN`.

The workflow needs **Settings → Actions → General → Workflow permissions** to allow the job's `contents: write` token, which is the default for personal repositories.

## Why not Flatpak or Snap

Headroom has to read and delete other apps' data across `$HOME`, call host tools (`snap`, `apt-get`, `journalctl`, `docker`, `flatpak`) and escalate through pkexec. A sandboxed build would need `--filesystem=home`, host-command escapes and a polkit bridge, which defeats the sandbox. It cleans Flatpak and Snap data, but it isn't shipped as either.

## Deviations from the spec (all on the safe side)

1. **Own fd-based remover instead of `shutil.rmtree`.** Python 3.10's `rmtree` has no `dir_fd`, so it can't operate relative to a verified parent fd. The app still asserts `shutil.rmtree.avoids_symlink_attacks` at startup, as required.
2. **Tool commands replace deletion** when the tool is installed (for example `pip cache purge`); otherwise the listed paths are deleted. The Go module cache, `gem cleanup`, Docker and Flatpak are **command-only**.
3. **Docker** runs as you if you can use the Docker socket (you're in the `docker` group); otherwise it runs through the helper.
4. **Added a "User Caches" sidebar category** for thumbnails, shader/font caches and `~/.cache/*`, which the spec's sidebar list didn't place.
5. **`/tmp/cursor-sandbox-cache`**: its *contents* that you own are removed, rather than the directory itself.
6. **Finders skip deny-listed folders.** Because the deny-list wins over everything, large files inside `~/Documents`, `~/Pictures` and `~/Desktop` are not listed.
7. **Hugging Face** rows delete the `models--*` directory directly; this is the spec's last-resort method, and it's equivalent to `hf cache rm` for one repo.
8. **Estimated sizes** are marked with `~`: unused Flatpak runtimes, the journal after vacuum, and `docker system prune`. `pnpm store prune` shows the whole store size, but only unreferenced packages are removed.
9. **Minimum window size** is 900×600 as specified, so the `Adw.Leaflet` folds only when the content can't fit (for example with large-text scaling).

## What was verified (and what wasn't)

**Verified by running, on this Ubuntu 22.04.5 machine:**
- 132 unit tests and 5 GUI smoke tests (Xvfb, X11) pass. ruff is clean, `desktop-file-validate` reports only a hint about the spec's `Categories` line, and `appstreamcli validate` passes.
- A read-only scan of a real developer home took about 30 s and found, for example, 22 GB of uv cache, 20 GB of pip cache, 16 GB of Docker build cache, a 26 GB old VS Code Insiders snap revision, and a 22.7 GB Cursor `globalStorage` (report-only).
- A full UI flow in a throwaway `$HOME`:
  - Dry run changed nothing.
  - The real clean removed exactly the selected items; `settings.json` and `state.vscdb` were untouched, and `.xsession-errors` was truncated, not deleted.
  - The confirmation stayed disabled until the checkboxes were ticked and `DELETE` was typed.
  - All worker callbacks ran on the main thread.
- `scripts/build-deb.sh` builds the `.deb`. Its contents and permissions were inspected; the packaged registry loads 66 cleaners / 173 options, and the packaged helper refuses to run without root.

**Not verified here** (see TESTING.md for the manual matrix):
- **Real `pkexec` runs of the helper.** The helper wasn't installed system-wide here; all its actions are unit-tested with a mocked `subprocess.run` and temporary directories.
- **`dpkg-buildpackage` / lintian.** debhelper and dh-python aren't installed on this machine; CI runs both.
- **`sudo apt install ./headroom_*.deb`** on a clean VM.
- **A Wayland session.** Only X11 was tested, via Xvfb.
- **Translations.** No `.po` files yet, and `xgettext` wasn't available to produce the `.pot`.
- **Paths for apps not installed here.** These are Slack, Discord, Teams, Obsidian, Postman, Element, Mattermost, Notion, Spotify, Edge, Chromium, the VS Code snap and Flatpak variants, VSCodium, JetBrains, Android, Unity, Homebrew, conda, Timeshift and Flatpak itself. They follow the documented layouts in the spec, but nothing here confirmed them on disk.

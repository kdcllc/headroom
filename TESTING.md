# Testing Headroom

## Automated

| Suite | Command | Needs |
|---|---|---|
| Unit (§8.1): safety layer, registry, scanner, deleter, selectors, parsers, helper, procs, planner, config, log, finders | `make test` or `/usr/bin/python3 -m pytest tests --ignore=tests/ui` | pytest only |
| GUI smoke (§8.2): launch, scan a fake HOME, rows/totals, preview, cancel confirmation, main-thread callbacks, Downloads finder | `make test-ui` | `python3-gi`, GTK 4.6, Adw 1.1, `xvfb` |
| Lint | `make lint` | ruff, desktop-file-utils, appstream |
| Package | `make deb && lintian ../headroom_*_all.deb` (or `scripts/build-deb.sh`) | dpkg-dev, debhelper, dh-python, lintian |

The GUI tests replace the docker/journal/snap probes and tool lookups, so they never touch the real system. Every unit test runs against a `tmp_path` fake `$HOME`.

## Manual matrix (fresh Ubuntu 22.04.5 VM)

Prepare the VM:
- Install Firefox (snap, default), Cursor (AppImage in `~/Applications`), VS Code from the `.deb` and as a snap (`sudo snap install code --classic`), `docker.io` (add yourself to the `docker` group, then build an image twice to create build cache), `flatpak` with one Flathub app, and a second revision of any snap (`sudo snap refresh <name> --channel=…`) so a **disabled** revision exists.
- Install the app with `sudo apt install ./headroom_0.1.0_all.deb` and start it from the app grid.

Before you start, check the logs folder: `ls ~/.local/state/headroom/`.

| # | Scenario | Steps | Expected |
|---|---|---|---|
| 1 | Install & launch | Open from the app grid | Window opens; About shows GTK 4.6.x / libadwaita 1.1.x; DRY RUN pill visible on first run |
| 2 | Scan responsiveness | Scan, then scroll and resize while it runs | UI never freezes; rows appear per app; spinner stops; toast “Scan complete” |
| 3 | Pre-selection | After the scan | Only Safe rows are ticked; Caution rows are not; Advanced rows are hidden until Preferences → Show advanced items |
| 4 | Running-app guard | Keep Firefox open, select the Firefox cache, press Preview… | Dialog “Firefox is running”. *Retry* after closing Firefox continues; *Skip these items* removes the Firefox rows from the plan; the process is never killed |
| 5 | Preview = clean | Preview… → Export list… → save; then clean for real; compare the export with the `clean-*.jsonl` (`path` of records with `result: ok`) | The same paths |
| 6 | Dry run | Leave Dry run on and run Clean | Result says “Would free …”; `find ~ -newer <export file>` shows no deletions; log records are `dry-run`; no password prompt |
| 7 | Real clean | Turn Dry run off; clean Safe items | “Freed X”, both the item sum and the statvfs delta shown; caches rebuilt after relaunching the apps |
| 8 | Caution confirmation | Select “Stale workspace storage” | Delete stays disabled until “I understand…” is ticked |
| 9 | Advanced confirmation | Enable advanced; select “Hot-exit backups” | Needs the checkbox **and** the Backups checkbox **and** typing `DELETE` |
| 10 | Cancel mid-run | Select several large items; Clean; press Cancel | Stops after the current item; result says “Cancelled”; the remaining items are untouched |
| 11 | One password prompt | Select apt.clean, journal vacuum, disabled snaps; Clean | Exactly **one** polkit dialog; per-action ✓/✗; helper lines merged into the log |
| 12 | Polkit cancel | Same as 11, cancel the password dialog | Root items show “authentication was cancelled”; user items already done; no crash |
| 13 | Helper refuses | `echo '{"actions":[{"id":"rm"}]}' \| pkexec /usr/libexec/headroom/headroom-helper --plan-stdin` | JSON error, exit 2, nothing run |
| 14 | Disabled snap | Clean “Disabled snap revisions” | `snap list --all` no longer shows `disabled` rows; freed ≈ `.snap` sizes |
| 15 | Kernel safety | `apt-get -s autoremove` listing an old kernel | Preview lists it; the running kernel (`uname -r`) is never removed (the helper refuses if it would be) |
| 16 | Docker | User in the `docker` group | Build-cache prune runs as the user (no password); volumes need the Advanced confirmation |
| 17 | Trash & undo | Downloads → tick an `.iso` → Move to Trash → Undo toast | The file appears in Files → Trash, then is restored to its original path |
| 18 | Trash fallback | Large file on a FAT USB stick without a trash folder | Asks “could not be moved to the Trash … Delete permanently instead?” |
| 19 | Symlink trap | `ln -s ~/Documents ~/.cache/trap`; scan; clean “Other application caches → trap” | Only the link is removed; `~/Documents` is intact |
| 20 | Protected files | Clean every Cursor/VS Code option (advanced on) | `User/settings.json`, `keybindings.json`, `snippets/`, `globalStorage/state.vscdb` still exist |
| 21 | Locale | `LANG=de_DE.UTF-8 headroom` | Starts; sizes formatted by GLib; tool parsing unaffected (commands run with `LANG=C`) |
| 22 | Wayland | Log in to “Ubuntu” (Wayland) session | All of 1–20 work; FileChooserNative opens the portal dialog |
| 23 | Xorg | Log in to “Ubuntu on Xorg” | All of 1–20 work |
| 24 | Single instance | Launch twice | The second launch focuses the first window |
| 25 | Logs | Run 31 cleans | Only 30 `clean-*.jsonl` files remain |
| 26 | Custom cleaner | Add the README example to `~/.config/headroom/cleaners.d/`; rescan | “My App” appears under User Caches as Caution; a file with `"rating": "safe"` or a path outside `$HOME` is rejected (message in the terminal) |

## Not covered automatically

The real pkexec round trip, apt/snap/journal actions on a live system, Wayland, translations, and the paths of apps not present on the build machine (listed in the README) are covered only by this manual matrix.

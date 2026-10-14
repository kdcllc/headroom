"""Entry point: ``python3 -m headroom``."""

import sys


def main() -> int:
    from .core.deleter import assert_rmtree_safe
    assert_rmtree_safe()
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
    except (ImportError, ValueError) as exc:
        print("Headroom needs GTK 4 and libadwaita from apt:\n"
              "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
              f"({exc})", file=sys.stderr)
        return 1
    from .app import HeadroomApplication
    return HeadroomApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

#!/bin/sh
# Run from a checkout with the system Python (PyGObject comes from apt, not pip).
# Root actions stay disabled unless the helper is installed (sudo make install-helper).
set -eu
cd "$(dirname "$0")/.."
exec /usr/bin/python3 -m headroom "$@"

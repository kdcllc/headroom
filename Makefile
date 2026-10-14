# Headroom — developer tasks. Runtime uses the system Python and apt's PyGObject.
PY        ?= /usr/bin/python3
VENV      ?= .venv
APP_ID    := io.github.kdcllc.Headroom
PREFIX    ?= $(HOME)/.local
LIBEXEC   := /usr/libexec/headroom
POLKIT    := /usr/share/polkit-1/actions

.PHONY: run test test-ui lint venv deb deb-simple install-user uninstall-user install-helper \
        uninstall-helper docs pot clean

run:
	$(PY) -m headroom

# Dev env with uv: system Python 3.10 + apt's gi visible, pytest/ruff from PyPI.
venv:
	uv venv --python $(PY) --system-site-packages $(VENV)
	uv pip install --python $(VENV)/bin/python pytest ruff

test:
	$(VENV)/bin/python -m pytest tests --ignore=tests/ui -q

test-ui:
	xvfb-run -a -s "-screen 0 1280x900x24" env GDK_BACKEND=x11 $(VENV)/bin/python -m pytest tests/ui -q

lint:
	$(VENV)/bin/ruff check headroom tests scripts helper/headroom-helper
	desktop-file-validate data/$(APP_ID).desktop
	appstreamcli validate --no-net data/$(APP_ID).metainfo.xml

docs:
	$(PY) scripts/gen_cleaner_docs.py

# Canonical package build (needs: dpkg-dev debhelper dh-python)
deb:
	dpkg-buildpackage -us -uc -b
	@echo "lint with: lintian ../headroom_*_all.deb"

# Fallback build with dpkg-deb only (same layout as debian/install)
deb-simple:
	scripts/build-deb.sh dist

pot:
	mkdir -p po
	xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 --from-code=UTF-8 \
	    --package-name=headroom -o po/headroom.pot $$(find headroom -name '*.py' | sort)

install-user:
	install -d $(PREFIX)/lib/headroom $(PREFIX)/bin $(HOME)/.local/share/applications \
	    $(HOME)/.local/share/icons/hicolor/scalable/apps
	rm -rf $(PREFIX)/lib/headroom/headroom $(PREFIX)/lib/headroom/data
	cp -r headroom $(PREFIX)/lib/headroom/
	install -d $(PREFIX)/lib/headroom/data
	cp -r data/cleaners $(PREFIX)/lib/headroom/data/
	printf '#!/bin/sh\nPYTHONPATH="%s/lib/headroom$${PYTHONPATH:+:$$PYTHONPATH}" exec /usr/bin/python3 -m headroom "$$@"\n' "$(PREFIX)" > $(PREFIX)/bin/headroom
	chmod 0755 $(PREFIX)/bin/headroom
	sed 's|^Exec=.*|Exec=$(PREFIX)/bin/headroom|' data/$(APP_ID).desktop > $(HOME)/.local/share/applications/$(APP_ID).desktop
	install -m 0644 data/$(APP_ID).svg $(HOME)/.local/share/icons/hicolor/scalable/apps/
	-update-desktop-database $(HOME)/.local/share/applications 2>/dev/null
	@echo "Installed for $(USER). System cleaning needs: sudo make install-helper"

uninstall-user:
	rm -rf $(PREFIX)/lib/headroom
	rm -f $(PREFIX)/bin/headroom $(HOME)/.local/share/applications/$(APP_ID).desktop \
	    $(HOME)/.local/share/icons/hicolor/scalable/apps/$(APP_ID).svg

# Dev testing of root actions: root-owned copy, never a user-writable script
install-helper:
	@test "$$(id -u)" = 0 || { echo "run: sudo make install-helper"; exit 1; }
	install -d -o root -g root -m 0755 $(LIBEXEC)
	install -o root -g root -m 0755 helper/headroom-helper $(LIBEXEC)/headroom-helper
	install -o root -g root -m 0644 data/$(APP_ID).policy $(POLKIT)/$(APP_ID).policy

uninstall-helper:
	@test "$$(id -u)" = 0 || { echo "run: sudo make uninstall-helper"; exit 1; }
	rm -f $(LIBEXEC)/headroom-helper $(POLKIT)/$(APP_ID).policy
	-rmdir $(LIBEXEC)

clean:
	rm -rf dist build .pytest_cache .ruff_cache
	find . -name '__pycache__' -prune -exec rm -rf {} +

"""gettext setup. All user-visible strings go through ``_``."""

import gettext
import os

DOMAIN = "headroom"
_here = os.path.dirname(os.path.abspath(__file__))
_localedirs = [os.path.join(os.path.dirname(_here), "build", "locale"), "/usr/share/locale"]
_localedir = next((d for d in _localedirs if os.path.isdir(d)), None)

translation = gettext.translation(DOMAIN, localedir=_localedir, fallback=True)
_ = translation.gettext
ngettext = translation.ngettext

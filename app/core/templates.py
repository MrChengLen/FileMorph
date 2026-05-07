# SPDX-License-Identifier: AGPL-3.0-or-later
"""Singleton Jinja2 templates instance shared across the app.

Lives in its own module so route packages can import the templates
without pulling ``app/main.py`` and creating an import cycle. Globals
(``api_base_url``, ``app_base_url``, ``site_jsonld``, etc.) are still
attached in ``app/main.py`` because they depend on runtime settings.
"""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.compat import base_dir

templates = Jinja2Templates(directory=str(base_dir() / "app" / "templates"))

# Identity-passthrough fallback so templates can call ``_('...')`` even
# before per-request locale binding (e.g. error pages rendered before
# middleware fires). The real translator lands in the per-request context
# via :func:`app.core.i18n.localized_context`, which overrides this.
templates.env.globals.setdefault("_", lambda s: s)
templates.env.globals.setdefault("gettext", lambda s: s)
templates.env.globals.setdefault("ngettext", lambda s, p, n: s if n == 1 else p)

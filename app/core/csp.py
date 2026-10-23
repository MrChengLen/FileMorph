# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content-Security-Policy profiles, chosen per route.

The site no longer sends one CSP for every response. ``app/main.py`` builds one
policy per profile at startup (``_build_csp_header``), and its security-headers
middleware answers each request with the profile the route chose:

- ``default`` — every page today: scripts from this origin, uploads to this
  server (and to ``API_BASE_URL`` when set).
- ``hybrid`` — ``default`` plus ``blob:`` images, for previews of files the
  browser processed itself. Uploads stay possible; the page decides when.
- ``local`` — strict pages and the engine files: the browser refuses fetch,
  XHR, WebSocket, EventSource and beacons (``connect-src 'none'``), form posts
  (``form-action 'none'``), plugins and frames. It does not stop navigation,
  pop-up windows (they load under their own profile) or WebRTC, nor requests
  for images, scripts and styles from this origin (the page needs them): it
  keeps the app's own code from uploading, it does not contain a hostile
  script.

A route that wants another profile than ``default`` calls
:func:`use_csp_profile`. Everything under ``/static/engine/`` gets ``local``
(``app/core/engine.py``).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

CSP_PROFILES = ("default", "hybrid", "local")


def use_csp_profile(scope: MutableMapping[str, Any], profile: str) -> None:
    """Answer the current request with CSP ``profile``.

    Pass ``request.scope``. The choice is kept in the request state
    (``request.state.csp_profile``), where the middleware reads it.
    """
    if profile not in CSP_PROFILES:
        raise ValueError(f"unknown CSP profile {profile!r}, expected one of {CSP_PROFILES}")
    scope.setdefault("state", {})["csp_profile"] = profile

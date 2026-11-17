### Added — browser tests: a page under the `local` CSP profile opens no data connection and posts no form, in Chromium and WebKit

A new workflow, `Browser tests` (`.github/workflows/browser.yml`), checks in real
browsers what the test suite could only check as headers. A page under the
`local` CSP profile — the profile the coming in-browser tools will use — tries
the data channels the profile refuses: fetch, XMLHttpRequest, `sendBeacon`,
WebSocket, EventSource and a form post. None of the requests reaches the
server, and the browser reports a CSP violation for each; the same probes on a
`default` page do reach it, so the test cannot pass on a broken probe.
Navigation, pop-up windows, workers started from outside the engine, WebRTC
and requests for images and scripts from the site's own origin are outside
what `local` blocks (`app/core/csp.py`). A module from the engine mount still
loads on the strict page. Each test runs in Chromium and in WebKit, the engine
of Safari on the iPhone (`tests/browser/`).

- The browsers come from the Playwright image of one release, pinned by
  digest; nothing in the job downloads a browser. Playwright and pytest come
  from a new hashed lockfile, `requirements-browser.lock`, which is audited
  against PyPI and OSV like the other lockfiles, kept in step by
  `lockfile-drift` and recompiled by the `deps-lock` workflow.
- It is a workflow of its own, not a job in `CI`, so that a test that flakes
  cannot hold back a deploy, and not a required check yet.
- `pytest tests/` leaves `tests/browser/` out; `docs/development.md` says how
  to run it locally.
- Engine code gets a lint of its own (`tests/test_engine_code.py`): no file
  under `app/static/engine/` may name fetch, XMLHttpRequest, WebSocket,
  EventSource, beacons, WebRTC, a new window, a form submission, a navigation
  or an image request. It catches the usual spellings, not code written to hide a call.

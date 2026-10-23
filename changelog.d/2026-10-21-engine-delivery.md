### Added — Groundwork for processing files in the browser, switched off

FileMorph is preparing an engine that processes files in the browser instead
of uploading them. This change lays the groundwork and changes nothing
visible: the new setting `LOCAL_TOOLS_ENABLED` is off by default, and no page
loads the engine yet.

- With `LOCAL_TOOLS_ENABLED=true`, the app serves the engine from
  `app/static/engine/` under `/static/engine/<tree-hash>/…`. The hash is the
  git tree id of that directory, so `git rev-parse <tag>:app/static/engine`
  shows which engine a release serves (docs/self-hosting.md, "Local tools").
  The files are cached as immutable, any other hash returns a plain 404 that
  is never cached, and the files are always sent as `text/javascript`,
  whatever type the operating system maps `.js` to. For now the engine holds
  only a placeholder module.
- The Content-Security-Policy comes in three profiles, chosen per route:
  `default` (unchanged, still used by every page), `hybrid` (adds `blob:`
  images for previews) and `local` (the browser refuses fetch, XHR,
  WebSocket, beacons, form posts, plugins and frames; navigation and pop-up
  windows stay possible). Engine files always get `local`.
- `base.html` loads `auth.js` and `app.js` in a `core_scripts` block, so a
  strict page can leave them out.

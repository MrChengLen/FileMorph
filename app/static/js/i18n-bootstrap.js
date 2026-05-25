// SPDX-License-Identifier: AGPL-3.0-or-later
// Parses the server-rendered i18n catalogue (#fm-i18n-strings, type
// application/json) into window.FM_I18N before any consumer script runs.
// Lives in its own file rather than inline so the strict CSP
// (script-src 'self' …) need not carry a second SHA-256 source-hash — see
// app/main.py::_build_csp_header and CLAUDE.md (no inline executable scripts).
try {
  const el = document.getElementById('fm-i18n-strings');
  window.FM_I18N = el ? JSON.parse(el.textContent) : {};
} catch (e) {
  console.error('FM_I18N parse failed', e);
  window.FM_I18N = {};
}

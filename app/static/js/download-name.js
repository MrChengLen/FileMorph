// SPDX-License-Identifier: AGPL-3.0-or-later
// The name a downloaded result gets, for app.js, pdf-tools.js and redact.js.
//
// FM_downloadName(res, fallback) reads it from the response's
// Content-Disposition. The server sends a name in plain ASCII without "%" as
// filename="Mein Urlaub.png", any other in two forms
// (app/core/utils.py::content_disposition): filename*=UTF-8''Gr%C3%BC%C3%9Fe.png
// (RFC 8187) beside an ASCII stand-in in filename="…". The filename* form
// wins, as in the browsers' own downloads. `fallback` comes only when the
// header names nothing readable — a proxy that drops it.
//
// FM_resultName(sourceName, suffix) builds that fallback as the server names
// a result: the picked file's name without its extension, plus the tool's
// suffix (".png", "_compressed.jpg", "_pages.zip"). The server's clean-up of
// the name is not repeated; the browser cleans up a download's name itself.
(function () {
  // One parameter after the disposition type: a name, "=", and a quoted
  // string (which may hold ";") or a token.
  const PARAM = /;\s*([^\s=;]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)/g;

  function unquote(value) {
    const v = value.trim();
    if (v.length < 2 || v[0] !== '"' || v[v.length - 1] !== '"') return v;
    return v.slice(1, -1).replace(/\\(.)/g, '$1');
  }

  // charset'language'%-encoded bytes. The server writes UTF-8; a name in
  // another charset is left to the filename="…" form.
  function decodeExtended(value) {
    const m = /^utf-8'[^']*'(.*)$/i.exec(value);
    if (!m) return '';
    try {
      return decodeURIComponent(m[1]);
    } catch (_) {
      return ''; // a broken %-sequence
    }
  }

  function nameFromHeader(header) {
    const params = {};
    for (const m of (header || '').matchAll(PARAM)) {
      params[m[1].toLowerCase()] = unquote(m[2]);
    }
    const extended = params['filename*'] ? decodeExtended(params['filename*']) : '';
    return (extended || params.filename || '').trim();
  }

  window.FM_downloadName = function (res, fallback) {
    return nameFromHeader(res.headers.get('Content-Disposition')) || fallback;
  };

  window.FM_resultName = function (sourceName, suffix) {
    const dot = sourceName.lastIndexOf('.');
    return (dot > 0 ? sourceName.slice(0, dot) : sourceName) + suffix;
  };
})();

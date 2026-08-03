// SPDX-License-Identifier: AGPL-3.0-or-later
// PDF tools (/pdf/split, /pdf/extract, /pdf/compress) — one shared script for
// all three tool pages, parametrised by #pdf-tool's data-tool/data-endpoint.
// Single-file upload → one POST → download. CSP-safe: no inline handlers —
// everything wired via addEventListener. Auth mirrors redact.js: plain fetch
// with optional X-API-Key + Bearer headers, so it works anonymously and
// resolves a logged-in user's tier server-side.
(function () {
  'use strict';

  const root = document.getElementById('pdf-tool');
  if (!root) return;

  const body = document.body;
  const UPLOAD_BASE = (body && body.dataset.apiBase) || '';
  const TOOL = root.dataset.tool || '';
  const ENDPOINT = root.dataset.endpoint || '';
  const I18N = window.FM_I18N || {};

  let selectedFile = null;

  const $ = (id) => document.getElementById(id);
  const show = (el) => el && el.classList.remove('hidden');
  const hide = (el) => el && el.classList.add('hidden');

  // Captured once: a converged compress overwrites the green summary, and a
  // later not-converged/no-images run on the same page load must restore this
  // neutral text instead of sitting under a stale "Compressed to X MB" claim.
  const DEFAULT_SUMMARY = ($('pdf-result-summary') && $('pdf-result-summary').textContent) || '';

  // Translate with {token} substitution.
  function t(key, fallback, vars) {
    let s = I18N[key] || fallback;
    if (vars) for (const k in vars) s = s.replace('{' + k + '}', vars[k]);
    return s;
  }

  function authHeaders() {
    const h = {};
    const key = localStorage.getItem('filemorph_api_key');
    if (key) h['X-API-Key'] = key;
    const token = localStorage.getItem('fm_access_token');
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }

  function showError(msg) {
    hide($('pdf-progress'));
    $('pdf-error-text').textContent = msg;
    show($('pdf-error'));
  }

  // Header code first, then HTTP status — mirrors the server's error
  // contract (app/api/routes/pdf_pages.py): 422 = not a PDF (no header);
  // 400 carries X-FileMorph-Error-Code (invalid_page_selection / invalid_pdf);
  // 429 = rate limit / monthly quota. Anything else falls back to the
  // server's own (already caller-safe) detail message.
  function errorFromResponse(res, data) {
    const code = res.headers.get('X-FileMorph-Error-Code');
    if (code === 'invalid_page_selection') {
      return t('pdfInvalidSelection', "Invalid page selection. Use 1-based page numbers and ranges, e.g. '1-3,5'.");
    }
    if (code === 'invalid_pdf') return t('pdfInvalidFile', 'Could not read the PDF. Verify the file is valid.');
    if (code === 'input_too_large') return t('errorInputTooLarge', 'File too large for your plan.');
    if (code === 'output_cap_exceeded') return t('errorOutputCapExceeded', 'Output would exceed your plan cap.');
    if (code === 'target_size_exceeds_cap') return t('errorTargetSizeExceedsCap', 'Target size exceeds your plan cap.');
    const detail = data && data.detail;
    // Pydantic validation 422s carry an array detail — not user-friendly text.
    if (res.status === 422 && !Array.isArray(detail)) return t('pdfNotAPdf', 'Please select a PDF file.');
    if (res.status === 429) return t('pdfRateLimited', 'Too many requests. Please wait a moment and try again.');
    return (typeof detail === 'string' && detail) || t('pdfToolError', 'Something went wrong. Please try again.');
  }

  // ── file selection ────────────────────────────────────────────────────────
  function setFile(file) {
    selectedFile = file;
    $('pdf-filename').textContent = file.name;
    hide($('pdf-idle'));
    show($('pdf-selected'));
    // back to a clean step-1 state if a previous run is on screen
    hide($('pdf-result'));
    hide($('pdf-error'));
    hide($('pdf-pages-warn'));
  }

  function clearFile() {
    selectedFile = null;
    $('pdf-file').value = '';
    show($('pdf-idle'));
    hide($('pdf-selected'));
  }

  function wireDropzone() {
    const dz = $('pdf-drop');
    const input = $('pdf-file');
    dz.addEventListener('click', () => input.click());
    dz.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('border-brand'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('border-brand'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('border-brand');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => { if (input.files[0]) setFile(input.files[0]); });
    $('pdf-clear').addEventListener('click', (e) => { e.stopPropagation(); clearFile(); });
    // Enter on the nested Clear button must not bubble to the dropzone's
    // keydown handler (which would re-open the file picker).
    $('pdf-clear').addEventListener('keydown', (e) => e.stopPropagation());
  }

  // ── extract: soft client-side mirror of the server's page-syntax rules ────
  // The server (parse_page_ranges) remains the source of truth — this only
  // blocks obviously-malformed syntax before an upload round-trip. A
  // syntactically valid but out-of-range selection still comes back as a
  // mapped server error.
  const PAGE_TOKEN_RE = /^(\d+)(?:-(\d+))?$/;

  function validatePages(spec) {
    // Strip ALL whitespace per token, not just the ends — the server accepts
    // "1 - 3" (parse_page_ranges strips inner whitespace too).
    const tokens = spec.split(',').map((s) => s.replace(/\s+/g, '')).filter(Boolean);
    if (tokens.length === 0) return false;
    for (const token of tokens) {
      const m = PAGE_TOKEN_RE.exec(token);
      if (!m) return false;
      const start = parseInt(m[1], 10);
      if (start < 1) return false;
      if (m[2] !== undefined) {
        const end = parseInt(m[2], 10);
        if (end < 1 || start > end) return false;
      }
    }
    return true;
  }

  function pagesWarnMessage() {
    return t('pdfInvalidSelection', "Invalid page selection. Use 1-based page numbers and ranges, e.g. '1-3,5'.");
  }

  function wirePagesInput() {
    const input = $('pdf-pages');
    if (!input) return;
    input.addEventListener('input', () => {
      const val = input.value.trim();
      if (!val || validatePages(val)) hide($('pdf-pages-warn'));
      else {
        $('pdf-pages-warn').textContent = pagesWarnMessage();
        show($('pdf-pages-warn'));
      }
    });
  }

  // ── submit ──────────────────────────────────────────────────────────────
  function filenameFromDisposition(res, fallback) {
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    return (m && m[1]) || fallback;
  }

  // Compress-honesty: read the achieved-size/converged/recompressible-images
  // headers. No images or not-converged → amber #pdf-honest-note with the
  // achieved size (download offered regardless — never a fake "success").
  // Converged → overwrite the green #pdf-result-summary with the achieved
  // size. Headers missing (stripping proxy) → leave the default neutral
  // "your file is ready" summary untouched.
  function showCompressHonesty(res) {
    const note = $('pdf-honest-note');
    hide(note);
    // Restore the neutral summary first — a previous converged run may have
    // overwritten it, and its stale claim must never survive into this run.
    $('pdf-result-summary').textContent = DEFAULT_SUMMARY;
    const achieved = res.headers.get('X-FileMorph-Achieved-Bytes');
    const converged = res.headers.get('X-FileMorph-Converged');
    const images = res.headers.get('X-FileMorph-Recompressible-Images');
    if (achieved === null || converged === null || images === null) return;

    const bytes = parseInt(achieved, 10);
    if (!isFinite(bytes)) return;
    const mb = (bytes / (1024 * 1024)).toFixed(2);
    if (images === '0') {
      note.textContent = t(
        'pdfCompressNoImages',
        'Nothing to recompress — this PDF has no images that can be shrunk. Size: {size} MB.',
        { size: mb }
      );
      show(note);
    } else if (converged !== 'true') {
      note.textContent = t(
        'pdfCompressNotConverged',
        "Couldn't fully reach your target size — best achieved: {size} MB.",
        { size: mb }
      );
      show(note);
    } else if (selectedFile && bytes < selectedFile.size) {
      $('pdf-result-summary').textContent = t('pdfCompressAchieved', 'Compressed to {size} MB', { size: mb });
    }
    // else: already at/under target without shrinking (max-quality shortcut) —
    // keep the neutral "ready" summary rather than claiming a compression.
  }

  async function submit() {
    if (!selectedFile) { showError(t('pdfSelectFile', 'Select a PDF file first.')); return; }

    let pagesValue = '';
    if (TOOL === 'extract') {
      pagesValue = ($('pdf-pages') && $('pdf-pages').value.trim()) || '';
      if (!pagesValue || !validatePages(pagesValue)) {
        $('pdf-pages-warn').textContent = pagesWarnMessage();
        show($('pdf-pages-warn'));
        return;
      }
    }

    let targetKb = null;
    if (TOOL === 'compress') {
      const mb = parseFloat(($('pdf-target-size') && $('pdf-target-size').value) || '0');
      if (!isFinite(mb) || mb <= 0) {
        showError(t('alertNoTargetSize', 'Please enter a target size in MB.'));
        return;
      }
      // Server rejects target_kb > 2 GB via form validation (422 with an
      // array detail) — catch it here with the proper message instead.
      if (mb > 2048) {
        showError(t('errorTargetSizeExceedsCap', 'Target size exceeds the allowed maximum.'));
        return;
      }
      targetKb = Math.max(1, Math.round(mb * 1024));
    }

    hide($('pdf-error'));
    hide($('pdf-result'));
    show($('pdf-progress'));

    const fd = new FormData();
    fd.append('file', selectedFile);
    if (TOOL === 'extract') fd.append('pages', pagesValue);
    if (TOOL === 'compress') fd.append('target_kb', String(targetKb));

    const btn = $('pdf-submit');
    btn.disabled = true;
    try {
      const res = await fetch(UPLOAD_BASE + ENDPOINT, {
        method: 'POST', headers: authHeaders(), body: fd,
      });
      hide($('pdf-progress'));
      if (!res.ok) {
        let data = {};
        try { data = await res.json(); } catch (_) { /* binary/no body */ }
        showError(errorFromResponse(res, data));
        return;
      }

      const blob = await res.blob();
      const fallbackExt = TOOL === 'split' ? 'zip' : 'pdf';
      const name = filenameFromDisposition(res, `result.${fallbackExt}`);
      const link = $('pdf-download');
      if (link.href && link.href.startsWith('blob:')) URL.revokeObjectURL(link.href);
      link.href = URL.createObjectURL(blob);
      link.download = name;

      hide($('pdf-honest-note'));
      if (TOOL === 'compress') showCompressHonesty(res);

      show($('pdf-result'));
    } catch (_) {
      showError(t('pdfToolError', 'Something went wrong. Please try again.'));
    } finally {
      btn.disabled = false;
    }
  }

  function restart() {
    clearFile();
    const link = $('pdf-download');
    if (link && link.href && link.href.startsWith('blob:')) {
      URL.revokeObjectURL(link.href);
      link.removeAttribute('href');
    }
    hide($('pdf-result'));
    hide($('pdf-error'));
    hide($('pdf-pages-warn'));
  }

  wireDropzone();
  wirePagesInput();
  $('pdf-submit').addEventListener('click', submit);
  $('pdf-restart').addEventListener('click', restart);
})();

// SPDX-License-Identifier: AGPL-3.0-or-later
// PDF tools (/pdf/split, /pdf/extract, /pdf/compress, /pdf/insert) — one shared
// script for all four tool pages, parametrised by #pdf-tool's
// data-tool/data-endpoint. Upload (insert: the PDF and the file to insert) →
// one POST → download. CSP-safe: no inline handlers —
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
  let insertFile = null; // /pdf/insert: the file that goes into the PDF
  let lastResult = null; // /pdf/insert: the result, the PDF of "Insert something else"

  const $ = (id) => document.getElementById(id);
  const show = (el) => el && el.classList.remove('hidden');
  const hide = (el) => el && el.classList.add('hidden');

  // Captured once: a converged compress overwrites the green summary, and a
  // later not-converged/no-images run on the same page load must restore this
  // neutral text instead of sitting under a stale "Compressed to X MB" claim.
  const DEFAULT_SUMMARY = ($('pdf-result-summary') && $('pdf-result-summary').textContent) || '';
  // Same capture-once pattern for the download-button label — the no-op
  // compress branch (no recompressible images) relabels it to "Download
  // unchanged file" so it never implies a compression that didn't happen.
  const DEFAULT_DOWNLOAD_LABEL = ($('pdf-download-label') && $('pdf-download-label').textContent) || '';

  // Translate with {token} substitution (every occurrence).
  function t(key, fallback, vars) {
    let s = I18N[key] || fallback;
    if (vars) for (const k in vars) s = s.split('{' + k + '}').join(vars[k]);
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

  // Upsell link (Upsell-Regeln): only next to the three quota-error codes
  // below, only when pricing_enabled — #pdf-error-upsell then doesn't exist
  // in the DOM at all on a self-host build without a pricing surface, hence
  // the null-guard.
  const UPSELL_ERROR_CODES = ['input_too_large', 'output_cap_exceeded', 'target_size_exceeds_cap'];

  function setUpsellVisible(visible) {
    const link = $('pdf-error-upsell');
    if (!link) return;
    link.classList.toggle('hidden', !visible);
  }

  // Next-step link to /pdf/extract, next to pdf_too_many_pages and
  // pdf_too_complex on the split, compress and insert pages.
  // #pdf-error-extract exists only there, hence the null-guard.
  function setExtractLinkVisible(visible) {
    const link = $('pdf-error-extract');
    if (!link) return;
    link.classList.toggle('hidden', !visible);
  }

  // /pdf/insert names the form field an error belongs to
  // (X-FileMorph-Error-Field): the message then starts with its label.
  const FIELD_LABELS = {
    file: () => t('pdfFieldFile', 'Your PDF'),
    insert_file: () => t('pdfFieldInsert', 'File to insert'),
    after_page: () => t('pdfFieldPosition', 'Position'),
  };

  function showError(msg, code, field) {
    window.FM_announce && window.FM_announce('');
    hide($('pdf-progress'));
    // An error replaces a result still on screen from an earlier run.
    hide($('pdf-result'));
    const known = field && Object.prototype.hasOwnProperty.call(FIELD_LABELS, field);
    const label = known ? FIELD_LABELS[field]() + ': ' : '';
    $('pdf-error-text').textContent = label + msg;
    setUpsellVisible(UPSELL_ERROR_CODES.includes(code));
    setExtractLinkVisible(code === 'pdf_too_many_pages' || code === 'pdf_too_complex');
    show($('pdf-error'));
  }

  // Header code first, then HTTP status — mirrors the server's error
  // contract (app/api/routes/pdf_pages.py): 422 = not a PDF (no header);
  // 400 carries X-FileMorph-Error-Code (invalid_page_selection / invalid_pdf /
  // pdf_encrypted / pdf_encryption_unsupported / pdf_too_many_pages /
  // pdf_too_complex; /pdf/insert also invalid_position / word_not_converted /
  // decompression_bomb / invalid_input, and 415 unsupported_format); every
  // route also file_type_not_permitted (400), request_too_large (413) and
  // server_busy (503); 429 = rate limit / monthly quota. Anything else falls
  // back to the server's own (already caller-safe) detail message.
  function errorFromResponse(res, data) {
    const code = res.headers.get('X-FileMorph-Error-Code');
    if (code === 'invalid_page_selection') {
      return t('pdfInvalidSelection', "Invalid page selection. Use 1-based page numbers and ranges, e.g. '1-3,5'.");
    }
    if (code === 'invalid_pdf') return t('pdfInvalidFile', 'Could not read the PDF. Verify the file is valid.');
    if (code === 'pdf_encrypted') {
      return t('pdfEncrypted', 'This PDF is password-protected. Remove the password (e.g. open the file and print it to a new PDF) and try again.');
    }
    if (code === 'pdf_encryption_unsupported') {
      return t('pdfEncryptionUnsupported', 'This PDF is protected with a certificate or an unsupported encryption. Remove the protection (e.g. ask the sender for an unprotected copy) and try again.');
    }
    // One code from several routes, but the next step differs: split points
    // to /pdf/extract (see #pdf-error-extract), extract to a smaller selection.
    if (code === 'pdf_too_many_pages') {
      if (TOOL === 'insert') {
        return t('pdfTooManyPagesInsert', 'Together the files would have more than 10,000 pages — too many for one insertion.');
      }
      if (TOOL === 'split') {
        return t('pdfTooManyPagesSplit', 'This PDF has more than 10,000 pages — too many to split at once. Extract up to 10,000 pages at a time with “Extract PDF pages”, then split each part.');
      }
      return t('pdfTooManyPagesExtract', 'You can extract at most 10,000 pages at once. Select fewer pages, or extract them in several parts.');
    }
    // /pdf/compress past the child process's memory, time or file size
    // limits; the compress page links on to the extract tool (#pdf-error-extract).
    if (code === 'pdf_too_complex') {
      if (TOOL === 'insert') {
        return t('pdfTooComplexInsert', 'These files are too large or complex to combine in one go. Insert into a smaller part of the PDF (“Extract PDF pages”), or shrink the files first with “Compress PDF”.');
      }
      return t('pdfTooComplex', 'This PDF is too large or complex to compress in one go. Extract fewer pages at a time with “Extract PDF pages”, then compress each part.');
    }
    if (code === 'invalid_position') {
      const count = res.headers.get('X-FileMorph-Page-Count') || '?';
      if (count === '1') {
        return t('pdfInvalidPositionOne', 'Your PDF has only 1 page — choose “At the start” or “At the end”.');
      }
      return t('pdfInvalidPosition', 'Your PDF has {count} pages — choose a page from 1 to {count}.', { count });
    }
    if (code === 'unsupported_format') {
      return t('pdfInsertUnsupported', "This file can't be inserted. Insert a PDF, a Word file (.docx) or an image (JPG, PNG, HEIC …); save other documents as .docx or PDF first.");
    }
    if (code === 'word_not_converted') {
      return t('pdfWordNotConverted', "This Word file couldn't be converted here. In Word, save it as a PDF (File → Save as → PDF) and insert the PDF.");
    }
    if (code === 'decompression_bomb') {
      return t('pdfImageTooLarge', 'The image is too large to process safely. Make it smaller and try again.');
    }
    if (code === 'invalid_input' && TOOL === 'insert') {
      return t('pdfInsertUnreadable', "The image couldn't be read. Save it as PNG or JPG and try again.");
    }
    if (code === 'file_type_not_permitted') {
      return t('errorFileTypeNotPermitted', 'File type not permitted. This file starts like a program or script, whatever its name says. Choose a file in one of the supported formats.');
    }
    if (code === 'request_too_large' && data && data.max_size_mb) {
      return t('errorRequestTooLarge', 'File too large: this server takes at most {max} MB per upload. Use a smaller file or self-host FileMorph — there you set the limits.', { max: data.max_size_mb });
    }
    if (code === 'server_busy') {
      return t('errorServerBusy', 'FileMorph is at capacity. The request was not processed; retry in a few seconds.');
    }
    if (code === 'input_too_large') return t('errorInputTooLarge', 'File too large.');
    if (code === 'output_cap_exceeded') return t('errorOutputCapExceeded', 'The result would be larger than allowed.');
    if (code === 'target_size_exceeds_cap') return t('errorTargetSizeExceedsCap', 'The target size is above the output limit.');
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

  // /pdf/insert: the second file.
  function setInsertFile(file) {
    insertFile = file;
    $('pdf-insert-filename').textContent = file.name;
    hide($('pdf-insert-idle'));
    show($('pdf-insert-selected'));
    hide($('pdf-result'));
    hide($('pdf-error'));
  }

  function clearInsertFile() {
    insertFile = null;
    const input = $('pdf-insert-file');
    if (!input) return;
    input.value = '';
    show($('pdf-insert-idle'));
    hide($('pdf-insert-selected'));
  }

  function wireDropzone(dzId, inputId, clearId, onFile, onClear) {
    const dz = $(dzId);
    const input = $(inputId);
    if (!dz) return;
    dz.addEventListener('click', () => input.click());
    dz.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('border-brand'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('border-brand'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('border-brand');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => { if (input.files[0]) onFile(input.files[0]); });
    $(clearId).addEventListener('click', (e) => { e.stopPropagation(); onClear(); });
    // Enter on the nested Clear button must not bubble to the dropzone's
    // keydown handler (which would re-open the file picker).
    $(clearId).addEventListener('keydown', (e) => e.stopPropagation());
  }

  // ── insert: where the pages go ──────────────────────────────────────────
  function positionChoice() {
    const checked = document.querySelector('input[name="pdf-position"]:checked');
    return checked ? checked.value : 'end';
  }

  function afterPageValue() {
    const input = $('pdf-after-page');
    const n = input ? input.valueAsNumber : NaN;
    return Number.isSafeInteger(n) && n >= 1 ? n : null;
  }

  // The live sentence under the choice: where the new pages will start.
  function updatePositionNote() {
    const note = $('pdf-position-note');
    if (!note) return;
    const choice = positionChoice();
    if (choice === 'start') {
      note.textContent = t('pdfPositionStart', 'The new pages start at page 1.');
    } else if (choice === 'after') {
      const n = afterPageValue();
      note.textContent = n ? t('pdfPositionAfter', 'The new pages start at page {page}.', { page: n + 1 }) : '';
    } else {
      note.textContent = t('pdfPositionEnd', 'The new pages go after the last page.');
    }
  }

  function wirePosition() {
    const radios = document.querySelectorAll('input[name="pdf-position"]');
    if (!radios.length) return;
    radios.forEach((radio) => radio.addEventListener('change', updatePositionNote));
    $('pdf-after-page').addEventListener('input', () => {
      // Typing a page number means "after page".
      document.querySelector('input[name="pdf-position"][value="after"]').checked = true;
      updatePositionNote();
    });
    updatePositionNote();
  }

  // The result in numbers, from the route's headers; without them (a
  // stripping proxy) the neutral "ready" summary stays.
  function showInsertSummary(res, blob) {
    const summary = $('pdf-result-summary');
    summary.textContent = DEFAULT_SUMMARY;
    const inserted = parseInt(res.headers.get('X-FileMorph-Inserted-Pages') || '', 10);
    const total = parseInt(res.headers.get('X-FileMorph-Page-Count') || '', 10);
    if (!isFinite(inserted) || !isFinite(total)) return;
    // Decimal units, as the compress tools count them; KB below 1 MB.
    const lang = document.documentElement.lang || undefined;
    const size = blob.size < 999500
      ? Math.max(1, Math.round(blob.size / 1e3)).toLocaleString(lang) + ' KB'
      : (blob.size / 1e6).toLocaleString(lang, { maximumFractionDigits: 1 }) + ' MB';
    summary.textContent = inserted === 1
      ? t('pdfInsertedOne', '1 page inserted — now {total} pages, {size}.', { total, size })
      : t('pdfInsertedMany', '{inserted} pages inserted — now {total} pages, {size}.', { inserted, total, size });
  }

  // "Insert something else": the result becomes the PDF — named like the
  // PDF the run started with, so the next download is <name>_inserted.pdf
  // again.
  function insertMore() {
    if (!lastResult) return;
    const link = $('pdf-download');
    if (link.href && link.href.startsWith('blob:')) {
      URL.revokeObjectURL(link.href);
      link.removeAttribute('href');
    }
    setFile(lastResult);
    $('pdf-filename').textContent = t('pdfWithInserted', '{name} (with the inserted pages)', {
      name: lastResult.name,
    });
    lastResult = null;
    clearInsertFile();
    document.querySelector('input[name="pdf-position"][value="end"]').checked = true;
    $('pdf-after-page').value = '';
    updatePositionNote();
    $('pdf-insert-drop').focus(); // the button that had the focus is hidden now
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
    // Same restore-first pattern for the download label — only the no-images
    // branch below overrides it.
    const label = $('pdf-download-label');
    if (label) label.textContent = DEFAULT_DOWNLOAD_LABEL;
    const achieved = res.headers.get('X-FileMorph-Achieved-Bytes');
    const converged = res.headers.get('X-FileMorph-Converged');
    const images = res.headers.get('X-FileMorph-Recompressible-Images');
    if (achieved === null || converged === null || images === null) return;

    const bytes = parseInt(achieved, 10);
    if (!isFinite(bytes)) return;
    const mb = (bytes / 1e6).toFixed(2); // decimal MB, as the target was entered
    if (images === '0') {
      note.textContent = t(
        'pdfCompressNoImages',
        'Nothing to recompress — this PDF has no images that can be shrunk. Size: {size} MB.',
        { size: mb }
      );
      show(note);
      // Honest label: never imply a compression that didn't happen.
      if (label) label.textContent = t('pdfDownloadUnchanged', 'Download unchanged file');
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

    // X-FileMorph-Warnings: scaled=<percent> — the images' resolution was
    // lowered to fit the target; never leave that unsaid.
    const scaled = /(?:^|,)\s*scaled=(\d+)/.exec(res.headers.get('X-FileMorph-Warnings') || '');
    if (scaled) {
      const text = t(
        'pdfCompressScaled',
        "The images in the PDF were scaled down to {percent} percent of their resolution — the lowest quality alone wasn't enough for the target size. Text and layout are unchanged.",
        { percent: scaled[1] }
      );
      note.textContent = note.classList.contains('hidden') ? text : note.textContent + ' ' + text;
      show(note);
    }
  }

  async function submit() {
    if (!selectedFile) { showError(t('pdfSelectFile', 'Select a PDF file first.')); return; }

    // /pdf/insert: what goes in, and where — 0 is the start, nothing the end.
    let afterPage = null;
    const baseName = selectedFile.name;
    if (TOOL === 'insert') {
      if (!insertFile) { showError(t('pdfSelectInsertFile', 'Choose the file to insert.'), null, 'insert_file'); return; }
      const choice = positionChoice();
      if (choice === 'start') afterPage = 0;
      if (choice === 'after') {
        afterPage = afterPageValue();
        if (afterPage === null) {
          showError(t('pdfEnterPage', 'Enter the page after which the new pages go.'), null, 'after_page');
          return;
        }
      }
    }

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
      // No error code passed: this is a hard form ceiling no plan can lift,
      // so the plans upsell must NOT appear (Upsell-Regeln).
      if (mb > 2048) {
        showError(t('errorTargetSizeTooHigh', 'The target size is above the allowed maximum of 2 GB.'));
        return;
      }
      // MB as upload portals and macOS count them (5 MB = 5,000,000 bytes),
      // rounded down, so the result fits a limit of that size either way.
      targetKb = Math.max(1, Math.floor(mb * 1e6 / 1024));
    }

    hide($('pdf-error'));
    setUpsellVisible(false);
    setExtractLinkVisible(false);
    hide($('pdf-result'));
    show($('pdf-progress'));
    window.FM_announce && window.FM_announce($('pdf-progress-text').textContent);

    const fd = new FormData();
    fd.append('file', selectedFile);
    if (TOOL === 'extract') fd.append('pages', pagesValue);
    if (TOOL === 'compress') fd.append('target_kb', String(targetKb));
    if (TOOL === 'insert') {
      fd.append('insert_file', insertFile);
      if (afterPage !== null) fd.append('after_page', String(afterPage));
    }

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
        showError(
          errorFromResponse(res, data),
          res.headers.get('X-FileMorph-Error-Code'),
          res.headers.get('X-FileMorph-Error-Field')
        );
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
      if (TOOL === 'insert') {
        lastResult = new File([blob], baseName, { type: 'application/pdf' });
        showInsertSummary(res, blob);
      }

      show($('pdf-result'));
      window.FM_announce && window.FM_announce($('pdf-result').innerText);
    } catch (_) {
      showError(t('pdfToolError', 'Something went wrong. Please try again.'));
    } finally {
      btn.disabled = false;
    }
  }

  function restart() {
    clearFile();
    clearInsertFile();
    lastResult = null;
    $('pdf-drop').focus(); // the button that had the focus is hidden now
    const link = $('pdf-download');
    if (link && link.href && link.href.startsWith('blob:')) {
      URL.revokeObjectURL(link.href);
      link.removeAttribute('href');
    }
    const label = $('pdf-download-label');
    if (label) label.textContent = DEFAULT_DOWNLOAD_LABEL;
    hide($('pdf-result'));
    hide($('pdf-error'));
    setUpsellVisible(false);
    setExtractLinkVisible(false);
    hide($('pdf-pages-warn'));
  }

  wireDropzone('pdf-drop', 'pdf-file', 'pdf-clear', setFile, clearFile);
  wireDropzone('pdf-insert-drop', 'pdf-insert-file', 'pdf-insert-clear', setInsertFile, clearInsertFile);
  wirePagesInput();
  wirePosition();
  $('pdf-submit').addEventListener('click', submit);
  $('pdf-restart').addEventListener('click', restart);
  if ($('pdf-insert-more')) $('pdf-insert-more').addEventListener('click', insertMore);
})();

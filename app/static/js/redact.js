// SPDX-License-Identifier: AGPL-3.0-or-later
// PII redaction tool (/redact). Two-phase: detect (free, anonymous-OK) → apply
// (paid). CSP-safe: no inline handlers — everything wired via addEventListener.
// Auth mirrors app.js: plain fetch with optional X-API-Key + Bearer headers, so
// it works anonymously and resolves a logged-in user's tier server-side.
(function () {
  'use strict';

  const root = document.getElementById('redact-tool');
  if (!root) return;

  const body = document.body;
  const UPLOAD_BASE = (body && body.dataset.apiBase) || '';
  const CREDIT_COST = root.dataset.creditCost || '1';
  const ELIGIBLE = (body && body.dataset.aiEligible || '')
    .split(',').map((s) => s.trim()).filter(Boolean);
  const I18N = window.FM_I18N || {};

  let selectedFile = null;
  let selectedMode = 'replace';

  const $ = (id) => document.getElementById(id);
  const show = (el) => el && el.classList.remove('hidden');
  const hide = (el) => el && el.classList.add('hidden');

  // Translate with {count}/{n} token substitution.
  function t(key, fallback, vars) {
    let s = I18N[key] || fallback;
    if (vars) for (const k in vars) s = s.replace('{' + k + '}', vars[k]);
    return s;
  }

  function entityLabel(type) {
    return I18N['redactEntity' + type] || type;
  }

  // Mask the value for on-screen display (the redaction itself is server-side).
  function maskValue(v) {
    if (!v) return '';
    return v.length > 6 ? v.slice(0, 3) + '***' + v.slice(-3) : '***';
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
    hide($('redact-progress'));
    $('redact-error-text').textContent = msg;
    show($('redact-error'));
  }

  function errorFromResponse(res, data) {
    const code = res.headers.get('X-FileMorph-Error-Code');
    if (code === 'ai_unavailable') return t('redactUnavailable', 'Redaction is not available on this deployment.');
    if (code === 'ai_credits_exhausted') return t('redactInsufficientCredits', 'Out of redaction credits — upgrade your plan or wait for the monthly reset.');
    if (code === 'redaction_verification_failed') return t('redactVerifyFailed', 'Redaction could not be verified — no file was produced. Please try again.');
    if (code === 'unsupported_format') return t('redactUnsupported', 'Unsupported file. Supported: TXT, DOCX, XLSX.');
    return (data && data.detail) || t('redactError', 'Redaction failed. Please try again.');
  }

  // ── file selection ────────────────────────────────────────────────────────
  function setFile(file) {
    selectedFile = file;
    $('redact-filename').textContent = file.name;
    hide($('redact-idle'));
    show($('redact-selected'));
    // back to a clean step-1 state if a previous run is on screen
    hide($('redact-findings'));
    hide($('redact-result'));
    hide($('redact-error'));
  }

  function clearFile() {
    selectedFile = null;
    $('redact-file').value = '';
    show($('redact-idle'));
    hide($('redact-selected'));
  }

  function wireDropzone() {
    const dz = $('redact-drop');
    const input = $('redact-file');
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
    $('redact-clear').addEventListener('click', (e) => { e.stopPropagation(); clearFile(); });
  }

  function wireMode() {
    const group = $('redact-mode');
    group.querySelectorAll('button[data-mode]').forEach((btn) => {
      btn.addEventListener('click', () => {
        selectedMode = btn.dataset.mode;
        group.querySelectorAll('button[data-mode]').forEach((b) => {
          const on = b === btn;
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
          b.classList.toggle('bg-brand', on);
          b.classList.toggle('text-white', on);
          b.classList.toggle('bg-gray-800', !on);
          b.classList.toggle('text-gray-200', !on);
        });
      });
    });
  }

  // ── phase 1: detect ─────────────────────────────────────────────────────────
  async function scan() {
    if (!selectedFile) { showError(t('redactNoFindings', 'Select a file first.')); return; }
    hide($('redact-error'));
    hide($('redact-findings'));
    $('redact-progress-text').textContent = t('redactScanning', 'Scanning…');
    show($('redact-progress'));

    const fd = new FormData();
    fd.append('file', selectedFile);
    try {
      const res = await fetch(UPLOAD_BASE + '/api/v1/ai/redact/detect', {
        method: 'POST', headers: authHeaders(), body: fd,
      });
      let data = {};
      try { data = await res.json(); } catch (_) { /* non-JSON */ }
      hide($('redact-progress'));
      if (!res.ok) { showError(errorFromResponse(res, data)); return; }
      renderFindings(data);
    } catch (_) {
      showError(t('redactError', 'Redaction failed. Please try again.'));
    }
  }

  function renderFindings(data) {
    const list = $('redact-findings-list');
    list.innerHTML = '';
    const findings = data.findings || [];
    $('redact-findings-count').textContent = findings.length
      ? t('redactFindings', '{count} item(s) found', { count: findings.length })
      : t('redactNoFindings', 'No PII detected in this file.');

    let hasPhone = false;
    findings.forEach((f) => {
      if (f.entity_type === 'PHONE') hasPhone = true;
      const row = document.createElement('div');
      row.className = 'flex justify-between gap-2 border-b border-gray-800 py-1';
      const conf = Math.round((f.confidence || 0) * 100);
      // textContent (not innerHTML) for every value: f.value comes from the
      // user's uploaded file, so it must never be interpolated as HTML.
      const left = document.createElement('span');
      const typeSpan = document.createElement('span');
      typeSpan.className = 'text-gray-200';
      typeSpan.textContent = entityLabel(f.entity_type);
      const valSpan = document.createElement('span');
      valSpan.className = 'text-gray-500 ml-1';
      valSpan.textContent = maskValue(f.value);
      left.appendChild(typeSpan);
      left.appendChild(valSpan);
      const right = document.createElement('span');
      right.className = conf < 90 ? 'text-amber-400' : 'text-gray-600';
      right.textContent = `${f.location} · ${conf}%`;
      row.appendChild(left);
      row.appendChild(right);
      list.appendChild(row);
    });

    const phoneNote = $('redact-phone-note');
    if (hasPhone) { phoneNote.textContent = t('redactPhoneReview', 'Phone numbers are lower-confidence — review before redacting.'); show(phoneNote); }
    else hide(phoneNote);

    let cost = t('redactCreditCost', 'Costs {n} credit per file', { n: CREDIT_COST });
    if (data.credits_remaining !== null && data.credits_remaining !== undefined) {
      cost += ' · ' + t('redactCreditsRemaining', '{n} credits remaining', { n: data.credits_remaining });
    }
    $('redact-cost').textContent = findings.length ? cost : '';

    show($('redact-findings'));
    gateApply();
  }

  // Decide apply button vs. paid-gate panel based on the logged-in user's tier.
  // The server still enforces 403/402 — this is just to avoid a cold wall.
  async function gateApply() {
    const applyBtn = $('redact-apply-btn');
    const gate = $('redact-paid-gate');
    let user = null;
    if (window.FM && window.FM.getUser) { try { user = await window.FM.getUser(); } catch (_) { /* anon */ } }
    const allowed = user && ELIGIBLE.includes(user.tier);
    if (allowed) { show(applyBtn); hide(gate); }
    else {
      hide(applyBtn);
      $('redact-paid-title').textContent = t('redactPaidTitle', 'Downloading the redacted file needs a paid plan');
      $('redact-paid-body').textContent = t('redactPaidBody', "You've seen the findings above. Redacting and downloading the file requires a Pro or Business plan.");
      show(gate);
    }
  }

  // ── phase 2: apply ──────────────────────────────────────────────────────────
  function filenameFromDisposition(res, fallback) {
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    return (m && m[1]) || fallback;
  }

  async function apply() {
    if (!selectedFile) return;
    hide($('redact-error'));
    $('redact-progress-text').textContent = t('redactApplying', 'Redacting…');
    show($('redact-progress'));

    const fd = new FormData();
    fd.append('file', selectedFile);
    fd.append('mode', selectedMode);
    try {
      const res = await fetch(UPLOAD_BASE + '/api/v1/ai/redact/apply', {
        method: 'POST', headers: authHeaders(), body: fd,
      });
      hide($('redact-progress'));
      if (!res.ok) {
        let data = {};
        try { data = await res.json(); } catch (_) { /* binary/no body */ }
        showError(errorFromResponse(res, data));
        return;
      }
      const blob = await res.blob();
      const name = filenameFromDisposition(res, 'redacted');
      const link = $('redact-download');
      link.href = URL.createObjectURL(blob);
      link.download = name;
      const n = res.headers.get('X-FileMorph-AI-Entities-Redacted') || '0';
      const left = res.headers.get('X-FileMorph-AI-Credits-Remaining');
      let summary = t('redactFindings', '{count} item(s) found', { count: n }).replace(/found/i, 'redacted');
      if (left !== null && left !== '') summary += ' · ' + t('redactCreditsRemaining', '{n} credits remaining', { n: left });
      $('redact-result-summary').textContent = summary;
      hide($('redact-findings'));
      show($('redact-result'));
    } catch (_) {
      showError(t('redactError', 'Redaction failed. Please try again.'));
    }
  }

  function restart() {
    clearFile();
    hide($('redact-result'));
    hide($('redact-findings'));
    hide($('redact-error'));
    show($('redact-step-upload'));
  }

  wireDropzone();
  wireMode();
  $('redact-scan-btn').addEventListener('click', scan);
  $('redact-apply-btn').addEventListener('click', apply);
  $('redact-restart').addEventListener('click', restart);
})();

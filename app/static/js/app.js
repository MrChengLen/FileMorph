/* FileMorph — UI logic */

// Heavy upload POSTs (convert/compress, single + batch) may route through a
// separate base URL when the main site sits behind a proxy that caps request
// bodies. Wired from `<body data-api-base>`, which the server fills from the
// `API_BASE_URL` env var. Empty string keeps uploads same-origin — which is
// the only path the test harness ever exercises. All other fetches (formats,
// auth, billing) stay same-origin regardless.
const UPLOAD_BASE = (document.body && document.body.dataset.apiBase) || '';

let supportedConversions = {};
let currentMode = 'convert';
let compressMode = 'quality'; // 'quality' | 'target' — only meaningful in compress mode
let selectedFiles = [];

const TARGET_SIZE_FORMATS = ['jpg', 'jpeg', 'webp'];

// ── Initialisation ────────────────────────────────────────────────────────────

async function init() {
  try {
    const res = await fetch('/api/v1/formats');
    if (res.ok) {
      const data = await res.json();
      supportedConversions = data.conversions || {};
    }
  } catch (_) {
    // Fall through — format list will be empty, user sees generic message
  }
}

init();

document.addEventListener('DOMContentLoaded', () => {
  const btnConvert = document.getElementById('btn-mode-convert');
  const btnCompress = document.getElementById('btn-mode-compress');
  if (btnConvert) btnConvert.addEventListener('click', () => setMode('convert'));
  if (btnCompress) btnCompress.addEventListener('click', () => setMode('compress'));

  const dz = document.getElementById('drop-zone');
  if (dz) {
    dz.addEventListener('click', () => document.getElementById('file-input').click());
    dz.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') document.getElementById('file-input').click();
    });
    dz.addEventListener('dragover', handleDragOver);
    dz.addEventListener('dragleave', handleDragLeave);
    dz.addEventListener('drop', handleDrop);
  }

  const fileInput = document.getElementById('file-input');
  if (fileInput) fileInput.addEventListener('change', handleFileSelect);

  const clearBtn = document.getElementById('clear-file-btn');
  if (clearBtn) clearBtn.addEventListener('click', clearAllFiles);

  const qualitySlider = document.getElementById('quality-slider');
  if (qualitySlider) qualitySlider.addEventListener('input', e => {
    document.getElementById('quality-label').textContent = e.target.value + '%';
  });

  const cmodeQuality = document.getElementById('cmode-quality');
  const cmodeTarget = document.getElementById('cmode-target');
  if (cmodeQuality) cmodeQuality.addEventListener('click', () => setCompressMode('quality'));
  if (cmodeTarget) cmodeTarget.addEventListener('click', () => setCompressMode('target'));

  const targetSizeInput = document.getElementById('target-size-input');
  if (targetSizeInput) targetSizeInput.addEventListener('input', updateTargetSizeLabel);

  const targetSelect = document.getElementById('target-format');
  if (targetSelect) targetSelect.addEventListener('change', () => {
    updateFormatWarning();
    updateQualityVisibility();
  });

  const suggestBtn = document.getElementById('format-warning-suggest');
  if (suggestBtn) suggestBtn.addEventListener('click', () => {
    const alt = suggestBtn.dataset.target;
    const sel = document.getElementById('target-format');
    if (alt && sel) {
      sel.value = alt;
      updateFormatWarning();
      updateQualityVisibility();
    }
  });

  const convertBtn = document.getElementById('convert-btn');
  if (convertBtn) convertBtn.addEventListener('click', submitForm);
});

// ── Mode toggle ───────────────────────────────────────────────────────────────

function setMode(mode) {
  currentMode = mode;
  const btnConvert = document.getElementById('btn-mode-convert');
  const btnCompress = document.getElementById('btn-mode-compress');
  const convertBtn = document.getElementById('convert-btn');

  btnConvert.setAttribute('aria-pressed', mode === 'convert' ? 'true' : 'false');
  btnCompress.setAttribute('aria-pressed', mode === 'compress' ? 'true' : 'false');

  if (mode === 'convert') {
    btnConvert.classList.add('bg-brand', 'text-white');
    btnConvert.classList.remove('text-gray-400');
    btnCompress.classList.remove('bg-brand', 'text-white');
    btnCompress.classList.add('text-gray-400');
    convertBtn.textContent = (window.FM_I18N && window.FM_I18N.convert) || 'Convert';
  } else {
    btnCompress.classList.add('bg-brand', 'text-white');
    btnCompress.classList.remove('text-gray-400');
    btnConvert.classList.remove('bg-brand', 'text-white');
    btnConvert.classList.add('text-gray-400');
    convertBtn.textContent = (window.FM_I18N && window.FM_I18N.compress) || 'Compress';
  }

  const qHeading = document.getElementById('quality-heading');
  if (qHeading) qHeading.textContent = mode === 'compress'
    ? ((window.FM_I18N && window.FM_I18N.compression) || 'Compression')
    : ((window.FM_I18N && window.FM_I18N.quality) || 'Quality');

  if (mode !== 'compress') {
    compressMode = 'quality';
  }

  // Drop-zone help text differs per mode: convert covers all source formats,
  // compress is limited to JPG/PNG/WebP/TIFF + MP4/AVI/MOV/MKV/WebM. The
  // server rejects mismatches anyway, but showing the right list up-front
  // keeps users from uploading e.g. an MP3 only to see a 422.
  const supConv = document.getElementById('supported-convert');
  const supComp = document.getElementById('supported-compress');
  if (supConv && supComp) {
    supConv.classList.toggle('hidden', mode !== 'convert');
    supComp.classList.toggle('hidden', mode !== 'compress');
  }

  updateConvertOptionsVisibility();
  renderFileList();
  updateQualityVisibility();
  updateFormatWarning();
  resetResultState();
}

function setCompressMode(mode) {
  compressMode = mode;
  syncCompressModeButtons();
  updateQualityVisibility();
}

function syncCompressModeButtons() {
  const qBtn = document.getElementById('cmode-quality');
  const tBtn = document.getElementById('cmode-target');
  if (!qBtn || !tBtn) return;
  const isQuality = compressMode === 'quality';
  qBtn.classList.toggle('bg-brand', isQuality);
  qBtn.classList.toggle('text-white', isQuality);
  qBtn.classList.toggle('text-gray-200', !isQuality);
  tBtn.classList.toggle('bg-brand', !isQuality);
  tBtn.classList.toggle('text-white', !isQuality);
  tBtn.classList.toggle('text-gray-200', isQuality);
}

function updateTargetSizeLabel() {
  const input = document.getElementById('target-size-input');
  const label = document.getElementById('target-size-label');
  if (!input || !label) return;
  const mb = parseFloat(input.value || '0');
  label.textContent = isFinite(mb) && mb > 0 ? `${mb.toFixed(2)} MB` : '—';
}

// The standalone target-format dropdown drives the single-file flow. In
// batch convert mode we render a per-row dropdown inside each file entry
// instead, so this whole block goes away — each row carries its own target.
function updateConvertOptionsVisibility() {
  const opts = document.getElementById('convert-options');
  if (!opts) return;
  const isBatch = selectedFiles.length > 1;
  const showStandalone = currentMode === 'convert' && !isBatch;
  opts.classList.toggle('hidden', !showStandalone);
}

// ── File selection ────────────────────────────────────────────────────────────

function handleFileSelect(event) {
  const files = Array.from(event.target.files || []);
  if (files.length) setFiles(files);
}

function handleDragOver(event) {
  event.preventDefault();
  document.getElementById('drop-zone').classList.add('drag-over');
}

function handleDragLeave(event) {
  document.getElementById('drop-zone').classList.remove('drag-over');
}

function handleDrop(event) {
  event.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  const files = Array.from(event.dataTransfer.files || []);
  if (files.length) setFiles(files);
}

function setFiles(files) {
  selectedFiles = files;

  document.getElementById('drop-idle').classList.add('hidden');
  document.getElementById('drop-selected').classList.remove('hidden');
  renderFileList();

  // Single-file flow: populate the standalone dropdown from the first file's
  // extension. Batch flow draws a per-row dropdown inside each row instead
  // (see renderFileList) and hides the standalone block.
  updateConvertOptionsVisibility();
  if (selectedFiles.length === 1) {
    updateTargetFormats(selectedFiles[0].name);
  }
  updateQualityVisibility();
  updateFormatWarning();
  resetResultState();
}

function renderFileList() {
  const list = document.getElementById('selected-files-list');
  const count = document.getElementById('selected-count');
  const isBatch = selectedFiles.length > 1;
  if (list) {
    list.innerHTML = '';
    selectedFiles.forEach((file, idx) => {
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between gap-2 text-sm';

      const name = document.createElement('span');
      name.className = 'truncate flex-1 text-white';
      name.textContent = file.name;

      const size = document.createElement('span');
      size.className = 'text-xs text-gray-500 shrink-0';
      size.textContent = formatBytes(file.size);

      // Batch convert: each file picks its own target — mixed-format
      // uploads (e.g. JPG + PNG) can't share one dropdown.
      let perRowSelect = null;
      if (isBatch && currentMode === 'convert') {
        perRowSelect = document.createElement('select');
        perRowSelect.className =
          'per-row-target bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs shrink-0 focus:outline-none focus:border-brand transition-colors';
        perRowSelect.setAttribute('aria-label', `Target format for ${file.name}`);
        const ext = getExtension(file.name);
        const targets = supportedConversions[ext] || [];
        if (targets.length === 0) {
          const opt = document.createElement('option');
          opt.value = '';
          opt.textContent = '— no targets —';
          perRowSelect.appendChild(opt);
          perRowSelect.disabled = true;
          row.classList.add('opacity-60');
        } else {
          targets.forEach(fmt => {
            const opt = document.createElement('option');
            opt.value = fmt;
            opt.textContent = fmt.toUpperCase();
            perRowSelect.appendChild(opt);
          });
        }
        perRowSelect.addEventListener('change', () => updateQualityVisibility());
        // Row lives inside #drop-zone — without stopPropagation, a click on
        // the select bubbles up and fires the drop-zone handler, which opens
        // the file picker instead of the dropdown. Keydown covers the
        // keyboard path (Enter/Space open the picker via the same handler).
        perRowSelect.addEventListener('click', e => e.stopPropagation());
        perRowSelect.addEventListener('keydown', e => e.stopPropagation());
      }

      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'text-xs text-gray-600 hover:text-red-400 transition-colors shrink-0';
      rm.setAttribute('aria-label', `Remove ${file.name}`);
      rm.textContent = '✕';
      rm.addEventListener('click', e => {
        e.stopPropagation();
        removeFile(idx);
      });

      row.appendChild(name);
      row.appendChild(size);
      if (perRowSelect) row.appendChild(perRowSelect);
      row.appendChild(rm);
      list.appendChild(row);
    });
  }
  if (count) {
    const totalBytes = selectedFiles.reduce((s, f) => s + f.size, 0);
    count.textContent = selectedFiles.length === 1
      ? `1 file · ${formatBytes(totalBytes)}`
      : `${selectedFiles.length} files · ${formatBytes(totalBytes)} total`;
  }
}

function removeFile(idx) {
  selectedFiles.splice(idx, 1);
  if (selectedFiles.length === 0) {
    clearAllFiles();
    return;
  }
  renderFileList();
  updateConvertOptionsVisibility();
  if (selectedFiles.length === 1) {
    updateTargetFormats(selectedFiles[0].name);
  }
  updateQualityVisibility();
  updateFormatWarning();
}

function clearAllFiles(event) {
  if (event) event.stopPropagation();
  selectedFiles = [];
  document.getElementById('file-input').value = '';
  document.getElementById('drop-idle').classList.remove('hidden');
  document.getElementById('drop-selected').classList.add('hidden');
  document.getElementById('target-format').innerHTML =
    '<option value="">— select a file first —</option>';
  document.getElementById('quality-section').classList.add('hidden');
  updateConvertOptionsVisibility();
  updateFormatWarning();
  resetResultState();
}

// ── Format helpers ────────────────────────────────────────────────────────────

// File types where quality slider is relevant
const QUALITY_TYPES = ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'avi', 'mov', 'mkv', 'webm'];

// S1-B: src→tgt pairs that inflate output size. Keys are source extensions,
// values map bad target → {factor: display string, suggest: better target}.
// Driven by measured amplification: JPG→PNG ≈ 5-10×, MP3→WAV ≈ 11×. The
// suggestion is only offered if the API actually supports it for this source.
const AMPLIFIERS = {
  jpg:  { png: { factor: '5–10× larger', suggest: 'webp' }, bmp: { factor: '5–10× larger', suggest: 'webp' }, tiff: { factor: '5–10× larger', suggest: 'webp' } },
  jpeg: { png: { factor: '5–10× larger', suggest: 'webp' }, bmp: { factor: '5–10× larger', suggest: 'webp' }, tiff: { factor: '5–10× larger', suggest: 'webp' } },
  heic: { png: { factor: '5–10× larger', suggest: 'webp' }, bmp: { factor: '5–10× larger', suggest: 'webp' } },
  webp: { png: { factor: '5–10× larger', suggest: 'jpg' }, bmp: { factor: '5–10× larger', suggest: 'jpg' } },
  mp3:  { wav: { factor: '~11× larger',  suggest: 'flac' } },
  ogg:  { wav: { factor: '~11× larger',  suggest: 'flac' } },
  m4a:  { wav: { factor: '~11× larger',  suggest: 'flac' } },
  aac:  { wav: { factor: '~11× larger',  suggest: 'flac' } },
};

function getExtension(filename) {
  return filename.split('.').pop().toLowerCase();
}

function updateTargetFormats(filename) {
  const ext = getExtension(filename);
  const select = document.getElementById('target-format');
  select.innerHTML = '';

  const targets = supportedConversions[ext] || [];
  if (targets.length === 0) {
    const noConvLabel = (window.FM_I18N && window.FM_I18N.noConversionsAvailable) || 'No conversions available for this format';
    select.innerHTML = '<option value="">' + noConvLabel + '</option>';
    updateFormatWarning();
    return;
  }

  targets.forEach(fmt => {
    const opt = document.createElement('option');
    opt.value = fmt;
    opt.textContent = fmt.toUpperCase();
    select.appendChild(opt);
  });
  updateFormatWarning();
}

function updateFormatWarning() {
  const warnEl = document.getElementById('format-warning');
  if (!warnEl) return;
  const textEl = document.getElementById('format-warning-text');
  const suggestBtn = document.getElementById('format-warning-suggest');

  // Warning is tied to the standalone dropdown. In batch mode that dropdown
  // is hidden (each row carries its own target), so the banner doesn't apply.
  const isBatch = selectedFiles.length > 1;
  if (selectedFiles.length === 0 || currentMode !== 'convert' || isBatch) {
    warnEl.classList.add('hidden');
    return;
  }

  const ext = getExtension(selectedFiles[0].name);
  const target = document.getElementById('target-format').value;
  const match = (AMPLIFIERS[ext] || {})[target];

  if (!match) {
    warnEl.classList.add('hidden');
    return;
  }

  const available = supportedConversions[ext] || [];
  if (!available.includes(match.suggest)) {
    // Suggested alternative isn't supported for this source — hide the banner
    // rather than proposing something the API would reject.
    warnEl.classList.add('hidden');
    return;
  }

  textEl.textContent = `Heads up: ${target.toUpperCase()} output is typically ${match.factor} than the source.`;
  suggestBtn.textContent = `Use ${match.suggest.toUpperCase()} instead →`;
  suggestBtn.dataset.target = match.suggest;
  warnEl.classList.remove('hidden');
}

function updateQualityVisibility() {
  const section = document.getElementById('quality-section');
  const cmodeToggle = document.getElementById('compress-mode-toggle');
  const targetSection = document.getElementById('target-size-section');

  const hideAll = () => {
    section.classList.add('hidden');
    if (cmodeToggle) cmodeToggle.classList.add('hidden');
    if (targetSection) targetSection.classList.add('hidden');
  };

  if (selectedFiles.length === 0) { hideAll(); return; }

  if (currentMode === 'compress') {
    // Target-size mode is only valid when every selected file is JPEG/WebP.
    const targetEligible = selectedFiles.every(f =>
      TARGET_SIZE_FORMATS.includes(getExtension(f.name))
    );
    if (cmodeToggle) {
      cmodeToggle.classList.toggle('hidden', !targetEligible);
      if (targetEligible) syncCompressModeButtons();
    }
    if (!targetEligible && compressMode === 'target') {
      compressMode = 'quality';
    }
    const showTarget = compressMode === 'target' && targetEligible;
    section.classList.toggle('hidden', showTarget);
    if (targetSection) targetSection.classList.toggle('hidden', !showTarget);
    if (showTarget) updateTargetSizeLabel();
    return;
  }

  // Convert mode: hide compress-mode-toggle and target-size-section.
  if (cmodeToggle) cmodeToggle.classList.add('hidden');
  if (targetSection) targetSection.classList.add('hidden');

  const isBatch = selectedFiles.length > 1;
  let relevant = selectedFiles.some(f => QUALITY_TYPES.includes(getExtension(f.name)));
  if (!relevant) {
    if (isBatch) {
      document.querySelectorAll('.per-row-target').forEach(sel => {
        if (QUALITY_TYPES.includes(sel.value)) relevant = true;
      });
    } else {
      const target = document.getElementById('target-format').value;
      if (QUALITY_TYPES.includes(target)) relevant = true;
    }
  }
  section.classList.toggle('hidden', !relevant);
}

// ── Submit ────────────────────────────────────────────────────────────────────

async function submitForm() {
  const I18N = window.FM_I18N || {};
  if (selectedFiles.length === 0) { alert(I18N.alertNoFiles || 'Please select at least one file.'); return; }

  const isBatch = selectedFiles.length > 1;
  const base = currentMode === 'convert' ? '/api/v1/convert' : '/api/v1/compress';
  const endpoint = UPLOAD_BASE + (isBatch ? `${base}/batch` : base);
  const quality = document.getElementById('quality-slider').value;

  const useTargetSize = currentMode === 'compress' && compressMode === 'target';

  const formData = new FormData();
  if (isBatch) {
    selectedFiles.forEach(f => formData.append('files', f));
  } else {
    formData.append('file', selectedFiles[0]);
  }
  if (useTargetSize) {
    const mb = parseFloat(document.getElementById('target-size-input').value || '0');
    if (!isFinite(mb) || mb <= 0) {
      alert(I18N.alertNoTargetSize || 'Please enter a target size in MB.');
      return;
    }
    formData.append('target_size_kb', String(Math.max(5, Math.round(mb * 1024))));
  } else {
    formData.append('quality', quality);
  }

  if (currentMode === 'convert') {
    if (isBatch) {
      // Batch: one target per file, in the same order as the files were
      // appended. Server rejects length mismatch with 422, but we guard
      // here so the user doesn't waste an upload round-trip on a typo.
      const rows = document.querySelectorAll('.per-row-target');
      if (rows.length !== selectedFiles.length) {
        alert(I18N.alertInconsistentTarget || 'Target format selection is inconsistent — please reselect your files.');
        return;
      }
      for (const sel of rows) {
        if (!sel.value) {
          alert(I18N.alertNoTargetAvailable || 'One of the files has no target format available. Remove it to proceed.');
          return;
        }
        formData.append('target_formats', sel.value);
      }
    } else {
      const target = document.getElementById('target-format').value;
      if (!target) { alert(I18N.alertNoTargetFormat || 'Please select a target format.'); return; }
      formData.append('target_format', target);
    }
  }

  showProgress(isBatch
    ? `Processing ${selectedFiles.length} files…`
    : 'Processing your file…');

  const headers = {};
  const savedKey = localStorage.getItem('filemorph_api_key');
  if (savedKey) headers['X-API-Key'] = savedKey;
  // A logged-in user's JWT (from /login or /register) identifies them to
  // the upload endpoints so tier-based quotas (batch size, file size) match
  // their account. Without this, the server falls back to the anonymous
  // tier even when the cockpit shows a paid plan.
  const accessToken = localStorage.getItem('fm_access_token');
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  try {
    const res = await fetch(endpoint, { method: 'POST', headers, body: formData });

    if (!res.ok) {
      let data = {};
      try { data = await res.json(); } catch (_) { /* non-JSON body */ }

      // Batch all-failed: server returns 422 with {summary, files[]}
      if (res.status === 422 && data && data.summary) {
        const first = data.files?.find(f => f.status === 'error')?.error_message
          || 'All files failed.';
        showError(`Batch failed: ${data.summary.failed}/${data.summary.total} files. First error: ${first}`);
      } else if (res.status === 400 && data.detail) {
        // Batch-size over tier limit lands here with a clear server message
        showError(data.detail);
      } else if (res.status === 401) {
        showError('Invalid API key. Check your key and try again.');
      } else if (res.status === 413) {
        showError(data.detail || 'File too large for your plan.');
      } else if (res.status === 429) {
        showError('Too many requests. Please wait a moment and try again.');
      } else {
        showError(data.detail || `Conversion failed (status ${res.status}).`);
      }
      return;
    }

    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    const nameMatch = disposition.match(/filename="?([^"]+)"?/);
    // Defensive fallback: if Content-Disposition is unreadable (e.g. a proxy
    // strips it), still produce a correctly-extensioned filename. The target
    // extension is known client-side: convert mode → the target-format
    // dropdown; compress mode → the source extension (output format matches).
    const outputExt = currentMode === 'convert'
      ? document.getElementById('target-format').value
      : getExtension(selectedFiles[0].name);
    const fallbackName = isBatch ? 'filemorph-batch.zip' : `result.${outputExt}`;
    const filename = nameMatch ? nameMatch[1] : fallbackName;

    const url = URL.createObjectURL(blob);
    const link = document.getElementById('download-link');
    link.href = url;
    link.download = filename;

    const label = document.getElementById('download-link-label');
    if (label) {
      const achieved = res.headers.get('X-FileMorph-Achieved-Bytes');
      if (!isBatch && useTargetSize && achieved) {
        const mb = (parseInt(achieved, 10) / (1024 * 1024)).toFixed(2);
        label.textContent = `Download Result (${mb} MB)`;
      } else {
        label.textContent = isBatch
          ? `Download ZIP (${selectedFiles.length} files)`
          : 'Download Result';
      }
    }

    showResult();
  } catch (e) {
    showError('Network error: ' + e.message);
  }
}

// ── State helpers ─────────────────────────────────────────────────────────────

function showProgress(text) {
  document.getElementById('progress-text').textContent = text;
  document.getElementById('progress-section').classList.remove('hidden');
  document.getElementById('result-section').classList.add('hidden');
  document.getElementById('error-section').classList.add('hidden');
  document.getElementById('convert-btn').disabled = true;
}

function showResult() {
  document.getElementById('progress-section').classList.add('hidden');
  document.getElementById('result-section').classList.remove('hidden');
  document.getElementById('error-section').classList.add('hidden');
  document.getElementById('convert-btn').disabled = false;
}

function showError(msg) {
  document.getElementById('error-text').textContent = msg;
  document.getElementById('progress-section').classList.add('hidden');
  document.getElementById('result-section').classList.add('hidden');
  document.getElementById('error-section').classList.remove('hidden');
  document.getElementById('convert-btn').disabled = false;
}

function resetResultState() {
  document.getElementById('progress-section').classList.add('hidden');
  document.getElementById('result-section').classList.add('hidden');
  document.getElementById('error-section').classList.add('hidden');
  document.getElementById('convert-btn').disabled = false;
}

// ── Utils ─────────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

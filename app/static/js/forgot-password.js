// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('send-btn').addEventListener('click', doReset);
  // Enter in the field sends — not Enter on a link or button (the skip link is
  // the first Tab stop and would send an empty form).
  document.addEventListener('keydown', function (e) { if (e.key === 'Enter' && e.target.matches('input')) doReset(); });
});

async function doReset() {
  const btn = document.getElementById('send-btn');
  const field = document.getElementById('email');
  const err = document.getElementById('error-msg');
  // Empty or malformed: the browser says so at the field (required, type=email).
  if (!field.reportValidity()) return;
  const label = btn.textContent;
  err.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = (window.FM_I18N && window.FM_I18N.sending) || 'Sending\u2026';
  let ok = false;
  try {
    const res = await fetch('/api/v1/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: field.value.trim() }),
    });
    ok = res.ok;
  } catch (_) { /* network error: reported below */ }
  if (!ok) {
    // No "email sent" unless the server took the request.
    err.textContent = (window.FM_I18N && window.FM_I18N.pdfToolError) || 'Something went wrong. Please try again.';
    err.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = label;
    return;
  }
  document.getElementById('form-section').classList.add('hidden');
  document.getElementById('success-msg').classList.remove('hidden');
}

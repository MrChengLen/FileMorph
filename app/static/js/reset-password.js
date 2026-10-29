// SPDX-License-Identifier: AGPL-3.0-or-later
(function () {
  // The emailed link carries the token in the fragment (#token=…), which the
  // browser never sends to the server. Links mailed before that change use
  // ?token=: accept them and move the token into the fragment. They expire
  // within 7 days of this change going live (October 2026); drop it then.
  function getToken() {
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get('token');
    if (fromHash) {
      return fromHash;
    }
    const fromQuery = new URLSearchParams(window.location.search).get('token');
    if (fromQuery) {
      window.history.replaceState(null, '', window.location.pathname + '#token=' + encodeURIComponent(fromQuery));
      return fromQuery;
    }
    return '';
  }

  function showError(message) {
    const err = document.getElementById('error-msg');
    err.textContent = message;
    err.classList.remove('hidden');
  }

  function clearError() {
    document.getElementById('error-msg').classList.add('hidden');
  }

  async function doReset(token) {
    const btn = document.getElementById('reset-btn');
    const pw1 = document.getElementById('new-password').value;
    const pw2 = document.getElementById('confirm-password').value;
    clearError();
    if (pw1.length < 8) {
      showError('Password must be at least 8 characters.');
      return;
    }
    if (pw1 !== pw2) {
      showError('Passwords do not match.');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Updating\u2026';
    try {
      const res = await fetch('/api/v1/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token, new_password: pw1 }),
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        throw new Error(data.detail || 'Reset failed.');
      }
      document.getElementById('form-section').classList.add('hidden');
      document.getElementById('success-msg').classList.remove('hidden');
    } catch (e) {
      showError(e.message);
      btn.disabled = false;
      btn.textContent = 'Update password';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const token = getToken();
    if (!token) {
      document.getElementById('form-section').classList.add('hidden');
      document.getElementById('no-token-msg').classList.remove('hidden');
      return;
    }
    document.getElementById('reset-btn').addEventListener('click', function () { doReset(token); });
    document.addEventListener('keydown', function (e) {
      // Only from a field — Enter on a link or button (skip link) is not a submit.
      if (e.key === 'Enter' && e.target.matches('input')) { doReset(token); }
    });
  });
})();

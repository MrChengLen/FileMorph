// SPDX-License-Identifier: AGPL-3.0-or-later
(function () {
  function getToken() {
    const params = new URLSearchParams(window.location.search);
    return params.get('token') || '';
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
      if (e.key === 'Enter') { doReset(token); }
    });
  });
})();

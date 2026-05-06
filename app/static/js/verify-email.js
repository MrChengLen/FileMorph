// SPDX-License-Identifier: AGPL-3.0-or-later
(function () {
  function getToken() {
    const params = new URLSearchParams(window.location.search);
    return params.get('token') || '';
  }

  function show(id) {
    document.getElementById(id).classList.remove('hidden');
  }

  function hide(id) {
    document.getElementById(id).classList.add('hidden');
  }

  function showError(message) {
    const err = document.getElementById('error-msg');
    err.textContent = message;
    err.classList.remove('hidden');
  }

  async function doVerify(token) {
    show('pending-msg');
    try {
      const res = await fetch('/api/v1/auth/verify-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token }),
      });
      const data = await res.json().catch(function () { return {}; });
      hide('pending-msg');
      if (!res.ok) {
        throw new Error(data.detail || 'Verification failed.');
      }
      show('success-msg');
    } catch (e) {
      hide('pending-msg');
      showError(e.message);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const token = getToken();
    if (!token) {
      show('no-token-msg');
      return;
    }
    doVerify(token);
  });
})();

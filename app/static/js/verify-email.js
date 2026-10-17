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

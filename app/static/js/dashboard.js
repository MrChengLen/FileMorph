// SPDX-License-Identifier: AGPL-3.0-or-later
async function loadUser() {
  const res = await window.FM.authFetch('/api/v1/auth/me');
  if (!res.ok) { window.location.href = '/login'; return; }
  const u = await res.json();
  document.getElementById('user-avatar').textContent = u.email[0].toUpperCase();
  document.getElementById('user-email').textContent = u.email;
  document.getElementById('user-tier').textContent = u.tier;
  document.getElementById('user-since').textContent =
    new Date(u.created_at).toLocaleDateString('de-DE', { year: 'numeric', month: 'long', day: 'numeric' });
  // Email-language preference. NULL on the server means "no explicit
  // preference, use the operator default" — the upstream default is `de`,
  // so reflect that in the picker.
  const langSel = document.getElementById('email-lang');
  if (langSel) langSel.value = u.preferred_lang || 'de';
}

async function saveEmailLang(value) {
  const status = document.getElementById('email-lang-status');
  if (status) status.textContent = '';
  const res = await window.FM.authFetch('/api/v1/auth/account/language', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferred_lang: value }),
  });
  if (!status) return;
  if (res.ok) {
    status.textContent = status.dataset.saved;
    setTimeout(function () { status.textContent = ''; }, 2000);
  } else {
    status.textContent = status.dataset.error;
  }
}

function _t(key, fallback) {
  return (window.FM_I18N && window.FM_I18N[key]) || fallback;
}

async function loadKeys() {
  const res = await window.FM.authFetch('/api/v1/keys');
  if (!res.ok) return;
  const keys = await res.json();
  const list = document.getElementById('keys-list');
  if (keys.length === 0) {
    list.innerHTML = '<p class="text-sm text-gray-500">' + _t('noApiKeys', 'No API keys yet. Create one above.') + '</p>';
    return;
  }
  const labelCreated = _t('created', 'Created');
  const labelLastUsed = _t('lastUsed', 'Last used');
  const labelNeverUsed = _t('neverUsed', 'Never used');
  const labelRevoke = _t('revoke', 'Revoke');
  const dateLocale = (document.documentElement.lang || 'de').startsWith('en') ? 'en-GB' : 'de-DE';
  list.innerHTML = keys.map(function (k) {
    return '<div class="flex items-center justify-between gap-3 bg-gray-800 rounded-xl px-4 py-3">' +
      '<div class="min-w-0">' +
      '<p class="text-sm font-medium truncate">' + k.label + '</p>' +
      '<p class="text-xs text-gray-500">' + labelCreated + ' ' + new Date(k.created_at).toLocaleDateString(dateLocale) +
      (k.last_used_at ? ' \u00b7 ' + labelLastUsed + ' ' + new Date(k.last_used_at).toLocaleDateString(dateLocale) : ' \u00b7 ' + labelNeverUsed) + '</p>' +
      '</div>' +
      '<button data-revoke-id="' + k.id + '" class="shrink-0 text-xs text-red-400 hover:text-red-300 px-3 py-1.5 rounded-lg border border-red-900 hover:border-red-700 transition-colors">' + labelRevoke + '</button>' +
      '</div>';
  }).join('');
  list.querySelectorAll('[data-revoke-id]').forEach(function (btn) {
    btn.addEventListener('click', function () { revokeKey(btn.dataset.revokeId); });
  });
}

async function createKey() {
  const btn = document.getElementById('create-key-btn');
  btn.disabled = true;
  btn.textContent = _t('creating', 'Creating\u2026');
  const res = await window.FM.authFetch('/api/v1/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: 'My API Key' }),
  });
  btn.disabled = false;
  btn.textContent = _t('newKey', '+ New Key');
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById('new-key-value').textContent = data.key;
  document.getElementById('new-key-box').classList.remove('hidden');
  loadKeys();
}

async function revokeKey(id) {
  if (!confirm(_t('revokeConfirm', 'Revoke this API key? This cannot be undone.'))) return;
  await window.FM.authFetch('/api/v1/keys/' + id, { method: 'DELETE' });
  loadKeys();
}

function copyKey() {
  var val = document.getElementById('new-key-value').textContent;
  navigator.clipboard.writeText(val).then(function () {
    var btn = document.getElementById('copy-key-btn');
    btn.textContent = _t('copied', 'Copied!');
    setTimeout(function () { btn.textContent = _t('copy', 'Copy'); }, 2000);
  });
}

// ── Danger zone: account deletion (PR-D) ──────────────────────────────────────

function showDeleteForm() {
  if (!confirm('This will permanently delete your account, API keys, and cancel any active subscription. Conversion-job records are anonymized. Continue?')) return;
  document.getElementById('delete-confirm-form').classList.remove('hidden');
  document.getElementById('delete-account-btn').classList.add('hidden');
}

function hideDeleteForm() {
  document.getElementById('delete-confirm-form').classList.add('hidden');
  document.getElementById('delete-account-btn').classList.remove('hidden');
  document.getElementById('delete-status').textContent = '';
}

async function confirmDeleteAccount() {
  const status = document.getElementById('delete-status');
  status.textContent = '';
  const res = await window.FM.authFetch('/api/v1/auth/account', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      password: document.getElementById('delete-confirm-password').value,
      confirm_email: document.getElementById('delete-confirm-email').value,
      confirm_word: document.getElementById('delete-confirm-word').value,
    }),
  });
  if (res.status === 204) {
    // Drop exactly the three keys the app writes (see privacy.html §6).
    localStorage.removeItem('fm_access_token');
    localStorage.removeItem('fm_refresh_token');
    localStorage.removeItem('filemorph_api_key');
    window.location.href = '/account-deleted';
    return;
  }
  if (res.status === 401) { window.location.href = '/login'; return; }
  if (res.status === 400 || res.status === 422) { status.textContent = status.dataset.err400; return; }
  if (res.status === 409) { status.textContent = status.dataset.err409; return; }
  status.textContent = status.dataset.err500;
}

document.addEventListener('DOMContentLoaded', function () {
  loadUser();
  loadKeys();
  document.getElementById('create-key-btn').addEventListener('click', createKey);
  document.getElementById('copy-key-btn').addEventListener('click', copyKey);
  const langSel = document.getElementById('email-lang');
  if (langSel) langSel.addEventListener('change', function (e) { saveEmailLang(e.target.value); });
  document.getElementById('delete-account-btn').addEventListener('click', showDeleteForm);
  document.getElementById('delete-cancel-btn').addEventListener('click', hideDeleteForm);
  document.getElementById('delete-confirm-submit').addEventListener('click', confirmDeleteAccount);
});

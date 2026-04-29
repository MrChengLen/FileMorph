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
}

async function loadKeys() {
  const res = await window.FM.authFetch('/api/v1/keys');
  if (!res.ok) return;
  const keys = await res.json();
  const list = document.getElementById('keys-list');
  if (keys.length === 0) {
    list.innerHTML = '<p class="text-sm text-gray-500">No API keys yet. Create one above.</p>';
    return;
  }
  list.innerHTML = keys.map(function (k) {
    return '<div class="flex items-center justify-between gap-3 bg-gray-800 rounded-xl px-4 py-3">' +
      '<div class="min-w-0">' +
      '<p class="text-sm font-medium truncate">' + k.label + '</p>' +
      '<p class="text-xs text-gray-500">Created ' + new Date(k.created_at).toLocaleDateString('de-DE') +
      (k.last_used_at ? ' \u00b7 Last used ' + new Date(k.last_used_at).toLocaleDateString('de-DE') : ' \u00b7 Never used') + '</p>' +
      '</div>' +
      '<button data-revoke-id="' + k.id + '" class="shrink-0 text-xs text-red-400 hover:text-red-300 px-3 py-1.5 rounded-lg border border-red-900 hover:border-red-700 transition-colors">Revoke</button>' +
      '</div>';
  }).join('');
  list.querySelectorAll('[data-revoke-id]').forEach(function (btn) {
    btn.addEventListener('click', function () { revokeKey(btn.dataset.revokeId); });
  });
}

async function createKey() {
  const btn = document.getElementById('create-key-btn');
  btn.disabled = true;
  btn.textContent = 'Creating\u2026';
  const res = await window.FM.authFetch('/api/v1/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: 'My API Key' }),
  });
  btn.disabled = false;
  btn.textContent = '+ New Key';
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById('new-key-value').textContent = data.key;
  document.getElementById('new-key-box').classList.remove('hidden');
  loadKeys();
}

async function revokeKey(id) {
  if (!confirm('Revoke this API key? This cannot be undone.')) return;
  await window.FM.authFetch('/api/v1/keys/' + id, { method: 'DELETE' });
  loadKeys();
}

function copyKey() {
  var val = document.getElementById('new-key-value').textContent;
  navigator.clipboard.writeText(val).then(function () {
    var btn = document.getElementById('copy-key-btn');
    btn.textContent = 'Copied!';
    setTimeout(function () { btn.textContent = 'Copy'; }, 2000);
  });
}

document.addEventListener('DOMContentLoaded', function () {
  loadUser();
  loadKeys();
  document.getElementById('create-key-btn').addEventListener('click', createKey);
  document.getElementById('copy-key-btn').addEventListener('click', copyKey);
});

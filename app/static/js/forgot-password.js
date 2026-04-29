// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('send-btn').addEventListener('click', doReset);
  document.addEventListener('keydown', function (e) { if (e.key === 'Enter') doReset(); });
});

async function doReset() {
  const btn = document.getElementById('send-btn');
  const email = document.getElementById('email').value.trim();
  btn.disabled = true;
  btn.textContent = 'Sending\u2026';
  await fetch('/api/v1/auth/forgot-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  document.getElementById('form-section').classList.add('hidden');
  document.getElementById('success-msg').classList.remove('hidden');
}

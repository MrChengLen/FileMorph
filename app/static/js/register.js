// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('reg-btn').addEventListener('click', doRegister);
  document.addEventListener('keydown', function (e) { if (e.key === 'Enter') doRegister(); });
});

async function doRegister() {
  const btn = document.getElementById('reg-btn');
  const err = document.getElementById('error-msg');
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const password2 = document.getElementById('password2').value;
  err.classList.add('hidden');
  if (password.length < 8) { err.textContent = 'Password must be at least 8 characters.'; err.classList.remove('hidden'); return; }
  if (password !== password2) { err.textContent = 'Passwords do not match.'; err.classList.remove('hidden'); return; }
  btn.disabled = true;
  btn.textContent = 'Creating account\u2026';
  try {
    const res = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { throw new Error(data.detail || 'Registration failed.'); }
    localStorage.setItem('fm_access_token', data.access_token);
    localStorage.setItem('fm_refresh_token', data.refresh_token);
    window.location.href = '/dashboard';
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Create Account';
  }
}

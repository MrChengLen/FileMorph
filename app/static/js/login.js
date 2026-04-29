// SPDX-License-Identifier: AGPL-3.0-or-later
async function doLogin() {
  const btn = document.getElementById('login-btn');
  const err = document.getElementById('error-msg');
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  err.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Signing in\u2026';
  try {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { throw new Error(data.detail || 'Login failed.'); }
    localStorage.setItem('fm_access_token', data.access_token);
    localStorage.setItem('fm_refresh_token', data.refresh_token);
    window.location.href = '/dashboard';
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Sign In';
  }
}

document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('login-btn').addEventListener('click', doLogin);
  document.addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
});

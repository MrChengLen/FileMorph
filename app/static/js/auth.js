// SPDX-License-Identifier: AGPL-3.0-or-later
(function () {
  'use strict';

  const ACCESS_KEY = 'fm_access_token';
  const REFRESH_KEY = 'fm_refresh_token';

  async function _refresh() {
    const rt = localStorage.getItem(REFRESH_KEY);
    if (!rt) return false;
    try {
      const res = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      localStorage.setItem(ACCESS_KEY, data.access_token);
      localStorage.setItem(REFRESH_KEY, data.refresh_token);
      return true;
    } catch { return false; }
  }

  async function authFetch(url, opts = {}) {
    const token = localStorage.getItem(ACCESS_KEY);
    if (!token) return new Response('{"detail":"Not authenticated."}', { status: 401 });
    const headers = { ...(opts.headers || {}), Authorization: `Bearer ${token}` };
    let res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
      const ok = await _refresh();
      if (ok) {
        headers.Authorization = `Bearer ${localStorage.getItem(ACCESS_KEY)}`;
        res = await fetch(url, { ...opts, headers });
      } else {
        localStorage.removeItem(ACCESS_KEY);
        localStorage.removeItem(REFRESH_KEY);
      }
    }
    return res;
  }

  async function getUser() {
    if (!localStorage.getItem(ACCESS_KEY)) return null;
    try {
      const res = await authFetch('/api/v1/auth/me');
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }

  function logout() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    window.location.href = '/login';
  }

  function _renderNavAuth(user) {
    const desktop = document.getElementById('nav-auth-desktop');
    const mobile = document.getElementById('nav-auth-mobile');
    if (!desktop) return;

    if (user) {
      const initial = user.email[0].toUpperCase();
      desktop.innerHTML = `
        <div class="relative group">
          <button class="w-8 h-8 rounded-full bg-brand flex items-center justify-center font-bold text-white text-xs">${initial}</button>
          <div class="absolute right-0 top-10 w-52 bg-gray-900 border border-gray-700 rounded-xl shadow-xl py-2 invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-all z-50">
            <div class="px-4 py-2 border-b border-gray-700">
              <p class="text-xs text-gray-400 truncate">${user.email}</p>
              <p class="text-xs text-brand capitalize">${user.tier}</p>
            </div>
            <a href="/dashboard" class="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white">Dashboard</a>
            <button data-action="signout" class="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-gray-800">Sign Out</button>
          </div>
        </div>`;
      desktop.querySelector('[data-action="signout"]').addEventListener('click', () => window.FM.logout());
      if (mobile) {
        mobile.innerHTML = `
          <a href="/dashboard" class="block text-gray-400 hover:text-white transition-colors py-1">Dashboard</a>
          <button data-action="signout-mobile" class="block text-red-400 hover:text-white py-1 text-left">Sign Out</button>`;
        mobile.querySelector('[data-action="signout-mobile"]').addEventListener('click', () => window.FM.logout());
      }
    } else {
      desktop.innerHTML = `
        <a href="/login" class="text-sm text-gray-300 hover:text-white transition-colors">Sign In</a>
        <a href="/register" class="text-sm px-4 py-1.5 rounded-lg bg-brand hover:bg-brand-dark text-white font-semibold transition-colors">Register</a>`;
      if (mobile) {
        mobile.innerHTML = `
          <a href="/login" class="block text-gray-400 hover:text-white transition-colors py-1">Sign In</a>
          <a href="/register" class="block text-brand hover:text-white py-1">Register</a>`;
      }
    }
  }

  async function init() {
    const user = await getUser();
    _renderNavAuth(user);
  }

  window.FM = { authFetch, getUser, logout };
  document.addEventListener('DOMContentLoaded', init);
})();

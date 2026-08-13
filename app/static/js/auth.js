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

    const I18N = window.FM_I18N || {};
    const lDashboard = I18N.dashboard || 'Dashboard';
    const lSignOut = I18N.signOut || 'Sign Out';
    const lSignIn = I18N.signIn || 'Sign In';
    const lRegister = I18N.register || 'Register';
    // Keep dynamic nav links in the user's currently-active locale namespace
    // (matches the server-side ``localized_url(..., current_prefix)`` rule
    // in base.html — clicking from /de/x stays in /de/, from /en/x stays
    // in /en/, from no-prefix stays no-prefix).
    const htmlLang = document.documentElement.lang || '';
    const localePrefix = htmlLang.startsWith('en')
      ? '/en'
      : htmlLang.startsWith('de')
        ? '/de'
        : '';

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
            <a href="${localePrefix}/dashboard" class="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white">${lDashboard}</a>
            <button data-action="signout" class="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-gray-800">${lSignOut}</button>
          </div>
        </div>`;
      desktop.querySelector('[data-action="signout"]').addEventListener('click', () => window.FM.logout());
      if (mobile) {
        mobile.innerHTML = `
          <a href="${localePrefix}/dashboard" class="block text-gray-400 hover:text-white transition-colors py-1">${lDashboard}</a>
          <button data-action="signout-mobile" class="block text-red-400 hover:text-white py-1 text-left">${lSignOut}</button>`;
        mobile.querySelector('[data-action="signout-mobile"]').addEventListener('click', () => window.FM.logout());
      }
    } else {
      desktop.innerHTML = `
        <a href="${localePrefix}/login" class="text-sm text-gray-300 hover:text-white transition-colors">${lSignIn}</a>
        <a href="${localePrefix}/register" class="text-sm px-4 py-1.5 rounded-lg bg-brand hover:bg-brand-dark text-white font-semibold transition-colors">${lRegister}</a>`;
      if (mobile) {
        mobile.innerHTML = `
          <a href="${localePrefix}/login" class="block text-gray-400 hover:text-white transition-colors py-1">${lSignIn}</a>
          <a href="${localePrefix}/register" class="block text-brand hover:text-white py-1">${lRegister}</a>`;
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

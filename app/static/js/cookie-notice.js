// SPDX-License-Identifier: AGPL-3.0-or-later
// Informational cookie notice (partials/cookie_notice.html). Deliberately NOT
// a consent dialog: FileMorph sets no cookies, so there is nothing to accept
// or reject — the bar only informs. Dismissal is remembered per browser in
// localStorage so the notice appears exactly once; a cookie here would
// contradict the very claim the notice makes.
document.addEventListener('DOMContentLoaded', function () {
  const KEY = 'fm_cookie_notice_dismissed';
  const notice = document.getElementById('cookie-notice');
  if (!notice) return;
  let dismissed = false;
  try {
    dismissed = localStorage.getItem(KEY) === '1';
  } catch (err) {
    dismissed = false; // storage blocked (e.g. cookies disabled) — never crash
  }
  if (dismissed) return;
  const btn = document.getElementById('cookie-notice-dismiss');
  if (!btn) return; // never reveal a bar that could not be dismissed
  notice.classList.remove('hidden');
  // Reserve the bar's height so it never covers the footer's legal links
  // (Impressum must stay reachable while the bar is up).
  document.body.style.paddingBottom = notice.offsetHeight + 'px';
  btn.addEventListener('click', function () {
    try {
      localStorage.setItem(KEY, '1');
    } catch (err) {
      // storage blocked — still hide for this page view
    }
    notice.classList.add('hidden');
    document.body.style.paddingBottom = '';
  });
});

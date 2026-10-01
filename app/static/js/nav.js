// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('nav-toggle');
  const menu = document.getElementById('nav-mobile-menu');
  // Pages with minimal chrome (/cancel) render neither the toggle nor the menu.
  if (!toggle || !menu) return;
  toggle.addEventListener('click', function () {
    menu.classList.toggle('hidden');
  });
});

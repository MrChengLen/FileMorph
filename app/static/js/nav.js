// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('nav-toggle');
  const menu = document.getElementById('nav-mobile-menu');
  // Pages with minimal chrome (/cancel) render neither the toggle nor the menu.
  if (!toggle || !menu) return;
  function setOpen(open) {
    menu.classList.toggle('hidden', !open);
    toggle.setAttribute('aria-expanded', String(open));
  }
  toggle.addEventListener('click', function () {
    setOpen(menu.classList.contains('hidden'));
  });
  // Escape on the button, inside the menu or on the bare page closes the menu
  // and hands the focus back to its button; a field elsewhere (the /formats
  // search) keeps its own Escape.
  document.addEventListener('keydown', function (e) {
    const fromNav = e.target === toggle || e.target === document.body || menu.contains(e.target);
    if (e.key === 'Escape' && fromNav && !menu.classList.contains('hidden')) {
      setOpen(false);
      toggle.focus();
    }
  });
});

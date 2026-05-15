// SPDX-License-Identifier: AGPL-3.0-or-later
// /contact form — anonymous POST to /api/v1/contact (no auth header).
// Outcome surfaced via the aria-live #contact-status region using
// localized strings carried on its data-* attributes.
document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('contact-form');
  if (!form) return;
  const status = document.getElementById('contact-status');
  const submit = document.getElementById('contact-submit');

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    status.textContent = '';
    const payload = {
      name: (document.getElementById('name')?.value || '').trim(),
      email: (document.getElementById('email')?.value || '').trim(),
      subject: (document.getElementById('subject')?.value || '').trim(),
      message: (document.getElementById('message')?.value || '').trim(),
      website: (document.getElementById('cf-website')?.value || ''),
    };
    if (submit) submit.disabled = true;
    try {
      const res = await fetch('/api/v1/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        status.textContent = status.dataset.ok;
        form.reset();
        // Leave the form in place; the aria-live confirmation is enough.
        // Keep the submit disabled so a stray double-click can't re-send.
      } else if (res.status === 429) {
        status.textContent = status.dataset.err429;
        if (submit) submit.disabled = false;
      } else if (res.status === 400 || res.status === 422) {
        status.textContent = status.dataset.err400;
        if (submit) submit.disabled = false;
      } else {
        status.textContent = status.dataset.err500;
        if (submit) submit.disabled = false;
      }
    } catch (err) {
      status.textContent = status.dataset.err500;
      if (submit) submit.disabled = false;
    }
  });

  // Convenience: pre-fill the email for a signed-in user. window.FM is
  // exposed by auth.js (always loaded); anonymous visitors see an empty
  // field.
  const u = window.FM && typeof window.FM.getUser === 'function' ? window.FM.getUser() : null;
  if (u && u.email) {
    const emailEl = document.getElementById('email');
    if (emailEl && !emailEl.value) emailEl.value = u.email;
  }
});

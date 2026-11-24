// SPDX-License-Identifier: AGPL-3.0-or-later
// /contact form — anonymous POST to /api/v1/contact (no auth header).
// Outcome shown in the #contact-status notice box (inside an aria-live
// region) using localized strings carried on its data-* attributes; the
// box's tone says whether the message went out (ok) or not (err).
document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('contact-form');
  if (!form) return;
  const status = document.getElementById('contact-status');
  const submit = document.getElementById('contact-submit');
  // "Write an email instead" (only rendered when the operator has an address).
  const mailto = document.getElementById('contact-mailto');
  const mailtoBase = mailto ? mailto.getAttribute('href') : '';
  // The errors where the form itself cannot deliver: too many attempts, a
  // server error, no mail set up on this server. (A 400 means: fix the form.)
  const MAILTO_CODES = [429, 500, 503];
  // The whole mailto link stays under this many characters: Windows mail
  // programs refuse links past about 2,000.
  const MAILTO_LINK_MAX = 1800;
  const ELLIPSIS = encodeURIComponent('…');

  // text URI-encoded by whole characters while it fits in room (for...of walks
  // code points; a cut through an emoji would make encodeURIComponent throw),
  // ending in "…" when cut.
  function encodeWithin(text, room) {
    let out = '';
    for (const ch of text) {
      const next = out + encodeURIComponent(ch);
      if (next.length > room) return out + ELLIPSIS;
      out = next;
    }
    return out;
  }

  // The link for what the visitor has typed right now: subject and message,
  // URI-encoded onto the server-rendered mailto: address. Each part gets the
  // room the parts before it leave, with space kept for the "…" of a cut, so
  // the whole link stays under MAILTO_LINK_MAX. Line breaks are CRLF (RFC 6068).
  function mailtoHref() {
    const subject = (document.getElementById('subject')?.value || '').trim();
    const message = (document.getElementById('message')?.value || '').trim().replace(/\r?\n/g, '\r\n');
    let href = mailtoBase;
    let sep = '?';
    for (const [key, text] of [['subject', subject], ['body', message]]) {
      const head = sep + key + '=';
      const room = MAILTO_LINK_MAX - href.length - head.length - ELLIPSIS.length;
      if (!text || room <= 0) continue;
      href += head + encodeWithin(text, room);
      sep = '&';
    }
    return href;
  }

  // Rebuilt on click too, so edits made after the error reach the mail.
  if (mailto) mailto.addEventListener('click', function () { mailto.setAttribute('href', mailtoHref()); });

  // Hand what the visitor typed to their own mail program.
  function offerMail() {
    if (!mailto) return;
    mailto.setAttribute('href', mailtoHref());
    mailto.classList.remove('hidden');
  }

  function showStatus(text, tone) {
    status.dataset.tone = tone;
    status.textContent = text;
    status.classList.remove('hidden');
  }

  // The error texts sit on #contact-status as data-err-NNN. Read them with
  // getAttribute, as cancel.js does: dataset only camel-cases a dash before a
  // letter, so data-err-400 is dataset['err-400'] and dataset.err400 would be
  // undefined (the error messages used to show no text at all).
  function showError(code) {
    showStatus(status.getAttribute('data-err-' + code) || status.getAttribute('data-err-500'), 'err');
    if (submit) {
      submit.disabled = false;
      submit.focus();
    }
    if (MAILTO_CODES.includes(code)) offerMail();
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    status.classList.add('hidden');
    status.textContent = '';
    if (mailto) mailto.classList.add('hidden');
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
        showStatus(status.dataset.ok, 'ok');
        form.reset();
        // Leave the form in place; the aria-live confirmation is enough.
        // Keep the submit disabled so a stray double-click can't re-send.
      } else if (res.status === 429) {
        showError(429);
      } else if (res.status === 400 || res.status === 422) {
        showError(400);
      } else if (res.status === 503) {
        showError(503);
      } else {
        showError(500);
      }
    } catch (err) {
      showError(500);
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

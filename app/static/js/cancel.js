// SPDX-License-Identifier: AGPL-3.0-or-later
// /cancel — § 312k BGB online cancellation ("Kündigungsbutton"). Anonymous POST
// to /api/v1/billing/cancellation (no auth header). The outcome is either the
// on-page receipt (server timestamp + summary + print button) or a localized
// error in the aria-live #cancel-status region. Every user-visible string comes
// from data-* attributes rendered server-side (same pattern as contact.js);
// values are written with textContent only, never parsed as HTML.
document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('cancel-form');
  if (!form) return;

  const REASON_MAX = 1000; // mirrors the API's length limit for `reason`
  const f = form.elements;
  const request = document.getElementById('cancel-request');
  const status = document.getElementById('cancel-status');
  const submit = document.getElementById('cancel-submit');
  const reasonWrap = document.getElementById('cancel-reason-wrap');
  const dateWrap = document.getElementById('cancel-date-wrap');
  const receipt = document.getElementById('cancel-receipt');

  const lang = (document.documentElement.lang || 'de').toLowerCase().startsWith('en') ? 'en' : 'de';
  const dateLocale = lang === 'en' ? 'en-GB' : 'de-DE';
  let inFlight = false;
  let contractChosen = false; // the visitor picked a contract themselves

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  // Local calendar day as YYYY-MM-DD (toISOString() would give the UTC day).
  function localIsoDay(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  // Function replacement on purpose: with a string, "$&" and friends inside a
  // user-typed email would be expanded by String.replace.
  function fill(template, token, value) {
    return template.replace(token, function () { return value; });
  }

  function checkedInput(name) {
    return form.querySelector('input[name="' + name + '"]:checked');
  }

  function labelText(input) {
    return input.closest('label').textContent.replace(/\s+/g, ' ').trim();
  }

  function formatDateTime(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    // No dateStyle here: some engines throw when it is combined with timeZoneName.
    return d.toLocaleString(dateLocale, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    });
  }

  function formatDay(iso) {
    const p = iso.split('-').map(Number);
    const d = new Date(p[0], p[1] - 1, p[2]); // local date, no UTC day shift
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(dateLocale, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  // Reason / end date are only part of the request while their option is selected.
  function syncFields() {
    const extraordinary = f.kind.value === 'extraordinary';
    const onDate = f.end.value === 'date';
    reasonWrap.classList.toggle('hidden', !extraordinary);
    dateWrap.classList.toggle('hidden', !onDate);
    // A hidden date field must neither block the submit nor be sent.
    f.end_date.disabled = !onDate;
    f.end_date.required = onDate;
  }

  f.reason.maxLength = REASON_MAX;
  f.end_date.min = localIsoDay(new Date());
  form.addEventListener('change', function (e) {
    if (e.target.name === 'contract') contractChosen = true;
    syncFields();
  });
  syncFields();

  // Snapshot of what is sent, taken once at submit time: the receipt must show
  // exactly the declaration that went out, not whatever the form holds later.
  function readForm() {
    const contract = checkedInput('contract');
    const kind = checkedInput('kind');
    const end = checkedInput('end');
    const extraordinary = kind.value === 'extraordinary';
    const onDate = end.value === 'date';
    return {
      payload: {
        email: f.email.value.trim(),
        contract: contract.value,
        kind: kind.value,
        reason: extraordinary ? f.reason.value.trim() : '',
        end: end.value,
        end_date: onDate ? f.end_date.value : null,
        website: f.website.value,
      },
      contractLabel: labelText(contract),
      kindLabel: labelText(kind),
    };
  }

  function showReceipt(sent, data) {
    const p = sent.payload;
    const field = function (name) { return receipt.querySelector('[data-field="' + name + '"]'); };
    field('email').textContent = p.email;
    field('contract').textContent = sent.contractLabel;
    field('kind').textContent = sent.kindLabel;
    field('reason').textContent = p.reason;
    document.getElementById('cancel-receipt-reason-row').classList.toggle('hidden', p.reason === '');
    field('end').textContent = p.end === 'date' ? formatDay(p.end_date) : field('end').dataset.endEarliest;

    const time = document.getElementById('cancel-receipt-time');
    time.textContent = fill(time.dataset.template, '{datetime}', formatDateTime(data.received_at));
    const mail = document.getElementById('cancel-receipt-email');
    mail.textContent = data.email_sent === true
      ? fill(mail.dataset.sent, '{email}', p.email)
      : mail.dataset.notSent;

    request.classList.add('hidden');
    receipt.classList.remove('hidden');
    document.getElementById('cancel-receipt-title').focus();
  }

  // The error texts sit on #cancel-status as data-err-NNN. Read them with
  // getAttribute: dataset only camel-cases a dash before a LETTER, so
  // data-err-422 is dataset['err-422'] and dataset.err422 would be undefined.
  // Only 422 / 429 / 503 have their own text; any other status gets the 500 one.
  function errText(code) {
    return status.getAttribute('data-err-' + code) || status.getAttribute('data-err-500');
  }

  function fail(text) {
    status.textContent = text;
    inFlight = false;
    submit.disabled = false;
    submit.focus();
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (inFlight) return;
    status.textContent = '';
    // Browser constraint check (works with novalidate, shows no native bubble):
    // required email, and a chosen end date that is not before today.
    if (!form.checkValidity()) {
      status.textContent = errText(422);
      const invalid = form.querySelector('input:invalid, textarea:invalid');
      if (invalid) invalid.focus();
      return;
    }
    inFlight = true;
    submit.disabled = true;
    try {
      const sent = readForm();
      const res = await fetch('/api/v1/billing/cancellation?lang=' + encodeURIComponent(lang), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sent.payload),
      });
      if (res.ok) {
        const data = await res.json();
        // Only a body with the server's receipt time counts as received; a 200
        // that is not our API's JSON (captive portal, proxy) must not read as success.
        if (data && typeof data.received_at === 'string') {
          showReceipt(sent, data);
          return;
        }
        fail(errText(500));
      } else {
        fail(errText(res.status));
      }
    } catch (err) {
      fail(errText(500));
    }
  });

  document.getElementById('cancel-print').addEventListener('click', function () {
    window.print();
  });

  // Convenience: pre-fill a signed-in user's email and plan. window.FM comes
  // from auth.js (loaded after this file, so it exists by DOMContentLoaded);
  // getUser() is async and resolves to null for anonymous visitors. Runs last so
  // a slow /me call never delays the wiring above, and never overwrites input.
  async function prefill() {
    if (!window.FM || typeof window.FM.getUser !== 'function') return;
    const u = await window.FM.getUser();
    if (!u) return;
    if (u.email && !f.email.value) f.email.value = u.email;
    if (u.tier === 'business' && !contractChosen) {
      const business = form.querySelector('input[name="contract"][value="business"]');
      if (business) business.checked = true;
    }
  }
  prefill().catch(function () { /* prefill is best-effort */ });
});

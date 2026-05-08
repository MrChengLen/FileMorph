// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', () => {
  // Wire withdrawal-waiver checkboxes to enable/disable their target buttons.
  // The checkbox + button pair represents an explicit two-step §356 (5) BGB
  // consent: the button stays disabled until the user actively ticks the
  // waiver box. The `data-target` attribute names the button id.
  document.querySelectorAll('.withdrawal-waiver').forEach((cb) => {
    const targetId = cb.dataset.target;
    const btn = document.getElementById(targetId);
    if (!btn) return;
    cb.addEventListener('change', () => {
      btn.disabled = !cb.checked;
    });
  });

  const proBtn = document.getElementById('pro-btn');
  const bizBtn = document.getElementById('business-btn');
  if (proBtn) proBtn.addEventListener('click', () => upgrade('pro'));
  if (bizBtn) bizBtn.addEventListener('click', () => upgrade('business'));
});

async function upgrade(tier) {
  const token = localStorage.getItem('fm_access_token');
  if (!token) {
    window.location.href = '/register?next=pricing';
    return;
  }
  const waiver = document.getElementById(tier + '-waiver');
  if (!waiver || !waiver.checked) {
    // The button shouldn't be clickable without the checkbox, but guard
    // anyway in case the markup or DOM is altered.
    return;
  }
  const btn = document.getElementById(tier + '-btn');
  btn.disabled = true;
  btn.textContent = 'Redirecting…';
  try {
    const res = await window.FM.authFetch('/api/v1/billing/checkout/' + tier, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ withdrawal_waiver_acknowledged: true }),
    });
    if (res.status === 503) {
      btn.disabled = false;
      btn.textContent = tier === 'pro' ? 'Upgrade to Pro' : 'Upgrade to Business';
      alert('Payments are not yet active. Please check back soon.');
      return;
    }
    const data = await res.json();
    if (data.url) window.location.href = data.url;
  } catch (e) {
    btn.disabled = false;
    btn.textContent = tier === 'pro' ? 'Upgrade to Pro' : 'Upgrade to Business';
  }
}

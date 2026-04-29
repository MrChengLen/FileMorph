// SPDX-License-Identifier: AGPL-3.0-or-later
document.addEventListener('DOMContentLoaded', () => {
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
  var btn = document.getElementById(tier + '-btn');
  btn.disabled = true;
  btn.textContent = 'Redirecting\u2026';
  try {
    var res = await window.FM.authFetch('/api/v1/billing/checkout/' + tier, { method: 'POST' });
    if (res.status === 503) {
      btn.disabled = false;
      btn.textContent = tier === 'pro' ? 'Upgrade to Pro' : 'Upgrade to Business';
      alert('Payments are not yet active. Please check back soon.');
      return;
    }
    var data = await res.json();
    if (data.url) window.location.href = data.url;
  } catch (e) {
    btn.disabled = false;
    btn.textContent = tier === 'pro' ? 'Upgrade to Pro' : 'Upgrade to Business';
  }
}

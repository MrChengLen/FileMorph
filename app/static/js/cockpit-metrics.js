// SPDX-License-Identifier: AGPL-3.0-or-later
// S10-lite: Anonymous Analytics widget on the admin cockpit.
//
// Renders three counter cards (page views, conversions, registrations) with
// SVG sparklines, plus the top-format-pairs list and the today failure-rate
// indicator. Data source: `/api/v1/cockpit/usage-summary?days=N`. Uses
// vanilla SVG instead of Chart.js for the sparklines — they're tiny enough
// (40px tall) that the 70 KB bundle would dwarf the value. The Chart.js
// instance for the signups line-chart on this page is unaffected.
//
// Boot order (matters for non-admin users):
//   1. cockpit.js verifies the JWT and either reveals #ck-dashboard (admin)
//      or shows #ck-forbidden (non-admin) — we attach a MutationObserver to
//      catch the moment the dashboard becomes visible.
//   2. Range buttons + first fetch are bound only AFTER the dashboard
//      appears. A non-admin therefore never wires up the listeners and the
//      forbidden /cockpit/usage-summary call (which would 403) is skipped.
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { days: 7, bound: false };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Build a sparkline path from an array of {date, count}. Width 200, height
  // 40, 2px stroke. Empty/zero arrays render a flat midline so the card
  // never looks broken. Each data point also renders an invisible larger
  // hit-circle with a native <title> tooltip — hovering the line reveals
  // the date+count without needing a JS popup library.
  function sparkline(series, color) {
    const w = 200, h = 40, pad = 2;
    if (!series || series.length === 0) {
      return `<svg viewBox="0 0 ${w} ${h}" class="w-full h-10" aria-hidden="true"><line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="#374151" stroke-width="1"/></svg>`;
    }
    const values = series.map((p) => p.count);
    const maxV = Math.max(...values, 1);
    const stepX = (w - pad * 2) / Math.max(series.length - 1, 1);
    const coords = series.map((p, i) => {
      const x = pad + i * stepX;
      const y = h - pad - ((p.count / maxV) * (h - pad * 2));
      return { x, y, p };
    });
    const points = coords.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    // Hit-circles 4px radius (transparent fill) with native tooltip. We don't
    // render visible dots — too noisy on a 40px-tall chart — but the larger
    // hit area keeps mouse-precision forgiving.
    const dots = coords
      .map(
        ({ x, y, p }) =>
          `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="transparent" stroke="none"><title>${escapeHtml(p.date)}: ${p.count.toLocaleString()}</title></circle>`,
      )
      .join('');
    return `<svg viewBox="0 0 ${w} ${h}" class="w-full h-10" preserveAspectRatio="none" role="img" aria-label="Sparkline chart"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>${dots}</svg>`;
  }

  function card(label, value, series, color) {
    return `
      <div class="bg-gray-950 border border-gray-800 rounded-xl p-4">
        <p class="text-xs text-gray-500 uppercase tracking-wider">${escapeHtml(label)}</p>
        <p class="text-3xl font-bold mt-1 ${color}">${value.toLocaleString()}</p>
        <div class="mt-3">${sparkline(series, color === 'text-brand' ? '#6366f1' : color === 'text-emerald-400' ? '#34d399' : '#9ca3af')}</div>
        <p class="text-[10px] text-gray-600 mt-1">last ${state.days} d</p>
      </div>`;
  }

  function renderPairs(pairs) {
    if (!pairs || pairs.length === 0) {
      const label = (window.FM_I18N && window.FM_I18N.noConversionsYet) || 'No conversions yet.';
      $('metrics-pairs').innerHTML = '<li class="text-xs text-gray-500">' + label + '</li>';
      return;
    }
    $('metrics-pairs').innerHTML = pairs
      .map(
        (p, i) => `
        <li class="flex items-center justify-between">
          <span class="text-gray-400">${i + 1}.</span>
          <span class="font-mono text-xs flex-1 mx-2">${escapeHtml(p.pair)}</span>
          <span class="text-gray-300 font-semibold">${p.count.toLocaleString()}</span>
        </li>`,
      )
      .join('');
  }

  function renderFailureRate(rate, sampleSize) {
    const el = $('metrics-failure-rate');
    const hint = $('metrics-failure-hint');
    if (rate === null || rate === undefined) {
      el.textContent = '—';
      el.className = 'text-3xl font-bold mt-1 text-gray-500';
      // Distinguish "no traffic" from "too little traffic to be meaningful".
      // The endpoint returns null + a sample_size for both, so we read the
      // count to pick the right user-facing copy.
      if (sampleSize && sampleSize > 0) {
        hint.textContent = `Only ${sampleSize} outcome${sampleSize === 1 ? '' : 's'} today — too few to compute a rate.`;
      } else {
        hint.textContent = (window.FM_I18N && window.FM_I18N.noJobsToday) || 'No conversion or compression jobs today yet.';
      }
      return;
    }
    const pct = (rate * 100).toFixed(1);
    el.textContent = pct + ' %';
    if (rate < 0.01) el.className = 'text-3xl font-bold mt-1 text-emerald-400';
    else if (rate < 0.05) el.className = 'text-3xl font-bold mt-1 text-yellow-400';
    else el.className = 'text-3xl font-bold mt-1 text-red-400';
    hint.textContent = sampleSize ? `n=${sampleSize} today` : '';
  }

  function showError() {
    $('metrics-error').classList.remove('hidden');
    $('metrics-grid').setAttribute('aria-busy', 'false');
    $('metrics-grid').innerHTML = '';
  }

  function hideError() {
    $('metrics-error').classList.add('hidden');
  }

  async function loadMetrics() {
    if (!window.FM || !window.FM.authFetch) return;
    let res;
    try {
      res = await window.FM.authFetch(`/api/v1/cockpit/usage-summary?days=${state.days}`);
    } catch (e) {
      // Network-layer failure — surface so admin knows the call never reached
      // the server (firewall, offline, DNS).
      showError();
      return;
    }
    if (res.status === 401 || res.status === 403) {
      // Auth went stale or admin was demoted between page load and now.
      // Don't render — cockpit.js will redirect the user shortly.
      return;
    }
    if (!res.ok) {
      // 5xx or unexpected status — admin needs to know the metrics pipeline
      // is broken instead of seeing silently empty cards.
      showError();
      return;
    }
    let data;
    try {
      data = await res.json();
    } catch (e) {
      showError();
      return;
    }
    hideError();

    if (data.metrics_enabled === false) {
      $('metrics-disabled').classList.remove('hidden');
      $('metrics-grid').innerHTML = '';
      $('metrics-grid').setAttribute('aria-busy', 'false');
      $('metrics-extras').classList.add('hidden');
      return;
    }
    $('metrics-disabled').classList.add('hidden');
    $('metrics-extras').classList.remove('hidden');

    const t = data.totals || { page_views: 0, conversions: 0, registrations: 0 };
    $('metrics-grid').innerHTML = [
      card('Page views', t.page_views, data.page_views_series, 'text-white'),
      card('Conversions', t.conversions, data.conversions_series, 'text-brand'),
      card('Registrations', t.registrations, data.registrations_series, 'text-emerald-400'),
    ].join('');
    $('metrics-grid').setAttribute('aria-busy', 'false');
    renderPairs(data.top_format_pairs);
    renderFailureRate(data.failure_rate_today, data.failure_sample_size);
  }

  function highlightActiveRange() {
    document.querySelectorAll('.ck-mrange').forEach((b) => {
      const active = parseInt(b.dataset.days, 10) === state.days;
      b.classList.toggle('border-brand', active);
      b.classList.toggle('text-white', active);
      b.classList.toggle('text-gray-400', !active);
      // a11y: signal the active state to screen readers in addition to the
      // visual border-color change.
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function attachRangeButtons() {
    if (state.bound) return;
    state.bound = true;
    document.querySelectorAll('.ck-mrange').forEach((b) => {
      b.addEventListener('click', () => {
        state.days = parseInt(b.dataset.days, 10) || 7;
        highlightActiveRange();
        loadMetrics();
      });
    });
    highlightActiveRange();
  }

  // Wait for the dashboard to actually become visible (cockpit.js gates it
  // behind the role=admin check). Polling beats refactoring cockpit.js for
  // an event hook this small. The observer is one-shot — once the dashboard
  // appears we wire up the buttons + first fetch, then disconnect. A
  // non-admin user never reaches the cb so range buttons stay inert and we
  // never make a /usage-summary call we know would 403.
  function whenDashboardReady(cb) {
    const dash = document.getElementById('ck-dashboard');
    if (!dash) return;
    if (!dash.classList.contains('hidden')) {
      cb();
      return;
    }
    const obs = new MutationObserver(() => {
      if (!dash.classList.contains('hidden')) {
        obs.disconnect();
        cb();
      }
    });
    obs.observe(dash, { attributes: true, attributeFilter: ['class'] });
  }

  document.addEventListener('DOMContentLoaded', () => {
    whenDashboardReady(() => {
      attachRangeButtons();
      loadMetrics();
    });
  });
})();

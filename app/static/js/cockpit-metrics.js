// SPDX-License-Identifier: AGPL-3.0-or-later
// S10-lite: Anonymous Analytics widget on the admin cockpit.
//
// Renders three counter cards (page views, conversions, registrations) with
// SVG sparklines, plus the top-format-pairs list and the 24h failure-rate
// indicator. Data source: `/api/v1/cockpit/usage-summary?days=N`. Uses
// vanilla SVG instead of Chart.js for the sparklines — they're tiny enough
// (40px tall) that the 70 KB bundle would dwarf the value. The Chart.js
// instance for the signups line-chart on this page is unaffected.
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { days: 7 };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Build a sparkline path from an array of {date, count}. Width 200, height
  // 40, 2px stroke. Empty/zero arrays render a flat midline so the card
  // never looks broken.
  function sparkline(series, color) {
    const w = 200, h = 40, pad = 2;
    if (!series || series.length === 0) {
      return `<svg viewBox="0 0 ${w} ${h}" class="w-full h-10"><line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="#374151" stroke-width="1"/></svg>`;
    }
    const values = series.map((p) => p.count);
    const maxV = Math.max(...values, 1);
    const stepX = (w - pad * 2) / Math.max(series.length - 1, 1);
    const points = series
      .map((p, i) => {
        const x = pad + i * stepX;
        const y = h - pad - ((p.count / maxV) * (h - pad * 2));
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
    return `<svg viewBox="0 0 ${w} ${h}" class="w-full h-10" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
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
      $('metrics-pairs').innerHTML = '<li class="text-xs text-gray-500">No conversions yet.</li>';
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

  function renderFailureRate(rate) {
    const el = $('metrics-failure-rate');
    const hint = $('metrics-failure-hint');
    if (rate === null || rate === undefined) {
      el.textContent = '—';
      el.className = 'text-3xl font-bold mt-1 text-gray-500';
      hint.textContent = 'No jobs in the last 24 hours.';
      return;
    }
    const pct = (rate * 100).toFixed(1);
    el.textContent = pct + ' %';
    if (rate < 0.01) el.className = 'text-3xl font-bold mt-1 text-emerald-400';
    else if (rate < 0.05) el.className = 'text-3xl font-bold mt-1 text-yellow-400';
    else el.className = 'text-3xl font-bold mt-1 text-red-400';
    hint.textContent = '';
  }

  async function loadMetrics() {
    if (!window.FM || !window.FM.authFetch) return;
    const res = await window.FM.authFetch(`/api/v1/cockpit/usage-summary?days=${state.days}`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.metrics_enabled === false) {
      $('metrics-disabled').classList.remove('hidden');
      $('metrics-grid').innerHTML = '';
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
    renderPairs(data.top_format_pairs);
    renderFailureRate(data.failure_rate_24h);
  }

  function highlightActiveRange() {
    document.querySelectorAll('.ck-mrange').forEach((b) => {
      const active = parseInt(b.dataset.days, 10) === state.days;
      b.classList.toggle('border-brand', active);
      b.classList.toggle('text-white', active);
      b.classList.toggle('text-gray-400', !active);
    });
  }

  function attachRangeButtons() {
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
  // an event hook this small.
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
    attachRangeButtons();
    whenDashboardReady(loadMetrics);
  });
})();

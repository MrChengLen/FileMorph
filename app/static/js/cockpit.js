// SPDX-License-Identifier: AGPL-3.0-or-later
// Admin cockpit — requires JWT + role=admin. Uses window.FM.authFetch from auth.js.
(function () {
  'use strict';

  const TIER_COLOR = {
    free: 'text-gray-400',
    pro: 'text-brand',
    business: 'text-emerald-400',
    enterprise: 'text-yellow-400',
  };
  const ROLE_COLOR = {
    user: 'text-gray-400',
    admin: 'text-yellow-400',
  };

  const state = {
    me: null,
    page: 1,
    limit: 25,
    total: 0,
    range: 30,
    chart: null,
  };

  const $ = (id) => document.getElementById(id);

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function showForbidden() {
    $('ck-loading').classList.add('hidden');
    $('ck-dashboard').classList.add('hidden');
    $('ck-forbidden').classList.remove('hidden');
  }

  function showDashboard() {
    $('ck-loading').classList.add('hidden');
    $('ck-forbidden').classList.add('hidden');
    $('ck-dashboard').classList.remove('hidden');
  }

  async function loadStats() {
    const res = await window.FM.authFetch('/api/v1/cockpit/stats');
    if (!res.ok) return;
    const s = await res.json();
    const cards = [
      { label: 'Total users', value: s.users.total, color: 'text-white' },
      { label: 'Active 24 h', value: s.active_24h, color: 'text-emerald-400' },
      { label: 'Signups 7 d', value: s.signups_7d, color: 'text-brand' },
      { label: 'Operations', value: s.operations_total, color: 'text-white' },
      { label: 'Failures 24 h', value: s.failed_24h, color: s.failed_24h > 0 ? 'text-red-400' : 'text-gray-400' },
    ];
    $('stats-grid').innerHTML = cards
      .map(
        (c) => `
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p class="text-xs text-gray-500 uppercase tracking-wider">${escapeHtml(c.label)}</p>
          <p class="text-3xl font-bold mt-1 ${c.color}">${c.value.toLocaleString()}</p>
        </div>`,
      )
      .join('');
  }

  async function loadChart(days) {
    const to = new Date();
    const from = new Date(to.getTime() - days * 86400000);
    const bucket = days <= 14 ? 'day' : days <= 60 ? 'day' : 'week';
    const url = `/api/v1/cockpit/timeseries?metric=signups&bucket=${bucket}&from=${from.toISOString()}&to=${to.toISOString()}`;
    const res = await window.FM.authFetch(url);
    if (!res.ok) return;
    const data = await res.json();
    const labels = data.points.map((p) => p.t);
    const values = data.points.map((p) => p.v);

    const ctx = $('signups-chart').getContext('2d');
    if (state.chart) state.chart.destroy();
    // eslint-disable-next-line no-undef
    state.chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: `Signups per ${bucket}`,
            data: values,
            borderColor: '#6366f1',
            backgroundColor: 'rgba(99, 102, 241, 0.2)',
            fill: true,
            tension: 0.3,
            pointRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: '#1f2937' } },
          y: { ticks: { color: '#6b7280', precision: 0 }, grid: { color: '#1f2937' }, beginAtZero: true },
        },
        plugins: { legend: { labels: { color: '#9ca3af' } } },
      },
    });
  }

  function buildUsersQuery() {
    const q = $('users-q').value.trim();
    const tier = $('users-tier').value;
    const role = $('users-role').value;
    const active = $('users-active').value;
    const params = new URLSearchParams();
    params.set('page', String(state.page));
    params.set('limit', String(state.limit));
    if (q) params.set('q', q);
    if (tier) params.set('tier', tier);
    if (role) params.set('role', role);
    if (active) params.set('is_active', active);
    return '/api/v1/cockpit/users?' + params.toString();
  }

  async function loadUsers() {
    const res = await window.FM.authFetch(buildUsersQuery());
    if (!res.ok) return;
    const data = await res.json();
    state.total = data.total;
    renderUsers(data.items);
    renderPagination();
  }

  function renderUsers(items) {
    $('user-count').textContent = `(${state.total.toLocaleString()})`;
    const tbody = $('users-tbody');
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-600">No users match these filters.</td></tr>';
      return;
    }
    tbody.innerHTML = items
      .map((u) => {
        const isSelf = state.me && u.id === state.me.id;
        return `
          <tr class="hover:bg-gray-800/50 transition-colors" data-uid="${u.id}">
            <td class="px-6 py-3 font-mono text-xs text-gray-300">${escapeHtml(u.email)}${isSelf ? ' <span class="text-yellow-400 text-[10px]">(you)</span>' : ''}</td>
            <td class="px-6 py-3 capitalize font-semibold ${TIER_COLOR[u.tier] || 'text-gray-300'}">${escapeHtml(u.tier)}</td>
            <td class="px-6 py-3 capitalize ${ROLE_COLOR[u.role] || 'text-gray-300'}">${escapeHtml(u.role)}</td>
            <td class="px-6 py-3">${u.is_active ? '<span class="text-emerald-400">✓</span>' : '<span class="text-red-400">✗</span>'}</td>
            <td class="px-6 py-3 text-gray-500 text-xs">${u.created_at ? new Date(u.created_at).toLocaleDateString('de-DE') : '—'}</td>
            <td class="px-6 py-3 text-right space-x-2">
              <button class="ck-edit px-2 py-1 text-xs rounded border border-gray-700 hover:border-brand">Edit</button>
              <button class="ck-deact px-2 py-1 text-xs rounded border border-gray-700 hover:border-red-500 disabled:opacity-30" ${isSelf || !u.is_active ? 'disabled' : ''}>Deactivate</button>
            </td>
          </tr>`;
      })
      .join('');
    // Bind row buttons.
    tbody.querySelectorAll('.ck-edit').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const row = e.currentTarget.closest('tr');
        const uid = row.dataset.uid;
        openEditModal(uid, items.find((x) => x.id === uid));
      });
    });
    tbody.querySelectorAll('.ck-deact').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const row = e.currentTarget.closest('tr');
        const uid = row.dataset.uid;
        if (!confirm('Soft-delete this user (sets is_active=false)?')) return;
        const res = await window.FM.authFetch(`/api/v1/cockpit/users/${uid}`, { method: 'DELETE' });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          alert(body.detail || 'Delete failed.');
          return;
        }
        loadUsers();
        loadStats();
      });
    });
  }

  function renderPagination() {
    const from = (state.page - 1) * state.limit + 1;
    const to = Math.min(state.page * state.limit, state.total);
    $('users-range').textContent = state.total
      ? `Showing ${from}–${to} of ${state.total.toLocaleString()}`
      : '';
    $('users-prev').disabled = state.page <= 1;
    $('users-next').disabled = state.page * state.limit >= state.total;
  }

  function openEditModal(uid, user) {
    $('edit-email').textContent = user.email;
    $('edit-tier').value = user.tier;
    $('edit-role').value = user.role;
    $('edit-active').checked = !!user.is_active;
    $('edit-error').classList.add('hidden');
    $('edit-modal').classList.remove('hidden');
    $('edit-modal').dataset.uid = uid;
  }

  function closeEditModal() {
    $('edit-modal').classList.add('hidden');
    delete $('edit-modal').dataset.uid;
  }

  async function saveEdit() {
    const uid = $('edit-modal').dataset.uid;
    const body = {
      tier: $('edit-tier').value,
      role: $('edit-role').value,
      is_active: $('edit-active').checked,
    };
    const err = $('edit-error');
    err.classList.add('hidden');
    const res = await window.FM.authFetch(`/api/v1/cockpit/users/${uid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      err.textContent = data.detail || 'Save failed.';
      err.classList.remove('hidden');
      return;
    }
    closeEditModal();
    await Promise.all([loadUsers(), loadStats()]);
  }

  function highlightRange() {
    document.querySelectorAll('.ck-range').forEach((btn) => {
      if (Number(btn.dataset.days) === state.range) {
        btn.classList.add('border-brand', 'text-white');
        btn.classList.remove('text-gray-400');
      } else {
        btn.classList.remove('border-brand', 'text-white');
        btn.classList.add('text-gray-400');
      }
    });
  }

  async function init() {
    const me = await window.FM.getUser();
    if (!me) {
      window.location.href = '/login?next=/cockpit';
      return;
    }
    if (me.role !== 'admin') {
      showForbidden();
      return;
    }
    state.me = me;
    $('ck-admin-email').textContent = `Signed in as ${me.email} · admin`;
    showDashboard();

    highlightRange();
    await Promise.all([loadStats(), loadChart(state.range), loadUsers()]);

    // Filter change triggers — reset to page 1.
    ['users-q', 'users-tier', 'users-role', 'users-active'].forEach((id) => {
      const el = $(id);
      const handler = () => { state.page = 1; loadUsers(); };
      el.addEventListener(id === 'users-q' ? 'input' : 'change', handler);
    });

    $('users-prev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadUsers(); } });
    $('users-next').addEventListener('click', () => {
      if (state.page * state.limit < state.total) { state.page++; loadUsers(); }
    });

    document.querySelectorAll('.ck-range').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.range = Number(btn.dataset.days);
        highlightRange();
        loadChart(state.range);
      });
    });

    $('edit-cancel').addEventListener('click', closeEditModal);
    $('edit-save').addEventListener('click', saveEdit);
    $('edit-modal').addEventListener('click', (e) => {
      if (e.target === $('edit-modal')) closeEditModal();
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();

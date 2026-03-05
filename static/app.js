/**
 * Severance Dashboard — app.js
 * Vanilla JS + Chart.js, no build step.
 */

// --- Config ---
const PROVIDER_COLORS = {
    anthropic: '#d97706',
    openai: '#10a37f',
    google: '#4285f4',
};

const MODEL_COLORS = [
    '#6366f1', '#8b5cf6', '#a855f7', '#d946ef',
    '#ec4899', '#f43f5e', '#ef4444', '#f97316',
    '#f59e0b', '#eab308', '#84cc16', '#22c55e',
    '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6',
];

// --- State ---
let currentRange = { start: null, end: null };
let currentGroupBy = 'provider';
let timelineChart = null;
let providerChart = null;

// --- Helpers ---
function fmt(n) {
    if (n == null || isNaN(n)) return '—';
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTokens(n) {
    if (n == null || isNaN(n)) return '—';
    if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return n.toLocaleString();
}

function fmtNum(n) {
    if (n == null || isNaN(n)) return '—';
    return n.toLocaleString();
}

function isoDate(d) {
    return d.toISOString().split('T')[0] + 'T00:00:00Z';
}

function getRange(preset) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let start, end;

    switch (preset) {
        case '7d':
            start = new Date(today); start.setDate(start.getDate() - 7);
            end = new Date(today); end.setDate(end.getDate() + 1);
            break;
        case '14d':
            start = new Date(today); start.setDate(start.getDate() - 14);
            end = new Date(today); end.setDate(end.getDate() + 1);
            break;
        case '30d':
            start = new Date(today); start.setDate(start.getDate() - 30);
            end = new Date(today); end.setDate(end.getDate() + 1);
            break;
        case 'mtd':
            start = new Date(now.getFullYear(), now.getMonth(), 1);
            end = new Date(today); end.setDate(end.getDate() + 1);
            break;
        case 'last-month':
            start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            end = new Date(now.getFullYear(), now.getMonth(), 1);
            break;
        default:
            start = new Date(today); start.setDate(start.getDate() - 30);
            end = new Date(today); end.setDate(end.getDate() + 1);
    }

    return { start: isoDate(start), end: isoDate(end) };
}

async function api(path, params = {}) {
    const url = new URL(path, window.location.origin);
    for (const [k, v] of Object.entries(params)) {
        if (v != null) url.searchParams.set(k, v);
    }
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
}

// --- Summary Cards ---
async function loadSummary() {
    try {
        const data = await api('/api/summary', currentRange);
        const c = data.current || {};
        const p = data.previous || {};
        const input = c.total_input_tokens || 0;
        const output = c.total_output_tokens || 0;
        const cached = c.total_cached_tokens || 0;

        document.getElementById('total-cost').textContent = fmt(c.total_cost_usd);
        document.getElementById('total-tokens').textContent =
            fmtTokens(input + output + cached);
        document.getElementById('token-breakdown').textContent =
            `${fmtTokens(input)} uncached in · ${fmtTokens(cached)} cached in · ${fmtTokens(output)} out`;
        document.getElementById('total-requests').textContent = fmtNum(c.total_requests);
        document.getElementById('total-models').textContent = fmtNum(c.model_count);
        document.getElementById('provider-count').textContent =
            `${c.provider_count || 0} provider${(c.provider_count || 0) !== 1 ? 's' : ''}`;

        // Delta
        const deltaEl = document.getElementById('total-delta');
        if (p.total_cost_usd && c.total_cost_usd) {
            const diff = c.total_cost_usd - p.total_cost_usd;
            const pct = ((diff / p.total_cost_usd) * 100).toFixed(0);
            const sign = diff > 0 ? '+' : '';
            deltaEl.textContent = `${sign}${fmt(diff)} (${sign}${pct}%) vs prev period`;
            deltaEl.className = 'card-delta ' + (diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat');
        } else {
            deltaEl.textContent = '';
        }
    } catch (e) {
        console.error('Failed to load summary:', e);
    }
}

// --- Timeline Chart ---
async function loadTimeline() {
    try {
        const data = await api('/api/usage', {
            ...currentRange,
            group_by: currentGroupBy,
        });

        const rows = data.data || [];
        if (!rows.length) {
            renderEmptyTimeline();
            return;
        }

        // Group data by series (provider or model)
        const seriesMap = {};
        for (const row of rows) {
            const key = currentGroupBy === 'model'
                ? `${row.provider}/${row.model || 'unknown'}`
                : row.provider;
            if (!seriesMap[key]) seriesMap[key] = {};
            seriesMap[key][row.date] = (seriesMap[key][row.date] || 0) + (row.cost_usd || 0);
        }

        // Get all dates sorted
        const dates = [...new Set(rows.map(r => r.date))].sort();

        // Build datasets
        const datasets = [];
        const keys = Object.keys(seriesMap).sort();
        keys.forEach((key, i) => {
            const color = currentGroupBy === 'provider'
                ? (PROVIDER_COLORS[key] || MODEL_COLORS[i % MODEL_COLORS.length])
                : MODEL_COLORS[i % MODEL_COLORS.length];
            datasets.push({
                label: key,
                data: dates.map(d => seriesMap[key][d] || 0),
                backgroundColor: color + 'cc',
                borderColor: color,
                borderWidth: 1,
                borderRadius: 3,
            });
        });

        if (timelineChart) timelineChart.destroy();
        const ctx = document.getElementById('timeline-chart').getContext('2d');
        timelineChart = new Chart(ctx, {
            type: 'bar',
            data: { labels: dates, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#8b8d98', boxWidth: 12, padding: 16, font: { size: 11 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${fmt(ctx.raw)}`,
                        },
                    },
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { color: '#2a2d3a' },
                        ticks: { color: '#5c5e6a', font: { size: 11 } },
                    },
                    y: {
                        stacked: true,
                        grid: { color: '#2a2d3a' },
                        ticks: {
                            color: '#5c5e6a',
                            font: { size: 11 },
                            callback: v => '$' + v.toFixed(2),
                        },
                    },
                },
            },
        });
    } catch (e) {
        console.error('Failed to load timeline:', e);
    }
}

function renderEmptyTimeline() {
    if (timelineChart) timelineChart.destroy();
    const ctx = document.getElementById('timeline-chart').getContext('2d');
    timelineChart = new Chart(ctx, {
        type: 'bar',
        data: { labels: ['No data'], datasets: [{ data: [0], backgroundColor: '#2a2d3a' }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: '#2a2d3a' }, ticks: { color: '#5c5e6a' } },
                y: { grid: { color: '#2a2d3a' }, ticks: { color: '#5c5e6a' } },
            },
        },
    });
}

// --- Provider Pie ---
async function loadProviders() {
    try {
        const data = await api('/api/providers', currentRange);
        const providers = data.providers || [];

        if (!providers.length) {
            if (providerChart) providerChart.destroy();
            return;
        }

        const labels = providers.map(p => p.provider);
        const values = providers.map(p => p.cost_usd || 0);
        const colors = labels.map(l => PROVIDER_COLORS[l] || '#6366f1');

        if (providerChart) providerChart.destroy();
        const ctx = document.getElementById('provider-chart').getContext('2d');
        providerChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors.map(c => c + 'cc'),
                    borderColor: colors,
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#8b8d98', boxWidth: 12, padding: 12, font: { size: 12 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.label}: ${fmt(ctx.raw)}`,
                        },
                    },
                },
            },
        });
    } catch (e) {
        console.error('Failed to load providers:', e);
    }
}

// --- Model Table ---
async function loadModels() {
    try {
        const data = await api('/api/models', currentRange);
        const models = data.models || [];
        const tbody = document.getElementById('model-tbody');

        if (!models.length) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="empty-state">
                    <h3>No data yet</h3>
                    <p>Click ⟳ to fetch data from your providers, or wait for the auto-refresh.</p>
                </td></tr>`;
            return;
        }

        tbody.innerHTML = models.map(m => `
            <tr>
                <td><span class="provider-badge ${m.provider}">${m.provider}</span></td>
                <td>${m.model || '—'}</td>
                <td class="num">${fmtTokens(m.input_tokens)}</td>
                <td class="num">${fmtTokens(m.output_tokens)}</td>
                <td class="num">${fmtTokens(m.cached_tokens)}</td>
                <td class="num">${fmtNum(m.requests)}</td>
                <td class="num">${fmt(m.cost_usd)}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Failed to load models:', e);
    }
}

// --- Load All ---
async function loadAll() {
    await Promise.all([
        loadSummary(),
        loadTimeline(),
        loadProviders(),
        loadModels(),
    ]);
    document.getElementById('last-refresh').textContent =
        'Last loaded: ' + new Date().toLocaleTimeString();
}

// --- Events ---

// Range buttons
document.querySelectorAll('.range-btn[data-range]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentRange = getRange(btn.dataset.range);
        loadAll();
    });
});

// Custom range
document.getElementById('custom-go').addEventListener('click', () => {
    const startInput = document.getElementById('custom-start').value;
    const endInput = document.getElementById('custom-end').value;
    if (startInput && endInput) {
        document.querySelectorAll('.range-btn[data-range]').forEach(b => b.classList.remove('active'));
        currentRange = {
            start: startInput + 'T00:00:00Z',
            end: endInput + 'T23:59:59Z',
        };
        loadAll();
    }
});

// Group by toggle
document.querySelectorAll('.toggle-btn[data-group]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentGroupBy = btn.dataset.group;
        loadTimeline();
    });
});

// Refresh button
document.getElementById('refresh-btn').addEventListener('click', async () => {
    const btn = document.getElementById('refresh-btn');
    btn.classList.add('spinning');
    btn.disabled = true;
    try {
        await fetch('/api/refresh?days=30', { method: 'POST' });
        await loadAll();
    } catch (e) {
        console.error('Refresh failed:', e);
        alert('Refresh failed. Check console for details.');
    } finally {
        btn.classList.remove('spinning');
        btn.disabled = false;
    }
});

// --- Init ---
currentRange = getRange('30d');
loadAll();

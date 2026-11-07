// AK-Bench UI JavaScript: real-time updates, filters, modal inspector and interactive charts

let refreshTimer = null;
let currentRefreshInterval = 0; // 0 = disabled

// ============================================================ Page-Load Indicator
// A decorative ramp: it says "the data is arriving", it does not measure the
// query. It is driven from one place so that every way of moving through the
// UI -- a link, a form, a browser button, a fetch that repaints a table, a run
// inspector -- shows the same signal, and shows it long enough to be seen.
const pageLoader = (function initPageLoader() {
  const prefersReducedMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const loader = document.getElementById('pageLoader');
  const bar = document.getElementById('pageLoaderBar');

  // A bar that is gone in 120 ms reads as a glitch, not as loading; one that
  // outlives the request reads as a lie. These are the two ends held together.
  const MIN_VISIBLE_MS = 550;
  const MAX_VISIBLE_MS = 4000;
  const FETCH_DELAY_MS = 150;

  const state = { visible: false, since: 0, hideTimer: null, capTimer: null, pending: 0 };

  const setWidth = (percent) => {
    if (bar) bar.style.width = percent + '%';
  };

  const show = () => {
    if (!loader || !bar || prefersReducedMotion) return;
    window.clearTimeout(state.hideTimer);
    window.clearTimeout(state.capTimer);
    if (!state.visible) {
      // Re-arm without letting the browser animate the reset: the bar has to
      // start at the left edge, not slide back to it.
      loader.style.transition = 'none';
      loader.style.display = '';
      loader.classList.remove('page-loader-done');
      setWidth(0);
      void loader.offsetWidth;
      loader.style.transition = '';
      state.visible = true;
      state.since = Date.now();
      state.capTimer = window.setTimeout(hide, MAX_VISIBLE_MS);
    }
    return true;
  };

  const hide = () => {
    if (!loader || state.pending > 0) return;
    window.clearTimeout(state.hideTimer);
    window.clearTimeout(state.capTimer);
    if (!state.visible) return;
    const held = Date.now() - state.since;
    state.hideTimer = window.setTimeout(() => {
      state.visible = false;
      loader.classList.add('page-loader-done');
    }, Math.max(0, MIN_VISIBLE_MS - held));
  };

  // Fast to two thirds, slower from there: a bar that never quite stalls looks
  // like work in progress without pretending to know how much is left.
  const ramp = () => {
    const climb = (delay, percent) => window.setTimeout(() => {
      if (state.visible) setWidth(percent);
    }, delay);
    climb(0, 38);
    climb(300, 66);
    climb(700, 84);
    climb(1300, 93);
  };

  const begin = () => {
    if (!show()) return false;
    ramp();
    return true;
  };

  // Every request in flight is a reason to keep the bar up. Short local answers
  // never show it at all, so the dashboard does not blink every refresh.
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  if (nativeFetch) {
    window.fetch = (input, init) => {
      if (prefersReducedMotion) return nativeFetch(input, init);
      const background = init && init.loader === false;
      if (background) return nativeFetch(input, init);
      let shown = false;
      const timer = window.setTimeout(() => { shown = begin(); }, FETCH_DELAY_MS);
      state.pending += 1;
      return nativeFetch(input, init).then(
        (response) => { window.clearTimeout(timer); state.pending -= 1; if (shown) hide(); return response; },
        (error) => { window.clearTimeout(timer); state.pending -= 1; if (shown) hide(); throw error; }
      );
    };
  }

  // A link, however it was made: server-rendered, painted by a script, or a
  // button that assigns location.href itself.
  document.addEventListener('click', (event) => {
    const anchor = event.target.closest && event.target.closest('a[href]');
    if (anchor) {
      const href = anchor.getAttribute('href') || '';
      const external = /^https?:\/\//i.test(href) && !href.startsWith(window.location.origin);
      const skips = external || anchor.target === '_blank' || anchor.hasAttribute('download')
        || /^(javascript:|#|mailto:|tel:)/i.test(href) || event.metaKey || event.ctrlKey
        || event.shiftKey || event.altKey || event.button !== 0;
      if (!skips) begin();
    }
    const trigger = event.target.closest && event.target.closest('button, [type="submit"]');
    if (trigger && trigger.closest('form')) begin();
  });

  document.addEventListener('submit', begin);

  // The catch-all: a script that navigates by assigning location covers every
  // path a delegated click could miss, and the browser may never fire load().
  window.addEventListener('beforeunload', begin);

  // Restored from the back/forward cache: the page is already drawn, so the
  // bar only says "you are back" before getting out of the way.
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    begin();
    window.setTimeout(hide, 260);
  });

  return { begin, hide };
})();

window.addEventListener('load', () => {
  pageLoader.begin();
  window.setTimeout(() => pageLoader.hide(), 250);
});

document.addEventListener('DOMContentLoaded', () => {
  initLiveRefresh();
  initRunsFilter();
  initModals();
  initTabs();
  initCompareHelpers();
  initSortableTables();
  initCopyButtons();
  initYamlHighlighting();
  initSparklines();
  const copyCsv = document.getElementById('btnCopyCsv');
  if (copyCsv) copyCsv.addEventListener('click', () => copyRunsTable('csv'));
  const copyMarkdown = document.getElementById('btnCopyMarkdown');
  if (copyMarkdown) copyMarkdown.addEventListener('click', () => copyRunsTable('markdown'));
  initRunsKeyNav();
  initThemeToggle();

  if (document.getElementById('liveStrip')) {
    fetchActiveRuns();
    setInterval(tickLiveElapsed, 1000);
  }
  initTaskCodeTree();
  initRunDiffPicker();
  initRunSelectionLimit();
});

// ============================================================ Live Refresh
function initLiveRefresh() {
  const refreshSelect = document.getElementById('refreshInterval');
  if (!refreshSelect) return;

  refreshSelect.addEventListener('change', (e) => {
    const val = parseInt(e.target.value, 10);
    setRefreshInterval(val);
  });

  const saved = localStorage.getItem('akbench_refresh_interval');
  if (saved) {
    refreshSelect.value = saved;
    setRefreshInterval(parseInt(saved, 10));
  }
}

function setRefreshInterval(seconds) {
  currentRefreshInterval = seconds;
  localStorage.setItem('akbench_refresh_interval', seconds);
  if (refreshTimer) clearInterval(refreshTimer);

  const dot = document.querySelector('.pulse-dot');
  if (seconds > 0) {
    if (dot) dot.style.display = 'inline-block';
    refreshTimer = setInterval(() => {
      triggerLiveUpdate();
    }, seconds * 1000);
  } else {
    if (dot) dot.style.display = 'none';
  }
}

function triggerLiveUpdate() {
  const filterForm = document.getElementById('runsFilterForm');
  if (filterForm) {
    fetchFilteredRuns();
    return;
  }
  const isDashboard = document.getElementById('dashboardRoot');
  if (isDashboard) {
    fetchOverviewData();
    fetchActiveRuns();
  }
}

// A run that has not finished is a run the reader can watch, and one stuck for
// an hour should not look like one that started two minutes ago. The strip is
// repainted from the API on the same interval as everything else; an empty
// list is a good answer, not an error, so it says so plainly.
async function fetchActiveRuns() {
  const body = document.getElementById('liveBody');
  const count = document.getElementById('liveCount');
  if (!body) return;
  try {
    const res = await fetch('/api/active-runs', { loader: false });
    if (!res.ok) return;
    const runs = await res.json();
    count.textContent = String(runs.length);
    if (!runs.length) {
      body.innerHTML = '<div class="live-none">All runs are finished.</div>';
      return;
    }
    body.innerHTML = runs.map(run => `
      <div class="live-run">
        <span class="live-state mono">${escapeHtml(run.status || 'running')}</span>
        <a href="/tasks/${encodeURIComponent(run.task_uid || '')}" class="mono">${escapeHtml(run.task_uid || '—')}</a>
        <span class="live-uid mono">${escapeHtml(run.uid || '')}</span>
        <span class="live-elapsed mono" data-since="${escapeHtml(run.started_at || '')}">—</span>
      </div>
    `).join('');
    tickLiveElapsed();
  } catch (err) {
    console.error('Failed to fetch active runs:', err);
  }
}

// Elapsed time is read from the clock, not from the server, so a run's age
// grows between refreshes without asking the database again.
function tickLiveElapsed() {
  document.querySelectorAll('.live-elapsed[data-since]').forEach((element) => {
    const since = element.dataset.since;
    if (!since) return;
    const seconds = Math.max(0, Math.round((Date.now() - new Date(since).getTime()) / 1000));
    element.textContent = formatDuration(seconds);
  });
}

async function fetchOverviewData() {
  try {
    const res = await fetch('/api/overview', { loader: false });
    if (!res.ok) return;
    const data = await res.json();
    updateDashboardDOM(data);
  } catch (err) {
    console.error('Failed to fetch overview data:', err);
  }
}

function updateDashboardDOM(data) {
  const runsCount = document.getElementById('statTotalRuns');
  if (runsCount) runsCount.textContent = (data.summary.runs || 0).toLocaleString();

  const evalCount = document.getElementById('statEvaluatedRuns');
  if (evalCount) evalCount.textContent = (data.summary.evaluated || 0).toLocaleString();

  const succRate = document.getElementById('statSuccessRate');
  if (succRate) {
    succRate.textContent = data.summary.success_rate !== null ? (data.summary.success_rate * 100).toFixed(1) + '%' : '—';
  }

  const meanScore = document.getElementById('statMeanScore');
  if (meanScore) {
    meanScore.textContent = data.summary.mean_score !== null ? Number(data.summary.mean_score).toFixed(3) : '—';
  }

  const meanDuration = document.getElementById('statMeanDuration');
  if (meanDuration) {
    meanDuration.textContent = formatDuration(data.summary.mean_duration_seconds);
  }

  const totalTokens = document.getElementById('statTotalTokens');
  if (totalTokens) {
    totalTokens.textContent = (data.summary.total_tokens || 0).toLocaleString();
  }
}

// ============================================================ Runs Filtering
function initRunsFilter() {
  const form = document.getElementById('runsFilterForm');
  if (!form) return;

  const inputs = form.querySelectorAll('input, select');
  let debounceTimeout = null;

  inputs.forEach(input => {
    input.addEventListener('input', () => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        fetchFilteredRuns();
      }, 250);
    });
    input.addEventListener('change', () => {
      fetchFilteredRuns();
    });
  });

  const resetBtn = document.getElementById('btnResetFilter');
  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      form.reset();
      fetchFilteredRuns();
    });
  }
}

async function fetchFilteredRuns() {
  const form = document.getElementById('runsFilterForm');
  if (!form) return;

  const formData = new FormData(form);
  const params = new URLSearchParams();
  for (const [key, val] of formData.entries()) {
    if (val) params.append(key, val);
  }

  const tbody = document.getElementById('runsTableBody');
  const countBadge = document.getElementById('runsMatchedCount');
  if (tbody) tbody.style.opacity = '0.5';

  try {
    const res = await fetch(`/api/runs?${params.toString()}`);
    if (!res.ok) throw new Error('API request failed');
    const data = await res.json();

    if (countBadge) countBadge.textContent = `${data.total} runs`;

    if (tbody) {
      tbody.innerHTML = '';
      if (data.runs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="15" style="text-align:center; padding:30px; color:var(--fg-faint);">No runs match the specified filter criteria.</td></tr>';
      } else {
        data.runs.forEach(run => {
          tbody.appendChild(createRunTableRow(run));
        });
      }
      initSparklines(tbody);
      tbody.style.opacity = '1';
      applyRunSelectionLimits();
    }
  } catch (err) {
    console.error('Error fetching filtered runs:', err);
    if (tbody) tbody.style.opacity = '1';
  }
}

function createRunTableRow(run) {
  const tr = document.createElement('tr');
  const verdictClass = run.verdict ? `badge-${run.verdict}` : 'badge-neutral';
  const scoreFormatted = run.score !== null && run.score !== undefined ? Number(run.score).toFixed(3) : '—';
  const durationFormatted = formatDuration(run.duration_seconds);
  const totalTokensFormatted = run.total_tokens ? Number(run.total_tokens).toLocaleString() : '—';
  const toolCallsFormatted = run.tool_call_count === null || run.tool_call_count === undefined
    ? '—'
    : Number(run.tool_call_count).toLocaleString();

  tr.innerHTML = `
    <td>
      <input type="checkbox" class="run-select-check" value="${escapeHtml(run.uid)}" />
    </td>
    <td>
      <a href="javascript:void(0)" onclick="openRunModal('${escapeHtml(run.uid)}')" class="mono" style="font-weight:600;">
        ${escapeHtml(run.uid)}
      </a>
      <div style="font-size:11px; color:var(--fg-faint); margin-top:2px;">
        ${escapeHtml(run.config_str || '—')}
      </div>
    </td>
    <td class="num mono" data-sort-value="${run.repetition === null || run.repetition === undefined ? '' : run.repetition}">
      ${run.repetition === null || run.repetition === undefined ? '—' : run.repetition}
    </td>
    <td>
      <a href="/tasks/${encodeURIComponent(run.task_uid || '')}" class="mono">
        ${escapeHtml(run.task_uid || '—')}
      </a>
    </td>
    <td class="mono" style="font-size:11.5px;">${escapeHtml(run.agent || '—')}</td>
    <td class="mono" style="font-size:11.5px;">${escapeHtml(run.runtime_id || '—')}</td>
    <td>
      <span class="badge ${verdictClass}">
        ${escapeHtml(run.verdict || 'unverified')}
      </span>
    </td>
    <td class="num">
      <span class="mono" style="font-weight:600; color:${getScoreColor(run.score)};">
        ${scoreFormatted}
      </span>
    </td>
    <td class="spark-cell">${sparkCell(run)}</td>
    <td class="num mono" data-sort-value="${run.duration_seconds === null || run.duration_seconds === undefined ? '' : run.duration_seconds}">${durationFormatted}</td>
    <td class="num mono">${totalTokensFormatted}</td>
    <td class="num mono" data-sort-value="${run.tool_call_count === null || run.tool_call_count === undefined ? '' : run.tool_call_count}">${toolCallsFormatted}</td>
    <td>
      <span class="badge badge-neutral" style="font-size:11px;">
        ${escapeHtml(run.status || 'unknown')}
      </span>
    </td>
    <td style="font-size:11px; color:var(--fg-faint); white-space:nowrap;">
      ${formatDate(run.started_at)}
    </td>
    <td style="text-align:right;">
      <button class="btn btn-sm" onclick="openRunModal('${escapeHtml(run.uid)}')">Inspect</button>
    </td>
  `;
  return tr;
}

// ============================================================ Modal & Tabs
function initModals() {
  const overlay = document.getElementById('runDetailModal');
  if (!overlay) return;

  const closeBtn = overlay.querySelector('.modal-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      overlay.classList.remove('open');
    });
  }

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      overlay.classList.remove('open');
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.classList.contains('open')) {
      overlay.classList.remove('open');
    }
  });
}

function initTabs() {
  document.addEventListener('click', (e) => {
    const tabBtn = e.target.closest('.modal-tab');
    if (!tabBtn) return;

    const parent = tabBtn.closest('.modal');
    if (!parent) return;

    const tabName = tabBtn.getAttribute('data-tab');
    parent.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
    parent.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    tabBtn.classList.add('active');
    const targetPane = parent.querySelector(`#tab-${tabName}`);
    if (targetPane) targetPane.classList.add('active');
  });
}

async function openRunModal(runUid) {
  const modal = document.getElementById('runDetailModal');
  if (!modal) return;

  modal.classList.add('open');
  const title = modal.querySelector('.modal-title');
  if (title) title.textContent = `Run Inspector: ${runUid}`;

  // Reset tab active state
  modal.querySelectorAll('.modal-tab').forEach((t, i) => {
    if (i === 0) t.classList.add('active');
    else t.classList.remove('active');
  });
  modal.querySelectorAll('.tab-pane').forEach((p, i) => {
    if (i === 0) p.classList.add('active');
    else p.classList.remove('active');
  });

  const bodyOverview = modal.querySelector('#tab-overview');
  const bodyEval = modal.querySelector('#tab-evaluation');
  const bodyEvents = modal.querySelector('#tab-events');
  const bodyArtifacts = modal.querySelector('#tab-artifacts');
  const bodyJson = modal.querySelector('#tab-json');

  if (bodyOverview) bodyOverview.innerHTML = '<div style="color:var(--fg-faint); text-align:center; padding:30px;">Loading run details...</div>';

  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runUid)}`);
    if (!res.ok) throw new Error('Failed to load run detail');
    const data = await res.json();
    renderRunModalContent(data, { bodyOverview, bodyEval, bodyEvents, bodyArtifacts, bodyJson });
  } catch (err) {
    if (bodyOverview) bodyOverview.innerHTML = `<div style="color:var(--red);">Error loading run: ${escapeHtml(err.message)}</div>`;
  }
}

// The evaluator's report names every test it ran; the counts only say how many
// passed. A run whose one failing test is named is a different thing to read
// than a run that is 90% something.
function renderRunTests(tests) {
  if (!tests || !tests.length) {
    return `
      <div class="panel">
        <div class="panel-header"><div class="panel-title">Individual Tests</div></div>
        <div class="panel-body" style="padding:14px; color:var(--fg-faint);">
          The evaluator recorded counts, not a per-test report, for this run.
        </div>
      </div>
    `;
  }
  const marks = { passed: '✔', failed: '✘', error: '✗', skipped: '○' };
  const rows = tests.map(test => `
    <div class="test-row test-row-${escapeHtml(test.status)}">
      <span class="test-mark mono" title="${escapeHtml(test.status)}">${marks[test.status] || '•'}</span>
      <span class="test-name mono">${escapeHtml(test.classname ? test.classname + '.' + test.name : test.name)}</span>
      <span class="test-time mono">${test.duration_seconds === null || test.duration_seconds === undefined ? '—' : test.duration_seconds.toFixed(3) + 's'}</span>
      ${test.detail ? `<div class="test-detail mono">${escapeHtml(test.detail)}</div>` : ''}
    </div>
  `).join('');
  const passed = tests.filter(t => t.status === 'passed').length;
  return `
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Individual Tests</div>
        <span class="badge badge-passed">${passed} passed</span>
      </div>
      <div class="test-list">${rows}</div>
    </div>
  `;
}

// How much a run paid, and how the payment split: input, of it cached, output,
// and reasoning. The headline is the cache hit ratio — the one number that
// tells whether the input the run was charged for was already on the shelf.
function renderTokenBreakdown(obs) {
  const parts = [
    { key: 'input', label: 'input', color: 'var(--blue, #5aa9ff)', value: obs.input_tokens || 0 },
    { key: 'cached', label: 'cached', color: 'var(--mint, #00e59b)', value: obs.cached_input_tokens || 0 },
    { key: 'output', label: 'output', color: 'var(--amber, #ffb44a)', value: obs.output_tokens || 0 },
    { key: 'reasoning', label: 'reasoning', color: '#c792ea', value: obs.reasoning_output_tokens || 0 },
  ];
  const stated = parts.filter(part => part.value > 0);
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  const cacheHit = obs.input_tokens
    ? ((obs.cached_input_tokens || 0) / obs.input_tokens * 100).toFixed(1) + '%'
    : '—';

  const bar = total
    ? `<div class="token-bar">
        ${stated.map(part => `<div class="token-seg" style="width:${(part.value / total * 100).toFixed(2)}%; background:${part.color};" title="${part.label}: ${part.value.toLocaleString()}"></div>`).join('')}
      </div>`
    : '';
  const legend = parts.map(part => `
    <div class="token-legend-item">
      <span class="token-swatch" style="background:${part.color};"></span>
      <span class="token-legend-label">${part.label}</span>
      <span class="token-legend-value mono">${part.value ? part.value.toLocaleString() : '—'}</span>
    </div>`).join('');

  return `
    <div class="token-headline">
      <span class="token-cache mono">cache hit ${cacheHit}</span>
    </div>
    ${bar}
    <div class="token-legend">${legend}</div>
  `;
}

function renderRunModalContent(data, { bodyOverview, bodyEval, bodyEvents, bodyArtifacts, bodyJson }) {
  const run = data.run;
  const score = data.score !== null ? Number(data.score).toFixed(3) : '—';
  const obs = run.observations || {};
  const evalInfo = data.evaluator_info || {};

  if (bodyOverview) {
    bodyOverview.innerHTML = `
      <div class="grid-cards" style="margin-bottom:18px;">
        <div class="card card-mint">
          <div class="card-title">Verdict & Score</div>
          <div class="card-value">${escapeHtml(data.verdict || 'unverified')} <span style="font-size:16px; color:#fff;">(${score})</span></div>
          <div class="card-sub">${evalInfo.passed || 0} passed / ${(evalInfo.total || 0)} tests</div>
        </div>
        <div class="card card-blue">
          <div class="card-title">Wall-Clock Duration</div>
          <div class="card-value">${formatDuration(data.duration_seconds)}</div>
          <div class="card-sub">${run.status || 'unknown'}</div>
        </div>
        <div class="card card-amber">
          <div class="card-title">Token Split</div>
          <div class="card-value">${obs.total_tokens ? Number(obs.total_tokens).toLocaleString() : '—'}</div>
          ${renderTokenBreakdown(obs)}
        </div>
      </div>

      <div class="panel" style="margin-bottom:16px;">
        <div class="panel-header"><div class="panel-title">Run Configuration & Environment</div></div>
        <div class="panel-body" style="padding:14px;">
          <table style="font-size:13px;">
            <tr><th style="width:200px;">Task</th><td><a href="/tasks/${encodeURIComponent(run.task_uid || '')}">${escapeHtml(run.task_uid || '—')}</a></td></tr>
            <tr><th>Experiment</th><td><a href="/experiments/${encodeURIComponent(run.experiment_uid || '')}">${escapeHtml(run.experiment_uid || '—')}</a></td></tr>
            <tr><th>Variant Config</th><td><code>${escapeHtml(JSON.stringify(data.variant_values || {}))}</code></td></tr>
            <tr><th>Agent & Runtime</th><td><code>${escapeHtml(run.agent || '—')}</code> (runtime: <code>${escapeHtml(run.runtime_id || 'default')}</code>)</td></tr>
            <tr><th>Observed Model</th><td><code>${escapeHtml(run.observed_model || run.requested_model || '—')}</code> (status: ${escapeHtml(run.model_verification || 'unverified')})</td></tr>
            <tr><th>Started / Finished</th><td>${formatDate(run.started_at)} → ${formatDate(run.finished_at)}</td></tr>
            ${run.error_message ? `<tr><th>Error Message</th><td style="color:var(--red); font-family:var(--mono);">${escapeHtml(run.error_message)}</td></tr>` : ''}
          </table>
        </div>
      </div>

      ${data.task_instruction ? `
        <div class="panel">
          <div class="panel-header"><div class="panel-title">Task Instruction / Prompt</div></div>
          <div class="panel-body" style="padding:14px;"><pre style="margin:0; max-height:220px; overflow-y:auto;">${escapeHtml(data.task_instruction)}</pre></div>
        </div>
      ` : ''}
    `;
  }

  if (bodyEval) {
    bodyEval.innerHTML = `
      <div style="margin-bottom:16px;">
        <div style="display:flex; gap:12px; align-items:center; margin-bottom:12px;">
          <span class="badge ${data.verdict ? 'badge-' + data.verdict : 'badge-neutral'}" style="font-size:14px; padding:4px 10px;">
            Verdict: ${escapeHtml(data.verdict || 'unverified')}
          </span>
          <span class="mono" style="font-size:14px; font-weight:600; color:${getScoreColor(data.score)};">
            Score: ${score}
          </span>
          <span style="color:var(--fg-dim); font-size:13px;">
            (${evalInfo.passed || 0} passed, ${evalInfo.failed || 0} failed, ${evalInfo.skipped || 0} skipped / ${evalInfo.total || 0} total)
          </span>
        </div>
        <div style="font-size:12px; color:var(--fg-faint); margin-bottom:16px;">
          Evaluator: <code>${escapeHtml(evalInfo.evaluator_id || 'pytest')}@${escapeHtml(evalInfo.evaluator_version || '1.0')}</code>
          ${evalInfo.duration_seconds ? `(eval duration: ${evalInfo.duration_seconds.toFixed(2)}s)` : ''}
        </div>
      </div>

      ${renderRunTests(data.tests)}

      <div class="panel">
        <div class="panel-header"><div class="panel-title">Detailed Evaluation Payload</div></div>
        <div class="panel-body" style="padding:14px;">
          <pre style="margin:0; max-height:350px;">${escapeHtml(JSON.stringify(data.evaluation_details || {}, null, 2))}</pre>
        </div>
      </div>
    `;
  }

  if (bodyEvents) {
    if (!data.events || data.events.length === 0) {
      bodyEvents.innerHTML = '<div style="color:var(--fg-faint); padding:20px; text-align:center;">No lifecycle events recorded for this run.</div>';
    } else {
      let timelineHtml = '<div class="timeline">';
      data.events.forEach(ev => {
        timelineHtml += `
          <div class="timeline-item">
            <div class="timeline-dot"></div>
            <div class="timeline-time">${formatDate(ev.at)}</div>
            <div class="timeline-content">
              <span class="badge badge-neutral" style="font-size:11px;">${escapeHtml(ev.event_type || 'event')}</span>
              <span style="margin-left:8px; color:#fff;">${escapeHtml(ev.message || '')}</span>
              ${ev.details ? `<pre style="margin:6px 0 0; padding:6px 10px; font-size:11px;">${escapeHtml(JSON.stringify(ev.details))}</pre>` : ''}
            </div>
          </div>
        `;
      });
      timelineHtml += '</div>';
      bodyEvents.innerHTML = timelineHtml;
    }
  }

  if (bodyArtifacts) {
    if (!data.artifacts || data.artifacts.length === 0) {
      bodyArtifacts.innerHTML = '<div style="color:var(--fg-faint); padding:20px; text-align:center;">No artifacts attached to this run.</div>';
    } else {
      let artHtml = `
        <table style="width:100%; margin-bottom:16px;">
          <thead>
            <tr><th>Kind</th><th>Filename</th><th>Size</th><th>Type</th><th>Actions</th></tr>
          </thead>
          <tbody>
      `;
      data.artifacts.forEach(art => {
        artHtml += `
          <tr>
            <td><span class="badge badge-info">${escapeHtml(art.kind)}</span></td>
            <td class="mono">${escapeHtml(art.filename || art.path || '')}</td>
            <td class="num mono">${formatBytes(art.size_bytes)}</td>
            <td style="color:var(--fg-faint); font-size:11.5px;">${escapeHtml(art.content_type || 'text/plain')}</td>
            <td>
              <button class="btn btn-sm" onclick="previewArtifact('${escapeHtml(run.uid)}', '${escapeHtml(art.kind)}')">Preview</button>
            </td>
          </tr>
        `;
      });
      artHtml += '</tbody></table><div id="artifactPreviewContainer"></div>';
      bodyArtifacts.innerHTML = artHtml;
    }
  }

  if (bodyJson) {
    bodyJson.innerHTML = `
      <div class="viewer-actions">
        <button class="btn btn-sm" type="button" data-copy-target="#runRawJson">Copy</button>
      </div>
      <pre id="runRawJson" style="max-height:500px; overflow-y:auto; margin:0;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  }
}

async function previewArtifact(runUid, kind) {
  const container = document.getElementById('artifactPreviewContainer');
  if (!container) return;
  container.innerHTML = `<div style="color:var(--fg-faint); padding:10px;">Loading ${escapeHtml(kind)}...</div>`;

  try {
    const res = await fetch(`/api/artifacts/${encodeURIComponent(runUid)}/${encodeURIComponent(kind)}`);
    if (!res.ok) throw new Error('Failed to load artifact');
    const data = await res.json();
    container.innerHTML = `
      <div class="panel" style="margin-top:16px;">
        <div class="panel-header">
          <div class="panel-title">Preview: ${escapeHtml(kind)} (${escapeHtml(data.path || '')})</div>
          <button class="btn btn-sm" type="button" data-copy-target="#artifactPreviewBody">Copy</button>
        </div>
        <div class="panel-body" style="padding:14px;">
          <pre id="artifactPreviewBody" style="margin:0; max-height:350px; overflow-y:auto;">${escapeHtml(data.content || '<empty>')}</pre>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="color:var(--red); padding:10px;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ============================================================ Run Selection
// The explorer compares two runs at a time, so two checks are the whole
// budget: once they are spent the rest of the table dims and stops answering
// clicks, rather than offering a third choice the Compare button will refuse.
// The selection is held by uid, so filtering the table neither loses it nor
// silently changes what is about to be compared.
const COMPARISON_SIZE = 2;
const selectedRunUids = new Set();

function applyRunSelectionLimits() {
  const full = selectedRunUids.size >= COMPARISON_SIZE;
  document.querySelectorAll('.run-select-check').forEach((box) => {
    const chosen = selectedRunUids.has(box.value);
    box.checked = chosen;
    box.disabled = full && !chosen;
    const row = box.closest('tr');
    if (row) row.classList.toggle('row-dimmed', full && !chosen);
  });
  renderRunSelectionHint();
}

function renderRunSelectionHint() {
  const hint = document.getElementById('runsSelectionHint');
  if (!hint) return;
  const chosen = Array.from(selectedRunUids);
  if (chosen.length === 0) {
    hint.textContent = 'Tip: select 2 runs to compare side by side';
  } else if (chosen.length === 1) {
    hint.textContent = '1 of 2 selected \u2014 pick one more';
  } else {
    hint.textContent = `Comparing: ${chosen[0]} \u00b7 ${chosen[1]}`;
  }
  hint.classList.toggle('is-armed', chosen.length === COMPARISON_SIZE);
}

function initRunSelectionLimit() {
  const tbody = document.getElementById('runsTableBody');
  if (!tbody) return;

  tbody.addEventListener('change', (event) => {
    const box = event.target.closest('.run-select-check');
    if (!box) return;
    if (box.checked) selectedRunUids.add(box.value);
    else selectedRunUids.delete(box.value);
    applyRunSelectionLimits();
  });

  const reset = document.getElementById('btnResetFilter');
  if (reset) {
    reset.addEventListener('click', () => selectedRunUids.clear());
  }
  applyRunSelectionLimits();
}

// ============================================================ Comparison Helpers
function initCompareHelpers() {
  const compareBtn = document.getElementById('btnCompareSelected');
  if (!compareBtn) return;

  compareBtn.addEventListener('click', () => {
    const checked = Array.from(document.querySelectorAll('.run-select-check:checked')).map(cb => cb.value);
    if (checked.length !== 2) {
      alert('Please select exactly 2 runs to compare side by side.');
      return;
    }
    window.location.href = `/compare?run_a=${encodeURIComponent(checked[0])}&run_b=${encodeURIComponent(checked[1])}`;
  });
}

// ============================================================ Utilities
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '—';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const remS = s % 60;
  if (m < 60) return `${m}m ${remS}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${remM}m`;
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('pl-PL', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return isoStr;
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getScoreColor(score) {
  if (score === null || score === undefined) return 'var(--fg-dim)';
  if (score >= 1.0) return 'var(--mint)';
  if (score >= 0.8) return 'var(--amber)';
  return 'var(--red)';
}


// ============================================================ Run Diff Picker
// The comparison studio offers the same runs in two lists. Choosing either one
// is a complete decision, so the form submits itself; the button stays for the
// keyboard and for anyone who prefers it.
function initRunDiffPicker() {
  const selects = document.querySelectorAll('.run-diff-select');
  if (!selects.length) return;
  const form = selects[0].form;
  if (!form) return;
  selects.forEach((select) => {
    select.addEventListener('change', () => form.submit());
  });
}

// ============================================================ Copy a table out
// A filtered table is an answer to a question, and the reader often wants it
// elsewhere: in a notebook as CSV, in a message as Markdown. The exporter reads
// the table that is on screen, so it exports what the filter selected rather
// than a server-side superset, and skips the columns that only exist to drive
// the page (the comparison checkbox, the Inspect button).
const EXPORT_COLUMNS = [
  { key: 'uid', label: 'run' },
  { key: 'task_uid', label: 'task' },
  { key: 'config_str', label: 'configuration' },
  { key: 'repetition', label: 'repetition' },
  { key: 'verdict', label: 'verdict' },
  { key: 'score', label: 'score' },
  { key: 'duration_seconds', label: 'duration_s' },
  { key: 'total_tokens', label: 'tokens' },
  { key: 'tool_call_count', label: 'tool_calls' },
  { key: 'status', label: 'status' },
  { key: 'started_at', label: 'started_at' },
];

function csvField(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function markdownField(value) {
  return String(value ?? '').replace(/\|/g, '\\|');
}

function tableToCsv(columns, rows) {
  const head = columns.map(column => csvField(column.label)).join(',');
  const body = rows.map(row => columns.map(column => csvField(row[column.key])).join(','));
  return [head, ...body].join('\n');
}

function tableToMarkdown(columns, rows) {
  const head = `| ${columns.map(column => markdownField(column.label)).join(' | ')} |`;
  const rule = `| ${columns.map(() => '---').join(' | ')} |`;
  const body = rows.map(row => `| ${columns.map(column => markdownField(row[column.key])).join(' | ')} |`);
  return [head, rule, ...body].join('\n');
}

// The rows come from the page's own data, not from the rendered cells: a cell
// that shows "1m 30s" would export as that string, and a reader taking the
// table to a notebook wants the numbers behind it.
async function copyRunsTable(format) {
  const runs = await currentRunsForExport();
  const columns = EXPORT_COLUMNS;
  const text = format === 'markdown' ? tableToMarkdown(columns, runs) : tableToCsv(columns, runs);
  copyText(text, format);
}

let exportCache = null;

async function currentRunsForExport() {
  // the same rows the table shows, refetched so a filter that has not been
  // repainted yet cannot export a stale answer
  const form = document.getElementById('runsFilterForm');
  const params = new URLSearchParams();
  if (form) {
    for (const [key, val] of new FormData(form).entries()) {
      if (val) params.append(key, val);
    }
  }
  params.set('limit', '0');
  try {
    const res = await fetch(`/api/runs?${params.toString()}`, { loader: false });
    if (!res.ok) return [];
    const data = await res.json();
    exportCache = data.runs;
    return data.runs;
  } catch (err) {
    console.error('Export failed:', err);
    return exportCache || [];
  }
}

function copyText(text, format) {
  const ok = () => flashCopied(format);
  const fail = () => flashCopied('failed');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(ok, fail);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try { copied = document.execCommand('copy'); } catch { copied = false; }
  area.remove();
  copied ? ok() : fail();
}

function flashCopied(format) {
  const hint = document.getElementById('runsSelectionHint');
  if (!hint) return;
  const original = hint.textContent;
  hint.textContent = format === 'failed'
    ? 'Copy failed — select the table and copy manually'
    : `Copied ${format === 'markdown' ? 'Markdown' : 'CSV'} to clipboard`;
  setTimeout(() => { hint.textContent = original; }, 1800);
}

// ============================================================ Keyboard navigation
// A table read by hand is read with the cursor: up and down move it, Enter
// opens the row it rests on, and / drops straight into the filter search so a
// reader can jump to a run by name. The cursor lives in the page, never in the
// data, so a filter that repaints the table simply starts the cursor at the top.
// It stays out of the way while the keyboard is elsewhere — an input, a select
// or the run inspector — and only the runs table takes the cursor.
const runsKeyNav = { focused: -1, rows: [] };

function runsKeyNavRows() {
  const tbody = document.getElementById('runsTableBody');
  runsKeyNav.rows = tbody
    ? Array.from(tbody.querySelectorAll('tr')).filter(row => row.querySelector('.run-select-check'))
    : [];
  return runsKeyNav.rows;
}

function runsKeyNavClear() {
  runsKeyNav.rows.forEach(row => row.classList.remove('row-focused'));
  runsKeyNav.focused = -1;
}

function runsKeyNavFocus(index) {
  const rows = runsKeyNavRows();
  if (!rows.length) return;
  runsKeyNav.rows.forEach(row => row.classList.remove('row-focused'));
  const next = Math.max(0, Math.min(rows.length - 1, index));
  const row = rows[next];
  row.classList.add('row-focused');
  row.scrollIntoView({ block: 'nearest' });
  runsKeyNav.focused = next;
}

function runsKeyNavModalOpen() {
  const modal = document.getElementById('runDetailModal');
  return modal ? modal.classList.contains('open') : false;
}

function runsKeyNavActive() {
  return document.getElementById('runsFilterForm') !== null && !runsKeyNavModalOpen();
}

function runsKeyNavOnKeydown(event) {
  if (!runsKeyNavActive()) return;
  const key = event.key;
  const target = event.target;
  const editing = target && (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable
  );
  // the keyboard belongs to whatever is being typed into, arrows and all
  if (editing) return;

  // "/" is the way in from anywhere else on the page; once the caret is in the
  // search box it is an ordinary character again
  if (key === '/') {
    const search = document.getElementById('filterSearch');
    if (search) {
      event.preventDefault();
      search.focus();
      search.select();
    }
    return;
  }

  if (key === 'ArrowDown') {
    event.preventDefault();
    runsKeyNavFocus(runsKeyNav.focused + 1);
    return;
  }
  if (key === 'ArrowUp') {
    event.preventDefault();
    runsKeyNavFocus(runsKeyNav.focused - 1);
    return;
  }
  if (key === 'Enter' && runsKeyNav.focused >= 0) {
    const row = runsKeyNav.rows[runsKeyNav.focused];
    const box = row && row.querySelector('.run-select-check');
    if (box) {
      event.preventDefault();
      openRunModal(box.value);
    }
  }
}

function initRunsKeyNav() {
  document.addEventListener('keydown', runsKeyNavOnKeydown);
}

// ============================================================ Theme
// The palette is a list of variables the pages already read, so switching the
// theme is a swap of that list and not a repaint of anything: the attribute on
// the root element decides which block of values wins. The choice is stored
// under one key and read back before the sheet paints (base.html), so a page
// never opens in the wrong palette. Charts are the one exception — they draw
// into a canvas and cannot read a variable — so they are asked to redraw.
const THEME_KEY = 'akbench_theme';

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
  return {
    text: read('--chart-tx', '#c6d3df'),
    dim: read('--chart-dim', '#8d9daf'),
    grid: read('--chart-grid', 'rgba(255,255,255,0.06)'),
  };
}

window.akbenchThemeColors = themeColors;

function paintThemeToggle(button) {
  if (!button) return;
  const light = currentTheme() === 'light';
  const label = button.querySelector('.theme-toggle-label');
  const icon = button.querySelector('.theme-toggle-icon');
  if (label) label.textContent = light ? 'Light' : 'Dark';
  if (icon) icon.textContent = light ? '\u2600' : '\u263d';
}

function setTheme(theme) {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (err) { /* nowhere to remember it; the theme still switches for this page */ }
  paintThemeToggle(document.getElementById('themeToggle'));
  // canvases keep the colours they were drawn with, so they are rebuilt
  document.dispatchEvent(new CustomEvent('akbench:theme'));
}

function initThemeToggle() {
  const button = document.getElementById('themeToggle');
  if (!button) return;
  paintThemeToggle(button);
  button.addEventListener('click', () => {
    setTheme(currentTheme() === 'light' ? 'dark' : 'light');
  });
}

// ============================================================ Run score sparkline
// One run's score is a single number; what a reader needs beside it is the
// history it came out of — the same task under the same configuration, run
// again and again — and where the declared baseline sits in that history.
//
// A cell carries the series as data attributes and this fills it with a small
// inline SVG: a line for the history, a dashed line for the baseline, a dot
// for the run the row is about. Both the server-rendered rows and the ones the
// filter paints carry the same attributes, so there is one renderer.
const SPARK_WIDTH = 84;
const SPARK_HEIGHT = 22;

function sparkCell(run) {
  const points = (run.trend_points || [])
    .map(value => (value === null || value === undefined ? '' : Number(value).toFixed(4)))
    .join(',');
  const baseline = run.baseline_score === null || run.baseline_score === undefined
    ? ''
    : Number(run.baseline_score).toFixed(4);
  const index = run.trend_index === null || run.trend_index === undefined ? '' : run.trend_index;
  return `<span class="spark" data-points="${points}" data-index="${index}" data-baseline="${baseline}"></span>`;
}

function renderSparkline(element) {
  const raw = (element.dataset.points || '').split(',').filter(s => s.length);
  if (raw.length < 2) return;
  const points = raw.map(Number);
  const index = Number(element.dataset.index);
  const baseline = element.dataset.baseline === '' ? null : Number(element.dataset.baseline);
  const own = Number.isFinite(index) ? points[index] : null;

  const x = (i) => (points.length === 1 ? SPARK_WIDTH / 2 : (i * (SPARK_WIDTH - 4)) / (points.length - 1) + 2);
  const y = (value) => SPARK_HEIGHT - 2 - value * (SPARK_HEIGHT - 4);

  const parts = [];
  if (baseline !== null && Number.isFinite(baseline)) {
    parts.push(`<line x1="0" y1="${y(baseline).toFixed(1)}" x2="${SPARK_WIDTH}" y2="${y(baseline).toFixed(1)}" class="spark-baseline"/>`);
  }
  const path = points.map((value, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
  parts.push(`<path d="${path}" class="spark-line"/>`);
  if (own !== null && Number.isFinite(own)) {
    parts.push(`<circle cx="${x(index).toFixed(1)}" cy="${y(own).toFixed(1)}" r="2.6" class="spark-dot"/>`);
  }

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`);
  svg.setAttribute('width', SPARK_WIDTH);
  svg.setAttribute('height', SPARK_HEIGHT);
  svg.classList.add('spark');
  if (own !== null && Number.isFinite(own)) {
    const verdict = baseline === null || !Number.isFinite(baseline)
      ? 'own'
      : (own >= baseline ? 'above' : 'below');
    svg.classList.add(`spark-${verdict}`);
    svg.dataset.score = own.toFixed(3);
    if (baseline !== null && Number.isFinite(baseline)) {
      svg.dataset.baseline = baseline.toFixed(3);
    }
  }
  svg.innerHTML = parts.join('');
  element.replaceChildren(svg);
  element.dataset.drawn = 'yes';
}

function initSparklines(root) {
  (root || document).querySelectorAll('.spark-cell .spark:not([data-drawn])')
    .forEach(renderSparkline);
}

// ============================================================ YAML colouring
// A descriptor is read for its keys, so the keys are what the eye should find
// first. The colouring is deliberately small: a comment, a key, a value, a
// list dash — nothing that would rewrite what the file says.
//
// Text is coloured after it has been escaped and only outside of it is touched,
// so a descriptor containing markup cannot inject anything into the page.
function highlightYaml(text) {
  const escaped = escapeHtml(text);
  return escaped
    .split('\n')
    .map((line) => {
      // a whole-line comment keeps its own colour and ends the line
      const comment = line.match(/^(\s*)(#.*)$/);
      if (comment) {
        return `${comment[1]}<span class="yaml-comment">${comment[2]}</span>`;
      }
      const entry = line.match(/^(\s*(?:-\s+)?)([\w.\-]+)(:\s?)(.*)$/);
      if (entry) {
        const [, lead, key, colon, rest] = entry;
        return `${lead}<span class="yaml-key">${key}</span>${colon}${highlightYamlValue(rest)}`;
      }
      const dash = line.match(/^(\s*)-(\s+)(.*)$/);
      if (dash) {
        return `${dash[1]}<span class="yaml-dash">-${dash[2]}</span>${highlightYamlValue(dash[3])}`;
      }
      return line;
    })
    .join('\n');
}

function highlightYamlValue(raw) {
  const value = raw ?? '';
  if (!value.trim()) return value;
  // a trailing comment keeps its own colour
  const split = value.match(/^(\s*[^#]*?)(\s+)(#.*)$/);
  const head = split ? split[1] : value;
  const tail = split ? `${split[2]}<span class="yaml-comment">${split[3]}</span>` : '';
  if (/^(['"]).*$1$/.test(head)) return `<span class="yaml-string">${head}</span>${tail}`;
  if (/^(true|false|null|~|yes|no|on|off)$/i.test(head)) return `<span class="yaml-bool">${head}</span>${tail}`;
  if (/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(head)) return `<span class="yaml-number">${head}</span>${tail}`;
  return `<span class="yaml-scalar">${head}</span>${tail}`;
}

function initYamlHighlighting() {
  document.querySelectorAll('pre.yaml-block').forEach((block) => {
    if (block.dataset.highlighted === 'yes') return;
    block.dataset.highlighted = 'yes';
    block.innerHTML = highlightYaml(block.textContent);
  });
}

// ============================================================ Copy to clipboard
// Every place that shows code or a descriptor gets a Copy beside it: reading a
// value out of a <pre> by dragging through it is the work the button removes.
// The button reads the text of the block it is told to copy, so it always hands
// over what is on screen — including a block that is still loading.
function initCopyButtons() {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-copy-target]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const source = document.querySelector(button.dataset.copyTarget);
    if (!source) return;
    const text = source.tagName === 'INPUT' || source.tagName === 'TEXTAREA'
      ? source.value
      : source.textContent;
    const done = (ok) => {
      const label = button.textContent;
      button.textContent = ok ? 'Copied' : 'Copy failed';
      button.disabled = true;
      setTimeout(() => { button.textContent = label; button.disabled = false; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
    } else {
      // the fallback a page served over http:// still needs
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      area.remove();
      done(ok);
    }
  });
}

// ============================================================ Task Code Tree
// A task page lists the files recorded with the task. Clicking one asks the
// API for its content and shows it in the viewer under the groups; the text is
// inserted as text, never parsed as markup, because it is the task's own code.
function initTaskCodeTree() {
  const tree = document.querySelector('.task-code');
  if (!tree) return;
  const viewer = document.getElementById('codeViewer');
  const pathLabel = document.getElementById('codeViewerPath');
  const body = document.getElementById('codeViewerBody');
  const close = document.getElementById('codeViewerClose');
  if (!viewer || !body) return;

  tree.addEventListener('click', async (event) => {
    const button = event.target.closest('.tree-file');
    if (!button) return;
    event.preventDefault();
    const taskUid = button.dataset.task;
    const filePath = button.dataset.path;
    if (!taskUid || !filePath) return;

    const active = tree.querySelector('.tree-file.active');
    if (active) active.classList.remove('active');
    button.classList.add('active');

    pathLabel.textContent = filePath;
    body.textContent = 'Loading…';
    viewer.hidden = false;
    try {
      const response = await fetch(
        `/api/tasks/${encodeURIComponent(taskUid)}/files/${filePath
          .split('/')
          .map(encodeURIComponent)
          .join('/')}`
      );
      if (!response.ok) throw new Error('not recorded');
      const data = await response.json();
      body.textContent = data.content;
    } catch (error) {
      body.textContent = 'This file was not recorded with the task.';
    }
  });

  if (close) {
    close.addEventListener('click', () => {
      viewer.hidden = true;
      body.textContent = '';
      const active = tree.querySelector('.tree-file.active');
      if (active) active.classList.remove('active');
    });
  }
}

// ============================================================ Sortable Tables
// A header carrying `data-sortable` sorts its column on click: first click
// ascending, second descending, third back to the order the page rendered.
// The value is read from the cell's `data-sort-value` when it has one (a
// formatted cell like "1m 30s" keeps its own number beside the text), and
// otherwise from the cell's leading text. Numbers and timestamps compare as
// numbers, everything else as text.
//
// `window.akbenchSortTables()` re-arms the headers of tables rendered after
// load (the analytics tables), and is idempotent.
function initSortableTables(root) {
  const scope = root || document;
  const tables = scope.matches && scope.matches('table')
    ? [scope]
    : Array.from(scope.querySelectorAll('table'));
  tables.forEach((table) => {
    if (table.dataset.sortable === 'off' || table.dataset.sortReady === 'yes') return;
    const headers = Array.from(table.querySelectorAll('thead th[data-sortable]'));
    if (!headers.length) return;
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    table.dataset.sortReady = 'yes';

    const state = { index: -1, ascending: true, original: null };

    const cellValue = (row, index) => {
      const cell = row.cells[index];
      if (!cell) return '';
      const explicit = cell.dataset.sortValue;
      if (explicit !== undefined) return explicit;
      // The cell's own text is what sorts: a badge or a bar beside it must not
      // pull the sort after itself. Whitespace is not a value — a cell whose
      // number lives inside a span has no own text and falls back to the text
      // it shows, or its column would sort on nothing at all.
      let text = '';
      cell.childNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
      });
      return text.trim() || (cell.textContent || '').trim();
    };

    const parseValue = (raw) => {
      const text = String(raw).trim();
      if (text === '' || text === '—' || text === '-') return { numeric: true, value: Number.NEGATIVE_INFINITY };
      const asNumber = Number(text.replace(/,/g, ''));
      if (Number.isFinite(asNumber) && /^-?\d[\d,]*\.?\d*[\w%]*$/.test(text)) {
        return { numeric: true, value: asNumber };
      }
      const asDate = Date.parse(text);
      if (!Number.isNaN(asDate) && /\d{4}-\d{2}-\d{2}/.test(text)) {
        return { numeric: true, value: asDate };
      }
      return { numeric: false, value: text.toLowerCase() };
    };

    // The order the page rendered, captured once per table body: the third
    // click restores the order the query asked for rather than an accident of
    // the last sort. A body that has been repainted (its rows are no longer
    // the ones captured) is captured again.
    const remembered = () => {
      const rows = Array.from(tbody.rows);
      if (!state.original || state.original.length !== rows.length
          || (rows.length && state.original[0] !== rows[0]
              && !state.original.includes(rows[0]))) {
        state.original = rows;
      }
      return state.original;
    };

    const sort = (index, ascending, rows) => {
      rows = rows.slice();
      rows.sort((a, b) => {
        const av = parseValue(cellValue(a, index));
        const bv = parseValue(cellValue(b, index));
        if (av.numeric !== bv.numeric) return av.numeric ? -1 : 1;
        const compared = av.numeric
          ? av.value - bv.value
          : av.value.localeCompare(bv.value);
        return ascending ? compared : -compared;
      });
      rows.forEach((row) => tbody.appendChild(row));
    };


    const clearIndicators = () => {
      headers.forEach((th) => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        th.removeAttribute('aria-sort');
      });
    };

    headers.forEach((th, index) => {
      th.tabIndex = 0;
      th.setAttribute('role', 'columnheader button');
      const activate = () => {
        const recorded = remembered();
        if (state.index === index) {
          state.ascending = !state.ascending;
        } else {
          state.index = index;
          state.ascending = true;
        }
        clearIndicators();
        th.classList.add(state.ascending ? 'sorted-asc' : 'sorted-desc');
        th.setAttribute('aria-sort', state.ascending ? 'ascending' : 'descending');
        sort(index, state.ascending, Array.from(tbody.rows));
      };

      const reset = () => {
        state.index = -1;
        state.ascending = true;
        clearIndicators();
        remembered().forEach((row) => tbody.appendChild(row));
      };
      th.title = 'Sort by ' + th.textContent.trim();
      th.addEventListener('click', activate);
      th.addEventListener('dblclick', reset);
      th.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate();
        }
        if (event.key === 'Escape') reset();
      });
    });
  });
}

// Tables rendered after the page loaded (the analytics tables) arm themselves
// through this global; it is idempotent per table, so calling it again after a
// repaint costs nothing.
window.akbenchSortTables = initSortableTables;

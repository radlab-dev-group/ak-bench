// AK-Bench Failure Analysis: cross-run aggregation of what failed and why.
// Rows arrive precomputed (pooled and per configuration) from /api/failures/data;
// this page filters, sorts and draws them — it computes no statistics of its own,
// so a filtered view shows the same intervals the server measured.
(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let DATA = null;
  const state = { config: '', category: '', minRuns: 1, showPassed: false, query: '' };
  const TESTS_SHOWN = 25;
  let testsExpanded = false;

  function fmtPct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; }
  function fmtNum(v) { return v == null ? '—' : Number(v).toLocaleString(); }
  function verdictBadge(v) {
    const cls = v === 'passed' ? 'badge-passed' : v === 'partial' ? 'badge-partial'
      : v === 'failed' ? 'badge-failed' : v === 'error' ? 'badge-error' : 'badge-neutral';
    return `<span class="badge ${cls}">${esc(v || 'unverified')}</span>`;
  }
  function runsLink(taskUid, variantUid) {
    const params = new URLSearchParams({ task_uid: taskUid });
    if (variantUid) params.set('variant_uid', variantUid);
    return `/runs?${params}`;
  }

  function matchesQuery(fields) {
    const q = state.query.trim().toLowerCase();
    if (!q) return true;
    const hay = fields.filter(Boolean).join(' ').toLowerCase();
    return q.split(/\s+/).every(word => hay.includes(word));
  }

  // A rate as a bar: the number alone is read as a grade, the bar as a distance
  // from "always" and "never", which is what a rate is. The band colour asks
  // the same question from the other side — a high pass rate is good, a high
  // fail rate is not.
  function rateCell(rate, kind, extraTitle) {
    const pct = rate == null ? 0 : rate * 100;
    const band = rate == null ? 'fl-fill-neutral'
      : kind === 'fail'
        ? (rate >= 0.5 ? 'fl-fill-red' : rate >= 0.2 ? 'fl-fill-amber' : 'fl-fill-mint')
        : (rate >= 0.8 ? 'fl-fill-mint' : rate >= 0.4 ? 'fl-fill-amber' : 'fl-fill-red');
    const title = extraTitle ? ` title="${esc(extraTitle)}"` : '';
    return `<td data-sort-value="${rate == null ? '' : rate}"${title}>` +
      `<div class="fl-rate"><div class="fl-rate-fill ${band}" style="width:${pct.toFixed(1)}%"></div>` +
      `<span class="fl-rate-label">${fmtPct(rate)}</span></div></td>`;
  }

  function ciCell(low, high) {
    const text = low == null || high == null ? '—' : `${fmtPct(low)} – ${fmtPct(high)}`;
    return `<td class="mono" style="font-size:11.5px; color:var(--fg-faint);" data-sort-value="${low == null ? '' : low}">${text}</td>`;
  }

  function verdictMixCell(verdicts, evaluated) {
    const entries = Object.entries(verdicts || {});
    const segs = entries.map(([v, n], i) => {
      const w = evaluated ? (n / evaluated * 100) : 0;
      const cls = v === 'passed' ? 'fl-seg-passed' : v === 'partial' ? 'fl-seg-partial'
        : v === 'failed' ? 'fl-seg-failed' : v === 'error' ? 'fl-seg-error' : 'fl-seg-neutral';
      return `<div class="fl-seg ${cls}" style="width:${w.toFixed(2)}%" title="${esc(v)}: ${n}"></div>`;
    }).join('');
    return `<td data-sort-value="${verdicts.passed ?? ''}"><div class="fl-verdicts">${segs}</div></td>`;
  }

  function taskCell(row) {
    return `<td><a href="/tasks/${encodeURIComponent(row.task_uid)}" class="mono" style="font-weight:600;">${esc(row.task_uid)}</a>` +
      (row.title ? `<div style="font-size:12px; color:var(--fg-dim); max-width:340px;">${esc(row.title)}</div>` : '') +
      `</td>`;
  }

  function configCell(row) {
    return `<td class="mono" style="font-size:11.5px; color:var(--fg-dim);">${esc(row.config_str || 'all configurations')}</td>`;
  }

  // ------------------------------------------------------------------ KPIs
  function renderKpis() {
    const s = DATA.summary;
    const k = (cls, t, v, sub) => `<div class="card ${cls}"><div class="card-title">${t}</div><div class="card-value">${v}</div><div class="card-sub">${sub}</div></div>`;
    const top = DATA.failure_classes[0];
    $('flKpis').innerHTML =
      k('card-blue', 'Runs evaluated', `${fmtNum(s.evaluated)} / ${fmtNum(s.runs)}`, `not passed: ${fmtNum(s.not_passed)}`) +
      k('card-amber', 'Tasks with failures', fmtNum(s.tasks_with_failures), 'at least one non-pass') +
      k('card-amber', 'Contradictory pairs', fmtNum(s.flaky_pairs), 'same task + config, mixed verdicts') +
      k('', 'Failing tests', fmtNum(s.failing_tests), 'distinct tests that failed somewhere') +
      k('', 'Top failure class', top ? esc(top.failure_class || top.status || 'unclassified') : '—',
        top ? `${fmtNum(top.count)} run(s) · ${esc(top.status || 'no status')}` : 'nothing to classify');
  }

  // ------------------------------------------------------------ hardest tasks
  function taskRows() {
    return DATA.tasks.filter(row => {
      if (state.config === '' ? row.config_str !== null : row.config_str !== state.config) return false;
      if (state.category && row.category !== state.category) return false;
      if (row.evaluated < state.minRuns) return false;
      if (!state.showPassed && row.passed >= row.evaluated) return false;
      return matchesQuery([row.task_uid, row.title, row.category, row.difficulty, row.config_str]);
    });
  }

  function renderTasks() {
    const rows = taskRows();
    $('flTasksCount').textContent = `${rows.length} task(s)`;
    if (!rows.length) {
      $('flTasks').innerHTML = emptyState('No task matches this slice — or nothing has failed in it.');
      return;
    }
    $('flTasks').innerHTML = `<table class="table-wide">
      <thead><tr>
        <th data-sortable>Task</th><th data-sortable>Category</th><th data-sortable>Difficulty</th>
        <th data-sortable>Configuration</th>
        <th data-sortable class="num">Evaluated</th><th data-sortable class="num">Passed</th>
        <th data-sortable>Pass rate</th><th data-sortable>95% interval</th><th>Verdicts</th><th>Runs</th>
      </tr></thead>
      <tbody>${rows.map(row => `<tr>
        ${taskCell(row)}
        <td><span class="badge badge-info">${esc(row.category || 'general')}</span></td>
        <td><span class="badge badge-neutral">${esc(row.difficulty || '—')}</span></td>
        ${configCell(row)}
        <td class="num mono" data-sort-value="${row.evaluated}">${fmtNum(row.evaluated)}</td>
        <td class="num mono" data-sort-value="${row.passed}">${fmtNum(row.passed)}</td>
        ${rateCell(row.pass_rate, 'pass')}
        ${ciCell(row.ci_low, row.ci_high)}
        ${verdictMixCell(row.verdicts, row.evaluated)}
        <td><a class="btn btn-sm" href="${runsLink(row.task_uid, row.variant_uid)}">Open</a></td>
      </tr>`).join('')}</tbody></table>`;
  }

  // ------------------------------------------------------------------- flaky
  function flakyRows() {
    return DATA.flaky.filter(row => {
      if (state.config && row.config_str !== state.config) return false;
      if (state.category && row.category !== state.category) return false;
      if (row.evaluated < state.minRuns) return false;
      return matchesQuery([row.task_uid, row.title, row.category, row.config_str]);
    });
  }

  function renderFlaky() {
    const rows = flakyRows();
    $('flFlakyCount').textContent = `${rows.length} pair(s)`;
    if (!rows.length) {
      $('flFlaky').innerHTML = emptyState('No repetition contradicts another here: every repeated task under one configuration gave one verdict.');
      return;
    }
    $('flFlaky').innerHTML = `<table class="table-wide">
      <thead><tr>
        <th data-sortable>Task</th><th data-sortable>Configuration</th>
        <th data-sortable class="num">Evaluated</th><th data-sortable class="num">Passed</th>
        <th data-sortable>Pass rate</th><th>Verdicts in order</th><th>Runs</th>
      </tr></thead>
      <tbody>${rows.map(row => `<tr>
        ${taskCell(row)}
        ${configCell(row)}
        <td class="num mono" data-sort-value="${row.evaluated}">${fmtNum(row.evaluated)}</td>
        <td class="num mono" data-sort-value="${row.passed}">${fmtNum(row.passed)}</td>
        ${rateCell(row.pass_rate, 'pass')}
        <td><div class="fl-seq">${row.sequence.map(run => {
          const ok = run.verdict === 'passed';
          const when = (run.started_at || '').slice(0, 16).replace('T', ' ');
          return `<span class="fl-seq-item ${ok ? 'fl-seq-pass' : 'fl-seq-fail'}" title="${esc(run.uid)} · ${esc(when)} · ${esc(run.verdict || 'unverified')}">${ok ? '✓' : '✗'}</span>`;
        }).join('')}</div></td>
        <td><a class="btn btn-sm" href="${runsLink(row.task_uid, row.variant_uid)}">Open</a></td>
      </tr>`).join('')}</tbody></table>`;
  }

  // ------------------------------------------------------------------- tests
  function testRows() {
    return DATA.tests.filter(row => {
      if (state.config === '' ? row.config_str !== null : row.config_str !== state.config) return false;
      return matchesQuery([row.name, row.classname, row.task_uid, row.title, row.config_str]);
    });
  }

  function renderTests() {
    const rows = testRows();
    $('flTestsCount').textContent = `${rows.length} test(s)`;
    if (!rows.length) {
      $('flTests').innerHTML = emptyState('No failing test here — either every run passed, or no evaluator wrote a JUnit report.');
      return;
    }
    const shown = testsExpanded ? rows : rows.slice(0, TESTS_SHOWN);
    const more = rows.length > TESTS_SHOWN
      ? `<div style="padding:12px 14px;"><button class="btn btn-sm" id="flTestsToggle">${testsExpanded ? 'Show top ' + TESTS_SHOWN : 'Show all ' + rows.length}</button></div>`
      : '';
    $('flTests').innerHTML = `<table class="table-wide">
      <thead><tr>
        <th data-sortable>Test</th><th data-sortable>Task</th><th data-sortable>Configuration</th>
        <th data-sortable class="num">Failed runs</th><th data-sortable class="num">Tested runs</th>
        <th data-sortable>Fail rate</th><th>Examples</th>
      </tr></thead>
      <tbody>${shown.map(row => `<tr>
        <td><div class="mono fl-test-name" title="${esc(row.classname ? row.classname + ' :: ' + row.name : row.name)}">${esc(row.name)}</div>
          ${row.classname ? `<div style="font-size:11px; color:var(--fg-faint);" class="mono">${esc(row.classname)}</div>` : ''}
          ${row.detail ? `<div class="fl-test-detail" title="${esc(row.detail)}">${esc(row.detail)}</div>` : ''}</td>
        <td>${row.title ? `<div style="max-width:260px;">${esc(row.title)}</div>` : ''}<span class="mono" style="font-size:11px; color:var(--fg-faint);">${esc(row.task_uid)}</span></td>
        ${configCell(row)}
        <td class="num mono" data-sort-value="${row.failed_runs}">${fmtNum(row.failed_runs)}</td>
        <td class="num mono" data-sort-value="${row.tested_runs}">${fmtNum(row.tested_runs)}</td>
        ${rateCell(row.fail_rate, 'fail')}
        <td>${(row.examples || []).map(uid => `<a class="btn btn-sm" style="margin:1px;" href="/runs?search=${encodeURIComponent(uid)}" title="open run ${esc(uid)}">${esc(String(uid).slice(0, 8))}</a>`).join('')}</td>
      </tr>`).join('')}</tbody></table>${more}`;
    const toggle = $('flTestsToggle');
    if (toggle) toggle.addEventListener('click', () => { testsExpanded = !testsExpanded; renderTests(); armSort(); });
  }

  // --------------------------------------------------------- failure classes
  function renderClasses() {
    const rows = DATA.failure_classes;
    if (!rows.length) {
      $('flClasses').innerHTML = emptyState('No harness-level failure: every run either passed or was evaluated against its task.');
      return;
    }
    const max = rows[0].count || 1;
    $('flClasses').innerHTML = rows.map(row => `
      <div class="fl-class-row">
        <div class="fl-class-bar"><div class="fl-class-fill" style="width:${(row.count / max * 100).toFixed(1)}%"></div></div>
        <div class="fl-class-label">${verdictBadge(row.failure_class || row.status || 'unclassified')}
          ${row.failure_class && row.status ? `<span class="badge badge-neutral">${esc(row.status)}</span>` : ''}</div>
        <div class="fl-class-count mono" data-count="${row.count}">${fmtNum(row.count)}</div>
        <div class="fl-class-example">
          ${row.example_error ? `<span class="mono fl-test-detail" title="${esc(row.example_error)}">${esc(row.example_error)}</span>` : ''}
          ${row.example_run_uid ? `<a class="btn btn-sm" href="/runs?search=${encodeURIComponent(row.example_run_uid)}">run</a>` : ''}
        </div>
      </div>`).join('');
  }

  function emptyState(text) {
    return `<div class="fl-empty">${esc(text)}</div>`;
  }

  function armSort() {
    if (window.akbenchSortTables) window.akbenchSortTables();
  }

  function render() {
    renderKpis();
    renderTasks();
    renderFlaky();
    renderTests();
    renderClasses();
    armSort();
    const s = DATA.summary;
    $('flCount').textContent = `${fmtNum(s.not_passed)} not passed / ${fmtNum(s.runs)} runs`;
  }

  // --------------------------------------------------------------- controls
  function fillSelect(el, items, value, allLabel) {
    el.innerHTML = `<option value="">${esc(allLabel)}</option>` +
      items.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    el.value = value;
  }

  function buildControls() {
    fillSelect($('flConfig'), DATA.configs, state.config, 'all configurations');
    fillSelect($('flCategory'), DATA.categories, state.category, 'all categories');
    $('flConfig').addEventListener('change', e => { state.config = e.target.value; render(); });
    $('flCategory').addEventListener('change', e => { state.category = e.target.value; render(); });
    $('flMinRuns').addEventListener('change', e => { state.minRuns = Number(e.target.value) || 1; render(); });
    $('flShowPassed').addEventListener('change', e => { state.showPassed = e.target.value === 'show'; render(); });
    let searchTimer = null;
    $('flSearch').addEventListener('input', e => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.query = e.target.value; render(); }, 150);
    });
  }

  fetch('/api/failures/data')
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      DATA = data;
      buildControls();
      render();
    })
    .catch(err => {
      $('flKpis').innerHTML = `<div class="card"><div class="card-title">The failure data could not be read</div><div class="card-sub">${esc(err.message)}</div></div>`;
    });
})();

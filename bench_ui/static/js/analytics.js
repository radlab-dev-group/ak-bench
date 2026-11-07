// AK-Bench Analytics Explorer: client-side grouping, filtering and many chart types.
(() => {
  const PALETTE = ['#00e59b', '#5aa9ff', '#ffb44a', '#c792ea', '#ff6b7a', '#4dd0e1', '#f0e68c', '#ff8a65', '#9ccc65', '#ba68c8', '#7986cb', '#e57373'];
  const TXT = '#c6d3df', DIM = '#8d9daf', GRID = 'rgba(255,255,255,0.06)';
  const MONO = 'ui-monospace, monospace';

  const METRICS = {
    score: { label: 'Score', get: r => r.score, fmt: v => v.toFixed(3) },
    pass: { label: 'Pass (1/0)', get: r => (r.verdict === 'passed' ? 1 : 0), fmt: v => (v * 100).toFixed(1) + '%' },
    duration: { label: 'Duration (s)', get: r => r.duration_seconds, fmt: fmtDur },
    total_tokens: { label: 'Total tokens', get: r => r.total_tokens, fmt: fmtNum },
    input_tokens: { label: 'Input tokens', get: r => r.input_tokens, fmt: fmtNum },
    cached_input_tokens: { label: 'Cached input tokens', get: r => r.cached_input_tokens, fmt: fmtNum },
    output_tokens: { label: 'Output tokens', get: r => r.output_tokens, fmt: fmtNum },
    tool_call_count: { label: 'Tool calls', get: r => r.tool_call_count, fmt: v => v.toFixed(1) },
    passed_tests: { label: 'Passed tests', get: r => r.passed_tests, fmt: v => v.toFixed(1) },
    failed_tests: { label: 'Failed tests', get: r => r.failed_tests, fmt: v => v.toFixed(1) },
    cache_ratio: { label: 'Cache hit ratio', get: r => (r.input_tokens ? (r.cached_input_tokens || 0) / r.input_tokens : null), fmt: v => (v * 100).toFixed(1) + '%' },
    tokens_per_s: { label: 'Tokens / s', get: r => (r.duration_seconds ? (r.total_tokens || 0) / r.duration_seconds : null), fmt: fmtNum },
  };

  let DATA = { rows: [], param_keys: [] };

  // Every chart spins while the data is on its way, then the overlay is torn
  // down the moment its chart has been drawn.
  function armSpinners() {
    document.querySelectorAll('.an-chart:not(.has-spinner)').forEach(el => {
      const spin = document.createElement('div');
      spin.className = 'an-chart-loading';
      spin.innerHTML = '<div class="an-spin"></div><span>loading…</span>';
      el.appendChild(spin);
      el.classList.add('has-spinner');
    });
  }
  function clearSpinners() {
    document.querySelectorAll('.an-chart .an-chart-loading').forEach(el => el.remove());
    document.querySelectorAll('.an-chart.has-spinner').forEach(el => el.classList.remove('has-spinner'));
  }
  let DIMS = {};
  const charts = {};
  const state = { group: 'config_str', split: '', metric: 'score', x: 'total_tokens', y: 'score', sort: 'metric_desc', agg: 'mean', filters: {} };

  function fmtNum(v) { return v == null ? '—' : Math.round(v).toLocaleString(); }
  function fmtDur(v) { if (v == null) return '—'; const s = Math.round(v); return s < 60 ? s + 's' : Math.floor(s / 60) + 'm ' + (s % 60) + 's'; }
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = id => document.getElementById(id);

  function buildDims() {
    DIMS = {
      config_str: { label: 'Configuration', get: r => r.config_str || r.variant_uid || '—' },
      task_uid: { label: 'Task', get: r => r.task_uid || '—' },
      model: { label: 'Model', get: r => r.model || '—' },
      agent: { label: 'Agent', get: r => r.agent || '—' },
      experiment_uid: { label: 'Experiment', get: r => r.experiment_uid || '—' },
      variant_uid: { label: 'Variant', get: r => r.variant_uid || '—' },
      verdict: { label: 'Verdict', get: r => r.verdict || '—' },
      status: { label: 'Status', get: r => r.status || '—' },
      category: { label: 'Task category', get: r => r.category || '—' },
      difficulty: { label: 'Task difficulty', get: r => r.difficulty || '—' },
      day: { label: 'Day', get: r => (r.started_at || '').slice(0, 10) || '—' },
      hour: { label: 'Hour of day', get: r => (r.started_at || '').slice(11, 13) || '—' },
    };
    DATA.param_keys.forEach(k => { DIMS['p:' + k] = { label: 'Param: ' + k, get: r => (r.params || {})[k] ?? '—' }; });
  }

  function fillSelect(el, items, value, allowNone) {
    el.innerHTML = (allowNone ? '<option value="">— none —</option>' : '') +
      items.map(([k, l]) => `<option value="${esc(k)}">${esc(l)}</option>`).join('');
    el.value = value;
  }

  function buildControls() {
    const dimItems = Object.entries(DIMS).map(([k, v]) => [k, v.label]);
    const metItems = Object.entries(METRICS).map(([k, v]) => [k, v.label]);
    fillSelect($('anGroup'), dimItems, state.group);
    fillSelect($('anSplit'), dimItems, state.split, true);
    fillSelect($('anMetric'), metItems, state.metric);
    fillSelect($('anX'), metItems, state.x);
    fillSelect($('anY'), metItems, state.y);
    $('anSort').value = state.sort;
    $('anAgg').value = state.agg;
    [['anGroup', 'group'], ['anSplit', 'split'], ['anMetric', 'metric'], ['anX', 'x'], ['anY', 'y'], ['anSort', 'sort'], ['anAgg', 'agg']]
      .forEach(([id, key]) => $(id).addEventListener('change', e => { state[key] = e.target.value; saveHash(); render(); }));
  }

  function buildFilters() {
    const keys = ['experiment_uid', 'config_str', 'task_uid', 'model', 'agent', 'verdict', 'status', 'category', 'difficulty']
      .concat(DATA.param_keys.map(k => 'p:' + k));
    const box = $('anFilters');
    box.innerHTML = '';
    keys.forEach(k => {
      const vals = [...new Set(DATA.rows.map(DIMS[k].get))].sort();
      if (vals.length < 2) return;
      const sel = state.filters[k] || [];
      const det = document.createElement('details');
      det.className = 'an-filter';
      det.innerHTML = `<summary>${esc(DIMS[k].label)} <span class="badge badge-neutral" data-badge="${esc(k)}">${sel.length ? sel.length + '/' + vals.length : 'all'}</span></summary>
        <div class="an-filter-body">${vals.map(v => `<label title="${esc(v)}"><input type="checkbox" data-k="${esc(k)}" value="${esc(v)}" ${!sel.length || sel.includes(v) ? 'checked' : ''}> <span>${esc(v)}</span></label>`).join('')}
        <div class="an-filter-actions"><a href="javascript:void(0)" data-all="${esc(k)}">all</a> · <a href="javascript:void(0)" data-none="${esc(k)}">none</a></div></div>`;
      box.appendChild(det);
    });
    if (box.dataset.bound) return;
    box.dataset.bound = '1';
    box.addEventListener('change', e => {
      const k = e.target.dataset.k; if (!k) return;
      collectFilter(k); saveHash(); render();
    });
    box.addEventListener('click', e => {
      const k = e.target.dataset.all || e.target.dataset.none; if (!k) return;
      box.querySelectorAll(`input[data-k="${CSS.escape(k)}"]`).forEach(i => { i.checked = !!e.target.dataset.all; });
      collectFilter(k); saveHash(); render();
    });
  }

  function collectFilter(k) {
    const inputs = [...document.querySelectorAll(`input[data-k="${CSS.escape(k)}"]`)];
    const checked = inputs.filter(i => i.checked).map(i => i.value);
    state.filters[k] = checked.length === inputs.length ? [] : (checked.length ? checked : ['\u0000none']);
    const b = document.querySelector(`[data-badge="${CSS.escape(k)}"]`);
    if (b) b.textContent = state.filters[k].length ? `${checked.length}/${inputs.length}` : 'all';
  }

  function filtered() {
    return DATA.rows.filter(r => Object.entries(state.filters).every(([k, vals]) => !vals.length || vals.includes(DIMS[k].get(r))));
  }

  // ----------------------------------------------------------- stats
  const nums = (rows, fn) => rows.map(fn).filter(v => v != null && !isNaN(v));
  function agg(vals, how) {
    if (!vals.length) return null;
    switch (how) {
      case 'sum': return vals.reduce((a, b) => a + b, 0);
      case 'min': return Math.min(...vals);
      case 'max': return Math.max(...vals);
      case 'median': { const s = [...vals].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
      default: return vals.reduce((a, b) => a + b, 0) / vals.length;
    }
  }
  const mean = v => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : null);
  const std = v => { if (v.length < 2) return 0; const m = mean(v); return Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1)); };

  function groupRows(rows, dim) {
    const m = new Map();
    rows.forEach(r => { const k = DIMS[dim].get(r); if (!m.has(k)) m.set(k, []); m.get(k).push(r); });
    return m;
  }

  function groupStats(rows) {
    const sc = nums(rows, METRICS.score.get), du = nums(rows, METRICS.duration.get), tk = nums(rows, METRICS.total_tokens.get);
    return {
      n: rows.length,
      pass: mean(nums(rows, METRICS.pass.get)),
      score: mean(sc), scoreStd: std(sc),
      dur: mean(du), tok: mean(tk),
      inp: mean(nums(rows, METRICS.input_tokens.get)), cached: mean(nums(rows, METRICS.cached_input_tokens.get)),
      out: mean(nums(rows, METRICS.output_tokens.get)), tools: mean(nums(rows, METRICS.tool_call_count.get)),
      verdicts: rows.reduce((a, r) => { a[r.verdict] = (a[r.verdict] || 0) + 1; return a; }, {}),
    };
  }

  function sortedGroups(rows) {
    const g = [...groupRows(rows, state.group).entries()];
    const mv = e => agg(nums(e[1], METRICS[state.metric].get), state.agg);
    if (state.sort === 'name') g.sort((a, b) => a[0].localeCompare(b[0]));
    else if (state.sort === 'count') g.sort((a, b) => b[1].length - a[1].length);
    else {
      const s = state.sort === 'metric_asc' ? 1 : -1;
      g.sort((a, b) => s * ((mv(a) ?? -Infinity) - (mv(b) ?? -Infinity)));
    }
    return g;
  }

  // ----------------------------------------------------------- charts
  function mk(id, cfg, heightPx) {
    if (charts[id]) charts[id].destroy();
    if (heightPx) { const h = $('h' + id.slice(2)); if (h) h.style.height = heightPx + 'px'; }
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false }, cfg.options);
    charts[id] = new Chart($(id), cfg);
  }
  const baseScale = (title, extra = {}) => Object.assign({
    ticks: { color: DIM, font: { family: MONO, size: 11 } }, grid: { color: GRID },
    title: title ? { display: true, text: title, color: DIM, font: { family: MONO, size: 11 } } : { display: false },
  }, extra);
  const legend = { labels: { color: TXT, font: { family: MONO, size: 11 }, boxWidth: 12, usePointStyle: true } };
  // Full (never truncated) labels: Chart.js wraps array labels
  function wrapLabel(s, w = 38) {
    s = String(s); if (s.length <= w) return s;
    const parts = s.split(/(?<=[,;\s])/); const out = []; let line = '';
    parts.forEach(p => { if ((line + p).length > w && line) { out.push(line.trim()); line = ''; } line += p; });
    if (line) out.push(line.trim());
    return out;
  }
  const rowH = n => Math.max(260, n * 34 + 90);
  const color = i => PALETTE[i % PALETTE.length];
  const alpha = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

  function renderBar(rows) {
    const M = METRICS[state.metric];
    $('tBar').textContent = `${state.agg} ${M.label} by ${DIMS[state.group].label}` + (state.split ? ` × ${DIMS[state.split].label}` : '');
    const groups = sortedGroups(rows);
    const labels = groups.map(g => wrapLabel(g[0]));
    let datasets;
    if (state.split) {
      const series = [...new Set(rows.map(DIMS[state.split].get))].sort();
      datasets = series.map((s, i) => ({
        label: s,
        data: groups.map(g => agg(nums(g[1].filter(r => DIMS[state.split].get(r) === s), M.get), state.agg)),
        backgroundColor: alpha(color(i), 0.75), borderColor: color(i), borderWidth: 1, borderRadius: 3,
      }));
    } else {
      datasets = [{
        label: `${state.agg} ${M.label}`, data: groups.map(g => agg(nums(g[1], M.get), state.agg)),
        backgroundColor: groups.map((_, i) => alpha(color(i), 0.75)), borderColor: groups.map((_, i) => color(i)), borderWidth: 1, borderRadius: 3,
      }];
    }
    const n = groups.length * Math.max(1, state.split ? datasets.length * 0.7 : 1);
    mk('chBar', {
      type: 'bar', data: { labels, datasets },
      options: {
        indexAxis: 'y',
        plugins: { legend: state.split ? legend : { display: false }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.raw == null ? '—' : M.fmt(c.raw)}` } } },
        scales: { x: baseScale(M.label, { beginAtZero: true }), y: baseScale('', { ticks: { color: TXT, font: { family: MONO, size: 11 }, autoSkip: false } }) },
      },
    }, rowH(n));
  }

  function renderRate(rows) {
    const groups = sortedGroups(rows); const st = groups.map(g => groupStats(g[1]));
    mk('chRate', {
      type: 'bar',
      data: {
        labels: groups.map(g => wrapLabel(g[0])),
        datasets: [
          { label: 'Success rate %', data: st.map(s => s.pass == null ? null : s.pass * 100), backgroundColor: 'rgba(0,229,155,.7)', borderRadius: 3 },
          { label: 'Mean score %', data: st.map(s => s.score == null ? null : s.score * 100), backgroundColor: 'rgba(90,169,255,.7)', borderRadius: 3 },
        ],
      },
      options: {
        indexAxis: 'y', plugins: { legend },
        scales: { x: baseScale('%', { min: 0, max: 100 }), y: baseScale('', { ticks: { color: TXT, font: { family: MONO, size: 11 }, autoSkip: false } }) },
      },
    }, rowH(groups.length * 1.6));
  }

  function renderVerdict(rows) {
    const groups = sortedGroups(rows); const st = groups.map(g => groupStats(g[1]));
    const verdicts = [...new Set(rows.map(r => r.verdict))].sort();
    const vc = { passed: '#00e59b', partial: '#ffb44a', failed: '#ff6b7a', unverified: '#5b6b7c' };
    mk('chVerdict', {
      type: 'bar',
      data: {
        labels: groups.map(g => wrapLabel(g[0])),
        datasets: verdicts.map((v, i) => ({
          label: v, backgroundColor: vc[v] || color(i),
          data: st.map(s => (s.verdicts[v] || 0) / s.n * 100),
        })),
      },
      options: {
        indexAxis: 'y', plugins: { legend },
        scales: { x: baseScale('%', { stacked: true, max: 100 }), y: baseScale('', { stacked: true, ticks: { color: TXT, font: { family: MONO, size: 11 }, autoSkip: false } }) },
      },
    }, rowH(groups.length));
  }

  function renderTokens(rows) {
    const groups = sortedGroups(rows); const st = groups.map(g => groupStats(g[1]));
    mk('chTok', {
      type: 'bar',
      data: {
        labels: groups.map(g => wrapLabel(g[0])),
        datasets: [
          { label: 'Cached input', data: st.map(s => s.cached), backgroundColor: 'rgba(90,169,255,.75)' },
          { label: 'Fresh input', data: st.map(s => s.inp == null ? null : s.inp - (s.cached || 0)), backgroundColor: 'rgba(255,180,74,.75)' },
          { label: 'Output', data: st.map(s => s.out), backgroundColor: 'rgba(199,146,234,.75)' },
        ],
      },
      options: {
        indexAxis: 'y', plugins: { legend },
        scales: { x: baseScale('tokens / run', { stacked: true }), y: baseScale('', { stacked: true, ticks: { color: TXT, font: { family: MONO, size: 11 }, autoSkip: false } }) },
      },
    }, rowH(groups.length));
  }

  function renderBubble(rows) {
    const groups = sortedGroups(rows); const st = groups.map(g => groupStats(g[1]));
    const maxDur = Math.max(1, ...st.map(s => s.dur || 0));
    mk('chBubble', {
      type: 'bubble',
      data: {
        datasets: groups.map((g, i) => ({
          label: g[0], backgroundColor: alpha(color(i), 0.55), borderColor: color(i),
          data: [{ x: st[i].tok || 0, y: st[i].score ?? 0, r: 6 + 18 * ((st[i].dur || 0) / maxDur), dur: st[i].dur, n: st[i].n }],
        })),
      },
      options: {
        plugins: {
          legend: Object.assign({}, legend, { position: 'bottom' }),
          tooltip: { callbacks: { label: c => `${c.dataset.label}: tokens ${fmtNum(c.raw.x)}, score ${c.raw.y.toFixed(3)}, time ${fmtDur(c.raw.dur)}, n=${c.raw.n}` } },
        },
        scales: { x: baseScale('mean tokens / run'), y: baseScale('mean score', { suggestedMin: 0, suggestedMax: 1 }) },
      },
    });
  }

  function renderRadar(rows) {
    const groups = sortedGroups(rows).slice(0, 8); const st = groups.map(g => groupStats(g[1]));
    const inv = (key) => { const vals = st.map(s => s[key]).filter(v => v != null); const mx = Math.max(...vals, 1e-9); return st.map(s => s[key] == null ? 0 : 1 - s[key] / mx * 0.9); };
    const axes = [
      ['Success', st.map(s => s.pass ?? 0)], ['Score', st.map(s => s.score ?? 0)],
      ['Speed', inv('dur')], ['Token economy', inv('tok')], ['Few tool calls', inv('tools')],
      ['Stability', st.map(s => Math.max(0, 1 - 2 * (s.scoreStd || 0)))],
    ];
    mk('chRadar', {
      type: 'radar',
      data: {
        labels: axes.map(a => a[0]),
        datasets: groups.map((g, i) => ({
          label: g[0], data: axes.map(a => a[1][i]), borderColor: color(i), backgroundColor: alpha(color(i), 0.12), pointBackgroundColor: color(i),
        })),
      },
      options: {
        plugins: { legend: Object.assign({}, legend, { position: 'bottom' }) },
        scales: { r: { min: 0, max: 1, angleLines: { color: GRID }, grid: { color: GRID }, pointLabels: { color: TXT, font: { family: MONO, size: 11 } }, ticks: { display: false } } },
      },
    });
  }

  function renderScatter(rows) {
    const X = METRICS[state.x], Y = METRICS[state.y];
    $('tScatter').textContent = `Runs: ${Y.label} vs ${X.label} (colored by ${DIMS[state.group].label})`;
    const groups = sortedGroups(rows);
    mk('chScatter', {
      type: 'scatter',
      data: {
        datasets: groups.map((g, i) => ({
          label: g[0], backgroundColor: alpha(color(i), 0.65), borderColor: color(i), pointRadius: 5, pointHoverRadius: 8,
          data: g[1].map(r => ({ x: X.get(r), y: Y.get(r), uid: r.uid, task: r.task_uid })).filter(p => p.x != null && p.y != null),
        })),
      },
      options: {
        plugins: {
          legend: Object.assign({}, legend, { position: 'bottom' }),
          tooltip: { callbacks: { label: c => `${c.raw.task} · ${X.label}=${X.fmt(c.raw.x)}, ${Y.label}=${Y.fmt(c.raw.y)}` } },
        },
        onClick: (_, els, ch) => { if (els.length) { const p = ch.data.datasets[els[0].datasetIndex].data[els[0].index]; if (window.openRunModal) openRunModal(p.uid); } },
        scales: { x: baseScale(X.label), y: baseScale(Y.label) },
      },
    });
  }

  function renderHist(rows) {
    const M = METRICS[state.metric];
    $('tHist').textContent = `${M.label} distribution per ${DIMS[state.group].label}`;
    const all = nums(rows, M.get); if (!all.length) { mk('chHist', { type: 'bar', data: { labels: [], datasets: [] } }); return; }
    const lo = Math.min(...all), hi = Math.max(...all), bins = 10, w = (hi - lo) / bins || 1;
    const groups = sortedGroups(rows).slice(0, 8);
    mk('chHist', {
      type: 'bar',
      data: {
        labels: Array.from({ length: bins }, (_, i) => M.fmt(lo + i * w)),
        datasets: groups.map((g, i) => {
          const c = new Array(bins).fill(0);
          nums(g[1], M.get).forEach(v => { c[Math.min(bins - 1, Math.floor((v - lo) / w))]++; });
          return { label: g[0], data: c, backgroundColor: alpha(color(i), 0.65), borderColor: color(i), borderWidth: 1 };
        }),
      },
      options: { plugins: { legend: Object.assign({}, legend, { position: 'bottom' }) }, scales: { x: baseScale(M.label + ' (bin start)'), y: baseScale('runs', { beginAtZero: true, ticks: { color: DIM, precision: 0 } }) } },
    });
  }

  function renderTimeline(rows) {
    const M = METRICS[state.metric];
    const groups = sortedGroups(rows);
    mk('chTime', {
      type: 'scatter',
      data: {
        datasets: groups.map((g, i) => ({
          label: g[0], showLine: true, tension: 0.2, borderColor: color(i), backgroundColor: alpha(color(i), 0.7), pointRadius: 4,
          data: g[1].filter(r => r.started_at && M.get(r) != null).sort((a, b) => a.started_at.localeCompare(b.started_at))
            .map(r => ({ x: new Date(r.started_at).getTime(), y: M.get(r), uid: r.uid, task: r.task_uid })),
        })),
      },
      options: {
        plugins: {
          legend: Object.assign({}, legend, { position: 'bottom' }),
          tooltip: { callbacks: { label: c => `${c.raw.task}: ${M.fmt(c.raw.y)} @ ${new Date(c.raw.x).toLocaleString('pl-PL')}` } },
        },
        scales: { x: baseScale('', { ticks: { color: DIM, callback: v => new Date(v).toLocaleString('pl-PL', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } }), y: baseScale(M.label) },
      },
    });
  }

  function renderCum(rows) {
    const groups = sortedGroups(rows);
    mk('chCum', {
      type: 'line',
      data: {
        datasets: groups.map((g, i) => {
          let acc = 0;
          return {
            label: g[0], borderColor: color(i), backgroundColor: alpha(color(i), 0.1), stepped: true, pointRadius: 0, borderWidth: 2,
            data: g[1].filter(r => r.started_at).sort((a, b) => a.started_at.localeCompare(b.started_at))
              .map(r => { acc += r.total_tokens || 0; return { x: new Date(r.started_at).getTime(), y: acc }; }),
          };
        }),
      },
      options: {
        parsing: false, plugins: { legend: Object.assign({}, legend, { position: 'bottom' }) },
        scales: { x: { type: 'linear', ticks: { color: DIM, callback: v => new Date(v).toLocaleString('pl-PL', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }, grid: { color: GRID } }, y: baseScale('cumulative tokens') },
      },
    });
  }

  function renderHeat(rows) {
    const M = METRICS[state.metric];
    $('tHeat').textContent = `Heatmap — ${DIMS.task_uid.label} × ${DIMS[state.group].label} (${state.agg} ${M.label})`;
    const cols = sortedGroups(rows).map(g => g[0]);
    const tasks = [...new Set(rows.map(r => r.task_uid))].sort();
    const cell = {}; const all = [];
    rows.forEach(r => { const k = r.task_uid + '\u0001' + DIMS[state.group].get(r); (cell[k] = cell[k] || []).push(r); });
    Object.keys(cell).forEach(k => { const v = agg(nums(cell[k], M.get), state.agg); cell[k] = { v, n: cell[k].length }; if (v != null) all.push(v); });
    const lo = Math.min(...all), hi = Math.max(...all);
    const good = state.metric === 'score' || state.metric === 'pass' || state.metric === 'passed_tests' || state.metric === 'cache_ratio' || state.metric === 'tokens_per_s';
    const shade = v => { if (v == null || hi === lo) return 'transparent'; let t = (v - lo) / (hi - lo); if (!good) t = 1 - t; return `rgba(${Math.round(255 * (1 - t))},${Math.round(80 + 149 * t)},${Math.round(120 + 35 * t)},0.35)`; };
    $('anHeat').innerHTML = `<table class="matrix-table"><thead><tr><th style="text-align:left;">Task</th>${cols.map(c => `<th style="white-space:normal; min-width:140px; max-width:260px; word-break:break-word;">${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
      tasks.map(t => `<tr><td class="matrix-task"><a href="/tasks/${encodeURIComponent(t)}">${esc(t)}</a></td>${cols.map(c => {
        const x = cell[t + '\u0001' + c]; return x && x.v != null ? `<td class="mono" style="background:${shade(x.v)}; text-align:center;" title="n=${x.n}">${M.fmt(x.v)}</td>` : '<td class="mono" style="text-align:center; color:var(--fg-faint);">—</td>';
      }).join('')}</tr>`).join('') + '</tbody></table>';
  }

  function renderTable(rows) {
    const groups = sortedGroups(rows);
    $('anTable').innerHTML = `<table><thead><tr><th data-sortable>${esc(DIMS[state.group].label)}</th><th class="num" data-sortable>Runs</th><th class="num" data-sortable>Success</th><th class="num" data-sortable>Mean score</th><th class="num" data-sortable>σ score</th><th class="num" data-sortable>Mean time</th><th class="num" data-sortable>Mean tokens</th><th class="num" data-sortable>Cache hit</th><th class="num" data-sortable>Tool calls</th></tr></thead><tbody>` +
      groups.map(([k, rs]) => {
        const s = groupStats(rs); const cr = mean(nums(rs, METRICS.cache_ratio.get));
        // Every formatted cell keeps its number in data-sort-value: the header
        // sorts the measurement, not the way it happens to be written here.
        const rank = (value) => value == null ? '' : String(value);
        return `<tr><td class="mono" style="white-space:normal; word-break:break-word; max-width:520px;">${esc(k)}</td><td class="num mono">${s.n}</td><td class="num mono" data-sort-value="${rank(s.pass)}">${s.pass == null ? '—' : (s.pass * 100).toFixed(1) + '%'}</td><td class="num mono" data-sort-value="${rank(s.score)}">${s.score == null ? '—' : s.score.toFixed(3)}</td><td class="num mono" data-sort-value="${rank(s.scoreStd)}">${s.scoreStd.toFixed(3)}</td><td class="num mono" data-sort-value="${rank(s.dur)}">${fmtDur(s.dur)}</td><td class="num mono" data-sort-value="${rank(s.tok)}">${fmtNum(s.tok)}</td><td class="num mono" data-sort-value="${rank(cr)}">${cr == null ? '—' : (cr * 100).toFixed(0) + '%'}</td><td class="num mono" data-sort-value="${rank(s.tools)}">${s.tools == null ? '—' : s.tools.toFixed(1)}</td></tr>`;
      }).join('') + '</tbody></table>';
    armSorting($('anTable'));
  }

  // A table painted after load has no headers wired for sorting; the global
  // sorter is idempotent, so re-arming after every repaint costs nothing.
  function armSorting(root) {
    if (root && window.akbenchSortTables) window.akbenchSortTables(root);
  }

  function renderKpis(rows) {
    const s = groupStats(rows);
    const k = (cls, t, v, sub) => `<div class="card ${cls}"><div class="card-title">${t}</div><div class="card-value">${v}</div><div class="card-sub">${sub}</div></div>`;
    const tasks = new Set(rows.map(r => r.task_uid)).size, cfgs = new Set(rows.map(r => r.config_str)).size;
    $('anKpis').innerHTML =
      k('card-mint', 'Success / Mean score', `${s.pass == null ? '—' : (s.pass * 100).toFixed(1) + '%'} / ${s.score == null ? '—' : s.score.toFixed(3)}`, `σ score ${s.scoreStd.toFixed(3)}`) +
      k('card-blue', 'Runs in selection', rows.length.toLocaleString(), `${tasks} task(s) · ${cfgs} config(s)`) +
      k('', 'Mean duration', fmtDur(s.dur), 'wall-clock per run') +
      k('card-amber', 'Mean tokens / run', fmtNum(s.tok), `in ${fmtNum(s.inp)} · out ${fmtNum(s.out)}`);
  }

  function render() {
    const rows = filtered();
    $('anCount').textContent = `${rows.length} / ${DATA.rows.length} runs`;
    if (!rows.length) {
      $('anKpis').innerHTML = '<div class="card"><div class="card-title">No runs match filters</div></div>';
      return;
    }
    renderKpis(rows); renderBar(rows); renderRate(rows); renderVerdict(rows); renderTokens(rows);
    renderBubble(rows); renderRadar(rows); renderScatter(rows); renderHist(rows); renderTimeline(rows); renderCum(rows);
    renderHeat(rows); renderTable(rows);
  }

  // ----------------------------------------------------------- state sharing
  function saveHash() { history.replaceState(null, '', '#' + encodeURIComponent(JSON.stringify(state))); }
  function loadHash() {
    try { if (location.hash.length > 1) Object.assign(state, JSON.parse(decodeURIComponent(location.hash.slice(1)))); } catch { /* ignore */ }
    ['group', 'split', 'x', 'y'].forEach(k => { if (state[k] && !(DIMS[state[k]] || METRICS[state[k]])) state[k] = ''; });
    if (!state.group) state.group = 'config_str';
  }

  function exportCsv() {
    const rows = filtered();
    const cols = ['uid', 'experiment_uid', 'variant_uid', 'config_str', 'task_uid', 'agent', 'model', 'status', 'verdict', 'score', 'passed_tests', 'failed_tests', 'total_tests', 'duration_seconds', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens', 'tool_call_count', 'started_at', 'finished_at'];
    const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [cols.join(',')].concat(rows.map(r => cols.map(c => q(r[c])).join(','))).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'akbench-runs.csv'; a.click();
  }

  async function load(first) {
    armSpinners();
    try {
      const res = await fetch('/api/analytics/data');
      DATA = res.ok ? await res.json() : { rows: [], param_keys: [] };
    } catch {
      DATA = { rows: [], param_keys: [] };
    }
    buildDims();
    if (first) { loadHash(); buildControls(); }
    buildFilters();
    render();
    // the charts above are constructed synchronously by render(); one frame
    // later they have painted, so the spinners may go
    requestAnimationFrame(clearSpinners);
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (typeof Chart === 'undefined') { $('anKpis').innerHTML = '<div class="card"><div class="card-title">Chart.js failed to load</div></div>'; return; }
    load(true);
    $('anExportCsv').addEventListener('click', exportCsv);
    $('anCopyLink').addEventListener('click', () => navigator.clipboard && navigator.clipboard.writeText(location.href));
    $('anReset').addEventListener('click', () => { history.replaceState(null, '', location.pathname); location.reload(); });
    // live refresh integration
    window.triggerLiveUpdate = () => load(false);
  });
})();

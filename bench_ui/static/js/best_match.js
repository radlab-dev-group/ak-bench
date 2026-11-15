// Best Match — exhaustive search for where auto_codex+knowledge wins
(() => {
  const $ = (s) => document.querySelector(s);
  const el = {
    loading: $('#bmLoading'),
    kpis: $('#bmKpis'),
    verdict: $('#bmVerdict'),
    hero: $('#bmHero'),
    heroBody: $('#bmHeroBody'),
    coverage: $('#bmCoverage'),
    coverageBody: $('#bmCoverageBody'),
    coverageBadge: $('#bmCoverageBadge'),
    catMetric: $('#bmCatMetric'),
    diffMetric: $('#bmDiffMetric'),
    winGroup: $('#bmWinGroup'),
    charts: $('#bmCharts'),
    panelCat: $('#panelCat'),
    panelDiff: $('#panelDiff'),
    panelCatDiff: $('#panelCatDiff'),
    panelTasks: $('#panelTasks'),
    panelTaskSet: $('#panelTaskSet'),
    panelWinning: $('#panelWinning'),
    empty: $('#bmEmpty'),
    catCount: $('#bmCatCount'),
    diffCount: $('#bmDiffCount'),
    catDiffCount: $('#bmCatDiffCount'),
    tasksCount: $('#bmTasksCount'),
    winningCount: $('#bmWinningCount'),
    catTable: $('#bmCatTable'),
    diffTable: $('#bmDiffTable'),
    catDiffTable: $('#bmCatDiffTable'),
    tasksTable: $('#bmTasksTable'),
    taskSetBody: $('#bmTaskSetBody'),
    taskSetBadge: $('#bmTaskSetBadge'),
    winningTable: $('#bmWinningTable'),
    catSubsets: $('#bmCatSubsets'),
    vsComp: $('#bmVsComp'),
    meta: $('#bmMeta'),
    targetDesc: $('#bmTargetDesc'),
    heat: $('#bmHeat'),
    minRuns: $('#bmMinRuns'),
    reload: $('#bmReload'),
    copyLink: $('#bmCopyLink'),
    sort: $('#bmSort'),
    onlyWinning: $('#bmOnlyWinning'),
    onlyEnough: $('#bmOnlyEnough'),
    pin: $('#bmPin'),
  };
  const PALETTE = ['#00e59b','#5aa9ff','#ffb44a','#c792ea','#ff6b7a','#4dd0e1'];
  let raw = null;
  let charts = {};

  function fmtPct(v){ if(v==null) return '—'; return (v*100).toFixed(1)+'%'; }
  function fmtScore(v){ if(v==null) return '—'; return v.toFixed(3); }
  function fmtDelta(v){ if(v==null) return '—'; const s=v>0?'+':''; return s+v.toFixed(3); }
  function deltaClass(v){ if(v==null) return 'bm-delta-zero'; return v>0?'bm-delta-plus':(v<0?'bm-delta-minus':'bm-delta-zero'); }
  function ciSpan(low, high){ if(low==null||high==null) return '—'; return `${fmtPct(low)} – ${fmtPct(high)}`; }

  function kpiCard(title, value, sub, color){
    return `<div class="card ${color||''}"><div class="card-title">${title}</div><div class="card-value">${value}</div><div class="card-sub">${sub}</div></div>`;
  }

  async function fetchData(){
    const minRuns = el.minRuns.value || 3;
    el.loading.style.display = 'flex';
    [el.kpis, el.verdict, el.hero, el.coverage, el.charts, el.panelCat, el.panelDiff, el.panelCatDiff, el.panelTasks, el.panelTaskSet, el.panelWinning, el.empty].forEach(e=>e.style.display='none');
    // destroy charts
    Object.values(charts).forEach(c=>{ try{c.destroy();}catch{} });
    charts={};
    try{
      const res = await fetch(`/api/best-match?min_runs=${encodeURIComponent(minRuns)}`);
      if(!res.ok) throw new Error(`HTTP ${res.status}`);
      raw = await res.json();
      render();
    }catch(e){
      el.loading.innerHTML = `<div class="fl-empty">Failed to load data: ${e.message}</div>`;
    }
  }

  function filteredSorted(list){
    if(!list) return [];
    let out = [...list];
    const onlyW = el.onlyWinning.checked;
    const onlyE = el.onlyEnough.checked;
    if(onlyW) out = out.filter(s=> s.delta.wins_both);
    if(onlyE) out = out.filter(s=> s.enough_data);
    const sort = el.sort.value;
    if(sort==='composite_desc') out.sort((a,b)=> (b.delta.composite??-9e9)-(a.delta.composite??-9e9));
    else if(sort==='success_desc') out.sort((a,b)=> (b.delta.delta_success_rate??-9e9)-(a.delta.delta_success_rate??-9e9));
    else if(sort==='score_desc') out.sort((a,b)=> (b.delta.delta_mean_score??-9e9)-(a.delta.delta_mean_score??-9e9));
    else if(sort==='name') out.sort((a,b)=> a.label.localeCompare(b.label));
    return out;
  }

  function renderKPIs(){
    const t = raw.target;
    const b = raw.baseline;
    const o = raw.overall;
    const m = raw.meta;
    el.meta.textContent = `${m.total_runs} runs · ${m.target_runs} target · ${m.other_runs} others · ${m.total_tasks} tasks`;
    el.targetDesc.innerHTML = `Found <strong style="color:var(--mint);">${t.runs} target runs</strong> (<strong>${t.evaluated} evaluated</strong>) vs <strong>${b.runs} baseline runs</strong> (<strong>${b.evaluated} evaluated</strong>)`;
    el.kpis.style.display='grid';
    const tSucc = fmtPct(t.summary.success_rate);
    const oSucc = fmtPct(b.summary.success_rate);
    const tScore = fmtScore(t.summary.mean_score);
    const oScore = fmtScore(b.summary.mean_score);
    const dSucc = o.delta.delta_success_rate;
    const dScore = o.delta.delta_mean_score;
    el.kpis.innerHTML =
      kpiCard('Target success_rate', tSucc, `auto_codex+knowledge: ${t.summary.passed}/${t.summary.evaluated} <span style="color:var(--fg-faint);">vs baseline ${oSucc}</span>`, 'card-mint') +
      kpiCard('Target mean_score', tScore, `vs baseline ${oScore}`, 'card-blue') +
      kpiCard('Δ success (target − others)', `<span class="${deltaClass(dSucc)}">${fmtDelta(dSucc)}</span>`, `ci target ${ciSpan(t.ci.low,t.ci.high)}<br>ci baseline ${ciSpan(b.ci.low,b.ci.high)}`) +
      kpiCard('Δ mean_score', `<span class="${deltaClass(dScore)}">${fmtDelta(dScore)}</span>`, `${o.delta.wins_both?'✅ wins on both indicators':'—'} · composite ${o.delta.composite==null?'—':fmtDelta(o.delta.composite)}`, o.delta.wins_both?'card-mint':'') +
      kpiCard('Winning slices', `${raw.optimal.winning_slices.length}`, `of ${raw.optimal.winning_slices_all.length} total slices winning on both indicators`, raw.optimal.winning_slices.length?'card-amber':'') +
      kpiCard('Optimal tasks', `${(raw.optimal.winning_task_ids||[]).length} tasks`, `where the target wins — the combined maximised set`, (raw.optimal.winning_task_ids||[]).length?'card-mint':'');
  }

  function renderVerdict(){
    el.verdict.style.display='block';
    const o = raw.overall;
    const interp = raw.interpretation.overall_verdict;
    const color = o.delta.wins_both ? 'var(--mint)' : (o.delta.delta_success_rate>0 ? 'var(--amber)' : 'var(--red)');
    el.verdict.innerHTML = `<div class="panel-body" style="display:flex; gap:14px; align-items:center; flex-wrap:wrap;">
      <div style="width:10px; height:48px; border-radius:4px; background:${color}; flex-shrink:0;"></div>
      <div style="flex:1;">
        <div style="font-weight:600; color:${color};">Overall verdict: ${interp}</div>
        <div style="font-size:12.5px; color:var(--fg-dim); margin-top:4px;">Overall Δsuccess <span class="${deltaClass(o.delta.delta_success_rate)}">${fmtDelta(o.delta.delta_success_rate)}</span> · Δscore <span class="${deltaClass(o.delta.delta_mean_score)}">${fmtDelta(o.delta.delta_mean_score)}</span> · target ${fmtPct(o.target_summary.success_rate)} (${o.target_summary.passed}/${o.target_summary.evaluated}) vs others ${fmtPct(o.other_summary.success_rate)} (${o.other_summary.passed}/${o.other_summary.evaluated})</div>
        <div style="font-size:11.5px; color:var(--fg-faint); margin-top:2px; font-family:var(--mono);">Win definition: Δsuccess &gt; 0 <strong>and</strong> Δmean_score &gt; 0 simultaneously → maximisation of all quality indicators. Sorted by <code>composite = Δsuccess + Δscore</code>.</div>
      </div>
      <div style="display:flex; gap:8px;">
        <a href="/compare" class="btn btn-sm">Compare in Studio</a>
        <a href="/analytics" class="btn btn-sm">Analytics</a>
      </div>
    </div>`;
  }

  function renderHero(){
    if(!raw.optimal) return;
    el.hero.style.display='block';
    const bestCat = raw.optimal.best_category;
    const bestDiff = raw.optimal.best_difficulty;
    const bestCatDiff = raw.optimal.best_category_difficulty;
    const bestTask = raw.optimal.best_task;
    const bestCatSubset = raw.optimal.best_category_subset;
    // choose the global best among these
    const candidates = [bestCat, bestDiff, bestCatDiff, bestTask, bestCatSubset].filter(Boolean);
    candidates.sort((a,b)=> (b.delta.composite??-9e9)-(a.delta.composite??-9e9));
    const globalBest = candidates[0];
    const taskSet = raw.optimal.task_set_winning;
    let html = '';
    if(globalBest){
      html += `<div style="margin-bottom:14px; padding:10px 14px; background:var(--panel-2); border:1px solid var(--mint-border); border-radius:8px;">
        <div style="font-size:11px; color:var(--mint); font-family:var(--mono); letter-spacing:.05em;">🏆 GLOBAL BEST — maximises all quality indicators</div>
        <div style="font-size:1.25rem; font-weight:700; margin:4px 0; color:var(--fg-strong);">${globalBest.label}</div>
        <div style="font-size:12.5px; color:var(--fg-dim);">Δsuccess <span class="${deltaClass(globalBest.delta.delta_success_rate)}">${fmtDelta(globalBest.delta.delta_success_rate)}</span> · Δscore <span class="${deltaClass(globalBest.delta.delta_mean_score)}">${fmtDelta(globalBest.delta.delta_mean_score)}</span> · composite <strong>${fmtDelta(globalBest.delta.composite)}</strong> &nbsp;|&nbsp; target ${fmtPct(globalBest.target_summary.success_rate)} (${globalBest.target_summary.passed}/${globalBest.target_summary.evaluated}) vs others ${fmtPct(globalBest.other_summary.success_rate)} (${globalBest.other_summary.passed}/${globalBest.other_summary.evaluated}) · target score ${fmtScore(globalBest.target_summary.mean_score)} vs ${fmtScore(globalBest.other_summary.mean_score)}</div>
        <div style="font-size:11.5px; color:var(--fg-faint); font-family:var(--mono); margin-top:4px;">${globalBest.enough_data ? '✅ enough data (≥ min_runs)' : '⚠️ insufficient data — indicative result'} · key: <code>${globalBest.key}</code></div>
      </div>`;
    }
    html += `<div class="bm-hero-grid">`;
    function heroCard(title, obj, icon){
      if(!obj) return `<div class="bm-hero-card"><div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono);">${title}</div><div style="color:var(--fg-faint); margin-top:6px;">No data</div></div>`;
      const isBest = globalBest && obj.key===globalBest.key;
      return `<div class="bm-hero-card ${isBest?'best':''}"><div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono);">${icon} ${title}</div>
        <div style="font-weight:700; margin:6px 0 4px; font-size:13.5px;">${obj.label}</div>
        <div style="font-size:12px;"><span class="${deltaClass(obj.delta.delta_success_rate)}">${fmtDelta(obj.delta.delta_success_rate)}</span> success · <span class="${deltaClass(obj.delta.delta_mean_score)}">${fmtDelta(obj.delta.delta_mean_score)}</span> score · <strong style="color:var(--mint);">${fmtDelta(obj.delta.composite)}</strong> composite</div>
        <div style="font-size:11.5px; color:var(--fg-dim); margin-top:6px;">target ${fmtPct(obj.target_summary.success_rate)} vs others ${fmtPct(obj.other_summary.success_rate)}<br>score ${fmtScore(obj.target_summary.mean_score)} vs ${fmtScore(obj.other_summary.mean_score)}</div>
        <div style="font-size:11px; color:var(--fg-faint); margin-top:6px; font-family:var(--mono);">${obj.enough_data?'✅':'⚠️'} ${obj.target_summary.evaluated} vs ${obj.other_summary.evaluated} evaluated · ${obj.target_summary.runs} vs ${obj.other_summary.runs} runs</div>
      </div>`;
    }
    html += heroCard('Best category', bestCat, '📦');
    html += heroCard('Best difficulty', bestDiff, '🎯');
    html += heroCard('Best category × difficulty', bestCatDiff, '🔀');
    html += heroCard('Best task', bestTask, '🧩');
    html += heroCard('Optimal category subset (brute force)', bestCatSubset, '📚');
    if(taskSet){
      html += `<div class="bm-hero-card best" style="grid-column: span 2;">
        <div style="font-size:11px; color:var(--mint); font-family:var(--mono);">🧪 MAXIMISED TASK SET — all winning tasks together</div>
        <div style="font-weight:700; margin:6px 0 4px; font-size:14px;">${taskSet.label} — ${taskSet.filter.task_uids.length} tasks</div>
        <div style="font-size:12px;"><span class="${deltaClass(taskSet.delta.delta_success_rate)}">${fmtDelta(taskSet.delta.delta_success_rate)}</span> success · <span class="${deltaClass(taskSet.delta.delta_mean_score)}">${fmtDelta(taskSet.delta.delta_mean_score)}</span> score · <strong>${fmtDelta(taskSet.delta.composite)}</strong></div>
        <div style="font-size:11.5px; color:var(--fg-dim); margin-top:6px;">target ${fmtPct(taskSet.target_summary.success_rate)} (${taskSet.target_summary.passed}/${taskSet.target_summary.evaluated}) vs others ${fmtPct(taskSet.other_summary.success_rate)} (${taskSet.other_summary.passed}/${taskSet.other_summary.evaluated})</div>
        <div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:4px;">${taskSet.filter.task_uids.map(id=>`<a href="/tasks/${id}" class="chip chip-sm" style="font-size:10.5px;">${id}</a>`).join(' ')}</div>
        <div style="font-size:11px; color:var(--fg-faint); margin-top:6px; font-family:var(--mono);">Combined result for the whole set — this is the exact scenario where the configuration beats the others.</div>
      </div>`;
    }
    html += `</div>`;
    if(taskSet){
      html += `<div style="margin-top:12px; padding:10px 14px; background:rgba(255,180,74,.08); border:1px solid var(--amber-border); border-radius:8px; font-size:12.5px; color:var(--fg-dim);">
        <strong style="color:var(--amber);">How to read this:</strong> This is the <em>maximised scenario</em> — the task/category/difficulty filter where <code>auto_codex+knowledge</code> simultaneously maximises <code>success_rate</code> and <code>mean_score</code>. Composite = Δsuccess + Δscore. The higher it is, the stronger the advantage over all other configurations.
      </div>`;
    }
    el.heroBody.innerHTML = html;
  }

  function renderCoverage(){
    el.coverage.style.display='block';
    const cats = raw.slices.by_category || [];
    const withTarget = cats.filter(c=> c.target_summary.evaluated>0).length;
    const total = cats.length;
    if(el.coverageBadge) el.coverageBadge.textContent = `${withTarget} / ${total} with data`;
    let html = `<div style="font-size:12px; color:var(--fg-dim); margin-bottom:10px;">The target <code>auto_codex+knowledge</code> has evaluated runs in <strong style="color:var(--mint);">${withTarget}</strong> of <strong>${total}</strong> task types (categories). The full list is below — categories without any target runs are marked as <em>no target data</em>, so their delta is <code>null</code> (not zero). This shows which task types are missing entirely from the "Deltas per category" chart.</div>`;
    html += '<table><thead><tr><th>Category (task type)</th><th class="num">Target eval</th><th class="num">Others eval</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Status</th></tr></thead><tbody>';
    cats.forEach(c=>{
      const has = c.target_summary.evaluated>0;
      const status = !has
        ? '<span class="badge badge-neutral">No target data</span>'
        : (c.delta.wins_both ? '<span class="badge badge-passed">WIN</span>' : '<span class="badge badge-info">Has data</span>');
      html += `<tr style="${c.delta.wins_both&&c.enough_data?'background:rgba(0,229,155,.06);':''}">
        <td><strong>${c.label}</strong></td>
        <td class="num mono">${c.target_summary.evaluated}</td>
        <td class="num mono">${c.other_summary.evaluated}</td>
        <td class="num mono ${deltaClass(c.delta.delta_success_rate)}">${fmtDelta(c.delta.delta_success_rate)}</td>
        <td class="num mono ${deltaClass(c.delta.delta_mean_score)}">${fmtDelta(c.delta.delta_mean_score)}</td>
        <td class="num mono" style="font-weight:700; color:${c.delta.composite>0?'var(--mint)':(c.delta.composite<0?'var(--red)':'var(--fg)')};">${fmtDelta(c.delta.composite)}</td>
        <td>${status}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    el.coverageBody.innerHTML = html;
  }

  function _barY(metric){
    if(metric==='success' || metric==='score') return { y:{ ticks:{color:'#5aa9ff', callback:(v)=> (v>0?'+':'')+v}, grid:{color:'rgba(255,255,255,.06)'} } };
    if(metric==='composite') return { y:{ ticks:{color:'#a5b3c2', callback:(v)=> (v>0?'+':'')+v}, grid:{color:'rgba(255,255,255,.06)'} } };
    return { y:{ ticks:{color:'#5aa9ff', callback:(v)=> (v>0?'+':'')+v}, grid:{color:'rgba(255,255,255,.06)'} }, y1:{ position:'right', ticks:{color:'#ffb44a'}, grid:{drawOnChartArea:false} } };
  }
  function _barDatasets(slices, metric, wins){
    const color = (arr)=> arr.map((v,i)=> wins[i] ? '#00e59b' : (v==null ? '#3a4654' : (v>0 ? '#5aa9ff' : '#ff6b7a')));
    const success = slices.map(c=> c.delta.delta_success_rate ?? null);
    const score = slices.map(c=> c.delta.delta_mean_score ?? null);
    const comp = slices.map(c=> c.delta.composite ?? null);
    if(metric==='composite') return [{ label:'composite Δ', data:comp, backgroundColor:color(comp), borderWidth:0 }];
    if(metric==='success') return [{ label:'Δ success', data:success, backgroundColor:color(success), borderWidth:0 }];
    if(metric==='score') return [{ label:'Δ score', data:score, backgroundColor:color(score), borderWidth:0 }];
    return [
      { label:'Δ success', data:success, backgroundColor:color(success), borderWidth:0 },
      { label:'Δ score', data:score, backgroundColor:color(score), borderWidth:0 },
      { label:'composite', type:'line', data:comp, borderColor:'#ffb44a', backgroundColor:'#ffb44a', yAxisID:'y1', tension:.25, pointRadius:3, borderWidth:2 },
    ];
  }
  function _barTooltip(slices){
    return { callbacks:{ label:(c)=>{
      const s = slices[c.dataIndex];
      const v = c.raw==null ? 'n/a' : fmtDelta(c.raw);
      return `${c.dataset.label}: ${v}  ·  target ${fmtPct(s.target_summary.success_rate)} (${s.target_summary.evaluated} eval) vs ${fmtPct(s.other_summary.success_rate)} (${s.other_summary.evaluated} eval)`;
    } } };
  }
  function buildCatChart(){
    const cats = raw.slices.by_category || [];
    const metric = el.catMetric ? el.catMetric.value : 'all';
    const wins = cats.map(c=> c.delta.wins_both && c.enough_data);
    const ctx = document.getElementById('chCat');
    if(!ctx) return;
    if(charts.chCat) charts.chCat.destroy();
    const datasets = _barDatasets(cats, metric, wins);
    charts.chCat = new Chart(ctx, {
      type:'bar',
      data:{ labels:cats.map(c=>c.label), datasets },
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display: datasets.length>1, labels:{color:'#c6d3df', boxWidth:12}}, tooltip:_barTooltip(cats) },
        scales:{ x:{ ticks:{color:'#a5b3c2', font:{family:'ui-monospace', size:11}, autoSkip:false, maxRotation:60, minRotation:30} }, ..._barY(metric) }
      }
    });
  }
  function buildDiffChart(){
    const diffs = raw.slices.by_difficulty || [];
    const metric = el.diffMetric ? el.diffMetric.value : 'all';
    const wins = diffs.map(d=> d.delta.wins_both && d.enough_data);
    const ctx = document.getElementById('chDiff');
    if(!ctx) return;
    if(charts.chDiff) charts.chDiff.destroy();
    const datasets = _barDatasets(diffs, metric, wins);
    charts.chDiff = new Chart(ctx, {
      type:'bar',
      data:{ labels:diffs.map(d=>d.label), datasets },
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display: datasets.length>1, labels:{color:'#c6d3df', boxWidth:12}}, tooltip:_barTooltip(diffs) },
        scales:{ x:{ ticks:{color:'#a5b3c2', font:{family:'ui-monospace', size:11}, autoSkip:false, maxRotation:60, minRotation:30} }, ..._barY(metric) }
      }
    });
  }
  function buildScatterChart(){
    const tasks = raw.slices.by_task || [];
    const pts = [];
    const colors = [];
    tasks.forEach(t=>{
      const x = t.other_summary.success_rate;
      const y = t.target_summary.success_rate;
      if(x==null || y==null) return;
      pts.push({ x, y, _t:t });
      colors.push((t.delta.wins_both && t.enough_data) ? '#00e59b' : (t.delta.composite>0 ? '#5aa9ff' : '#ff6b7a'));
    });
    const ctx = document.getElementById('chScatter');
    if(!ctx || !pts.length) return;
    if(charts.chScatter) charts.chScatter.destroy();
    charts.chScatter = new Chart(ctx, {
      type:'scatter',
      data:{ datasets:[
        { label:'tasks (target vs others success_rate)', data:pts, pointBackgroundColor:colors, pointRadius:5, pointHoverRadius:7 },
        { label:'parity line (target = others)', type:'line', data:[{x:0,y:0},{x:1,y:1}], borderColor:'#a5b3c2', borderDash:[6,4], pointRadius:0, fill:false },
      ]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{color:'#c6d3df'}},
          tooltip:{ callbacks:{ label:(c)=>{
            const t = c.raw._t;
            if(!t) return '';
            return `${t.filter.task_uid}: target ${fmtPct(t.target_summary.success_rate)} vs others ${fmtPct(t.other_summary.success_rate)} · Δsuccess ${fmtDelta(t.delta.delta_success_rate)} (${t.target_summary.evaluated} vs ${t.other_summary.evaluated} eval)`;
          } } } },
        scales:{ x:{ min:0, max:1, title:{display:true, text:'others success_rate', color:'#a5b3c2'}, ticks:{color:'#a5b3c2', callback:(v)=> (v*100).toFixed(0)+'%'}, grid:{color:'rgba(255,255,255,.06)'} },
          y:{ min:0, max:1, title:{display:true, text:'target success_rate', color:'#a5b3c2'}, ticks:{color:'#a5b3c2', callback:(v)=> (v*100).toFixed(0)+'%'}, grid:{color:'rgba(255,255,255,.06)'} } }
      }
    });
  }

  // Bars beside the win-diagram scatter: the exact same task set, but counted
  // instead of plotted — per group (category / difficulty) how many tasks the
  // target wins on both indicators, how many stay undecided, how many it loses.
  function buildWinBarsChart(){
    const ctx = document.getElementById('chWinBars');
    if(!ctx) return;
    if(charts.chWinBars){ charts.chWinBars.destroy(); charts.chWinBars = null; }
    const groupBy = (el.winGroup && el.winGroup.value) || 'category';
    const tasks = raw.slices.by_task || [];
    const groups = new Map();
    tasks.forEach(t=>{
      const raw_key = groupBy === 'difficulty' ? t.filter.difficulty : t.filter.category;
      const key = raw_key || 'unknown';
      if(!groups.has(key)) groups.set(key, { key, win:0, tie:0, loss:0, total:0 });
      const g = groups.get(key);
      g.total += 1;
      if(t.delta.wins_both && t.enough_data) g.win += 1;
      else if(t.delta.composite != null && t.delta.composite < 0) g.loss += 1;
      else g.tie += 1;
    });
    const rows = [...groups.values()].sort((a,b)=> (b.win - a.win) || (b.total - a.total) || a.key.localeCompare(b.key));
    if(!rows.length){
      ctx.parentElement.innerHTML = '<div class="fl-empty">No tasks to count.</div>';
      return;
    }
    const totalWin = rows.reduce((s,r)=> s + r.win, 0);
    const totalAll = rows.reduce((s,r)=> s + r.total, 0);
    // leave room to the right of the longest bar for the "won / all" label
    const maxTotal = Math.max(...rows.map(r=> r.total)) + 1;
    const titleEl = document.getElementById('bmWinBarsTitle');
    if(titleEl) titleEl.textContent = groupBy === 'difficulty' ? 'Win balance — tasks by difficulty' : 'Win balance — tasks by category';
    charts.chWinBars = new Chart(ctx, {
      type:'bar',
      data:{ labels:rows.map(r=> r.key), datasets:[
        { label:'wins both', data:rows.map(r=> r.win), backgroundColor:'#00e59b', stack:'s' },
        { label:'undecided', data:rows.map(r=> r.tie), backgroundColor:'#ffb44a', stack:'s' },
        { label:'loses', data:rows.map(r=> r.loss), backgroundColor:'#ff6b7a', stack:'s' },
      ]},
      options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{ labels:{color:'#c6d3df', boxWidth:12} },
          title:{ display:true, text:`${totalWin} of ${totalAll} tasks win on both indicators`, color:'#c6d3df', font:{size:12, weight:'600'}, padding:{bottom:10} },
          tooltip:{ callbacks:{
            label:(c)=> ` ${c.dataset.label}: ${c.parsed.x} of ${rows[c.dataIndex].total} tasks`,
            footer:(items)=>{
              const r = rows[items[0].dataIndex];
              const pct = r.total ? (r.win / r.total * 100).toFixed(0) : '0';
              return `won ${r.win}/${r.total} (${pct}%)`;
            },
          } },
        },
        scales:{
          x:{ stacked:true, beginAtZero:true, suggestedMax:maxTotal, ticks:{ color:'#a5b3c2', precision:0, callback:(v)=> Number.isInteger(v)? v : '' }, grid:{color:'rgba(255,255,255,.06)'}, title:{display:true, text:'Number of tasks', color:'#a5b3c2'} },
          y:{ stacked:true, ticks:{ color:'#a5b3c2', font:{family:'ui-monospace', size:10} }, grid:{display:false} },
        },
      },
      plugins:[{
        // "won / total" at the end of every stacked bar — the count alone
        // hides how big the group is, the ratio is what makes groups comparable
        id:'bmWinRatio',
        afterDatasetsDraw(chart){
          const { ctx:c, scales:{ x } } = chart;
          c.save();
          c.font = '10px ui-monospace, monospace';
          c.textAlign = 'left';
          c.textBaseline = 'middle';
          rows.forEach((r, i)=>{
            const meta = chart.getDatasetMeta(0).data[i];
            if(!meta) return;
            c.fillStyle = r.win ? '#c6d3df' : '#8d9daf';
            c.fillText(`${r.win}/${r.total}`, x.getPixelForValue(r.total) + 5, meta.y);
          });
          c.restore();
        },
      }],
    });
  }

  function renderCharts(){
    el.charts.style.display='block';
    buildCatChart();
    buildDiffChart();
    buildScatterChart();
    buildWinBarsChart();
    if(el.winGroup) el.winGroup.onchange = ()=> buildWinBarsChart();
    if(el.catMetric) el.catMetric.onchange = ()=> buildCatChart();
    if(el.diffMetric) el.diffMetric.onchange = ()=> buildDiffChart();
    // tasks bar top 12
    const tasks = [...(raw.slices.by_task||[])].sort((a,b)=> (b.delta.composite??-9e9)-(a.delta.composite??-9e9)).slice(0,12);
    const ctxTasks = document.getElementById('chTasks');
    if(ctxTasks && tasks.length){
      const tLabels = tasks.map(t=> t.filter.task_uid);
      const tTarget = tasks.map(t=> t.target_summary.success_rate ?? 0);
      const tOther = tasks.map(t=> t.other_summary.success_rate ?? 0);
      charts.chTasks = new Chart(ctxTasks, {
        type:'bar',
        data:{ labels:tLabels, datasets:[
          {label:'target success', data:tTarget, backgroundColor:'#00e59b'},
          {label:'others success', data:tOther, backgroundColor:'#1a232e', borderColor:'#5aa9ff', borderWidth:1},
        ]},
        options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#c6d3df'}}}, scales:{ x:{ min:0, max:1, ticks:{color:'#a5b3c2', callback:(v)=> (v*100).toFixed(0)+'%'}, grid:{color:'rgba(255,255,255,.06)'} }, y:{ ticks:{color:'#a5b3c2', font:{size:10}} } } }
      });
    }
    // heatmap category x difficulty
    renderHeat();
    // cat subsets table
    renderCatSubsets();
    // vs competitors
    renderVsComp();
  }

  function renderHeat(){
    const cats = raw.meta.categories;
    const diffs = raw.meta.difficulties;
    const map = {};
    (raw.slices.by_category_difficulty||[]).forEach(s=>{
      const k = `${s.filter.category}|${s.filter.difficulty}`;
      map[k]=s;
    });
    let html = '<table><thead><tr><th></th>';
    diffs.forEach(d=> html+=`<th>${d}</th>`);
    html+='</tr></thead><tbody>';
    cats.forEach(cat=>{
      html+=`<tr><th style="text-align:left;">${cat}</th>`;
      diffs.forEach(diff=>{
        const s = map[`${cat}|${diff}`];
        if(!s){ html+='<td style="background:var(--panel-2); color:var(--fg-faint);">—</td>'; return; }
        const comp = s.delta.composite;
        const bg = comp==null ? 'var(--panel-2)' : (comp>0.3?'rgba(0,229,155,.32)': comp>0?'rgba(90,169,255,.28)': comp<-0.05?'rgba(255,107,122,.22)':'var(--panel-2)');
        const fg = comp!=null && comp>0.08 ? 'var(--mint)' : (comp!=null && comp<0?'var(--red)':'var(--fg)');
        html+=`<td title="${cat} · ${diff}\nΔsuccess ${fmtDelta(s.delta.delta_success_rate)}\nΔscore ${fmtDelta(s.delta.delta_mean_score)}\ncomposite ${fmtDelta(comp)}\ntarget ${fmtPct(s.target_summary.success_rate)} vs ${fmtPct(s.other_summary.success_rate)}" style="background:${bg}; color:${fg}; border:1px solid rgba(255,255,255,.06); cursor:default;">${comp==null?'—':fmtDelta(comp)}<div style="font-size:9.5px; color:var(--fg-faint);">${fmtPct(s.target_summary.success_rate)} vs ${fmtPct(s.other_summary.success_rate)}</div></td>`;
      });
      html+='</tr>';
    });
    html+='</tbody></table>';
    html+=`<div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono); margin-top:6px;">Colour: green = target wins (composite >0), intensity = strength of the advantage. Click a cell → filter the table below.</div>`;
    el.heat.innerHTML = html;
  }

  function renderCatSubsets(){
    const rows = (raw.optimal.best_category_subsets_ranked||[]).slice(0,10);
    if(!rows.length){ el.catSubsets.innerHTML='<div class="fl-empty">Not enough categories for brute force.</div>'; return; }
    let html = '<table><thead><tr><th>#</th><th>Category subset</th><th class="num">Target success</th><th class="num">Others success</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Evid.</th></tr></thead><tbody>';
    rows.forEach((r,i)=>{
      const isBest = i===0;
      html+=`<tr style="${isBest?'background:rgba(0,229,155,.07);':''}"><td class="mono">${isBest?'🏆':i+1}</td><td><code>${r.label}</code></td><td class="num mono">${fmtPct(r.target_summary.success_rate)}</td><td class="num mono">${fmtPct(r.other_summary.success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td><td class="num mono" style="font-weight:700; color:${r.delta.composite>0?'var(--mint)':'var(--fg)'}">${fmtDelta(r.delta.composite)}</td><td style="font-size:11px; color:var(--fg-faint);">${r.target_summary.evaluated} vs ${r.other_summary.evaluated}${r.enough_data?' ✅':' ⚠️'}</td></tr>`;
    });
    html+='</tbody></table>';
    el.catSubsets.innerHTML = html;
  }

  function renderVsComp(){
    const rows = raw.vs_competitors || [];
    if(!rows.length){ el.vsComp.innerHTML='<div class="fl-empty">No competitors.</div>'; return; }
    let html = '<table><thead><tr><th>Competitor</th><th class="num">Target</th><th class="num">Competitor</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Verdict</th></tr></thead><tbody>';
    rows.forEach(r=>{
      html+=`<tr><td class="mono" style="font-size:11.5px; max-width:320px; overflow:hidden; text-overflow:ellipsis;">${r.filter.competitor}</td><td class="num mono">${fmtPct(r.target_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.target_summary.mean_score)}</div></td><td class="num mono">${fmtPct(r.other_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.other_summary.mean_score)}</div></td><td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td><td class="num mono" style="font-weight:700;">${fmtDelta(r.delta.composite)}</td><td>${r.delta.wins_both ? '<span class="badge badge-passed">WIN</span>' : (r.delta.delta_success_rate>0?'<span class="badge badge-neutral">partial</span>':'<span class="badge badge-failed">lose</span>')}</td></tr>`;
    });
    html+='</tbody></table>';
    el.vsComp.innerHTML = html;
  }

  function tableHTML(rows){
    let html = '<table><thead><tr><th>Slice</th><th class="num">Target</th><th class="num">Others</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th class="num">Target eval</th><th class="num">Others eval</th><th>Status</th></tr></thead><tbody>';
    rows.forEach(r=>{
      const win = r.delta.wins_both;
      html+=`<tr style="${win && r.enough_data?'background:rgba(0,229,155,.06);':''}">
        <td><strong>${r.label}</strong><div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono);">${r.key}</div></td>
        <td class="num mono">${fmtPct(r.target_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.target_summary.mean_score)}</div></td>
        <td class="num mono">${fmtPct(r.other_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.other_summary.mean_score)}</div></td>
        <td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td>
        <td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td>
        <td class="num mono" style="font-weight:700; color:${r.delta.composite>0?'var(--mint)': r.delta.composite<0?'var(--red)':'var(--fg)'}">${fmtDelta(r.delta.composite)}</td>
        <td class="num mono">${r.target_summary.passed}/${r.target_summary.evaluated}</td>
        <td class="num mono">${r.other_summary.passed}/${r.other_summary.evaluated}</td>
        <td>${win ? '<span class="badge badge-passed">WIN both</span>' : '<span class="badge badge-neutral">—</span>'} ${r.enough_data?'<span class="badge badge-info">enough</span>':'<span class="badge badge-neutral">low n</span>'}</td>
      </tr>`;
    });
    html+='</tbody></table>';
    return html;
  }

  function tasksTableHTML(rows){
    let html = '<table class="table-wide"><thead><tr><th>Task</th><th>Category</th><th>Difficulty</th><th class="num">Target</th><th class="num">Others</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Link</th></tr></thead><tbody>';
    rows.forEach(r=>{
      const win = r.delta.wins_both;
      html+=`<tr style="${win && r.enough_data?'background:rgba(0,229,155,.06);':''}">
        <td><a href="/tasks/${r.filter.task_uid}" class="mono" style="font-weight:600;">${r.filter.task_uid}</a><div style="font-size:11px; color:var(--fg-faint); max-width:280px; overflow:hidden; text-overflow:ellipsis;">${r.filter.title||''}</div></td>
        <td><span class="badge badge-info">${r.filter.category||'—'}</span></td><td><span class="badge badge-neutral">${r.filter.difficulty||'—'}</span></td>
        <td class="num mono">${fmtPct(r.target_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.target_summary.mean_score)}</div></td>
        <td class="num mono">${fmtPct(r.other_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.other_summary.mean_score)}</div></td>
        <td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td>
        <td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td>
        <td class="num mono" style="font-weight:700;">${fmtDelta(r.delta.composite)}</td>
        <td><a href="/runs?task_uid=${r.filter.task_uid}" class="btn btn-sm">Runs</a></td>
      </tr>`;
    });
    html+='</tbody></table>';
    return html;
  }

  function renderTables(){
    const cat = filteredSorted(raw.slices.by_category);
    const diff = filteredSorted(raw.slices.by_difficulty);
    const catdiff = filteredSorted(raw.slices.by_category_difficulty);
    const tasks = filteredSorted(raw.slices.by_task);
    const winning = raw.optimal.winning_slices || [];
    // show panels if have data
    if(cat.length || raw.slices.by_category.length){
      el.panelCat.style.display='block';
      el.catCount.textContent = `${cat.length} / ${raw.slices.by_category.length}`;
      el.catTable.innerHTML = tableHTML(cat.length?cat:raw.slices.by_category);
    }
    if(diff.length || raw.slices.by_difficulty.length){
      el.panelDiff.style.display='block';
      el.diffCount.textContent = `${diff.length} / ${raw.slices.by_difficulty.length}`;
      el.diffTable.innerHTML = tableHTML(diff.length?diff:raw.slices.by_difficulty);
    }
    if(catdiff.length || raw.slices.by_category_difficulty.length){
      el.panelCatDiff.style.display='block';
      el.catDiffCount.textContent = `${catdiff.length} / ${raw.slices.by_category_difficulty.length}`;
      el.catDiffTable.innerHTML = tableHTML(catdiff.length?catdiff:raw.slices.by_category_difficulty);
    }
    if(tasks.length || raw.slices.by_task.length){
      el.panelTasks.style.display='block';
      el.tasksCount.textContent = `${tasks.length} / ${raw.slices.by_task.length}`;
      el.tasksTable.innerHTML = tasksTableHTML(tasks.length?tasks:raw.slices.by_task);
    }
    // task set
    const tset = raw.optimal.task_set_winning || raw.optimal.task_set_winning_all;
    if(tset){
      el.panelTaskSet.style.display='block';
      el.taskSetBadge.textContent = `${tset.filter.task_uids.length} tasks`;
      el.taskSetBody.innerHTML = `
        <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:12px;">
          <div><strong>${tset.label}</strong> — composite <span class="${deltaClass(tset.delta.composite)}" style="font-weight:700;">${fmtDelta(tset.delta.composite)}</span> · Δsuccess <span class="${deltaClass(tset.delta.delta_success_rate)}">${fmtDelta(tset.delta.delta_success_rate)}</span> · Δscore <span class="${deltaClass(tset.delta.delta_mean_score)}">${fmtDelta(tset.delta.delta_mean_score)}</span></div>
          <div style="font-size:11.5px; color:var(--fg-faint);">target ${fmtPct(tset.target_summary.success_rate)} (${tset.target_summary.passed}/${tset.target_summary.evaluated}) vs others ${fmtPct(tset.other_summary.success_rate)} (${tset.other_summary.passed}/${tset.other_summary.evaluated}) · score ${fmtScore(tset.target_summary.mean_score)} vs ${fmtScore(tset.other_summary.mean_score)}</div>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;">${tset.filter.task_uids.map(id=>{
          const meta = raw.slices.by_task.find(s=>s.filter.task_uid===id);
          const cat = meta?.filter.category||''; const diff=meta?.filter.difficulty||'';
          return `<a href="/tasks/${id}" class="chip" style="font-size:11px;">${id}<span style="color:var(--fg-faint); margin-left:6px;">${cat}·${diff}</span></a>`;
        }).join('')}</div>
        <div style="margin-top:10px;"><a href="/runs?search=${tset.filter.task_uids.slice(0,5).join(' ')}" class="btn btn-sm">View runs for these tasks</a> <span style="font-size:11px; color:var(--fg-faint);">This is the maximised set — every task in it is a task where the target wins on both indicators.</span></div>
      `;
    }
    if(winning.length){
      el.panelWinning.style.display='block';
      el.winningCount.textContent = `${winning.length}`;
      let html = '<table><thead><tr><th>#</th><th>Slice</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th class="num">Target</th><th class="num">Others</th></tr></thead><tbody>';
      winning.forEach((r,i)=>{
        html+=`<tr><td class="mono">${i+1}</td><td><code>${r.key}</code> — <strong>${r.label}</strong><div style="font-size:11px; color:var(--fg-faint);">${r.enough_data?'✅ enough':'⚠️ low'} · ${r.target_summary.evaluated} vs ${r.other_summary.evaluated} eval</div></td><td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td><td class="num mono" style="font-weight:700; color:var(--mint);">${fmtDelta(r.delta.composite)}</td><td class="num mono">${fmtPct(r.target_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.target_summary.mean_score)}</div></td><td class="num mono">${fmtPct(r.other_summary.success_rate)}<div style="font-size:10px; color:var(--fg-faint);">${fmtScore(r.other_summary.mean_score)}</div></td></tr>`;
      });
      html+='</tbody></table>';
      el.winningTable.innerHTML = html;
    }
  }

  function render(){
    if(!raw) return;
    el.loading.style.display='none';
    if(raw.meta.total_runs===0 || raw.target.runs===0){
      el.empty.style.display='block';
      el.empty.innerHTML = `<div class="panel-body"><strong>No data for the target.</strong><div style="color:var(--fg-dim); font-size:13px; margin-top:6px;">The history has ${raw.meta.total_runs} runs, but none were recognised as <code>auto_codex+knowledge</code>. Check whether experiments were run with the <code>auto_codex</code> model and the <code>agentic_knowledge</code> pipeline.</div><div style="margin-top:10px; font-size:11.5px; color:var(--fg-faint); font-family:var(--mono);">Meta: categories=${raw.meta.categories.join(', ')||'—'} · difficulties=${raw.meta.difficulties.join(', ')||'—'} · tasks=${raw.meta.total_tasks}</div></div>`;
      return;
    }
    renderKPIs();
    renderVerdict();
    renderHero();
    renderCoverage();
    renderCharts();
    renderTables();
  }

  // events
  el.reload.addEventListener('click', fetchData);
  el.minRuns.addEventListener('change', fetchData);
  el.sort.addEventListener('change', ()=>{ if(raw) renderTables(); });
  el.onlyWinning.addEventListener('change', ()=>{ if(raw) renderTables(); });
  el.onlyEnough.addEventListener('change', ()=>{ if(raw) renderTables(); });
  el.copyLink.addEventListener('click', ()=>{
    const url = new URL(window.location.href);
    url.searchParams.set('min_runs', el.minRuns.value);
    navigator.clipboard.writeText(url.toString()).then(()=>{ el.copyLink.textContent='Copied!'; setTimeout(()=> el.copyLink.textContent='Copy link',1200); });
  });
  // pinned toggle
  if(el.pin){
    el.pin.addEventListener('click', ()=>{
      const c = document.getElementById('bmControls');
      const pinned = c.classList.toggle('pinned-explicit');
      // toggle sticky: if not pinned explicit and mobile we want static, but we use CSS for that
      if(c.classList.contains('pinned-controls')){
        c.style.position = pinned ? 'sticky' : 'sticky';
      }
      el.pin.setAttribute('aria-pressed', pinned ? 'true':'false');
      el.pin.querySelector('.pin-label').textContent = pinned ? 'Pinned' : 'Unpinned';
    });
  }
  // init from URL
  const urlMin = new URLSearchParams(window.location.search).get('min_runs');
  if(urlMin) el.minRuns.value = urlMin;
  // fetch immediately on tab enter
  fetchData();
})();

// Best Match — exhaustive search for where auto_codex+knowledge wins
(() => {
  const $ = (s) => document.querySelector(s);
  const el = {
    loading: $('#bmLoading'),
    kpis: $('#bmKpis'),
    verdict: $('#bmVerdict'),
    hero: $('#bmHero'),
    heroBody: $('#bmHeroBody'),
    optimalGrid: $('#bmOptimalGrid'),
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
    [el.kpis, el.verdict, el.hero, el.optimalGrid, el.charts, el.panelCat, el.panelDiff, el.panelCatDiff, el.panelTasks, el.panelTaskSet, el.panelWinning, el.empty].forEach(e=>e.style.display='none');
    // destroy charts
    Object.values(charts).forEach(c=>{ try{c.destroy();}catch{} });
    charts={};
    try{
      const res = await fetch(`/api/best-match?min_runs=${encodeURIComponent(minRuns)}`);
      if(!res.ok) throw new Error(`HTTP ${res.status}`);
      raw = await res.json();
      render();
    }catch(e){
      el.loading.innerHTML = `<div class="fl-empty">Błąd pobierania: ${e.message}</div>`;
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
    el.targetDesc.innerHTML = `Znaleziono <strong style="color:var(--mint);">${t.runs} runów</strong> target (<strong>${t.evaluated} evaluated</strong>) vs <strong>${b.runs} runów</strong> baseline (<strong>${b.evaluated} evaluated</strong>)`;
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
      kpiCard('Δ mean_score', `<span class="${deltaClass(dScore)}">${fmtDelta(dScore)}</span>`, `${o.delta.wins_both?'✅ wygrywa na oba wskaźniki':'—'} · composite ${o.delta.composite==null?'—':fmtDelta(o.delta.composite)}`, o.delta.wins_both?'card-mint':'') +
      kpiCard('Wygrywające slice’y', `${raw.optimal.winning_slices.length}`, `z ${raw.optimal.winning_slices_all.length} wszystkich z win na oba wskaźniki`, raw.optimal.winning_slices.length?'card-amber':'') +
      kpiCard('Optymalne zadania', `${(raw.optimal.winning_task_ids||[]).length} tasks`, `gdzie target wygrywa — łączny zestaw maksymalizujący`, (raw.optimal.winning_task_ids||[]).length?'card-mint':'');
  }

  function renderVerdict(){
    el.verdict.style.display='block';
    const o = raw.overall;
    const interp = raw.interpretation.overall_verdict;
    const color = o.delta.wins_both ? 'var(--mint)' : (o.delta.delta_success_rate>0 ? 'var(--amber)' : 'var(--red)');
    el.verdict.innerHTML = `<div class="panel-body" style="display:flex; gap:14px; align-items:center; flex-wrap:wrap;">
      <div style="width:10px; height:48px; border-radius:4px; background:${color}; flex-shrink:0;"></div>
      <div style="flex:1;">
        <div style="font-weight:600; color:${color};">Werdykt ogólny: ${interp}</div>
        <div style="font-size:12.5px; color:var(--fg-dim); margin-top:4px;">Overall Δsuccess <span class="${deltaClass(o.delta.delta_success_rate)}">${fmtDelta(o.delta.delta_success_rate)}</span> · Δscore <span class="${deltaClass(o.delta.delta_mean_score)}">${fmtDelta(o.delta.delta_mean_score)}</span> · target ${fmtPct(o.target_summary.success_rate)} (${o.target_summary.passed}/${o.target_summary.evaluated}) vs others ${fmtPct(o.other_summary.success_rate)} (${o.other_summary.passed}/${o.other_summary.evaluated})</div>
        <div style="font-size:11.5px; color:var(--fg-faint); margin-top:2px; font-family:var(--mono);">Definicja wygranej: Δsuccess &gt; 0 <strong>i</strong> Δmean_score &gt; 0 jednocześnie → maksymalizacja wszystkich wskaźników jakości. Sortowanie po <code>composite = Δsuccess + Δscore</code>.</div>
      </div>
      <div style="display:flex; gap:8px;">
        <a href="/compare" class="btn btn-sm">Porównaj w Studio</a>
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
        <div style="font-size:11px; color:var(--mint); font-family:var(--mono); letter-spacing:.05em;">🏆 GLOBAL BEST — maksymalizuje wszystkie wskaźniki jakości</div>
        <div style="font-size:1.25rem; font-weight:700; margin:4px 0; color:var(--fg-strong);">${globalBest.label}</div>
        <div style="font-size:12.5px; color:var(--fg-dim);">Δsuccess <span class="${deltaClass(globalBest.delta.delta_success_rate)}">${fmtDelta(globalBest.delta.delta_success_rate)}</span> · Δscore <span class="${deltaClass(globalBest.delta.delta_mean_score)}">${fmtDelta(globalBest.delta.delta_mean_score)}</span> · composite <strong>${fmtDelta(globalBest.delta.composite)}</strong> &nbsp;|&nbsp; target ${fmtPct(globalBest.target_summary.success_rate)} (${globalBest.target_summary.passed}/${globalBest.target_summary.evaluated}) vs others ${fmtPct(globalBest.other_summary.success_rate)} (${globalBest.other_summary.passed}/${globalBest.other_summary.evaluated}) · target score ${fmtScore(globalBest.target_summary.mean_score)} vs ${fmtScore(globalBest.other_summary.mean_score)}</div>
        <div style="font-size:11.5px; color:var(--fg-faint); font-family:var(--mono); margin-top:4px;">${globalBest.enough_data ? '✅ wystarczająco danych (≥ min_runs)' : '⚠️ mało danych — wynik orientacyjny'} · kluc: <code>${globalBest.key}</code></div>
      </div>`;
    }
    html += `<div class="bm-hero-grid">`;
    function heroCard(title, obj, icon){
      if(!obj) return `<div class="bm-hero-card"><div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono);">${title}</div><div style="color:var(--fg-faint); margin-top:6px;">brak danych</div></div>`;
      const isBest = globalBest && obj.key===globalBest.key;
      return `<div class="bm-hero-card ${isBest?'best':''}"><div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono);">${icon} ${title}</div>
        <div style="font-weight:700; margin:6px 0 4px; font-size:13.5px;">${obj.label}</div>
        <div style="font-size:12px;"><span class="${deltaClass(obj.delta.delta_success_rate)}">${fmtDelta(obj.delta.delta_success_rate)}</span> success · <span class="${deltaClass(obj.delta.delta_mean_score)}">${fmtDelta(obj.delta.delta_mean_score)}</span> score · <strong style="color:var(--mint);">${fmtDelta(obj.delta.composite)}</strong> composite</div>
        <div style="font-size:11.5px; color:var(--fg-dim); margin-top:6px;">target ${fmtPct(obj.target_summary.success_rate)} vs others ${fmtPct(obj.other_summary.success_rate)}<br>score ${fmtScore(obj.target_summary.mean_score)} vs ${fmtScore(obj.other_summary.mean_score)}</div>
        <div style="font-size:11px; color:var(--fg-faint); margin-top:6px; font-family:var(--mono);">${obj.enough_data?'✅':'⚠️'} ${obj.target_summary.evaluated} vs ${obj.other_summary.evaluated} evaluated · ${obj.target_summary.runs} vs ${obj.other_summary.runs} runs</div>
      </div>`;
    }
    html += heroCard('Najlepsza kategoria', bestCat, '📦');
    html += heroCard('Najlepsza trudność', bestDiff, '🎯');
    html += heroCard('Najlepsze kategoria × trudność', bestCatDiff, '🔀');
    html += heroCard('Najlepsze zadanie', bestTask, '🧩');
    html += heroCard('Optymalny podzbiór kategorii (brute-force)', bestCatSubset, '📚');
    if(taskSet){
      html += `<div class="bm-hero-card best" style="grid-column: span 2;">
        <div style="font-size:11px; color:var(--mint); font-family:var(--mono);">🧪 ZESTAW MAKSYMALIZUJĄCY — wszystkie wygrywające zadania razem</div>
        <div style="font-weight:700; margin:6px 0 4px; font-size:14px;">${taskSet.label} — ${taskSet.filter.task_uids.length} zadań</div>
        <div style="font-size:12px;"><span class="${deltaClass(taskSet.delta.delta_success_rate)}">${fmtDelta(taskSet.delta.delta_success_rate)}</span> success · <span class="${deltaClass(taskSet.delta.delta_mean_score)}">${fmtDelta(taskSet.delta.delta_mean_score)}</span> score · <strong>${fmtDelta(taskSet.delta.composite)}</strong></div>
        <div style="font-size:11.5px; color:var(--fg-dim); margin-top:6px;">target ${fmtPct(taskSet.target_summary.success_rate)} (${taskSet.target_summary.passed}/${taskSet.target_summary.evaluated}) vs others ${fmtPct(taskSet.other_summary.success_rate)} (${taskSet.other_summary.passed}/${taskSet.other_summary.evaluated})</div>
        <div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:4px;">${taskSet.filter.task_uids.map(id=>`<a href="/tasks/${id}" class="chip chip-sm" style="font-size:10.5px;">${id}</a>`).join(' ')}</div>
        <div style="font-size:11px; color:var(--fg-faint); margin-top:6px; font-family:var(--mono);">Połączony wynik dla całego zestawu — dokładnie w tej sytuacji konfiguracja bije inne.</div>
      </div>`;
    }
    html += `</div>`;
    if(taskSet){
      html += `<div style="margin-top:12px; padding:10px 14px; background:rgba(255,180,74,.08); border:1px solid var(--amber-border); border-radius:8px; font-size:12.5px; color:var(--fg-dim);">
        <strong style="color:var(--amber);">Jak czytać:</strong> To jest <em>zmaksymalizowana sytuacja</em> — filtr zadań/kategorii/trudności, w którym <code>auto_codex+knowledge</code> jednocześnie maksymalizuje <code>success_rate</code> i <code>mean_score</code>. Composite = Δsuccess + Δscore. Im większy, tym silniejsza przewaga nad wszystkimi innymi konfiguracjami.
      </div>`;
    }
    el.heroBody.innerHTML = html;
  }

  function renderOptimalGrid(){
    el.optimalGrid.style.display='grid';
    const o = raw.optimal;
    const cards = [];
    function card(title, obj, note){
      if(!obj) return;
      const d = obj.delta;
      cards.push(`<div class="card" style="border-top:2px solid ${d.wins_both?'var(--mint)':'var(--line)'};">
        <div class="card-title">${title}</div>
        <div style="font-weight:700; font-size:15px; margin:6px 0;">${obj.label}</div>
        <div style="font-family:var(--mono); font-size:12px;">Δsuccess <span class="${deltaClass(d.delta_success_rate)}">${fmtDelta(d.delta_success_rate)}</span> · Δscore <span class="${deltaClass(d.delta_mean_score)}">${fmtDelta(d.delta_mean_score)}</span> · <strong>${fmtDelta(d.composite)}</strong></div>
        <div style="font-size:11.5px; color:var(--fg-faint); margin-top:6px;">${note||''}<br>target ${fmtPct(obj.target_summary.success_rate)} vs ${fmtPct(obj.other_summary.success_rate)} · ${obj.target_summary.evaluated} vs ${obj.other_summary.evaluated} eval</div>
      </div>`);
    }
    card('Najlepsza kategoria', o.best_category, `kategoria: ${o.best_category?.filter.category||''}`);
    card('Najlepsza trudność', o.best_difficulty, `trudność: ${o.best_difficulty?.filter.difficulty||''}`);
    card('Najlepsze kat×trud', o.best_category_difficulty, '');
    card('Najlepsze zadanie', o.best_task, `${o.best_task?.filter.category||''} · ${o.best_task?.filter.difficulty||''}`);
    card('Najlepszy podzbiór kategorii', o.best_category_subset, `brute-force 2^n kategorii`);
    if(o.task_set_winning) card('Zestaw wygrywających zadań', o.task_set_winning, `${o.task_set_winning.filter.task_uids.length} tasks`);
    el.optimalGrid.innerHTML = cards.join('');
  }

  function renderCharts(){
    el.charts.style.display='block';
    // category bar
    const cats = raw.slices.by_category || [];
    const catLabels = cats.map(c=>c.label);
    const catComp = cats.map(c=>c.delta.composite ?? 0);
    const catWins = cats.map(c=> c.delta.wins_both && c.enough_data);
    const ctxCat = document.getElementById('chCat');
    if(ctxCat){
      charts.chCat = new Chart(ctxCat, {
        type:'bar',
        data:{ labels:catLabels, datasets:[{ label:'composite Δ', data:catComp, backgroundColor: catComp.map((v,i)=> catWins[i]?'#00e59b':(v>0?'#5aa9ff':'#ff6b7a')), borderWidth:0 }]},
        options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c)=> `${c.label}: ${c.raw?.toFixed(3)}`}}}, scales:{ x:{ ticks:{color:'#a5b3c2', font:{family:'ui-monospace', size:11}}}, y:{ ticks:{color:'#a5b3c2'}, grid:{color:'rgba(255,255,255,.06)'} } } }
      });
    }
    const diffs = raw.slices.by_difficulty || [];
    const diffLabels = diffs.map(d=>d.label);
    const diffComp = diffs.map(d=>d.delta.composite ?? 0);
    const diffWins = diffs.map(d=> d.delta.wins_both && d.enough_data);
    const ctxDiff = document.getElementById('chDiff');
    if(ctxDiff){
      charts.chDiff = new Chart(ctxDiff, {
        type:'bar',
        data:{ labels:diffLabels, datasets:[{ label:'composite Δ', data:diffComp, backgroundColor: diffComp.map((v,i)=> diffWins[i]?'#00e59b':(v>0?'#5aa9ff':'#ff6b7a')), borderWidth:0 }]},
        options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{ x:{ ticks:{color:'#a5b3c2'}}, y:{ ticks:{color:'#a5b3c2'}, grid:{color:'rgba(255,255,255,.06)'} } } }
      });
    }
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
    html+=`<div style="font-size:11px; color:var(--fg-faint); font-family:var(--mono); margin-top:6px;">Kolor: zielony = target wygrywa (composite >0), intensywność = siła przewagi. Klik w komórkę → filtr w tabeli poniżej.</div>`;
    el.heat.innerHTML = html;
  }

  function renderCatSubsets(){
    const rows = (raw.optimal.best_category_subsets_ranked||[]).slice(0,10);
    if(!rows.length){ el.catSubsets.innerHTML='<div class="fl-empty">Za mało kategorii do brute-force.</div>'; return; }
    let html = '<table><thead><tr><th>#</th><th>Podzbiór kategorii</th><th class="num">Target success</th><th class="num">Others success</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Evid.</th></tr></thead><tbody>';
    rows.forEach((r,i)=>{
      const isBest = i===0;
      html+=`<tr style="${isBest?'background:rgba(0,229,155,.07);':''}"><td class="mono">${isBest?'🏆':i+1}</td><td><code>${r.label}</code></td><td class="num mono">${fmtPct(r.target_summary.success_rate)}</td><td class="num mono">${fmtPct(r.other_summary.success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_success_rate)}">${fmtDelta(r.delta.delta_success_rate)}</td><td class="num mono ${deltaClass(r.delta.delta_mean_score)}">${fmtDelta(r.delta.delta_mean_score)}</td><td class="num mono" style="font-weight:700; color:${r.delta.composite>0?'var(--mint)':'var(--fg)'}">${fmtDelta(r.delta.composite)}</td><td style="font-size:11px; color:var(--fg-faint);">${r.target_summary.evaluated} vs ${r.other_summary.evaluated}${r.enough_data?' ✅':' ⚠️'}</td></tr>`;
    });
    html+='</tbody></table>';
    el.catSubsets.innerHTML = html;
  }

  function renderVsComp(){
    const rows = raw.vs_competitors || [];
    if(!rows.length){ el.vsComp.innerHTML='<div class="fl-empty">Brak konkurentów.</div>'; return; }
    let html = '<table><thead><tr><th>Konkurent</th><th class="num">Target</th><th class="num">Konkurent</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Werdykt</th></tr></thead><tbody>';
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
        <td>${win ? '<span class="badge badge-passed">WIN oba</span>' : '<span class="badge badge-neutral">—</span>'} ${r.enough_data?'<span class="badge badge-info">enough</span>':'<span class="badge badge-neutral">low n</span>'}</td>
      </tr>`;
    });
    html+='</tbody></table>';
    return html;
  }

  function tasksTableHTML(rows){
    let html = '<table class="table-wide"><thead><tr><th>Task</th><th>Kategoria</th><th>Trudność</th><th class="num">Target</th><th class="num">Others</th><th class="num">Δsuccess</th><th class="num">Δscore</th><th class="num">Composite</th><th>Link</th></tr></thead><tbody>';
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
        <div style="margin-top:10px;"><a href="/runs?search=${tset.filter.task_uids.slice(0,5).join(' ')}" class="btn btn-sm">Zobacz runs dla tych zadań</a> <span style="font-size:11px; color:var(--fg-faint);">To jest zmaksymalizowany zestaw — każdy task w nim to task, gdzie target wygrywa oba wskaźniki.</span></div>
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
      el.empty.innerHTML = `<div class="panel-body"><strong>Brak danych dla targetu.</strong><div style="color:var(--fg-dim); font-size:13px; margin-top:6px;">Historia ma ${raw.meta.total_runs} runs, ale żaden nie został rozpoznany jako <code>auto_codex+knowledge</code>. Sprawdź czy zostały uruchomione eksperymenty z modelem <code>auto_codex</code> i pipeline <code>agentic_knowledge</code>.</div><div style="margin-top:10px; font-size:11.5px; color:var(--fg-faint); font-family:var(--mono);">Meta: categories=${raw.meta.categories.join(', ')||'—'} · difficulties=${raw.meta.difficulties.join(', ')||'—'} · tasks=${raw.meta.total_tasks}</div></div>`;
      return;
    }
    renderKPIs();
    renderVerdict();
    renderHero();
    renderOptimalGrid();
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

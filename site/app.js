const state = {
  products: [], events: [], status: {}, view: 'latest', model: 'ALL', source: 'ALL', period: 7,
  patternLevel: 'ALL', patternCategory: 'ALL', favorites: new Set(), feedback: {},
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const beijing = (iso) => iso ? new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false,
}).format(new Date(iso)) : '—';
const fullBeijing = (iso) => iso ? new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false,
}).format(new Date(iso)) + '（北京时间）' : '尚无';
const ageDays = (iso) => (Date.now() - new Date(iso).getTime()) / 86400000;

function loadLocal() {
  try { state.favorites = new Set(JSON.parse(localStorage.getItem('fw:favorites') || '[]')); } catch (_) {}
  try { state.feedback = JSON.parse(localStorage.getItem('fw:feedback') || '{}'); } catch (_) {}
}
function saveLocal() {
  localStorage.setItem('fw:favorites', JSON.stringify([...state.favorites]));
  localStorage.setItem('fw:feedback', JSON.stringify(state.feedback));
}

function applyUrl() {
  const params = new URLSearchParams(location.search);
  const view = params.get('view'); const model = params.get('model');
  if (['latest','current','patterns','history','favorites','status'].includes(view)) state.view = view;
  if (['F171','F705','F141','F640','RF640','F41'].includes(model)) state.model = model === 'RF640' ? 'F640' : model;
  if (model === 'RF640') state.source = 'RF640';
}

function modelMatch(p) {
  if (state.model === 'ALL') return true;
  if (state.model === 'F640') return p.family === 'F640' && (state.source === 'ALL' || p.source_key === state.source);
  return p.model === state.model || p.family === state.model;
}

function adjustedScore(product) {
  const base = product.pattern?.score || 0; const feedback = state.feedback[product.id];
  if (feedback === 'false_positive') return base - 35;
  if (feedback === 'dislike') return base - 15;
  if (feedback === 'collectible') return base + 20;
  if (feedback === 'like') return base + 8;
  return base;
}

function visibleProducts() {
  const eventIds = new Set(state.events.map(e => e.product_id));
  let items = state.products.filter(modelMatch);
  if (state.view === 'latest') items = items.filter(p => eventIds.has(p.id) && ageDays(p.first_seen_at) <= state.period);
  if (state.view === 'current') items = items.filter(p => p.status === 'available');
  if (state.view === 'patterns') items = items.filter(p => p.pattern && p.pattern.level !== '普通' && p.pattern.level !== '未知')
    .filter(p => state.patternLevel === 'ALL' || p.pattern.level === state.patternLevel)
    .filter(p => state.patternCategory === 'ALL' || (p.pattern.categories || []).some(c => c.startsWith(state.patternCategory)));
  if (state.view === 'favorites') items = items.filter(p => state.favorites.has(p.id));
  if (state.view === 'patterns') items.sort((a,b) => adjustedScore(b) - adjustedScore(a));
  else items.sort((a,b) => String(b.first_seen_at).localeCompare(String(a.first_seen_at)));
  return items;
}

function statusLabel(value) {
  return {available:'在售', possibly_sold:'待确认', sold:'已售罄'}[value] || '未知';
}

function renderControls() {
  const controls = $('#controls'); controls.innerHTML = '';
  if (state.view === 'latest') {
    controls.innerHTML = `<select id="period"><option value="1">最近24小时</option><option value="7">最近7天</option><option value="30">最近30天</option></select>`;
    $('#period').value = String(state.period); $('#period').onchange = e => { state.period = Number(e.target.value); render(); };
  } else if (state.view === 'patterns') {
    controls.innerHTML = `<select id="pattern-level"><option value="ALL">全部等级</option><option>疑似稀有</option><option>值得关注</option></select>
      <select id="pattern-category"><option value="ALL">全部类型</option><option value="A">A 文字</option><option value="B">B 几何</option><option value="C">C 具象候选</option><option value="D">D 历史差异</option></select>`;
    $('#pattern-level').value = state.patternLevel; $('#pattern-category').value = state.patternCategory;
    $('#pattern-level').onchange = e => { state.patternLevel=e.target.value; render(); };
    $('#pattern-category').onchange = e => { state.patternCategory=e.target.value; render(); };
  } else if (state.view === 'favorites') {
    controls.innerHTML = `<button id="export-local">导出收藏与反馈</button><label class="file-label">导入<input id="import-local" type="file" accept="application/json"></label>`;
    $('#export-local').onclick = exportLocal; $('#import-local').onchange = importLocal;
  }
}

function renderCard(product) {
  const node = $('#card-template').content.firstElementChild.cloneNode(true);
  if (state.view === 'favorites') node.classList.add('favorites-view');
  if (state.view === 'patterns') node.classList.add('patterns-view');
  const img = node.querySelector('img'); img.src = product.images?.[0] || 'icon.svg'; img.alt = `${product.full_name} ${product.official_item_number}`;
  node.querySelector('.image-button').onclick = () => openGallery(product);
  node.querySelector('h2').textContent = product.full_name || `${product.model} ${product.name}`;
  const badge = node.querySelector('.state-badge'); badge.textContent = statusLabel(product.status); badge.classList.add(product.status || 'unknown');
  node.querySelector('.item-number').textContent = `#${product.official_item_number} · ${product.primary_color || '未标注'}`;
  const price = product.price == null ? '价格未标注' : `${product.price} ${product.currency || ''}`;
  node.querySelector('.meta').textContent = `${price} · 首见 ${beijing(product.first_seen_at)}${product.is_relisted ? ' · 重新上架' : ''}`;
  const pattern = product.pattern; const note = node.querySelector('.pattern-note');
  note.textContent = pattern ? `${pattern.level} ${pattern.score}/100 · ${pattern.reason}` : '未进行图案分析（基线商品不会追溯分析）';
  const favorite = node.querySelector('.favorite-button');
  favorite.textContent = state.favorites.has(product.id) ? '♥' : '♡'; favorite.classList.toggle('active', state.favorites.has(product.id));
  favorite.onclick = () => { state.favorites.has(product.id) ? state.favorites.delete(product.id) : state.favorites.add(product.id); saveLocal(); render(); };
  node.querySelector('.buy-link').href = product.url;
  node.querySelectorAll('[data-feedback]').forEach(button => {
    button.classList.toggle('selected', state.feedback[product.id] === button.dataset.feedback);
    button.onclick = () => { state.feedback[product.id] = state.feedback[product.id] === button.dataset.feedback ? null : button.dataset.feedback; saveLocal(); render(); };
  });
  node.ondblclick = () => node.classList.toggle('expanded');
  return node;
}

function renderStatus() {
  const panel = $('#status-panel'); const s = state.status; const models = s.models || {};
  const modelRows = ['F171','F705','F141','F640','RF640','F41'].map(key => {
    const m = models[key] || {}; const health = m.last_error ? `异常：${m.last_error}` : (m.initialized ? '正常' : '尚未建立基线');
    return `<p><strong>${key}</strong> · ${m.last_valid_count ?? 0} 件 · ${health}<br>上次成功：${fullBeijing(m.last_success_at)}</p>`;
  }).join('');
  panel.innerHTML = `<div class="status-card"><h2>运行状态</h2><p><strong>最后任一成功：</strong>${fullBeijing(s.last_success_at)}</p><p><strong>最后全部成功：</strong>${fullBeijing(s.last_full_success_at)}</p><p><strong>最近错误：</strong>${s.last_error || '无'}</p></div>
    <div class="status-card"><h2>监控覆盖</h2>${modelRows}</div>
    <div class="status-card"><h2>数据与隐私</h2><p>${s.disclosure || ''}</p><div class="export-row"><a href="data/inventory.json" download>导出 JSON</a><a href="data/inventory.csv" download>导出 CSV</a></div></div>`;
}

function render() {
  $$('.tab').forEach(b => b.classList.toggle('selected', b.dataset.view === state.view));
  $$('#model-nav .chip').forEach(b => b.classList.toggle('selected', b.dataset.model === state.model));
  $$('#f640-subnav .chip').forEach(b => b.classList.toggle('selected', b.dataset.source === state.source));
  $('#f640-subnav').classList.toggle('hidden', state.model !== 'F640');
  document.body.className = `${state.view}-view`;
  const statusMode = state.view === 'status'; $('#grid').classList.toggle('hidden', statusMode); $('#status-panel').classList.toggle('hidden', !statusMode);
  renderControls();
  if (statusMode) { renderStatus(); $('#summary').innerHTML = `<b>系统状态</b><br>监控任务数据与各型号健康度`; return; }
  const items = visibleProducts(); const grid = $('#grid'); grid.innerHTML = '';
  items.forEach(p => grid.appendChild(renderCard(p)));
  if (!items.length) grid.innerHTML = `<p class="empty">这个视图目前没有真实商品记录。首次运行只建立基线，不会把已有库存显示为“新品”。</p>`;
  const labels = {latest:'最新发现',current:'当前在售',patterns:'特殊图案',history:'历史档案',favorites:'我的收藏'};
  $('#summary').innerHTML = `<b>${labels[state.view]} · ${items.length}</b><br>数据更新：${fullBeijing(state.status.last_success_at)}`;
}

function openGallery(product) {
  const content = $('#gallery-content'); content.innerHTML = '';
  (product.images?.length ? product.images : ['icon.svg']).forEach((src,index) => {
    const slide = document.createElement('div'); slide.className='gallery-slide';
    const img = document.createElement('img'); img.src=src; img.alt=`${product.full_name} 图片 ${index+1}`; slide.appendChild(img); content.appendChild(slide);
  });
  $('#gallery-dialog').showModal();
}

function exportLocal() {
  const payload = {version:1, exported_at:new Date().toISOString(), favorites:[...state.favorites], feedback:state.feedback};
  const blob = new Blob([JSON.stringify(payload,null,2)], {type:'application/json'}); const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='freitag-watch-favorites.json'; a.click(); URL.revokeObjectURL(a.href);
}
async function importLocal(event) {
  const file=event.target.files?.[0]; if(!file) return;
  try { const payload=JSON.parse(await file.text()); state.favorites=new Set(payload.favorites || []); state.feedback=payload.feedback || {}; saveLocal(); render(); }
  catch (_) { alert('导入失败：文件不是有效的 FREITAG WATCH 导出文件。'); }
}

async function boot() {
  loadLocal(); applyUrl();
  try {
    const [products,events,status] = await Promise.all(['inventory.json','events.json','status.json'].map(name => fetch(`data/${name}`,{cache:'no-store'}).then(r => {if(!r.ok) throw Error(r.status); return r.json();})));
    state.products=products; state.events=events; state.status=status;
  } catch (error) {
    $('#summary').textContent=`真实库存数据读取失败：${error.message}`; return;
  }
  $$('#model-nav .chip').forEach(b => b.onclick=()=>{state.model=b.dataset.model;state.source='ALL';render();});
  $$('#f640-subnav .chip').forEach(b => b.onclick=()=>{state.source=b.dataset.source;render();});
  $$('.tab').forEach(b => b.onclick=()=>{state.view=b.dataset.view;render();scrollTo({top:0,behavior:'smooth'});});
  $('#gallery-close').onclick=()=>$('#gallery-dialog').close(); $('#info-button').onclick=()=>$('#info-dialog').showModal(); $('#info-close').onclick=()=>$('#info-dialog').close();
  render();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(()=>{});
}
boot();


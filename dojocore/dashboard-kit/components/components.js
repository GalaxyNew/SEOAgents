/* ============================================================
   dashboard-kit · components/components.js
   七件套的零依赖 DOM 工厂（A 档页面用）。
   B 档（React）直接用 components.css 的类名即可，无需引入本文件。
   ============================================================ */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/** 状态 → 胶囊修饰类（全联邦统一语义，禁改） */
export const STATUS_CLASS = {
  IN_PROGRESS: 'dk-pill--in-progress',
  ASSIGNED:    'dk-pill--assigned',
  STALE:       'dk-pill--stale',
  BLOCKED:     'dk-pill--blocked',
  FAILED:      'dk-pill--failed',
  REJECTED:    'dk-pill--failed',
  REVIEW:      'dk-pill--review',
  PASSED:      'dk-pill--passed',
  FRESH:       'dk-pill--fresh',
};

export function statusClass(status) {
  return STATUS_CLASS[String(status || '').toUpperCase()] || 'dk-pill--neutral';
}

/** ① 宫格卡 */
export function KpiCard({ label, value, unit, delta, accent = false, dataStatus }) {
  const root = el('div', 'dk-kpi dk-cardin' + (accent ? ' dk-kpi--accent' : ''));
  const head = el('div', 'dk-kpi__label', label);
  if (dataStatus) head.appendChild(DataBadge(dataStatus));
  root.appendChild(head);

  const v = el('div', 'dk-kpi__value');
  // 数据铁律：缺数渲染空状态而非补零
  v.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
  if (unit) v.appendChild(el('span', 'dk-kpi__unit', unit));
  root.appendChild(v);

  if (delta !== undefined && delta !== null) {
    const dir = Number(delta) > 0 ? 'up' : Number(delta) < 0 ? 'down' : 'flat';
    const sign = Number(delta) > 0 ? '+' : '';
    root.appendChild(el('div', `dk-kpi__delta dk-kpi__delta--${dir}`, `${sign}${delta}`));
  }
  return root;
}

/** ② 状态灯 */
export function StatusDot(kind = 'neutral') {
  const map = { ok: 'ok', warn: 'warn', bad: 'bad', rev: 'rev', accent: 'accent', live: 'live' };
  return el('span', 'dk-dot' + (map[kind] ? ` dk-dot--${map[kind]}` : ''));
}

/** 状态胶囊 */
export function StatusPill(status, text) {
  const p = el('span', `dk-pill ${statusClass(status)}`);
  p.appendChild(StatusDot('accent'));
  p.appendChild(el('span', null, text || status));
  return p;
}

/** 数据新鲜度徽标（数据铁律：MOCK 必须显式标注） */
export function DataBadge(status) {
  const s = String(status || '').toUpperCase();
  const cls = s === 'REAL' ? 'real'
    : s === 'MOCK' ? 'mock'
    : s === 'STALE' ? 'stale'
    : 'na';
  const label = s === 'DATA_UNAVAILABLE' ? 'N/A' : s || 'N/A';
  return el('span', `dk-badge-data dk-badge-data--${cls}`, label);
}

/** ③ 时间线流 */
export function Timeline(items = []) {
  const root = el('div', 'dk-timeline');
  items.forEach((it) => {
    const item = el('div', 'dk-timeline__item dk-cardin');
    const rail = el('div', 'dk-timeline__rail');
    rail.appendChild(StatusDot(it.kind || 'accent'));
    item.appendChild(rail);

    const body = el('div', 'dk-timeline__body');
    if (it.time) body.appendChild(el('div', 'dk-timeline__time', it.time));
    body.appendChild(el('div', 'dk-timeline__title', it.title || ''));
    if (it.desc) body.appendChild(el('div', 'dk-timeline__desc', it.desc));
    item.appendChild(body);
    root.appendChild(item);
  });
  if (!items.length) root.appendChild(EmptyState('暂无事件'));
  return root;
}

/** ④ 任务卡表 */
export function TaskTable({ columns = [], rows = [] }) {
  const wrap = el('div', 'dk-table-wrap');
  const table = el('table', 'dk-table');
  const thead = el('thead');
  const trh = el('tr');
  columns.forEach((c) => trh.appendChild(el('th', null, c.title || c.key)));
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  rows.forEach((row) => {
    const tr = el('tr');
    columns.forEach((c) => {
      const td = el('td', c.numeric ? 'dk-table__num' : c.mono ? 'dk-table__id' : null);
      const raw = row[c.key];
      if (c.key === 'status') td.appendChild(StatusPill(raw));
      else td.textContent = raw === null || raw === undefined || raw === '' ? '—' : String(raw);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  if (!rows.length) wrap.appendChild(EmptyState('暂无任务'));
  return wrap;
}

/** ⑤ 收发件列表 */
export function InboxList(items = []) {
  const root = el('div', 'dk-inbox');
  items.forEach((it) => {
    const item = el('div', 'dk-inbox__item dk-cardin');
    item.appendChild(el('span', `dk-inbox__dir dk-inbox__dir--${it.direction === 'out' ? 'out' : 'in'}`,
      it.direction === 'out' ? 'OUT' : 'IN'));
    const main = el('div', 'dk-inbox__main');
    main.appendChild(el('div', 'dk-inbox__subject', it.subject || '(无主题)'));
    main.appendChild(el('div', 'dk-inbox__meta',
      [it.from, it.to && `→ ${it.to}`, it.time].filter(Boolean).join('  ')));
    item.appendChild(main);
    if (it.status) item.appendChild(StatusPill(it.status));
    root.appendChild(item);
  });
  if (!items.length) root.appendChild(EmptyState('收发件箱为空'));
  return root;
}

/** ⑥ 资产卡 */
export function AssetCard({ name, thumb, size, kind, dataStatus }) {
  const root = el('div', 'dk-asset dk-cardin');
  const t = el('div', 'dk-asset__thumb');
  if (thumb) {
    const img = document.createElement('img');
    img.src = thumb; img.alt = name || 'asset'; img.loading = 'lazy';
    t.appendChild(img);
  } else {
    t.textContent = kind || 'FILE';
  }
  root.appendChild(t);
  const n = el('div', 'dk-asset__name', name || '未命名');
  root.appendChild(n);
  const meta = el('div', 'dk-asset__meta', [kind, size].filter(Boolean).join(' · ') || '—');
  if (dataStatus) meta.appendChild(DataBadge(dataStatus));
  root.appendChild(meta);
  return root;
}

/** ⑦ 图表壳 */
export function ChartShell({ title, extra, height = 220 }) {
  const root = el('div', 'dk-chart');
  const head = el('div', 'dk-chart__head');
  head.appendChild(el('div', 'dk-chart__title', title || ''));
  if (extra) head.appendChild(typeof extra === 'string' ? el('div', 'dk-timeline__time', extra) : extra);
  root.appendChild(head);
  const body = el('div', 'dk-chart__body');
  body.style.height = `${height}px`;
  root.appendChild(body);
  root.body = body; // 供 ECharts init 挂载
  return root;
}

/** 空状态（数据铁律：缺数不补零） */
export function EmptyState(text = '暂无数据', hint) {
  const root = el('div', 'dk-chart__empty');
  root.style.position = 'static';
  root.style.padding = 'var(--sp-6)';
  root.appendChild(el('div', null, text));
  if (hint) root.appendChild(el('div', null, hint));
  return root;
}

const api = {
  KpiCard, StatusDot, StatusPill, DataBadge, Timeline,
  TaskTable, InboxList, AssetCard, ChartShell, EmptyState,
  statusClass, STATUS_CLASS,
};
try { window.DashboardKit = api; } catch { /* SSR */ }
export default api;

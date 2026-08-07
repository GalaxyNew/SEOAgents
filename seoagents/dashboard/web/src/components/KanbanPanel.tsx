import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useIsMobile } from '../hooks'
import { Responsive, WidthProvider, type LayoutItem } from 'react-grid-layout/legacy'

/**
 * 任务流转看板 V8.2 — 20×12 可拖拽网格 (react-grid-layout)
 *
 * - 20 列 × 12 行（比 V8 的 10 列细一倍）
 * - 拖拽卡片换位置，其它卡片自动让位重排
 * - 拖拽右下角手柄改大小，邻居自动联动
 * - 所有可编辑断点都显式映射回 canonical 20 列后持久化
 * - 布局存 localStorage，刷新后恢复；兼容迁移 v8.1 10 列缓存
 * - ✏️ 按钮切换编辑 / 锁定模式
 */

// ── 类型 ──────────────────────────────────────────────────
type Task = {
  id: string; title: string; body: string; assignee: string; status: string
  priority: number; created_by: string
  created_at_iso: string | null; started_at_iso: string | null; completed_at_iso: string | null
  is_open: boolean; current_step_key?: string; workflow_template_id?: string
  last_failure_error?: string; consecutive_failures?: number
}

type Board = {
  ok: boolean; source: string; total: number; open_count: number
  columns: Record<string, Task[]>
  statuses: { open: string[]; closed: string[] }
}

type CollabItem = {
  request_id: string; title?: string; status: string
  from?: { dept: string }; to?: { dept: string; capability?: string }
  capability?: string; deadline?: string; overdue?: boolean
  deliverable_asset_ids?: string[]
  expected_deliverable?: { asset_class: string; count: number; acceptance: string[] }
  priority?: string
}

type DeptStatus = {
  dept_id: string; name: string; running: number; pending: number; done: number; blocked: number
}

// ── 网格常量 ──────────────────────────────────────────────
const CANONICAL_COLS = 20

// ── 断点配置 ──────────────────────────────────────────────
type GridBreakpoint = 'lg' | 'md' | 'sm' | 'xs'
const BREAKPOINTS: Record<GridBreakpoint, number> = { lg: 1180, md: 900, sm: 620, xs: 0 }
const COLS_MAP: Record<GridBreakpoint, number> = { lg: CANONICAL_COLS, md: 16, sm: 8, xs: 1 }
const ROW_HEIGHT = 48   // px, 配合 gap 算

// ── 模块 ID ──────────────────────────────────────────────
type ModuleId = 'stats' | 'running' | 'pending' | 'done' | 'events' | 'collab' | 'depts'
const MODULE_ORDER: ModuleId[] = ['stats', 'running', 'pending', 'done', 'events', 'collab', 'depts']
const MODULE_IDS = new Set<string>(MODULE_ORDER)

// ── 默认 canonical 20 列布局 ─────────────────────────────
const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'stats',   x: 0,  y: 0,  w: 20, h: 2, minW: 8, minH: 1 },
  { i: 'running', x: 0,  y: 2,  w: 12, h: 5, minW: 6, minH: 2 },
  { i: 'events',  x: 12, y: 2,  w: 8,  h: 5, minW: 4, minH: 2 },
  { i: 'pending', x: 0,  y: 7,  w: 6,  h: 3, minW: 4, minH: 1 },
  { i: 'done',    x: 6,  y: 7,  w: 6,  h: 3, minW: 4, minH: 1 },
  { i: 'collab',  x: 12, y: 7,  w: 8,  h: 3, minW: 4, minH: 1 },
  { i: 'depts',   x: 0,  y: 10, w: 20, h: 2, minW: 8, minH: 1 },
]
const DEFAULT_BY_ID = new Map(DEFAULT_LAYOUT.map((item) => [item.i as ModuleId, item]))

const MODULE_LABELS: Record<ModuleId, { icon: string; title: string; color: string; showHeader: boolean }> = {
  stats:   { icon: '📊', title: '统计胶囊',     color: '#4f8cff', showHeader: false },
  running: { icon: '⚡', title: '执行中',       color: '#4f8cff', showHeader: true },
  pending: { icon: '⏳', title: '待办',         color: '#8b93a7', showHeader: true },
  done:    { icon: '✅', title: '已完成',       color: '#3ecf8e', showHeader: true },
  events:  { icon: '●',  title: '实时事件流',   color: '#8b93a7', showHeader: true },
  collab:  { icon: '🔗', title: '跨部门协作流', color: '#dde3f0', showHeader: true },
  depts:   { icon: '📈', title: '部门任务状态', color: '#8b93a7', showHeader: true },
}

const LAYOUT_KEY = 'kp-layout-v8.2-20col'
const LEGACY_LAYOUT_KEY = 'kp-layout-v8.1'
const LAYOUT_VERSION = 2
const MAX_LAYOUT_ROWS = 10_000

type PersistedLayoutV2 = {
  version: typeof LAYOUT_VERSION
  cols: typeof CANONICAL_COLS
  layout: LayoutItem[]
}

type LayoutRect = Pick<LayoutItem, 'x' | 'y' | 'w' | 'h'>

const isFiniteInt = (value: unknown): value is number => (
  typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value)
)

const collides = (a: LayoutRect, b: LayoutRect) => (
  a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
)

/**
 * 仅接受完整、有限、无越界、无碰撞的布局。任何坏缓存都整体拒绝，不能把
 * 一半坏数据交给 react-grid-layout “修一修”，否则会产生负坐标或静默丢卡。
 */
function validateLayout(input: unknown, cols: number): LayoutItem[] | null {
  if (!Array.isArray(input) || input.length !== MODULE_ORDER.length) return null
  const byId = new Map<ModuleId, LayoutItem>()
  for (const raw of input) {
    if (!raw || typeof raw !== 'object') return null
    const item = raw as Record<string, unknown>
    if (typeof item.i !== 'string' || !MODULE_IDS.has(item.i) || byId.has(item.i as ModuleId)) return null
    if (![item.x, item.y, item.w, item.h].every(isFiniteInt)) return null
    const x = item.x as number
    const y = item.y as number
    const w = item.w as number
    const h = item.h as number
    if (x < 0 || y < 0 || w < 1 || h < 1 || x + w > cols || y + h > MAX_LAYOUT_ROWS) return null
    byId.set(item.i as ModuleId, { i: item.i, x, y, w, h })
  }
  const ordered = MODULE_ORDER.map((id) => byId.get(id)!)
  for (let i = 0; i < ordered.length; i++) {
    for (let j = i + 1; j < ordered.length; j++) {
      if (collides(ordered[i], ordered[j])) return null
    }
  }
  return ordered
}

function withCanonicalConstraints(layout: LayoutItem[]): LayoutItem[] {
  return MODULE_ORDER.map((id) => {
    const item = layout.find((candidate) => candidate.i === id)!
    const defaults = DEFAULT_BY_ID.get(id)!
    return {
      i: id,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      minW: Math.min(defaults.minW ?? 1, item.w),
      minH: Math.min(defaults.minH ?? 1, item.h),
    }
  })
}

/**
 * 一维边界的 largest-remainder 映射。所有边界都由同一组整数累计值导出，
 * 所以共享边界保持共享；正向 20→16/8 与反向 16/8→20 使用同一算法。
 */
function mapBoundaries(values: number[], sourceCols: number, targetCols: number): Map<number, number> {
  const unique = [...new Set([0, sourceCols, ...values])].sort((a, b) => a - b)
  const exactIntervals = unique.slice(1).map((value, index) => (
    ((value - unique[index]) * targetCols) / sourceCols
  ))
  const sizes = exactIntervals.map(Math.floor)
  let remainder = targetCols - sizes.reduce((sum, value) => sum + value, 0)
  const ranked = exactIntervals
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index)
  for (let index = 0; index < remainder; index++) sizes[ranked[index].index]++
  const result = new Map<number, number>([[unique[0], 0]])
  let cursor = 0
  sizes.forEach((size, index) => {
    cursor += size
    result.set(unique[index + 1], cursor)
  })
  return result
}

function compactVertically(layout: LayoutItem[]): LayoutItem[] {
  const placed: LayoutItem[] = []
  const sorted = layout.map((item) => ({ ...item })).sort((a, b) => a.y - b.y || a.x - b.x || MODULE_ORDER.indexOf(a.i as ModuleId) - MODULE_ORDER.indexOf(b.i as ModuleId))
  for (const item of sorted) {
    let y = 0
    while (y < item.y && !placed.some((other) => collides({ ...item, y }, other))) y++
    item.y = y
    while (placed.some((other) => collides(item, other))) item.y++
    placed.push(item)
  }
  return MODULE_ORDER.map((id) => placed.find((item) => item.i === id)!)
}

function mapLayoutColumns(base: LayoutItem[], sourceCols: number, targetCols: number): LayoutItem[] {
  if (sourceCols === targetCols) return compactVertically(base.map((item) => ({ ...item })))
  const boundaryMap = mapBoundaries(base.flatMap((item) => [item.x, item.x + item.w]), sourceCols, targetCols)
  const mapped = base.map((item) => {
    const left = boundaryMap.get(item.x)!
    const right = boundaryMap.get(item.x + item.w)!
    return {
      ...item,
      x: Math.min(left, targetCols - 1),
      w: Math.max(1, Math.min(targetCols - left, right - left)),
      // minW 也必须在同一坐标系；不能把 canonical minW=8 原样塞进 8 列布局。
      minW: Math.max(1, Math.min(targetCols, Math.round((item.minW ?? 1) * targetCols / sourceCols))),
    }
  })
  return compactVertically(mapped)
}

// 单列只读堆叠布局（移动端竖排，并为触控内容预留足够高度）
const MOBILE_HEIGHTS: Record<ModuleId, number> = {
  stats: 4,
  running: 5,
  pending: 4,
  done: 4,
  events: 5,
  collab: 7,
  depts: 4,
}

function stackLayout(base: LayoutItem[]): LayoutItem[] {
  let y = 0
  return MODULE_ORDER.map((moduleId) => {
    const source = base.find((item) => item.i === moduleId) || DEFAULT_BY_ID.get(moduleId)!
    const h = MOBILE_HEIGHTS[moduleId]
    const item = { ...source, x: 0, y, w: 1, h, minW: 1, minH: 1, isDraggable: false, isResizable: false }
    y += h
    return item
  })
}

function buildAllLayouts(canonical: LayoutItem[]) {
  return {
    lg: canonical.map((item) => ({ ...item })),
    md: mapLayoutColumns(canonical, CANONICAL_COLS, COLS_MAP.md),
    sm: mapLayoutColumns(canonical, CANONICAL_COLS, COLS_MAP.sm),
    xs: stackLayout(canonical),
  }
}

/** 旧 v8.1 是裸 10 列数组；只在完整合法时迁移，并保留旧 key 便于降级。 */
function migrateLegacyLayout(input: unknown): LayoutItem[] | null {
  const legacy = validateLayout(input, 10)
  if (!legacy) return null
  return withCanonicalConstraints(mapLayoutColumns(legacy, 10, CANONICAL_COLS))
}

function parseCanonicalCache(raw: string): LayoutItem[] | null {
  try {
    const parsed: unknown = JSON.parse(raw)
    const payload = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Partial<PersistedLayoutV2>
      : null
    if (!payload || payload.version !== LAYOUT_VERSION || payload.cols !== CANONICAL_COLS) return null
    const valid = validateLayout(payload.layout, CANONICAL_COLS)
    return valid ? withCanonicalConstraints(valid) : null
  } catch {
    return null
  }
}

function loadLayout(): LayoutItem[] {
  try {
    const currentRaw = localStorage.getItem(LAYOUT_KEY)
    if (currentRaw !== null) {
      // 新 key 存在但损坏时 fail closed 到默认值；绝不再采信更旧缓存。
      return parseCanonicalCache(currentRaw) || DEFAULT_LAYOUT.map((item) => ({ ...item }))
    }
    const legacyRaw = localStorage.getItem(LEGACY_LAYOUT_KEY)
    if (legacyRaw !== null) {
      let parsed: unknown
      try { parsed = JSON.parse(legacyRaw) } catch { return DEFAULT_LAYOUT.map((item) => ({ ...item })) }
      const migrated = migrateLegacyLayout(parsed)
      if (!migrated) return DEFAULT_LAYOUT.map((item) => ({ ...item }))
      saveLayout(migrated)
      return migrated
    }
  } catch { /* localStorage 可被浏览器策略禁用，使用内存默认值 */ }
  return DEFAULT_LAYOUT.map((item) => ({ ...item }))
}

function saveLayout(layout: LayoutItem[]) {
  const valid = validateLayout(layout, CANONICAL_COLS)
  if (!valid) return false
  const payload: PersistedLayoutV2 = {
    version: LAYOUT_VERSION,
    cols: CANONICAL_COLS,
    layout: withCanonicalConstraints(valid),
  }
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}

// ── 主题 ──────────────────────────────────────────────────
const T = {
  bg: '#0b0e14', bg2: '#11151f', panel: '#161b28', panel2: '#1c2333',
  line: '#252d40', txt: '#dde3f0', dim: '#8b93a7', faint: '#5a6275',
  acc: '#4f8cff', ok: '#3ecf8e', warn: '#f5b83d', bad: '#f4655f', rev: '#b07cff',
}

const ST: Record<string, { label: string; color: string }> = {
  pending:{label:'待办',color:T.dim}, todo:{label:'待办',color:T.dim},
  in_progress:{label:'进行中',color:T.acc}, running:{label:'执行中',color:T.acc},
  review:{label:'待验收',color:T.rev}, blocked:{label:'阻塞',color:T.bad},
  done:{label:'完成',color:T.ok}, completed:{label:'完成',color:T.ok},
  failed:{label:'失败',color:T.bad}, cancelled:{label:'取消',color:T.faint},
}

const COLLAB_ST: Record<string,{color:string;label:string}> = {
  PENDING:{color:T.dim,label:'待处理'}, ACCEPTED:{color:T.acc,label:'已接收'},
  IN_PROGRESS:{color:T.acc,label:'执行中'}, BLOCKED:{color:T.warn,label:'阻塞'},
  DELIVERED:{color:T.rev,label:'已交付'}, RETURNED:{color:'#f97316',label:'已退回'},
  REJECTED:{color:T.bad,label:'已拒绝'}, EXPIRED:{color:T.faint,label:'已过期'},
  ESCALATED:{color:T.bad,label:'已升级'}, CLOSED:{color:T.ok,label:'已关闭'},
}

const POLL = 5000

// ── CSS（动画 + react-grid-layout 暗色覆盖）──────────────
const CSS = `
@keyframes kp-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1}}
@keyframes kp-glow{0%,100%{box-shadow:0 0 0 0 transparent}50%{box-shadow:0 0 14px 2px var(--kp-glow,transparent)}}
@keyframes kp-blink{50%{opacity:.25}}
@keyframes kp-dash{to{background-position:24px 0}}
@keyframes kp-spin{to{transform:rotate(360deg)}}
.kp-ev{animation:kp-in .3s ease-out}
.kp-run{animation:kp-glow 2s ease-in-out infinite}
.kp-dot{display:inline-block;width:7px;height:7px;border-radius:50%;animation:kp-blink 1.5s infinite}
.kp-arrow{background:repeating-linear-gradient(90deg,currentColor 0 6px,transparent 6px 12px);background-size:24px 2px;animation:kp-dash .8s linear infinite;opacity:.7}
.kp-spin{animation:kp-spin 1s linear infinite}

/* react-resizable 基础 handle CSS（原来从 node_modules 导入，现内联）*/
.kp-rgl .react-resizable {
  position: relative;
}
.kp-rgl .react-resizable-handle {
  position: absolute;
  width: 20px;
  height: 20px;
  bottom: 0;
  right: 0;
  cursor: se-resize;
  background-repeat: no-repeat;
  background-origin: content-box;
  box-sizing: border-box;
  background-position: bottom right;
  padding: 0 3px 3px 0;
  z-index: 10;
}

/* react-grid-layout 暗色覆盖 */
.kp-rgl .react-grid-item {
  transition: all 200ms ease;
  transition-property: left, top, width, height;
}
.kp-rgl .react-grid-item.react-grid-placeholder {
  background: ${T.acc} !important;
  opacity: 0.15 !important;
  border-radius: 10px !important;
  border: 2px dashed ${T.acc} !important;
}
.kp-rgl .react-resizable-handle {
  opacity: 0;
  transition: opacity .15s;
}
.kp-rgl .react-grid-item:hover .react-resizable-handle {
  opacity: 0.6;
}
.kp-rgl .react-resizable-handle::after {
  content: '';
  position: absolute;
  right: 3px;
  bottom: 3px;
  width: 8px;
  height: 8px;
  border-right: 2px solid ${T.acc};
  border-bottom: 2px solid ${T.acc};
}
.kp-rgl .react-resizable-handle:hover {
  opacity: 1 !important;
}
.kp-rgl .react-resizable-handle:hover::after {
  border-right-color: ${T.acc} !important;
  border-bottom-color: ${T.acc} !important;
  width: 10px !important;
  height: 10px !important;
}
.kp-rgl .react-grid-item.react-draggable-dragging {
  box-shadow: 0 8px 30px rgba(0,0,0,0.5);
  z-index: 100;
  cursor: grabbing !important;
}
.kp-rgl .react-grid-item > .kp-drag-handle {
  cursor: grab;
}
.kp-rgl .react-grid-item.react-draggable-dragging > .kp-drag-handle {
  cursor: grabbing;
}
@media (max-width: 619px) {
  .kp-rgl { -webkit-overflow-scrolling: touch; }
  .kp-rgl .react-grid-item { transition: none; }
  .kp-rgl .react-resizable-handle { display: none !important; }
  .kp-mobile-scroll { overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  .kp-mobile-stack { grid-template-columns: 1fr !important; }
  .kp-mobile-action { min-width: 44px; min-height: 44px; padding: 8px 10px !important; }
  .kp-mobile-card { width: min(78vw, 280px) !important; min-width: min(78vw, 280px) !important; }
  .kp-mobile-task { min-height: 44px; }
  .kp-rgl .react-grid-item { touch-action: pan-y !important; }
}
`

// ── 小组件 ────────────────────────────────────────────────
const StatPill = ({n,label,color}:{n:number;label:string;color:string}) => (
  <div style={{display:'flex',alignItems:'baseline',gap:5,background:T.bg2,border:`1px solid ${T.line}`,borderRadius:9,padding:'5px 11px',flexShrink:0}}>
    <span style={{fontSize:18,fontWeight:700,fontFamily:'SF Mono,monospace',color:n>0?color:T.faint}}>{n}</span>
    <span style={{fontSize:11,color:T.dim}}>{label}</span>
  </div>
)

const miniBtn = (bg:string,fg:string,isMobile=false):React.CSSProperties => ({
  background:bg,color:fg,border:0,borderRadius:6,padding:isMobile?'8px 10px':'2px 7px',minHeight:isMobile?44:undefined,minWidth:isMobile?52:undefined,fontSize:isMobile?11:9,fontWeight:600,cursor:'pointer',
})

// ── 区块标题（带拖拽手柄） ────────────────────────────────
const SectionHeader = ({icon,title,color,count,extra,dragHandle}:{icon:string;title:string;color:string;count?:number;extra?:React.ReactNode;dragHandle?:boolean}) => (
  <div style={{display:'flex',alignItems:'center',gap:6,paddingBottom:6,borderBottom:`1px solid ${T.line}`,marginBottom:8,flexShrink:0,touchAction:dragHandle?'none':'auto'}} className={dragHandle ? 'kp-drag-handle' : ''}>
    <span className="kp-dot" style={{background:color,width:6,height:6}}/>
    <span style={{fontSize:12,fontWeight:700,color}}>{icon} {title}</span>
    {count!==undefined && <span style={{fontSize:11,color:T.faint}}>{count}</span>}
    {extra}
  </div>
)

// ════════════════════════════════════════════════════════════
// 主组件
// ════════════════════════════════════════════════════════════
// WidthProvider HOC 自动测量容器宽度（legacy API）
const ResponsiveGridLayout = WidthProvider(Responsive)

export const KanbanPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [board,setBoard] = useState<Board|null>(null)
  const [health,setHealth] = useState<any>(null)
  const [inbox,setInbox] = useState<CollabItem[]>([])
  const [outbox,setOutbox] = useState<CollabItem[]>([])
  const [depts,setDepts] = useState<DeptStatus[]>([])
  const [collabError,setCollabError] = useState('')
  const [loading,setLoading] = useState(true)
  const [detail,setDetail] = useState<any>(null)
  const [msg,setMsg] = useState('')
  const [autoRefresh,setAutoRefresh] = useState(true)
  const [events,setEvents] = useState<{id:string;text:string;ts:number;type:string}[]>([])
  const [lastUpdate,setLastUpdate] = useState(0)
  const [,forceTick] = useState(0)
  const prevRef = useRef<Board|null>(null)
  const evCtr = useRef(0)

  // ── 布局状态 ──
  const [layout, setLayout] = useState<LayoutItem[]>(loadLayout)
  const [editMode, setEditMode] = useState(false)
  const [activeBreakpoint, setActiveBreakpoint] = useState<GridBreakpoint>('lg')
  const layoutChangeArmedRef = useRef(false)
  const layouts = useMemo(() => buildAllLayouts(layout), [layout])

  const addEv = useCallback((text:string,type:string) => {
    evCtr.current++
    setEvents(p => [{id:`ev-${evCtr.current}`,text,ts:Date.now(),type},...p].slice(0,50))
  },[])

  const load = useCallback(async() => {
    try {
      const h = await (await fetch('/api/kanban/health')).json()
      setHealth(h)
      if (h.reachable) {
        const b = await (await fetch('/api/kanban/board')).json()
        if (prevRef.current) {
          const pm = new Map<string,any>()
          Object.values(prevRef.current.columns).flat().forEach((t:any) => pm.set(t.id,t))
          Object.values(b.columns).flat().forEach((t:any) => {
            const old = pm.get(t.id)
            if (!old) addEv(`新卡: ${t.title}`,'create')
            else if (old.status !== t.status) addEv(`${t.title} → ${ST[t.status]?.label||t.status}`, t.status==='done'?'done':'move')
          })
        }
        prevRef.current = b
        setBoard(b)
      }
      try {
        const [inboxResponse, outboxResponse] = await Promise.all([
          fetch('/api/v1/inbox'),
          fetch('/api/v1/outbox'),
        ])
        if (!inboxResponse.ok || !outboxResponse.ok) throw new Error('collab unavailable')
        const [i, o] = await Promise.all([inboxResponse.json(), outboxResponse.json()])
        setInbox(i.items||[]); setOutbox(o.items||[]); setCollabError('')
      } catch { setCollabError('协作服务不可用') }
      try {
        const response = await fetch('/api/v1/departments')
        if (!response.ok) throw new Error('departments unavailable')
        const d = await response.json()
        if (d.departments) {
          const ds: DeptStatus[] = Object.entries(d.departments).map(([id,v]:[string,any]) => ({
            dept_id: id, name: v.name||id,
            running: 0, pending: 0, done: 0, blocked: 0,
          }))
          setDepts(ds)
        }
      } catch { /* depts optional */ }
    } catch { /* silent */ } finally { setLoading(false); setLastUpdate(Date.now()) }
  },[addEv])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (!autoRefresh) return; const t = setInterval(load,POLL); return () => clearInterval(t) }, [autoRefresh,load])
  useEffect(() => { const t = setInterval(() => forceTick(x => x+1), 1000); return () => clearInterval(t) }, [])

  const move = async (id:string,status:string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})})
    if (!r.ok) { setMsg(`流转失败: ${(await r.json()).detail}`); return }
    setMsg(''); load()
  }
  const openDetail = async (id:string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`)
    const j = await r.json()
    setDetail(r.ok ? j.task : {id,error:j.detail})
  }
  // ── 布局回调 ──
  const persistBreakpointLayout = useCallback((breakpointLayout: LayoutItem[]) => {
    if (activeBreakpoint === 'xs') return
    const cols = COLS_MAP[activeBreakpoint]
    const valid = validateLayout(breakpointLayout, cols)
    if (!valid) return
    const canonical = withCanonicalConstraints(
      activeBreakpoint === 'lg'
        ? compactVertically(valid)
        : mapLayoutColumns(valid, cols, CANONICAL_COLS),
    )
    const canonicalValid = validateLayout(canonical, CANONICAL_COLS)
    if (!canonicalValid) return

    // Smaller grids quantize 20-column boundaries. Persist only edits whose canonical
    // representation derives back to the exact active-breakpoint geometry; otherwise
    // react-grid-layout would appear to save an edit that silently changes on refresh.
    if (activeBreakpoint !== 'lg') {
      const roundTrip = mapLayoutColumns(canonicalValid, CANONICAL_COLS, cols)
      const roundTripValid = validateLayout(roundTrip, cols)
      const exactRoundTrip = roundTripValid && MODULE_ORDER.every((id) => {
        const before = valid.find((item) => item.i === id)!
        const after = roundTripValid.find((item) => item.i === id)!
        return before.x === after.x && before.y === after.y && before.w === after.w && before.h === after.h
      })
      if (!exactRoundTrip) {
        setLayout((current) => current.map((item) => ({ ...item })))
        setMsg('当前断点的布局无法无损映射到 20 列，已恢复到上次保存的布局。')
        return
      }
    }

    const next = withCanonicalConstraints(canonicalValid)
    setMsg('')
    setLayout(next)
    saveLayout(next)
  }, [activeBreakpoint])

  const armLayoutChange = useCallback(() => {
    if (activeBreakpoint !== 'xs') layoutChangeArmedRef.current = true
  }, [activeBreakpoint])

  const finishLayoutChange = useCallback((breakpointLayout: readonly LayoutItem[]) => {
    if (!layoutChangeArmedRef.current) return
    layoutChangeArmedRef.current = false
    persistBreakpointLayout(breakpointLayout.map((item) => ({ ...item })))
  }, [persistBreakpointLayout])

  const resetLayout = () => {
    const defaults = DEFAULT_LAYOUT.map((item) => ({ ...item }))
    localStorage.removeItem(LAYOUT_KEY)
    setLayout(defaults)
    saveLayout(defaults)
  }

  // ── 计算数据 ──────────────────────────────────────────
  const cols = board?.columns || {}
  const laneRunning = [...(cols.in_progress||[]),...(cols.running||[])]
  const laneReview = [...(cols.review||[])]
  const lanePending = [...(cols.pending||[]),...(cols.todo||[])]
  const laneBlocked = [...(cols.blocked||[])]
  const laneDone = [...(cols.done||[]),...(cols.completed||[]),...(cols.failed||[]),...(cols.cancelled||[])]
  const total = board?.total ?? 0
  const doneCount = laneDone.length
  const progress = total > 0 ? Math.round((doneCount/total)*100) : 0
  const secsAgo = lastUpdate ? Math.floor((Date.now()-lastUpdate)/1000) : 0

  if (loading && !board) return (
    <div style={{color:T.dim,textAlign:'center',padding:40,display:'flex',alignItems:'center',justifyContent:'center',gap:8}}>
      <span className="kp-spin" style={{display:'inline-block',width:14,height:14,border:`2px solid ${T.line}`,borderTopColor:T.acc,borderRadius:'50%'}}/>
      正在载入...
    </div>
  )
  if (health && !health.reachable) return (
    <div style={{background:T.panel,border:`1px solid ${T.bad}40`,borderRadius:10,padding:16}}>
      <div style={{color:T.bad,fontWeight:700}}>⚠️ seohm 看板未接通</div>
      <div style={{color:T.dim,fontSize:12,marginTop:4}}>{health.reason}</div>
    </div>
  )

  // ═══ 卡片渲染器 ═══
  const renderRunningCard = (t:Task) => {
    const s = ST[t.status] || {label:t.status,color:T.faint}
    return (
      <div key={t.id} style={{display:'flex',alignItems:'stretch',flexShrink:0}}>
        <div className="kp-run kp-mobile-card" onClick={()=>openDetail(t.id)} style={{
          '--kp-glow': s.color+'60',
          background:T.bg2, border:`1px solid ${T.line}`, borderLeft:`4px solid ${s.color}`,
          borderRadius:10, padding:'10px 12px', cursor:'pointer', width:230, minWidth:230,
          transition:'transform .12s, border-color .12s',
        } as React.CSSProperties}
        onMouseEnter={e=>{e.currentTarget.style.transform='translateY(-2px)';e.currentTarget.style.borderColor=s.color}}
        onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';e.currentTarget.style.borderColor=T.line}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
            <span style={{fontWeight:600,fontSize:12.5,color:T.txt,lineHeight:1.35,flex:1}}>{t.workflow_template_id?.startsWith('REQ-')&&<span style={{color:T.rev,marginRight:3}}>🔗</span>}{t.title}</span>
            <span style={{fontFamily:'SF Mono,monospace',fontSize:10,color:t.priority<=2?T.bad:T.faint,flexShrink:0,marginLeft:4}}>P{t.priority}</span>
          </div>
          <div style={{display:'flex',alignItems:'center',gap:5,marginTop:3}}>
            <span className="kp-dot" style={{background:s.color,width:5,height:5}}/>
            <span style={{fontSize:10.5,color:s.color,fontWeight:600}}>{s.label}</span>
            <span style={{fontSize:10.5,color:T.dim}}>· 👤{t.assignee||'—'}</span>
          </div>
          {t.current_step_key && <div style={{marginTop:4,fontSize:10.5,color:T.dim,background:T.panel2,borderRadius:5,padding:'3px 7px',border:`1px solid ${T.line}`,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>⚡ {t.current_step_key}</div>}
          <div style={{marginTop:5,height:3,background:T.line,borderRadius:2,overflow:'hidden'}}>
            <div style={{height:'100%',width:t.status==='running'?'60%':t.status==='in_progress'?'35%':'10%',background:`linear-gradient(90deg,${s.color},${s.color}aa)`,transition:'width .5s'}}/>
          </div>
          {t.last_failure_error && <div style={{color:T.bad,fontSize:9.5,marginTop:3}}>✗ {t.last_failure_error.slice(0,38)}{(t.consecutive_failures||0)>1?` (×${t.consecutive_failures})`:''}</div>}
          <div style={{display:'flex',gap:3,marginTop:5}} onClick={e=>e.stopPropagation()}>
            <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok,isMobile)}>完成</button>
            <button onClick={()=>move(t.id,'review')} style={miniBtn(T.rev+'20',T.rev,isMobile)}>验收</button>
            <button onClick={()=>move(t.id,'blocked')} style={miniBtn(T.warn+'20',T.warn,isMobile)}>阻塞</button>
          </div>
        </div>
        <div style={{width:28,minWidth:28,display:'flex',alignItems:'center',justifyContent:'center'}}>
          <div className="kp-arrow" style={{width:'100%',height:2,color:s.color}}/>
        </div>
      </div>
    )
  }

  const renderCompactCard = (t:Task) => {
    const s = ST[t.status] || {label:t.status,color:T.faint}
    return (
      <div
        key={t.id}
        className={isMobile?'kp-mobile-task':''}
        onClick={()=>openDetail(t.id)}
        style={{background:T.bg2,border:`1px solid ${T.line}`,borderLeft:`3px solid ${s.color}`,borderRadius:7,padding:isMobile?'9px 10px':'5px 9px',cursor:'pointer',transition:'transform .12s, border-color .12s',display:'flex',flexDirection:'column',justifyContent:'center'}}
        onMouseEnter={e=>{e.currentTarget.style.transform='translateY(-1px)';e.currentTarget.style.borderColor=s.color}}
        onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';e.currentTarget.style.borderColor=T.line}}
      >
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:4}}>
          <span style={{fontSize:11.5,fontWeight:600,color:T.txt,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',flex:1}}>{t.workflow_template_id?.startsWith('REQ-')&&<span style={{color:T.rev,marginRight:2}}>🔗</span>}{t.title}</span>
          <span style={{fontSize:9,color:s.color,fontWeight:600,flexShrink:0}}>{s.label}</span>
        </div>
        <div style={{fontSize:9.5,color:T.faint,marginTop:1}}>👤{t.assignee||'—'} · {t.created_at_iso||''}</div>
      </div>
    )
  }

  // ═══ 部门状态卡片 ═══
  const DEPT_COLORS: Record<string,string> = { seo: T.acc, intel: T.rev }
  const renderDeptCard = (d: DeptStatus) => {
    const c = DEPT_COLORS[d.dept_id] || T.dim
    return (
      <div key={d.dept_id} style={{display:'flex',alignItems:'stretch',flexShrink:0}}>
        <div style={{background:T.bg2,border:`1px solid ${T.line}`,borderLeft:`4px solid ${c}`,borderRadius:10,padding:'10px 12px',width:200,minWidth:200}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <span style={{fontSize:12.5,fontWeight:700,color:c}}>{d.name}</span>
            <span style={{fontFamily:'SF Mono,monospace',fontSize:10,color:T.faint}}>{d.dept_id}</span>
          </div>
          <div style={{display:'flex',gap:8,marginTop:8}}>
            <div style={{textAlign:'center'}}><div style={{fontSize:16,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.acc}}>{d.running}</div><div style={{fontSize:9,color:T.dim}}>⚡</div></div>
            <div style={{textAlign:'center'}}><div style={{fontSize:16,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.dim}}>{d.pending}</div><div style={{fontSize:9,color:T.dim}}>⏳</div></div>
            <div style={{textAlign:'center'}}><div style={{fontSize:16,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.bad}}>{d.blocked}</div><div style={{fontSize:9,color:T.dim}}>🚫</div></div>
            <div style={{textAlign:'center'}}><div style={{fontSize:16,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.ok}}>{d.done}</div><div style={{fontSize:9,color:T.dim}}>✅</div></div>
          </div>
        </div>
        <div style={{width:28,minWidth:28,display:'flex',alignItems:'center',justifyContent:'center'}}>
          <div className="kp-arrow" style={{width:'100%',height:2,color:c}}/>
        </div>
      </div>
    )
  }

  // ═══ 模块内容渲染 ═══
  const renderModuleContent = (modId: ModuleId): React.ReactNode => {
    switch (modId) {
      case 'stats':
        return (
          <>
            <div style={{display:'flex',gap:6,flexWrap:'wrap',alignItems:'center',flexShrink:0, height:'100%'}}>
              <StatPill n={laneRunning.length} label="执行中" color={T.acc}/>
              <StatPill n={laneReview.length} label="待验收" color={T.rev}/>
              <StatPill n={lanePending.length} label="待办" color={T.dim}/>
              <StatPill n={laneBlocked.length} label="阻塞" color={T.bad}/>
              <StatPill n={doneCount} label="完成" color={T.ok}/>
              <div style={{marginLeft:'auto',display:'flex',gap:5,alignItems:'center',flexShrink:0}}>
                {autoRefresh && <span style={{display:'flex',alignItems:'center',gap:3,fontSize:10,color:T.ok}}>
                  <span className="kp-dot" style={{background:T.ok,width:5,height:5}}/>LIVE {secsAgo}s
                </span>}
                <div style={{width:60,height:4,background:T.line,borderRadius:2,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${progress}%`,background:`linear-gradient(90deg,${T.ok},${T.acc})`,transition:'width .5s'}}/>
                </div>
                <span style={{fontSize:9,color:T.faint,width:24}}>{progress}%</span>
                <button className={isMobile?'kp-mobile-action':''} aria-label={autoRefresh?'暂停自动刷新':'启用自动刷新'} onClick={()=>setAutoRefresh(!autoRefresh)} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${autoRefresh?T.ok+'40':T.line}`,background:autoRefresh?T.ok+'15':T.panel2,color:autoRefresh?T.ok:T.dim,cursor:'pointer'}}>{autoRefresh?'⏸':'▶'}</button>
                <button className={isMobile?'kp-mobile-action':''} aria-label="立即刷新" onClick={load} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>↻</button>
                {!isMobile && <button aria-label="编辑布局" onClick={()=>setEditMode(!editMode)} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${editMode?T.warn:T.line}`,background:editMode?T.warn+'15':T.panel2,color:editMode?T.warn:T.dim,cursor:'pointer'}}>✏️</button>}
              </div>
            </div>
            {msg && <div style={{background:T.bad+'15',border:`1px solid ${T.bad}40`,borderRadius:6,padding:'5px 10px',color:T.bad,fontSize:11,flexShrink:0,marginTop:4}}>{msg}</div>}
          </>
        )

      case 'running':
        return (
          <div className="kp-mobile-scroll" style={{flex:1,minHeight:0,overflowX:'auto',overflowY:'hidden',display:'flex',alignItems:'flex-start'}}>
            {laneRunning.length===0 && laneReview.length===0 && laneBlocked.length===0 ? (
              <div style={{color:T.faint,fontSize:11,padding:'8px 0'}}>暂无执行中任务</div>
            ) : (
              <>
                {laneRunning.map(renderRunningCard)}
                {laneReview.map(t=>{
                  const s=ST[t.status]||{label:t.status,color:T.faint}
                  return (
                    <div key={t.id} style={{display:'flex',alignItems:'stretch',flexShrink:0}}>
                      <div onClick={()=>openDetail(t.id)} style={{background:T.bg2,border:`1px solid ${s.color}40`,borderLeft:`4px solid ${s.color}`,borderRadius:10,padding:'10px 12px',cursor:'pointer',width:230,minWidth:230}}>
                        <div style={{fontWeight:600,fontSize:12.5,color:T.txt}}>{t.title}</div>
                        <div style={{display:'flex',alignItems:'center',gap:5,marginTop:3}}><span className="kp-dot" style={{background:s.color,width:5,height:5}}/><span style={{fontSize:10.5,color:s.color,fontWeight:600}}>{s.label}</span></div>
                        <div style={{display:'flex',gap:3,marginTop:5}} onClick={e=>e.stopPropagation()}>
                          <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok,isMobile)}>验收通过</button>
                          <button onClick={()=>move(t.id,'in_progress')} style={miniBtn(T.warn+'20',T.warn,isMobile)}>退回</button>
                        </div>
                      </div>
                      <div style={{width:28,minWidth:28,display:'flex',alignItems:'center',justifyContent:'center'}}><div className="kp-arrow" style={{width:'100%',height:2,color:s.color}}/></div>
                    </div>
                  )
                })}
                {laneBlocked.map(t=>{
                  const s=ST[t.status]||{label:t.status,color:T.faint}
                  return (
                    <div key={t.id} style={{display:'flex',alignItems:'stretch',flexShrink:0}}>
                      <div onClick={()=>openDetail(t.id)} style={{background:T.bg2,border:`1px solid ${s.color}40`,borderLeft:`4px solid ${s.color}`,borderRadius:10,padding:'10px 12px',cursor:'pointer',width:230,minWidth:230}}>
                        <div style={{fontWeight:600,fontSize:12.5,color:T.txt}}>{t.title}</div>
                        <div style={{display:'flex',alignItems:'center',gap:5,marginTop:3}}><span className="kp-dot" style={{background:s.color,width:5,height:5}}/><span style={{fontSize:10.5,color:s.color,fontWeight:600}}>{s.label}</span></div>
                        {t.last_failure_error && <div style={{color:T.bad,fontSize:9.5,marginTop:3}}>✗ {t.last_failure_error.slice(0,38)}</div>}
                      </div>
                    </div>
                  )
                })}
              </>
            )}
          </div>
        )

      case 'pending':
        return (
          <div style={{flex:1,minHeight:0,overflowY:'auto',display:'flex',flexDirection:'column',gap:3}}>
            {lanePending.length===0 ? <div style={{color:T.faint,fontSize:10,padding:'4px 0'}}>空</div> : lanePending.map(renderCompactCard)}
          </div>
        )

      case 'done':
        return (
          <div style={{flex:1,minHeight:0,overflowY:'auto',display:'flex',flexDirection:'column',gap:3}}>
            {laneDone.length===0 ? <div style={{color:T.faint,fontSize:10,padding:'4px 0'}}>空</div> : laneDone.map(renderCompactCard)}
          </div>
        )

      case 'events':
        return (
          <div style={{flex:1,minHeight:0,overflowY:'auto'}}>
            {events.length===0 && <div style={{color:T.faint,fontSize:10,padding:'10px 0',textAlign:'center'}}>等待事件…</div>}
            {events.map(ev=>{
              const colors:any={move:T.acc,create:T.ok,done:T.ok,error:T.bad}
              const icons:any={move:'→',create:'✨',done:'🎉',error:'✗'}
              const age=Math.floor((Date.now()-ev.ts)/1000)
              const ageStr=age<60?`${age}s`:age<3600?`${Math.floor(age/60)}m`:`${Math.floor(age/3600)}h`
              return (
                <div key={ev.id} className="kp-ev" style={{display:'flex',gap:5,padding:'4px 0',borderBottom:`1px solid ${T.line}40`,fontSize:11}}>
                  <span style={{color:colors[ev.type]||T.dim,fontWeight:700,flexShrink:0}}>{icons[ev.type]||'•'}</span>
                  <span style={{color:T.txt,flex:1,lineHeight:1.35}}>{ev.text}</span>
                  <span style={{color:T.faint,fontSize:9,fontFamily:'SF Mono,monospace',flexShrink:0}}>{ageStr}</span>
                </div>
              )
            })}
          </div>
        )

      case 'collab':
        return (
          <>
            {collabError ? (
              <div style={{color:T.bad,fontSize:11}}>{collabError}</div>
            ) : inbox.length===0 && outbox.length===0 ? (
              <div style={{color:T.faint,fontSize:11,padding:'6px 0'}}>暂无协作单</div>
            ) : (
              <>
                <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:10,marginBottom:8}}>
                  <div style={{textAlign:'center'}}><div style={{fontSize:15,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.acc}}>{outbox.length}</div><div style={{fontSize:9,color:T.dim}}>📤 发出</div></div>
                  <div className="kp-arrow" style={{width:35,height:2,color:T.dim}}/>
                  <div style={{textAlign:'center'}}><div style={{fontSize:15,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.rev}}>{inbox.length+outbox.length}</div><div style={{fontSize:9,color:T.dim}}>协作中</div></div>
                  <div className="kp-arrow" style={{width:35,height:2,color:T.dim}}/>
                  <div style={{textAlign:'center'}}><div style={{fontSize:15,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.ok}}>{inbox.length}</div><div style={{fontSize:9,color:T.dim}}>📥 接收</div></div>
                </div>
                <div className="kp-mobile-stack" style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                  {[['📤 发件箱',outbox],['📥 收件箱',inbox]].map(([title,items]:any)=>(
                    <div key={title}>
                      <div style={{fontSize:10.5,fontWeight:700,color:T.dim,marginBottom:3}}>{title} ({items.length})</div>
                      <div style={{display:'flex',flexDirection:'column',gap:3,maxHeight:100,overflowY:'auto'}}>
                        {items.length===0 && <div style={{color:T.faint,fontSize:10,padding:'3px 0'}}>暂无</div>}
                        {items.map((it:CollabItem)=>{
                          const meta=COLLAB_ST[it.status]||{color:T.faint,label:it.status}
                          return (
                            <div key={it.request_id} style={{background:T.bg2,border:`1px solid ${meta.color}30`,borderLeft:`3px solid ${meta.color}`,borderRadius:5,padding:'4px 7px',fontSize:10.5}}>
                              <div style={{display:'flex',justifyContent:'space-between'}}><span style={{color:T.txt,fontWeight:600}}>{it.capability||it.to?.capability||'—'}</span><span style={{fontSize:8.5,fontWeight:700,padding:'1px 4px',borderRadius:3,background:meta.color+'20',color:meta.color}}>{meta.label}</span></div>
                              <div style={{color:T.dim,fontSize:9,marginTop:1}}>📤{it.from?.dept||it.to?.dept||'—'} {it.deadline&&`· ⏰${it.deadline.slice(0,10)}`}</div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )

      case 'depts':
        return (
          <div className="kp-mobile-scroll" style={{display:'flex',alignItems:'flex-start',gap:0,overflowX:'auto',minHeight:50}}>
            {depts.length===0 ? (
              <div style={{color:T.faint,fontSize:11,padding:'6px 0'}}>暂无部门数据</div>
            ) : (
              depts.map(renderDeptCard)
            )}
          </div>
        )
    }
  }

  // ═══ 骨架 ═══
  return (
    <div style={{display:'flex',flexDirection:'column',gap:0,minHeight:0,width:'100%',height:'100%',overflow:'hidden'}}>
      <style>{CSS}</style>

      {/* 编辑模式提示条 */}
      {editMode && !isMobile && (
        <div style={{background:T.warn+'15',border:`1px solid ${T.warn}40`,borderRadius:6,padding:'5px 10px',display:'flex',alignItems:'center',gap:8,marginBottom:6,flexShrink:0}}>
          <span style={{color:T.warn,fontSize:11,fontWeight:600}}>✏️ 布局编辑模式</span>
          <span style={{color:T.dim,fontSize:10}}>拖拽模块标题移动位置 · 拖右下角调整大小 · 邻居自动让位</span>
          <button onClick={resetLayout} style={{marginLeft:'auto',padding:'3px 8px',fontSize:10,borderRadius:5,border:`1px solid ${T.bad}`,background:T.bad+'15',color:T.bad,cursor:'pointer'}}>↺ 恢复默认</button>
          <button onClick={()=>setEditMode(false)} style={{padding:'3px 10px',fontSize:10,borderRadius:5,border:`1px solid ${T.ok}`,background:T.ok+'15',color:T.ok,cursor:'pointer'}}>✓ 完成</button>
        </div>
      )}

      {/* react-grid-layout 网格 */}
      <div className="kp-rgl" style={{flex:'1 1 0',width:'100%',minWidth:0,minHeight:0,overflowX:'hidden',overflowY:'auto',scrollbarGutter:'stable'}}>
        <ResponsiveGridLayout
          className="kp-layout"
          layouts={layouts}
          cols={COLS_MAP}
          rowHeight={ROW_HEIGHT}
          margin={[6, 6]}
          containerPadding={[0, 0]}
          isDraggable={editMode && !isMobile}
          isResizable={editMode && !isMobile}
          isBounded={true}
          draggableHandle=".kp-drag-handle"
          compactType="vertical"
          preventCollision={false}
          useCSSTransforms={true}
          onBreakpointChange={(breakpoint: string) => {
            const nextBreakpoint = breakpoint as GridBreakpoint
            layoutChangeArmedRef.current = false
            setActiveBreakpoint(nextBreakpoint)
            if (nextBreakpoint === 'xs') setEditMode(false)
          }}
          onDragStart={armLayoutChange}
          onResizeStart={armLayoutChange}
          onDragStop={(next) => finishLayoutChange(next)}
          onResizeStop={(next) => finishLayoutChange(next)}
          breakpoints={BREAKPOINTS}
        >
          {MODULE_ORDER.map(modId => {
            const meta = MODULE_LABELS[modId]
            return (
              <div
                key={modId}
                style={{
                  background: T.panel,
                  border: `1px solid ${editMode ? T.acc + '60' : T.line}`,
                  borderRadius: 10,
                  padding: modId === 'stats' ? (isMobile ? 8 : 6) : (isMobile ? 9 : 10),
                  display: 'flex',
                  flexDirection: 'column',
                  minHeight: 0,
                  overflow: 'hidden',
                  boxSizing: 'border-box',
                }}
              >
                {/* 模块标题（stats 模块不需要标题，它本身就是顶栏） */}
                {meta.showHeader && (
                  <SectionHeader
                    icon={meta.icon}
                    title={meta.title}
                    color={meta.color}
                    dragHandle={editMode && !isMobile}
                    count={modId==='running' ? laneRunning.length+laneReview.length+laneBlocked.length :
                           modId==='pending' ? lanePending.length :
                           modId==='done' ? doneCount :
                           modId==='events' ? events.length :
                           modId==='collab' ? inbox.length+outbox.length :
                           modId==='depts' ? depts.length : undefined}
                  />
                )}

                {/* 模块内容 */}
                {renderModuleContent(modId)}
              </div>
            )
          })}
        </ResponsiveGridLayout>
      </div>

      {/* ═══ 详情弹窗 ═══ */}
      {detail && (
        <div onClick={()=>setDetail(null)} style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.8)',zIndex:9999,display:'flex',alignItems:'center',justifyContent:'center',padding:isMobile?0:20}}>
          <div onClick={e=>e.stopPropagation()} style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:isMobile?0:10,padding:isMobile?14:16,width:'100%',maxWidth:isMobile?'none':560,height:isMobile?'100%':'auto',maxHeight:isMobile?'100%':'80vh',overflowY:'auto'}}>
            {detail.error ? <div style={{color:T.bad}}>{detail.error}</div> : (
              <>
                <div style={{fontSize:15,fontWeight:700,color:T.txt}}>{detail.title}</div>
                <div style={{fontSize:10,color:T.faint,marginTop:2,fontFamily:'SF Mono,monospace'}}>{detail.id} · {detail.status} · P{detail.priority} · 👤{detail.assignee||'未指派'}</div>
                {detail.body && <div style={{color:T.txt,fontSize:12,marginTop:10,whiteSpace:'pre-wrap'}}>{detail.body}</div>}
                {(detail.runs||[]).length>0 && (
                  <div style={{marginTop:10}}><div style={{fontSize:11,fontWeight:700,color:T.dim,marginBottom:4}}>执行记录</div>
                    {detail.runs.map((r:any)=>(<div key={r.id} style={{background:T.bg2,borderRadius:5,padding:5,marginTop:3,fontSize:10,color:T.dim}}>#{r.id} {r.step_key} · {r.status} {r.error&&<span style={{color:T.bad}}>✗{r.error}</span>}</div>))}
                  </div>
                )}
                <button className={isMobile?'kp-mobile-action':''} onClick={()=>setDetail(null)} style={{marginTop:12,padding:isMobile?'10px 16px':'5px 12px',minHeight:isMobile?44:undefined,fontSize:isMobile?13:11,borderRadius:6,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

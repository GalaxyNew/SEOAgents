import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useIsMobile } from '../hooks'
import { Responsive, WidthProvider, type LayoutItem } from 'react-grid-layout/legacy'

/**
 * 任务流转看板 V8 — 10×12 可拖拽网格 (react-grid-layout)
 *
 * - 10 列 × 12 行
 * - 拖拽卡片换位置，其它卡片自动让位重排
 * - 拖拽右下角手柄改大小，邻居自动联动
 * - 布局存 localStorage，刷新后恢复
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
const COLS = 10
const ROWS = 12

// ── 断点配置 ──────────────────────────────────────────────
const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }
const COLS_MAP = { lg: 10, md: 8, sm: 4, xs: 2, xxs: 1 }
const ROW_HEIGHT = 48   // px, 配合 gap 算

// ── 模块 ID ──────────────────────────────────────────────
type ModuleId = 'stats' | 'running' | 'pending' | 'done' | 'events' | 'collab' | 'depts'

// ── 默认布局 ──────────────────────────────────────────────
const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'stats',   x: 0, y: 0,  w: 10, h: 2, minW: 4, minH: 1 },  // 顶栏全宽
  { i: 'running', x: 0, y: 2,  w: 6,  h: 5, minW: 3, minH: 2 },  // 执行中 左大块
  { i: 'events',  x: 6, y: 2,  w: 4,  h: 5, minW: 2, minH: 2 },  // 事件流 右
  { i: 'pending', x: 0, y: 7,  w: 3,  h: 3, minW: 2, minH: 1 },  // 待办
  { i: 'done',    x: 3, y: 7,  w: 3,  h: 3, minW: 2, minH: 1 },  // 已完成
  { i: 'collab',  x: 6, y: 7,  w: 4,  h: 3, minW: 2, minH: 1 },  // 协作流
  { i: 'depts',   x: 0, y: 10, w: 10, h: 2, minW: 4, minH: 1 },  // 部门状态 底部全宽
]

const MODULE_LABELS: Record<ModuleId, { icon: string; title: string; color: string; showHeader: boolean }> = {
  stats:   { icon: '📊', title: '统计胶囊',     color: '#4f8cff', showHeader: false },
  running: { icon: '⚡', title: '执行中',       color: '#4f8cff', showHeader: true },
  pending: { icon: '⏳', title: '待办',         color: '#8b93a7', showHeader: true },
  done:    { icon: '✅', title: '已完成',       color: '#3ecf8e', showHeader: true },
  events:  { icon: '●',  title: '实时事件流',   color: '#8b93a7', showHeader: true },
  collab:  { icon: '🔗', title: '跨部门协作流', color: '#dde3f0', showHeader: true },
  depts:   { icon: '📈', title: '部门任务状态', color: '#8b93a7', showHeader: true },
}

const MODULE_ORDER: ModuleId[] = ['stats', 'running', 'pending', 'done', 'events', 'collab', 'depts']

const LAYOUT_KEY = 'kp-layout-v8'

// ── 按列数生成自适应布局（将 10 列布局缩放到目标列数） ────
function scaleLayout(base: LayoutItem[], targetCols: number): LayoutItem[] {
  if (targetCols >= 10) return base.map(it => ({ ...it }))
  const ratio = targetCols / 10
  return base.map(it => ({
    ...it,
    x: Math.min(Math.floor(it.x * ratio), targetCols - 1),
    w: Math.max(1, Math.min(Math.round(it.w * ratio), targetCols)),
  }))
}

// 单列堆叠布局（移动端竖排）
function stackLayout(base: LayoutItem[]): LayoutItem[] {
  return base.map((it, i) => ({
    ...it,
    x: 0,
    y: base.slice(0, i).reduce((s, p) => s + p.h, 0),
    w: 1,
    minW: 1,
  }))
}

// 预生成所有断点的布局
function buildAllLayouts(lg: LayoutItem[]) {
  return {
    lg,
    md: scaleLayout(lg, 8),
    sm: scaleLayout(lg, 4),
    xs: scaleLayout(lg, 2),
    xxs: stackLayout(lg),
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
`

// ── 小组件 ────────────────────────────────────────────────
const StatPill = ({n,label,color}:{n:number;label:string;color:string}) => (
  <div style={{display:'flex',alignItems:'baseline',gap:5,background:T.bg2,border:`1px solid ${T.line}`,borderRadius:9,padding:'5px 11px',flexShrink:0}}>
    <span style={{fontSize:18,fontWeight:700,fontFamily:'SF Mono,monospace',color:n>0?color:T.faint}}>{n}</span>
    <span style={{fontSize:11,color:T.dim}}>{label}</span>
  </div>
)

const miniBtn = (bg:string,fg:string):React.CSSProperties => ({
  background:bg,color:fg,border:0,borderRadius:4,padding:'2px 7px',fontSize:9,fontWeight:600,cursor:'pointer',
})

// ── 区块标题（带拖拽手柄） ────────────────────────────────
const SectionHeader = ({icon,title,color,count,extra,dragHandle}:{icon:string;title:string;color:string;count?:number;extra?:React.ReactNode;dragHandle?:boolean}) => (
  <div className={dragHandle ? 'kp-drag-handle' : ''} style={{display:'flex',alignItems:'center',gap:6,paddingBottom:6,borderBottom:`1px solid ${T.line}`,marginBottom:8,flexShrink:0,touchAction:'none'}}>
    <span className="kp-dot" style={{background:color,width:6,height:6}}/>
    <span style={{fontSize:12,fontWeight:700,color}}>{icon} {title}</span>
    {count!==undefined && <span style={{fontSize:11,color:T.faint}}>{count}</span>}
    {extra}
  </div>
)

// ── Layout 持久化 ─────────────────────────────────────────
const loadLayout = (): LayoutItem[] => {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length === MODULE_ORDER.length) {
        // 确保 minW/minH 存在
        return parsed.map((it: any) => ({
          ...it,
          minW: it.minW ?? 2,
          minH: it.minH ?? 1,
        }))
      }
    }
  } catch {}
  return DEFAULT_LAYOUT
}

const saveLayout = (layout: LayoutItem[]) => {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)) } catch {}
}

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
        const [i,o] = await Promise.all([(await fetch('/api/v1/inbox')).json(),(await fetch('/api/v1/outbox')).json()])
        setInbox(i.items||[]); setOutbox(o.items||[]); setCollabError('')
      } catch { setCollabError('协作服务不可用') }
      try {
        const d = await (await fetch('/api/v1/departments')).json()
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
  const onLayoutChange = useCallback((newLayout: LayoutItem[]) => {
    setLayout(newLayout)
    saveLayout(newLayout)
  }, [])

  const resetLayout = () => {
    localStorage.removeItem(LAYOUT_KEY)
    setLayout(DEFAULT_LAYOUT)
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
        <div className="kp-run" onClick={()=>openDetail(t.id)} style={{
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
            <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok)}>完成</button>
            <button onClick={()=>move(t.id,'review')} style={miniBtn(T.rev+'20',T.rev)}>验收</button>
            <button onClick={()=>move(t.id,'blocked')} style={miniBtn(T.warn+'20',T.warn)}>阻塞</button>
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
      <div key={t.id} onClick={()=>openDetail(t.id)} style={{background:T.bg2,border:`1px solid ${T.line}`,borderLeft:`3px solid ${s.color}`,borderRadius:7,padding:'5px 9px',cursor:'pointer',transition:'transform .12s, border-color .12s'}}
        onMouseEnter={e=>{e.currentTarget.style.transform='translateY(-1px)';e.currentTarget.style.borderColor=s.color}}
        onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';e.currentTarget.style.borderColor=T.line}}>
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
                <button onClick={()=>setAutoRefresh(!autoRefresh)} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${autoRefresh?T.ok+'40':T.line}`,background:autoRefresh?T.ok+'15':T.panel2,color:autoRefresh?T.ok:T.dim,cursor:'pointer'}}>{autoRefresh?'⏸':'▶'}</button>
                <button onClick={load} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>↻</button>
                <button onClick={()=>setEditMode(!editMode)} style={{padding:'3px 7px',fontSize:10,borderRadius:5,border:`1px solid ${editMode?T.warn:T.line}`,background:editMode?T.warn+'15':T.panel2,color:editMode?T.warn:T.dim,cursor:'pointer'}}>✏️</button>
              </div>
            </div>
            {msg && <div style={{background:T.bad+'15',border:`1px solid ${T.bad}40`,borderRadius:6,padding:'5px 10px',color:T.bad,fontSize:11,flexShrink:0,marginTop:4}}>{msg}</div>}
          </>
        )

      case 'running':
        return (
          <div style={{flex:1,minHeight:0,overflowX:'auto',overflowY:'hidden',display:'flex',alignItems:'flex-start'}}>
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
                          <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok)}>验收通过</button>
                          <button onClick={()=>move(t.id,'in_progress')} style={miniBtn(T.warn+'20',T.warn)}>退回</button>
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
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
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
          <div style={{display:'flex',alignItems:'flex-start',gap:0,overflowX:'auto',minHeight:50}}>
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
    <div style={{display:'flex',flexDirection:'column',gap:0,minHeight:0,height:'100%'}}>
      <style>{CSS}</style>

      {/* 编辑模式提示条 */}
      {editMode && (
        <div style={{background:T.warn+'15',border:`1px solid ${T.warn}40`,borderRadius:6,padding:'5px 10px',display:'flex',alignItems:'center',gap:8,marginBottom:6,flexShrink:0}}>
          <span style={{color:T.warn,fontSize:11,fontWeight:600}}>✏️ 布局编辑模式</span>
          <span style={{color:T.dim,fontSize:10}}>拖拽模块标题移动位置 · 拖右下角调整大小 · 邻居自动让位</span>
          <button onClick={resetLayout} style={{marginLeft:'auto',padding:'3px 8px',fontSize:10,borderRadius:5,border:`1px solid ${T.bad}`,background:T.bad+'15',color:T.bad,cursor:'pointer'}}>↺ 恢复默认</button>
          <button onClick={()=>setEditMode(false)} style={{padding:'3px 10px',fontSize:10,borderRadius:5,border:`1px solid ${T.ok}`,background:T.ok+'15',color:T.ok,cursor:'pointer'}}>✓ 完成</button>
        </div>
      )}

      {/* react-grid-layout 网格 */}
      <div className="kp-rgl" style={{flex:1,minHeight:0,overflow:'auto'}}>
        <ResponsiveGridLayout
          className="kp-layout"
          layouts={buildAllLayouts(layout)}
          cols={COLS_MAP}
          rowHeight={ROW_HEIGHT}
          margin={[6, 6]}
          containerPadding={[0, 0]}
          isDraggable={editMode}
          isResizable={editMode}
          draggableHandle=".kp-drag-handle"
          compactType="vertical"
          preventCollision={false}
          useCSSTransforms={true}
          onLayoutChange={(curr: any) => onLayoutChange(curr)}
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
                  padding: modId === 'stats' ? 6 : 10,
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
                    dragHandle={editMode}
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
        <div onClick={()=>setDetail(null)} style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.8)',zIndex:9999,display:'flex',alignItems:'center',justifyContent:'center',padding:20}}>
          <div onClick={e=>e.stopPropagation()} style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:16,width:'100%',maxWidth:560,maxHeight:'80vh',overflowY:'auto'}}>
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
                <button onClick={()=>setDetail(null)} style={{marginTop:12,padding:'5px 12px',fontSize:11,borderRadius:6,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

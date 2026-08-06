import { useEffect, useState, useRef, useCallback } from 'react'
import { useIsMobile } from '../hooks'

/**
 * 任务流转看板 V3 — 参考 Mac Agent 作战大屏布局
 *
 * 布局：顶部统计胶囊 → 三泳道看板（运行中/待执行/已完成）→ 跨部门协作流 → 实时事件流
 */

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
  history?: { from: string; to: string; at: string }[]
}

// ── 主题变量（和作战大屏一致）──────────────────────────────
const T = {
  bg: '#0b0e14', bg2: '#11151f', panel: '#161b28', panel2: '#1c2333',
  line: '#252d40', txt: '#dde3f0', dim: '#8b93a7', faint: '#5a6275',
  acc: '#4f8cff', ok: '#3ecf8e', warn: '#f5b83d', bad: '#f4655f', rev: '#b07cff',
}

// 状态 → 标签/颜色
const ST: Record<string, { cls: string; label: string; color: string }> = {
  pending:     { cls: 'pend', label: '待办',   color: T.dim },
  todo:        { cls: 'pend', label: '待办',   color: T.dim },
  in_progress: { cls: 'run',  label: '进行中', color: T.acc },
  running:     { cls: 'run',  label: '执行中', color: T.acc },
  review:      { cls: 'rev',  label: '待验收', color: T.rev },
  blocked:     { cls: 'blk',  label: '阻塞',   color: T.bad },
  done:        { cls: 'ok',   label: '完成',   color: T.ok },
  completed:   { cls: 'ok',   label: '完成',   color: T.ok },
  failed:      { cls: 'blk',  label: '失败',   color: T.bad },
  cancelled:   { cls: 'pend', label: '取消',   color: T.faint },
}

const COLLAB_ST: Record<string, { color: string; label: string }> = {
  PENDING: { color: T.dim, label: '待处理' }, ACCEPTED: { color: T.acc, label: '已接收' },
  IN_PROGRESS: { color: T.acc, label: '执行中' }, BLOCKED: { color: T.warn, label: '阻塞' },
  DELIVERED: { color: T.rev, label: '已交付' }, RETURNED: { color: '#f97316', label: '已退回' },
  REJECTED: { color: T.bad, label: '已拒绝' }, EXPIRED: { color: T.faint, label: '已过期' },
  ESCALATED: { color: T.bad, label: '已升级' }, CLOSED: { color: T.ok, label: '已关闭' },
}

const POLL = 5000

// ── CSS（注入到组件）──────────────────────────────────────
const CSS = `
@keyframes kp-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
@keyframes kp-glow{0%,100%{box-shadow:0 0 0 0 transparent}50%{box-shadow:0 0 14px 2px var(--kp-glow)}}
@keyframes kp-blink{50%{opacity:.25}}
@keyframes kp-dash{to{background-position:24px 0}}
@keyframes kp-hover{from{transform:translateY(0)}to{transform:translateY(-2px)}}
.kp-ev{animation:kp-in .3s ease-out}
.kp-card-run{animation:kp-glow 2s ease-in-out infinite}
.kp-dot{display:inline-block;width:7px;height:7px;border-radius:50%;animation:kp-blink 1.5s infinite}
.kp-arrow{background:repeating-linear-gradient(90deg,currentColor 0 6px,transparent 6px 12px);background-size:24px 2px;animation:kp-dash .8s linear infinite;opacity:.7}
.kp-spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
`

// ── 小组件 ────────────────────────────────────────────────
const StatPill = ({ n, label, color }: { n: number; label: string; color: string }) => (
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, background: T.bg2, border: `1px solid ${T.line}`, borderRadius: 9, padding: '6px 12px' }}>
    <span style={{ fontSize: 19, fontWeight: 700, fontFamily: 'SF Mono,monospace', color }}>{n}</span>
    <span style={{ fontSize: 11, color: T.dim }}>{label}</span>
  </div>
)

const StatusTag = ({ status }: { status: string }) => {
  const s = ST[status] || { cls: 'pend', label: status, color: T.faint }
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 20, fontSize: 11,
      border: `1px solid ${s.color}`, color: s.color, background: s.color + '15',
    }}>{s.label}</span>
  )
}

// ── 任务卡片（参考 fcard）─────────────────────────────────
const TaskCard = ({ t, onClick, onMove }: { t: Task; onClick: () => void; onMove: (id: string, st: string) => void }) => {
  const s = ST[t.status] || { label: t.status, color: T.faint }
  const isRun = t.status === 'in_progress' || t.status === 'running'
  const isCollab = t.workflow_template_id?.startsWith('REQ-')
  return (
    <div
      className={isRun ? 'kp-card-run' : ''}
      onClick={onClick}
      style={{
        '--kp-glow': s.color + '60',
        background: T.bg2, border: `1px solid ${T.line}`, borderLeft: `4px solid ${s.color}`,
        borderRadius: 10, padding: '9px 10px', fontSize: 12, cursor: 'pointer',
        transition: 'transform .12s, border-color .12s',
      } as React.CSSProperties}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.borderColor = s.color }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.borderColor = T.line }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ fontWeight: 600, lineHeight: 1.35, flex: 1, color: T.txt, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {isCollab && <span style={{ color: T.rev, marginRight: 4 }}>🔗</span>}
          {t.title}
        </span>
        <span style={{ fontFamily: 'SF Mono,monospace', fontSize: 10, color: T.faint, flexShrink: 0, marginLeft: 6 }}>
          {t.priority <= 2 ? `P${t.priority}` : ''}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
        <span className="kp-dot" style={{ background: s.color, width: 6, height: 6 }} />
        <span style={{ fontSize: 11, color: s.color, fontWeight: 600 }}>{s.label}</span>
        {t.assignee && <span style={{ fontSize: 11, color: T.dim }}>· 👤 {t.assignee}</span>}
      </div>
      {t.last_failure_error && (
        <div style={{ color: T.bad, fontSize: 10, marginTop: 3 }}>
          ✗ {t.last_failure_error.slice(0, 50)}{(t.consecutive_failures || 0) > 1 ? ` (×${t.consecutive_failures})` : ''}
        </div>
      )}
      {t.is_open && (
        <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }} onClick={e => e.stopPropagation()}>
          {!isRun && <button onClick={() => onMove(t.id, 'in_progress')} style={{ padding: '2px 8px', fontSize: 10, borderRadius: 5, border: `1px solid ${T.acc}40`, background: T.acc + '15', color: T.acc, cursor: 'pointer' }}>开始</button>}
          <button onClick={() => onMove(t.id, 'done')} style={{ padding: '2px 8px', fontSize: 10, borderRadius: 5, border: `1px solid ${T.ok}40`, background: T.ok + '15', color: T.ok, cursor: 'pointer' }}>完成</button>
          <button onClick={() => onMove(t.id, 'blocked')} style={{ padding: '2px 8px', fontSize: 10, borderRadius: 5, border: `1px solid ${T.warn}40`, background: T.warn + '15', color: T.warn, cursor: 'pointer' }}>阻塞</button>
        </div>
      )}
    </div>
  )
}

// ── 泳道列 ────────────────────────────────────────────────
const Lane = ({ title, color, icon, count, children }: any) => (
  <div style={{ flex: 1, minHeight: 120, display: 'flex', flexDirection: 'column' }}>
    <div style={{ fontSize: 11.5, fontWeight: 700, marginBottom: 4, paddingBottom: 3, borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
      <span className="kp-dot" style={{ background: color, width: 6, height: 6 }} />
      <span style={{ color }}>{icon} {title}</span>
      <span style={{ color: T.faint, fontWeight: 400, fontSize: 11 }}>{count}</span>
    </div>
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, paddingRight: 4 }}>
      {children}
    </div>
  </div>
)

// ════════════════════════════════════════════════════════════
// 主组件
// ════════════════════════════════════════════════════════════
export const KanbanPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [board, setBoard] = useState<Board | null>(null)
  const [health, setHealth] = useState<any>(null)
  const [inbox, setInbox] = useState<CollabItem[]>([])
  const [outbox, setOutbox] = useState<CollabItem[]>([])
  const [collabError, setCollabError] = useState('')
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<any>(null)
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newBody, setNewBody] = useState('')
  const [newAssignee, setNewAssignee] = useState('hm')
  const [msg, setMsg] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [events, setEvents] = useState<{ id: string; text: string; ts: number; type: string }[]>([])
  const [lastUpdate, setLastUpdate] = useState(0)
  const [, forceTick] = useState(0)
  const prevRef = useRef<Board | null>(null)
  const evCtr = useRef(0)

  const addEv = useCallback((text: string, type: string) => {
    evCtr.current += 1
    setEvents(p => [{ id: `ev-${evCtr.current}`, text, ts: Date.now(), type }, ...p].slice(0, 30))
  }, [])

  const load = useCallback(async () => {
    try {
      const h = await (await fetch('/api/kanban/health')).json()
      setHealth(h)
      if (h.reachable) {
        const b = await (await fetch('/api/kanban/board')).json()
        // diff
        if (prevRef.current) {
          const pm = new Map<string, Task>()
          Object.values(prevRef.current.columns).flat().forEach((t: any) => pm.set(t.id, t))
          Object.values(b.columns).flat().forEach((t: any) => {
            const old = pm.get(t.id)
            if (!old) addEv(`新卡: ${t.title}`, 'create')
            else if (old.status !== t.status) {
              const s = ST[t.status]?.label || t.status
              addEv(`${t.title} → ${s}`, t.status === 'done' ? 'done' : 'move')
            }
          })
        }
        prevRef.current = b
        setBoard(b)
      }
      try {
        const [i, o] = await Promise.all([(await fetch('/api/v1/inbox')).json(), (await fetch('/api/v1/outbox')).json()])
        setInbox(i.items || []); setOutbox(o.items || []); setCollabError('')
      } catch { setCollabError('协作服务不可用') }
    } catch { /* silent */ } finally { setLoading(false); setLastUpdate(Date.now()) }
  }, [addEv])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(load, POLL)
    return () => clearInterval(t)
  }, [autoRefresh, load])
  useEffect(() => { const t = setInterval(() => forceTick(x => x + 1), 1000); return () => clearInterval(t) }, [])

  const move = async (id: string, status: string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) })
    if (!r.ok) { setMsg(`流转失败: ${(await r.json()).detail}`); return }
    setMsg(''); load()
  }
  const openDetail = async (id: string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`)
    const j = await r.json()
    setDetail(r.ok ? j.task : { id, error: j.detail })
  }
  const create = async () => {
    if (!newTitle.trim()) return
    const r = await fetch('/api/kanban/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: newTitle, body: newBody, assignee: newAssignee, created_by: 'dashboard' }) })
    if (!r.ok) { setMsg(`建卡失败: ${(await r.json()).detail}`); return }
    setNewTitle(''); setNewBody(''); setShowNew(false); setMsg(''); load()
  }

  // ── 统计 ──────────────────────────────────────────────
  const cols = board?.columns || {}
  const running = (cols.in_progress || []).length + (cols.running || []).length
  const review = (cols.review || []).length
  const pending = (cols.pending || []).length + (cols.todo || []).length
  const blocked = (cols.blocked || []).length
  const done = (cols.done || []).length + (cols.completed || []).length
  const total = board?.total ?? 0
  const progress = total > 0 ? Math.round((done / total) * 100) : 0
  const secsAgo = lastUpdate ? Math.floor((Date.now() - lastUpdate) / 1000) : 0

  if (loading && !board) return (
    <div style={{ color: T.dim, textAlign: 'center', padding: 40, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
      <span className="kp-spin" style={{ display: 'inline-block', width: 14, height: 14, border: `2px solid ${T.line}`, borderTopColor: T.acc, borderRadius: '50%' }} />
      正在载入任务流转看板...
    </div>
  )

  if (health && !health.reachable) return (
    <div style={{ background: T.panel, border: `1px solid ${T.bad}40`, borderRadius: 10, padding: 16 }}>
      <div style={{ color: T.bad, fontWeight: 700 }}>⚠️ seohm 看板未接通</div>
      <div style={{ color: T.dim, fontSize: 12, marginTop: 4 }}>{health.reason}</div>
      <div style={{ color: T.faint, fontSize: 11 }}>路径: {health.path}</div>
    </div>
  )

  // ── 泳道分组 ──────────────────────────────────────────
  const laneRunning = [...(cols.in_progress || []), ...(cols.running || [])]
  const laneReview = [...(cols.review || [])]
  const laneBlocked = [...(cols.blocked || [])]
  const lanePending = [...(cols.pending || []), ...(cols.todo || [])]
  const laneDone = [...(cols.done || []), ...(cols.completed || []), ...(cols.failed || []), ...(cols.cancelled || [])]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <style>{CSS}</style>

      {/* ═══ 顶部：统计胶囊 + 控制 ═══ */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <StatPill n={running} label="执行中" color={T.acc} />
          <StatPill n={review} label="待验收" color={T.rev} />
          <StatPill n={pending} label="待办" color={T.dim} />
          <StatPill n={blocked} label="阻塞" color={T.bad} />
          <StatPill n={done} label="完成" color={T.ok} />
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          {autoRefresh && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: T.ok }}>
              <span className="kp-dot" style={{ background: T.ok, width: 6, height: 6 }} />LIVE · {secsAgo}s
            </span>
          )}
          {/* 进度条 */}
          <div style={{ width: 100, height: 5, background: T.line, borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${progress}%`, background: `linear-gradient(90deg, ${T.ok}, ${T.acc})`, transition: 'width .5s' }} />
          </div>
          <span style={{ fontSize: 10, color: T.faint, fontFamily: 'SF Mono,monospace' }}>{progress}%</span>
          <button onClick={() => setAutoRefresh(!autoRefresh)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: `1px solid ${autoRefresh ? T.ok + '40' : T.line}`, background: autoRefresh ? T.ok + '15' : T.panel2, color: autoRefresh ? T.ok : T.dim, cursor: 'pointer' }}>
            {autoRefresh ? '⏸' : '▶'}
          </button>
          <button onClick={() => setShowNew(!showNew)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: `1px solid ${T.acc}`, background: T.acc, color: '#fff', cursor: 'pointer' }}>＋ 新建</button>
          <button onClick={load} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: `1px solid ${T.line}`, background: T.panel2, color: T.txt, cursor: 'pointer' }}>↻</button>
        </div>
      </div>

      {msg && <div style={{ background: T.bad + '15', border: `1px solid ${T.bad}40`, borderRadius: 8, padding: '8px 12px', color: T.bad, fontSize: 12 }}>{msg}</div>}

      {showNew && (
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input placeholder="任务标题" value={newTitle} onChange={e => setNewTitle(e.target.value)} style={{ background: T.bg2, border: `1px solid ${T.line}`, borderRadius: 7, color: T.txt, fontSize: 12, padding: '6px 10px' }} />
          <textarea placeholder="描述（可选）" value={newBody} onChange={e => setNewBody(e.target.value)} rows={2} style={{ background: T.bg2, border: `1px solid ${T.line}`, borderRadius: 7, color: T.txt, fontSize: 12, padding: '6px 10px', resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 6 }}>
            <input placeholder="指派给" value={newAssignee} onChange={e => setNewAssignee(e.target.value)} style={{ background: T.bg2, border: `1px solid ${T.line}`, borderRadius: 7, color: T.txt, fontSize: 12, padding: '6px 10px', width: 120 }} />
            <button onClick={create} disabled={!newTitle.trim()} style={{ padding: '6px 14px', fontSize: 12, borderRadius: 7, border: 0, background: newTitle.trim() ? T.acc : T.line, color: '#fff', cursor: 'pointer' }}>创建</button>
          </div>
        </div>
      )}

      {/* ═══ 三泳道看板（核心布局）═══ */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr',
        gap: 12, minHeight: 300,
      }}>
        {/* 泳道1：运行中 + 验收 */}
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 'calc(100vh - 280px)' }}>
          <Lane title="执行中" color={T.acc} icon="⚡" count={laneRunning.length}>
            {laneRunning.length === 0 && laneReview.length === 0
              ? <div style={{ color: T.faint, fontSize: 11, padding: '16px 0', textAlign: 'center' }}>空</div>
              : <>
                {laneRunning.map(t => <TaskCard key={t.id} t={t} onClick={() => openDetail(t.id)} onMove={move} />)}
                {laneReview.length > 0 && <div style={{ fontSize: 11, fontWeight: 700, color: T.rev, marginTop: 4, paddingBottom: 3, borderBottom: `1px solid ${T.line}` }}>🔍 待验收</div>}
                {laneReview.map(t => <TaskCard key={t.id} t={t} onClick={() => openDetail(t.id)} onMove={move} />)}
              </>}
          </Lane>
        </div>

        {/* 泳道2：待办 + 阻塞 */}
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 'calc(100vh - 280px)' }}>
          <Lane title="待办" color={T.dim} icon="⏳" count={lanePending.length}>
            {lanePending.length === 0 && laneBlocked.length === 0
              ? <div style={{ color: T.faint, fontSize: 11, padding: '16px 0', textAlign: 'center' }}>空</div>
              : <>
                {lanePending.map(t => <TaskCard key={t.id} t={t} onClick={() => openDetail(t.id)} onMove={move} />)}
                {laneBlocked.length > 0 && <div style={{ fontSize: 11, fontWeight: 700, color: T.warn, marginTop: 4, paddingBottom: 3, borderBottom: `1px solid ${T.line}` }}>🚫 阻塞</div>}
                {laneBlocked.map(t => <TaskCard key={t.id} t={t} onClick={() => openDetail(t.id)} onMove={move} />)}
              </>}
          </Lane>
        </div>

        {/* 泳道3：已完成 */}
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 'calc(100vh - 280px)' }}>
          <Lane title="已完成" color={T.ok} icon="✅" count={laneDone.length}>
            {laneDone.length === 0
              ? <div style={{ color: T.faint, fontSize: 11, padding: '16px 0', textAlign: 'center' }}>空</div>
              : laneDone.map(t => <TaskCard key={t.id} t={t} onClick={() => openDetail(t.id)} onMove={move} />)}
          </Lane>
        </div>
      </div>

      {/* ═══ 跨部门协作流 ═══ */}
      {(inbox.length > 0 || outbox.length > 0) && (
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: T.txt, marginBottom: 10 }}>🔗 跨部门协作流</div>
          {/* 流向指示器 */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginBottom: 12 }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'SF Mono,monospace', color: T.acc }}>{outbox.length}</div>
              <div style={{ fontSize: 10, color: T.dim }}>📤 发出</div>
            </div>
            <div className="kp-arrow" style={{ width: 50, height: 2, color: T.dim }} />
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'SF Mono,monospace', color: T.rev }}>{inbox.length + outbox.length}</div>
              <div style={{ fontSize: 10, color: T.dim }}>协作中</div>
            </div>
            <div className="kp-arrow" style={{ width: 50, height: 2, color: T.dim }} />
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'SF Mono,monospace', color: T.ok }}>{inbox.length}</div>
              <div style={{ fontSize: 10, color: T.dim }}>📥 接收</div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
            {[
              ['📤 发件箱', outbox], ['📥 收件箱', inbox]
            ].map(([title, items]: any) => (
              <div key={title}>
                <div style={{ fontSize: 11, fontWeight: 700, color: T.dim, marginBottom: 5 }}>{title} ({items.length})</div>
                {items.length === 0 && <div style={{ color: T.faint, fontSize: 11, padding: '8px 0' }}>暂无</div>}
                {items.map((it: CollabItem) => {
                  const meta = COLLAB_ST[it.status] || { color: T.faint, label: it.status }
                  const cap = it.capability || it.to?.capability || '—'
                  const dept = it.from?.dept || it.to?.dept || '—'
                  return (
                    <div key={it.request_id} style={{ background: T.bg2, border: `1px solid ${meta.color}30`, borderLeft: `3px solid ${meta.color}`, borderRadius: 8, padding: '6px 10px', marginBottom: 5, fontSize: 11 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: T.txt, fontWeight: 600 }}>{cap}</span>
                        <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: meta.color + '20', color: meta.color }}>{meta.label}</span>
                      </div>
                      <div style={{ color: T.dim, fontSize: 10, marginTop: 2 }}>📤 {dept} · {it.priority || ''} {it.deadline && `· ⏰ ${it.deadline.slice(0, 10)}`}</div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ 实时事件流 ═══ */}
      {events.length > 0 && (
        <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: T.dim, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="kp-dot" style={{ background: T.acc, width: 6, height: 6 }} />实时事件流
            <span style={{ fontSize: 10, color: T.faint, fontWeight: 400 }}>最近 {events.length} 条</span>
          </div>
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {events.map(ev => {
              const colors: Record<string, string> = { move: T.acc, create: T.ok, done: T.ok, error: T.bad }
              const icons: Record<string, string> = { move: '→', create: '✨', done: '🎉', error: '✗' }
              const age = Math.floor((Date.now() - ev.ts) / 1000)
              const ageStr = age < 60 ? `${age}s` : age < 3600 ? `${Math.floor(age / 60)}m` : `${Math.floor(age / 3600)}h`
              return (
                <div key={ev.id} className="kp-ev" style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: `1px solid ${T.line}50`, fontSize: 12 }}>
                  <span style={{ color: colors[ev.type] || T.dim, fontWeight: 700 }}>{icons[ev.type] || '•'}</span>
                  <span style={{ color: T.txt, flex: 1 }}>{ev.text}</span>
                  <span style={{ color: T.faint, fontSize: 10, fontFamily: 'SF Mono,monospace' }}>{ageStr}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ═══ 详情弹窗 ═══ */}
      {detail && (
        <div onClick={() => setDetail(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16, width: '100%', maxWidth: 640, maxHeight: '85vh', overflowY: 'auto' }}>
            {detail.error ? (
              <div style={{ color: T.bad }}>{detail.error}</div>
            ) : (
              <>
                <div style={{ fontSize: 15, fontWeight: 700, color: T.txt }}>{detail.title}</div>
                <div style={{ fontSize: 10, color: T.faint, marginTop: 2, fontFamily: 'SF Mono,monospace' }}>
                  {detail.id} · <StatusTag status={detail.status} /> · P{detail.priority} · 👤{detail.assignee || '未指派'}
                </div>
                {detail.body && <div style={{ color: T.txt, fontSize: 12, marginTop: 10, whiteSpace: 'pre-wrap' }}>{detail.body}</div>}
                {(detail.runs || []).length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: T.dim, marginBottom: 6 }}>执行记录</div>
                    {detail.runs.map((r: any) => (
                      <div key={r.id} style={{ background: T.bg2, borderRadius: 6, padding: 6, marginTop: 4, fontSize: 10, color: T.dim }}>
                        #{r.id} {r.step_key} · {r.status} {r.error && <span style={{ color: T.bad }}>✗ {r.error}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {(detail.events || []).length > 0 && (
                  <details style={{ marginTop: 12 }}>
                    <summary style={{ cursor: 'pointer', fontSize: 11, color: T.faint }}>事件轨迹 ({detail.events.length})</summary>
                    {detail.events.map((e: any) => (
                      <div key={e.id} style={{ fontSize: 10, color: T.faint, marginTop: 3, fontFamily: 'SF Mono,monospace' }}>{e.kind} · {e.payload}</div>
                    ))}
                  </details>
                )}
                <button onClick={() => setDetail(null)} style={{ marginTop: 14, padding: '6px 14px', fontSize: 12, borderRadius: 7, border: `1px solid ${T.line}`, background: T.panel2, color: T.txt, cursor: 'pointer' }}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

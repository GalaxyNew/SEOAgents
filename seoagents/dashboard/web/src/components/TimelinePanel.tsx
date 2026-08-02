import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'

/**
 * 时间规划 —— hm 的时间线。排期、触发、确认、分诊,并显示负载率与护栏。
 * 数据全部来自 /api/timeline/*,没有任何前端造数。
 */

type Node = {
  node_id: string
  kind: string
  intent: string
  scheduled_at: string
  expected_minutes: number
  state: string
  subject_ref?: string
  chain_depth?: number
  outcome?: string
}

type Agenda = {
  now: string
  horizon_hours: number
  upcoming: Node[]
  in_flight: Node[]
  unread_count: number
  committed_minutes: number
  load_ratio: number
  next_free_slot: string
}

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

const KIND_META: Record<string, { label: string; color: string }> = {
  START: { label: '开工', color: '#3b82f6' },
  CHECKPOINT: { label: '检查', color: '#a855f7' },
  DEADLINE: { label: '截止', color: '#ef4444' },
  REVIEW: { label: '复盘', color: '#10b981' },
}

const fmt = (iso: string) => {
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch { return iso }
}

export const TimelinePanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [agenda, setAgenda] = useState<Agenda | null>(null)
  const [due, setDue] = useState<Node[]>([])
  const [unread, setUnread] = useState<Node[]>([])
  const [hours, setHours] = useState(24)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [nKind, setNKind] = useState('START')
  const [nIntent, setNIntent] = useState('')
  const [nAt, setNAt] = useState('')
  const [nMin, setNMin] = useState(30)

  const load = async (h = hours) => {
    setLoading(true); setErr('')
    try {
      const [a, d, u] = await Promise.all([
        (await fetch(`/api/timeline/agenda?hours_ahead=${h}`)).json(),
        (await fetch('/api/timeline/due')).json(),
        (await fetch('/api/timeline/unread')).json(),
      ])
      setAgenda(a)
      setDue(Array.isArray(d) ? d : (d.items || d.nodes || []))
      setUnread(Array.isArray(u) ? u : (u.items || u.nodes || []))
    } catch (e) {
      setErr(`时间线不可用: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const act = async (path: string, body?: any, label = '') => {
    try {
      const r = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { setMsg(`${label}失败: ${j.detail || r.status}`); return }
      setMsg(`${label}成功`); load()
    } catch (e) { setMsg(`${label}异常: ${e}`) }
  }

  const schedule = async () => {
    if (!nIntent.trim() || !nAt) return
    // datetime-local 是本地时间,转成带时区的 ISO 再提交
    const iso = new Date(nAt).toISOString()
    const r = await fetch('/api/timeline/nodes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduled_at: iso, kind: nKind, intent: nIntent, expected_minutes: nMin }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setMsg(`排期被拒: ${j.detail || JSON.stringify(j)}`); return }
    setMsg('已排入时间线'); setNIntent(''); setShowNew(false); load()
  }

  if (loading && !agenda) {
    return <div style={{ ...card, color: '#9ca3af', textAlign: 'center' }}>🗓️ 正在载入时间线...</div>
  }
  if (err) {
    return <div style={{ ...card, borderColor: '#7f1d1d', color: '#f87171' }}>⚠️ {err}</div>
  }

  const load_pct = Math.round((agenda?.load_ratio || 0) * 100)
  const loadColor = load_pct > 80 ? '#ef4444' : load_pct > 50 ? '#f59e0b' : '#10b981'

  const nodeRow = (n: Node, actions = true) => {
    const meta = KIND_META[n.kind] || { label: n.kind, color: '#64748b' }
    return (
      <div key={n.node_id} style={{
        display: 'flex', alignItems: isMobile ? 'flex-start' : 'center', gap: 8, background: '#0f172a',
        border: '1px solid #1e293b', borderRadius: 6, padding: '7px 9px', fontSize: 11,
        flexWrap: isMobile ? 'wrap' : 'nowrap',
      }}>
        <span style={{
          flexShrink: 0, background: '#1e293b', color: meta.color, borderRadius: 3,
          padding: '1px 6px', fontSize: 9, fontWeight: 700, width: 40, textAlign: 'center',
        }}>{meta.label}</span>
        <span style={{ flexShrink: 0, color: '#94a3b8', fontSize: 10, width: 88 }}>{fmt(n.scheduled_at)}</span>
        <span style={{ flex: 1, minWidth: isMobile ? '100%' : 0, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: isMobile ? 'normal' : 'nowrap', order: isMobile ? 3 : 0 }}>
          {n.intent}
        </span>
        <span style={{ flexShrink: 0, color: '#475569', fontSize: 10, width: 40, textAlign: 'right' }}>{n.expected_minutes}分</span>
        {actions && (
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            <button onClick={() => act(`/api/timeline/nodes/${n.node_id}/fire`, undefined, '触发')} style={miniBtn('#1e3a8a', '#93c5fd')}>触发</button>
            <button onClick={() => act(`/api/timeline/nodes/${n.node_id}/ack`, { outcome: '已完成(面板确认)' }, '确认')} style={miniBtn('#064e3b', '#6ee7b7')}>确认</button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        <div style={card}>
          <div style={{ fontSize: 10, color: '#64748b' }}>⏱️ 负载率</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: loadColor }}>{load_pct}%</div>
          <div style={{ background: '#1f2937', height: 4, borderRadius: 2, marginTop: 4, overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(load_pct, 100)}%`, background: loadColor, height: '100%' }} />
          </div>
          <div style={{ fontSize: 9, color: '#475569', marginTop: 3 }}>
            已承诺 {agenda?.committed_minutes} 分 / 未来 {agenda?.horizon_hours} 小时
          </div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 10, color: '#64748b' }}>📅 已排节点</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{agenda?.upcoming.length ?? 0}</div>
          <div style={{ fontSize: 9, color: '#475569', marginTop: 3 }}>执行中 {agenda?.in_flight.length ?? 0}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 10, color: '#64748b' }}>🔔 待办到点</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: due.length ? '#f59e0b' : '#e2e8f0' }}>{due.length}</div>
          <div style={{ fontSize: 9, color: '#475569', marginTop: 3 }}>未读 {agenda?.unread_count ?? 0}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 10, color: '#64748b' }}>🕳️ 下一个空档</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#60a5fa', marginTop: 4 }}>
            {agenda ? fmt(agenda.next_free_slot) : '—'}
          </div>
        </div>
      </div>

      {/* 操作条 */}
      <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: '#64748b' }}>视野</span>
        {[24, 72, 168].map((h) => (
          <button key={h} onClick={() => { setHours(h); load(h) }}
            style={btn(hours === h ? '#3b82f6' : '#334155')}>{h === 24 ? '1天' : h === 72 ? '3天' : '7天'}</button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowNew(!showNew)} style={btn('#2563eb')}>＋ 排期</button>
        <button onClick={() => act('/api/timeline/sweep', {}, '清扫')} style={btn('#334155')}>🧹 扫过期</button>
        <button onClick={() => act('/api/timeline/triage', {}, '分诊')} style={btn('#334155')}>📮 分诊未读</button>
        <button onClick={() => load()} style={btn('#334155')}>↻</button>
      </div>

      {msg && <div style={{ ...card, fontSize: 11, color: msg.includes('失败') || msg.includes('拒') ? '#f87171' : '#6ee7b7' }}>{msg}</div>}

      {showNew && (
        <div style={{ ...card, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <select value={nKind} onChange={(e) => setNKind(e.target.value)} style={{ ...input, width: 100 }}>
            {Object.entries(KIND_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <input placeholder="要做什么(intent)" value={nIntent} onChange={(e) => setNIntent(e.target.value)} style={{ ...input, flex: 1, minWidth: 180 }} />
          <input type="datetime-local" value={nAt} onChange={(e) => setNAt(e.target.value)} style={{ ...input, width: 190, colorScheme: 'dark' }} />
          <input type="number" min={5} step={5} value={nMin} onChange={(e) => setNMin(Number(e.target.value))} style={{ ...input, width: 80 }} title="预计耗时(分钟)" />
          <button onClick={schedule} disabled={!nIntent.trim() || !nAt} style={btn(nIntent.trim() && nAt ? '#2563eb' : '#334155')}>排入</button>
        </div>
      )}

      {/* 到点待办 */}
      {due.length > 0 && (
        <div style={{ ...card, borderColor: '#78350f' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#fcd34d', marginBottom: 6 }}>🔔 已到点,等你处理 ({due.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{due.map((n) => nodeRow(n))}</div>
        </div>
      )}

      {/* 执行中 */}
      {(agenda?.in_flight.length ?? 0) > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#38bdf8', marginBottom: 6 }}>▶ 执行中 ({agenda!.in_flight.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{agenda!.in_flight.map((n) => nodeRow(n))}</div>
        </div>
      )}

      {/* 日程 */}
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', marginBottom: 6 }}>
          🗓️ 未来 {agenda?.horizon_hours} 小时日程 ({agenda?.upcoming.length ?? 0})
        </div>
        {(agenda?.upcoming.length ?? 0) === 0 ? (
          <div style={{ color: '#475569', fontSize: 11, padding: '14px 0', textAlign: 'center' }}>
            这段视野内没有已排节点 —— 时间线是空的,不是没取到数据
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{agenda!.upcoming.map((n) => nodeRow(n))}</div>
        )}
      </div>

      {/* 未读 */}
      {unread.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#a855f7', marginBottom: 6 }}>📮 未读回执 ({unread.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{unread.map((n) => nodeRow(n, false))}</div>
        </div>
      )}

      <div style={{ fontSize: 10, color: '#475569', textAlign: 'right' }}>
        护栏:日节点上限 / 检查链深度上限 / 最小间隔 / 30 天视野 —— 越界的排期会被后端拒绝并说明原因
      </div>
    </div>
  )
}

const btn = (bg: string): React.CSSProperties => ({
  background: bg, color: '#fff', border: 0, borderRadius: 5, padding: '5px 12px',
  fontSize: 11, fontWeight: 600, cursor: 'pointer',
})
const miniBtn = (bg: string, fg: string): React.CSSProperties => ({
  background: bg, color: fg, border: 0, borderRadius: 4, padding: '2px 7px',
  fontSize: 9, fontWeight: 600, cursor: 'pointer',
})
const input: React.CSSProperties = {
  background: '#0f172a', border: '1px solid #334155', borderRadius: 5,
  color: '#e2e8f0', fontSize: 11, padding: '5px 8px', boxSizing: 'border-box',
}

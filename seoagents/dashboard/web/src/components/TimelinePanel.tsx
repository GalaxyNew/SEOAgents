import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { TimelineTrack } from './TimelineTrack'

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
  runtime_state?: string
  created_by?: string
  cron?: {
    job_id: string
    schedule_display?: string
    next_run_at?: string
    last_run_at?: string
    last_status?: string
    last_error?: string
    enabled?: boolean
    execution?: Record<string, unknown>
  }
  context?: Record<string, any>
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
  cron_jobs?: any[]
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

// 来源标识
const SOURCE_META: Record<string, { label: string; color: string; tip: string }> = {
  ag: { label: 'Ag', color: '#22d3ee', tip: 'Agent自主创建' },
  yh: { label: 'Yh', color: '#fbbf24', tip: '用户手动创建' },
  ya: { label: 'Ya', color: '#a78bfa', tip: '用户让Agent创建' },
}
const sourceOf = (cb?: string) => {
  if (!cb || cb === 'unknown') return null
  if (['timeline-ui', 'manual', 'user', 'yh', 'you'].includes(cb)) return SOURCE_META.yh
  if (cb.startsWith('user-ask') || cb.startsWith('ya-')) return SOURCE_META.ya
  return SOURCE_META.ag
}

export const TimelinePanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [agenda, setAgenda] = useState<Agenda | null>(null)
  const [due, setDue] = useState<Node[]>([])
  const [unread, setUnread] = useState<Node[]>([])
  const [hours, setHours] = useState(15)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [nKind, setNKind] = useState('START')
  const [nIntent, setNIntent] = useState('')
  const [nAt, setNAt] = useState('')
  const [nMin, setNMin] = useState(30)
  const [rangeNodes, setRangeNodes] = useState<any[]>([])
  const [picked, setPicked] = useState<any | null>(null)
  // 两种执行方式:交给 agent 跑一条指令,或到点启动一个工作流。
  // 不选就是纯提醒 —— 投递了但不自动执行。
  const [nMode, setNMode] = useState<'agent' | 'workflow'>('agent')
  const [nTask, setNTask] = useState('')
  const [nSchedule, setNSchedule] = useState('')
  const [nDeliver, setNDeliver] = useState('local')
  const [nWf, setNWf] = useState('')
  const [wfList, setWfList] = useState<any[]>([])

  const load = async (h = hours) => {
    setLoading(true); setErr('')
    try {
      const [a, u] = await Promise.all([
        (await fetch(`/api/timeline/agenda-v2?hours_ahead=${h}`)).json(),
        (await fetch('/api/timeline/unread')).json(),
      ])
      setAgenda(a)
      try {
        const rg = await (await fetch(`/api/timeline/range-v2?hours_back=${Math.max(h, 24)}&hours_ahead=${h}`)).json()
        setRangeNodes(rg.nodes || [])
      } catch { setRangeNodes([]) }
      setDue([])
      setUnread(Array.isArray(u) ? u : (u.items || u.nodes || []))
    } catch (e) {
      setErr(`时间线不可用: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    fetch('/api/workflows/templates').then(r => r.json())
      .then(d => setWfList(d.templates || d.items || []))
      .catch(() => setWfList([]))
  }, [])

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
    if (nMode === 'agent' && !nTask.trim()) { setMsg('请填写 Agent 任务要求'); return }
    if (nMode === 'workflow' && !nWf) { setMsg('请选择工作流'); return }
    // datetime-local 是本地时间,转成带时区的 ISO；schedule 可填 cron/interval。
    const iso = new Date(nAt).toISOString()
    const selectedWf = wfList.find((w: any) => (w.template_id || w.id) === nWf)
    // 一次性节点写入 Timeline，由固定 Hermes Timeline Pulse 每分钟唤醒；
    // 周期排期直接创建 Hermes Cron，避免 Pulse 自行繁殖 Cron。
    const endpoint = nSchedule.trim() ? '/api/timeline/schedules' : '/api/timeline/plans'
    const r = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scheduled_at: iso,
        schedule: nSchedule.trim(),
        kind: nKind,
        intent: nIntent,
        expected_minutes: nMin,
        task_type: nMode === 'agent' ? 'agent_prompt' : 'workflow',
        prompt: nMode === 'agent' ? nTask : '',
        workflow_id: nMode === 'workflow' ? nWf : '',
        workflow_version: nMode === 'workflow' ? (selectedWf?.version || '') : '',
        deliver: nDeliver,
        created_by: 'timeline-ui',
      }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setMsg(`排期被拒: ${j.detail || JSON.stringify(j)}`); return }
    setMsg(j.cron?.job_id ? `已创建 Hermes Cron · ${j.cron.job_id}` : `已排入 Timeline · ${j.node_id || ''}`)
    setNIntent(''); setNTask(''); setNSchedule(''); setShowNew(false); load()
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
        {(() => { const st = sourceOf(n.created_by); return st ? (
          <span style={{ flexShrink: 0, fontSize: 8, fontWeight: 700, color: st.color, background: '#0b1220', borderRadius: 3, padding: '1px 5px', textAlign: 'center' }} title={st.tip}>{st.label}</span>
        ) : null })()}
        <span style={{ flexShrink: 0, color: '#94a3b8', fontSize: 10, width: 88 }}>{fmt(n.scheduled_at)}</span>
        <span style={{ flex: 1, minWidth: isMobile ? '100%' : 0, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: isMobile ? 'normal' : 'nowrap', order: isMobile ? 3 : 0 }}>
          {n.intent}
        </span>
        <span style={{ flexShrink: 0, color: '#475569', fontSize: 10, width: 40, textAlign: 'right' }}>{n.expected_minutes}分</span>
        <span style={{ flexShrink: 0, color: '#475569', fontSize: 9, minWidth: 62 }}>
          {n.runtime_state || n.state}
        </span>
        {actions && (n.cron?.job_id || n.context?.scheduler === 'hermes-pulse') && (
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            {n.runtime_state === 'BLOCKED_APPROVAL' ? (
              <button onClick={() => act(`/api/timeline/schedules/${n.node_id}/approve`, undefined, '批准执行')} style={miniBtn('#78350f', '#fde68a')}>批准</button>
            ) : (
              <button onClick={() => act(`/api/timeline/schedules/${n.node_id}/run`, undefined, '立即运行')} style={miniBtn('#1e3a8a', '#93c5fd')}>运行</button>
            )}
            <button onClick={() => act(`/api/timeline/schedules/${n.node_id}/${n.runtime_state === 'PAUSED' ? 'resume' : 'pause'}`, undefined, n.runtime_state === 'PAUSED' ? '恢复' : '暂停')} style={miniBtn('#374151', '#d1d5db')}>
              {n.runtime_state === 'PAUSED' ? '恢复' : '暂停'}
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <TimelineTrack nodes={rangeNodes} onPick={setPicked} defaultHours={hours} key={`track-${hours}`} />

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
          <div style={{ fontSize: 9, color: '#475569', marginTop: 3 }}>Hermes Cron 执行中 {agenda?.in_flight.length ?? 0}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 10, color: '#64748b' }}>⏰ Cron 固定节律</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{agenda?.cron_jobs?.length ?? 0}</div>
          <div style={{ fontSize: 9, color: '#475569', marginTop: 3 }}>全部任务最终由 Hermes Cron 执行</div>
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
        {[15, 24, 72, 168].map((h) => (
          <button key={h} onClick={() => { setHours(h); load(h) }}
            style={btn(hours === h ? '#3b82f6' : '#334155')}>{h === 15 ? '15小时' : h === 24 ? '1天' : h === 72 ? '3天' : '7天'}</button>
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
          <input placeholder="可选：cron或 every 2h" value={nSchedule} onChange={(e) => setNSchedule(e.target.value)} style={{ ...input, width: 150 }} title="留空则按左侧时间执行一次" />
          <select value={nDeliver} onChange={(e) => setNDeliver(e.target.value)} style={{ ...input, width: 100 }}>
            <option value="local">仅 Timeline</option>
            <option value="origin">同步飞书</option>
          </select>
          <input type="number" min={5} step={5} value={nMin} onChange={(e) => setNMin(Number(e.target.value))} style={{ ...input, width: 80 }} title="预计耗时(分钟)" />
          <button onClick={schedule} disabled={!nIntent.trim() || !nAt} style={btn(nIntent.trim() && nAt ? '#2563eb' : '#334155')}>排入</button>

          <div style={{ width: '100%', borderTop: '1px solid #1f2937', paddingTop: 8, marginTop: 2 }}>
            <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>
              执行方式（一次性任务由 Hermes Timeline Pulse 到点执行；周期任务直连 Hermes Cron）
              <span style={{ color: '#64748b', marginLeft: 6 }}>
                可直接输入 Agent 任务，或选择已保存工作流
              </span>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              {([['agent', '新建 Agent 任务'], ['workflow', '执行已有工作流']] as const).map(([m, label]) => (
                <button key={m} onClick={() => setNMode(m)} style={{
                  background: nMode === m ? '#1e293b' : 'transparent',
                  color: nMode === m ? '#60a5fa' : '#94a3b8',
                  border: `1px solid ${nMode === m ? '#3b82f6' : '#1f2937'}`,
                  borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer',
                }}>{label}</button>
              ))}
              {nMode === 'agent' && (
                <input placeholder="输入完整要求，当前 Hermes 按要求执行" value={nTask}
                  onChange={(e) => setNTask(e.target.value)}
                  style={{ ...input, flex: 1, minWidth: 300 }} />
              )}
              {nMode === 'workflow' && (
                <select value={nWf} onChange={(e) => setNWf(e.target.value)} style={{ ...input, flex: 1, minWidth: 220 }}>
                  <option value="">选一个已保存工作流…</option>
                  {wfList.map((w: any) => (
                    <option key={w.template_id || w.id} value={w.template_id || w.id}>
                      {w.name || w.template_id || w.id}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        </div>
      )}

      {picked && (
        <div onClick={() => setPicked(null)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 100001,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div onClick={(e) => e.stopPropagation()} style={{
            width: 460, maxWidth: '100%', background: '#0f172a',
            border: '1px solid #1e293b', borderRadius: 12, padding: 16,
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9', marginBottom: 10 }}>
              {picked.intent}
            </div>
            {([
              ['类型 / 状态', `${picked.kind} · ${picked.state}`],
              ['计划时间', new Date(picked.scheduled_at).toLocaleString('zh-CN', { hour12: false })],
              ['对象', picked.subject_ref || '—'],
              ['结论', picked.outcome || '(尚未执行)'],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '78px 1fr', gap: 8, fontSize: 12, marginBottom: 6 }}>
                <span style={{ color: '#64748b' }}>{k}</span>
                <span style={{ color: '#cbd5e1', wordBreak: 'break-all' }}>{v}</span>
              </div>
            ))}
            {picked.context && Object.keys(picked.context).length > 0 && (
              <pre style={{
                fontSize: 10, color: '#94a3b8', background: '#0b1220', borderRadius: 6,
                padding: 8, marginTop: 8, maxHeight: 160, overflow: 'auto',
              }}>{JSON.stringify(picked.context, null, 2)}</pre>
            )}
            <button onClick={() => setPicked(null)} style={{ ...btn('#374151'), marginTop: 10, width: '100%' }}>关闭</button>
          </div>
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

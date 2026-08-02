import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'

/**
 * 任务卡 —— 数据源是 seohm 的看板(/data/hermes-seo/kanban.db),
 * 与 seohm 共用同一份卡;下半区是 SEOAgents 自己的跨部门协作单。
 */

type Task = {
  id: string
  title: string
  body: string
  assignee: string
  status: string
  priority: number
  created_by: string
  created_at_iso: string | null
  started_at_iso: string | null
  completed_at_iso: string | null
  is_open: boolean
  current_step_key?: string
  last_failure_error?: string
}

type Board = {
  ok: boolean
  source: string
  total: number
  open_count: number
  columns: Record<string, Task[]>
  statuses: { open: string[]; closed: string[] }
}

type CollabItem = Record<string, any>

const COL_META: Record<string, { label: string; color: string }> = {
  pending: { label: '待办', color: '#64748b' },
  todo: { label: '待办', color: '#64748b' },
  in_progress: { label: '进行中', color: '#3b82f6' },
  running: { label: '执行中', color: '#0ea5e9' },
  review: { label: '待验收', color: '#a855f7' },
  blocked: { label: '阻塞', color: '#f59e0b' },
  done: { label: '完成', color: '#10b981' },
  completed: { label: '完成', color: '#10b981' },
  failed: { label: '失败', color: '#ef4444' },
  cancelled: { label: '取消', color: '#475569' },
}

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

export const KanbanPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [board, setBoard] = useState<Board | null>(null)
  const [health, setHealth] = useState<any>(null)
  const [inbox, setInbox] = useState<CollabItem[]>([])
  const [outbox, setOutbox] = useState<CollabItem[]>([])
  const [collabError, setCollabError] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<any>(null)
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newBody, setNewBody] = useState('')
  const [newAssignee, setNewAssignee] = useState('hm')
  const [msg, setMsg] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const h = await (await fetch('/api/kanban/health')).json()
      setHealth(h)
      if (h.reachable) setBoard(await (await fetch('/api/kanban/board')).json())
      try {
        const [i, o] = await Promise.all([
          (await fetch('/api/v1/inbox')).json(),
          (await fetch('/api/v1/outbox')).json(),
        ])
        setInbox(i.items || [])
        setOutbox(o.items || [])
        setCollabError('')
      } catch (e) {
        setCollabError(String(e))
      }
    } catch (e) {
      setMsg(`加载失败: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const move = async (id: string, status: string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
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
    const r = await fetch('/api/kanban/tasks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle, body: newBody, assignee: newAssignee, created_by: 'dashboard' }),
    })
    if (!r.ok) { setMsg(`建卡失败: ${(await r.json()).detail}`); return }
    setNewTitle(''); setNewBody(''); setShowNew(false); setMsg(''); load()
  }

  if (loading && !board) {
    return <div style={{ ...card, color: '#9ca3af', textAlign: 'center' }}>📋 正在载入任务卡...</div>
  }

  // 看板不可达时如实说明,不画一块空板子冒充"没有任务"
  if (health && !health.reachable) {
    return (
      <div style={{ ...card, borderColor: '#7f1d1d' }}>
        <div style={{ color: '#f87171', fontWeight: 700, marginBottom: 6 }}>⚠️ seohm 看板未接通</div>
        <div style={{ color: '#94a3b8', fontSize: 12 }}>{health.reason}</div>
        <div style={{ color: '#64748b', fontSize: 11, marginTop: 4 }}>路径: {health.path}</div>
      </div>
    )
  }

  const cols = board?.columns || {}
  const orderedOpen = ['pending', 'todo', 'in_progress', 'running', 'review', 'blocked']
  const orderedClosed = ['done', 'completed', 'failed', 'cancelled']

  const renderCard = (t: Task) => (
    <div
      key={t.id}
      onClick={() => openDetail(t.id)}
      style={{
        background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
        padding: '8px 10px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 4,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
        <span style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600, lineHeight: 1.35 }}>{t.title}</span>
        <span style={{
          flexShrink: 0, fontSize: 9, fontWeight: 700, borderRadius: 3, padding: '1px 5px', height: 'fit-content',
          background: t.priority <= 2 ? '#7f1d1d' : '#1e293b', color: t.priority <= 2 ? '#fca5a5' : '#64748b',
        }}>P{t.priority}</span>
      </div>
      {t.body && <div style={{ color: '#64748b', fontSize: 10, lineHeight: 1.4, maxHeight: 28, overflow: 'hidden' }}>{t.body}</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 9, color: '#475569' }}>
        <span>{t.assignee ? `👤 ${t.assignee}` : '未指派'}</span>
        <span>{t.created_at_iso || ''}</span>
      </div>
      {t.last_failure_error && (
        <div style={{ color: '#f87171', fontSize: 9 }}>✗ {t.last_failure_error.slice(0, 60)}</div>
      )}
      {t.is_open && (
        <div style={{ display: 'flex', gap: 4, marginTop: 2 }} onClick={(e) => e.stopPropagation()}>
          {t.status !== 'in_progress' && (
            <button onClick={() => move(t.id, 'in_progress')} style={miniBtn('#1e3a8a', '#93c5fd')}>开始</button>
          )}
          <button onClick={() => move(t.id, 'done')} style={miniBtn('#064e3b', '#6ee7b7')}>完成</button>
          <button onClick={() => move(t.id, 'blocked')} style={miniBtn('#78350f', '#fcd34d')}>阻塞</button>
        </div>
      )}
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 头部 */}
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#f3f4f6' }}>📋 任务卡 · Hermes 看板</div>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
            与 seohm 共用同一份卡 · 共 {board?.total ?? 0} 张,未关闭 {board?.open_count ?? 0} 张 · 源 {board?.source}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => setShowNew(!showNew)} style={btn('#2563eb')}>＋ 新建卡</button>
          <button onClick={load} style={btn('#334155')}>↻ 刷新</button>
        </div>
      </div>

      {msg && <div style={{ ...card, borderColor: '#7f1d1d', color: '#f87171', fontSize: 12 }}>{msg}</div>}

      {showNew && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input placeholder="任务标题" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} style={input} />
          <textarea placeholder="任务描述(可选)" value={newBody} onChange={(e) => setNewBody(e.target.value)} rows={2} style={{ ...input, resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input placeholder="指派给" value={newAssignee} onChange={(e) => setNewAssignee(e.target.value)} style={{ ...input, width: 140 }} />
            <button onClick={create} disabled={!newTitle.trim()} style={btn(newTitle.trim() ? '#2563eb' : '#334155')}>创建</button>
          </div>
        </div>
      )}

      {/* 看板列 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
        {orderedOpen.map((st) => {
          const items = cols[st] || []
          const meta = COL_META[st] || { label: st, color: '#64748b' }
          if (items.length === 0 && st === 'todo') return null
          return (
            <div key={st} style={{ ...card, padding: 10, display: 'flex', flexDirection: 'column', gap: 6, minHeight: 120 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: meta.color }}>● {meta.label}</span>
                <span style={{ fontSize: 10, color: '#475569' }}>{items.length}</span>
              </div>
              {items.length === 0
                ? <div style={{ color: '#334155', fontSize: 10, textAlign: 'center', padding: '16px 0' }}>空</div>
                : items.map(renderCard)}
            </div>
          )
        })}
      </div>

      {/* 已关闭 */}
      <details style={card}>
        <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#94a3b8' }}>
          已关闭 ({orderedClosed.reduce((n, s) => n + (cols[s] || []).length, 0)})
        </summary>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginTop: 8 }}>
          {orderedClosed.flatMap((s) => (cols[s] || []).map(renderCard))}
        </div>
      </details>

      {/* 跨部门协作单 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
        {[['📥 收件箱 · 别的部门派给 SEO', inbox], ['📤 发件箱 · SEO 派出去的', outbox]].map(([title, items]: any) => (
          <div key={title} style={card}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', marginBottom: 6 }}>
              {title} <span style={{ color: '#475569', fontWeight: 400 }}>({items.length})</span>
            </div>
            {collabError && <div style={{ color: '#f87171', fontSize: 11 }}>协作服务不可用: {collabError}</div>}
            {!collabError && items.length === 0 && (
              <div style={{ color: '#475569', fontSize: 11, padding: '10px 0' }}>暂无协作单</div>
            )}
            {items.map((it: any, i: number) => (
              <div key={i} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '6px 8px', marginBottom: 5, fontSize: 11 }}>
                <div style={{ color: '#e2e8f0' }}>{it.capability || it.title || it.request_id}</div>
                <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
                  {it.from?.dept || it.to?.dept || '—'} · {it.status || '—'} · {it.due_at || ''}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 详情弹窗 */}
      {detail && (
        <div onClick={() => setDetail(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: '100%', maxWidth: 640, maxHeight: '85vh', overflowY: 'auto' }}>
            {detail.error ? (
              <div style={{ color: '#f87171' }}>{detail.error}</div>
            ) : (
              <>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>{detail.title}</div>
                <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                  {detail.id} · {detail.status} · P{detail.priority} · 👤{detail.assignee || '未指派'} · 建于 {detail.created_at_iso}
                </div>
                {detail.body && <div style={{ color: '#cbd5e1', fontSize: 12, marginTop: 10, whiteSpace: 'pre-wrap' }}>{detail.body}</div>}
                {(detail.runs || []).length > 0 && (
                  <>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginTop: 12 }}>执行记录</div>
                    {detail.runs.map((r: any) => (
                      <div key={r.id} style={{ background: '#0f172a', borderRadius: 6, padding: 6, marginTop: 4, fontSize: 10, color: '#cbd5e1' }}>
                        #{r.id} {r.step_key} · {r.status} {r.error && <span style={{ color: '#f87171' }}>✗ {r.error}</span>}
                        {r.summary && <div style={{ color: '#64748b' }}>{r.summary}</div>}
                      </div>
                    ))}
                  </>
                )}
                {(detail.comments || []).length > 0 && (
                  <>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginTop: 12 }}>评论</div>
                    {detail.comments.map((c: any) => (
                      <div key={c.id} style={{ background: '#0f172a', borderRadius: 6, padding: 6, marginTop: 4, fontSize: 11, color: '#cbd5e1' }}>
                        <span style={{ color: '#60a5fa' }}>{c.author}</span>: {c.body}
                      </div>
                    ))}
                  </>
                )}
                {(detail.events || []).length > 0 && (
                  <details style={{ marginTop: 12 }}>
                    <summary style={{ cursor: 'pointer', fontSize: 11, color: '#64748b' }}>事件轨迹 ({detail.events.length})</summary>
                    {detail.events.map((e: any) => (
                      <div key={e.id} style={{ fontSize: 10, color: '#475569', marginTop: 3, fontFamily: 'monospace' }}>
                        {e.kind} · {e.payload}
                      </div>
                    ))}
                  </details>
                )}
                <button onClick={() => setDetail(null)} style={{ ...btn('#334155'), marginTop: 14 }}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
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
  color: '#e2e8f0', fontSize: 12, padding: '6px 8px', boxSizing: 'border-box', width: '100%',
}

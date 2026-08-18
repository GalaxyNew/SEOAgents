import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, Field, inputStyle, btn } from '../ui'

/**
 * 部门目录 —— 管的是「我认识哪些别的部门实例」。
 *
 * 本实例自己代表哪个部门由 config.collab 决定,不在这里改。
 * 能力清单一律从对方 /api/v1/capabilities 拉,不给手填:让人敲一串能力名
 * 等于允许「声称对方能做某事」,工作流据此派活,到时候会失败得莫名其妙。
 *
 * 新建与编辑都走弹窗 —— 全站统一,不在页面上内联表单。
 */

type Dept = {
  id: string
  display_name: string
  endpoint: string
  description: string
  enabled: boolean
  reachable?: boolean
  reason?: string
  capabilities?: string[]
  latency_ms?: number
  last_probe_at?: number
}

type SelfInfo = { dept: string; display_name: string; endpoint: string; note: string }

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 10, padding: '12px 14px',
}

const fmtTime = (ts?: number) =>
  ts ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'

const EMPTY = { id: '', display_name: '', endpoint: '', description: '' }

export const DepartmentPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [self, setSelf] = useState<SelfInfo | null>(null)
  const [items, setItems] = useState<Dept[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [probing, setProbing] = useState<string | null>(null)

  const [editing, setEditing] = useState<Dept | null>(null)   // null = 未打开
  const [isNew, setIsNew] = useState(false)
  const [form, setForm] = useState({ ...EMPTY })
  const [saving, setSaving] = useState(false)
  const [confirmDel, setConfirmDel] = useState<Dept | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const d = await (await fetch('/api/departments')).json()
      setSelf(d.self || null)
      setItems(d.items || [])
    } catch (e) {
      setMsg(`加载失败: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openNew = () => {
    setForm({ ...EMPTY }); setIsNew(true)
    setEditing({ ...EMPTY, enabled: true } as Dept)
  }

  const openEdit = (d: Dept) => {
    setForm({ id: d.id, display_name: d.display_name, endpoint: d.endpoint, description: d.description || '' })
    setIsNew(false); setEditing(d)
  }

  const save = async () => {
    if (!form.id.trim()) return
    setSaving(true)
    try {
      const r = isNew
        ? await fetch('/api/departments', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              id: form.id.trim(), display_name: form.display_name.trim(),
              endpoint: form.endpoint.trim(), description: form.description.trim(),
            }),
          })
        : await fetch(`/api/departments/${form.id}`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              display_name: form.display_name.trim(),
              endpoint: form.endpoint.trim(), description: form.description.trim(),
            }),
          })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { setMsg(`${isNew ? '新增' : '保存'}失败: ${j.detail || r.status}`); return }
      setMsg(''); setEditing(null); load()
    } finally { setSaving(false) }
  }

  const probe = async (id: string) => {
    setProbing(id)
    try {
      const r = await fetch(`/api/departments/${id}/probe`, { method: 'POST' })
      if (!r.ok) setMsg(`探测失败: ${(await r.json().catch(() => ({}))).detail || r.status}`)
      else setMsg('')
      load()
    } finally { setProbing(null) }
  }

  const probeAll = async () => {
    setProbing('*')
    try { await fetch('/api/departments/probe-all', { method: 'POST' }); load() }
    finally { setProbing(null) }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    const r = await fetch(`/api/departments/${confirmDel.id}`, { method: 'DELETE' })
    if (!r.ok) setMsg(`删除失败: ${(await r.json().catch(() => ({}))).detail}`)
    setConfirmDel(null); load()
  }

  const toggle = async (d: Dept) => {
    await fetch(`/api/departments/${d.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !d.enabled }),
    })
    load()
  }

  if (loading) {
    return <div style={{ ...card, color: 'var(--dim)', textAlign: 'center' }}>🏢 正在载入部门目录…</div>
  }

  const reachable = items.filter((d) => d.reachable).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ ...card, borderColor: 'var(--accent-soft)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)' }}>
              🏠 本实例 · {self?.display_name}
              <span style={{ color: 'var(--border)', fontWeight: 400 }}> ({self?.dept})</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--faint)', marginTop: 3, fontFamily: 'monospace' }}>
              对外端点: {self?.endpoint}
            </div>
            <div style={{ fontSize: 10, color: 'var(--border)', marginTop: 2 }}>{self?.note}</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={openNew} style={btn('var(--accent2)')}>＋ 新建部门</button>
            <button onClick={probeAll} disabled={probing === '*' || items.length === 0}
              style={btn('var(--border)')}>{probing === '*' ? '探测中…' : '↻ 全部探测'}</button>
          </div>
        </div>
      </div>

      {msg && <div style={{ ...card, borderColor: 'var(--bad-soft)', color: 'var(--bad)', fontSize: 11 }}>{msg}</div>}

      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
          🏢 已知部门 ({items.length})
          {items.length > 0 && (
            <span style={{ fontWeight: 400, color: reachable === items.length ? 'var(--ok)' : 'var(--warn)', marginLeft: 8 }}>
              {reachable}/{items.length} 可达
            </span>
          )}
        </div>

        {items.length === 0 ? (
          <div style={{ color: 'var(--border)', fontSize: 11, padding: '16px 0', textAlign: 'center', lineHeight: 1.7 }}>
            还没有登记任何其他部门。<br />
            工作流里的跨部门节点(如向 <code style={{ color: 'var(--rev)' }}>intel</code> 要配图)
            会因为找不到对方而无法执行。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {items.map((d) => (
              <div key={d.id} style={{
                background: 'var(--surface)',
                border: `1px solid ${d.reachable ? 'var(--ok-soft)' : 'var(--bad-soft)'}`,
                borderLeft: `3px solid ${d.reachable ? 'var(--ok)' : 'var(--bad)'}`,
                borderRadius: 8, padding: '9px 11px', opacity: d.enabled ? 1 : 0.5,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                      {d.display_name || d.id}
                      <span style={{ color: 'var(--border)', fontWeight: 400, marginLeft: 6, fontFamily: 'monospace' }}>{d.id}</span>
                      {!d.enabled && <span style={{ color: 'var(--warn)', fontSize: 10, marginLeft: 6 }}>已停用</span>}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--faint)', fontFamily: 'monospace', marginTop: 2, wordBreak: 'break-all' }}>
                      {d.endpoint || '(未配置端点)'}
                    </div>
                    {d.description && <div style={{ fontSize: 10, color: 'var(--dim)', marginTop: 3 }}>{d.description}</div>}
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                    <button onClick={() => probe(d.id)} disabled={probing === d.id} style={btn('var(--border)')}>
                      {probing === d.id ? '…' : '探测'}
                    </button>
                    <button onClick={() => openEdit(d)} style={btn('var(--border)')}>编辑</button>
                    <button onClick={() => toggle(d)} style={btn('var(--border)')}>{d.enabled ? '停用' : '启用'}</button>
                    <button onClick={() => setConfirmDel(d)} style={btn('var(--bad-soft)')}>删除</button>
                  </div>
                </div>

                <div style={{ marginTop: 7, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: d.reachable ? 'var(--ok)' : 'var(--bad)' }}>
                    {d.reachable ? `● 可达 ${d.latency_ms ?? '?'}ms` : '● 不可达'}
                  </span>
                  {!d.reachable && d.reason && <span style={{ fontSize: 10, color: 'var(--bad)' }}>{d.reason}</span>}
                  <span style={{ fontSize: 10, color: 'var(--border)' }}>探测于 {fmtTime(d.last_probe_at)}</span>
                </div>

                {d.reachable && (
                  <div style={{ marginTop: 5 }}>
                    <span style={{ fontSize: 10, color: 'var(--faint)' }}>对方声明的能力: </span>
                    {(d.capabilities || []).length === 0 ? (
                      <span style={{ fontSize: 10, color: 'var(--warn)' }}>未声明任何能力 —— 无法承接跨部门节点</span>
                    ) : (
                      (d.capabilities || []).map((c) => (
                        <span key={c} style={{
                          background: 'var(--panel)', color: 'var(--rev)', borderRadius: 3,
                          padding: '1px 6px', fontSize: 9, marginRight: 4, display: 'inline-block',
                        }}>{c}</span>
                      ))
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 新建 / 编辑 */}
      <Modal
        open={!!editing}
        title={isNew ? '新建部门' : `编辑 ${form.display_name || form.id}`}
        subtitle="对方必须是独立部署的实例,能响应 /api/v1/capabilities;能力清单自动拉取,无需手填"
        onClose={() => setEditing(null)}
        footer={
          <>
            <button onClick={() => setEditing(null)} style={btn('var(--border)')}>取消</button>
            <button onClick={save} disabled={!form.id.trim() || saving}
              style={btn(form.id.trim() && !saving ? 'var(--accent2)' : 'var(--border)')}>
              {saving ? '保存中…' : isNew ? '创建并探测' : '保存'}
            </button>
          </>
        }
      >
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
          <Field label="部门标识" hint={isNew ? '创建后不可修改,如 intel' : '不可修改'}>
            <input value={form.id} disabled={!isNew}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              placeholder="intel"
              style={{ ...inputStyle, opacity: isNew ? 1 : 0.5 }} />
          </Field>
          <Field label="显示名">
            <input value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              placeholder="情报部" style={inputStyle} />
          </Field>
        </div>
        <Field label="端点" hint="对方实例的 HTTP 根地址,保存后会立即探测连通性">
          <input value={form.endpoint}
            onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
            placeholder="http://10.0.0.5:8765" style={inputStyle} />
        </Field>
        <Field label="说明">
          <input value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="配图与素材采集" style={inputStyle} />
        </Field>
      </Modal>

      {/* 删除确认 */}
      <Modal
        open={!!confirmDel}
        title="删除部门"
        width={420}
        onClose={() => setConfirmDel(null)}
        footer={
          <>
            <button onClick={() => setConfirmDel(null)} style={btn('var(--border)')}>取消</button>
            <button onClick={doDelete} style={btn('var(--bad)')}>确认删除</button>
          </>
        }
      >
        <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.7 }}>
          确定删除 <strong style={{ color: 'var(--text)' }}>{confirmDel?.display_name || confirmDel?.id}</strong> 吗?
          <div style={{ color: 'var(--warn)', fontSize: 11, marginTop: 8 }}>
            引用了该部门的工作流节点会因为找不到对方而无法执行。
            只是暂时不用的话,建议用「停用」而不是删除。
          </div>
        </div>
      </Modal>
    </div>
  )
}

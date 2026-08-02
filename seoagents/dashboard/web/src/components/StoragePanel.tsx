import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, Field, inputStyle, btn } from '../ui'

/**
 * 中央存储与资产台账。
 *
 * 三块内容对应三个问题:节点(东西存在哪)、配额(还剩多少免费额度)、
 * 台账(谁产出的、能不能回滚)。
 *
 * 界面上刻意不提供「改 level」的入口。声明是 L3 就得按 L3 交付 —— 经验库里
 * 那条 `2026-07-21 终验擅自降低已声明资产类别` 的原案,就是在终验环节把
 * L3 改成 L2 混过去的。门禁做在数据库,界面也不给这个念头留口子。
 *
 * L3 的备份不需要人填:提交时系统会真的镜像到第二个节点,拿实际落点当
 * backup_location。填不出来的资产,压根登记不进来。
 */

type Node = {
  id: string; label: string; kind: string; bucket: string
  enabled: boolean; default: boolean; writable: boolean
  block_reason: string; quota: Record<string, number>
  ratios: Record<string, number>
}

type QuotaNode = {
  node: string; label: string; writable: boolean
  usage: Record<string, number>; ratios: Record<string, number>
  forecast: Record<string, number>; confidence: string; warnings: string[]
  quota: Record<string, number>
}

type Asset = {
  asset_id: string; name: string; class: string; level: string; status: string
  task_id: string; owner_department: string; owner_agent: string
  location: string; storage_node: string; backup_location: string | null
  rollback: string | null; review_cycle: string | null
  summary: string; usage: string; source_evidence: string
  checksum: string | null; size_bytes: number | null
  created_at: string; verified_at: string | null; verified_by: string | null
  data_status: string
}

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

const LEVEL_COLOR: Record<string, string> = {
  L0: '#6b7280', L1: '#3b82f6', L2: '#f59e0b', L3: '#ef4444',
}
const LEVEL_HINT: Record<string, string> = {
  L0: '临时草稿,可随时丢弃',
  L1: '一般产出,丢了要重做但不致命',
  L2: '重要产出,丢了影响业务连续性',
  L3: '核心生产资产,必须有异地备份与回滚方案',
}

const gb = (b: number) => `${(b / 1024 ** 3).toFixed(2)}GB`
const pct = (r?: number) => (r == null ? '—' : `${(r * 100).toFixed(1)}%`)

const EMPTY = {
  name: '', content: '', dept: 'shared', kind: 'misc', level: 'L1',
  asset_class: 'DOC', task_id: '', owner_agent: '', summary: '', usage: '',
  source_evidence: '', node_id: '',
}

export const StoragePanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [nodes, setNodes] = useState<Node[]>([])
  const [quota, setQuota] = useState<QuotaNode[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [stats, setStats] = useState<Record<string, unknown>>({})
  const [levelFilter, setLevelFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ ...EMPTY })
  const [detail, setDetail] = useState<Asset | null>(null)
  const [note, setNote] = useState('')

  const load = async () => {
    setBusy(true); setErr('')
    try {
      const q = levelFilter ? `?level=${levelFilter}` : ''
      const [n, qu, a] = await Promise.all([
        fetch('/api/storage/nodes').then(r => r.json()),
        fetch('/api/storage/quota').then(r => r.json()),
        fetch(`/api/storage/assets${q}`).then(r => r.json()),
      ])
      setNodes(n.nodes || [])
      setQuota(qu.nodes || [])
      setAssets(a.assets || [])
      setStats(a.stats || {})
    } catch (e) {
      setErr(`加载失败: ${e}`)
    } finally { setBusy(false) }
  }

  useEffect(() => { void load() }, [levelFilter])

  const submit = async () => {
    setBusy(true); setNote('')
    try {
      const res = await fetch('/api/storage/assets', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const body = await res.json()
      if (!res.ok) {
        // 后端把 L3 门禁的拒绝理由放在 detail.message,原样呈现 ——
        // 换成「保存失败」这类泛泛提示,人就不知道该补什么。
        const d = body?.detail
        setNote(`✗ ${typeof d === 'object' ? `[${d.code}] ${d.message}` : (d || '提交失败')}`)
        return
      }
      setNote(
        `✓ ${body.asset_id} 已登记` +
        (body.backup ? ` · 已镜像到 ${body.backup.split(':')[0]}` : ''),
      )
      setCreating(false); setForm({ ...EMPTY }); await load()
    } catch (e) {
      setNote(`✗ ${e}`)
    } finally { setBusy(false) }
  }

  const verify = async (id: string) => {
    const res = await fetch(`/api/storage/assets/${id}/verify`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verified_by: 'hm' }),
    })
    const b = await res.json()
    setNote(res.ok ? `✓ ${id} 已通过终验` : `✗ ${b?.detail?.message || '终验被拒'}`)
    await load()
  }

  const drill = async (id: string) => {
    setNote('演练中…')
    const res = await fetch(`/api/storage/assets/${id}/restore`, { method: 'POST' })
    const b = await res.json()
    setNote(res.ok
      ? `✓ 回滚演练成功:从 ${b.restored_from} 恢复 ${b.size}B 到 ${b.to_node}`
      : `✗ ${b?.detail?.message || b?.detail || '恢复失败'}`)
  }

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {err && <div style={{ ...card, borderColor: '#7f1d1d', color: '#fca5a5' }}>{err}</div>}

      {/* 节点与配额 */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>存储节点</h3>
          <button style={btn('#1f2937')} onClick={() => void load()} disabled={busy}>
            {busy ? '刷新中…' : '刷新'}
          </button>
        </div>
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit,minmax(260px,1fr))' }}>
          {nodes.map(n => {
            const q = quota.find(x => x.node === n.id)
            const used = q?.usage?.bytes_stored ?? 0
            const limit = (n.quota?.storage_gb || 0) * 1024 ** 3
            const ratio = limit ? used / limit : 0
            return (
              <div key={n.id} style={{ ...card, borderColor: n.writable ? '#1f2937' : '#7f1d1d' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <strong>{n.label || n.id}</strong>
                  <span style={{ fontSize: 11, color: '#6b7280' }}>
                    {n.kind}{n.default ? ' · 默认' : ''}
                  </span>
                </div>
                <div style={{ margin: '8px 0 4px', height: 6, background: '#1f2937', borderRadius: 3 }}>
                  <div style={{
                    width: `${Math.min(100, ratio * 100)}%`, height: '100%', borderRadius: 3,
                    background: ratio > 0.9 ? '#ef4444' : ratio > 0.7 ? '#f59e0b' : '#22c55e',
                  }} />
                </div>
                <div style={{ fontSize: 12, color: '#9ca3af' }}>
                  {gb(used)} / {n.quota?.storage_gb ?? '?'}GB（{pct(ratio)}）
                </div>
                {!n.writable && (
                  <div style={{ fontSize: 11, color: '#fca5a5', marginTop: 6 }}>只读:{n.block_reason}</div>
                )}
                {q?.warnings?.map((w, i) => (
                  <div key={i} style={{ fontSize: 11, color: '#fbbf24', marginTop: 6 }}>⚠ {w}</div>
                ))}
                {q && !q.warnings?.length && (
                  <div style={{ fontSize: 11, color: '#6b7280', marginTop: 6 }}>
                    月底预估 {gb(q.forecast?.bytes_stored ?? 0)}
                    <span title="当月天数太少时线性外推不可靠"> · 置信 {q.confidence}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* 资产台账 */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>
            资产台账
            <span style={{ fontSize: 12, color: '#6b7280', fontWeight: 400, marginLeft: 8 }}>
              共 {String(stats.total ?? 0)} 项
              {Number(stats.unverified_l3 ?? 0) > 0 && (
                <span style={{ color: '#fbbf24' }}> · {String(stats.unverified_l3)} 项 L3 待终验</span>
              )}
            </span>
          </h3>
          <div style={{ display: 'flex', gap: 6 }}>
            <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)} style={{ ...inputStyle, width: 120 }}>
              <option value="">全部等级</option>
              {['L0', 'L1', 'L2', 'L3'].map(l => <option key={l} value={l}>{l}</option>)}
            </select>
            <button style={btn('#2563eb')} onClick={() => { setNote(''); setCreating(true) }}>登记资产</button>
          </div>
        </div>

        {note && (
          <div style={{ ...card, marginBottom: 8, borderColor: note.startsWith('✓') ? '#14532d' : '#7f1d1d',
                        color: note.startsWith('✓') ? '#86efac' : '#fca5a5', fontSize: 13 }}>
            {note}
          </div>
        )}

        <div style={{ display: 'grid', gap: 8 }}>
          {assets.length === 0 && (
            <div style={{ ...card, color: '#6b7280', fontSize: 13 }}>
              还没有登记任何资产。产出物登记后才有「在哪、谁的、怎么回滚」的答案。
            </div>
          )}
          {assets.map(a => (
            <div key={a.asset_id} style={{ ...card, cursor: 'pointer' }} onClick={() => setDetail(a)}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{
                  background: LEVEL_COLOR[a.level], color: '#fff', fontSize: 11,
                  padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                }} title={LEVEL_HINT[a.level]}>{a.level}</span>
                <strong style={{ fontSize: 14 }}>{a.name}</strong>
                <span style={{ fontSize: 11, color: '#6b7280' }}>{a.asset_id}</span>
                <span style={{ fontSize: 11, color: a.verified_at ? '#22c55e' : '#6b7280', marginLeft: 'auto' }}>
                  {a.verified_at ? `已验 · ${a.verified_by}` : a.status}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>{a.summary}</div>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                {a.storage_node || a.location.split(':')[0]}:{a.location}
                {a.backup_location && <span style={{ color: '#22c55e' }}> · 备份 {a.backup_location.split(':')[0]}</span>}
                {a.level === 'L3' && !a.backup_location && <span style={{ color: '#ef4444' }}> · 无备份(异常)</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 登记弹窗 */}
      {creating && (
        <Modal open title="登记资产" onClose={() => setCreating(false)} width={620}>
          <div style={{ display: 'grid', gap: 10 }}>
            <Field label="名称"><input style={inputStyle} value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })} placeholder="seo-monthly-report.md" /></Field>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr' }}>
              <Field label="等级" hint={LEVEL_HINT[form.level]}>
                <select style={inputStyle} value={form.level}
                  onChange={e => setForm({ ...form, level: e.target.value })}>
                  {['L0', 'L1', 'L2', 'L3'].map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </Field>
              <Field label="类别">
                <select style={inputStyle} value={form.asset_class}
                  onChange={e => setForm({ ...form, asset_class: e.target.value })}>
                  {['DOC', 'CODE', 'DATA', 'MEDIA', 'PROMPT', 'AUTO', 'INFRA', 'MODEL', 'BIZ']
                    .map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
            </div>
            {form.level === 'L3' && (
              <div style={{ ...card, borderColor: '#78350f', background: '#1c1917', fontSize: 12, color: '#fbbf24' }}>
                L3 会自动镜像到第二个存储节点,备份位置与回滚方案由系统按实际落点填写。
                若当时没有第二个可写节点,登记会被拒绝而不是先记上、备份以后再补。
              </div>
            )}
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr' }}>
              <Field label="部门"><input style={inputStyle} value={form.dept}
                onChange={e => setForm({ ...form, dept: e.target.value })} /></Field>
              <Field label="用途分区">
                <select style={inputStyle} value={form.kind}
                  onChange={e => setForm({ ...form, kind: e.target.value })}>
                  {['report', 'content', 'image', 'dataset', 'backup', 'skill', 'misc']
                    .map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </Field>
              <Field label="指定节点" hint="留空按用途自动路由">
                <select style={inputStyle} value={form.node_id}
                  onChange={e => setForm({ ...form, node_id: e.target.value })}>
                  <option value="">自动</option>
                  {nodes.filter(n => n.writable).map(n => <option key={n.id} value={n.id}>{n.label || n.id}</option>)}
                </select>
              </Field>
            </div>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr' }}>
              <Field label="任务号"><input style={inputStyle} value={form.task_id}
                onChange={e => setForm({ ...form, task_id: e.target.value })} placeholder="T-44" /></Field>
              <Field label="产出 agent"><input style={inputStyle} value={form.owner_agent}
                onChange={e => setForm({ ...form, owner_agent: e.target.value })} placeholder="seo-analyst" /></Field>
            </div>
            <Field label="摘要"><input style={inputStyle} value={form.summary}
              onChange={e => setForm({ ...form, summary: e.target.value })} placeholder="这份东西是什么" /></Field>
            <Field label="用途"><input style={inputStyle} value={form.usage}
              onChange={e => setForm({ ...form, usage: e.target.value })} placeholder="谁会来读它、拿它做什么" /></Field>
            <Field label="来源证据" hint="数据是怎么来的。写不出来的资产不该登记 —— 那意味着没人能验证它">
              <input style={inputStyle} value={form.source_evidence}
                onChange={e => setForm({ ...form, source_evidence: e.target.value })}
                placeholder="GSC 2026-07 导出 + DataForSEO 实测" /></Field>
            <Field label="内容">
              <textarea style={{ ...inputStyle, minHeight: 120, fontFamily: 'ui-monospace,monospace' }}
                value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} />
            </Field>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={btn('#374151')} onClick={() => setCreating(false)}>取消</button>
              <button style={btn('#2563eb')} onClick={() => void submit()}
                disabled={busy || !form.name || !form.summary || !form.source_evidence}>
                {busy ? '提交中…' : '登记'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* 详情弹窗 */}
      {detail && (
        <Modal open title={detail.name} onClose={() => setDetail(null)} width={640}>
          <div style={{ display: 'grid', gap: 8, fontSize: 13 }}>
            {([
              ['资产号', detail.asset_id], ['等级', `${detail.level} — ${LEVEL_HINT[detail.level]}`],
              ['类别 / 状态', `${detail.class} / ${detail.status}`],
              ['归属', `${detail.owner_department} · ${detail.owner_agent}`],
              ['任务号', detail.task_id], ['位置', `${detail.storage_node || ''} ${detail.location}`],
              ['备份位置', detail.backup_location || '—'],
              ['回滚方案', detail.rollback || '—'],
              ['复核周期', detail.review_cycle || '—'],
              ['校验和', detail.checksum || '—'],
              ['数据状态', detail.data_status],
              ['来源证据', detail.source_evidence],
              ['用途', detail.usage],
              ['创建时间', detail.created_at],
              ['终验', detail.verified_at ? `${detail.verified_at} by ${detail.verified_by}` : '未终验'],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '92px 1fr', gap: 8 }}>
                <span style={{ color: '#6b7280' }}>{k}</span>
                <span style={{ wordBreak: 'break-all' }}>{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
              {detail.backup_location && (
                <button style={btn('#7c2d12')} onClick={() => void drill(detail.asset_id)}
                  title="从备份节点恢复到主节点。写下来没跑过的回滚步骤,出事那天就是第一次跑">
                  回滚演练
                </button>
              )}
              {!detail.verified_at && (
                <button style={btn('#15803d')} onClick={() => void verify(detail.asset_id)}>通过终验</button>
              )}
              <button style={btn('#374151')} onClick={() => setDetail(null)}>关闭</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

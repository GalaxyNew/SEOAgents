import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { WorkflowEditor } from './WorkflowEditor'

/**
 * 工作流中心 —— 模板库、节点流程图、运行实例看板。
 * 全部数据来自 /api/workflows/*。
 */

type Template = {
  id: string
  name: string
  version: string
  dept: string
  description: string
  node_count: number
  layer_count: number
  max_parallel: number
  external_deps: Array<{ node: string; dept: string; capability: string }>
  human_gates: string[]
  tags: string[]
}

type NodeType = {
  id: string
  label: string
  required_config: string[]
  hint: string
  runs_externally: boolean
  acceptance_required: boolean
}

type Instance = Record<string, any>

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

const NODE_COLOR: Record<string, string> = {
  agent_task: '#3b82f6',
  tool_call: '#10b981',
  dept_request: '#a855f7',
  human_gate: '#f59e0b',
}

const STATE_COLOR: Record<string, string> = {
  pending: '#64748b', ready: '#38bdf8', running: '#3b82f6', in_progress: '#3b82f6',
  done: '#10b981', completed: '#10b981', failed: '#ef4444', blocked: '#f59e0b',
  waiting: '#a855f7', cancelled: '#475569',
}

export const WorkflowPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [templates, setTemplates] = useState<Template[]>([])
  const [nodeTypes, setNodeTypes] = useState<NodeType[]>([])
  const [departments, setDepartments] = useState<any[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [detail, setDetail] = useState<any>(null)
  const [tplDetail, setTplDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [showEditor, setShowEditor] = useState(false)
  const [tools, setTools] = useState<string[]>([])
  const [deptIds, setDeptIds] = useState<string[]>([])

  const load = async () => {
    setLoading(true); setErr('')
    try {
      const [t, nt, d, ins] = await Promise.all([
        (await fetch('/api/workflows/templates')).json(),
        (await fetch('/api/workflows/node-types')).json(),
        (await fetch('/api/workflows/departments')).json(),
        (await fetch('/api/workflows/instances')).json(),
      ])
      setTemplates(t.templates || [])
      setNodeTypes(nt.types || [])
      setDepartments(d.departments || [])
      setInstances(ins.items || [])
      // 节点编辑要选具体工具与目标部门,两者都从真实注册表取,不写死
      try {
        const cfg = await (await fetch('/api/config')).json()
        setTools((cfg?.resolved?.tools as string[]) || [])
      } catch { setTools([]) }
      try {
        const dp = await (await fetch('/api/departments')).json()
        setDeptIds((dp?.items || []).filter((x: any) => x.enabled).map((x: any) => x.id))
      } catch { setDeptIds([]) }
    } catch (e) {
      setErr(`工作流服务不可用: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openTemplate = async (id: string) => {
    const r = await fetch(`/api/workflows/templates/${id}`)
    const j = await r.json()
    setTplDetail(r.ok ? j : { error: j.detail || '模板读取失败' })
  }

  const openInstance = async (id: string) => {
    const r = await fetch(`/api/workflows/instances/${id}`)
    const j = await r.json()
    setDetail(r.ok ? j : { error: j.detail || '实例读取失败' })
  }

  const startInstance = async (templateId: string) => {
    const r = await fetch('/api/workflows/instances', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setMsg(`创建实例失败: ${j.detail || r.status}`); return }
    setMsg(`已创建实例 ${j.instance_id || ''}`); load()
  }

  const nodeAction = async (instId: string, nodeId: string, action: string) => {
    const r = await fetch(`/api/workflows/instances/${instId}/nodes/${nodeId}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(action === 'fail' ? { reason: '面板手动标记失败' } : {}),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setMsg(`${action} 失败: ${j.detail || r.status}`); return }
    setMsg(`节点 ${nodeId} 已${action}`)
    openInstance(instId); load()
  }

  if (loading) return <div style={{ ...card, color: '#9ca3af', textAlign: 'center' }}>⚙️ 正在载入工作流...</div>
  if (err) return <div style={{ ...card, borderColor: '#7f1d1d', color: '#f87171' }}>⚠️ {err}</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        {[
          ['📐 模板', templates.length, '#60a5fa'],
          ['▶ 运行实例', instances.length, '#10b981'],
          ['🧩 节点类型', nodeTypes.length, '#a855f7'],
          ['🏢 已注册部门', departments.length, departments.length ? '#e2e8f0' : '#f59e0b'],
        ].map(([label, val, color]: any) => (
          <div key={label} style={card}>
            <div style={{ fontSize: 10, color: '#64748b' }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color }}>{val}</div>
          </div>
        ))}
      </div>

      {msg && <div style={{ ...card, fontSize: 11, color: msg.includes('失败') ? '#f87171' : '#6ee7b7' }}>{msg}</div>}

      {/* 节点类型图例 */}
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', marginBottom: 8 }}>🧩 节点类型</div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(230px, 1fr))', gap: 8 }}>
          {nodeTypes.map((nt) => (
            <div key={nt.id} style={{ background: '#0f172a', border: `1px solid ${NODE_COLOR[nt.id] || '#1e293b'}`, borderRadius: 6, padding: '7px 9px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: NODE_COLOR[nt.id] || '#e2e8f0', fontSize: 11, fontWeight: 700 }}>{nt.label}</span>
                <span style={{ fontSize: 9, color: '#475569' }}>
                  {nt.runs_externally ? '跨部门' : '本部门'}{nt.acceptance_required ? ' · 需验收' : ''}
                </span>
              </div>
              <div style={{ fontSize: 9, color: '#64748b', marginTop: 3 }}>{nt.hint}</div>
              <div style={{ fontSize: 9, color: '#475569', marginTop: 2, fontFamily: 'monospace' }}>
                必填: {nt.required_config.join(', ')}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 模板库 */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6' }}>📐 模板库 ({templates.length})</span>
          <button onClick={() => setShowEditor(true)} style={btn('#2563eb')}>＋ 新建模板</button>
        </div>
        {templates.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 11, textAlign: 'center', padding: '18px 0', lineHeight: 1.9 }}>
            还没有工作流模板<br />
            <button onClick={() => setShowEditor(true)} style={{ ...btn('#2563eb'), marginTop: 6 }}>
              ＋ 建第一个
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8 }}>
            {templates.map((t) => (
              <div key={t.id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '9px 11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
                  <div>
                    <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 700 }}>{t.name}</div>
                    <div style={{ color: '#475569', fontSize: 9, fontFamily: 'monospace' }}>{t.id} · v{t.version} · {t.dept}</div>
                  </div>
                  <span style={{ flexShrink: 0, background: '#1e293b', color: '#60a5fa', borderRadius: 3, padding: '1px 5px', fontSize: 9 }}>
                    {t.node_count} 节点
                  </span>
                </div>
                <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 5, lineHeight: 1.4 }}>{t.description}</div>
                <div style={{ display: 'flex', gap: 10, marginTop: 6, fontSize: 9, color: '#64748b', flexWrap: 'wrap' }}>
                  <span>📊 {t.layer_count} 层</span>
                  <span>⇉ 并行 {t.max_parallel}</span>
                  {t.human_gates.length > 0 && <span style={{ color: '#f59e0b' }}>🚦 {t.human_gates.length} 个人工闸门</span>}
                  {t.external_deps.length > 0 && <span style={{ color: '#a855f7' }}>🔗 {t.external_deps.length} 个跨部门依赖</span>}
                </div>
                {t.external_deps.map((d, i) => (
                  <div key={i} style={{ fontSize: 9, color: '#a855f7', marginTop: 3, fontFamily: 'monospace' }}>
                    ↗ {d.node} → {d.dept}.{d.capability}
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 5, marginTop: 8 }}>
                  <button onClick={() => openTemplate(t.id)} style={btn('#334155')}>查看流程</button>
                  <button onClick={() => startInstance(t.id)} style={btn('#2563eb')}>▶ 起一个实例</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 实例看板 */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6' }}>▶ 运行实例 ({instances.length})</span>
          <button onClick={load} style={btn('#334155')}>↻ 刷新</button>
        </div>
        {instances.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 11, textAlign: 'center', padding: '14px 0' }}>
            当前没有运行中的工作流实例 —— 上面挑个模板起一个
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {instances.map((ins) => (
              <div key={ins.instance_id || ins.id} onClick={() => openInstance(ins.instance_id || ins.id)}
                style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '8px 10px', cursor: 'pointer' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                  <span style={{ color: '#e2e8f0' }}>{ins.template_id || ins.name}</span>
                  <span style={{ color: STATE_COLOR[ins.state || ins.status] || '#64748b', fontWeight: 600 }}>
                    {ins.state || ins.status}
                  </span>
                </div>
                <div style={{ fontSize: 9, color: '#475569', marginTop: 2, fontFamily: 'monospace' }}>
                  {ins.instance_id || ins.id} · 创建于 {ins.created_at || '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 部门 */}
      {departments.length === 0 && (
        <div style={{ ...card, borderColor: '#78350f' }}>
          <div style={{ fontSize: 11, color: '#fcd34d' }}>
            ⚠️ 本实例尚未在 dojocore 里注册本地部门画像(这与上方的「已知部门」目录是两回事:
            那里登记的是别的实例,这里说的是本实例自己的能力声明)。
          </div>
        </div>
      )}

      <WorkflowEditor
        open={showEditor}
        nodeTypes={nodeTypes}
        tools={tools}
        departments={deptIds}
        onClose={() => setShowEditor(false)}
        onSaved={() => { setMsg('模板已保存'); load() }}
      />

      {/* 模板流程弹窗 */}
      {tplDetail && (
        <div onClick={() => setTplDetail(null)} style={overlay}>
          <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: '100%', maxWidth: 720, maxHeight: '85vh', overflowY: 'auto' }}>
            {tplDetail.error ? <div style={{ color: '#f87171' }}>{tplDetail.error}</div> : (
              <>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>{tplDetail.name || tplDetail.id}</div>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 10 }}>{tplDetail.description}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(tplDetail.nodes || []).map((n: any, i: number) => (
                    <div key={n.id || i} style={{
                      display: 'flex', alignItems: 'center', gap: 8, background: '#0f172a',
                      borderLeft: `3px solid ${NODE_COLOR[n.type] || '#334155'}`, borderRadius: 4, padding: '6px 9px',
                    }}>
                      <span style={{ color: '#475569', fontSize: 9, width: 20 }}>{i + 1}</span>
                      <span style={{ color: NODE_COLOR[n.type] || '#94a3b8', fontSize: 9, width: 66 }}>{n.type}</span>
                      <span style={{ flex: 1, color: '#e2e8f0', fontSize: 11 }}>{n.label || n.id}</span>
                      {n.depends_on?.length > 0 && (
                        <span style={{ color: '#475569', fontSize: 9, fontFamily: 'monospace' }}>← {n.depends_on.join(',')}</span>
                      )}
                    </div>
                  ))}
                </div>
                <button onClick={() => setTplDetail(null)} style={{ ...btn('#334155'), marginTop: 12 }}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}

      {/* 实例详情弹窗 */}
      {detail && (
        <div onClick={() => setDetail(null)} style={overlay}>
          <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: '100%', maxWidth: 720, maxHeight: '85vh', overflowY: 'auto' }}>
            {detail.error ? <div style={{ color: '#f87171' }}>{detail.error}</div> : (
              <>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>
                  {detail.template_id} <span style={{ fontSize: 11, color: STATE_COLOR[detail.state] || '#64748b' }}>{detail.state}</span>
                </div>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, fontFamily: 'monospace' }}>{detail.instance_id}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(detail.nodes || []).map((n: any) => (
                    <div key={n.node_id || n.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8, background: '#0f172a',
                      borderLeft: `3px solid ${STATE_COLOR[n.state] || '#334155'}`, borderRadius: 4, padding: '6px 9px',
                    }}>
                      <span style={{ flex: 1, color: '#e2e8f0', fontSize: 11 }}>{n.label || n.node_id || n.id}</span>
                      <span style={{ color: STATE_COLOR[n.state] || '#64748b', fontSize: 10, width: 64 }}>{n.state}</span>
                      <div style={{ display: 'flex', gap: 3 }}>
                        {['begin', 'complete', 'fail'].map((a) => (
                          <button key={a} onClick={() => nodeAction(detail.instance_id, n.node_id || n.id, a)}
                            style={miniBtn(a === 'fail' ? '#7f1d1d' : a === 'complete' ? '#064e3b' : '#1e3a8a',
                              a === 'fail' ? '#fca5a5' : a === 'complete' ? '#6ee7b7' : '#93c5fd')}>
                            {a === 'begin' ? '开始' : a === 'complete' ? '完成' : '失败'}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <button onClick={() => setDetail(null)} style={{ ...btn('#334155'), marginTop: 12 }}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999,
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12,
}
const btn = (bg: string): React.CSSProperties => ({
  background: bg, color: '#fff', border: 0, borderRadius: 5, padding: '4px 10px',
  fontSize: 10, fontWeight: 600, cursor: 'pointer',
})
const miniBtn = (bg: string, fg: string): React.CSSProperties => ({
  background: bg, color: fg, border: 0, borderRadius: 4, padding: '2px 7px',
  fontSize: 9, fontWeight: 600, cursor: 'pointer',
})

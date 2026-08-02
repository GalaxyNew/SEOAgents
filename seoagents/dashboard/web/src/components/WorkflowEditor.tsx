import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, Field, inputStyle, btn } from '../ui'

/**
 * 工作流模板编辑器 —— 弹窗内自由组合节点。
 *
 * 保存前一定先调后端 `/templates/validate`:节点类型的必填项、依赖是否成环、
 * 跨部门节点的目标部门是否存在,这些规则在后端,前端不重复实现一遍
 * (两份规则迟早会不一致,而不一致时前端放行、后端拒绝是最难查的那种)。
 */

type NodeType = {
  id: string
  label: string
  required_config: string[]
  hint: string
  runs_externally: boolean
  acceptance_required: boolean
}

export type DraftNode = {
  id: string
  type: string
  title: string
  depends_on: string[]
  acceptance: string[]
  config: Record<string, string>
  on_failure: string
  timeout_hours: number
  optional: boolean
}

const emptyNode = (seq: number): DraftNode => ({
  id: `step_${seq}`,
  type: 'agent_task',
  title: '',
  depends_on: [],
  acceptance: [],
  config: {},
  on_failure: 'stop',
  timeout_hours: 24,
  optional: false,
})

const NODE_COLOR: Record<string, string> = {
  agent_task: '#3b82f6', tool_call: '#10b981',
  dept_request: '#a855f7', human_gate: '#f59e0b',
}

export const WorkflowEditor: React.FC<{
  open: boolean
  nodeTypes: NodeType[]
  tools: string[]
  departments: string[]
  onClose: () => void
  onSaved: () => void
}> = ({ open, nodeTypes, tools, departments, onClose, onSaved }) => {
  const isMobile = useIsMobile()
  const [meta, setMeta] = useState({ id: '', name: '', dept: 'seo', description: '', version: '1.0' })
  const [nodes, setNodes] = useState<DraftNode[]>([emptyNode(1)])
  const [active, setActive] = useState(0)
  const [checking, setChecking] = useState(false)
  const [issues, setIssues] = useState<string[]>([])
  const [okMsg, setOkMsg] = useState('')

  useEffect(() => {
    if (!open) return
    setMeta({ id: '', name: '', dept: 'seo', description: '', version: '1.0' })
    setNodes([emptyNode(1)]); setActive(0); setIssues([]); setOkMsg('')
  }, [open])

  const spec = (t: string) => nodeTypes.find((n) => n.id === t)
  const cur = nodes[active]

  const patch = (i: number, p: Partial<DraftNode>) =>
    setNodes((ns) => ns.map((n, k) => (k === i ? { ...n, ...p } : n)))

  const addNode = () => {
    const n = emptyNode(nodes.length + 1)
    // 默认串在上一个节点后面 —— 大多数流程是线性的,要并行再手动去掉依赖
    if (nodes.length > 0) n.depends_on = [nodes[nodes.length - 1].id]
    setNodes([...nodes, n]); setActive(nodes.length)
  }

  const removeNode = (i: number) => {
    const gone = nodes[i].id
    const rest = nodes.filter((_, k) => k !== i)
      .map((n) => ({ ...n, depends_on: n.depends_on.filter((d) => d !== gone) }))
    setNodes(rest.length ? rest : [emptyNode(1)])
    setActive(Math.max(0, Math.min(active, rest.length - 1)))
  }

  const payload = () => ({
    ...meta,
    id: meta.id.trim(),
    name: meta.name.trim() || meta.id.trim(),
    nodes: nodes.map((n) => ({
      id: n.id.trim(), type: n.type, title: n.title.trim() || n.id,
      depends_on: n.depends_on, acceptance: n.acceptance.filter((a) => a.trim()),
      config: Object.fromEntries(Object.entries(n.config).filter(([, v]) => String(v).trim())),
      on_failure: n.on_failure, timeout_hours: Number(n.timeout_hours) || 24,
      optional: n.optional,
    })),
  })

  /** 校验一律走后端 —— 规则只有一份 */
  const validate = async (): Promise<boolean> => {
    setChecking(true); setIssues([]); setOkMsg('')
    try {
      const r = await fetch('/api/workflows/templates/validate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      })
      const j = await r.json().catch(() => ({}))
      // 后端返回 {valid: bool, error: string};兼容可能的多条形态
      const errs: string[] = j.error ? [String(j.error)]
        : Array.isArray(j.errors) ? j.errors
        : j.detail ? [String(j.detail)] : []
      if (!r.ok || j.valid === false || errs.length) {
        setIssues(errs.length ? errs : [`校验失败 (HTTP ${r.status})`])
        return false
      }
      setOkMsg('校验通过')
      return true
    } catch (e) {
      setIssues([`校验请求异常: ${e}`]); return false
    } finally { setChecking(false) }
  }

  const save = async () => {
    if (!(await validate())) return
    const r = await fetch('/api/workflows/templates', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setIssues([`保存失败: ${j.detail || r.status}`]); return }
    onSaved(); onClose()
  }

  const idOk = (v: string) => /^[a-z][a-z0-9_]{1,39}$/.test(v)
  const canSave = idOk(meta.id.trim()) && nodes.every((n) => idOk(n.id.trim()))

  return (
    <Modal
      open={open}
      title="新建工作流模板"
      subtitle="自由组合节点;保存前会用后端规则校验必填项、依赖闭环与跨部门目标"
      width={900}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} style={btn('#334155')}>取消</button>
          <button onClick={validate} disabled={checking} style={btn('#334155')}>
            {checking ? '校验中…' : '仅校验'}
          </button>
          <button onClick={save} disabled={!canSave || checking}
            style={btn(canSave && !checking ? '#2563eb' : '#334155')}>保存模板</button>
        </>
      }
    >
      {/* 基本信息 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 120px', gap: 10 }}>
        <Field label="模板 ID" hint="英文小写下划线,保存后不可改">
          <input value={meta.id} onChange={(e) => setMeta({ ...meta, id: e.target.value })}
            placeholder="blog_content_chain"
            style={{ ...inputStyle, borderColor: !meta.id || /^[a-z][a-z0-9_]{1,39}$/.test(meta.id) ? '#334155' : '#7f1d1d' }} />
        </Field>
        <Field label="显示名">
          <input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })}
            placeholder="站内 Blog 文章发布" style={inputStyle} />
        </Field>
        <Field label="版本">
          <input value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })}
            style={inputStyle} />
        </Field>
      </div>
      <Field label="说明">
        <input value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })}
          placeholder="这个流程解决什么问题" style={inputStyle} />
      </Field>

      {/* 节点编排 */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '210px 1fr', gap: 12, marginTop: 6 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8' }}>节点 ({nodes.length})</span>
            <button onClick={addNode} style={btn('#2563eb')}>＋</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 320, overflowY: 'auto' }}>
            {nodes.map((n, i) => (
              <div key={i} onClick={() => setActive(i)} style={{
                background: i === active ? '#1e293b' : '#0f172a',
                border: `1px solid ${i === active ? '#3b82f6' : '#1e293b'}`,
                borderLeft: `3px solid ${NODE_COLOR[n.type] || '#475569'}`,
                borderRadius: 6, padding: '6px 8px', cursor: 'pointer',
              }}>
                <div style={{ fontSize: 11, color: '#e2e8f0', fontWeight: 600 }}>
                  {i + 1}. {n.title || n.id}
                </div>
                <div style={{ fontSize: 9, color: '#64748b', marginTop: 2 }}>
                  {spec(n.type)?.label || n.type}
                  {n.depends_on.length > 0 && ` · 依赖 ${n.depends_on.join(',')}`}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 单节点编辑 */}
        {cur && (
          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 11 }}>
            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
              <Field label="节点 ID" hint="小写字母开头,2-40 位(后端规则)">
                <input value={cur.id}
                  onChange={(e) => patch(active, { id: e.target.value })}
                  style={{
                    ...inputStyle,
                    borderColor: /^[a-z][a-z0-9_]{1,39}$/.test(cur.id) ? '#334155' : '#7f1d1d',
                  }} />
              </Field>
              <Field label="类型">
                <select value={cur.type}
                  onChange={(e) => patch(active, { type: e.target.value, config: {} })}
                  style={inputStyle}>
                  {nodeTypes.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
              </Field>
            </div>
            <div style={{ fontSize: 10, color: '#64748b', marginTop: -4, marginBottom: 8 }}>
              {spec(cur.type)?.hint}
            </div>

            <Field label="标题">
              <input value={cur.title} onChange={(e) => patch(active, { title: e.target.value })}
                placeholder="这一步要达成什么" style={inputStyle} />
            </Field>

            {/* 按类型渲染必填配置 —— 必填项由后端 node-types 下发,不在前端写死 */}
            {(spec(cur.type)?.required_config || []).map((k) => (
              <Field key={k} label={`${k}(必填)`}>
                {k === 'tool' ? (
                  <select value={cur.config[k] || ''}
                    onChange={(e) => patch(active, { config: { ...cur.config, [k]: e.target.value } })}
                    style={inputStyle}>
                    <option value="">选择工具…</option>
                    {tools.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                ) : k === 'dept' ? (
                  <select value={cur.config[k] || ''}
                    onChange={(e) => patch(active, { config: { ...cur.config, [k]: e.target.value } })}
                    style={inputStyle}>
                    <option value="">选择部门…</option>
                    {departments.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                ) : k === 'instruction' || k === 'prompt' ? (
                  <textarea rows={3} value={cur.config[k] || ''}
                    onChange={(e) => patch(active, { config: { ...cur.config, [k]: e.target.value } })}
                    placeholder={k === 'prompt' ? '要人确认什么' : '要 agent 做什么,写具体'}
                    style={{ ...inputStyle, resize: 'vertical' }} />
                ) : (
                  <input value={cur.config[k] || ''}
                    onChange={(e) => patch(active, { config: { ...cur.config, [k]: e.target.value } })}
                    style={inputStyle} />
                )}
              </Field>
            ))}

            {cur.type === 'dept_request' && departments.length === 0 && (
              <div style={{ background: '#1f1a10', border: '1px solid #78350f', borderRadius: 6,
                            padding: 8, fontSize: 10, color: '#fcd34d', marginBottom: 10 }}>
                还没有登记任何其他部门,这个跨部门节点将无法执行。
                先去「设置 → 部门管理」加一个。
              </div>
            )}

            <Field label="依赖节点" hint="不选即为起始节点;多个依赖表示全部完成后才开始">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {nodes.filter((_, i) => i !== active).map((n) => {
                  const on = cur.depends_on.includes(n.id)
                  return (
                    <span key={n.id} onClick={() => patch(active, {
                      depends_on: on ? cur.depends_on.filter((d) => d !== n.id) : [...cur.depends_on, n.id],
                    })} style={{
                      background: on ? '#1e3a8a' : '#1e293b',
                      border: `1px solid ${on ? '#3b82f6' : '#334155'}`,
                      color: on ? '#93c5fd' : '#64748b',
                      borderRadius: 4, padding: '2px 7px', fontSize: 10, cursor: 'pointer',
                    }}>{n.id}</span>
                  )
                })}
                {nodes.length === 1 && <span style={{ fontSize: 10, color: '#475569' }}>只有一个节点</span>}
              </div>
            </Field>

            <Field label="验收标准"
              hint={spec(cur.type)?.acceptance_required
                ? '这类节点必须逐条勾验收才能标记完成 —— 一条都没有会被后端拒绝'
                : '可选'}>
              {cur.acceptance.map((a, ai) => (
                <div key={ai} style={{ display: 'flex', gap: 5, marginBottom: 4 }}>
                  <input value={a} onChange={(e) => {
                    const arr = [...cur.acceptance]; arr[ai] = e.target.value
                    patch(active, { acceptance: arr })
                  }} placeholder="可被客观检验的一条标准" style={inputStyle} />
                  <button onClick={() => patch(active, {
                    acceptance: cur.acceptance.filter((_, k) => k !== ai),
                  })} style={btn('#7f1d1d')}>×</button>
                </div>
              ))}
              <button onClick={() => patch(active, { acceptance: [...cur.acceptance, ''] })}
                style={btn('#334155')}>＋ 加一条</button>
            </Field>

            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr', gap: 10 }}>
              <Field label="失败处理">
                <select value={cur.on_failure} onChange={(e) => patch(active, { on_failure: e.target.value })}
                  style={inputStyle}>
                  <option value="stop">停止整条流程</option>
                  <option value="skip">跳过继续</option>
                  <option value="retry">重试</option>
                </select>
              </Field>
              <Field label="超时(小时)">
                <input type="number" min={1} value={cur.timeout_hours}
                  onChange={(e) => patch(active, { timeout_hours: Number(e.target.value) })}
                  style={inputStyle} />
              </Field>
              <Field label="可选节点">
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#cbd5e1', paddingTop: 6 }}>
                  <input type="checkbox" checked={cur.optional}
                    onChange={(e) => patch(active, { optional: e.target.checked })}
                    style={{ accentColor: '#3b82f6' }} />
                  失败不阻断
                </label>
              </Field>
            </div>

            <div style={{ textAlign: 'right', borderTop: '1px solid #1e293b', paddingTop: 8 }}>
              <button onClick={() => removeNode(active)} style={btn('#7f1d1d')}>删除此节点</button>
            </div>
          </div>
        )}
      </div>

      {issues.length > 0 && (
        <div style={{ background: '#1f1315', border: '1px solid #7f1d1d', borderRadius: 6,
                      padding: 10, marginTop: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#fca5a5', marginBottom: 5 }}>
            校验未通过({issues.length})
          </div>
          {issues.map((e, i) => (
            <div key={i} style={{ fontSize: 11, color: '#fca5a5', lineHeight: 1.7 }}>· {e}</div>
          ))}
        </div>
      )}
      {okMsg && (
        <div style={{ background: '#0f1f19', border: '1px solid #065f46', borderRadius: 6,
                      padding: 9, marginTop: 10, fontSize: 11, color: '#6ee7b7' }}>
          ✓ {okMsg} —— 可以保存了
        </div>
      )}
    </Modal>
  )
}

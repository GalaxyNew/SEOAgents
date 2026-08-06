import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import {
  Alert,
  Modal,
  btn,
  formatApiError,
  inputStyle,
  parseApiResponse,
  useDialogs,
  useToast,
} from '../ui'
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
type ParamSchemaItem = { name: string; type: string; description: string; required: boolean; default: string }

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

const NODE_COLOR: Record<string, string> = {
  input: '#06b6d4',
  agent_task: '#3b82f6',
  tool_call: '#10b981',
  dept_request: '#a855f7',
  human_gate: '#f59e0b',
  verify: '#ef4444',
  output: '#ec4899',
}

const STATE_COLOR: Record<string, string> = {
  pending: '#64748b', ready: '#38bdf8', running: '#3b82f6', in_progress: '#3b82f6',
  done: '#10b981', completed: '#10b981', failed: '#ef4444', blocked: '#f59e0b',
  waiting: '#a855f7', cancelled: '#475569',
  paused: '#f59e0b',
}

export const WorkflowPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const toast = useToast()
  const dialogs = useDialogs()
  const [templates, setTemplates] = useState<Template[]>([])
  const [nodeTypes, setNodeTypes] = useState<NodeType[]>([])
  const [departments, setDepartments] = useState<any[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [detail, setDetail] = useState<any>(null)
  const [tplDetail, setTplDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [showEditor, setShowEditor] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<any>(null)
  const [tools, setTools] = useState<string[]>([])
  const [deptIds, setDeptIds] = useState<string[]>([])
  const [showInputPrompt, setShowInputPrompt] = useState<{ templateId: string; templateName: string; paramSchema: ParamSchemaItem[] } | null>(null)
  const [inputParams, setInputParams] = useState<Record<string, string>>({})

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    setErr('')
    try {
      const responses = await Promise.all([
        fetch('/api/workflows/templates'),
        fetch('/api/workflows/node-types'),
        fetch('/api/workflows/departments'),
        fetch('/api/workflows/instances'),
      ])
      const [t, nt, d, ins] = await Promise.all([
        parseApiResponse<any>(responses[0], '模板列表读取失败'),
        parseApiResponse<any>(responses[1], '节点类型读取失败'),
        parseApiResponse<any>(responses[2], '部门列表读取失败'),
        parseApiResponse<any>(responses[3], '实例列表读取失败'),
      ])
      setTemplates(t.templates || [])
      setNodeTypes(nt.types || [])
      setDepartments(d.departments || [])
      setInstances(ins.items || [])
      // 节点编辑要选具体工具与目标部门,两者都从真实注册表取,不写死
      try {
        const cfg = await parseApiResponse<any>(await fetch('/api/config'), '配置读取失败')
        setTools((cfg?.resolved?.tools as string[]) || [])
      } catch { setTools([]) }
      try {
        const dp = await parseApiResponse<any>(await fetch('/api/departments'), '部门注册表读取失败')
        setDeptIds((dp?.items || []).filter((x: any) => x.enabled).map((x: any) => x.id))
      } catch { setDeptIds([]) }
    } catch (error) {
      setErr(`工作流服务不可用：${formatApiError(error)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openTemplate = async (id: string) => {
    try {
      setTplDetail(await parseApiResponse<any>(await fetch(`/api/workflows/templates/${id}`), '模板读取失败'))
    } catch (error) {
      setTplDetail({ error: formatApiError(error, '模板读取失败') })
    }
  }

  const openInstance = async (id: string) => {
    try {
      setDetail(await parseApiResponse<any>(await fetch(`/api/workflows/instances/${id}`), '实例读取失败'))
    } catch (error) {
      setDetail({ error: formatApiError(error, '实例读取失败') })
    }
  }

  const editTemplate = async (id: string) => {
    try {
      const template = await parseApiResponse<any>(await fetch(`/api/workflows/templates/${id}`), '读取模板失败')
      setEditingTemplate(template)
      setShowEditor(true)
    } catch (error) {
      toast.error(`读取模板失败：${formatApiError(error)}`)
    }
  }

  const startInstance = async (templateId: string, instanceParams?: Record<string, string>, autoStart = false) => {
    try {
      const result = await parseApiResponse<any>(await fetch('/api/workflows/instances', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: templateId, auto_start: autoStart, input_params: instanceParams || {} }),
      }), '创建实例失败')
      if (autoStart) {
        const count = result.runtime?.created?.length || 0
        toast.success(`实例 ${result.instance_id || ''} 已启动 · ${count} 个首层节点运行中`)
      } else {
        toast.success(`实例 ${result.instance_id || ''} 已创建（待运行）`)
      }
      void load(true)
    } catch (error) {
      toast.error(`创建实例失败：${formatApiError(error)}`)
    }
  }

  const instanceAction = async (id: string, action: 'start' | 'pause' | 'resume' | 'delete') => {
    if (action === 'delete') {
      const approved = await dialogs.confirm({
        title: `删除工作流实例 ${id}`,
        message: <>确定删除实例 <code>{id}</code> 吗？</>,
        consequence: '系统会停止可控运行并删除实例记录；删除后无法从面板恢复。',
        confirmLabel: '停止并删除',
        tone: 'danger',
      })
      if (!approved) return
    }
    try {
      await parseApiResponse(await fetch(`/api/workflows/instances/${id}${action === 'delete' ? '' : `/${action}`}`, {
        method: action === 'delete' ? 'DELETE' : 'POST', headers: { 'Content-Type': 'application/json' },
      }), `${action} 失败`)
      toast.success(`实例 ${id} 已${action === 'start' ? '启动' : action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '删除'}`)
      if (detail?.instance_id === id && action === 'delete') setDetail(null)
      else if (detail?.instance_id === id) void openInstance(id)
      void load(true)
    } catch (error) {
      toast.error(`${action} 失败：${formatApiError(error)}`)
    }
  }

  const approveNode = async (instId: string, nodeId: string) => {
    const approval = await dialogs.form<{ approver: string; note: string }>({
      title: `具名批准节点 ${nodeId}`,
      subtitle: `工作流实例 ${instId} · 批准将释放一次受控执行`,
      submitLabel: '批准并继续',
      fields: [
        {
          name: 'approver',
          label: '审批人',
          required: true,
          placeholder: '请输入真实人员姓名',
          hint: '不得填写 agent、Hermes、system 等系统身份',
          validate: (value) => /^(agent|hermes|system)$/i.test(value) ? '审批人必须是具名人员，不能使用系统身份' : undefined,
        },
        { name: 'note', label: '审批备注', type: 'textarea', placeholder: '可选：记录审批依据或范围' },
      ],
    })
    if (!approval) return
    try {
      await parseApiResponse(await fetch(`/api/workflows/instances/${instId}/nodes/${nodeId}/approve`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approver: approval.approver, approved: true, note: approval.note }),
      }), '审批失败')
      toast.success(`节点 ${nodeId} 已由 ${approval.approver} 批准`)
      void openInstance(instId)
      void load(true)
    } catch (error) {
      toast.error(`审批失败：${formatApiError(error)}`)
    }
  }

  const nodeAction = async (instId: string, nodeId: string, action: string) => {
    try {
      await parseApiResponse(await fetch(`/api/workflows/instances/${instId}/nodes/${nodeId}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(action === 'fail' ? { reason: '面板手动标记失败' } : {}),
      }), `${action} 失败`)
      toast.success(`节点 ${nodeId} 已${action}`)
      void openInstance(instId)
      void load(true)
    } catch (error) {
      toast.error(`${action} 失败：${formatApiError(error)}`)
    }
  }

  if (loading) return <div style={{ ...card, color: '#9ca3af', textAlign: 'center' }}>⚙️ 正在载入工作流...</div>
  if (err) return <Alert tone="error" title="工作流服务不可用">{err}</Alert>

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
          <button onClick={() => { setEditingTemplate(null); setShowEditor(true) }} style={btn('#2563eb')}>＋ 新建模板</button>
        </div>
        {templates.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 11, textAlign: 'center', padding: '18px 0', lineHeight: 1.9 }}>
            还没有工作流模板<br />
            <button onClick={() => { setEditingTemplate(null); setShowEditor(true) }} style={{ ...btn('#2563eb'), marginTop: 6 }}>
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
                  <button onClick={() => openTemplate(t.id)} style={btn('#334155')}>查看 DAG</button>
                  <button onClick={() => editTemplate(t.id)} style={btn('#475569')}>编辑</button>
                  <button onClick={async () => {
                    // 获取完整模板，提取 input 节点的参数 schema
                    let schema: ParamSchemaItem[] = []
                    try {
                      const full = await parseApiResponse<any>(await fetch(`/api/workflows/templates/${t.id}`), '模板参数读取失败')
                      const inputNode = (full.nodes || []).find((node: any) => node.type === 'input')
                      if (inputNode?.config?.input_params_schema) {
                        schema = inputNode.config.input_params_schema.filter((parameter: ParamSchemaItem) => parameter.name?.trim())
                      }
                    } catch (error) {
                      toast.error(`模板参数读取失败：${formatApiError(error)}`)
                      return
                    }
                    // 用默认值预填
                    const defaults: Record<string, string> = {}
                    schema.forEach((p) => { if (p.default) defaults[p.name] = p.default })
                    setInputParams(defaults)
                    setShowInputPrompt({ templateId: t.id, templateName: t.name, paramSchema: schema })
                  }} style={btn('#2563eb')}>＋ 创建实例</button>
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
          <button onClick={() => load(true)} style={btn('#334155')}>↻ 刷新</button>
        </div>
        {instances.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 11, textAlign: 'center', padding: '14px 0' }}>
            当前没有运行中的工作流实例 —— 上面挑个模板起一个
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {instances.map((ins) => (
              <div key={ins.instance_id || ins.id}
                style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '8px 10px' }}>
                <div onClick={() => openInstance(ins.instance_id || ins.id)} style={{ cursor: 'pointer' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                    <span style={{ color: '#e2e8f0' }}>{ins.title || ins.template_id || ins.name}</span>
                    <span style={{ color: STATE_COLOR[(ins.state || ins.status || '').toLowerCase()] || '#64748b', fontWeight: 600 }}>
                      {ins.state || ins.status}
                    </span>
                  </div>
                  <div style={{ fontSize: 9, color: '#475569', marginTop: 2, fontFamily: 'monospace' }}>
                    {ins.instance_id || ins.id} · {ins.progress?.percent ?? 0}% · 创建于 {ins.created_at || '—'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 5, marginTop: 7 }}>
                  {(['PENDING', 'BLOCKED', 'CREATED'] as string[]).includes(ins.status) && <button onClick={() => instanceAction(ins.instance_id, 'start')} style={btn('#2563eb')}>▶ 运行</button>}
                  {ins.status === 'RUNNING' && <><button onClick={() => instanceAction(ins.instance_id, 'pause')} style={btn('#92400e')}>⏸ 暂停</button><button onClick={() => instanceAction(ins.instance_id, 'delete')} style={btn('#7f1d1d')}>⏹ 停止</button></>}
                  {ins.status === 'PAUSED' && <><button onClick={() => instanceAction(ins.instance_id, 'resume')} style={btn('#047857')}>▶ 恢复</button><button onClick={() => instanceAction(ins.instance_id, 'delete')} style={btn('#7f1d1d')}>⏹ 停止</button></>}
                  {['DONE', 'FAILED', 'CANCELLED'].includes(ins.status) && <button onClick={() => instanceAction(ins.instance_id, 'delete')} style={btn('#7f1d1d')}>删除</button>}
                  {ins.status === 'RUNNING' && <span style={{ marginLeft: 4, fontSize: 10, animation: 'spin 1s linear infinite', display: 'inline-block' }}>⚙️</span>}
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

      {/* 参数输入弹窗 — 创建实例时按 schema 展示 */}
      <Modal
        open={!!showInputPrompt}
        title={`创建实例${showInputPrompt ? ` · ${showInputPrompt.templateName}` : ''}`}
        subtitle={showInputPrompt?.paramSchema.length ? '请按参数要求填写输入参数' : '此工作流无需输入参数'}
        width={520}
        closeOnBackdrop={false}
        onClose={() => { setShowInputPrompt(null); setInputParams({}) }}
        footer={showInputPrompt ? (
          <>
            <button onClick={() => { setShowInputPrompt(null); setInputParams({}) }} style={btn('#334155')}>取消</button>
            <button onClick={() => {
              const missing = showInputPrompt.paramSchema.filter((p) => p.required && !(inputParams[p.name] || p.default)?.trim())
              if (missing.length) { toast.warning(`缺少必填参数：${missing.map((item) => item.name).join('、')}`); return }
              void startInstance(showInputPrompt.templateId, inputParams, false)
              setShowInputPrompt(null)
              setInputParams({})
            }} style={btn('#047857')}>创建实例</button>
            <button onClick={() => {
              const missing = showInputPrompt.paramSchema.filter((p) => p.required && !(inputParams[p.name] || p.default)?.trim())
              if (missing.length) { toast.warning(`缺少必填参数：${missing.map((item) => item.name).join('、')}`); return }
              void startInstance(showInputPrompt.templateId, inputParams, true)
              setShowInputPrompt(null)
              setInputParams({})
            }} style={btn('#2563eb')}>创建并运行</button>
          </>
        ) : undefined}
      >
        {showInputPrompt && (showInputPrompt.paramSchema.length > 0 ? showInputPrompt.paramSchema.map((p, index) => (
          <div key={p.name} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#e2e8f0' }}>{p.name}</span>
              <span style={{ fontSize: 9, background: '#1e293b', color: '#60a5fa', borderRadius: 3, padding: '1px 5px' }}>{p.type}</span>
              {p.required && <span style={{ fontSize: 9, color: '#ef4444' }}>*必填</span>}
            </div>
            {p.description && <div style={{ fontSize: 9, color: '#64748b', marginBottom: 3 }}>{p.description}</div>}
            <input
              data-autofocus={index === 0 ? 'true' : undefined}
              value={inputParams[p.name] || ''}
              onChange={(event) => setInputParams((current) => ({ ...current, [p.name]: event.target.value }))}
              placeholder={p.default ? `默认：${p.default}` : `请输入 ${p.type} 类型的值`}
              style={inputStyle}
            />
          </div>
        )) : <Alert tone="info">此工作流无需输入参数，可以直接创建。</Alert>)}
      </Modal>

      <WorkflowEditor
        open={showEditor}
        initialTemplate={editingTemplate}
        nodeTypes={nodeTypes}
        tools={tools}
        departments={deptIds}
        templates={templates.map(t => ({ id: t.id, name: t.name }))}
        onClose={() => { setShowEditor(false); setEditingTemplate(null) }}
        onSaved={() => { toast.success(editingTemplate ? '模板新版本已保存' : '模板已保存'); void load(true) }}
      />

      {/* 模板流程弹窗 */}
      <Modal
        open={!!tplDetail}
        title={tplDetail?.name || tplDetail?.id || '模板详情'}
        subtitle={tplDetail?.description}
        width={720}
        closeOnBackdrop={false}
        onClose={() => setTplDetail(null)}
        footer={<button onClick={() => setTplDetail(null)} style={btn('#334155')}>关闭</button>}
      >
        {tplDetail?.error ? <Alert tone="error">{tplDetail.error}</Alert> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {(tplDetail?.nodes || []).map((node: any, index: number) => (
              <div key={node.id || index} style={{
                display: 'flex', alignItems: 'center', gap: 8, background: '#0f172a',
                borderLeft: `3px solid ${NODE_COLOR[node.type] || '#334155'}`, borderRadius: 4, padding: '6px 9px',
              }}>
                <span style={{ color: '#475569', fontSize: 9, width: 20 }}>{index + 1}</span>
                <span style={{ color: NODE_COLOR[node.type] || '#94a3b8', fontSize: 9, width: 66 }}>{node.type}</span>
                <span style={{ flex: 1, color: '#e2e8f0', fontSize: 11 }}>{node.label || node.id}</span>
                {node.depends_on?.length > 0 && (
                  <span style={{ color: '#475569', fontSize: 9, fontFamily: 'monospace' }}>← {node.depends_on.join(',')}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* 实例详情弹窗 */}
      <Modal
        open={!!detail}
        title={detail?.template_id || '实例详情'}
        subtitle={detail?.instance_id}
        width={760}
        closeOnBackdrop={false}
        onClose={() => setDetail(null)}
        footer={<button onClick={() => setDetail(null)} style={btn('#334155')}>关闭</button>}
      >
        {detail?.error ? <Alert tone="error">{detail.error}</Alert> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {detail?.state && (
              <div style={{ marginBottom: 7, fontSize: 11, color: STATE_COLOR[String(detail.state).toLowerCase()] || '#64748b' }}>
                当前状态：{detail.state}
              </div>
            )}
            {(detail?.nodes || []).map((node: any) => (
              <div key={node.node_id || node.id} style={{
                display: 'flex', alignItems: 'center', gap: 8, background: '#0f172a',
                borderLeft: `3px solid ${STATE_COLOR[String(node.state || '').toLowerCase()] || '#334155'}`, borderRadius: 4, padding: '6px 9px',
              }}>
                <span style={{ flex: 1, color: '#e2e8f0', fontSize: 11 }}>{node.title || node.label || node.node_id || node.id}</span>
                <span style={{ color: STATE_COLOR[String(node.state || '').toLowerCase()] || '#64748b', fontSize: 10, width: 110 }}>{node.state}{node.runtime_status ? ` · ${node.runtime_status}` : ''}</span>
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                  {(node.state === 'WAITING_HUMAN' || node.runtime_status === 'BLOCKED_APPROVAL') && (
                    <button onClick={() => approveNode(detail.instance_id, node.node_id || node.id)} style={miniBtn('#92400e', '#fde68a')}>具名批准</button>
                  )}
                  {!['WAITING_HUMAN'].includes(node.state) && ['begin', 'complete', 'fail'].map((action) => (
                    <button key={action} onClick={() => nodeAction(detail.instance_id, node.node_id || node.id, action)}
                      style={miniBtn(action === 'fail' ? '#7f1d1d' : action === 'complete' ? '#064e3b' : '#1e3a8a',
                        action === 'fail' ? '#fca5a5' : action === 'complete' ? '#6ee7b7' : '#93c5fd')}>
                      {action === 'begin' ? '开始' : action === 'complete' ? '完成' : '失败'}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}

const miniBtn = (bg: string, fg: string): React.CSSProperties => ({
  background: bg, color: fg, border: 0, borderRadius: 4, padding: '2px 7px',
  fontSize: 9, fontWeight: 600, cursor: 'pointer',
})

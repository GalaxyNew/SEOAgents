import { useEffect, useMemo, useRef, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, Field, inputStyle, btn } from '../ui'

type NodeType = {
  id: string; label: string; required_config: string[]; hint: string
  runs_externally: boolean; acceptance_required: boolean
}
export type DraftNode = {
  id: string; type: string; title: string; depends_on: string[]; acceptance: string[]
  config: Record<string, any>; on_failure: string; timeout_hours: number; optional: boolean
}
type Pos = { x: number; y: number }
type TemplateData = Record<string, any>
type PortDrag = { source: string; x: number; y: number }

const NODE_W = 210, NODE_H = 112
const NODE_COLOR: Record<string, string> = {
  input: '#06b6d4', agent_task: '#3b82f6', tool_call: '#10b981', dept_request: '#a855f7',
  human_gate: '#f59e0b', verify: '#ef4444', output: '#ec4899',
}

// 已知模型的推理强度选项 —— 各品牌参数名不同
const PROVIDER_MODELS: Record<string, { label: string; efforts: { value: string; label: string }[] }> = {
  zai: { label: '智谱 (zai)', efforts: [
    { value: '', label: '默认' }, { value: 'ultra', label: 'ultra' }, { value: 'high', label: 'high' }, { value: 'standard', label: 'standard' },
  ]},
  sub2api: { label: 'Sub2API', efforts: [
    { value: '', label: '默认' }, { value: 'high', label: 'high' }, { value: 'medium', label: 'medium' }, { value: 'low', label: 'low' },
  ]},
  openai: { label: 'OpenAI', efforts: [
    { value: '', label: '默认' }, { value: 'high', label: 'high' }, { value: 'medium', label: 'medium' }, { value: 'low', label: 'low' },
  ]},
}

const makeNode = (id: string, type: string, title = ''): DraftNode => ({
  id, type, title, depends_on: [], acceptance: [],
  config: type === 'input' ? { input_mode: 'none' }
    : type === 'output' ? { output_mode: 'end' } : {},
  on_failure: 'stop', timeout_hours: 24, optional: false,
})

function initialNodes(): DraftNode[] {
  const input = makeNode('input_1', 'input', '输入')
  const output = makeNode('output_1', 'output', '结束')
  // 默认不连线——用户手动从输出端拖到输入端连线
  return [input, output]
}

function normaliseNode(raw: any, i: number): DraftNode {
  const type = String(raw?.type || 'agent_task')
  return {
    ...makeNode(String(raw?.id || `step_${i + 1}`), type),
    title: String(raw?.title || raw?.label || ''), depends_on: [...(raw?.depends_on || [])],
    acceptance: [...(raw?.acceptance || [])], config: { ...(raw?.config || {}) },
    on_failure: String(raw?.on_failure || 'stop'), timeout_hours: Number(raw?.timeout_hours || 24),
    optional: Boolean(raw?.optional),
  }
}

function topologicalPositions(nodes: DraftNode[]): Record<string, Pos> {
  const byId = Object.fromEntries(nodes.map(n => [n.id, n])), memo: Record<string, number> = {}
  const visiting = new Set<string>()
  const depth = (id: string): number => {
    if (memo[id] !== undefined) return memo[id]; if (visiting.has(id)) return 0
    visiting.add(id); const n = byId[id]
    memo[id] = !n?.depends_on?.length ? 0 : 1 + Math.max(...n.depends_on.map(d => byId[d] ? depth(d) : 0))
    visiting.delete(id); return memo[id]
  }
  const layers: Record<number, string[]> = {}
  nodes.forEach(n => (layers[depth(n.id)] ||= []).push(n.id))
  const out: Record<string, Pos> = {}
  Object.keys(layers).map(Number).sort((a, b) => a - b).forEach(d => {
    const ids = layers[d], total = ids.length * 145
    ids.forEach((id, i) => { out[id] = { x: 60 + d * 285, y: Math.max(40, 360 - total / 2 + i * 145) } })
  })
  return out
}

export const WorkflowEditor: React.FC<{
  open: boolean; initialTemplate?: TemplateData | null; nodeTypes: NodeType[]
  tools: string[]; departments: string[]; templates?: Array<{ id: string; name: string }>
  onClose: () => void; onSaved: () => void
}> = ({ open, initialTemplate, nodeTypes, tools, departments, templates = [], onClose, onSaved }) => {
  const isMobile = useIsMobile(), editing = Boolean(initialTemplate?.id), canvasRef = useRef<HTMLDivElement | null>(null)
  const [meta, setMeta] = useState({ id: '', name: '', dept: 'seo', description: '', version: '1.0' })
  const [nodes, setNodes] = useState<DraftNode[]>(initialNodes())
  const [positions, setPositions] = useState<Record<string, Pos>>(topologicalPositions(initialNodes()))
  const [active, setActive] = useState('input_1'), [tab, setTab] = useState<'params' | 'test'>('params')
  const [draftNode, setDraftNode] = useState<DraftNode | null>(null), [nodeDirty, setNodeDirty] = useState(false)
  const [drag, setDrag] = useState<{ id: string; sx: number; sy: number; base: Pos } | null>(null)
  const [portDrag, setPortDrag] = useState<PortDrag | null>(null), [checking, setChecking] = useState(false)
  const [issues, setIssues] = useState<string[]>([]), [okMsg, setOkMsg] = useState('')
  const [zoom, setZoom] = useState(1), [fullscreen, setFullscreen] = useState(false), [saving, setSaving] = useState(false)
  // 右侧参数面板展开/折叠
  const [panelOpen, setPanelOpen] = useState(false)
  // 画布平移：中键拖动
  const [pan, setPan] = useState({ x: 0, y: 0 }), [panning, setPanning] = useState<{ sx: number; sy: number; base: { x: number; y: number } } | null>(null)
  // 全局脏标记（模板层面有未保存的改动）
  const [globalDirty, setGlobalDirty] = useState(false)
  // 关闭确认弹窗
  const [confirmClose, setConfirmClose] = useState(false)

  // ---- 生命周期 ----
  useEffect(() => {
    if (!open) return
    const setup = async () => {
      if (initialTemplate?.id) {
        const ns = (initialTemplate.nodes || []).map(normaliseNode)
        const saved = initialTemplate?.metadata?.canvas?.positions || {}
        setMeta({ id: initialTemplate.id, name: initialTemplate.name || initialTemplate.id,
          dept: initialTemplate.dept || 'seo', description: initialTemplate.description || '', version: initialTemplate.version || '1.0' })
        setNodes(ns); setPositions(Object.keys(saved).length ? saved : topologicalPositions(ns)); setActive(ns[0]?.id || '')
        setZoom(Number(initialTemplate?.metadata?.canvas?.viewport?.zoom || 1))
      } else {
        const ns = initialNodes(); let id = ''
        try { const r = await fetch('/api/workflows/templates/id', { method: 'POST' }); id = (await r.json()).template_id || '' } catch { /* surfaced at save */ }
        setMeta({ id, name: '', dept: 'seo', description: '', version: '1.0' })
        setNodes(ns); setPositions(topologicalPositions(ns)); setActive(ns[0].id); setZoom(1)
      }
      setIssues([]); setOkMsg(''); setTab('params'); setNodeDirty(false); setPortDrag(null); setGlobalDirty(false)
      setPan({ x: 0, y: 0 })
    }
    setup()
  }, [open, initialTemplate])

  useEffect(() => {
    const n = nodes.find(x => x.id === active); setDraftNode(n ? { ...n, config: { ...n.config }, acceptance: [...n.acceptance], depends_on: [...n.depends_on] } : null); setNodeDirty(false)
  }, [active, nodes])

  // ---- 画布交互 ----
  useEffect(() => {
    if (!drag) return
    const move = (e: MouseEvent) => { setPositions(p => ({ ...p, [drag.id]: {
      x: Math.max(8, drag.base.x + (e.clientX - drag.sx) / zoom), y: Math.max(8, drag.base.y + (e.clientY - drag.sy) / zoom),
    } })); setGlobalDirty(true) }
    const up = () => setDrag(null); window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [drag, zoom])

  useEffect(() => {
    if (!portDrag) return
    const move = (e: MouseEvent) => {
      const rect = canvasRef.current?.getBoundingClientRect(); if (!rect) return
      setPortDrag(p => p ? { ...p, x: (e.clientX - rect.left - pan.x) / zoom,
        y: (e.clientY - rect.top - pan.y) / zoom } : null)
    }
    const up = () => setPortDrag(null); window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [portDrag, zoom, pan])

  useEffect(() => {
    if (!panning) return
    const move = (e: MouseEvent) => setPan({ x: panning.base.x + (e.clientX - panning.sx), y: panning.base.y + (e.clientY - panning.sy) })
    const up = () => setPanning(null); window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [panning])

  // 滚轮缩放（直接滚动即缩放）
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault(); setZoom(z => Math.max(.3, Math.min(2.5, +(z - e.deltaY * .0015).toFixed(2))))
  }

  // ---- 节点操作 ----
  const spec = (t: string) => nodeTypes.find(n => n.id === t)
  const patchDraft = (patch: Partial<DraftNode>) => { if (!draftNode) return; setDraftNode({ ...draftNode, ...patch }); setNodeDirty(true); setGlobalDirty(true) }
  const saveNode = () => {
    if (!draftNode) return
    const oldId = active, newId = draftNode.id.trim()
    if (!/^[a-z][a-z0-9_]{1,39}$/.test(newId)) { setIssues(['节点 ID 必须是小写字母开头的 2-40 位标识']); return }
    if (newId !== oldId && nodes.some(n => n.id === newId)) { setIssues([`节点 ID ${newId} 已存在`]); return }
    setNodes(ns => ns.map(n => n.id === oldId ? { ...draftNode, id: newId } : { ...n, depends_on: n.depends_on.map(d => d === oldId ? newId : d) }))
    setPositions(p => { if (newId === oldId) return p; const out = { ...p }; out[newId] = out[oldId]; delete out[oldId]; return out })
    setActive(newId); setNodeDirty(false); setOkMsg(`节点 ${newId} 已保存到草稿`); setIssues([])
  }
  const selectNode = (id: string) => {
    if (nodeDirty && id !== active) { setIssues(['当前节点内容尚未保存，请先点击"保存节点"']); return }
    setActive(id)
  }
  const addNode = (type: string) => {
    if (type === 'input' && nodes.some(n => n.type === 'input')) { setIssues(['每个模板只能有一个输入节点']); return }
    let seq = 1, id = `${type}_${seq}`; while (nodes.some(n => n.id === id)) id = `${type}_${++seq}`
    const n = makeNode(id, type, spec(type)?.label || type); setNodes(ns => [...ns, n]); setGlobalDirty(true)
    setPositions(p => ({ ...p, [id]: { x: 80 + (nodes.length % 5) * 240, y: 90 + Math.floor(nodes.length / 5) * 150 } })); setActive(id)
  }
  const removeNode = (id: string) => {
    const rest = nodes.filter(n => n.id !== id).map(n => ({ ...n, depends_on: n.depends_on.filter(d => d !== id) }))
    if (!rest.length) return; setNodes(rest); setGlobalDirty(true)
    setPositions(p => { const out = { ...p }; delete out[id]; return out }); setActive(rest[0].id)
  }
  const connect = (source: string, target: string) => {
    if (!source || source === target) return
    const s = nodes.find(n => n.id === source), t = nodes.find(n => n.id === target)
    if (!s || !t || s.type === 'output' || t.type === 'input') { setIssues(['输出节点不能连接下游；输入节点不能连接上游']); return }
    if (!t.depends_on.includes(source)) { setNodes(ns => ns.map(n => n.id === target ? { ...n, depends_on: [...n.depends_on, source] } : n)); setGlobalDirty(true) }
    setPortDrag(null); setActive(target); setIssues([])
  }
  const disconnect = (source: string, target: string) => { setNodes(ns => ns.map(n => n.id === target ? { ...n, depends_on: n.depends_on.filter(d => d !== source) } : n)); setGlobalDirty(true) }
  // 卡片内联编辑：直接更新节点列表（跳过草稿，但标记全局脏）
  const inlinePatch = (id: string, patch: Partial<DraftNode>) => { setNodes(ns => ns.map(n => n.id === id ? { ...n, ...patch, config: patch.config ? { ...n.config, ...patch.config } : n.config } : n)); setGlobalDirty(true); if (draftNode?.id === id) setDraftNode(d => d ? { ...d, ...patch, config: patch.config ? { ...d.config, ...patch.config } : d.config } : null) }
  const autoLayout = () => { setPositions(topologicalPositions(nodes)); setGlobalDirty(true) }

  // ---- 尝试关闭：脏检测 ----
  const tryClose = () => {
    if (globalDirty || nodeDirty) setConfirmClose(true)
    else onClose()
  }

  const payload = () => ({ ...meta, name: meta.name.trim() || '未命名工作流',
    metadata: { ...(initialTemplate?.metadata || {}), canvas: { positions, viewport: { zoom } } }, tags: initialTemplate?.tags || [],
    nodes: nodes.map(n => ({ ...n, title: n.title.trim() || n.id, acceptance: n.acceptance.filter(a => a.trim()),
      config: Object.fromEntries(Object.entries(n.config).filter(([, v]) => String(v ?? '').trim())), timeout_hours: Number(n.timeout_hours) || 24 })),
  })

  const validate = async (): Promise<boolean> => {
    if (nodeDirty) { setIssues(['先保存当前节点，再校验模板']); return false }
    setChecking(true); setIssues([]); setOkMsg('')
    try {
      const r = await fetch('/api/workflows/templates/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) })
      const j = await r.json().catch(() => ({})); const errs = j.error ? [String(j.error)] : j.detail ? [String(j.detail)] : []
      if (!r.ok || j.valid === false || errs.length) { setIssues(errs.length ? errs : [`校验失败 HTTP ${r.status}`]); return false }
      setOkMsg(`校验通过 · ${j.summary?.layer_count || 0} 层 · 最大并行 ${j.summary?.max_parallel || 0}`); return true
    } catch (e) { setIssues([`校验请求异常: ${e}`]); return false } finally { setChecking(false) }
  }

  const save = async () => {
    if (!(await validate())) return; setSaving(true)
    try {
      const r = await fetch(editing ? `/api/workflows/templates/${meta.id}` : '/api/workflows/templates', {
        method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()),
      }); const j = await r.json().catch(() => ({}))
      if (!r.ok) { setIssues([`保存失败: ${typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || r.status)}`]); return }
      setOkMsg(`模板 ${meta.id} 已保存`); setGlobalDirty(false); onSaved(); onClose()
    } catch (e) { setIssues([`保存请求异常: ${e}`]) } finally { setSaving(false) }
  }

  // ---- 渲染辅助 ----
  const canvasW = Math.max(1500, ...Object.values(positions).map(p => p.x + NODE_W + 100)), canvasH = Math.max(720, ...Object.values(positions).map(p => p.y + NODE_H + 100))
  const edges = useMemo(() => nodes.flatMap(n => n.depends_on.map(d => ({ source: d, target: n.id }))), [nodes])
  const line = (source: string, target: string) => {
    const a = positions[source], b = positions[target]; if (!a || !b) return ''
    const x1 = a.x + NODE_W, y1 = a.y + 56, x2 = b.x, y2 = b.y + 56, c = Math.max(70, Math.abs(x2 - x1) * .45)
    return `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`
  }

  // ---- 浮动提示（替代全屏模式下的底部固定块） ----
  const toast = (issues.length > 0 || okMsg)
    ? <div style={{ position: fullscreen ? 'fixed' : 'relative', ...(fullscreen ? { top: 8, right: 8, zIndex: 1001 } : { marginTop: 9 }),
        minWidth: 280, maxWidth: 400, background: issues.length > 0 ? '#1f1315' : '#0f1f19',
        border: `1px solid ${issues.length > 0 ? '#7f1d1d' : '#065f46'}`, borderRadius: 6, padding: 9 }}>
      {issues.map((x, i) => <div key={i} style={{ color: '#fca5a5', fontSize: 11 }}>· {x}</div>)}
      {okMsg && <div style={{ color: '#6ee7b7', fontSize: 11 }}>✓ {okMsg}</div>}
    </div>
    : null

  // ---- 全屏模式 ----
  if (fullscreen) return <>
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: '#07101f', display: 'flex', flexDirection: 'column' }}
      onMouseDown={e => { if (e.button === 1) { e.preventDefault(); setPanning({ sx: e.clientX, sy: e.clientY, base: pan }) } }}>
      {/* 顶部工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#94a3b8', fontSize: 10, marginRight: 8 }}>{meta.name || meta.id || '新模板'} · 中键拖动 · 滚轮缩放</span>
          {nodeTypes.map(t => <button key={t.id} onClick={() => addNode(t.id)} style={btn(NODE_COLOR[t.id] || '#334155')}>＋ {t.label}</button>)}
          <button onClick={autoLayout} style={btn('#334155')}>自动布局</button>
          <button onClick={() => setZoom(z => Math.max(.3, +(z - .1).toFixed(1)))} style={btn('#334155')}>−</button>
          <span style={{ color: '#94a3b8', fontSize: 10 }}>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom(z => Math.min(2.5, +(z + .1).toFixed(1)))} style={btn('#334155')}>＋</button>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={validate} disabled={checking || nodeDirty} style={btn('#334155')}>{checking ? '校验中…' : '测试 DAG'}</button>
          <button onClick={save} disabled={saving || checking || nodeDirty} style={btn('#2563eb')}>{saving ? '保存中…' : '保存'}</button>
          <button onClick={() => setFullscreen(false)} style={btn('#334155')}>退出全屏</button>
        </div>
      </div>
      {/* 画布区 */}
      <div ref={canvasRef} style={{ position: 'relative', flex: 1, overflow: 'hidden' }} onWheel={handleWheel}>
        <div style={{ position: 'absolute', width: canvasW, height: canvasH, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: '0 0',
          backgroundImage: 'radial-gradient(#263247 1px, transparent 1px)', backgroundSize: '20px 20px' }}>
          <CanvasSVG edges={edges} positions={positions} line={line} portDrag={portDrag} disconnect={disconnect} />
          {nodes.map(n => <NodeCard key={n.id} n={n} active={active === n.id} spec={spec} positions={positions} nodes={nodes}
            portDrag={portDrag} onSelect={selectNode} onDrag={setDrag} onPortDown={setPortDrag} onPortUp={connect} onPatch={inlinePatch} />)}
        </div>
        {/* 右侧参数面板 — 垂直居中 */}
        {panelOpen && draftNode && <div style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', width: 320, maxHeight: '70vh', background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 12, overflowY: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,.5)' }}>
          <NodeEditor draftNode={draftNode} tab={tab} setTab={setTab} patchDraft={patchDraft} saveNode={saveNode} removeNode={removeNode} active={active}
            nodeTypes={nodeTypes} tools={tools} departments={departments} templates={templates} meta={meta} nodeDirty={nodeDirty} spec={spec} />
        </div>}
        {/* 折叠/展开按钮 — 垂直居中 */}
        <button onClick={() => setPanelOpen(v => !v)} style={{ position: 'absolute', right: panelOpen ? 338 : 0, top: '50%', transform: 'translateY(-50%)', zIndex: 1002,
          width: 24, height: 48, borderRadius: '8px 0 0 8px', border: '1px solid #1e293b', borderRight: 0, background: '#0f172a', color: '#94a3b8',
          cursor: 'pointer', fontSize: 11, transition: 'right .2s' }} title={panelOpen ? '折叠参数面板' : '展开参数面板'}>
          {panelOpen ? '▶' : '◀'}
        </button>
      </div>
      {toast}
    </div>
  </>

  return (
    <Modal open={open} title={editing ? `编辑模板 · ${meta.name || meta.id}` : '创建工作流模板'}
      subtitle="拖动卡片 · 从输出端拖到输入端连线 · 点击连线删除 · 中键拖画布 · Alt+滚轮缩放"
      width={1500} onClose={tryClose} closeOnBackdrop={false} closeOnEscape={false}
      footer={<>
        <span style={{ fontSize: 10, color: globalDirty ? '#fbbf24' : '#475569', marginRight: 'auto' }}>{globalDirty ? '● 有未保存修改' : ''}</span>
        <button onClick={() => setFullscreen(v => !v)} style={btn('#334155')}>全屏</button>
        <button onClick={validate} disabled={checking || nodeDirty} style={btn('#334155')}>{checking ? '校验中…' : '测试 DAG'}</button>
        <button onClick={save} disabled={saving || checking || nodeDirty} style={btn(nodeDirty ? '#334155' : '#2563eb')}>{saving ? '保存中…' : editing ? '保存模板' : '创建模板'}</button>
      </>}>
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 130px', gap: 8 }}>
        <Field label="模板 ID" hint="系统自动生成"><input disabled value={meta.id || '正在生成…'} style={inputStyle} /></Field>
        <Field label="显示名"><input value={meta.name} onChange={e => { setMeta({ ...meta, name: e.target.value }); setGlobalDirty(true) }} style={inputStyle} /></Field>
        <Field label="版本"><input value={meta.version} onChange={e => { setMeta({ ...meta, version: e.target.value }); setGlobalDirty(true) }} style={inputStyle} /></Field>
      </div>
      <Field label="说明"><input value={meta.description} onChange={e => { setMeta({ ...meta, description: e.target.value }); setGlobalDirty(true) }} style={inputStyle} /></Field>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        {nodeTypes.map(t => <button key={t.id} onClick={() => addNode(t.id)} style={btn(NODE_COLOR[t.id] || '#334155')}>＋ {t.label}</button>)}
        <button onClick={autoLayout} style={btn('#334155')}>自动布局</button>
        <button onClick={() => setZoom(z => Math.max(.4, +(z - .1).toFixed(1)))} style={btn('#334155')}>−</button>
        <span style={{ color: '#94a3b8', fontSize: 10 }}>{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(z => Math.min(2, +(z + .1).toFixed(1)))} style={btn('#334155')}>＋</button>
        <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }} style={btn('#334155')}>重置</button>
        {nodeDirty && <span style={{ color: '#fbbf24', fontSize: 10 }}>● 当前节点未保存</span>}
        <span style={{ marginLeft: 'auto', color: '#64748b', fontSize: 10 }}>中键拖画布 · 滚轮缩放</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: panelOpen ? (isMobile ? '1fr' : 'minmax(0,1fr) 340px') : '1fr', gap: 10, transition: 'grid-template-columns .2s' }}>
        <div ref={canvasRef} style={{ height: 640, overflow: 'hidden', background: '#07101f', border: '1px solid #1e293b', borderRadius: 8 }}
          onMouseDown={e => { if (e.button === 1) { e.preventDefault(); setPanning({ sx: e.clientX, sy: e.clientY, base: pan }) } }} onWheel={handleWheel}>
          <div style={{ position: 'relative', width: canvasW, height: canvasH, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: '0 0',
            backgroundImage: 'radial-gradient(#263247 1px, transparent 1px)', backgroundSize: '20px 20px' }}>
            <CanvasSVG edges={edges} positions={positions} line={line} portDrag={portDrag} disconnect={disconnect} />
            {nodes.map(n => <NodeCard key={n.id} n={n} active={active === n.id} spec={spec} positions={positions} nodes={nodes}
              portDrag={portDrag} onSelect={selectNode} onDrag={setDrag} onPortDown={setPortDrag} onPortUp={connect} onPatch={inlinePatch} />)}
          </div>
        </div>
        {panelOpen && <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 11, minHeight: 640, overflowY: 'auto', maxHeight: 640 }}>
          {!draftNode ? <div style={{ color: '#64748b' }}>选择一个节点</div> :
            <NodeEditor draftNode={draftNode} tab={tab} setTab={setTab} patchDraft={patchDraft} saveNode={saveNode} removeNode={removeNode} active={active}
              nodeTypes={nodeTypes} tools={tools} departments={departments} templates={templates} meta={meta} nodeDirty={nodeDirty} spec={spec} />}
        </div>}
      </div>
      {/* 非全屏模式：inline 折叠/展开按钮 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
        <button onClick={() => setPanelOpen(v => !v)} style={{ ...btn('#334155'), fontSize: 10 }}>
          {panelOpen ? '▶ 折叠参数面板' : '◀ 展开参数面板'}
        </button>
      </div>
      {toast}

      {/* 关闭确认 —— 有未保存改动时弹出 */}
      {confirmClose && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 100001, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={e => e.stopPropagation()}>
          <div style={{ background: '#111827', border: '1px solid #334155', borderRadius: 10, padding: 20, maxWidth: 380 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f3f4f6', marginBottom: 8 }}>有未保存的修改</div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 16 }}>关闭将丢弃当前所有改动（节点位置、连线、参数等）。确定放弃吗？</div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setConfirmClose(false)} style={btn('#2563eb')}>继续编辑</button>
              <button onClick={() => { setConfirmClose(false); setGlobalDirty(false); setNodeDirty(false); onClose() }} style={btn('#7f1d1d')}>放弃修改</button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ============ Canvas SVG ============
const CanvasSVG: React.FC<{
  edges: { source: string; target: string }[]; positions: Record<string, Pos>
  line: (s: string, t: string) => string; portDrag: PortDrag | null
  disconnect: (s: string, t: string) => void
}> = ({ edges, positions, line, portDrag, disconnect }) => (
  <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
    {edges.map(e => <g key={`${e.source}-${e.target}`}>
      <path d={line(e.source, e.target)} stroke="#64748b" strokeWidth="2" fill="none" />
      <path d={line(e.source, e.target)} stroke="transparent" strokeWidth="14" fill="none"
        style={{ pointerEvents: 'stroke', cursor: 'pointer' }} onClick={() => disconnect(e.source, e.target)} />
    </g>)}
    {portDrag && positions[portDrag.source] &&
      <path d={`M ${positions[portDrag.source].x + NODE_W} ${positions[portDrag.source].y + 56} L ${portDrag.x} ${portDrag.y}`}
        stroke="#60a5fa" strokeWidth="2" strokeDasharray="5 4" fill="none" />}
  </svg>
)

// ============ Node Card (内联可编辑) ============
const NodeCard: React.FC<{
  n: DraftNode; active: boolean; spec: (t: string) => any; positions: Record<string, Pos>
  nodes: DraftNode[]; portDrag: PortDrag | null
  onSelect: (id: string) => void; onDrag: (d: any) => void
  onPortDown: (p: PortDrag) => void; onPortUp: (source: string, target: string) => void
  onPatch: (id: string, patch: Partial<DraftNode>) => void
}> = ({ n, active, spec, positions, nodes, portDrag, onSelect, onDrag, onPortDown, onPortUp, onPatch }) => {
  const p = positions[n.id] || { x: 50, y: 50 }, color = NODE_COLOR[n.type] || '#64748b'
  const [expanded, setExpanded] = useState(true)
  // 卡片内联可编辑的关键字段
  const reqConfig = spec(n.type)?.required_config || []
  return (
    <div onClick={() => onSelect(n.id)} style={{ position: 'absolute', left: p.x, top: p.y, width: NODE_W,
      background: active ? '#13213a' : '#0f172a', border: `1px solid ${active ? color : '#334155'}`, borderTop: `3px solid ${color}`,
      borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,.35)', boxSizing: 'border-box', userSelect: 'none' }}>
      <div onMouseDown={e => { e.stopPropagation(); onDrag({ id: n.id, sx: e.clientX, sy: e.clientY, base: p }) }}
        style={{ padding: '7px 10px 4px', cursor: 'grab', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <input value={n.title} onClick={e => e.stopPropagation()} onChange={e => onPatch(n.id, { title: e.target.value })}
          style={{ background: 'transparent', border: 0, color: '#e2e8f0', fontSize: 11, fontWeight: 700, outline: 'none', width: 130, padding: 0 }} />
        <span style={{ color, fontSize: 8, flexShrink: 0 }}>{spec(n.type)?.label || n.type}</span>
      </div>
      <div style={{ padding: '0 10px', color: '#64748b', fontSize: 9, fontFamily: 'monospace' }}>{n.id}</div>
      <div style={{ padding: '3px 10px', color: '#94a3b8', fontSize: 9, display: 'flex', justifyContent: 'space-between' }}>
        <span>入 {n.depends_on.length} · 出 {nodes.filter(x => x.depends_on.includes(n.id)).length}</span>
        {reqConfig.length > 0 && <button onClick={e => { e.stopPropagation(); setExpanded(v => !v) }} style={{ background: 'transparent', border: 0, color: expanded ? '#60a5fa' : '#64748b', cursor: 'pointer', fontSize: 9, padding: 0 }}>{expanded ? '▲ 收起' : '▼ 展开'}</button>}
      </div>
      {/* 内联必填字段 — 展开时直接显示 */}
      {expanded && reqConfig.length > 0 && <div style={{ padding: '6px 10px', borderTop: '1px solid #1e2937', marginTop: 4 }} onClick={e => e.stopPropagation()}>
        {reqConfig.map((k: string) => <div key={k} style={{ marginBottom: 5 }}>
          <span style={{ fontSize: 8, color: '#64748b', display: 'block', marginBottom: 2 }}>{k}</span>
          {k === 'tool' ? <select value={n.config[k] || ''} onChange={e => onPatch(n.id, { config: { ...n.config, [k]: e.target.value } })} style={{ ...inputStyle, fontSize: 9, padding: '3px 5px', width: '100%' }}><option value="">…</option></select>
          : k === 'dept' ? <select value={n.config[k] || ''} onChange={e => onPatch(n.id, { config: { ...n.config, [k]: e.target.value } })} style={{ ...inputStyle, fontSize: 9, padding: '3px 5px', width: '100%' }}><option value="">…</option><option value="seo">seo</option></select>
          : (k === 'instruction' || k === 'prompt' || k === 'command') ? <textarea rows={2} value={n.config[k] || ''} onChange={e => onPatch(n.id, { config: { ...n.config, [k]: e.target.value } })} style={{ ...inputStyle, fontSize: 9, padding: '3px 5px', resize: 'none', width: '100%' }} />
          : <input value={n.config[k] || ''} onChange={e => onPatch(n.id, { config: { ...n.config, [k]: e.target.value } })} style={{ ...inputStyle, fontSize: 9, padding: '3px 5px', width: '100%' }} />}
        </div>)}
      </div>}
      {/* 收起时留底部间距 */}
      {!expanded && <div style={{ height: 6 }} />}
      {n.type !== 'input' && <button title="输入端：松开完成连线" onMouseUp={e => { e.stopPropagation(); if (portDrag) onPortUp(portDrag.source, n.id) }}
        style={{ position: 'absolute', left: -8, top: 48, width: 16, height: 16, padding: 0, borderRadius: '50%', border: '2px solid #94a3b8', background: portDrag ? '#1d4ed8' : '#0f172a', cursor: 'crosshair' }} />}
      {n.type !== 'output' && <button title="输出端：按住拖动" onMouseDown={e => { e.stopPropagation(); onPortDown({ source: n.id, x: p.x + NODE_W, y: p.y + 56 }) }}
        style={{ position: 'absolute', right: -8, top: 48, width: 16, height: 16, padding: 0, borderRadius: '50%', border: `2px solid ${color}`, background: portDrag?.source === n.id ? color : '#0f172a', cursor: 'crosshair' }} />}
    </div>
  )
}

// ============ Node Editor Panel ============
const NodeEditor: React.FC<{
  draftNode: DraftNode; tab: 'params' | 'test'; setTab: (t: 'params' | 'test') => void
  patchDraft: (p: Partial<DraftNode>) => void; saveNode: () => void; removeNode: (id: string) => void; active: string
  nodeTypes: NodeType[]; tools: string[]; departments: string[]; templates: Array<{ id: string; name: string }>; meta: any
  nodeDirty: boolean; spec: (t: string) => any
}> = ({ draftNode, tab, setTab, patchDraft, saveNode, removeNode, active, nodeTypes, tools, departments, templates, meta, nodeDirty, spec }) => {
  const inputMode = draftNode.type === 'input'
  const outputMode = draftNode.type === 'output'
  const isAgentType = !['input', 'output'].includes(draftNode.type)

  return <>
    <div style={{ display: 'flex', gap: 5, marginBottom: 10 }}>
      <button onClick={() => setTab('params')} style={btn(tab === 'params' ? '#2563eb' : '#334155')}>参数</button>
      <button onClick={() => setTab('test')} style={btn(tab === 'test' ? '#2563eb' : '#334155')}>测试设置</button>
    </div>

    {tab === 'params' ? <>
      <Field label="节点 ID"><input value={draftNode.id} onChange={e => patchDraft({ id: e.target.value })} style={inputStyle} /></Field>
      <Field label="标题"><input value={draftNode.title} onChange={e => patchDraft({ title: e.target.value })} style={inputStyle} /></Field>
      <Field label="类型">
        <input disabled value={nodeTypes.find(t => t.id === draftNode.type)?.label || draftNode.type} style={{ ...inputStyle, opacity: 0.6, cursor: 'not-allowed' }} />
      </Field>

      {/* ---- 输入节点 ---- */}
      {inputMode && <>
        <Field label="输入模式">
          <select value={draftNode.config.input_mode || 'none'} onChange={e => patchDraft({ config: { ...draftNode.config, input_mode: e.target.value } })} style={inputStyle}>
            <option value="none">无输入</option><option value="direct">实例输入参数</option><option value="workflow">已有工作流</option>
          </select>
        </Field>
        {draftNode.config.input_mode === 'direct' && <InputParamSchemaEditor draftNode={draftNode} patchDraft={patchDraft} />}
        {draftNode.config.input_mode === 'workflow' && <Field label="已有工作流">
          <select value={draftNode.config.workflow_id || ''} onChange={e => patchDraft({ config: { ...draftNode.config, workflow_id: e.target.value } })} style={inputStyle}>
            <option value="">请选择…</option>{templates.filter(t => t.id !== meta.id).map(t => <option key={t.id} value={t.id}>{t.name} ({t.id})</option>)}
          </select>
        </Field>}
      </>}

      {/* ---- 输出节点 ---- */}
      {outputMode && <>
        <Field label="输出模式">
          <select value={draftNode.config.output_mode || 'end'} onChange={e => patchDraft({ config: { ...draftNode.config, output_mode: e.target.value } })} style={inputStyle}>
            <option value="end">结束</option><option value="result">输出结果</option><option value="boolean">真假结果</option>
            <option value="webhook">发送至 Webhook</option><option value="agent">Agent 协作输出</option>
          </select>
        </Field>
        {draftNode.config.output_mode === 'boolean' && <Field label="真假值">
          <select value={String(draftNode.config.boolean_value ?? 'true')} onChange={e => patchDraft({ config: { ...draftNode.config, boolean_value: e.target.value } })} style={inputStyle}>
            <option value="true">True</option><option value="false">False</option>
          </select>
        </Field>}
        {draftNode.config.output_mode === 'webhook' && <WebhookFields draftNode={draftNode} patchDraft={patchDraft} />}
        {draftNode.config.output_mode === 'agent' && <Field label="Agent 指令" hint="描述需要的格式、内容等要求">
          <textarea rows={4} value={draftNode.config.agent_instruction || ''} onChange={e => patchDraft({ config: { ...draftNode.config, agent_instruction: e.target.value } })} placeholder="例如：将上游结果整理为 Markdown 格式的周报，包含数据表格和趋势分析" style={{ ...inputStyle, resize: 'vertical' }} />
        </Field>}
      </>}

      {/* ---- Agent/Tool/Dept 节点：模型配置 ---- */}
      {isAgentType && (spec(draftNode.type)?.required_config || []).map((k: string) =>
        <Field key={k} label={`${k}（必填）`}>
          {k === 'tool' ? <select value={draftNode.config[k] || ''} onChange={e => patchDraft({ config: { ...draftNode.config, [k]: e.target.value } })} style={inputStyle}><option value="">选择工具…</option>{tools.map(t => <option key={t}>{t}</option>)}</select>
          : k === 'dept' ? <select value={draftNode.config[k] || ''} onChange={e => patchDraft({ config: { ...draftNode.config, [k]: e.target.value } })} style={inputStyle}><option value="">选择部门…</option>{departments.map(d => <option key={d}>{d}</option>)}</select>
          : (k === 'instruction' || k === 'prompt' || k === 'command') ? <textarea rows={4} value={draftNode.config[k] || ''} onChange={e => patchDraft({ config: { ...draftNode.config, [k]: e.target.value } })} style={{ ...inputStyle, resize: 'vertical' }} />
          : <input value={draftNode.config[k] || ''} onChange={e => patchDraft({ config: { ...draftNode.config, [k]: e.target.value } })} style={inputStyle} />}
        </Field>
      )}

      {/* ---- 模型/推理强度选择（仅 agent_task 和 dept_request） ---- */}
      {(draftNode.type === 'agent_task' || draftNode.type === 'dept_request') && <>
        <div style={{ borderTop: '1px solid #1e293b', margin: '10px 0 8px', paddingTop: 8 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8' }}>模型配置（可选，留空用部门/系统默认）</span>
        </div>
        <Field label="Provider">
          <select value={draftNode.config.provider || ''} onChange={e => patchDraft({ config: { ...draftNode.config, provider: e.target.value, model: '', reasoning_effort: '' } })} style={inputStyle}>
            <option value="">默认</option>{Object.entries(PROVIDER_MODELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </Field>
        {draftNode.config.provider && <Field label="模型名">
          <input value={draftNode.config.model || ''} onChange={e => patchDraft({ config: { ...draftNode.config, model: e.target.value } })} placeholder="如 glm-5.2 / gpt-5.6-sol" style={inputStyle} />
        </Field>}
        {draftNode.config.provider && <Field label="推理强度" hint={PROVIDER_MODELS[draftNode.config.provider]?.label || ''}>
          <select value={draftNode.config.reasoning_effort || ''} onChange={e => patchDraft({ config: { ...draftNode.config, reasoning_effort: e.target.value } })} style={inputStyle}>
            {PROVIDER_MODELS[draftNode.config.provider]?.efforts.map(e => <option key={e.value} value={e.value}>{e.label}</option>) || <option value="">默认</option>}
          </select>
        </Field>}
      </>}
    </> : <>
      <Field label="验收标准" hint={spec(draftNode.type)?.acceptance_required ? '必填' : '可选；设置后必须通过才能完成'}>
        {draftNode.acceptance.map((a, i) => <div key={i} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
          <input value={a} onChange={e => { const arr = [...draftNode.acceptance]; arr[i] = e.target.value; patchDraft({ acceptance: arr }) }} style={inputStyle} />
          <button onClick={() => patchDraft({ acceptance: draftNode.acceptance.filter((_, k) => k !== i) })} style={btn('#7f1d1d')}>×</button>
        </div>)}
        <button onClick={() => patchDraft({ acceptance: [...draftNode.acceptance, ''] })} style={btn('#334155')}>＋ 添加验收</button>
      </Field>
      <Field label="失败处理">
        <select value={draftNode.on_failure} onChange={e => patchDraft({ on_failure: e.target.value })} style={inputStyle}>
          <option value="stop">停止流程</option><option value="continue">独立分支继续</option><option value="escalate">升级处理</option>
        </select>
      </Field>
      <Field label="超时（小时）"><input type="number" min={1} value={draftNode.timeout_hours} onChange={e => patchDraft({ timeout_hours: Number(e.target.value) })} style={inputStyle} /></Field>
    </>}

    <div style={{ borderTop: '1px solid #1e293b', marginTop: 12, paddingTop: 8 }}>
      <button onClick={saveNode} disabled={!nodeDirty} style={{ ...btn(nodeDirty ? '#047857' : '#334155'), width: '100%' }}>保存节点</button>
      <button onClick={() => removeNode(active)} style={{ ...btn('#7f1d1d'), marginTop: 6, width: '100%' }}>删除节点</button>
    </div>
  </>
}


// ============ 飞书群预设 (webhook 目标群 + webhook 地址 + 签名) ============
// 一个群绑定一套 webhook 信息，选中即自动填入
type GroupPreset = { chat_id: string; name: string; webhook_url?: string; webhook_signature?: string }

const BUILTIN_GROUPS: GroupPreset[] = [
  { chat_id: "oc_26a08f6d203173ad35e68f8583a08729", name: "IGORSEO 群", webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/547bbe86-daa8-4fdc-aae2-9dfb5679bcc4" },
  { chat_id: "oc_9def38914084900857e69171b359c195", name: "总办群" },
  { chat_id: "oc_416b8200000000000000000000000000", name: "开发群" },
  { chat_id: "oc_341c6c0a000000000000000000000000", name: "通知群" },
  { chat_id: "oc_b8ace6c0a00000000000000000000000", name: "运维群" },
  { chat_id: "oc_8a3924592c01a16b7723823e7946148d", name: "协同群" },
]

function getCustomGroups(): GroupPreset[] {
  try { return JSON.parse(localStorage.getItem('wf_custom_groups') || '[]') } catch { return [] }
}
function saveCustomGroups(list: GroupPreset[]) {
  localStorage.setItem('wf_custom_groups', JSON.stringify(list))
}

function getAllGroups(): GroupPreset[] {
  const custom = getCustomGroups()
  const seen = new Set(BUILTIN_GROUPS.map(g => g.chat_id))
  return [...BUILTIN_GROUPS, ...custom.filter(g => !seen.has(g.chat_id))]
}

// 群选择器组件 — 选中群后自动填入 webhook_url + 签名
const GroupPicker: React.FC<{
  selected: string
  onSelect: (group: GroupPreset) => void
}> = ({ selected, onSelect }) => {
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState('')
  const [newId, setNewId] = useState('')
  const [newWebhook, setNewWebhook] = useState('')
  const [newSig, setNewSig] = useState('')
  const groups = getAllGroups()
  const selectedGroup = groups.find(g => g.chat_id === selected)

  const addGroup = () => {
    if (!newName.trim() || !newId.trim()) return
    const custom = getCustomGroups()
    const exists = [...BUILTIN_GROUPS, ...custom].find(g => g.chat_id === newId.trim())
    if (exists) return
    const preset: GroupPreset = {
      chat_id: newId.trim(),
      name: newName.trim(),
      webhook_url: newWebhook.trim() || undefined,
      webhook_signature: newSig.trim() || undefined,
    }
    custom.push(preset)
    saveCustomGroups(custom)
    onSelect(preset)
    setNewName(''); setNewId(''); setNewWebhook(''); setNewSig(''); setShowAdd(false)
  }

  return <>
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      <select
        value={selected}
        onChange={e => {
          const g = groups.find(x => x.chat_id === e.target.value)
          if (g) onSelect(g)
        }}
        style={{ ...inputStyle, flex: 1 }}
      >
        <option value="">不指定（默认 IGORSEO 群）</option>
        {groups.map(g => <option key={g.chat_id} value={g.chat_id}>{g.name}</option>)}
      </select>
      <button onClick={() => setShowAdd(!showAdd)}
        style={{ ...btn('#334155'), padding: '4px 8px', fontSize: 11, whiteSpace: 'nowrap' }}>
        {showAdd ? '取消' : '+ 新增'}
      </button>
    </div>
    {showAdd && <div style={{ marginTop: 4, padding: 6, border: '1px solid #1e293b', borderRadius: 6 }}>
      <input placeholder="群名称（如：内容部群）" value={newName}
        onChange={e => setNewName(e.target.value)}
        style={{ ...inputStyle, marginBottom: 4 }} />
      <input placeholder="chat_id（oc_ 开头）" value={newId}
        onChange={e => setNewId(e.target.value)}
        style={{ ...inputStyle, marginBottom: 4 }} />
      <input placeholder="Webhook 地址（选 @Agent 时可留空）" value={newWebhook}
        onChange={e => setNewWebhook(e.target.value)}
        style={{ ...inputStyle, marginBottom: 4 }} />
      <input placeholder="签名（可选）" value={newSig}
        onChange={e => setNewSig(e.target.value)}
        style={{ ...inputStyle, marginBottom: 4 }} />
      <button onClick={addGroup} disabled={!newName.trim() || !newId.trim()}
        style={{ ...btn('#047857'), width: '100%', fontSize: 11 }}>
        保存群
      </button>
    </div>}
    {selectedGroup && <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
      {selectedGroup.chat_id}
      {selectedGroup.webhook_url && <span style={{ color: '#22c55e' }}> · 有 webhook</span>}
      {selectedGroup.webhook_signature && <span style={{ color: '#22c55e' }}> · 有签名</span>}
    </div>}
  </>
}

// ============ Agent 联系人簿 (webhook @ 多选) ============
const AGENT_CONTACTS: {id:string;name:string;open_id:string;dept:string;role:string}[] = [{"id": "seo-geo", "name": "GEO与AI搜索专员", "open_id": "ou_dea59944bb5ef22c893b93f876a7a743", "dept": "SEO部", "role": "SEO部·AI 搜索可见性监测与可引用性优化(fb版建队 2026-07-22;"}, {"id": "seo", "name": "SEO 策略师", "open_id": "ou_e0ec0200d61b23ba9461ca1b1a065651", "dept": "SEO部", "role": "SEO/内容增长"}, {"id": "seo-analyst", "name": "SEO数据分析师", "open_id": "ou_4a1b476f85584f202399dbb3433c4111", "dept": "SEO部", "role": "SEO部·SEO 数据管道、基线冻结与效果归因(fb版建队 2026-07-22"}, {"id": "seo-tech", "name": "技术SEO专员", "open_id": "ou_5da0062942922c9866f83773600b6add", "dept": "SEO部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "seo-pr", "name": "数字PR与外链运营", "open_id": "ou_62169e1c0218c021d9d001bdc44ec649", "dept": "SEO部", "role": "SEO部·可链接资产、审批制外联与外链台账(fb版建队 2026-07-22;凭"}, {"id": "main", "name": "HR·人事总监", "open_id": "ou_9a6306fe5496efa8eb544f1b634ad75f", "dept": "人事部", "role": "人事总监：能力档案/选派/模型梯队/考核评级/培训管理。见 🏛️ 公司化运作制度"}, {"id": "skill-trainer", "name": "技能培训师", "open_id": "ou_e135001a6fb5eec718a451612842502a", "dept": "人事部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "editor-in-chief", "name": "新媒体主编", "open_id": "ou_8c78ffb2283d1b28d3733dcb793e613b", "dept": "内容部", "role": "新媒体内容总编：创作大纲骨架（总规划/文章系列/文章概要框架）、创作剧本、编排脚"}, {"id": "writer", "name": "新媒体作家", "open_id": "ou_6932e9ca62cf4bde67595fa890b07dba", "dept": "内容部", "role": "新媒体写作专家：选题策划/爆款标题/多平台文案（公众号·小红书·短视频·知乎）/"}, {"id": "work", "name": "特朗资讯", "open_id": "ou_3628e844d7e25050885c2b87e4a82bf9", "dept": "外部账号", "role": "旧应用账号（特朗资讯），非正式编制。保留兼容 binding。"}, {"id": "cs-director", "name": "客服总监", "open_id": "ou_2b5fe35e6e33ff8fd396e171132b32eb", "dept": "客服部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "charlie-reception", "name": "查理小助手", "open_id": "ou_69d1a3ec0b4e2b72bf7bd32465047ddf", "dept": "客服部", "role": "接待/卡密验证"}, {"id": "reception", "name": "查理智能助手", "open_id": "ou_65a34f9c8552257097fcef3c9b29cb34", "dept": "客服部", "role": "智能客服/知识引导"}, {"id": "butler", "name": "查理统计员", "open_id": "ou_d50d7422a7364baf6636718670c58459", "dept": "客服部", "role": "多维表格/到期/拉群"}, {"id": "charlie-ai", "name": "查理资讯_AI助理", "open_id": "ou_99730369c1cad7bcc7d75e84ee1a0a5a", "dept": "客服部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "api-tester", "name": "API 测试员", "open_id": "ou_4f654c6714254b2604c6ad36d96ecb7c", "dept": "开发部", "role": "端到端测试"}, {"id": "devops", "name": "DevOps 与云运维", "open_id": "ou_04870b1ac676bf6c3b871abafa24aee3", "dept": "开发部", "role": "部署/健康检查/回滚"}, {"id": "code-reviewer", "name": "全栈代码审查官", "open_id": "ou_b2512785f7452fc2096755c3c2f11614", "dept": "开发部", "role": "质量/安全审查"}, {"id": "fullstack", "name": "全栈开发工程师", "open_id": "ou_e102f98184a25851e27bc706e9c69cc1", "dept": "开发部", "role": "前后端实现"}, {"id": "db-optimizer", "name": "数据库优化师", "open_id": "ou_7831b6de47bf5cf92b85cf557558c75e", "dept": "开发部", "role": "数据结构/迁移/索引"}, {"id": "architect", "name": "系统架构师", "open_id": "ou_4ce11fcd7fab053a5c95ef9ba205c2f0", "dept": "开发部", "role": "协作架构/ADR/降级"}, {"id": "task-orchestrator", "name": "任务编排师", "open_id": "ou_abaa049f3d314b23e2164d6e75e5c397", "dept": "总经办", "role": "(org-v2 补录 2026-07-18;open_id 已抓取)"}, {"id": "inspector", "name": "巡察员", "open_id": "ou_9c25c8a0f8ff3cffde926e4316e60ce9", "dept": "总经办", "role": "任务巡查与模型健康监测"}, {"id": "hermes", "name": "查理资讯_Bot", "open_id": "ou_3c67d0b41368867a00b2cf1f26a295b4", "dept": "总经办", "role": "总经理 · 总调度(控制面,非执行编制)"}, {"id": "report-downloader", "name": "情报专员_主管", "open_id": "ou_884464b64c5c05e6ba441bdf613fa4f6", "dept": "情报部", "role": "情报系统：对外资讯搜集/交叉验证/整合交付（【情报需求单】）+ 大屏内容编排 +"}, {"id": "info-analyst", "name": "资讯分析师", "open_id": "ou_0ea394b689a675916e0b8fa0f4f0d6a2", "dept": "情报部", "role": "资讯分析与整理专家"}, {"id": "n8n-operator", "name": "n8n操作师", "open_id": "ou_1d8a94a89ad86615c44691e96e965898", "dept": "技术支撑", "role": "N8N 自动化运维：工作流管理/API集成/定时任务/监控告警"}, {"id": "localization-expert", "name": "本土化运营专家", "open_id": "ou_a5804591355cffe3522c37afe30bdbaa", "dept": "本土化部", "role": "本土化培训部主管"}, {"id": "xianyu", "name": "闲鱼运营助手", "open_id": "ou_c2262071c66c51698d87f0d2a937478e", "dept": "电商部", "role": "闲鱼运营"}, {"id": "ui", "name": "UI 设计师", "open_id": "ou_2b264f5f8e363fd9dd4d965c0d1bc569", "dept": "设计部", "role": "**界面设计归口**（2026-07-09 用户钦定）：yudao 全部界面（v"}, {"id": "ux", "name": "UX 研究员", "open_id": "ou_b7421d0f544c1ecc6e42aeaff88a5f65", "dept": "设计部", "role": "用户体验研究"}, {"id": "visual-painter", "name": "新媒体画家", "open_id": "ou_5f86fc146b45d47b86dd54a96d274d61", "dept": "设计部", "role": "新媒体原创图像生成与语义配图"}, {"id": "visual-creator", "name": "视觉素材设计师", "open_id": "ou_e28be81c3dd075a884552cb6f114a1ee", "dept": "设计部", "role": "视觉素材设计：配图/封面/海报/素材创作"}, {"id": "infra-admin", "name": "基础资产管理员", "open_id": "ou_6e56030a366434e7d34e08b6fa1c7c2c", "dept": "资源部", "role": "基础设施与任务产物资产台账、分类归档、检索和到期监控"}, {"id": "resource", "name": "查理_管家Bot", "open_id": "ou_5789e5121aac7a902e04d13b3ade8767", "dept": "资源部", "role": "管家：LLM/额度/服务器资源归口，响应【资源申请】"}, {"id": "store-ops", "name": "独立站与淘宝运营", "open_id": "ou_00aa23aee46c056a931ff50793e7f4ca", "dept": "运营部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "material-scout", "name": "素材采集专员", "open_id": "ou_50c87f261bef53c6db75a9c30eea13aa", "dept": "运营部", "role": "(org-v2 补录 2026-07-18;open_id 待 bind-dep"}, {"id": "ops-director", "name": "运营总监", "open_id": "ou_dfbd6630b46957efd5f968d84355ddca", "dept": "运营部", "role": "运营部主管"}, {"id": "pm", "name": "高级项目经理", "open_id": "ou_33167648f2f682145b69276e763033f7", "dept": "项目部", "role": "WBS拆解/排期/风险"}]

const DEPT_ORDER = ['总经办','开发部','SEO部','内容部','运营部','客服部','资源部','人事部','项目部','设计部','情报部','电商部','本土化部','技术支撑','外部账号','其他']

const AgentContactPicker: React.FC<{
  selected: string[]
  onChange: (ids: string[]) => void
}> = ({ selected, onChange }) => {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const toggle = (id: string) => {
    if (selected.includes(id)) onChange(selected.filter(x => x !== id))
    else onChange([...selected, id])
  }

  const filtered = AGENT_CONTACTS.filter(c =>
    !query || c.name.toLowerCase().includes(query.toLowerCase()) ||
    c.id.toLowerCase().includes(query.toLowerCase()) ||
    c.dept.includes(query)
  )

  const byDept: Record<string, typeof AGENT_CONTACTS> = {}
  for (const c of filtered) {
    if (!byDept[c.dept]) byDept[c.dept] = []
    byDept[c.dept].push(c)
  }
  const depts = Object.keys(byDept).sort((a, b) =>
    (DEPT_ORDER.indexOf(a) === -1 ? 99 : DEPT_ORDER.indexOf(a)) -
    (DEPT_ORDER.indexOf(b) === -1 ? 99 : DEPT_ORDER.indexOf(b))
  )

  return <>
    <div onClick={() => setOpen(!open)} style={{
      padding: '6px 10px', border: '1px solid #334155', borderRadius: 6,
      cursor: 'pointer', fontSize: 12, display: 'flex', flexWrap: 'wrap',
      gap: 4, minHeight: 34, alignItems: 'center',
      background: selected.length ? 'rgba(37,99,235,.12)' : 'transparent',
    }}>
      {selected.length === 0
        ? <span style={{ opacity: .5 }}>点击选择要 @ 的 Agent（可多选）</span>
        : selected.map(id => {
            const c = AGENT_CONTACTS.find(x => x.id === id)
            return <span key={id} style={{
              padding: '2px 8px', borderRadius: 10, fontSize: 11,
              background: 'rgba(37,99,235,.3)', whiteSpace: 'nowrap',
            }}>{c?.name || id}</span>
          })
      }
      <span style={{ marginLeft: 'auto', opacity: .5, fontSize: 11 }}>{open ? '▲' : '▼'}</span>
    </div>
    {open && <div style={{
      marginTop: 4, border: '1px solid #262b36', borderRadius: 6,
      maxHeight: 300, overflowY: 'auto', background: '#0d1117',
    }}>
      <input placeholder="搜索 agent…" value={query}
        onChange={e => setQuery(e.target.value)}
        style={{ ...inputStyle, margin: 6, width: 'calc(100% - 16px)' }} />
      {selected.length > 0 && <button onClick={() => onChange([])}
        style={{ ...btn('#7f1d1d'), margin: '0 6px 4px', padding: '2px 8px', fontSize: 11 }}>清空选择</button>}
      {depts.map(dept => <div key={dept}>
        <div style={{
          padding: '4px 10px', fontSize: 11, fontWeight: 600,
          color: '#94a3b8', borderBottom: '1px solid #1e293b',
        }}>{dept}</div>
        {byDept[dept].map(c => {
          const on = selected.includes(c.id)
          return <div key={c.id} onClick={() => toggle(c.id)}
            title={c.role}
            style={{
              padding: '5px 10px', cursor: 'pointer', fontSize: 12,
              display: 'flex', alignItems: 'center', gap: 8,
              background: on ? 'rgba(37,99,235,.2)' : 'transparent',
            }}>
            <span style={{ width: 14, textAlign: 'center' }}>{on ? '☑' : '☐'}</span>
            <span>{c.name}</span>
            <span style={{ fontSize: 10, opacity: .5, marginLeft: 'auto' }}>{c.id}</span>
          </div>
        })}
      </div>)}
    </div>}
  </>
}

// ============ Webhook Fields (签名 + 预设) ============
// ============ Global Webhook Presets (localStorage, 所有工作流共享) ============
type WebhookPreset = { name: string; url: string; signature?: string }

function getGlobalPresets(): WebhookPreset[] {
  try { return JSON.parse(localStorage.getItem('wf_webhook_presets') || '[]') } catch { return [] }
}
function saveGlobalPresets(list: WebhookPreset[]) {
  localStorage.setItem('wf_webhook_presets', JSON.stringify(list))
}

const WebhookFields: React.FC<{ draftNode: DraftNode; patchDraft: (p: Partial<DraftNode>) => void }> = ({ draftNode, patchDraft }) => {
  const [presets, setPresets] = useState<WebhookPreset[]>(getGlobalPresets())
  const [newPresetName, setNewPresetName] = useState('')
  const atAgents: string[] = draftNode.config.at_agents || []

  // 选了联系人后自动填 webhook_url 为中转地址
  const updateAgents = (ids: string[]) => {
    // 不再覆盖 webhook_url — 用户始终输入真实地址，后台自动判断是否走中转
    patchDraft({ config: { ...draftNode.config,
      at_agents: ids,
    }})
  }

  const savePreset = (name: string) => {
    if (!name.trim() || !draftNode.config.webhook_url) return
    const next = [...presets.filter(p => p.name !== name.trim()), { name: name.trim(), url: draftNode.config.webhook_url, signature: draftNode.config.webhook_signature || '' }]
    setPresets(next); saveGlobalPresets(next); setNewPresetName('')
  }
  const deletePreset = (name: string) => {
    const next = presets.filter(p => p.name !== name)
    setPresets(next); saveGlobalPresets(next)
  }

  return <>
    <Field label="通知方式" hint="群@ = 发到群里并 @ agent；私聊 = 直接发私聊给 agent">
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          onClick={() => patchDraft({ config: { ...draftNode.config, notify_mode: 'group' } })}
          style={{
            ...btn(draftNode.config.notify_mode === 'private' ? '#334155' : '#047857'),
            flex: 1, fontSize: 12,
          }}>
          群 @
        </button>
        <button
          onClick={() => patchDraft({ config: { ...draftNode.config, notify_mode: 'private' } })}
          style={{
            ...btn(draftNode.config.notify_mode === 'private' ? '#047857' : '#334155'),
            flex: 1, fontSize: 12,
          }}>
          私聊
        </button>
      </div>
    </Field>
    {draftNode.config.notify_mode !== 'private' && <Field label="目标群" hint="选中后自动填入 Webhook 地址和签名；选 @ Agent 时后台走中转">
      <GroupPicker selected={draftNode.config.target_chat_id || ''} onSelect={(g) => patchDraft({ config: { ...draftNode.config, target_chat_id: g.chat_id, webhook_url: g.webhook_url || draftNode.config.webhook_url || '', webhook_signature: g.webhook_signature || draftNode.config.webhook_signature || '' } })} />
    </Field>}
    <Field label="通知 Agent" hint={draftNode.config.notify_mode === 'private' ? '选择要私聊通知的 Agent（私聊不支持 @，只发消息）' : '选择后，后台自动将此 Webhook 切为 @ 中转发送，你填的地址保持不变'}>
      <AgentContactPicker selected={atAgents} onChange={updateAgents} />
    </Field>
    <Field label="Webhook HTTPS 地址" hint="填写飞书群机器人地址；选了 @Agent 时后台自动走中转，地址不用改">
      <input value={draftNode.config.webhook_url || ''} onChange={e => patchDraft({ config: { ...draftNode.config, webhook_url: e.target.value } })} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." style={inputStyle} />
    </Field>
    <Field label="签名" hint="可选；填写后将进行 HMAC-SHA256 签名校验">
      <input value={draftNode.config.webhook_signature || ''} onChange={e => patchDraft({ config: { ...draftNode.config, webhook_signature: e.target.value } })} placeholder="不填写则不校验" style={inputStyle} />
    </Field>
    <Field label="预设" hint="全局共享，所有工作流可用">
      <select value="" onChange={e => {
        if (e.target.value) { const p = JSON.parse(e.target.value); patchDraft({ config: { ...draftNode.config, webhook_url: p.url, webhook_signature: p.signature || '' } }); e.target.selectedIndex = 0 }
      }} style={inputStyle}>
        <option value="">选择预设…</option>{presets.map((p, i) => <option key={i} value={JSON.stringify(p)}>{p.name}</option>)}
      </select>
    </Field>
    {/* 已保存的预设列表 */}
    {presets.length > 0 && <div style={{ marginBottom: 6 }}>
      {presets.map(p => (
        <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3, fontSize: 9 }}>
          <span style={{ color: '#60a5fa', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
          <span style={{ color: '#475569', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.url}</span>
          <button onClick={() => deletePreset(p.name)} style={miniBtnStyle('#7f1d1d', '#fca5a5')}>×</button>
        </div>
      ))}
    </div>}
    {/* 保存当前为预设 */}
    <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
      <input placeholder="预设名称" value={newPresetName} onChange={e => setNewPresetName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') savePreset(newPresetName) }} style={{ ...inputStyle, flex: 1 }} />
      <button onClick={() => savePreset(newPresetName)} disabled={!draftNode.config.webhook_url} style={btn('#334155')}>存为预设</button>
    </div>
    <Field label="Agent 协作输出" hint="可选；启用后 Agent 参与 Webhook 内容生成">
      <select value={draftNode.config.webhook_agent_enabled ? 'yes' : 'no'} onChange={e => patchDraft({ config: { ...draftNode.config, webhook_agent_enabled: e.target.value === 'yes' } })} style={inputStyle}>
        <option value="no">不启用</option><option value="yes">启用 Agent 协作</option>
      </select>
    </Field>
    {draftNode.config.webhook_agent_enabled && <Field label="Agent 协作指令" hint="描述需要 Agent 生成的内容格式与要求">
      <textarea rows={3} value={draftNode.config.webhook_agent_instruction || ''} onChange={e => patchDraft({ config: { ...draftNode.config, webhook_agent_instruction: e.target.value } })} placeholder="例如：将上游数据格式化为 JSON，包含 title、url、summary 字段" style={{ ...inputStyle, resize: 'vertical' }} />
    </Field>}
  </>
}

// ============ Input Parameter Schema Editor ============
type ParamSchema = { name: string; type: string; description: string; required: boolean; default: string }
const PARAM_TYPES = ['str', 'int', 'float', 'bool', 'json']

const InputParamSchemaEditor: React.FC<{ draftNode: DraftNode; patchDraft: (p: Partial<DraftNode>) => void }> = ({ draftNode, patchDraft }) => {
  const params: ParamSchema[] = draftNode.config.input_params_schema || []

  const updateParam = (i: number, patch: Partial<ParamSchema>) => {
    const next = params.map((p, idx) => idx === i ? { ...p, ...patch } : p)
    patchDraft({ config: { ...draftNode.config, input_params_schema: next } })
  }
  const addParam = () => {
    patchDraft({ config: { ...draftNode.config, input_params_schema: [...params, { name: '', type: 'str', description: '', required: true, default: '' }] } })
  }
  const removeParam = (i: number) => {
    patchDraft({ config: { ...draftNode.config, input_params_schema: params.filter((_, idx) => idx !== i) } })
  }

  return <>
    <div style={{ borderTop: '1px solid #1e293b', margin: '8px 0 6px', paddingTop: 8 }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8' }}>输入参数定义</span>
      <span style={{ fontSize: 9, color: '#475569', marginLeft: 6 }}>创建实例时按此 schema 提供参数</span>
    </div>
    {params.length === 0 && <div style={{ fontSize: 10, color: '#475569', padding: '6px 0' }}>暂无参数，点击下方添加</div>}
    {params.map((p, i) => (
      <div key={i} style={{ background: '#080f1d', border: '1px solid #1e2937', borderRadius: 5, padding: 7, marginBottom: 6 }}>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input value={p.name} onChange={e => updateParam(i, { name: e.target.value })} placeholder="参数名 (如 site_url)" style={{ ...inputStyle, fontSize: 10, flex: 1 }} />
          <select value={p.type} onChange={e => updateParam(i, { type: e.target.value })} style={{ ...inputStyle, fontSize: 10, width: 64 }}>
            {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button onClick={() => removeParam(i)} style={miniBtnStyle('#7f1d1d', '#fca5a5')}>×</button>
        </div>
        <input value={p.description} onChange={e => updateParam(i, { description: e.target.value })} placeholder="参数说明（必填时创建实例会提示）" style={{ ...inputStyle, fontSize: 9, marginTop: 4, width: '100%' }} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
          <label style={{ fontSize: 9, color: '#64748b', display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
            <input type="checkbox" checked={p.required} onChange={e => updateParam(i, { required: e.target.checked })} style={{ width: 12, height: 12 }} />
            必填
          </label>
          <input value={p.default} onChange={e => updateParam(i, { default: e.target.value })} placeholder="默认值（可选）" style={{ ...inputStyle, fontSize: 9, flex: 1 }} />
        </div>
      </div>
    ))}
    <button onClick={addParam} style={{ ...btn('#334155'), width: '100%', fontSize: 10 }}>＋ 添加参数</button>
  </>
}

const miniBtnStyle = (bg: string, fg: string): React.CSSProperties => ({ background: bg, color: fg, border: 0, borderRadius: 3, padding: '2px 6px', fontSize: 9, cursor: 'pointer' })

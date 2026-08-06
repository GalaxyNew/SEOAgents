import React, { useEffect, useRef, useState } from 'react'
import { useIsMobile } from '../hooks'
import {
  Modal,
  formatApiError,
  parseApiResponse,
  useDialogs,
  useQuickCommands,
  useToast,
} from '../ui'
import type { MetricsSummary } from './MetricsPanel'
import type { TabId } from '../App'

/**
 * SEOAgent 控制台 —— 单一入口就是 hm。
 *
 * 三点和旧版不同:
 * 1. 不再让用户选角色。系统本身是多智能体,但对外只暴露 hm;auditor/writer/linker
 *    由 hm 通过 system_ops(dispatch) 内部调度 —— 用户面对的是一个负责人,不是一个岗位选择器。
 * 2. 走异步任务:提交拿 job_id 再轮询。带工具调用的对话动辄两三分钟,同步请求会撞上
 *    Cloudflare 100 秒源站超时,拿回一张 HTML 错误页,前端 JSON.parse 直接崩。
 * 3. 上下文与提示词都改成「先填进输入框、用户确认后再发」,不再点一下就飞出去。
 */

export interface AgentCopilotDrawerProps {
  isOpen: boolean
  onClose: () => void
  // 从 App 导入而不是照抄一份:两处各写一遍,加页面时必然漏改一处
  activeTab: TabId
  summary: MetricsSummary | null
  configData: any
  drawerWidth: number
  onWidthChange: (width: number) => void
}

interface TraceStep {
  tool: string
  action?: string
  arguments: any
  output: string
  ok: boolean
}

interface ChatMessage {
  id: string
  sender: 'user' | 'agent'
  text: string
  turns?: number
  trace?: TraceStep[]
  ts: string
  pending?: boolean
  elapsed?: number
}

interface Conversation {
  id: string
  title: string
  archived: boolean
  created_at: string
  updated_at: string
  message_count: number
  last_text: string
  provider?: string
  model?: string
  reasoning_effort?: string
}

interface ContextItem {
  key: string
  label: string
  preview: string          // 列表里给人看的一行摘要
  payload: unknown         // 真正带给 hm 的原始数据结构
}

interface ModelProvider {
  slug: string
  label: string
  is_current: boolean
  models: string[]
  capabilities?: Record<string, {
    reasoning?: boolean
    fast?: boolean
    reasoning_efforts?: string[]
    reasoning_source?: string
  }>
}

interface ModelOptions {
  providers: ModelProvider[]
  current: { provider: string; model: string }
}

const TAB_LABEL: Record<string, string> = {
  dashboard: '监控大屏',
  gsc_overview: 'GSC 大屏',
  kanban: '任务卡',
  timeline: '时间规划',
  workflow: '工作流',
  capability: '能力中心',
  departments: '部门管理',
  config: '系统配置',
}

/** 按当前页面 + 真实可用工具生成的快捷指令。工具不可用的不出现在列表里。 */
function buildStarters(activeTab: string, tools: string[]): Array<{ id: string; title: string; prompt: string }> {
  const has = (t: string) => tools.includes(t)
  const hasDfsSerp = tools.some((t) => t.includes('serp_organic_live_advanced'))
  const all: Array<{ id: string; title: string; prompt: string; when: boolean }> = [
    {
      id: 'status', title: '🩺 系统体检',
      prompt: '调用 system_ops 的 status,把系统当前状态、可用工具和待办告诉我。',
      when: has('system_ops'),
    },
    {
      id: 'audit', title: '🔍 技术审计',
      prompt: '用 site_technical_auditor 审计首页,列出致命问题与死链清单,按严重度排序。',
      when: has('site_technical_auditor'),
    },
    {
      id: 'cwv', title: '⚡ 性能体检',
      prompt: '用 lighthouse_audit 测首页 Core Web Vitals,给出 performance 分、LCP、CLS,并说明哪一项最该先改。',
      when: has('lighthouse_audit'),
    },
    {
      id: 'traffic', title: '📈 流量复盘',
      prompt: '用 google_seo_monitor 查最近 28 天 GSC 表现,对比上一周期,指出涨跌最大的关键词和落地页。',
      when: has('google_seo_monitor'),
    },
    {
      id: 'rank', title: '🎯 排名核查',
      prompt: '用 serp_rank_tracker 查我们追踪的关键词在西班牙的实测排位(location_name=Spain, language_code=es),没进前 20 的单独列出来。',
      when: has('serp_rank_tracker'),
    },
    {
      id: 'compet', title: '🥊 竞品对比',
      prompt: '用 mcp_dataforseo_serp_organic_live_advanced 查我们主词在西班牙(location_name=Spain, language_code=es)的前 10 名都是谁,分析他们比我们强在哪。',
      when: hasDfsSerp,
    },
    {
      id: 'link', title: '🔗 内链优化',
      prompt: '分析当前站点结构,用 nlp_internal_linker 给出锚文本与内链植入建议。',
      when: has('nlp_internal_linker'),
    },
    {
      id: 'index', title: '📮 收录处理',
      prompt: '用 gsc_indexing_ops 生成 sitemap 并提交收录;若有死链先出 301 提案(注意:提案不等于已修复)。',
      when: has('gsc_indexing_ops'),
    },
    {
      id: 'plan', title: '🗓️ 排期',
      prompt: '看一下我的时间线负载,把今天该做的事排进去,写明每项预计耗时。',
      when: has('system_ops'),
    },
  ]
  return all.filter((s) => s.when).map(({ id, title, prompt }) => ({ id, title, prompt }))
}

export const AgentCopilotDrawer: React.FC<AgentCopilotDrawerProps> = ({
  isOpen,
  onClose,
  activeTab,
  summary,
  configData,
  drawerWidth,
  onWidthChange,
}) => {
  const isMobile = useIsMobile()
  const qc = useQuickCommands()
  const dialogs = useDialogs()
  const toast = useToast()
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'agent',
      text: '我是 hm,SEO 这摊归我管。技术审计、内容、内链这些我会自己派给专员,你直接说要什么就行。\n\n下面的快捷指令按当前真实可用的工具生成;点「📎 页面上下文」可以挑要带上的数据。',
      ts: new Date().toLocaleTimeString(),
    },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [queuedCount, setQueuedCount] = useState(0)
  const [busyInputMode, setBusyInputMode] = useState<'steer' | 'queue'>('steer')
  const [reasoningOpen, setReasoningOpen] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const [progress, setProgress] = useState<{kind:string;text:string}[]>([])
  const progressScrollRef = useRef<HTMLDivElement | null>(null)
  const [openTrace, setOpenTrace] = useState<string | null>(null)
  const [tools, setTools] = useState<string[]>([])
  const [showCtx, setShowCtx] = useState(false)
  const [ctxItems, setCtxItems] = useState<ContextItem[]>([])
  const [ctxPicked, setCtxPicked] = useState<Record<string, boolean>>({})
  const [isResizing, setIsResizing] = useState(false)
  const [convId, setConvId] = useState<string | null>(null)
  const [convs, setConvs] = useState<Conversation[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [histTab, setHistTab] = useState<'active' | 'archived'>('active')
  const [convTitle, setConvTitle] = useState('新对话')
  const [modelOptions, setModelOptions] = useState<ModelOptions | null>(null)
  const [modelsLoading, setModelsLoading] = useState(true)
  const [modelOptionsError, setModelOptionsError] = useState('')
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('auto')
  const reasoningEffortRef = useRef('auto')
  const reasoningCursorRef = useRef(0)
  const activeJobRef = useRef<string | null>(null)
  const reasoningSeenRef = useRef<Set<number>>(new Set())
  const turnGenerationRef = useRef(0)
  // 移动端浏览器的地址栏会伸缩,100vh 是「地址栏收起后」的高度 —— 用它布局
  // 底部会被顶到可视区外。visualViewport 给的是真实可视高度,键盘弹出时也准。
  const [vh, setVh] = useState<number | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((d) => setTools((d?.resolved?.tools as string[]) || []))
      .catch(() => setTools([]))
  }, [])

  useEffect(() => {
    fetch('/api/agent/model-options')
      .then((r) => r.json())
      .then((d: ModelOptions) => {
        setModelOptions(d)
        setModelOptionsError('')
        setModelsLoading(false)
        const currentProvider = d?.current?.provider || d?.providers?.[0]?.slug || ''
        const row = (d?.providers || []).find((p) => p.slug === currentProvider)
        setSelectedProvider(currentProvider)
        setSelectedModel(d?.current?.model || row?.models?.[0] || '')
        setReasoningEffort('auto')
        if (!(d?.providers || []).some((p) => p.slug === currentProvider && p.models?.includes(d?.current?.model))) {
          setSelectedProvider(row?.slug || d?.providers?.[0]?.slug || '')
          setSelectedModel(row?.models?.[0] || d?.providers?.[0]?.models?.[0] || '')
        }
      })
      .catch(() => {
        setModelsLoading(false)
        setModelOptionsError('Hermes 官方模型能力目录不可用，已停止发送')
        setModelOptions(null)
      })
  }, [])

  const selectedCapability = modelOptions?.providers
    .find((p) => p.slug === selectedProvider)
    ?.capabilities?.[selectedModel]
  const selectedReasoningEfforts = ['auto', ...(selectedCapability?.reasoning_efforts || [])]

  const modelOptionsSignature = JSON.stringify(
    modelOptions?.providers.find((p) => p.slug === selectedProvider)?.capabilities?.[selectedModel]?.reasoning_efforts || [],
  )

  useEffect(() => {
    if (selectedReasoningEfforts.length > 1 && !selectedReasoningEfforts.includes(reasoningEffort)) {
      setReasoningEffort('auto')
    }
  }, [selectedProvider, selectedModel, modelOptionsSignature])

  useEffect(() => {
    reasoningEffortRef.current = reasoningEffort
  }, [reasoningEffort])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => window.clearInterval(timer)
  }, [busy])

  useEffect(() => {
    const el = progressScrollRef.current
    if (reasoningOpen && el) el.scrollTop = el.scrollHeight
  }, [progress, reasoningOpen])

  // 真实可视高度。visualViewport 会随地址栏伸缩和键盘弹出而变,
  // 拿它当抽屉高度,输入框就不会被挤到屏幕外面去。
  useEffect(() => {
    const vv = window.visualViewport
    const sync = () => setVh(vv ? vv.height : window.innerHeight)
    sync()
    vv?.addEventListener('resize', sync)
    vv?.addEventListener('scroll', sync)
    window.addEventListener('resize', sync)
    window.addEventListener('orientationchange', sync)
    return () => {
      vv?.removeEventListener('resize', sync)
      vv?.removeEventListener('scroll', sync)
      window.removeEventListener('resize', sync)
      window.removeEventListener('orientationchange', sync)
    }
  }, [])

  // ── 会话 ──────────────────────────────────────────────────────────
  const loadConvs = async (archived = false) => {
    try {
      const d = await fetch(`/api/conversations?archived=${archived}`).then((r) => r.json())
      setConvs(d.conversations || [])
    } catch { setConvs([]) }
  }

  // 首次打开:接着最近一次的对话,而不是每次都从空白开始。
  // 会话记录的意义就在于「上次说到哪了」还在。
  useEffect(() => {
    if (!isOpen || convId) return
    ;(async () => {
      try {
        const d = await fetch('/api/conversations').then((r) => r.json())
        const latest = (d.conversations || [])[0]
        if (latest) await openConv(latest.id)
        else await newConv()
      } catch { /* 后端不可用时保持本地状态,不打断使用 */ }
    })()
  }, [isOpen])

  const WELCOME: ChatMessage = {
    id: 'welcome', sender: 'agent',
    text: '我是 hm,SEO 这摊归我管。技术审计、内容、内链这些我会自己派给专员,你直接说要什么就行。\n\n下面的快捷指令按当前真实可用的工具生成;点「📎 页面上下文」可以挑要带上的数据。',
    ts: new Date().toLocaleTimeString(),
  }

  const newConv = async () => {
    try {
      const d = await fetch('/api/conversations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      }).then((r) => r.json())
      setConvId(d.id)
      setConvTitle(d.title || '新对话')
    } catch { setConvId(null) }
    setMessages([WELCOME])
    setProgress([])
    reasoningCursorRef.current = 0
    reasoningSeenRef.current = new Set()
    turnGenerationRef.current += 1
    setShowHistory(false)
  }

  const openConv = async (conversationKey: string) => {
    try {
      const cid = conversationKey
      const d = await fetch(`/api/conversations/${cid}`).then((r) => r.json())
      setConvId(d.id)
      setConvTitle(d.title || '对话')
      setSelectedProvider(d.provider)
      if (d.model) setSelectedModel(d.model)
      if (d.reasoning_effort) setReasoningEffort(d.reasoning_effort)
      setProgress([])
      turnGenerationRef.current += 1
      reasoningCursorRef.current = 0
      reasoningSeenRef.current = new Set()
      const loaded: ChatMessage[] = (d.messages || []).map((m: any, i: number) => ({
        id: m.id || `m_${i}`, sender: m.sender, text: m.text,
        turns: m.turns ?? undefined, elapsed: m.elapsed ?? undefined,
        trace: m.trace || [],
        ts: new Date(m.ts).toLocaleTimeString(),
      }))
      setMessages(loaded.length ? loaded : [WELCOME])
      void reconnectActiveJob(cid)
    } catch { /* 打不开就保持当前 */ }
    setShowHistory(false)
  }

  const archiveConv = async (cid: string, archived: boolean) => {
    try {
      await parseApiResponse(await fetch(`/api/conversations/${cid}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ archived }),
      }), archived ? '归档对话失败' : '取回对话失败')
      await loadConvs(histTab === 'archived')
      if (archived && cid === convId) await newConv()
      toast.success(archived ? '对话已归档' : '对话已取回')
    } catch (error) {
      toast.error(`${archived ? '归档' : '取回'}对话失败：${formatApiError(error)}`)
    }
  }

  const deleteConv = async (cid: string) => {
    const conversation = convs.find((item) => item.id === cid)
    const approved = await dialogs.confirm({
      title: `永久删除对话「${conversation?.title || cid}」`,
      message: '确定永久删除这条对话及其消息记录吗？如果只是暂时收起，请改用归档。',
      consequence: '删除后无法恢复。',
      confirmLabel: '永久删除',
      tone: 'danger',
    })
    if (!approved) return
    try {
      await parseApiResponse(await fetch(`/api/conversations/${cid}`, { method: 'DELETE' }), '删除对话失败')
      await loadConvs(histTab === 'archived')
      if (cid === convId) await newConv()
      toast.success(`对话「${conversation?.title || cid}」已删除`)
    } catch (error) {
      toast.error(`删除对话失败：${formatApiError(error)}`)
    }
  }

  // 宽度拖拽
  useEffect(() => {
    if (!isResizing) return
    const move = (e: MouseEvent) => {
      const w = window.innerWidth - e.clientX
      onWidthChange(Math.min(Math.max(w, 320), Math.min(900, window.innerWidth - 200)))
    }
    const up = () => setIsResizing(false)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [isResizing, onWidthChange])

  if (!isOpen) return null

  // ── 页面上下文:采集当前页面的数据块,交给用户勾选 ──
  const collectContext = async (): Promise<ContextItem[]> => {
    const items: ContextItem[] = []
    // 摘要只是给人在勾选列表里认的;带给 hm 的必须是原始结构。
    // 早先只传一行「数据区间: 2026-07-27 ~ 2026-08-02」,hm 拿到等于什么都没拿到。
    const push = (key: string, label: string, payload: any, preview?: string) => {
      if (payload === undefined || payload === null || payload === '') return
      const p = preview ?? (
        Array.isArray(payload) ? `${payload.length} 条`
        : typeof payload === 'object' ? `${Object.keys(payload).length} 个字段`
        : String(payload)
      )
      items.push({ key, label, preview: p, payload })
    }

    if (activeTab === 'dashboard') {
      push('metrics', '监控指标全量', summary,
        `M_t ${summary?.latest_m_t ?? '暂无'} · V_t ${summary?.v_t ?? '暂无'} · 死链 ${summary?.open_dead_links ?? 0}`)
      push('serp', 'SERP 排位明细', summary?.serp_positions,
        `${(summary?.serp_positions || []).length} 个词`)
      push('skills', '已固化技能', summary?.skills?.filter((s: any) => !s.built_in),
        `${(summary?.skills || []).filter((s: any) => !s.built_in).length} 个`)
    } else if (activeTab === 'gsc_overview') {
      try {
        const d = await fetch('/api/gsc/overview?range=7d').then((r) => r.json())
        push('gsc_meta', '站点与区间', {
          site_url: d?.site_url, gsc_property: d?.gsc_property,
          brand_name: d?.brand_name, date_range: d?.date_range,
          range_start: d?.range_start, range_end: d?.range_end,
          data_status: d?.data_status, is_real_gsc: d?.is_real_gsc,
          sample_status: d?.sample_status, zero_impression_days: d?.zero_impression_days,
        }, `${d?.brand_name || d?.site_url} · ${d?.date_range}`)
        push('gsc_summary', 'KPI 汇总(含同比)', d?.summary,
          `点击 ${d?.summary?.clicks?.value} · 展示 ${d?.summary?.impressions?.value} · CTR ${d?.summary?.ctr?.value}`)
        push('gsc_trend', '每日趋势序列', d?.trend_series,
          `${(d?.trend_series || []).length} 天逐日数据`)
        push('gsc_kw', 'Top 关键词', d?.top_keywords,
          `${(d?.top_keywords || []).length} 个词(含排名/展现/CTR)`)
        push('gsc_pages', 'Top 落地页', d?.landing_pages,
          `${(d?.landing_pages || []).length} 个页面`)
        push('gsc_country', '点击国家', d?.countries,
          `${(d?.countries || []).length} 个国家`)
      } catch { /* 取不到就不放进列表,不编造 */ }
    } else if (activeTab === 'kanban') {
      try {
        const d = await fetch('/api/kanban/board').then((r) => r.json())
        push('kb_stat', '看板统计', { total: d?.total, open_count: d?.open_count, source: d?.source },
          `共 ${d?.total} 张,未关闭 ${d?.open_count}`)
        push('kb_items', '任务卡全量', d?.items, `${(d?.items || []).length} 张卡(含状态/指派/优先级)`)
        push('kb_columns', '按状态分组', d?.columns,
          `${Object.keys(d?.columns || {}).length} 个状态列`)
      } catch { /* noop */ }
    } else if (activeTab === 'timeline') {
      try {
        const d = await fetch('/api/timeline/agenda?hours_ahead=24').then((r) => r.json())
        push('tl_agenda', '日程全量', d,
          `负载 ${Math.round((d?.load_ratio || 0) * 100)}% · 已排 ${(d?.upcoming || []).length} · 执行中 ${(d?.in_flight || []).length}`)
        push('tl_upcoming', '待执行节点', d?.upcoming, `${(d?.upcoming || []).length} 个`)
        push('tl_inflight', '执行中节点', d?.in_flight, `${(d?.in_flight || []).length} 个`)
      } catch { /* noop */ }
    } else if (activeTab === 'workflow') {
      try {
        const [t, i] = await Promise.all([
          fetch('/api/workflows/templates').then((r) => r.json()),
          fetch('/api/workflows/instances').then((r) => r.json()),
        ])
        push('wf_tpl', '工作流模板', t?.templates,
          `${(t?.templates || []).length} 个模板(含节点数/依赖/闸门)`)
        push('wf_inst', '运行实例', i?.items, `${i?.total ?? 0} 个实例`)
      } catch { /* noop */ }
    } else if (activeTab === 'capability') {
      try {
        const c = await fetch('/api/capabilities').then((r) => r.json())
        const un = Object.entries(c || {}).filter(([, v]: any) => v?.uncovered).map(([k]) => k)
        const risky = Object.entries(c || {}).filter(([, v]: any) => v?.single_source_risk).map(([k]) => k)
        push('cap_matrix', '能力覆盖矩阵', c,
          `${Object.keys(c || {}).length} 项能力 · ${un.length} 未覆盖 · ${risky.length} 单源风险`)
        push('cap_gaps', '缺口清单', { uncovered: un, single_source_risk: risky },
          `未覆盖 ${un.length} · 单源 ${risky.length}`)
      } catch { /* noop */ }
    } else if (activeTab === 'config') {
      let cfg = configData
      if (!cfg?.resolved) {
        try { cfg = await fetch('/api/config').then((r) => r.json()) } catch { /* noop */ }
      }
      const r = cfg?.resolved || {}
      push('cfg_resolved', '生效配置(已脱敏)', r,
        `${r.site} · provider ${r.provider} · ${(r.tools || []).length} 个工具`)
      push('cfg_scoring', 'M_t 权重与阈值', r.scoring,
        `α=${r.scoring?.alpha} β=${r.scoring?.beta} γ=${r.scoring?.gamma} δ=${r.scoring?.delta}`)
      push('cfg_tools', '已注册工具清单', r.tools, `${(r.tools || []).length} 个`)
    }
    return items
  }

  const openContextPicker = async () => {
    const items = await collectContext()
    setCtxItems(items)
    setCtxPicked(Object.fromEntries(items.map((i) => [i.key, true])))
    setShowCtx(true)
  }

  /** 勾选的上下文拼进输入框 —— 不直接发送,用户还能改 */
  /** 勾选的上下文以真实 JSON 拼进输入框 —— 不直接发送,用户还能改 */
  const applyContext = () => {
    const picked = ctxItems.filter((i) => ctxPicked[i.key])
    if (picked.length === 0) { setShowCtx(false); return }
    const payload: Record<string, unknown> = {}
    picked.forEach((i) => { payload[i.key] = i.payload })
    const block =
      `[${TAB_LABEL[activeTab] || activeTab} · 实时数据快照]\n` +
      '```json\n' + JSON.stringify(payload, null, 2) + '\n```'
    setInput((prev) => (prev ? `${block}\n\n${prev}` : `${block}\n\n`))
    setShowCtx(false)
    setTimeout(() => textareaRef.current?.focus(), 50)
  }

  const pollJob = async (
    jobId: string,
    conversationId: string,
    initialProgress: {kind:string;text:string}[] = [],
    initialBaseline = 0,
    generation = turnGenerationRef.current,
  ) => {
    activeJobRef.current = jobId
    setBusy(true)
    setProgress(initialProgress)
    let lastElapsed = elapsed
    const started = Date.now()
    const deadline = started + 15 * 60 * 1000
    let baseline = Math.max(reasoningCursorRef.current, initialBaseline)
    let lastBaseline = initialBaseline
    let lastProgressSignature = ''
    let lastPersistAt = 0
    if (baseline > reasoningCursorRef.current) reasoningCursorRef.current = baseline
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500))
      const pr = await fetch(`/api/agent/jobs/${jobId}`)
      const pct = pr.headers.get('content-type') || ''
      if (!pr.ok) {
        if (pr.status === 404) break
        continue
      }
      if (!pct.includes('application/json')) continue
      const job = await pr.json()
      if (generation !== turnGenerationRef.current) return
      lastElapsed = Number(job.elapsed_seconds || lastElapsed)
      setElapsed(Math.max(0, Math.floor(lastElapsed)))
      setQueuedCount(Number(job.queued_count || 0))
      const currentBaseline = Number(job.reasoning_baseline || 0)
      if (currentBaseline > 0 && lastBaseline > 0 && currentBaseline !== lastBaseline) {
        turnGenerationRef.current += 1
        reasoningCursorRef.current = currentBaseline
        baseline = currentBaseline
        setProgress(Array.isArray(job.progress) ? job.progress : [])
      }
      lastBaseline = currentBaseline || lastBaseline
      if (Array.isArray(job.progress) && job.progress.length > 0) {
        setProgress(job.progress)
        const signature = JSON.stringify(job.progress)
        if (signature !== lastProgressSignature && Date.now() - lastPersistAt >= 5000) {
          lastProgressSignature = signature
          lastPersistAt = Date.now()
          try {
            await fetch(`/api/agent/jobs/${jobId}/checkpoint`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({}),
            })
          } catch { /* live in-memory stream remains available */ }
        }
      }
      if (conversationId && reasoningEffortRef.current !== 'none' && !job.progress?.some((p: any) => p.kind === 'thinking')) {
        try {
          baseline = Math.max(baseline, Number(job.reasoning_baseline || 0))
          if (baseline > reasoningCursorRef.current) reasoningCursorRef.current = baseline
          const rr = await fetch(
            `/api/agent/sessions/${conversationId}/reasoning?after_id=${reasoningCursorRef.current}`,
          ).then((r) => r.json())
          reasoningCursorRef.current = Math.max(reasoningCursorRef.current, Number(rr?.last_id || 0))
          const fresh = (rr?.items || []).filter((x: any) => {
            const id = Number(x.id || 0)
            const key = (turnGenerationRef.current * 1_000_000_000) + id
            if (!id || reasoningSeenRef.current.has(key)) return false
            reasoningSeenRef.current.add(key)
            return true
          })
          if (fresh.length > 0) {
            setProgress((prev) => [
              ...prev,
              ...fresh.map((x: any) => ({ kind: 'thinking', text: String(x.text || '') })),
            ].slice(-60))
          }
        } catch { /* provider reasoning unavailable; task status remains authoritative */ }
      }
      if (busy) {
        const loaded = await fetch(`/api/conversations/${conversationId}`).then((r) => r.json()).catch(() => null)
        if (loaded?.messages) {
          setMessages((loaded.messages || []).map((m: any, i: number) => ({
            id: m.id || `m_${i}`, sender: m.sender, text: m.text,
            turns: m.turns ?? undefined, elapsed: m.elapsed ?? undefined,
            trace: m.trace || [], ts: new Date(m.ts).toLocaleTimeString(),
          })))
        }
      }
      if (job.status !== 'done') continue
      setProgress((prev) => prev.slice(-60))
      if (!job.result_ok) {
        setMessages((m) => [...m, {
          id: `e_${Date.now()}`, sender: 'agent', text: `⚠️ 执行失败: ${job.error || '未知错误'}`,
          ts: new Date().toLocaleTimeString(),
        }])
      }
      if (job.result_ok) {
        const loaded = await fetch(`/api/conversations/${conversationId}`).then((r) => r.json()).catch(() => null)
        if (loaded?.messages) {
          setMessages((loaded.messages || []).map((m: any, i: number) => ({
            id: m.id || `m_${i}`, sender: m.sender, text: m.text,
            turns: m.turns ?? undefined, elapsed: m.elapsed ?? undefined,
            trace: m.trace || [], ts: new Date(m.ts).toLocaleTimeString(),
          })))
        }
      } else {
        // Failure is already rendered above; no duplicate bubble.
      }
      activeJobRef.current = null
      setBusy(false)
      setElapsed(0)
      return
    }
    activeJobRef.current = null
    setBusy(false)
    setElapsed(0)
  }

  const reconnectActiveJob = async (cid: string) => {
    try {
      const d = await fetch(`/api/agent/conversations/${cid}/active-job`).then((r) => r.json())
      if (!d.active && d.status === 'unknown' && d.error) {
        setMessages((m) => [...m, {
          id: `e_${Date.now()}`, sender: 'agent', text: `⚠️ ${d.error}`,
          ts: new Date().toLocaleTimeString(),
        }])
      }
      if (!d.active) return
      setElapsed(Math.max(0, Math.floor((Date.now() - Number(d.created_at) * 1000) / 1000)))
      setQueuedCount(Number(d.queued_count || 0))
      void pollJob(d.job_id, cid, d.progress || [], Number(d.reasoning_baseline || 0), turnGenerationRef.current)
    } catch { /* no active job */ }
  }

  // ── 发送:提交异步任务后轮询 ──
  const send = async (override?: string) => {
    const text = (override ?? input).trim()
    if (!text) return
    if (!convId) {
      setMessages((m) => [...m, {
        id: `e_${Date.now()}`, sender: 'agent', text: '⚠️ 对话会话尚未建立，请稍后重试。',
        ts: new Date().toLocaleTimeString(),
      }])
      return
    }
    if (!selectedProvider || !selectedModel) {
      setMessages((m) => [...m, {
        id: `e_${Date.now()}`, sender: 'agent',
        text: modelsLoading ? '⚠️ 正在从 Hermes 官方能力目录加载模型，请稍后再发送。' : `⚠️ ${modelOptionsError || '模型目录不可用，拒绝发送。'}`,
        ts: new Date().toLocaleTimeString(),
      }])
      return
    }
    const now = new Date().toLocaleTimeString()
    const optimisticId = `u_${Date.now()}`
    setMessages((m) => [...m, { id: optimisticId, sender: 'user', text, ts: now }])
    setInput('')
    const sendGeneration = turnGenerationRef.current
    if (busy) {
      let accepted = false
      try {
        const endpoint = busyInputMode === 'steer' ? 'steer' : 'queue'
        const res = await fetch(`/api/agent/conversations/${convId}/${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            task: text,
            role: 'hm',
            conversation_id: convId,
            provider: selectedProvider,
            model: selectedModel,
            reasoning_effort: reasoningEffort,
          }),
        })
        const d = await res.json()
        if (!res.ok) throw new Error(d.detail || `${busyInputMode === 'steer' ? '插入' : '追加'}失败`)
        accepted = true
        if (busyInputMode === 'queue') setQueuedCount(Number(d.queued_count || 1))
      } catch (err) {
        setMessages((m) => [
          ...m.filter((msg) => msg.id !== optimisticId),
          {
            id: `e_${Date.now()}`, sender: 'agent',
            text: `⚠️ ${busyInputMode === 'steer' ? '执行中插入' : '追加队列'}失败: ${err}`,
            ts: new Date().toLocaleTimeString(),
          },
        ])
        setInput(text)
      }
      if (!accepted) return
      return
    }
    setBusy(true)
    setElapsed(0)
    setProgress([])
    reasoningCursorRef.current = 0
    reasoningSeenRef.current = new Set()
    turnGenerationRef.current += 1
    const fail = (msg: string) => {
      setMessages((m) => [...m, {
        id: `e_${Date.now()}`, sender: 'agent', text: `⚠️ ${msg}`,
        ts: new Date().toLocaleTimeString(),
      }])
    }

    try {
      const res = await fetch('/api/agent/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: text,
          role: 'hm',
          conversation_id: convId,
          provider: selectedProvider,
          model: selectedModel,
          reasoning_effort: reasoningEffort,
        }),
      })
      // 网关异常时返回的是 HTML,不能直接 .json() —— 那正是 "Unexpected token '<'" 的来源
      const ct = res.headers.get('content-type') || ''
      if (!ct.includes('application/json')) {
        fail(`服务返回了非 JSON 响应(HTTP ${res.status})。通常是网关或服务重启中,稍后重试。`)
        return
      }
      const sub = await res.json()
      if (!sub.job_id) { fail(`任务提交失败: ${sub.detail || sub.error || '未知'}`); return }
      activeJobRef.current = sub.job_id
      await pollJob(sub.job_id, convId as string, [], Number(sub.reasoning_baseline || 0), turnGenerationRef.current)
    } catch (err) {
      fail(`请求异常: ${err}`)
    } finally {
      if (!activeJobRef.current) {
        setBusy(false)
        setElapsed(0)
      }
    }
  }

  // 内置(按当前可用工具生成)+ 用户从能力中心加的,后者可在此直接移除
  const starters = [
    ...buildStarters(activeTab, tools),
    ...qc.cmds.map((c) => ({ id: c.id, title: c.title, prompt: c.prompt, custom: true })),
  ]
  const width = isMobile ? '100vw' : `${drawerWidth}px`

  return (
    <>
      {isResizing && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 999999, cursor: 'col-resize', userSelect: 'none' }} />
      )}

      <Modal
        open={showHistory}
        title="历史对话"
        width={500}
        closeOnBackdrop={false}
        onClose={() => setShowHistory(false)}
        zIndex={100001}
        footer={(
          <button onClick={() => void newConv()} style={{ ...smallBtn, background: '#2563eb', color: '#fff' }}>✚ 新建对话</button>
        )}
      >
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          {(['active', 'archived'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => { setHistTab(tab); void loadConvs(tab === 'archived') }}
              style={{
                ...smallBtn,
                background: histTab === tab ? '#1e293b' : 'transparent',
                color: histTab === tab ? '#60a5fa' : '#94a3b8',
                border: `1px solid ${histTab === tab ? '#3b82f6' : '#334155'}`,
              }}
            >{tab === 'active' ? '进行中' : '已归档'}</button>
          ))}
        </div>
        {convs.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: '#64748b', fontSize: 13 }}>
            {histTab === 'archived' ? '没有已归档的对话' : '还没有历史对话'}
          </div>
        )}
        {convs.map((conversation) => (
          <div
            key={conversation.id}
            onClick={() => void openConv(conversation.id)}
            style={{
              padding: '9px 11px', borderRadius: 8, cursor: 'pointer',
              background: conversation.id === convId ? '#1e293b' : 'transparent',
              border: `1px solid ${conversation.id === convId ? '#334155' : 'transparent'}`,
              marginBottom: 4,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 13, color: '#e2e8f0', fontWeight: 500, flex: 1,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{conversation.title}</span>
              <span style={{ fontSize: 10, color: '#475569' }}>{conversation.message_count} 条</span>
              <button
                title={histTab === 'archived' ? '取回' : '归档'}
                onClick={(event) => { event.stopPropagation(); void archiveConv(conversation.id, histTab !== 'archived') }}
                style={{ background: 'transparent', border: 0, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '2px 4px' }}
              >{histTab === 'archived' ? '↩' : '📥'}</button>
              <button
                title="删除"
                onClick={(event) => { event.stopPropagation(); void deleteConv(conversation.id) }}
                style={{ background: 'transparent', border: 0, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '2px 4px' }}
              >🗑</button>
            </div>
            {conversation.last_text && (
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {conversation.last_text}
              </div>
            )}
            <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
              {new Date(conversation.updated_at).toLocaleString('zh-CN', { hour12: false })}
            </div>
          </div>
        ))}
      </Modal>
      <div
        className="copilot-drawer"
        style={{
          position: 'fixed', top: 0, right: 0, width, maxWidth: '100vw',
          // 优先用实测可视高度;拿不到时退回 dvh(动态视口),再退回 vh。
          // 直接写 100vh 会让底部输入框沉到移动端可视区外面。
          height: vh ? `${vh}px` : '100dvh',
          background: '#0f172a', borderLeft: '1px solid #1e293b',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.5)', zIndex: 9999,
          display: 'flex', flexDirection: 'column',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        {!isMobile && (
          <div
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            title="按住左右拖动调整宽度"
            style={{
              position: 'absolute', top: 0, left: -6, width: 12, height: '100%',
              cursor: 'col-resize', zIndex: 10000,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <div style={{ width: 3, height: 48, borderRadius: 2, background: isResizing ? '#3b82f6' : '#334155' }} />
          </div>
        )}

        {/* 头部 */}
        <div style={{
          padding: '14px 16px', background: '#1e293b', borderBottom: '1px solid #334155',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 20 }}>🧭</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15, color: '#f8fafc' }}>
                SEOAgent
                <span style={{ fontSize: 11, color: '#64748b', marginLeft: 8 }}>hm · Hermes</span>
              </div>
              <div style={{
                fontSize: 11, color: '#94a3b8', maxWidth: 180,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }} title={convTitle}>
                {convTitle}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <button onClick={() => void newConv()} title="新建对话" style={{
              background: 'transparent', border: 0, color: '#94a3b8',
              fontSize: 16, cursor: 'pointer', padding: '4px 7px',
            }}>✚</button>
            <button
              onClick={() => { setHistTab('active'); void loadConvs(false); setShowHistory(true) }}
              title="历史对话" style={{
                background: 'transparent', border: 0, color: '#94a3b8',
                fontSize: 15, cursor: 'pointer', padding: '4px 7px',
              }}>🕘</button>
            <button onClick={onClose} title="收起" style={{
              background: 'transparent', border: 0, color: '#94a3b8',
              fontSize: 18, cursor: 'pointer', padding: '4px 8px',
            }}>✕</button>
          </div>
        </div>

        {/* 消息区 */}
        <div style={{ flex: 1, padding: 16, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {messages.map((msg) => (
            <div key={msg.id} style={{ alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
              <div style={{
                fontSize: 11, color: '#64748b', marginBottom: 4,
                textAlign: msg.sender === 'user' ? 'right' : 'left',
              }}>
                {msg.sender === 'user' ? '你' : 'hm'} · {msg.ts}
                {msg.elapsed != null && <span> · 用时 {msg.elapsed}s</span>}
              </div>
              <div style={{
                background: msg.sender === 'user' ? '#2563eb' : '#1e293b',
                color: msg.sender === 'user' ? '#fff' : '#e2e8f0',
                padding: '12px 14px',
                borderRadius: msg.sender === 'user' ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                fontSize: 13, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                border: msg.sender === 'user' ? 'none' : '1px solid #334155',
              }}>
                {msg.text}
                {msg.trace && msg.trace.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #334155' }}>
                    <button
                      onClick={() => setOpenTrace(openTrace === msg.id ? null : msg.id)}
                      style={{
                        background: 'transparent', border: 0, color: '#38bdf8',
                        fontSize: 12, cursor: 'pointer', padding: 0,
                        display: 'flex', alignItems: 'center', gap: 4,
                      }}
                    >
                      🛠️ 工具执行轨迹 ({msg.trace.length} 步) {openTrace === msg.id ? '▲ 收起' : '▼ 展开'}
                    </button>
                    {openTrace === msg.id && (
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {msg.trace.map((step, i) => (
                          <div key={i} style={{
                            background: '#0f172a', border: `1px solid ${step.ok ? '#059669' : '#dc2626'}`,
                            borderRadius: 6, padding: 8, fontSize: 11, fontFamily: 'monospace',
                          }}>
                            <div style={{ color: step.ok ? '#34d399' : '#f87171', fontWeight: 'bold' }}>
                              #{i + 1} {step.tool} ({step.ok ? 'SUCCESS' : 'FAILED'})
                            </div>
                            {step.arguments && (
                              <div style={{ color: '#94a3b8', marginTop: 4 }}>
                                Arg: {JSON.stringify(step.arguments)}
                              </div>
                            )}
                            <div style={{ color: '#cbd5e1', marginTop: 4, maxHeight: 120, overflowY: 'auto' }}>
                              {step.output}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div style={{ alignSelf: 'flex-start', color: '#38bdf8', fontSize: 12, display: 'flex', gap: 6 }}>
              <span>⏳ hm 正在处理… {elapsed}s</span>
              <span style={{ color: '#475569' }}>(带工具的任务通常 1-3 分钟)</span>
            </div>
          )}
          {(busy || progress.length > 0) && (
            <div style={{
              alignSelf: 'flex-start', maxWidth: '92%', background: '#0b1220',
              border: '1px solid #1e293b', borderLeft: '3px solid #3b82f6',
              borderRadius: 8, padding: '8px 10px', fontSize: 12,
            }}>
              <div style={{ color: '#60a5fa', fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>{busy ? `执行中 · ${elapsed}s` : '本次执行过程'}{queuedCount > 0 ? ` · 待处理 ${queuedCount}` : ''}</span>
                <button
                  onClick={() => setReasoningOpen((v) => !v)}
                  aria-expanded={reasoningOpen}
                  style={{
                    marginLeft: 'auto', background: 'transparent', border: 0,
                    color: '#93c5fd', fontSize: 11, cursor: 'pointer', padding: '1px 4px',
                  }}
                >
                  {reasoningOpen ? '▲ 收起' : '▼ 展开'}
                </button>
              </div>
              {reasoningOpen && (
                <div
                  ref={progressScrollRef}
                  style={{ maxHeight: 220, overflowY: 'auto', paddingRight: 4, scrollBehavior: 'smooth' }}
                >
                  {progress.length === 0 && (
                    <div style={{ color: '#64748b' }}>正在连接模型…</div>
                  )}
                  {progress.map((p, i) => (
                    <div key={i} style={{ marginBottom: 3, lineHeight: 1.5 }}>
                      {p.kind === 'thinking' ? (
                        <div style={{ color: '#cbd5e1', whiteSpace: 'pre-wrap' }}>
                          <span style={{ color: '#818cf8', marginRight: 5 }}>思考</span>
                          {p.text}
                        </div>
                      ) : p.kind === 'assistant' ? (
                        <div style={{ color: '#e2e8f0', whiteSpace: 'pre-wrap' }}>
                          <span style={{ color: '#38bdf8', marginRight: 5 }}>输出</span>
                          {p.text}
                        </div>
                      ) : p.kind === 'compacting' ? (
                        <div style={{ color: '#fbbf24', whiteSpace: 'pre-wrap' }}>
                          <span style={{ color: '#f59e0b', marginRight: 5 }}>压缩</span>
                          {p.text}
                        </div>
                      ) : (
                        <div style={{ color: p.kind === 'tool' ? '#94a3b8' : '#64748b' }}>
                          <span style={{
                            color: p.kind === 'turn' ? '#f59e0b'
                                 : p.kind === 'tool_start' ? '#22d3ee' : '#22c55e',
                            marginRight: 5,
                          }}>
                            {p.kind === 'turn' ? '轮次' : p.kind === 'tool_start' ? '调用' : p.kind === 'status' ? '状态' : '完成'}
                          </span>
                          {p.text}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* 快捷指令 */}
        <div style={{ padding: '8px 16px', background: '#0f172a', borderTop: '1px solid #1e293b' }}>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>
            快捷指令 <span style={{ color: '#475569' }}>· 点击填入输入框可再编辑 · 蓝色为你从能力中心添加的</span>
          </div>
          <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
            {starters.length === 0 && (
              <span style={{ fontSize: 11, color: '#475569' }}>正在读取可用工具…</span>
            )}
            {starters.map((s: any) => (
              <span
                key={s.id}
                onClick={() => {
                  setInput(s.prompt)
                  setTimeout(() => textareaRef.current?.focus(), 50)
                }}
                title={s.prompt}
                style={{
                  background: s.custom ? '#1e3a8a' : '#1e293b',
                  border: `1px solid ${s.custom ? '#3b82f6' : '#334155'}`,
                  borderRadius: 12, color: '#93c5fd', fontSize: 11,
                  padding: '3px 8px 3px 10px', whiteSpace: 'nowrap',
                  cursor: 'pointer', flexShrink: 0,
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                }}
              >
                {s.title}
                {s.custom && (
                  <span
                    onClick={(e) => { e.stopPropagation(); qc.remove(s.id) }}
                    title="从快捷指令移除"
                    style={{ color: '#64748b', fontSize: 12, lineHeight: 1 }}
                  >×</span>
                )}
              </span>
            ))}
          </div>
        </div>

        {/* 输入区 */}
        <div style={{ padding: '12px 16px', background: '#1e293b', borderTop: '1px solid #334155' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: 8, flexWrap: 'wrap' }}>
            <button onClick={openContextPicker} style={{
              background: '#334155', border: 0, borderRadius: 4, color: '#38bdf8',
              fontSize: 11, padding: '4px 10px', cursor: 'pointer', fontWeight: 500,
            }}>
              📎 页面上下文 ({TAB_LABEL[activeTab] || activeTab})
            </button>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              {busy && (
                <select
                  aria-label="执行中指令方式"
                  value={busyInputMode}
                  onChange={(e) => setBusyInputMode(e.target.value as 'steer' | 'queue')}
                  style={{ ...modelSelect, maxWidth: 118, borderColor: '#7c3aed' }}
                  title="插入当前轮：下一次工具返回后生效；排队下一轮：当前回答结束后继续"
                >
                  <option value="steer">插入当前轮</option>
                  <option value="queue">排队下一轮</option>
                </select>
              )}
              <select
                aria-label="模型服务商"
                value={selectedProvider}
                disabled={busy || !modelOptions}
                onChange={(e) => {
                  const provider = e.target.value
                  const row = modelOptions?.providers.find((p) => p.slug === provider)
                  setSelectedProvider(provider)
                  setSelectedModel(row?.models?.[0] || '')
                }}
                style={modelSelect}
              >
                {(modelOptions?.providers || []).map((p) => (
                  <option key={p.slug} value={p.slug}>{p.label}</option>
                ))}
              </select>
              <select
                aria-label="模型"
                value={selectedModel}
                disabled={busy || !selectedProvider}
                onChange={(e) => setSelectedModel(e.target.value)}
                style={{ ...modelSelect, maxWidth: 180 }}
              >
                {(modelOptions?.providers.find((p) => p.slug === selectedProvider)?.models || []).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <select
                aria-label="推理强度"
                value={reasoningEffort}
                disabled={busy || modelsLoading || !modelOptions || selectedReasoningEfforts.length <= 1}
                onChange={(e) => setReasoningEffort(e.target.value)}
                style={modelSelect}
                title={
                  selectedReasoningEfforts.length > 1
                    ? `推理强度 · 来源 ${selectedCapability?.reasoning_source || 'unavailable'}`
                    : '该模型未从官方能力目录声明可选推理强度，使用模型默认值'
                }
              >
                {selectedReasoningEfforts.map((x) => (
                  <option key={x} value={x}>{x === 'auto' ? '推理 默认' : `推理 ${x}`}</option>
                ))}
              </select>
            </div>
            <span style={{ fontSize: 11, color: '#64748b' }}>Enter 发送 · Shift+Enter 换行</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea
              ref={textareaRef}
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="跟 hm 说你要什么…"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              style={{
                flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
                color: '#f8fafc', padding: '8px 10px', fontSize: 12, lineHeight: 1.4,
                outline: 'none', resize: 'vertical', minHeight: 60, maxHeight: 280, boxSizing: 'border-box',
              }}
            />
            <button
              onClick={() => send()}
              disabled={!input.trim()}
              style={{
                height: 42, background: !input.trim() ? '#334155' : busy ? 'linear-gradient(135deg, #7c3aed, #6d28d9)' : 'linear-gradient(135deg, #2563eb, #1d4ed8)',
                color: '#fff', border: 0, borderRadius: 8, padding: '0 16px',
                fontWeight: 600, fontSize: 13,
                cursor: !input.trim() ? 'not-allowed' : 'pointer',
              }}
              title={busy ? (busyInputMode === 'steer' ? '插入当前轮，下一次工具返回后生效' : '追加到当前会话，当前轮结束后自动执行') : '发送'}
            >
              {busy ? (busyInputMode === 'steer' ? '插入' : '追加') : '发送'}
            </button>
          </div>
        </div>
      </div>

      {/* 上下文勾选弹窗 */}
      <Modal
        open={showCtx}
        title="📎 选择要带上的上下文"
        subtitle={`来自「${TAB_LABEL[activeTab] || activeTab}」的实时数据 · 勾选后会拼进输入框，不会直接发送`}
        width={560}
        closeOnBackdrop={false}
        onClose={() => setShowCtx(false)}
        zIndex={100000}
        footer={(
          <>
            <button onClick={() => setCtxPicked(Object.fromEntries(ctxItems.map((item) => [item.key, true])))} style={smallBtn}>全选</button>
            <button onClick={() => setCtxPicked({})} style={smallBtn}>全不选</button>
            <span style={{ flex: 1 }} />
            <button onClick={() => setShowCtx(false)} style={smallBtn}>取消</button>
            <button onClick={applyContext} style={{ ...smallBtn, background: '#2563eb', color: '#fff' }}>
              加入输入框 ({ctxItems.filter((item) => ctxPicked[item.key]).length} 项 ·{' '}
              {(() => {
                const payload: Record<string, unknown> = {}
                ctxItems.filter((item) => ctxPicked[item.key]).forEach((item) => { payload[item.key] = item.payload })
                const length = JSON.stringify(payload).length
                return length > 1024 ? `${(length / 1024).toFixed(1)}KB` : `${length}B`
              })()})
            </button>
          </>
        )}
      >
        {ctxItems.length === 0 && (
          <div style={{ color: '#475569', fontSize: 12, textAlign: 'center', padding: '20px 0' }}>
            当前页面没有可提取的数据（可能还没加载完，或该页无结构化数据）
          </div>
        )}
        {ctxItems.map((item) => (
          <label key={item.key} style={{
            display: 'flex', alignItems: 'flex-start', gap: 8, padding: '7px 0',
            borderBottom: '1px solid #1f2937', cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={!!ctxPicked[item.key]}
              onChange={(event) => setCtxPicked((current) => ({ ...current, [item.key]: event.target.checked }))}
              style={{ marginTop: 3, accentColor: '#3b82f6', flexShrink: 0 }}
            />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 600 }}>{item.label}</div>
              <div style={{ fontSize: 11, color: '#64748b', wordBreak: 'break-word', maxHeight: 44, overflow: 'hidden' }}>
                {item.preview}
              </div>
            </div>
          </label>
        ))}
      </Modal>
    </>
  )
}

const modelSelect: React.CSSProperties = {
  background: '#0f172a', color: '#cbd5e1', border: '1px solid #334155',
  borderRadius: 5, padding: '4px 7px', fontSize: 10, maxWidth: 130,
}

const smallBtn: React.CSSProperties = {
  background: '#334155', color: '#cbd5e1', border: 0, borderRadius: 5,
  padding: '5px 12px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
}

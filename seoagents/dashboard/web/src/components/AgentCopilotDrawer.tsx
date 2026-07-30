import React, { useEffect, useRef, useState } from 'react'
import type { MetricsSummary } from './MetricsPanel'

export interface AgentCopilotDrawerProps {
  isOpen: boolean
  onClose: () => void
  activeTab: 'dashboard' | 'gsc_overview' | 'config'
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
  role?: string
  turns?: number
  trace?: TraceStep[]
  ts: string
}

interface PromptStarter {
  id: string
  title: string
  prompt: string
}

const DEFAULT_STARTERS: PromptStarter[] = [
  { id: '1', title: '🔍 诊断死链', prompt: '诊断首页收录与死链问题' },
  { id: '2', title: '✍️ E-E-A-T 重写', prompt: '为当前页面生成符合 E-E-A-T 的规范 Meta 与 Schema JSON-LD' },
  { id: '3', title: '🔗 内链优化', prompt: '分析并推荐当前页面的最佳锚文本与内链结构' },
]

export const AgentCopilotDrawer: React.FC<AgentCopilotDrawerProps> = ({
  isOpen,
  onClose,
  activeTab,
  summary,
  configData,
  drawerWidth,
  onWidthChange,
}) => {
  const [role, setRole] = useState<string>('auditor')
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'agent',
      text: '你好！我是 SEOAgents 智能体 Copilot。你可以随时向我下达 SEO 诊断、E-E-A-T 内容重写或内链优化任务。按住左侧蓝色控制条可平滑拖动调整面板宽度。点击【📌 附带当前页面上下文】可导入实时页面与配置数据！',
      ts: new Date().toLocaleTimeString(),
    },
  ])
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null)

  // Resizable Drag State
  const [isResizing, setIsResizing] = useState<boolean>(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Custom Quick Prompts State
  const [starters, setStarters] = useState<PromptStarter[]>(DEFAULT_STARTERS)
  const [showCustomPromptModal, setShowCustomPromptModal] = useState<boolean>(false)
  const [newStarterTitle, setNewStarterTitle] = useState('')
  const [newStarterPrompt, setNewStarterPrompt] = useState('')

  // Load custom prompts from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem('seoagents_custom_prompts')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          setStarters(parsed)
        }
      }
    } catch (e) {
      console.warn('Failed to load custom prompts from localStorage', e)
    }
  }, [])

  // Auto-expand Textarea Height on inputText change (Shift+Enter or Context Injection)
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      const newHeight = Math.min(Math.max(textareaRef.current.scrollHeight, 60), 280)
      textareaRef.current.style.height = `${newHeight}px`
    }
  }, [inputText])

  const saveStarters = (newStarters: PromptStarter[]) => {
    setStarters(newStarters)
    try {
      localStorage.setItem('seoagents_custom_prompts', JSON.stringify(newStarters))
    } catch (e) {
      console.warn('Failed to save custom prompts to localStorage', e)
    }
  }

  // 100% Reliable Screen Mask Mouse Drag Handling
  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      const newW = window.innerWidth - e.clientX
      const clampedW = Math.max(320, Math.min(newW, window.innerWidth - 80))
      onWidthChange(clampedW)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, onWidthChange])

  if (!isOpen) return null

  // Context Grabbing Logic (Handles both Dashboard & System Config, with Live Fetch Fallback)
  const handleGrabContext = async () => {
    let contextStr = ''
    if (activeTab === 'dashboard') {
      contextStr = `[当前监控大屏上下文快照]\n- 目标站点: ${summary?.site || 'https://example.com'}\n- 综合演化评分 M_t: ${
        summary?.latest_m_t != null ? summary.latest_m_t.toFixed(2) : '暂无'
      }\n- AEO 品牌可见度 V_t: ${
        summary?.v_t != null ? (summary.v_t * 100).toFixed(1) + '%' : '暂无'
      }\n- 未修复死链数: ${summary?.open_dead_links ?? 0}\n- SERP 关键词排位: ${
        summary?.serp_positions
          ?.map(p => `${p.keyword} (#${p.position ?? '未上榜'})`)
          .join(', ') || '无'
      }\n- 已固化静态技能数: ${summary?.skills?.filter(s => !s.built_in).length ?? 0}\n`
    } else {
      let cfg = configData
      if (!cfg || !cfg.resolved) {
        try {
          cfg = await fetch('/api/config').then(r => r.json())
        } catch (e) {
          console.warn('Failed to fetch config snapshot', e)
        }
      }

      const resv = cfg?.resolved || {}
      const redc = cfg?.redacted || {}

      contextStr = `[当前系统配置快照]\n- 目标站点: ${resv.site || redc?.sites?.site_url || '未指定'}\n- GSC 属性: ${
        resv.gsc_property || redc?.sites?.gsc_property || '未指定'
      }\n- LLM Provider: ${resv.provider || redc?.llm_providers?.default_provider || 'mock'}\n- 追踪关键词: ${
        (resv.tracked_keywords || redc?.sites?.tracked_keywords || []).join(', ') || '无'
      }\n- M_t 打分权重: alpha=${resv.scoring?.alpha ?? 0.4}, beta=${resv.scoring?.beta ?? 0.2}, gamma=${
        resv.scoring?.gamma ?? 0.3
      }, delta=${resv.scoring?.delta ?? 0.1}, 固化门槛分=${resv.scoring?.skill_compile_threshold ?? 150}\n- OpenSERP 端点: ${
        resv.openserp_endpoint || '未配置'
      }\n- Seonaut 端点: ${resv.seonaut_endpoint || '未配置'}\n- 飞书 Webhook: ${
        redc?.gateway?.feishu_webhook_url ? '已配置' : '未配置 (Dry-run)'
      }\n`
    }

    setInputText(prev => (prev ? `${prev}\n\n${contextStr}` : contextStr))
  }

  const handleAddCustomStarter = () => {
    const t = newStarterTitle.trim()
    const p = newStarterPrompt.trim()
    if (!t || !p) return
    const updated = [...starters, { id: `custom_${Date.now()}`, title: t, prompt: p }]
    saveStarters(updated)
    setNewStarterTitle('')
    setNewStarterPrompt('')
    setShowCustomPromptModal(false)
  }

  const handleRemoveStarter = (id: string) => {
    const updated = starters.filter(s => s.id !== id)
    saveStarters(updated)
  }

  const handleSend = async (taskOverride?: string) => {
    const textToSend = (taskOverride || inputText).trim()
    if (!textToSend || loading) return

    const userMsgId = `user_${Date.now()}`
    const userMsg: ChatMessage = {
      id: userMsgId,
      sender: 'user',
      text: textToSend,
      role: role,
      ts: new Date().toLocaleTimeString(),
    }

    setMessages(prev => [...prev, userMsg])
    if (!taskOverride) setInputText('')
    setLoading(true)

    try {
      const res = await fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: textToSend, role: role }),
      })
      const data = await res.json()

      if (data.ok) {
        const agentMsg: ChatMessage = {
          id: `agent_${Date.now()}`,
          sender: 'agent',
          text: data.data?.final_text || '任务处理完毕。',
          turns: data.data?.turns,
          trace: data.data?.trace || [],
          ts: new Date().toLocaleTimeString(),
        }
        setMessages(prev => [...prev, agentMsg])
      } else {
        setMessages(prev => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            sender: 'agent',
            text: `⚠️ 智能体执行失败: ${data.error || '未知错误'}`,
            ts: new Date().toLocaleTimeString(),
          },
        ])
      }
    } catch (e) {
      setMessages(prev => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          sender: 'agent',
          text: `⚠️ 网络请求异常: ${e}`,
          ts: new Date().toLocaleTimeString(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Full-screen Drag Mask to prevent iframe / text selection from swallowing mouse movements */}
      {isResizing && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 999999,
            cursor: 'col-resize',
            userSelect: 'none',
          }}
        />
      )}

      <div
        className="copilot-drawer"
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          width: `${drawerWidth}px`,
          maxWidth: '100vw',
          height: '100vh',
          background: '#0f172a',
          borderLeft: '1px solid #1e293b',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.5)',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        {/* Left Border Drag Handle (12px Grab Zone) */}
        <div
          onMouseDown={e => {
            e.preventDefault()
            setIsResizing(true)
          }}
          title="按住左右拖动调整 Copilot 面板宽度"
          style={{
            position: 'absolute',
            top: 0,
            left: '-6px',
            width: '12px',
            height: '100%',
            cursor: 'col-resize',
            zIndex: 10000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              width: '3px',
              height: '48px',
              borderRadius: '2px',
              background: isResizing ? '#3b82f6' : '#334155',
              transition: 'background 0.2s',
            }}
          />
        </div>

        {/* Header */}
        <div
          style={{
            padding: '14px 16px',
            background: '#1e293b',
            borderBottom: '1px solid #334155',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '20px' }}>🤖</span>
            <div>
              <div style={{ fontWeight: '700', fontSize: '15px', color: '#f8fafc' }}>
                SEOAgents Copilot
                <span style={{ fontSize: '11px', color: '#64748b', marginLeft: '8px' }}>({drawerWidth}px)</span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>常驻右侧 Copilot 控制台 · 可拖拽左侧控制条调节宽度</div>
            </div>
          </div>
          <button
            onClick={onClose}
            title="收起 Copilot 面板"
            style={{
              background: 'transparent',
              border: 0,
              color: '#94a3b8',
              fontSize: '18px',
              cursor: 'pointer',
              padding: '4px 8px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Role Selector */}
        <div
          style={{
            padding: '10px 16px',
            background: '#0f172a',
            borderBottom: '1px solid #1e293b',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span style={{ fontSize: '12px', color: '#64748b' }}>智能体角色:</span>
          <select
            value={role}
            onChange={e => setRole(e.target.value)}
            style={{
              flex: 1,
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '6px',
              color: '#38bdf8',
              fontSize: '12px',
              padding: '4px 8px',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="auditor">🔍 Auditor (SEO / 死链技术审计)</option>
            <option value="writer">✍️ Writer (E-E-A-T 内容重写润色)</option>
            <option value="linker">🔗 Linker (上下文锚文本内链优化)</option>
            <option value="universal">🤖 Universal Agent (全能智能体)</option>
          </select>
        </div>

        {/* Message Feed */}
        <div
          style={{
            flex: 1,
            padding: '16px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
          }}
        >
          {messages.map(msg => (
            <div
              key={msg.id}
              style={{
                alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '92%',
              }}
            >
              {/* Sender Label */}
              <div
                style={{
                  fontSize: '11px',
                  color: '#64748b',
                  marginBottom: '4px',
                  textAlign: msg.sender === 'user' ? 'right' : 'left',
                }}
              >
                {msg.sender === 'user' ? `你 (${msg.role || 'user'})` : 'SEOAgents Copilot'} · {msg.ts}
              </div>

              {/* Bubble Content */}
              <div
                style={{
                  background: msg.sender === 'user' ? '#2563eb' : '#1e293b',
                  color: msg.sender === 'user' ? '#ffffff' : '#e2e8f0',
                  padding: '12px 14px',
                  borderRadius: msg.sender === 'user' ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                  fontSize: '13px',
                  lineHeight: '1.5',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  border: msg.sender === 'user' ? 'none' : '1px solid #334155',
                }}
              >
                {msg.text}

                {/* Tool Trace Steps Visualization */}
                {msg.trace && msg.trace.length > 0 && (
                  <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid #334155' }}>
                    <button
                      onClick={() => setExpandedTraceId(expandedTraceId === msg.id ? null : msg.id)}
                      style={{
                        background: 'transparent',
                        border: 0,
                        color: '#38bdf8',
                        fontSize: '12px',
                        cursor: 'pointer',
                        padding: 0,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                    >
                      🛠️ 工具执行轨迹 ({msg.trace.length} 步) {expandedTraceId === msg.id ? '▲ 收起' : '▼ 展开'}
                    </button>

                    {expandedTraceId === msg.id && (
                      <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {msg.trace.map((step, idx) => (
                          <div
                            key={idx}
                            style={{
                              background: '#0f172a',
                              border: `1px solid ${step.ok ? '#059669' : '#dc2626'}`,
                              borderRadius: '6px',
                              padding: '8px',
                              fontSize: '11px',
                              fontFamily: 'monospace',
                            }}
                          >
                            <div style={{ color: step.ok ? '#34d399' : '#f87171', fontWeight: 'bold' }}>
                              #{idx + 1} {step.tool} ({step.ok ? 'SUCCESS' : 'FAILED'})
                            </div>
                            {step.arguments && (
                              <div style={{ color: '#94a3b8', marginTop: '4px' }}>
                                Arg: {JSON.stringify(step.arguments)}
                              </div>
                            )}
                            <div style={{ color: '#cbd5e1', marginTop: '4px', maxHeight: '120px', overflowY: 'auto' }}>
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

          {loading && (
            <div style={{ alignSelf: 'flex-start', color: '#38bdf8', fontSize: '12px', display: 'flex', gap: '6px' }}>
              <span>⏳ 智能体思考与工具调用中...</span>
            </div>
          )}
        </div>

        {/* Customizable Quick Prompt Starters */}
        <div style={{ padding: '8px 16px', background: '#0f172a', borderTop: '1px solid #1e293b' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '11px', color: '#64748b' }}>快捷任务提示词:</span>
            <button
              onClick={() => setShowCustomPromptModal(!showCustomPromptModal)}
              style={{
                background: 'transparent',
                border: 0,
                color: '#60a5fa',
                fontSize: '11px',
                cursor: 'pointer',
                padding: 0,
              }}
            >
              {showCustomPromptModal ? '收起设置' : '⚙️ 自定义提示词'}
            </button>
          </div>

          {/* Custom Prompt Edit Form */}
          {showCustomPromptModal && (
            <div
              style={{
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                padding: '10px',
                marginBottom: '10px',
              }}
            >
              <div style={{ fontSize: '12px', color: '#f3f4f6', fontWeight: 'bold', marginBottom: '8px' }}>
                添加自定义提示词模版
              </div>
              <input
                type="text"
                placeholder="提示词按钮标题 (例: 📊 SERP分析)"
                value={newStarterTitle}
                onChange={e => setNewStarterTitle(e.target.value)}
                style={{
                  width: '100%',
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#fff',
                  padding: '6px 8px',
                  fontSize: '12px',
                  marginBottom: '6px',
                  boxSizing: 'border-box',
                }}
              />
              <input
                type="text"
                placeholder="提示词完整任务文本..."
                value={newStarterPrompt}
                onChange={e => setNewStarterPrompt(e.target.value)}
                style={{
                  width: '100%',
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#fff',
                  padding: '6px 8px',
                  fontSize: '12px',
                  marginBottom: '8px',
                  boxSizing: 'border-box',
                }}
              />
              <div style={{ textAlign: 'right' }}>
                <button
                  onClick={handleAddCustomStarter}
                  style={{
                    background: '#2563eb',
                    color: '#fff',
                    border: 0,
                    borderRadius: '4px',
                    padding: '4px 12px',
                    fontSize: '12px',
                    cursor: 'pointer',
                  }}
                >
                  + 保存添加
                </button>
              </div>
            </div>
          )}

          {/* Prompt Badges List */}
          <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', paddingBottom: '4px' }}>
            {starters.map(st => (
              <span
                key={st.id}
                style={{
                  background: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  color: '#94a3b8',
                  fontSize: '11px',
                  padding: '3px 10px',
                  whiteSpace: 'nowrap',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span onClick={() => handleSend(st.prompt)} style={{ cursor: 'pointer', color: '#93c5fd' }}>
                  {st.title}
                </span>
                {starters.length > 1 && (
                  <span
                    onClick={() => handleRemoveStarter(st.id)}
                    title="删除该提示词"
                    style={{ cursor: 'pointer', color: '#f87171', fontSize: '12px' }}
                  >
                    ×
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>

        {/* Input Area with Auto-expanding & Resizable Textarea */}
        <div style={{ padding: '12px 16px', background: '#1e293b', borderTop: '1px solid #334155' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <button
              onClick={handleGrabContext}
              style={{
                background: '#334155',
                border: 0,
                borderRadius: '4px',
                color: '#38bdf8',
                fontSize: '11px',
                padding: '4px 10px',
                cursor: 'pointer',
                fontWeight: '500',
              }}
            >
              📌 附带当前页面上下文 ({activeTab === 'dashboard' ? '监控大屏' : '系统配置'})
            </button>
            <span style={{ fontSize: '11px', color: '#64748b' }}>Shift+Enter 换行自动撑高</span>
          </div>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
            <textarea
              ref={textareaRef}
              rows={2}
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              placeholder="与 SEOAgents 智能体对话，下达诊断或优化指令 (Shift+Enter 换行自动撑高)..."
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              style={{
                flex: 1,
                background: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: '#f8fafc',
                padding: '8px 10px',
                fontSize: '12px',
                lineHeight: '1.4',
                outline: 'none',
                resize: 'vertical',
                minHeight: '60px',
                maxHeight: '280px',
                boxSizing: 'border-box',
              }}
            />
            <button
              onClick={() => handleSend()}
              disabled={loading || !inputText.trim()}
              style={{
                height: '42px',
                background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
                color: '#fff',
                border: 0,
                borderRadius: '8px',
                padding: '0 16px',
                fontWeight: '600',
                fontSize: '13px',
                cursor: loading || !inputText.trim() ? 'not-allowed' : 'pointer',
                opacity: loading || !inputText.trim() ? 0.6 : 1,
              }}
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

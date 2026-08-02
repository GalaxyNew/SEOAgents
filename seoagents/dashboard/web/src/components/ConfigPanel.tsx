import React, { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'

export interface ConfigPanelProps {
  onConfigSaved?: () => void
}

const cardStyle: React.CSSProperties = {
  background: '#111827',
  border: '1px solid #1f2937',
  borderRadius: '12px',
  padding: '20px',
  marginBottom: '20px',
  boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
}

const sectionHeaderStyle: React.CSSProperties = {
  fontSize: '15px',
  fontWeight: '600',
  color: '#60a5fa',
  borderBottom: '1px solid #1f2937',
  paddingBottom: '8px',
  marginBottom: '16px',
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '13px',
  fontWeight: '500',
  color: '#9ca3af',
  marginBottom: '6px',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: '#1f2937',
  border: '1px solid #374151',
  borderRadius: '8px',
  padding: '10px 12px',
  color: '#f3f4f6',
  fontSize: '14px',
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.2s',
}

const numInputStyle: React.CSSProperties = {
  ...inputStyle,
  width: '100%',
}

export const ConfigPanel: React.FC<ConfigPanelProps> = ({ onConfigSaved }) => {
  const isMobile = useIsMobile()
  const [loading, setLoading] = useState<boolean>(true)
  const [saving, setSaving] = useState<boolean>(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Form State
  const [siteUrl, setSiteUrl] = useState('')
  const [gscProperty, setGscProperty] = useState('')
  const [brandName, setBrandName] = useState('')
  const [keywords, setKeywords] = useState<string[]>([])
  const [newKw, setNewKw] = useState('')

  const [provider, setProvider] = useState('mock')
  const [anthropicKey, setAnthropicKey] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [openaiModel, setOpenaiModel] = useState('')
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('')

  const [alpha, setAlpha] = useState(0.4)
  const [beta, setBeta] = useState(0.2)
  const [gamma, setGamma] = useState(0.3)
  const [delta, setDelta] = useState(0.1)
  const [threshold, setThreshold] = useState(150.0)

  const [openserpEndpoint, setOpenserpEndpoint] = useState('')
  const [seonautEndpoint, setSeonautEndpoint] = useState('')
  const [feishuWebhook, setFeishuWebhook] = useState('')

  // Multi-Site State
  const [monitoredSites, setMonitoredSites] = useState<Array<{ site_url: string; gsc_property: string; brand_name: string; tracked_keywords: string[] }>>([])
  const [newSiteUrl, setNewSiteUrl] = useState('')
  const [newSiteGsc, setNewSiteGsc] = useState('')
  const [newSiteBrand, setNewSiteBrand] = useState('')

  const fetchConfig = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/config')
      const data = await res.json()
      const raw = data.redacted || {}
      const resv = data.resolved || {}

      setSiteUrl(raw?.sites?.site_url || resv?.site || '')
      setGscProperty(raw?.sites?.gsc_property || resv?.gsc_property || '')
      setBrandName(raw?.sites?.brand_name || '')
      setKeywords(raw?.sites?.tracked_keywords || resv?.tracked_keywords || [])
      setMonitoredSites(resv?.monitored_sites || [])

      setProvider(raw?.llm_providers?.default_provider || resv?.provider || 'mock')
      setAnthropicKey(raw?.llm_providers?.anthropic?.api_key || '')
      setOpenaiKey(raw?.llm_providers?.openai_compat?.api_key || '')
      setOpenaiModel(raw?.llm_providers?.openai_compat?.model || '')
      setOpenaiBaseUrl(raw?.llm_providers?.openai_compat?.base_url || '')

      setAlpha(raw?.scoring?.alpha ?? resv?.scoring?.alpha ?? 0.4)
      setBeta(raw?.scoring?.beta ?? resv?.scoring?.beta ?? 0.2)
      setGamma(raw?.scoring?.gamma ?? resv?.scoring?.gamma ?? 0.3)
      setDelta(raw?.scoring?.delta ?? resv?.scoring?.delta ?? 0.1)
      setThreshold(raw?.scoring?.skill_compile_threshold ?? resv?.scoring?.skill_compile_threshold ?? 150.0)

      setOpenserpEndpoint(raw?.seo_credentials?.openserp_endpoint || resv?.openserp_endpoint || '')
      setSeonautEndpoint(raw?.seo_credentials?.seonaut_endpoint || resv?.seonaut_endpoint || '')
      setFeishuWebhook(raw?.gateway?.feishu_webhook_url || '')
    } catch (err) {
      setMessage({ type: 'error', text: `配置加载失败: ${err}` })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchConfig()
  }, [])

  const handleAddKeyword = () => {
    const trimmed = newKw.trim()
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords([...keywords, trimmed])
      setNewKw('')
    }
  }

  const handleRemoveKeyword = (kw: string) => {
    setKeywords(keywords.filter(k => k !== kw))
  }

  const handleAddNewSiteClick = () => {
    const defaultUrl = `https://newsite-${monitoredSites.length + 1}.com`
    const defaultGsc = `sc-domain:newsite-${monitoredSites.length + 1}.com`
    const defaultBrand = `NewSite ${monitoredSites.length + 1}`
    const newSite = {
      site_url: defaultUrl,
      gsc_property: defaultGsc,
      brand_name: defaultBrand,
      tracked_keywords: ['seo', 'aeo'],
    }
    const updated = [...monitoredSites, newSite]
    setMonitoredSites(updated)
    setSiteUrl(defaultUrl)
    setGscProperty(defaultGsc)
    setBrandName(defaultBrand)
    setKeywords(['seo', 'aeo'])
  }

  const handleRemoveSite = (url: string) => {
    const filtered = monitoredSites.filter(s => s.site_url !== url)
    setMonitoredSites(filtered)
    if (url === siteUrl && filtered.length > 0) {
      handleSelectSiteAsPrimary(filtered[0])
    }
  }

  const handleSelectSiteAsPrimary = (s: { site_url: string; gsc_property: string; brand_name: string; tracked_keywords: string[] }) => {
    // Before switching, sync current edits back to current site in list
    setMonitoredSites(prev =>
      prev.map(item => (item.site_url === siteUrl ? { ...item, site_url: siteUrl, gsc_property: gscProperty, brand_name: brandName, tracked_keywords: keywords } : item))
    )
    setSiteUrl(s.site_url)
    setGscProperty(s.gsc_property)
    setBrandName(s.brand_name)
    setKeywords(s.tracked_keywords || [])
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMessage(null)

    // Sync current form state into monitoredSites list
    const currentInList = monitoredSites.find(s => s.site_url === siteUrl)
    const sitesListPayload = currentInList
      ? monitoredSites.map(s => (s.site_url === siteUrl ? { site_url: siteUrl, gsc_property: gscProperty, brand_name: brandName, tracked_keywords: keywords } : s))
      : [{ site_url: siteUrl, gsc_property: gscProperty, brand_name: brandName, tracked_keywords: keywords }, ...monitoredSites]

    const patch = {
      sites: {
        site_url: siteUrl,
        gsc_property: gscProperty,
        brand_name: brandName,
        tracked_keywords: keywords,
        monitored_sites: sitesListPayload,
      },
      llm_providers: {
        default_provider: provider,
        anthropic: {
          api_key: anthropicKey,
        },
        openai_compat: {
          api_key: openaiKey,
          model: openaiModel,
          base_url: openaiBaseUrl,
        },
      },
      scoring: {
        alpha: Number(alpha),
        beta: Number(beta),
        gamma: Number(gamma),
        delta: Number(delta),
        skill_compile_threshold: Number(threshold),
      },
      seo_credentials: {
        openserp_endpoint: openserpEndpoint,
        seonaut_endpoint: seonautEndpoint,
      },
      gateway: {
        feishu_webhook_url: feishuWebhook,
      },
    }

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      const data = await res.json()
      if (data.ok) {
        setMessage({ type: 'success', text: '✅ 配置保存成功！改动已写入 ~/.dojo/agents.yaml 并实时生效。' })
        if (onConfigSaved) onConfigSaved()
      } else {
        setMessage({ type: 'error', text: `保存失败: ${data.error || '未知错误'}` })
      }
    } catch (err) {
      setMessage({ type: 'error', text: `请求异常: ${err}` })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div style={{ ...cardStyle, color: '#9ca3af', textAlign: 'center' }}>⚙️ 正在载入系统配置...</div>
  }

  return (
    <form onSubmit={handleSave} style={{ width: '100%', margin: '0 auto' }}>
      {message && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            fontSize: '14px',
            background: message.type === 'success' ? '#064e3b' : '#7f1d1d',
            color: message.type === 'success' ? '#6ee7b7' : '#fca5a5',
            border: `1px solid ${message.type === 'success' ? '#059669' : '#dc2626'}`,
          }}
        >
          {message.text}
        </div>
      )}

      {/* 统一的监控站点与关键词配置 */}
      <div style={cardStyle}>
        <div style={{ ...sectionHeaderStyle, justifyContent: 'space-between' }}>
          <span>🌐 监控站点与关键词管理 (Monitored Sites)</span>
          <button
            type="button"
            onClick={handleAddNewSiteClick}
            style={{
              background: '#2563eb',
              color: '#fff',
              border: 0,
              borderRadius: '6px',
              padding: '6px 14px',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            + 纳管新站点
          </button>
        </div>

        {/* 已纳管多站点选择列表 */}
        <div style={{ marginBottom: '20px' }}>
          <label style={labelStyle}>已纳管监控站点列表（点击站点卡片可随时切换编辑或激活）：</label>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(280px, 1fr))', gap: '10px', marginTop: '8px' }}>
            {monitoredSites.map((s, idx) => {
              const isSelected = s.site_url === siteUrl
              return (
                <div
                  key={idx}
                  onClick={() => handleSelectSiteAsPrimary(s)}
                  style={{
                    background: isSelected ? '#1e293b' : '#1f2937',
                    border: `1.5px solid ${isSelected ? '#3b82f6' : '#374151'}`,
                    borderRadius: '10px',
                    padding: '12px 14px',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    position: 'relative',
                    boxShadow: isSelected ? '0 0 12px rgba(59,130,246,0.25)' : 'none',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: isSelected ? '#60a5fa' : '#9ca3af' }}>
                      {isSelected ? '★ 当前激活主站' : `站点 ${idx + 1}`}
                    </span>
                    {monitoredSites.length > 1 && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          handleRemoveSite(s.site_url)
                        }}
                        style={{
                          background: 'transparent',
                          color: '#ef4444',
                          border: 0,
                          fontSize: '13px',
                          cursor: 'pointer',
                          padding: '0 4px',
                        }}
                        title="删除站点"
                      >
                        ✕
                      </button>
                    )}
                  </div>

                  <div style={{ fontSize: '14px', fontWeight: '700', color: '#f3f4f6', marginBottom: '4px', wordBreak: 'break-all' }}>
                    {s.site_url}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9ca3af' }}>
                    GSC: {s.gsc_property}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9ca3af', marginTop: '2px' }}>
                    品牌: {s.brand_name || '未设'} | 词库: {s.tracked_keywords?.length || 0} 个
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* 当前选中站点的配置编辑表单 */}
        <div style={{ background: '#182232', border: '1px solid #283548', borderRadius: '10px', padding: '16px', marginTop: '14px' }}>
          <div style={{ fontSize: '14px', fontWeight: '700', color: '#60a5fa', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>✏️ 编辑站点配置：</span>
            <span style={{ color: '#f3f4f6', fontFamily: 'monospace' }}>{siteUrl}</span>
          </div>

          <div className="grid-2-col" style={{ marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>站点 URL (Site URL)</label>
              <input
                type="text"
                value={siteUrl}
                onChange={e => setSiteUrl(e.target.value)}
                placeholder="https://example.com"
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>GSC 属性标识 (Domain Property)</label>
              <input
                type="text"
                value={gscProperty}
                onChange={e => setGscProperty(e.target.value)}
                placeholder="sc-domain:example.com"
                style={inputStyle}
              />
            </div>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>品牌名称 (AEO/GEO 品牌识别)</label>
            <input
              type="text"
              value={brandName}
              onChange={e => setBrandName(e.target.value)}
              placeholder="SEOAgents"
              style={inputStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>追踪核心关键词列表 (SEO Tracked Keywords)</label>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
              <input
                type="text"
                value={newKw}
                onChange={e => setNewKw(e.target.value)}
                placeholder="输入关键词按回车或点击添加"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleAddKeyword()
                  }
                }}
                style={{ ...inputStyle, flex: '1 1 200px' }}
              />
              <button
                type="button"
                onClick={handleAddKeyword}
                style={{
                  background: '#2563eb',
                  color: '#fff',
                  border: 0,
                  borderRadius: '8px',
                  padding: '0 20px',
                  height: '42px',
                  cursor: 'pointer',
                  fontWeight: '600',
                }}
              >
                + 添加
              </button>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {keywords.map((kw, i) => (
                <span
                  key={i}
                  style={{
                    background: '#1e293b',
                    color: '#60a5fa',
                    border: '1px solid #3b82f6',
                    borderRadius: '16px',
                    padding: '4px 12px',
                    fontSize: '13px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  {kw}
                  <button
                    type="button"
                    onClick={() => handleRemoveKeyword(kw)}
                    style={{ background: 'transparent', color: '#9ca3af', border: 0, cursor: 'pointer', padding: 0, fontWeight: 'bold' }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* LLM Provider 配置 */}

      <div style={cardStyle}>
        <div style={sectionHeaderStyle}>🤖 LLM 智能体引擎配置</div>
        <div style={{ marginBottom: '16px' }}>
          <label style={labelStyle}>默认 LLM Provider</label>
          <select
            value={provider}
            onChange={e => setProvider(e.target.value)}
            style={{ ...inputStyle, cursor: 'pointer', height: '42px' }}
          >
            <option value="mock">Mock 降级模式 (无密钥，确定性演示数据)</option>
            <option value="anthropic">Anthropic (Claude 3.5 Sonnet / Haiku)</option>
            <option value="openai_compat">OpenAI 兼容接口 (DeepSeek / GLM / 本地 Ollama)</option>
          </select>
        </div>

        {provider === 'anthropic' && (
          <div>
            <label style={labelStyle}>Anthropic API Key</label>
            <input
              type="password"
              value={anthropicKey}
              onChange={e => setAnthropicKey(e.target.value)}
              placeholder="sk-ant-..."
              style={inputStyle}
            />
          </div>
        )}

        {provider === 'openai_compat' && (
          <div className="grid-2-col">
            <div>
              <label style={labelStyle}>API Key</label>
              <input
                type="password"
                value={openaiKey}
                onChange={e => setOpenaiKey(e.target.value)}
                placeholder="sk-..."
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>模型名称 (Model)</label>
              <input
                type="text"
                value={openaiModel}
                onChange={e => setOpenaiModel(e.target.value)}
                placeholder="deepseek-chat 或 gpt-4o"
                style={inputStyle}
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>Base URL (自定义端点，可选)</label>
              <input
                type="text"
                value={openaiBaseUrl}
                onChange={e => setOpenaiBaseUrl(e.target.value)}
                placeholder="https://api.deepseek.com/v1"
                style={inputStyle}
              />
            </div>
          </div>
        )}
      </div>

      {/* M_t 量化公式打分权重 */}
      <div style={cardStyle}>
        <div style={sectionHeaderStyle}>🧮 Self-Evolution 自进化打分权重 ($M_t$)</div>
        <p style={{ fontSize: '12px', color: '#9ca3af', marginTop: '-8px', marginBottom: '16px' }}>
          公式：M_t = α·C_t + β·I_t + γ·Σ(W_i / R_it) - δ·E_t
        </p>

        <div className="grid-4-col" style={{ marginBottom: '16px' }}>
          <div>
            <label style={labelStyle}>Alpha ($\alpha$) - 点击量增量</label>
            <input
              type="number"
              step="0.05"
              value={alpha}
              onChange={e => setAlpha(parseFloat(e.target.value) || 0)}
              style={numInputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Beta ($\beta$) - 索引收录率</label>
            <input
              type="number"
              step="0.05"
              value={beta}
              onChange={e => setBeta(parseFloat(e.target.value) || 0)}
              style={numInputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Gamma ($\gamma$) - SERP 排位</label>
            <input
              type="number"
              step="0.05"
              value={gamma}
              onChange={e => setGamma(parseFloat(e.target.value) || 0)}
              style={numInputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Delta ($\delta$) - 缺陷惩罚</label>
            <input
              type="number"
              step="0.05"
              value={delta}
              onChange={e => setDelta(parseFloat(e.target.value) || 0)}
              style={numInputStyle}
            />
          </div>
        </div>

        <div>
          <label style={labelStyle}>技能固化阈值 (Skill Compile Threshold)</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <input
              type="number"
              step="5"
              value={threshold}
              onChange={e => setThreshold(parseFloat(e.target.value) || 150)}
              style={{ ...numInputStyle, maxWidth: '200px' }}
            />
            <span style={{ fontSize: '12px', color: '#6b7280' }}>
              当演化得分低于该阈值时触发自动重写与内链优化修复
            </span>
          </div>
        </div>
      </div>

      {/* 外挂端点与通知 */}
      <div style={cardStyle}>
        <div style={sectionHeaderStyle}>🔗 服务端点与飞书通知网关</div>
        <div className="grid-2-col" style={{ marginBottom: '16px' }}>
          <div>
            <label style={labelStyle}>OpenSERP 端点 URL</label>
            <input
              type="text"
              value={openserpEndpoint}
              onChange={e => setOpenserpEndpoint(e.target.value)}
              placeholder="http://localhost:7000"
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Seonaut 审计面板 URL</label>
            <input
              type="text"
              value={seonautEndpoint}
              onChange={e => setSeonautEndpoint(e.target.value)}
              placeholder="http://localhost:8080"
              style={inputStyle}
            />
          </div>
        </div>

        <div>
          <label style={labelStyle}>飞书群机器人 Webhook 地址 (留空 = dry-run 控制台打印)</label>
          <input
            type="text"
            value={feishuWebhook}
            onChange={e => setFeishuWebhook(e.target.value)}
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
            style={inputStyle}
          />
        </div>
      </div>

      {/* 提交按钮 */}
      <div style={{ textAlign: 'right', marginTop: '24px' }}>
        <button
          type="submit"
          disabled={saving}
          style={{
            width: '100%',
            maxWidth: '300px',
            background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
            color: '#fff',
            border: 0,
            borderRadius: '8px',
            padding: '14px 32px',
            fontSize: '15px',
            fontWeight: '600',
            cursor: saving ? 'wait' : 'pointer',
            boxShadow: '0 4px 14px rgba(37,99,235,0.4)',
          }}
        >
          {saving ? '⏳ 保存应用中...' : '💾 保存并实时应用配置'}
        </button>
      </div>
    </form>
  )
}

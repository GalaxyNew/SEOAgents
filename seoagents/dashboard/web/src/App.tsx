import { useEffect, useRef, useState } from 'react'
import { SeoAuditPanel } from './components/SeoAuditPanel'
import { MetricsPanel, type MetricsSummary } from './components/MetricsPanel'
import { ConfigPanel } from './components/ConfigPanel'
import { AgentCopilotDrawer } from './components/AgentCopilotDrawer'
import { GscOverviewPanel } from './components/GscOverviewPanel'
import { KanbanPanel } from './components/KanbanPanel'
import { TimelinePanel } from './components/TimelinePanel'
import { WorkflowPanel } from './components/WorkflowPanel'
import { CapabilityPanel } from './components/CapabilityPanel'
import { DepartmentPanel } from './components/DepartmentPanel'
import { useIsMobile } from './hooks'

type TabId = 'dashboard' | 'gsc_overview' | 'kanban' | 'timeline' | 'workflow' | 'capability' | 'departments' | 'config'

export default function App() {
  // tab 存进 URL hash:刷新后回到原页面,链接也能直接分享到具体页
  const VALID_TABS: TabId[] = ['dashboard', 'gsc_overview', 'kanban', 'timeline', 'workflow', 'capability', 'departments', 'config']
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const h = (window.location.hash || '').replace(/^#\/?/, '') as TabId
    return VALID_TABS.includes(h) ? h : 'dashboard'
  })
  useEffect(() => {
    if (window.location.hash.replace(/^#\/?/, '') !== activeTab) {
      window.history.replaceState(null, '', `#${activeTab}`)
    }
  }, [activeTab])
  useEffect(() => {
    const onHash = () => {
      const h = (window.location.hash || '').replace(/^#\/?/, '') as TabId
      if (VALID_TABS.includes(h) && h !== activeTab) setActiveTab(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [activeTab])
  const isMobile = useIsMobile()
  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [configData, setConfigData] = useState<any>(null)
  const [seonautEndpoint, setSeonautEndpoint] = useState<string>('')
  const [providerName, setProviderName] = useState<string>('mock')
  const [isCopilotOpen, setIsCopilotOpen] = useState<boolean>(true)
  const [copilotWidth, setCopilotWidth] = useState<number>(460)
  const [isDesktop, setIsDesktop] = useState<boolean>(window.innerWidth >= 1024)

  // Right-side Settings Dropdown state
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false)
  const settingsRef = useRef<HTMLDivElement>(null)

  const refresh = async () => {
    try {
      const sum = await fetch('/api/metrics/summary').then(r => r.json())
      setSummary(sum)
      const cfg = await fetch('/api/config').then(r => r.json())
      setConfigData(cfg)
      setSeonautEndpoint(cfg?.resolved?.seonaut_endpoint ?? '')
      setProviderName(cfg?.resolved?.provider ?? 'mock')
    } catch (e) {
      console.warn('refresh failed', e)
    }
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30_000)

    const handleResize = () => {
      setIsDesktop(window.innerWidth >= 1024)
    }
    window.addEventListener('resize', handleResize)

    // Click outside to close settings dropdown
    const handleClickOutside = (event: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(event.target as Node)) {
        setIsSettingsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)

    return () => {
      clearInterval(timer)
      window.removeEventListener('resize', handleResize)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [])

  return (
    <div style={{ minHeight: '100vh', background: '#0b0f19', color: '#e6edf6', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {/* Header */}
      <header
        style={{
          background: '#111827',
          borderBottom: '1px solid #1f2937',
          padding: '14px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        {/* Left: Brand Logo & Title */}
        <div
          onClick={() => setActiveTab('dashboard')}
          style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }}
          title="点击返回监控大屏"
        >
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              fontSize: '18px',
              color: '#fff',
              boxShadow: '0 2px 8px rgba(59,130,246,0.3)',
            }}
          >
            S
          </div>
          <div>
            <h1 style={{ fontSize: '18px', fontWeight: '700', margin: 0, color: '#f3f4f6', display: 'flex', alignItems: 'center', gap: '8px' }}>
              SEOAgents · 自进化智能体集群
            </h1>
            <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>
              {summary?.site || 'https://example.com'} · DojoAgents 七层架构
            </div>
          </div>
        </div>

        {/* Center Nav: Quick View Switcher */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: '6px', overflowX: 'auto', maxWidth: '100%', paddingBottom: '2px', scrollbarWidth: 'thin' }}>
          {([
            ['dashboard', '📊 监控大屏'],
            ['gsc_overview', '📈 GSC 大屏'],
            ['kanban', '📋 任务卡'],
            ['timeline', '🗓️ 时间规划'],
            ['workflow', '⚙️ 工作流'],
            ['capability', '🧭 能力中心'],
          ] as Array<[TabId, string]>).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                background: activeTab === id ? '#1e293b' : 'transparent',
                color: activeTab === id ? '#60a5fa' : '#9ca3af',
                border: `1px solid ${activeTab === id ? '#3b82f6' : 'transparent'}`,
                borderRadius: '8px',
                padding: isMobile ? '5px 9px' : '6px 12px',
                fontSize: isMobile ? '12px' : '13px',
                fontWeight: '600',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                transition: 'all 0.2s ease',
              }}
            >
              {label}
            </button>
          ))}

          {activeTab === 'config' && (
            <span
              style={{
                fontSize: '12px',
                color: '#3b82f6',
                background: '#1e1b4b',
                padding: '4px 10px',
                borderRadius: '6px',
                border: '1px solid #4338ca',
                fontWeight: '500',
              }}
            >
              ⚙️ 当前位置：配置中心
            </span>
          )}
        </nav>


        {/* Right Side Controls & Settings Dropdown */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '12px' }}>
          <span
            style={{
              background: '#064e3b',
              color: '#34d399',
              padding: '4px 10px',
              borderRadius: '12px',
              border: '1px solid #059669',
              fontWeight: '500',
            }}
          >
            ● Active Monitor
          </span>
          <span
            style={{
              background: '#1e1b4b',
              color: '#a5b4fc',
              padding: '4px 10px',
              borderRadius: '12px',
              border: '1px solid #4338ca',
            }}
          >
            Provider: {providerName}
          </span>


          {/* Settings Dropdown Button */}
          <div ref={settingsRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setIsSettingsOpen(!isSettingsOpen)}
              style={{
                background: isSettingsOpen ? '#374151' : '#1f2937',
                color: '#f3f4f6',
                border: '1px solid #374151',
                borderRadius: '8px',
                padding: '7px 14px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'background-color 0.2s',
                boxShadow: isSettingsOpen ? '0 0 0 2px rgba(59,130,246,0.4)' : 'none',
              }}
            >
              <span>⚙️ 设置</span>
              <span style={{ fontSize: '10px', transition: 'transform 0.2s', transform: isSettingsOpen ? 'rotate(180deg)' : 'rotate(0)' }}>▼</span>
            </button>

            {/* Dropdown Menu Popup */}
            {isSettingsOpen && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 8px)',
                  width: '200px',
                  background: '#111827',
                  border: '1px solid #374151',
                  borderRadius: '10px',
                  padding: '6px',
                  boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
                  zIndex: 1000,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '2px',
                }}
              >
                <button
                  onClick={() => {
                    setActiveTab('gsc_overview')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'gsc_overview' ? '#1f2937' : 'transparent',
                    color: activeTab === 'gsc_overview' ? '#60a5fa' : '#e5e7eb',
                    border: 0,
                    borderRadius: '6px',
                    padding: '10px 12px',
                    fontSize: '13px',
                    fontWeight: '500',
                    textAlign: 'left',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    width: '100%',
                    boxSizing: 'border-box',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1f2937')}
                  onMouseLeave={e => (e.currentTarget.style.background = activeTab === 'gsc_overview' ? '#1f2937' : 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    📈 GSC 数据大屏
                  </span>
                  {activeTab === 'gsc_overview' && <span style={{ fontSize: '12px', color: '#60a5fa' }}>✓</span>}
                </button>

                <button
                  onClick={() => {
                    setActiveTab('departments')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'departments' ? '#1f2937' : 'transparent',
                    color: activeTab === 'departments' ? '#60a5fa' : '#e5e7eb',
                    border: 0,
                    borderRadius: '6px',
                    padding: '10px 12px',
                    fontSize: '13px',
                    fontWeight: '500',
                    textAlign: 'left',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    width: '100%',
                    boxSizing: 'border-box',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1f2937')}
                  onMouseLeave={e => (e.currentTarget.style.background = activeTab === 'departments' ? '#1f2937' : 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    🏢 部门管理
                  </span>
                  {activeTab === 'departments' && <span style={{ fontSize: '12px', color: '#60a5fa' }}>✓</span>}
                </button>

                <button
                  onClick={() => {
                    setActiveTab('config')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'config' ? '#1f2937' : 'transparent',
                    color: activeTab === 'config' ? '#60a5fa' : '#e5e7eb',
                    border: 0,
                    borderRadius: '6px',
                    padding: '10px 12px',
                    fontSize: '13px',
                    fontWeight: '500',
                    textAlign: 'left',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    width: '100%',
                    boxSizing: 'border-box',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1f2937')}
                  onMouseLeave={e => (e.currentTarget.style.background = activeTab === 'config' ? '#1f2937' : 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    ⚙️ 系统配置中心
                  </span>
                  {activeTab === 'config' && <span style={{ fontSize: '12px', color: '#60a5fa' }}>✓</span>}
                </button>


                <a
                  href="/docs"
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => setIsSettingsOpen(false)}
                  style={{
                    background: 'transparent',
                    color: '#e5e7eb',
                    borderRadius: '6px',
                    padding: '10px 12px',
                    fontSize: '13px',
                    fontWeight: '500',
                    textDecoration: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    boxSizing: 'border-box',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1f2937')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    📚 API 接口文档
                  </span>
                  <span style={{ fontSize: '11px', color: '#9ca3af' }}>↗</span>
                </a>

                {activeTab === 'config' && (
                  <>
                    <div style={{ height: '1px', background: '#1f2937', margin: '4px 0' }} />
                    <button
                      onClick={() => {
                        setActiveTab('dashboard')
                        setIsSettingsOpen(false)
                      }}
                      style={{
                        background: 'transparent',
                        color: '#9ca3af',
                        border: 0,
                        borderRadius: '6px',
                        padding: '8px 12px',
                        fontSize: '12px',
                        fontWeight: '500',
                        textAlign: 'left',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        width: '100%',
                        boxSizing: 'border-box',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = '#1f2937')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      📊 返回监控大屏
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Area (uncompressed, full-featured layout) */}
      <main
        style={{
          flex: 1,
          height: 'calc(100vh - 65px)',
          maxHeight: 'calc(100vh - 65px)',
          overflowY: activeTab === 'gsc_overview' ? 'hidden' : 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          padding: isMobile ? '10px 12px' : '12px 20px',
          paddingRight: isDesktop && isCopilotOpen ? `${copilotWidth + 20}px` : (isMobile ? '12px' : '20px'),
          width: '100%',
          maxWidth: '100%',
          margin: '0 auto',
          boxSizing: 'border-box',
          transition: 'padding-right 0.2s ease',
        }}
      >


        {activeTab === 'dashboard' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <MetricsPanel summary={summary} onRefresh={refresh} />
            <SeoAuditPanel seonautEndpoint={seonautEndpoint} />
          </div>
        )}

        {activeTab === 'gsc_overview' && (
          <GscOverviewPanel
            monitoredSites={configData?.resolved?.monitored_sites || []}
            onSelectSite={site => {
              setConfigData((prev: any) => ({
                ...prev,
                resolved: {
                  ...prev?.resolved,
                  site: site.site_url,
                  gsc_property: site.gsc_property,
                  tracked_keywords: site.tracked_keywords,
                },
              }))
            }}
          />
        )}

        {activeTab === 'kanban' && <KanbanPanel />}

        {activeTab === 'timeline' && <TimelinePanel />}

        {activeTab === 'workflow' && <WorkflowPanel />}

        {activeTab === 'capability' && <CapabilityPanel />}

        {activeTab === 'departments' && (
          <div style={{ maxWidth: '1100px', margin: '0 auto', width: '100%', paddingBottom: '32px' }}>
            <div style={{ marginBottom: '16px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#f3f4f6', margin: 0 }}>🏢 部门管理</h2>
              <p style={{ fontSize: '12px', color: '#9ca3af', margin: '6px 0 0' }}>
                登记本联邦里其他部门实例的端点与能力。跨部门工作流节点靠它找到对方。
              </p>
            </div>
            <DepartmentPanel />
          </div>
        )}

        {activeTab === 'config' && (

          <div style={{ maxWidth: '960px', margin: '0 auto', width: '100%', paddingBottom: '32px' }}>
            <div style={{ marginBottom: '24px', textAlign: 'center' }}>
              <h2 style={{ fontSize: '22px', fontWeight: '700', color: '#f3f4f6', marginBottom: '8px' }}>
                ⚙️ 系统配置中心 (Config Portal)
              </h2>
              <p style={{ fontSize: '14px', color: '#9ca3af', margin: '0 auto', maxWidth: '680px', lineHeight: '1.6' }}>
                在这里可视化管理目标站点、LLM 智能体 API Key、演化打分权重与飞书通知网关，配置改动将自动持久化至本地配置文件。
              </p>
            </div>
            <ConfigPanel onConfigSaved={refresh} />
          </div>
        )}
      </main>

      {/* Persistent Right Side Copilot Drawer */}
      <AgentCopilotDrawer
        isOpen={isCopilotOpen}
        onClose={() => setIsCopilotOpen(false)}
        activeTab={activeTab}
        summary={summary}
        configData={configData}
        drawerWidth={copilotWidth}
        onWidthChange={setCopilotWidth}
      />

      {/* Floating Trigger Button when Drawer is closed */}
      {!isCopilotOpen && (
        <button
          onClick={() => setIsCopilotOpen(true)}
          className="rainbow-gradient-btn"
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            color: '#fff',
            border: 0,
            borderRadius: '28px',
            padding: '14px 24px',
            fontWeight: '700',
            fontSize: '14px',
            cursor: 'pointer',
            zIndex: 9000,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            textShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}
        >
          <span>🤖 SEOAgent</span>
        </button>
      )}

    </div>
  )
}

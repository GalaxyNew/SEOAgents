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
import { StoragePanel } from './components/StoragePanel'
import { DepartmentPanel } from './components/DepartmentPanel'
import { useIsMobile } from './hooks'

export type TabId = 'dashboard' | 'gsc_overview' | 'kanban' | 'timeline' | 'workflow' | 'capability' | 'storage' | 'departments' | 'config'

export default function App() {
  // tab 存进 URL hash:刷新后回到原页面,链接也能直接分享到具体页
  const VALID_TABS: TabId[] = ['dashboard', 'gsc_overview', 'kanban', 'timeline', 'workflow', 'capability', 'storage', 'departments', 'config']
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
  const [isCopilotOpen, setIsCopilotOpen] = useState<boolean>(window.innerWidth >= 820)
  const [copilotWidth, setCopilotWidth] = useState<number>(460)
  const [viewportHeight, setViewportHeight] = useState<number>(() => window.visualViewport?.height ?? window.innerHeight)


  // Right-side Settings Dropdown state
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false)
  const settingsRef = useRef<HTMLDivElement>(null)

  // Theme hue (shared with login page via localStorage)
  const [themeHue, setThemeHue] = useState<number>(() => {
    const saved = localStorage.getItem('themeHue')
    const h = saved ? parseInt(saved, 10) : 220
    document.documentElement.style.setProperty('--hue', String(h))
    return isNaN(h) ? 220 : h
  })
  const applyHue = (h: number) => {
    setThemeHue(h)
    document.documentElement.style.setProperty('--hue', String(h))
    localStorage.setItem('themeHue', String(h))
  }

  const refresh = async () => {
    try {
      const sum = await fetch('/api/metrics/summary').then(r => r.json())
      setSummary(sum)
      const cfg = await fetch('/api/config').then(r => r.json())
      setConfigData(cfg)
      setSeonautEndpoint(cfg?.resolved?.seonaut_endpoint ?? '')
    } catch (e) {
      console.warn('refresh failed', e)
    }
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30_000)

    const handleResize = () => {
      setViewportHeight(window.visualViewport?.height ?? window.innerHeight)
    }
    window.addEventListener('resize', handleResize)
    window.visualViewport?.addEventListener('resize', handleResize)
    window.visualViewport?.addEventListener('scroll', handleResize)

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
      window.visualViewport?.removeEventListener('resize', handleResize)
      window.visualViewport?.removeEventListener('scroll', handleResize)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [])

  // 与 useIsMobile(820) 同一个阈值：>=820 为 fixed 侧栏并让出等宽正文；<820 为全屏 overlay。
  const reserveCopilotSpace = !isMobile && isCopilotOpen

  return (
    <div style={{ height: isMobile ? `${viewportHeight}px` : '100vh', minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg)', color: 'var(--ink)', fontFamily: 'var(--font-body)' }}>
      {/* Header */}
      <header
        style={{
          background: 'var(--panel)',
          borderBottom: '1px solid var(--line)',
          padding: isMobile ? '8px 10px 6px' : '14px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: isMobile ? '8px' : '12px',
        }}
      >
        {/* Left: Brand Logo & Title */}
        <div
          onClick={() => setActiveTab('dashboard')}
          style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '8px' : '12px', cursor: 'pointer', minWidth: 0 }}
          title="点击返回监控大屏"
        >
          <div
            style={{
              width: isMobile ? '32px' : '36px',
              height: isMobile ? '32px' : '36px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, var(--acc), var(--acc-2))',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              fontSize: '18px',
              color: 'var(--ink)',
              boxShadow: '0 2px 8px rgba(59,130,246,0.3)',
            }}
          >
            S
          </div>
          <div>
            <h1 style={{ fontSize: isMobile ? '15px' : '18px', fontWeight: '700', margin: 0, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap' }}>
              {isMobile ? 'SEOAgents' : 'SEOAgents · 自进化智能体集群'}
            </h1>
            <div style={{ display: isMobile ? 'none' : 'block', fontSize: '12px', color: 'var(--ink-faint)', marginTop: '2px' }}>
              {summary?.site || 'https://example.com'} · DojoAgents 七层架构
            </div>
          </div>
        </div>

        {/* Center Nav: Quick View Switcher */}
        <nav aria-label="主导航" style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '4px' : '6px', overflowX: 'auto', width: isMobile ? '100%' : 'auto', maxWidth: '100%', order: isMobile ? 3 : 'initial', padding: isMobile ? '6px 0 2px' : '0 0 2px', borderTop: isMobile ? '1px solid var(--line)' : 'none', scrollbarWidth: 'thin' }}>
          {([
            ['dashboard', '📊 监控大屏'],
            ['gsc_overview', '📈 GSC 大屏'],
            ['kanban', '📋 任务卡'],
            ['timeline', '🗓️ 时间规划'],
            ['workflow', '⚙️ 工作流'],
            ['capability', '🧭 能力中心'],
            ['storage', '🗄️ 存储资产'],
          ] as Array<[TabId, string]>).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                background: activeTab === id ? 'oklch(0.22 0.02 var(--hue))' : 'transparent',
                color: activeTab === id ? 'var(--acc)' : 'var(--ink-dim)',
                border: `1px solid activeTab === id ? 'var(--acc)' : 'transparent'}`,
                borderRadius: '8px',
                padding: isMobile ? '9px 10px' : '6px 12px',
                minHeight: isMobile ? 44 : undefined,
                minWidth: isMobile ? 44 : undefined,
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

          <a href="/static/preview/seo-control-tower-v1-enhanced.html" target="_blank" rel="noreferrer" style={{ background: 'transparent', color: 'oklch(0.75 0.12 calc(var(--hue) + 70))', border: '1px solid transparent', borderRadius: '8px', padding: isMobile ? '9px 10px' : '6px 12px', minHeight: isMobile ? 44 : undefined, minWidth: isMobile ? 44 : undefined, display:'inline-flex', alignItems:'center', fontSize: isMobile ? '12px' : '13px', fontWeight: '600', cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap', textDecoration: 'none', transition: 'all 0.2s ease' }}>SEO 总控大屏 ↗</a>

          {activeTab === 'config' && (
            <span
              style={{
                fontSize: '12px',
                color: 'var(--acc)',
                background: 'oklch(0.22 0.03 280)',
                padding: '4px 10px',
                borderRadius: '6px',
                border: '1px solid oklch(0.45 0.12 270)',
                fontWeight: '500',
              }}
            >
              ⚙️ 当前位置：配置中心
            </span>
          )}
        </nav>


        {/* Right Side Controls & Settings Dropdown */}
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '4px' : '10px', fontSize: '12px', marginLeft: isMobile ? 'auto' : 0 }}>
          <span
            style={{
              display: isMobile ? 'none' : 'inline-flex',
              background: 'oklch(0.30 0.05 155)',
              color: 'var(--ok)',
              padding: '4px 10px',
              borderRadius: '12px',
              border: '1px solid var(--ok)',
              fontWeight: '500',
            }}
          >
            ● Active Monitor
          </span>


          {/* Settings Dropdown Button */}
          <div ref={settingsRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setIsSettingsOpen(!isSettingsOpen)}
              style={{
                background: isSettingsOpen ? 'var(--panel-2)' : 'var(--panel)',
                color: 'var(--ink)',
                border: '1px solid var(--panel-2)',
                borderRadius: '8px',
                padding: isMobile ? '8px 10px' : '7px 14px',
                minWidth: isMobile ? 44 : undefined,
                minHeight: isMobile ? 44 : undefined,
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
              <span>{isMobile ? '⚙️' : '⚙️ 设置'}</span>
              {!isMobile && <span style={{ fontSize: '10px', transition: 'transform 0.2s', transform: isSettingsOpen ? 'rotate(180deg)' : 'rotate(0)' }}>▼</span>}
            </button>

            {/* Dropdown Menu Popup */}
            {isSettingsOpen && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 8px)',
                  width: '200px',
                  background: 'var(--panel)',
                  border: '1px solid var(--panel-2)',
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
                    background: 'transparent',
                    color: 'var(--ink)',
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
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    📈 GSC 数据大屏
                  </span>

                </button>

                <button
                  onClick={() => {
                    setActiveTab('departments')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'departments' ? 'var(--panel)' : 'transparent',
                    color: activeTab === 'departments' ? 'var(--acc)' : 'var(--ink)',
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
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
                  onMouseLeave={e => (e.currentTarget.style.background = activeTab === 'departments' ? 'var(--panel)' : 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    🏢 部门管理
                  </span>
                  {activeTab === 'departments' && <span style={{ fontSize: '12px', color: 'var(--acc)' }}>✓</span>}
                </button>

                <button
                  onClick={() => {
                    setActiveTab('config')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'config' ? 'var(--panel)' : 'transparent',
                    color: activeTab === 'config' ? 'var(--acc)' : 'var(--ink)',
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
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
                  onMouseLeave={e => (e.currentTarget.style.background = activeTab === 'config' ? 'var(--panel)' : 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    ⚙️ 系统配置中心
                  </span>
                  {activeTab === 'config' && <span style={{ fontSize: '12px', color: 'var(--acc)' }}>✓</span>}
                </button>

                <div style={{ height: 1, background: 'var(--panel)', margin: '6px 0' }} />

                {/* Theme Hue Slider */}
                <div style={{ padding: '10px 12px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--ink-dim)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>🎨 主题色相</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--acc)', fontSize: '11px' }}>{themeHue}°</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={360}
                    value={themeHue}
                    onChange={e => applyHue(parseInt(e.target.value, 10))}
                    style={{
                      width: '100%',
                      height: '6px',
                      appearance: 'none',
                      WebkitAppearance: 'none',
                      background: 'linear-gradient(90deg, oklch(0.7 0.2 0), oklch(0.7 0.2 60), oklch(0.7 0.2 120), oklch(0.7 0.2 180), oklch(0.7 0.2 240), oklch(0.7 0.2 300), oklch(0.7 0.2 360))',
                      borderRadius: '3px',
                      outline: 'none',
                      cursor: 'pointer',
                    }}
                  />
                </div>

                <div style={{ height: 1, background: 'var(--panel)', margin: '6px 0' }} />

                <button
                  onClick={async () => {
                    await fetch('/api/auth/logout', { method: 'POST' })
                    window.location.reload()
                  }}
                  style={{
                    background: 'transparent', color: 'oklch(0.72 0.15 20)', border: 0,
                    borderRadius: '6px', padding: '10px 12px', fontSize: '13px',
                    fontWeight: '500', textAlign: 'left', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '8px',
                    width: '100%', boxSizing: 'border-box', transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  🚪 退出登录
                </button>


                <a
                  href="/docs"
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => setIsSettingsOpen(false)}
                  style={{
                    background: 'transparent',
                    color: 'var(--ink)',
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
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    📚 API 接口文档
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--ink-dim)' }}>↗</span>
                </a>

                {activeTab === 'config' && (
                  <>
                    <div style={{ height: '1px', background: 'var(--panel)', margin: '4px 0' }} />
                    <button
                      onClick={() => {
                        setActiveTab('dashboard')
                        setIsSettingsOpen(false)
                      }}
                      style={{
                        background: 'transparent',
                        color: 'var(--ink-dim)',
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
                      onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel)')}
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
          flex: '1 1 0',
          minHeight: 0,
          height: 'auto',
          maxHeight: 'none',
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          padding: isMobile ? '6px 8px' : '12px 20px',
          paddingRight: reserveCopilotSpace ? `${copilotWidth + 20}px` : (isMobile ? '8px' : '20px'),
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
          />
        )}

        {activeTab === 'kanban' && <KanbanPanel />}

        {activeTab === 'timeline' && <TimelinePanel />}

        {activeTab === 'workflow' && <WorkflowPanel />}

        {activeTab === 'capability' && <CapabilityPanel />}

        {activeTab === 'storage' && <StoragePanel />}

        {activeTab === 'departments' && (
          <div style={{ maxWidth: '1100px', margin: '0 auto', width: '100%', paddingBottom: '32px' }}>
            <div style={{ marginBottom: '16px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>🏢 部门管理</h2>
              <p style={{ fontSize: '12px', color: 'var(--ink-dim)', margin: '6px 0 0' }}>
                登记本联邦里其他部门实例的端点与能力。跨部门工作流节点靠它找到对方。
              </p>
            </div>
            <DepartmentPanel />
          </div>
        )}

        {activeTab === 'config' && (

          <div style={{ maxWidth: '960px', margin: '0 auto', width: '100%', paddingBottom: '32px' }}>
            <div style={{ marginBottom: '24px', textAlign: 'center' }}>
              <h2 style={{ fontSize: '22px', fontWeight: '700', color: 'var(--ink)', marginBottom: '8px' }}>
                ⚙️ 系统配置中心 (Config Portal)
              </h2>
              <p style={{ fontSize: '14px', color: 'var(--ink-dim)', margin: '0 auto', maxWidth: '680px', lineHeight: '1.6' }}>
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
            bottom: isMobile ? '16px' : '24px',
            right: isMobile ? '16px' : '24px',
            color: 'var(--ink)',
            border: 0,
            borderRadius: isMobile ? '50%' : '28px',
            width: isMobile ? 48 : undefined,
            height: isMobile ? 48 : undefined,
            padding: isMobile ? 0 : '14px 24px',
            fontWeight: '700',
            fontSize: isMobile ? 22 : 14,
            cursor: 'pointer',
            zIndex: 9000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            textShadow: '0 1px 3px rgba(0,0,0,0.4)',
            boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
          }}
        >
          <span>{isMobile ? '' : '🤖 SEOAgent'}</span>
        </button>
      )}

    </div>
  )
}

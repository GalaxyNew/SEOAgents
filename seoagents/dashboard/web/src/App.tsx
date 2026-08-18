import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { SeoAuditPanel } from './components/SeoAuditPanel'
import { MetricsPanel, type MetricsSummary } from './components/MetricsPanel'
import { useIsMobile } from './hooks'
import {
  PRESET_THEMES,
  initTheme,
  applyHue as kitApplyHue,
  getMode,
  toggleMode,
  onThemeChange,
  type ThemeMode,
} from './theme'

/* 路由级懒加载（22 号文 §六 首屏体积门禁）
   ────────────────────────────────────────────────────────────
   这些面板各自只在对应 tab 打开时才需要，但同步 import 会把 recharts（331KB）、
   react-grid-layout（38KB）等全部塞进首屏。Lighthouse 实测：首屏 952KB JS 中
   692KB 未被使用，FCP/LCP 被拖到 6.3s。
   改为 lazy() 后 vendor-charts / vendor-grid 变成按需 chunk，不再阻塞首屏。
   dashboard 首页只保留 MetricsPanel + SeoAuditPanel（默认 tab 立即要用）。 */
const ConfigPanel = lazy(() => import('./components/ConfigPanel').then(m => ({ default: m.ConfigPanel })))
const AgentCopilotDrawer = lazy(() => import('./components/AgentCopilotDrawer').then(m => ({ default: m.AgentCopilotDrawer })))
const GscOverviewPanel = lazy(() => import('./components/GscOverviewPanel').then(m => ({ default: m.GscOverviewPanel })))
const KanbanPanel = lazy(() => import('./components/KanbanPanel').then(m => ({ default: m.KanbanPanel })))
const TimelinePanel = lazy(() => import('./components/TimelinePanel').then(m => ({ default: m.TimelinePanel })))
const WorkflowPanel = lazy(() => import('./components/WorkflowPanel').then(m => ({ default: m.WorkflowPanel })))
const CapabilityPanel = lazy(() => import('./components/CapabilityPanel').then(m => ({ default: m.CapabilityPanel })))
const StoragePanel = lazy(() => import('./components/StoragePanel').then(m => ({ default: m.StoragePanel })))
const DepartmentPanel = lazy(() => import('./components/DepartmentPanel').then(m => ({ default: m.DepartmentPanel })))

/** 懒加载面板的占位骨架 —— 预留高度，避免 chunk 到达时撑开页面产生 CLS */
const PanelFallback = () => (
  <div className="dk-panel" style={{ minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--dim)', fontSize: 'var(--fs-sm)' }}>
    <span className="dk-pulse">载入中…</span>
  </div>
)

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
  // Copilot 抽屉延后挂载：首屏绘制完成后再拉它的 chunk（见下方渲染处注释）
  const [copilotMounted, setCopilotMounted] = useState<boolean>(false)
  useEffect(() => {
    const idle = (window as any).requestIdleCallback
      ? (window as any).requestIdleCallback(() => setCopilotMounted(true), { timeout: 1500 })
      : window.setTimeout(() => setCopilotMounted(true), 300)
    return () => {
      if ((window as any).cancelIdleCallback) (window as any).cancelIdleCallback(idle)
      else window.clearTimeout(idle)
    }
  }, [])
  const [copilotWidth, setCopilotWidth] = useState<number>(460)
  const [viewportHeight, setViewportHeight] = useState<number>(() => window.visualViewport?.height ?? window.innerHeight)


  // Right-side Settings Dropdown state
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false)
  const settingsRef = useRef<HTMLDivElement>(null)

  // 主题：交给 dashboard-kit themes.js（22 号文 §2.2）
  // hue 只驱动强调组；底座中性恒定；明暗模式翻转 L 阶梯
  const [themeHue, setThemeHue] = useState<number>(() => initTheme().hue)
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => getMode())
  const applyHue = (h: number) => {
    setThemeHue(kitApplyHue(h))
  }
  // 跨页/跨标签同步（另一个标签改了主题，本页跟随）
  useEffect(() => onThemeChange(({ hue, mode }) => {
    setThemeHue(hue)
    setThemeMode(mode)
  }), [])

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

  // ── Ch.5: View Transitions — Tab 切换动画 ──
  const switchTab = (tab: TabId) => {
    if (tab === activeTab) return
    const swap = () => setActiveTab(tab)
    if ('startViewTransition' in document) {
      (document as any).startViewTransition(swap)
    } else {
      swap()
    }
  }

  // 与 useIsMobile(820) 同一个阈值：>=820 为 fixed 侧栏并让出等宽正文；<820 为全屏 overlay。
  const reserveCopilotSpace = !isMobile && isCopilotOpen

  return (
    <div style={{ height: isMobile ? `${viewportHeight}px` : '100vh', minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font-ui)' }}>
      {/* Header */}
      <header
        style={{
          background: 'var(--panel)',
          borderBottom: '1px solid var(--border)',
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
          onClick={() => switchTab('dashboard')}
          style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '8px' : '12px', cursor: 'pointer', minWidth: 0 }}
          title="点击返回监控大屏"
        >
          <div
            style={{
              width: isMobile ? '32px' : '36px',
              height: isMobile ? '32px' : '36px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, var(--accent), var(--accent2))',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              fontSize: '18px',
              color: 'var(--text)',
              boxShadow: '0 2px 8px var(--accent-line)',
            }}
          >
            S
          </div>
          <div>
            <h1 style={{ fontSize: isMobile ? '15px' : '18px', fontWeight: '700', margin: 0, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap' }}>
              {isMobile ? 'SEOAgents' : 'SEOAgents · 自进化智能体集群'}
            </h1>
            <div style={{ display: isMobile ? 'none' : 'block', fontSize: '12px', color: 'var(--faint)', marginTop: '2px' }}>
              {summary?.site || 'https://example.com'} · DojoAgents 七层架构
            </div>
          </div>
        </div>

        {/* Center Nav: Quick View Switcher */}
        <nav aria-label="主导航" style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '4px' : '6px', overflowX: 'auto', width: isMobile ? '100%' : 'auto', maxWidth: '100%', order: isMobile ? 3 : 'initial', padding: isMobile ? '6px 0 2px' : '0 0 2px', borderTop: isMobile ? '1px solid var(--border)' : 'none', scrollbarWidth: 'thin' }}>
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
              onClick={() => switchTab(id)}
              style={{
                background: activeTab === id ? 'oklch(0.22 0.02 var(--hue))' : 'transparent',
                color: activeTab === id ? 'var(--accent)' : 'var(--dim)',
                border: `1px solid activeTab === id ? 'var(--accent)' : 'transparent'}`,
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
                color: 'var(--accent)',
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
                background: isSettingsOpen ? 'var(--panel2)' : 'var(--panel)',
                color: 'var(--text)',
                border: '1px solid var(--panel2)',
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
                boxShadow: isSettingsOpen ? '0 0 0 2px var(--accent-line)' : 'none',
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
                  border: '1px solid var(--panel2)',
                  borderRadius: '10px',
                  padding: '6px',
                  boxShadow: '0 10px 25px -5px oklch(0% 0 0 / .5), 0 8px 10px -6px oklch(0% 0 0 / .5)',
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
                    color: 'var(--text)',
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
                    color: activeTab === 'departments' ? 'var(--accent)' : 'var(--text)',
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
                  {activeTab === 'departments' && <span style={{ fontSize: '12px', color: 'var(--accent)' }}>✓</span>}
                </button>

                <button
                  onClick={() => {
                    setActiveTab('config')
                    setIsSettingsOpen(false)
                  }}
                  style={{
                    background: activeTab === 'config' ? 'var(--panel)' : 'transparent',
                    color: activeTab === 'config' ? 'var(--accent)' : 'var(--text)',
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
                  {activeTab === 'config' && <span style={{ fontSize: '12px', color: 'var(--accent)' }}>✓</span>}
                </button>

                <div style={{ height: 1, background: 'var(--panel)', margin: '6px 0' }} />

                {/* dashboard-kit 主题引擎：6 预设主题环 + 自定义 hue + 明暗模式 */}
                <div style={{ padding: '10px 12px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--dim)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>🎨 主题</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)', fontSize: '11px' }}>{themeHue}°</span>
                  </div>
                  <div className="dk-theme-switch" style={{ marginBottom: '10px', flexWrap: 'wrap' }}>
                    {PRESET_THEMES.map(t => (
                      <button
                        key={t.id}
                        className="dk-swatch"
                        aria-pressed={themeHue === t.hue}
                        aria-label={`${t.name}（${t.dept}）`}
                        title={`${t.name} · ${t.dept}`}
                        onClick={() => applyHue(t.hue)}
                        style={{ background: `oklch(70% 0.16 ${t.hue})` }}
                      />
                    ))}
                    <button
                      className="dk-mode-toggle"
                      onClick={() => setThemeMode(toggleMode())}
                      title="明暗模式切换"
                      style={{ marginLeft: 'auto' }}
                    >
                      {themeMode === 'dark' ? '🌙 深色' : '☀️ 浅色'}
                    </button>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={360}
                    value={themeHue}
                    aria-label="自定义主题色相"
                    onChange={e => applyHue(parseInt(e.target.value, 10))}
                    style={{
                      width: '100%',
                      height: '6px',
                      appearance: 'none',
                      WebkitAppearance: 'none',
                      background: 'linear-gradient(90deg, oklch(0.7 0.16 0), oklch(0.7 0.16 60), oklch(0.7 0.16 120), oklch(0.7 0.16 180), oklch(0.7 0.16 240), oklch(0.7 0.16 300), oklch(0.7 0.16 360))',
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
                    color: 'var(--text)',
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
                  <span style={{ fontSize: '11px', color: 'var(--dim)' }}>↗</span>
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
                        color: 'var(--dim)',
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

        {/* 懒加载面板统一挂 Suspense —— fallback 预留高度，chunk 到达不产生 CLS */}
        <Suspense fallback={<PanelFallback />}>

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
              <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text)', margin: 0 }}>🏢 部门管理</h2>
              <p style={{ fontSize: '12px', color: 'var(--dim)', margin: '6px 0 0' }}>
                登记本联邦里其他部门实例的端点与能力。跨部门工作流节点靠它找到对方。
              </p>
            </div>
            <DepartmentPanel />
          </div>
        )}

        {activeTab === 'config' && (

          <div style={{ maxWidth: '960px', margin: '0 auto', width: '100%', paddingBottom: '32px' }}>
            <div style={{ marginBottom: '24px', textAlign: 'center' }}>
              <h2 style={{ fontSize: '22px', fontWeight: '700', color: 'var(--text)', marginBottom: '8px' }}>
                ⚙️ 系统配置中心 (Config Portal)
              </h2>
              <p style={{ fontSize: '14px', color: 'var(--dim)', margin: '0 auto', maxWidth: '680px', lineHeight: '1.6' }}>
                在这里可视化管理目标站点、LLM 智能体 API Key、演化打分权重与飞书通知网关，配置改动将自动持久化至本地配置文件。
              </p>
            </div>
            <ConfigPanel onConfigSaved={refresh} />
          </div>
        )}

        </Suspense>
      </main>

      {/* Persistent Right Side Copilot Drawer（懒加载，且延到首屏绘制后再挂载）
          桌面端默认 isOpen=true，若直接渲染会在首屏就拉取它的 chunk，把 FCP/LCP 拖慢。
          用 copilotMounted 推迟一帧，视觉行为不变（用户看到的仍是默认展开）。 */}
      {copilotMounted && (
        <Suspense fallback={null}>
          <AgentCopilotDrawer
            isOpen={isCopilotOpen}
            onClose={() => setIsCopilotOpen(false)}
            activeTab={activeTab}
            summary={summary}
            configData={configData}
            drawerWidth={copilotWidth}
            onWidthChange={setCopilotWidth}
          />
        </Suspense>
      )}

      {/* Floating Trigger Button when Drawer is closed */}
      {!isCopilotOpen && (
        <button
          onClick={() => setIsCopilotOpen(true)}
          className="rainbow-gradient-btn"
          style={{
            position: 'fixed',
            bottom: isMobile ? '16px' : '24px',
            right: isMobile ? '16px' : '24px',
            color: 'var(--text)',
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
            textShadow: '0 1px 3px oklch(0% 0 0 / .4)',
            boxShadow: '0 4px 16px oklch(0% 0 0 / .3)',
          }}
        >
          <span>{isMobile ? '' : '🤖 SEOAgent'}</span>
        </button>
      )}

    </div>
  )
}

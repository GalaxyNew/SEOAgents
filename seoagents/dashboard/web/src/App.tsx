import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { SeoAuditPanel } from './components/SeoAuditPanel'
import { MetricsPanel, type MetricsSummary } from './components/MetricsPanel'
import { useIsMobile } from './hooks'
import { CommandPalette } from './components/CommandPalette'
import { OverviewPanel } from './components/OverviewPanel'
import { SideNav } from './layout/SideNav'
import { TopBar } from './layout/TopBar'
import {
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
const KeywordPoolPanel = lazy(() => import('./components/KeywordPoolPanel').then(m => ({ default: m.KeywordPoolPanel })))

/** 懒加载面板的占位骨架 —— 预留高度，避免 chunk 到达时撑开页面产生 CLS */
const PanelFallback = () => (
  <div className="dk-panel" style={{ minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--dim)', fontSize: 'var(--fs-sm)' }}>
    <span className="dk-pulse">载入中…</span>
  </div>
)

export type TabId = 'dashboard' | 'monitor' | 'gsc_overview' | 'keywords' | 'kanban' | 'timeline' | 'workflow' | 'capability' | 'storage' | 'departments' | 'config'

export default function App() {
  // tab 存进 URL hash:刷新后回到原页面,链接也能直接分享到具体页
  const VALID_TABS: TabId[] = ['dashboard', 'monitor', 'gsc_overview', 'keywords', 'kanban', 'timeline', 'workflow', 'capability', 'storage', 'departments', 'config']
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

  // v3 侧导航：移动端 overlay 抽屉开合
  const [navOpen, setNavOpen] = useState(false)
  // 侧栏关键词徽标：挂载时拉一次词池总数
  const [keywordCount, setKeywordCount] = useState<number | null>(null)
  useEffect(() => {
    fetch('/api/keywords/pool?limit=1')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d?.total) setKeywordCount(d.total) })
      .catch(() => {})
  }, [])
  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' })
    window.location.reload()
  }

  // ⌘K 命令面板
  const [paletteOpen, setPaletteOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(v => !v)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div style={{ height: isMobile ? `${viewportHeight}px` : '100vh', minHeight: 0, overflow: 'hidden', display: 'flex', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font-ui)' }}>
      {/* v3 侧导航（桌面常驻 216px；移动端 overlay 抽屉） */}
      <SideNav
        activeTab={activeTab}
        onSwitch={switchTab}
        themeHue={themeHue}
        themeMode={themeMode}
        onApplyHue={applyHue}
        onToggleMode={() => setThemeMode(toggleMode())}
        keywordCount={keywordCount}
        isMobile={isMobile}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        onLogout={handleLogout}
        onOpenPalette={() => setPaletteOpen(true)}
      />

      {/* 主区：顶栏 + 内容 */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <TopBar
          activeTab={activeTab}
          site={summary?.site ?? null}
          onRefresh={refresh}
          isMobile={isMobile}
          onOpenNav={() => setNavOpen(true)}
        />

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

        {activeTab === 'dashboard' && <OverviewPanel summary={summary} />}

        {activeTab === 'monitor' && (
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

        {activeTab === 'keywords' && <KeywordPoolPanel />}

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
      </div>{/* 主区 end */}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onSwitch={switchTab} />

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

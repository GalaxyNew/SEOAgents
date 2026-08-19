/**
 * SideNav — 216px 侧导航（UI v3 · PR-A）
 *
 * 设计对应概念稿 seoag-ui-v3-preview.html 左栏：
 * logo / 分组导航（工作台·生产·协同·系统）/ 底部主题环+明暗+用户区。
 *
 * 纯展示组件：tab 状态机仍在 App.tsx（hash 路由兼容不动），
 * 这里只接收 activeTab + 回调。移动端（<820）由 App 控制 overlay 开合。
 */
import { PRESET_THEMES, type ThemeMode } from '../theme'
import type { TabId } from '../App'

type NavItem = { id: TabId; label: string; icon: string; badge?: string }
type NavGroup = { title: string; items: NavItem[] }

export const NAV_GROUPS: NavGroup[] = [
  {
    title: '工作台',
    items: [
      { id: 'dashboard', label: '总览', icon: '📊' },
      { id: 'monitor', label: '监控大屏', icon: '🖥️' },
      { id: 'gsc_overview', label: 'GSC 数据', icon: '📈' },
      { id: 'keywords', label: '关键词池', icon: '🔤' },
    ],
  },
  {
    title: '生产',
    items: [
      { id: 'kanban', label: '任务卡', icon: '📋' },
      { id: 'timeline', label: '时间规划', icon: '🗓️' },
      { id: 'workflow', label: '工作流', icon: '⚙️' },
    ],
  },
  {
    title: '协同',
    items: [
      { id: 'departments', label: '部门协作', icon: '🏢' },
      { id: 'storage', label: '存储资产', icon: '🗄️' },
    ],
  },
  {
    title: '系统',
    items: [
      { id: 'capability', label: '能力中心', icon: '🧭' },
      { id: 'config', label: '配置中心', icon: '⚙️' },
    ],
  },
]

export const TAB_TITLES: Record<TabId, { title: string; subtitle: string }> = {
  dashboard: { title: '总览', subtitle: '今天该关注什么，一屏看完 · 点模块看明细' },
  monitor: { title: '监控大屏', subtitle: 'M_t 演化评分与 SEO 审计全景' },
  gsc_overview: { title: 'GSC 数据', subtitle: 'Search Console 表现大屏' },
  keywords: { title: '关键词池', subtitle: '双源市场词表 · 搜索量/难度/意图' },
  kanban: { title: '任务卡', subtitle: '部门任务看板' },
  timeline: { title: '时间规划', subtitle: '排期与里程碑' },
  workflow: { title: '工作流', subtitle: '内容产线与自动化编排' },
  capability: { title: '能力中心', subtitle: '智能体能力与技能' },
  storage: { title: '存储资产', subtitle: '中央存储与资产路由' },
  departments: { title: '部门协作', subtitle: '联邦部门端点与能力目录' },
  config: { title: '配置中心', subtitle: '站点 / LLM / 权重 / 通知' },
}

export function SideNav({
  activeTab,
  onSwitch,
  themeHue,
  themeMode,
  onApplyHue,
  onToggleMode,
  keywordCount,
  isMobile,
  open,
  onClose,
  onLogout,
}: {
  activeTab: TabId
  onSwitch: (tab: TabId) => void
  themeHue: number
  themeMode: ThemeMode
  onApplyHue: (hue: number) => void
  onToggleMode: () => void
  keywordCount: number | null
  isMobile: boolean
  open: boolean
  onClose: () => void
  onLogout: () => void
}) {
  const badgeFor = (id: TabId): string | null => {
    if (id === 'keywords' && keywordCount) {
      return keywordCount >= 1000 ? `${(keywordCount / 1000).toFixed(1)}k` : String(keywordCount)
    }
    return null
  }

  const nav = (
    <nav
      aria-label="主导航"
      style={{
        width: 216,
        flex: 'none',
        height: '100%',
        background: 'var(--surface, var(--panel))',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '14px 10px 12px',
        boxSizing: 'border-box',
        overflowY: 'auto',
      }}
    >
      {/* logo */}
      <div
        onClick={() => onSwitch('dashboard')}
        style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '2px 8px 12px', cursor: 'pointer' }}
        title="返回总览"
      >
        <div
          style={{
            width: 28, height: 28, borderRadius: 7, flex: 'none',
            background: 'linear-gradient(135deg, var(--accent), var(--accent2))',
            display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: 12, color: 'var(--text)',
          }}
        >
          SA
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: '.02em', color: 'var(--text)' }}>SEOAgents</div>
          <div style={{ color: 'var(--faint)', fontSize: 10 }}>SEO 部 · 联邦节点</div>
        </div>
      </div>

      {/* 分组导航 */}
      {NAV_GROUPS.map(g => (
        <div key={g.title}>
          <div style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--faint)', padding: '12px 10px 5px', textTransform: 'uppercase' }}>
            {g.title}
          </div>
          {g.items.map(item => {
            const on = activeTab === item.id
            const badge = badgeFor(item.id)
            return (
              <button
                key={item.id}
                onClick={() => { onSwitch(item.id); if (isMobile) onClose() }}
                aria-current={on ? 'page' : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 9, width: '100%',
                  padding: isMobile ? '11px 10px' : '7.5px 10px', minHeight: isMobile ? 44 : undefined,
                  borderRadius: 8, border: 0, textAlign: 'left', cursor: 'pointer',
                  background: on ? 'oklch(from var(--accent) l c h / .12)' : 'transparent',
                  color: on ? 'var(--accent)' : 'var(--dim)',
                  fontSize: 13, fontWeight: on ? 600 : 500,
                  transition: 'background .15s, color .15s',
                }}
                onMouseEnter={e => { if (!on) e.currentTarget.style.background = 'var(--panel)' }}
                onMouseLeave={e => { if (!on) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ fontSize: 13, flex: 'none' }}>{item.icon}</span>
                <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.label}</span>
                {badge && (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--faint)' }}>{badge}</span>
                )}
              </button>
            )
          })}
        </div>
      ))}

      {/* 外链：SEO 总控大屏 */}
      <a
        href="/static/preview/seo-control-tower-v1-enhanced.html"
        target="_blank"
        rel="noreferrer"
        style={{
          display: 'flex', alignItems: 'center', gap: 9, padding: '7.5px 10px', marginTop: 4,
          borderRadius: 8, color: 'oklch(0.75 0.12 calc(var(--hue) + 70))', fontSize: 13,
          fontWeight: 500, textDecoration: 'none',
        }}
      >
        <span style={{ fontSize: 13 }}>🖥️</span>
        <span style={{ flex: 1 }}>SEO 总控大屏</span>
        <span style={{ fontSize: 11, color: 'var(--dim)' }}>↗</span>
      </a>

      {/* 底部：主题 + 用户 */}
      <div style={{ marginTop: 'auto', paddingTop: 10, borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px 8px', flexWrap: 'wrap' }}>
          {PRESET_THEMES.map(t => (
            <button
              key={t.id}
              className="dk-swatch"
              aria-pressed={themeHue === t.hue}
              aria-label={`${t.name}（${t.dept}）`}
              title={`${t.name} · ${t.dept}`}
              onClick={() => onApplyHue(t.hue)}
              style={{ background: `oklch(70% 0.16 ${t.hue})` }}
            />
          ))}
          <button
            className="dk-mode-toggle"
            onClick={onToggleMode}
            title="明暗模式切换"
            style={{ marginLeft: 'auto' }}
          >
            {themeMode === 'dark' ? '🌙' : '☀️'}
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 6 }}>
          <div
            style={{
              width: 24, height: 24, borderRadius: '50%', flex: 'none',
              background: 'var(--panel2)', border: '1px solid var(--border)',
              display: 'grid', placeItems: 'center', fontSize: 10, color: 'var(--accent)',
            }}
          >
            管
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11.5, color: 'var(--text)' }}>admin</div>
            <div style={{ color: 'var(--faint)', fontSize: 10 }}>SEO HM · 在线</div>
          </div>
          <button
            onClick={onLogout}
            title="退出登录"
            style={{
              background: 'transparent', border: 0, cursor: 'pointer',
              color: 'var(--faint)', fontSize: 13, padding: '4px 6px',
            }}
          >
            ⎋
          </button>
        </div>
      </div>
    </nav>
  )

  if (!isMobile) return nav

  // 移动端：overlay 抽屉
  return (
    <>
      {open && (
        <div
          onClick={onClose}
          style={{ position: 'fixed', inset: 0, background: 'oklch(0% 0 0 / .5)', zIndex: 1200 }}
        />
      )}
      <div
        style={{
          position: 'fixed', top: 0, left: open ? 0 : -240, bottom: 0, zIndex: 1201,
          transition: 'left .22s ease',
        }}
      >
        {nav}
      </div>
    </>
  )
}

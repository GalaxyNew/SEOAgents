/**
 * TopBar — 50px 顶栏（UI v3 · PR-A）
 *
 * 面包屑（当前页名+副标题）/ 站点标识 / 数据新鲜度 / 全局操作。
 * 移动端左侧出汉堡按钮（开侧栏抽屉）。
 */
import { TAB_TITLES } from './SideNav'
import type { TabId } from '../App'

export function TopBar({
  activeTab,
  site,
  onRefresh,
  isMobile,
  onOpenNav,
}: {
  activeTab: TabId
  site: string | null
  onRefresh: () => void
  isMobile: boolean
  onOpenNav: () => void
}) {
  const meta = TAB_TITLES[activeTab] ?? { title: '', subtitle: '' }
  return (
    <header
      style={{
        height: 50, flex: 'none', display: 'flex', alignItems: 'center', gap: 12,
        padding: isMobile ? '0 10px' : '0 20px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--surface, var(--panel))',
        boxSizing: 'border-box',
      }}
    >
      {isMobile && (
        <button
          onClick={onOpenNav}
          aria-label="打开导航"
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 8,
            minWidth: 40, minHeight: 40, cursor: 'pointer', color: 'var(--text)', fontSize: 16,
          }}
        >
          ☰
        </button>
      )}

      <div style={{ minWidth: 0, display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap' }}>{meta.title}</span>
        {!isMobile && (
          <span style={{ color: 'var(--faint)', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {meta.subtitle}
          </span>
        )}
      </div>

      {site && !isMobile && (
        <span
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 11px',
            border: '1px solid var(--border)', borderRadius: 20, background: 'var(--panel)',
            fontSize: 12, color: 'var(--text)',
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)' }} />
          <b style={{ fontWeight: 600 }}>{site.replace(/^https?:\/\//, '')}</b>
        </span>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          onClick={onRefresh}
          style={{
            padding: '5.5px 13px', borderRadius: 7, border: '1px solid var(--border)',
            background: 'var(--panel)', color: 'var(--text)', fontSize: 12, cursor: 'pointer',
            minHeight: isMobile ? 40 : undefined,
          }}
        >
          刷新
        </button>
      </div>
    </header>
  )
}

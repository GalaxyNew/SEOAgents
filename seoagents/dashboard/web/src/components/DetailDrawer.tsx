/**
 * DetailDrawer — 通用详情抽屉（UI v3 · PR-B）
 *
 * 概念稿交互：点任意模块 → 右滑 470px 抽屉（移动端全屏）+ 遮罩，
 * Esc / 点遮罩 / ✕ 关闭。内容由调用方以 children 传入，本组件只管壳。
 * prefers-reduced-motion 下退化为直接显隐（transition 由 CSS 变量控制）。
 */
import { useEffect } from 'react'
import { useIsMobile } from '../hooks'

export function DetailDrawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  const isMobile = useIsMobile()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        aria-hidden
        style={{
          position: 'fixed', inset: 0, background: 'oklch(0% 0 0 / .45)',
          opacity: open ? 1 : 0, pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity .22s', zIndex: 1100,
        }}
      />
      {/* 抽屉 */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{
          position: 'fixed', top: 0, bottom: 0,
          right: open ? 0 : (isMobile ? '-100vw' : -500),
          width: isMobile ? '100vw' : 470, maxWidth: '100vw',
          background: 'var(--surface, var(--panel))',
          borderLeft: '1px solid var(--border)',
          transition: 'right .26s cubic-bezier(.3,.9,.3,1)',
          zIndex: 1101, display: 'flex', flexDirection: 'column',
          boxShadow: open ? '-18px 0 50px oklch(0% 0 0 / .35)' : 'none',
        }}
      >
        <header
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px',
            borderBottom: '1px solid var(--border)', flex: 'none',
          }}
        >
          <b style={{ fontSize: 14, color: 'var(--text)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {title}
          </b>
          <button
            onClick={onClose}
            aria-label="关闭"
            style={{
              background: 'transparent', border: 0, cursor: 'pointer',
              color: 'var(--faint)', fontSize: 15,
              minWidth: 44, minHeight: 44, display: 'grid', placeItems: 'center',
            }}
          >
            ✕
          </button>
        </header>
        <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '14px 12px 24px' : '16px 18px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {open ? children : null}
        </div>
      </aside>
    </>
  )
}

/* ── 抽屉内通用小组件 ── */

export function DrawerHero({ value, unit, delta, deltaTone }: {
  value: string; unit?: string; delta?: string; deltaTone?: 'up' | 'down' | 'flat'
}) {
  const tone = deltaTone === 'down' ? 'var(--bad)' : deltaTone === 'flat' ? 'var(--faint)' : 'var(--ok)'
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 32, fontWeight: 700, letterSpacing: '-.02em', color: 'var(--text)' }}>{value}</span>
      {unit && <span style={{ color: 'var(--faint)', fontSize: 12 }}>{unit}</span>}
      {delta && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, padding: '2px 8px', borderRadius: 10, color: tone, background: `oklch(from ${tone} l c h / .12)` }}>
          {delta}
        </span>
      )}
    </div>
  )
}

export function DrawerSection({ title, hint, children }: {
  title: string; hint?: string; children: React.ReactNode
}) {
  return (
    <section style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
      <header style={{ padding: '9px 13px', borderBottom: '1px solid var(--border)', fontSize: 11.5, fontWeight: 600, color: 'var(--text)', display: 'flex', gap: 8, alignItems: 'center' }}>
        {title}
        {hint && <span style={{ color: 'var(--faint)', fontWeight: 400, fontSize: 10 }}>{hint}</span>}
      </header>
      {children}
    </section>
  )
}

export function HBar({ label, pct, value, sub, color }: {
  label: string; pct: number; value: string; sub?: string; color?: string
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11.5, color: 'var(--text)' }}>
      <span style={{ width: 96, color: 'var(--dim)', flex: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ flex: 1, height: 9, borderRadius: 5, background: 'var(--panel2)', overflow: 'hidden' }}>
        <i style={{ display: 'block', height: '100%', borderRadius: 5, width: `${Math.min(100, Math.max(0, pct))}%`, background: color || 'var(--accent)' }} />
      </span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, width: 74, textAlign: 'right', flex: 'none' }}>{value}</span>
      {sub !== undefined && <span style={{ color: 'var(--faint)', fontSize: 10, width: 34, textAlign: 'right', flex: 'none' }}>{sub}</span>}
    </div>
  )
}

export function DrawerNote({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 10.5, color: 'var(--faint)', padding: '0 2px', lineHeight: 1.6 }}>{children}</div>
}

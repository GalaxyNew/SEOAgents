import React, { useEffect, useState } from 'react'

/**
 * 全站共用的界面基件。
 *
 * 建这一层是因为「新建一律用弹窗」这条规则散落在五个页面里各写一遍,
 * 迟早会长出五种不同的关闭行为、五种不同的遮罩透明度。
 */

// ── 通用弹窗 ────────────────────────────────────────────────────────
export const Modal: React.FC<{
  open: boolean
  title: string
  subtitle?: string
  width?: number
  onClose: () => void
  footer?: React.ReactNode
  children: React.ReactNode
}> = ({ open, title, subtitle, width = 560, onClose, footer, children }) => {
  // Esc 关闭:弹窗一多,没有键盘退路会很烦
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.78)', zIndex: 100000,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#111827', border: '1px solid #334155', borderRadius: 12,
          width: '100%', maxWidth: width, maxHeight: '86vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 60px rgba(0,0,0,0.7)',
        }}
      >
        <div style={{
          padding: '13px 16px', borderBottom: '1px solid #1f2937',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f3f4f6' }}>{title}</div>
            {subtitle && (
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{subtitle}</div>
            )}
          </div>
          <button onClick={onClose} title="关闭 (Esc)" style={{
            background: 'transparent', border: 0, color: '#94a3b8',
            fontSize: 17, cursor: 'pointer', padding: '0 4px', lineHeight: 1,
          }}>✕</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>{children}</div>

        {footer && (
          <div style={{
            padding: '11px 16px', borderTop: '1px solid #1f2937',
            display: 'flex', justifyContent: 'flex-end', gap: 7,
          }}>{footer}</div>
        )}
      </div>
    </div>
  )
}

// ── 表单件 ──────────────────────────────────────────────────────────
export const Field: React.FC<{ label: string; hint?: string; children: React.ReactNode }> =
  ({ label, hint, children }) => (
    <div style={{ marginBottom: 11 }}>
      <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4, fontWeight: 600 }}>
        {label}
      </label>
      {children}
      {hint && <div style={{ fontSize: 10, color: '#475569', marginTop: 3 }}>{hint}</div>}
    </div>
  )

export const inputStyle: React.CSSProperties = {
  background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
  color: '#e2e8f0', fontSize: 12, padding: '7px 9px',
  boxSizing: 'border-box', width: '100%', outline: 'none',
}

export const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  background: bg, color: fg, border: 0, borderRadius: 6,
  padding: '6px 13px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
})

// ── 快捷指令:用户自选,持久化 ──────────────────────────────────────
export interface QuickCmd {
  id: string
  title: string
  prompt: string
  origin?: string      // 来自哪个能力/插件/技能
}

const LS_KEY = 'seoagents.quickCommands.v1'

function read(): QuickCmd[] {
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as QuickCmd[]) : []
  } catch { return [] }
}

function write(list: QuickCmd[]): void {
  try { window.localStorage.setItem(LS_KEY, JSON.stringify(list)) } catch { /* 隐私模式下静默 */ }
  // 同一页面内的其他组件不会收到 storage 事件,得自己广播
  window.dispatchEvent(new CustomEvent('quickcmds-changed'))
}

/** 快捷指令的读写。跨组件同步靠自定义事件,不引第三方状态库。 */
export function useQuickCommands() {
  const [cmds, setCmds] = useState<QuickCmd[]>(read)

  useEffect(() => {
    const sync = () => setCmds(read())
    window.addEventListener('quickcmds-changed', sync)
    window.addEventListener('storage', sync)   // 另一个标签页改了也跟上
    return () => {
      window.removeEventListener('quickcmds-changed', sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  return {
    cmds,
    has: (id: string) => cmds.some((c) => c.id === id),
    add: (c: QuickCmd) => {
      const cur = read()
      if (cur.some((x) => x.id === c.id)) return
      write([...cur, c])
    },
    remove: (id: string) => write(read().filter((c) => c.id !== id)),
    toggle: (c: QuickCmd) => {
      const cur = read()
      write(cur.some((x) => x.id === c.id)
        ? cur.filter((x) => x.id !== c.id)
        : [...cur, c])
    },
    clear: () => write([]),
  }
}

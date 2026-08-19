/**
 * CommandPalette — ⌘K 命令面板（UI v3 · PR-C）
 *
 * 三段结果：
 *   ① 关键词（词池实时搜索，防抖 250ms，显示 量/KD/意图）
 *   ② 页面跳转（tab 模糊匹配）
 *   ③ 操作（跳到对应页执行——查词进词池页、产线进工作流页）
 * 键盘：⌘K/Ctrl+K 唤起 · ↑↓ 选择 · ↵ 执行 · Esc 关闭。
 * 移动端：全屏面板（顶部输入 + 全高结果区）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { NAV_GROUPS } from '../layout/SideNav'
import { useIsMobile } from '../hooks'
import type { TabId } from '../App'

type PoolItem = { keyword: string; search_volume: number; difficulty: number | null; intent?: string | null }

type Entry =
  | { kind: 'kw'; kw: PoolItem }
  | { kind: 'page'; id: TabId; label: string; icon: string }
  | { kind: 'action'; label: string; icon: string; run: () => void }

export function CommandPalette({
  open,
  onClose,
  onSwitch,
}: {
  open: boolean
  onClose: () => void
  onSwitch: (tab: TabId) => void
}) {
  const isMobile = useIsMobile()
  const [q, setQ] = useState('')
  const [kws, setKws] = useState<PoolItem[]>([])
  const [sel, setSel] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debRef = useRef<number>(0)

  /* 词池搜索（防抖） */
  useEffect(() => {
    if (!open) return
    window.clearTimeout(debRef.current)
    if (!q.trim()) { setKws([]); return }
    debRef.current = window.setTimeout(() => {
      fetch(`/api/keywords/pool?q=${encodeURIComponent(q.trim())}&limit=6`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => setKws(d?.items || []))
        .catch(() => setKws([]))
    }, 250)
    return () => window.clearTimeout(debRef.current)
  }, [q, open])

  useEffect(() => {
    if (open) { setQ(''); setKws([]); setSel(0); setTimeout(() => inputRef.current?.focus(), 60) }
  }, [open])

  /* 组装结果列表 */
  const pages: Entry[] = NAV_GROUPS.flatMap(g => g.items)
    .filter(it => !q.trim() || it.label.toLowerCase().includes(q.trim().toLowerCase()))
    .map(it => ({ kind: 'page' as const, id: it.id, label: it.label, icon: it.icon }))

  const actions: Entry[] = [
    { kind: 'action' as const, label: q.trim() ? `在词池中搜索「${q.trim()}」` : '打开关键词池', icon: '🔍', run: () => { onSwitch('keywords'); onClose() } },
    { kind: 'action' as const, label: '查看内容产线', icon: '⚙️', run: () => { onSwitch('workflow'); onClose() } },
    { kind: 'action' as const, label: '查看排名与监控', icon: '🖥️', run: () => { onSwitch('monitor'); onClose() } },
  ]

  const entries: Entry[] = [
    ...kws.map(kw => ({ kind: 'kw' as const, kw })),
    ...pages,
    ...actions,
  ]

  const exec = useCallback((e: Entry) => {
    if (e.kind === 'kw') { onSwitch('keywords'); onClose() }
    else if (e.kind === 'page') { onSwitch(e.id); onClose() }
    else e.run()
  }, [onSwitch, onClose])

  /* 键盘导航 */
  useEffect(() => {
    if (!open) return
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') { ev.preventDefault(); onClose() }
      else if (ev.key === 'ArrowDown') { ev.preventDefault(); setSel(s => Math.min(entries.length - 1, s + 1)) }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); setSel(s => Math.max(0, s - 1)) }
      else if (ev.key === 'Enter') { ev.preventDefault(); const e = entries[sel]; if (e) exec(e) }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, entries, sel, exec, onClose])

  useEffect(() => { setSel(0) }, [q, kws.length])

  if (!open) return null

  const kdTone = (kd: number | null) =>
    kd == null ? 'var(--faint)' : kd <= 10 ? 'var(--ok)' : kd <= 30 ? 'var(--warn)' : 'var(--bad)'

  let idx = -1
  const renderEntry = (e: Entry) => {
    idx += 1
    const i = idx
    const selected = i === sel
    const base: React.CSSProperties = {
      display: 'flex', alignItems: 'center', gap: 11,
      padding: isMobile ? '13px 16px' : '9px 18px', minHeight: isMobile ? 48 : undefined,
      fontSize: 13, cursor: 'pointer', color: 'var(--text)',
      background: selected ? 'oklch(from var(--accent) l c h / .12)' : 'transparent',
    }
    if (e.kind === 'kw') {
      return (
        <div key={`kw-${e.kw.keyword}`} style={base} onMouseEnter={() => setSel(i)} onClick={() => exec(e)}>
          <span style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--panel2)', display: 'grid', placeItems: 'center', fontSize: 12, flex: 'none' }}>🔍</span>
          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {e.kw.keyword}
            {e.kw.intent && <span style={{ color: 'var(--faint)', fontSize: 11, marginLeft: 8 }}>{e.kw.intent.split(',')[0]}</span>}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: kdTone(e.kw.difficulty), flex: 'none' }}>
            {e.kw.difficulty != null ? `KD ${Math.round(e.kw.difficulty)}` : ''}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--dim)', flex: 'none' }}>
            {e.kw.search_volume.toLocaleString('es-ES')}/月
          </span>
        </div>
      )
    }
    if (e.kind === 'page') {
      return (
        <div key={`pg-${e.id}`} style={base} onMouseEnter={() => setSel(i)} onClick={() => exec(e)}>
          <span style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--panel2)', display: 'grid', placeItems: 'center', fontSize: 12, flex: 'none' }}>{e.icon}</span>
          <span style={{ flex: 1 }}>{e.label}</span>
          <span style={{ fontSize: 10, color: 'var(--faint)' }}>页面</span>
        </div>
      )
    }
    return (
      <div key={`ac-${e.label}`} style={base} onMouseEnter={() => setSel(i)} onClick={() => exec(e)}>
        <span style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--panel2)', display: 'grid', placeItems: 'center', fontSize: 12, flex: 'none' }}>{e.icon}</span>
        <span style={{ flex: 1 }}>{e.label}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--faint)', background: 'var(--panel2)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px' }}>↵</span>
      </div>
    )
  }

  const Sec = ({ children }: { children: React.ReactNode }) => (
    <div style={{ fontSize: 10, color: 'var(--faint)', letterSpacing: '.12em', padding: '10px 18px 4px', textTransform: 'uppercase' }}>{children}</div>
  )

  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, background: 'oklch(0% 0 0 / .55)',
        backdropFilter: 'blur(3px)', zIndex: 1300,
        display: 'grid', placeItems: 'start center',
        paddingTop: isMobile ? 0 : '14vh',
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="命令面板"
        style={{
          width: isMobile ? '100vw' : 560, maxWidth: '100vw',
          height: isMobile ? '100dvh' : 'auto', maxHeight: isMobile ? '100dvh' : '62vh',
          background: 'var(--panel)', border: '1px solid var(--border)',
          borderRadius: isMobile ? 0 : 14, overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 70px oklch(0% 0 0 / .5)',
        }}
      >
        <input
          ref={inputRef}
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="搜关键词、跳页面、执行操作…"
          aria-label="命令输入"
          style={{
            width: '100%', padding: isMobile ? '16px 16px' : '15px 18px',
            background: 'none', border: 'none', outline: 'none',
            color: 'var(--text)', fontSize: 15, borderBottom: '1px solid var(--border)',
            boxSizing: 'border-box', flex: 'none',
          }}
        />
        <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 10 }}>
          {kws.length > 0 && <Sec>关键词</Sec>}
          {kws.map(kw => renderEntry({ kind: 'kw', kw }))}
          {pages.length > 0 && <Sec>页面</Sec>}
          {pages.map(p => renderEntry(p))}
          <Sec>操作</Sec>
          {actions.map(a => renderEntry(a))}
        </div>
        {isMobile && (
          <button
            onClick={onClose}
            style={{
              flex: 'none', margin: 10, minHeight: 44, borderRadius: 10,
              border: '1px solid var(--border)', background: 'var(--panel2)',
              color: 'var(--text)', fontSize: 13, cursor: 'pointer',
            }}
          >
            关闭
          </button>
        )}
      </div>
    </div>
  )
}

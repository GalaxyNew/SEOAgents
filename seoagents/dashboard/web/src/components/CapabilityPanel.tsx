import { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, btn, useQuickCommands, type QuickCmd } from '../ui'

/**
 * 能力中心 —— 双屏:左边选,右边看细节。
 *
 * 早先把插件、能力矩阵、技能三块平铺在一页,DataForSEO 这种带 89 个工具的
 * 插件只显示一行摘要,等于告诉你「它很强」但不告诉你强在哪。现在点开就能
 * 看到它实际提供的每一个 API,再点单项看用法。
 *
 * 每一项旁边有 ⚡ 开关:打开就把对应的指令加进 Copilot 的快捷指令区。
 */

type Capability = {
  label: string
  installed: string[]
  available_to_install: string[]
  unavailable: string[]
  comparable: boolean
  single_source_risk: boolean
  uncovered: boolean
}

type CatalogEntry = {
  id: string
  display_name: string
  capabilities: string[]
  capability_labels: string[]
  summary: string
  homepage: string
  installed?: boolean
}

type Skill = { id: string; kind: string; description: string; [k: string]: any }

type Selected =
  | { type: 'plugin'; id: string }
  | { type: 'capability'; id: string }
  | { type: 'skill'; id: string }
  | null

const card: React.CSSProperties = {
  background: '#111827', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 14px',
}

/** 从工具名反推它属于哪个 MCP 插件 */
const toolPrefix = (pluginId: string) => `mcp_${pluginId}_`

export const CapabilityPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const qc = useQuickCommands()
  const [caps, setCaps] = useState<Record<string, Capability>>({})
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])
  const [installedCount, setInstalledCount] = useState(0)
  const [skills, setSkills] = useState<Skill[]>([])
  const [tools, setTools] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [sel, setSel] = useState<Selected>(null)
  const [detail, setDetail] = useState<{ title: string; body: React.ReactNode } | null>(null)
  /**
   * 左侧手风琴。默认只开「插件」——三个列表同时平铺会占满整屏,
   * 右边的详情反而被挤到看不见,而右边才是这个页面的主体。
   * 记住选择:同一个人通常反复看同一组。
   */
  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(sessionStorage.getItem('capOpen') || '') || { plugin: true } }
    catch { return { plugin: true } }
  })
  const toggle = (k: string) => setOpen(o => {
    const next = { ...o, [k]: !o[k] }
    sessionStorage.setItem('capOpen', JSON.stringify(next))
    return next
  })

  const load = async () => {
    setLoading(true); setErr('')
    try {
      const [c, cat, sk, cfg] = await Promise.all([
        (await fetch('/api/capabilities')).json(),
        (await fetch('/api/catalog')).json(),
        (await fetch('/api/skills')).json(),
        (await fetch('/api/config')).json(),
      ])
      setCaps(c || {})
      setCatalog(cat.items || [])
      setInstalledCount(cat.installed_count || 0)
      setSkills(sk.data || [])
      setTools((cfg?.resolved?.tools as string[]) || [])
    } catch (e) {
      setErr(`能力目录不可用: ${e}`)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  if (loading) return <div style={{ ...card, color: '#9ca3af', textAlign: 'center' }}>🧭 正在载入能力目录…</div>
  if (err) return <div style={{ ...card, borderColor: '#7f1d1d', color: '#f87171' }}>⚠️ {err}</div>

  const capList = Object.entries(caps)
  const uncovered = capList.filter(([, v]) => v.uncovered)
  const risky = capList.filter(([, v]) => v.single_source_risk)

  const quickToggle = (c: QuickCmd) => {
    qc.toggle(c)
    setMsg(qc.has(c.id) ? `已从快捷指令移除:${c.title}` : `已加入快捷指令:${c.title}`)
    setTimeout(() => setMsg(''), 2600)
  }

  const Star: React.FC<{ cmd: QuickCmd }> = ({ cmd }) => (
    <button
      onClick={(e) => { e.stopPropagation(); quickToggle(cmd) }}
      title={qc.has(cmd.id) ? '已在快捷指令中,点击移除' : '加入 Copilot 快捷指令'}
      style={{
        background: qc.has(cmd.id) ? '#1e3a8a' : 'transparent',
        border: `1px solid ${qc.has(cmd.id) ? '#3b82f6' : '#334155'}`,
        color: qc.has(cmd.id) ? '#93c5fd' : '#64748b',
        borderRadius: 5, padding: '2px 7px', fontSize: 10,
        cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap',
      }}
    >
      {qc.has(cmd.id) ? '⚡ 已加入' : '⚡ 加入'}
    </button>
  )

  // ── 左栏 ────────────────────────────────────────────────────────
  const listItem = (
    key: string, active: boolean, onClick: () => void,
    title: React.ReactNode, sub: string, accent: string, right?: React.ReactNode,
  ) => (
    <div key={key} onClick={onClick} style={{
      background: active ? '#1e293b' : '#0f172a',
      border: `1px solid ${active ? '#3b82f6' : '#1e293b'}`,
      borderLeft: `3px solid ${accent}`,
      borderRadius: 7, padding: '8px 10px', cursor: 'pointer',
      display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0' }}>{title}</div>
        <div style={{ fontSize: 10, color: '#64748b', marginTop: 2, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</div>
      </div>
      {right}
    </div>
  )

  /** 手风琴分组头。计数放头上 —— 收起时也得知道里面有多少 */
  const section = (key: string, icon: string, title: string,
                   badge: React.ReactNode, body: React.ReactNode) => (
    <div style={card}>
      <div onClick={() => toggle(key)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          fontSize: 11, fontWeight: 700, color: '#94a3b8',
          marginBottom: open[key] ? 7 : 0, userSelect: 'none',
        }}>
        <span style={{
          display: 'inline-block', width: 10, transition: 'transform .15s',
          transform: open[key] ? 'rotate(90deg)' : 'none', color: '#64748b',
        }}>▶</span>
        <span>{icon} {title}</span>
        <span style={{ flex: 1 }} />
        {badge}
      </div>
      {open[key] && body}
    </div>
  )

  const left = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {section('plugin', '🔌', `插件 (${catalog.length},已装 ${installedCount})`, null, (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {catalog.map((e) => {
            const n = tools.filter((t) => t.startsWith(toolPrefix(e.id))).length
            return listItem(
              e.id, sel?.type === 'plugin' && sel.id === e.id,
              () => setSel({ type: 'plugin', id: e.id }),
              <>{e.display_name}{e.installed && <span style={{ color: '#6ee7b7', marginLeft: 6, fontSize: 10 }}>已装</span>}</>,
              n > 0 ? `${n} 个已注册工具` : e.summary,
              e.installed ? '#10b981' : '#475569',
              n > 0 ? <span style={{ fontSize: 10, color: '#60a5fa', flexShrink: 0 }}>{n}</span> : undefined,
            )
          })}
        </div>
      ))}

      {section('capability', '🧭', `能力 (${capList.length})`, (
        <span style={{ fontWeight: 400, fontSize: 10 }}>
          {uncovered.length > 0 && <span style={{ color: '#ef4444' }}>{uncovered.length} 未覆盖</span>}
          {risky.length > 0 && <span style={{ color: '#f59e0b', marginLeft: 6 }}>{risky.length} 单源</span>}
        </span>
      ), (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {capList.map(([k, v]) => listItem(
            k, sel?.type === 'capability' && sel.id === k,
            () => setSel({ type: 'capability', id: k }),
            v.label,
            v.uncovered ? '未覆盖 —— 没有插件能提供' : v.installed.join(', ') || '未安装提供方',
            v.uncovered ? '#ef4444' : v.single_source_risk ? '#f59e0b' : '#10b981',
          ))}
        </div>
      ))}

      {section('skill', '🎓', `技能 (${skills.length})`, null, (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {skills.map((s) => listItem(
            s.id, sel?.type === 'skill' && sel.id === s.id,
            () => setSel({ type: 'skill', id: s.id }),
            s.id, s.description || s.kind, '#a855f7',
          ))}
          {skills.length === 0 && (
            <div style={{ color: '#475569', fontSize: 11, textAlign: 'center', padding: '10px 0' }}>
              还没有沉淀出技能
            </div>
          )}
        </div>
      ))}
    </div>
  )

  // ── 右栏 ────────────────────────────────────────────────────────
  const right = (() => {
    if (!sel) {
      return (
        <div style={{ ...card, color: '#475569', fontSize: 12, textAlign: 'center', padding: '48px 20px', lineHeight: 1.9 }}>
          从左边选一项查看详情<br />
          <span style={{ fontSize: 11 }}>插件会列出它实际提供的每个 API,点开看用法</span>
        </div>
      )
    }

    if (sel.type === 'plugin') {
      const e = catalog.find((x) => x.id === sel.id)
      if (!e) return null
      const mine = tools.filter((t) => t.startsWith(toolPrefix(e.id)))
      // 按名字里的领域词分组,89 个平铺没法看
      const groups: Record<string, string[]> = {}
      mine.forEach((t) => {
        const short = t.replace(toolPrefix(e.id), '')
        const g = short.split('_')[0] || 'other'
        ;(groups[g] ||= []).push(short)
      })
      return (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>
              {e.display_name}
              {e.installed && <span style={{ background: '#064e3b', color: '#6ee7b7', borderRadius: 4, padding: '1px 6px', fontSize: 10, marginLeft: 8 }}>已装</span>}
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 5, lineHeight: 1.6 }}>{e.summary}</div>
            {e.homepage && <div style={{ fontSize: 10, color: '#60a5fa', marginTop: 4, wordBreak: 'break-all' }}>{e.homepage}</div>}
          </div>

          <div>
            <span style={{ fontSize: 10, color: '#64748b' }}>提供能力: </span>
            {(e.capability_labels || e.capabilities || []).map((c) => (
              <span key={c} style={{ background: '#1e293b', color: '#94a3b8', borderRadius: 3, padding: '1px 6px', fontSize: 9, marginRight: 4 }}>{c}</span>
            ))}
          </div>

          {mine.length === 0 ? (
            <div style={{ color: '#f59e0b', fontSize: 11 }}>
              尚未注册任何工具 —— 这个插件还没接上,或者没有 MCP 端点
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6' }}>
                提供的 API / MCP 工具({mine.length})
              </div>
              {/* 每个分组一张小卡片。之前是 89 个 chip 平铺成一片,
                  分组标题淹在里面,眼睛没有落点 —— 卡片给了边界。 */}
              <div style={{
                display: 'grid', gap: 10,
                gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))',
              }}>
              {Object.entries(groups).sort((a, b) => b[1].length - a[1].length).map(([g, list]) => (
                <div key={g} style={{
                  border: '1px solid #1e293b', borderRadius: 8, padding: 10,
                  background: '#0b1220',
                }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6,
                    fontSize: 11, color: '#a855f7', fontWeight: 700,
                  }}>
                    <span>{g}</span>
                    <span style={{
                      fontSize: 10, padding: '0 6px', borderRadius: 9,
                      background: 'rgba(168,85,247,.18)', color: '#c4b5fd',
                    }}>{list.length}</span>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {list.map((short) => {
                      const full = toolPrefix(e.id) + short
                      return (
                        <span key={short}
                          onClick={() => setDetail({
                            title: full,
                            body: (
                              <div style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.8 }}>
                                <div style={{ color: '#94a3b8', marginBottom: 8 }}>来自插件 <strong>{e.display_name}</strong></div>
                                <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: 10, fontFamily: 'monospace', fontSize: 11, color: '#93c5fd', wordBreak: 'break-all' }}>
                                  {full}
                                </div>
                                <div style={{ marginTop: 12, fontWeight: 700, color: '#f3f4f6' }}>怎么用</div>
                                <div style={{ marginTop: 4 }}>
                                  在 Copilot 里直接跟 hm 说要做什么,它会自己选工具。也可以点名:
                                </div>
                                <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: 10, marginTop: 6, fontSize: 11, color: '#cbd5e1' }}>
                                  用 {full} 查…(记得说明地域:location_name=Spain, language_code=es)
                                </div>
                                <div style={{ marginTop: 12, color: '#f59e0b', fontSize: 11, lineHeight: 1.7 }}>
                                  ⚠️ DataForSEO 的 location_name 默认是 United States。不显式传就是查美国,
                                  而且不会报错 —— 数据看着正常,国家却是错的。
                                </div>
                              </div>
                            ),
                          })}
                          style={{
                            background: '#0f172a', border: '1px solid #1e293b', borderRadius: 4,
                            color: '#cbd5e1', fontSize: 10, padding: '2px 7px',
                            cursor: 'pointer', fontFamily: 'monospace',
                          }}>{short}</span>
                      )
                    })}
                  </div>
                </div>
              ))}
              </div>
            </>
          )}

          <div style={{ borderTop: '1px solid #1f2937', paddingTop: 9, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, color: '#64748b' }}>把这个插件的常用查询加进快捷指令</span>
            <Star cmd={{
              id: `plugin:${e.id}`, origin: e.display_name,
              title: `🔌 ${e.display_name}`,
              prompt: `用 ${e.display_name} 的工具查一下(记得传 location_name=Spain, language_code=es):`,
            }} />
          </div>
        </div>
      )
    }

    if (sel.type === 'capability') {
      const v = caps[sel.id]
      if (!v) return null
      const color = v.uncovered ? '#ef4444' : v.single_source_risk ? '#f59e0b' : '#10b981'
      return (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>{v.label}</div>
            <div style={{ fontSize: 10, color: '#475569', fontFamily: 'monospace', marginTop: 2 }}>{sel.id}</div>
            <div style={{ color, fontSize: 12, fontWeight: 700, marginTop: 6 }}>
              {v.uncovered ? '● 未覆盖' : v.single_source_risk ? '● 单一数据源' : '● 已覆盖'}
            </div>
          </div>
          {v.uncovered && (
            <div style={{ background: '#1f1315', border: '1px solid #7f1d1d', borderRadius: 6, padding: 9, fontSize: 11, color: '#fca5a5', lineHeight: 1.7 }}>
              目前没有任何已安装的插件能提供这项能力。用到它的流程会拿不到数据,
              评分引擎会因此拒绝出分(而不是给个估算值)。
            </div>
          )}
          {v.single_source_risk && (
            <div style={{ background: '#1f1a10', border: '1px solid #78350f', borderRadius: 6, padding: 9, fontSize: 11, color: '#fcd34d', lineHeight: 1.7 }}>
              只有一个数据源,无法交叉验证。这个源出错时没有第二方能发现。
            </div>
          )}
          <div style={{ fontSize: 11, lineHeight: 2 }}>
            <div><span style={{ color: '#64748b' }}>已安装提供方:</span> <span style={{ color: '#6ee7b7' }}>{v.installed.join(', ') || '无'}</span></div>
            <div><span style={{ color: '#64748b' }}>可安装:</span> <span style={{ color: '#93c5fd' }}>{v.available_to_install.join(', ') || '无'}</span></div>
            <div><span style={{ color: '#64748b' }}>不可用:</span> <span style={{ color: '#64748b' }}>{v.unavailable.join(', ') || '无'}</span></div>
            <div><span style={{ color: '#64748b' }}>可交叉验证:</span> <span style={{ color: v.comparable ? '#a855f7' : '#64748b' }}>{v.comparable ? '是' : '否'}</span></div>
          </div>
          <div style={{ borderTop: '1px solid #1f2937', paddingTop: 9, display: 'flex', justifyContent: 'flex-end' }}>
            <Star cmd={{
              id: `cap:${sel.id}`, origin: v.label,
              title: `🧭 ${v.label}`,
              prompt: `检查一下「${v.label}」这项能力当前的数据状况,如果取不到就说明原因,不要估算。`,
            }} />
          </div>
        </div>
      )
    }

    const s = skills.find((x) => x.id === sel.id)
    if (!s) return null
    return (
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#f3f4f6' }}>{s.id}</div>
          <span style={{ background: '#1e293b', color: '#a855f7', borderRadius: 3, padding: '1px 6px', fontSize: 10 }}>{s.kind}</span>
        </div>
        <div style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.7 }}>{s.description}</div>
        <pre style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: 9, fontSize: 10, color: '#94a3b8', maxHeight: 260, overflow: 'auto' }}>
          {JSON.stringify(s, null, 2)}
        </pre>
        <div style={{ borderTop: '1px solid #1f2937', paddingTop: 9, display: 'flex', justifyContent: 'space-between', gap: 7 }}>
          <button onClick={async () => {
            setMsg(`正在重放 ${s.id}…`)
            const r = await fetch('/api/skills/replay', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ skill_id: s.id }),
            })
            const j = await r.json().catch(() => ({}))
            setMsg(j.ok ? `${s.id} 重放完成` : `重放失败: ${j.error || j.detail || r.status}`)
          }} style={btn('#334155')}>▶ 重放</button>
          <Star cmd={{
            id: `skill:${s.id}`, origin: s.id,
            title: `🎓 ${s.id}`,
            prompt: `用技能 ${s.id} 处理:`,
          }} />
        </div>
      </div>
    )
  })()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
          <span style={{ color: '#64748b' }}>能力 <strong style={{ color: '#60a5fa' }}>{capList.length}</strong></span>
          <span style={{ color: '#64748b' }}>未覆盖 <strong style={{ color: uncovered.length ? '#ef4444' : '#10b981' }}>{uncovered.length}</strong></span>
          <span style={{ color: '#64748b' }}>单源风险 <strong style={{ color: risky.length ? '#f59e0b' : '#10b981' }}>{risky.length}</strong></span>
          <span style={{ color: '#64748b' }}>插件 <strong style={{ color: '#a855f7' }}>{installedCount}/{catalog.length}</strong></span>
          <span style={{ color: '#64748b' }}>工具 <strong style={{ color: '#e2e8f0' }}>{tools.length}</strong></span>
          <span style={{ color: '#64748b' }}>快捷指令 <strong style={{ color: '#93c5fd' }}>{qc.cmds.length}</strong></span>
        </div>
        <button onClick={load} style={btn('#334155')}>↻ 刷新</button>
      </div>

      {msg && <div style={{ ...card, fontSize: 11, color: msg.includes('失败') ? '#f87171' : '#6ee7b7' }}>{msg}</div>}

      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : 'minmax(260px, 360px) 1fr',
        gap: 10, alignItems: 'start',
      }}>
        {left}
        {right}
      </div>

      <Modal open={!!detail} title={detail?.title || ''} width={560} onClose={() => setDetail(null)}>
        {detail?.body}
      </Modal>
    </div>
  )
}

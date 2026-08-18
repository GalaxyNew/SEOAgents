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

/** 已安装工具的统一元信息:工具 ID → 中文名、说明、实现能力 */
const TOOL_META: Record<string, { label: string; desc: string; capability: string; catalog: string }> = {
  google_seo_monitor: {
    label: 'Google 搜索监控',
    desc: '拉取 GSC 真实点击率、展现量、平均排名、趋势',
    capability: 'traffic',
    catalog: 'google_search_console',
  },
  gsc_indexing_ops: {
    label: '收录运维',
    desc: 'sitemap 生成、301 映射、收录状态实测',
    capability: 'indexing',
    catalog: 'google_search_console',
  },
  lighthouse_audit: {
    label: '性能审计',
    desc: 'Core Web Vitals,优先 PSI API,其次本地 Chromium',
    capability: 'cwv',
    catalog: 'lighthouse',
  },
  site_technical_auditor: {
    label: '技术 SEO 审计',
    desc: '同域 BFS:标题/描述/H1/canonical/死链/hreflang',
    capability: 'site_audit',
    catalog: 'python_seo_analyzer',
  },
  serp_rank_tracker: {
    label: 'SERP 排名追踪',
    desc: '目标关键词的谷歌实测排位,优先 DataForSEO',
    capability: 'serp_rank',
    catalog: 'openserp',
  },
  keyword_discovery: {
    label: '关键词发现',
    desc: '合并 GSC 实际词、DataForSEO 建议、竞品词',
    capability: 'keyword_research',
    catalog: 'dataforseo',
  },
  nlp_internal_linker: {
    label: '内链推荐',
    desc: '基于 TF-IDF 语义矩阵匹配,自动植入内链',
    capability: 'internal_link',
    catalog: '',
  },
  aeo_visibility_monitor: {
    label: 'AI 搜索可见度',
    desc: '品牌在 ChatGPT/Claude/Perplexity/AIO 的被引用率',
    capability: 'aeo_visibility',
    catalog: 'searchstack_aeo',
  },
  asset_hub: {
    label: '中央资产存储',
    desc: '产物登记、检索、血缘(多节点)',
    capability: '',
    catalog: '',
  },
  platform_ops: {
    label: '平台管理',
    desc: '系统配置、工具安装、凭证管理(读操作直接执行)',
    capability: '',
    catalog: '',
  },
  system_ops: {
    label: '系统运维面板',
    desc: 'SEOAgents 系统管理(hm 专用)',
    capability: '',
    catalog: '',
  },
}

type Selected =
  | { type: 'plugin'; id: string }
  | { type: 'capability'; id: string }
  | { type: 'skill'; id: string }
  | { type: 'tool'; id: string }
  | null

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 10, padding: '12px 14px',
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
  const [search, setSearch] = useState('')
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

  if (loading) return <div style={{ ...card, color: 'var(--dim)', textAlign: 'center' }}>🧭 正在载入能力目录…</div>
  if (err) return <div style={{ ...card, borderColor: 'var(--bad-soft)', color: 'var(--bad)' }}>⚠️ {err}</div>

  // ── 搜索过滤 ────────────────────────────────────────────────
  const capList = Object.entries(caps)
  const q = search.trim().toLowerCase()
  const filteredCatalog = q ? catalog.filter(e =>
    e.display_name.toLowerCase().includes(q) ||
    e.id.toLowerCase().includes(q) ||
    (e.summary || '').toLowerCase().includes(q) ||
    (e.capability_labels || []).some(c => c.toLowerCase().includes(q))
  ) : catalog
  const filteredCaps = q ? capList.filter(([k, v]) =>
    k.toLowerCase().includes(q) ||
    (v.label || '').toLowerCase().includes(q) ||
    (v.installed || []).some(t => t.toLowerCase().includes(q))
  ) : capList
  const filteredSkills = q ? skills.filter(s =>
    s.id.toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    (s.kind || '').toLowerCase().includes(q)
  ) : skills
  const toolIds = Object.keys(TOOL_META)
  const filteredTools = q ? toolIds.filter(id => {
    const meta = TOOL_META[id]
    return id.toLowerCase().includes(q) ||
      meta.label.toLowerCase().includes(q) ||
      meta.desc.toLowerCase().includes(q) ||
      meta.capability.toLowerCase().includes(q)
  }) : toolIds

  // 搜索时自动展开所有折叠面板
  const searchOpen: Record<string, boolean> | null = q ? { tool: true, plugin: true, capability: true, skill: true } : null
  const effectiveOpen = searchOpen || open

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
        background: qc.has(cmd.id) ? 'var(--accent-soft)' : 'transparent',
        border: `1px solid ${qc.has(cmd.id) ? 'var(--accent)' : 'var(--border)'}`,
        color: qc.has(cmd.id) ? 'var(--accent)' : 'var(--faint)',
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
      background: active ? 'var(--panel)' : 'var(--surface)',
      border: `1px solid ${active ? 'var(--accent)' : 'var(--panel)'}`,
      borderLeft: `3px solid ${accent}`,
      borderRadius: 7, padding: '8px 10px', cursor: 'pointer',
      display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{title}</div>
        <div style={{ fontSize: 10, color: 'var(--faint)', marginTop: 2, overflow: 'hidden',
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
          fontSize: 11, fontWeight: 700, color: 'var(--dim)',
          marginBottom: effectiveOpen[key] ? 7 : 0, userSelect: 'none',
        }}>
        <span style={{
          display: 'inline-block', width: 10, transition: 'transform .15s',
          transform: effectiveOpen[key] ? 'rotate(90deg)' : 'none', color: 'var(--faint)',
        }}>▶</span>
        <span>{icon} {title}</span>
        <span style={{ flex: 1 }} />
        {badge}
      </div>
      {effectiveOpen[key] && body}
    </div>
  )

  const left = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 搜索框 */}
      <div style={card}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="🔍 搜索插件、能力、技能…"
          style={{
            width: '100%', boxSizing: 'border-box',
            background: 'var(--surface)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 6,
            padding: '7px 10px', fontSize: 12, outline: 'none',
          }}
        />
        {q && (
          <div style={{ fontSize: 10, color: 'var(--faint)', marginTop: 5 }}>
            {filteredCatalog.length + filteredCaps.length + filteredSkills.length} 个结果
          </div>
        )}
      </div>
      {section('tool', '⚙️', `已安装工具 (${filteredTools.length})`, null, (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {filteredTools.map(id => {
            const meta = TOOL_META[id]
            const capLabel = meta.capability && caps[meta.capability] ? caps[meta.capability].label : meta.capability
            return listItem(
              id, sel?.type === 'tool' && sel.id === id,
              () => setSel({ type: 'tool', id }),
              <>{meta.label} <span style={{ fontFamily: 'monospace', fontSize: 9, color: 'var(--border)' }}>{id}</span></>,
              meta.desc + (capLabel ? ` → ${capLabel}` : ''),
              'var(--accent)',
            )
          })}
        </div>
      ))}

      {section('plugin', '🔌', `插件 (${filteredCatalog.length}${q ? '/' + catalog.length : ''},已装 ${installedCount})`, null, (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {filteredCatalog.map((e) => {
            const n = tools.filter((t) => t.startsWith(toolPrefix(e.id))).length
            return listItem(
              e.id, sel?.type === 'plugin' && sel.id === e.id,
              () => setSel({ type: 'plugin', id: e.id }),
              <>{e.display_name}{e.installed && <span style={{ color: 'var(--ok)', marginLeft: 6, fontSize: 10 }}>已装</span>}</>,
              n > 0 ? `${n} 个已注册工具` : e.summary,
              e.installed ? 'var(--ok)' : 'var(--border)',
              n > 0 ? <span style={{ fontSize: 10, color: 'var(--accent)', flexShrink: 0 }}>{n}</span> : undefined,
            )
          })}
        </div>
      ))}

      {section('capability', '🧭', `能力 (${filteredCaps.length}${q ? '/' + capList.length : ''})`, (
        <span style={{ fontWeight: 400, fontSize: 10 }}>
          {uncovered.length > 0 && <span style={{ color: 'var(--bad)' }}>{uncovered.length} 未覆盖</span>}
          {risky.length > 0 && <span style={{ color: 'var(--warn)', marginLeft: 6 }}>{risky.length} 单源</span>}
        </span>
      ), (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {filteredCaps.map(([k, v]) => listItem(
            k, sel?.type === 'capability' && sel.id === k,
            () => setSel({ type: 'capability', id: k }),
            v.label,
            v.uncovered ? '未覆盖 —— 没有插件能提供' : v.installed.join(', ') || '未安装提供方',
            v.uncovered ? 'var(--bad)' : v.single_source_risk ? 'var(--warn)' : 'var(--ok)',
          ))}
        </div>
      ))}

      {section('skill', '🎓', `技能 (${filteredSkills.length}${q ? '/' + skills.length : ''})`, null, (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {filteredSkills.map((s) => listItem(
            s.id, sel?.type === 'skill' && sel.id === s.id,
            () => setSel({ type: 'skill', id: s.id }),
            s.id, s.description || s.kind, 'var(--rev)',
          ))}
          {filteredSkills.length === 0 && (
            <div style={{ color: 'var(--border)', fontSize: 11, textAlign: 'center', padding: '10px 0' }}>
              {q ? '没有匹配的技能' : '还没有沉淀出技能'}
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
        <div style={{ ...card, color: 'var(--border)', fontSize: 12, textAlign: 'center', padding: '48px 20px', lineHeight: 1.9 }}>
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
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
              {e.display_name}
              {e.installed && <span style={{ background: 'var(--ok-soft)', color: 'var(--ok)', borderRadius: 4, padding: '1px 6px', fontSize: 10, marginLeft: 8 }}>已装</span>}
            </div>
            <div style={{ fontSize: 11, color: 'var(--dim)', marginTop: 5, lineHeight: 1.6 }}>{e.summary}</div>
            {e.homepage && <div style={{ fontSize: 10, color: 'var(--accent)', marginTop: 4, wordBreak: 'break-all' }}>{e.homepage}</div>}
          </div>

          <div>
            <span style={{ fontSize: 10, color: 'var(--faint)' }}>提供能力: </span>
            {(e.capability_labels || e.capabilities || []).map((c) => (
              <span key={c} style={{ background: 'var(--panel)', color: 'var(--dim)', borderRadius: 3, padding: '1px 6px', fontSize: 9, marginRight: 4 }}>{c}</span>
            ))}
          </div>

          {mine.length === 0 ? (
            <div style={{ color: 'var(--warn)', fontSize: 11 }}>
              尚未注册任何工具 —— 这个插件还没接上,或者没有 MCP 端点
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
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
                  border: '1px solid var(--panel)', borderRadius: 8, padding: 10,
                  background: 'var(--bg)',
                }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6,
                    fontSize: 11, color: 'var(--rev)', fontWeight: 700,
                  }}>
                    <span>{g}</span>
                    <span style={{
                      fontSize: 10, padding: '0 6px', borderRadius: 9,
                      background: 'var(--rev-soft)', color: 'var(--rev)',
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
                              <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.8 }}>
                                <div style={{ color: 'var(--dim)', marginBottom: 8 }}>来自插件 <strong>{e.display_name}</strong></div>
                                <div style={{ background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 6, padding: 10, fontFamily: 'monospace', fontSize: 11, color: 'var(--accent)', wordBreak: 'break-all' }}>
                                  {full}
                                </div>
                                <div style={{ marginTop: 12, fontWeight: 700, color: 'var(--text)' }}>怎么用</div>
                                <div style={{ marginTop: 4 }}>
                                  在 Copilot 里直接跟 hm 说要做什么,它会自己选工具。也可以点名:
                                </div>
                                <div style={{ background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 6, padding: 10, marginTop: 6, fontSize: 11, color: 'var(--text)' }}>
                                  用 {full} 查…(记得说明地域:location_name=Spain, language_code=es)
                                </div>
                                <div style={{ marginTop: 12, color: 'var(--warn)', fontSize: 11, lineHeight: 1.7 }}>
                                  ⚠️ DataForSEO 的 location_name 默认是 United States。不显式传就是查美国,
                                  而且不会报错 —— 数据看着正常,国家却是错的。
                                </div>
                              </div>
                            ),
                          })}
                          style={{
                            background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 4,
                            color: 'var(--text)', fontSize: 10, padding: '2px 7px',
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

          <div style={{ borderTop: '1px solid var(--panel)', paddingTop: 9, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, color: 'var(--faint)' }}>把这个插件的常用查询加进快捷指令</span>
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
      const color = v.uncovered ? 'var(--bad)' : v.single_source_risk ? 'var(--warn)' : 'var(--ok)'
      return (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{v.label}</div>
            <div style={{ fontSize: 10, color: 'var(--border)', fontFamily: 'monospace', marginTop: 2 }}>{sel.id}</div>
            <div style={{ color, fontSize: 12, fontWeight: 700, marginTop: 6 }}>
              {v.uncovered ? '● 未覆盖' : v.single_source_risk ? '● 单一数据源' : '● 已覆盖'}
            </div>
          </div>
          {v.uncovered && (
            <div style={{ background: 'var(--bad-soft)', border: '1px solid var(--bad-soft)', borderRadius: 6, padding: 9, fontSize: 11, color: 'var(--bad)', lineHeight: 1.7 }}>
              目前没有任何已安装的插件能提供这项能力。用到它的流程会拿不到数据,
              评分引擎会因此拒绝出分(而不是给个估算值)。
            </div>
          )}
          {v.single_source_risk && (
            <div style={{ background: 'var(--warn-soft)', border: '1px solid var(--warn-soft)', borderRadius: 6, padding: 9, fontSize: 11, color: 'var(--warn)', lineHeight: 1.7 }}>
              只有一个数据源,无法交叉验证。这个源出错时没有第二方能发现。
            </div>
          )}
          <div style={{ fontSize: 11, lineHeight: 2 }}>
            <div><span style={{ color: 'var(--faint)' }}>已安装提供方:</span> <span style={{ color: 'var(--ok)' }}>{v.installed.join(', ') || '无'}</span></div>
            <div><span style={{ color: 'var(--faint)' }}>可安装:</span> <span style={{ color: 'var(--accent)' }}>{v.available_to_install.join(', ') || '无'}</span></div>
            <div><span style={{ color: 'var(--faint)' }}>不可用:</span> <span style={{ color: 'var(--faint)' }}>{v.unavailable.join(', ') || '无'}</span></div>
            <div><span style={{ color: 'var(--faint)' }}>可交叉验证:</span> <span style={{ color: v.comparable ? 'var(--rev)' : 'var(--faint)' }}>{v.comparable ? '是' : '否'}</span></div>
          </div>
          <div style={{ borderTop: '1px solid var(--panel)', paddingTop: 9, display: 'flex', justifyContent: 'flex-end' }}>
            <Star cmd={{
              id: `cap:${sel.id}`, origin: v.label,
              title: `🧭 ${v.label}`,
              prompt: `检查一下「${v.label}」这项能力当前的数据状况,如果取不到就说明原因,不要估算。`,
            }} />
          </div>
        </div>
      )
    }

    if (sel.type === 'tool') {
      const meta = TOOL_META[sel.id]
      if (!meta) return null
      const capInfo = meta.capability && caps[meta.capability] ? caps[meta.capability] : null
      const catEntry = meta.catalog ? catalog.find(e => e.id === meta.catalog) : null
      return (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{meta.label}</div>
            <div style={{ fontSize: 10, color: 'var(--border)', fontFamily: 'monospace', marginTop: 2 }}>{sel.id}</div>
            <div style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 700, marginTop: 6 }}>● 已安装</div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.7 }}>{meta.desc}</div>

          <div style={{ fontSize: 11, lineHeight: 2 }}>
            {capInfo && (
              <div>
                <span style={{ color: 'var(--faint)' }}>实现能力:</span>{' '}
                <span style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}
                  onClick={() => setSel({ type: 'capability', id: meta.capability })}>
                  {capInfo.label}
                </span>{' '}
                {capInfo.single_source_risk && <span style={{ color: 'var(--warn)', fontSize: 10 }}>⚠ 单源</span>}
              </div>
            )}
            {catEntry && (
              <div>
                <span style={{ color: 'var(--faint)' }}>目录条目:</span>{' '}
                <span style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}
                  onClick={() => setSel({ type: 'plugin', id: catEntry.id })}>
                  {catEntry.display_name}
                </span>
              </div>
            )}
            {!capInfo && !catEntry && (
              <div>
                <span style={{ color: 'var(--faint)' }}>说明:</span>{' '}
                <span style={{ color: 'var(--dim)' }}>平台内置工具,不映射到外部能力</span>
              </div>
            )}
          </div>

          <div style={{ background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 6, padding: 9, fontSize: 11, color: 'var(--dim)', lineHeight: 1.7 }}>
            <div style={{ color: 'var(--faint)', marginBottom: 4 }}>用法示例</div>
            <div style={{ fontFamily: 'monospace', color: 'var(--accent)' }}>用 {sel.id}({meta.label})查一下…</div>
          </div>

          <div style={{ borderTop: '1px solid var(--panel)', paddingTop: 9, display: 'flex', justifyContent: 'flex-end' }}>
            <Star cmd={{
              id: `tool:${sel.id}`, origin: meta.label,
              title: `⚙️ ${meta.label}`,
              prompt: `用 ${sel.id}(${meta.label})查一下:`,
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
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{s.id}</div>
          <span style={{ background: 'var(--panel)', color: 'var(--rev)', borderRadius: 3, padding: '1px 6px', fontSize: 10 }}>{s.kind}</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.7 }}>{s.description}</div>
        <pre style={{ background: 'var(--surface)', border: '1px solid var(--panel)', borderRadius: 6, padding: 9, fontSize: 10, color: 'var(--dim)', maxHeight: 260, overflow: 'auto' }}>
          {JSON.stringify(s, null, 2)}
        </pre>
        <div style={{ borderTop: '1px solid var(--panel)', paddingTop: 9, display: 'flex', justifyContent: 'space-between', gap: 7 }}>
          <button onClick={async () => {
            setMsg(`正在重放 ${s.id}…`)
            const r = await fetch('/api/skills/replay', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ skill_id: s.id }),
            })
            const j = await r.json().catch(() => ({}))
            setMsg(j.ok ? `${s.id} 重放完成` : `重放失败: ${j.error || j.detail || r.status}`)
          }} style={btn('var(--border)')}>▶ 重放</button>
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
          <span style={{ color: 'var(--faint)' }}>能力 <strong style={{ color: 'var(--accent)' }}>{capList.length}</strong></span>
          <span style={{ color: 'var(--faint)' }}>未覆盖 <strong style={{ color: uncovered.length ? 'var(--bad)' : 'var(--ok)' }}>{uncovered.length}</strong></span>
          <span style={{ color: 'var(--faint)' }}>单源风险 <strong style={{ color: risky.length ? 'var(--warn)' : 'var(--ok)' }}>{risky.length}</strong></span>
          <span style={{ color: 'var(--faint)' }}>插件 <strong style={{ color: 'var(--rev)' }}>{installedCount}/{catalog.length}</strong></span>
          <span style={{ color: 'var(--faint)' }}>工具 <strong style={{ color: 'var(--text)' }}>{tools.length}</strong></span>
          <span style={{ color: 'var(--faint)' }}>快捷指令 <strong style={{ color: 'var(--accent)' }}>{qc.cmds.length}</strong></span>
        </div>
        <button onClick={load} style={btn('var(--border)')}>↻ 刷新</button>
      </div>

      {msg && <div style={{ ...card, fontSize: 11, color: msg.includes('失败') ? 'var(--bad)' : 'var(--ok)' }}>{msg}</div>}

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

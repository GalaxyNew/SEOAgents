/**
 * OverviewPanel — 决策台首页（UI v3 · PR-B）
 *
 * 设计：一屏回答三件事——现在什么状态（KPI）/ 今天发生了什么（时间线）/
 * 下一步干什么（机会词、转化词直接给答案）。全部用现有 API，零新后端：
 *   /api/metrics/summary        M_t、SERP、死链、技能
 *   /api/keywords/pool          机会词（sort=difficulty&min_vol=500）、转化词（intent=Transactional）
 *   /api/workflows/instances    产线动态
 * 每个模块可点击 → DetailDrawer 展开明细（明细数据同源，多拉几行）。
 * GA4 模块位（PR-D 接入）：summary 卡渲染「未接入」空态，接入后自动亮起。
 *
 * 移动端：KPI 4列→2列，主网格 3列→1列（CSS grid auto-fit）。
 */
import { useCallback, useEffect, useState } from 'react'
import type { MetricsSummary } from './MetricsPanel'
import { DetailDrawer, DrawerHero, DrawerSection, HBar, DrawerNote } from './DetailDrawer'
import { useIsMobile } from '../hooks'

/* ── 数据类型 ── */
type PoolItem = { keyword: string; search_volume: number; difficulty: number | null; intent?: string | null; cpc?: number }
type WfInstance = { id?: string; name?: string; status?: string; progress?: number; template_name?: string; updated_at?: string }

type DrawerId =
  | null | 'health' | 'serp' | 'deadlinks' | 'skills'
  | 'sweet' | 'trans' | 'pipeline'

const fmtInt = (n: number | null | undefined) => (n ?? 0).toLocaleString('es-ES')

/* KD 徽章色阶：≤10 绿 / ≤30 黄 / 其余红；null=没数据显示 — */
function KdBadge({ kd }: { kd: number | null }) {
  if (kd === null || kd === undefined) return <span style={{ color: 'var(--faint)' }}>—</span>
  const tone = kd <= 10 ? 'var(--ok)' : kd <= 30 ? 'var(--warn)' : 'var(--bad)'
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 10.5, padding: '1.5px 8px', borderRadius: 9,
      fontWeight: 600, color: tone, background: `oklch(from ${tone} l c h / .13)`,
    }}>
      {Math.round(kd)}
    </span>
  )
}

/* KPI 卡：可点击展开 */
function KpiCard({ label, value, unit, delta, deltaTone, src, onClick, empty }: {
  label: string; value: string; unit?: string; delta?: string
  deltaTone?: 'up' | 'down' | 'flat'; src?: string; onClick?: () => void; empty?: boolean
}) {
  const tone = deltaTone === 'down' ? 'var(--bad)' : deltaTone === 'flat' ? 'var(--faint)' : 'var(--ok)'
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={e => { if (onClick && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onClick() } }}
      className="dk-panel"
      style={{
        padding: '13px 15px 11px', position: 'relative', overflow: 'hidden',
        cursor: onClick ? 'pointer' : 'default', minHeight: 64,
        opacity: empty ? .55 : 1,
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--dim)', display: 'flex', alignItems: 'center', gap: 6 }}>
        {label}
        {src && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8.5, letterSpacing: '.05em', padding: '1px 5px', borderRadius: 4, background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--faint)' }}>
            {src}
          </span>
        )}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 24, fontWeight: 700, letterSpacing: '-.02em', marginTop: 3, color: 'var(--text)' }}>
        {value}
        {unit && <span style={{ fontSize: 12, color: 'var(--faint)', fontWeight: 400, marginLeft: 2 }}>{unit}</span>}
      </div>
      {delta && (
        <span style={{ position: 'absolute', top: 12, right: 13, fontFamily: 'var(--font-mono)', fontSize: 11, padding: '2px 7px', borderRadius: 10, color: tone, background: `oklch(from ${tone} l c h / .12)` }}>
          {delta}
        </span>
      )}
    </div>
  )
}

/* 模块卡（带 header + 展开提示） */
function ModuleCard({ title, hint, onExpand, children, style }: {
  title: string; hint?: string; onExpand?: () => void; children: React.ReactNode; style?: React.CSSProperties
}) {
  return (
    <section
      className="dk-panel"
      style={{ overflow: 'hidden', padding: 0, ...style }}
    >
      <header
        onClick={onExpand}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '11px 14px',
          borderBottom: '1px solid var(--border)', cursor: onExpand ? 'pointer' : 'default',
        }}
      >
        <b style={{ fontSize: 12.5, color: 'var(--text)' }}>{title}</b>
        {hint && <span style={{ color: 'var(--faint)', fontSize: 10.5 }}>{hint}</span>}
        {onExpand && <span style={{ marginLeft: 'auto', color: 'var(--accent)', fontSize: 11, whiteSpace: 'nowrap' }}>展开 ↗</span>}
      </header>
      {children}
    </section>
  )
}

/* 简表 */
function MiniTable({ head, rows }: { head: (string | React.ReactNode)[]; rows: React.ReactNode[][] }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr>
          {head.map((h, i) => (
            <th key={i} style={{ fontSize: 10.5, color: 'var(--faint)', textAlign: i === 0 ? 'left' : 'right', fontWeight: 500, padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={head.length} style={{ padding: '18px 14px', textAlign: 'center', color: 'var(--faint)', fontSize: 11 }}>暂无数据</td></tr>
        )}
        {rows.map((cells, ri) => (
          <tr key={ri}>
            {cells.map((c, ci) => (
              <td key={ci} style={{
                padding: '8.5px 14px', borderBottom: ri === rows.length - 1 ? 'none' : '1px solid oklch(from var(--border) l c h / .45)',
                textAlign: ci === 0 ? 'left' : 'right',
                fontFamily: ci === 0 ? undefined : 'var(--font-mono)',
                color: 'var(--text)',
              }}>{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function OverviewPanel({ summary }: { summary: MetricsSummary | null }) {
  const isMobile = useIsMobile()
  const [drawer, setDrawer] = useState<DrawerId>(null)
  const [sweet, setSweet] = useState<PoolItem[]>([])
  const [trans, setTrans] = useState<PoolItem[]>([])
  const [transTotal, setTransTotal] = useState(0)
  const [wf, setWf] = useState<WfInstance[]>([])
  const [poolTotal, setPoolTotal] = useState<number | null>(null)

  const load = useCallback(async () => {
    // 机会词：难度升序 + 量下限（甜点区）
    fetch('/api/keywords/pool?sort=difficulty&min_vol=500&limit=12')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) { setSweet(d.items || []); setPoolTotal(d.total ?? null) } })
      .catch(() => {})
    // 转化词
    fetch('/api/keywords/pool?intent=Transactional&min_vol=100&sort=volume&limit=12')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) { setTrans(d.items || []); setTransTotal(d.total || 0) } })
      .catch(() => {})
    // 产线（workflow instances）
    fetch('/api/workflows/instances?limit=8')
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        const items = Array.isArray(d) ? d : (d?.items || d?.instances || [])
        setWf(items.slice(0, 8))
      })
      .catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  const serp = summary?.serp_positions || []
  const top10 = serp.filter((p: any) => p?.position != null && p.position <= 10).length
  const deadLinks = summary?.open_dead_links ?? 0
  const skills = Array.isArray(summary?.skills) ? summary.skills.length : 0
  const mt = summary?.latest_m_t

  const wfStatus = (s?: string) => {
    const v = (s || '').toLowerCase()
    if (['running', 'in_progress', 'active'].includes(v)) return { label: '进行中', tone: 'var(--accent)' }
    if (['done', 'completed', 'success', 'passed'].includes(v)) return { label: '完成', tone: 'var(--ok)' }
    if (['failed', 'error'].includes(v)) return { label: '失败', tone: 'var(--bad)' }
    return { label: s || '待定', tone: 'var(--faint)' }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* ── KPI 行 1：SEO ── */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(4,1fr)', gap: 12 }}>
        <KpiCard
          label="综合演化评分"
          value={mt != null ? Number(mt).toFixed(2) : '—'}
          delta={mt != null ? 'M_t' : undefined} deltaTone="flat"
          onClick={() => setDrawer('health')}
        />
        <KpiCard
          label="首页词（Top10）"
          value={String(top10)} unit="个"
          onClick={() => setDrawer('serp')}
        />
        <KpiCard
          label="关键词池"
          value={poolTotal != null ? fmtInt(poolTotal) : '—'} unit="词"
          delta="双源" deltaTone="flat"
          onClick={() => setDrawer('sweet')}
        />
        <KpiCard
          label="待处理 · 死链"
          value={String(deadLinks)} unit="项"
          delta={deadLinks === 0 ? '健康' : '待修'} deltaTone={deadLinks === 0 ? 'up' : 'down'}
          onClick={() => setDrawer('deadlinks')}
        />
      </div>

      {/* ── KPI 行 2：GA4 占位（PR-D 点亮）── */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(4,1fr)', gap: 12 }}>
        <KpiCard label="活跃用户" value="—" src="GA4" empty delta="未接入" deltaTone="flat" />
        <KpiCard label="自然搜索会话" value="—" src="GA4" empty delta="未接入" deltaTone="flat" />
        <KpiCard label="互动率" value="—" src="GA4" empty delta="未接入" deltaTone="flat" />
        <KpiCard label="关键事件（转化）" value="—" src="GA4" empty delta="未接入" deltaTone="flat" />
      </div>

      {/* ── 主网格 ── */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12, alignItems: 'start' }}>
        {/* 机会词 */}
        <ModuleCard title="机会词 · 甜点区" hint="量≥500 且难度最低" onExpand={() => setDrawer('sweet')}>
          <MiniTable
            head={['关键词', '量/月', 'KD']}
            rows={sweet.slice(0, 5).map(k => [
              <span key="k">{k.keyword}{k.intent ? <span style={{ fontSize: 10, color: 'var(--faint)', marginLeft: 6 }}>{k.intent.split(',')[0]}</span> : null}</span>,
              fmtInt(k.search_volume),
              <KdBadge key="kd" kd={k.difficulty} />,
            ])}
          />
        </ModuleCard>

        {/* 转化词 */}
        <ModuleCard title="转化词追踪" hint={`Transactional · ${transTotal} 词`} onExpand={() => setDrawer('trans')}>
          <MiniTable
            head={['关键词', '量/月', 'KD']}
            rows={trans.slice(0, 5).map(k => [
              k.keyword,
              fmtInt(k.search_volume),
              <KdBadge key="kd" kd={k.difficulty} />,
            ])}
          />
        </ModuleCard>

        {/* SERP 排位 */}
        <ModuleCard title="关键词排位" hint="最近一次刷新" onExpand={() => setDrawer('serp')}>
          <MiniTable
            head={['关键词', '位置']}
            rows={serp.slice(0, 5).map((p: any) => [
              p?.keyword ?? '—',
              <span key="pos" style={{ color: (p?.position ?? 99) <= 10 ? 'var(--ok)' : 'var(--dim)' }}>
                {p?.position != null ? `#${Math.round(p.position)}` : '—'}
              </span>,
            ])}
          />
        </ModuleCard>

        {/* 内容产线 */}
        <ModuleCard title="内容产线" hint="工作流实例" onExpand={() => setDrawer('pipeline')}>
          <div style={{ padding: '6px 0 8px' }}>
            {wf.length === 0 && (
              <div style={{ padding: '18px 14px', textAlign: 'center', color: 'var(--faint)', fontSize: 11 }}>暂无运行中的产线</div>
            )}
            {wf.slice(0, 4).map((w, i) => {
              const st = wfStatus(w.status)
              return (
                <div key={w.id || i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px', fontSize: 11.5 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, padding: '1.5px 7px', borderRadius: 8, flex: 'none', color: st.tone, background: `oklch(from ${st.tone} l c h / .12)` }}>
                    {st.label}
                  </span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text)' }}>
                    {w.name || w.template_name || w.id || '—'}
                  </span>
                </div>
              )
            })}
          </div>
        </ModuleCard>
      </div>

      {/* ── 数据新鲜度底栏 ── */}
      <div style={{ display: 'flex', gap: 16, color: 'var(--faint)', fontSize: 10.5, padding: '2px 4px', flexWrap: 'wrap' }}>
        <span>SERP <b style={{ color: 'var(--dim)', fontWeight: 500 }}>{serp.length ? `${serp.length} 词` : 'DATA_UNAVAILABLE'}</b></span>
        <span>词池 <b style={{ color: 'var(--dim)', fontWeight: 500 }}>{poolTotal != null ? fmtInt(poolTotal) : '—'}</b></span>
        <span>GA4 <b style={{ color: 'var(--dim)', fontWeight: 500 }}>未接入</b></span>
      </div>

      {/* ══ 抽屉们 ══ */}
      <DetailDrawer open={drawer === 'health'} title="综合演化评分 M_t" onClose={() => setDrawer(null)}>
        <DrawerHero value={mt != null ? Number(mt).toFixed(2) : '—'} unit="综合演化评分" />
        <DrawerSection title="历史趋势" hint="最近 30 次评估">
          <div style={{ padding: '10px 13px 6px' }}>
            <MtSpark history={summary?.m_t_history || []} />
          </div>
        </DrawerSection>
        <DrawerSection title="构成">
          <div style={{ padding: '12px 14px 14px', display: 'flex', flexDirection: 'column', gap: 9 }}>
            <HBar label="AEO 可见度 V_t" pct={(summary?.v_t ?? 0) * 100} value={summary?.v_t != null ? `${(summary.v_t * 100).toFixed(0)}%` : '—'} />
            <HBar label="固化技能" pct={Math.min(100, skills * 10)} value={String(skills)} color="oklch(76% .13 297)" />
            <HBar label="死链（越少越好）" pct={Math.min(100, deadLinks * 20)} value={String(deadLinks)} color={deadLinks ? 'var(--bad)' : 'var(--ok)'} />
          </div>
        </DrawerSection>
        <DrawerNote>M_t 由演化引擎按站点技术健康 / 内容 / 收录 / 外链综合打分；历史全量在「监控大屏」。</DrawerNote>
      </DetailDrawer>

      <DetailDrawer open={drawer === 'serp'} title="关键词排位 · 全部" onClose={() => setDrawer(null)}>
        <DrawerHero value={String(top10)} unit={`/ ${serp.length} 词进首页`} />
        <DrawerSection title="全部追踪词">
          <MiniTable
            head={['关键词', '位置']}
            rows={serp.map((p: any) => [
              p?.keyword ?? '—',
              <span key="p" style={{ color: (p?.position ?? 99) <= 10 ? 'var(--ok)' : 'var(--dim)' }}>
                {p?.position != null ? `#${Math.round(p.position)}` : '—'}
              </span>,
            ])}
          />
        </DrawerSection>
        <DrawerNote>排名每 15 天全量刷新（DataForSEO SERP），点「排名追踪」页看历史曲线。</DrawerNote>
      </DetailDrawer>

      <DetailDrawer open={drawer === 'deadlinks'} title="死链与告警" onClose={() => setDrawer(null)}>
        <DrawerHero value={String(deadLinks)} unit="个未修复死链" deltaTone={deadLinks ? 'down' : 'up'} delta={deadLinks ? '待处理' : '健康'} />
        <DrawerNote>死链明细与修复记录在「监控大屏 → SEO 审计」面板；此处为汇总入口。</DrawerNote>
      </DetailDrawer>

      <DetailDrawer open={drawer === 'sweet'} title="机会词 · 甜点区" onClose={() => setDrawer(null)}>
        <DrawerHero value={String(sweet.length)} unit="个高性价比词（量≥500 · 难度升序）" />
        <DrawerSection title="按易做程度排序" hint="KD 越低越先做">
          <MiniTable
            head={['关键词', '量/月', 'KD']}
            rows={sweet.map(k => [
              <span key="k">{k.keyword}{k.intent ? <span style={{ fontSize: 10, color: 'var(--faint)', marginLeft: 6 }}>{k.intent.split(',')[0]}</span> : null}</span>,
              fmtInt(k.search_volume),
              <KdBadge key="kd" kd={k.difficulty} />,
            ])}
          />
        </DrawerSection>
        <DrawerNote>💡 完整词池在「关键词池」页（{poolTotal != null ? fmtInt(poolTotal) : '—'} 词，支持搜索/意图过滤）。</DrawerNote>
      </DetailDrawer>

      <DetailDrawer open={drawer === 'trans'} title={`转化词追踪 · ${transTotal} 词`} onClose={() => setDrawer(null)}>
        <DrawerSection title="Transactional 词（按量排序）">
          <MiniTable
            head={['关键词', '量/月', 'KD']}
            rows={trans.map(k => [k.keyword, fmtInt(k.search_volume), <KdBadge key="kd" kd={k.difficulty} />])}
          />
        </DrawerSection>
        <DrawerNote>💡 转化词是营收主线——低 KD 高量的词优先补落地页与内链。</DrawerNote>
      </DetailDrawer>

      <DetailDrawer open={drawer === 'pipeline'} title="内容产线 · 工作流实例" onClose={() => setDrawer(null)}>
        <DrawerSection title="最近实例">
          <MiniTable
            head={['名称', '状态']}
            rows={wf.map((w, i) => {
              const st = wfStatus(w.status)
              return [
                w.name || w.template_name || w.id || `#${i}`,
                <span key="s" style={{ color: st.tone }}>{st.label}</span>,
              ]
            })}
          />
        </DrawerSection>
        <DrawerNote>编排与节点详情在「工作流」页。</DrawerNote>
      </DetailDrawer>
    </div>
  )
}

/* M_t 历史迷你趋势（SVG 折线，无图表库依赖，不进 vendor-charts） */
function MtSpark({ history }: { history: { ts: number; m_t: number | null }[] }) {
  const pts = history.filter(h => h.m_t != null)
  if (pts.length < 2) return <div style={{ color: 'var(--faint)', fontSize: 11, padding: '12px 0' }}>历史数据不足</div>
  const vals = pts.map(p => p.m_t as number)
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = max - min || 1
  const W = 420, H = 80
  const d = pts.map((p, i) => {
    const x = (i / (pts.length - 1)) * W
    const y = H - 8 - ((p.m_t as number) - min) / span * (H - 20)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} aria-label="M_t 历史趋势">
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2.2" />
    </svg>
  )
}

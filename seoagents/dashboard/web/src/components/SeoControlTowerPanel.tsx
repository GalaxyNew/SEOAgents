import React, { useEffect, useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type DataStatus = 'REAL' | 'DEGRADED' | 'UNAVAILABLE' | 'DISPUTED' | string

type SearchMetrics = {
  clicks: number | null
  impressions: number | null
  ctr: number | null
  position: number | null
} | null

type GaMetrics = {
  sessions: number | null
  users: number | null
  new_users: number | null
  engaged_sessions: number | null
  engagement_rate: number | null
  key_events: number | null
  page_views: number | null
}

type Overview = {
  schema_version: string
  generated_at: string
  site: { hostname: string; site_url: string; market: string; timezone: string }
  gsc: {
    source: string
    data_status: DataStatus
    data_window: string
    known_limitations: string[]
    cross_validation: string
    d0: string
    d1: string
    periods: Record<string, SearchMetrics>
    trend: Array<{ date: string; clicks: number | null; impressions: number | null; position: number | null }>
  }
  ga4: {
    source: string
    data_status: DataStatus
    data_window: string
    known_limitations: string[]
    cross_validation: string
    d0: string
    d1: string
    totals: Record<string, GaMetrics | null>
    organic_7d: GaMetrics | null
    countries: Array<GaMetrics & { country: string }>
    landing_pages: Array<GaMetrics & { path: string }>
    devices: Array<GaMetrics & { device: string }>
  }
  psi: {
    source: string
    data_status: DataStatus
    data_window: string
    known_limitations: string[]
    tested_at: string
    mobile: PsiDevice | null
    desktop: PsiDevice | null
  }
  technical: {
    source: string
    data_status: DataStatus
    data_window: string
    known_limitations: string[]
    robots_status: number | null
    sitemap_status: number | null
    sitemap_urls: number | null
    crawled_urls: number | null
    http_200: number | null
    canonical_conflicts: number | null
    missing_titles: number | null
    missing_descriptions: number | null
    duplicate_title_groups: number | null
    suspected_broken_links: { data_status: DataStatus; source_rows: number; unique_targets: number; reason: string } | null
    indexing: { data_status: DataStatus; indexed_urls: number | null; reason: string }
    content: { data_status: DataStatus; total: number | null; published: number | null; draft: number | null }
  }
  report: {
    data_status: DataStatus
    status: string
    report_date: string
    asset_id: string
    asset_status: string
    feishu_url: string
    feishu_status: string
    gates: Array<{ name: string; status: string }>
  }
  execution: {
    workflow: { data_status: DataStatus; items: WorkflowItem[] }
    timeline: { data_status: DataStatus; items: TimelineItem[] }
  }
  aeo: { data_status: DataStatus }
}

type PsiDevice = {
  data_status: DataStatus
  performance: number | null
  fcp_ms: number | null
  lcp_ms: number | null
  cls: number | null
  tbt_ms: number | null
  speed_index_ms: number | null
  payload_kb: number | null
  request_count: number | null
  run_count: number
  unique_fetch_times: number
  high_variance: boolean
}

type WorkflowItem = {
  instance_id: string
  template_id: string
  name: string
  system_status: string
  business_status: string
  completed_nodes: number
  total_nodes: number
  current_node: string
  hermes_run_id: string
  runtime_status: string
  evidence_present: boolean
  updated_at: string
}

type TimelineItem = {
  node_id: string
  kind: string
  state: string
  intent: string
  scheduled_at: string
  runtime_state: string
  hermes_run_id: string
}

const C = {
  bg: '#06101e', panel: '#0d192b', panel2: '#101e33', line: '#20324c', text: '#eaf2ff', muted: '#8296b0',
  blue: '#4b8dff', cyan: '#22d3ee', green: '#2dd4a6', yellow: '#f5c451', red: '#ff6577', purple: '#a78bfa',
}

const COUNTRY_POINTS: Record<string, { x: number; y: number; label: string }> = {
  'United States': { x: 22, y: 38, label: '美国' },
  Singapore: { x: 77, y: 66, label: '新加坡' },
  Japan: { x: 86, y: 42, label: '日本' },
  Belarus: { x: 58, y: 30, label: '白俄罗斯' },
  China: { x: 75, y: 42, label: '中国' },
  Netherlands: { x: 50, y: 29, label: '荷兰' },
}

const WORLD_PATHS = [
  'M70 68 L130 35 210 42 245 78 212 112 165 115 132 150 104 134 88 98 Z',
  'M205 154 L240 170 250 234 218 294 190 258 198 208 179 175 Z',
  'M315 56 L360 40 389 64 375 95 340 102 318 84 Z',
  'M350 110 L408 96 453 119 447 164 418 185 401 245 370 226 357 173 333 143 Z',
  'M420 64 L514 38 622 56 684 91 666 130 610 127 570 161 515 153 485 126 438 119 Z',
  'M623 208 L684 206 718 238 690 268 638 263 610 235 Z',
]

function statusColor(status: DataStatus) {
  if (status === 'REAL' || status === 'COMPLETE') return C.green
  if (status === 'DEGRADED' || status === 'COMPLETE_WITH_DEGRADED' || status === 'COMPLETE_WITH_UNAVAILABLE') return C.yellow
  if (status === 'DISPUTED' || status === 'BLOCKED') return C.red
  return C.muted
}

function Badge({ status }: { status: DataStatus }) {
  const color = statusColor(status)
  return <span style={{ color, border: `1px solid ${color}77`, background: `${color}13`, padding: '3px 7px', borderRadius: 99, fontSize: 9, fontWeight: 800 }}>{status}</span>
}

function Panel({ title, subtitle, status, children, id }: { title: string; subtitle?: string; status?: DataStatus; children: React.ReactNode; id?: string }) {
  return <section id={id} style={{ background: `linear-gradient(155deg,${C.panel2},${C.panel})`, border: `1px solid ${C.line}`, borderRadius: 13, padding: 14, minWidth: 0, boxShadow: '0 12px 28px #0004' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
      <div><div style={{ fontSize: 14, fontWeight: 850 }}>{title}</div>{subtitle && <div style={{ color: C.muted, fontSize: 10, marginTop: 2 }}>{subtitle}</div>}</div>
      {status && <Badge status={status} />}
    </div>
    {children}
  </section>
}

function Kpi({ label, value, detail, color }: { label: string; value: React.ReactNode; detail: string; color: string }) {
  return <article style={{ background: `linear-gradient(155deg,${C.panel2},${C.panel})`, border: `1px solid ${C.line}`, borderRadius: 13, padding: '11px 13px', borderTop: `2px solid ${color}` }}>
    <div style={{ color: C.muted, fontSize: 10 }}>{label}</div>
    <strong style={{ display: 'block', fontSize: 23, margin: '3px 0', letterSpacing: '-.5px' }}>{value}</strong>
    <small style={{ color, fontSize: 10 }}>{detail}</small>
  </article>
}

const formatNumber = (value: number | null | undefined, digits = 0) => value == null ? 'DATA_UNAVAILABLE' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const formatPct = (value: number | null | undefined) => value == null ? 'DATA_UNAVAILABLE' : `${(value * 100).toFixed(1)}%`
const formatMs = (value: number | null | undefined) => value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`

function deltaText(current: number | null | undefined, previous: number | null | undefined, lowerBetter = false) {
  if (current == null || previous == null || previous === 0) return '对照窗口不可用'
  const delta = ((current - previous) / previous) * 100
  const good = lowerBetter ? delta < 0 : delta > 0
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}% · ${good ? '改善' : '观察'}`
}

function SourceNote({ source, window, limitations }: { source: string; window: string; limitations: string[] }) {
  return <div style={{ marginTop: 10, paddingTop: 8, borderTop: `1px solid ${C.line}`, color: C.muted, fontSize: 9, lineHeight: 1.55 }}>
    【数据来源】{source}　【数据窗口】{window || 'UNAVAILABLE'}<br />
    【已知局限】{limitations.join('；')}
  </div>
}

function TrendTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return <div style={{ background: '#071120f2', border: `1px solid ${C.blue}`, borderRadius: 8, padding: '8px 10px', color: C.text, fontSize: 10 }}>
    <b style={{ color: C.blue }}>{row.date}</b><br />
    自然点击 {formatNumber(row.clicks)}<br />展示 {formatNumber(row.impressions)}<br />加权排名 {row.position == null ? '—（零展现）' : `P${row.position.toFixed(1)}`}
  </div>
}

function GscTrend({ data }: { data: Overview['gsc'] }) {
  const [lockedDate, setLockedDate] = useState<string>('')
  const locked = data.trend.find(row => row.date === lockedDate)
  return <Panel title="GSC 点击 / 展示 / 加权排名趋势" subtitle="双轴 · 零展现排名断开 · 点击图中日期可锁定/解锁" status={data.data_status}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap', minHeight: 25 }}>
      <select value={lockedDate} onChange={event => setLockedDate(event.target.value)} style={{ background: '#0a1627', color: C.text, border: `1px solid ${C.line}`, borderRadius: 6, padding: '4px 7px', fontSize: 10 }}>
        <option value="">全周期 · 点击或选择锁定单日</option>
        {data.trend.map(row => <option key={row.date} value={row.date}>{row.date} · {row.clicks} 点击 / {row.impressions} 展示</option>)}
      </select>
      {locked && <button onClick={() => setLockedDate('')} style={{ background: C.blue, color: '#fff', border: 0, borderRadius: 6, padding: '4px 8px', cursor: 'pointer', fontSize: 10 }}>✕ 解锁 {locked.date}</button>}
    </div>
    <div style={{ width: '100%', height: 310, marginTop: 4 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data.trend} onClick={(state: any) => {
          const date = state?.activePayload?.[0]?.payload?.date || state?.activeLabel
          if (date) setLockedDate((old) => old === date ? '' : date)
        }} margin={{ top: 15, right: 15, left: -24, bottom: 0 }}>
          <defs><linearGradient id="towerImpressions" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={C.yellow} stopOpacity={.35} /><stop offset="95%" stopColor={C.yellow} stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke={C.line} />
          <XAxis dataKey="date" stroke={C.muted} fontSize={9} tickFormatter={(v) => String(v).slice(5)} interval="preserveStartEnd" />
          <YAxis yAxisId="left" stroke={C.muted} fontSize={9} />
          <YAxis yAxisId="right" orientation="right" reversed domain={[1, 'auto']} stroke={C.purple} fontSize={9} />
          <Tooltip content={<TrendTooltip />} /><Legend wrapperStyle={{ fontSize: 9 }} />
          <Area yAxisId="left" type="monotone" dataKey="impressions" name="GSC 展示" stroke={C.yellow} fill="url(#towerImpressions)" strokeWidth={2} />
          <Line yAxisId="left" type="monotone" dataKey="clicks" name="GSC 自然点击" stroke={C.blue} strokeWidth={2.4} dot={{ r: 2.5 }} activeDot={{ r: 6 }} />
          <Line yAxisId="right" type="monotone" dataKey="position" name="GSC 加权排名" stroke={C.purple} strokeWidth={2} strokeDasharray="4 4" connectNulls={false} dot={{ r: 2.5 }} />
          {lockedDate && <ReferenceLine yAxisId="left" x={lockedDate} stroke={C.blue} strokeWidth={2} strokeDasharray="4 4" />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    {locked && <div style={{ background: '#0a1627', border: `1px solid ${C.blue}55`, borderRadius: 8, padding: 8, fontSize: 10 }}>锁定 {locked.date}：<b>{formatNumber(locked.clicks)}</b> 点击 · <b>{formatNumber(locked.impressions)}</b> 展示 · <b>{locked.position == null ? '排名无定义' : `P${locked.position.toFixed(1)}`}</b></div>}
    <SourceNote source={data.source} window={data.data_window} limitations={data.known_limitations} />
  </Panel>
}

function Ga4WorldMap({ data }: { data: Overview['ga4'] }) {
  const maxSessions = Math.max(1, ...data.countries.map(row => row.sessions || 0))
  const [selected, setSelected] = useState<string>(data.countries[0]?.country || '')
  const selectedRow = data.countries.find(row => row.country === selected)
  return <Panel title="GA4 世界来访地图" subtitle="国家标签 = GA4 全站 sessions / users，不是 GSC 国家点击" status={data.data_status}>
    <div style={{ position: 'relative', minHeight: 305, background: 'radial-gradient(circle at center,#102a47,#07121f 70%)', border: `1px solid ${C.line}`, borderRadius: 10, overflow: 'hidden' }}>
      <svg viewBox="0 0 760 320" role="img" aria-label="GA4 visitor world map" style={{ width: '100%', height: 'auto', display: 'block' }}>
        <defs><pattern id="towerGrid" width="38" height="32" patternUnits="userSpaceOnUse"><path d="M38 0H0V32" fill="none" stroke="#27415e" strokeWidth=".5" opacity=".45" /></pattern></defs>
        <rect width="760" height="320" fill="url(#towerGrid)" />
        {WORLD_PATHS.map((path, index) => <path key={index} d={path} fill="#183451" stroke="#31577d" strokeWidth="1.2" />)}
        {data.countries.map((country, index) => {
          const point = COUNTRY_POINTS[country.country]
          if (!point) return null
          const r = 5 + ((country.sessions || 0) / maxSessions) * 10
          const cx = point.x * 7.6
          const cy = point.y * 3.2
          const active = selected === country.country
          return <g key={country.country} onClick={() => setSelected(country.country)} style={{ cursor: 'pointer' }}>
            <circle cx={cx} cy={cy} r={r + 6} fill={C.cyan} opacity={.08} />
            <circle cx={cx} cy={cy} r={r} fill={active ? C.yellow : C.cyan} opacity={.85} stroke="#fff" strokeWidth={active ? 1.8 : .7} />
            <text x={cx + r + 5} y={cy - 3} fill="#eaf2ff" fontSize="11" fontWeight="700">{point.label}</text>
            <text x={cx + r + 5} y={cy + 10} fill="#93a9c3" fontSize="9">{country.sessions ?? '—'} sessions</text>
          </g>
        })}
      </svg>
      {data.countries.some(row => !COUNTRY_POINTS[row.country]) && <div style={{ position: 'absolute', left: 8, bottom: 8, fontSize: 9, color: C.muted }}>未定位：{data.countries.filter(row => !COUNTRY_POINTS[row.country]).map(row => `${row.country} ${row.sessions ?? '—'}`).join(' · ')}</div>}
    </div>
    {selectedRow && <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6 }}>
      {[['国家', selectedRow.country], ['会话', formatNumber(selectedRow.sessions)], ['用户', formatNumber(selectedRow.users)], ['参与率', formatPct(selectedRow.engagement_rate)]].map(([label, value]) => <div key={label} style={{ background: '#0a1627', border: `1px solid ${C.line}`, borderRadius: 8, padding: 8 }}><div style={{ color: C.muted, fontSize: 9 }}>{label}</div><b style={{ fontSize: 12 }}>{value}</b></div>)}
    </div>}
    <SourceNote source={data.source} window={data.data_window} limitations={data.known_limitations} />
  </Panel>
}

function MetricTable({ rows }: { rows: Array<[string, React.ReactNode, React.ReactNode?]> }) {
  return <div>{rows.map(([name, value, extra]) => <div key={name} style={{ display: 'grid', gridTemplateColumns: 'minmax(110px,1fr) auto auto', gap: 8, alignItems: 'center', borderTop: `1px solid ${C.line}`, padding: '7px 0', fontSize: 10 }}><span style={{ color: C.muted }}>{name}</span><b>{value}</b>{extra && <span>{extra}</span>}</div>)}</div>
}

function PsiCard({ label, device }: { label: string; device: PsiDevice | null }) {
  if (!device) return <div style={{ color: C.muted }}>DATA_UNAVAILABLE</div>
  return <div style={{ background: '#0a1627', border: `1px solid ${C.line}`, borderRadius: 10, padding: 11 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><b>{label}</b><Badge status={device.data_status} /></div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '9px 0' }}><div style={{ width: 58, height: 58, borderRadius: '50%', display: 'grid', placeItems: 'center', background: '#091523', border: `6px solid ${(device.performance || 0) >= 90 ? C.green : C.yellow}`, fontSize: 20, fontWeight: 900 }}>{device.performance ?? '—'}</div><div style={{ fontSize: 9, color: C.muted }}>Lighthouse 实验室分数<br />{device.run_count} 次记录 / {device.unique_fetch_times} 个 fetchTime</div></div>
    <MetricTable rows={[["FCP", formatMs(device.fcp_ms)], ["LCP", formatMs(device.lcp_ms), device.lcp_ms != null && device.lcp_ms > 4000 ? <Badge status="DEGRADED" /> : undefined], ["CLS", formatNumber(device.cls, 3)], ["TBT（非 INP）", formatMs(device.tbt_ms)], ["载荷", device.payload_kb == null ? '—' : `${device.payload_kb} KB`]]} />
  </div>
}

export function SeoControlTowerPanel() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/public/seo-control-tower/overview', { headers: { Accept: 'application/json' } })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const body = await response.json() as Overview
      if (body.schema_version !== 'seo-control-tower.public.v2') throw new Error('公开聚合协议不兼容')
      setData(body)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '公开聚合加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const workflowItems = data?.execution.workflow.items || []
  const timelineItems = data?.execution.timeline.items || []
  const latestTimeline = useMemo(() => timelineItems.slice(0, 5), [timelineItems])

  if (loading && !data) return <div style={{ minHeight: '60vh', display: 'grid', placeItems: 'center', color: C.muted }}>正在加载安全公开聚合…</div>
  if (!data) return <div style={{ padding: 24, color: C.red }}>SEO 总控大屏不可用：{error || 'DATA_UNAVAILABLE'} <button onClick={load}>重试</button></div>

  const g0 = data.gsc.periods.d0
  const g1 = data.gsc.periods.d1
  const g7 = data.gsc.periods.cur7
  const gp7 = data.gsc.periods.prev7
  const ga0 = data.ga4.totals.d0
  const ga1 = data.ga4.totals.d1
  const ga7 = data.ga4.totals.cur7
  const mobile = data.psi.mobile

  return <div style={{ minHeight: '100%', background: C.bg, color: C.text, padding: '14px 16px 28px', fontFamily: 'Inter,system-ui,-apple-system,sans-serif', overflowY: 'auto' }}>
    <div style={{ maxWidth: 1720, margin: '0 auto' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div><h2 style={{ margin: 0, fontSize: 20 }}>SEO 总控大屏 V2</h2><div style={{ color: C.muted, fontSize: 10 }}>{data.site.hostname} · {data.site.market} · 搜索 × 行为 × 体验 × 执行</div></div>
        <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
          <span style={{ border: `1px solid ${C.line}`, padding: '6px 9px', borderRadius: 8, fontSize: 10 }}>GSC_D0 {data.gsc.d0 || 'UNAVAILABLE'}</span>
          <span style={{ border: `1px solid ${C.line}`, padding: '6px 9px', borderRadius: 8, fontSize: 10 }}>GA4_D0 {data.ga4.d0 || 'UNAVAILABLE'}</span>
          <span style={{ border: `1px solid ${C.line}`, padding: '6px 9px', borderRadius: 8, fontSize: 10 }}>PSI {data.psi.tested_at ? data.psi.tested_at.slice(0, 16).replace('T', ' ') : 'UNAVAILABLE'}</span>
          <button onClick={load} disabled={loading} style={{ background: C.blue, color: '#fff', border: 0, borderRadius: 8, padding: '6px 10px', cursor: loading ? 'wait' : 'pointer' }}>{loading ? '刷新中…' : '↻ 刷新'}</button>
        </div>
      </header>

      {error && <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 9500, color: C.yellow, border: `1px solid ${C.yellow}55`, borderRadius: 8, padding: '8px 14px', background: 'rgba(20,20,30,.9)', boxShadow: '0 8px 24px rgba(0,0,0,.4)', maxWidth: 'calc(100vw - 32px)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', backdropFilter: 'blur(8px)' }}>⚠ 刷新失败，保留旧数据</div>}

      <div className="tower-kpi-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(0,1fr))', gap: 10 }}>
        <Kpi label={`GSC 自然点击 · D0 ${data.gsc.d0}`} value={formatNumber(g0?.clicks)} detail={deltaText(g0?.clicks, g1?.clicks)} color={C.blue} />
        <Kpi label={`GSC 展示 · D0 ${data.gsc.d0}`} value={formatNumber(g0?.impressions)} detail={deltaText(g0?.impressions, g1?.impressions)} color={C.yellow} />
        <Kpi label="GSC 加权排名（非实测 SERP）" value={g0?.position == null ? 'DATA_UNAVAILABLE' : `P${g0.position.toFixed(1)}`} detail={g1?.position == null ? 'D-1 不可用' : `D-1 P${g1.position.toFixed(1)}`} color={C.purple} />
        <Kpi label={`GA4 全站会话 · D0 ${data.ga4.d0}`} value={formatNumber(ga0?.sessions)} detail={deltaText(ga0?.sessions, ga1?.sessions)} color={C.cyan} />
        <Kpi label="GA4 近7日 Organic 会话" value={formatNumber(data.ga4.organic_7d?.sessions)} detail={`参与率 ${formatPct(data.ga4.organic_7d?.engagement_rate)}`} color={C.green} />
        <Kpi label="PSI Mobile · Lighthouse" value={formatNumber(mobile?.performance)} detail={`LCP ${formatMs(mobile?.lcp_ms)}`} color={C.red} />
      </div>

      <div className="tower-split" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 10, marginTop: 10 }}>
        <GscTrend data={data.gsc} />
        <Ga4WorldMap data={data.ga4} />
      </div>

      <div className="tower-three" style={{ display: 'grid', gridTemplateColumns: '1fr 1.12fr .92fr', gap: 10, marginTop: 10 }}>
        <Panel title="GSC 周期对照" subtitle="GSC 与 GA4 不合并为“总流量”" status={data.gsc.data_status}>
          <MetricTable rows={[
            ['近7日点击', formatNumber(g7?.clicks), <span style={{ color: C.red }}>{deltaText(g7?.clicks, gp7?.clicks)}</span>],
            ['近7日展示', formatNumber(g7?.impressions), <span style={{ color: C.red }}>{deltaText(g7?.impressions, gp7?.impressions)}</span>],
            ['近7日 CTR', formatPct(g7?.ctr)],
            ['近30日点击', formatNumber(data.gsc.periods.cur30?.clicks)],
            ['前30日点击', formatNumber(data.gsc.periods.prev30?.clicks)],
          ]} />
          <SourceNote source={data.gsc.source} window={data.gsc.data_window} limitations={data.gsc.known_limitations} />
        </Panel>
        <Panel title="GA4 用户行为" subtitle="全站 totals / Organic Search 分层展示" status={data.ga4.data_status}>
          <MetricTable rows={[
            ['近7日全站 Sessions', formatNumber(ga7?.sessions)],
            ['近7日 Users', formatNumber(ga7?.users)],
            ['近7日 Engaged Sessions', formatNumber(ga7?.engaged_sessions)],
            ['全站参与率', formatPct(ga7?.engagement_rate)],
            ['Organic Sessions', formatNumber(data.ga4.organic_7d?.sessions)],
            ['Organic 参与率', formatPct(data.ga4.organic_7d?.engagement_rate)],
            ['Key Events', formatNumber(ga7?.key_events)],
          ]} />
          <SourceNote source={data.ga4.source} window={data.ga4.data_window} limitations={data.ga4.known_limitations} />
        </Panel>
        <Panel title="数据新鲜度 / 可用性" subtitle="来源日期各自独立" status="REAL">
          <MetricTable rows={[
            ['GSC_D0', data.gsc.d0 || 'UNAVAILABLE', <Badge status={data.gsc.data_status} />],
            ['GA4_D0', data.ga4.d0 || 'UNAVAILABLE', <Badge status={data.ga4.data_status} />],
            ['PSI', data.psi.tested_at ? data.psi.tested_at.slice(0, 10) : 'UNAVAILABLE', <Badge status={data.psi.data_status} />],
            ['技术 / crawl', data.technical.data_window ? data.technical.data_window.slice(0, 10) : 'UNAVAILABLE', <Badge status={data.technical.data_status} />],
            ['AEO', '未配置真实探测器', <Badge status={data.aeo.data_status} />],
          ]} />
        </Panel>
      </div>

      <div className="tower-split" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
        <Panel title="PageSpeed / Core Web Vitals" subtitle="Lighthouse lab；CrUX/INP 不可用时不补零" status={data.psi.data_status} id="experience">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}><PsiCard label="Mobile" device={data.psi.mobile} /><PsiCard label="Desktop" device={data.psi.desktop} /></div>
          <SourceNote source={data.psi.source} window={data.psi.data_window} limitations={data.psi.known_limitations} />
        </Panel>
        <Panel title="技术 / 收录 / 内容健康" subtitle="sitemap 不等于已索引" status={data.technical.data_status} id="technical">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 7 }}>
            {[
              ['HTTP 200', `${formatNumber(data.technical.http_200)} / ${formatNumber(data.technical.crawled_urls)}`],
              ['Sitemap URL', formatNumber(data.technical.sitemap_urls)],
              ['Canonical 冲突', formatNumber(data.technical.canonical_conflicts)],
              ['缺失 Title', formatNumber(data.technical.missing_titles)],
              ['重复 Title 组', formatNumber(data.technical.duplicate_title_groups)],
              ['Published / Draft', `${formatNumber(data.technical.content.published)} / ${formatNumber(data.technical.content.draft)}`],
            ].map(([label, value]) => <div key={label} style={{ background: '#0a1627', border: `1px solid ${C.line}`, borderRadius: 8, padding: 9 }}><div style={{ color: C.muted, fontSize: 9 }}>{label}</div><b style={{ fontSize: 14 }}>{value}</b></div>)}
          </div>
          <div style={{ marginTop: 8, padding: 8, borderRadius: 8, background: `${C.yellow}12`, border: `1px solid ${C.yellow}55`, fontSize: 10 }}><Badge status={data.technical.indexing.data_status} />　收录：{data.technical.indexing.reason}</div>
          {data.technical.suspected_broken_links && <div style={{ marginTop: 8, padding: 8, borderRadius: 8, background: `${C.red}10`, border: `1px solid ${C.red}55`, fontSize: 10 }}><Badge status={data.technical.suspected_broken_links.data_status} />　疑似断链来源 {data.technical.suspected_broken_links.source_rows}，唯一目标 {data.technical.suspected_broken_links.unique_targets}；{data.technical.suspected_broken_links.reason}</div>}
          <SourceNote source={data.technical.source} window={data.technical.data_window} limitations={data.technical.known_limitations} />
        </Panel>
      </div>

      <div className="tower-split" style={{ display: 'grid', gridTemplateColumns: '.92fr 1.48fr', gap: 10, marginTop: 10 }}>
        <Panel title="今日巡检报告" subtitle={`${data.report.report_date} · 完成不等于所有探针可用`} status={data.report.status} id="report">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 6 }}>
            {data.report.gates.map(gate => <div key={gate.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, borderTop: `1px solid ${C.line}`, padding: '7px 0', fontSize: 10 }}><span>{gate.name}</span><Badge status={gate.status} /></div>)}
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <a href={data.report.feishu_url} target="_blank" rel="noreferrer" style={{ color: '#fff', background: C.blue, textDecoration: 'none', padding: '7px 10px', borderRadius: 7, fontSize: 10 }}>打开飞书巡检报告 ↗</a>
            <span title={data.report.asset_id} style={{ border: `1px solid ${C.line}`, padding: '7px 10px', borderRadius: 7, fontSize: 10, color: C.green }}>Asset Hub：{data.report.asset_status}</span>
          </div>
          <div style={{ marginTop: 8, color: C.muted, fontSize: 9, wordBreak: 'break-all' }}>asset_id: {data.report.asset_id}</div>
        </Panel>

        <Panel title="Workflow / Timeline 真实进度" subtitle="系统状态、Hermes 进程与业务证据分开" status={data.execution.workflow.data_status} id="execution">
          {workflowItems.length === 0 ? <div style={{ color: C.muted }}>Workflow DATA_UNAVAILABLE</div> : workflowItems.map(item => <div key={item.instance_id} style={{ background: '#0a1627', border: `1px solid ${C.line}`, borderRadius: 9, padding: 10, marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}><div><b>{item.name}</b><div style={{ color: C.muted, fontFamily: 'monospace', fontSize: 9 }}>{item.instance_id}</div></div><div style={{ display: 'flex', gap: 5 }}><Badge status={item.system_status} /><Badge status={item.business_status} /></div></div>
            <div style={{ height: 5, background: '#192a42', borderRadius: 4, margin: '8px 0', overflow: 'hidden' }}><div style={{ width: `${item.total_nodes ? (item.completed_nodes / item.total_nodes) * 100 : 0}%`, height: '100%', background: item.business_status === 'BLOCKED' ? C.red : C.blue }} /></div>
            <div style={{ color: C.muted, fontSize: 9 }}>节点 {item.completed_nodes}/{item.total_nodes} · 当前 {item.current_node || '—'} · Hermes {item.hermes_run_id || '—'} {item.runtime_status || ''} · 业务证据 {item.evidence_present ? '有' : '待确认'}</div>
          </div>)}
          <div style={{ marginTop: 6, color: C.muted, fontSize: 10, fontWeight: 700 }}>Timeline · 固定站点只读投影</div>
          {latestTimeline.length === 0 ? <div style={{ color: C.muted, fontSize: 10, marginTop: 5 }}>无匹配站点的公开 Timeline 项</div> : latestTimeline.map(item => <div key={item.node_id} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 7, borderTop: `1px solid ${C.line}`, padding: '7px 0', fontSize: 9 }}><div><b>{item.intent}</b><div style={{ color: C.muted }}>{item.node_id} · {item.scheduled_at}</div></div><Badge status={item.runtime_state || item.state} /></div>)}
        </Panel>
      </div>

      <footer style={{ color: C.muted, fontSize: 9, marginTop: 10, textAlign: 'center' }}>公开只读固定站点聚合 · 不含凭证、配置、原始用户级 GA4、写接口或内部异常堆栈 · 生成于 {data.generated_at}</footer>
    </div>
    <style>{`
      @media(max-width:1100px){.tower-kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}.tower-three{grid-template-columns:1fr!important}}
      @media(max-width:760px){.tower-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.tower-split{grid-template-columns:1fr!important}}
      @media(max-width:480px){.tower-kpi-grid{grid-template-columns:1fr!important}}
    `}</style>
  </div>
}

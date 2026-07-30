import React, { useEffect, useState } from 'react'
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts'

export interface MonitoredSite {
  site_url: string
  gsc_property: string
  brand_name: string
  tracked_keywords: string[]
}

export interface GscOverviewPanelProps {
  monitoredSites?: MonitoredSite[]
  onSelectSite?: (site: MonitoredSite) => void
}

interface GscData {
  site_url: string
  domain_name: string
  gsc_property: string
  date_range: string
  single_date?: string | null
  range_type: string
  last_synced: string
  freshness?: string
  is_real_gsc?: boolean
  sample_status?: string
  zero_impression_days?: number
  summary: {
    clicks: { value: number; change: string; is_down: boolean }
    impressions: { value: number; change: string; is_down: boolean }
    ctr: { value: string; change: string; is_down: boolean }
    avg_position: { value: number | string; change: string; is_up: boolean }
  }
  trend_series: Array<{ date: string; full_date?: string; clicks: number; impressions: number; position: number | null; filled?: boolean }>
  top_keywords: Array<{ keyword: string; is_new: boolean; clicks: number; delta_clicks: string; impressions: number; ctr: string; position: number; delta_position: string }>
  landing_pages: Array<{ path: string; clicks: number; delta: string; impressions: number; ctr: string; position: number }>
  countries: Array<{ code: string; name: string; clicks: number; ctr: string }>
  footer_status?: {
    tasks_summary: string
    datasource: string
  }
}

// Custom Interactive Dark Mode Chart Tooltip
const CustomChartTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const item = payload[0].payload
    return (
      <div
        style={{
          background: 'rgba(15, 23, 42, 0.95)',
          border: '1px solid #3b82f6',
          borderRadius: 8,
          padding: '8px 12px',
          fontSize: 11,
          color: '#f8fafc',
          boxShadow: '0 8px 20px rgba(0,0,0,0.6)',
        }}
      >
        <div style={{ fontWeight: 700, color: '#60a5fa', marginBottom: 4 }}>
          📅 {item.full_date || label} (点击可锁定/查看当天全量数据)
        </div>
        <div style={{ color: '#3b82f6', fontWeight: 600 }}>🖱️ 自然点击: {item.clicks}</div>
        <div style={{ color: '#eab308', fontWeight: 600 }}>👁️ 展示量: {item.impressions}</div>
        <div style={{ color: '#c084fc', fontWeight: 600 }}>
          📍 平均排名: {item.position !== null ? `P${item.position}` : '— (零展现)'}
        </div>
      </div>
    )
  }
  return null
}

export const GscOverviewPanel: React.FC<GscOverviewPanelProps> = ({ monitoredSites = [], onSelectSite }) => {
  const [selectedSiteUrl, setSelectedSiteUrl] = useState<string>('')
  const [rangeType, setRangeType] = useState<string>('7d')
  const [selectedSingleDate, setSelectedSingleDate] = useState<string | null>(null)
  const [kwFilter, setKwFilter] = useState<'all' | 'non_brand' | 'rising' | 'falling'>('all')
  const [loading, setLoading] = useState<boolean>(true)
  const [data, setData] = useState<GscData | null>(null)
  const [nowStr, setNowStr] = useState<string>('')

  // Modal Expand State ('keywords' | 'pages' | 'countries' | null)
  const [modalType, setModalType] = useState<'keywords' | 'pages' | 'countries' | null>(null)

  // Live clock
  useEffect(() => {
    const updateTime = () => {
      const d = new Date()
      setNowStr(d.toLocaleString('zh-CN', { hour12: false }))
    }
    updateTime()
    const timer = setInterval(updateTime, 1000)
    return () => clearInterval(timer)
  }, [])

  // Fetch GSC data dynamically whenever site, range, or selected single date changes
  const loadData = async (siteUrl?: string, range: string = '7d', singleDate: string | null = null) => {
    setLoading(true)
    try {
      const url = `/api/gsc/overview?range=${range}${siteUrl ? `&site_url=${encodeURIComponent(siteUrl)}` : ''}${singleDate ? `&single_date=${encodeURIComponent(singleDate)}` : ''}`
      const res = await fetch(url)
      const json = await res.json()
      if (json.ok) {
        setData(json)
        if (!selectedSiteUrl && json.site_url) {
          setSelectedSiteUrl(json.site_url)
        }
      }
    } catch (e) {
      console.warn('Failed to load GSC overview data', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData(selectedSiteUrl, rangeType, selectedSingleDate)
  }, [selectedSiteUrl, rangeType])

  const handleSiteChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value
    setSelectedSiteUrl(val)
    loadData(val, rangeType, selectedSingleDate)
    const match = monitoredSites.find(s => s.site_url === val)
    if (match && onSelectSite) {
      onSelectSite(match)
    }
  }

  const handleRangeChange = (r: string) => {
    setRangeType(r)
    setSelectedSingleDate(null)
    loadData(selectedSiteUrl, r, null)
  }

  const handleChartClick = (chartState: any) => {
    if (!chartState) return
    let clickedDate: string | null = null
    if (chartState.activePayload && chartState.activePayload.length > 0) {
      clickedDate = chartState.activePayload[0].payload.full_date || chartState.activePayload[0].payload.date
    } else if (chartState.activeLabel) {
      clickedDate = chartState.activeLabel
    }
    if (clickedDate) {
      const match = series.find(s => s.date === clickedDate || s.full_date === clickedDate)
      const fullDateToUse = match?.full_date || clickedDate
      const newSingleDate = selectedSingleDate === fullDateToUse ? null : fullDateToUse
      setSelectedSingleDate(newSingleDate)
      loadData(selectedSiteUrl, rangeType, newSingleDate)
    }
  }

  if (loading && !data) {
    return (
      <div style={{ background: '#0b0f19', borderRadius: 12, padding: 24, textAlign: 'center', color: '#9ca3af' }}>
        🔄 正在计算全屏 GSC 视图...
      </div>
    )
  }

  const summary = data?.summary || {
    clicks: { value: 0, change: '-100%', is_down: true },
    impressions: { value: 9, change: '-31%', is_down: true },
    ctr: { value: '0.0%', change: '-100%', is_down: true },
    avg_position: { value: 43.8, change: '+76%', is_up: true },
  }

  const series = data?.trend_series || []
  const isInsufficient = data?.sample_status === 'INSUFFICIENT_DATA'
  const zeroDaysCount = data?.zero_impression_days ?? series.filter(s => s.impressions === 0).length

  // Calculate short date key for ReferenceLine rendering
  let shortSelectedDateKey = ''
  if (selectedSingleDate) {
    const match = series.find(s => s.full_date === selectedSingleDate || s.date === selectedSingleDate)
    if (match) {
      shortSelectedDateKey = match.date
    } else if (selectedSingleDate.length === 10) {
      shortSelectedDateKey = selectedSingleDate.substring(5)
    } else {
      shortSelectedDateKey = selectedSingleDate
    }
  }

  return (
    <div
      className="gsc-panel-container"
      style={{
        background: '#090d16',
        color: '#e5e7eb',
        borderRadius: 14,
        padding: '12px 16px',
        border: '1px solid #1e293b',
        position: 'relative',
        height: '100%',
        maxHeight: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        overflow: 'hidden',
        boxSizing: 'border-box',
      }}
    >
      {/* Top Bar Navigation & Filters */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 8, flexShrink: 0 }}>
        {/* Title & Site Switcher */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h2 style={{ fontSize: 17, fontWeight: 800, color: '#f8fafc', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
            📊 SEO 数据大屏
          </h2>

          <select
            value={selectedSiteUrl || data?.site_url || ''}
            onChange={handleSiteChange}
            style={{
              background: '#1e293b',
              color: '#f8fafc',
              border: '1px solid #334155',
              borderRadius: 6,
              padding: '3px 8px',
              fontSize: 13,
              fontWeight: 600,
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            {monitoredSites.length > 0 ? (
              monitoredSites.map(s => (
                <option key={s.site_url} value={s.site_url}>
                  {s.site_url.replace('https://', '').replace('http://', '')} ({s.brand_name || '主站'})
                </option>
              ))
            ) : (
              <option value={data?.site_url || ''}>{data?.domain_name || 'mejorsiptv.shop'}</option>
            )}
          </select>

          {isInsufficient && (
            <span
              style={{
                background: '#7c2d12',
                color: '#ff8c00',
                border: '1px solid #c2410c',
                padding: '2px 8px',
                borderRadius: 10,
                fontSize: 10,
                fontWeight: 700,
              }}
              title="样本不足 (<10次展现)，不可用于直接优化决策"
            >
              ⚠️ INSUFFICIENT_DATA
            </span>
          )}
        </div>

        {/* Time Range Switcher Pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, background: '#1e293b', padding: 2, borderRadius: 6 }}>
          {['24h', '7d', '30d', '3m'].map((r) => {
            const labelMap: Record<string, string> = { '24h': '24小时', '7d': '7日', '30d': '30日', '3m': '3个月' }
            const active = rangeType === r
            return (
              <button
                key={r}
                onClick={() => handleRangeChange(r)}
                style={{
                  background: active ? '#3b82f6' : 'transparent',
                  color: active ? '#fff' : '#94a3b8',
                  border: 0,
                  borderRadius: 4,
                  padding: '3px 10px',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  boxShadow: active ? '0 2px 6px rgba(59,130,246,0.4)' : 'none',
                }}
              >
                {labelMap[r]}
              </button>
            )
          })}
        </div>

        {/* Status Indicators & Refresh */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
          <span
            style={{
              background: data?.is_real_gsc ? '#064e3b' : '#78350f',
              color: data?.is_real_gsc ? '#34d399' : '#fbbf24',
              padding: '2px 8px',
              borderRadius: 10,
              border: `1px solid ${data?.is_real_gsc ? '#059669' : '#d97706'}`,
              fontWeight: 600,
              cursor: 'help',
            }}
            title={
              data?.is_real_gsc
                ? '已成功对接 Google Search Console 官方实时 API 数据'
                : '需在 Google Search Console Web 后台 (search.google.com/search-console) 将 Service Account 邮箱: igoriptv2-gsc-reader@grounded-style-501621-k3.iam.gserviceaccount.com 添加为使用者'
            }
          >
            {data?.is_real_gsc ? '🟢 REAL_GSC_API 官方实时' : '🟡 GSC 待授权预览'}
          </span>

          <span style={{ color: selectedSingleDate ? '#60a5fa' : '#94a3b8', fontWeight: selectedSingleDate ? 700 : 400 }}>
            {data?.date_range || '2026-07-22 ~ 2026-07-29'}
          </span>

          <button
            onClick={() => loadData(selectedSiteUrl, rangeType, selectedSingleDate)}
            style={{ background: '#1e293b', color: '#cbd5e1', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px', fontSize: 11, cursor: 'pointer' }}
          >
            🔄 同步
          </button>
          <span style={{ color: '#64748b' }}>{nowStr}</span>
        </div>
      </div>

      {/* Top 4 Metrics Summary Cards */}
      <div className="gsc-kpi-grid" style={{ marginBottom: 8, flexShrink: 0 }}>
        {/* Card 1: 自然点击 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #3b82f6' : '1px solid #1f2937', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8', marginBottom: 2 }}>
            <span>🖱️</span> 自然点击 {selectedSingleDate && <span style={{ color: '#60a5fa', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>{summary.clicks.value}</div>
          <div style={{ fontSize: 10, color: summary.clicks.is_down ? '#f87171' : '#34d399', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.clicks.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 2: 展示量 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #eab308' : '1px solid #1f2937', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8', marginBottom: 2 }}>
            <span>👁️</span> 展示量 {selectedSingleDate && <span style={{ color: '#eab308', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>{summary.impressions.value}</div>
          <div style={{ fontSize: 10, color: summary.impressions.is_down ? '#f87171' : '#34d399', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.impressions.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 3: 点击率 CTR */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #3b82f6' : '1px solid #1f2937', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8', marginBottom: 2 }}>
            <span>🎯</span> 点击率 CTR {selectedSingleDate && <span style={{ color: '#60a5fa', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>{summary.ctr.value}</div>
          <div style={{ fontSize: 10, color: summary.ctr.is_down ? '#f87171' : '#34d399', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.ctr.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 4: 平均排名 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #c084fc' : '1px solid #1f2937', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8', marginBottom: 2 }}>
            <span>📍</span> 平均排名 {selectedSingleDate ? '(当日)' : '(加权)'}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>
            {summary.avg_position.value ?? '—'}
          </div>
          <div style={{ fontSize: 10, color: summary.avg_position.is_up ? '#34d399' : '#f87171', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.avg_position.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>
      </div>

      {/* Middle Section: Recharts Trend Line Chart (2.5x height: 360px) */}
      <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #3b82f6' : '1px solid #1f2937', borderRadius: 10, padding: '10px 14px', marginBottom: 8, height: '360px', flexShrink: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', transition: 'all 0.2s' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#f3f4f6' }}>
              📈 点击 / 展示趋势 {rangeType === '24h' ? '24 小时' : rangeType === '7d' ? '7 日' : rangeType === '30d' ? '30 日' : '3 个月'}
            </span>

            {/* Interactive Single-Date Quick Switcher Select */}
            <select
              value={selectedSingleDate || ''}
              onChange={(e) => {
                const val = e.target.value || null
                setSelectedSingleDate(val)
                loadData(selectedSiteUrl, rangeType, val)
              }}
              style={{
                background: selectedSingleDate ? '#1e3a8a' : '#1e293b',
                color: selectedSingleDate ? '#60a5fa' : '#cbd5e1',
                border: `1px solid ${selectedSingleDate ? '#3b82f6' : '#334155'}`,
                borderRadius: 6,
                padding: '2px 8px',
                fontSize: 11,
                fontWeight: 600,
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              <option value="">📅 锁定单日 (当前: 全周期汇总)</option>
              {series.map(s => (
                <option key={s.full_date || s.date} value={s.full_date || s.date}>
                  📍 锁定 {s.full_date || s.date} ({s.clicks} 点击 / {s.impressions} 展现)
                </option>
              ))}
            </select>
            
            {selectedSingleDate ? (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedSingleDate(null)
                  loadData(selectedSiteUrl, rangeType, null)
                }}
                style={{
                  background: '#3b82f6',
                  color: '#ffffff',
                  border: 0,
                  borderRadius: 4,
                  padding: '2px 8px',
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  boxShadow: '0 2px 6px rgba(59,130,246,0.4)',
                }}
              >
                ✕ 解锁全周期
              </button>
            ) : (
              <span style={{ fontSize: 10, color: '#64748b', fontWeight: 400 }}>
                (💡 点击图中任意点或下拉框选单日，全屏各板块锁定显示该日数据)
              </span>
            )}
          </div>

          <div style={{ fontSize: 10, color: '#94a3b8' }}>
            <span style={{ background: '#1e293b', color: '#cbd5e1', padding: '2px 8px', borderRadius: 4 }}>
              {series.length} 天中 {zeroDaysCount} 天零展现 (零展现日断开)
            </span>
          </div>
        </div>

        {/* Professional Recharts Chart Container (310px canvas height) */}
        <div style={{ width: '100%', height: 310, flexShrink: 0 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={series}
              margin={{ top: 15, right: 20, left: -20, bottom: -5 }}
              onClick={handleChartClick}
              style={{ cursor: 'pointer' }}
            >
              <defs>
                <linearGradient id="colorImpr" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#eab308" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#eab308" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" stroke="#94a3b8" fontSize={10} interval="preserveStartEnd" />
              <YAxis yAxisId="left" stroke="#94a3b8" fontSize={10} />
              <YAxis yAxisId="right" orientation="right" reversed domain={[1, 100]} stroke="#c084fc" fontSize={10} />
              <Tooltip content={<CustomChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              <Area yAxisId="left" type="monotone" dataKey="impressions" name="展示量" stroke="#eab308" fill="url(#colorImpr)" strokeWidth={2} />
              <Line yAxisId="left" type="monotone" dataKey="clicks" name="自然点击" stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 3.5 }} activeDot={{ r: 7 }} />
              <Line yAxisId="right" type="monotone" dataKey="position" name="平均排名 (零展现日断开)" stroke="#c084fc" strokeWidth={2} strokeDasharray="4 4" connectNulls={false} dot={{ r: 3.5 }} />
              
              {/* Highlight Blue Vertical Dashed Line for Clicked/Selected Date */}
              {shortSelectedDateKey && (
                <ReferenceLine
                  yAxisId="left"
                  x={shortSelectedDateKey}
                  stroke="#3b82f6"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  label={{ value: `📍 锁定 ${shortSelectedDateKey}`, fill: '#60a5fa', fontSize: 11, position: 'top', fontWeight: 800 }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Bottom 3-Column Detailed Metrics Section */}
      <div className="gsc-bottom-grid" style={{ flex: 1, minHeight: 120, overflow: 'hidden' }}>
        {/* Col 1: 📌 关键词 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #334155' : '1px solid #1f2937', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>📌</span> 关键词 {selectedSingleDate && <span style={{ color: '#60a5fa', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('keywords')}
              style={{
                background: '#1e293b',
                color: '#60a5fa',
                border: '1px solid #334155',
                borderRadius: 4,
                padding: '1px 6px',
                fontSize: 10,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ↗ 放大
            </button>
          </div>

          <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexShrink: 0 }}>
            {[
              { id: 'all', label: '全部' },
              { id: 'non_brand', label: '非品牌' },
              { id: 'rising', label: '▲ 上升' },
              { id: 'falling', label: '▼ 下降' },
            ].map(f => (
              <button
                key={f.id}
                onClick={() => setKwFilter(f.id as any)}
                style={{
                  background: kwFilter === f.id ? '#1e293b' : 'transparent',
                  color: kwFilter === f.id ? '#60a5fa' : '#64748b',
                  border: 0,
                  borderRadius: 4,
                  padding: '2px 6px',
                  fontSize: 10,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1 }}>
            {(
              (data?.top_keywords || []).filter(kw => {
                if (kwFilter === 'non_brand') {
                  const domainName = (data?.domain_name || '').toLowerCase()
                  return !kw.keyword.toLowerCase().includes(domainName)
                }
                if (kwFilter === 'rising') {
                  return kw.delta_clicks.includes('+') || kw.clicks > 0
                }
                if (kwFilter === 'falling') {
                  return kw.delta_clicks.includes('-')
                }
                return true
              })
            ).map((kw, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid #1f2937' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                  <span style={{ color: '#64748b', fontSize: 10, minWidth: 14 }}>{i + 1}</span>
                  <span style={{ color: '#e2e8f0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{kw.keyword}</span>
                  {kw.is_new && <span style={{ background: '#1e3a8a', color: '#60a5fa', padding: '1px 4px', borderRadius: 3, fontSize: 9, fontWeight: 700 }}>NEW</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
                  <span style={{ color: '#64748b', fontSize: 10 }}>CTR {kw.ctr}</span>
                  <span style={{ background: '#1e293b', color: '#94a3b8', padding: '1px 4px', borderRadius: 3, fontSize: 10, fontWeight: 600 }}>
                    P{kw.position}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Col 2: 📄 落地页面 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #334155' : '1px solid #1f2937', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>📄</span> 落地页面 {selectedSingleDate && <span style={{ color: '#60a5fa', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('pages')}
              style={{
                background: '#1e293b',
                color: '#60a5fa',
                border: '1px solid #334155',
                borderRadius: 4,
                padding: '1px 6px',
                fontSize: 10,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ↗ 放大
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1 }}>
            {(data?.landing_pages || []).map((page, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid #1f2937' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                  <span style={{ color: '#64748b', fontSize: 10, minWidth: 14 }}>{i + 1}</span>
                  <span style={{ color: '#60a5fa', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontFamily: 'monospace' }}>{page.path}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
                  <span style={{ color: page.delta.includes('+') ? '#34d399' : '#94a3b8', fontSize: 10, fontWeight: 600 }}>{page.delta}</span>
                  <span style={{ color: '#64748b', fontSize: 10 }}>CTR {page.ctr}</span>
                  <span style={{ background: '#1e293b', color: '#94a3b8', padding: '1px 4px', borderRadius: 3, fontSize: 10, fontWeight: 600 }}>
                    P{page.position}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Col 3: 🌍 点击国家 */}
        <div style={{ background: '#111827', border: selectedSingleDate ? '1px solid #334155' : '1px solid #1f2937', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#f3f4f6', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>🌍</span> 点击国家 {selectedSingleDate && <span style={{ color: '#60a5fa', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('countries')}
              style={{
                background: '#1e293b',
                color: '#60a5fa',
                border: '1px solid #334155',
                borderRadius: 4,
                padding: '1px 6px',
                fontSize: 10,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ↗ 放大
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1 }}>
            {(data?.countries || []).map((country, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid #1f2937' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '60%' }}>
                  <span style={{ background: '#1e293b', color: '#38bdf8', padding: '1px 5px', borderRadius: 3, fontSize: 9, fontWeight: 700, minWidth: 28, textAlign: 'center' }}>
                    {country.code}
                  </span>
                  <span style={{ color: '#e2e8f0' }}>{country.name}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '40%', justifyContent: 'flex-end' }}>
                  <div style={{ width: 35, background: '#1f2937', height: 4, borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(country.clicks * 20, 100)}%`, background: '#eab308', height: '100%' }} />
                  </div>
                  <span style={{ color: '#f8fafc', fontWeight: 700, minWidth: 10 }}>{country.clicks}</span>
                  <span style={{ color: '#64748b', fontSize: 10, minWidth: 45, textAlign: 'right' }}>CTR {country.ctr}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer Agent Task Status Bar */}
      <div style={{ marginTop: 6, paddingTop: 4, borderTop: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#64748b', flexShrink: 0 }}>
        <div>⚙️ {data?.footer_status?.tasks_summary || 'SEO 运营 2存活 · 2执行 · 0等待 · 0阻塞'}</div>
        <div>数据源: {data?.footer_status?.datasource || 'Google Search Console 真实采样引擎'} · {nowStr}</div>
      </div>

      {/* Full Detailed Modal Popup */}
      {modalType && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ background: '#111827', border: '1px solid #374151', borderRadius: 14, width: '100%', maxWidth: 840, maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 40px rgba(0,0,0,0.8)' }}>
            {/* Modal Header */}
            <div style={{ padding: '14px 20px', borderBottom: '1px solid #1f2937', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f3f4f6', margin: 0 }}>
                  {modalType === 'keywords' && '🔑 关键词全量'}
                  {modalType === 'pages' && '📄 落地页面全量'}
                  {modalType === 'countries' && '🌍 点击国家全量'}
                </h3>
                <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
                  {rangeType} · {data?.date_range}
                </div>
              </div>
              <button
                onClick={() => setModalType(null)}
                style={{ background: 'transparent', color: '#9ca3af', border: 0, fontSize: 18, cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* Modal Content Table */}
            <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
              {modalType === 'keywords' && (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #374151', color: '#9ca3af' }}>
                      <th style={{ padding: '8px 10px' }}>关键词</th>
                      <th style={{ padding: '8px 10px' }}>点击</th>
                      <th style={{ padding: '8px 10px' }}>Δ点击</th>
                      <th style={{ padding: '8px 10px' }}>展示</th>
                      <th style={{ padding: '8px 10px' }}>CTR</th>
                      <th style={{ padding: '8px 10px' }}>排名</th>
                      <th style={{ padding: '8px 10px' }}>Δ排名</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.top_keywords || []).map((kw, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1f2937', color: '#e5e7eb' }}>
                        <td style={{ padding: '10px', fontWeight: 600 }}>
                          {kw.keyword} {kw.is_new && <span style={{ background: '#1e3a8a', color: '#60a5fa', padding: '1px 5px', borderRadius: 3, fontSize: 9, marginLeft: 4 }}>NEW</span>}
                        </td>
                        <td style={{ padding: '10px' }}>{kw.clicks}</td>
                        <td style={{ padding: '10px', color: '#34d399' }}>{kw.delta_clicks}</td>
                        <td style={{ padding: '10px' }}>{kw.impressions}</td>
                        <td style={{ padding: '10px' }}>{kw.ctr}</td>
                        <td style={{ padding: '10px', fontWeight: 700 }}>{kw.position}</td>
                        <td style={{ padding: '10px', color: '#f87171' }}>{kw.delta_position}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {modalType === 'pages' && (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #374151', color: '#9ca3af' }}>
                      <th style={{ padding: '8px 10px' }}>页面路径</th>
                      <th style={{ padding: '8px 10px' }}>点击</th>
                      <th style={{ padding: '8px 10px' }}>变动</th>
                      <th style={{ padding: '8px 10px' }}>展示</th>
                      <th style={{ padding: '8px 10px' }}>CTR</th>
                      <th style={{ padding: '8px 10px' }}>排名</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.landing_pages || []).map((p, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1f2937', color: '#e5e7eb' }}>
                        <td style={{ padding: '10px', color: '#60a5fa', fontFamily: 'monospace' }}>{p.path}</td>
                        <td style={{ padding: '10px' }}>{p.clicks}</td>
                        <td style={{ padding: '10px', color: p.delta.includes('+') ? '#34d399' : '#9ca3af' }}>{p.delta}</td>
                        <td style={{ padding: '10px' }}>{p.impressions}</td>
                        <td style={{ padding: '10px' }}>{p.ctr}</td>
                        <td style={{ padding: '10px', fontWeight: 700 }}>{p.position}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {modalType === 'countries' && (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #374151', color: '#9ca3af' }}>
                      <th style={{ padding: '8px 10px' }}>代码</th>
                      <th style={{ padding: '8px 10px' }}>国家 / 地区</th>
                      <th style={{ padding: '8px 10px' }}>点击数</th>
                      <th style={{ padding: '8px 10px' }}>CTR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.countries || []).map((c, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1f2937', color: '#e5e7eb' }}>
                        <td style={{ padding: '10px', fontWeight: 700, color: '#38bdf8' }}>{c.code}</td>
                        <td style={{ padding: '10px' }}>{c.name}</td>
                        <td style={{ padding: '10px', fontWeight: 700 }}>{c.clicks}</td>
                        <td style={{ padding: '10px' }}>{c.ctr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import React, { useEffect, useState } from 'react'
import { useIsMobile } from '../hooks'
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
  custom_range?: boolean
  range_start?: string
  range_end?: string
  custom_range_error?: string
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
          background: 'var(--surface)',
          border: '1px solid var(--accent)',
          borderRadius: 8,
          padding: '8px 12px',
          fontSize: 11,
          color: 'var(--text)',
          boxShadow: '0 8px 20px oklch(0% 0 0 / .6)',
        }}
      >
        <div style={{ fontWeight: 700, color: 'var(--accent)', marginBottom: 4 }}>
          📅 {item.full_date || label} (点击可锁定/查看当天全量数据)
        </div>
        <div style={{ color: 'var(--accent)', fontWeight: 600 }}>🖱️ 自然点击: {item.clicks}</div>
        <div style={{ color: 'var(--warn)', fontWeight: 600 }}>👁️ 展示量: {item.impressions}</div>
        <div style={{ color: 'var(--rev)', fontWeight: 600 }}>
          📍 平均排名: {item.position !== null ? `P${item.position}` : '— (零展现)'}
        </div>
      </div>
    )
  }
  return null
}

export const GscOverviewPanel: React.FC<GscOverviewPanelProps> = ({ monitoredSites = [], onSelectSite }) => {
  const isMobile = useIsMobile()
  const [selectedSiteUrl, setSelectedSiteUrl] = useState<string>('')
  const [rangeType, setRangeType] = useState<string>('7d')
  const [customStart, setCustomStart] = useState<string>('')
  const [customEnd, setCustomEnd] = useState<string>('')
  const [showCustom, setShowCustom] = useState<boolean>(false)
  const [selectedSingleDate, setSelectedSingleDate] = useState<string | null>(null)
  const [kwFilter, setKwFilter] = useState<'all' | 'non_brand' | 'rising' | 'falling'>('all')
  const [loading, setLoading] = useState<boolean>(true)
  const [data, setData] = useState<GscData | null>(null)
  const [nowStr, setNowStr] = useState<string>('')
  const [syncing, setSyncing] = useState<boolean>(false)
  const [lastSync, setLastSync] = useState<Date | null>(null)

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
      const custom = range === 'custom' && customStart && customEnd
        ? `&start_date=${customStart}&end_date=${customEnd}` : ''
      const url = `/api/gsc/overview?range=${range}${siteUrl ? `&site_url=${encodeURIComponent(siteUrl)}` : ''}${singleDate ? `&single_date=${encodeURIComponent(singleDate)}` : ''}${custom}`
      const res = await fetch(url)
      const json = await res.json()
      if (json.ok) {
        setData(json)
        if (!selectedSiteUrl && json.site_url) {
          setSelectedSiteUrl(json.site_url)
        }
      }
      setLastSync(new Date())
    } catch (e) {
      console.warn('Failed to load GSC overview data', e)
    } finally {
      setLoading(false)
      setSyncing(false)
    }
  }

  /** 手动同步:立刻拉一次,并显示进行中动画 */
  const manualSync = () => {
    if (syncing) return
    setSyncing(true)
    loadData(selectedSiteUrl, rangeType, selectedSingleDate)
  }

  useEffect(() => {
    loadData(selectedSiteUrl, rangeType, selectedSingleDate)
  }, [selectedSiteUrl, rangeType])

  // 30 分钟自动同步一次。GSC 数据本身有延迟,更密没有意义,
  // 只会白白消耗配额。锁定单日时不自动刷,免得把用户看的那天冲掉。
  useEffect(() => {
    const AUTO_SYNC_MS = 30 * 60 * 1000
    const timer = setInterval(() => {
      if (document.hidden) return
      if (selectedSingleDate) return
      setSyncing(true)
      loadData(selectedSiteUrl, rangeType, null)
    }, AUTO_SYNC_MS)
    return () => clearInterval(timer)
  }, [selectedSiteUrl, rangeType, selectedSingleDate])

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
      <div style={{ background: 'var(--bg)', borderRadius: 12, padding: 24, textAlign: 'center', color: 'var(--dim)' }}>
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
        background: 'var(--bg)',
        color: 'var(--text)',
        borderRadius: 14,
        padding: '12px 16px',
        border: '1px solid var(--panel)',
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
          <h2 style={{ fontSize: 17, fontWeight: 800, color: 'var(--text)', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
            📊 SEO 数据大屏
          </h2>

          <select
            value={selectedSiteUrl || data?.site_url || ''}
            onChange={handleSiteChange}
            style={{
              background: 'var(--panel)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
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
                background: 'var(--warn-soft)',
                color: 'var(--warn)',
                border: '1px solid var(--warn)',
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, background: 'var(--panel)', padding: 2, borderRadius: 6 }}>
          {['24h', '7d', '30d', '3m', 'custom'].map((r) => {
            const labelMap: Record<string, string> = { '24h': '24小时', '7d': '7日', '30d': '30日', '3m': '3个月', 'custom': '📅 自定义' }
            const active = rangeType === r
            return (
              <button
                key={r}
                onClick={() => {
                  if (r === 'custom') {
                    setShowCustom(!showCustom)
                    setRangeType('custom')
                  } else {
                    setShowCustom(false)
                    handleRangeChange(r)
                  }
                }}
                style={{
                  background: active ? 'var(--accent)' : 'transparent',
                  color: active ? 'var(--text)' : 'var(--dim)',
                  border: 0,
                  borderRadius: 4,
                  padding: '3px 10px',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  boxShadow: active ? '0 2px 6px var(--accent-line)' : 'none',
                }}
              >
                {labelMap[r]}
              </button>
            )
          })}
        </div>

        {/* 自定义日期区间 */}
        {showCustom && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px' }}>
            <input
              type="date"
              value={customStart}
              max={customEnd || undefined}
              onChange={(e) => setCustomStart(e.target.value)}
              style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text)', fontSize: 11, padding: '2px 6px', colorScheme: 'dark' }}
            />
            <span style={{ color: 'var(--faint)', fontSize: 11 }}>~</span>
            <input
              type="date"
              value={customEnd}
              min={customStart || undefined}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setCustomEnd(e.target.value)}
              style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text)', fontSize: 11, padding: '2px 6px', colorScheme: 'dark' }}
            />
            <button
              disabled={!customStart || !customEnd}
              onClick={() => {
                setSelectedSingleDate(null)
                loadData(selectedSiteUrl, 'custom', null)
              }}
              style={{
                background: customStart && customEnd ? 'var(--accent)' : 'var(--border)',
                color: customStart && customEnd ? 'var(--text)' : 'var(--faint)',
                border: 0, borderRadius: 4, padding: '3px 10px', fontSize: 11, fontWeight: 600,
                cursor: customStart && customEnd ? 'pointer' : 'not-allowed',
              }}
            >
              查询
            </button>
            {data?.custom_range_error && (
              <span style={{ color: 'var(--bad)', fontSize: 10 }}>⚠️ {data.custom_range_error}</span>
            )}
          </div>
        )}

        {/* Status Indicators & Refresh */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
          <span
            style={{
              background: data?.is_real_gsc ? 'var(--ok-soft)' : 'var(--warn-soft)',
              color: data?.is_real_gsc ? 'var(--ok)' : 'var(--warn)',
              padding: '2px 8px',
              borderRadius: 10,
              border: `1px solid ${data?.is_real_gsc ? 'var(--ok)' : 'var(--warn)'}`,
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

          <span style={{ color: selectedSingleDate ? 'var(--accent)' : 'var(--dim)', fontWeight: selectedSingleDate ? 700 : 400 }}>
            {data?.date_range || '2026-07-22 ~ 2026-07-29'}
          </span>

          <button
            onClick={manualSync}
            disabled={syncing || loading}
            title={lastSync ? `上次同步 ${lastSync.toLocaleTimeString('zh-CN', { hour12: false })} · 每 30 分钟自动同步` : '每 30 分钟自动同步'}
            style={{
              background: syncing ? 'var(--accent-soft)' : 'var(--panel)',
              color: syncing ? 'var(--accent)' : 'var(--text)',
              border: `1px solid ${syncing ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 4, padding: '2px 8px', fontSize: 11,
              cursor: syncing || loading ? 'wait' : 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}
          >
            <span style={{
              display: 'inline-block',
              animation: syncing || loading ? 'gscSpin 0.9s linear infinite' : 'none',
            }}>🔄</span>
            {syncing ? '同步中' : '同步'}
          </button>
          {syncing && (
            <span style={{ color: 'var(--accent)', fontSize: 10 }}>正在拉取 GSC…</span>
          )}
          {!syncing && lastSync && (
            <span style={{ color: 'var(--border)', fontSize: 10 }}>
              上次 {lastSync.toLocaleTimeString('zh-CN', { hour12: false })}
            </span>
          )}
          <span style={{ color: 'var(--faint)' }}>{nowStr}</span>
        </div>
      </div>

      {/* Top 4 Metrics Summary Cards */}
      <div className="gsc-kpi-grid" style={{ marginBottom: 8, flexShrink: 0 }}>
        {/* Card 1: 自然点击 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--accent)' : '1px solid var(--panel)', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--dim)', marginBottom: 2 }}>
            <span>🖱️</span> 自然点击 {selectedSingleDate && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{summary.clicks.value}</div>
          <div style={{ fontSize: 10, color: summary.clicks.is_down ? 'var(--bad)' : 'var(--ok)', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.clicks.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 2: 展示量 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--warn)' : '1px solid var(--panel)', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--dim)', marginBottom: 2 }}>
            <span>👁️</span> 展示量 {selectedSingleDate && <span style={{ color: 'var(--warn)', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{summary.impressions.value}</div>
          <div style={{ fontSize: 10, color: summary.impressions.is_down ? 'var(--bad)' : 'var(--ok)', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.impressions.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 3: 点击率 CTR */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--accent)' : '1px solid var(--panel)', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--dim)', marginBottom: 2 }}>
            <span>🎯</span> 点击率 CTR {selectedSingleDate && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>(当日)</span>}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{summary.ctr.value}</div>
          <div style={{ fontSize: 10, color: summary.ctr.is_down ? 'var(--bad)' : 'var(--ok)', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.ctr.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>

        {/* Card 4: 平均排名 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--rev)' : '1px solid var(--panel)', borderRadius: 8, padding: '8px 12px', position: 'relative', overflow: 'hidden', transition: 'all 0.2s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--dim)', marginBottom: 2 }}>
            <span>📍</span> 平均排名 {selectedSingleDate ? '(当日)' : '(加权)'}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>
            {summary.avg_position.value ?? '—'}
          </div>
          <div style={{ fontSize: 10, color: summary.avg_position.is_up ? 'var(--ok)' : 'var(--bad)', marginTop: 2, fontWeight: 600 }}>
            {selectedSingleDate ? `日期: ${selectedSingleDate}` : `${summary.avg_position.change} vs 上${rangeType === '7d' ? '7 日' : '周期'}`}
          </div>
        </div>
      </div>

      {/* Middle Section: Recharts Trend Line Chart (2.5x height: 360px) */}
      <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--accent)' : '1px solid var(--panel)', borderRadius: 10, padding: '10px 14px', marginBottom: 8, height: '360px', flexShrink: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', transition: 'all 0.2s' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
              📈 点击 / 展示趋势 {rangeType === 'custom' ? (data?.date_range || '自定义区间') : rangeType === '24h' ? '24 小时' : rangeType === '7d' ? '7 日' : rangeType === '30d' ? '30 日' : '3 个月'}
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
                background: selectedSingleDate ? 'var(--accent-soft)' : 'var(--panel)',
                color: selectedSingleDate ? 'var(--accent)' : 'var(--text)',
                border: `1px solid ${selectedSingleDate ? 'var(--accent)' : 'var(--border)'}`,
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
                  background: 'var(--accent)',
                  color: 'var(--text)',
                  border: 0,
                  borderRadius: 4,
                  padding: '2px 8px',
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  boxShadow: '0 2px 6px var(--accent-line)',
                }}
              >
                ✕ 解锁全周期
              </button>
            ) : (
              <span style={{ fontSize: 10, color: 'var(--faint)', fontWeight: 400 }}>
                (💡 点击图中任意点或下拉框选单日，全屏各板块锁定显示该日数据)
              </span>
            )}
          </div>

          <div style={{ fontSize: 10, color: 'var(--dim)' }}>
            <span style={{ background: 'var(--panel)', color: 'var(--text)', padding: '2px 8px', borderRadius: 4 }}>
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
                  <stop offset="5%" stopColor="var(--warn)" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="var(--warn)" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--panel)" />
              <XAxis dataKey="date" stroke="var(--dim)" fontSize={10} interval="preserveStartEnd" />
              <YAxis yAxisId="left" stroke="var(--dim)" fontSize={10} />
              <YAxis yAxisId="right" orientation="right" reversed domain={[1, 100]} stroke="var(--rev)" fontSize={10} />
              <Tooltip content={<CustomChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              <Area yAxisId="left" type="monotone" dataKey="impressions" name="展示量" stroke="var(--warn)" fill="url(#colorImpr)" strokeWidth={2} />
              <Line yAxisId="left" type="monotone" dataKey="clicks" name="自然点击" stroke="var(--accent)" strokeWidth={2.5} dot={{ r: 3.5 }} activeDot={{ r: 7 }} />
              <Line yAxisId="right" type="monotone" dataKey="position" name="平均排名 (零展现日断开)" stroke="var(--rev)" strokeWidth={2} strokeDasharray="4 4" connectNulls={false} dot={{ r: 3.5 }} />
              
              {/* Highlight Blue Vertical Dashed Line for Clicked/Selected Date */}
              {shortSelectedDateKey && (
                <ReferenceLine
                  yAxisId="left"
                  x={shortSelectedDateKey}
                  stroke="var(--accent)"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  label={{ value: `📍 锁定 ${shortSelectedDateKey}`, fill: 'var(--accent)', fontSize: 11, position: 'top', fontWeight: 800 }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Bottom 3-Column Detailed Metrics Section */}
      <div className="gsc-bottom-grid" style={{ flex: 1, minHeight: 120, overflow: isMobile ? 'visible' : 'hidden' }}>
        {/* Col 1: 📌 关键词 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--border)' : '1px solid var(--panel)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>📌</span> 关键词 {selectedSingleDate && <span style={{ color: 'var(--accent)', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('keywords')}
              style={{
                background: 'var(--panel)',
                color: 'var(--accent)',
                border: '1px solid var(--border)',
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
                  background: kwFilter === f.id ? 'var(--panel)' : 'transparent',
                  color: kwFilter === f.id ? 'var(--accent)' : 'var(--faint)',
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
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid var(--panel)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0, overflow: 'hidden' }}>
                  <span style={{ color: 'var(--faint)', fontSize: 10, minWidth: 14, flexShrink: 0 }}>{i + 1}</span>
                  <span style={{ color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{kw.keyword}</span>
                  {kw.is_new && <span style={{ background: 'var(--accent-soft)', color: 'var(--accent)', padding: '1px 4px', borderRadius: 3, fontSize: 9, fontWeight: 700, flexShrink: 0 }}>NEW</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap', flexShrink: 0, marginLeft: 8 }}>
                  <span style={{ color: 'var(--faint)', fontSize: 10, width: 62, textAlign: 'right' }}>CTR {kw.ctr}</span>
                  <span style={{ background: 'var(--panel)', color: 'var(--dim)', padding: '1px 4px', borderRadius: 3, fontSize: 10, fontWeight: 600, width: 42, textAlign: 'center', boxSizing: 'border-box' }}>
                    P{kw.position}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Col 2: 📄 落地页面 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--border)' : '1px solid var(--panel)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>📄</span> 落地页面 {selectedSingleDate && <span style={{ color: 'var(--accent)', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('pages')}
              style={{
                background: 'var(--panel)',
                color: 'var(--accent)',
                border: '1px solid var(--border)',
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
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid var(--panel)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0, overflow: 'hidden' }}>
                  <span style={{ color: 'var(--faint)', fontSize: 10, minWidth: 14, flexShrink: 0 }}>{i + 1}</span>
                  <span style={{ color: 'var(--accent)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontFamily: 'monospace' }}>{page.path}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap', flexShrink: 0, marginLeft: 8 }}>
                  <span style={{ color: page.delta.includes('+') ? 'var(--ok)' : 'var(--dim)', fontSize: 10, fontWeight: 600, width: 34, textAlign: 'right' }}>{page.delta}</span>
                  <span style={{ color: 'var(--faint)', fontSize: 10, width: 62, textAlign: 'right' }}>CTR {page.ctr}</span>
                  <span style={{ background: 'var(--panel)', color: 'var(--dim)', padding: '1px 4px', borderRadius: 3, fontSize: 10, fontWeight: 600, width: 42, textAlign: 'center', boxSizing: 'border-box' }}>
                    P{page.position}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Col 3: 🌍 点击国家 */}
        <div style={{ background: 'var(--surface)', border: selectedSingleDate ? '1px solid var(--border)' : '1px solid var(--panel)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>🌍</span> 点击国家 {selectedSingleDate && <span style={{ color: 'var(--accent)', fontSize: 10 }}>({selectedSingleDate})</span>}
            </div>
            <button
              onClick={() => setModalType('countries')}
              style={{
                background: 'var(--panel)',
                color: 'var(--accent)',
                border: '1px solid var(--border)',
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
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, paddingBottom: 4, borderBottom: '1px solid var(--panel)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, overflow: 'hidden' }}>
                  <span style={{ background: 'var(--panel)', color: 'var(--accent2)', padding: '1px 5px', borderRadius: 3, fontSize: 9, fontWeight: 700, minWidth: 28, textAlign: 'center' }}>
                    {country.code}
                  </span>
                  <span style={{ color: 'var(--text)' }}>{country.name}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 8, justifyContent: 'flex-end' }}>
                  <div style={{ width: 35, background: 'var(--panel)', height: 4, borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
                    <div style={{ width: `${Math.min(country.clicks * 20, 100)}%`, background: 'var(--warn)', height: '100%' }} />
                  </div>
                  <span style={{ color: 'var(--text)', fontWeight: 700, width: 18, textAlign: 'right' }}>{country.clicks}</span>
                  <span style={{ color: 'var(--faint)', fontSize: 10, width: 62, textAlign: 'right' }}>CTR {country.ctr}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer Agent Task Status Bar */}
      <div style={{ marginTop: 6, paddingTop: 4, borderTop: '1px solid var(--panel)', display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--faint)', flexShrink: 0 }}>
        <div>⚙️ {data?.footer_status?.tasks_summary || 'SEO 运营 2存活 · 2执行 · 0等待 · 0阻塞'}</div>
        <div>数据源: {data?.footer_status?.datasource || 'Google Search Console 真实采样引擎'} · {nowStr}</div>
      </div>

      {/* Full Detailed Modal Popup */}
      {modalType && (
        <div style={{ position: 'fixed', inset: 0, background: 'oklch(0% 0 0 / .8)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, width: '100%', maxWidth: 840, maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 40px oklch(0% 0 0 / .8)' }}>
            {/* Modal Header */}
            <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--panel)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', margin: 0 }}>
                  {modalType === 'keywords' && '🔑 关键词全量'}
                  {modalType === 'pages' && '📄 落地页面全量'}
                  {modalType === 'countries' && '🌍 点击国家全量'}
                </h3>
                <div style={{ fontSize: 11, color: 'var(--dim)', marginTop: 2 }}>
                  {rangeType} · {data?.date_range}
                </div>
              </div>
              <button
                onClick={() => setModalType(null)}
                style={{ background: 'transparent', color: 'var(--dim)', border: 0, fontSize: 18, cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* Modal Content Table */}
            <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
              {modalType === 'keywords' && (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)' }}>
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
                      <tr key={i} style={{ borderBottom: '1px solid var(--panel)', color: 'var(--text)' }}>
                        <td style={{ padding: '10px', fontWeight: 600 }}>
                          {kw.keyword} {kw.is_new && <span style={{ background: 'var(--accent-soft)', color: 'var(--accent)', padding: '1px 5px', borderRadius: 3, fontSize: 9, marginLeft: 4 }}>NEW</span>}
                        </td>
                        <td style={{ padding: '10px' }}>{kw.clicks}</td>
                        <td style={{ padding: '10px', color: 'var(--ok)' }}>{kw.delta_clicks}</td>
                        <td style={{ padding: '10px' }}>{kw.impressions}</td>
                        <td style={{ padding: '10px' }}>{kw.ctr}</td>
                        <td style={{ padding: '10px', fontWeight: 700 }}>{kw.position}</td>
                        <td style={{ padding: '10px', color: 'var(--bad)' }}>{kw.delta_position}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {modalType === 'pages' && (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)' }}>
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
                      <tr key={i} style={{ borderBottom: '1px solid var(--panel)', color: 'var(--text)' }}>
                        <td style={{ padding: '10px', color: 'var(--accent)', fontFamily: 'monospace' }}>{p.path}</td>
                        <td style={{ padding: '10px' }}>{p.clicks}</td>
                        <td style={{ padding: '10px', color: p.delta.includes('+') ? 'var(--ok)' : 'var(--dim)' }}>{p.delta}</td>
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
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)' }}>
                      <th style={{ padding: '8px 10px' }}>代码</th>
                      <th style={{ padding: '8px 10px' }}>国家 / 地区</th>
                      <th style={{ padding: '8px 10px' }}>点击数</th>
                      <th style={{ padding: '8px 10px' }}>CTR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.countries || []).map((c, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--panel)', color: 'var(--text)' }}>
                        <td style={{ padding: '10px', fontWeight: 700, color: 'var(--accent2)' }}>{c.code}</td>
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

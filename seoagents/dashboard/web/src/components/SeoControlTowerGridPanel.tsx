import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useIsMobile } from '../hooks'
import { Responsive, WidthProvider, type LayoutItem } from 'react-grid-layout/legacy'

/**
 * SEO 总控大屏 V1 — React 可拖拽网格版
 *
 * 从独立静态 HTML 迁移为 React 组件，使用与任务卡完全相同的 react-grid-layout
 * 20 列 canonical 布局系统。布局核心函数从 KanbanPanel.tsx 提取并适配大屏模块。
 *
 * - 20 列 × N 行可拖拽网格
 * - 拖拽卡片换位置 / 拖右下角改大小
 * - 布局存 localStorage（key: seo-tower-layout-v1），刷新后恢复
 * - 数据从 /static/preview/seo-control-tower-sites.json 加载
 * - UNAVAILABLE 不补零、DEGRADED 带原因、显示数据来源和窗口
 */

// ════════════════════════════════════════════════════════════
// 网格常量 & 布局核心函数（从 KanbanPanel 提取，适配大屏模块）
// ════════════════════════════════════════════════════════════

const CANONICAL_COLS = 20

type GridBreakpoint = 'lg' | 'md' | 'sm' | 'xs'
const BREAKPOINTS: Record<GridBreakpoint, number> = { lg: 1180, md: 900, sm: 620, xs: 0 }
const COLS_MAP: Record<GridBreakpoint, number> = { lg: CANONICAL_COLS, md: 16, sm: 8, xs: 1 }
const ROW_HEIGHT = 48

// ── 大屏模块 ID ──────────────────────────────────────────
type TowerModuleId =
  | 'kpi-bar'
  | 'inspection'
  | 'execution'
  | 'freshness'
  | 'gsc-trend'
  | 'ga4-map'
  | 'gsc-search'
  | 'ga4-behavior'
  | 'keywords'
  | 'landing'
  | 'content'
  | 'psi'
  | 'technical'
  | 'inspection-flow'
  | 'workflow-timeline'

const MODULE_ORDER: TowerModuleId[] = [
  'kpi-bar', 'inspection', 'execution', 'freshness',
  'gsc-trend', 'ga4-map',
  'gsc-search', 'ga4-behavior',
  'keywords', 'landing', 'content',
  'psi', 'technical',
  'inspection-flow', 'workflow-timeline',
]
const MODULE_IDS = new Set<string>(MODULE_ORDER)

const MODULE_LABELS: Record<TowerModuleId, { icon: string; title: string }> = {
  'kpi-bar':          { icon: '📊', title: '核心 KPI' },
  'inspection':       { icon: '🔍', title: '今日巡检报告' },
  'execution':        { icon: '⚙️', title: '执行与调度' },
  'freshness':        { icon: '⏱️', title: '数据新鲜度' },
  'gsc-trend':        { icon: '📈', title: 'GSC 点击 / 展示 / 加权排名趋势' },
  'ga4-map':          { icon: '🌍', title: 'GA4 世界来访地图' },
  'gsc-search':       { icon: '🔎', title: 'GSC 搜索表现' },
  'ga4-behavior':     { icon: '👥', title: 'GA4 用户行为' },
  'keywords':         { icon: '🔑', title: '关键词机会' },
  'landing':          { icon: '📄', title: '落地页行为' },
  'content':          { icon: '📝', title: '内容与收录健康' },
  'psi':              { icon: '⚡', title: 'PageSpeed / Core Web Vitals' },
  'technical':        { icon: '🔧', title: '技术 SEO 快照' },
  'inspection-flow':  { icon: '🔄', title: '每日巡检报告进度' },
  'workflow-timeline':{ icon: '📋', title: 'Workflow / Timeline 真实进度' },
}

// ── 默认 canonical 20 列布局 ─────────────────────────────
const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'kpi-bar',           x: 0,  y: 0,  w: 20, h: 2,  minW: 10, minH: 2 },
  { i: 'inspection',        x: 0,  y: 2,  w: 7,  h: 5,  minW: 5,  minH: 3 },
  { i: 'execution',         x: 7,  y: 2,  w: 7,  h: 5,  minW: 5,  minH: 3 },
  { i: 'freshness',         x: 14, y: 2,  w: 6,  h: 5,  minW: 4,  minH: 3 },
  { i: 'gsc-trend',         x: 0,  y: 7,  w: 10, h: 6,  minW: 6,  minH: 4 },
  { i: 'ga4-map',           x: 10, y: 7,  w: 10, h: 6,  minW: 6,  minH: 4 },
  { i: 'gsc-search',        x: 0,  y: 13, w: 10, h: 5,  minW: 5,  minH: 3 },
  { i: 'ga4-behavior',      x: 10, y: 13, w: 10, h: 5,  minW: 5,  minH: 3 },
  { i: 'keywords',          x: 0,  y: 18, w: 7,  h: 5,  minW: 4,  minH: 3 },
  { i: 'landing',           x: 7,  y: 18, w: 7,  h: 5,  minW: 4,  minH: 3 },
  { i: 'content',           x: 14, y: 18, w: 6,  h: 5,  minW: 4,  minH: 3 },
  { i: 'psi',               x: 0,  y: 23, w: 10, h: 5,  minW: 5,  minH: 3 },
  { i: 'technical',         x: 10, y: 23, w: 10, h: 5,  minW: 5,  minH: 3 },
  { i: 'inspection-flow',   x: 0,  y: 28, w: 10, h: 5,  minW: 5,  minH: 3 },
  { i: 'workflow-timeline', x: 10, y: 28, w: 10, h: 5,  minW: 5,  minH: 3 },
]
const DEFAULT_BY_ID = new Map(DEFAULT_LAYOUT.map((item) => [item.i as TowerModuleId, item]))

const LAYOUT_KEY = 'seo-tower-layout-v1'
const LAYOUT_VERSION = 2
const MAX_LAYOUT_ROWS = 10_000

type PersistedLayoutV2 = {
  version: typeof LAYOUT_VERSION
  cols: typeof CANONICAL_COLS
  layout: LayoutItem[]
}

type LayoutRect = Pick<LayoutItem, 'x' | 'y' | 'w' | 'h'>

const isFiniteInt = (value: unknown): value is number => (
  typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value)
)

const collides = (a: LayoutRect, b: LayoutRect) => (
  a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
)

function validateLayout(input: unknown, cols: number): LayoutItem[] | null {
  if (!Array.isArray(input) || input.length !== MODULE_ORDER.length) return null
  const byId = new Map<TowerModuleId, LayoutItem>()
  for (const raw of input) {
    if (!raw || typeof raw !== 'object') return null
    const item = raw as Record<string, unknown>
    if (typeof item.i !== 'string' || !MODULE_IDS.has(item.i) || byId.has(item.i as TowerModuleId)) return null
    if (![item.x, item.y, item.w, item.h].every(isFiniteInt)) return null
    const x = item.x as number
    const y = item.y as number
    const w = item.w as number
    const h = item.h as number
    if (x < 0 || y < 0 || w < 1 || h < 1 || x + w > cols || y + h > MAX_LAYOUT_ROWS) return null
    byId.set(item.i as TowerModuleId, { i: item.i, x, y, w, h })
  }
  const ordered = MODULE_ORDER.map((id) => byId.get(id)!)
  for (let i = 0; i < ordered.length; i++) {
    for (let j = i + 1; j < ordered.length; j++) {
      if (collides(ordered[i], ordered[j])) return null
    }
  }
  return ordered
}

function withCanonicalConstraints(layout: LayoutItem[]): LayoutItem[] {
  return MODULE_ORDER.map((id) => {
    const item = layout.find((candidate) => candidate.i === id)!
    const defaults = DEFAULT_BY_ID.get(id)!
    return {
      i: id,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      minW: Math.min(defaults.minW ?? 1, item.w),
      minH: Math.min(defaults.minH ?? 1, item.h),
    }
  })
}

function mapBoundaries(values: number[], sourceCols: number, targetCols: number): Map<number, number> {
  const unique = [...new Set([0, sourceCols, ...values])].sort((a, b) => a - b)
  const exactIntervals = unique.slice(1).map((value, index) => (
    ((value - unique[index]) * targetCols) / sourceCols
  ))
  const sizes = exactIntervals.map(Math.floor)
  let remainder = targetCols - sizes.reduce((sum, value) => sum + value, 0)
  const ranked = exactIntervals
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index)
  for (let index = 0; index < remainder; index++) sizes[ranked[index].index]++
  const result = new Map<number, number>([[unique[0], 0]])
  let cursor = 0
  sizes.forEach((size, index) => {
    cursor += size
    result.set(unique[index + 1], cursor)
  })
  return result
}

function compactVertically(layout: LayoutItem[]): LayoutItem[] {
  const placed: LayoutItem[] = []
  const sorted = layout.map((item) => ({ ...item })).sort((a, b) => a.y - b.y || a.x - b.x || MODULE_ORDER.indexOf(a.i as TowerModuleId) - MODULE_ORDER.indexOf(b.i as TowerModuleId))
  for (const item of sorted) {
    let y = 0
    while (y < item.y && !placed.some((other) => collides({ ...item, y }, other))) y++
    item.y = y
    while (placed.some((other) => collides(item, other))) item.y++
    placed.push(item)
  }
  return MODULE_ORDER.map((id) => placed.find((item) => item.i === id)!)
}

function mapLayoutColumns(base: LayoutItem[], sourceCols: number, targetCols: number): LayoutItem[] {
  if (sourceCols === targetCols) return compactVertically(base.map((item) => ({ ...item })))
  const boundaryMap = mapBoundaries(base.flatMap((item) => [item.x, item.x + item.w]), sourceCols, targetCols)
  const mapped = base.map((item) => {
    const left = boundaryMap.get(item.x)!
    const right = boundaryMap.get(item.x + item.w)!
    return {
      ...item,
      x: Math.min(left, targetCols - 1),
      w: Math.max(1, Math.min(targetCols - left, right - left)),
      minW: Math.max(1, Math.min(targetCols, Math.round((item.minW ?? 1) * targetCols / sourceCols))),
    }
  })
  return compactVertically(mapped)
}

const MOBILE_HEIGHTS: Record<TowerModuleId, number> = {
  'kpi-bar': 5, 'inspection': 6, 'execution': 6, 'freshness': 5,
  'gsc-trend': 6, 'ga4-map': 5, 'gsc-search': 5, 'ga4-behavior': 5,
  'keywords': 6, 'landing': 6, 'content': 5,
  'psi': 6, 'technical': 5, 'inspection-flow': 5, 'workflow-timeline': 6,
}

function stackLayout(base: LayoutItem[]): LayoutItem[] {
  let y = 0
  return MODULE_ORDER.map((moduleId) => {
    const source = base.find((item) => item.i === moduleId) || DEFAULT_BY_ID.get(moduleId)!
    const h = MOBILE_HEIGHTS[moduleId]
    const item = { ...source, x: 0, y, w: 1, h, minW: 1, minH: 1, isDraggable: false, isResizable: false }
    y += h
    return item
  })
}

function buildAllLayouts(canonical: LayoutItem[]) {
  return {
    lg: canonical.map((item) => ({ ...item })),
    md: mapLayoutColumns(canonical, CANONICAL_COLS, COLS_MAP.md),
    sm: mapLayoutColumns(canonical, CANONICAL_COLS, COLS_MAP.sm),
    xs: stackLayout(canonical),
  }
}

function parseCanonicalCache(raw: string): LayoutItem[] | null {
  try {
    const parsed: unknown = JSON.parse(raw)
    const payload = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Partial<PersistedLayoutV2>
      : null
    if (!payload || payload.version !== LAYOUT_VERSION || payload.cols !== CANONICAL_COLS) return null
    const valid = validateLayout(payload.layout, CANONICAL_COLS)
    return valid ? withCanonicalConstraints(valid) : null
  } catch {
    return null
  }
}

function loadLayout(): LayoutItem[] {
  try {
    const currentRaw = localStorage.getItem(LAYOUT_KEY)
    if (currentRaw !== null) {
      return parseCanonicalCache(currentRaw) || DEFAULT_LAYOUT.map((item) => ({ ...item }))
    }
  } catch { /* localStorage 可被禁用 */ }
  return DEFAULT_LAYOUT.map((item) => ({ ...item }))
}

function saveLayout(layout: LayoutItem[]) {
  const valid = validateLayout(layout, CANONICAL_COLS)
  if (!valid) return false
  const payload: PersistedLayoutV2 = {
    version: LAYOUT_VERSION,
    cols: CANONICAL_COLS,
    layout: withCanonicalConstraints(valid),
  }
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}

// ════════════════════════════════════════════════════════════
// 暗色主题（复用 standalone HTML 变量）
// ════════════════════════════════════════════════════════════

const C = {
  bg: '#06101e', p: '#0d192b', p2: '#101e33', line: '#20324c',
  txt: '#eaf2ff', mut: '#8296b0',
  b: '#4b8dff', c: '#22d3ee', g: '#2dd4a6', y: '#f5c451', r: '#ff6577', v: '#a78bfa',
}

const U = 'DATA_UNAVAILABLE'

// ════════════════════════════════════════════════════════════
// 数据访问器（从 standalone HTML JS 迁移为 TypeScript）
// ════════════════════════════════════════════════════════════

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = Record<string, any>

const present = (value: unknown): boolean => value !== null && value !== undefined && value !== ''
const finite = (value: unknown): boolean => present(value) && typeof value === 'number' && Number.isFinite(value)
const list = (value: unknown): unknown[] | null => Array.isArray(value) ? value : null

const pick = (obj: unknown, keys: string[], fallback: unknown = null): unknown => {
  if (!obj || typeof obj !== 'object') return fallback
  for (const key of keys) {
    const v = (obj as Record<string, unknown>)[key]
    if (present(v)) return v
  }
  return fallback
}

const asJson = (v: unknown): Json => (v && typeof v === 'object' ? v as Json : {})

const statusVal = (value: unknown): string => present(value) ? String(value).trim().toUpperCase() : 'UNAVAILABLE'

const statusClass = (value: string): string => {
  const s = value
  if (['REAL', 'COMPLETE', 'DONE', 'ACKED', 'LINK_PROVIDED', 'HEALTHY', 'PASS', 'PASSED'].includes(s)) return 'real'
  if (s.includes('DEGRADED') || s.includes('IN_PROGRESS') || ['PAUSED', 'PENDING', 'READY', 'RUNNING', 'PARTIAL'].includes(s)) return 'warn'
  if (s.includes('DISPUTED') || s.includes('BLOCKED') || s.includes('FAILED') || s.includes('CONFLICT') || s === 'ERROR') return 'bad'
  return 'gray'
}

const num = (value: unknown, digits = 0): string => finite(value) ? Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : U
const pct = (value: unknown): string => {
  if (!finite(value)) return U
  const raw = Number(value), normalized = Math.abs(raw) <= 1 ? raw * 100 : raw
  return `${normalized.toFixed(1)}%`
}
const rankStr = (value: unknown): string => finite(value) && Number(value) > 0 ? `P${Number(value).toFixed(1)}` : U
const millis = (value: unknown): string => !finite(value) ? U : Number(value) >= 1000 ? `${(Number(value) / 1000).toFixed(2)}s` : `${Math.round(Number(value))}ms`
const scalarText = (value: unknown): string => present(value) ? String(value) : U
const dateOnly = (value: unknown): string => present(value) ? String(value).slice(0, 10) : U

const delta = (current: unknown, previous: unknown, lowerBetter = false): string => {
  if (!finite(current) || !finite(previous)) return U
  if (Number(previous) === 0) return '对照基数为 0'
  const change = (Number(current) - Number(previous)) / Number(previous) * 100
  const good = lowerBetter ? change < 0 : change > 0
  return `${change >= 0 ? '+' : ''}${change.toFixed(1)}% · ${good ? '改善' : '观察'}`
}

const worstStatus = (values: unknown[]): string => {
  const rankMap: Record<string, number> = { REAL: 0, COMPLETE: 0, ACKED: 0, DEGRADED: 1, COMPLETE_WITH_DEGRADED: 1, IN_PROGRESS: 1, PAUSED: 1, UNAVAILABLE: 2, DISPUTED: 3, BLOCKED: 3, FAILED: 3 }
  let worst = 'REAL', score = -1
  values.forEach(v => {
    const s = statusVal(v), n = rankMap[s] ?? (s.includes('DEGRADED') ? 1 : s.includes('UNAVAILABLE') ? 2 : s.includes('BLOCKED') || s.includes('FAILED') || s.includes('DISPUTED') ? 3 : 2)
    if (n > score) { score = n; worst = s }
  })
  return worst
}

// ── section provenance ──
type SectionMeta = {
  data_status: string
  source: string
  data_window: string
  known_limitations: string[] | null
  cross_validation: string
  reason: string | null
}

function sectionMeta(section: unknown): SectionMeta {
  const s = (section && typeof section === 'object' ? section : {}) as Json
  const p = (s.provenance && typeof s.provenance === 'object' ? s.provenance : {}) as Json
  return {
    data_status: statusVal(pick(s, ['data_status'], pick(p, ['data_status'], 'UNAVAILABLE'))),
    source: String(pick(s, ['source'], pick(p, ['source'], U))),
    data_window: String(pick(s, ['data_window'], pick(p, ['data_window'], U))),
    known_limitations: list(pick(s, ['known_limitations'], pick(p, ['known_limitations'], null))) as string[] | null,
    cross_validation: String(pick(s, ['cross_validation'], pick(p, ['cross_validation'], U))),
    reason: pick(s, ['reason', 'degraded_reason', 'status_reason', 'error'], pick(p, ['reason', 'degraded_reason'], null)) as string | null,
  }
}

function unavailableSection(reason: string): Json {
  return { data_status: 'UNAVAILABLE', source: U, data_window: U, known_limitations: [reason], cross_validation: U, reason }
}

// ── site level accessors ──
function sectionFor(site: Json | null, primary: string, fallback: string | null, reason: string): Json {
  if (!site) return unavailableSection(reason)
  const value = site[primary]
  if (value && typeof value === 'object') return value as Json
  if (fallback && site[fallback] && typeof site[fallback] === 'object') return site[fallback] as Json
  return unavailableSection(reason)
}

const gscOf = (site: Json | null): Json => sectionFor(site, 'gsc', null, 'GSC 模块缺失')
const ga4Of = (site: Json | null): Json => sectionFor(site, 'ga4', null, 'GA4 模块缺失')
const psiOf = (site: Json | null): Json => sectionFor(site, 'psi', null, 'PSI 模块缺失')
const technicalOf = (site: Json | null): Json => sectionFor(site, 'technical', null, '技术模块缺失')
const reportOf = (site: Json | null): Json => sectionFor(site, 'inspection', 'report', '巡检报告模块缺失')

function executionOf(site: Json | null): Json {
  if (site && site.execution && typeof site.execution === 'object') return site.execution as Json
  return {}
}
function workflowOf(site: Json | null): Json {
  const e = executionOf(site), value = e.workflow || (site && site.workflow)
  return value && typeof value === 'object' ? value as Json : unavailableSection('Workflow 模块缺失')
}
function timelineOf(site: Json | null): Json {
  const e = executionOf(site), value = e.timeline || (site && site.timeline)
  return value && typeof value === 'object' ? value as Json : unavailableSection('Timeline 模块缺失')
}

type SiteInfo = { hostname: string; display_name: string; market: string; timezone: string; site_url: string | null }
function siteInfo(site: Json | null): SiteInfo {
  const s = (site && site.site && typeof site.site === 'object' ? site.site : {}) as Json
  const hostname = String(pick(s, ['hostname', 'domain'], pick(site, ['hostname', 'domain', 'site_id'], U))).replace(/^https?:\/\//, '').replace(/\/$/, '')
  return {
    hostname,
    site_url: pick(s, ['site_url', 'url'], pick(site, ['site_url'], null)) as string | null,
    display_name: String(pick(s, ['display_name', 'name', 'label'], pick(site, ['display_name', 'name'], hostname))),
    market: String(pick(s, ['market'], pick(site, ['market'], U))),
    timezone: String(pick(s, ['timezone'], pick(site, ['timezone'], U))),
  }
}

// ── GSC / GA4 period accessors ──
function periods(gsc: Json): Json {
  return (gsc && typeof gsc.periods === 'object') ? gsc.periods as Json : ((gsc && typeof gsc.kpis === 'object') ? gsc.kpis as Json : {})
}
function period(gsc: Json, name: string): Json | null {
  const p = periods(gsc)
  const aliases: Record<string, string[]> = {
    d0: ['d0', 'latest_day'],
    d1: ['d1', 'previous_day'],
    cur7: ['cur7', 'current_7d', 'last_7d', 'recent_7d'],
    prev7: ['prev7', 'previous_7d', 'prior_7d'],
    cur30: ['cur30', 'current_30d', 'last_30d', 'recent_30d'],
    prev30: ['prev30', 'previous_30d', 'prior_30d'],
  }
  for (const k of aliases[name] || [name]) {
    const v = p[k]
    if (v && typeof v === 'object') return v as Json
  }
  return null
}
function gaTotals(ga4: Json): Json {
  return (ga4 && typeof ga4.totals === 'object') ? ga4.totals as Json : ((ga4 && typeof ga4.kpis === 'object') ? ga4.kpis as Json : {})
}
function gaPeriod(ga4: Json, name: string): Json | null {
  const p = gaTotals(ga4)
  const aliases: Record<string, string[]> = {
    d0: ['d0', 'latest_day'],
    d1: ['d1', 'previous_day'],
    cur7: ['cur7', 'current_7d', 'last_7d', 'recent_7d'],
    prev7: ['prev7', 'previous_7d', 'prior_7d'],
  }
  for (const k of aliases[name] || [name]) {
    const v = p[k]
    if (v && typeof v === 'object') return v as Json
  }
  return null
}

// ════════════════════════════════════════════════════════════
// CSS（暗色主题 + react-grid-layout 覆盖）
// ════════════════════════════════════════════════════════════

const CSS = `
.tw-rgl .react-grid-item {
  transition: all 200ms ease;
  transition-property: left, top, width, height;
}
.tw-rgl .react-grid-item.react-grid-placeholder {
  background: ${C.b} !important;
  opacity: 0.15 !important;
  border-radius: 10px !important;
  border: 2px dashed ${C.b} !important;
}
.tw-rgl .react-resizable-handle {
  opacity: 0;
  transition: opacity .15s;
}
.tw-rgl .react-grid-item:hover .react-resizable-handle {
  opacity: 0.6;
}
.tw-rgl .react-resizable-handle::after {
  content: '';
  position: absolute;
  right: 3px; bottom: 3px;
  width: 8px; height: 8px;
  border-right: 2px solid ${C.b};
  border-bottom: 2px solid ${C.b};
}
.tw-rgl .react-resizable-handle:hover {
  opacity: 1 !important;
}
.tw-rgl .react-grid-item.react-draggable-dragging {
  box-shadow: 0 8px 30px rgba(0,0,0,0.5);
  z-index: 100;
  cursor: grabbing !important;
}
.tw-rgl .react-grid-item > .tw-drag-handle {
  cursor: grab;
}
.tw-rgl .react-grid-item.react-draggable-dragging > .tw-drag-handle {
  cursor: grabbing;
}
@keyframes tw-spin { to { transform: rotate(360deg) } }
.tw-spin { animation: tw-spin 1s linear infinite; display: inline-block; }

/* status tags */
.tw-tag { display: inline-flex; align-items: center; gap: 3px; font-size: 9px; font-weight: 700; padding: 1px 7px; border-radius: 4px; letter-spacing: .03em; white-space: nowrap; }
.tw-tag.real { color: #59e3bd; background: #0a2d28; border: 1px solid #227965; }
.tw-tag.warn { color: #f5c451; background: #2d2810; border: 1px solid #6b5e2b; }
.tw-tag.bad  { color: #ff8a96; background: #2d131b; border: 1px solid #6b2733; }
.tw-tag.gray { color: ${C.mut}; background: #0e1a2c; border: 1px solid ${C.line}; }

/* tables */
.tw-table { width: 100%; border-collapse: collapse; font-size: 10.5px; }
.tw-table th { text-align: left; color: ${C.mut}; font-weight: 600; padding: 4px 6px; border-bottom: 1px solid ${C.line}; white-space: nowrap; }
.tw-table td { padding: 3px 6px; border-bottom: 1px solid ${C.line}30; color: ${C.txt}; }
.tw-table tr:hover td { background: ${C.p2}50; }
.tw-table .tw-empty { color: ${C.mut}; text-align: center; padding: 10px; }

/* status-reason banners */
.tw-reason { font-size: 10px; padding: 4px 8px; border-radius: 4px; margin-top: 4px; }
.tw-reason.warn { background: #2d2810; border-left: 3px solid ${C.y}; color: #f5d878; }
.tw-reason.bad  { background: #2d131b; border-left: 3px solid ${C.r}; color: #ffb8c0; }
.tw-reason.gray { background: #0e1a2c; border-left: 3px solid ${C.line}; color: ${C.mut}; }

@media (max-width: 619px) {
  .tw-rgl .react-grid-item { transition: none; }
  .tw-rgl .react-resizable-handle { display: none !important; }
}
`

// ════════════════════════════════════════════════════════════
// 小组件
// ════════════════════════════════════════════════════════════

const Tag: React.FC<{ status: string }> = ({ status }) => {
  const s = statusVal(status)
  return <span className={`tw-tag ${statusClass(s)}`}>{s}</span>
}

const MetaLine: React.FC<{ section: unknown }> = ({ section }) => {
  const m = sectionMeta(section)
  const limitations = m.known_limitations === null ? U : (m.known_limitations.length ? m.known_limitations.map(scalarText).join('；') : '无已声明局限')
  return (
    <div style={{ fontSize: 9, color: C.mut, borderTop: `1px solid ${C.line}50`, paddingTop: 5, marginTop: 'auto', lineHeight: 1.5 }}>
      【数据来源】<b style={{ color: C.c }}>{m.source}</b>　【data_status】{m.data_status}　【数据窗口】{m.data_window}<br />
      【已知局限】{limitations}　【交叉验证】{m.cross_validation}
    </div>
  )
}

const NoticeBox: React.FC<{ section: unknown }> = ({ section }) => {
  const m = sectionMeta(section)
  if (m.data_status === 'DEGRADED') return <div className="tw-reason warn"><b>DEGRADED：</b>{m.reason || '未提供降级原因'}</div>
  if (m.data_status === 'DISPUTED') return <div className="tw-reason bad"><b>DISPUTED：</b>{m.reason || '未提供分歧原因'}</div>
  if (m.data_status === 'UNAVAILABLE') return <div className="tw-reason gray"><b>DATA_UNAVAILABLE：</b>{m.reason || '本模块没有可用数据'}</div>
  return m.reason ? <div className={`tw-reason ${statusClass(m.data_status)}`}>{m.reason}</div> : null
}

const PanelHeader: React.FC<{ title: string; subtitle?: string; badge?: string; dragHandle?: boolean }> = ({ title, subtitle, badge, dragHandle }) => (
  <div className={dragHandle ? 'tw-drag-handle' : ''} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, paddingBottom: 5, borderBottom: `1px solid ${C.line}`, marginBottom: 7, flexShrink: 0, touchAction: dragHandle ? 'none' : 'auto' }}>
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.txt, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</div>
      {subtitle && <div style={{ fontSize: 9, color: C.mut, marginTop: 1 }}>{subtitle}</div>}
    </div>
    {badge && <Tag status={badge} />}
  </div>
)

const MiniBox: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ background: C.p, border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 8px', display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
    <span style={{ fontSize: 9, color: C.mut }}>{label}</span>
    <b style={{ fontSize: 13, color: C.txt, fontFamily: 'SF Mono, monospace' }}>{children}</b>
  </div>
)

const Bar: React.FC<{ label: string; value: unknown; max: number }> = ({ label, value, max }) => {
  const width = finite(value) && max > 0 ? Math.max(0, Math.min(100, Number(value) / max * 100)) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10 }}>
      <span style={{ color: C.mut, width: 64, flexShrink: 0, textAlign: 'right' }}>{label}</span>
      <i style={{ flex: 1, height: 8, background: C.line, borderRadius: 4, overflow: 'hidden', display: 'block' }}>
        <u style={{ display: 'block', height: '100%', width: `${width.toFixed(1)}%`, background: `linear-gradient(90deg, ${C.b}, ${C.c})`, borderRadius: 4 }} />
      </i>
      <b style={{ color: C.txt, fontFamily: 'SF Mono, monospace', width: 52, textAlign: 'right' }}>{num(value)}</b>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 各面板渲染器
// ════════════════════════════════════════════════════════════

const KpiBar: React.FC<{ site: Json }> = ({ site }) => {
  const g = gscOf(site), ga = ga4Of(site), psi = psiOf(site)
  const g0 = period(g, 'd0'), g1 = period(g, 'd1'), g7 = period(g, 'cur7'), gp7 = period(g, 'prev7')
  const ga0 = gaPeriod(ga, 'd0'), ga1 = gaPeriod(ga, 'd1'), ga7 = gaPeriod(ga, 'cur7')
  const organic = ga.organic_7d || ga.organic7d || null
  const mobile = psi.mobile || null
  const info = siteInfo(site)

  const kpis = [
    { label: `GSC 自然点击 · D0 ${dateOnly(pick(g, ['d0', 'latest_date']))}`, value: num(pick(g0, ['clicks'])), delta: delta(pick(g0, ['clicks']), pick(g1, ['clicks'])), detail: `7日 ${num(pick(g7, ['clicks']))} · 前7日 ${num(pick(gp7, ['clicks']))}`, color: C.b },
    { label: `GSC 展示 · D0 ${dateOnly(pick(g, ['d0', 'latest_date']))}`, value: num(pick(g0, ['impressions'])), delta: delta(pick(g0, ['impressions']), pick(g1, ['impressions'])), detail: `7日 ${num(pick(g7, ['impressions']))} · 前7日 ${num(pick(gp7, ['impressions']))}`, color: C.y },
    { label: 'GSC 加权排名', value: rankStr(pick(g0, ['position', 'weighted_position'])), delta: finite(pick(g1, ['position', 'weighted_position'])) ? `D-1 ${rankStr(pick(g1, ['position', 'weighted_position']))}` : U, detail: '不是实测 SERP 排名', color: C.v },
    { label: `GA4 会话 · D0 ${dateOnly(pick(ga, ['d0', 'latest_date']))}`, value: num(pick(ga0, ['sessions'])), delta: delta(pick(ga0, ['sessions']), pick(ga1, ['sessions'])), detail: `7日总会话 ${num(pick(ga7, ['sessions']))}`, color: C.c },
    { label: '7日 Organic 会话', value: num(pick(organic, ['sessions'])), delta: `参与率 ${pct(pick(organic, ['engagement_rate']))}`, detail: `hostName：${info.hostname === U ? U : info.hostname}`, color: C.g },
    { label: 'PSI Mobile', value: num(pick(mobile, ['performance', 'score']) ? pick(pick(mobile, ['performance', 'score']) instanceof Object ? {} : mobile, ['performance', 'score']) : pick(mobile, ['performance', 'score'])), delta: `LCP ${millis(pick(mobile, ['lcp_ms', 'lcp']))}`, detail: `CLS ${num(pick(mobile, ['cls']), 3)} · TBT ${millis(pick(mobile, ['tbt_ms', 'tbt']))}`, color: C.r },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6, height: '100%', alignContent: 'center' }}>
      {kpis.map((kpi, i) => (
        <div key={i} style={{ background: `linear-gradient(135deg, ${kpi.color}15, transparent)`, border: `1px solid ${kpi.color}30`, borderLeft: `3px solid ${kpi.color}`, borderRadius: 7, padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
          <span style={{ fontSize: 9, color: C.mut, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{kpi.label}</span>
          <strong style={{ fontSize: 18, color: kpi.color, fontFamily: 'SF Mono, monospace', lineHeight: 1.2 }}>{kpi.value}</strong>
          <b style={{ fontSize: 9, color: finite(pick(g0, ['clicks'])) ? C.g : C.mut }}>{kpi.delta}</b>
          <small style={{ fontSize: 8, color: C.mut, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{kpi.detail}</small>
        </div>
      ))}
    </div>
  )
}

const InspectionPanel: React.FC<{ site: Json }> = ({ site }) => {
  const report = reportOf(site), gsc = gscOf(site), ga4 = ga4Of(site), psi = psiOf(site)
  const info = siteInfo(site)
  const gates = list(pick(report, ['gates']))
  const reportStatus = String(pick(report, ['status'], sectionMeta(report).data_status))

  let progress = pick(report, ['progress_pct', 'progress', 'completion_pct'])
  if (!finite(progress) && gates && gates.length) {
    const complete = gates.filter((g) => ['COMPLETE', 'DONE', 'REAL', 'LINK_PROVIDED', 'PASS', 'PASSED', 'COMPLETE_WITH_DEGRADED', 'COMPLETE_WITH_UNAVAILABLE'].includes(statusVal(pick(g, ['status'])))).length
    progress = complete / gates.length * 100
  }
  const progressText = finite(progress) ? `${Math.max(0, Math.min(100, Number(progress))).toFixed(0)}%` : U
  const progressNum = finite(progress) ? Math.max(0, Math.min(100, Number(progress))) : 0

  return (
    <>
      <PanelHeader title="今日巡检报告" subtitle={`${scalarText(info.display_name)} · ${dateOnly(pick(report, ['report_date', 'date']))}`} badge={reportStatus} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative', width: 44, height: 44, flexShrink: 0 }}>
            <svg viewBox="0 0 44 44" width="44" height="44">
              <circle cx="22" cy="22" r="18" fill="none" stroke={C.line} strokeWidth="3" />
              <circle cx="22" cy="22" r="18" fill="none" stroke={progressNum > 0 ? C.g : C.mut} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${(progressNum / 100) * 113} 113`} transform="rotate(-90 22 22)" />
            </svg>
            <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: C.g }}>{progressText}</span>
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.txt }}>{scalarText(pick(report, ['summary', 'headline'], reportStatus || U))}</div>
            <div style={{ fontSize: 9, color: C.mut }}>GSC D0 {dateOnly(pick(gsc, ['d0', 'latest_date']))} · GA4 D0 {dateOnly(pick(ga4, ['d0', 'latest_date']))} · PSI {dateOnly(pick(psi, ['tested_at', 'test_date']))}</div>
          </div>
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {gates === null ? <li style={{ fontSize: 10, color: C.mut }}>{U}</li> : gates.length === 0 ? <li style={{ fontSize: 10, color: C.mut }}>本次真实清单为空</li> : gates.map((g, i) => {
            const s = statusVal(pick(g, ['status'])), cls = statusClass(s)
            return <li key={i} title={String(pick(g, ['reason'], ''))} style={{ fontSize: 10, color: cls === 'real' ? C.g : cls === 'bad' ? C.r : cls === 'warn' ? C.y : C.mut, display: 'flex', gap: 4 }}>
              <span>{cls === 'real' ? '✓' : cls === 'bad' ? '✗' : cls === 'warn' ? '◐' : '○'}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{scalarText(pick(g, ['name'], U))} · {s}</span>
            </li>
          })}
        </ul>
        <NoticeBox section={report} />
        <MetaLine section={report} />
      </div>
    </>
  )
}

const ExecutionPanel: React.FC<{ site: Json }> = ({ site }) => {
  const e = executionOf(site), matrix = list(pick(e, ['module_matrix']))
  const workflow = workflowOf(site), timeline = timelineOf(site)
  const combined = sectionMeta(e).data_status
  const enabled = finite(pick(e, ['enabled_count'])) ? Number(pick(e, ['enabled_count'])) : matrix ? matrix.filter((x) => statusVal(pick(x, ['activation_status'])) === 'ENABLED').length : null
  const completed = finite(pick(e, ['real_count'])) ? Number(pick(e, ['real_count'])) : matrix ? matrix.filter((x) => statusVal(pick(x, ['data_status'])) === 'REAL').length : null
  const total = matrix ? matrix.length : null
  const schedule = pick(e, ['schedule', 'cron_cadence', 'pulse_cadence'])
  const conflict = pick(e, ['reason', 'conflict_reason'], pick(workflow, ['reason'], null))

  return (
    <>
      <PanelHeader title="执行与调度" subtitle="Workflow / Timeline / Hermes Cron" badge={combined} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.txt }}>
          {finite(completed) && finite(total) ? `${completed}/${total} 个模块槽位已有 REAL 结果` : U}
        </div>
        <div style={{ fontSize: 9, color: C.mut }}>已激活 {finite(enabled) ? enabled : U} · 模块优先 / 站点次序 / 每 10 分钟</div>
        {matrix && matrix.length > 0 && (
          <table className="tw-table">
            <thead><tr><th>时间</th><th>模块</th><th>数据</th></tr></thead>
            <tbody>
              {matrix.map((x, i) => (
                <tr key={i}><td>{scalarText(pick(x, ['schedule_hhmm'], U))}</td><td>{scalarText(pick(x, ['module_label', 'module_id'], U))}</td><td><Tag status={String(pick(x, ['data_status']))} /></td></tr>
              ))}
            </tbody>
          </table>
        )}
        {present(schedule) && <div style={{ fontSize: 9, color: C.mut }}>调度：{scalarText(schedule)}</div>}
        {present(conflict) && <div style={{ fontSize: 10, color: C.y, background: '#2d2810', borderRadius: 4, padding: '3px 6px' }}>{scalarText(conflict)}</div>}
        <NoticeBox section={e} />
        <MetaLine section={e} />
      </div>
    </>
  )
}

const FreshnessPanel: React.FC<{ site: Json }> = ({ site }) => {
  const section = (site.freshness && typeof site.freshness === 'object' ? site.freshness : {}) as Json
  const modules = list(pick(section, ['modules']))
  const overall = sectionMeta(section).data_status
  const rows = modules === null ? [] : modules

  return (
    <>
      <PanelHeader title="数据新鲜度" subtitle="每个来源独立 D0，不强行对齐" badge={overall} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        {rows.length === 0 ? <div style={{ color: C.mut, fontSize: 10, textAlign: 'center', padding: 8 }}>{U}</div> : (
          <table className="tw-table">
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>{scalarText(pick(row, ['label', 'module_id'], U))}</td>
                  <td>{scalarText(pick(row, ['freshness'], 'UNKNOWN'))}<div style={{ fontSize: 8, color: C.mut }}>{dateOnly(pick(row, ['collected_at']))}{pick(row, ['reason']) ? ` · ${scalarText(pick(row, ['reason']))}` : ''}</div></td>
                  <td><Tag status={String(pick(row, ['data_status']))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{ fontSize: 9, color: C.mut, marginTop: 4 }}>与今日巡检和执行调度读取同一 module matrix；未启用模块不补零。</div>
      </div>
    </>
  )
}

// ── GSC 趋势图（SVG）──
type TrendPoint = { date: string; clicks: number | null; impressions: number | null; position: number | null }

function cleanTrend(gsc: Json): TrendPoint[] | null {
  const raw = list(pick(gsc, ['trend', 'daily']))
  if (raw === null) return null
  const result: TrendPoint[] = []
  for (const row of raw) {
    const r = row as Json
    // JSON uses `key` for date (compatible with both `key` and `keys[0]`)
    const dateRaw = Array.isArray(r.keys) ? r.keys[0] : pick(r, ['key', 'date', 'day'], null)
    const clicks = pick(r, ['clicks'])
    const impressions = pick(r, ['impressions'])
    const rawPos = pick(r, ['position', 'weighted_position'])
    const date = present(dateRaw) ? String(dateRaw) : U
    result.push({
      date,
      clicks: finite(clicks) ? Number(clicks) : null,
      impressions: finite(impressions) ? Number(impressions) : null,
      position: finite(rawPos) && Number(rawPos) > 0 && (!finite(impressions) || Number(impressions) > 0) ? Number(rawPos) : null,
    })
  }
  return result.filter(row => row.date !== U)
}

const GscTrendPanel: React.FC<{ site: Json }> = ({ site }) => {
  const g = gscOf(site)
  const series = useMemo(() => cleanTrend(g), [g])

  const { paths, ticks, empty } = useMemo(() => {
    if (!series || !series.length) return { paths: null, ticks: [], empty: series === null ? U : '本窗口无真实趋势记录' }
    const W = 800, H = 300, L = 52, R = 54, T = 25, B = 35
    const PW = W - L - R, PH = H - T - B
    const maxLeft = Math.max(1, ...series.flatMap(r => [r.clicks, r.impressions]).filter(v => v !== null).map(Number))
    const maxPosition = Math.max(100, ...series.map(r => r.position).filter(v => v !== null).map(Number))
    const x = (i: number) => series.length === 1 ? L + PW / 2 : L + i * PW / (series.length - 1)
    const yLeft = (v: number) => T + PH - (v / maxLeft) * PH
    const yPos = (v: number) => T + ((v - 1) / (maxPosition - 1)) * PH

    const makePath = (key: 'clicks' | 'impressions' | 'position', yFn: (v: number) => number): string => {
      let d = '', open = false
      series.forEach((r, i) => {
        const v = r[key]
        if (v === null || !finite(v)) { open = false; return }
        d += `${open ? 'L' : 'M'}${x(i).toFixed(1)} ${yFn(v).toFixed(1)} `
        open = true
      })
      return d
    }

    const tickIdx = [0, Math.floor((series.length - 1) / 2), series.length - 1].filter((v, i, a) => a.indexOf(v) === i)

    return {
      paths: {
        impressions: makePath('impressions', yLeft),
        clicks: makePath('clicks', yLeft),
        position: makePath('position', yPos),
        xFn: x, yLeftFn: yLeft, yPosFn: yPos,
        W, H, L, R, T, B, PW, PH, maxLeft, maxPosition,
      },
      ticks: tickIdx.map(i => ({ x: x(i), label: series[i].date.slice(5), y: H - 14 })),
      empty: '',
    }
  }, [series])

  const m = sectionMeta(g)

  return (
    <>
      <PanelHeader title="GSC 点击 / 展示 / 加权排名趋势" subtitle="原生 SVG 双轴 · 零展示日不伪造排名" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        {empty ? (
          <div style={{ display: 'grid', placeItems: 'center', flex: 1, color: C.mut, fontSize: 12 }}>{empty}</div>
        ) : paths ? (
          <>
            <div style={{ display: 'flex', gap: 10, fontSize: 9, color: C.mut, flexShrink: 0 }}>
              <span><i style={{ display: 'inline-block', width: 8, height: 8, background: C.b, borderRadius: 2, marginRight: 3 }} />自然点击</span>
              <span><i style={{ display: 'inline-block', width: 8, height: 8, background: C.y, borderRadius: 2, marginRight: 3 }} />展示量（左轴）</span>
              <span><i style={{ display: 'inline-block', width: 8, height: 8, background: C.v, borderRadius: 2, marginRight: 3 }} />加权排名（右轴反向）</span>
            </div>
            <svg viewBox={`0 0 ${paths.W} ${paths.H}`} style={{ width: '100%', flex: 1, minHeight: 0 }} preserveAspectRatio="none">
              {/* grid lines */}
              {Array.from({ length: 5 }).map((_, i) => {
                const yy = paths.T + i * paths.PH / 4
                return <g key={i}>
                  <line x1={paths.L} y1={yy} x2={paths.W - paths.R} y2={yy} stroke={C.line} strokeWidth="0.5" opacity="0.5" />
                  <text x={paths.L - 6} y={yy + 3} textAnchor="end" fill={C.mut} fontSize="9">{num(paths.maxLeft * (1 - i / 4), 0)}</text>
                  <text x={paths.W - paths.R + 6} y={yy + 3} fill={C.mut} fontSize="9">P{Math.round(1 + (paths.maxPosition - 1) * i / 4)}</text>
                </g>
              })}
              {paths.impressions && <path d={paths.impressions} fill="none" stroke={C.y} strokeWidth="2" />}
              {paths.clicks && <path d={paths.clicks} fill="none" stroke={C.b} strokeWidth="2.5" />}
              {paths.position && <path d={paths.position} fill="none" stroke={C.v} strokeWidth="2" strokeDasharray="5 4" />}
              {ticks.map((t, i) => <text key={i} x={t.x} y={t.y} textAnchor="middle" fill={C.mut} fontSize="9">{t.label}</text>)}
            </svg>
          </>
        ) : null}
        <NoticeBox section={g} />
        <MetaLine section={g} />
      </div>
    </>
  )
}

// ── GA4 世界地图 ──
const WORLD_POINTS: Record<string, [number, number, string]> = {
  'United States': [22, 38, '美国'], US: [22, 38, '美国'], USA: [22, 38, '美国'],
  Canada: [18, 25, '加拿大'], Mexico: [20, 48, '墨西哥'], Brazil: [28, 69, '巴西'],
  Spain: [48, 35, '西班牙'], France: [49, 31, '法国'], Germany: [52, 29, '德国'],
  'United Kingdom': [47, 26, '英国'], UK: [47, 26, '英国'],
  Netherlands: [50, 28, '荷兰'], Italy: [52, 36, '意大利'], Russia: [66, 23, '俄罗斯'],
  India: [68, 52, '印度'], China: [75, 41, '中国'], Japan: [86, 41, '日本'],
  'South Korea': [83, 40, '韩国'], Singapore: [77, 65, '新加坡'],
  Australia: [88, 79, '澳大利亚'], 'New Zealand': [94, 88, '新西兰'],
}

const Ga4MapPanel: React.FC<{ site: Json }> = ({ site }) => {
  const ga = ga4Of(site)
  const countries = list(pick(ga, ['countries']))
  const m = sectionMeta(ga)

  const located = useMemo(() => {
    if (!countries) return []
    return countries.filter((row) => {
      const r = row as Json
      if (finite(pick(r, ['x'])) && finite(pick(r, ['y']))) return true
      const name = String(pick(r, ['country', 'name', 'country_name'], U))
      return !!(WORLD_POINTS[name] || WORLD_POINTS[name.toUpperCase()])
    })
  }, [countries])

  const unlocated = useMemo(() => {
    if (!countries) return []
    return countries.filter((row) => {
      const r = row as Json
      if (finite(pick(r, ['x'])) && finite(pick(r, ['y']))) return false
      const name = String(pick(r, ['country', 'name', 'country_name'], U))
      return !(WORLD_POINTS[name] || WORLD_POINTS[name.toUpperCase()])
    })
  }, [countries])

  const maxSessions = Math.max(1, ...located.map((r) => { const v = pick(r as Json, ['sessions']); return finite(v) ? Number(v) : 0 }))

  const emptyText = !countries ? U : !countries.length ? '本窗口无真实国家记录' : ''

  return (
    <>
      <PanelHeader title="GA4 世界来访地图" subtitle="国家点位 = GA4 sessions / users" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        {emptyText ? (
          <div style={{ display: 'grid', placeItems: 'center', flex: 1, color: C.mut, fontSize: 12 }}>{emptyText}</div>
        ) : (
          <>
            <svg viewBox="0 0 760 320" style={{ width: '100%', flex: 1, minHeight: 0 }} preserveAspectRatio="xMidYMid meet">
              <defs>
                <pattern id="twMapGrid" width="38" height="32" patternUnits="userSpaceOnUse">
                  <path d="M38 0H0V32" fill="none" stroke="#27415e" strokeWidth="0.5" opacity="0.45" />
                </pattern>
              </defs>
              <rect width="760" height="320" fill="url(#twMapGrid)" />
              {/* simplified continents */}
              <g fill="#183451" stroke="#31577d" strokeWidth="1.2">
                <path d="M70 68 L130 35 210 42 245 78 212 112 165 115 132 150 104 134 88 98 Z" />
                <path d="M205 154 L240 170 250 234 218 294 190 258 198 208 179 175 Z" />
                <path d="M350 110 L408 96 453 119 447 164 418 185 401 245 370 226 357 173 333 143 Z" />
                <path d="M420 64 L514 38 622 56 684 91 666 130 610 127 570 161 515 153 485 126 438 119 Z" />
                <path d="M623 208 L684 206 718 238 690 268 638 263 610 235 Z" />
              </g>
              {located.map((row, i) => {
                const r = asJson(row)
                let px = 0, py = 0, label = U
                if (finite(pick(r, ['x'])) && finite(pick(r, ['y']))) {
                  px = Number(pick(r, ['x'])); py = Number(pick(r, ['y']))
                  label = String(pick(r, ['label', 'country_zh'], String(pick(r, ['country', 'name', 'country_name'], U))))
                } else {
                  const name = String(pick(r, ['country', 'name', 'country_name'], U))
                  const pt = WORLD_POINTS[name] || WORLD_POINTS[name.toUpperCase()]
                  if (!pt) return null
                  px = pt[0]; py = pt[1]; label = pt[2]
                }
                const cx = px * 7.6, cy = py * 3.2
                const sessions = finite(pick(r, ['sessions'])) ? Number(pick(r, ['sessions'])) : 0
                const radius = 5 + sessions / maxSessions * 10
                return (
                  <g key={i}>
                    <circle cx={cx} cy={cy} r={radius + 6} fill={C.c} opacity="0.12" />
                    <circle cx={cx} cy={cy} r={radius} fill={C.c} stroke="#071120" strokeWidth="1" />
                    <text x={cx + radius + 4} y={cy - 2} fill={C.txt} fontSize="8">{label}</text>
                    <text x={cx + radius + 4} y={cy + 9} fill={C.mut} fontSize="7">{num(pick(r, ['sessions']))} sessions</text>
                  </g>
                )
              })}
            </svg>
            {unlocated.length > 0 && (
              <div style={{ fontSize: 9, color: C.mut }}>
                <b>未定位国家：</b>{unlocated.map((r) => `${scalarText(pick(r as Json, ['country', 'name', 'country_name'], U))}（会话 ${num(pick(r as Json, ['sessions']))}）`).join(' · ')}
              </div>
            )}
          </>
        )}
        <NoticeBox section={ga} />
        <MetaLine section={ga} />
      </div>
    </>
  )
}

// ── GSC 搜索表现 ──
const GscSearchPanel: React.FC<{ site: Json }> = ({ site }) => {
  const g = gscOf(site)
  const g7 = period(g, 'cur7'), gp7 = period(g, 'prev7'), g30 = period(g, 'cur30')
  const vals = [pick(gp7, ['clicks']), pick(g7, ['clicks']), pick(gp7, ['impressions']), pick(g7, ['impressions'])]
  const max = Math.max(1, ...vals.filter(finite).map(Number))
  const m = sectionMeta(g)

  return (
    <>
      <PanelHeader title="GSC 搜索表现" subtitle="官方 Search Analytics 口径；GSC 与 GA4 不合并" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <Bar label="前7日点击" value={vals[0]} max={max} />
          <Bar label="近7日点击" value={vals[1]} max={max} />
          <Bar label="前7日展示" value={vals[2]} max={max} />
          <Bar label="近7日展示" value={vals[3]} max={max} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))', gap: 4 }}>
          <MiniBox label="7日点击变化">{delta(vals[1], vals[0])}</MiniBox>
          <MiniBox label="7日展示变化">{delta(vals[3], vals[2])}</MiniBox>
          <MiniBox label="30日点击">{num(pick(g30, ['clicks']))}</MiniBox>
          <MiniBox label="30日展示">{num(pick(g30, ['impressions']))}</MiniBox>
          <MiniBox label="7日 CTR">{pct(pick(g7, ['ctr']))}</MiniBox>
          <MiniBox label="7日加权排名">{rankStr(pick(g7, ['position', 'weighted_position']))}</MiniBox>
        </div>
        <NoticeBox section={g} />
        <MetaLine section={g} />
      </div>
    </>
  )
}

// ── GA4 用户行为 ──
const Ga4BehaviorPanel: React.FC<{ site: Json }> = ({ site }) => {
  const ga = ga4Of(site)
  const ga0 = gaPeriod(ga, 'd0'), ga1 = gaPeriod(ga, 'd1'), ga7 = gaPeriod(ga, 'cur7')
  const organic = ga.organic_7d || ga.organic7d || null
  const info = siteInfo(site)
  const gaVals = [pick(ga1, ['sessions']), pick(ga0, ['sessions']), pick(organic, ['sessions']), pick(ga7, ['sessions'])]
  const gaMax = Math.max(1, ...gaVals.filter(finite).map(Number))
  const m = sectionMeta(ga)

  return (
    <>
      <PanelHeader title="GA4 用户行为" subtitle={`GA4 Data API · hostName=${info.hostname}`} badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <Bar label="D-1 会话" value={gaVals[0]} max={gaMax} />
          <Bar label="D0 会话" value={gaVals[1]} max={gaMax} />
          <Bar label="7日 Organic" value={gaVals[2]} max={gaMax} />
          <Bar label="7日总会话" value={gaVals[3]} max={gaMax} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))', gap: 4 }}>
          <MiniBox label="7日总用户">{num(pick(ga7, ['users']))}</MiniBox>
          <MiniBox label="7日新用户">{num(pick(ga7, ['new_users']))}</MiniBox>
          <MiniBox label="7日参与会话">{num(pick(ga7, ['engaged_sessions']))}</MiniBox>
          <MiniBox label="7日参与率">{pct(pick(ga7, ['engagement_rate']))}</MiniBox>
          <MiniBox label="关键事件">{num(pick(ga7, ['key_events', 'conversions']))}</MiniBox>
          <MiniBox label="Organic 参与率">{pct(pick(organic, ['engagement_rate']))}</MiniBox>
        </div>
        <NoticeBox section={ga} />
        <MetaLine section={ga} />
      </div>
    </>
  )
}

// ── 关键词机会 ──
const KeywordsPanel: React.FC<{ site: Json }> = ({ site }) => {
  const g = gscOf(site)
  const keywords = list(pick(g, ['keywords', 'queries']))
  const m = sectionMeta(g)

  return (
    <>
      <PanelHeader title="关键词机会" subtitle="GSC 查询维度 · 近 7 个完整日" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        {keywords === null ? <div style={{ color: C.mut, fontSize: 10, textAlign: 'center', padding: 10 }}>{U}</div> : (
          <table className="tw-table">
            <thead><tr><th>查询词</th><th>展示</th><th>点击</th><th>CTR</th><th>位置</th></tr></thead>
            <tbody>
              {keywords.length === 0 ? <tr><td colSpan={5} className="tw-empty">本窗口无真实关键词记录</td></tr> : keywords.slice(0, 30).map((r, i) => {
                const row = r as Json
                return <tr key={i}>
                  <td title={String(pick(row, ['key', 'query', 'keyword'], U))} style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{scalarText(pick(row, ['key', 'query', 'keyword'], U))}</td>
                  <td>{num(pick(row, ['impressions']))}</td>
                  <td>{num(pick(row, ['clicks']))}</td>
                  <td>{pct(pick(row, ['ctr']))}</td>
                  <td>{rankStr(pick(row, ['position', 'weighted_position']))}</td>
                </tr>
              })}
            </tbody>
          </table>
        )}
        <NoticeBox section={g} />
        <MetaLine section={g} />
      </div>
    </>
  )
}

// ── 落地页行为 ──
const LandingPanel: React.FC<{ site: Json }> = ({ site }) => {
  const ga = ga4Of(site)
  const landing = list(pick(ga, ['landing_pages', 'pages']))
  const m = sectionMeta(ga)

  return (
    <>
      <PanelHeader title="落地页行为" subtitle="GA4 Landing Page · 近 7 日" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        {landing === null ? <div style={{ color: C.mut, fontSize: 10, textAlign: 'center', padding: 10 }}>{U}</div> : (
          <table className="tw-table">
            <thead><tr><th>页面</th><th>会话</th><th>用户</th><th>参与率</th><th>关键事件</th></tr></thead>
            <tbody>
              {landing.length === 0 ? <tr><td colSpan={5} className="tw-empty">本窗口无真实落地页记录</td></tr> : landing.slice(0, 30).map((r, i) => {
                const row = r as Json
                return <tr key={i}>
                  <td title={String(pick(row, ['path', 'landing_page', 'page'], U))} style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{scalarText(pick(row, ['path', 'landing_page', 'page'], U))}</td>
                  <td>{num(pick(row, ['sessions']))}</td>
                  <td>{num(pick(row, ['users']))}</td>
                  <td>{pct(pick(row, ['engagement_rate']))}</td>
                  <td>{num(pick(row, ['key_events', 'events', 'conversions']))}</td>
                </tr>
              })}
            </tbody>
          </table>
        )}
        <NoticeBox section={ga} />
        <MetaLine section={ga} />
      </div>
    </>
  )
}

// ── 内容与收录健康 ──
const ContentPanel: React.FC<{ site: Json }> = ({ site }) => {
  const tech = technicalOf(site)
  const m = sectionMeta(tech)

  // Try content_indexing (newer schema) first, then technical.content/indexing
  const ci = (site.content_indexing && typeof site.content_indexing === 'object') ? site.content_indexing as Json : null
  const techContent = tech.content && typeof tech.content === 'object' ? tech.content as Json : {}
  const techIndexing = tech.indexing && typeof tech.indexing === 'object' ? tech.indexing as Json : unavailableSection('URL Inspection 数据缺失')
  const broken = tech.suspected_broken_links || null

  if (ci) {
    // Newer schema
    const dbCounts = (ci.db_counts && typeof ci.db_counts === 'object') ? ci.db_counts as Json : {}
    const urlInsp = (ci.url_inspection && typeof ci.url_inspection === 'object') ? ci.url_inspection as Json : {}
    const indexed = pick(urlInsp, ['indexed_pass_count'])
    const ciStatus = sectionMeta(ci).data_status

    return (
      <>
        <PanelHeader title="内容与收录健康" subtitle="数据库 / sitemap / URL Inspection" badge={ciStatus} dragHandle />
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(85px, 1fr))', gap: 4 }}>
            <MiniBox label="Sitemap URL">{num(pick(ci, ['sitemap_url_count']))}</MiniBox>
            <MiniBox label="数据库文章">{num(pick(dbCounts, ['total']))}</MiniBox>
            <MiniBox label="Published">{num(pick(dbCounts, ['published']))}</MiniBox>
            <MiniBox label="Draft">{num(pick(dbCounts, ['draft']))}</MiniBox>
            <MiniBox label="已索引 URL">{num(indexed)}</MiniBox>
            <MiniBox label="检查成功/请求">{num(pick(urlInsp, ['successful']))}/{num(pick(urlInsp, ['requested']))}</MiniBox>
          </div>
          {(() => {
            const cs = pick(urlInsp, ['coverage_state'])
            if (!cs || typeof cs !== 'object') return null
            return (
              <div style={{ fontSize: 9, color: C.mut }}>
                <b>收录分布：</b>{Object.entries(asJson(cs)).map(([k, v]) => `${scalarText(k)}=${num(v)}`).join(' · ')}
              </div>
            )
          })()}
          <NoticeBox section={ci} />
          <MetaLine section={ci} />
        </div>
      </>
    )
  }

  // Fallback: old schema
  const indexed = pick(techIndexing, ['indexed_urls', 'count'])
  return (
    <>
      <PanelHeader title="内容与收录健康" subtitle="数据库 / sitemap / URL Inspection" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(85px, 1fr))', gap: 4 }}>
          <MiniBox label="Sitemap URL">{num(pick(tech, ['sitemap_urls']))}</MiniBox>
          <MiniBox label="数据库文章">{num(pick(techContent, ['total']))}</MiniBox>
          <MiniBox label="Published">{num(pick(techContent, ['published']))}</MiniBox>
          <MiniBox label="Draft">{num(pick(techContent, ['draft']))}</MiniBox>
          <MiniBox label="已索引 URL">{num(indexed)}</MiniBox>
          <MiniBox label="收录状态">{sectionMeta(techIndexing).data_status}</MiniBox>
        </div>
        <NoticeBox section={tech} />
        <MetaLine section={tech} />
      </div>
    </>
  )
}

// ── PSI / Core Web Vitals ──
const PsiDevice: React.FC<{ label: string; device: unknown }> = ({ label, device }) => {
  if (!device || typeof device !== 'object') {
    return (
      <div style={{ background: C.p, border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <b style={{ fontSize: 11, color: C.txt }}>{label}</b>
          <Tag status="UNAVAILABLE" />
        </div>
        <div style={{ color: C.mut, fontSize: 10, marginTop: 2 }}>{U}</div>
      </div>
    )
  }
  const d = device as Json
  const m = sectionMeta(d)
  const score = pick(d, ['performance', 'score'])
  const scoreNum = finite(score) ? Number(score) : null

  return (
    <div style={{ background: C.p, border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <b style={{ fontSize: 11, color: C.txt }}>{label}</b>
        <Tag status={m.data_status} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3 }}>
        <span style={{ fontSize: 22, fontWeight: 800, fontFamily: 'SF Mono, monospace', color: scoreNum !== null && scoreNum >= 90 ? C.g : scoreNum !== null ? C.y : C.mut }}>{num(score)}</span>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, flex: 1 }}>
          <MiniBox label="FCP">{millis(pick(d, ['fcp_ms', 'fcp']))}</MiniBox>
          <MiniBox label="LCP">{millis(pick(d, ['lcp_ms', 'lcp']))}</MiniBox>
          <MiniBox label="CLS">{num(pick(d, ['cls']), 3)}</MiniBox>
          <MiniBox label="TBT">{millis(pick(d, ['tbt_ms', 'tbt']))}</MiniBox>
        </div>
      </div>
      {m.data_status === 'DEGRADED' && <div className="tw-reason warn"><b>DEGRADED：</b>{m.reason || '未提供降级原因'}</div>}
      {m.data_status === 'UNAVAILABLE' && <NoticeBox section={d} />}
    </div>
  )
}

const PsiPanel: React.FC<{ site: Json }> = ({ site }) => {
  const psi = psiOf(site)
  const m = sectionMeta(psi)
  return (
    <>
      <PanelHeader title="PageSpeed / Core Web Vitals" subtitle="Lighthouse 实验室数据；TBT 不替代 INP" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
        <PsiDevice label="Mobile" device={psi.mobile} />
        <PsiDevice label="Desktop" device={psi.desktop} />
        <NoticeBox section={psi} />
        <MetaLine section={psi} />
      </div>
    </>
  )
}

// ── 技术 SEO 快照 ──
const TechnicalPanel: React.FC<{ site: Json }> = ({ site }) => {
  const tech = technicalOf(site)
  const m = sectionMeta(tech)
  return (
    <>
      <PanelHeader title="技术 SEO 快照" subtitle="直接 HTTPS crawl；sitemap 不等于已索引" badge={m.data_status} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(85px, 1fr))', gap: 4 }}>
          <MiniBox label="HTTP 200">{num(pick(tech, ['http_200']))} / {num(pick(tech, ['crawled_urls']))}</MiniBox>
          <MiniBox label="Canonical 冲突">{num(pick(tech, ['canonical_conflicts']))}</MiniBox>
          <MiniBox label="缺失 Title">{num(pick(tech, ['missing_titles']))}</MiniBox>
          <MiniBox label="缺失 Description">{num(pick(tech, ['missing_descriptions']))}</MiniBox>
          <MiniBox label="hreflang 问题">{num(pick(tech, ['hreflang_issues']))}</MiniBox>
          <MiniBox label="重复 Title 组">{num(pick(tech, ['duplicate_title_groups']))}</MiniBox>
          <MiniBox label="Robots HTTP">{num(pick(tech, ['robots_status']))}</MiniBox>
          <MiniBox label="Sitemap HTTP">{num(pick(tech, ['sitemap_status']))}</MiniBox>
          <MiniBox label="Sitemap URL">{num(pick(tech, ['sitemap_urls']))}</MiniBox>
        </div>
        <NoticeBox section={tech} />
        <MetaLine section={tech} />
      </div>
    </>
  )
}

// ── 巡检报告进度 ──
const InspectionFlowPanel: React.FC<{ site: Json }> = ({ site }) => {
  const report = reportOf(site)
  const gates = list(pick(report, ['gates']))
  const reportStatus = String(pick(report, ['status'], sectionMeta(report).data_status))

  return (
    <>
      <PanelHeader title="每日巡检报告进度" subtitle="完成 = 采集 + 验证 + 结论 + Asset + 飞书回读" badge={reportStatus} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
        {gates === null ? <div style={{ color: C.mut, fontSize: 10 }}>{U}</div> : gates.length === 0 ? <div style={{ color: C.mut, fontSize: 10 }}>本次真实门禁清单为空</div> : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
            {gates.map((g, i) => {
              const gate = g as Json
              const s = statusVal(pick(gate, ['status']))
              const cls = statusClass(s)
              const color = cls === 'real' ? C.g : cls === 'bad' ? C.r : cls === 'warn' ? C.y : C.mut
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  {i > 0 && <span style={{ color: C.mut, fontSize: 10 }}>›</span>}
                  <div title={String(pick(gate, ['reason'], ''))} style={{ background: `${color}15`, border: `1px solid ${color}40`, borderRadius: 5, padding: '3px 6px', fontSize: 9, color, textAlign: 'center', lineHeight: 1.3 }}>
                    {scalarText(pick(gate, ['name'], U))}<br />{s}
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
          <MiniBox label="Asset Hub">{scalarText(pick(report, ['asset_status'], U))}</MiniBox>
          <MiniBox label="飞书回读">{scalarText(pick(report, ['feishu_status'], U))}</MiniBox>
        </div>
        <div style={{ fontSize: 8, color: C.mut }}>asset_id: {scalarText(pick(report, ['asset_id'], U))}</div>
        <NoticeBox section={report} />
        <MetaLine section={report} />
      </div>
    </>
  )
}

// ── Workflow / Timeline ──
const WorkflowTimelinePanel: React.FC<{ site: Json }> = ({ site }) => {
  const workflow = workflowOf(site), timeline = timelineOf(site)
  const items = list(pick(workflow, ['items'])), timelines = list(pick(timeline, ['items']))
  const overall = worstStatus([sectionMeta(workflow).data_status, sectionMeta(timeline).data_status])

  return (
    <>
      <PanelHeader title="Workflow / Timeline 真实进度" subtitle="系统状态、Hermes 进程、业务证据" badge={overall} dragHandle />
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
        {/* Workflow section */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.c, marginBottom: 3 }}>Workflow</div>
          {items === null ? <div style={{ fontSize: 10, color: C.mut }}>Workflow {U}</div> : items.length === 0 ? <div style={{ fontSize: 10, color: C.mut }}>0 个真实 Workflow 实例</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {items.map((item, i) => {
                const it = item as Json
                const completed = pick(it, ['completed_nodes']), total = pick(it, ['total_nodes'])
                const progress = finite(total) && Number(total) > 0 && finite(completed) ? Number(completed) / Number(total) * 100 : 0
                const business = statusVal(pick(it, ['business_status']))
                const reason = pick(it, ['reason', 'blocked_reason', 'evidence_summary'])
                return (
                  <div key={i} style={{ background: C.p, border: `1px solid ${C.line}`, borderRadius: 5, padding: '4px 6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4 }}>
                      <div style={{ minWidth: 0 }}>
                        <b style={{ fontSize: 10, color: C.txt }}>{scalarText(pick(it, ['name', 'title'], U))}</b>
                        <div style={{ fontSize: 8, color: C.mut }}>{scalarText(pick(it, ['instance_id', 'id'], U))}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                        <Tag status={String(pick(it, ['system_status', 'status']))} />
                        <Tag status={business} />
                      </div>
                    </div>
                    <div style={{ height: 3, background: C.line, borderRadius: 2, marginTop: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, progress))}%`, background: C.b, transition: 'width .3s' }} />
                    </div>
                    <div style={{ fontSize: 8, color: C.mut, marginTop: 2 }}>节点 {num(completed)}/{num(total)} · 当前 {scalarText(pick(it, ['current_node'], U))} · run_id {scalarText(pick(it, ['hermes_run_id', 'run_id'], U))}</div>
                    {present(reason) && <div style={{ fontSize: 9, color: statusClass(business) === 'bad' ? C.r : C.y, marginTop: 2 }}>{scalarText(reason)}</div>}
                  </div>
                )
              })}
            </div>
          )}
        </div>
        {/* Timeline section */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.c, marginBottom: 3 }}>Timeline</div>
          {timelines === null ? <div style={{ fontSize: 10, color: C.mut }}>Timeline {U}</div> : timelines.length === 0 ? <div style={{ fontSize: 10, color: C.mut }}>0 个真实 Timeline 项</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {timelines.map((item, i) => {
                const it = item as Json
                return (
                  <div key={i} style={{ background: C.p, border: `1px solid ${C.line}`, borderRadius: 5, padding: '4px 6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4 }}>
                      <div style={{ minWidth: 0 }}>
                        <b style={{ fontSize: 10, color: C.txt }}>{scalarText(pick(it, ['intent', 'name', 'title'], U))}</b>
                        <div style={{ fontSize: 8, color: C.mut }}>{scalarText(pick(it, ['node_id', 'id'], U))} · {scalarText(pick(it, ['scheduled_at', 'next_run'], U))}</div>
                      </div>
                      <Tag status={String(pick(it, ['runtime_state', 'state', 'status']))} />
                    </div>
                    <div style={{ fontSize: 8, color: C.mut, marginTop: 1 }}>kind {scalarText(pick(it, ['kind'], U))} · run_id {scalarText(pick(it, ['hermes_run_id', 'run_id'], U))}</div>
                    {present(pick(it, ['reason', 'blocked_reason'])) && <div style={{ fontSize: 9, color: C.y, marginTop: 1 }}>{scalarText(pick(it, ['reason', 'blocked_reason']))}</div>}
                  </div>
                )
              })}
            </div>
          )}
        </div>
        <MetaLine section={workflow} />
        <div style={{ fontSize: 9, color: C.mut, borderTop: `1px solid ${C.line}50`, paddingTop: 3 }}>Timeline：{sectionMeta(timeline).source} · {sectionMeta(timeline).data_window}</div>
      </div>
    </>
  )
}

// ════════════════════════════════════════════════════════════
// 主组件
// ════════════════════════════════════════════════════════════

const ResponsiveGridLayout = WidthProvider(Responsive)

export const SeoControlTowerGridPanel: React.FC = () => {
  const isMobile = useIsMobile()

  // ── 数据状态 ──
  const [repository, setRepository] = useState<Map<string, Json>>(new Map())
  const [activeHost, setActiveHost] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [overallStatus, setOverallStatus] = useState('UNAVAILABLE')

  // ── 布局状态 ──
  const [layout, setLayout] = useState<LayoutItem[]>(loadLayout)
  const [editMode, setEditMode] = useState(false)
  const [activeBreakpoint, setActiveBreakpoint] = useState<GridBreakpoint>('lg')
  const layoutChangeArmedRef = useRef(false)
  const layouts = useMemo(() => buildAllLayouts(layout), [layout])

  const site = repository.get(activeHost) || null

  const loadData = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const response = await fetch('/static/preview/seo-control-tower-sites.json', { cache: 'no-store', headers: { Accept: 'application/json' } })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const body: Json = await response.json()
      const raw = body.sites
      if (!raw || (typeof raw !== 'object')) throw new Error('缺少 sites 对象')
      const entries = Array.isArray(raw) ? raw.map((s: unknown) => [null, s] as [string | null, unknown]) : Object.entries(raw)
      const out = new Map<string, Json>()
      for (const [key, value] of entries) {
        if (!value || typeof value !== 'object') continue
        let v = value as Json
        if (!v.site || typeof v.site !== 'object') v = { ...v, site: { hostname: key || pick(v, ['hostname', 'domain'], null) } }
        else if (!present(pick(v.site, ['hostname'])) && key) v = { ...v, site: { ...v.site, hostname: key } }
        const hostname = siteInfo(v).hostname.toLowerCase()
        if (hostname && hostname !== U.toLowerCase()) out.set(hostname, v)
      }
      if (!out.size) throw new Error('sites 中没有有效站点对象')
      setRepository(out)
      // Pick default: URL ?site param > body.default_site > mejorsiptv.shop > first
      const queryHost = new URL(window.location.href).searchParams.get('site')?.toLowerCase()
      const preferred = (queryHost && out.has(queryHost)) ? queryHost
        : out.has(String(body.default_site || '').toLowerCase()) ? String(body.default_site).toLowerCase()
        : out.has('mejorsiptv.shop') ? 'mejorsiptv.shop'
        : Array.from(out.keys())[0] || ''
      setActiveHost(prev => out.has(prev) ? prev : preferred)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
      setRepository(new Map())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // ── 计算全局状态 ──
  useEffect(() => {
    if (!site) { setOverallStatus('UNAVAILABLE'); return }
    const statuses = [gscOf(site), ga4Of(site), psiOf(site), technicalOf(site), reportOf(site), workflowOf(site), timelineOf(site)].map(s => sectionMeta(s).data_status)
    setOverallStatus(worstStatus(statuses))
  }, [site])

  // ── 布局回调 ──
  const persistBreakpointLayout = useCallback((breakpointLayout: LayoutItem[]) => {
    if (activeBreakpoint === 'xs') return
    const cols = COLS_MAP[activeBreakpoint]
    const valid = validateLayout(breakpointLayout, cols)
    if (!valid) return
    const canonical = withCanonicalConstraints(
      activeBreakpoint === 'lg'
        ? compactVertically(valid)
        : mapLayoutColumns(valid, cols, CANONICAL_COLS),
    )
    const canonicalValid = validateLayout(canonical, CANONICAL_COLS)
    if (!canonicalValid) return
    const next = withCanonicalConstraints(canonicalValid)
    setLayout(next)
    saveLayout(next)
  }, [activeBreakpoint])

  const armLayoutChange = useCallback(() => {
    if (activeBreakpoint !== 'xs') layoutChangeArmedRef.current = true
  }, [activeBreakpoint])

  const finishLayoutChange = useCallback((breakpointLayout: readonly LayoutItem[]) => {
    if (!layoutChangeArmedRef.current) return
    layoutChangeArmedRef.current = false
    persistBreakpointLayout(breakpointLayout.map((item) => ({ ...item })))
  }, [persistBreakpointLayout])

  const resetLayout = () => {
    const defaults = DEFAULT_LAYOUT.map((item) => ({ ...item }))
    localStorage.removeItem(LAYOUT_KEY)
    setLayout(defaults)
    saveLayout(defaults)
  }

  const info = site ? siteInfo(site) : null
  const hostOptions = Array.from(repository.keys()).sort()

  const renderModuleContent = (modId: TowerModuleId): React.ReactNode => {
    if (!site) return <div style={{ color: C.mut, textAlign: 'center', padding: 20, fontSize: 12 }}>{U}</div>
    switch (modId) {
      case 'kpi-bar':           return <KpiBar site={site} />
      case 'inspection':        return <InspectionPanel site={site} />
      case 'execution':         return <ExecutionPanel site={site} />
      case 'freshness':         return <FreshnessPanel site={site} />
      case 'gsc-trend':         return <GscTrendPanel site={site} />
      case 'ga4-map':           return <Ga4MapPanel site={site} />
      case 'gsc-search':        return <GscSearchPanel site={site} />
      case 'ga4-behavior':      return <Ga4BehaviorPanel site={site} />
      case 'keywords':          return <KeywordsPanel site={site} />
      case 'landing':           return <LandingPanel site={site} />
      case 'content':           return <ContentPanel site={site} />
      case 'psi':               return <PsiPanel site={site} />
      case 'technical':         return <TechnicalPanel site={site} />
      case 'inspection-flow':   return <InspectionFlowPanel site={site} />
      case 'workflow-timeline': return <WorkflowTimelinePanel site={site} />
    }
  }

  // ═══ 加载中 / 错误 ═══
  if (loading && repository.size === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: C.mut, padding: 40, fontSize: 13 }}>
        <span className="tw-spin" style={{ width: 16, height: 16, border: `2px solid ${C.line}`, borderTopColor: C.b, borderRadius: '50%' }} />
        正在加载大屏数据...
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minHeight: 0, width: '100%', height: '100%', overflow: 'hidden' }}>
      <style>{CSS}</style>

      {/* ── 顶部工具栏 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6, flexShrink: 0 }}>
        {/* Site selector */}
        <select
          value={activeHost}
          onChange={e => setActiveHost(e.target.value)}
          style={{ background: C.p, color: C.txt, border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 8px', fontSize: 11, minWidth: 160 }}
        >
          {hostOptions.length === 0 && <option value="">—</option>}
          {hostOptions.map(host => {
            const s = repository.get(host)
            const displayName = s ? siteInfo(s).display_name : host
            return <option key={host} value={host}>{displayName} · {host}</option>
          })}
        </select>

        {/* Overall status pill */}
        <span className={`tw-tag ${statusClass(overallStatus)}`}>● {overallStatus}</span>

        {/* Market pill */}
        {info && <span style={{ fontSize: 10, color: C.mut, border: `1px solid ${C.line}`, background: C.p, padding: '3px 7px', borderRadius: 6 }}>市场：{info.market}</span>}

        {/* Refresh button */}
        <button onClick={loadData} style={{ background: C.p, color: C.txt, border: `1px solid ${C.line}`, borderRadius: 6, padding: '4px 8px', fontSize: 10, cursor: 'pointer' }}>↻ 刷新</button>

        {/* Edit mode toggle */}
        {!isMobile && (
          <button onClick={() => setEditMode(!editMode)} style={{ marginLeft: 'auto', background: editMode ? `${C.y}20` : C.p, color: editMode ? C.y : C.mut, border: `1px solid ${editMode ? C.y : C.line}`, borderRadius: 6, padding: '4px 10px', fontSize: 10, cursor: 'pointer' }}>
            {editMode ? '✏️ 编辑布局中' : '✏️ 编辑布局'}
          </button>
        )}
      </div>

      {/* Edit mode toolbar */}
      {editMode && !isMobile && (
        <div style={{ background: `${C.y}15`, border: `1px solid ${C.y}40`, borderRadius: 6, padding: '5px 10px', display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexShrink: 0 }}>
          <span style={{ color: C.y, fontSize: 11, fontWeight: 600 }}>✏️ 布局编辑模式</span>
          <span style={{ color: C.mut, fontSize: 10 }}>拖拽模块标题移动 · 拖右下角调整大小</span>
          <button onClick={resetLayout} style={{ marginLeft: 'auto', padding: '3px 8px', fontSize: 10, borderRadius: 5, border: `1px solid ${C.r}`, background: `${C.r}15`, color: C.r, cursor: 'pointer' }}>↺ 恢复默认</button>
          <button onClick={() => setEditMode(false)} style={{ padding: '3px 10px', fontSize: 10, borderRadius: 5, border: `1px solid ${C.g}`, background: `${C.g}15`, color: C.g, cursor: 'pointer' }}>✓ 完成</button>
        </div>
      )}

      {/* Load error banner */}
      {loadError && (
        <div style={{ background: `${C.r}15`, border: `1px solid ${C.r}40`, borderRadius: 6, padding: '5px 10px', color: C.r, fontSize: 11, marginBottom: 6, flexShrink: 0 }}>
          ✕ 数据加载失败：{loadError}
        </div>
      )}

      {/* react-grid-layout 网格 */}
      <div className="tw-rgl" style={{ flex: '1 1 0', width: '100%', minWidth: 0, minHeight: 0, overflowX: 'hidden', overflowY: 'auto', scrollbarGutter: 'stable' }}>
        <ResponsiveGridLayout
          className="tw-layout"
          layouts={layouts}
          cols={COLS_MAP}
          rowHeight={ROW_HEIGHT}
          margin={[6, 6]}
          containerPadding={[0, 0]}
          isDraggable={editMode && !isMobile}
          isResizable={editMode && !isMobile}
          isBounded={true}
          draggableHandle=".tw-drag-handle"
          compactType="vertical"
          preventCollision={false}
          useCSSTransforms={true}
          onBreakpointChange={(breakpoint: string) => {
            const nextBreakpoint = breakpoint as GridBreakpoint
            layoutChangeArmedRef.current = false
            setActiveBreakpoint(nextBreakpoint)
            if (nextBreakpoint === 'xs') setEditMode(false)
          }}
          onDragStart={armLayoutChange}
          onResizeStart={armLayoutChange}
          onDragStop={(next) => finishLayoutChange(next)}
          onResizeStop={(next) => finishLayoutChange(next)}
          breakpoints={BREAKPOINTS}
        >
          {MODULE_ORDER.map(modId => {
            const meta = MODULE_LABELS[modId]
            const showHeader = modId !== 'kpi-bar'
            return (
              <div
                key={modId}
                style={{
                  background: `linear-gradient(155deg, ${C.p2}, ${C.p})`,
                  border: `1px solid ${editMode ? C.b + '60' : C.line}`,
                  borderRadius: 10,
                  padding: modId === 'kpi-bar' ? 8 : 10,
                  display: 'flex',
                  flexDirection: 'column',
                  minHeight: 0,
                  overflow: 'hidden',
                  boxSizing: 'border-box',
                }}
              >
                {showHeader && (
                  <PanelHeader
                    title={`${meta.icon} ${meta.title}`}
                    dragHandle={editMode && !isMobile}
                  />
                )}
                {renderModuleContent(modId)}
              </div>
            )
          })}
        </ResponsiveGridLayout>
      </div>

      {/* Footer */}
      <div style={{ fontSize: 9, color: C.mut, textAlign: 'center', padding: '4px 0', flexShrink: 0, borderTop: `1px solid ${C.line}50` }}>
        SEO Control Tower V1 React · 模块×站点独立工作流 · {U} 不补零 · 布局存 localStorage（seo-tower-layout-v1）
      </div>
    </div>
  )
}

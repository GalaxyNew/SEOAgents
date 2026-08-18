import { useCallback, useEffect, useRef, useState } from 'react'
import './KeywordPoolPanel.css'

/**
 * 关键词池面板 — DataForSEO 全量西班牙 IPTV 词表（keyword_pool 表）。
 *
 * 数据是一次性拉取入库的市场全量词（含搜索量/难度），只读浏览；
 * 「哪些词值得本站追」的人工确认流在 keywords/candidates，不在这。
 *
 * 三种排序对应运营的三种视角：
 * - volume：市场热度（默认）
 * - difficulty：难度升序 = 最容易啃的词在前
 * - keyword：字母序（找特定词）
 */
type PoolItem = {
  keyword: string
  search_volume: number
  cpc: number
  competition: number
  difficulty: number
  updated_at: string
}

type PoolResp = {
  total: number
  offset: number
  limit: number
  updated_at: string | null
  items: PoolItem[]
}

const PAGE = 50

export function KeywordPoolPanel() {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'volume' | 'difficulty' | 'keyword'>('volume')
  const [page, setPage] = useState(0)
  const [data, setData] = useState<PoolResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setLoading(true)
    setErr('')
    try {
      const u = new URL('/api/keywords/pool', window.location.origin)
      u.searchParams.set('q', q)
      u.searchParams.set('sort', sort)
      u.searchParams.set('limit', String(PAGE))
      u.searchParams.set('offset', String(page * PAGE))
      const r = await fetch(u, { signal: ac.signal })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setData(await r.json())
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setErr(String(e))
    } finally {
      if (abortRef.current === ac) setLoading(false)
    }
  }, [q, sort, page])

  // 防抖搜索
  useEffect(() => {
    const t = setTimeout(load, q ? 300 : 0)
    return () => clearTimeout(t)
  }, [load, q])

  useEffect(() => { setPage(0) }, [q, sort])

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1

  return (
    <section className="dk-panel">
      <header>
        <h2>关键词池 · 西班牙 IPTV 全量</h2>
        <p className="dk-hint">
          DataForSEO 市场词表（{data?.total ?? '…'} 词）· 数据时间{' '}
          {data?.updated_at?.slice(0, 16).replace('T', ' ') ?? '—'}
        </p>
      </header>

      <div className="dk-kw-toolbar">
        <input
          type="search"
          placeholder="搜索关键词…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="搜索关键词"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          aria-label="排序"
        >
          <option value="volume">按搜索量</option>
          <option value="difficulty">按难度（易→难）</option>
          <option value="keyword">按字母</option>
        </select>
      </div>

      {err && <div className="dk-alert dk-alert--bad">加载失败：{err}</div>}

      <table className="dk-table">
        <thead>
          <tr>
            <th>#</th>
            <th>关键词</th>
            <th className="dk-kw-vol">搜索量/月</th>
            <th className="dk-kw-vol">CPC</th>
            <th className="dk-kw-kd">难度</th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((it, i) => (
            <tr key={it.keyword}>
              <td className="dk-dim">{page * PAGE + i + 1}</td>
              <td>{it.keyword}</td>
              <td className="dk-kw-vol">{it.search_volume.toLocaleString('es-ES')}</td>
              <td className="dk-kw-vol">{it.cpc ? `€${it.cpc.toFixed(2)}` : '—'}</td>
              <td className="dk-kw-kd">
                <span
                  className={
                    'dk-badge ' +
                    (it.difficulty <= 10 ? 'dk-badge--ok' : it.difficulty <= 30 ? 'dk-badge--warn' : 'dk-badge--bad')
                  }
                >
                  {it.difficulty.toFixed(0)}
                </span>
              </td>
            </tr>
          ))}
          {!loading && !data?.items.length && (
            <tr>
              <td colSpan={5} className="dk-dim" style={{ textAlign: 'center', padding: 24 }}>
                {q ? `没有匹配「${q}」的词` : '词池为空 — 尚未拉取'}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="dk-kw-meta">
        <span>
          {loading ? '加载中…' : `${data?.items.length ?? 0} / ${data?.total ?? 0} 词`}
        </span>
        <span>
          第 {page + 1} / {totalPages} 页
        </span>
      </div>

      <div className="dk-kw-pager">
        <button className="dk-btn" disabled={page === 0 || loading} onClick={() => setPage((p) => p - 1)}>
          ← 上一页
        </button>
        <button className="dk-btn" disabled={page + 1 >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
          下一页 →
        </button>
      </div>
    </section>
  )
}

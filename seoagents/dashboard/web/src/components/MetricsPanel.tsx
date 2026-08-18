import React, { useState } from 'react'

export interface MetricsSummary {
  site: string
  latest_m_t: number | null
  m_t_history: { ts: number; m_t: number }[]
  serp_positions: { keyword: string; position: number | null; url: string; engine: string }[]
  aeo_visibility: { engine: string; mention_rate: number }[]
  v_t: number | null
  open_dead_links: number
  skills: { id: string; built_in: boolean; steps: number }[]
  provider: string
}

const card: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--panel)',
  borderRadius: 12,
  padding: 16,
}

const Stat: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div style={{ ...card, flex: '1 1 140px', minWidth: 140 }}>
    <div style={{ color: 'var(--dim)', fontSize: 12, marginBottom: 6 }}>{label}</div>
    <div style={{ fontSize: 24, fontWeight: 700, color: tone ?? 'var(--text)' }}>{value}</div>
  </div>
)

export const MetricsPanel: React.FC<{
  summary: MetricsSummary | null
  onRefresh: () => void
}> = ({ summary, onRefresh }) => {
  const [busy, setBusy] = useState(false)

  const runEvolution = async () => {
    setBusy(true)
    try {
      await fetch('/api/jobs/evolution/run', { method: 'POST' })
      onRefresh()
    } finally {
      setBusy(false)
    }
  }

  if (!summary) return <div style={card}>加载中…</div>
  const compiled = (summary.skills || []).filter(s => !s.built_in).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <Stat
          label="综合演化评分 M_t"
          value={summary.latest_m_t == null ? '–' : summary.latest_m_t.toFixed(2)}
          tone={summary.latest_m_t != null && summary.latest_m_t > 100 ? 'var(--ok)' : 'var(--warn)'}
        />
        <Stat
          label="AEO 品牌可见度 V_t"
          value={summary.v_t == null ? '–' : `${(summary.v_t * 100).toFixed(1)}%`}
        />
        <Stat
          label="未修复死链"
          value={String(summary.open_dead_links)}
          tone={summary.open_dead_links > 0 ? 'var(--bad)' : 'var(--ok)'}
        />
        <Stat label="已固化技能" value={String(compiled)} />
        <div style={{ ...card, flex: '1 1 200px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <button
            onClick={runEvolution}
            disabled={busy}
            style={{
              width: '100%',
              background: 'var(--accent)',
              color: 'var(--text)',
              border: 0,
              borderRadius: 8,
              padding: '12px 18px',
              fontSize: 14,
              fontWeight: '600',
              cursor: busy ? 'wait' : 'pointer',
            }}
          >
            {busy ? '进化中…' : '▶ 立即执行进化流水线'}
          </button>
        </div>
      </div>

      <div style={card}>
        <div style={{ color: 'var(--dim)', fontSize: 12, marginBottom: 10 }}>关键词 SERP 排位</div>
        <div className="table-responsive">
          <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse', minWidth: '300px' }}>
            <tbody>
              {(summary.serp_positions || []).map(p => (
                <tr key={p.keyword} style={{ borderBottom: '1px solid var(--panel)' }}>
                  <td style={{ padding: '8px 10px' }}>{p.keyword}</td>
                  <td
                    style={{
                      padding: '8px 10px',
                      color: p.position != null && p.position <= 10 ? 'var(--ok)' : 'var(--bad)',
                      fontWeight: 'bold',
                    }}
                  >
                    {p.position == null ? '未上榜' : `#${p.position}`}
                  </td>
                  <td style={{ padding: '8px 10px', color: 'var(--dim)' }}>{p.engine}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

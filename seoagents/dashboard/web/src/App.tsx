import { useEffect, useState } from 'react'
import { SeoAuditPanel } from './components/SeoAuditPanel'
import { MetricsPanel, type MetricsSummary } from './components/MetricsPanel'

export default function App() {
  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [seonautEndpoint, setSeonautEndpoint] = useState<string>('')

  const refresh = async () => {
    try {
      const sum = await fetch('/api/metrics/summary').then(r => r.json())
      setSummary(sum)
      const cfg = await fetch('/api/config').then(r => r.json())
      setSeonautEndpoint(cfg?.resolved?.seonaut_endpoint ?? '')
    } catch (e) {
      console.warn('refresh failed', e)
    }
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{ padding: 20, color: '#e6edf6', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>
        SEOAgents · 技术审计与 AEO 看板
        <span style={{ color: '#8ba0b8', fontSize: 12, marginLeft: 10 }}>{summary?.site}</span>
      </h1>
      <MetricsPanel summary={summary} onRefresh={refresh} />
      <SeoAuditPanel seonautEndpoint={seonautEndpoint} />
    </div>
  )
}

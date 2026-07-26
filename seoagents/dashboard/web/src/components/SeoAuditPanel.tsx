import React from 'react'

/**
 * Seonaut 外挂审计看板嵌入面板 (L1)。
 * 手册 §7.1 的修正版: endpoint 不再硬编码,由后端 /api/config 下发。
 */
export const SeoAuditPanel: React.FC<{ seonautEndpoint: string }> = ({ seonautEndpoint }) => {
  if (!seonautEndpoint) return null
  return (
    <div className="seo-audit-container" style={{
      padding: 16, background: '#111826', borderRadius: 12,
      border: '1px solid #1e2a3c', marginTop: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: '#fff', margin: 0 }}>
          Seonaut 专业技术审计面板
        </h2>
        <span style={{
          padding: '2px 8px', background: '#34c98e', fontSize: 11,
          color: '#04140d', fontWeight: 600, borderRadius: 6,
        }}>
          Active Monitor (OpenSERP &amp; Lighthouse)
        </span>
      </div>
      <div style={{ width: '100%', height: 600, borderRadius: 8, border: '1px solid #1e2a3c', overflow: 'hidden' }}>
        <iframe
          src={seonautEndpoint}
          title="Seonaut Integration Dashboard"
          style={{ width: '100%', height: '100%', border: 0, background: '#fff' }}
          sandbox="allow-scripts allow-same-origin"
        />
      </div>
    </div>
  )
}

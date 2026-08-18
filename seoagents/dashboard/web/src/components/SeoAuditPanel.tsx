import React, { useEffect, useState } from 'react'

/**
 * 外挂审计面板 (L1)。
 *
 * 早先这里无条件把 endpoint 塞进 iframe。问题是配置值是
 * `http://localhost:9000` —— 那个 localhost 指的是**服务器**,而 iframe 在
 * **你的浏览器**里解析,于是浏览器去连你自己电脑的 9000 端口,得到
 * 「localhost 拒绝了我们的连接请求」。而 Seonaut 按方案本来就是挂起未部署的。
 *
 * 现在先探一次可达性,不可达就说明白为什么,不再显示一个假的「Active Monitor」。
 */
export const SeoAuditPanel: React.FC<{ seonautEndpoint: string }> = ({ seonautEndpoint }) => {
  const [state, setState] = useState<'checking' | 'ok' | 'unreachable' | 'local-only'>('checking')

  useEffect(() => {
    if (!seonautEndpoint) return
    let host = ''
    try {
      host = new URL(seonautEndpoint).hostname
    } catch {
      setState('unreachable')
      return
    }
    // 服务器侧的 localhost 在浏览器里指向的是用户自己的机器,嵌进来必然连不上
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
      setState('local-only')
      return
    }
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), 5000)
    fetch(seonautEndpoint, { mode: 'no-cors', signal: ctl.signal })
      .then(() => setState('ok'))
      .catch(() => setState('unreachable'))
      .finally(() => clearTimeout(timer))
    return () => { clearTimeout(timer); ctl.abort() }
  }, [seonautEndpoint])

  if (!seonautEndpoint) return null

  const shell: React.CSSProperties = {
    padding: 16, background: 'var(--surface)', borderRadius: 12,
    border: '1px solid var(--panel)', marginTop: 14,
  }

  const badge = (text: string, bg: string, fg: string) => (
    <span style={{ padding: '2px 8px', background: bg, fontSize: 11, color: fg, fontWeight: 600, borderRadius: 6 }}>
      {text}
    </span>
  )

  return (
    <div className="seo-audit-container" style={shell}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', margin: 0 }}>
          Seonaut 专业技术审计面板
        </h2>
        {state === 'ok' && badge('已接入', 'var(--ok)', 'var(--ok-soft)')}
        {state === 'checking' && badge('探测中…', 'var(--border)', 'var(--text)')}
        {state === 'local-only' && badge('未部署', 'var(--warn-soft)', 'var(--warn)')}
        {state === 'unreachable' && badge('不可达', 'var(--bad-soft)', 'var(--bad)')}
      </div>

      {state === 'ok' && (
        <div style={{ width: '100%', height: 600, borderRadius: 8, border: '1px solid var(--panel)', overflow: 'hidden' }}>
          <iframe
            src={seonautEndpoint}
            title="Seonaut Integration Dashboard"
            style={{ width: '100%', height: '100%', border: 0, background: 'var(--text)' }}
            sandbox="allow-scripts allow-same-origin"
          />
        </div>
      )}

      {state === 'checking' && (
        <div style={{ color: 'var(--faint)', fontSize: 12, padding: '24px 0', textAlign: 'center' }}>
          正在探测 {seonautEndpoint} …
        </div>
      )}

      {state === 'local-only' && (
        <div style={{ color: 'var(--dim)', fontSize: 12, lineHeight: 1.8, padding: '8px 0' }}>
          <div style={{ color: 'var(--warn)', fontWeight: 600, marginBottom: 6 }}>
            Seonaut 尚未部署,当前配置指向服务器本机
          </div>
          配置值是 <code style={{ color: 'var(--accent)' }}>{seonautEndpoint}</code>。
          这个 <code>localhost</code> 指的是<strong>服务器自己</strong>,而页面在你的浏览器里跑,
          所以浏览器会去连<strong>你这台电脑</strong>的端口 —— 这就是「localhost 拒绝了连接请求」的来源。
          <div style={{ marginTop: 8, color: 'var(--faint)' }}>
            按方案 14 号文,Seonaut 是<strong>主动挂起</strong>的:它结果不带 data_status、不进 Asset Hub、
            不参与交叉验证,装上会是个信息孤岛。而 site_audit 能力已有内置爬虫覆盖。
            <br />
            要启用的话:部署 Seonaut 后把 endpoint 改成可从浏览器访问的地址(如经 Cloudflare Tunnel 暴露的域名)。
          </div>
        </div>
      )}

      {state === 'unreachable' && (
        <div style={{ color: 'var(--dim)', fontSize: 12, lineHeight: 1.8, padding: '8px 0' }}>
          <div style={{ color: 'var(--bad)', fontWeight: 600, marginBottom: 6 }}>
            无法连接 {seonautEndpoint}
          </div>
          服务可能未启动,或该地址从浏览器所在网络不可达。不显示空白 iframe,免得看起来像「面板坏了」。
        </div>
      )}
    </div>
  )
}

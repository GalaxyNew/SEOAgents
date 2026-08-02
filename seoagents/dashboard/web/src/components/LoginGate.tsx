import { useEffect, useState } from 'react'
import { inputStyle, btn } from '../ui'

/**
 * 登录门。未登录时挡在整个应用前面。
 *
 * 后端对默认口令的账号会一路返回 403 MUST_CHANGE_PASSWORD,所以这里把
 * 「改口令」做成登录流程的一部分而不是设置页里的一个可选项 —— 让人登进去
 * 却发现哪儿都点不动,比直接要求改口令更难理解。
 */

type Session = { authenticated: boolean; username?: string; role?: string; must_change?: boolean }

const wrap: React.CSSProperties = {
  position: 'fixed', inset: 0, display: 'grid', placeItems: 'center',
  background: '#0b1120', zIndex: 9999,
}
const box: React.CSSProperties = {
  width: 340, background: '#111827', border: '1px solid #1f2937',
  borderRadius: 12, padding: '26px 24px',
}

export const LoginGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sess, setSess] = useState<Session | null>(null)
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [np, setNp] = useState('')
  const [np2, setNp2] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const check = async () => {
    try {
      const r = await fetch('/api/auth/session').then(x => x.json())
      setSess(r)
    } catch {
      setSess({ authenticated: false })
    }
  }
  useEffect(() => { void check() }, [])

  const login = async () => {
    setBusy(true); setErr('')
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      })
      const b = await res.json()
      if (!res.ok) { setErr(b.detail || '登录失败'); return }
      setSess({ authenticated: true, username: b.username, role: b.role, must_change: b.must_change })
      setP('')
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const change = async () => {
    if (np !== np2) { setErr('两次输入的新口令不一致'); return }
    setBusy(true); setErr('')
    try {
      const res = await fetch('/api/auth/password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: p || 'admin123', new_password: np }),
      })
      const b = await res.json()
      if (!res.ok) { setErr(b.detail || '修改失败'); return }
      setNp(''); setNp2(''); await check()
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  if (sess === null) return null                    // 会话还没查完,先不闪登录页
  if (sess.authenticated && !sess.must_change) return <>{children}</>

  const mustChange = sess.authenticated && sess.must_change

  return (
    <div style={wrap}>
      <div style={box}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>SEOAgents</div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 18 }}>
          {mustChange ? '首次登录,请设置新口令' : '请登录'}
        </div>

        {!mustChange ? (
          <div style={{ display: 'grid', gap: 10 }}>
            <input style={inputStyle} placeholder="用户名" value={u} autoFocus
              onChange={e => setU(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && void login()} />
            <input style={inputStyle} placeholder="口令" type="password" value={p}
              onChange={e => setP(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && void login()} />
            <button style={{ ...btn('#2563eb'), width: '100%', padding: '9px 0' }}
              onClick={() => void login()} disabled={busy || !u || !p}>
              {busy ? '登录中…' : '登录'}
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            <div style={{
              fontSize: 12, color: '#fbbf24', background: '#1c1917',
              border: '1px solid #78350f', borderRadius: 6, padding: '8px 10px', lineHeight: 1.5,
            }}>
              这个后台可以从公网访问,而 admin/admin123 正是扫描器最先试的一组。
              换掉它之前,其它功能都用不了。
            </div>
            <input style={inputStyle} placeholder="当前口令" type="password" value={p}
              onChange={e => setP(e.target.value)} />
            <input style={inputStyle} placeholder="新口令（至少 8 位）" type="password" value={np}
              autoFocus onChange={e => setNp(e.target.value)} />
            <input style={inputStyle} placeholder="再输一次新口令" type="password" value={np2}
              onChange={e => setNp2(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && void change()} />
            <button style={{ ...btn('#15803d'), width: '100%', padding: '9px 0' }}
              onClick={() => void change()} disabled={busy || np.length < 8 || !np2}>
              {busy ? '提交中…' : '设置新口令'}
            </button>
          </div>
        )}

        {err && (
          <div style={{ marginTop: 12, fontSize: 12, color: '#fca5a5' }}>{err}</div>
        )}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'

/**
 * 登录门。未登录时把人送到 `/login`。
 *
 * 这里刻意**不再自己画一套登录界面**。此前 React 版和 `static/login.html`
 * 各有一份实现,同一个页面维护两处 —— 我改了 React 那份的扫描线和渐变色带,
 * 线上实际在用的 HTML 那份原封不动,白改一轮。
 *
 * 现在唯一真源是 `static/login.html`(服务端 `/login` 路由)。React 这边只
 * 负责判断「登没登录、要不要改口令」,然后跳过去。
 */

type Session = {
  authenticated: boolean
  username?: string
  role?: string
  must_change?: boolean
}

export const LoginGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sess, setSess] = useState<Session | null>(null)

  useEffect(() => {
    let alive = true
    fetch('/api/auth/session')
      .then((r) => r.json())
      .then((d: Session) => { if (alive) setSess(d) })
      .catch(() => { if (alive) setSess({ authenticated: false }) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!sess) return
    // 已登录且不需要改口令 —— 放行
    if (sess.authenticated && !sess.must_change) return
    // 带默认口令的账号后端会一路 403,登录页那边会引导改口令
    const target = sess.must_change ? '/login?change=1' : '/login'
    if (!window.location.pathname.startsWith('/login')) {
      window.location.replace(target)
    }
  }, [sess])

  // 会话还没查完先不渲染,避免闪一下主界面再跳走
  if (sess === null) return null
  if (!sess.authenticated || sess.must_change) return null
  return <>{children}</>
}

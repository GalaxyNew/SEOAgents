import { useEffect, useRef, useState } from 'react'

/**
 * 登录门。未登录时挡在整个应用前面。
 *
 * 后端对默认口令的账号会一路返回 403 MUST_CHANGE_PASSWORD,所以「改口令」
 * 做成登录流程的一部分,而不是设置页里一个可选项 —— 让人登进去却发现哪儿都
 * 点不动,比直接要求改口令更难理解。
 *
 * 背景那张网是真的在跑物理:节点漂移、近邻连线、鼠标形成引力。它对应的是
 * 这套系统每天在做的事 —— 爬到的页面是节点,页面间的链接是边。不是随便找的
 * 装饰动画。
 *
 * 性能上做了三件事,否则登录页会把风扇吹起来:
 *   1. 节点数按视口面积算,小屏不会画一样多的点
 *   2. 连线只在近邻之间求,距离用平方比较,不开根号
 *   3. 标签页切到后台时停掉 rAF —— 没人看的动画不该烧 CPU
 */

type Session = {
  authenticated: boolean
  username?: string
  role?: string
  must_change?: boolean
}

// ── 背景:链接图 ──────────────────────────────────────────────────────
const NetworkCanvas: React.FC = () => {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return

    let raf = 0
    let w = 0
    let h = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const mouse = { x: -9999, y: -9999 }
    type P = { x: number; y: number; vx: number; vy: number; r: number }
    let pts: P[] = []

    const seed = () => {
      w = cv.clientWidth
      h = cv.clientHeight
      cv.width = w * dpr
      cv.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      // 按面积定密度,不按固定值 —— 手机上画 120 个点纯属浪费
      const n = Math.min(110, Math.round((w * h) / 13000))
      pts = Array.from({ length: n }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: Math.random() * 1.5 + 0.6,
      }))
    }

    const LINK = 130
    const LINK2 = LINK * LINK
    const PULL = 170
    const PULL2 = PULL * PULL

    const draw = () => {
      ctx.clearRect(0, 0, w, h)

      for (const p of pts) {
        // 鼠标附近轻微牵引,松手就慢慢散回去
        const mdx = mouse.x - p.x
        const mdy = mouse.y - p.y
        const md2 = mdx * mdx + mdy * mdy
        if (md2 < PULL2 && md2 > 1) {
          const f = (1 - md2 / PULL2) * 0.0016
          p.vx += mdx * f
          p.vy += mdy * f
        }
        p.x += p.vx
        p.y += p.vy
        // 阻尼,否则牵引会越积越快,最后所有点糊在鼠标上
        p.vx *= 0.994
        p.vy *= 0.994
        if (p.x < 0 || p.x > w) p.vx *= -1
        if (p.y < 0 || p.y > h) p.vy *= -1
        p.x = Math.max(0, Math.min(w, p.x))
        p.y = Math.max(0, Math.min(h, p.y))
      }

      // 连线。距离比较用平方,省掉每帧几千次开根号
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x
          const dy = pts[i].y - pts[j].y
          const d2 = dx * dx + dy * dy
          if (d2 > LINK2) continue
          const a = (1 - d2 / LINK2) * 0.5
          ctx.strokeStyle = `rgba(56,189,248,${a * 0.55})`
          ctx.lineWidth = 0.6
          ctx.beginPath()
          ctx.moveTo(pts[i].x, pts[i].y)
          ctx.lineTo(pts[j].x, pts[j].y)
          ctx.stroke()
        }
      }

      for (const p of pts) {
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(125,211,252,0.85)'
        ctx.fill()
      }

      raf = requestAnimationFrame(draw)
    }

    const onMove = (e: MouseEvent) => {
      const b = cv.getBoundingClientRect()
      mouse.x = e.clientX - b.left
      mouse.y = e.clientY - b.top
    }
    const onLeave = () => {
      mouse.x = -9999
      mouse.y = -9999
    }
    // 切到别的标签页就停 —— 没人看的动画不该占着 CPU
    const onVis = () => {
      cancelAnimationFrame(raf)
      if (!document.hidden) raf = requestAnimationFrame(draw)
    }

    seed()
    raf = requestAnimationFrame(draw)
    window.addEventListener('resize', seed)
    window.addEventListener('mousemove', onMove)
    cv.addEventListener('mouseleave', onLeave)
    document.addEventListener('visibilitychange', onVis)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', seed)
      window.removeEventListener('mousemove', onMove)
      cv.removeEventListener('mouseleave', onLeave)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <canvas
      ref={ref}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  )
}

// ── 样式 ──────────────────────────────────────────────────────────────
const CSS = `
@keyframes sg-rotate { to { transform: rotate(360deg) } }
@keyframes sg-scan   { 0% { top: -10% } 100% { top: 110% } }
@keyframes sg-blink  { 0%,100% { opacity: 1 } 50% { opacity: .25 } }
@keyframes sg-rise   { from { opacity: 0; transform: translateY(14px) } to { opacity: 1; transform: none } }
@keyframes sg-orbit  { to { transform: rotate(-360deg) } }

.sg-wrap { position: fixed; inset: 0; z-index: 9999; background: #04060d;
  display: grid; place-items: center; overflow: hidden;
  font-family: ui-sans-serif, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif; }

.sg-grid { position: absolute; inset: -50%; opacity: .5;
  background-image:
    linear-gradient(rgba(56,189,248,.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56,189,248,.055) 1px, transparent 1px);
  background-size: 46px 46px;
  transform: perspective(560px) rotateX(62deg) translateY(-16%); }

.sg-glow { position: absolute; width: 900px; height: 900px; border-radius: 50%;
  background: radial-gradient(circle, rgba(37,99,235,.20) 0%, rgba(14,116,144,.09) 40%, transparent 68%);
  filter: blur(28px); pointer-events: none; }

.sg-vignette { position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(ellipse at center, transparent 34%, rgba(2,4,10,.82) 100%); }

.sg-scan { position: absolute; left: 0; right: 0; height: 120px; pointer-events: none;
  background: linear-gradient(180deg, transparent, rgba(56,189,248,.05), transparent);
  animation: sg-scan 7s linear infinite; }

.sg-card { position: relative; width: 372px; padding: 2px; border-radius: 16px;
  animation: sg-rise .5s cubic-bezier(.22,1,.36,1) both; }
.sg-card::before { content:''; position:absolute; inset:-1px; border-radius:17px; padding:1px;
  background: conic-gradient(from 0deg, transparent 0deg, #22d3ee 40deg, #6366f1 90deg, transparent 150deg, transparent 360deg);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor; mask-composite: exclude;
  animation: sg-rotate 6s linear infinite; }

.sg-inner { position: relative; border-radius: 15px; padding: 30px 28px 24px;
  background: linear-gradient(165deg, rgba(13,19,34,.94), rgba(7,11,22,.97));
  border: 1px solid rgba(56,189,248,.13);
  box-shadow: 0 24px 70px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.045); }

.sg-corner { position:absolute; width:15px; height:15px; border-color:#22d3ee; opacity:.55; }
.sg-corner.tl { top:9px; left:9px;  border-top:1.5px solid; border-left:1.5px solid; }
.sg-corner.tr { top:9px; right:9px; border-top:1.5px solid; border-right:1.5px solid; }
.sg-corner.bl { bottom:9px; left:9px;  border-bottom:1.5px solid; border-left:1.5px solid; }
.sg-corner.br { bottom:9px; right:9px; border-bottom:1.5px solid; border-right:1.5px solid; }

.sg-mark { position: relative; width: 52px; height: 52px; margin: 0 auto 16px; }
.sg-mark i { position:absolute; inset:0; border-radius:50%;
  border:1px solid rgba(34,211,238,.28); }
.sg-mark i:nth-child(2) { inset:7px; border-color:rgba(99,102,241,.34);
  animation: sg-orbit 9s linear infinite; border-style:dashed; }
.sg-mark b { position:absolute; inset:15px; border-radius:9px; display:grid; place-items:center;
  background: linear-gradient(135deg,#22d3ee,#4f46e5); color:#04060d;
  font-size:12px; font-weight:800; letter-spacing:.4px; font-style:normal;
  box-shadow: 0 0 18px rgba(34,211,238,.5); }

.sg-title { text-align:center; font-size:21px; font-weight:700; letter-spacing:2.5px;
  color:#e8f4ff; margin:0 0 5px;
  text-shadow: 0 0 22px rgba(56,189,248,.42); }
.sg-sub { text-align:center; font-size:10.5px; letter-spacing:1.6px; margin:0 0 22px;
  color:#4d7fa6; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.sg-sub s { text-decoration:none; color:#22d3ee; animation: sg-blink 1.4s steps(1) infinite; }

.sg-field { position:relative; margin-bottom:12px; }
.sg-field label { position:absolute; left:12px; top:-7px; padding:0 5px; font-size:9.5px;
  letter-spacing:1.3px; color:#4d7fa6; background:#0a1122; border-radius:3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.sg-field input { width:100%; box-sizing:border-box; height:42px; padding:0 13px;
  background:rgba(6,12,26,.85); color:#dcefff; font-size:14px;
  border:1px solid rgba(56,189,248,.16); border-radius:9px; outline:none;
  transition: border-color .18s, box-shadow .18s, background .18s; }
.sg-field input::placeholder { color:#33526e; }
.sg-field input:focus { border-color:#22d3ee; background:rgba(8,17,34,.95);
  box-shadow: 0 0 0 3px rgba(34,211,238,.11), 0 0 22px rgba(34,211,238,.14); }

.sg-btn { position:relative; width:100%; height:43px; margin-top:6px; border:0;
  border-radius:9px; cursor:pointer; overflow:hidden; color:#04060d;
  font-size:14px; font-weight:700; letter-spacing:2.5px;
  background: linear-gradient(100deg,#22d3ee,#4f46e5);
  box-shadow: 0 8px 26px rgba(34,211,238,.24);
  transition: transform .14s, box-shadow .18s, filter .18s; }
.sg-btn:hover:not(:disabled) { transform:translateY(-1px); filter:brightness(1.07);
  box-shadow: 0 12px 34px rgba(34,211,238,.36); }
.sg-btn:active:not(:disabled) { transform:translateY(0) scale(.99); }
.sg-btn:disabled { opacity:.34; cursor:not-allowed; box-shadow:none; }
.sg-btn span { position:absolute; top:0; left:-120%; width:60%; height:100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.42), transparent);
  transition: left .5s; }
.sg-btn:hover:not(:disabled) span { left:130%; }

.sg-warn { font-size:11.5px; line-height:1.65; color:#fbbf24; margin-bottom:13px;
  padding:9px 11px; border-radius:8px; background:rgba(69,26,3,.42);
  border:1px solid rgba(180,83,9,.42); }

.sg-err { margin-top:12px; font-size:11.5px; color:#fca5a5; text-align:center;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

.sg-foot { margin-top:18px; padding-top:13px; border-top:1px solid rgba(56,189,248,.09);
  display:flex; justify-content:space-between; font-size:9.5px; letter-spacing:.7px;
  color:#3c6484; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.sg-dot { display:inline-block; width:5px; height:5px; border-radius:50%; background:#22c55e;
  margin-right:5px; box-shadow:0 0 7px #22c55e; animation: sg-blink 2.1s ease-in-out infinite; }

@media (prefers-reduced-motion: reduce) {
  .sg-card::before, .sg-scan, .sg-mark i:nth-child(2), .sg-dot, .sg-sub s { animation: none }
}
@media (max-width: 420px) { .sg-card { width: calc(100vw - 34px) } }
`

// ── 组件 ──────────────────────────────────────────────────────────────
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
      setSess(await fetch('/api/auth/session').then(r => r.json()))
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
      if (!b.must_change) setP('')
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const change = async () => {
    if (np !== np2) { setErr('两次输入的新口令不一致'); return }
    setBusy(true); setErr('')
    try {
      const res = await fetch('/api/auth/password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: p, new_password: np }),
      })
      const b = await res.json()
      if (!res.ok) { setErr(b.detail || '修改失败'); return }
      setNp(''); setNp2(''); setP(''); await check()
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  if (sess === null) return null              // 会话还没查完,别闪一下登录页
  if (sess.authenticated && !sess.must_change) return <>{children}</>
  const mustChange = Boolean(sess.authenticated && sess.must_change)

  return (
    <div className="sg-wrap">
      <style>{CSS}</style>
      <div className="sg-grid" />
      <NetworkCanvas />
      <div className="sg-glow" />
      <div className="sg-vignette" />
      <div className="sg-scan" />

      <div className="sg-card">
        <div className="sg-inner">
          <i className="sg-corner tl" /><i className="sg-corner tr" />
          <i className="sg-corner bl" /><i className="sg-corner br" />

          <div className="sg-mark"><i /><i /><b>SEO</b></div>
          <h1 className="sg-title">SEOAGENTS</h1>
          <p className="sg-sub">
            {mustChange ? 'SET NEW CREDENTIALS' : '自适应演化 · SEO 智能体集群'}<s>_</s>
          </p>

          {!mustChange ? (
            <>
              <div className="sg-field">
                <label>USER</label>
                <input value={u} autoFocus placeholder="用户名"
                  onChange={e => setU(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && void login()} />
              </div>
              <div className="sg-field">
                <label>PASS</label>
                <input type="password" value={p} placeholder="口令"
                  onChange={e => setP(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && void login()} />
              </div>
              <button className="sg-btn" onClick={() => void login()} disabled={busy || !u || !p}>
                {busy ? '验证中' : '接 入 系 统'}<span />
              </button>
            </>
          ) : (
            <>
              <div className="sg-warn">
                这个后台可以从公网访问,而 admin/admin123 正是扫描器最先试的一组。
                换掉它之前,其它功能都用不了。
              </div>
              <div className="sg-field">
                <label>CURRENT</label>
                <input type="password" value={p} placeholder="当前口令"
                  onChange={e => setP(e.target.value)} />
              </div>
              <div className="sg-field">
                <label>NEW</label>
                <input type="password" value={np} autoFocus placeholder="新口令（至少 8 位）"
                  onChange={e => setNp(e.target.value)} />
              </div>
              <div className="sg-field">
                <label>CONFIRM</label>
                <input type="password" value={np2} placeholder="再输一次"
                  onChange={e => setNp2(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && void change()} />
              </div>
              <button className="sg-btn" onClick={() => void change()}
                disabled={busy || np.length < 8 || !np2 || !p}>
                {busy ? '提交中' : '设 置 新 口 令'}<span />
              </button>
            </>
          )}

          {err && <div className="sg-err">// {err}</div>}

          <div className="sg-foot">
            <span><i className="sg-dot" />SYSTEM ONLINE</span>
            <span>DATA_STATUS · REAL</span>
          </div>
        </div>
      </div>
    </div>
  )
}

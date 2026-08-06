import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * 横向时间轴。当前时刻居中,左边已发生、右边将发生。
 *
 * 三个刻意的决定:
 *
 * * **「现在」这条线固定在中央,不随拖动移动**。拖的是时间本身。让现在线
 *   跟着跑的话,人一松手就找不到「此刻在哪」。
 * * **卡片贪心分层装箱,保证不重叠**。上下交替加固定阈值是不够的 ——
 *   密集时段照样叠在一起。这里给每张卡算出实际占用区间,逐层找第一个放得下
 *   的位置;放不下就再开一层。
 * * **滚轮缩放锚定光标下的时刻**。缩放时如果锚在中心,光标指着的那个节点会
 *   跑掉,人得重新找。锚在光标处,指着谁就一直是谁。
 */

type Node = {
  node_id: string
  kind: string
  state: string
  intent: string
  scheduled_at: string
  outcome?: string
  subject_ref?: string
  context?: Record<string, unknown>
  created_by?: string
}

const KIND_COLOR: Record<string, string> = {
  START: '#3b82f6', CHECKPOINT: '#f59e0b', REPORT: '#8b5cf6',
  DEADLINE: '#ef4444', RECURRING: '#14b8a6', REVIEW: '#22c55e',
}
const KIND_LABEL: Record<string, string> = {
  START: '开始', CHECKPOINT: '检查点', REPORT: '汇报',
  DEADLINE: '截止', RECURRING: '周期', REVIEW: '复盘',
}
const STATE_LABEL: Record<string, string> = {
  SCHEDULED: '待执行', FIRED: '已投递', ACKED: '已完成',
  CATCHUP: '补办', DROPPED: '已放弃', CANCELLED: '已取消',
  MISSED: '未触发', UNACKED: '无人处理',
}

// 来源标识:Ag=Agent自主创建, Yh=用户手动创建, Ya=用户让Agent创建
const SOURCE_TAG: Record<string, { label: string; color: string }> = {
  ag: { label: 'Ag', color: '#22d3ee' },
  yh: { label: 'Yh', color: '#fbbf24' },
  ya: { label: 'Ya', color: '#a78bfa' },
}
const sourceTagOf = (createdBy?: string) => {
  if (!createdBy || createdBy === 'unknown') return null
  // 用户手动创建: timeline-ui, manual, 用户名等
  if (['timeline-ui', 'manual', 'user', 'yh', 'you'].includes(createdBy)) return SOURCE_TAG.yh
  // 用户让Agent创建: 含 user-ask / ya 前缀
  if (createdBy.startsWith('user-ask') || createdBy.startsWith('ya-')) return SOURCE_TAG.ya
  // 其余都是 Agent 自主创建
  return SOURCE_TAG.ag
}

const CARD_W = 186
const CARD_GAP = 8
const LANE_H = 62          // 一层的高度(卡片 + 间距)
const MIN_MS_PER_PX = 30_000        // 最细:约 7.5 小时一屏
const MAX_MS_PER_PX = 3_600_000     // 最粗:约 37 天一屏

const fmtSpan = (ms: number) => {
  const h = ms / 3600e3
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)} 小时`
  const d = h / 24
  return d < 60 ? `${d.toFixed(d < 10 ? 1 : 0)} 天` : `${(d / 30).toFixed(1)} 个月`
}
const fmtTime = (t: number | string) =>
  new Date(t).toLocaleString('zh-CN', { hour12: false, month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit' })

export const TimelineTrack: React.FC<{
  nodes: Node[]
  onPick?: (n: Node) => void
  defaultHours?: number
}> = ({ nodes, onPick, defaultHours = 15 }) => {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  // 根据传入的视野小时数算出初始 ms/px,让一屏正好展示该时长
  const [msPerPx, setMsPerPx] = useState((defaultHours * 3600e3) / 900)
  const [offsetMs, setOffsetMs] = useState(0)
  const [drag, setDrag] = useState<{ x: number; base: number } | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  // 容器宽度已知后,按 defaultHours 重新校准缩放,确保一屏正好展示选定的视野
  // 用 defaultHours 做依赖:视野切换(key 变了→组件重建)时重新校准
  useEffect(() => {
    if (width <= 0) return
    setMsPerPx((defaultHours * 3600e3) / width)
  }, [width, defaultHours])

  const centerMs = now + offsetMs
  const toX = (iso: string) => (new Date(iso).getTime() - centerMs) / msPerPx + width / 2

  // ── 贪心分层装箱 ────────────────────────────────────────────────────
  // 上下交替只解决了「两张卡」的情况。真正要保证不重叠,得给每张卡算出它
  // 占用的横向区间,然后逐层找第一个放得下的位置。同一层内按左边界排序,
  // 只需和该层最后一张比 —— 因为节点已按时间排序,后来的一定在右边。
  const laid = useMemo(() => {
    const sorted = [...nodes].sort(
      (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
    const laneEnd: Record<string, number> = {}   // "side:lane" → 该层已占到的右边界
    return sorted.map((n) => {
      const x = toX(n.scheduled_at)
      const left = x - CARD_W / 2
      const right = x + CARD_W / 2 + CARD_GAP
      // 先试上方,再试下方,同层放不下就加一层 —— 交替是为了视觉平衡,
      // 但不以牺牲「不重叠」为代价
      let lane = 0
      let side: -1 | 1 = -1
      for (let k = 0; k < 40; k++) {
        lane = Math.floor(k / 2)
        side = (k % 2 === 0 ? -1 : 1) as -1 | 1
        const key = `${side}:${lane}`
        if (laneEnd[key] === undefined || laneEnd[key] <= left) {
          laneEnd[key] = right
          break
        }
      }
      return { node: n, x, side, lane }
    })
  }, [nodes, centerMs, msPerPx, width])

  const visible = laid.filter((l) => l.x > -CARD_W && l.x < width + CARD_W)
  const maxLane = visible.reduce((m, l) => Math.max(m, l.lane), 0)
  // 高度跟着最深的那一层长,卡片永远不会被容器裁掉
  const H = Math.max(240, (maxLane + 1) * LANE_H * 2 + 70)

  // ── 刻度 ────────────────────────────────────────────────────────────
  const half = (width / 2) * msPerPx
  const step = [
    15 * 60e3, 30 * 60e3, 3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3,
    24 * 3600e3, 3 * 24 * 3600e3, 7 * 24 * 3600e3, 30 * 24 * 3600e3,
  ].find((s) => s >= msPerPx * 130) || 90 * 24 * 3600e3
  const ticks: number[] = []
  for (let t = Math.ceil((centerMs - half) / step) * step; t < centerMs + half; t += step) {
    ticks.push(t)
  }

  // ── 拖动 ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!drag) return
    const move = (e: MouseEvent) =>
      setOffsetMs(drag.base - (e.clientX - drag.x) * msPerPx)
    const up = () => setDrag(null)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [drag, msPerPx])

  // ── 滚轮缩放 ────────────────────────────────────────────────────────
  // 用原生监听器 + passive:false,否则 React 的合成事件里 preventDefault
  // 不生效,缩放时整页会跟着滚。
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const cursorX = e.clientX - rect.left
      const next = Math.min(MAX_MS_PER_PX, Math.max(MIN_MS_PER_PX,
        msPerPx * (e.deltaY > 0 ? 1.15 : 1 / 1.15)))
      // 锚定光标下的时刻:缩放前后,光标指着的仍是同一时刻。
      // 锚在中心的话,人盯着的那个节点会跑掉,得重新找。
      const timeAtCursor = centerMs + (cursorX - width / 2) * msPerPx
      const nextCenter = timeAtCursor - (cursorX - width / 2) * next
      setMsPerPx(next)
      setOffsetMs(nextCenter - now)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [msPerPx, centerMs, width, now])

  const spanMs = width * msPerPx

  return (
    <div style={{
      background: '#111827', border: '1px solid #1f2937',
      borderRadius: 10, padding: '10px 0 12px', marginBottom: 14,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '0 14px 8px', flexWrap: 'wrap',
      }}>
        <strong style={{ fontSize: 13, color: '#e5e7eb' }}>时间轴</strong>
        {/* 当前跨度实时显示 —— 缩放时人要知道自己看的是多长一段时间 */}
        <span style={{
          fontSize: 11, color: '#22d3ee', fontFamily: 'ui-monospace, monospace',
          background: '#0b1220', border: '1px solid #1e293b',
          borderRadius: 5, padding: '2px 8px',
        }}>
          视野 {fmtSpan(spanMs)}
        </span>
        <span style={{ fontSize: 11, color: '#475569' }}>
          {fmtTime(centerMs - spanMs / 2)} ~ {fmtTime(centerMs + spanMs / 2)}
        </span>
        <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>
          拖动平移 · 滚轮缩放
        </span>
        {offsetMs !== 0 && (
          <button onClick={() => setOffsetMs(0)} style={{
            background: '#2563eb', color: '#fff', border: 0,
            borderRadius: 6, padding: '3px 9px', fontSize: 11, cursor: 'pointer',
          }}>回到现在</button>
        )}
      </div>

      <div
        ref={boxRef}
        onMouseDown={(e) => setDrag({ x: e.clientX, base: offsetMs })}
        style={{
          position: 'relative', height: H, overflow: 'hidden',
          cursor: drag ? 'grabbing' : 'grab', userSelect: 'none',
        }}
      >
        {ticks.map((t) => {
          const x = (t - centerMs) / msPerPx + width / 2
          return (
            <div key={t} style={{ position: 'absolute', left: x, top: 0, bottom: 0 }}>
              <div style={{ position: 'absolute', top: 0, bottom: 0, width: 1, background: '#1a2434' }} />
              <div style={{
                position: 'absolute', top: H / 2 + 8, left: 4, fontSize: 10,
                color: '#475569', whiteSpace: 'nowrap',
                fontFamily: 'ui-monospace, monospace',
              }}>{fmtTime(t)}</div>
            </div>
          )
        })}

        <div style={{
          position: 'absolute', left: 0, right: 0, top: H / 2, height: 2,
          background: 'linear-gradient(90deg, #1f2937, #334155, #1f2937)',
        }} />

        <div style={{
          position: 'absolute', left: width / 2, top: 0, bottom: 0,
          width: 2, background: '#ef4444', opacity: .85,
        }}>
          <div style={{
            position: 'absolute', top: 2, left: 6, fontSize: 10, color: '#fca5a5',
            fontFamily: 'ui-monospace, monospace', whiteSpace: 'nowrap',
          }}>现在</div>
        </div>

        {visible.map(({ node: n, x, side, lane }) => {
          const color = KIND_COLOR[n.kind] || '#64748b'
          const done = n.state === 'ACKED'
          const stalk = 24 + lane * LANE_H
          const cardTop = side < 0 ? H / 2 - stalk - 56 : H / 2 + stalk
          const isHover = hover === n.node_id
          return (
            <div key={n.node_id}>
              <div style={{
                position: 'absolute', left: x - 1,
                top: side < 0 ? H / 2 - stalk : H / 2,
                width: 2, height: stalk, background: color, opacity: .45,
              }} />
              <div style={{
                position: 'absolute', left: x - 5, top: H / 2 - 5,
                width: 10, height: 10, borderRadius: '50%',
                background: done ? color : '#0b1220',
                border: `2px solid ${color}`,
                boxShadow: isHover ? `0 0 10px ${color}` : 'none',
              }} />
              <div
                onMouseEnter={() => setHover(n.node_id)}
                onMouseLeave={() => setHover(null)}
                onClick={(e) => { e.stopPropagation(); onPick?.(n) }}
                style={{
                  position: 'absolute', left: x - CARD_W / 2, top: cardTop,
                  width: CARD_W, height: 52, boxSizing: 'border-box',
                  background: '#0f172a', border: `1px solid ${isHover ? color : '#1f2937'}`,
                  borderLeft: `3px solid ${color}`, borderRadius: 6,
                  padding: '5px 8px', cursor: 'pointer', overflow: 'hidden',
                  transition: 'border-color .15s',
                }}
              >
                <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                  <span style={{ fontSize: 9, color, fontWeight: 600 }}>
                    {KIND_LABEL[n.kind] || n.kind}
                  </span>
                  <span style={{ fontSize: 9, color: done ? '#22c55e' : '#64748b' }}>
                    {STATE_LABEL[n.state] || n.state}
                  </span>
                  {(() => { const st = sourceTagOf(n.created_by); return st ? (
                    <span style={{ fontSize: 8, color: st.color, fontWeight: 700, background: '#0b1220', borderRadius: 3, padding: '1px 4px', marginLeft: 'auto' }} title={st.label === 'Ag' ? 'Agent自主创建' : st.label === 'Yh' ? '用户手动创建' : '用户让Agent创建'}>
                      {st.label}
                    </span>
                  ) : null })()}
                </div>
                <div style={{
                  fontSize: 11, color: '#e2e8f0',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{n.intent}</div>
                <div style={{
                  fontSize: 10, color: n.outcome ? '#94a3b8' : '#475569',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{n.outcome || fmtTime(n.scheduled_at)}</div>
              </div>
            </div>
          )
        })}

        {visible.length === 0 && (
          <div style={{
            position: 'absolute', inset: 0, display: 'grid', placeItems: 'center',
            color: '#475569', fontSize: 12,
          }}>
            这段时间没有节点 —— 拖动或滚轮缩小看看
          </div>
        )}
      </div>
    </div>
  )
}

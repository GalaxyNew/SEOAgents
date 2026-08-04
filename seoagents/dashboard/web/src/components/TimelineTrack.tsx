import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * 横向时间轴。当前时刻居中,左边已发生、右边将发生,节点上下交替。
 *
 * 几个刻意的决定:
 *
 * * **「现在」这条线固定在中央,不随拖动移动**。拖的是时间本身。如果让
 *   现在线跟着跑,人一松手就找不到「此刻在哪」了。
 * * **已发生的节点必须显示 outcome**。一个只标「做过了」的圆点没有价值 ——
 *   要能一眼看出那轮结论是什么、数据可不可信。
 * * **缩放按时间跨度而不是像素**。按像素缩放会让「一天」在不同缩放级别下
 *   宽度不同,人对照两个节点间隔时会得出错误的时间感。
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
}

// 缩放档位:每像素代表多少毫秒。跨度是真实时间,不是像素比例。
const ZOOMS = [
  { label: '6 小时', msPerPx: (6 * 3600e3) / 900 },
  { label: '1 天', msPerPx: (24 * 3600e3) / 900 },
  { label: '3 天', msPerPx: (72 * 3600e3) / 900 },
  { label: '7 天', msPerPx: (168 * 3600e3) / 900 },
]

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString('zh-CN', { hour12: false, month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit' })

export const TimelineTrack: React.FC<{
  nodes: Node[]
  onPick?: (n: Node) => void
}> = ({ nodes, onPick }) => {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(900)
  const [zoom, setZoom] = useState(1)
  const [offsetMs, setOffsetMs] = useState(0)     // 视图中心相对「现在」的偏移
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

  const msPerPx = ZOOMS[zoom].msPerPx
  const centerMs = now + offsetMs
  const half = (width / 2) * msPerPx

  const toX = (iso: string) => (new Date(iso).getTime() - centerMs) / msPerPx + width / 2

  // 上下交替,同侧再按时间错开高度 —— 否则密集时段的标签会叠在一起
  const laid = useMemo(() => {
    const sorted = [...nodes].sort(
      (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
    const lastX: Record<number, number> = {}
    return sorted.map((n, i) => {
      const x = toX(n.scheduled_at)
      const side = i % 2 === 0 ? -1 : 1
      // 同侧前一个太近就再抬高一层
      const key = side
      const crowded = lastX[key] !== undefined && Math.abs(x - lastX[key]) < 150
      lastX[key] = x
      return { node: n, x, side, lane: crowded ? 1 : 0 }
    })
  }, [nodes, centerMs, msPerPx, width])

  const visible = laid.filter((l) => l.x > -220 && l.x < width + 220)

  // 刻度:按缩放选一个整齐的间隔
  const tickMs = msPerPx * 150
  const step = [3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3, 72 * 3600e3]
    .find((s) => s >= tickMs) || 168 * 3600e3
  const firstTick = Math.ceil((centerMs - half) / step) * step
  const ticks: number[] = []
  for (let t = firstTick; t < centerMs + half; t += step) ticks.push(t)

  const onDown = (e: React.MouseEvent) => {
    setDrag({ x: e.clientX, base: offsetMs })
  }
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

  const H = 250

  return (
    <div style={{
      background: '#111827', border: '1px solid #1f2937',
      borderRadius: 10, padding: '10px 0 12px', marginBottom: 14,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '0 14px 8px', flexWrap: 'wrap',
      }}>
        <strong style={{ fontSize: 13, color: '#e5e7eb', marginRight: 'auto' }}>
          时间轴
          <span style={{ fontSize: 11, color: '#6b7280', fontWeight: 400, marginLeft: 8 }}>
            按住拖动 · 左为已发生
          </span>
        </strong>
        {ZOOMS.map((z, i) => (
          <button key={z.label} onClick={() => setZoom(i)} style={{
            background: zoom === i ? '#1e293b' : 'transparent',
            color: zoom === i ? '#60a5fa' : '#94a3b8',
            border: `1px solid ${zoom === i ? '#3b82f6' : '#1f2937'}`,
            borderRadius: 6, padding: '3px 9px', fontSize: 11, cursor: 'pointer',
          }}>{z.label}</button>
        ))}
        {offsetMs !== 0 && (
          <button onClick={() => setOffsetMs(0)} style={{
            background: '#2563eb', color: '#fff', border: 0,
            borderRadius: 6, padding: '3px 9px', fontSize: 11, cursor: 'pointer',
          }}>回到现在</button>
        )}
      </div>

      <div
        ref={boxRef}
        onMouseDown={onDown}
        style={{
          position: 'relative', height: H, overflow: 'hidden',
          cursor: drag ? 'grabbing' : 'grab', userSelect: 'none',
        }}
      >
        {/* 刻度 */}
        {ticks.map((t) => {
          const x = (t - centerMs) / msPerPx + width / 2
          return (
            <div key={t} style={{ position: 'absolute', left: x, top: 0, bottom: 0 }}>
              <div style={{ position: 'absolute', top: 0, bottom: 0, width: 1, background: '#1a2434' }} />
              <div style={{
                position: 'absolute', top: H / 2 + 8, left: 4, fontSize: 10,
                color: '#475569', whiteSpace: 'nowrap',
                fontFamily: 'ui-monospace, monospace',
              }}>
                {new Date(t).toLocaleString('zh-CN', { hour12: false, month: '2-digit',
                  day: '2-digit', hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          )
        })}

        {/* 主轴 */}
        <div style={{
          position: 'absolute', left: 0, right: 0, top: H / 2, height: 2,
          background: 'linear-gradient(90deg, #1f2937, #334155, #1f2937)',
        }} />

        {/* 现在线 —— 固定在正中,拖动的是时间不是它 */}
        <div style={{
          position: 'absolute', left: width / 2, top: 0, bottom: 0,
          width: 2, background: '#ef4444', opacity: .85,
        }}>
          <div style={{
            position: 'absolute', top: 2, left: 6, fontSize: 10, color: '#fca5a5',
            fontFamily: 'ui-monospace, monospace', whiteSpace: 'nowrap',
          }}>现在</div>
        </div>

        {/* 节点 */}
        {visible.map(({ node: n, x, side, lane }) => {
          const color = KIND_COLOR[n.kind] || '#64748b'
          const done = n.state === 'ACKED'
          const stalk = 26 + lane * 46
          const cardTop = side < 0 ? H / 2 - stalk - 62 : H / 2 + stalk
          const isHover = hover === n.node_id
          return (
            <div key={n.node_id}>
              <div style={{
                position: 'absolute', left: x - 1,
                top: side < 0 ? H / 2 - stalk : H / 2,
                width: 2, height: stalk, background: color, opacity: .5,
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
                  position: 'absolute', left: x - 92, top: cardTop, width: 184,
                  background: '#0f172a', border: `1px solid ${isHover ? color : '#1f2937'}`,
                  borderLeft: `3px solid ${color}`, borderRadius: 6,
                  padding: '5px 8px', cursor: 'pointer', transition: 'border-color .15s',
                }}
              >
                <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                  <span style={{ fontSize: 9, color, fontWeight: 600 }}>
                    {KIND_LABEL[n.kind] || n.kind}
                  </span>
                  <span style={{ fontSize: 9, color: done ? '#22c55e' : '#64748b' }}>
                    {STATE_LABEL[n.state] || n.state}
                  </span>
                </div>
                <div style={{
                  fontSize: 11, color: '#e2e8f0', marginTop: 1,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{n.intent}</div>
                {/* 已完成的必须显示结论 —— 只标「做过了」的圆点没有价值 */}
                {n.outcome ? (
                  <div style={{
                    fontSize: 10, color: '#94a3b8', marginTop: 2, lineHeight: 1.35,
                    display: '-webkit-box', WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical', overflow: 'hidden',
                  }}>{n.outcome}</div>
                ) : (
                  <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                    {fmtTime(n.scheduled_at)}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {visible.length === 0 && (
          <div style={{
            position: 'absolute', inset: 0, display: 'grid', placeItems: 'center',
            color: '#475569', fontSize: 12,
          }}>
            这段时间没有节点 —— 拖动或换个跨度看看
          </div>
        )}
      </div>
    </div>
  )
}

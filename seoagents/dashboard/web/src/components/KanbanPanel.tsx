import { useEffect, useState, useRef, useCallback } from 'react'
import { useIsMobile } from '../hooks'

/**
 * 任务流转看板 V4 — 横向泳道布局
 *
 * 布局：
 *   顶部统计胶囊
 *   ┌──────────────────────────────────────────┐
 *   │ ⚡ 执行中（横向展开，卡片含步骤+进度+连接线）│  ← 大区域，占满高度
 *   └──────────────────────────────────────────┘
 *   ┌──────────────┬───────────────────────────┐
 *   │ ⏳ 待办(1行)  │ ✅ 已完成(1行)            │  ← 各占一行卡片高度
 *   └──────────────┴───────────────────────────┘
 *   🔗 跨部门协作流（如有）
 *   ● 实时事件流
 */

type Task = {
  id: string; title: string; body: string; assignee: string; status: string
  priority: number; created_by: string
  created_at_iso: string | null; started_at_iso: string | null; completed_at_iso: string | null
  is_open: boolean; current_step_key?: string; workflow_template_id?: string
  last_failure_error?: string; consecutive_failures?: number
}

type Board = {
  ok: boolean; source: string; total: number; open_count: number
  columns: Record<string, Task[]>
  statuses: { open: string[]; closed: string[] }
}

type CollabItem = {
  request_id: string; title?: string; status: string
  from?: { dept: string }; to?: { dept: string; capability?: string }
  capability?: string; deadline?: string; overdue?: boolean
  deliverable_asset_ids?: string[]
  expected_deliverable?: { asset_class: string; count: number; acceptance: string[] }
  priority?: string
}

const T = {
  bg: '#0b0e14', bg2: '#11151f', panel: '#161b28', panel2: '#1c2333',
  line: '#252d40', txt: '#dde3f0', dim: '#8b93a7', faint: '#5a6275',
  acc: '#4f8cff', ok: '#3ecf8e', warn: '#f5b83d', bad: '#f4655f', rev: '#b07cff',
}

const ST: Record<string, { label: string; color: string }> = {
  pending:{label:'待办',color:T.dim}, todo:{label:'待办',color:T.dim},
  in_progress:{label:'进行中',color:T.acc}, running:{label:'执行中',color:T.acc},
  review:{label:'待验收',color:T.rev}, blocked:{label:'阻塞',color:T.bad},
  done:{label:'完成',color:T.ok}, completed:{label:'完成',color:T.ok},
  failed:{label:'失败',color:T.bad}, cancelled:{label:'取消',color:T.faint},
}

const COLLAB_ST: Record<string,{color:string;label:string}> = {
  PENDING:{color:T.dim,label:'待处理'}, ACCEPTED:{color:T.acc,label:'已接收'},
  IN_PROGRESS:{color:T.acc,label:'执行中'}, BLOCKED:{color:T.warn,label:'阻塞'},
  DELIVERED:{color:T.rev,label:'已交付'}, RETURNED:{color:'#f97316',label:'已退回'},
  REJECTED:{color:T.bad,label:'已拒绝'}, EXPIRED:{color:T.faint,label:'已过期'},
  ESCALATED:{color:T.bad,label:'已升级'}, CLOSED:{color:T.ok,label:'已关闭'},
}

const POLL = 5000

const CSS = `
@keyframes kp-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1}}
@keyframes kp-glow{0%,100%{box-shadow:0 0 0 0 transparent}50%{box-shadow:0 0 14px 2px var(--kp-glow,transparent)}}
@keyframes kp-blink{50%{opacity:.25}}
@keyframes kp-dash{to{background-position:24px 0}}
@keyframes kp-spin{to{transform:rotate(360deg)}}
@keyframes kp-step-glow{0%,100%{border-color:var(--kp-glow,T.acc)}50%{border-color:color-mix(in srgb,var(--kp-glow,T.acc) 30%,var(--kp-line,T.line))}}
.kp-ev{animation:kp-in .3s ease-out}
.kp-run{animation:kp-glow 2s ease-in-out infinite}
.kp-dot{display:inline-block;width:7px;height:7px;border-radius:50%;animation:kp-blink 1.5s infinite}
.kp-arrow{background:repeating-linear-gradient(90deg,currentColor 0 6px,transparent 6px 12px);background-size:24px 2px;animation:kp-dash .8s linear infinite;opacity:.7}
.kp-spin{animation:kp-spin 1s linear infinite}
.kp-step-active{animation:kp-step-glow 1.6s ease-in-out infinite}
`

const StatPill = ({n,label,color}:{n:number;label:string;color:string}) => (
  <div style={{display:'flex',alignItems:'baseline',gap:6,background:T.bg2,border:`1px solid ${T.line}`,borderRadius:9,padding:'6px 12px'}}>
    <span style={{fontSize:19,fontWeight:700,fontFamily:'SF Mono,monospace',color:n>0?color:T.faint}}>{n}</span>
    <span style={{fontSize:11,color:T.dim}}>{label}</span>
  </div>
)

const miniBtn = (bg:string,fg:string):React.CSSProperties => ({
  background:bg,color:fg,border:0,borderRadius:4,padding:'2px 7px',fontSize:9,fontWeight:600,cursor:'pointer',
})

export const KanbanPanel: React.FC = () => {
  const isMobile = useIsMobile()
  const [board,setBoard] = useState<Board|null>(null)
  const [health,setHealth] = useState<any>(null)
  const [inbox,setInbox] = useState<CollabItem[]>([])
  const [outbox,setOutbox] = useState<CollabItem[]>([])
  const [collabError,setCollabError] = useState('')
  const [loading,setLoading] = useState(true)
  const [detail,setDetail] = useState<any>(null)
  const [showNew,setShowNew] = useState(false)
  const [newTitle,setNewTitle] = useState('')
  const [newBody,setNewBody] = useState('')
  const [newAssignee,setNewAssignee] = useState('hm')
  const [msg,setMsg] = useState('')
  const [autoRefresh,setAutoRefresh] = useState(true)
  const [events,setEvents] = useState<{id:string;text:string;ts:number;type:string}[]>([])
  const [lastUpdate,setLastUpdate] = useState(0)
  const [,forceTick] = useState(0)
  const prevRef = useRef<Board|null>(null)
  const evCtr = useRef(0)

  const addEv = useCallback((text:string,type:string) => {
    evCtr.current++
    setEvents(p => [{id:`ev-${evCtr.current}`,text,ts:Date.now(),type},...p].slice(0,30))
  },[])

  const load = useCallback(async() => {
    try {
      const h = await (await fetch('/api/kanban/health')).json()
      setHealth(h)
      if (h.reachable) {
        const b = await (await fetch('/api/kanban/board')).json()
        if (prevRef.current) {
          const pm = new Map<string,any>()
          Object.values(prevRef.current.columns).flat().forEach((t:any) => pm.set(t.id,t))
          Object.values(b.columns).flat().forEach((t:any) => {
            const old = pm.get(t.id)
            if (!old) addEv(`新卡: ${t.title}`,'create')
            else if (old.status !== t.status) {
              addEv(`${t.title} → ${ST[t.status]?.label||t.status}`, t.status==='done'?'done':'move')
            }
          })
        }
        prevRef.current = b
        setBoard(b)
      }
      try {
        const [i,o] = await Promise.all([(await fetch('/api/v1/inbox')).json(),(await fetch('/api/v1/outbox')).json()])
        setInbox(i.items||[]); setOutbox(o.items||[]); setCollabError('')
      } catch { setCollabError('协作服务不可用') }
    } catch { /* silent */ } finally { setLoading(false); setLastUpdate(Date.now()) }
  },[addEv])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (!autoRefresh) return; const t = setInterval(load,POLL); return () => clearInterval(t) }, [autoRefresh,load])
  useEffect(() => { const t = setInterval(() => forceTick(x => x+1), 1000); return () => clearInterval(t) }, [])

  const move = async (id:string,status:string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})})
    if (!r.ok) { setMsg(`流转失败: ${(await r.json()).detail}`); return }
    setMsg(''); load()
  }
  const openDetail = async (id:string) => {
    const r = await fetch(`/api/kanban/tasks/${id}`)
    const j = await r.json()
    setDetail(r.ok ? j.task : {id,error:j.detail})
  }
  const create = async () => {
    if (!newTitle.trim()) return
    const r = await fetch('/api/kanban/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:newTitle,body:newBody,assignee:newAssignee,created_by:'dashboard'})})
    if (!r.ok) { setMsg(`建卡失败: ${(await r.json()).detail}`); return }
    setNewTitle(''); setNewBody(''); setShowNew(false); setMsg(''); load()
  }

  const cols = board?.columns || {}
  const laneRunning = [...(cols.in_progress||[]),...(cols.running||[])]
  const laneReview = [...(cols.review||[])]
  const lanePending = [...(cols.pending||[]),...(cols.todo||[])]
  const laneBlocked = [...(cols.blocked||[])]
  const laneDone = [...(cols.done||[]),...(cols.completed||[]),...(cols.failed||[]),...(cols.cancelled||[])]
  const total = board?.total ?? 0
  const doneCount = laneDone.length
  const progress = total > 0 ? Math.round((doneCount/total)*100) : 0
  const secsAgo = lastUpdate ? Math.floor((Date.now()-lastUpdate)/1000) : 0

  if (loading && !board) return (
    <div style={{color:T.dim,textAlign:'center',padding:40,display:'flex',alignItems:'center',justifyContent:'center',gap:8}}>
      <span className="kp-spin" style={{display:'inline-block',width:14,height:14,border:`2px solid ${T.line}`,borderTopColor:T.acc,borderRadius:'50%'}} />
      正在载入...
    </div>
  )
  if (health && !health.reachable) return (
    <div style={{background:T.panel,border:`1px solid ${T.bad}40`,borderRadius:10,padding:16}}>
      <div style={{color:T.bad,fontWeight:700}}>⚠️ seohm 看板未接通</div>
      <div style={{color:T.dim,fontSize:12,marginTop:4}}>{health.reason}</div>
    </div>
  )

  // ═══ 横向执行中卡片（含步骤+连接线）═══
  const renderRunningCard = (t:Task) => {
    const s = ST[t.status] || {label:t.status,color:T.faint}
    const isCollab = t.workflow_template_id?.startsWith('REQ-')
    return (
      <div key={t.id} style={{display:'flex',alignItems:'stretch',gap:0,minWidth:0}}>
        {/* 卡片 */}
        <div
          className="kp-run"
          onClick={() => openDetail(t.id)}
          style={{
            '--kp-glow': s.color+'60',
            background:T.bg2, border:`1px solid ${T.line}`, borderLeft:`4px solid ${s.color}`,
            borderRadius:10, padding:'10px 12px', cursor:'pointer', width:260, minWidth:260,
            transition:'transform .12s, border-color .12s',
          } as React.CSSProperties}
          onMouseEnter={e=>{e.currentTarget.style.transform='translateY(-2px)';e.currentTarget.style.borderColor=s.color}}
          onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';e.currentTarget.style.borderColor=T.line}}
        >
          {/* header */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
            <span style={{fontWeight:600,fontSize:13,color:T.txt,lineHeight:1.35,flex:1}}>
              {isCollab && <span style={{color:T.rev,marginRight:4}}>🔗</span>}
              {t.title}
            </span>
            <span style={{fontFamily:'SF Mono,monospace',fontSize:10,color:t.priority<=2?T.bad:T.faint,flexShrink:0,marginLeft:6}}>
              P{t.priority}
            </span>
          </div>
          {/* status + assignee */}
          <div style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
            <span className="kp-dot" style={{background:s.color,width:6,height:6}}/>
            <span style={{fontSize:11,color:s.color,fontWeight:600}}>{s.label}</span>
            <span style={{fontSize:11,color:T.dim}}>· 👤 {t.assignee || '未指派'}</span>
          </div>
          {/* current step */}
          {t.current_step_key && (
            <div style={{marginTop:6,fontSize:11,color:T.dim,background:T.panel2,borderRadius:6,padding:'4px 8px',border:`1px solid ${T.line}`,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>
              ⚡ {t.current_step_key}
            </div>
          )}
          {/* progress bar */}
          <div style={{marginTop:6,height:4,background:T.line,borderRadius:3,overflow:'hidden'}}>
            <div style={{height:'100%',width:t.status==='running'?'60%':t.status==='in_progress'?'35%':'10%',background:`linear-gradient(90deg,${s.color},${s.color}aa)`,transition:'width .5s'}}/>
          </div>
          {/* failure */}
          {t.last_failure_error && (
            <div style={{color:T.bad,fontSize:10,marginTop:4}}>✗ {t.last_failure_error.slice(0,45)}{(t.consecutive_failures||0)>1?` (×${t.consecutive_failures})`:''}</div>
          )}
          {/* buttons */}
          <div style={{display:'flex',gap:4,marginTop:6}} onClick={e=>e.stopPropagation()}>
            <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok)}>完成</button>
            <button onClick={()=>move(t.id,'review')} style={miniBtn(T.rev+'20',T.rev)}>验收</button>
            <button onClick={()=>move(t.id,'blocked')} style={miniBtn(T.warn+'20',T.warn)}>阻塞</button>
          </div>
        </div>
        {/* 连接线 */}
        <div style={{width:36,minWidth:36,display:'flex',alignItems:'center',justifyContent:'center'}}>
          <div className="kp-arrow" style={{width:'100%',height:2,color:s.color}}/>
        </div>
      </div>
    )
  }

  // ═══ 紧凑卡片（待办/已完成列）═══
  const renderCompactCard = (t:Task) => {
    const s = ST[t.status] || {label:t.status,color:T.faint}
    return (
      <div
        key={t.id}
        onClick={() => openDetail(t.id)}
        style={{
          background:T.bg2,border:`1px solid ${T.line}`,borderLeft:`3px solid ${s.color}`,
          borderRadius:8,padding:'6px 10px',cursor:'pointer',minWidth:0,
          transition:'transform .12s, border-color .12s',
        }}
        onMouseEnter={e=>{e.currentTarget.style.transform='translateY(-1px)';e.currentTarget.style.borderColor=s.color}}
        onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';e.currentTarget.style.borderColor=T.line}}
      >
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:6}}>
          <span style={{fontSize:12,fontWeight:600,color:T.txt,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',flex:1}}>
            {t.workflow_template_id?.startsWith('REQ-') && <span style={{color:T.rev,marginRight:3}}>🔗</span>}
            {t.title}
          </span>
          <span style={{fontSize:9,color:s.color,fontWeight:600,flexShrink:0}}>{s.label}</span>
        </div>
        <div style={{fontSize:10,color:T.faint,marginTop:1}}>
          👤 {t.assignee||'—'} · {t.created_at_iso||''}
        </div>
      </div>
    )
  }

  return (
    <div style={{display:'flex',flexDirection:'column',gap:12}}>
      <style>{CSS}</style>

      {/* ═══ 统计胶囊 ═══ */}
      <div style={{display:'flex',gap:8,flexWrap:'wrap',alignItems:'center'}}>
        <StatPill n={laneRunning.length} label="执行中" color={T.acc} />
        <StatPill n={laneReview.length} label="待验收" color={T.rev} />
        <StatPill n={lanePending.length} label="待办" color={T.dim} />
        <StatPill n={laneBlocked.length} label="阻塞" color={T.bad} />
        <StatPill n={doneCount} label="完成" color={T.ok} />
        <div style={{marginLeft:'auto',display:'flex',gap:6,alignItems:'center'}}>
          {autoRefresh && <span style={{display:'flex',alignItems:'center',gap:4,fontSize:10,color:T.ok}}>
            <span className="kp-dot" style={{background:T.ok,width:6,height:6}}/>LIVE · {secsAgo}s
          </span>}
          <div style={{width:80,height:5,background:T.line,borderRadius:3,overflow:'hidden'}}>
            <div style={{height:'100%',width:`${progress}%`,background:`linear-gradient(90deg,${T.ok},${T.acc})`,transition:'width .5s'}}/>
          </div>
          <span style={{fontSize:10,color:T.faint}}>{progress}%</span>
          <button onClick={()=>setAutoRefresh(!autoRefresh)} style={{padding:'4px 8px',fontSize:11,borderRadius:6,border:`1px solid ${autoRefresh?T.ok+'40':T.line}`,background:autoRefresh?T.ok+'15':T.panel2,color:autoRefresh?T.ok:T.dim,cursor:'pointer'}}>{autoRefresh?'⏸':'▶'}</button>
          <button onClick={()=>setShowNew(!showNew)} style={{padding:'4px 10px',fontSize:11,borderRadius:6,border:`1px solid ${T.acc}`,background:T.acc,color:'#fff',cursor:'pointer'}}>＋</button>
          <button onClick={load} style={{padding:'4px 8px',fontSize:11,borderRadius:6,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>↻</button>
        </div>
      </div>

      {msg && <div style={{background:T.bad+'15',border:`1px solid ${T.bad}40`,borderRadius:8,padding:'8px 12px',color:T.bad,fontSize:12}}>{msg}</div>}

      {showNew && (
        <div style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:14,display:'flex',flexDirection:'column',gap:6}}>
          <input placeholder="任务标题" value={newTitle} onChange={e=>setNewTitle(e.target.value)} style={{background:T.bg2,border:`1px solid ${T.line}`,borderRadius:7,color:T.txt,fontSize:12,padding:'6px 10px'}}/>
          <textarea placeholder="描述（可选）" value={newBody} onChange={e=>setNewBody(e.target.value)} rows={2} style={{background:T.bg2,border:`1px solid ${T.line}`,borderRadius:7,color:T.txt,fontSize:12,padding:'6px 10px',resize:'vertical'}}/>
          <div style={{display:'flex',gap:6}}>
            <input placeholder="指派给" value={newAssignee} onChange={e=>setNewAssignee(e.target.value)} style={{background:T.bg2,border:`1px solid ${T.line}`,borderRadius:7,color:T.txt,fontSize:12,padding:'6px 10px',width:120}}/>
            <button onClick={create} disabled={!newTitle.trim()} style={{padding:'6px 14px',fontSize:12,borderRadius:7,border:0,background:newTitle.trim()?T.acc:T.line,color:'#fff',cursor:'pointer'}}>创建</button>
          </div>
        </div>
      )}

      {/* ═══ 执行中泳道（大区域，横向展开）═══ */}
      <div style={{
        background:T.panel, border:`1px solid ${T.line}`, borderRadius:10, padding:14,
        display:'flex', flexDirection:'column', gap:8,
      }}>
        <div style={{display:'flex',alignItems:'center',gap:6,paddingBottom:6,borderBottom:`1px solid ${T.line}`}}>
          <span className="kp-dot" style={{background:T.acc,width:6,height:6}}/>
          <span style={{fontSize:12,fontWeight:700,color:T.acc}}>⚡ 执行中</span>
          <span style={{fontSize:11,color:T.faint}}>{laneRunning.length}</span>
          {laneReview.length > 0 && <>
            <span style={{color:T.faint,margin:'0 4px'}}>·</span>
            <span style={{fontSize:12,fontWeight:700,color:T.rev}}>🔍 待验收</span>
            <span style={{fontSize:11,color:T.faint}}>{laneReview.length}</span>
          </>}
          {laneBlocked.length > 0 && <>
            <span style={{color:T.faint,margin:'0 4px'}}>·</span>
            <span style={{fontSize:12,fontWeight:700,color:T.bad}}>🚫 阻塞</span>
            <span style={{fontSize:11,color:T.faint}}>{laneBlocked.length}</span>
          </>}
        </div>
        {/* 横向卡片流 */}
        <div style={{
          display:'flex', alignItems:'flex-start', gap:0, overflowX:'auto', paddingBottom:4,
          minHeight: laneRunning.length > 0 ? 140 : 40,
        }}>
          {laneRunning.length === 0 && laneReview.length === 0 && laneBlocked.length === 0 && (
            <div style={{color:T.faint,fontSize:12,padding:'16px 0'}}>暂无执行中任务</div>
          )}
          {laneRunning.map(renderRunningCard)}
          {/* 待验收卡片 */}
          {laneReview.map(t => {
            const s = ST[t.status] || {label:t.status,color:T.faint}
            return (
              <div key={t.id} style={{display:'flex',alignItems:'stretch'}}>
                <div onClick={()=>openDetail(t.id)} style={{
                  background:T.bg2, border:`1px solid ${s.color}40`, borderLeft:`4px solid ${s.color}`,
                  borderRadius:10, padding:'10px 12px', cursor:'pointer', width:260, minWidth:260,
                }}>
                  <div style={{fontWeight:600,fontSize:13,color:T.txt}}>{t.title}</div>
                  <div style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
                    <span className="kp-dot" style={{background:s.color,width:6,height:6}}/>
                    <span style={{fontSize:11,color:s.color,fontWeight:600}}>{s.label}</span>
                  </div>
                  <div style={{display:'flex',gap:4,marginTop:6}} onClick={e=>e.stopPropagation()}>
                    <button onClick={()=>move(t.id,'done')} style={miniBtn(T.ok+'20',T.ok)}>验收通过</button>
                    <button onClick={()=>move(t.id,'in_progress')} style={miniBtn(T.warn+'20',T.warn)}>退回</button>
                  </div>
                </div>
                <div style={{width:36,minWidth:36,display:'flex',alignItems:'center',justifyContent:'center'}}>
                  <div className="kp-arrow" style={{width:'100%',height:2,color:s.color}}/>
                </div>
              </div>
            )
          })}
          {/* 阻塞卡片 */}
          {laneBlocked.map(t => {
            const s = ST[t.status] || {label:t.status,color:T.faint}
            return (
              <div key={t.id} style={{display:'flex',alignItems:'stretch'}}>
                <div onClick={()=>openDetail(t.id)} style={{
                  background:T.bg2, border:`1px solid ${s.color}40`, borderLeft:`4px solid ${s.color}`,
                  borderRadius:10, padding:'10px 12px', cursor:'pointer', width:260, minWidth:260,
                }}>
                  <div style={{fontWeight:600,fontSize:13,color:T.txt}}>{t.title}</div>
                  <div style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
                    <span className="kp-dot" style={{background:s.color,width:6,height:6}}/>
                    <span style={{fontSize:11,color:s.color,fontWeight:600}}>{s.label}</span>
                  </div>
                  {t.last_failure_error && <div style={{color:T.bad,fontSize:10,marginTop:3}}>✗ {t.last_failure_error.slice(0,45)}</div>}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ═══ 待办 + 已完成（各一行）═══ */}
      <div style={{display:'grid',gridTemplateColumns:isMobile?'1fr':'1fr 1fr',gap:12}}>
        {/* 待办 */}
        <div style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:12}}>
          <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:8,paddingBottom:6,borderBottom:`1px solid ${T.line}`}}>
            <span className="kp-dot" style={{background:T.dim,width:6,height:6}}/>
            <span style={{fontSize:12,fontWeight:700,color:T.dim}}>⏳ 待办</span>
            <span style={{fontSize:11,color:T.faint}}>{lanePending.length}</span>
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:5,maxHeight:200,overflowY:'auto'}}>
            {lanePending.length === 0
              ? <div style={{color:T.faint,fontSize:11,padding:'8px 0'}}>空</div>
              : lanePending.map(renderCompactCard)}
          </div>
        </div>
        {/* 已完成 */}
        <div style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:12}}>
          <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:8,paddingBottom:6,borderBottom:`1px solid ${T.line}`}}>
            <span className="kp-dot" style={{background:T.ok,width:6,height:6}}/>
            <span style={{fontSize:12,fontWeight:700,color:T.ok}}>✅ 已完成</span>
            <span style={{fontSize:11,color:T.faint}}>{doneCount}</span>
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:5,maxHeight:200,overflowY:'auto'}}>
            {laneDone.length === 0
              ? <div style={{color:T.faint,fontSize:11,padding:'8px 0'}}>空</div>
              : laneDone.map(renderCompactCard)}
          </div>
        </div>
      </div>

      {/* ═══ 跨部门协作流 ═══ */}
      {(inbox.length>0||outbox.length>0) && (
        <div style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:14}}>
          <div style={{fontSize:13,fontWeight:700,color:T.txt,marginBottom:10}}>🔗 跨部门协作流</div>
          <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:16,marginBottom:12}}>
            <div style={{textAlign:'center'}}><div style={{fontSize:18,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.acc}}>{outbox.length}</div><div style={{fontSize:10,color:T.dim}}>📤 发出</div></div>
            <div className="kp-arrow" style={{width:50,height:2,color:T.dim}}/>
            <div style={{textAlign:'center'}}><div style={{fontSize:18,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.rev}}>{inbox.length+outbox.length}</div><div style={{fontSize:10,color:T.dim}}>协作中</div></div>
            <div className="kp-arrow" style={{width:50,height:2,color:T.dim}}/>
            <div style={{textAlign:'center'}}><div style={{fontSize:18,fontWeight:700,fontFamily:'SF Mono,monospace',color:T.ok}}>{inbox.length}</div><div style={{fontSize:10,color:T.dim}}>📥 接收</div></div>
          </div>
          <div style={{display:'grid',gridTemplateColumns:isMobile?'1fr':'1fr 1fr',gap:10}}>
            {[['📤 发件箱',outbox],['📥 收件箱',inbox]].map(([title,items]:any)=>(
              <div key={title}>
                <div style={{fontSize:11,fontWeight:700,color:T.dim,marginBottom:5}}>{title} ({items.length})</div>
                {items.length===0 && <div style={{color:T.faint,fontSize:11,padding:'8px 0'}}>暂无</div>}
                {items.map((it:CollabItem)=>{
                  const meta = COLLAB_ST[it.status]||{color:T.faint,label:it.status}
                  return (
                    <div key={it.request_id} style={{background:T.bg2,border:`1px solid ${meta.color}30`,borderLeft:`3px solid ${meta.color}`,borderRadius:8,padding:'6px 10px',marginBottom:5,fontSize:11}}>
                      <div style={{display:'flex',justifyContent:'space-between'}}><span style={{color:T.txt,fontWeight:600}}>{it.capability||it.to?.capability||'—'}</span><span style={{fontSize:9,fontWeight:700,padding:'1px 6px',borderRadius:3,background:meta.color+'20',color:meta.color}}>{meta.label}</span></div>
                      <div style={{color:T.dim,fontSize:10,marginTop:2}}>📤 {it.from?.dept||it.to?.dept||'—'} · {it.priority||''} {it.deadline&&`· ⏰ ${it.deadline.slice(0,10)}`}</div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ 实时事件流 ═══ */}
      {events.length>0 && (
        <div style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:14}}>
          <div style={{fontSize:12,fontWeight:700,color:T.dim,marginBottom:8,display:'flex',alignItems:'center',gap:6}}>
            <span className="kp-dot" style={{background:T.acc,width:6,height:6}}/>实时事件流
            <span style={{fontSize:10,color:T.faint,fontWeight:400}}>最近 {events.length} 条</span>
          </div>
          <div style={{maxHeight:200,overflowY:'auto'}}>
            {events.map(ev=>{
              const colors:any={move:T.acc,create:T.ok,done:T.ok,error:T.bad}
              const icons:any={move:'→',create:'✨',done:'🎉',error:'✗'}
              const age=Math.floor((Date.now()-ev.ts)/1000)
              const ageStr=age<60?`${age}s`:age<3600?`${Math.floor(age/60)}m`:`${Math.floor(age/3600)}h`
              return (
                <div key={ev.id} className="kp-ev" style={{display:'flex',gap:8,padding:'5px 0',borderBottom:`1px solid ${T.line}50`,fontSize:12}}>
                  <span style={{color:colors[ev.type]||T.dim,fontWeight:700}}>{icons[ev.type]||'•'}</span>
                  <span style={{color:T.txt,flex:1}}>{ev.text}</span>
                  <span style={{color:T.faint,fontSize:10,fontFamily:'SF Mono,monospace'}}>{ageStr}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ═══ 详情弹窗 ═══ */}
      {detail && (
        <div onClick={()=>setDetail(null)} style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.8)',zIndex:9999,display:'flex',alignItems:'center',justifyContent:'center',padding:20}}>
          <div onClick={e=>e.stopPropagation()} style={{background:T.panel,border:`1px solid ${T.line}`,borderRadius:10,padding:16,width:'100%',maxWidth:640,maxHeight:'85vh',overflowY:'auto'}}>
            {detail.error ? (
              <div style={{color:T.bad}}>{detail.error}</div>
            ) : (
              <>
                <div style={{fontSize:15,fontWeight:700,color:T.txt}}>{detail.title}</div>
                <div style={{fontSize:10,color:T.faint,marginTop:2,fontFamily:'SF Mono,monospace'}}>
                  {detail.id} · {detail.status} · P{detail.priority} · 👤{detail.assignee||'未指派'}
                </div>
                {detail.body && <div style={{color:T.txt,fontSize:12,marginTop:10,whiteSpace:'pre-wrap'}}>{detail.body}</div>}
                {(detail.runs||[]).length>0 && (
                  <div style={{marginTop:12}}>
                    <div style={{fontSize:12,fontWeight:700,color:T.dim,marginBottom:6}}>执行记录</div>
                    {detail.runs.map((r:any)=>(
                      <div key={r.id} style={{background:T.bg2,borderRadius:6,padding:6,marginTop:4,fontSize:10,color:T.dim}}>
                        #{r.id} {r.step_key} · {r.status} {r.error&&<span style={{color:T.bad}}>✗ {r.error}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {(detail.events||[]).length>0 && (
                  <details style={{marginTop:12}}>
                    <summary style={{cursor:'pointer',fontSize:11,color:T.faint}}>事件轨迹 ({detail.events.length})</summary>
                    {detail.events.map((e:any)=>(
                      <div key={e.id} style={{fontSize:10,color:T.faint,marginTop:3,fontFamily:'SF Mono,monospace'}}>{e.kind} · {e.payload}</div>
                    ))}
                  </details>
                )}
                <button onClick={()=>setDetail(null)} style={{marginTop:14,padding:'6px 14px',fontSize:12,borderRadius:7,border:`1px solid ${T.line}`,background:T.panel2,color:T.txt,cursor:'pointer'}}>关闭</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

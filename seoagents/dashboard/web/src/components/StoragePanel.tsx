import { useEffect, useMemo, useState } from 'react'
import { useIsMobile } from '../hooks'
import { Modal, Field, inputStyle, btn, formatApiError, parseApiResponse, useToast } from '../ui'

/**
 * 中央存储与资产台账(改版)。
 *
 * 改版做了四件事:分类带计数、点资产名直接打开、上传、拿链接。
 *
 * ── 为什么是双模式 ──────────────────────────────────────────────
 * 现有本地后端有两个硬限制:`POST /api/storage/assets` 只收 `content: string`
 * (**纯文本,传不了二进制**),而且没有任何签直取链接的端点。所以「上传文件 +
 * 拿分享链接」在本地模式下做不到 —— 那正是中央存储调度中心存在的理由。
 *
 * 于是页面同时支持两条路:
 *   本地模式  走 /api/storage/*。文本可传,「链接」只能给落点(node:key)
 *   中心模式  走调度中心 /v1/*。二进制可传,链接是真的一次性直取 URL
 *
 * 填了调度中心地址就自动切过去,**并且界面上明说现在是哪种模式** ——
 * 17 号文 §7 的迁移是「双写观察一周」再切,那期间两条路都得在,
 * 而且必须能一眼看出走的是哪条。藏起来的话,观察期就没法观察。
 *
 * ── 保留的老规矩 ────────────────────────────────────────────────
 * 界面上**不提供改 level 的入口**。声明是 L3 就得按 L3 交付 —— 经验库里
 * `2026-07-21 终验擅自降低已声明资产类别` 那条原案,就是在终验环节把 L3
 * 改成 L2 混过去的。门禁做在数据库,界面也不给这个念头留口子。
 *
 * L3 的 backup_location 也不给人填:提交时系统真的镜像到第二个节点,
 * 拿实际落点写入。手填一行字什么都能过,那是纸面合规。
 */

/**
 * 节点配额。两边字段名不一样,统一归一化成这个形状再渲染:
 *   本地 /api/storage/quota → {quota:{storage_gb}, usage:{bytes_stored}, ratios:{bytes_stored}}
 *   调度中心 /v1/nodes      → {capacity_bytes, used_bytes, used_ratio}
 * 之前直接按后者的键名读前者,全是 undefined —— 于是容量和已用一片空白。
 */
type QuotaNode = {
  node: string; label: string; writable: boolean
  used: number; capacity: number; ratio: number
  blockReason?: string
  /** 按本月速率外推到月底的占用。17 号文 §4.3 的「月底预估」就是它 */
  forecast?: number
  warnings?: string[]
}
type Asset = {
  asset_id: string; name: string; class: string; level: string; status: string
  location?: string; storage_node?: string; backup_location?: string
  size_bytes?: number | string; checksum?: string
  owner_department?: string; summary?: string; created_at?: string
}

const LEVEL_COLOR: Record<string, string> = {
  L0: 'var(--faint)', L1: 'var(--accent)', L2: 'var(--warn)', L3: 'var(--bad)',
}
const LEVEL_HINT: Record<string, string> = {
  L1: '临时产出,可再生',
  L2: '常规资产,单点存储即可',
  L3: '核心资产,必须有异地备份与回滚方案',
}
const STATUS_LABEL: Record<string, string> = {
  ACTIVE: '已落地', DECLARED: '已声明', ARCHIVED: '已归档', DELETED: '已删除',
}
/** 「已声明」不等于「已落地」—— 这两个混在一起看,台账就失去意义了 */
const STATUS_HINT: Record<string, string> = {
  ACTIVE: '字节确认落地,校验和已核',
  DECLARED: '只是声明了要产出,**没有验证过字节真的在**',
}

/**
 * 按扩展名认类型。**不给「自动」留兜底成 misc 的机会** ——
 * 认不出来时把下拉留给人选,而不是默默塞个 misc:
 * 台账里一堆 misc 等于没有分类。
 */
const KIND_BY_EXT: Record<string, string> = {
  md: 'doc', txt: 'doc', pdf: 'doc', docx: 'doc', rtf: 'doc',
  json: 'dataset', csv: 'dataset', tsv: 'dataset', xlsx: 'dataset', parquet: 'dataset', db: 'dataset',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'image',
  py: 'code', ts: 'code', tsx: 'code', js: 'code', jsx: 'code', sh: 'code',
  sql: 'code', yaml: 'code', yml: 'code', toml: 'code', go: 'code', rs: 'code',
  zip: 'backup', tar: 'backup', gz: 'backup', bz2: 'backup', bak: 'backup', dump: 'backup',
  log: 'report', html: 'report',
}
const CLASS_BY_KIND: Record<string, string> = {
  doc: 'DOC', report: 'DOC', dataset: 'DATA', image: 'IMAGE', code: 'CODE', backup: 'DATA',
}
const KIND_OPTIONS = ['doc', 'report', 'dataset', 'image', 'code', 'backup', 'misc']

/** 纵轴的类别导航。顺序固定 —— 位置会变的导航栏没法形成肌肉记忆 */
const CLASS_NAV: { id: string; label: string; icon: string }[] = [
  { id: '', label: '全部资产', icon: '▤' },
  { id: 'DOC', label: '文档', icon: '📄' },
  { id: 'DATA', label: '数据', icon: '📊' },
  { id: 'CODE', label: '代码', icon: '⌨' },
  { id: 'IMAGE', label: '图片', icon: '🖼' },
  { id: 'INFRA', label: '基础设施', icon: '⚙' },
  { id: 'OTHER', label: '未分类', icon: '◇' },
]

/**
 * 资产的类别。台账里 `class` 可能是空的(旧记录、别的部门写进来的),
 * 空的时候按文件名推 —— 否则它们全挤在「未分类」里,纵轴导航就废了。
 * 推不出来才真的算未分类。
 */
const effectiveClass = (a: { class?: string; name?: string }): string => {
  const raw = (a.class || '').toUpperCase()
  if (raw && CLASS_NAV.some(c => c.id === raw)) return raw
  const ext = (a.name || '').split('.').pop()?.toLowerCase() || ''
  const kind = KIND_BY_EXT[ext]
  return kind ? (CLASS_BY_KIND[kind] || 'OTHER') : 'OTHER'
}

/** 能在弹窗里直接看的类型 —— 其余给「新窗口打开」 */
const previewKind = (name: string, ct?: string): 'text' | 'image' | 'pdf' | 'binary' => {
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (/^image\//.test(ct || '') || ['png','jpg','jpeg','gif','webp','svg'].includes(ext)) return 'image'
  if (ext === 'pdf' || ct === 'application/pdf') return 'pdf'
  if (/^text\//.test(ct || '') || ['md','txt','json','csv','tsv','log','yaml','yml','py','ts','tsx','js','sh','sql','html','toml'].includes(ext)) return 'text'
  return 'binary'
}

const EMPTY = {
  name: '', content: '', dept: 'shared', kind: 'misc', level: 'L1',
  asset_class: 'DOC', task_id: '', owner_agent: '', summary: '', usage: '',
  source_evidence: '', node_id: '', rollback: '', review_cycle: '90d',
}

const fmtSize = (b?: number | string) => {
  const n = Number(b || 0)
  if (!n) return '—'
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)}M`
  if (n >= 1024) return `${(n / 1024).toFixed(0)}K`
  return `${n}B`
}

export const StoragePanel: React.FC = () => {
  const isMobile = useIsMobile()
  const toast = useToast()
  const [quota, setQuota] = useState<QuotaNode[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [busy, setBusy] = useState(false)

  // 分类:等级 / 状态 / 类别 / 部门,四维独立筛选
  const [fLevel, setFLevel] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [fClass, setFClass] = useState('')
  const [fDept, setFDept] = useState('')
  const [fNode, setFNode] = useState('')
  const [fKind, setFKind] = useState('')
  const [q, setQ] = useState('')

  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ ...EMPTY })
  const [detail, setDetail] = useState<Asset | null>(null)
  const [depts, setDepts] = useState<string[]>([])
  // 预览:点资产名后在**当前页**开大弹窗,不再跳新标签页
  const [preview, setPreview] = useState<{
    asset: Asset; kind: 'text' | 'image' | 'pdf' | 'binary'
    text?: string; url?: string; warn?: string
  } | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  // 列表 / 卡片。列表适合比对字段(等级、备份、大小对齐着看),
  // 卡片适合浏览(尤其图片类)。两种场景都真实存在,所以给开关而不是替换。
  const [view, setView] = useState<'list' | 'card'>(
    () => (sessionStorage.getItem('storageView') as 'list' | 'card') || 'list')
  const switchView = (v: 'list' | 'card') => { setView(v); sessionStorage.setItem('storageView', v) }

  // 调度中心地址。留空 = 本地模式。这是 17 号文 §7 第 3 步的开关
  const [hubBase, setHubBase] = useState(() => localStorage.getItem('hubBase') || '')
  const [hubToken, setHubToken] = useState(() => localStorage.getItem('hubToken') || '')
  // 显式开关：即使填了中心地址，也要手动打开才走中心模式
  const [hubEnabled, setHubEnabled] = useState(() => localStorage.getItem('hubEnabled') === 'true')
  const toggleHub = () => {
    const next = !hubEnabled
    setHubEnabled(next)
    localStorage.setItem('hubEnabled', String(next))
  }
  const hubMode = hubEnabled && Boolean(hubBase && hubToken)

  const load = async () => {
    setBusy(true)
    try {
      if (hubMode) {
        const h = { 'X-Service-Token': hubToken }
        const [n, a] = await Promise.all([
          fetch(`${hubBase}/v1/nodes`, { headers: h }).then(r => r.json()),
          fetch(`${hubBase}/v1/assets?status=&limit=500`, { headers: h }).then(r => r.json()),
        ])
        setQuota((n.nodes || []).map((x: any): QuotaNode => ({
          node: x.id, label: x.label || x.id, writable: !!x.writable,
          used: Number(x.used_bytes || 0), capacity: Number(x.capacity_bytes || 0),
          ratio: Number(x.used_ratio || 0),
        })))
        setAssets((a.assets || []).map((x: any) => ({
          asset_id: x.id, name: x.name, class: x.kind, level: x.level, status: x.status,
          location: `${x.node_id}:${x.object_key}`, storage_node: x.node_id,
          backup_location: x.backup_location, size_bytes: x.size_bytes,
          checksum: x.checksum, owner_department: x.dept, summary: x.summary,
        })))
      } else {
        const [qu, a] = await Promise.all([
          fetch('/api/storage/quota').then(r => r.json()),
          fetch('/api/storage/assets').then(r => r.json()),
        ])
        setQuota((qu.nodes || []).map((x: any): QuotaNode => {
          const capacity = Number(x?.quota?.storage_gb || 0) * 1024 ** 3
          const used = Number(x?.usage?.bytes_stored || 0)
          return {
            node: x.node, label: x.label || x.node, writable: !!x.writable,
            used, capacity,
            ratio: Number(x?.ratios?.bytes_stored ?? (capacity ? used / capacity : 0)),
            blockReason: x.block_reason || '',
            forecast: Number(x?.forecast?.bytes_stored || 0),
            warnings: x.warnings || [],
          }
        }))
        setAssets(a.assets || [])
      }
    } catch (e) {
      toast('err', `加载失败: ${formatApiError(e)}`)
    } finally { setBusy(false) }
  }

  useEffect(() => { void load() }, [hubMode, hubBase, hubToken])

  // 部门下拉的来源:本部门 + 已登记的兄弟部门 + 台账里出现过的。
  // 三者合并去重 —— 只取其中一个都会漏(接口里没有历史部门,台账里没有新建的)
  useEffect(() => {
    void (async () => {
      const set = new Set<string>(['shared'])
      try {
        const d = await fetch('/api/departments').then(r => r.json())
        if (d?.self?.dept) set.add(d.self.dept)
        for (const it of d?.items || []) if (it?.id) set.add(it.id)
      } catch { /* 接口挂了不该让上传用不了,下面还有台账兜底 */ }
      assets.forEach(a => a.owner_department && set.add(a.owner_department))
      setDepts([...set].sort())
    })()
  }, [assets])

  // ── 分类计数 ────────────────────────────────────────────────
  const counts = useMemo(() => {
    const by = (k: keyof Asset) => assets.reduce<Record<string, number>>((m, a) => {
      const v = String(a[k] ?? ''); m[v] = (m[v] || 0) + 1; return m
    }, {})
    const cls = assets.reduce<Record<string, number>>((m, a) => {
      const c = effectiveClass(a); m[c] = (m[c] || 0) + 1; return m
    }, {})
    return { level: by('level'), status: by('status'), cls,
             dept: by('owner_department'), node: by('storage_node'),
             kind: by('class') }
  }, [assets])

  const shown = useMemo(() => assets.filter(a =>
    (!fLevel || a.level === fLevel) &&
    (!fStatus || a.status === fStatus) &&
    (!fClass || effectiveClass(a) === fClass) &&
    (!fDept || a.owner_department === fDept) &&
    (!fNode || a.storage_node === fNode) &&
    (!fKind || a.class === fKind) &&
    (!q || (a.name || '').toLowerCase().includes(q.toLowerCase()))
  ), [assets, fLevel, fStatus, fClass, fDept, fNode, fKind, q])

  // ── 点资产名 → 当前页大弹窗查看 ──────────────────────────────
  // 之前是开新标签页。改成弹窗的理由:看一眼资产内容是个高频动作,
  // 每次都甩一个新标签页出去,看完还得手动关,标签栏很快就满了。
  // 真要在新窗口打开的,弹窗里给按钮。
  const open = async (a: Asset) => {
    setPreviewBusy(true)
    const kind = previewKind(a.name, undefined)
    try {
      if (hubMode) {
        const r = await parseApiResponse<any>(await fetch(`${hubBase}/v1/assets/${a.asset_id}/fetch?prefer=near`,
          { headers: { 'X-Service-Token': hubToken } }), '资产链接读取失败')
        if (kind === 'text') {
          const txt = await fetch(r.url).then(x => x.text())
          setPreview({ asset: a, kind: 'text', text: txt, url: r.url })
        } else {
          setPreview({ asset: a, kind, url: r.url })
        }
        return
      }
      // 本地模式:文本走 /content(顺带拿到 checksum 比对结果),
      // 图片/PDF 走 /raw —— /content 会把二进制 utf-8 解码掉,图片到这儿已经烂了
      if (kind === 'image' || kind === 'pdf') {
        const probe = await fetch(`/api/storage/assets/${a.asset_id}/raw`)
        if (!probe.ok) {
          const msg = await probe.text()
          throw new Error(msg.slice(0, 300) || `HTTP ${probe.status}`)
        }
        setPreview({ asset: a, kind, url: `/api/storage/assets/${a.asset_id}/raw` })
        return
      }
      const r = await parseApiResponse<any>(await fetch(`/api/storage/assets/${a.asset_id}/content`), '资产内容读取失败')
      setPreview({
        asset: a, kind: kind === 'text' ? 'text' : 'binary', text: r.content,
        url: `/api/storage/assets/${a.asset_id}/raw`,
        warn: r.checksum_match === false
          ? '校验和与台账不符:内容可能被合法更新过而台账没跟上,也可能被改过。系统不替它下结论。'
          : undefined,
      })
    } catch (e) {
      toast('err', `打开失败: ${formatApiError(e)}`)
    } finally { setPreviewBusy(false) }
  }

  /**
   * 下载。两种模式取字节的路子不同,但都必须**用台账里的资产名**落盘 ——
   * 存储节点上的 key 是 `dept/kind/id/name` 这种路径,直接拿它当文件名
   * 会存出一堆看不懂的东西。
   */
  const download = async (a: Asset) => {
    try {
      let blob: Blob
      if (hubMode) {
        const r = await parseApiResponse<any>(await fetch(`${hubBase}/v1/assets/${a.asset_id}/fetch?prefer=near`,
          { headers: { 'X-Service-Token': hubToken } }), '资产下载链接读取失败')
        blob = await fetch(r.url).then(x => {
          if (!x.ok) throw new Error(`取回失败 HTTP ${x.status}`)
          return x.blob()
        })
      } else {
        // 走 /raw 而不是 /content:后者会把二进制 utf-8 解码,下下来是坏的
        const r = await fetch(`/api/storage/assets/${a.asset_id}/raw`)
        if (!r.ok) throw new Error((await r.text()).slice(0, 300) || `HTTP ${r.status}`)
        blob = await r.blob()
      }
      const url = URL.createObjectURL(blob)
      const el = document.createElement('a')
      el.href = url; el.download = a.name || a.asset_id
      document.body.appendChild(el); el.click(); el.remove()
      // 立刻回收会让部分浏览器下载不到,给一拍
      setTimeout(() => URL.revokeObjectURL(url), 2000)
      toast('ok', `已下载 ${a.name}`)
    } catch (e) {
      toast('err', `下载失败: ${formatApiError(e)}`)
    }
  }

  const copyLink = async (a: Asset) => {
    try {
      if (hubMode) {
        const r = await parseApiResponse<any>(await fetch(`${hubBase}/v1/assets/${a.asset_id}/fetch?prefer=near`,
          { headers: { 'X-Service-Token': hubToken } }), '资产链接读取失败')
        await navigator.clipboard.writeText(r.url)
        toast('ok', `链接已复制,${Math.round((r.expires_in || 0) / 60)} 分钟内有效。这是一次性直取链接。`)
      } else {
        await navigator.clipboard.writeText(a.location || '')
        toast('ok', '本地模式没有直取链接,已复制**落点**(node:key)。要真链接得接调度中心 —— 见页面顶部。')
      }
    } catch (e) { toast('err', `取链接失败: ${formatApiError(e)}`) }
  }

  // ── 上传 ──────────────────────────────────────────────────
  const pickFile = async (f: File | null) => {
    if (!f) return
    // 类型自动识别:按扩展名认。认不出来**不猜**,保持当前选择让人自己定 ——
    // 默默塞个 misc 的话,台账里会攒出一堆没有分类的东西
    const ext = (f.name.split('.').pop() || '').toLowerCase()
    const guessed = KIND_BY_EXT[ext]
    setForm(s => ({
      ...s,
      name: s.name || f.name,
      kind: guessed || s.kind,
      asset_class: CLASS_BY_KIND[guessed || s.kind] || s.asset_class,
    }))
    if (hubMode) { setForm(s => ({ ...s, content: '' })); (window as any).__hubFile = f; return }
    // 本地后端只收 content: string。二进制读进来会被 UTF-8 解码毁掉,
    // 与其存一份坏数据,不如直接说不行。
    const looksText = /^(text\/|application\/(json|xml|yaml|javascript))/.test(f.type)
      || /\.(md|txt|json|ya?ml|csv|tsv|log|py|ts|tsx|js|html|css|sql)$/i.test(f.name)
    if (!looksText) {
      toast('err', `本地模式只能存文本,「${f.name}」看起来是二进制。要传二进制得接调度中心(页面顶部填地址)。`)
      return
    }
    const text = await f.text()
    setForm(s => ({ ...s, content: text }))
  }

  const submit = async () => {
    setBusy(true)
    try {
      if (hubMode) {
        const f: File | undefined = (window as any).__hubFile
        const buf = f ? await f.arrayBuffer() : new TextEncoder().encode(form.content).buffer
        const alloc = await parseApiResponse<any>(await fetch(`${hubBase}/v1/assets/allocate`, {
          method: 'POST',
          headers: { 'X-Service-Token': hubToken, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            dept: form.dept, kind: form.kind, name: form.name, level: form.level,
            size_bytes: buf.byteLength, content_type: f?.type || 'text/plain',
            summary: form.summary, usage: form.usage, task_id: form.task_id,
            owner_agent: form.owner_agent, source_evidence: form.source_evidence,
            rollback: form.rollback, review_cycle: form.review_cycle,
          }),
        }), '存储空间分配失败')

        let via = '直传'
        try {
          const put = await fetch(alloc.upload.url, {
            method: alloc.upload.method || 'PUT',
            headers: alloc.upload.headers || {}, body: buf,
          })
          if (!put.ok) throw new Error(`HTTP ${put.status}`)
          if (alloc.mirror?.url) {
            const m = await fetch(alloc.mirror.url, {
              method: 'PUT', headers: alloc.mirror.headers || {}, body: buf,
            })
            if (!m.ok) throw new Error(`镜像 HTTP ${m.status}`)
          }
        } catch {
          // 存储桶没配 CORS,浏览器直传被拦 —— 退回代理上传,但要说出来
          via = '经调度中心中转'
          const r = await fetch(`${hubBase}/v1/assets/${alloc.asset_id}/proxy-upload`, {
            method: 'PUT', headers: { 'X-Service-Token': hubToken }, body: buf,
          })
          if (!r.ok) throw new Error(`代理上传失败: ${await r.text()}`)
        }

        const digest = await crypto.subtle.digest('SHA-256', buf)
        const checksum = 'sha256:' + [...new Uint8Array(digest)]
          .map(b => b.toString(16).padStart(2, '0')).join('')
        const res = await parseApiResponse<any>(await fetch(`${hubBase}/v1/assets/${alloc.asset_id}/commit`, {
          method: 'POST',
          headers: { 'X-Service-Token': hubToken, 'Content-Type': 'application/json' },
          body: JSON.stringify({ checksum, size_bytes: buf.byteLength }),
        }), '资产提交失败')
        toast('ok', `已上传 ${alloc.asset_id},状态 ${res.status}(${via})。`
          + (res.status === 'MIRRORING' ? ' 冷备份异步进行中,拷完才转已完成。' : ''))
        ;(window as any).__hubFile = undefined
      } else {
        const res = await fetch('/api/storage/assets', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        })
        const body = await res.json()
        if (!res.ok) {
          // 后端把 L3 门禁的拒绝理由放在 detail,原样呈现 —— 不要替它改写措辞
          throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
        }
        toast('ok', `已登记 ${body.asset_id || ''}`)
      }
      setCreating(false); setForm({ ...EMPTY }); void load()
    } catch (e) {
      toast('err', formatApiError(e))
    } finally { setBusy(false) }
  }

  // ── 渲染 ──────────────────────────────────────────────────
  const chip = (active: boolean, label: string, n: number, onClick: () => void, color?: string) => (
    <button key={label} onClick={onClick} style={{
      ...btn(active ? 'var(--accent2)' : 'var(--panel)', active ? 'var(--text)' : (color || 'var(--text)')),
      padding: '4px 10px', fontSize: 12,
    }}>
      {label}<span style={{
        marginLeft: 6, padding: '0 5px', borderRadius: 9, fontSize: 11,
        background: 'oklch(100% 0 0 / .14)',
      }}>{n}</span>
    </button>
  )

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {/* 模式开关 —— 迁移期必须一眼看出走的是哪条路 */}
      <div style={{
        border: '1px solid var(--panel)', borderRadius: 10, padding: 12,
        background: hubMode ? 'var(--ok-soft)' : 'var(--warn-soft)',
      }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <strong>{hubMode ? '🌐 中心模式' : '💻 本地模式'}</strong>
          <span style={{ fontSize: 12, opacity: .75 }}>
            {hubMode
              ? '走中央存储调度中心 —— 可传二进制,链接是一次性直取 URL'
              : '走本地 /api/storage —— 只能存文本,「链接」只是落点'}
          </span>
          <span style={{ flex: 1 }} />
          {/* 显式切换按钮 */}
          {hubBase && hubToken && (
            <button onClick={toggleHub} style={{
              ...btn(hubMode ? 'var(--ok)' : 'var(--panel)', hubMode ? 'var(--bg)' : 'var(--text)'),
              padding: '5px 14px', fontSize: 12, fontWeight: 600,
              borderRadius: 8, cursor: 'pointer',
              border: hubMode ? '1px solid var(--ok)' : '1px solid var(--border)',
            }}>
              {hubMode ? '● 中心模式已开启' : '○ 点击开启中心模式'}
            </button>
          )}
          {!hubMode && (
            <span style={{ fontSize: 11, opacity: .6, width: '100%' }}>
              调度中心尚未部署到广州,所以这两项现在**没有值可填** —— 留空即可。
              部署完成后:地址 <code>https://&lt;广州域名&gt;:8080</code>,
              令牌是 <code>/data/hub/hub.env</code> 里的 <code>HUB_SERVICE_TOKEN</code>。
            </span>
          )}
          <input style={{ ...inputStyle, width: isMobile ? '100%' : 240 }}
            title="调度中心部署到广州后才有地址,形如 https://<域名>:8080。没部署就留空,留空即本地模式"
            placeholder="调度中心地址(未部署则留空)" value={hubBase}
            onChange={e => { setHubBase(e.target.value.trim()); localStorage.setItem('hubBase', e.target.value.trim()) }} />
          <input style={{ ...inputStyle, width: isMobile ? '100%' : 200 }} type="password"
            title="部署调度中心时 openssl rand -hex 32 生成、写在 /data/hub/hub.env 里的 HUB_SERVICE_TOKEN"
            placeholder="服务令牌(同上)" value={hubToken}
            onChange={e => { setHubToken(e.target.value.trim()); localStorage.setItem('hubToken', e.target.value.trim()) }} />
        </div>
      </div>

      {/* 节点与配额 */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong>存储节点</strong>
          {(() => {
            // 总容量 = 各节点之和。无上限的节点不参与合计,但要说出来 ——
            // 悄悄把它算成 0 或者忽略,总数就骗人了
            const cap = quota.reduce((m, n) => m + (n.capacity || 0), 0)
            const used = quota.reduce((m, n) => m + (n.used || 0), 0)
            const unlimited = quota.filter(n => !n.capacity).length
            const pct = cap ? Math.round(used / cap * 100) : 0
            return (
              <span style={{ fontSize: 12, opacity: .75, display: 'flex', gap: 10, alignItems: 'center' }}>
                <span>
                  合计 <strong style={{ color: pct >= 90 ? 'var(--bad)' : pct >= 70 ? 'var(--warn)' : 'var(--ok)' }}>
                    {fmtSize(used)}
                  </strong> / {cap ? fmtSize(cap) : '—'}
                  {cap ? `（${pct}%，剩 ${fmtSize(Math.max(0, cap - used))}）` : ''}
                </span>
                {unlimited > 0 && <span style={{ opacity: .6 }}>· {unlimited} 个节点无上限,未计入</span>}
                <span style={{ opacity: .6 }}>· 点节点可筛选</span>
              </span>
            )
          })()}
        </div>
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: `repeat(auto-fill,minmax(${isMobile ? 150 : 220}px,1fr))` }}>
          {quota.map(n => {
            const pct = Math.round((n.ratio || (n.capacity ? n.used / n.capacity : 0)) * 100)
            const col = pct >= 90 ? 'var(--bad)' : pct >= 70 ? 'var(--warn)' : 'var(--ok)'
            const on = fNode === n.node
            const cnt = counts.node[n.node] || 0
            // 月底预估:按本月速率外推。超过容量时提前标红 ——
            // 等真的写满再报警,那时已经停写了
            const fPct = n.capacity && n.forecast ? Math.round(n.forecast / n.capacity * 100) : 0
            return (
              <div key={n.node}
                onClick={() => setFNode(on ? '' : n.node)}
                title={on ? '再点一次取消筛选' : `只看存在 ${n.label} 上的资产`}
                style={{
                  border: `1px solid ${on ? 'var(--accent2)' : 'var(--panel)'}`,
                  background: on ? 'var(--accent-soft)' : undefined,
                  borderRadius: 8, padding: 10, cursor: 'pointer',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                  <strong style={{ fontSize: 13 }}>{n.label}</strong>
                  <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {cnt > 0 && (
                      <span style={{
                        fontSize: 11, padding: '0 6px', borderRadius: 9,
                        background: on ? 'var(--accent-line)' : 'var(--border)',
                      }}>{cnt}</span>
                    )}
                    <span style={{ fontSize: 11, color: n.writable ? 'var(--dim)' : 'var(--warn)' }}
                      title={n.blockReason || undefined}>
                      {n.writable ? '可写' : '只读'}
                    </span>
                  </span>
                </div>

                <div style={{
                  position: 'relative', height: 6, background: 'var(--bg)',
                  borderRadius: 3, overflow: 'hidden', margin: '7px 0 4px',
                }}>
                  <i style={{ display: 'block', height: '100%', width: `${Math.min(pct, 100)}%`, background: col }} />
                  {/* 90% 停写线 —— 让人一眼看出离限制还有多远,而不是等它变红 */}
                  <i style={{
                    position: 'absolute', left: '90%', top: 0, bottom: 0, width: 1,
                    background: 'var(--bad)',
                  }} />
                </div>

                <div style={{ fontSize: 11, opacity: .7, display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <span>{fmtSize(n.used)} / {n.capacity ? fmtSize(n.capacity) : '无上限'}</span>
                  <span style={{ color: col }}>{n.capacity ? `${pct}%` : ''}</span>
                </div>
                <div style={{ fontSize: 11, opacity: .5, marginTop: 2 }}>
                  剩余 {n.capacity ? fmtSize(Math.max(0, n.capacity - n.used)) : '—'}
                  {fPct > 0 && (
                    <span style={{ color: fPct >= 90 ? 'var(--bad)' : undefined }}>
                      {' · '}月底预估 {fPct}%
                    </span>
                  )}
                </div>
                {(n.warnings || []).map((w, i) => (
                  <div key={i} style={{ fontSize: 11, color: 'var(--warn)', marginTop: 4 }}>⚠ {w}</div>
                ))}
              </div>
            )
          })}
          {!quota.length && <span style={{ opacity: .6, fontSize: 12 }}>暂无节点</span>}
        </div>
      </div>

      {/* 资产台账:类别走纵轴,筛选走横轴 */}
      <div style={{
        display: 'grid', gap: 14,
        gridTemplateColumns: isMobile ? '1fr' : '168px 1fr',
        alignItems: 'start',
      }}>

        {/* ── 纵轴:类别导航 ──────────────────────────────────
            类别是资产的**固有属性**,不随筛选变;所以放侧栏当导航。
            等级/状态/部门是**看问题的角度**,会频繁换,所以放顶部横条。
            两者混在一起排成几行 chip,点哪个都像在筛选,分不清主次。 */}
        <div style={{
          display: 'flex', gap: 4,
          flexDirection: isMobile ? 'row' : 'column',
          overflowX: isMobile ? 'auto' : undefined,
          paddingBottom: isMobile ? 4 : 0,
        }}>
          {CLASS_NAV.map(c => {
            const n = c.id ? (counts.cls[c.id] || 0) : assets.length
            const on = fClass === c.id
            if (c.id && !n) return null   // 空类别不占位置
            return (
              <button key={c.id || 'all'} onClick={() => setFClass(c.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap',
                  background: on ? 'var(--accent2)' : 'transparent',
                  color: on ? 'var(--text)' : 'var(--text)',
                  border: 0, borderRadius: 7, padding: '7px 10px',
                  fontSize: 13, cursor: 'pointer', textAlign: 'left',
                  width: isMobile ? undefined : '100%',
                }}>
                <span style={{ opacity: .85 }}>{c.icon}</span>
                <span style={{ flex: 1 }}>{c.label}</span>
                <span style={{
                  fontSize: 11, padding: '0 6px', borderRadius: 9,
                  background: on ? 'oklch(100% 0 0 / .22)' : 'var(--border)',
                }}>{n}</span>
              </button>
            )
          })}
        </div>

        {/* ── 右侧:横轴筛选 + 表格 ────────────────────────── */}
        <div>
          <div style={{
            display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
            marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--panel)',
          }}>
            <select style={{ ...inputStyle, width: 120 }} value={fLevel}
              onChange={e => setFLevel(e.target.value)}
              title={fLevel ? LEVEL_HINT[fLevel] : '按资产等级筛选'}>
              <option value="">全部等级</option>
              {['L1', 'L2', 'L3'].map(l =>
                <option key={l} value={l}>{l}（{counts.level[l] || 0}）</option>)}
            </select>
            <select style={{ ...inputStyle, width: 130 }} value={fStatus}
              onChange={e => setFStatus(e.target.value)}
              title={fStatus ? STATUS_HINT[fStatus] : '「已声明」不等于「已落地」'}>
              <option value="">全部状态</option>
              {Object.keys(counts.status).filter(Boolean).map(st =>
                <option key={st} value={st}>{STATUS_LABEL[st] || st}（{counts.status[st]}）</option>)}
            </select>
            <select style={{ ...inputStyle, width: 120 }} value={fDept}
              onChange={e => setFDept(e.target.value)}>
              <option value="">全部部门</option>
              {Object.keys(counts.dept).filter(Boolean).map(d =>
                <option key={d} value={d}>{d}（{counts.dept[d]}）</option>)}
            </select>
            <select style={{ ...inputStyle, width: 130 }} value={fKind}
              onChange={e => setFKind(e.target.value)}
              title="按台账登记的类型筛选">
              <option value="">全部分类</option>
              {Object.keys(counts.kind).filter(Boolean).sort().map(k =>
                <option key={k} value={k}>{k}（{counts.kind[k]}）</option>)}
            </select>
            <input style={{ ...inputStyle, width: isMobile ? '100%' : 180 }} placeholder="搜索名称"
              value={q} onChange={e => setQ(e.target.value)} />
            {(fLevel || fStatus || fDept || fNode || fKind || q) && (
              <button style={{ ...btn('var(--panel)'), padding: '5px 10px' }}
                onClick={() => { setFLevel(''); setFStatus(''); setFDept(''); setFNode(''); setFKind(''); setQ('') }}>清空筛选</button>
            )}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 12, opacity: .55 }}>{shown.length} / {assets.length}</span>
            <span style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
              {([['list', '☰', '列表'], ['card', '▦', '卡片']] as const).map(([v, icon, label]) => (
                <button key={v} onClick={() => switchView(v)} title={label}
                  style={{
                    background: view === v ? 'var(--accent2)' : 'transparent',
                    color: view === v ? 'var(--text)' : 'var(--dim)',
                    border: 0, padding: '5px 9px', fontSize: 12, cursor: 'pointer',
                  }}>{icon}</button>
              ))}
            </span>
            <button style={{ ...btn('var(--panel)'), padding: '5px 10px' }}
              onClick={() => void load()} disabled={busy}>{busy ? '…' : '刷新'}</button>
            <button style={{ ...btn('var(--accent2)'), padding: '5px 10px' }}
              onClick={() => setCreating(true)}>上传资产</button>
          </div>

          {view === 'list' && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ opacity: .6, fontSize: 11 }}>
                    <th style={{ textAlign: 'left', padding: 8 }}>资产</th>
                    <th style={{ textAlign: 'left', padding: 8 }}>分类</th>
                    <th style={{ textAlign: 'left', padding: 8 }}>等级</th>
                    <th style={{ textAlign: 'left', padding: 8 }}>状态</th>
                    {!isMobile && <th style={{ textAlign: 'left', padding: 8 }}>大小</th>}
                    {!isMobile && <th style={{ textAlign: 'left', padding: 8 }}>备份</th>}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {shown.map(a => {
                    const cls = effectiveClass(a)
                    const nav = CLASS_NAV.find(c => c.id === cls)
                    return (
                      <tr key={a.asset_id} style={{ borderTop: '1px solid var(--panel)' }}>
                        <td style={{ padding: 8 }}>
                          <span onClick={() => void open(a)} title="点击在本页查看"
                            style={{ cursor: 'pointer', fontWeight: 500, textDecoration: 'underline dotted' }}>
                            {a.name}{previewBusy ? ' …' : ''}
                          </span>
                          <div style={{ fontSize: 11, opacity: .5 }}>{a.asset_id}</div>
                        </td>
                        <td style={{ padding: 8, fontSize: 12, opacity: .85, whiteSpace: 'nowrap' }}
                          title={a.class ? '台账登记的分类' : '台账没登记,按文件名推断出来的'}>
                          {nav?.icon} {nav?.label || '未分类'}
                          {!a.class && <span style={{ opacity: .5 }}>*</span>}
                        </td>
                        <td style={{ padding: 8 }}>
                          <span title={LEVEL_HINT[a.level]} style={{
                            padding: '1px 7px', borderRadius: 20, fontSize: 11, fontWeight: 600,
                            border: `1px solid ${LEVEL_COLOR[a.level] || 'var(--faint)'}`,
                            color: LEVEL_COLOR[a.level] || 'var(--faint)',
                          }}>{a.level}</span>
                        </td>
                        <td style={{ padding: 8 }}>
                          <span title={STATUS_HINT[a.status]} style={{
                            fontSize: 12, color: a.status === 'ACTIVE' ? 'var(--ok)' : 'var(--warn)',
                          }}>{STATUS_LABEL[a.status] || a.status}</span>
                        </td>
                        {!isMobile && <td style={{ padding: 8, opacity: .7 }}>{fmtSize(a.size_bytes)}</td>}
                        {!isMobile && (
                          <td style={{ padding: 8, fontSize: 12 }}>
                            {a.level !== 'L3' ? <span style={{ opacity: .4 }}>—</span>
                              : a.backup_location ? <span style={{ color: 'var(--ok)' }}>✓ {a.backup_location.split(':')[0]}</span>
                                : <span style={{ color: 'var(--bad)' }}>✗ 缺备份</span>}
                          </td>
                        )}
                        <td style={{ padding: 8, whiteSpace: 'nowrap' }}>
                          <button style={{ ...btn('var(--panel)'), padding: '3px 8px' }}
                            onClick={() => void download(a)}>下载</button>
                          <button style={{ ...btn('var(--panel)'), padding: '3px 8px', marginLeft: 6 }}
                            onClick={() => void copyLink(a)}>{hubMode ? '链接' : '落点'}</button>
                          <button style={{ ...btn('var(--panel)'), padding: '3px 8px', marginLeft: 6 }}
                            onClick={() => setDetail(a)}>详情</button>
                        </td>
                      </tr>
                    )
                  })}
                  {!shown.length && (
                    <tr><td colSpan={7} style={{ padding: 14, opacity: .6 }}>
                      这个分类下没有资产
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {view === 'card' && (
            <div style={{
              display: 'grid', gap: 10,
              gridTemplateColumns: `repeat(auto-fill,minmax(${isMobile ? 150 : 230}px,1fr))`,
            }}>
              {shown.map(a => {
                const cls = effectiveClass(a)
                const nav = CLASS_NAV.find(c => c.id === cls)
                const missingBackup = a.level === 'L3' && !a.backup_location
                return (
                  <div key={a.asset_id} style={{
                    border: `1px solid ${missingBackup ? 'var(--bad-soft)' : 'var(--panel)'}`,
                    borderRadius: 9, padding: 11, display: 'flex', flexDirection: 'column', gap: 7,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 15 }}>{nav?.icon}</span>
                      <span title={LEVEL_HINT[a.level]} style={{
                        padding: '0 6px', borderRadius: 20, fontSize: 10, fontWeight: 700,
                        border: `1px solid ${LEVEL_COLOR[a.level] || 'var(--faint)'}`,
                        color: LEVEL_COLOR[a.level] || 'var(--faint)',
                      }}>{a.level}</span>
                      <span style={{ flex: 1 }} />
                      <span title={STATUS_HINT[a.status]} style={{
                        fontSize: 11, color: a.status === 'ACTIVE' ? 'var(--ok)' : 'var(--warn)',
                      }}>{STATUS_LABEL[a.status] || a.status}</span>
                    </div>

                    <div onClick={() => void open(a)} title="点击在本页查看"
                      style={{
                        cursor: 'pointer', fontWeight: 500, fontSize: 13, lineHeight: 1.4,
                        wordBreak: 'break-word', textDecoration: 'underline dotted',
                      }}>{a.name}</div>

                    {a.summary && (
                      <div style={{
                        fontSize: 11, opacity: .6, lineHeight: 1.5,
                        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>{a.summary}</div>
                    )}

                    <div style={{ fontSize: 11, opacity: .5, marginTop: 'auto' }}>
                      {fmtSize(a.size_bytes)} · {a.owner_department || '—'}
                      {a.level === 'L3' && (
                        <span style={{ color: a.backup_location ? 'var(--ok)' : 'var(--bad)' }}>
                          {' · '}{a.backup_location ? '有备份' : '缺备份'}
                        </span>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: 5 }}>
                      <button style={{ ...btn('var(--panel)'), padding: '3px 8px', flex: 1 }}
                        onClick={() => void download(a)}>下载</button>
                      <button style={{ ...btn('var(--panel)'), padding: '3px 8px' }}
                        onClick={() => void copyLink(a)}>{hubMode ? '链接' : '落点'}</button>
                      <button style={{ ...btn('var(--panel)'), padding: '3px 8px' }}
                        onClick={() => setDetail(a)}>…</button>
                    </div>
                  </div>
                )
              })}
              {!shown.length && (
                <div style={{ padding: 14, opacity: .6, gridColumn: '1 / -1' }}>这个分类下没有资产</div>
              )}
            </div>
          )}

          <div style={{ fontSize: 11, opacity: .45, marginTop: 8 }}>
            带 * 的分类是按文件名推断的 —— 台账里没登记 class。上传时会自动识别并写入。
          </div>
        </div>
      </div>

      {/* 上传 */}
      {creating && (
        <Modal open title="上传资产" onClose={() => setCreating(false)} width={620}>
          <div style={{ display: 'grid', gap: 10 }}>
            {!hubMode && (
              <div style={{ fontSize: 12, padding: 8, borderRadius: 6, border: '1px solid var(--warn)', color: 'var(--warn)' }}>
                本地模式只能存**文本**。要传图片、压缩包等二进制,先在页面顶部接上调度中心。
              </div>
            )}
            <Field label="选文件">
              <input type="file" onChange={e => void pickFile(e.target.files?.[0] || null)} />
            </Field>
            <Field label="资产名"><input style={inputStyle} value={form.name}
              onChange={e => setForm(s => ({ ...s, name: e.target.value }))} /></Field>
            {!hubMode && (
              <Field label="内容(文本)"><textarea style={{ ...inputStyle, minHeight: 100 }} value={form.content}
                onChange={e => setForm(s => ({ ...s, content: e.target.value }))} /></Field>
            )}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <Field label="部门">
                <select style={{ ...inputStyle, width: 130 }} value={form.dept}
                  onChange={e => setForm(s => ({ ...s, dept: e.target.value }))}>
                  {depts.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </Field>
              <Field label="类型" hint="选文件后按扩展名自动识别,认不出才要手选">
                <select style={{ ...inputStyle, width: 130 }} value={form.kind}
                  onChange={e => setForm(s => ({
                    ...s, kind: e.target.value,
                    asset_class: CLASS_BY_KIND[e.target.value] || 'DOC',
                  }))}>
                  {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </Field>
              <Field label="等级">
                <select style={{ ...inputStyle, width: 190 }} value={form.level}
                  onChange={e => setForm(s => ({ ...s, level: e.target.value }))}>
                  <option value="L1">L1 · 临时产出</option>
                  <option value="L2">L2 · 常规资产</option>
                  <option value="L3">L3 · 核心(强制异地备份)</option>
                </select>
              </Field>
            </div>
            {form.level === 'L3' && (
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <Field label="回滚方案"><input style={{ ...inputStyle, width: 220 }} value={form.rollback}
                  onChange={e => setForm(s => ({ ...s, rollback: e.target.value }))} /></Field>
                <Field label="复核周期"><input style={{ ...inputStyle, width: 110 }} value={form.review_cycle}
                  onChange={e => setForm(s => ({ ...s, review_cycle: e.target.value }))} /></Field>
                <div style={{ fontSize: 11, opacity: .6, alignSelf: 'end' }}>
                  备份位置不用填 —— 系统按实际镜像落点写入
                </div>
              </div>
            )}
            <Field label="说明"><input style={inputStyle} value={form.summary}
              onChange={e => setForm(s => ({ ...s, summary: e.target.value }))} /></Field>
            <button style={btn('var(--accent2)')} disabled={busy} onClick={() => void submit()}>{busy ? '上传中…' : '上传'}</button>
          </div>
        </Modal>
      )}

      {/* 资产预览 —— 在当前页看,不甩新标签页 */}
      {preview && (
        <Modal open title={preview.asset.name}
          subtitle={`${preview.asset.level} · ${preview.asset.asset_id}`}
          onClose={() => setPreview(null)} width={900}>
          <div style={{ display: 'grid', gap: 10 }}>
            {preview.warn && (
              <div style={{ padding: 8, borderRadius: 6, border: '1px solid var(--warn)', color: 'var(--warn)', fontSize: 12 }}>
                ⚠ {preview.warn}
              </div>
            )}
            {preview.kind === 'text' && (
              <pre style={{
                margin: 0, maxHeight: '60vh', overflow: 'auto', background: 'var(--surface)',
                border: '1px solid var(--border)', borderRadius: 6, padding: 12,
                fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>{preview.text}</pre>
            )}
            {preview.kind === 'image' && preview.url && (
              <img src={preview.url} alt={preview.asset.name}
                style={{ maxWidth: '100%', maxHeight: '60vh', objectFit: 'contain', borderRadius: 6 }} />
            )}
            {preview.kind === 'pdf' && preview.url && (
              <iframe src={preview.url} title={preview.asset.name}
                style={{ width: '100%', height: '60vh', border: '1px solid var(--border)', borderRadius: 6 }} />
            )}
            {preview.kind === 'binary' && (
              <div style={{ padding: 12, opacity: .75, fontSize: 13 }}>
                这是二进制内容,页面里渲染不了 —— 用下面的按钮下载或在新窗口打开。
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {preview.url && (
                <button style={btn('var(--panel)')}
                  onClick={() => window.open(preview.url, '_blank')}>新窗口打开</button>
              )}
              <button style={btn('var(--panel)')} onClick={() => void download(preview.asset)}>下载</button>
              <button style={btn('var(--panel)')} onClick={() => void copyLink(preview.asset)}>
                {hubMode ? '复制链接' : '复制落点'}
              </button>
              <button style={btn('var(--panel)')} onClick={() => { setDetail(preview.asset); setPreview(null) }}>
                看详情
              </button>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 11, opacity: .5, alignSelf: 'center' }}>
                {fmtSize(preview.asset.size_bytes)} · {preview.asset.location}
              </span>
            </div>
          </div>
        </Modal>
      )}

      {detail && (
        <Modal open title={detail.name} onClose={() => setDetail(null)} width={640}>
          <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
            <div>资产号 <code>{detail.asset_id}</code></div>
            <div>落点 <code>{detail.location || '—'}</code></div>
            <div>备份 <code>{detail.backup_location || '—'}</code></div>
            <div>校验和 <code style={{ wordBreak: 'break-all' }}>{detail.checksum || '—'}</code></div>
            <div style={{ opacity: .7 }}>{detail.summary}</div>
            {detail.status === 'DECLARED' && (
              <div style={{ marginTop: 6, padding: 8, borderRadius: 6, border: '1px solid var(--warn)', color: 'var(--warn)' }}>
                这条只是**已声明**,没有验证过字节真的落地。台账里「说了要做」和「做完了」
                必须分得开,否则台账就失去意义了。
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}

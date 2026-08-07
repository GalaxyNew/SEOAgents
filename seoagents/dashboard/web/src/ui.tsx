import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

/**
 * 全站共用的界面基件与反馈层。
 *
 * 所有弹窗都遵循同一关闭策略：画布外点击不关闭；X、明确按钮或允许的 Escape
 * 才关闭。异步 Confirm/Form 会在所有关闭路径上结算 Promise。
 */

// ── 通用弹窗 ────────────────────────────────────────────────────────
export const Modal: React.FC<{
  open: boolean
  title: string
  subtitle?: string
  width?: number
  onClose: () => void
  footer?: React.ReactNode
  children: React.ReactNode
  closeOnBackdrop?: boolean
  closeOnEscape?: boolean
  fullscreen?: boolean
  zIndex?: number
}> = ({
  open,
  title,
  subtitle,
  width = 560,
  onClose,
  footer,
  children,
  closeOnBackdrop = false,
  closeOnEscape = true,
  fullscreen = false,
  zIndex = 100000,
}) => {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const timer = window.setTimeout(() => {
      const panel = panelRef.current
      const target = panel?.querySelector<HTMLElement>(
        '[data-autofocus="true"], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])',
      )
      ;(target || panel)?.focus()
    }, 0)
    return () => {
      window.clearTimeout(timer)
      const previous = previousFocusRef.current
      if (previous?.isConnected) previous.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && closeOnEscape) {
        event.preventDefault()
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.offsetParent !== null)
      if (!focusable.length) {
        event.preventDefault()
        panelRef.current.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, closeOnEscape])

  if (!open) return null
  return (
    <div
      onMouseDown={(event) => {
        if (closeOnBackdrop && event.target === event.currentTarget) onClose()
      }}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.78)', zIndex,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14,
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        style={{
          background: '#111827', border: '1px solid #334155', borderRadius: 12,
          width: fullscreen ? 'calc(100vw - 16px)' : '100%',
          maxWidth: fullscreen ? 'none' : width,
          height: fullscreen ? 'calc(100vh - 16px)' : undefined,
          maxHeight: fullscreen ? 'none' : '86vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 60px rgba(0,0,0,0.7)', outline: 'none',
        }}
      >
        <div style={{
          padding: '13px 16px', borderBottom: '1px solid #1f2937',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f3f4f6' }}>{title}</div>
            {subtitle && (
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{subtitle}</div>
            )}
          </div>
          <button
            data-testid="modal-close"
            type="button"
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
            style={{
              minWidth: 44, minHeight: 44,
              background: 'transparent', border: 0, color: '#94a3b8',
              fontSize: 17, cursor: 'pointer', padding: 8, lineHeight: 1,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}
          >✕</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>{children}</div>

        {footer && (
          <div style={{
            padding: '11px 16px', borderTop: '1px solid #1f2937',
            display: 'flex', justifyContent: 'flex-end', gap: 7, flexWrap: 'wrap',
          }}>{footer}</div>
        )}
      </div>
    </div>
  )
}

// ── Alert / 表单件 ──────────────────────────────────────────────────
export type AlertTone = 'info' | 'success' | 'warning' | 'error'

const ALERT_STYLE: Record<AlertTone, { bg: string; border: string; color: string; icon: string }> = {
  info: { bg: 'rgba(30,58,138,.28)', border: '#3b82f6', color: '#bfdbfe', icon: 'i' },
  success: { bg: 'rgba(6,78,59,.28)', border: '#10b981', color: '#a7f3d0', icon: '✓' },
  warning: { bg: 'rgba(120,53,15,.28)', border: '#f59e0b', color: '#fde68a', icon: '!' },
  error: { bg: 'rgba(127,29,29,.28)', border: '#ef4444', color: '#fecaca', icon: '×' },
}

export const Alert: React.FC<{
  tone?: AlertTone
  title?: string
  children: React.ReactNode
  onClose?: () => void
}> = ({ tone = 'info', title, children, onClose }) => {
  const style = ALERT_STYLE[tone]
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} style={{
      display: 'flex', alignItems: 'flex-start', gap: 9, padding: '9px 11px',
      borderRadius: 8, background: style.bg, border: `1px solid ${style.border}`,
      color: style.color, fontSize: 12, lineHeight: 1.5,
    }}>
      <span aria-hidden="true" style={{
        flexShrink: 0, width: 18, height: 18, borderRadius: 9, background: style.border,
        color: '#08101f', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 800,
      }}>{style.icon}</span>
      <div style={{ flex: 1, minWidth: 0, wordBreak: 'break-word' }}>
        {title && <div style={{ fontWeight: 700, marginBottom: 2 }}>{title}</div>}
        {children}
      </div>
      {onClose && (
        <button onClick={onClose} aria-label="关闭" style={{
          border: 0, background: 'transparent', color: style.color, opacity: .7,
          cursor: 'pointer', padding: 0, fontSize: 15,
        }}>×</button>
      )}
    </div>
  )
}

export const Field: React.FC<{
  label: string
  hint?: string
  required?: boolean
  error?: string
  children: React.ReactNode
}> = ({ label, hint, required, error, children }) => (
  <div style={{ marginBottom: 11 }}>
    <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4, fontWeight: 600 }}>
      {label}{required && <span style={{ color: '#f87171' }}> *</span>}
    </label>
    {children}
    {error
      ? <div style={{ fontSize: 10, color: '#f87171', marginTop: 3 }}>{error}</div>
      : hint && <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>{hint}</div>}
  </div>
)

export const inputStyle: React.CSSProperties = {
  background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
  color: '#e2e8f0', fontSize: 12, padding: '7px 9px',
  boxSizing: 'border-box', width: '100%', outline: 'none',
}

export const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  background: bg, color: fg, border: 0, borderRadius: 6,
  padding: '6px 13px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
})

// ── 全站 Toast ──────────────────────────────────────────────────────
export type ToastKind = 'success' | 'error' | 'warning' | 'info'
type ToastKindInput = ToastKind | 'ok' | 'err' | 'warn'
export type ToastOptions = { title?: string; duration?: number | null }
type ToastItem = ToastOptions & { id: number; kind: ToastKind; message: string }

export type ToastApi = ((kind: ToastKindInput, message: string, options?: ToastOptions) => number) & {
  success: (message: string, options?: ToastOptions) => number
  error: (message: string, options?: ToastOptions) => number
  warning: (message: string, options?: ToastOptions) => number
  info: (message: string, options?: ToastOptions) => number
  dismiss: (id: number) => void
  clear: () => void
}

const ToastContext = createContext<ToastApi | null>(null)
let toastSequence = 0

const normalizeToastKind = (kind: ToastKindInput): ToastKind => (
  kind === 'ok' ? 'success' : kind === 'err' ? 'error' : kind === 'warn' ? 'warning' : kind
)

const TOAST_STYLE: Record<ToastKind, { bg: string; border: string; color: string; icon: string }> = {
  error: { bg: 'rgba(127,29,29,.94)', border: '#ef4444', color: '#fecaca', icon: '✕' },
  success: { bg: 'rgba(6,78,59,.94)', border: '#10b981', color: '#a7f3d0', icon: '✓' },
  warning: { bg: 'rgba(120,53,15,.94)', border: '#f59e0b', color: '#fde68a', icon: '!' },
  info: { bg: 'rgba(30,58,138,.94)', border: '#3b82f6', color: '#dbeafe', icon: 'i' },
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timersRef = useRef<Map<number, number>>(new Map())

  const dismiss = useCallback((id: number) => {
    const timer = timersRef.current.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    timersRef.current.delete(id)
    setToasts((items) => items.filter((item) => item.id !== id))
  }, [])

  const clear = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer))
    timersRef.current.clear()
    setToasts([])
  }, [])

  const add = useCallback((kindInput: ToastKindInput, message: string, options: ToastOptions = {}) => {
    const kind = normalizeToastKind(kindInput)
    const id = ++toastSequence
    const duration = options.duration === undefined
      ? (kind === 'error' ? null : kind === 'success' ? 4000 : kind === 'warning' ? 8000 : 6000)
      : options.duration
    setToasts((items) => [
      ...items.filter((item) => !(item.kind === kind && item.message === message)),
      { id, kind, message, title: options.title, duration },
    ].slice(-6))
    if (duration && duration > 0) {
      const timer = window.setTimeout(() => dismiss(id), duration)
      timersRef.current.set(id, timer)
    }
    return id
  }, [dismiss])

  const api = useMemo(() => {
    const value = ((kind: ToastKindInput, message: string, options?: ToastOptions) => add(kind, message, options)) as ToastApi
    value.success = (message, options) => add('success', message, options)
    value.error = (message, options) => add('error', message, options)
    value.warning = (message, options) => add('warning', message, options)
    value.info = (message, options) => add('info', message, options)
    value.dismiss = dismiss
    value.clear = clear
    return value
  }, [add, dismiss, clear])

  useEffect(() => () => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer))
    timersRef.current.clear()
  }, [])

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toasts.length > 0 && (
        <div aria-live="polite" aria-atomic="false" style={{
          position: 'fixed', right: 16, bottom: 16, zIndex: 300000,
          display: 'flex', flexDirection: 'column', gap: 8,
          width: 420, maxWidth: 'calc(100vw - 32px)', pointerEvents: 'none',
        }}>
          {toasts.length > 1 && (
            <button onClick={clear} style={{
              alignSelf: 'flex-end', pointerEvents: 'auto', background: '#1f2937',
              color: '#cbd5e1', border: '1px solid #334155', borderRadius: 6,
              padding: '2px 9px', fontSize: 11, cursor: 'pointer',
            }}>全部关闭（{toasts.length}）</button>
          )}
          {toasts.map((toast) => {
            const style = TOAST_STYLE[toast.kind]
            return (
              <div key={toast.id} role={toast.kind === 'error' ? 'alert' : 'status'} style={{
                pointerEvents: 'auto', display: 'flex', gap: 10, alignItems: 'flex-start',
                background: style.bg, border: `1px solid ${style.border}`, color: style.color,
                borderRadius: 10, padding: '10px 12px', fontSize: 12.5, lineHeight: 1.55,
                boxShadow: '0 8px 24px rgba(0,0,0,.45)', backdropFilter: 'blur(6px)',
              }}>
                <span aria-hidden="true" style={{
                  flexShrink: 0, width: 18, height: 18, borderRadius: 9, marginTop: 1,
                  background: style.border, color: '#0b1020', fontSize: 11, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>{style.icon}</span>
                <span style={{ flex: 1, minWidth: 0, wordBreak: 'break-word', maxHeight: 200, overflow: 'auto' }}>
                  {toast.title && <strong style={{ display: 'block' }}>{toast.title}</strong>}
                  {toast.message}
                </span>
                <button onClick={() => dismiss(toast.id)} title="关闭" aria-label="关闭通知" style={{
                  flexShrink: 0, background: 'transparent', border: 0, color: style.color,
                  opacity: .7, cursor: 'pointer', fontSize: 15, lineHeight: 1, padding: '0 2px',
                }}>×</button>
              </div>
            )
          })}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast 必须在 FeedbackProvider 或 ToastProvider 内使用')
  return context
}

// ── 异步 Confirm / FormModal ────────────────────────────────────────
export type ConfirmDialogOptions = {
  title: string
  message: React.ReactNode
  consequence?: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
}

export type FormFieldOption = { value: string; label: string }
export type FormField = {
  name: string
  label: string
  type?: 'text' | 'textarea' | 'password' | 'select'
  required?: boolean
  placeholder?: string
  hint?: string
  initialValue?: string
  options?: FormFieldOption[]
  validate?: (value: string, values: Record<string, string>) => string | undefined
}

export type FormDialogOptions = {
  title: string
  subtitle?: string
  fields: FormField[]
  initialValues?: Record<string, string>
  submitLabel?: string
  cancelLabel?: string
  width?: number
  tone?: 'default' | 'danger'
  validate?: (values: Record<string, string>) => string | undefined
}

export const ConfirmDialog: React.FC<{
  open: boolean
  options: ConfirmDialogOptions
  onConfirm: () => void
  onCancel: () => void
}> = ({ open, options, onConfirm, onCancel }) => (
  <Modal
    open={open}
    title={options.title}
    width={460}
    onClose={onCancel}
    closeOnBackdrop={false}
    closeOnEscape
    zIndex={400000}
    footer={(
      <>
        <button onClick={onCancel} style={btn('#334155')}>{options.cancelLabel || '取消'}</button>
        <button data-autofocus="true" onClick={onConfirm} style={btn(options.tone === 'danger' ? '#b91c1c' : '#2563eb')}>
          {options.confirmLabel || '确认'}
        </button>
      </>
    )}
  >
    <div style={{ color: '#cbd5e1', fontSize: 13, lineHeight: 1.65 }}>{options.message}</div>
    {options.consequence && (
      <div style={{ marginTop: 12 }}>
        <Alert tone={options.tone === 'danger' ? 'error' : 'warning'} title="操作后果">
          {options.consequence}
        </Alert>
      </div>
    )}
  </Modal>
)

export const FormModal: React.FC<{
  open: boolean
  options: FormDialogOptions
  onSubmit: (values: Record<string, string>) => void
  onCancel: () => void
}> = ({ open, options, onSubmit, onCancel }) => {
  const initialValues = useMemo(() => Object.fromEntries(
    options.fields.map((field) => [field.name, options.initialValues?.[field.name] ?? field.initialValue ?? '']),
  ), [options])
  const [values, setValues] = useState<Record<string, string>>(initialValues)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')

  const submit = () => {
    const normalized = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim()]))
    const nextErrors: Record<string, string> = {}
    for (const field of options.fields) {
      const value = normalized[field.name] || ''
      if (field.required && !value) nextErrors[field.name] = `请填写${field.label}`
      else {
        const error = field.validate?.(value, normalized)
        if (error) nextErrors[field.name] = error
      }
    }
    setErrors(nextErrors)
    const nextFormError = Object.keys(nextErrors).length ? '' : (options.validate?.(normalized) || '')
    setFormError(nextFormError)
    if (Object.keys(nextErrors).length || nextFormError) return
    onSubmit(normalized)
  }

  return (
    <Modal
      open={open}
      title={options.title}
      subtitle={options.subtitle}
      width={options.width || 520}
      onClose={onCancel}
      closeOnBackdrop={false}
      closeOnEscape
      zIndex={400000}
      footer={(
        <>
          <button onClick={onCancel} style={btn('#334155')}>{options.cancelLabel || '取消'}</button>
          <button onClick={submit} style={btn(options.tone === 'danger' ? '#b91c1c' : '#2563eb')}>
            {options.submitLabel || '提交'}
          </button>
        </>
      )}
    >
      {formError && <div style={{ marginBottom: 10 }}><Alert tone="error">{formError}</Alert></div>}
      {options.fields.map((field, index) => (
        <Field key={field.name} label={field.label} hint={field.hint} required={field.required} error={errors[field.name]}>
          {field.type === 'textarea' ? (
            <textarea
              data-autofocus={index === 0 ? 'true' : undefined}
              value={values[field.name] || ''}
              placeholder={field.placeholder}
              rows={4}
              onChange={(event) => {
                setValues((current) => ({ ...current, [field.name]: event.target.value }))
                setErrors((current) => ({ ...current, [field.name]: '' }))
              }}
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          ) : field.type === 'select' ? (
            <select
              data-autofocus={index === 0 ? 'true' : undefined}
              value={values[field.name] || ''}
              onChange={(event) => {
                setValues((current) => ({ ...current, [field.name]: event.target.value }))
                setErrors((current) => ({ ...current, [field.name]: '' }))
              }}
              style={inputStyle}
            >
              {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          ) : (
            <input
              data-autofocus={index === 0 ? 'true' : undefined}
              type={field.type === 'password' ? 'password' : 'text'}
              value={values[field.name] || ''}
              placeholder={field.placeholder}
              onChange={(event) => {
                setValues((current) => ({ ...current, [field.name]: event.target.value }))
                setErrors((current) => ({ ...current, [field.name]: '' }))
              }}
              onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); submit() } }}
              style={inputStyle}
            />
          )}
        </Field>
      ))}
    </Modal>
  )
}

type DialogRequest =
  | { id: number; kind: 'confirm'; options: ConfirmDialogOptions; resolve: (value: boolean) => void }
  | { id: number; kind: 'form'; options: FormDialogOptions; resolve: (value: Record<string, string> | null) => void }

type DialogApi = {
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>
  form: <T extends Record<string, string> = Record<string, string>>(options: FormDialogOptions) => Promise<T | null>
}

const DialogContext = createContext<DialogApi | null>(null)
let dialogSequence = 0

export const DialogProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [active, setActive] = useState<DialogRequest | null>(null)
  const activeRef = useRef<DialogRequest | null>(null)
  const queueRef = useRef<DialogRequest[]>([])

  const enqueue = useCallback((request: DialogRequest) => {
    if (!activeRef.current) {
      activeRef.current = request
      setActive(request)
    } else {
      queueRef.current.push(request)
    }
  }, [])

  const settle = useCallback((value: boolean | Record<string, string> | null) => {
    const current = activeRef.current
    if (!current) return
    activeRef.current = null
    if (current.kind === 'confirm') current.resolve(value === true)
    else current.resolve(value && typeof value === 'object' ? value : null)
    const next = queueRef.current.shift() || null
    activeRef.current = next
    setActive(next)
  }, [])

  const api = useMemo<DialogApi>(() => ({
    confirm: (options) => new Promise<boolean>((resolve) => {
      enqueue({ id: ++dialogSequence, kind: 'confirm', options, resolve })
    }),
    form: <T extends Record<string, string> = Record<string, string>>(options: FormDialogOptions) => (
      new Promise<T | null>((resolve) => {
        enqueue({
          id: ++dialogSequence,
          kind: 'form',
          options,
          resolve: (value) => resolve(value as T | null),
        })
      })
    ),
  }), [enqueue])

  useEffect(() => () => {
    const current = activeRef.current
    if (current) {
      if (current.kind === 'confirm') current.resolve(false)
      else current.resolve(null)
    }
    queueRef.current.forEach((request) => {
      if (request.kind === 'confirm') request.resolve(false)
      else request.resolve(null)
    })
    activeRef.current = null
    queueRef.current = []
  }, [])

  return (
    <DialogContext.Provider value={api}>
      {children}
      {active?.kind === 'confirm' && (
        <ConfirmDialog
          key={active.id}
          open
          options={active.options}
          onCancel={() => settle(false)}
          onConfirm={() => settle(true)}
        />
      )}
      {active?.kind === 'form' && (
        <FormModal
          key={active.id}
          open
          options={active.options}
          onCancel={() => settle(null)}
          onSubmit={(values) => settle(values)}
        />
      )}
    </DialogContext.Provider>
  )
}

export function useDialogs(): DialogApi {
  const context = useContext(DialogContext)
  if (!context) throw new Error('useDialogs 必须在 FeedbackProvider 或 DialogProvider 内使用')
  return context
}

export const FeedbackProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ToastProvider>
    <DialogProvider>{children}</DialogProvider>
  </ToastProvider>
)

// ── 统一 API 错误解析 ───────────────────────────────────────────────
export class ApiError extends Error {
  status?: number
  code?: string
  detail?: unknown
  body?: unknown

  constructor(message: string, options: { status?: number; code?: string; detail?: unknown; body?: unknown } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.detail = options.detail
    this.body = options.body
  }
}

type ExtractedError = { message?: string; code?: string; detail?: unknown }

const textValue = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value.trim() || undefined
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return undefined
}

const extractApiError = (value: unknown, depth = 0): ExtractedError => {
  if (depth > 5 || value == null) return {}
  if (value instanceof ApiError) return { message: value.message, code: value.code, detail: value.detail }
  if (value instanceof Error) return { message: value.message }
  const direct = textValue(value)
  if (direct) {
    if (/^[\[{]/.test(direct)) {
      try { return extractApiError(JSON.parse(direct), depth + 1) } catch { /* 原始文本本身就是错误 */ }
    }
    return { message: direct }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = extractApiError(item, depth + 1)
      if (found.message || found.code) return found
    }
    return {}
  }
  if (typeof value !== 'object') return {}

  const object = value as Record<string, unknown>
  const code = textValue(object.code) || textValue(object.error_code)
  for (const key of ['detail', 'error', 'message', 'reason', 'description']) {
    if (!(key in object)) continue
    const found = extractApiError(object[key], depth + 1)
    if (found.message || found.code) {
      return { message: found.message, code: found.code || code, detail: key === 'detail' ? object[key] : found.detail }
    }
  }
  return { code, detail: object.detail }
}

const parseBodyText = (text: string): unknown => {
  const trimmed = text.trim()
  if (!trimmed) return undefined
  try { return JSON.parse(trimmed) } catch { return trimmed }
}

const makeApiError = (
  body: unknown,
  status?: number,
  statusText?: string,
  fallback = '请求失败',
): ApiError => {
  const extracted = extractApiError(body)
  const suffix = status ? ` (HTTP ${status})` : ''
  const message = extracted.message || (extracted.code ? `${fallback}（${extracted.code}）` : `${fallback}${suffix}`)
  return new ApiError(message, {
    status,
    code: extracted.code,
    detail: typeof body === 'object' && body !== null ? (body as Record<string, unknown>).detail : body,
    body: body ?? statusText,
  })
}

/** 解析非 2xx Response，保留 status/code/detail，并生成可直接展示的 message。 */
export async function parseApiError(response: Response, fallback = '请求失败'): Promise<ApiError> {
  let body: unknown
  try { body = parseBodyText(await response.text()) } catch { body = undefined }
  return makeApiError(body, response.status, response.statusText, fallback)
}

/**
 * 读取 API 响应；HTTP 非 2xx 或 GenericResult `{ok:false}` 统一抛出 ApiError。
 * JSON、字符串错误和原始文本都只读取一次，不会出现二次 `.json()` 失败。
 */
export async function parseApiResponse<T = unknown>(response: Response, fallback = '请求失败'): Promise<T> {
  let body: unknown
  try { body = parseBodyText(await response.text()) } catch { body = undefined }
  const genericFailure = typeof body === 'object' && body !== null && (body as Record<string, unknown>).ok === false
  if (!response.ok || genericFailure) throw makeApiError(body, response.status, response.statusText, fallback)
  return body as T
}

/** 把网络异常、ApiError、结构化 detail/error/message 都转成用户可读文案。 */
export function formatApiError(error: unknown, fallback = '请求失败'): string {
  const extracted = extractApiError(error)
  return extracted.message || (extracted.code ? `${fallback}（${extracted.code}）` : fallback)
}

// ── 快捷指令:用户自选,持久化 ──────────────────────────────────────
export interface QuickCmd {
  id: string
  title: string
  prompt: string
  origin?: string
}

const LS_KEY = 'seoagents.quickCommands.v1'

function read(): QuickCmd[] {
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as QuickCmd[]) : []
  } catch { return [] }
}

function write(list: QuickCmd[]): void {
  try { window.localStorage.setItem(LS_KEY, JSON.stringify(list)) } catch { /* 隐私模式下静默 */ }
  window.dispatchEvent(new CustomEvent('quickcmds-changed'))
}

/** 快捷指令的读写。跨组件同步靠自定义事件,不引第三方状态库。 */
export function useQuickCommands() {
  const [cmds, setCmds] = useState<QuickCmd[]>(read)

  useEffect(() => {
    const sync = () => setCmds(read())
    window.addEventListener('quickcmds-changed', sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener('quickcmds-changed', sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  return {
    cmds,
    has: (id: string) => cmds.some((c) => c.id === id),
    add: (c: QuickCmd) => {
      const cur = read()
      if (cur.some((x) => x.id === c.id)) return
      write([...cur, c])
    },
    remove: (id: string) => write(read().filter((c) => c.id !== id)),
    toggle: (c: QuickCmd) => {
      const cur = read()
      write(cur.some((x) => x.id === c.id)
        ? cur.filter((x) => x.id !== c.id)
        : [...cur, c])
    },
    clear: () => write([]),
  }
}

/* ============================================================
   dashboard-kit · themes.js
   主题引擎：hue 切换 + 明暗模式 + 持久化 + 跨页同步
   依据：22 号文 §2.2（六色预设环 + 自定义 hue）

   零依赖，原生 ESM。同时挂 window.DashboardKitTheme 供 A 档页面直接用。

   铁律：
     - localStorage 全部 try/catch（file:// 与隐私模式抛 SecurityError）
     - 切主题 = 改 --hue 一个数，绝不逐元素改色
     - storage 事件跨页同步
   ============================================================ */

const HUE_KEY = 'themeHue';
const MODE_KEY = 'themeMode';

/** 六色预设环（22 号文 §2.2，部门专属色映射） */
export const PRESET_THEMES = [
  { id: 'federal-purple', name: '联邦紫', hue: 285, dept: '主 Hermes / 指挥中心' },
  { id: 'deep-blue',      name: '深空蓝', hue: 220, dept: '开发部 / 运维 HM' },
  { id: 'pine-green',     name: '松绿',   hue: 160, dept: 'SEO 部' },
  { id: 'gold',           name: '鎏金',   hue: 85,  dept: '情报部' },
  { id: 'molten-orange',  name: '熔橙',   hue: 25,  dept: '创作部 / 运营部' },
  { id: 'crimson',        name: '绯红',   hue: 350, dept: '巡查 HM / 告警态' },
];

export const DEFAULT_HUE = 285;
export const MODES = ['dark', 'light'];

/* ── 安全存储：隐私模式 / file:// 下静默降级 ── */
function safeGet(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function safeSet(key, value) {
  try { window.localStorage.setItem(key, value); return true; } catch { return false; }
}

function clampHue(h) {
  const n = Number(h);
  if (!Number.isFinite(n)) return DEFAULT_HUE;
  return ((Math.round(n) % 360) + 360) % 360;
}

function normalizeMode(m) {
  return MODES.includes(m) ? m : null;
}

/** 系统深浅色偏好 */
export function systemMode() {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

/** 读取当前生效 hue（存储 → 默认） */
export function getHue() {
  const saved = safeGet(HUE_KEY);
  return saved === null ? DEFAULT_HUE : clampHue(saved);
}

/** 读取当前生效模式（存储 → 系统跟随） */
export function getMode() {
  return normalizeMode(safeGet(MODE_KEY)) || systemMode();
}

/**
 * 应用 hue —— 主题切换的唯一动作：改一个 CSS 变量。
 * @param {number} hue 0-360
 * @param {{persist?: boolean}} [opts]
 */
export function applyHue(hue, opts = {}) {
  const h = clampHue(hue);
  document.documentElement.style.setProperty('--hue', String(h));
  if (opts.persist !== false) safeSet(HUE_KEY, String(h));
  emit({ hue: h, mode: getMode() });
  return h;
}

/**
 * 应用明暗模式 —— 翻转 [data-mode] 属性，tokens.css 负责阶梯翻转。
 * @param {'dark'|'light'} mode
 */
export function applyMode(mode, opts = {}) {
  const m = normalizeMode(mode) || 'dark';
  document.documentElement.setAttribute('data-mode', m);
  document.documentElement.style.colorScheme = m;
  if (opts.persist !== false) safeSet(MODE_KEY, m);
  emit({ hue: getHue(), mode: m });
  return m;
}

export function toggleMode() {
  return applyMode(getMode() === 'dark' ? 'light' : 'dark');
}

/** 按预设 id 切换 */
export function applyPreset(id) {
  const preset = PRESET_THEMES.find((t) => t.id === id || t.name === id);
  if (!preset) return null;
  applyHue(preset.hue);
  return preset;
}

/* ── 变更订阅 ── */
const listeners = new Set();
function emit(detail) {
  listeners.forEach((fn) => { try { fn(detail); } catch { /* 单个订阅者异常不影响其他 */ } });
  try {
    window.dispatchEvent(new CustomEvent('dk:themechange', { detail }));
  } catch { /* 老内核无 CustomEvent 构造器 */ }
}

/** 订阅主题变化，返回取消订阅函数 */
export function onThemeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * 初始化：读存储 → 应用 → 挂跨页同步 + 系统偏好跟随。
 * 幂等，可重复调用。
 */
export function initTheme(opts = {}) {
  const hue = opts.hue !== undefined ? clampHue(opts.hue) : getHue();
  const stored = normalizeMode(safeGet(MODE_KEY));
  const mode = opts.mode ? normalizeMode(opts.mode) : (stored || systemMode());

  applyHue(hue, { persist: false });
  applyMode(mode, { persist: false });

  if (!initTheme._wired) {
    initTheme._wired = true;

    // 跨页/跨标签同步
    window.addEventListener('storage', (e) => {
      if (e.key === HUE_KEY && e.newValue != null) applyHue(e.newValue, { persist: false });
      if (e.key === MODE_KEY && e.newValue != null) applyMode(e.newValue, { persist: false });
    });

    // 用户未显式选过模式时，跟随系统
    try {
      const mq = window.matchMedia('(prefers-color-scheme: light)');
      const handler = (ev) => {
        if (normalizeMode(safeGet(MODE_KEY))) return; // 用户已显式选择，不覆盖
        applyMode(ev.matches ? 'light' : 'dark', { persist: false });
      };
      if (mq.addEventListener) mq.addEventListener('change', handler);
      else if (mq.addListener) mq.addListener(handler);
    } catch { /* 无 matchMedia 的环境 */ }
  }

  return { hue, mode };
}

/* ============================================================
   ECharts 同源着色（22 号文 §五 S5）
   多系列走黄金角 137.5° 等距采样，任意条数不撞色。
   ============================================================ */

/** 读取当前 token 的计算值 */
export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * 生成 n 条系列的同源色（基于当前 hue 黄金角采样）
 * @param {number} n
 */
export function seriesColors(n = 8) {
  const base = getHue();
  const mode = getMode();
  const L = mode === 'light' ? 52 : 70;
  const C = mode === 'light' ? 0.16 : 0.15;
  return Array.from({ length: n }, (_, i) =>
    `oklch(${L}% ${C} ${(base + i * 137.5) % 360})`);
}

/**
 * 由 tokens 运行时生成 ECharts theme 对象。
 * 切主题 → 重建 → setOption，图表与 UI 永远同源。
 */
export function echartsTheme(seriesCount = 8) {
  return {
    color: seriesColors(seriesCount),
    backgroundColor: 'transparent',
    textStyle: { fontFamily: token('--font-ui'), color: token('--dim') },
    title: { textStyle: { color: token('--text') } },
    legend: { textStyle: { color: token('--dim') } },
    grid: { borderColor: token('--border') },
    categoryAxis: {
      axisLine: { lineStyle: { color: token('--border') } },
      axisLabel: { color: token('--dim') },
      splitLine: { lineStyle: { color: token('--border') } },
    },
    valueAxis: {
      axisLine: { lineStyle: { color: token('--border') } },
      axisLabel: { color: token('--dim') },
      splitLine: { lineStyle: { color: token('--border') } },
    },
    tooltip: {
      backgroundColor: token('--panel2'),
      borderColor: token('--border'),
      textStyle: { color: token('--text') },
    },
  };
}

/* ── A 档页面全局挂载（无构建工具时直接用 window.DashboardKitTheme）── */
const api = {
  PRESET_THEMES, DEFAULT_HUE, MODES,
  initTheme, getHue, getMode, applyHue, applyMode, applyPreset,
  toggleMode, onThemeChange, systemMode, token, seriesColors, echartsTheme,
};
try { window.DashboardKitTheme = api; } catch { /* SSR / worker */ }

export default api;

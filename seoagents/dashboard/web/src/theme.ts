/**
 * dashboard-kit 主题引擎的 TypeScript 桥接。
 * 实际实现在 dojocore/dashboard-kit/themes.js（联邦标准件，零依赖 ESM）。
 * 本文件只做类型标注，不复制任何逻辑——kit 是唯一事实源。
 */
// @ts-ignore -- kit 为纯 JS 标准件，无 .d.ts
import kit from '../../../../dojocore/dashboard-kit/themes.js'

export type ThemeMode = 'dark' | 'light'

export interface PresetTheme {
  id: string
  name: string
  hue: number
  dept: string
}

export interface ThemeState {
  hue: number
  mode: ThemeMode
}

export const PRESET_THEMES: PresetTheme[] = kit.PRESET_THEMES
export const DEFAULT_HUE: number = kit.DEFAULT_HUE

/** 初始化：读存储 → 应用 → 挂跨页同步。幂等。 */
export const initTheme = (opts?: Partial<ThemeState>): ThemeState => kit.initTheme(opts)

/** 应用 hue（唯一主题变量），返回归一化后的值 */
export const applyHue = (hue: number): number => kit.applyHue(hue)

/** 应用明暗模式 */
export const applyMode = (mode: ThemeMode): ThemeMode => kit.applyMode(mode)

/** 明暗切换，返回切换后的模式 */
export const toggleMode = (): ThemeMode => kit.toggleMode()

export const getHue = (): number => kit.getHue()
export const getMode = (): ThemeMode => kit.getMode()

/** 订阅主题变化，返回取消订阅函数 */
export const onThemeChange = (fn: (s: ThemeState) => void): (() => void) => kit.onThemeChange(fn)

/** ECharts / 图表同源着色（22 号文 §五 S5） */
export const seriesColors = (n?: number): string[] => kit.seriesColors(n)
export const echartsTheme = (n?: number): Record<string, unknown> => kit.echartsTheme(n)

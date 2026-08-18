#!/usr/bin/env node
/* ============================================================
   dashboard-kit · audit.mjs
   构建时门禁（22 号文 §六）——不过不给发。

   检查项：
     A. 硬编码色值扫描      组件/页面层 0 个字面量色（tokens.css 白名单除外）
     B. 底座 hue 隔离       bg/surface/panel/border/text 类 token 不含 var(--hue)
     C. 对比度 AA           正文/背景 ≥4.5:1，大字 ≥3:1，6 主题 × 明暗 = 12 组全跑
     D. 字体白名单          仅 Inter / JetBrains Mono / 思源黑体 + 系统回退
     E. 首屏体积            ≤200KB gzip（A 档含内联；B 档 vendor 另计，总量 ≤350KB）
     F. reduced-motion      媒体查询存在且覆盖全部动画

   零依赖，纯 Node ≥18。用法：
     node dojocore/dashboard-kit/audit.mjs [--root <repo>] [--json]
   ============================================================ */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, extname, relative, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const __dirname = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const JSON_OUT = args.includes('--json');
const rootIdx = args.indexOf('--root');
const REPO = rootIdx >= 0 ? args[rootIdx + 1] : join(__dirname, '..', '..');

const KIT_DIR = join(REPO, 'dojocore', 'dashboard-kit');
const TOKENS_CSS = join(KIT_DIR, 'tokens.css');

/* 扫描目标：页面/组件层源码 */
const SCAN_TARGETS = [
  join(REPO, 'seoagents', 'dashboard', 'web', 'src'),
  join(KIT_DIR, 'components'),
  join(KIT_DIR, 'layout'),
];
/* 白名单：允许出现字面量色值的文件（tokens 是唯一色彩事实源） */
const COLOR_WHITELIST = [TOKENS_CSS];

const BUILD_DIR = join(REPO, 'seoagents', 'dashboard', 'static', 'app');

const results = [];
function record(id, name, ok, detail, items = []) {
  results.push({ id, name, ok, detail, items });
}

/* ── 文件遍历 ── */
function walk(dir, exts = ['.css', '.ts', '.tsx', '.js', '.jsx', '.html']) {
  if (!existsSync(dir)) return [];
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry.startsWith('.')) continue;
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) out.push(...walk(p, exts));
    else if (exts.includes(extname(p)) && !p.endsWith('.bak')) out.push(p);
  }
  return out;
}

/* ============================================================
   OKLCH → sRGB → 相对亮度 → WCAG 对比度
   ============================================================ */
function oklchToSrgb(L, C, Hdeg) {
  const h = (Hdeg * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);

  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;

  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;

  let r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  let g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  let bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;

  const gamma = (u) => {
    const x = u <= 0.0031308 ? 12.92 * u : 1.055 * Math.pow(Math.max(u, 0), 1 / 2.4) - 0.055;
    return Math.min(1, Math.max(0, x));
  };
  return [gamma(r), gamma(g), gamma(bl)];
}

function relLuminance([r, g, b]) {
  const f = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(c1, c2) {
  const L1 = relLuminance(c1), L2 = relLuminance(c2);
  const [hi, lo] = L1 > L2 ? [L1, L2] : [L2, L1];
  return (hi + 0.05) / (lo + 0.05);
}

/* ── 从 tokens.css 解析 oklch() 定义（支持 calc(var(--hue) ± n)）── */
function parseTokens(cssText, blockSelector) {
  // 抓取指定选择器块
  const re = new RegExp(`${blockSelector.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\s*\\{([\\s\\S]*?)\\n\\}`, 'm');
  const m = cssText.match(re);
  if (!m) return {};
  const body = m[1];
  const tokens = {};
  const lineRe = /--([\w-]+)\s*:\s*([^;]+);/g;
  let hit;
  while ((hit = lineRe.exec(body)) !== null) {
    tokens[`--${hit[1]}`] = hit[2].trim();
  }
  return tokens;
}

/** 把 token 值解析成 {L,C,H} —— 只处理 oklch()，含 alpha 的返回 null（不参与正文对比度） */
function resolveOklch(value, hue) {
  const m = value.match(/^oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+(.+?)\s*\)$/i);
  if (!m) return null;
  if (/\//.test(value)) return null; // 带 alpha，跳过
  let L = parseFloat(m[1]);
  if (value.includes('%')) L = L / 100;
  const C = parseFloat(m[2]);
  const hRaw = m[3].trim();

  let H;
  if (/^[\d.]+$/.test(hRaw)) H = parseFloat(hRaw);
  else if (/var\(--hue\)/.test(hRaw) && !/calc/.test(hRaw)) H = hue;
  else {
    const cm = hRaw.match(/calc\(\s*var\(--hue\)\s*([+-])\s*([\d.]+)\s*\)/);
    if (cm) H = cm[1] === '+' ? hue + parseFloat(cm[2]) : hue - parseFloat(cm[2]);
    else return null;
  }
  return { L, C, H: ((H % 360) + 360) % 360 };
}

/* ============================================================
   A. 硬编码色值扫描
   ============================================================ */
function checkHardcodedColors() {
  const files = SCAN_TARGETS.flatMap((d) => walk(d));
  const offenders = [];
  // 命中：#hex / rgb() / rgba() / hsl() / hsla()  —— oklch() 允许（感知色空间，token 内部也用）
  const colorRe = /(#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\()/g;

  for (const f of files) {
    if (COLOR_WHITELIST.includes(f)) continue;
    const text = readFileSync(f, 'utf8');
    const lines = text.split('\n');
    lines.forEach((line, i) => {
      // 跳过 url(data:image/svg+xml...) 里的 %23 编码与注释行
      const stripped = line.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*/, '');
      if (/url\(["']?data:/.test(stripped)) return;
      let m;
      colorRe.lastIndex = 0;
      while ((m = colorRe.exec(stripped)) !== null) {
        offenders.push(`${relative(REPO, f)}:${i + 1}  ${m[1]}`);
      }
    });
  }
  record('A', '硬编码色值扫描', offenders.length === 0,
    offenders.length === 0 ? '0 个字面量色值' : `${offenders.length} 处字面量色值`,
    offenders.slice(0, 30));
}

/* ============================================================
   B. 底座 hue 隔离
   ============================================================ */
function checkBaseHueIsolation() {
  const css = readFileSync(TOKENS_CSS, 'utf8');
  const BASE = ['--bg', '--surface', '--panel', '--panel2', '--border', '--text', '--dim', '--faint'];
  const offenders = [];
  for (const block of [':root', '[data-mode="light"]']) {
    const tokens = parseTokens(css, block);
    for (const name of BASE) {
      const v = tokens[name];
      if (v && /var\(--hue\)/.test(v)) offenders.push(`${block} ${name}: ${v}`);
    }
    // 彩度上限 ≤0.014（22 号文硬约束）
    for (const name of BASE) {
      const v = tokens[name];
      if (!v) continue;
      const m = v.match(/oklch\(\s*[\d.]+%?\s+([\d.]+)\s/);
      if (m && parseFloat(m[1]) > 0.014) offenders.push(`${block} ${name} 彩度 ${m[1]} > 0.014`);
    }
  }
  record('B', '底座 hue 隔离 + 中性彩度', offenders.length === 0,
    offenders.length === 0 ? '底座恒定中性，未引用 --hue，彩度 ≤0.014' : `${offenders.length} 项违规`,
    offenders);
}

/* ============================================================
   C. 对比度 AA（6 主题 × 明暗 = 12 组）
   ============================================================ */
const PRESET_HUES = [
  { name: '联邦紫', hue: 285 }, { name: '深空蓝', hue: 220 }, { name: '松绿', hue: 160 },
  { name: '鎏金', hue: 85 }, { name: '熔橙', hue: 25 }, { name: '绯红', hue: 350 },
];

function checkContrast() {
  const css = readFileSync(TOKENS_CSS, 'utf8');
  const failures = [];
  const samples = [];

  for (const mode of ['dark', 'light']) {
    const tokens = mode === 'dark'
      ? parseTokens(css, ':root')
      : { ...parseTokens(css, ':root'), ...parseTokens(css, '[data-mode="light"]') };

    for (const { name, hue } of PRESET_HUES) {
      const get = (t) => {
        const r = resolveOklch(tokens[t] || '', hue);
        return r ? oklchToSrgb(r.L, r.C, r.H) : null;
      };
      const bg = get('--bg');
      const panel = get('--panel');
      const text = get('--text');
      const dim = get('--dim');
      const accent = get('--accent');
      if (!bg || !panel || !text) { failures.push(`${mode}/${name}: token 解析失败`); continue; }

      const pairs = [
        ['正文/底色', text, bg, 4.5],
        ['正文/面板', text, panel, 4.5],
        ['次要文字/面板', dim, panel, 4.5],
        ['强调色(大字)/面板', accent, panel, 3.0],
      ];
      for (const [label, fg, b, min] of pairs) {
        if (!fg) continue;
        const ratio = contrast(fg, b);
        samples.push(`${mode}/${name} ${label} = ${ratio.toFixed(2)}:1 (需 ≥${min})`);
        if (ratio < min) failures.push(`${mode}/${name} ${label} ${ratio.toFixed(2)}:1 < ${min}`);
      }
    }
  }
  record('C', `对比度 AA（${PRESET_HUES.length} 主题 × 明暗 = ${PRESET_HUES.length * 2} 组）`,
    failures.length === 0,
    failures.length === 0
      ? `${samples.length} 项配对全部达标`
      : `${failures.length}/${samples.length} 项未达标`,
    failures.length ? failures : samples.slice(0, 8));
}

/* ============================================================
   D. 字体白名单
   ============================================================ */
function checkFonts() {
  const ALLOWED = [
    'inter variable', 'inter', 'jetbrains mono', 'source han sans cn vf',
    'noto sans cjk sc', 'pingfang sc', 'microsoft yahei',
    // 度量对齐用的回退族（kit 内部定义，不是第四字体——src 全是 local()）
    'inter fallback', 'mono fallback',
    // 系统回退关键字
    'system-ui', '-apple-system', 'blinkmacsystemfont', 'segoe ui',
    'ui-monospace', 'sf mono', 'menlo', 'consolas', 'monospace',
    'sans-serif', 'serif', 'ui-serif', 'georgia', 'inherit', 'initial', 'unset',
  ];
  const files = [
    ...SCAN_TARGETS.flatMap((d) => walk(d)),
    TOKENS_CSS,
    join(REPO, 'seoagents', 'dashboard', 'web', 'index.html'),
  ].filter((f) => existsSync(f));

  const offenders = [];
  const fontRe = /font-family\s*[:=]\s*([^;}\n]+)/gi;
  const faceRe = /@font-face/gi;

  for (const f of files) {
    const text = readFileSync(f, 'utf8');
    // 页面私自 @font-face（仅 kit 允许分发字体）
    if (faceRe.test(text) && !f.startsWith(KIT_DIR)) {
      offenders.push(`${relative(REPO, f)}: 页面私自 @font-face（禁止引入第四字体）`);
    }
    faceRe.lastIndex = 0;
    let m;
    while ((m = fontRe.exec(text)) !== null) {
      const decl = m[1];
      if (/var\(--font/.test(decl)) continue; // 走 token，合规
      const families = decl.split(',').map((s) => s.replace(/["'`]/g, '').trim().toLowerCase())
        .filter(Boolean);
      for (const fam of families) {
        if (fam.startsWith('var(') || fam.startsWith('${')) continue;
        if (!ALLOWED.includes(fam)) {
          offenders.push(`${relative(REPO, f)}: 非白名单字体 "${fam}"`);
        }
      }
    }
    // Google Fonts 外链（性能 + 字体白名单双违规）
    if (/fonts\.googleapis\.com|fonts\.gstatic\.com/.test(text)) {
      offenders.push(`${relative(REPO, f)}: 外链 Google Fonts（应由 kit 本地分发）`);
    }
  }
  const uniq = [...new Set(offenders)];
  record('D', '字体白名单（三字体 + 系统回退）', uniq.length === 0,
    uniq.length === 0 ? '仅使用 Inter / JetBrains Mono / 思源黑体 + 系统回退' : `${uniq.length} 处违规`,
    uniq.slice(0, 20));
}

/* ============================================================
   E. 首屏体积
   ============================================================ */
function checkBundleSize() {
  if (!existsSync(BUILD_DIR)) {
    record('E', '首屏体积 ≤200KB gzip', false, `构建产物不存在：${relative(REPO, BUILD_DIR)}（先跑 npm run build）`);
    return;
  }
  const files = walk(BUILD_DIR, ['.js', '.css', '.html']);
  let entryGzip = 0;
  let totalGzip = 0;
  const detail = [];
  for (const f of files) {
    const buf = readFileSync(f);
    const gz = gzipSync(buf).length;
    totalGzip += gz;
    const base = relative(BUILD_DIR, f);
    detail.push(`${base}  ${(gz / 1024).toFixed(1)}KB gz`);
    // 首屏 = index.html + 入口 chunk + 主 css（vendor 另计）
    if (/^index\.html$/.test(base) || /index-.*\.(js|css)$/.test(base)) entryGzip += gz;
  }
  const okEntry = entryGzip <= 200 * 1024;
  const okTotal = totalGzip <= 350 * 1024;
  record('E', '首屏体积（入口 ≤200KB / 总量 ≤350KB gzip）', okEntry && okTotal,
    `入口 ${(entryGzip / 1024).toFixed(1)}KB gz · 总量 ${(totalGzip / 1024).toFixed(1)}KB gz`,
    detail.sort((a, b) => parseFloat(b.split('  ')[1]) - parseFloat(a.split('  ')[1])).slice(0, 10));
}

/* ============================================================
   F. reduced-motion 覆盖
   ============================================================ */
function checkReducedMotion() {
  const cssFiles = [
    TOKENS_CSS,
    join(KIT_DIR, 'components', 'components.css'),
    join(KIT_DIR, 'layout', 'layout.css'),
    ...walk(join(REPO, 'seoagents', 'dashboard', 'web', 'src'), ['.css']),
  ].filter((f) => existsSync(f));

  const hasQuery = cssFiles.some((f) =>
    /@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)/.test(readFileSync(f, 'utf8')));

  // 覆盖性：全局通配符关停
  const covers = cssFiles.some((f) => {
    const t = readFileSync(f, 'utf8');
    const m = t.match(/@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{([\s\S]*?)\n\}/);
    return m && /\*\s*,\s*\*::before\s*,\s*\*::after/.test(m[1]) && /animation-duration/.test(m[1]);
  });

  record('F', 'prefers-reduced-motion 覆盖全部动画', hasQuery && covers,
    hasQuery && covers ? '媒体查询存在且全局通配覆盖' :
      !hasQuery ? '缺少 prefers-reduced-motion 媒体查询' : '媒体查询存在但未全局覆盖（需 *, *::before, *::after）');
}

/* ============================================================
   运行
   ============================================================ */
checkHardcodedColors();
checkBaseHueIsolation();
checkContrast();
checkFonts();
checkBundleSize();
checkReducedMotion();

const passed = results.filter((r) => r.ok).length;
const allOk = passed === results.length;

if (JSON_OUT) {
  console.log(JSON.stringify({ ok: allOk, passed, total: results.length, results }, null, 2));
} else {
  console.log('\n══════ dashboard-kit audit（22 号文 §六 发版门禁）══════\n');
  for (const r of results) {
    console.log(`${r.ok ? '✅' : '❌'} [${r.id}] ${r.name}`);
    console.log(`     ${r.detail}`);
    if (!r.ok && r.items?.length) {
      r.items.slice(0, 15).forEach((i) => console.log(`       · ${i}`));
      if (r.items.length > 15) console.log(`       … 另有 ${r.items.length - 15} 项`);
    }
    console.log('');
  }
  console.log(`──────  ${passed}/${results.length} 项通过  ${allOk ? '门禁 PASS' : '门禁 FAIL — 不给发'}  ──────\n`);
}

process.exit(allOk ? 0 : 1);

#!/usr/bin/env python3
"""
G1-F 前端迁移：把 SEOAgents dashboard 的字面量色值批量映射到 dashboard-kit tokens。

原则（用户纪律：换技术不重做视觉）：
  - 按 HSL 明度阶梯保序映射，视觉外观基本不变
  - 蓝紫系强调色 → 主题强调组（随 --hue 切换）
  - 中性灰蓝 → 底座组（恒定）
  - 绿/黄/红/紫 → 语义组（恒定）
  - 带 alpha 的 rgba → color-mix 或 *-soft token

用法：python3 dojocore/dashboard-kit/scripts/migrate_to_tokens.py [--dry-run]
"""
import re
import sys
from pathlib import Path

DRY = '--dry-run' in sys.argv
ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'seoagents' / 'dashboard' / 'web' / 'src'

# ── 色值 → token 映射表 ─────────────────────────────────────────
# 依据实测 HSL：hue / L / S 三维分类（见 audit 附录）
HEX_MAP = {
    # ═══ 底座组：中性灰蓝（hue 210-226，恒定不随主题）═══
    # 最深背景 L<9  → --bg
    '#0004': 'var(--bg)', '#090d16': 'var(--bg)', '#0b0e14': 'var(--bg)',
    '#06101e': 'var(--bg)', '#0b0f19': 'var(--bg)', '#0d1017': 'var(--bg)',
    '#0d1117': 'var(--bg)', '#080f1d': 'var(--bg)', '#07101f': 'var(--bg)',
    '#07121f': 'var(--bg)', '#08101f': 'var(--bg)', '#0b1020': 'var(--bg)',
    '#0b1220': 'var(--bg)', '#091523': 'var(--bg)',
    # 次层 L 9-13 → --surface
    '#11151f': 'var(--surface)', '#0a1627': 'var(--surface)', '#111826': 'var(--surface)',
    '#0d192b': 'var(--surface)', '#111827': 'var(--surface)', '#0f172a': 'var(--surface)',
    '#161b28': 'var(--surface)', '#101e33': 'var(--surface)',
    # 面板 L 14-20 → --panel
    '#182232': 'var(--panel)', '#13213a': 'var(--panel)', '#1a2434': 'var(--panel)',
    '#1c2333': 'var(--panel)', '#1e2937': 'var(--panel)', '#1f2937': 'var(--panel)',
    '#102a47': 'var(--panel)', '#1e293b': 'var(--panel)', '#1e2a3c': 'var(--panel)',
    '#192a42': 'var(--panel)', '#262b36': 'var(--panel)', '#252d40': 'var(--panel)',
    # 面板2 L 20-27 → --panel2
    '#183451': 'var(--panel2)', '#20324c': 'var(--panel2)', '#263247': 'var(--panel2)',
    '#283548': 'var(--panel2)', '#27415e': 'var(--panel2)',
    # 边框 L 26-35 → --border
    '#334155': 'var(--border)', '#374151': 'var(--border)', '#31577d': 'var(--border)',
    '#475569': 'var(--border)',
    # 次要文字 L 40-50 → --faint
    '#5a6275': 'var(--faint)', '#6b7280': 'var(--faint)', '#64748b': 'var(--faint)',
    # 弱化文字 L 60-68 → --dim
    '#8296b0': 'var(--dim)', '#8b93a7': 'var(--dim)', '#8ba0b8': 'var(--dim)',
    '#9ca3af': 'var(--dim)', '#94a3b8': 'var(--dim)', '#93a9c3': 'var(--dim)',
    # 正文 L>83 → --text
    '#cbd5e1': 'var(--text)', '#d1d5db': 'var(--text)', '#dde3f0': 'var(--text)',
    '#e5e7eb': 'var(--text)', '#e2e8f0': 'var(--text)', '#e6edf6': 'var(--text)',
    '#f3f4f6': 'var(--text)', '#f1f5f9': 'var(--text)', '#f8fafc': 'var(--text)',
    '#fff': 'var(--text)', '#ffffff': 'var(--text)',

    # ═══ 主题强调组：蓝/靛/紫系 → 随 --hue ═══
    # 深色强调底 → --accent-soft
    '#1e3a8a': 'var(--accent-soft)', '#1d4ed8': 'var(--accent2)',
    '#eaf2ff': 'var(--text)', '#dbeafe': 'var(--accent)', '#bfdbfe': 'var(--accent)',
    '#93c5fd': 'var(--accent)',
    # 主强调
    '#3b82f6': 'var(--accent)', '#2563eb': 'var(--accent2)', '#60a5fa': 'var(--accent)',
    '#4b8dff': 'var(--accent)', '#4c8dff': 'var(--accent)', '#4f8cff': 'var(--accent)',
    '#38bdf8': 'var(--accent2)', '#22d3ee': 'var(--accent2)', '#06b6d4': 'var(--accent2)',
    '#14b8a6': 'var(--accent3)',
    # 靛紫 → REVIEW 语义 / accent3
    '#818cf8': 'var(--rev)', '#8b5cf6': 'var(--rev)', '#a78bfa': 'var(--rev)',
    '#7c3aed': 'var(--rev)', '#6d28d9': 'var(--rev)', '#a855f7': 'var(--rev)',
    '#b07cff': 'var(--rev)', '#c084fc': 'var(--rev)', '#c4b5fd': 'var(--rev)',
    '#ec4899': 'var(--rev)',

    # ═══ 语义组：绿（ok）═══
    '#04140d': 'var(--ok-soft)', '#0f1f19': 'var(--ok-soft)',
    '#064e3b': 'var(--ok-soft)', '#065f46': 'var(--ok-soft)', '#047857': 'var(--ok)',
    '#059669': 'var(--ok)', '#10b981': 'var(--ok)', '#22c55e': 'var(--ok)',
    '#3fb950': 'var(--ok)', '#34c98e': 'var(--ok)', '#2dd4a6': 'var(--ok)',
    '#34d399': 'var(--ok)', '#3ecf8e': 'var(--ok)', '#6ee7b7': 'var(--ok)',
    '#a7f3d0': 'var(--ok)',

    # ═══ 语义组：黄橙（warn）═══
    '#1f1a10': 'var(--warn-soft)', '#78350f': 'var(--warn-soft)', '#92400e': 'var(--warn-soft)',
    '#d97706': 'var(--warn)', '#eab308': 'var(--warn)', '#d29922': 'var(--warn)',
    '#ff8c00': 'var(--warn)', '#f59e0b': 'var(--warn)', '#fbbf24': 'var(--warn)',
    '#f2b234': 'var(--warn)', '#f5b83d': 'var(--warn)', '#f5c451': 'var(--warn)',
    '#fcd34d': 'var(--warn)', '#f0cd7a': 'var(--warn)', '#fde68a': 'var(--warn)',
    '#f97316': 'var(--warn)', '#c2410c': 'var(--warn)', '#7c2d12': 'var(--warn-soft)',

    # ═══ 语义组：红（bad）═══
    '#1f1315': 'var(--bad-soft)', '#7f1d1d': 'var(--bad-soft)', '#b91c1c': 'var(--bad)',
    '#dc2626': 'var(--bad)', '#ef4444': 'var(--bad)', '#f85149': 'var(--bad)',
    '#f2606b': 'var(--bad)', '#f4655f': 'var(--bad)', '#ff6577': 'var(--bad)',
    '#f87171': 'var(--bad)', '#fca5a5': 'var(--bad)', '#fecaca': 'var(--bad)',
}

# 带 alpha 的 8 位 hex
HEX8_MAP = {
    '#071120f2': 'var(--bg)',
}

# ── rgba() → token 映射 ──────────────────────────────────────
# 黑色半透明阴影 → --shadow-* 或保留为 oklch（tokens 允许）
RGBA_MAP = {
    # 纯黑遮罩/阴影 → oklch 中性（audit 允许 oklch）
    'rgba(0,0,0,0.8)':  'oklch(0% 0 0 / .8)',
    'rgba(0,0,0,0.78)': 'oklch(0% 0 0 / .78)',
    'rgba(0,0,0,0.7)':  'oklch(0% 0 0 / .7)',
    'rgba(0,0,0,.7)':   'oklch(0% 0 0 / .7)',
    'rgba(0,0,0,0.6)':  'oklch(0% 0 0 / .6)',
    'rgba(0,0,0,.6)':   'oklch(0% 0 0 / .6)',
    'rgba(0,0,0,0.5)':  'oklch(0% 0 0 / .5)',
    'rgba(0,0,0,.5)':   'oklch(0% 0 0 / .5)',
    'rgba(0,0,0,.45)':  'oklch(0% 0 0 / .45)',
    'rgba(0,0,0,0.4)':  'oklch(0% 0 0 / .4)',
    'rgba(0,0,0,.4)':   'oklch(0% 0 0 / .4)',
    'rgba(0,0,0,.35)':  'oklch(0% 0 0 / .35)',
    'rgba(0,0,0,0.3)':  'oklch(0% 0 0 / .3)',
    'rgba(0,0,0,0.2)':  'oklch(0% 0 0 / .2)',
    'rgba(20,20,30,.9)': 'oklch(12% 0.01 260 / .9)',
    'rgba(15,23,42,0.95)': 'var(--surface)',
    # 白色叠层
    'rgba(255,255,255,.22)': 'oklch(100% 0 0 / .22)',
    'rgba(255,255,255,.14)': 'oklch(100% 0 0 / .14)',
    # 强调蓝半透明 → --accent-soft / --accent-line
    'rgba(59,130,246,0.4)':  'var(--accent-line)',
    'rgba(59,130,246,0.3)':  'var(--accent-line)',
    'rgba(59,130,246,0.25)': 'var(--accent-soft)',
    'rgba(37,99,235,0.4)':   'var(--accent-line)',
    'rgba(37,99,235,.45)':   'var(--accent-line)',
    'rgba(37,99,235,.3)':    'var(--accent-line)',
    'rgba(37,99,235,.2)':    'var(--accent-soft)',
    'rgba(37,99,235,.12)':   'var(--accent-soft)',
    'rgba(30,58,138,.94)':   'var(--accent-soft)',
    'rgba(30,58,138,.28)':   'var(--accent-soft)',
    # 中性半透明
    'rgba(148,163,184,.16)': 'var(--border)',
    # 语义半透明
    'rgba(63,185,80,.08)':  'var(--ok-soft)',
    'rgba(6,78,59,.94)':    'var(--ok-soft)',
    'rgba(6,78,59,.28)':    'var(--ok-soft)',
    'rgba(210,153,34,.08)': 'var(--warn-soft)',
    'rgba(120,53,15,.94)':  'var(--warn-soft)',
    'rgba(120,53,15,.28)':  'var(--warn-soft)',
    'rgba(248,81,73,.55)':  'var(--bad)',
    'rgba(127,29,29,.94)':  'var(--bad-soft)',
    'rgba(127,29,29,.28)':  'var(--bad-soft)',
    'rgba(168,85,247,.18)': 'var(--rev-soft)',
}


def normalize_rgba(text: str) -> str:
    """把 rgba( 1, 2, 3 , .4 ) 规范成 rgba(1,2,3,.4) 以便查表"""
    return re.sub(r'\s+', '', text)


def migrate_file(path: Path) -> tuple[int, list[str]]:
    original = path.read_text(encoding='utf-8')
    text = original
    unmapped = []

    # 1. rgba/rgb → token（先做，避免 hex 规则误伤）
    def rgba_sub(m):
        raw = m.group(0)
        key = normalize_rgba(raw)
        if key in RGBA_MAP:
            return RGBA_MAP[key]
        unmapped.append(f'{path.name}: {raw}')
        return raw

    text = re.sub(r'rgba?\([^)]*\)', rgba_sub, text)

    # 2. 8 位 hex（带 alpha）
    for h, tok in HEX8_MAP.items():
        text = re.sub(re.escape(h), tok, text, flags=re.IGNORECASE)

    # 3. 3/4/6 位 hex
    def hex_sub(m):
        raw = m.group(0)
        key = raw.lower()
        if key in HEX_MAP:
            return HEX_MAP[key]
        if key in HEX8_MAP:
            return HEX8_MAP[key]
        unmapped.append(f'{path.name}: {raw}')
        return raw

    text = re.sub(r'#[0-9a-fA-F]{3,8}\b', hex_sub, text)

    changed = text != original
    if changed and not DRY:
        path.write_text(text, encoding='utf-8')
    return (1 if changed else 0), unmapped


def main():
    files = [p for p in SRC.rglob('*')
             if p.suffix in {'.tsx', '.ts', '.css'} and not p.name.endswith('.bak')]
    total_changed = 0
    all_unmapped = []
    for f in sorted(files):
        n, un = migrate_file(f)
        total_changed += n
        all_unmapped.extend(un)

    print(f'{"[DRY-RUN] " if DRY else ""}迁移文件数：{total_changed}/{len(files)}')
    if all_unmapped:
        print(f'\n⚠️ 未映射色值 {len(all_unmapped)} 处：')
        for u in sorted(set(all_unmapped)):
            print(f'  · {u}')
    else:
        print('✅ 全部色值已映射到 token')


if __name__ == '__main__':
    main()

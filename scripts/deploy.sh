#!/usr/bin/env bash
# deploy.sh — pull, rebuild, restart, verify. Run on the server.
#
# Written because the deployment path had drifted into a state nobody could
# describe: images tagged with an old commit, newer code arriving through a
# mounted volume, and PYTHONPATH deciding which of the two actually ran. This
# script makes the running code equal to the committed code, and says so.
#
#   ./scripts/deploy.sh              pull + rebuild + restart + verify
#   ./scripts/deploy.sh --verify     verify only, change nothing
#   ./scripts/deploy.sh --no-build   restart without rebuilding
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE="${COMPOSE:-$REPO/docker-compose.yml}"
BRANCH="${BRANCH:-fix/conftest-windows-path-yaml-escape}"
DASH="${DASH:-http://127.0.0.1:8765}"
MCP="${MCP:-http://127.0.0.1:7801}"

G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; C=$'\033[36m'; N=$'\033[0m'
ok(){ echo "${G}[ OK ]${N} $*"; }; bad(){ echo "${R}[FAIL]${N} $*"; FAILED=$((FAILED+1)); }
warn(){ echo "${Y}[WARN]${N} $*"; }; sec(){ echo; echo "${C}━━━ $* ━━━${N}"; }
FAILED=0

VERIFY_ONLY=0; NO_BUILD=0
for a in "$@"; do case "$a" in --verify) VERIFY_ONLY=1;; --no-build) NO_BUILD=1;; esac; done

# ── code ──────────────────────────────────────────────────────────────
if [ "$VERIFY_ONLY" -eq 0 ]; then
  sec "1. 拉取代码"
  cd "$REPO" || { bad "仓库不存在: $REPO"; exit 1; }
  BEFORE=$(git rev-parse --short HEAD 2>/dev/null)
  git fetch origin --quiet && git pull --ff-only origin "$BRANCH" || bad "git pull 失败"
  AFTER=$(git rev-parse --short HEAD 2>/dev/null)
  [ "$BEFORE" = "$AFTER" ] && ok "已是最新 $AFTER" || ok "$BEFORE → $AFTER"
  git --no-pager log --oneline -1

  # ── build ───────────────────────────────────────────────────────────
  if [ "$NO_BUILD" -eq 0 ]; then
    sec "2. 重建镜像"
    # Tag with the commit so `docker ps` answers "which code is this?" honestly.
    export SEOAGENTS_TAG="$AFTER"
    docker compose -f "$COMPOSE" build --build-arg "GIT_SHA=$AFTER" \
      && ok "构建完成 (tag=$AFTER)" || bad "构建失败"
  fi

  sec "3. 重启"
  docker compose -f "$COMPOSE" up -d && ok "容器已拉起" || bad "启动失败"
  sleep 6
fi

# ── verify ────────────────────────────────────────────────────────────
sec "4. 运行态核对"

# The failure this whole script exists to prevent: image says one thing, the
# process runs another because a mounted volume shadows it.
echo "容器与镜像:"
docker compose -f "$COMPOSE" ps --format '  {{.Name}}\t{{.Image}}\t{{.Status}}' 2>/dev/null \
  || docker ps --format '  {{.Names}}\t{{.Image}}\t{{.Status}}'

DASH_C=$(docker ps --format '{{.Names}}' | grep -iE 'dash' | head -1)
if [ -n "$DASH_C" ]; then
  RUNNING=$(docker exec "$DASH_C" python -c \
    "import subprocess;print(subprocess.run(['git','-C','/app','rev-parse','--short','HEAD'],capture_output=True,text=True).stdout.strip() or 'n/a')" 2>/dev/null)
  EXPECT=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)
  if [ "$RUNNING" = "n/a" ] || [ -z "$RUNNING" ]; then
    warn "容器内无 git 信息,改用模块探测"
  elif [ "$RUNNING" = "$EXPECT" ]; then
    ok "容器内代码 = 仓库 HEAD ($EXPECT)"
  else
    bad "容器内 $RUNNING ≠ 仓库 $EXPECT —— 挂载卷可能盖住了镜像代码"
  fi
  docker exec "$DASH_C" sh -c 'env | grep -q "^PYTHONPATH=" && echo yes || echo no' 2>/dev/null \
    | grep -q yes && warn "容器设了 PYTHONPATH —— 代码来源不唯一,建议移除" \
                  || ok "无 PYTHONPATH 覆盖"
fi

sec "5. 端点自检"
probe(){ # probe <标签> <url> <期望码>
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$2")
  [ "$code" = "${3:-200}" ] && ok "$(printf '%-34s' "$1") $code" || bad "$(printf '%-34s' "$1") $code"
}
probe "看板 /healthz"          "$DASH/healthz"
probe "旧看板 /"               "$DASH/"
probe "控制台 /console"        "$DASH/console"
probe "工具目录 /api/catalog"  "$DASH/api/catalog"
probe "能力矩阵 /api/capabilities" "$DASH/api/capabilities"
probe "工作流 /api/workflows/templates" "$DASH/api/workflows/templates"
probe "收发件箱 /api/v1/inbox" "$DASH/api/v1/inbox"
probe "时间线 /api/timeline/agenda" "$DASH/api/timeline/agenda"
probe "GSC 面板 /api/gsc/overview"  "$DASH/api/gsc/overview?range=7d"

MCP_TOOLS=$(curl -s --max-time 10 "$MCP/mcp" -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("result",{}).get("tools",[])))' 2>/dev/null)
[ "${MCP_TOOLS:-0}" -ge 8 ] && ok "MCP 工具数 $MCP_TOOLS" || bad "MCP 工具数 ${MCP_TOOLS:-取不到}(应 ≥8)"

sec "6. 数据诚信自检"
# The point of the whole build: with a source missing it must report nothing,
# not invent something plausible.
GSC=$(curl -s --max-time 10 "$DASH/api/gsc/overview?range=7d")
if [ -n "$GSC" ]; then
  echo "$GSC" | python3 - <<'PY'
import sys, json
d = json.load(sys.stdin)
real = d.get("is_real_gsc")
kw = d.get("top_keywords") or []
status = d.get("keywords_status")
print(f"  GSC 接通: {real} | 关键词状态: {status} | 关键词条数: {len(kw)}")
if not real and kw:
    print("  \033[31m[FAIL]\033[0m 未接通却有关键词数据 —— 存在编造路径")
    sys.exit(1)
print("  \033[32m[ OK ]\033[0m 无数据时不编造")
PY
  [ $? -ne 0 ] && FAILED=$((FAILED+1))
fi

sec "结果"
if [ "$FAILED" -eq 0 ]; then
  echo "${G}部署核对通过,0 项异常${N}"
else
  echo "${R}${FAILED} 项异常 —— 上线前必须处理${N}"; exit 1
fi

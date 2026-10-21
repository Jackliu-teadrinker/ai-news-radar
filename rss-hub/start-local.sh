#!/usr/bin/env bash
# rss-hub/start-local.sh — 本地一键起 RSSHub（临时验证/接入前试跑）
# 用法:  bash rss-hub/start-local.sh
# 环境变量:
#   RSSHUB_DIR      源码+依赖目录 (默认 ~/.cache/ai-radar-rsshub)
#   RSSHUB_PORT     监听端口       (默认 1200)
#   GIT_PROXY       出网代理 URL   (默认空；本机出网被挡时设 http://127.0.0.1:7897)
#
# 需要本地装好 node (>=22, 建议 22/24) 和 npm。会自动装 pnpm。

set -euo pipefail

RSSHUB_DIR="${RSSHUB_DIR:-$HOME/.cache/ai-radar-rsshub}"
RSSHUB_PORT="${RSSHUB_PORT:-1200}"
GIT_PROXY="${GIT_PROXY:-}"

echo "==> 检查 node 版本"
command -v node >/dev/null || { echo "未装 node，请先装 node >= 22 (https://nodejs.org)"; exit 1; }
node -v

echo "==> 准备源码目录: $RSSHUB_DIR"
if [ ! -d "$RSSHUB_DIR/lib" ]; then
  if [ -n "$GIT_PROXY" ]; then
    echo "==> 通过代理 $GIT_PROXY 克隆 RSSHub"
    GIT_PROXY_URL="http://127.0.0.1:7897"   # Mihomo 本地代理，git 走 http(s).proxy
    git -c http.proxy="$GIT_PROXY_URL" -c https.proxy="$GIT_PROXY_URL" \
      clone --depth 1 https://github.com/DIYgod/RSSHub.git "$RSSHUB_DIR"
  else
    git clone --depth 1 https://github.com/DIYgod/RSSHub.git "$RSSHUB_DIR"
  fi
else
  echo "==> 已存在，git pull 更新"
  git -C "$RSSHUB_DIR" pull --depth 1 2>/dev/null || true
fi

echo "==> 安装 pnpm (全局, 若缺)"
command -v pnpm >/dev/null || npm i -g pnpm

cd "$RSSHUB_DIR"
echo "==> pnpm install (首次约 3 分钟)"
PUPPETEER_SKIP_DOWNLOAD=1 pnpm install

echo "==> 前台启动 RSSHub dev 在 :$RSSHUB_PORT (Ctrl+C 停)"
echo "    另开终端跑:  bash $(cd "$(dirname "$0")" && pwd)/probe-toutiao.sh http://127.0.0.1:$RSSHUB_PORT"
PORT="$RSSHUB_PORT" pnpm run dev

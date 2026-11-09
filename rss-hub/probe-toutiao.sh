#!/usr/bin/env bash
# rss-hub/probe-toutiao.sh — 探测验证：确认 RSSHub 服务通 + 头条反爬绕过成功
# 用法:  bash rss-hub/probe-toutiao.sh [BASE_URL] [CHANNEL]
#   BASE_URL  默认 http://127.0.0.1:1200
#   CHANNEL   默认 news_tech (可选: news_hot / digital / recommend / video ...)
# 成功: 打印 "✓ 真 RSS，绕过 a_bogus 反爬成功" + 前 8 条 title
# 失败: 打印 ✗ + 原始输出前 400 字符 (通常是欢迎页/404, 说明服务没起或路径错)

set -uo pipefail

BASE_URL="${1:-http://127.0.0.1:1200}"
CHANNEL="${2:-news_tech}"

# 频道名 → 中文 (仅用于日志)
case "$CHANNEL" in
  news_tech) CH_CN="科技";;
  news_hot)  CH_CN="热点";;
  digital)   CH_CN="数码";;
  recommend) CH_CN="推荐";;
  video)     CH_CN="视频";;
  *)         CH_CN="$CHANNEL";;
esac

echo "==> 探测 $BASE_URL/toutiao/channel/$CHANNEL ($CH_CN)"
resp=$(curl -s --max-time 50 "$BASE_URL/toutiao/channel/$CHANNEL" 2>/dev/null)

if echo "$resp" | grep -qiE "<rss|<feed|<channel|<item>"; then
  echo "✓ 真 RSS，绕过 a_bogus 反爬成功"
  echo "$resp" | grep -oiE "<title>[^<]*" | head -n 1 || true
  echo "$resp" | grep -oiE "<title>[^<]*" | tail -n +2 | head -n 8
else
  echo "✗ 非 RSS 输出 (服务未起 / 路径错 / 404)。原始输出前 400 字符:"
  echo "$resp" | head -c 400
  echo
  exit 1
fi

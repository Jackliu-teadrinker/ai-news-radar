#!/usr/bin/env bash
# Radar local fallback refresh — runs the full pipeline locally and pushes to master.
# Used while GitHub Actions is disabled at the account level (Bug #34).
# Pages is build_type=legacy with source=master, so pushing to master publishes the site.
#
# Log: ~/ai-news-radar-gh/local_refresh.log
# Run:  bash local_refresh.sh
set -u

REPO_DIR="$HOME/ai-news-radar-gh"
PY="$REPO_DIR/.venv-radar/Scripts/python.exe"
LOG="$REPO_DIR/local_refresh.log"
STALE_AFTER_MIN=45

export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897

cd "$REPO_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- freshness gate: skip if a recent run already refreshed data ---
LAST=$(python -c "import json;print(json.load(open('data/latest-24h-min.json',encoding='utf-8'))['generated_at'])" 2>/dev/null)
AGE_MIN=$(python - "$LAST" <<'PY' 2>/dev/null
import sys
from datetime import datetime, timezone
try:
    g = datetime.fromisoformat(sys.argv[1])
    print(int((datetime.now(timezone.utc) - g).total_seconds() // 60))
except Exception:
    print(99999)
PY
)
# --- ACTIONS HEALTH GATE (2026-10-12): self-gate to stop the dual-writer stomp ---
# local_refresh 只在 Actions 不健康时接管。远端 Pages 数据年龄 < GATE_AFTER_MIN
# 说明 update-news.yml (radar-auto) 仍在正常刷新，本地直接 no-op，避免本地 commit
# 晚于 Actions push 落地 -> "! rejected 非 fast-forward" 的莫名终止 (10/12 根因)。
# 拉不到远端视为 stale (99999)，宁可本地补一刀，不让安全网静默失效。
GATE_AFTER_MIN=40
REMOTE_AGE=$(curl -s --max-time 20 "https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json?cb=$(date +%s)" 2>/dev/null | python -c "
import sys, json
from datetime import datetime, timezone
try:
    d = json.load(sys.stdin)
    g = datetime.fromisoformat(d['generated_at'].replace('Z', '+00:00'))
    print(int((datetime.now(timezone.utc) - g).total_seconds() // 60))
except Exception:
    print(99999)
")
log "=== local_refresh start (local_gen=$LAST local_age=${AGE_MIN}min remote_age=${REMOTE_AGE}min) ==="
if [ "${REMOTE_AGE:-99999}" -lt "$GATE_AFTER_MIN" ]; then
    log "SKIP: Actions healthy (remote data ${REMOTE_AGE}min old < ${GATE_AFTER_MIN}min), local no-op"
    exit 0
fi
log "Actions unhealthy/stale (remote_age=${REMOTE_AGE}min >= ${GATE_AFTER_MIN}min) -> local takes over"
if [ "${AGE_MIN:-99999}" -lt "$STALE_AFTER_MIN" ]; then
    log "SKIP: local data is fresh (<${STALE_AFTER_MIN}min), nothing to do"
    exit 0
fi

# --- sync with master (scripts only; data/ takes master's newer snapshot on conflict) ---
# 2026-10-14 重大修复：这里的 merge 冲突处理会把冲突标记提交进 master。
# 症状：index.html 从 2026-10-10 起被污染 83 个 commit，23 组 <<<<<<< / ======= / >>>>>>，
# 24 份完整页面串在一起，master 和 Pages 上都在裸奔。浏览器把标记当文本渲染在页面上，
# 而不只是"内容被重复"——用户看到的是满屏 <<<<<<< HEAD。
# 根因：`git merge` 冲突后只 `git checkout --theirs data/` 处理 data/，
# 但 index.html 同样冲突（本地 cache-bust 正则 vs Actions 正则），留在工作区带着标记，
# 后面 `git add data/ index.html` 就把带标记的文件提交推上 master。
# 修法：冲突一律用"取 master 版"处理全部文件，并且推送前硬性校验无冲突标记。
git -c http.proxy=http://127.0.0.1:7897 fetch origin master -q 2>>"$LOG" || { log "FETCH FAILED"; exit 1; }
if ! git merge-base --is-ancestor HEAD origin/master 2>/dev/null; then
    git merge origin/master --no-edit -q >>"$LOG" 2>&1 || true
    if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
        log "merge conflict on: $(git diff --name-only --diff-filter=U | tr '\n' ' ')"
        # 全部冲突文件取 master 版（数据要最新、index.html 要干净版本）
        git checkout --theirs -- $(git diff --name-only --diff-filter=U | tr '\n' ' ') 2>>"$LOG"
        git add $(git diff --name-only --diff-filter=U | tr '\n' ' ') 2>>"$LOG"
        log "merge conflict -> resolved all conflicted files to master's version"
    fi
    git commit --no-edit -q >>"$LOG" 2>&1 || true
fi

# 硬闸：冲突标记绝不能进 commit / push（bug #35 回归防护）
if grep -lqE '^(<<<<<<<|>>>>>>>|=======)$' index.html scripts/*.py *.yml .github/workflows/*.yml 2>/dev/null; then
    log "GUARD CONFLICT MARKERS FOUND — aborting before pipeline (would publish broken index.html)"
    git reset --hard HEAD -q 2>/dev/null
    exit 1
fi
log "pre-flight: no conflict markers in tracked source files"

# --- pipeline (same order as .github/workflows/update-news.yml) ---
log "run: update_news.py"
"$PY" scripts/update_news.py --output-dir data --window-hours 24 \
    --rss-opml feeds/follow.example.opml --custom-opml feeds/custom.opml \
    --archive-days 21 >>"$LOG" 2>&1 || { log "update_news FAILED"; exit 1; }

log "run: arxiv_fetcher.py"
"$PY" scripts/arxiv_fetcher.py --output-dir data --window-hours 24 >>"$LOG" 2>&1 || log "arxiv warn"

log "run: government_fetcher.py"
"$PY" scripts/government_fetcher.py >>"$LOG" 2>&1 || log "gov warn"

log "run: toutiao_fetcher.py"
"$PY" scripts/toutiao_fetcher.py >>"$LOG" 2>&1 || log "toutiao warn"

log "run: curated_collector.py"
"$PY" scripts/curated_collector.py --data-path data/latest-24h-min.json --curated-dir data/curated >>"$LOG" 2>&1 || log "curate warn"

# --- index.html version hash (cache-bust) ---
python - <<'PY' >>"$LOG" 2>&1
import re
from datetime import datetime, timezone
p = 'index.html'
c = open(p, encoding='utf-8').read()
now = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
open(p, 'w', encoding='utf-8').write(re.sub(r'v=[0-9a-f]{8,40}', 'v=' + now, c))
print('index version ->', now)
PY

# --- GUARD: never push empty data (mirrors commit 2ca5f987) ---
N=$(python -c "import json;print(json.load(open('data/latest-24h-min.json',encoding='utf-8'))['total_items'])" 2>/dev/null)
log "GUARD total_items=$N"
if [ "${N:-0}" -eq 0 ]; then
    log "GUARD EMPTY — refusing to push; master keeps its last good snapshot"
    git checkout -- data/latest-24h-min.json 2>/dev/null
    exit 0
fi

# --- commit + push ---
# 2026-10-12: push 前 re-fetch + ff-merge，吸收双写窗口里 Actions 新落的 commit，
# 尽量避免 "! rejected 非 fast-forward"；仍被拒时不再盲目回滚，留 trace。
git add data/ index.html
if git diff --cached --quiet; then
    log "no changes to commit"
    exit 0
fi
git -c user.email="radar-bot@users.noreply.github.com" -c user.name="radar-bot" \
    commit -q -m "[radar-local] data refresh $(date -u '+%Y-%m-%dT%H:%MZ') (Actions disabled, local fallback)" >>"$LOG" 2>&1

git -c http.proxy=http://127.0.0.1:7897 fetch origin master -q 2>>"$LOG" || { log "REFETCH FAILED"; exit 1; }
if ! git merge-base --is-ancestor HEAD origin/master 2>/dev/null; then
    log "re-syncing (Actions landed a commit during our pipeline run)"
    git merge origin/master --no-edit -q >>"$LOG" 2>&1 || { log "RE-SYNC MERGE FAILED"; exit 1; }
    # 同 bug #35：re-sync 也可能冲突，全部取 master 版再校验
    if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
        git checkout --theirs -- $(git diff --name-only --diff-filter=U | tr '\n' ' ') 2>>"$LOG"
        git add $(git diff --name-only --diff-filter=U | tr '\n' ' ') 2>>"$LOG"
        git commit --no-edit -q >>"$LOG" 2>&1 || true
        log "re-sync conflict -> resolved to master's version"
    fi
fi

# 推送前最后一道闸：带冲突标记的 index.html 一律不推（bug #35 回归防护）
if grep -qE '^(<<<<<<<|>>>>>>>|=======)$' index.html 2>/dev/null; then
    log "GUARD CONFLICT MARKERS IN index.html — REFUSING TO PUSH (Pages would show <<<<<<< HEAD)"
    git reset --hard HEAD -q 2>/dev/null
    exit 1
fi
if git -c http.proxy=http://127.0.0.1:7897 push origin master >>"$LOG" 2>&1; then
    log "PUSH OK $(git rev-parse --short HEAD)"
else
    log "PUSH FAILED — leaving commit in place for next run's re-sync"
fi

log "=== local_refresh done ==="

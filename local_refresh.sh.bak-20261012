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
log "=== local_refresh start (last_gen=$LAST age=${AGE_MIN}min) ==="
if [ "${AGE_MIN:-99999}" -lt "$STALE_AFTER_MIN" ]; then
    log "SKIP: data is fresh (<${STALE_AFTER_MIN}min), nothing to do"
    exit 0
fi

# --- sync with master (scripts only; data/ takes master's newer snapshot on conflict) ---
git -c http.proxy=http://127.0.0.1:7897 fetch origin master -q 2>>"$LOG" || { log "FETCH FAILED"; exit 1; }
if ! git merge-base --is-ancestor HEAD origin/master 2>/dev/null; then
    git merge origin/master --no-edit -q >>"$LOG" 2>&1
    if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
        git checkout --theirs data/ && git add data/
        log "merge conflict -> resolved data/ to master's snapshot"
    fi
    git commit --no-edit -q >>"$LOG" 2>&1
fi

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
git add data/ index.html
if git diff --cached --quiet; then
    log "no changes to commit"
    exit 0
fi
git -c user.email="radar-bot@users.noreply.github.com" -c user.name="radar-bot" \
    commit -q -m "[radar-local] data refresh $(date -u '+%Y-%m-%dT%H:%MZ') (Actions disabled, local fallback)" >>"$LOG" 2>&1

git -c http.proxy=http://127.0.0.1:7897 -c http.sslVerify=false push origin master >>"$LOG" 2>&1 \
    && log "PUSH OK $(git rev-parse --short HEAD)" || log "PUSH FAILED"

log "=== local_refresh done ==="

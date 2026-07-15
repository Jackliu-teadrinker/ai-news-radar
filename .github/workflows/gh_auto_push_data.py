#!/usr/bin/env python3
"""Auto-push script for AI News Radar.

Detects actual file changes, pushes them via git or REST API fallback.
NO self-dispatch logic here — watchdog is in a separate workflow
(radar-health-check.yml) with proper cooldown protection.
"""

import json
import os
import subprocess
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path

# --- Configuration ---
REPO = "Jackliu-teadrinker/ai-news-radar"
BRANCH = "master"
DATA_FILES = [
    "data/latest-24h.json",
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
    "index.html",
]
# Jack 2026-06-10 18:58 CST: curated/ directory added by curated_collector.py
# Use git add <dir> to capture all daily files
DATA_DIRS = [
    "data/curated",
]
VERSION_FILE = "data/.radar_version"

# --- Helpers ---
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    r = run(["gh", "auth", "token"])
    return r.stdout.strip() if r.returncode == 0 else None

def git_push():
    """Stage changed data files, commit, then push. The 'nothing to commit' guard prevents empty pushes."""
    # 1. Configure git identity (required for commit on GH Actions runner)
    run(["git", "config", "user.email", "radar-bot@users.noreply.github.com"])
    run(["git", "config", "user.name", "ai-news-radar-bot"])
    # 2. Stage changed data files
    files = changed_files_collector()
    # 2b. Stage all files under DATA_DIRS (curated/ etc.) - directories not in DATA_FILES
    for d in DATA_DIRS:
        if Path(d).exists():
            r = run(["git", "add", d])
            if r.returncode != 0:
                print(f"[PUSH] git add {d} failed: {r.stderr.strip()[:200]}")
                return False
    if not files:
        print("[PUSH] no changed files, skipping commit + push")
        return True
    r = run(["git", "add", "--"] + files)
    if r.returncode != 0:
        print(f"[PUSH] git add failed: {r.stderr.strip()[:200]}")
        return False
    # 3. Check if anything is actually staged
    status_r = run(["git", "diff", "--cached", "--quiet"])
    if status_r.returncode == 0:
        print("[PUSH] nothing staged, skipping commit + push")
        return True
    # 4. Bump version + commit
    version = read_version() + 1
    write_version(version)
    msg = f"[radar-v{version}] Self-healing: data refresh"
    r = run(["git", "commit", "-m", msg])
    if r.returncode == 0:
        print(f"[PUSH] git commit OK: {msg}")
    else:
        print(f"[PUSH] git commit failed: {r.stderr.strip()[:200]}")
        return False
    # 5. Push
    r = run(["git", "push", "origin", BRANCH])
    if r.returncode == 0:
        print("[PUSH] git push OK")
        return True
    print(f"[PUSH] git push failed: {r.stderr.strip()[:200]}")
    return False

def changed_files_collector():
    """Return list of data files that differ from HEAD. Reuses DATA_FILES constant."""
    changed = []
    for f in DATA_FILES:
        if not Path(f).exists():
            continue
        r = run(["git", "diff", "--quiet", "HEAD", "--", f])
        if r.returncode != 0:
            changed.append(f)
    return changed

def rest_api_push(token, changed_files):
    """Fallback: create blob → tree → commit → update ref via REST API."""
    print("[FALLBACK] attempting REST API push...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "radar-auto-push/3.0",
    }
    base = f"https://api.github.com/repos/{REPO}"

    def api(method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
                return r.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception as e:
            return 0, {"error": str(e)}

    # 1. Get current HEAD
    status, ref = api("GET", f"/git/ref/heads/{BRANCH}")
    if status != 200:
        print(f"[FALLBACK] get ref failed: {ref}")
        return False
    head_sha = ref["object"]["sha"]

    # 2. Get current commit's tree
    status, commit = api("GET", f"/git/commits/{head_sha}")
    if status != 200:
        print(f"[FALLBACK] get commit failed: {commit}")
        return False
    base_tree = commit["tree"]["sha"]

    # 3. Create blobs for changed files
    tree_entries = []
    for fpath in changed_files:
        try:
            content_bytes = Path(fpath).read_bytes()
            content_b64 = base64.b64encode(content_bytes).decode("ascii")
        except Exception as e:
            print(f"[FALLBACK] read {fpath} failed: {e}")
            continue
        status, blob = api("POST", "/git/blobs", {"content": content_b64, "encoding": "base64"})
        if status != 201:
            print(f"[FALLBACK] blob for {fpath} failed: {blob}")
            continue
        tree_entries.append({
            "path": fpath,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        print(f"[FALLBACK] blob OK: {fpath} -> {blob['sha'][:12]}")

    if not tree_entries:
        print("[FALLBACK] no blobs created")
        return False

    # 4. Create new tree
    status, tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_entries})
    if status != 201:
        print(f"[FALLBACK] create tree failed: {tree}")
        return False
    print(f"[FALLBACK] tree: {tree['sha'][:12]}")

    # 5. Bump version
    version = read_version() + 1
    write_version(version)

    # 6. Create commit
    status, new_commit = api("POST", "/git/commits", {
        "message": f"[radar-v{version}] Self-healing: data refresh",
        "tree": tree["sha"],
        "parents": [head_sha],
    })
    if status != 201:
        print(f"[FALLBACK] create commit failed: {new_commit}")
        return False
    print(f"[FALLBACK] commit: {new_commit['sha'][:12]}")

    # 7. Update ref
    status, result = api("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": new_commit["sha"]})
    if status != 200:
        print(f"[FALLBACK] update ref failed: {result}")
        return False
    print(f"[FALLBACK] ✅ ref updated to {new_commit['sha'][:12]}")
    return True

def read_version():
    fp = Path(VERSION_FILE)
    if not fp.exists():
        return 0
    try:
        content = fp.read_text(encoding="utf-8").strip()
        try:
            obj = json.loads(content)
            if isinstance(obj, dict):
                return int(obj.get("version", 0))
            return int(obj)
        except json.JSONDecodeError:
            return int(content)
    except Exception:
        return 0

def write_version(v):
    fp = Path(VERSION_FILE)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps({"version": v}, ensure_ascii=False), encoding="utf-8")

# --- Main ---
def main():
    print(f"[INFO] CWD: {os.getcwd()}")
    print(f"[INFO] Repo: {REPO} (branch: {BRANCH})")

    # 1. Detect actual file changes
    changed = []
    for f in DATA_FILES:
        if not Path(f).exists():
            print(f"[SKIP] {f} (not found)")
            continue
        r = run(["git", "diff", "--quiet", "HEAD", "--", f])
        if r.returncode != 0:
            changed.append(f)
            print(f"[CHANGED] {f}")
        else:
            print(f"[SAME]   {f}")

    if not changed:
        print("[INFO] no file changes detected, no push needed")
        return 0

    # 2. Push
    token = get_token()
    if not token:
        print("[FATAL] no GitHub token available")
        return 1

    print(f"[ACTION] {len(changed)} file(s) changed, pushing...")
    if git_push():
        return 0
    if rest_api_push(token, changed):
        return 0
    print("[FATAL] all push methods failed")
    return 2

if __name__ == "__main__":
    sys.exit(main())

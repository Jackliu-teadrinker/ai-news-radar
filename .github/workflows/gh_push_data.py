#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub.
- Uses gh api for GitHub API (authenticated via GH_TOKEN env or gh's default credential)
- Falls back to git add/commit/push with configured git user
- Must be run from repo root.
"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]
HTML_FILE = "index.html"

# Detect repo root (where .git exists)
REPO_ROOT = None
for candidate in [os.path.dirname(os.path.abspath(__file__)),
                  os.getcwd(),
                  os.path.expanduser("~")]:
    if candidate and os.path.exists(os.path.join(candidate, ".git")):
        REPO_ROOT = candidate
        break
if not REPO_ROOT:
    REPO_ROOT = os.getcwd()


def run_git(args, check=True, cwd=None):
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True,
        cwd=cwd or REPO_ROOT
    )
    if check and result.returncode != 0:
        print(f"  git {' '.join(args)} FAILED: {result.stderr[:300]}", file=sys.stderr)
    return result


def get_git_sha():
    result = run_git(["rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else ""


def get_token():
    return os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))


def api_get(path):
    """GET via gh api (uses GH_TOKEN env or default gh credentials)."""
    token = get_token()
    # Use gh api for proper authentication
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}"],
        capture_output=True, text=True,
        cwd=REPO_ROOT
    )
    if result.returncode != 0:
        print(f"  API GET {path}: gh failed", file=sys.stderr)
        return {}
    try:
        return json.loads(result.stdout)
    except:
        return {}


def api_put(path, content, sha, message):
    """PUT via gh api or git commit+push as fallback."""
    token = get_token()

    # Try gh api first
    b64 = base64.b64encode(content).decode("ascii")
    body = json.dumps({"message": message, "content": b64, "sha": sha})
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    tmp.write(body)
    tmp.close()
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/contents/{path}",
             "--method", "PUT", "--input", tmp.name],
            capture_output=True, text=True,
            cwd=REPO_ROOT
        )
        os.unlink(tmp.name)
        if result.returncode == 0:
            resp = json.loads(result.stdout)
            html_url = resp.get("commit", {}).get("html_url", "no url")
            print(f"  OK: {path} -> {html_url}")
            return True
        print(f"  gh API {path} failed: {result.stderr[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"  gh API {path}: {e}", file=sys.stderr)
        try: os.unlink(tmp.name)
        except: pass

    # Fall back to git add/commit/push
    print(f"  Falling back to git for {path}")
    full_path = os.path.join(REPO_ROOT, path)
    dir_path = os.path.dirname(full_path)
    os.makedirs(dir_path, exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(content)

    run_git(["add", path], check=False)
    commit_r = run_git(["commit", "-m", message], check=False)
    if commit_r.returncode != 0:
        if "nothing to commit" in commit_r.stdout:
            print(f"  No change: {path}")
            return True
        print(f"  git commit failed: {commit_r.stderr[:200]}", file=sys.stderr)
        return False

    push_r = run_git(["push"], check=False)
    if push_r.returncode == 0:
        print(f"  OK (git): {path}")
        return True
    print(f"  git push failed: {push_r.stderr[:200]}", file=sys.stderr)
    return False


def update_html_cache_buster(html_content, sha):
    """
    Replace the query string in the app.js <script src="...assets/app.js?v=...">
    to ?sha=<sha> using surgical string replacement.
    """
    if not sha:
        print("  [DEBUG] sha empty, skip")
        return html_content, False

    content_str = html_content.decode("utf-8")

    # Find the script tag context
    idx = content_str.find("assets/app.js")
    if idx < 0:
        print("  [ERROR] assets/app.js not found!")
        return html_content, False

    # Find the src="...assets/app.js?v=..." and replace just the query part
    # Pattern: src="...assets/app.js" followed by ?... and then "
    app_js_in_src = 'assets/app.js'
    old_src_marker = f'src="./{app_js_in_src}?v=20260520t"'

    if old_src_marker in content_str:
        new_src = f'src="./{app_js_in_src}?sha={sha}"'
        new_content = content_str.replace(old_src_marker, new_src)
        changed = new_content != content_str
        if changed:
            print(f"  [DEBUG] Replaced fixed marker: {old_src_marker} -> {new_src}")
        return new_content.encode("utf-8"), changed

    # Generic approach: find src="...assets/app.js[?...]" and replace query
    pattern = r'(src="[^"?]*assets/app\.js)\?[^"]*(")'
    replacement = rf'\1?sha={sha}\2'
    new_content_str, count = re.subn(pattern, replacement, content_str)

    if count > 0:
        changed = new_content_str != content_str
        print(f"  [DEBUG] Generic replace: {count} matches, changed={changed}")
        return new_content_str.encode("utf-8"), changed

    print("  [ERROR] No script tag match found!")
    return html_content, False


def main():
    current_sha = get_git_sha()
    token = get_token()
    print(f"[INFO] git SHA: {current_sha[:8] if current_sha else 'unknown'}")
    print(f"[INFO] GH_TOKEN: {'set' if token else 'NOT set'}")

    # --- HTML cache buster ---
    html_changed = False
    html_path = os.path.join(REPO_ROOT, HTML_FILE)
    if os.path.exists(html_path):
        html_content = open(html_path, "rb").read()
        html_sha = api_get(HTML_FILE).get("sha", "")

        new_html, changed = update_html_cache_buster(html_content, current_sha)
        if changed:
            print(f"[INFO] HTML cache buster: updating (sha={current_sha[:8]})")
            ok = api_put(
                HTML_FILE, new_html, html_sha,
                f"chore: update app.js cache buster to {current_sha[:8]}"
            )
            html_changed = ok
        else:
            print(f"[INFO] HTML cache buster: already current or failed to match")
    else:
        print(f"[WARN] {html_path} not found")

    # --- Data files ---
    pushed_data = []
    for df in DATA_FILES:
        df_path = os.path.join(REPO_ROOT, df)
        if not os.path.exists(df_path):
            print(f"Skip (not found): {df}")
            continue
        content = open(df_path, "rb").read()
        file_info = api_get(df)
        sha = file_info.get("sha", "")
        old_size = file_info.get("size", 0)
        msg = f"Update {df} via workflow $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        if old_size == len(content) and sha:
            print(f"No change: {df} ({len(content)} bytes)")
            continue
        ok = api_put(df, content, sha, msg)
        if ok:
            pushed_data.append(df)

    total = len(pushed_data) + (1 if html_changed else 0)
    print(f"\n{'Updated' if total else 'No change'}: "
          f"{'index.html ' if html_changed else ''}"
          f"{' '.join(pushed_data)}")


if __name__ == "__main__":
    main()

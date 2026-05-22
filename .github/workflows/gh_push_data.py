#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub via raw GitHub API.
Uses GITHUB_TOKEN env var (available in GitHub Actions).
"""
import base64
import json
import os
import re
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
GITHUB_API = "https://api.github.com"


def get_git_sha() -> str:
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def api_get(path: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  API GET {path}: HTTP {e.code}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  API GET {path}: {e}", file=sys.stderr)
        return {}


def api_put(path: str, content: bytes, sha: str, message: str) -> bool:
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    b64 = base64.b64encode(content).decode("ascii")
    body = json.dumps({"message": message, "content": b64, "sha": sha})
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            html_url = result.get("commit", {}).get("html_url", "no url")
            print(f"  OK: {path} -> {html_url}")
            return True
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")
        print(f"  FAILED PUT {path}: HTTP {e.code} - {body_err[:300]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  FAILED PUT {path}: {e}", file=sys.stderr)
        return False


def update_html_cache_buster(html_content: bytes, sha: str) -> tuple[bytes, bool]:
    """Replace/update cache-buster query in app.js script src URL."""
    if not sha:
        print("  [DEBUG] sha is empty, skipping")
        return html_content, False

    content_str = html_content.decode("utf-8")

    # Show what we're searching for
    app_js_idx = content_str.find("assets/app.js")
    if app_js_idx < 0:
        print("  [DEBUG] 'assets/app.js' NOT FOUND in HTML!")
        return html_content, False

    snippet = content_str[max(0, app_js_idx-50):app_js_idx+80]
    print(f"  [DEBUG] Found 'assets/app.js' at offset {app_js_idx}")
    print(f"  [DEBUG] Context: {repr(snippet)}")

    def replace_src(match):
        tag = match.group(0)
        new_tag = re.sub(
            r'(src="[^"?]*assets/app\.js)(?:\?[^"]*)?(")',
            rf'\1?sha={sha}\2',
            tag
        )
        print(f"  [DEBUG] Replace: {repr(tag)} -> {repr(new_tag)}")
        return new_tag

    pattern = r'<script[^>]+src="[^"]*assets/app\.js[^"]*"[^>]*>'
    new_content_str, count = re.subn(pattern, replace_src, content_str)

    if count == 0:
        # Try simpler pattern
        pattern2 = r'<script[^>]*src="[^"]*assets/app\.js"[^>]*>'
        new_content_str, count2 = re.subn(pattern2, replace_src, content_str)
        print(f"  [DEBUG] Pattern2 matched {count2} times")
        if count2 == 0:
            print("  [DEBUG] Neither pattern matched!")
            return html_content, False

    changed = new_content_str != content_str
    print(f"  [DEBUG] Changed: {changed}, count: {count + count2}")
    return new_content_str.encode("utf-8"), changed


def main():
    current_sha = get_git_sha()
    token = os.environ.get("GITHUB_TOKEN", "")
    print(f"[DEBUG] GITHUB_TOKEN set: {bool(token)}")
    print(f"[DEBUG] GITHUB_TOKEN prefix: {token[:4] if token else 'EMPTY'}...")
    print(f"[DEBUG] Current git SHA: {current_sha[:8] if current_sha else 'unknown'}")

    # --- HTML cache buster ---
    html_changed = False
    if os.path.exists(HTML_FILE):
        html_content = open(HTML_FILE, "rb").read()
        print(f"[DEBUG] index.html size: {len(html_content)} bytes")
        html_info = api_get(HTML_FILE)
        html_sha = html_info.get("sha", "")
        print(f"[DEBUG] index.html sha on GitHub: {html_sha[:8] if html_sha else 'unknown'}")

        new_html, changed = update_html_cache_buster(html_content, current_sha)
        if changed:
            print(f"HTML cache buster: UPDATE needed (sha={current_sha[:8]})")
            ok = api_put(
                HTML_FILE, new_html, html_sha,
                f"chore: update app.js cache buster to {current_sha[:8]}"
            )
            html_changed = ok
            if not ok:
                print("  [ERROR] HTML API put returned False!")
        else:
            print("HTML cache buster: already current — skip")
    else:
        print(f"index.html not found locally — skip")

    # --- Data files ---
    pushed_data = []
    for df in DATA_FILES:
        if not os.path.exists(df):
            print(f"Skip (not found): {df}")
            continue
        content = open(df, "rb").read()
        file_info = api_get(df)
        sha = file_info.get("sha", "")
        msg = f"Update {df} via workflow $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        old_size = file_info.get("size", 0)
        if old_size == len(content) and sha:
            print(f"No change: {df} ({len(content)} bytes)")
            continue
        print(f"Push: {df} ({len(content)} bytes)")
        ok = api_put(df, content, sha, msg)
        if ok:
            pushed_data.append(df)

    total_changed = len(pushed_data) + (1 if html_changed else 0)
    if total_changed:
        what = ["index.html" if html_changed else ""] + pushed_data
        print(f"\nUpdated {total_changed} file(s): {', '.join(w for w in what if w)}")
    else:
        print("\nNo files changed")


if __name__ == "__main__":
    main()

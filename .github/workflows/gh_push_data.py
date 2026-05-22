#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub via raw GitHub API.
Uses GITHUB_TOKEN env var (available in GitHub Actions).
- Reads current git SHA and uses it as cache buster in index.html src URL
- Only pushes index.html if the SHA actually changed (idempotent)
"""
import base64
import json
import os
import re
import sys
import urllib.request

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]
HTML_FILE = "index.html"
GITHUB_API = "https://api.github.com"


def get_git_sha() -> str:
    """Get current HEAD commit SHA via git command."""
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def api_get(path: str) -> dict:
    """GET /repos/{owner}/{repo}/contents/{path}"""
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API GET failed for {path}: {e}", file=sys.stderr)
        return {}


def api_put(path: str, content: bytes, sha: str, message: str) -> bool:
    """PUT /repos/{owner}/{repo}/contents/{path}"""
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
        print(f"  FAILED: {path}: HTTP {e.code} - {body_err[:300]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  FAILED: {path}: {e}", file=sys.stderr)
        return False


def update_html_cache_buster(html_content: bytes, sha: str) -> tuple[bytes, bool]:
    """
    Replace/update the cache-buster query in the app.js <script src> URL.
    Sets ?sha=<sha> in the src attribute.
    Returns (new_content, changed).
    """
    if not sha:
        return html_content, False

    content_str = html_content.decode("utf-8")

    def replace_src(match):
        tag = match.group(0)
        # Replace existing query (?v=...) with ?sha=<sha>
        new_tag = re.sub(
            r'(src="[^"?]*assets/app\.js)(?:\?[^"]*)?(")',
            rf'\1?sha={sha}\2',
            tag
        )
        return new_tag

    pattern = r'<script[^>]+src="[^"]*assets/app\.js[^"]*"[^>]*>'
    new_content_str, count = re.subn(pattern, replace_src, content_str)

    if count == 0:
        print(f"  WARNING: could not find app.js script tag in index.html", file=sys.stderr)
        return html_content, False

    changed = new_content_str != content_str
    return new_content_str.encode("utf-8"), changed


def main():
    current_sha = get_git_sha()
    print(f"Current git SHA: {current_sha[:8] if current_sha else 'unknown'}")
    has_token = bool(os.environ.get("GITHUB_TOKEN", ""))
    print(f"GITHUB_TOKEN available: {has_token}")

    # --- HTML cache buster (push only if SHA changed) ---
    html_changed = False
    if os.path.exists(HTML_FILE):
        html_content = open(HTML_FILE, "rb").read()
        html_info = api_get(HTML_FILE)
        html_sha = html_info.get("sha", "")

        new_html, changed = update_html_cache_buster(html_content, current_sha)
        if changed:
            print(f"HTML cache buster update needed (sha={current_sha[:8]})")
            ok = api_put(
                HTML_FILE, new_html, html_sha,
                f"chore: update app.js cache buster to {current_sha[:8]}"
            )
            html_changed = ok
        else:
            print(f"HTML cache buster already current — skip")
    else:
        print(f"index.html not found locally — skip HTML update")

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

        print(f"Push: {df} ({len(content)} bytes, sha={sha[:8] if sha else 'new'})")
        ok = api_put(df, content, sha, msg)
        if ok:
            pushed_data.append(df)

    total_changed = len(pushed_data) + (1 if html_changed else 0)
    if total_changed:
        what = ["index.html" if html_changed else ""] + pushed_data
        print(f"\nUpdated {total_changed} file(s): {', '.join(w for w in what if w)}")
    else:
        print("\nNo files changed — nothing to push")


if __name__ == "__main__":
    main()

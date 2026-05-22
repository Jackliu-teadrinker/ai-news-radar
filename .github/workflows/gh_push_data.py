#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub via GitHub API.
- Reads current git SHA and injects it as cache buster in index.html
- Only pushes index.html if the SHA changed (idempotent)
- Bypasses git push TLS issues by using gh api.
Must be run from the repo root (where .git exists).
"""
import subprocess
import base64
import json
import os
import sys
import re
import tempfile

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]
HTML_FILE = "index.html"
CACHE_BUSTER_ATTR = "data-app-sha"   # attribute name in HTML tag


def get_git_sha() -> str:
    """Get current HEAD commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def gh_get(path: str) -> dict:
    """GET /repos/{owner}/{repo}/contents/{path}"""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout)


def gh_put(path: str, content: bytes, sha: str, message: str) -> bool:
    """PUT /repos/{owner}/{repo}/contents/{path} via gh api."""
    b64 = base64.b64encode(content).decode("ascii")
    body = json.dumps({"message": message, "content": b64, "sha": sha})
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(body)
        tmp = f.name
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/contents/{path}",
             "--method", "PUT", "--input", tmp],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  FAILED: {result.stderr[:200]}", file=sys.stderr)
            return False
        resp = json.loads(result.stdout)
        print(f"  OK: {path} -> {resp.get('commit', {}).get('html_url', 'no url')}")
        return True
    finally:
        os.unlink(tmp)


def update_html_cache_buster(html_content: bytes, sha: str) -> tuple[bytes, bool]:
    """
    Inject/update data-app-sha attribute in the <script src="assets/app.js"> tag.
    Returns (new_content, changed).
    If sha is empty, returns unchanged content.
    """
    if not sha:
        return html_content, False

    content_str = html_content.decode("utf-8")
    sha_attr = f'{CACHE_BUSTER_ATTR}="{sha}"'

    # Pattern: <script src="assets/app.js" ...>
    # We need to add/update data-app-sha in that tag
    pattern = r'(<script\s+[^>]*src="[^"]*assets/app\.js"[^>]*)'
    replacement = rf'\1 {sha_attr}'

    new_content_str, count = re.subn(pattern, replacement, content_str)
    if count == 0:
        # Try alternate: script tag might not have other attrs
        pattern2 = r'(<script\s+src="[^"]*assets/app\.js")(\s*>)'
        replacement2 = rf'\1 {sha_attr}\2'
        new_content_str, count2 = re.subn(pattern2, replacement2, content_str)
        if count2 == 0:
            print(f"  WARNING: could not find app.js script tag in index.html", file=sys.stderr)
            return html_content, False

    changed = (new_content_str != content_str)
    return new_content_str.encode("utf-8"), changed


def main():
    current_sha = get_git_sha()
    print(f"Current git SHA: {current_sha[:8] if current_sha else 'unknown'}")

    # --- HTML cache buster ---
    html_changed = False
    if os.path.exists(HTML_FILE):
        html_content = open(HTML_FILE, "rb").read()
        html_info = gh_get(HTML_FILE)
        html_sha = html_info.get("sha", "")

        new_html, changed = update_html_cache_buster(html_content, current_sha)
        if changed:
            print(f"HTML cache buster update needed (sha={current_sha[:8]})")
            ok = gh_put(HTML_FILE, new_html, html_sha,
                        f"chore: update HTML cache buster to {current_sha[:8]}")
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
        file_info = gh_get(df)
        sha = file_info.get("sha", "")
        msg = f"Update {df} via workflow $(date -u +'%Y-%m-%dT%H:%M:%SZ')"

        old_size = file_info.get("size", 0)
        if old_size == len(content) and sha:
            print(f"No change: {df} ({len(content)} bytes)")
            continue

        print(f"Push: {df} ({len(content)} bytes, sha={sha[:8] if sha else 'new'})")
        ok = gh_put(df, content, sha, msg)
        if ok:
            pushed_data.append(df)

    total_changed = len(pushed_data) + (1 if html_changed else 0)
    if total_changed:
        print(f"\nUpdated {total_changed} file(s): "
              f"{'index.html ' if html_changed else ''}"
              f"{' '.join(pushed_data)}")
    else:
        print("\nNo files changed — nothing to push")


if __name__ == "__main__":
    main()

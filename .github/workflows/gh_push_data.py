#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub via git push.
Uses git credential helper configured by actions/checkout (GITHUB_TOKEN via git config).
- Reads current git SHA and uses it as cache buster in index.html src URL
- Only pushes index.html if the SHA actually changed (idempotent)
Must be run from the repo root (where .git exists).
"""
import base64
import json
import os
import re
import subprocess
import sys

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]
HTML_FILE = "index.html"


def run_git(args: list, check=True) -> subprocess.CompletedProcess:
    """Run a git command, return CompletedProcess."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)) or "."
    )
    if check and result.returncode != 0:
        print(f"  git {' '.join(args)} FAILED: {result.stderr[:200]}", file=sys.stderr)
    return result


def get_git_sha() -> str:
    """Get current HEAD commit SHA."""
    result = run_git(["rev-parse", "HEAD"])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_gh_token() -> str:
    """Try to get GitHub token from git credential or env."""
    # Try git credential
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="url=https://github.com\n",
        capture_output=True, text=True
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line.startswith("password="):
                return line[9:]
    # Fall back to env
    return os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))


def api_get(path: str) -> dict:
    """GET /repos/{owner}/{repo}/contents/{path} via GitHub API."""
    token = get_gh_token()
    if not token:
        print("  [WARN] No GitHub token available for API calls", file=sys.stderr)
        return {}

    import urllib.request
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API GET {path}: {e}", file=sys.stderr)
        return {}


def api_put(path: str, content: bytes, sha: str, message: str) -> bool:
    """PUT via GitHub API using curl (git credential-helper aware)."""
    token = get_gh_token()
    if not token:
        print("  [WARN] No token for API, trying git push instead", file=sys.stderr)
        return False

    import urllib.request
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    b64 = base64.b64encode(content).decode("ascii")
    body = json.dumps({"message": message, "content": b64, "sha": sha})

    import tempfile
    body_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    body_file.write(body)
    body_file.close()

    curl_cmd = [
        "curl", "-s", "-X", "PUT",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "Content-Type: application/json",
        "-d", f"@{body_file.name}",
        url
    ]
    try:
        result = subprocess.run(curl_cmd, capture_output=True, text=True)
        os.unlink(body_file.name)
        if result.returncode != 0:
            print(f"  curl FAILED: {result.stderr[:200]}", file=sys.stderr)
            return False
        resp = json.loads(result.stdout)
        html_url = resp.get("commit", {}).get("html_url", "no url")
        print(f"  OK: {path} -> {html_url}")
        return True
    except Exception as e:
        print(f"  API PUT {path}: {e}", file=sys.stderr)
        try: os.unlink(body_file.name)
        except: pass
        return False


def update_html_cache_buster(html_content: bytes, sha: str) -> tuple[bytes, bool]:
    """Replace/update cache-buster query in app.js <script src> URL."""
    if not sha:
        print("  [DEBUG] sha is empty, skip")
        return html_content, False

    content_str = html_content.decode("utf-8")

    # Find assets/app.js context
    app_js_idx = content_str.find("assets/app.js")
    if app_js_idx < 0:
        print("  [ERROR] 'assets/app.js' NOT FOUND in HTML!")
        return html_content, False

    print(f"  [DEBUG] Found 'assets/app.js' at offset {app_js_idx}")

    def replace_src(match):
        tag = match.group(0)
        new_tag = re.sub(
            r'(src="[^"?]*assets/app\.js)(?:\?[^"]*)?(")',
            rf'\1?sha={sha}\2',
            tag
        )
        if new_tag != tag:
            print(f"  [DEBUG] Replaced: {repr(tag[-60:])} -> {repr(new_tag[-60:])}")
        return new_tag

    # Match <script ... src="...assets/app.js..." ... >
    pattern = r'<script[^>]+src="[^"]*assets/app\.js[^"]*"[^>]*>'
    new_content_str, count = re.subn(pattern, replace_src, content_str)

    if count == 0:
        print("  [ERROR] No script tag matched!")
        return html_content, False

    changed = new_content_str != content_str
    print(f"  [DEBUG] Changed={changed}, matched={count}")
    return new_content_str.encode("utf-8"), changed


def main():
    current_sha = get_git_sha()
    has_token = bool(get_gh_token())
    print(f"[INFO] git SHA: {current_sha[:8] if current_sha else 'unknown'}")
    print(f"[INFO] GitHub token: {'available (' + get_gh_token()[:4] + '...)' if has_token else 'NOT available'}")

    # --- HTML cache buster ---
    html_changed = False
    if os.path.exists(HTML_FILE):
        html_content = open(HTML_FILE, "rb").read()
        html_info = api_get(HTML_FILE)
        html_sha = html_info.get("sha", "")

        new_html, changed = update_html_cache_buster(html_content, current_sha)
        if changed:
            print(f"[INFO] HTML cache buster update needed (sha={current_sha[:8]})")
            ok = api_put(
                HTML_FILE, new_html, html_sha,
                f"chore: update app.js cache buster to {current_sha[:8]}"
            )
            html_changed = ok
            if not ok:
                print("  [WARN] HTML API put failed — trying git add/commit/push")
                # Write updated HTML locally
                open(HTML_FILE, "wb").write(new_html)
                run_git(["add", HTML_FILE])
                commit_result = run_git(["commit", "-m", f"chore: update app.js cache buster to {current_sha[:8]}"])
                if commit_result.returncode == 0:
                    push_result = run_git(["push"])
                    if push_result.returncode == 0:
                        print(f"  [OK] HTML pushed via git push")
                        html_changed = True
                    else:
                        print(f"  [FAIL] git push failed: {push_result.stderr[:200]}")
                else:
                    print(f"  [FAIL] git commit failed: {commit_result.stderr[:200]}")
        else:
            print(f"[INFO] HTML cache buster already current — skip")
    else:
        print(f"[WARN] index.html not found locally")

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
        ok = api_put(df, content, sha, msg)
        if ok:
            pushed_data.append(df)
        else:
            # Fall back to git add/commit/push
            run_git(["add", df])
            commit_r = run_git(["commit", "-m", msg])
            if commit_r.returncode == 0:
                push_r = run_git(["push"])
                if push_r.returncode == 0:
                    print(f"  [OK] {df} pushed via git push")
                    pushed_data.append(df)
                else:
                    print(f"  [FAIL] git push {df}: {push_r.stderr[:200]}")
            else:
                print(f"  [FAIL] git commit {df}: {commit_r.stderr[:200]}")

    total_changed = len(pushed_data) + (1 if html_changed else 0)
    if total_changed:
        print(f"\nUpdated {total_changed} file(s)")
    else:
        print("\nNo files changed")


if __name__ == "__main__":
    main()

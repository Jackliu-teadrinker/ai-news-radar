#!/usr/bin/env python3
"""
Push data files to GitHub via GitHub API (bypasses git push TLS issues).
Must be run from the repo root (where .git exists).
"""
import subprocess
import base64
import json
import os
import sys

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]


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
    """PUT /repos/{owner}/{repo}/contents/{path}"""
    b64 = base64.b64encode(content).decode("ascii")
    body = json.dumps({"message": message, "content": b64, "sha": sha})
    # Write body to temp file to avoid shell escaping issues
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(body)
        tmp = f.name
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/contents/{path}", "--method", "PUT", "--input", tmp],
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


def main():
    changed = []
    for df in DATA_FILES:
        if not os.path.exists(df):
            print(f"Skip (not found): {df}")
            continue

        content = open(df, "rb").read()
        file_info = gh_get(df)
        sha = file_info.get("sha", "")
        msg = f"Update {df} via workflow $(date -u +'%Y-%m-%dT%H:%M:%SZ')"

        # Check if content changed by comparing size
        old_size = file_info.get("size", 0)
        if old_size == len(content) and sha:
            print(f"No change: {df} ({len(content)} bytes)")
            continue

        print(f"Push: {df} ({len(content)} bytes, sha={sha[:8] if sha else 'new'})")
        ok = gh_put(df, content, sha, msg)
        if ok:
            changed.append(df)

    if changed:
        print(f"\nUpdated {len(changed)} files: {', '.join(changed)}")
    else:
        print("\nNo files changed — nothing to push")


if __name__ == "__main__":
    main()

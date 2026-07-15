#!/usr/bin/env python3
"""Update the version hash in index.html's app.js script tag.

This ensures browsers always fetch the latest app.js, preventing stale UI bugs.
The version hash is based on the current UTC timestamp.
"""
import re
import sys
from datetime import datetime, timezone

INDEX_HTML = "index.html"

def main():
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    new_version = f"v={now}"

    # Replace the version in the script tag: <script src="./assets/app.js?v=...">
    pattern = r'<script\s+src="\./assets/app\.js\?v=[^"]*"'
    match = re.search(pattern, content)
    if not match:
        print(f"[WARN] No app.js script tag found in {INDEX_HTML}")
        sys.exit(0)

    old = match.group(0)
    new = re.sub(r'\?v=\d+', f'?v={now}', old)
    content = content.replace(old, new)

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[UPDATE] index.html version: {new_version}")

if __name__ == "__main__":
    main()

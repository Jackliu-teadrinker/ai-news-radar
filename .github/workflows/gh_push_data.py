#!/usr/bin/env python3
"""
Push data files + HTML cache buster to GitHub via GIT (not gh api).
===============================================================
所有更新通过git add/commit/push完成，彻底消除gh api游离blob问题。

用法：python gh_push_data.py
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime

REPO = "jackliu-teadrinker/ai-news-radar"
DATA_FILES = [
    "data/latest-24h-min.json",
    "data/latest-24h-all.json",
    "data/source-status.json",
]
HTML_FILE = "index.html"
APP_JS_FILE = "assets/app.js"

# 全局版本计数器文件（也存git）
VERSION_FILE = ".radar_version"

# Detect repo root (where .git exists)
REPO_ROOT = None
for candidate in [os.path.dirname(os.path.abspath(__file__)),
                  os.getcwd()]:
    candidate = os.path.abspath(candidate)
    if os.path.exists(os.path.join(candidate, ".git")):
        REPO_ROOT = candidate
        break
if not REPO_ROOT:
    REPO_ROOT = os.getcwd()


def run_git(args, check=True, cwd=None, env=None):
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True,
        cwd=cwd or REPO_ROOT, env=full_env
    )
    for line in result.stdout.strip().split('\n'):
        if line.strip():
            print(f"  git {' '.join(args)}: {line}")
    if check and result.returncode != 0:
        print(f"  git {' '.join(args)} FAILED: {result.stderr[:300]}", file=sys.stderr)
    return result


def get_current_version():
    """读取当前版本号（从VERSION_FILE）"""
    vf = os.path.join(REPO_ROOT, VERSION_FILE)
    if os.path.exists(vf):
        try:
            return int(open(vf).read().strip())
        except:
            pass
    return 0


def bump_version():
    """递增版本号，写入VERSION_FILE，git commit"""
    ver = get_current_version() + 1
    vf = os.path.join(REPO_ROOT, VERSION_FILE)
    with open(vf, "w") as f:
        f.write(str(ver))
    print(f"  [VERSION] bumped to {ver}")
    return ver


def get_app_js_sha():
    """获取app.js的git blob SHA"""
    result = run_git(["ls-files", "-s", APP_JS_FILE], check=False, cwd=REPO_ROOT)
    if result.returncode == 0:
        # output: "0 <sha> <stage> <path>"
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            return parts[1]
    return None


def update_html_version(html_content, version):
    """
    替换 index.html 中的 app.js 版本号为新的版本号。
    兼容旧格式: ?sha=XXX 或 ?v=N
    """
    content_str = html_content.decode("utf-8") if isinstance(html_content, bytes) else html_content
    
    # 新格式: app.js?v=123
    new_marker = f'app.js?v={version}"'
    
    # 替换所有变体: ?sha=XXX, ?v=N, 各种长度
    # 找 assets/app.js 所在的 script src 行
    pattern = r'(src="[^"]*assets/app\.js)\?[^"]*(")'
    
    def replacer(m):
        return m.group(1) + '?' + f'v={version}' + m.group(2)
    
    new_content, count = re.subn(pattern, replacer, content_str)
    
    if count > 0:
        print(f"  [HTML] Updated app.js version marker {count}处 -> v={version}")
        return new_content.encode("utf-8") if isinstance(html_content, bytes) else new_content
    else:
        # 找不到？尝试直接追加
        print(f"  [HTML] 未找到 app.js marker，尝试直接在assets/app.js后加?v=")
        new_content = content_str.replace(
            'assets/app.js"', f'assets/app.js?v={version}"'
        )
        if new_content != content_str:
            print(f"  [HTML] 直接追加版本号成功")
            return new_content.encode("utf-8") if isinstance(html_content, bytes) else new_content
        print(f"  [HTML] 警告: 无法更新版本号")
        return html_content


def main():
    print(f"[RADAR] gh_push_data.py (git-only mode)")
    print(f"[INFO] Repo root: {REPO_ROOT}")
    
    # 1. Bump 版本号
    new_version = bump_version()
    
    # 2. 更新 index.html 的 app.js 版本引用
    html_path = os.path.join(REPO_ROOT, HTML_FILE)
    if os.path.exists(html_path):
        html_content = open(html_path, "rb").read()
        new_html = update_html_version(html_content, new_version)
        with open(html_path, "wb") as f:
            f.write(new_html)
        print(f"  [OK] {HTML_FILE} updated with v={new_version}")
    else:
        print(f"  [WARN] {HTML_FILE} not found")
    
    # 3. git add + commit + push (统一commit，包含所有变更)
    run_git(["add", "-A"], cwd=REPO_ROOT)
    
    # 检查是否有变更
    diff = run_git(["diff", "--cached", "--stat"], check=False, cwd=REPO_ROOT)
    if not diff.stdout.strip():
        print(f"[INFO] No changes to commit")
        return
    
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"chore: radar update v{new_version} ({ts})"
    run_git(["commit", "-m", msg], cwd=REPO_ROOT)
    
    push = run_git(["push"], cwd=REPO_ROOT)
    if push.returncode == 0:
        print(f"[+] Pushed: {msg}")
    else:
        print(f"[!] Push failed: {push.stderr[:200]}")
    
    # 4. Data files (已有workflow step commit，这里仅记录)
    for df in DATA_FILES:
        df_path = os.path.join(REPO_ROOT, df)
        if os.path.exists(df_path):
            size = os.path.getsize(df_path)
            print(f"  [DATA] {df}: {size} bytes")

    print(f"\n[OK] Done! app.js version = v={new_version}")


if __name__ == "__main__":
    main()

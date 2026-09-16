#!/usr/bin/env python3
"""
微信公众号文章采集器 v2 — 集成 wechat-article-claw

功能：
  1. 通过 Exa MCP 搜索微信公众号文章（site:mp.weixin.qq.com）
  2. 使用 wechat-fetch.py 抓取文章正文，过滤无关内容
  3. 合并用户手动提供的文章列表（wechat-manual.json）
  4. 输出标准化格式，接入 update_news.py pipeline

用法：
  python wechat-collector-v2.py --manual                    # 只加载手动文章
  python wechat-collector-v2.py --search "具身智能"          # 搜索 + 手动
  python wechat-collector-v2.py --all                       # 全量搜索 + 手动
  python wechat-collector-v2.py --output wechat-out.json    # 输出到文件
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

DEFAULT_KEYWORDS = [
    "具身智能", "机器人", "人形机器人", "脑机接口",
    "Physical AI", "embodied AI", "humanoid robot", "AI 机器人",
]

RELEVANCE_KEYWORDS = [
    "机器人", "人形", "具身", "AI", "人工智能", "智能", "机械",
    "brain-computer", "BCI", "脑机", "肢体", "操控", "运动",
    "humanoid", "embodied", "physical AI", "robotics", "robot",
    "Tesla", "Optimus", "Figure", "Unitree", "宇树", "智元",
    "Boston Dynamics", "波士顿动力", "Atlas", "G1", "H1",
    "小米", "CyberDog", "铁蛋", "Iron",
]

# 2026-09-16: Jack 要展示"主要是采集 8 个机器人/具身关键词命中的文章"。
# 命中这 8 个词的公众号文章优先展示（排前面、给更高 relevance），
# 其余 AI HOT 的纯 AI 模型类公众号文（无机器人信号）作为补充。
ROBOT_KEYWORDS = [
    "具身智能", "机器人", "人形机器人", "脑机接口",
    "Physical AI", "embodied AI", "humanoid robot", "AI 机器人",
]


def robot_signal(text: str) -> int:
    """标题+摘要命中机器人/具身关键词的个数（用于展示排序与 relevance 加权）。"""
    blob = (text or "").lower()
    n = 0
    for kw in ROBOT_KEYWORDS:
        if kw.lower() in blob:
            n += 1
    return n

# ── AI HOT 聚合源（公众号文章抓取） ─────────────────────────────
# 参考 LearnPrompt/ai-news-radar：AI HOT 聚合 API 会把各 AI 公众号文章
# 转成带标题+摘要+publishedAt 的 mp.weixin.qq.com 链接，已做 AI 相关性
# 打分（score≥60 才 selected），比直接爬微信稳定得多。
AIHOT_API_BASE = "https://aihot.virxact.com/api/public/items"
AIHOT_UA = "Mozilla/5.0 (compatible; AI-News-Radar/1.0)"
AIHOT_TAKE = 100          # 单页条数
AIHOT_MAX_PAGES = 2       # 2 页 = 200 条缓冲（窗口由 MAX_AGE 收窄，多页只为拿到足够候选）
AIHOT_MIN_SCORE = 60      # 只收 AI HOT 自己筛选过的（与参考库一致）
# 2026-09-16: Jack 要"只要最近 1 天"，不收 5~7 天旧文。
# 收窄到 1 天；多拉 2 页做缓冲，保证当天文章拉全（拉多了由时间窗过滤掉）。
AIHOT_MAX_AGE_DAYS = 1    # 只收最近 1 天的公众号文章


def fetch_aihot_wechat() -> list[dict]:
    """拉取 AI HOT 聚合的 AI 公众号文章（参考 LearnPrompt/ai-news-radar 方案）。

    返回与 search_wechat_via_exa 兼容的 dict 列表：
      {title, url, publishedAt, snippet, source}
    失败（网络/4xx/5xx/空）返回 []，绝不抛异常中断主流程。
    """
    import urllib.request
    import urllib.parse

    results = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=AIHOT_MAX_AGE_DAYS)
    cursor = ""
    for _page in range(AIHOT_MAX_PAGES):
        params = {"mode": "selected", "take": str(AIHOT_TAKE)}
        if cursor:
            params["cursor"] = cursor
        url = f"{AIHOT_API_BASE}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": AIHOT_UA, "Accept": "application/json"},
            )
            payload = json.loads(urllib.request.urlopen(req, timeout=25).read())
        except Exception as e:
            print(f"[AIHOT] 拉取失败 (page): {e}")
            break
        items = payload.get("items", [])
        if not items:
            break
        for it in items:
            try:
                score = float(it.get("score") or 0)
                if score < AIHOT_MIN_SCORE:
                    continue
                raw_src = str(it.get("source", "")).strip()
                # 只收 AI 公众号文章（source 形如 "公众号：XXX"），排除 X/HN/RSS
                if "公众号" not in raw_src:
                    continue
                pub_raw = str(it.get("publishedAt") or "")
                if not pub_raw:
                    continue
                pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                if pub_dt < cutoff:
                    continue
                title = str(it.get("title") or "").strip()
                link = str(it.get("url") or "").strip()
                if not title or not link:
                    continue
                # source 去掉 "公众号：" 前缀，只留账号名（前端显示更干净）
                account = raw_src.replace("公众号：", "").replace("公众号:", "").strip()
                snippet = str(it.get("summary") or "")[:500]
                results.append({
                    "title": title,
                    "url": link,
                    "publishedAt": pub_dt.isoformat(),
                    "snippet": snippet,
                    "source": f"公众号：{account}" if account else raw_src,
                    # 机器人/具身信号数（标题+摘要），>0 优先展示
                    "robot_hits": robot_signal(title + " " + snippet),
                })
            except Exception:
                continue
        if not payload.get("hasNext") or not payload.get("nextCursor"):
            break
        cursor = str(payload.get("nextCursor") or "")
    n_robot = sum(1 for r in results if r.get("robot_hits", 0) > 0)
    print(f"[AIHOT] 拉到 {len(results)} 篇 AI 公众号文章（最近 {AIHOT_MAX_AGE_DAYS} 天，score≥{AIHOT_MIN_SCORE}，其中机器人/具身命中 {n_robot} 篇）")
    return results


def sha1_short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_wechat_time(published_str: str) -> str:
    if not published_str:
        return now_iso()
    s = published_str.strip()
    # ISO-8601 带 T（AI HOT API 返回 "2026-09-15T14:30:59+00:00"）
    if "T" in s:
        try:
            return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        if " " in s:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(s, "%Y-%m-%d")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return now_iso()


def _parse_exa_text(text: str) -> list[dict]:
    """解析 Exa web_search_exa 返回的纯文本块（Title:/URL:/Published:/Highlights:）。

    抽出来在正常字符串里解析，避免内嵌子进程脚本的 \\n 转义陷阱
    （多层 f-string 里 \\\\n 会被渲染成字面量反斜杠+n，split 切不开 SSE 行）。
    """
    import re as _re
    out = []
    if not text:
        return out
    blocks = _re.split(r"(?m)^Title:\s*", text)
    for b in blocks[1:]:
        lines = b.strip().split("\n")
        title = lines[0].strip()
        url = ""
        published = ""
        highlights = ""
        for ln in lines[1:]:
            ls = ln.strip()
            low = ls.lower()
            if low.startswith("url:"):
                url = ls[4:].strip()
            elif low.startswith("published:"):
                published = ls[10:].strip()
            elif low.startswith("highlights:"):
                highlights = ls[11:].strip()
        if title and url and url.startswith("http"):
            out.append({
                "title": title,
                "url": url,
                "publishedAt": published if published not in ("", "N/A") else "",
                "snippet": (highlights or title)[:300],
            })
    return out


def search_wechat_via_exa(keyword: str, max_results: int = 20) -> list[dict]:
    """通过 Exa MCP 搜索微信公众号文章.

    2026-09-16: 重写。子进程只负责调 Exa API 并把 result.content[0].text
    原样打印出来（一行 base64 编码防换行），外层 _parse_exa_text 解析。
    旧版在内嵌 f-string 里用 \\\\n 切分 SSE，多层转义后变成字面量，永远切不开 → 0 篇。
    """
    results = []
    try:
        # 内嵌脚本用占位符，普通字符串拼接（避免 f-string 嵌套花括号转义地狱）
        _script = (
            "import requests, json, sys, base64\n"
            'EXA_MCP_URL = "https://mcp.exa.ai/mcp"\n'
            'payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",\n'
            '    "params": {"name": "web_search_exa",\n'
            '        "arguments": {"query": "site:mp.weixin.qq.com __KW__", "numResults": __NR__}}}\n'
            'headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}\n'
            'r = requests.post(EXA_MCP_URL, json=payload, headers=headers, timeout=45)\n'
            'r.raise_for_status()\n'
            'text = r.content.decode("utf-8", errors="replace").strip()\n'
            "res = None\n"
            'for line in text.split("\\n"):\n'
            '    if line.startswith("data: "):\n'
            '        d = json.loads(line[6:])\n'
            '        if "error" in d:\n'
            '            print("EXA_ERROR:" + json.dumps(d["error"], ensure_ascii=False)); sys.exit(0)\n'
            '        res = d.get("result", {}); break\n'
            "if res is None:\n"
            '    print("EXA_EMPTY"); sys.exit(0)\n'
            'c = res.get("content") or []\n'
            'blob = c[0].get("text", "") if c and isinstance(c[0], dict) else ""\n'
            'print("EXA_B64:" + base64.b64encode(blob.encode("utf-8")).decode("ascii"))\n'
        ).replace("__KW__", keyword).replace("__NR__", str(max_results))
        result = subprocess.run(
            ["python", "-c", _script],
            capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace"
        )
        for line in (result.stdout or "").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("EXA_ERROR:"):
                print(f"[WECHAT] Exa error for {keyword}: {line[10:]}")
                continue
            if line.startswith("EXA_EMPTY"):
                continue
            if line.startswith("EXA_B64:"):
                import base64 as _b64
                blob = _b64.b64decode(line[8:]).decode("utf-8", errors="replace")
                results.extend(_parse_exa_text(blob))
    except Exception as e:
        print(f"[WECHAT] Exa MCP 搜索失败 {keyword}: {e}")
    return results


def fetch_and_filter_wechat_article(url: str) -> Optional[dict]:
    """使用 wechat-fetch.py 抓取正文并过滤无关内容."""
    try:
        wechat_fetch_paths = [
            Path.home() / ".hermes" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
            Path.home() / ".openclaw" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
            Path.home() / "AppData" / "Local" / "hermes" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
        ]
        fetch_script = None
        for p in wechat_fetch_paths:
            if p.exists():
                fetch_script = str(p)
                break
        if not fetch_script:
            return None
        result = subprocess.run(
            ["python", fetch_script, url],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            content = result.stdout.strip()
            if len(content) > 200:
                content_lower = content.lower()
                relevance_score = sum(1 for kw in RELEVANCE_KEYWORDS if kw.lower() in content_lower)
                if relevance_score >= 2:
                    return {"content": content[:2000], "relevance_score": relevance_score, "success": True}
                else:
                    print(f"[WECHAT] 文章不相关 (relevance={relevance_score}): {url}")
                    return None
    except Exception as e:
        print(f"[WECHAT] 抓取失败 {url}: {e}")
    return None


def load_manual_articles() -> list[dict]:
    """加载用户手动添加的微信公众号文章，支持多种格式."""
    manual_paths = [
        Path.home() / ".hermes" / "wechat-manual.json",
        Path.home() / "AppData" / "Local" / "hermes" / "wechat-manual.json",
        Path.cwd() / "wechat-manual.json",
    ]
    for p in manual_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 支持两种格式: [{"url": ...}] 或 {"articles": [{"url": ...}]}
                if isinstance(data, list):
                    articles = data
                elif isinstance(data, dict) and "articles" in data:
                    articles = data["articles"]
                else:
                    print(f"[WECHAT] 未知格式 {p}")
                    return []
                print(f"[WECHAT] 加载手动文章: {len(articles)} 条 ({p})")
                return articles
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WECHAT] 加载手动文章失败 {p}: {e}")
                return []
    print("[WECHAT] 未找到手动文章文件")
    return []


def collect_wechat_articles(
    keywords: list[str] = None,
    hours: int = 24,
    max_per_keyword: int = 20,
    include_manual: bool = True,
    filter_by_content: bool = True,
) -> list[dict]:
    """采集微信公众号文章.

    2026-09-16: Jack 要求展示"主要是采集 8 个机器人/具身关键词命中的文章"。
    优先级：① Exa 关键词搜索（命中 8 个机器人/具身词）为主 → ② AI HOT 补充
    （最近 1 天公众号文）→ ③ 手动添加。机器人/具身命中的文章排最前。
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS
    all_articles = {}

    # ① Exa 关键词搜索（主源：命中 8 个机器人/具身词的公众号文）
    print(f"[WECHAT] 开始搜索 {len(keywords)} 个关键词（主源：机器人/具身）...")
    exa_count = 0
    for kw in keywords:
        print(f"  搜索: {kw}")
        search_results = search_wechat_via_exa(kw, max_results=max_per_keyword)
        print(f"    找到 {len(search_results)} 篇")
        for sr in search_results:
            url = sr.get("url", "")
            if not url or url in all_articles:
                continue
            filtered = None
            if filter_by_content:
                filtered = fetch_and_filter_wechat_article(url)
            text_blob = sr.get("title", "") + " " + (filtered["content"] if filtered else sr.get("snippet", ""))
            hits = robot_signal(text_blob)
            all_articles[url] = {
                "title": sr.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(sr.get("publishedAt", "")),
                "source": "微信公众号",
                "description": filtered["content"] if filtered else (sr.get("snippet", "") or ""),
                "relevance_score": (filtered["relevance_score"] if filtered else 0) + hits * 5,
                "robot_hits": hits,
                "first_seen_at": now_iso(),
            }
            exa_count += 1
    print(f"[WECHAT] Exa 关键词搜索得到 {exa_count} 篇（去重后 {len(all_articles)}）")

    # ② AI HOT 聚合源（补充：最近 1 天公众号文，带摘要+真实时间）
    aihot_results = fetch_aihot_wechat()
    for sr in aihot_results:
        url = sr.get("url", "")
        if not url or url in all_articles:
            continue
        text_blob = sr.get("title", "") + " " + sr.get("snippet", "")
        hits = robot_signal(text_blob)
        all_articles[url] = {
            "title": sr.get("title", ""),
            "url": url,
            "published_at": normalize_wechat_time(sr.get("publishedAt", "")),
            "source": sr.get("source", "微信公众号"),
            "description": sr.get("snippet", ""),
            "relevance_score": (10 if hits == 0 else 0) + hits * 5,
            "robot_hits": hits,
            "first_seen_at": now_iso(),
        }
    print(f"[WECHAT] 加 AI HOT 后共 {len(all_articles)} 篇（去重后）")

    if include_manual:
        manual = load_manual_articles()
        for m in manual:
            url = m.get("url", "")
            if not url or url in all_articles:
                continue
            text_blob = m.get("title", "") + " " + m.get("description", m.get("notes", ""))
            hits = robot_signal(text_blob)
            all_articles[url] = {
                "title": m.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(m.get("published_at", "")),
                "source": m.get("source", "微信公众号"),
                "description": m.get("description", m.get("notes", "")),
                "relevance_score": 10 + hits * 5,
                "robot_hits": hits,
                "first_seen_at": now_iso(),
            }

    results = []
    for url, article in all_articles.items():
        results.append({
            "id": sha1_short(url),
            "title": article.get("title", ""),
            "title_zh": "",
            "url": url,
            "published_at": article.get("published_at", now_iso()),
            "site_name": "微信公众号",
            "site_id": "wechat",
            "source": article.get("source", "微信公众号"),
            "description": article.get("description", ""),
            "ai_score": 0, "relevance": 0, "authority": 0,
            "depth": 0, "timeliness": 0, "writing_value": 0, "total_score": 0,
            "ai_label": "wechat",
            "robot_hits": article.get("robot_hits", 0),
            "first_seen_at": article.get("first_seen_at", now_iso()),
        })
    # 排序：机器人/具身命中数 ↓，再时间 ↓（命中的排最前，命中的里新的在前）
    results.sort(key=lambda x: (-x.get("robot_hits", 0), x.get("published_at", "")))
    print(f"[WECHAT] 最终输出 {len(results)} 篇标准化文章（机器人/具身命中 {sum(1 for r in results if r['robot_hits']>0)} 篇排前）")
    return results


def main():
    parser = argparse.ArgumentParser(description="微信公众号文章采集器 v2")
    parser.add_argument("--search", nargs="+", help="搜索关键词")
    parser.add_argument("--hours", type=int, default=24, help="搜索时间范围（小时）")
    parser.add_argument("--max-per-keyword", type=int, default=20, help="每个关键词最大结果数")
    parser.add_argument("--manual", action="store_true", help="同时加载手动添加的文章")
    parser.add_argument("--no-filter", action="store_true", help="跳过正文抓取和内容过滤")
    parser.add_argument("--output", "-o", help="输出文件路径（JSON）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不输出")
    args = parser.parse_args()
    keywords = args.search if args.search else DEFAULT_KEYWORDS
    articles = collect_wechat_articles(
        keywords=keywords, hours=args.hours, max_per_keyword=args.max_per_keyword,
        include_manual=args.manual, filter_by_content=not args.no_filter,
    )
    if args.dry_run:
        print(f"\n[DRY RUN] 预览 {len(articles)} 篇文章:")
        for a in articles[:5]:
            print(f"  - {a['title']} ({a['url'][:60]}...)")
        if len(articles) > 5:
            print(f"  ... 还有 {len(articles) - 5} 篇")
        return
    if args.output:
        output = {"generated_at": now_iso(), "total": len(articles), "articles": articles}
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 已保存到 {args.output}")
    else:
        output = {"generated_at": now_iso(), "total": len(articles), "articles": articles}
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

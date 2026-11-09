#!/usr/bin/env python3
"""从仓库里已有的数据重建抓取状态（解决"云端每轮冷启动"的问题）

背景
----
云端 runner 是无状态的：每轮 checkout 下来只有 data/ 里的快照，
`seen_urls.json`（去重）、`title-zh-cache.json`（翻译缓存）、`archive.json`（21 天归档）
都是空的。于是每轮都要重新翻译、重新判定新旧、archive_total 归零。

但这些东西**本来就能从仓库里的数据推出来**：
  seen_urls        ← 所有出现过的 url（分片 + 当日快照）
  title-zh-cache   ← item 的 title / title_zh 字段
  archive.json     ← data/days/*.json 按天聚合成 21 天滚动窗口

唯一推不出来的是 gn-url-cache.json（GN 跳转 → 真实地址的解析结果，快照里没存），
那部分交给 actions/cache 传递。

用法：
  python scripts/rebuild_state.py --data-dir data --archive-days 21
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[STATE] WARN 读取 {path} 失败：{e}")
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def collect_items(data_dir):
    """分片 + 当日快照里的所有条目（按 url 去重，保留高分）"""
    seen = {}
    days_dir = os.path.join(data_dir, "days")
    if os.path.isdir(days_dir):
        for fn in sorted(os.listdir(days_dir)):
            if not (fn.endswith(".json") and len(fn) == 15):
                continue
            d = load_json(os.path.join(days_dir, fn), {})
            for it in (d.get("items_ai") or []):
                u = it.get("url")
                if not u:
                    continue
                old = seen.get(u)
                if old is None or float(it.get("total_score") or 0) > float(old.get("total_score") or 0):
                    seen[u] = it
    snap = load_json(os.path.join(data_dir, "latest-24h-min.json"), {})
    for it in (snap.get("items_ai") or []):
        u = it.get("url")
        if not u:
            continue
        old = seen.get(u)
        if old is None or float(it.get("total_score") or 0) > float(old.get("total_score") or 0):
            seen[u] = it
    return seen


def parse_dt(raw):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--archive-days", type=int, default=21)
    ap.add_argument("--max-seen", type=int, default=20000, help="seen_urls 上限，防止无限增长")
    args = ap.parse_args()

    items_by_url = collect_items(args.data_dir)
    print(f"[STATE] 从仓库数据收集到 {len(items_by_url)} 条唯一条目")

    # 1) seen_urls
    seen_path = os.path.join(args.data_dir, "seen_urls.json")
    existing = load_json(seen_path, {"urls": []})
    urls = list(existing.get("urls") or [])
    known = set(urls)
    added = 0
    for u in items_by_url:
        if u not in known:
            known.add(u)
            urls.append(u)
            added += 1
    if len(urls) > args.max_seen:
        urls = urls[-args.max_seen:]
    save_json(seen_path, {"urls": urls})
    print(f"[STATE] seen_urls: +{added} → {len(urls)}")

    # 2) title-zh-cache
    tz_path = os.path.join(args.data_dir, "title-zh-cache.json")
    cache = load_json(tz_path, {})
    before = len(cache)
    for it in items_by_url.values():
        t, zh = (it.get("title") or "").strip(), (it.get("title_zh") or "").strip()
        if t and zh and t not in cache:
            cache[t] = zh
    save_json(tz_path, cache)
    print(f"[STATE] title-zh-cache: {before} → {len(cache)}")

    # 3) archive.json（21 天滚动窗口）
    ar_path = os.path.join(args.data_dir, "archive.json")
    ar = load_json(ar_path, {})
    ar_items = list(ar.get("items") or [])
    if not ar_items:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.archive_days)
        rebuilt = []
        for it in items_by_url.values():
            dt = parse_dt(it.get("published_at")) or parse_dt(it.get("first_seen_at"))
            if dt is None or dt >= cutoff:
                rebuilt.append(it)
        ar_items = rebuilt
        print(f"[STATE] archive: 空 → 重建 {len(ar_items)} 条（{args.archive_days} 天窗口）")
    else:
        print(f"[STATE] archive: 已存在 {len(ar_items)} 条，保留")
    save_json(ar_path, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(ar_items),
        "items": ar_items,
    })

    # gn-url-cache 无法自举，这里只做存在性提示
    gn = os.path.join(args.data_dir, "gn-url-cache.json")
    if os.path.exists(gn):
        try:
            n = len(json.load(open(gn, encoding="utf-8")))
        except Exception:
            n = -1
        print(f"[STATE] gn-url-cache: {n} 条（来自 actions/cache 或本地）")
    else:
        print("[STATE] gn-url-cache: 缺失 → 本轮需要重新解析 GN 跳转（较慢，属正常）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

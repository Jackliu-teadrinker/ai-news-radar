#!/usr/bin/env python3
"""按日分片生成器（方案C，云端与本地共用同一套规则）

输入：<data-dir>/latest-24h-min.json
输出：<days-dir>/YYYY-MM-DD.json（一条一行，便于 git 按行 delta）+ <days-dir>/index.json

规则（必须与 ops/windows/run-radar.ps1 内的一致）：
  1. 按 published_at 换算到 UTC+8 的日期归属分片；缺 published_at 的归今天。
  2. 同 url 去重，保留 total_score 更高的那条。
  3. 已存在的条目保持原顺序（只追加、不重排），这样 git delta 只增不重排。
  4. 文件格式：{"date","generated_at","total_items","items_ai":[...]}，
     每个 item 独占一行；文件末尾带换行。
  5. index.json：{"generated_at","latest","days":[...],"source_count","archive_total"}
  6. 超过 --keep-days 的分片：给了 --archive-dir 就挪过去，否则直接删除。

用法：
  python scripts/build_shards.py --data-dir data --days-dir data/days
  python scripts/build_shards.py --data-dir data --days-dir data/days --keep-days 60
"""
import argparse
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def day_key(item, fallback):
    raw = (item.get("published_at") or "").strip()
    if not raw:
        return fallback
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).strftime("%Y-%m-%d")
    except Exception:
        return fallback


def load_day(path):
    """读已有分片，返回 (ordered list of items, set of urls)"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("items_ai") or [])
    except Exception as e:
        print(f"[SHARD] WARN 读取失败 {path}: {e}（按空分片重建）")
        return []


def write_day(path, day, generated_at, items):
    lines = ",\n".join(
        json.dumps(it, ensure_ascii=False, separators=(",", ":")) for it in items
    )
    body = (
        '{"date":"%s","generated_at":"%s","total_items":%d,"items_ai":[\n%s\n]}\n'
        % (day, generated_at, len(items), lines)
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data", help="latest-24h-min.json 所在目录")
    ap.add_argument("--days-dir", default=os.path.join("data", "days"))
    ap.add_argument("--keep-days", type=int, default=60)
    ap.add_argument("--archive-dir", default=None,
                    help="超期分片移到这里（不传则直接删除；云端通常不传）")
    args = ap.parse_args()

    snap_path = os.path.join(args.data_dir, "latest-24h-min.json")
    if not os.path.exists(snap_path):
        print(f"[SHARD] 找不到 {snap_path}，跳过")
        return 0
    with open(snap_path, encoding="utf-8") as f:
        snap = json.load(f)

    generated_at = snap.get("generated_at") or datetime.now(timezone.utc).isoformat()
    items = snap.get("items_ai") or []
    today = datetime.now(CST).strftime("%Y-%m-%d")
    os.makedirs(args.days_dir, exist_ok=True)

    # 按 published_at 分桶
    buckets = {}
    for it in items:
        if not it.get("url"):
            continue
        buckets.setdefault(day_key(it, today), []).append(it)

    for day in sorted(buckets):
        path = os.path.join(args.days_dir, f"{day}.json")
        existing = load_day(path)
        by_url = {}
        order = []
        for it in existing:
            u = it.get("url")
            if not u or u in by_url:
                continue
            by_url[u] = it
            order.append(u)
        added = 0
        for it in buckets[day]:
            u = it["url"]
            old = by_url.get(u)
            if old is None:
                added += 1
                order.append(u)
                by_url[u] = it
            elif float(it.get("total_score") or 0) > float(old.get("total_score") or 0):
                by_url[u] = it          # 原地替换，位置不变
        merged = [by_url[u] for u in order]

        if added == 0 and existing and len(merged) == len(existing):
            print(f"[SHARD] {day}.json 无新增，跳过写入（{len(merged)} 条）")
            continue
        write_day(path, day, generated_at, merged)
        print(f"[SHARD] {day}.json 新增 {added} 条，累计 {len(merged)} 条")

    # index.json
    days = sorted(
        f[:-5] for f in os.listdir(args.days_dir)
        if f.endswith(".json") and f != "index.json" and len(f) == 15
    )
    total_feeds = 0
    ss = os.path.join(args.data_dir, "source-status.json")
    if os.path.exists(ss):
        try:
            with open(ss, encoding="utf-8") as f:
                total_feeds = int((json.load(f).get("summary") or {}).get("total_feeds") or 0)
        except Exception:
            pass
    index = {
        "generated_at": generated_at,
        "latest": days[-1] if days else today,
        "days": days,
        "source_count": total_feeds,
        "archive_total": snap.get("archive_total") or 0,
    }
    with open(os.path.join(args.days_dir, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"[SHARD] index.json: latest={index['latest']} days={len(days)}")

    # 保留策略
    if args.keep_days > 0:
        cutoff = (datetime.now(CST) - timedelta(days=args.keep_days)).strftime("%Y-%m-%d")
        for d in days:
            if d < cutoff:
                src = os.path.join(args.days_dir, f"{d}.json")
                if args.archive_dir:
                    os.makedirs(args.archive_dir, exist_ok=True)
                    shutil.move(src, os.path.join(args.archive_dir, f"{d}.json"))
                    print(f"[SHARD] {d} 超过 {args.keep_days} 天，归档")
                else:
                    os.remove(src)
                    print(f"[SHARD] {d} 超过 {args.keep_days} 天，移出仓库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

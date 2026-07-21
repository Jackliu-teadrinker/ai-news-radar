#!/usr/bin/env python3
"""Curate high-quality articles from latest-24h-min.json (Jack 2026-06-10 18:58 CST 方案 A).

规则:
- 阈值: total_score >= 60 (5 维评分)
- dedup: 跨 24h 用 URL hash 去重 (同 URL 不重复入)
- 上限: 每天 50 条 (防爆)
- 输出: data/curated/YYYY-MM-DD.json (按 CST 日期)
- 字段精简: id/title/title_zh/url/published_at/source/site_name/description/total_score/relevance/authority/depth/timeliness/writing_value/ai_label
- 增量: 同一天多次 run 追加不覆盖
"""

import argparse
import json
import os
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CURATED_DIR = "data/curated"
# Jack 2026-06-10 18:58 CST 方案 A. 实际 score 范围 60-130 (relevance*100 + authority + depth + writing + timeliness).
# 阈值 60 几近全过 → 调到 80 (取 top ~50/d) 才有意义。动态调整看 daily volume.
SCORE_THRESHOLD = 80
DAILY_MAX = 50
SHANGHAI = ZoneInfo("Asia/Shanghai")


def curate(data_path: str, curated_dir: str = CURATED_DIR) -> dict:
    """Read latest-24h-min.json, filter, dedup, append to today's file."""
    with open(data_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    items = payload.get("items_ai", payload.get("items", []))
    if not items:
        return {"status": "no_items", "added": 0, "total_today": 0}

    # 1. Filter by score
    high_quality = [it for it in items if (it.get("total_score") or 0) >= SCORE_THRESHOLD]
    print(f"[CURATE] total={len(items)}  pass_score(>={SCORE_THRESHOLD})={len(high_quality)}")

    if not high_quality:
        return {"status": "no_high_quality", "added": 0, "total_today": 0}

    # 2. Sort by total_score desc
    high_quality.sort(key=lambda x: x.get("total_score") or 0, reverse=True)

    # 3. Determine today (CST)
    now_sh = datetime.now(SHANGHAI)
    today_key = now_sh.strftime("%Y-%m-%d")
    output_path = os.path.join(curated_dir, f"{today_key}.json")

    # 4. Load existing curated for today (for dedup)
    existing_ids = set()
    existing_items = []
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_items = existing.get("items", [])
            existing_ids = {it["id"] for it in existing_items if "id" in it}
        except Exception as e:
            print(f"[CURATE] WARN: failed to load existing {output_path}: {e}")

    # 5. Dedupe + add
    new_items = []
    for it in high_quality:
        url = it.get("url", "")
        if not url:
            continue
        # id = sha1(url) for cross-day dedup
        sid = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        it["id"] = sid
        if sid in existing_ids:
            continue
        existing_ids.add(sid)
        new_items.append(it)

    # 6. Cap at DAILY_MAX (keep top DAILY_MAX by total_score)
    if len(existing_items) + len(new_items) > DAILY_MAX:
        # combine + sort + truncate
        combined = existing_items + new_items
        combined.sort(key=lambda x: x.get("total_score") or 0, reverse=True)
        final_items = combined[:DAILY_MAX]
        new_ids = {it["id"] for it in new_items}
        dropped = len(combined) - DAILY_MAX
        new_items_kept = [it for it in final_items if it["id"] in new_ids]
        print(f"[CURATE] daily cap hit, dropped {dropped} (existing={len(existing_items)}, new={len(new_items)})")
    else:
        final_items = existing_items + new_items
        new_items_kept = new_items

    # 7. Sort final by total_score desc
    final_items.sort(key=lambda x: x.get("total_score") or 0, reverse=True)

    # 8. Build output
    output = {
        "date": today_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score_threshold": SCORE_THRESHOLD,
        "total_items": len(final_items),
        "new_added": len(new_items_kept),
        "items": final_items,
    }

    # 9. Write
    os.makedirs(curated_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[CURATE] wrote {output_path}: total={len(final_items)}  new_added={len(new_items_kept)}")
    return {
        "status": "ok",
        "path": output_path,
        "total_today": len(final_items),
        "new_added": len(new_items_kept),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data-path", default="data/latest-24h-min.json")
    p.add_argument("--curated-dir", default=CURATED_DIR)
    args = p.parse_args()
    result = curate(args.data_path, args.curated_dir)
    print(f"[CURATE] result: {json.dumps(result, ensure_ascii=False)}")
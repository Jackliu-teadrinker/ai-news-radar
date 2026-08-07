# 翻译功能集成指南 — translate_utils.py

## 文件结构

`scripts/translate_utils.py` 是共享翻译工具模块，供 `arxiv_fetcher.py` 和 `government_fetcher.py` 复用。

### 核心函数

```python
from translate_utils import is_english, translate_text, translate_batch

# 判断是否为英文标题（<20% 中文字符）
is_english("Robot Learning from Human Demonstrations")  # True

# 翻译单个文本（带缓存 + 重试）
result = translate_text("Robot Learning")  # "机器人学习"

# 批量翻译（并发，自动跳过已缓存）
trans_map = translate_batch(["Title 1", "Title 2"])
# Returns: {"Title 1": "翻译1", "Title 2": "翻译2"}
```

### 缓存机制

- 缓存文件：`data/title-zh-cache.json`（15KB+，每次重写完整文件）
- 读缓存 → 跳过已翻译 → 只翻译新标题
- `_save_cache(cache_dict)` 必须传完整 dict，不是传 key+value

### 使用模式（在 fetcher 中）

```python
# 1. 导入
sys.path.insert(0, os.path.dirname(__file__))
from translate_utils import is_english, translate_batch

# 2. 在 main() 中抓取后翻译
english_titles = [item['title'] for item in filtered if is_english(item['title'])]
if english_titles:
    print(f"[X] Translating {len(english_titles)} English titles...")
    trans_map = translate_batch(english_titles)
    for item in filtered:
        if item['title'] in trans_map and trans_map[item['title']]:
            item['title_zh'] = trans_map[item['title']]

# 3. 写入数据时包含 title_zh
output = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_items": len(filtered),
    "items": filtered,  # 每个 item 可能有 title_zh 字段
}
```

### Pitfall：_save_cache 签名

❌ 错误：`_save_cache(text, translated)` — TypeError
✅ 正确：
```python
cache = _load_cache()
cache[text] = translated
_save_cache(cache)
```

### Pitfall：Google Translate API 限流

- 长标题（>50 字符）更容易触发 429
- 重试退避：1.5s → 3s → 4.5s
- timeout 设为 10s（默认 8s 容易超时）
- 失败时打印 `[TRANSLATE] Failed after N attempts: ...` 便于诊断

### Pitfall：翻译后必须 commit 数据

翻译在内存里完成，但必须写入 JSON 文件并 commit，否则 workflow 下次跑会覆盖。

```bash
git add data/arxiv-papers.json data/government-news.json
git commit -m "data: 翻译后的标题"
git push origin master
```

### Pitfall：data/*.json 冲突时永远用 theirs

rebase 时 `data/arxiv-papers.json` 几乎必然冲突：
```bash
git checkout --theirs data/arxiv-papers.json data/government-news.json
git add data/
git rebase --continue
```

本地副本旧没关系——workflow 下次跑完 auto-push 会修正 origin/master 的 data。
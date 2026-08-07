"""测试 Bing 搜索功能"""
import sys
sys.path.insert(0, r"C:\Users\86571\.openclaw\workspace\ai-news-radar\scripts")

from bings_search_fetcher import search_bing

print("测试 Bing 搜索...")
results = search_bing("人形机器人", max_results=10)
print(f"\n返回结果: {len(results)} 条")

for i, item in enumerate(results[:5], 1):
    print(f"\n{i}. {item['title']}")
    print(f"   URL: {item['url'][:80]}")
    print(f"   来源: {item.get('site_name', 'N/A')}")
    print(f"   摘要: {item['description'][:60] if item['description'] else '(无摘要)'}")

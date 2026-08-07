#!/usr/bin/env python3
"""测试搜索专区脚本"""
import sys
sys.path.insert(0, r"C:\Users\86571\.openclaw\workspace\ai-news-radar\scripts")

from search_fetcher import search_toutiao, search_wechat, search_36kr, search_jiqizhixin

print("测试各信源...")

print("\n1. 今日头条搜索:")
results = search_toutiao("人形机器人")
print(f"   返回 {len(results)} 条")

print("\n2. 微信公众号搜索:")
results = search_wechat("人形机器人")
print(f"   返回 {len(results)} 条")

print("\n3. 36氪搜索:")
results = search_36kr("人形机器人")
print(f"   返回 {len(results)} 条")

print("\n4. 机器之心搜索:")
results = search_jiqizhixin("人形机器人")
print(f"   返回 {len(results)} 条")

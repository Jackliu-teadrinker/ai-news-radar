#!/usr/bin/env python3
"""
快速验证 translate_utils.py 翻译功能是否正常
用法：python scripts/verify_translation.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from translate_utils import is_english, translate_text, translate_batch

def main():
    print("=== translate_utils.py 功能验证 ===\n")
    
    # 1. is_english 测试
    print("1. is_english() 测试:")
    tests = [
        ("Robot Learning from Human Demonstrations", True),
        ("机器人在真实场景的学习适应能力显著提升", False),
        (" Embodied AI for Robotics", True),
        ("具身智能发展趋势", False),
    ]
    for text, expected in tests:
        result = is_english(text)
        status = "✅" if result == expected else "❌"
        print(f"  {status} is_english('{text[:40]}...') = {result} (expected {expected})")
    
    # 2. translate_text 测试
    print("\n2. translate_text() 测试:")
    test_titles = [
        "Robot Learning from Human Demonstrations",
        "Embodied AI",
        "Humanoid Robot Navigation",
    ]
    for title in test_titles:
        result = translate_text(title)
        status = "✅" if result else "❌ (empty)"
        print(f"  {status} '{title[:40]}...'")
        if result:
            print(f"       -> {result[:50]}")
    
    # 3. translate_batch 测试
    print("\n3. translate_batch() 测试:")
    batch_result = translate_batch(test_titles)
    for title, trans in batch_result.items():
        status = "✅" if trans else "❌ (empty)"
        print(f"  {status} '{title[:40]}...'")
        if trans:
            print(f"       -> {trans[:50]}")
    
    # 4. 缓存检查
    print("\n4. 缓存状态:")
    from translate_utils import _load_cache
    cache = _load_cache()
    print(f"  缓存条目数: {len(cache)}")
    
    print("\n=== 验证完成 ===")

if __name__ == '__main__':
    main()
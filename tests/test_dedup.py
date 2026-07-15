"""Tests for cross-feed deduplication (BUG#1 fix)."""
import sys
sys.path.insert(0, r'C:\Users\86571\ai-news-radar-gh\scripts')
import importlib

# Force fresh import
if 'update_news' in sys.modules:
    importlib.reload(sys.modules['update_news'])

from update_news import normalize_title_for_dedup, cross_feed_deduplicate


def test_normalize_title_basic():
    assert normalize_title_for_dedup("宁波华翔投资成立机器人新公司") == "宁波华翔投资成立机器人新公司"


def test_normalize_title_punctuation_diff():
    a = normalize_title_for_dedup("宁波华翔投资成立机器人新公司，含多项AI业务")
    b = normalize_title_for_dedup("宁波华翔投资成立机器人新公司 含多项AI业务")
    assert a == b


def test_normalize_title_english():
    a = normalize_title_for_dedup("Japan invests in physical AI!")
    b = normalize_title_for_dedup("Japan invests in physical AI")
    assert a == b


def test_normalize_title_strip_google_news_source():
    """Google News adds ' - Source Name' to titles; strip it for cross-feed dedup."""
    a = normalize_title_for_dedup("Bear Robotics to Acquire Kinisi Robotics - ACCESS Newswire")
    b = normalize_title_for_dedup("Bear Robotics to Acquire Kinisi Robotics - Yahoo Finance")
    assert a == b


def test_cross_feed_same_article_different_id():
    items = [
        {'title': '宇树科技发布新款机器人', 'url': 'https://a.com', 'total_score': 80},
        {'title': '宇树科技发布新款机器人！', 'url': 'https://b.com', 'total_score': 75},
    ]
    result, removed = cross_feed_deduplicate(items)
    assert removed == 1
    assert len(result) == 1
    assert result[0]['total_score'] == 80


def test_cross_feed_different_articles_not_deduped():
    items = [
        {'title': '宇树科技发布新款机器人', 'url': 'https://a.com', 'total_score': 80},
        {'title': '宁波华翔投资成立机器人新公司', 'url': 'https://b.com', 'total_score': 75},
    ]
    result, removed = cross_feed_deduplicate(items)
    assert removed == 0
    assert len(result) == 2


def test_cross_feed_three_duplicates():
    items = [
        {'title': '宇树科技发布新款机器人', 'url': 'https://a.com', 'total_score': 60},
        {'title': '宇树科技发布新款机器人！', 'url': 'https://b.com', 'total_score': 80},
        {'title': '宇树科技发布新款机器人...', 'url': 'https://c.com', 'total_score': 70},
    ]
    result, removed = cross_feed_deduplicate(items)
    assert removed == 2
    assert len(result) == 1
    assert result[0]['total_score'] == 80


def test_cross_feed_no_scores():
    items = [
        {'title': '宇树牵手英伟达', 'url': 'https://a.com', 'relevance': 0.9},
        {'title': '宇树牵手英伟达！', 'url': 'https://b.com', 'relevance': 0.8},
    ]
    result, removed = cross_feed_deduplicate(items)
    assert removed == 1
    assert len(result) == 1
    assert result[0]['relevance'] == 0.9
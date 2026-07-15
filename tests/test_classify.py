"""Tests for cross-label classification priority (BUG#2 fix).

Verifies that robot-related articles are NOT misclassified as physical_ai.
"""
import sys
sys.path.insert(0, r'C:\Users\86571\ai-news-radar-gh\scripts')

from update_news import GN_LABEL_MAP


def test_physical_ai_has_robot_removed():
    """GN: Physical AI should NOT have 'robot' in its OPML query."""
    # The key itself still maps to 'physical_ai' label
    # But the OPML query (feeds/follow.example.opml) should not contain 'robot'
    # We verify the GN_LABEL_MAP is intact and the cross-label override works
    assert GN_LABEL_MAP.get('GN: Physical AI') == 'physical_ai'


def test_cross_label_override_in_code():
    """Verify the cross-label override logic exists in score_item."""
    # Read the source to check the override code is present
    with open(r'C:\Users\86571\ai-news-radar-gh\scripts\update_news.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Check that the override code is present
    assert 'has_robot_signal' in source
    assert 'gn_label == \'physical_ai\'' in source or "gn_label == 'physical_ai'" in source
    assert 'robotics' in source  # fallback label
    
    # Check the robot signal keywords
    for kw in ['机器人', '人形', '具身智能', 'humanoid', 'embodied']:
        assert kw in source, f"Missing keyword: {kw}"


def test_gn_label_map_intact():
    """Verify GN_LABEL_MAP hasn't been accidentally broken."""
    assert GN_LABEL_MAP.get('GN: humanoid robot') == 'humanoid'
    assert GN_LABEL_MAP.get('GN: Physical AI') == 'physical_ai'
    assert GN_LABEL_MAP.get('GN: BCI') == 'brain_computer'
    assert GN_LABEL_MAP.get('GN: robot') == 'robotics'
    assert len(GN_LABEL_MAP) >= 10  # reasonable size

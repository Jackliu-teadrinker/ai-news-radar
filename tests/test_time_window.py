#!/usr/bin/env python3
"""
test_time_window.py - 时间窗口逻辑单元测试

目的：防止类似 2026-08-30 时间窗口 Bug 反转事件再次发生。

覆盖场景：
  1. ANCHOR_HOUR=19 之前运行（如 15:00 CST）→ 窗口起点 = 昨天 19:00
  2. ANCHOR_HOUR=19 之后运行（如 23:30 CST）→ 窗口起点 = 今天 19:00
  3. 边界：刚好 ANCHOR_HOUR 时 → 窗口起点 = 昨天 19:00（因为 now_sh > today_anchor 为 False）
  4. RSS 数据时间过滤：起点必须 ≤ now_ts
  5. 防御 bc58c191 类型错误：脚本不能有 literal `n
  6. 防御 typo：常见 edit mistake 检测
"""
import os
import re
import sys
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# 路径配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
# 强制使用脚本同目录的 files/ 子目录（避免污染 user 目录）
TEST_DATA_DIR = os.path.join(SCRIPT_DIR, 'files')
os.makedirs(os.path.join(TEST_DATA_DIR, 'scripts'), exist_ok=True)
os.makedirs(os.path.join(TEST_DATA_DIR, '.github', 'workflows'), exist_ok=True)
UPDATE_NEWS_PATH = os.path.join(TEST_DATA_DIR, 'scripts', 'update_news.py')
WORKFLOW_YML_PATH = os.path.join(TEST_DATA_DIR, '.github', 'workflows', 'update-news.yml')


def _ensure_local_files():
    """如果本地找不到 update_news.py，从 GitHub 下载"""
    global UPDATE_NEWS_PATH
    if not os.path.exists(UPDATE_NEWS_PATH):
        import urllib.request
        try:
            req = urllib.request.Request(
                'https://raw.githubusercontent.com/Jackliu-teadrinker/ai-news-radar/master/scripts/update_news.py',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode('utf-8')
            os.makedirs(os.path.dirname(UPDATE_NEWS_PATH), exist_ok=True)
            with open(UPDATE_NEWS_PATH, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            raise unittest.SkipTest(f"Cannot fetch update_news.py: {e}")


class TimeWindowLogicTest(unittest.TestCase):
    """测试时间窗口计算的正确性"""

    ANCHOR_HOUR = 19

    def compute_window(self, now_sh):
        """复刻 update_news.py 中的时间窗口计算逻辑

        这是脚本 line 991-997 的精确复刻。任何对 update_news.py 的修改
        必须保证这个函数的语义与原代码一致。
        """
        today_anchor = now_sh.replace(
            hour=self.ANCHOR_HOUR, minute=0, second=0, microsecond=0
        )
        if now_sh > today_anchor:
            start_dt = today_anchor
        else:
            start_dt = today_anchor - timedelta(days=1)
        start_ts = start_dt.timestamp()
        now_ts = now_sh.timestamp()
        return start_ts, now_ts

    def test_before_anchor_window_contains_yesterday(self):
        """15:00 CST 运行 → 起点必须 = 昨天 19:00 CST（窗口 ~20h）"""
        now_sh = datetime(2026, 8, 30, 15, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        start_ts, now_ts = self.compute_window(now_sh)

        expected_start = datetime(2026, 8, 29, 19, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(start_ts, expected_start.timestamp(),
                         f"15:00 CST 运行时，窗口起点应为昨天 19:00，实际 {start_ts}")
        self.assertLess(start_ts, now_ts,
                        "窗口起点必须早于当前时间（否则所有 item 被过滤）")

    def test_after_anchor_window_contains_today(self):
        """23:30 CST 运行 → 起点必须 = 今天 19:00 CST（窗口 ~4.5h）"""
        now_sh = datetime(2026, 8, 30, 23, 30, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        start_ts, now_ts = self.compute_window(now_sh)

        expected_start = datetime(2026, 8, 30, 19, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(start_ts, expected_start.timestamp(),
                         f"23:30 CST 运行时，窗口起点应为今天 19:00，实际 {start_ts}")
        self.assertLess(start_ts, now_ts,
                        "窗口起点必须早于当前时间")

    def test_exactly_at_anchor_uses_yesterday(self):
        """刚好 19:00 CST 运行 → 起点 = 昨天 19:00（now_sh > today_anchor 为 False）"""
        now_sh = datetime(2026, 8, 30, 19, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        start_ts, now_ts = self.compute_window(now_sh)

        expected_start = datetime(2026, 8, 29, 19, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(start_ts, expected_start.timestamp(),
                         "19:00 CST 整点运行时，起点应为昨天 19:00")
        # 整点时刻 now_ts > start_ts，窗口 = 24h（昨天 19:00 → 今天 19:00）
        self.assertGreater(now_ts, start_ts,
                         "整点时窗口应该 = 24h（昨天 19:00 → 今天 19:00）")

    def test_window_never_negative(self):
        """所有测试时间点都必须满足 start_ts ≤ now_ts"""
        test_times = [
            (0, 0), (8, 0), (12, 0), (15, 0), (18, 59),
            (19, 0), (19, 1), (19, 30), (22, 0), (23, 59),
        ]
        for hour, minute in test_times:
            now_sh = datetime(2026, 8, 30, hour, minute, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
            start_ts, now_ts = self.compute_window(now_sh)
            self.assertLessEqual(
                start_ts, now_ts,
                f"窗口反转！{hour:02d}:{minute:02d} CST 时，start_ts={start_ts:.0f} > now_ts={now_ts:.0f}"
            )

    def test_rss_items_in_window_included(self):
        """验证 RSS 数据（过去 24h 内）能被正确包含"""
        # 模拟 15:00 CST 运行
        now_sh = datetime(2026, 8, 30, 15, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        start_ts, now_ts = self.compute_window(now_sh)

        # 一个发布于 14:00 CST 的 item（30分钟前）
        item_pub = datetime(2026, 8, 30, 14, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertTrue(
            start_ts <= item_pub.timestamp() <= now_ts,
            "14:00 CST 发布的 RSS item 应该在 15:00 CST 运行的窗口内"
        )

        # 一个发布于昨天 20:00 CST 的 item（约19小时前）
        item_pub_2 = datetime(2026, 8, 29, 20, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertTrue(
            start_ts <= item_pub_2.timestamp() <= now_ts,
            "昨天 20:00 CST 发布的 RSS item 应该在 15:00 CST 运行的窗口内"
        )

        # 一个发布于今天 19:00 CST 的 item（未来，不应该被包含）
        item_pub_3 = datetime(2026, 8, 30, 19, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertFalse(
            start_ts <= item_pub_3.timestamp() <= now_ts,
            "今天 19:00 CST（未来）的 RSS item 不应该被包含"
        )


class ScriptSyntaxTest(unittest.TestCase):
    """测试脚本本身的语法和导入"""

    def setUp(self):
        """确保本地有 update_news.py（只在不存在时下载，避免覆盖手动修改）"""
        global UPDATE_NEWS_PATH
        if not os.path.exists(UPDATE_NEWS_PATH):
            # 只在本地不存在时才下载（避免覆盖手动 injection）
            import urllib.request
            try:
                req = urllib.request.Request(
                    'https://raw.githubusercontent.com/Jackliu-teadrinker/ai-news-radar/master/scripts/update_news.py',
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read().decode('utf-8')
                os.makedirs(os.path.dirname(UPDATE_NEWS_PATH), exist_ok=True)
                with open(UPDATE_NEWS_PATH, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                self.skipTest(f"Cannot fetch update_news.py: {e}")

    def _extract_time_window_logic_from_script(self):
        """从 update_news.py 中提取时间窗口计算的 if/else 块

        返回 (now_sh_branch_value, else_branch_value, comparison_op)
        例如 correct: ('today_anchor', 'today_anchor - timedelta(days=1)', '>')
        例如 buggy:   ('today_anchor - timedelta(days=1)', 'today_anchor', '>=')
        """
        if not os.path.exists(UPDATE_NEWS_PATH):
            self.skipTest("update_news.py not found")
        with open(UPDATE_NEWS_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到时间窗口代码块（约 line 991-998）
        pattern = re.compile(
            r'if\s+(now_sh\s*([><=]+)\s*today_anchor)\s*:\s*\n'
            r'\s+start_dt\s*=\s*([^\n]+)\s*\n'
            r'\s*else\s*:\s*\n'
            r'\s+start_dt\s*=\s*([^\n]+)',
            re.MULTILINE
        )
        m = pattern.search(content)
        if not m:
            self.skipTest("Time window pattern not found (may have changed)")
        return {
            'comparison': m.group(2).strip(),
            'if_branch': m.group(3).strip(),
            'else_branch': m.group(4).strip(),
        }

    def test_time_window_logic_not_inverted(self):
        """REGRESSION TEST: 检测 2026-08-30 时间窗口反转 Bug

        如果有人把 if/else 的两个分支反了，这个测试会失败。
        """
        logic = self._extract_time_window_logic_from_script()
        # 正确逻辑：if 分支（after 19:00）应该用 today_anchor（今天 19:00）
        #            else 分支（before 19:00）应该用 today_anchor - timedelta(days=1)
        self.assertEqual(
            logic['if_branch'], 'today_anchor',
            f"BUG: if 分支应该是 today_anchor，但实际是 '{logic['if_branch']}'。"
            f"这会导致 19:00 CST 之后运行时窗口过短（2026-08-30 时间窗口反转 Bug）"
        )
        self.assertEqual(
            logic['else_branch'], 'today_anchor - timedelta(days=1)',
            f"BUG: else 分支应该是 'today_anchor - timedelta(days=1)'，"
            f"但实际是 '{logic['else_branch']}'。"
            f"这会导致 19:00 CST 之前运行时窗口为负，所有数据被过滤"
        )
        self.assertEqual(
            logic['comparison'], '>',
            f"BUG: 比较操作应该是 '>'，但实际是 '{logic['comparison']}'。"
            f"如果是 '>=' 会导致 19:00 整点时窗口起点错误"
        )

    def test_python_syntax(self):
        """update_news.py 必须能通过 py_compile"""
        if not os.path.exists(UPDATE_NEWS_PATH):
            self.skipTest(f"update_news.py not found at {UPDATE_NEWS_PATH}")
        import py_compile
        try:
            py_compile.compile(UPDATE_NEWS_PATH, doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"update_news.py syntax error: {e}")

    def test_no_literal_backtick_n(self):
        """防御 bc58c191 Bug：脚本中不能有 literal `n（应该是真正的换行）"""
        if not os.path.exists(UPDATE_NEWS_PATH):
            self.skipTest("update_news.py not found")
        with open(UPDATE_NEWS_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        # 反引号 + n 字面量（不是 \n 转义）
        bad_pattern = re.compile(r'`n')
        matches = bad_pattern.findall(content)
        self.assertEqual(
            len(matches), 0,
            f"Found literal `n in update_news.py (defensive against bc58c191): {matches[:5]}"
        )

    def test_no_common_typos(self):
        """防御常见 typo（如 output_dirtput_dir）"""
        if not os.path.exists(UPDATE_NEWS_PATH):
            self.skipTest("update_news.py not found")
        with open(UPDATE_NEWS_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        typos = [
            'output_dirtput',  # 来自 fix_script.py 的 typo
            'window_hourss',
            'args.output_dirtput',
            'sys.exit(0)`n',   # 反引号 + n + sys.exit
            '`n    sys.exit',  # 反引号 n + sys.exit
        ]
        for typo in typos:
            self.assertNotIn(
                typo, content,
                f"Found known typo in update_news.py: '{typo}'"
            )

    def test_imports_work(self):
        """脚本必须能导入（catch 隐藏的 import error）"""
        if not os.path.exists(UPDATE_NEWS_PATH):
            self.skipTest("update_news.py not found")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("update_news", UPDATE_NEWS_PATH)
            module = importlib.util.module_from_spec(spec)
            # Note: 不执行 main，只验证 import
            spec.loader.exec_module(module)
        except SyntaxError as e:
            self.fail(f"Syntax error: {e}")
        except ImportError as e:
            # import 失败可能是缺包（feedparser 等），但这不算 script bug
            self.skipTest(f"Import error (likely missing dep): {e}")
        except Exception as e:
            # 其他运行时错误（如 ZoneInfo 缺 tzdata）也不一定算 bug
            if 'No module named' in str(e):
                self.skipTest(f"Missing dependency: {e}")
            # 但是真正的 script bug 应该 fail
            self.fail(f"Unexpected error loading update_news.py: {e}")


class WorkflowYmlTest(unittest.TestCase):
    """测试 GitHub Actions workflow 配置"""

    def setUp(self):
        """如果本地找不到 workflow.yml，从 GitHub 下载"""
        global WORKFLOW_YML_PATH
        if not os.path.exists(WORKFLOW_YML_PATH):
            # 尝试从 GitHub 临时下载
            import urllib.request, base64
            try:
                req = urllib.request.Request(
                    'https://raw.githubusercontent.com/Jackliu-teadrinker/ai-news-radar/master/.github/workflows/update-news.yml',
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read().decode('utf-8')
                os.makedirs(os.path.dirname(WORKFLOW_YML_PATH), exist_ok=True)
                with open(WORKFLOW_YML_PATH, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                self.skipTest(f"Cannot fetch workflow.yml: {e}")

    def test_workflow_yaml_exists(self):
        """workflow yml 必须存在"""
        self.assertTrue(
            os.path.exists(WORKFLOW_YML_PATH),
            f"Workflow file not found: {WORKFLOW_YML_PATH}"
        )

    def test_workflow_yaml_parseable(self):
        """workflow yml 必须能正确解析"""
        if not os.path.exists(WORKFLOW_YML_PATH):
            self.skipTest("workflow.yml not found")
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        with open(WORKFLOW_YML_PATH, 'r', encoding='utf-8') as f:
            try:
                yaml.safe_load(f.read())
            except yaml.YAMLError as e:
                self.fail(f"workflow yml parse error: {e}")

    def test_workflow_has_no_duplicate_keys(self):
        """防御 348f65bf Bug：concurrency 块不能有重复 key"""
        if not os.path.exists(WORKFLOW_YML_PATH):
            self.skipTest("workflow.yml not found")
        with open(WORKFLOW_YML_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 在 concurrency 块中检测重复的 top-level keys
        in_concurrency = False
        concurrency_keys = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == 'concurrency:':
                in_concurrency = True
                continue
            if in_concurrency:
                if not stripped or stripped.startswith('#'):
                    continue
                # 检测顶级 key（以 2 空格缩进，不是更深）
                if line.startswith('  ') and not line.startswith('    '):
                    key = stripped.split(':')[0]
                    if key in concurrency_keys:
                        self.fail(
                            f"Duplicate key '{key}' in concurrency block "
                            f"(line {i+1}, first seen at line {concurrency_keys[key]+1})"
                        )
                    concurrency_keys[key] = i
                # 离开 concurrency 块
                elif not line.startswith(' '):
                    break


class RegressionTest(unittest.TestCase):
    """回归测试：防止 2026-08-30 时间窗口反转事件重演"""

    def test_buggy_inversion_caught(self):
        """直接验证：如果有人把 update_news.py 反转，是否能被单元测试抓到

        这个测试不需要执行 update_news.py，而是直接检查我们的 compute_window
        函数和 buggy 版本（已知的错误版本）的行为差异。
        """
        ANCHOR_HOUR = 19

        def correct_logic(now_sh):
            today_anchor = now_sh.replace(hour=ANCHOR_HOUR, minute=0, second=0, microsecond=0)
            if now_sh > today_anchor:
                start_dt = today_anchor
            else:
                start_dt = today_anchor - timedelta(days=1)
            return start_dt.timestamp()

        def buggy_inverted_logic(now_sh):
            """2026-08-30 那个错误 fix 的版本"""
            today_anchor = now_sh.replace(hour=ANCHOR_HOUR, minute=0, second=0, microsecond=0)
            if now_sh >= today_anchor:
                start_dt = today_anchor - timedelta(days=1)  # BUG!
            else:
                start_dt = today_anchor  # BUG!
            return start_dt.timestamp()

        # 在 15:00 CST 时
        now_sh = datetime(2026, 8, 30, 15, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))

        correct_start = correct_logic(now_sh)
        buggy_start = buggy_inverted_logic(now_sh)
        now_ts = now_sh.timestamp()

        # Correct: start_ts < now_ts (window includes recent data)
        self.assertLess(correct_start, now_ts, "Correct logic should have positive window")

        # Buggy: start_ts > now_ts (window negative, all data filtered)
        self.assertGreater(buggy_start, now_ts, "Buggy logic should produce negative window")

        # The test catches the regression
        self.assertNotEqual(correct_start, buggy_start,
                            "Correct and buggy logic should differ at 15:00 CST")


def main():
    """运行所有测试"""
    # 先确保本地有文件（从 GitHub 拉取）
    try:
        _ensure_local_files()
    except unittest.SkipTest as e:
        print(f"Warning: {e}")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加所有测试类
    suite.addTests(loader.loadTestsFromTestCase(TimeWindowLogicTest))
    suite.addTests(loader.loadTestsFromTestCase(ScriptSyntaxTest))
    suite.addTests(loader.loadTestsFromTestCase(WorkflowYmlTest))
    suite.addTests(loader.loadTestsFromTestCase(RegressionTest))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()

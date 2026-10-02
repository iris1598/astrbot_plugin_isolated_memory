"""test_advanced_memory.py - 针对升级特性（结构化记忆、加权打分、MMR多样性、高重要性保护、Agent工具）的单元测试。"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import bootstrap

_HAS = bootstrap.bootstrap()

if _HAS:
    try:
        from astrbot_plugin_isolated_memory.memory import ExtractedFact, MemoryManager
        from astrbot_plugin_isolated_memory.main import Main
    except ImportError:
        from memory import ExtractedFact, MemoryManager
        from main import Main
else:
    ExtractedFact = None
    MemoryManager = None
    Main = None


class FakeConfig(dict):
    pass


def make_manager(**mem):
    cfg = FakeConfig(memory=dict(mem))
    ctx = type("C", (), {"kb_manager": None})()
    return MemoryManager(ctx, cfg)


def run(coro):
    return asyncio.run(coro)


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestStructuredExtraction(unittest.TestCase):
    """测试结构化抽取与向后兼容性。"""

    def test_structured_json_parsing(self):
        payload = json.dumps({
            "memories": [
                {
                    "content": "用户对芒果和花生重度过敏",
                    "importance": 0.95,
                    "type": "preference",
                },
                {
                    "content": "用户计划在 2026-11-01 参加考试",
                    "importance": 0.5,
                    "type": "planned",
                },
            ]
        })
        facts = MemoryManager._parse_extraction(payload)
        self.assertEqual(len(facts), 2)

        # 验证事实内容与属性
        self.assertEqual(facts[0], "用户对芒果和花生重度过敏")
        self.assertEqual(facts[0].importance, 0.95)
        self.assertEqual(facts[0].fact_type, "preference")

        self.assertEqual(facts[1], "用户计划在 2026-11-01 参加考试")
        self.assertEqual(facts[1].importance, 0.5)
        self.assertEqual(facts[1].fact_type, "planned")

        # 验证与普通字符串的 100% 兼容性
        self.assertTrue(isinstance(facts[0], str))
        self.assertEqual(facts[0].upper(), "用户对芒果和花生重度过敏")

    def test_build_extract_prompt_livingmemory_style(self):
        """测试借鉴 livingmemory 的提取提示词构造（时间绝对化、消歧、分级与原子化事实）。"""
        mgr = make_manager()
        prompt = mgr._build_extract_prompt(
            turns=[("我明天要去上海出差", "好的，祝出差顺利！")],
            persona="友好的智能管家",
            user_name="小李",
        )
        self.assertIn("长期记忆提炼专家", prompt)
        self.assertIn("小李", prompt)
        self.assertIn("时间绝对化换算", prompt)
        self.assertIn("主体自包含与消除代词", prompt)
        self.assertIn("0.9 ~ 1.0 (核心重要)", prompt)
        self.assertIn("宁缺毋滥", prompt)
        self.assertIn('"memories":[{"content":', prompt)

    def test_backward_compatibility_with_string_array(self):
        """验证旧版纯字符串数组解析完全兼容，并赋默认值。"""
        payload = '{"memories": ["用户喜欢黑咖啡", "家里养了一只英短猫"]}'
        facts = MemoryManager._parse_extraction(payload)
        self.assertEqual(len(facts), 2)
        self.assertEqual(facts, ["用户喜欢黑咖啡", "家里养了一只英短猫"])
        self.assertEqual(facts[0].importance, 0.6)
        self.assertEqual(facts[0].fact_type, "factual")


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestMMRDeduplication(unittest.TestCase):
    """测试 MMR 多样性打散。"""

    def test_mmr_selects_diverse_candidates(self):
        candidates = [
            {"text": "喜欢喝冰美式咖啡", "effective": 0.95},
            {"text": "特别喜欢喝冰美式咖啡", "effective": 0.92},  # 极度相似
            {"text": "生活在杭州市西湖区", "effective": 0.70},    # 完全不同领域
        ]
        # 当 top_k = 2 时，MMR 应当挑出 第1条 和 第3条，而不是语义完全重复的第2条
        selected = MemoryManager._apply_mmr(candidates, top_k=2, mmr_lambda=0.6)
        self.assertEqual(len(selected), 2)
        texts = [s["text"] for s in selected]
        self.assertEqual(texts[0], "喜欢喝冰美式咖啡")
        self.assertEqual(texts[1], "生活在杭州市西湖区")


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestHighImportanceProtection(unittest.TestCase):
    """测试高重要性记忆保护（豁免 TTL 过期删除）。"""

    def test_important_memory_not_dropped_in_sweep(self):
        now = time.time()
        day = 86400.0

        # 两条都已存在 120 天（超过 ttl=90 天）
        # normal: 重要度 0.6 -> 应被清扫删除
        # crucial: 重要度 0.95 -> 豁免删除
        docs = [
            {
                "doc_id": "normal_doc",
                "text": "用户昨天吃了拉面",
                "updated_at": now - 120 * day,
                "metadata": {"importance": 0.6, "type": "episodic"},
            },
            {
                "doc_id": "crucial_doc",
                "text": "用户对青霉素严重过敏",
                "updated_at": now - 120 * day,
                "metadata": {"importance": 0.95, "type": "preference"},
            },
        ]

        deleted_ids = []

        class MockDS:
            async def get_documents(self, **kwargs):
                return []

        class MockVecDB:
            document_storage = MockDS()

            async def delete(self, doc_id):
                deleted_ids.append(doc_id)

            async def count_documents(self, **kwargs):
                return 1

        class MockKB:
            vec_db = MockVecDB()
            kb = type("K", (), {"kb_id": "test_kb", "kb_name": "test_kb"})()
            init_error = None
            kb_db = type("DB", (), {
                "update_kb_stats": staticmethod(lambda **k: asyncio.sleep(0)),
                "get_db": lambda self: asyncio.sleep(0),
            })()

            async def refresh_kb(self):
                pass

        mgr = make_manager(
            memory_ttl_days=90,
            memory_sweep_interval_minutes=0,
            memory_protect_important=True,
        )

        async def fake_ensure_kb():
            return MockKB()

        async def fake_all_chunks(vec_db, owner):
            return docs

        async def fake_sync_doc(kb, owner):
            pass

        mgr.ensure_kb = fake_ensure_kb
        mgr._all_owner_chunks = fake_all_chunks
        mgr._sync_mem_doc = fake_sync_doc

        run(mgr.sweep("test_owner", force=True))

        self.assertIn("normal_doc", deleted_ids)
        self.assertNotIn("crucial_doc", deleted_ids)


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestAgentToolsAndManualAdd(unittest.TestCase):
    """测试 Agent 函数调用工具与 /记忆添加 指令。"""

    def setUp(self):
        self.added_records = []

        class MockMemoryMgr:
            def __init__(self):
                self.added_records = []

            async def add_memory(self, owner, text, importance=None, fact_type=None):
                self.added_records.append((owner, text, importance, fact_type))
                return True

            async def recall(self, owner, query, top_k=3):
                return [
                    {
                        "text": "用户喜欢吃清淡食物",
                        "age_days": 1.0,
                        "effective": 0.88,
                        "importance": 0.8,
                        "type": "preference",
                    }
                ]

        class MockContext:
            conversation_manager = None
            persona_manager = None

        self.plugin = Main(
            MockContext(),
            FakeConfig(
                memory_enabled=True,
                memory_agent_tools_enabled=True,
                memory_tool_memorize_enabled=True,
                memory_tool_recall_enabled=True,
            ),
        )
        self.plugin.memory = MockMemoryMgr()
        self.plugin._ensure_memory = lambda: asyncio.sleep(0, result=self.plugin.memory)
        self.plugin._group_gate = lambda event: {}
        self.plugin._gate_block_reason = lambda event: None

    def test_memorize_user_memory_tool(self):
        class MockEvent:
            unified_msg_origin = "test_user_umo"
            message_obj = type("M", (), {"group_id": None})()

        res = run(
            self.plugin.memorize_user_memory(
                MockEvent(),
                content="用户叫李华，是一名高中生",
                importance=0.9,
                fact_type="factual",
            )
        )
        self.assertIn("已成功记入长期记忆", res)
        self.assertEqual(len(self.plugin.memory.added_records), 1)
        self.assertEqual(
            self.plugin.memory.added_records[0],
            ("test_user_umo", "用户叫李华，是一名高中生", 0.9, "factual"),
        )

    def test_memorize_disabled_by_default(self):
        """测试主动记忆录入关闭时拦截。"""
        self.plugin.config = FakeConfig(
            memory_enabled=True,
            memory_agent_tools_enabled=True,
            memory_tool_memorize_enabled=False,
            memory_tool_recall_enabled=True,
        )
        class MockEvent:
            unified_msg_origin = "test_user_umo"
            message_obj = type("M", (), {"group_id": None})()

        res = run(
            self.plugin.memorize_user_memory(
                MockEvent(),
                content="用户叫李华，是一名高中生",
            )
        )
        self.assertIn("主动记录记忆工具已被管理员禁用", res)

    def test_all_agent_tools_disabled(self):
        """测试 Agent 工具总开关关闭。"""
        self.plugin.config = FakeConfig(
            memory_enabled=True,
            memory_agent_tools_enabled=False,
        )
        class MockEvent:
            unified_msg_origin = "test_user_umo"
            message_obj = type("M", (), {"group_id": None})()

        res1 = run(self.plugin.memorize_user_memory(MockEvent(), content="测试"))
        self.assertIn("Agent 记忆工具已被管理员禁用", res1)

        res2 = run(self.plugin.recall_user_memory(MockEvent(), query="测试"))
        self.assertIn("Agent 记忆工具已被管理员禁用", res2)

    def test_sync_agent_tools_state(self):
        """测试同步 AstrBot FuncTool 的 active 状态。"""
        class MockFuncTool:
            def __init__(self, name):
                self.name = name
                self.active = True

        tool_recall = MockFuncTool("recall_user_memory")
        tool_memorize = MockFuncTool("memorize_user_memory")

        class MockToolManager:
            func_list = [tool_recall, tool_memorize]

        class MockContextWithTM:
            def get_llm_tool_manager(self):
                return MockToolManager()

        self.plugin.context = MockContextWithTM()
        self.plugin.config = FakeConfig(
            memory_enabled=True,
            memory_agent_tools_enabled=True,
            memory_tool_recall_enabled=True,
            memory_tool_memorize_enabled=False,
        )
        self.plugin._sync_agent_tools_state()
        self.assertTrue(tool_recall.active)
        self.assertFalse(tool_memorize.active)

    def test_recall_user_memory_tool(self):
        class MockEvent:
            unified_msg_origin = "test_user_umo"
            message_obj = type("M", (), {"group_id": None})()

        res = run(self.plugin.recall_user_memory(MockEvent(), query="饮食偏好"))
        self.assertIn("检索到的相关用户记忆", res)
        self.assertIn("用户喜欢吃清淡食物", res)

    def test_cmd_memory_add(self):
        class MockEvent:
            unified_msg_origin = "test_user_umo"
            message_obj = type("M", (), {"group_id": None})()

            def plain_result(self, text):
                return ("PLAIN", text)

        async def _call():
            return [
                res
                async for res in self.plugin.cmd_memory_add(
                    MockEvent(), "我最喜欢的运动是羽毛球"
                )
            ]

        results = run(_call())
        self.assertEqual(len(results), 1)
        self.assertIn("已记录记忆", results[0][1])
        self.assertEqual(len(self.plugin.memory.added_records), 1)
        self.assertEqual(self.plugin.memory.added_records[0][1], "我最喜欢的运动是羽毛球")
        self.assertEqual(self.plugin.memory.added_records[0][2], 0.9)


if __name__ == "__main__":
    unittest.main(verbosity=2)

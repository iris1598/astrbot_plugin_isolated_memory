"""test_advanced_memory.py - 针对升级特性（结构化记忆、加权打分、MMR多样性、高重要性保护、Agent工具）的单元测试。"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import bootstrap

_HAS = bootstrap.bootstrap()

if _HAS:
    try:
        from astrbot_plugin_isolated_memory.memory import (
            ExtractedFact,
            MemoryManager,
            _detect_query_intent,
        )
        from astrbot_plugin_isolated_memory.main import Main
    except ImportError:
        from memory import ExtractedFact, MemoryManager, _detect_query_intent
        from main import Main
else:
    ExtractedFact = None
    MemoryManager = None
    _detect_query_intent = None
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


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestRecallOptimizations(unittest.TestCase):
    """测试召回优化（意图动态加权、类型定向加成、Rerank 模型支持、防幻觉注入协议）。"""

    def test_detect_query_intent(self):
        # 偏好意图
        p_res = _detect_query_intent("你记得我平时最爱喝什么饮料吗？")
        self.assertEqual(p_res["intent"], "preference")
        self.assertIn("preference", p_res["preferred_types"])
        self.assertGreater(p_res["weights"][1], 0.3)

        # 个人资料意图
        prof_res = _detect_query_intent("我叫什么名字？家住在哪里？")
        self.assertEqual(prof_res["intent"], "profile")
        self.assertIn("factual", prof_res["preferred_types"])

        # 计划意图
        plan_res = _detect_query_intent("下周有什么考试安排？")
        self.assertEqual(plan_res["intent"], "planned")
        self.assertIn("planned", plan_res["preferred_types"])

        # 近期意图
        rec_res = _detect_query_intent("昨天咱们聊了什么内容？")
        self.assertEqual(rec_res["intent"], "recency")
        self.assertGreaterEqual(rec_res["weights"][2], 0.4)

        # 常规意图
        gen_res = _detect_query_intent("今天外面太阳挺大的")
        self.assertEqual(gen_res["intent"], "general")

    def test_fact_type_boost_in_recall(self):
        """测试类型定向加成：当意图匹配对应类型时获得加权。"""
        now = time.time()
        docs = [
            {
                "doc_id": "pref_doc",
                "similarity": 0.85,
                "data": {
                    "doc_id": "pref_doc",
                    "text": "用户偏好喝无糖乌龙茶",
                    "updated_at": now - 30 * 86400,
                    "metadata": json.dumps({"importance": 0.8, "type": "preference"}),
                },
            },
            {
                "doc_id": "episodic_doc",
                "similarity": 0.85,
                "data": {
                    "doc_id": "episodic_doc",
                    "text": "用户昨天喝了一杯西瓜汁",
                    "updated_at": now - 30 * 86400,
                    "metadata": json.dumps({"importance": 0.8, "type": "episodic"}),
                },
            },
        ]

        class MockVecDB:
            async def retrieve(self, query, k, fetch_k, metadata_filters):
                return [
                    type("Res", (), {"similarity": d["similarity"], "data": d["data"]})()
                    for d in docs
                ]

            document_storage = type(
                "DS",
                (),
                {
                    "stopwords": set(),
                    "search_sparse": staticmethod(lambda tokens, limit: asyncio.sleep(0, result=[])),
                    "update_document_by_doc_id": staticmethod(lambda doc_id, text: asyncio.sleep(0)),
                },
            )()

        class MockKB:
            vec_db = MockVecDB()
            kb = type("K", (), {"kb_id": "test_kb", "kb_name": "test_kb", "embedding_provider_id": "ep"})()
            init_error = None

        mgr = make_manager(memory_half_life_days=14, memory_min_score=0.0)
        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())

        hits = run(mgr.recall("owner", "我最喜欢喝什么饮料？"))
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["doc_id"], "pref_doc")
        self.assertGreater(hits[0]["effective"], hits[1]["effective"])

    def test_rerank_integration_and_fallback(self):
        """测试 Rerank 模型调用及异常自动回退。"""
        now = time.time()
        docs = [
            {
                "doc_id": "doc1",
                "similarity": 0.90,
                "data": {"doc_id": "doc1", "text": "用户喜欢吃面条", "updated_at": now, "metadata": "{}"},
            },
            {
                "doc_id": "doc2",
                "similarity": 0.80,
                "data": {"doc_id": "doc2", "text": "用户讨厌吃香菜", "updated_at": now, "metadata": "{}"},
            },
        ]

        class MockVecDB:
            async def retrieve(self, query, k, fetch_k, metadata_filters):
                return [
                    type("Res", (), {"similarity": d["similarity"], "data": d["data"]})()
                    for d in docs
                ]

            document_storage = type(
                "DS",
                (),
                {
                    "stopwords": set(),
                    "search_sparse": staticmethod(lambda tokens, limit: asyncio.sleep(0, result=[])),
                    "update_document_by_doc_id": staticmethod(lambda doc_id, text: asyncio.sleep(0)),
                },
            )()

        class MockKB:
            vec_db = MockVecDB()
            kb = type("K", (), {"kb_id": "test_kb", "kb_name": "test_kb", "embedding_provider_id": "ep"})()
            init_error = None

        class MockRerankProvider:
            async def rerank(self, query, documents, top_n=None):
                return [
                    type("RR", (), {"index": 1, "relevance_score": 0.99})(),
                    type("RR", (), {"index": 0, "relevance_score": 0.10})(),
                ]

        mgr = make_manager(memory_rerank_enabled=True, memory_min_score=0.0)
        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
        mgr._get_rerank_provider = lambda: MockRerankProvider()

        hits = run(mgr.recall("owner", "测试查询"))
        self.assertEqual(hits[0]["doc_id"], "doc2")

        class FailingRerankProvider:
            async def rerank(self, query, documents, top_n=None):
                raise RuntimeError("API timeout")

        mgr._get_rerank_provider = lambda: FailingRerankProvider()
        fallback_hits = run(mgr.recall("owner", "测试查询"))
        self.assertEqual(len(fallback_hits), 2)
        self.assertEqual(fallback_hits[0]["doc_id"], "doc1")

    def test_format_injection_anti_hallucination_protocol(self):
        """测试防幻觉与冲突抑制注入格式。"""
        mgr = make_manager(memory_inject_max_chars=1000)
        hits = [
            {"text": "用户喜欢喝美式", "age_days": 0.5, "type": "preference"},
            {"text": "下周五去北京参加学术会议", "age_days": 2.0, "type": "planned"},
        ]
        formatted = mgr.format_injection(hits)
        self.assertIn("--- BEGIN USER BACKGROUND MEMORY ---", formatted)
        self.assertIn("【历史记忆参考】", formatted)
        self.assertIn("- [用户偏好/禁忌] 用户喜欢喝美式（今天）", formatted)
        self.assertIn("- [既定计划/日程] 下周五去北京参加学术会议（约2天前）", formatted)
        self.assertIn("【防幻觉与冲突准则】：", formatted)
        self.assertIn("必须无条件以用户当前的最新表述为准", formatted)
        self.assertIn("--- END USER BACKGROUND MEMORY ---", formatted)


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestMemoryUpgrade(unittest.TestCase):
    """测试存量历史记忆全量原子化重构与属性升级。"""

    def test_build_upgrade_prompt(self):
        mgr = make_manager()
        docs = [
            {"text": "用户喜欢吃辣"},
            {"text": "用户目前在杭州做前端开发"},
        ]
        prompt = mgr._build_upgrade_prompt(docs, user_name="测试者")
        self.assertIn("测试者", prompt)
        self.assertIn("<raw_memories>", prompt)
        self.assertIn("1. 用户喜欢吃辣", prompt)
        self.assertIn("2. 用户目前在杭州做前端开发", prompt)
        self.assertIn("preference", prompt)
        self.assertIn("factual", prompt)
        self.assertIn("planned", prompt)
        self.assertIn("episodic", prompt)

    def test_upgrade_memories_success(self):
        mgr = make_manager()
        deleted_owners = []
        inserted_items = []

        class MockVecDB:
            async def delete_documents(self, metadata_filters=None):
                if metadata_filters and "memory_owner" in metadata_filters:
                    deleted_owners.append(metadata_filters["memory_owner"])

            async def insert(self, content, metadata=None):
                inserted_items.append((content, metadata))

            async def count_documents(self, metadata_filter=None):
                return len(inserted_items)

        class MockKB:
            vec_db = MockVecDB()

            class kb:
                kb_id = "test_kb_id"

        async def fake_ensure_kb():
            return MockKB()

        async def fake_all_chunks(vec_db, owner):
            return [
                {"text": "用户特别喜欢喝无糖乌龙茶"},
                {"text": "用户在上海做后端开发，主要用Python"},
            ]

        async def fake_llm_chat(prompt, provider_id=None, timeout=None, umo=""):
            return (
                '[\n'
                '  {"content": "用户偏好饮用无糖乌龙茶", "importance": 0.75, "fact_type": "preference"},\n'
                '  {"content": "用户在上海从事后端开发，主力语言为Python", "importance": 0.90, "fact_type": "factual"}\n'
                ']'
            )

        mgr.ensure_kb = fake_ensure_kb
        mgr._all_owner_chunks = fake_all_chunks
        mgr._llm_chat = fake_llm_chat
        mgr._ensure_mem_doc = lambda kb, owner: asyncio.sleep(0, result="mem_doc_1")
        mgr._refresh_stats = lambda kb: asyncio.sleep(0)
        mgr._sync_mem_doc = lambda kb, owner: asyncio.sleep(0)

        res = run(mgr.upgrade_memories("test_owner", user_name="小明"))
        self.assertTrue(res["success"])
        self.assertEqual(res["before_count"], 2)
        self.assertEqual(res["after_count"], 2)
        self.assertEqual(res["type_counts"]["preference"], 1)
        self.assertEqual(res["type_counts"]["factual"], 1)
        self.assertEqual(res["protected_count"], 1)  # 0.90 >= 0.85
        self.assertIn("test_owner", deleted_owners)
        self.assertEqual(len(inserted_items), 2)
        self.assertEqual(inserted_items[1][1]["importance"], 0.90)
        self.assertEqual(inserted_items[1][1]["type"], "factual")

    def test_upgrade_memories_empty(self):
        mgr = make_manager()

        class MockKB:
            vec_db = None

        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
        mgr._all_owner_chunks = lambda vec_db, owner: asyncio.sleep(0, result=[])

        res = run(mgr.upgrade_memories("empty_owner"))
        self.assertTrue(res["success"])
        self.assertEqual(res["before_count"], 0)
        self.assertEqual(res["after_count"], 0)

    def test_upgrade_memories_llm_failure_safety(self):
        mgr = make_manager()
        deleted_owners = []

        class MockVecDB:
            async def delete_documents(self, metadata_filters=None):
                deleted_owners.append(metadata_filters)

        class MockKB:
            vec_db = MockVecDB()

        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
        mgr._all_owner_chunks = lambda vec_db, owner: asyncio.sleep(
            0, result=[{"text": "重要记忆"}]
        )
        mgr._llm_chat = lambda prompt, provider_id=None, timeout=None, umo="": asyncio.sleep(
            0, result=""
        )

        res = run(mgr.upgrade_memories("fail_owner"))
        self.assertFalse(res["success"])
        self.assertEqual(len(deleted_owners), 0)  # 原有记忆安全保留，未删除

    def test_cmd_memory_upgrade_dispatch(self):
        class MockMemoryMgr:
            async def upgrade_memories(self, owner, user_name="", umo=""):
                return {
                    "success": True,
                    "message": "记忆升级成功",
                    "before_count": 3,
                    "after_count": 2,
                    "type_counts": {"preference": 1, "factual": 1},
                    "protected_count": 1,
                    "sample_facts": ["[preference] 喜好", "[factual] 资料"],
                }

        class MockContext:
            conversation_manager = None
            persona_manager = None

        plugin = Main(MockContext(), FakeConfig(memory_enabled=True))
        plugin.memory = MockMemoryMgr()
        plugin._ensure_memory = lambda: asyncio.sleep(0, result=plugin.memory)
        plugin._group_gate = lambda event: {}
        plugin._gate_block_reason = lambda event: None

        class FakeEvent:
            unified_msg_origin = "test_umo"

            def get_sender_name(self):
                return "测试用户"

            def plain_result(self, text):
                return text

        async def _test():
            results = []
            async for r in plugin.cmd_memory_upgrade(FakeEvent()):
                results.append(r)
            return results

        results = run(_test())
        self.assertTrue(any("记忆结构化升级完成" in r for r in results))
        self.assertTrue(any("原始记忆: 3 条" in r for r in results))
        self.assertTrue(any("重构后原子记忆: 2 条" in r for r in results))


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestAdminBackupAndBatchUpgrade(unittest.TestCase):
    """测试管理员记忆全量备份与全员一键升级。"""

    def test_backup_all_memories_and_list(self):
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            mgr = make_manager()

            class MockKB:
                class kb:
                    kb_id = "kb_backup_test"
                    kb_name = "测试库"
                vec_db = None

            mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
            mgr.get_all_memory_owners = lambda: asyncio.sleep(0, result=["user_a", "user_b"])

            async def fake_all_chunks(vec_db, owner):
                if owner == "user_a":
                    return [{"text": "记忆A1", "updated_at": 100, "metadata": {}}]
                return [
                    {"text": "记忆B1", "updated_at": 100, "metadata": {}},
                    {"text": "记忆B2", "updated_at": 105, "metadata": {}},
                ]

            mgr._all_owner_chunks = fake_all_chunks

            res = run(mgr.backup_all_memories(backup_dir=tmpdir))
            self.assertTrue(res["success"])
            self.assertEqual(res["owners_count"], 2)
            self.assertEqual(res["total_chunks"], 3)
            self.assertTrue(os.path.exists(res["file_path"]))

            with open(res["file_path"], "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["total_owners"], 2)
            self.assertEqual(data["total_chunks"], 3)
            self.assertIn("user_a", data["memories"])
            self.assertIn("user_b", data["memories"])

            backups = mgr.list_backups(backup_dir=tmpdir)
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]["file_name"], res["file_name"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_backup_dir_uses_plugin_data_and_migrates_legacy(self):
        """测试备份目录遵循 AstrBot 规范（存放在 plugin_data，并可无损迁移旧 plugins 目录下的文件）。"""
        mgr = make_manager()
        with tempfile.TemporaryDirectory() as tmp_base:
            old_plugins_dir = os.path.join(tmp_base, "plugins", "astrbot_plugin_isolated_memory", "backups")
            expected_plugin_data_dir = os.path.join(tmp_base, "plugin_data", "astrbot_plugin_isolated_memory", "backups")
            os.makedirs(old_plugins_dir, exist_ok=True)

            legacy_file = os.path.join(old_plugins_dir, "memory_backup_20261001_100000.json")
            with open(legacy_file, "w", encoding="utf-8") as f:
                f.write('{"backup_version": 1}')

            # 模拟 get_astrbot_data_path 返回 tmp_base
            with unittest.mock.patch("astrbot.core.utils.astrbot_path.get_astrbot_data_path", return_value=tmp_base, create=True):
                # 同时也 patch StarTools 抛异常以测试 base_data fallback 逻辑
                with unittest.mock.patch("astrbot.api.star.StarTools.get_data_dir", side_effect=RuntimeError("no StarTools")):
                    res_dir = mgr._get_backup_dir()
                    self.assertEqual(os.path.abspath(res_dir), os.path.abspath(expected_plugin_data_dir))
                    self.assertNotIn("data" + os.sep + "plugins", res_dir)
                    self.assertIn("plugin_data", res_dir)
                    # 验证旧文件被平移到新持久化目录
                    migrated_file = os.path.join(res_dir, "memory_backup_20261001_100000.json")
                    self.assertTrue(os.path.exists(migrated_file))

    def test_upgrade_all_memories(self):
        mgr = make_manager()

        class MockKB:
            vec_db = None

        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
        mgr.backup_all_memories = lambda: asyncio.sleep(
            0, result={"success": True, "file_name": "auto_backup.json"}
        )
        mgr.get_all_memory_owners = lambda: asyncio.sleep(0, result=["user_1", "user_2"])
        mgr._all_owner_chunks = lambda vec_db, owner: asyncio.sleep(
            0, result=[{"text": "记忆"}]
        )

        async def fake_upgrade(owner, user_name="", umo=""):
            return {
                "success": True,
                "before_count": 2,
                "after_count": 1,
                "type_counts": {"preference": 1},
                "protected_count": 1,
                "sample_facts": ["fact"],
            }

        mgr.upgrade_memories = fake_upgrade

        res = run(mgr.upgrade_all_memories())
        self.assertTrue(res["success"])
        self.assertEqual(res["total_users"], 2)
        self.assertEqual(res["success_users"], 2)
        self.assertEqual(res["before_chunks"], 4)
        self.assertEqual(res["after_chunks"], 2)
        self.assertEqual(res["type_counts"]["preference"], 2)
        self.assertEqual(res["protected_count"], 2)

    def test_admin_commands_permission_and_dispatch(self):
        class MockMemoryMgr:
            async def backup_all_memories(self):
                return {
                    "success": True,
                    "file_name": "backup_20261006.json",
                    "owners_count": 2,
                    "total_chunks": 5,
                    "file_size_kb": 1.2,
                    "file_path": "/path/backup_20261006.json",
                }

            def list_backups(self):
                return [
                    {
                        "file_name": "backup_20261006.json",
                        "file_size_kb": 1.2,
                        "created_at": "2026-10-06 00:00:00",
                    }
                ]

            async def upgrade_all_memories(self, progress_callback=None, umo=""):
                return {
                    "success": True,
                    "backup_result": {"file_name": "auto_snap.json"},
                    "total_users": 2,
                    "success_users": 2,
                    "failed_users": [],
                    "before_chunks": 6,
                    "after_chunks": 4,
                    "type_counts": {"preference": 2, "factual": 2},
                    "protected_count": 2,
                }

        class MockContext:
            conversation_manager = None
            persona_manager = None

        plugin = Main(MockContext(), FakeConfig(memory_enabled=True))
        plugin.memory = MockMemoryMgr()
        plugin._ensure_memory = lambda: asyncio.sleep(0, result=plugin.memory)
        plugin._group_gate = lambda event: {}
        plugin._gate_block_reason = lambda event: None

        class MemberEvent:
            role = "member"
            unified_msg_origin = "member_umo"
            def is_admin(self): return False
            def get_sender_id(self): return "1001"
            def get_sender_name(self): return "普通成员"
            def plain_result(self, text): return text

        class AdminEvent:
            role = "admin"
            unified_msg_origin = "admin_umo"
            def is_admin(self): return True
            def get_sender_id(self): return "1000"
            def get_sender_name(self): return "管理员"
            def plain_result(self, text): return text

        # 1. 验证普通成员被拦截
        async def _test_member_backup():
            res = []
            async for r in plugin.cmd_memory_backup(MemberEvent()):
                res.append(r)
            return res

        r_mem = run(_test_member_backup())
        self.assertTrue(any("权限不足" in r for r in r_mem))

        async def _test_member_upgrade_all():
            res = []
            async for r in plugin.cmd_memory_upgrade_all(MemberEvent()):
                res.append(r)
            return res

        r_mem_up = run(_test_member_upgrade_all())
        self.assertTrue(any("权限不足" in r for r in r_mem_up))

        # 2. 验证管理员执行备份
        async def _test_admin_backup():
            res = []
            async for r in plugin.cmd_memory_backup(AdminEvent()):
                res.append(r)
            return res

        r_adm_bak = run(_test_admin_backup())
        self.assertTrue(any("记忆全量备份完成" in r for r in r_adm_bak))

        # 3. 验证管理员列出备份
        async def _test_admin_list_backup():
            res = []
            async for r in plugin.cmd_memory_backup(AdminEvent(), action="列表"):
                res.append(r)
            return res

        r_adm_list = run(_test_admin_list_backup())
        self.assertTrue(any("历史记忆备份列表" in r for r in r_adm_list))

        # 4. 验证管理员执行全员升级
        async def _test_admin_upgrade_all():
            res = []
            async for r in plugin.cmd_memory_upgrade_all(AdminEvent()):
                res.append(r)
            return res

        r_adm_up = run(_test_admin_upgrade_all())
        self.assertTrue(any("全员记忆结构化升级完成" in r for r in r_adm_up))

        # 5. 验证管理员输入 /记忆升级 全部 自动代理到全员升级
        async def _test_admin_upgrade_target_all():
            res = []
            async for r in plugin.cmd_memory_upgrade(AdminEvent(), target="全部"):
                res.append(r)
            return res

        r_adm_all_param = run(_test_admin_upgrade_target_all())
        self.assertTrue(any("全员记忆结构化升级完成" in r for r in r_adm_all_param))


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestMemoryRestore(unittest.TestCase):
    """测试记忆恢复功能。"""

    def test_restore_memories_success(self):
        mgr = make_manager()
        deleted_owners = []
        inserted_items = []

        class MockVecDB:
            async def delete_documents(self, metadata_filters=None):
                if metadata_filters and "memory_owner" in metadata_filters:
                    deleted_owners.append(metadata_filters["memory_owner"])

            async def insert(self, content, metadata=None):
                inserted_items.append((content, metadata))

            async def count_documents(self, metadata_filter=None):
                return len(inserted_items)

        class MockKB:
            vec_db = MockVecDB()
            class kb:
                kb_id = "test_kb_id"

        mgr.ensure_kb = lambda: asyncio.sleep(0, result=MockKB())
        mgr._ensure_mem_doc = lambda kb, owner: asyncio.sleep(0, result="mem_doc_1")
        mgr._refresh_stats = lambda kb: asyncio.sleep(0)
        mgr._sync_mem_doc = lambda kb, owner: asyncio.sleep(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_data = {
                "backup_version": 1,
                "created_at": "2026-10-05T12:00:00",
                "memories": {
                    "user_a": [
                        {"text": "用户喜欢吃面条", "updated_at": 100, "metadata": {"type": "preference", "importance": 0.8}},
                        {"text": "用户在杭州", "updated_at": 101, "metadata": {"type": "factual", "importance": 0.9}},
                    ],
                    "user_b": [
                        {"text": "用户在北京", "updated_at": 102, "metadata": {"type": "factual", "importance": 0.7}},
                    ]
                }
            }
            bf = os.path.join(tmpdir, "memory_backup_20261005_120000.json")
            with open(bf, "w", encoding="utf-8") as f:
                json.dump(backup_data, f)

            # 1. 覆盖恢复全员
            res = run(mgr.restore_memories_from_backup(
                backup_identifier="1",
                mode="overwrite",
                backup_dir=tmpdir,
            ))
            self.assertTrue(res["success"])
            self.assertEqual(res["restored_owners"], 2)
            self.assertEqual(res["restored_chunks"], 3)
            self.assertIn("user_a", deleted_owners)
            self.assertIn("user_b", deleted_owners)

            # 2. 单独恢复 user_a
            inserted_items.clear()
            deleted_owners.clear()
            res_single = run(mgr.restore_memories_from_backup(
                backup_identifier="1",
                mode="overwrite",
                target_owner="user_a",
                backup_dir=tmpdir,
            ))
            self.assertTrue(res_single["success"])
            self.assertEqual(res_single["restored_owners"], 1)
            self.assertEqual(res_single["restored_chunks"], 2)
            self.assertEqual(deleted_owners, ["user_a"])

    def test_cmd_memory_restore_permissions_and_output(self):
        class MockMemoryMgr:
            def list_backups(self, backup_dir=None):
                return [{
                    "file_name": "memory_backup_20261005_120000.json",
                    "file_path": "/fake/memory_backup_20261005_120000.json",
                    "file_size_kb": 12.5,
                    "created_at": "2026-10-05 12:00:00",
                }]

            async def restore_memories_from_backup(self, backup_identifier="1", mode="overwrite", target_owner=None):
                return {
                    "success": True,
                    "message": "记忆恢复成功",
                    "file_name": "memory_backup_20261005_120000.json",
                    "mode": mode,
                    "restored_owners": 2,
                    "restored_chunks": 5,
                    "skipped_chunks": 0,
                    "auto_backup_file": "memory_backup_pre_restore.json",
                }

        class MockContext:
            conversation_manager = None
            persona_manager = None

        plugin = Main(MockContext(), FakeConfig(memory_enabled=True))
        plugin.memory = MockMemoryMgr()
        plugin._ensure_memory = lambda: asyncio.sleep(0, result=plugin.memory)

        class MemberEvent:
            role = "member"
            def is_admin(self): return False
            def get_sender_id(self): return "1001"
            def plain_result(self, text): return text

        class AdminEvent:
            role = "admin"
            def is_admin(self): return True
            def get_sender_id(self): return "1000"
            def plain_result(self, text): return text

        # 普通用户拦截
        async def _test_member():
            res = []
            async for r in plugin.cmd_memory_restore(MemberEvent()):
                res.append(r)
            return res

        r_mem = run(_test_member())
        self.assertTrue(any("权限不足" in r for r in r_mem))

        # 管理员无参数列出备份
        async def _test_admin_list():
            res = []
            async for r in plugin.cmd_memory_restore(AdminEvent()):
                res.append(r)
            return res

        r_adm_list = run(_test_admin_list())
        self.assertTrue(any("可用记忆备份列表" in r for r in r_adm_list))

        # 管理员指定备份恢复
        async def _test_admin_restore():
            res = []
            async for r in plugin.cmd_memory_restore(AdminEvent(), target="1"):
                res.append(r)
            return res

        r_adm_restore = run(_test_admin_restore())
        self.assertTrue(any("记忆恢复完成" in r for r in r_adm_restore))
        self.assertTrue(any("恢复用户数: 2 位" in r for r in r_adm_restore))


if __name__ == "__main__":
    unittest.main(verbosity=2)



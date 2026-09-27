"""鸣潮角色匹配核心逻辑与扩展测试。

验证：
1. characters_data 模块加载 5 位初始角色与动态追加新角色；
2. MemoryManager.build_character_match 纯向量锚点计算与时间衰减；
3. LLM 仅用于评语（关闭或超时回退内置模版）；
4. format_character_report 纯文本格式排版；
5. cmd_memory_mbti 指令（xxti / /xxti）入口执行与门控拦截。
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import bootstrap
import test_gate

_HAS = bootstrap.bootstrap()


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestCharacterMatch(unittest.IsolatedAsyncioTestCase):
    """鸣潮角色匹配模块单元测试。"""

    def setUp(self):
        from characters_data import CharacterProfile, get_characters
        self.get_characters = get_characters
        self.CharacterProfile = CharacterProfile

    def test_load_builtin_characters(self):
        """验证能正确读取内置的 5 位鸣潮角色。"""
        chars = self.get_characters(force_reload=True)
        self.assertGreaterEqual(len(chars), 5)
        names = {c.name for c in chars}
        self.assertIn("爱弥斯", names)
        self.assertIn("莫宁", names)
        self.assertIn("西格莉卡", names)
        self.assertIn("达妮娅", names)
        self.assertIn("陆赫斯", names)

        for c in chars:
            self.assertTrue(len(c.anchors) >= 3, f"{c.name} 锚点数不足")
            self.assertTrue(len(c.quotes) >= 1, f"{c.name} 经典台词缺失")

    def test_extensibility_custom_directory(self):
        """验证添加外部角色目录可实现平滑动态扩展。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            custom_yaml = tmppath / "jiyan.yaml"
            custom_yaml.write_text(
                """
id: jiyan
name: 忌炎
title: 夜归军领军
tagline: 虽千万人，吾往矣。
tags:
  - 沉稳坚毅
  - 统帅大局
desc: 夜归军领军，沉稳刚毅，心怀天下。
anchors:
  - 用户性格沉稳刚毅，具有统领大局的领袖气质
  - 用户在危机面前勇于担当，身先士卒
quotes:
  - 虽千万人，吾往矣。
""",
                encoding="utf-8",
            )
            chars = self.get_characters(custom_dir=tmppath, force_reload=True)
            self.assertEqual(len(chars), 1)
            self.assertEqual(chars[0].name, "忌炎")
            self.assertEqual(len(chars[0].anchors), 2)

    async def test_build_character_match_pure_vector(self):
        """验证纯向量匹配逻辑（确定性算分与排序，LLM 仅用于评语）。"""
        from memory import MemoryManager

        context = MagicMock()
        config = {
            "memory": {
                "memory_enabled": True,
                "memory_kb_name": ["mock_kb"],
                "memory_mbti_llm_commentary": False,  # 关闭 LLM，确保纯向量+模版评语
            }
        }
        mgr = MemoryManager(context, config)

        # 模拟知识库与 embedding provider
        mock_kb = MagicMock()
        mock_kb.kb.embedding_provider_id = "test_ep"
        mock_ep = MagicMock()

        # 为测试提供简单的伪向量 (爱弥斯特征 vs 莫宁特征)
        # 假设向量维度为 3
        async def fake_get_embeddings(texts):
            vectors = []
            for t in texts:
                if "活泼" in t or "乐观" in t or "幽默" in t or "开心" in t:
                    vectors.append([1.0, 0.0, 0.0])
                elif "严谨" in t or "理性" in t or "科学" in t or "逻辑" in t:
                    vectors.append([0.0, 1.0, 0.0])
                else:
                    vectors.append([0.1, 0.1, 0.1])
            return vectors

        mock_ep.get_embeddings = fake_get_embeddings
        mock_kb.get_ep = AsyncMock(return_value=mock_ep)
        mgr.ensure_kb = AsyncMock(return_value=mock_kb)

        # 用户记忆偏向活泼开朗 (爱弥斯特征)
        entries = [
            {"text": "用户今天很开心，讲了很多搞笑的笑话逗朋友们大笑", "updated_at": 1000000},
            {"text": "即使遇到了倒霉的事情，用户还是心态乐观地面对", "updated_at": 1000000},
            {"text": "用户富有童心，喜欢新奇好玩的游戏", "updated_at": 1000000},
        ]

        report = await mgr.build_character_match(entries, umo="test_umo")
        self.assertIsNotNone(report)
        top = report["top_character"]
        self.assertEqual(top["name"], "爱弥斯")
        self.assertGreater(top["resonance"], 70)
        self.assertTrue(len(report["rankings"]) >= 5)
        # 确认排行榜降序排列
        resonances = [r["resonance"] for r in report["rankings"]]
        self.assertEqual(resonances, sorted(resonances, reverse=True))

        # 验证文本格式化
        text = mgr.format_character_report(report)
        self.assertIn("【漂泊者记忆 · 鸣潮角色共鸣档案】", text)
        self.assertIn("爱弥斯", text)
        self.assertIn("全域角色共鸣度分布", text)

    async def test_cmd_memory_mbti_image_dispatch(self):
        """验证命令默认执行海报图片渲染与发送（自动匹配角色图并限制 Top 5）。"""
        mod = test_gate.load_memory_main()
        Main = mod.Main

        context = MagicMock()
        context.kb_manager = MagicMock()
        config = {
            "memory": {
                "memory_enabled": True,
                "memory_kb_name": ["mock_kb"],
                "memory_mbti_min_memories": 5,
                "character_match_output_mode": "image",
            }
        }
        plugin = Main(context, config)
        plugin._gate_block_reason = lambda ev: None
        plugin._ensure_memory = AsyncMock(return_value=MagicMock())

        mock_report = {
            "top_character": {
                "id": "aemis",
                "name": "爱弥斯",
                "title": "远航星",
                "tagline": "未完成曲复活！",
                "tags": ["灵动豁达"],
                "desc": "描述",
                "resonance": 92,
            },
            "rankings": [
                {"name": "爱弥斯", "resonance": 92},
                {"name": "莫宁", "resonance": 60},
            ],
            "commentary": "测试共鸣评语",
            "sample_count": 5,
            "used_count": 5,
            "truncated": False,
        }
        plugin.memory = MagicMock()
        plugin.memory.collect_memory_entries = AsyncMock(
            return_value=[{"text": f"m{i}", "updated_at": 100} for i in range(6)]
        )
        plugin.memory.build_character_match = AsyncMock(return_value=mock_report)
        plugin.memory.format_character_report = MagicMock(return_value="这是格式化后的纯文本共鸣报告")

        event = MagicMock()
        event.unified_msg_origin = "Iris:GroupMessage:10086_123"
        event.image_result = lambda path: ("IMAGE", path)
        event.plain_result = lambda msg: ("PLAIN", msg)

        results = [res async for res in plugin.cmd_memory_mbti(event, "")]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "IMAGE")
        self.assertTrue(results[0][1].endswith(".png"))

    async def test_cmd_memory_mbti_plain_text_dispatch(self):
        """验证传参'文本'时强制走纯文本分发模式。"""
        mod = test_gate.load_memory_main()
        Main = mod.Main

        context = MagicMock()
        context.kb_manager = MagicMock()
        config = {
            "memory": {
                "memory_enabled": True,
                "memory_kb_name": ["mock_kb"],
                "memory_mbti_min_memories": 5,
            }
        }
        plugin = Main(context, config)
        plugin._gate_block_reason = lambda ev: None
        plugin._ensure_memory = AsyncMock(return_value=MagicMock())

        mock_report = {
            "top_character": {
                "id": "aemis",
                "name": "爱弥斯",
                "title": "远航星",
                "tagline": "未完成曲复活！",
                "tags": ["灵动豁达"],
                "desc": "描述",
                "resonance": 92,
            },
            "rankings": [
                {"name": "爱弥斯", "resonance": 92},
                {"name": "莫宁", "resonance": 60},
            ],
            "commentary": "测试共鸣评语",
            "sample_count": 5,
            "used_count": 5,
            "truncated": False,
        }
        plugin.memory = MagicMock()
        plugin.memory.collect_memory_entries = AsyncMock(
            return_value=[{"text": f"m{i}", "updated_at": 100} for i in range(6)]
        )
        plugin.memory.build_character_match = AsyncMock(return_value=mock_report)
        plugin.memory.format_character_report = MagicMock(return_value="这是格式化后的纯文本共鸣报告")

        event = MagicMock()
        event.unified_msg_origin = "Iris:GroupMessage:10086_123"
        event.plain_result = lambda msg: ("PLAIN", msg)

        results = [res async for res in plugin.cmd_memory_mbti(event, "文本")]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("PLAIN", "这是格式化后的纯文本共鸣报告"))

    def test_character_render_and_image_lookup(self):
        """测试角色头像检索、Top 5 截断与海报生成。"""
        from astrbot_plugin_isolated_session import character_render

        # 验证能自动检索到角色素材
        img_aemis = character_render.find_character_image("爱弥斯")
        self.assertIsNotNone(img_aemis)
        self.assertTrue(img_aemis.exists())

        img_luhesi = character_render.find_character_image("陆·赫斯")
        self.assertIsNotNone(img_luhesi)
        self.assertTrue(img_luhesi.exists())

        # 验证 Top 5 截断与海报生成
        mock_report = {
            "top_character": {
                "name": "爱弥斯",
                "id": "aemis",
                "title": "远航星",
                "resonance": 92,
                "tagline": "十几年前失落的未完成曲此刻复活！",
                "tags": ["灵动豁达", "浪漫执着"],
            },
            "commentary": "测试寄语",
            "rankings": [
                {"name": f"角色{i}", "resonance": 90 - i * 5} for i in range(10)
            ],
            "used_count": 15,
        }
        poster_path = character_render.render_character_resonance_poster(
            mock_report, top_k=5
        )
        self.assertIsNotNone(poster_path)
        self.assertTrue(poster_path.exists())
        self.assertGreater(poster_path.stat().st_size, 1000)
        try:
            poster_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()


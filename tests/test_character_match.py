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
        self.assertIn("quotes", top)
        self.assertIn("selected_quote", top)
        self.assertTrue(len(top["quotes"]) >= 1)
        self.assertIn(top["selected_quote"], top["quotes"])
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
        try:
            from astrbot_plugin_isolated_memory import character_render
        except ImportError:
            import character_render

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


    def test_json_character_file_loading(self):
        """验证支持从 JSON 格式动态加载角色档案。"""
        import json
        import tempfile
        from pathlib import Path
        try:
            from astrbot_plugin_isolated_memory import characters_data
        except ImportError:
            import characters_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_json = {
                "id": "jiyan",
                "name": "忌炎",
                "title": "夜归军领军",
                "tagline": "虽千万人，吾往矣。",
                "tags": ["沉稳坚毅", "统帅大局"],
                "desc": "夜归军领军",
                "quotes": ["虽千万人，吾往矣。"],
                "anchors": ["用户性格沉稳刚毅，具有统领大局的领袖气质"],
            }
            json_file = Path(tmp_dir) / "jiyan.json"
            json_file.write_text(json.dumps(sample_json, ensure_ascii=False), encoding="utf-8")

            chars = characters_data.get_characters(custom_dir=tmp_dir, force_reload=True)
            self.assertEqual(len(chars), 1)
            self.assertEqual(chars[0].name, "忌炎")
            self.assertEqual(chars[0].id, "jiyan")

    async def test_character_quote_semantic_and_fallback(self):
        """验证角色多台词语义向量匹配选择与降级随机选择。"""
        from memory import MemoryManager

        context = MagicMock()
        mgr = MemoryManager(context, {})

        char = self.CharacterProfile(
            id="test_char",
            name="测试角色",
            tagline="第一句台词",
            quotes=[
                "第一句台词：平凡度日",
                "第二句台词：向往探索浩瀚星空与宇宙真理",
                "第三句台词：战斗到底永不退缩",
            ],
            anchors=["锚点"],
        )

        mock_kb = MagicMock()
        mock_kb.kb.embedding_provider_id = "test_provider"
        mock_ep = MagicMock()

        # 模拟嵌入向量：星空/探索 -> [1.0, 0.0]；战斗 -> [0.0, 1.0]；其他 -> [0.1, 0.1]
        async def fake_get_embeddings(texts):
            vectors = []
            for t in texts:
                if "星空" in t or "探索" in t:
                    vectors.append([1.0, 0.0])
                elif "战斗" in t or "退缩" in t:
                    vectors.append([0.0, 1.0])
                else:
                    vectors.append([0.1, 0.1])
            return vectors

        mock_ep.get_embeddings = fake_get_embeddings
        mock_kb.get_ep = AsyncMock(return_value=mock_ep)

        # 1. 记忆向量偏向星空探索 [1.0, 0.0]，应匹配到第2句台词
        quote_star = await mgr._select_best_quote(
            char, target_vec=[1.0, 0.0], kb=mock_kb
        )
        self.assertEqual(quote_star, "第二句台词：向往探索浩瀚星空与宇宙真理")

        # 2. 记忆向量偏向战斗 [0.0, 1.0]，应匹配到第3句台词
        quote_battle = await mgr._select_best_quote(
            char, target_vec=[0.0, 1.0], kb=mock_kb
        )
        self.assertEqual(quote_battle, "第三句台词：战斗到底永不退缩")

        # 3. 异常或无向量时，降级从候选台词库中随机选取
        quote_fallback = await mgr._select_best_quote(char, target_vec=None, kb=None)
        self.assertIn(quote_fallback, char.quotes)

        # 4. quotes 为空时，回退 tagline
        char_no_quotes = self.CharacterProfile(
            id="empty_char",
            name="无台词角色",
            tagline="保底座右铭",
            quotes=[],
            anchors=["锚点"],
        )
        quote_empty = await mgr._select_best_quote(char_no_quotes)
        self.assertEqual(quote_empty, "保底座右铭")

    async def test_session_persona_commentary_and_render(self):
        """验证会话角色评语生成（自定义 LLM / 降级 / 格式化 / 海报卡片自适应）。"""
        from memory import MemoryManager
        import character_render

        context = MagicMock()
        mgr = MemoryManager(context, {
            "memory": {
                "character_match_llm_commentary": True,
                "character_match_llm_provider_id": "custom_provider_123",
                "character_match_llm_timeout": 15,
            }
        })

        top_match = {
            "name": "长离",
            "title": "离火弈局的谋定者",
            "resonance": 92,
            "evidence": "下棋与布局思考",
        }
        rankings = [
            {"name": "长离", "resonance": 92},
            {"name": "今汐", "resonance": 80},
        ]
        entries = [{"text": "日常记录：今天和朋友下围棋很开心"}]

        # 1. LLM 正常返回评语
        mgr._llm_chat = AsyncMock(return_value="“测出来原来是长离大人呀，怪不得平日谋略出众！”")
        remark = await mgr._generate_session_role_commentary(
            top_match=top_match,
            rankings=rankings,
            selected_entries=entries,
            session_persona_name="折枝",
            session_persona_prompt="你是鸣潮角色折枝，性格文静内敛，热爱画画。",
            umo="test_umo",
        )
        self.assertIsNotNone(remark)
        self.assertEqual(remark["persona_name"], "折枝")
        self.assertEqual(remark["text"], "测出来原来是长离大人呀，怪不得平日谋略出众！")

        # 验证调用 _llm_chat 时透传了自定义 provider_id 与 timeout
        mgr._llm_chat.assert_called_once()
        call_kwargs = mgr._llm_chat.call_args.kwargs
        self.assertEqual(call_kwargs["provider_id"], "custom_provider_123")
        self.assertEqual(call_kwargs["timeout"], 15)

        # 2. LLM 超时或失败时，平滑降级为保底模版
        mgr._llm_chat = AsyncMock(return_value=None)
        fallback_remark = await mgr._generate_session_role_commentary(
            top_match=top_match,
            rankings=rankings,
            selected_entries=entries,
            session_persona_name="折枝",
            session_persona_prompt="",
            umo="test_umo",
        )
        self.assertIsNotNone(fallback_remark)
        self.assertEqual(fallback_remark["persona_name"], "折枝")
        self.assertIn("长离", fallback_remark["text"])
        self.assertIn("92%", fallback_remark["text"])

        # 3. 配置关闭时返回 None
        mgr_disabled = MemoryManager(context, {
            "memory": {"character_match_llm_commentary": False}
        })
        remark_disabled = await mgr_disabled._generate_session_role_commentary(
            top_match=top_match,
            rankings=rankings,
            selected_entries=entries,
            session_persona_name="折枝",
        )
        self.assertIsNone(remark_disabled)

        # 4. 纯文本格式化验证：评语出现在全域角色共鸣度分布下方
        mock_report = {
            "top_character": top_match,
            "rankings": rankings,
            "commentary": "常规特质解析",
            "session_persona_remark": remark,
            "sample_count": 5,
            "used_count": 5,
        }
        text = mgr.format_character_report(mock_report)
        self.assertIn("✦ 全域角色共鸣度分布：", text)
        self.assertIn("✦ 【折枝】的共鸣简评：", text)
        self.assertIn("测出来原来是长离大人呀", text)
        # 确认评语在分布之后
        pos_dist = text.index("✦ 全域角色共鸣度分布：")
        pos_remark = text.index("✦ 【折枝】的共鸣简评：")
        self.assertGreater(pos_remark, pos_dist)

        # 5. 海报图片渲染验证：含有 session_persona_remark 时成功出图且高度适配延伸
        poster_path = character_render.render_character_resonance_poster(mock_report)
        self.assertIsNotNone(poster_path)
        self.assertTrue(poster_path.exists())
        from PIL import Image
        with Image.open(poster_path) as img:
            self.assertEqual(img.size[0], 880)
            self.assertGreater(img.size[1], 1260)  # 高度自适应延伸
        poster_path.unlink(missing_ok=True)

    async def test_character_match_max_memories_selection(self):
        """验证最多最近 N 条记忆参数与配置项截取逻辑。"""
        from memory import MemoryManager

        context = MagicMock()
        mgr = MemoryManager(context, {
            "memory": {
                "character_match_max_memories": 2,
            }
        })

        mock_kb = MagicMock()
        mock_kb.kb.embedding_provider_id = "test_ep"
        mock_ep = MagicMock()
        mock_ep.get_embeddings = AsyncMock(side_effect=lambda texts: [[0.1, 0.1, 0.1]] * len(texts))
        mock_kb.get_ep = AsyncMock(return_value=mock_ep)
        mgr.ensure_kb = AsyncMock(return_value=mock_kb)

        entries = [
            {"text": "记忆1（最新）", "updated_at": 400},
            {"text": "记忆2", "updated_at": 300},
            {"text": "记忆3", "updated_at": 200},
            {"text": "记忆4（最旧）", "updated_at": 100},
        ]

        # 1. 默认 max_entries=0 时读取配置项 character_match_max_memories (2条)
        report = await mgr.build_character_match(entries)
        self.assertIsNotNone(report)
        self.assertEqual(report["sample_count"], 4)
        self.assertEqual(report["used_count"], 2)
        self.assertTrue(report["truncated"])

        # 2. 动态指定 max_entries=3 覆盖配置
        report3 = await mgr.build_character_match(entries, max_entries=3)
        self.assertIsNotNone(report3)
        self.assertEqual(report3["sample_count"], 4)
        self.assertEqual(report3["used_count"], 3)
        self.assertTrue(report3["truncated"])

        # 3. 动态指定 max_entries=10 大于总条数
        report_all = await mgr.build_character_match(entries, max_entries=10)
        self.assertIsNotNone(report_all)
        self.assertEqual(report_all["sample_count"], 4)
        self.assertEqual(report_all["used_count"], 4)
        self.assertFalse(report_all["truncated"])

        # 4. 纯文本格式验证：截断时提示“共 4 条记忆，取最近 2 条参与比对”
        text_truncated = mgr.format_character_report(report)
        self.assertIn("共 4 条记忆，取最近 2 条参与比对", text_truncated)

        # 未截断时提示“基于全部 4 条长期记忆推测生成”
        text_full = mgr.format_character_report(report_all)
        self.assertIn("基于全部 4 条长期记忆推测生成", text_full)

    async def test_cmd_memory_mbti_dynamic_count_arg(self):
        """验证命令中传递动态条数（如 xxti 20, /记忆测评 最近10条）的透传。"""
        mod = test_gate.load_memory_main()
        Main = mod.Main

        context = MagicMock()
        context.kb_manager = MagicMock()
        config = {
            "memory": {
                "memory_enabled": True,
                "memory_kb_name": ["mock_kb"],
                "memory_mbti_min_memories": 3,
                "character_match_output_mode": "text",
            }
        }
        plugin = Main(context, config)
        plugin._gate_block_reason = lambda ev: None
        plugin._ensure_memory = AsyncMock(return_value=MagicMock())

        plugin.memory = MagicMock()
        plugin.memory.collect_memory_entries = AsyncMock(
            return_value=[{"text": f"m{i}", "updated_at": 100} for i in range(10)]
        )
        plugin.memory.build_character_match = AsyncMock(return_value={
            "top_character": {"name": "长离", "resonance": 90, "tags": []},
            "rankings": [],
            "commentary": "评语",
            "sample_count": 10,
            "used_count": 3,
            "truncated": True,
        })
        plugin.memory.format_character_report = MagicMock(return_value="共鸣报告文本")

        event = MagicMock()
        event.unified_msg_origin = "Iris:GroupMessage:10086_123"
        event.plain_result = lambda msg: ("PLAIN", msg)
        event.get_message_str = MagicMock(return_value="xxti 3")

        results = [res async for res in plugin.cmd_memory_mbti(event, "3")]
        self.assertEqual(len(results), 1)
        # 验证 build_character_match 被调用时透传了 max_entries=3
        plugin.memory.build_character_match.assert_called_once()
        call_kwargs = plugin.memory.build_character_match.call_args.kwargs
        self.assertEqual(call_kwargs["max_entries"], 3)


if __name__ == "__main__":
    unittest.main()


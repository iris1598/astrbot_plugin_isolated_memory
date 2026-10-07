"""
test_affinity.py - 原生好感度、自由关系与即时心境子系统单元测试集
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from astrbot_plugin_isolated_memory.affinity_manager import (
    AffinityManager,
    extract_user_id,
    group_storage_key,
)
from astrbot_plugin_isolated_memory.affinity_service import (
    AffinityService,
    clean_affinity_tags,
    format_bond_depth,
)


class TestAffinityManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_aff_mgr_"))
        self.mgr = AffinityManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_user_info(self):
        info = self.mgr.get_user_info("Group:123", "User:456")
        self.assertEqual(info["score"], 0)
        self.assertEqual(info["relation"], "普通朋友")
        self.assertEqual(info["eval"], "初次见面")
        self.assertEqual(info["mood_state"], "平常心")
        self.assertIsNone(info["pending_rel"])

    def test_unbounded_score_adjustment(self):
        # 测试无上下限累加
        self.mgr.adjust_score("Group:123", "User:456", 100, user_name="测试员")
        info = self.mgr.get_user_info("Group:123", "User:456")
        self.assertEqual(info["score"], 100)
        self.assertEqual(info["user_name"], "测试员")

        # 累加到高分 3855
        self.mgr.adjust_score("Group:123", "User:456", 3755)
        info = self.mgr.get_user_info("Group:123", "User:456")
        self.assertEqual(info["score"], 3855)

        # 扣减负分
        self.mgr.adjust_score("Group:123", "User:456", -4000)
        info = self.mgr.get_user_info("Group:123", "User:456")
        self.assertEqual(info["score"], -145)

    def test_persona_isolation(self):
        # 西格莉卡人格
        self.mgr.adjust_score("Group:1", "User:A", 500, persona_id="西格莉卡")
        self.mgr.set_relation("Group:1", "User:A", "并肩战友", persona_id="西格莉卡")

        # 爱弥斯人格
        self.mgr.adjust_score("Group:1", "User:A", 50, persona_id="爱弥斯")
        self.mgr.set_relation("Group:1", "User:A", "摸鱼搭子", persona_id="爱弥斯")

        x_info = self.mgr.get_user_info("Group:1", "User:A", persona_id="西格莉卡")
        a_info = self.mgr.get_user_info("Group:1", "User:A", persona_id="爱弥斯")

        self.assertEqual(x_info["score"], 500)
        self.assertEqual(x_info["relation"], "并肩战友")
        self.assertEqual(a_info["score"], 50)
        self.assertEqual(a_info["relation"], "摸鱼搭子")

    def test_list_users_and_summary_stats(self):
        self.mgr.set_score("Group:1", "User:1", 100, persona_id="P1", user_name="Tom")
        self.mgr.set_score("Group:1", "User:2", 200, persona_id="P1", user_name="Jerry")
        self.mgr.set_relation("Group:1", "User:1", "铁哥们", persona_id="P1")

        # 列表分页与搜索
        res = self.mgr.list_users(keyword="Tom", page=1, page_size=10)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["user_name"], "Tom")
        self.assertEqual(res["items"][0]["score"], 100)
        self.assertIn("P1", res["personas"])

        # 统计
        stats = self.mgr.get_summary_stats()
        self.assertEqual(stats["total_users"], 2)
        self.assertEqual(stats["max_score"], 200)
        self.assertEqual(stats["relations"]["铁哥们"], 1)

    def test_freeform_relation_proposal_and_confirm(self):
        # 提议新关系
        ok, msg, pending = self.mgr.propose_relation(
            "Group:1", "User:1", "互怼损友", reason="聊天很合得来"
        )
        self.assertTrue(ok)
        self.assertEqual(pending["from"], "普通朋友")
        self.assertEqual(pending["to"], "互怼损友")

        # 确认关系
        ok, old_rel, new_rel = self.mgr.confirm_relation("Group:1", "User:1")
        self.assertTrue(ok)
        self.assertEqual(old_rel, "普通朋友")
        self.assertEqual(new_rel, "互怼损友")

        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["relation"], "互怼损友")
        self.assertIsNone(info["pending_rel"])

    def test_freeform_relation_cancel_and_cooldown(self):
        self.mgr.propose_relation("Group:1", "User:1", "知心密友")
        ok, rejected = self.mgr.cancel_relation("Group:1", "User:1")
        self.assertTrue(ok)
        self.assertEqual(rejected, "知心密友")

        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["relation"], "普通朋友")
        self.assertIsNotNone(info["rel_cooldown_until"])

        # 冷却期内再次提议应被拒绝
        ok2, msg2, _ = self.mgr.propose_relation("Group:1", "User:1", "甜蜜恋人")
        self.assertFalse(ok2)
        self.assertIn("冷静期", msg2)

    def test_transient_mood_and_decay(self):
        self.mgr.update_mood("Group:1", "User:1", "傲娇赌气", reason="被说笨蛋", ttl=2)
        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["mood_state"], "傲娇赌气")
        self.assertEqual(info["mood_reason"], "被说笨蛋")
        self.assertEqual(info["mood_ttl"], 2)

        # 第 1 轮衰减
        self.mgr.decay_mood("Group:1", "User:1")
        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["mood_state"], "傲娇赌气")
        self.assertEqual(info["mood_ttl"], 1)

        # 第 2 轮衰减：归零自动恢复平常心
        self.mgr.decay_mood("Group:1", "User:1")
        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["mood_state"], "平常心")
        self.assertEqual(info["mood_ttl"], 0)

    def test_clear_eval_preserves_score_and_relation(self):
        self.mgr.adjust_score("Group:1", "User:1", 3855)
        self.mgr.set_relation("Group:1", "User:1", "挚爱恋人")
        self.mgr.update_eval("Group:1", "User:1", "很有趣的前辈")
        self.mgr.update_mood("Group:1", "User:1", "开心")

        cleared = self.mgr.clear_user_eval("Group:1", "User:1")
        self.assertTrue(cleared)

        info = self.mgr.get_user_info("Group:1", "User:1")
        self.assertEqual(info["eval"], "初次见面")
        self.assertEqual(info["mood_state"], "平常心")
        # 核心保证：分数、关系绝对不被篡改！
        self.assertEqual(info["score"], 3855)
        self.assertEqual(info["relation"], "挚爱恋人")

    def test_legacy_data_migration(self):
        legacy_root = self.temp_dir / "legacy_fav"
        legacy_root.mkdir(parents=True, exist_ok=True)
        default_json = {
            "Group:100": {
                "User:老玩家": {
                    "score": 4200,
                    "relation": "知心挚友",
                    "eval": "一直陪着我的老朋友",
                    "name": "测试老张",
                }
            }
        }
        with open(legacy_root / "favorability.json", "w", encoding="utf-8") as f:
            json.dump(default_json, f)

        # 人格目录
        p_dir = legacy_root / "personas" / "西格莉卡"
        p_dir.mkdir(parents=True, exist_ok=True)
        persona_json = {
            "Group:100": {
                "User:老玩家": {
                    "score": 5888,
                    "relation": "挚爱恋人",
                    "eval": "专属前辈",
                    "name": "测试老张",
                }
            }
        }
        with open(p_dir / "favorability.json", "w", encoding="utf-8") as f:
            json.dump(persona_json, f)

        migrated = self.mgr.migrate_from_legacy_plugin(legacy_root)
        self.assertEqual(migrated, 2)

        # 验证默认人格数据 100% 导入
        def_info = self.mgr.get_user_info("Group:100", "User:老玩家", persona_id="default")
        self.assertEqual(def_info["score"], 4200)
        self.assertEqual(def_info["relation"], "知心挚友")
        self.assertEqual(def_info["eval"], "一直陪着我的老朋友")

        # 验证西格莉卡数据 100% 导入
        p_info = self.mgr.get_user_info("Group:100", "User:老玩家", persona_id="西格莉卡")
        self.assertEqual(p_info["score"], 5888)
        self.assertEqual(p_info["relation"], "挚爱恋人")
        self.assertEqual(p_info["eval"], "专属前辈")


class TestAffinityService(unittest.TestCase):
    def test_build_prompt_context(self):
        user_info = {
            "score": 3855,
            "relation": "互怼损友",
            "eval": "喜欢开玩笑的前辈",
            "mood_state": "傲娇赌气",
            "mood_reason": "被抢了零食",
            "mood_ttl": 2,
            "pending_rel": None,
        }
        prompt = AffinityService.build_prompt_context(user_info)
        self.assertIn("互怼损友", prompt)
        self.assertIn("3855", prompt)
        self.assertIn("极深羁绊与漫长陪伴", prompt)
        self.assertIn("傲娇赌气", prompt)
        self.assertIn("喜欢开玩笑的前辈", prompt)

    def test_parse_response_with_tags(self):
        raw_text = (
            "哼，今天就勉强原谅你啦！[FAV:+2] [MOOD:害羞/被夸奖了] "
            "[REL:并肩战友] [EVAL:其实是个靠得住的家伙]"
        )
        parsed = AffinityService.parse_response(raw_text)
        self.assertEqual(parsed["fav_delta"], 2)
        self.assertTrue(parsed["has_fav_tag"])
        self.assertEqual(parsed["mood"], ("害羞", "被夸奖了"))
        self.assertEqual(parsed["rel_proposal"], "并肩战友")
        self.assertEqual(parsed["eval_text"], "其实是个靠得住的家伙")
        # 验证 100% 无标签残留
        self.assertEqual(parsed["clean_text"], "哼，今天就勉强原谅你啦！")

    def test_fallback_active_boost(self):
        raw_text = "今天的天气真不错呀，我们一起去散步吧！"
        # 默认不输出标签时好感度严格加 0（不变）
        parsed_default = AffinityService.parse_response(raw_text)
        self.assertEqual(parsed_default["fav_delta"], 0)
        self.assertFalse(parsed_default["has_fav_tag"])
        self.assertEqual(parsed_default["clean_text"], raw_text)

        # 仅当显式传入 default_active_boost=True 时才兜底微增
        parsed_boost = AffinityService.parse_response(raw_text, default_active_boost=True)
        self.assertEqual(parsed_boost["fav_delta"], 1)

    def test_clean_tags_variations(self):
        messy_text = "你好啊！**[FAV:+1]** 【MOOD:开心】 (REL:死党) [EVAL:新人]"
        cleaned = clean_affinity_tags(messy_text)
        self.assertEqual(cleaned, "你好啊！")


    def test_notice_message_formatting(self):
        # 验证提示消息拼接格式与原版保持一致（无任何人格前缀）
        change = 2
        score = 3855
        eval_text = "很有趣的人"
        tips = []
        if change != 0:
            symbol = "+" if change > 0 else ""
            tips.append(f"好感度 {symbol}{change}（当前: {score}）")
        if eval_text:
            tips.append("评价已更新 ✨")
        msg = " | ".join(tips)
        self.assertEqual(msg, "好感度 +2（当前: 3855） | 评价已更新 ✨")
        self.assertNotIn("【", msg)


class TestAffinityCommands(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_aff_cmd_"))
        self.mgr = AffinityManager(self.temp_dir)

        class MockPlugin:
            def __init__(self, mgr):
                self.affinity_mgr = mgr
                self.affinity_renderer = None
                self.affinity_enabled = True

            def affinity_keys(self, event):
                return "Group:123", str(event.get_sender_id())

            async def resolve_affinity_persona(self, event):
                return "西格莉卡"

        self.plugin = MockPlugin(self.mgr)
        from astrbot_plugin_isolated_memory.commands_affinity import AffinityCommands
        self.cmds = AffinityCommands(self.plugin)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cmd_query_no_persona_tag(self):
        import asyncio

        class MockEvent:
            message_str = "/好感度"

            def get_sender_id(self):
                return "User:456"

            def get_sender_name(self):
                return "测试者"

            def plain_result(self, text):
                return text

        ev = MockEvent()
        results = []

        async def run():
            async for res in self.cmds.cmd_query(ev):
                results.append(res)

        asyncio.run(run())
        self.assertEqual(len(results), 1)
        self.assertNotIn("【西格莉卡】", results[0])
        self.assertIn("的羁绊档案", results[0])

    def test_cmd_confirm_relation_with_at_and_no_persona_tag(self):
        import asyncio
        from astrbot.core.message.components import At
        from astrbot.core.message.message_event_result import MessageEventResult

        self.mgr.propose_relation("Group:123", "User:456", "知心好友", persona_id="西格莉卡")

        class MockEvent:
            message_str = "/确认关系"

            def get_sender_id(self):
                return "User:456"

            def get_sender_name(self):
                return "测试者"

            def chain_result(self, chain):
                mer = MessageEventResult()
                mer.chain = chain
                return mer

            def plain_result(self, text):
                return text

        ev = MockEvent()
        results = []

        async def run():
            async for res in self.cmds.cmd_confirm_relation(ev):
                results.append(res)

        asyncio.run(run())
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertIsInstance(res, MessageEventResult)
        has_at = any(isinstance(c, At) and c.qq == "User:456" for c in res.chain)
        self.assertTrue(has_at)
        text = res.get_plain_text()
        self.assertNotIn("【西格莉卡】", text)
        self.assertIn("双方关系已确认为：「知心好友」", text)

    def test_cmd_cancel_relation_with_at(self):
        import asyncio
        from astrbot.core.message.components import At
        from astrbot.core.message.message_event_result import MessageEventResult

        self.mgr.propose_relation("Group:123", "User:456", "知心好友", persona_id="西格莉卡")

        class MockEvent:
            message_str = "/取消关系"

            def get_sender_id(self):
                return "User:456"

            def get_sender_name(self):
                return "测试者"

            def chain_result(self, chain):
                mer = MessageEventResult()
                mer.chain = chain
                return mer

            def plain_result(self, text):
                return text

        ev = MockEvent()
        results = []

        async def run():
            async for res in self.cmds.cmd_cancel_relation(ev):
                results.append(res)

        asyncio.run(run())
        self.assertEqual(len(results), 1)
        res = results[0]
        has_at = any(isinstance(c, At) and c.qq == "User:456" for c in res.chain)
        self.assertTrue(has_at)
        text = res.get_plain_text()
        self.assertNotIn("【西格莉卡】", text)
        self.assertIn("已拒绝将关系调整为", text)

    def test_admin_commands_no_persona_tag(self):
        import asyncio

        class MockEvent:
            def __init__(self, msg):
                self.message_str = msg
                self.role = "admin"

            def get_sender_id(self):
                return "User:Admin"

            def get_sender_name(self):
                return "管理员"

            def plain_result(self, text):
                return text

        # 1. 设置好感度
        ev = MockEvent("/设置好感度 User:456 999")
        results = []

        async def run1():
            async for res in self.cmds.cmd_admin_set_score(ev):
                results.append(res)

        asyncio.run(run1())
        self.assertNotIn("【西格莉卡】", results[0])
        self.assertIn("已将用户 User:456 的好感度设为 999", results[0])

        # 2. 设置关系
        ev = MockEvent("/设置关系 User:456 挚友")
        results = []

        async def run2():
            async for res in self.cmds.cmd_admin_set_relation(ev):
                results.append(res)

        asyncio.run(run2())
        self.assertNotIn("【西格莉卡】", results[0])
        self.assertIn("已将用户 User:456 的关系设为「挚友」", results[0])

        # 3. 重置指定好感度
        ev = MockEvent("/重置指定好感度 User:456")
        results = []

        async def run3():
            async for res in self.cmds.cmd_admin_reset_user(ev):
                results.append(res)

        asyncio.run(run3())
        self.assertNotIn("【西格莉卡】", results[0])
        self.assertIn("已重置用户 User:456 的好感度档案", results[0])

    def test_relation_proposal_chain_with_at(self):
        from astrbot.core.message.components import At, Plain
        from astrbot.core.message.message_event_result import MessageChain

        sender_name = "小明"
        aff_user_id = "12345678"
        rel_proposal = "灵魂伴侣"
        notice = (
            f" 💞 想将与你的关系演进为「{rel_proposal}」\n"
            f"回复「/确认关系」生效，或「/取消关系」拒绝（10分钟内有效）"
        )
        mc = MessageChain().at(sender_name, aff_user_id).message(notice)
        self.assertEqual(len(mc.chain), 2)
        self.assertIsInstance(mc.chain[0], At)
        self.assertEqual(str(mc.chain[0].qq), "12345678")
        self.assertEqual(mc.chain[0].name, "小明")
        self.assertIsInstance(mc.chain[1], Plain)
        self.assertNotIn("【", mc.chain[1].text)
        self.assertIn("灵魂伴侣", mc.chain[1].text)


if __name__ == "__main__":
    unittest.main()



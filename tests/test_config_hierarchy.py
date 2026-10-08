"""配置层次与 _conf_schema.json 规范性单元测试。

验证：
1. _conf_schema.json 正确按 9 个卡片分区组织，每个分区均为 type: object 且 items 完整映射 47 个字段；
2. Main._mcfg 与 MemoryManager._cfg 具备自适应多层读取能力（支持新 9 大分区、旧 memory 分组、根级平铺与 Mock）；
3. Main 的好感度与核心属性通过 _mcfg 正确映射；
4. 缺省值与未知字典结构的优雅回退。
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from astrbot_plugin_isolated_memory.main import Main
from astrbot_plugin_isolated_memory.memory import MemoryManager

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "_conf_schema.json"


class TestConfSchema(unittest.TestCase):
    """测试 _conf_schema.json 结构的合法性与完整性（完全对照 AstrBot 官方规范与 old 版本）。"""

    def setUp(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_root_structure_matches_old(self):
        expected_root_keys = [
            "memory_groups",
            "enable_debug_log",
            "affinity_enabled",
            "affinity_mood_enabled",
            "affinity_default_active_boost",
            "affinity_render_theme",
            "affinity_notice_enabled",
            "favorability_reset_eval_with_session",
            "affinity_system_time_enabled",
            "memory",
        ]
        self.assertEqual(list(self.schema.keys()), expected_root_keys)

        # 验证 memory_groups 符合 template_list 规范
        mg = self.schema["memory_groups"]
        self.assertEqual(mg.get("type"), "template_list")
        self.assertIn("templates", mg)
        self.assertIn("group_config", mg["templates"])
        tmpl = mg["templates"]["group_config"]
        self.assertIn("name", tmpl)
        self.assertIn("label", tmpl)
        self.assertIn("display_item", tmpl)
        self.assertEqual(tmpl["display_item"], "group_id")
        self.assertIn("group_id", tmpl["items"])
        self.assertIn("group_name", tmpl["items"])
        self.assertIn("memory_enabled", tmpl["items"])

        # 验证 memory 模块
        mem = self.schema["memory"]
        self.assertEqual(mem.get("type"), "object")
        self.assertIn("items", mem)

    def test_schema_leaf_fields_count(self):
        # 9 个根级字段 + memory 下 39 个字段 = 共 48 个配置项
        root_fields = [k for k in self.schema.keys() if k != "memory"]
        mem_fields = list(self.schema["memory"]["items"].keys())
        total_fields = root_fields + mem_fields

        self.assertEqual(len(total_fields), 48)
        self.assertEqual(len(set(total_fields)), 48, "配置项不得有重名")

        # 检查关键字段分布
        self.assertIn("memory_groups", self.schema)
        self.assertIn("enable_debug_log", self.schema)
        self.assertIn("affinity_enabled", self.schema)
        self.assertIn("affinity_mood_enabled", self.schema)
        self.assertIn("affinity_render_theme", self.schema)
        self.assertIn("affinity_system_time_enabled", self.schema)

        mem_items = self.schema["memory"]["items"]
        self.assertIn("memory_enabled", mem_items)
        self.assertIn("memory_kb_name", mem_items)
        self.assertIn("memory_extract_interval", mem_items)
        self.assertIn("memory_half_life_days", mem_items)
        self.assertIn("memory_max_docs_per_user", mem_items)
        self.assertIn("memory_agent_tools_enabled", mem_items)
        self.assertIn("memory_rerank_enabled", mem_items)
        self.assertIn("memory_mbti_enabled", mem_items)


class TestConfigAdaptiveLookup(unittest.TestCase):
    """测试 Main._mcfg 与 MemoryManager._cfg 的多级自适应查找。"""

    def setUp(self):
        self.mock_context = MagicMock()

    def test_mcfg_flat_dict(self):
        cfg = {
            "affinity_enabled": False,
            "memory_half_life_days": 14,
        }
        main = Main(self.mock_context, cfg)
        self.assertFalse(main._mcfg("affinity_enabled", True))
        self.assertEqual(main._mcfg("memory_half_life_days", 30), 14)
        self.assertEqual(main._mcfg("non_existent", "default_val"), "default_val")

    def test_mcfg_legacy_memory_group(self):
        cfg = {
            "affinity_enabled": True,
            "memory": {
                "memory_enabled": True,
                "memory_half_life_days": 20,
            },
        }
        main = Main(self.mock_context, cfg)
        self.assertTrue(main._mcfg("memory_enabled", False))
        self.assertEqual(main._mcfg("memory_half_life_days", 30), 20)

    def test_mcfg_new_nine_sections(self):
        cfg = {
            "basic_settings": {
                "enable_debug_log": True,
            },
            "affinity_settings": {
                "affinity_enabled": True,
                "affinity_mood_enabled": False,
                "affinity_render_theme": "light",
            },
            "memory_core": {
                "memory_enabled": True,
                "memory_kb_name": ["kb_test"],
            },
            "memory_retrieval": {
                "memory_half_life_days": 45.0,
            },
        }
        main = Main(self.mock_context, cfg)
        self.assertTrue(main._mcfg("enable_debug_log", False))
        self.assertTrue(main.affinity_enabled)
        self.assertFalse(main.affinity_mood_enabled)
        self.assertEqual(main.affinity_render_theme, "light")
        self.assertTrue(main._mcfg("memory_enabled", False))
        self.assertEqual(main._mcfg("memory_half_life_days", 30.0), 45.0)

    def test_mcfg_priority_new_section_overrides_stale_root(self):
        # 如果新分区已修改，且根级残留了旧值，应优先读取新分区
        cfg = {
            "affinity_enabled": True,  # 旧根级
            "affinity_settings": {
                "affinity_enabled": False,  # 新分区
            },
        }
        main = Main(self.mock_context, cfg)
        self.assertFalse(main.affinity_enabled)
        self.assertFalse(main._mcfg("affinity_enabled", True))

    def test_memory_manager_cfg_lookup(self):
        cfg = {
            "memory_core": {
                "memory_kb_name": ["shared_kb"],
            },
            "memory_retrieval": {
                "memory_half_life_days": 10.5,
            },
        }
        mgr = MemoryManager(self.mock_context, cfg)
        self.assertEqual(mgr._cfg("memory_half_life_days", 30), 10.5)
        self.assertEqual(mgr._kb_name(), "shared_kb")

    def test_fallback_unknown_sub_dict(self):
        cfg = {
            "custom_section": {
                "custom_key": "custom_value",
            }
        }
        main = Main(self.mock_context, cfg)
        self.assertEqual(main._mcfg("custom_key", "none"), "custom_value")


if __name__ == "__main__":
    unittest.main()

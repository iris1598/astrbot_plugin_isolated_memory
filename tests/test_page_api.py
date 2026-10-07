"""test_page_api.py - 针对管理后台 Page API 路由与业务逻辑的单元测试。"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import bootstrap

_HAS = bootstrap.bootstrap()

if _HAS:
    try:
        from astrbot_plugin_isolated_memory.main import Main
        from astrbot_plugin_isolated_memory import page_api as page_api_mod
        from astrbot_plugin_isolated_memory.page_api import (
            PluginPageApi,
            PAGE_API_PREFIX,
            _format_timestamp,
            _normalize_metadata,
        )
    except ImportError:
        from main import Main
        import page_api as page_api_mod
        from page_api import (
            PluginPageApi,
            PAGE_API_PREFIX,
            _format_timestamp,
            _normalize_metadata,
        )
else:
    Main = None
    page_api_mod = None
    PluginPageApi = None


def run(coro):
    return asyncio.run(coro)


class MockDocStorage:
    def __init__(self, docs=None):
        self.docs = docs or []

    async def get_documents(self, metadata_filters=None, offset=None, limit=None):
        out = []
        for d in self.docs:
            if metadata_filters:
                md = d.get("metadata", {})
                match = True
                for k, v in metadata_filters.items():
                    if md.get(k) != v:
                        match = False
                        break
                if not match:
                    continue
            out.append(d)
        if offset is not None:
            out = out[offset:]
        if limit is not None:
            out = out[:limit]
        return out


class MockResult:
    def __init__(self, similarity: float, data: dict):
        self.similarity = similarity
        self.data = data


class MockVecDB:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.document_storage = MockDocStorage(self.docs)
        self.deleted_ids = []
        self.inserted = []

    async def delete(self, doc_id: str):
        self.deleted_ids.append(doc_id)
        self.docs = [d for d in self.docs if str(d.get("doc_id")) != str(doc_id)]
        self.document_storage.docs = self.docs
        return True

    async def insert(self, content: str, metadata: dict = None, id: str = None):
        doc_id = id or f"doc_{len(self.docs) + 1}"
        new_doc = {
            "id": len(self.docs) + 1,
            "doc_id": doc_id,
            "text": content,
            "metadata": metadata or {},
            "updated_at": int(time.time()),
        }
        self.docs.append(new_doc)
        self.inserted.append(new_doc)
        self.document_storage.docs = self.docs
        return len(self.docs)

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        fetch_k: int = 20,
        rerank: bool = False,
        metadata_filters: dict | None = None,
    ):
        hits = []
        for d in self.docs[:k]:
            hits.append(MockResult(similarity=0.88, data=d))
        return hits


class MockKB:
    def __init__(self, docs=None):
        self.vec_db = MockVecDB(docs)
        self.kb = mock.MagicMock()
        self.kb.kb_id = "test_kb_id"
        self.kb.kb_name = "test_kb"


@unittest.skipUnless(_HAS, "需要含 astrbot 的 Python 环境")
class TestPageApi(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_page_api_")
        self.initial_docs = [
            {
                "id": 1,
                "doc_id": "doc_u1_1",
                "text": "用户喜欢吃草莓蛋糕",
                "metadata": {
                    "memory_owner": "user_1",
                    "user_id": "user_1",
                    "importance": 0.8,
                    "type": "preference",
                    "memory_created_at": 1700000000,
                    "memory_updated_at": 1700000100,
                },
                "updated_at": 1700000100,
            },
            {
                "id": 2,
                "doc_id": "doc_u1_2",
                "text": "用户计划在十月份参加编程比赛",
                "metadata": {
                    "memory_owner": "user_1",
                    "user_id": "user_1",
                    "importance": 0.5,
                    "type": "planned",
                    "memory_created_at": 1700000200,
                    "memory_updated_at": 1700000200,
                },
                "updated_at": 1700000200,
            },
            {
                "id": 3,
                "doc_id": "doc_u2_1",
                "text": "用户居住在北京海淀区",
                "metadata": {
                    "memory_owner": "user_2",
                    "user_id": "user_2",
                    "importance": 0.9,
                    "type": "factual",
                    "memory_created_at": 1700000300,
                    "memory_updated_at": 1700000300,
                },
                "updated_at": 1700000300,
            },
        ]
        self.mock_kb = MockKB(list(self.initial_docs))

        # Mock Plugin
        self.plugin = mock.MagicMock()
        self.plugin.context = mock.MagicMock()
        self.registered_apis = []

        def mock_register_web_api(route, handler, methods, desc):
            self.registered_apis.append((route, handler, methods, desc))

        self.plugin.context.register_web_api = mock_register_web_api

        # Mock MemoryManager
        self.memory_mgr = mock.MagicMock()
        self.memory_mgr.ensure_kb = mock.AsyncMock(return_value=self.mock_kb)
        self.memory_mgr._refresh_stats = mock.AsyncMock()
        self.memory_mgr._sync_mem_doc = mock.AsyncMock()
        self.memory_mgr._half_life_days.return_value = 30.0
        self.memory_mgr._ttl_days.return_value = 90.0
        self.memory_mgr._max_docs.return_value = 200
        self.memory_mgr._dup_threshold.return_value = 0.9
        self.memory_mgr._protect_important.return_value = True
        self.memory_mgr._consolidate_enabled.return_value = False
        self.memory_mgr._consolidation_enabled.return_value = True
        self.memory_mgr._consolidation_min_age_days.return_value = 7
        self.memory_mgr._consolidation_max_importance.return_value = 0.5
        self.memory_mgr._consolidation_min_group_size.return_value = 3
        self.memory_mgr._consolidation_max_groups.return_value = 5
        self.memory_mgr.consolidate_memories = mock.AsyncMock(
            return_value={"groups": 1, "merged": 3, "new_memories": 1, "deleted": 3}
        )
        self.memory_mgr._rerank_enabled.return_value = False
        self.memory_mgr._rerank_provider_id.return_value = ""
        self.memory_mgr.list_backups.return_value = [
            {"filename": "backup_20261001.json", "total_memories": 3, "total_users": 2}
        ]
        self.memory_mgr.backup_all_memories = mock.AsyncMock(
            return_value={"total_memories": 3, "filename": "backup_new.json"}
        )
        self.memory_mgr.restore_memories_from_backup = mock.AsyncMock(
            return_value={"restored_count": 3}
        )
        self.memory_mgr._get_backup_dir.return_value = self.tmp_dir
        self.memory_mgr.upgrade_all_memories = mock.AsyncMock(
            return_value={"memories_upgraded": 2, "owners_checked": 2}
        )
        self.memory_mgr.recall = mock.AsyncMock(
            return_value=[
                {
                    "doc_id": "doc_u1_1",
                    "text": "用户喜欢吃草莓蛋糕",
                    "decayed_score": 0.85,
                    "raw_score": 0.90,
                    "days_ago": 1.2,
                    "metadata": {"importance": 0.8, "type": "preference"},
                }
            ]
        )
        self.memory_mgr.add_memory = mock.AsyncMock(return_value=True)

        self.plugin.memory = self.memory_mgr
        self.page_api = PluginPageApi(self.plugin)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_register_routes(self):
        """测试页面路由注册。"""
        self.page_api.register_routes()
        self.assertEqual(len(self.registered_apis), 15)
        routes = [r[0] for r in self.registered_apis]
        self.assertIn(f"{PAGE_API_PREFIX}/stats", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/detail", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/update", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/batch-delete", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/batch-update", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/export", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/memories/import", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/recall/test", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/backups", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/backups/create", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/backups/restore", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/backups/delete", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/consolidation/status", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/consolidation/run", routes)
        self.assertIn(f"{PAGE_API_PREFIX}/upgrade/run", routes)

    def test_get_stats(self):
        """测试统计数据获取。"""
        res = run(self.page_api.get_stats())
        self.assertEqual(res["status"], "ok")
        data = res["data"]
        self.assertEqual(data["total_memories"], 3)
        self.assertEqual(data["total_sessions"], 2)
        self.assertEqual(data["atom_breakdown"]["preference"], 1)
        self.assertEqual(data["atom_breakdown"]["planned"], 1)
        self.assertEqual(data["atom_breakdown"]["factual"], 1)
        self.assertIn("7-8", data["importance_distribution"])

    def test_list_memories_all(self):
        """测试查询全部记忆。"""
        with mock.patch.object(page_api_mod, "_get_request_query", return_value={}):
            res = run(self.page_api.list_memories())
            self.assertEqual(res["status"], "ok")
            data = res["data"]
            self.assertEqual(data["total"], 3)
            self.assertEqual(len(data["items"]), 3)

    def test_list_memories_filter_session(self):
        """测试按用户/会话过滤记忆。"""
        with mock.patch.object(page_api_mod, "_get_request_query", return_value={"session_id": "user_2"}):
            res = run(self.page_api.list_memories())
            self.assertEqual(res["status"], "ok")
            data = res["data"]
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["metadata"]["memory_owner"], "user_2")

    def test_list_memories_filter_keyword(self):
        """测试关键词搜索。"""
        with mock.patch.object(page_api_mod, "_get_request_query", return_value={"keyword": "蛋糕"}):
            res = run(self.page_api.list_memories())
            self.assertEqual(res["status"], "ok")
            data = res["data"]
            self.assertEqual(data["total"], 1)
            self.assertIn("蛋糕", data["items"][0]["text"])

    def test_list_memories_filter_type(self):
        """测试事实类型过滤。"""
        with mock.patch.object(page_api_mod, "_get_request_query", return_value={"type": "planned"}):
            res = run(self.page_api.list_memories())
            self.assertEqual(res["status"], "ok")
            data = res["data"]
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["metadata"]["type"], "planned")

    def test_get_memory_detail(self):
        """测试获取单条记忆详情。"""
        with mock.patch.object(page_api_mod, "_get_request_query", return_value={"memory_id": "doc_u1_1"}):
            res = run(self.page_api.get_memory_detail())
            self.assertEqual(res["status"], "ok")
            data = res["data"]
            self.assertEqual(data["doc_id"], "doc_u1_1")
            self.assertEqual(data["session_id"], "user_1")
            self.assertEqual(data["importance"], 0.8)

    def test_update_memory(self):
        """测试更新单条记忆。"""
        body = {
            "memory_id": "doc_u1_1",
            "content": "用户非常喜欢吃新鲜草莓蛋糕",
            "importance": 0.95,
            "memory_type": "PREFERENCE",
        }
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=body):
            res = run(self.page_api.update_memory())
            self.assertEqual(res["status"], "ok")
            self.assertIn("doc_u1_1", self.mock_kb.vec_db.deleted_ids)
            self.assertTrue(any("新鲜草莓蛋糕" in d["text"] for d in self.mock_kb.vec_db.inserted))

    def test_batch_delete_memories(self):
        """测试批量删除记忆。"""
        body = {"memory_ids": ["doc_u1_1", "doc_u2_1"]}
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=body):
            res = run(self.page_api.batch_delete_memories())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["deleted_count"], 2)
            self.assertIn("doc_u1_1", self.mock_kb.vec_db.deleted_ids)
            self.assertIn("doc_u2_1", self.mock_kb.vec_db.deleted_ids)

    def test_batch_update_memories(self):
        """测试批量修改重要度与类型。"""
        body = {
            "memory_ids": ["doc_u1_1", "doc_u1_2"],
            "importance": 0.85,
            "memory_type": "factual",
        }
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=body):
            res = run(self.page_api.batch_update_memories())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["updated_count"], 2)

    def test_export_and_import_memories(self):
        """测试导出与导入记忆。"""
        # 导出
        with mock.patch.object(page_api_mod, "_get_request_json", return_value={"memory_ids": []}):
            res = run(self.page_api.export_memories())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["total"], 3)
            memories = res["data"]["memories"]

        # 导入
        import_body = {
            "items": [
                {"owner": "user_3", "content": "用户喜欢旅行", "importance": 0.7, "type": "preference"}
            ]
        }
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=import_body):
            res = run(self.page_api.import_memories())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["imported_count"], 1)
            self.memory_mgr.add_memory.assert_awaited()

    def test_test_recall_with_session(self):
        """测试指定用户会话的混合召回。"""
        body = {"query": "草莓", "k": 3, "session_id": "user_1"}
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=body):
            res = run(self.page_api.test_recall())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["total"], 1)
            self.assertEqual(res["data"]["results"][0]["doc_id"], "doc_u1_1")

    def test_test_recall_without_session(self):
        """测试不指定用户会话时的知识库向量召回（FaissVecDB.retrieve 兼容）。"""
        body = {"query": "蛋糕", "k": 2, "session_id": ""}
        with mock.patch.object(page_api_mod, "_get_request_json", return_value=body):
            res = run(self.page_api.test_recall())
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["data"]["total"], 2)
            self.assertEqual(res["data"]["results"][0]["doc_id"], "doc_u1_1")
            self.assertEqual(res["data"]["results"][0]["score"], 0.88)

    def test_backup_management(self):
        """测试备份增删查与恢复。"""
        # 查
        res = run(self.page_api.list_backups())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["data"]["total"], 1)

        # 增
        res = run(self.page_api.create_backup())
        self.assertEqual(res["status"], "ok")
        self.memory_mgr.backup_all_memories.assert_awaited()

        # 恢复
        with mock.patch.object(page_api_mod, "_get_request_json", return_value={"filename": "backup_20261001.json"}):
            res = run(self.page_api.restore_backup())
            self.assertEqual(res["status"], "ok")
            self.memory_mgr.restore_memories_from_backup.assert_awaited_with("backup_20261001.json")

        # 删
        test_file = os.path.join(self.tmp_dir, "test_del.json")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("{}")
        with mock.patch.object(page_api_mod, "_get_request_json", return_value={"filename": "test_del.json"}):
            res = run(self.page_api.delete_backup())
            self.assertEqual(res["status"], "ok")
            self.assertFalse(os.path.exists(test_file))

    def test_consolidation_and_upgrade(self):
        """测试整合状态、立即整理与一键升级。"""
        res = run(self.page_api.get_consolidation_status())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["data"]["half_life_days"], 30.0)
        self.assertTrue(res["data"]["enabled"])
        self.assertEqual(res["data"]["min_age_days"], 7)
        self.assertEqual(res["data"]["max_importance"], 0.5)

        # 测试立即整理
        res_cons = run(self.page_api.run_consolidation())
        self.assertEqual(res_cons["status"], "ok")
        self.assertEqual(res_cons["data"]["groups"], 1)
        self.assertEqual(res_cons["data"]["merged"], 3)

        # 测试一键升级
        res = run(self.page_api.run_upgrade())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["data"]["memories_upgraded"], 2)


if __name__ == "__main__":
    unittest.main()

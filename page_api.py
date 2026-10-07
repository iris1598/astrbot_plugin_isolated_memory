"""
官方插件 Page API 适配层与视图处理器。

提供 WebUI 管理后台所需的原生 Web API 路由：
- 统计数据 (stats)
- 记忆管理 (memories, detail, update, batch-delete, batch-update, export, import)
- 召回测试 (recall/test)
- 备份恢复与管理 (backups, create, restore, delete)
- 记忆整理与升级 (consolidation/status, upgrade/run)
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_isolated_memory"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}/page"


async def _get_request_query() -> dict[str, Any]:
    """获取当前请求的 Query 参数字典，兼容 AstrBot 官方 Web 代理与 Quart 兼容上下文。"""
    try:
        from astrbot.api.web import request as web_req
        if getattr(web_req, "query", None):
            return dict(web_req.query)
    except Exception:
        pass
    try:
        from quart import request as q_req
        if getattr(q_req, "args", None):
            return dict(q_req.args)
    except Exception:
        pass
    return {}


async def _get_request_json() -> dict[str, Any]:
    """获取当前请求的 JSON Body 字典。"""
    try:
        from astrbot.api.web import request as web_req
        body = await web_req.json()
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    try:
        from quart import request as q_req
        body = await q_req.get_json()
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return {}


def _ok(data: Any = None) -> dict[str, Any]:
    """构造标准成功响应格式。"""
    return {"status": "ok", "data": data if data is not None else {}}


def _error(message: str) -> dict[str, Any]:
    """构造标准错误响应格式。"""
    return {"status": "error", "message": str(message)}


def _normalize_metadata(raw_md: Any) -> dict[str, Any]:
    """规范化元数据为 dict。"""
    if isinstance(raw_md, dict):
        return raw_md
    if isinstance(raw_md, str) and raw_md.strip():
        try:
            parsed = json.loads(raw_md)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _format_timestamp(ts: Any) -> str:
    """格式化时间戳或时间字符串为可读日期。"""
    if not ts:
        return "--"
    try:
        if isinstance(ts, (int, float)):
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
        val = float(ts)
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(val))
    except Exception:
        return str(ts)


class PluginPageApi:
    """IsolatedMemory 官方插件管理页面 API。"""

    def __init__(self, plugin) -> None:
        self.plugin = plugin

    async def _ensure_memory_manager(self):
        """确保 MemoryManager 已就绪。"""
        if getattr(self.plugin, "memory", None) is None:
            err = await self.plugin._try_init()
            if err:
                return None, _error(f"记忆系统未就绪: {err}")
        mgr = getattr(self.plugin, "memory", None)
        if mgr is None:
            return None, _error("记忆系统未就绪")
        kb = await mgr.ensure_kb()
        if kb is None:
            return None, _error("记忆知识库未就绪")
        return (mgr, kb), None

    def register_routes(self) -> None:
        """向 AstrBot 注册管理页面 API 路由。"""
        register = getattr(self.plugin.context, "register_web_api", None)
        if not register:
            return

        routes = [
            (f"{PAGE_API_PREFIX}/stats", self.get_stats, ["GET"], "IsolatedMemory 统计数据"),
            (f"{PAGE_API_PREFIX}/memories", self.list_memories, ["GET"], "IsolatedMemory 记忆列表"),
            (f"{PAGE_API_PREFIX}/memories/detail", self.get_memory_detail, ["GET"], "IsolatedMemory 记忆详情"),
            (f"{PAGE_API_PREFIX}/memories/update", self.update_memory, ["POST"], "IsolatedMemory 更新记忆"),
            (f"{PAGE_API_PREFIX}/memories/batch-delete", self.batch_delete_memories, ["POST"], "IsolatedMemory 批量删除记忆"),
            (f"{PAGE_API_PREFIX}/memories/batch-update", self.batch_update_memories, ["POST"], "IsolatedMemory 批量更新记忆"),
            (f"{PAGE_API_PREFIX}/memories/export", self.export_memories, ["POST"], "IsolatedMemory 导出记忆"),
            (f"{PAGE_API_PREFIX}/memories/import", self.import_memories, ["POST"], "IsolatedMemory 导入记忆"),
            (f"{PAGE_API_PREFIX}/recall/test", self.test_recall, ["POST"], "IsolatedMemory 召回检索测试"),
            (f"{PAGE_API_PREFIX}/backups", self.list_backups, ["GET"], "IsolatedMemory 备份列表"),
            (f"{PAGE_API_PREFIX}/backups/create", self.create_backup, ["POST"], "IsolatedMemory 创建备份"),
            (f"{PAGE_API_PREFIX}/backups/restore", self.restore_backup, ["POST"], "IsolatedMemory 恢复备份"),
            (f"{PAGE_API_PREFIX}/backups/delete", self.delete_backup, ["POST"], "IsolatedMemory 删除备份"),
            (f"{PAGE_API_PREFIX}/consolidation/status", self.get_consolidation_status, ["GET"], "IsolatedMemory 整合配置与状态"),
            (f"{PAGE_API_PREFIX}/upgrade/run", self.run_upgrade, ["POST"], "IsolatedMemory 一键升级全部记忆"),
        ]

        for route, handler, methods, desc in routes:
            register(route, handler, methods, desc)
        logger.info(f"[IsolatedMemory] 已注册 {len(routes)} 个管理页面 API 路由")

    # ==================== API 处理器 ====================

    async def get_stats(self) -> dict[str, Any]:
        """获取插件统计信息。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            all_docs = []
            if ds and hasattr(ds, "get_documents"):
                all_docs = await ds.get_documents(metadata_filters={}, offset=None, limit=None)

            total = 0
            session_counts: dict[str, int] = {}
            type_counts: dict[str, int] = {
                "factual": 0,
                "preference": 0,
                "episodic": 0,
                "planned": 0,
                "general": 0,
            }
            # 10 个区间：0-1, 1-2, 2-3, ..., 9-10
            importance_dist = {f"{i}-{i+1}": 0 for i in range(10)}
            total_importance = 0.0

            for doc in all_docs:
                md = _normalize_metadata(doc.get("metadata"))
                owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
                if not owner and "memory_owner" not in md:
                    continue
                total += 1
                if owner:
                    session_counts[owner] = session_counts.get(owner, 0) + 1

                fact_type = str(md.get("type") or "factual").strip().lower()
                if fact_type not in type_counts:
                    type_counts[fact_type] = 0
                type_counts[fact_type] += 1

                imp = float(md.get("importance", 0.6) or 0.6)
                total_importance += imp
                # 归一化到 0-10 区间
                scaled_imp = min(9.999, max(0.0, imp * 10.0 if imp <= 1.0 else imp))
                bin_idx = int(scaled_imp)
                bin_key = f"{bin_idx}-{bin_idx+1}"
                importance_dist[bin_key] = importance_dist.get(bin_key, 0) + 1

            recent_sessions = [
                {"session_id": sid, "message_count": cnt}
                for sid, cnt in sorted(session_counts.items(), key=lambda x: -x[1])[:20]
            ]

            data = {
                "total_memories": total,
                "total_sessions": len(session_counts),
                "avg_importance": round(total_importance / total, 2) if total > 0 else 0.6,
                "status_breakdown": {
                    "active": total,
                    "archived": 0,
                    "deleted": 0,
                },
                "graph_nodes": 0,
                "atom_count": total,
                "atom_breakdown": type_counts,
                "importance_distribution": importance_dist,
                "recent_sessions": recent_sessions,
            }
            return _ok(data)
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 获取统计失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def list_memories(self) -> dict[str, Any]:
        """获取记忆列表（带过滤、排序与分页）。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        query = await _get_request_query()
        session_id = str(query.get("session_id") or "").strip()
        keyword = str(query.get("keyword") or "").strip().lower()
        type_filter = str(query.get("type") or "").strip().lower()
        if type_filter in {"all", ""}:
            type_filter = None
        sort_key = str(query.get("sort") or "created_desc").strip().lower()

        try:
            page = max(1, int(query.get("page", 1)))
            page_size = min(200, max(1, int(query.get("page_size", 20))))
        except Exception:
            return _error("分页参数无效")

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _ok({"items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False})

            # 若指定了 session_id，直接使用元数据过滤以提高性能
            metadata_filters = {}
            if session_id:
                metadata_filters["memory_owner"] = session_id

            rows = await ds.get_documents(metadata_filters=metadata_filters, offset=None, limit=None)

            filtered: list[dict[str, Any]] = []
            for r in rows:
                md = _normalize_metadata(r.get("metadata"))
                owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
                if not owner and "memory_owner" not in md:
                    continue

                text = str(r.get("text") or "")
                doc_id = str(r.get("doc_id") or "")
                raw_id = str(r.get("id") or doc_id)
                fact_type = str(md.get("type") or "factual").strip().lower()

                # 关键词过滤
                if keyword:
                    match_kw = (
                        keyword in text.lower()
                        or keyword in owner.lower()
                        or keyword in doc_id.lower()
                    )
                    if not match_kw:
                        continue

                # 事实类型过滤
                if type_filter and fact_type != type_filter:
                    continue

                created_ts = md.get("memory_created_at") or r.get("updated_at")
                updated_ts = md.get("memory_updated_at") or r.get("updated_at")
                imp = float(md.get("importance", 0.6) or 0.6)

                filtered.append({
                    "id": doc_id,
                    "doc_id": doc_id,
                    "raw_id": raw_id,
                    "text": text,
                    "summary": text[:90] + ("…" if len(text) > 90 else ""),
                    "metadata": {
                        "memory_owner": owner,
                        "session_id": owner,
                        "importance": imp,
                        "type": fact_type,
                        "memory_type": fact_type.upper(),
                        "create_time": created_ts,
                        "updated_at": updated_ts,
                        "status": "active",
                    },
                    "created_at": _format_timestamp(created_ts),
                    "updated_at": _format_timestamp(updated_ts),
                    "_sort_created": float(created_ts or 0),
                    "_sort_updated": float(updated_ts or 0),
                    "_sort_importance": imp,
                })

            # 排序
            if sort_key == "created_asc":
                filtered.sort(key=lambda x: x["_sort_created"])
            elif sort_key == "updated_desc":
                filtered.sort(key=lambda x: x["_sort_updated"], reverse=True)
            elif sort_key == "importance_desc":
                filtered.sort(key=lambda x: x["_sort_importance"], reverse=True)
            elif sort_key == "importance_asc":
                filtered.sort(key=lambda x: x["_sort_importance"])
            else:  # created_desc default
                filtered.sort(key=lambda x: x["_sort_created"], reverse=True)

            total = len(filtered)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paged_items = filtered[start_idx:end_idx]

            # 移除私有排序键
            for it in paged_items:
                it.pop("_sort_created", None)
                it.pop("_sort_updated", None)
                it.pop("_sort_importance", None)

            return _ok({
                "items": paged_items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": end_idx < total,
                "filters": {
                    "session_id": session_id,
                    "keyword": keyword,
                    "type": type_filter,
                },
                "sort": sort_key,
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 获取记忆列表失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def get_memory_detail(self) -> dict[str, Any]:
        """获取单条记忆的详细信息。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        query = await _get_request_query()
        memory_id = str(query.get("memory_id") or query.get("id") or query.get("doc_id") or "").strip()
        if not memory_id:
            return _error("缺少 memory_id 参数")

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _error("底层文档存储不可用")

            rows = await ds.get_documents(metadata_filters={}, offset=None, limit=None)
            target = None
            for r in rows:
                if str(r.get("doc_id")) == memory_id or str(r.get("id")) == memory_id:
                    target = r
                    break

            if not target:
                return _error(f"未找到 ID 为 {memory_id} 的记忆")

            md = _normalize_metadata(target.get("metadata"))
            owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
            fact_type = str(md.get("type") or "factual").strip().lower()
            imp = float(md.get("importance", 0.6) or 0.6)
            created_ts = md.get("memory_created_at") or target.get("updated_at")
            updated_ts = md.get("memory_updated_at") or target.get("updated_at")
            text = str(target.get("text") or "")

            return _ok({
                "memory_id": target.get("doc_id") or target.get("id"),
                "doc_id": target.get("doc_id"),
                "text": text,
                "summary": text,
                "content": text,
                "session_id": owner,
                "memory_owner": owner,
                "memory_type": fact_type.upper(),
                "importance": imp,
                "importance_scale": "0-1",
                "status": "active",
                "created_at": _format_timestamp(created_ts),
                "updated_at": _format_timestamp(updated_ts),
                "metadata": md,
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 获取记忆详情失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def update_memory(self) -> dict[str, Any]:
        """更新记忆文本内容、重要度或事实类型。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        memory_id = str(body.get("memory_id") or body.get("doc_id") or "").strip()
        new_text = str(body.get("content") or body.get("text") or body.get("summary") or "").strip()
        new_importance = body.get("importance")
        new_type = str(body.get("memory_type") or body.get("type") or "").strip()

        if not memory_id:
            return _error("缺少 memory_id 参数")
        if not new_text:
            return _error("记忆文本不能为空")

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _error("底层文档存储不可用")

            rows = await ds.get_documents(metadata_filters={}, offset=None, limit=None)
            target = None
            for r in rows:
                if str(r.get("doc_id")) == memory_id or str(r.get("id")) == memory_id:
                    target = r
                    break

            if not target:
                return _error(f"未找到 ID 为 {memory_id} 的记忆")

            old_doc_id = str(target.get("doc_id"))
            md = _normalize_metadata(target.get("metadata"))
            owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()

            # 处理重要度（支持 0-1 或 0-10 范围）
            if new_importance is not None:
                parsed_imp = float(new_importance)
                if parsed_imp > 1.0:
                    parsed_imp /= 10.0
                md["importance"] = round(max(0.1, min(1.0, parsed_imp)), 2)

            if new_type:
                md["type"] = new_type.lower()

            ts = int(time.time())
            md["memory_updated_at"] = ts

            # 删除旧 chunk 并插入新 chunk（重新生成向量嵌入与对齐）
            await kb.vec_db.delete(old_doc_id)
            await kb.vec_db.insert(content=new_text, metadata=md)

            await mgr._refresh_stats(kb)
            if owner:
                await mgr._sync_mem_doc(kb, owner)

            return _ok({"updated": True, "doc_id": memory_id})
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 更新记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def batch_delete_memories(self) -> dict[str, Any]:
        """批量删除选中的记忆。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        memory_ids = body.get("memory_ids") or []
        if not isinstance(memory_ids, list) or not memory_ids:
            return _error("未提供待删除的 memory_ids 列表")

        id_set = {str(mid).strip() for mid in memory_ids if str(mid).strip()}
        if not id_set:
            return _error("待删除列表为空")

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _error("底层文档存储不可用")

            rows = await ds.get_documents(metadata_filters={}, offset=None, limit=None)
            deleted_count = 0
            affected_owners: set[str] = set()

            for r in rows:
                doc_id = str(r.get("doc_id"))
                raw_id = str(r.get("id"))
                if doc_id in id_set or raw_id in id_set:
                    md = _normalize_metadata(r.get("metadata"))
                    owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
                    if owner:
                        affected_owners.add(owner)
                    await kb.vec_db.delete(doc_id)
                    deleted_count += 1

            if deleted_count > 0:
                await mgr._refresh_stats(kb)
                for owner in affected_owners:
                    await mgr._sync_mem_doc(kb, owner)

            return _ok({"deleted_count": deleted_count})
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 批量删除记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def batch_update_memories(self) -> dict[str, Any]:
        """批量更新选中记忆的属性（重要度或类型）。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        memory_ids = body.get("memory_ids") or []
        new_importance = body.get("importance")
        new_type = str(body.get("memory_type") or body.get("type") or "").strip()

        if not isinstance(memory_ids, list) or not memory_ids:
            return _error("未提供待更新的 memory_ids 列表")

        id_set = {str(mid).strip() for mid in memory_ids if str(mid).strip()}
        if not id_set:
            return _error("待更新列表为空")

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _error("底层文档存储不可用")

            rows = await ds.get_documents(metadata_filters={}, offset=None, limit=None)
            updated_count = 0
            affected_owners: set[str] = set()

            for r in rows:
                doc_id = str(r.get("doc_id"))
                raw_id = str(r.get("id"))
                if doc_id in id_set or raw_id in id_set:
                    md = _normalize_metadata(r.get("metadata"))
                    owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
                    if owner:
                        affected_owners.add(owner)

                    text = str(r.get("text") or "")
                    if new_importance is not None:
                        parsed_imp = float(new_importance)
                        if parsed_imp > 1.0:
                            parsed_imp /= 10.0
                        md["importance"] = round(max(0.1, min(1.0, parsed_imp)), 2)
                    if new_type:
                        md["type"] = new_type.lower()

                    md["memory_updated_at"] = int(time.time())

                    await kb.vec_db.delete(doc_id)
                    await kb.vec_db.insert(content=text, metadata=md)
                    updated_count += 1

            if updated_count > 0:
                await mgr._refresh_stats(kb)
                for owner in affected_owners:
                    await mgr._sync_mem_doc(kb, owner)

            return _ok({"updated_count": updated_count})
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 批量更新记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def export_memories(self) -> dict[str, Any]:
        """导出记忆数据。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        target_ids = body.get("memory_ids") or []
        export_all = not bool(target_ids)
        id_set = {str(mid).strip() for mid in target_ids if str(mid).strip()}

        try:
            ds = getattr(kb.vec_db, "document_storage", None)
            if not ds or not hasattr(ds, "get_documents"):
                return _error("底层文档存储不可用")

            rows = await ds.get_documents(metadata_filters={}, offset=None, limit=None)
            memories: list[dict[str, Any]] = []

            for r in rows:
                doc_id = str(r.get("doc_id"))
                raw_id = str(r.get("id"))
                if not export_all and doc_id not in id_set and raw_id not in id_set:
                    continue

                md = _normalize_metadata(r.get("metadata"))
                owner = str(md.get("memory_owner") or md.get("user_id") or "").strip()
                if not owner and "memory_owner" not in md:
                    continue

                memories.append({
                    "id": doc_id,
                    "owner": owner,
                    "content": str(r.get("text") or ""),
                    "type": str(md.get("type") or "factual").strip().lower(),
                    "importance": float(md.get("importance", 0.6) or 0.6),
                    "created_at": md.get("memory_created_at") or r.get("updated_at"),
                    "updated_at": md.get("memory_updated_at") or r.get("updated_at"),
                })

            return _ok({
                "memories": memories,
                "total": len(memories),
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 导出记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def import_memories(self) -> dict[str, Any]:
        """导入记忆列表。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        raw_items = body.get("items") or body.get("memories") or []
        if not isinstance(raw_items, list) or not raw_items:
            return _error("未提供可导入的记忆条目")

        imported_count = 0
        skipped_count = 0

        try:
            for item in raw_items:
                if not isinstance(item, dict):
                    skipped_count += 1
                    continue
                content = str(item.get("content") or item.get("text") or item.get("summary") or "").strip()
                owner = str(item.get("owner") or item.get("session_id") or item.get("user_id") or "").strip()
                if not content or not owner:
                    skipped_count += 1
                    continue

                imp = item.get("importance")
                fact_type = str(item.get("type") or item.get("memory_type") or "factual").strip().lower()

                success = await mgr.add_memory(
                    owner=owner,
                    text=content,
                    importance=float(imp) if imp is not None else 0.6,
                    fact_type=fact_type,
                )
                if success:
                    imported_count += 1
                else:
                    skipped_count += 1

            return _ok({
                "imported_count": imported_count,
                "skipped_count": skipped_count,
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 导入记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def test_recall(self) -> dict[str, Any]:
        """测试记忆召回与打分。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, kb = ready

        body = await _get_request_json()
        query = str(body.get("query") or "").strip()
        session_id = str(body.get("session_id") or "").strip()
        try:
            k = max(1, min(50, int(body.get("k", 5))))
        except Exception:
            k = 5

        if not query:
            return _error("查询内容 query 不能为空")

        try:
            results: list[dict[str, Any]] = []

            if session_id:
                # 指定用户时，使用完整的混合检索 + 衰减打分
                hits = await mgr.recall(session_id, query, top_k=k)
                for rank, hit in enumerate(hits, start=1):
                    md = _normalize_metadata(hit.get("metadata"))
                    results.append({
                        "rank": rank,
                        "doc_id": hit.get("doc_id", ""),
                        "text": hit.get("text", ""),
                        "score": round(float(hit.get("decayed_score", hit.get("raw_score", 0.0))), 4),
                        "raw_score": round(float(hit.get("raw_score", 0.0)), 4),
                        "days_ago": round(float(hit.get("days_ago", 0.0)), 1),
                        "owner": session_id,
                        "importance": float(md.get("importance", 0.6) or 0.6),
                        "type": str(md.get("type") or "factual").strip().lower(),
                        "created_at": _format_timestamp(md.get("memory_created_at")),
                    })
            else:
                # 未指定用户时，使用知识库向量检索（兼容 FaissVecDB 的 k 参数与 BaseVecDB 的 top_k 参数）
                try:
                    vec_hits = await kb.vec_db.retrieve(query, k)
                except TypeError:
                    try:
                        vec_hits = await kb.vec_db.retrieve(query=query, k=k)
                    except TypeError:
                        vec_hits = await kb.vec_db.retrieve(query=query, top_k=k)

                for rank, hit in enumerate(vec_hits, start=1):
                    # 适配 AstrBot 原生 Result(similarity=..., data=dict) 结构
                    hit_data = getattr(hit, "data", None)
                    if not isinstance(hit_data, dict):
                        hit_data = hit if isinstance(hit, dict) else {}

                    raw_md = hit_data.get("metadata") or getattr(hit, "metadata", None)
                    md = _normalize_metadata(raw_md)
                    owner = str(md.get("memory_owner") or md.get("user_id") or "--").strip()
                    score = getattr(hit, "similarity", getattr(hit, "score", hit_data.get("score", 0.0)))
                    doc_id = hit_data.get("doc_id") or hit_data.get("id") or getattr(hit, "doc_id", getattr(hit, "id", ""))
                    text = hit_data.get("text") or hit_data.get("content") or getattr(hit, "content", getattr(hit, "text", ""))

                    results.append({
                        "rank": rank,
                        "doc_id": str(doc_id),
                        "text": str(text),
                        "score": round(float(score or 0.0), 4),
                        "raw_score": round(float(score or 0.0), 4),
                        "days_ago": 0.0,
                        "owner": owner,
                        "importance": float(md.get("importance", 0.6) or 0.6),
                        "type": str(md.get("type") or "factual").strip().lower(),
                        "created_at": _format_timestamp(md.get("memory_created_at")),
                    })

            return _ok({
                "results": results,
                "total": len(results),
                "query": query,
                "session_id": session_id,
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 召回测试失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def list_backups(self) -> dict[str, Any]:
        """获取所有备份列表。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        try:
            backups = mgr.list_backups()
            return _ok({
                "backups": backups,
                "total": len(backups),
            })
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 列出备份失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def create_backup(self) -> dict[str, Any]:
        """立即执行一次全量备份。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        try:
            res = await mgr.backup_all_memories()
            return _ok(res)
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 创建备份失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def restore_backup(self) -> dict[str, Any]:
        """从备份文件恢复记忆。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        body = await _get_request_json()
        filename = str(body.get("filename") or "").strip()
        if not filename:
            return _error("缺少备份文件名 filename")

        try:
            res = await mgr.restore_memories_from_backup(filename)
            return _ok(res)
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 恢复备份失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def delete_backup(self) -> dict[str, Any]:
        """删除指定备份文件。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        body = await _get_request_json()
        filename = str(body.get("filename") or "").strip()
        if not filename:
            return _error("缺少备份文件名 filename")

        try:
            base_name = os.path.basename(filename)
            if not base_name.endswith(".json"):
                return _error("非法备份文件名")

            backup_dir = mgr._get_backup_dir()
            file_path = os.path.join(backup_dir, base_name)
            if not os.path.isfile(file_path):
                return _error(f"备份文件不存在: {base_name}")

            os.remove(file_path)
            return _ok({"deleted": True, "filename": base_name})
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 删除备份失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def get_consolidation_status(self) -> dict[str, Any]:
        """获取记忆衰减与整合配置。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        try:
            data = {
                "half_life_days": mgr._half_life_days(),
                "ttl_days": mgr._ttl_days(),
                "max_docs": mgr._max_docs(),
                "dup_threshold": mgr._dup_threshold(),
                "protect_important": mgr._protect_important(),
                "consolidate_enabled": mgr._consolidate_enabled(),
                "rerank_enabled": mgr._rerank_enabled(),
                "rerank_provider_id": mgr._rerank_provider_id(),
            }
            return _ok(data)
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 获取整合配置失败: {exc}", exc_info=True)
            return _error(str(exc))

    async def run_upgrade(self) -> dict[str, Any]:
        """一键升级所有用户的旧格式记忆。"""
        ready, err = await self._ensure_memory_manager()
        if err:
            return err
        mgr, _ = ready

        try:
            res = await mgr.upgrade_all_memories()
            return _ok(res)
        except Exception as exc:
            logger.error(f"[IsolatedMemory PageAPI] 一键升级记忆失败: {exc}", exc_info=True)
            return _error(str(exc))

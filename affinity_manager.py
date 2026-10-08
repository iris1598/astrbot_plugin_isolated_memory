"""
affinity_manager.py - 统一好感度、自由关系与轻量心境数据管理层

采用 SQLite 关系型存储，彻底告别旧版多 JSON 并发锁与数据丢失风险。
核心特性：
1. 无上下限分数存储（-∞ ~ +∞），100% 完整继承历史高分；
2. 自由式关系定位（free-form relationship），不再受 7 档线性天梯束缚；
3. 轻量级即时心境（transient mood）：状态、诱因与生命周期自衰减；
4. 严格隔离：(group_key, user_id, persona_id) 联合主键；
5. 原生一键迁移器：自动无损导入旧版 astrbot_plugin_favorability 数据。
"""

import asyncio
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger


def group_storage_key(umo: str, sender_id: str) -> str:
    """把会话隔离(unique_session)的每用户群 UMO 归一化为群级存储键。

    官方隔离开启后群聊 UMO 形如 {平台}:GroupMessage:{用户}_{群}，
    好感度数据按群共享，剥掉发话者前缀还原为 {平台}:GroupMessage:{群}。
    同时兼容旧版 isolated_queue__{用户}__{群} 格式。
    私聊/webchat 等非群 UMO 原样返回。
    """
    parts = umo.split(":", 2)
    if len(parts) != 3 or parts[1] != "GroupMessage":
        return umo
    sid = parts[2]
    # 兼容旧插件队列格式: isolated_queue__1927736726__1041386550 -> 1041386550
    if "isolated_queue__" in sid:
        sub_parts = sid.split("__")
        if len(sub_parts) >= 3 and sub_parts[-1]:
            return f"{parts[0]}:{parts[1]}:{sub_parts[-1]}"
    prefix = f"{sender_id}_"
    if sender_id and sid.startswith(prefix) and len(sid) > len(prefix):
        return f"{parts[0]}:{parts[1]}:{sid[len(prefix):]}"
    return umo


def extract_user_id(raw: str) -> str:
    """从 @ 提及文本中提取用户 ID。"""
    raw = (raw or "").strip()
    if not raw:
        return raw

    m = re.search(r"\(([^()]+)\)$", raw)
    if not m:
        m = re.search(r"\(([^()]+)\)", raw)
    if m:
        val = m.group(1).strip()
        if val:
            return val

    cleaned = raw.lstrip("@").strip()
    return cleaned if cleaned else raw


class AffinityManager:
    """好感度、自由关系与心境状态数据管理器。"""

    DEFAULT_RELATION = "普通朋友"
    DEFAULT_EVAL = "初次见面"
    DEFAULT_MOOD = "平常心"
    RELATION_PENDING_TTL = 600  # 关系确认提议有效期：10分钟
    RELATION_COOLDOWN = 600     # 关系拒绝后的冷却时间：10分钟

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "affinity_v1.db"
        self._lock = asyncio.Lock()
        self.detected_legacy_groups: set[str] = set()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化 SQLite 数据表与索引。"""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_affinity (
                    group_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT 'default',
                    user_name TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    relation TEXT DEFAULT '普通朋友',
                    pending_rel TEXT DEFAULT NULL,
                    rel_cooldown_until REAL DEFAULT NULL,
                    eval TEXT DEFAULT '初次见面',
                    mood_state TEXT DEFAULT '平常心',
                    mood_reason TEXT DEFAULT '',
                    mood_ttl INTEGER DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (group_key, user_id, persona_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_group_persona_score 
                ON user_affinity(group_key, persona_id, score DESC);
                """
            )
            conn.commit()

    # ── 数据查询与基础获取 ──────────────────────────────────────────

    def get_user_info(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> dict[str, Any]:
        """获取用户好感度档案（带默认值兜底）。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM user_affinity 
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (group_key, uid, pid),
            )
            row = cursor.fetchone()
            if row:
                pending = None
                if row["pending_rel"]:
                    try:
                        pending = json.loads(row["pending_rel"])
                    except Exception:
                        pending = None
                return {
                    "group_key": row["group_key"],
                    "user_id": row["user_id"],
                    "persona_id": row["persona_id"],
                    "user_name": row["user_name"] or "",
                    "score": int(row["score"]),
                    "relation": row["relation"] or self.DEFAULT_RELATION,
                    "pending_rel": pending,
                    "rel_cooldown_until": row["rel_cooldown_until"],
                    "eval": row["eval"] or self.DEFAULT_EVAL,
                    "mood_state": row["mood_state"] or self.DEFAULT_MOOD,
                    "mood_reason": row["mood_reason"] or "",
                    "mood_ttl": int(row["mood_ttl"] or 0),
                    "updated_at": float(row["updated_at"]),
                }

        # 默认新用户
        return {
            "group_key": group_key,
            "user_id": uid,
            "persona_id": pid,
            "user_name": "",
            "score": 0,
            "relation": self.DEFAULT_RELATION,
            "pending_rel": None,
            "rel_cooldown_until": None,
            "eval": self.DEFAULT_EVAL,
            "mood_state": self.DEFAULT_MOOD,
            "mood_reason": "",
            "mood_ttl": 0,
            "updated_at": time.time(),
        }

    def effective_pending(self, user_info: dict[str, Any]) -> Optional[dict[str, Any]]:
        """检查是否有未过期的关系变动提议。"""
        pending = user_info.get("pending_rel")
        if not isinstance(pending, dict):
            return None
        expires_at = pending.get("expires_at", 0)
        if time.time() > expires_at:
            return None
        return pending

    # ── 数据写入与增删改 ──────────────────────────────────────────

    def adjust_score(
        self,
        group_key: str,
        user_id: str,
        delta: int,
        persona_id: str = "default",
        user_name: str = "",
    ) -> int:
        """增减好感度分数（无上下限）。返回更新后的新分值。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT score, user_name FROM user_affinity 
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (group_key, uid, pid),
            )
            row = cursor.fetchone()
            if row:
                new_score = int(row["score"]) + delta
                name = user_name if user_name else row["user_name"]
                conn.execute(
                    """
                    UPDATE user_affinity 
                    SET score = ?, user_name = ?, updated_at = ?
                    WHERE group_key = ? AND user_id = ? AND persona_id = ?
                    """,
                    (new_score, name, now, group_key, uid, pid),
                )
            else:
                new_score = delta
                conn.execute(
                    """
                    INSERT INTO user_affinity (
                        group_key, user_id, persona_id, user_name, score, 
                        relation, eval, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group_key,
                        uid,
                        pid,
                        user_name,
                        new_score,
                        self.DEFAULT_RELATION,
                        self.DEFAULT_EVAL,
                        now,
                    ),
                )
            conn.commit()
            return new_score

    def set_score(
        self,
        group_key: str,
        user_id: str,
        score: int,
        persona_id: str = "default",
        user_name: str = "",
    ) -> None:
        """直接设置好感度数值（管理员操作）。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT user_name FROM user_affinity 
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (group_key, uid, pid),
            )
            row = cursor.fetchone()
            if row:
                name = user_name if user_name else row["user_name"]
                conn.execute(
                    """
                    UPDATE user_affinity 
                    SET score = ?, user_name = ?, updated_at = ?
                    WHERE group_key = ? AND user_id = ? AND persona_id = ?
                    """,
                    (score, name, now, group_key, uid, pid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO user_affinity (
                        group_key, user_id, persona_id, user_name, score, 
                        relation, eval, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group_key,
                        uid,
                        pid,
                        user_name,
                        score,
                        self.DEFAULT_RELATION,
                        self.DEFAULT_EVAL,
                        now,
                    ),
                )
            conn.commit()

    def _ensure_user_row(
        self,
        conn: sqlite3.Connection,
        group_key: str,
        uid: str,
        pid: str,
        user_name: str = "",
    ) -> None:
        """确保用户行在 user_affinity 表中存在。"""
        now = time.time()
        conn.execute(
            """
            INSERT INTO user_affinity (
                group_key, user_id, persona_id, user_name, score, 
                relation, eval, mood_state, mood_reason, mood_ttl, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, '', 0, ?)
            ON CONFLICT(group_key, user_id, persona_id) DO UPDATE SET
                user_name = COALESCE(NULLIF(excluded.user_name, ''), user_affinity.user_name)
            """,
            (
                group_key,
                uid,
                pid,
                user_name,
                self.DEFAULT_RELATION,
                self.DEFAULT_EVAL,
                self.DEFAULT_MOOD,
                now,
            ),
        )

    def update_eval(
        self, group_key: str, user_id: str, eval_text: str, persona_id: str = "default"
    ) -> None:
        """更新对用户的阶段评价/印象。"""
        if not eval_text or not eval_text.strip():
            return
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()
        clean_eval = eval_text.strip()[:30]

        with self._get_connection() as conn:
            self._ensure_user_row(conn, group_key, uid, pid)
            conn.execute(
                """
                UPDATE user_affinity 
                SET eval = ?, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (clean_eval, now, group_key, uid, pid),
            )
            conn.commit()

    def clear_user_eval(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> bool:
        """重置用户评价为初始状态（供 /会话重置 调用），严格保留其它数据。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT eval FROM user_affinity 
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (group_key, uid, pid),
            )
            row = cursor.fetchone()
            if not row or row["eval"] == self.DEFAULT_EVAL:
                return False

            conn.execute(
                """
                UPDATE user_affinity 
                SET eval = ?, mood_state = ?, mood_reason = '', mood_ttl = 0, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (self.DEFAULT_EVAL, self.DEFAULT_MOOD, now, group_key, uid, pid),
            )
            conn.commit()
            return True

    # ── 自由式关系系统 ──────────────────────────────────────────

    def set_relation(
        self, group_key: str, user_id: str, relation: str, persona_id: str = "default"
    ) -> None:
        """直接设定关系（自由式关系标签，管理员或脚本调用）。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()
        clean_rel = (relation or "").strip()[:20] or self.DEFAULT_RELATION

        with self._get_connection() as conn:
            self._ensure_user_row(conn, group_key, uid, pid)
            conn.execute(
                """
                UPDATE user_affinity 
                SET relation = ?, pending_rel = NULL, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (clean_rel, now, group_key, uid, pid),
            )
            conn.commit()

    def propose_relation(
        self,
        group_key: str,
        user_id: str,
        target_relation: str,
        reason: str = "",
        persona_id: str = "default",
        user_name: str = "",
    ) -> tuple[bool, str, dict[str, Any]]:
        """由大模型提议将关系演进为 target_relation。

        Returns:
            tuple[bool, str, dict]: (是否成功创建提议, 原因或当前状态, 提议字典)
        """
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        target_rel = (target_relation or "").strip()[:20]
        if not target_rel:
            return False, "关系名称不能为空", {}

        info = self.get_user_info(group_key, uid, persona_id=pid)
        curr_rel = info["relation"]
        if curr_rel == target_rel:
            return False, f"当前双方关系已经是「{curr_rel}」", {}

        # 检查冷却时间
        now = time.time()
        cooldown = info.get("rel_cooldown_until")
        if cooldown and now < cooldown:
            remaining = int(cooldown - now)
            return False, f"关系变动尚处于冷静期（剩余 {remaining} 秒）", {}

        # 检查是否已有生效中的提议
        active_pending = self.effective_pending(info)
        if active_pending:
            if active_pending.get("to") == target_rel:
                return False, f"已有前往「{target_rel}」的待确认提议", active_pending
            # 允许更新提议

        pending_data = {
            "from": curr_rel,
            "to": target_rel,
            "reason": reason[:50] if reason else "",
            "created_at": now,
            "expires_at": now + self.RELATION_PENDING_TTL,
        }

        with self._get_connection() as conn:
            self._ensure_user_row(conn, group_key, uid, pid, user_name)
            conn.execute(
                """
                UPDATE user_affinity 
                SET pending_rel = ?, user_name = COALESCE(NULLIF(?, ''), user_name), updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (json.dumps(pending_data, ensure_ascii=False), user_name, now, group_key, uid, pid),
            )
            conn.commit()

        return True, "提议已创建", pending_data

    def confirm_relation(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> tuple[bool, str, str]:
        """用户回复「确认关系」，使提议生效。

        Returns:
            tuple[bool, str, str]: (是否成功, 旧关系, 新关系)
        """
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        info = self.get_user_info(group_key, uid, persona_id=pid)
        pending = self.effective_pending(info)
        if not pending:
            return False, info["relation"], ""

        old_rel = pending.get("from") or info["relation"]
        new_rel = pending.get("to", self.DEFAULT_RELATION)
        now = time.time()

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE user_affinity 
                SET relation = ?, pending_rel = NULL, rel_cooldown_until = NULL, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (new_rel, now, group_key, uid, pid),
            )
            conn.commit()

        return True, old_rel, new_rel

    def cancel_relation(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> tuple[bool, str]:
        """用户回复「取消关系」，拒绝并开启冷却时间。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        info = self.get_user_info(group_key, uid, persona_id=pid)
        pending = self.effective_pending(info)
        if not pending:
            return False, ""

        rejected_target = pending.get("to", "")
        now = time.time()

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE user_affinity 
                SET pending_rel = NULL, rel_cooldown_until = ?, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (now + self.RELATION_COOLDOWN, now, group_key, uid, pid),
            )
            conn.commit()

        return True, rejected_target

    # ── 轻量即时心境系统 (Transient Mood) ──────────────────────────

    def update_mood(
        self,
        group_key: str,
        user_id: str,
        state: str,
        reason: str = "",
        ttl: int = 2,
        persona_id: str = "default",
    ) -> None:
        """更新即时心境（保持 1~3 轮，到期自动衰减）。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        clean_state = (state or "").strip()[:10] or self.DEFAULT_MOOD
        clean_reason = (reason or "").strip()[:40]
        actual_ttl = max(1, min(5, int(ttl or 2)))
        now = time.time()

        with self._get_connection() as conn:
            self._ensure_user_row(conn, group_key, uid, pid)
            conn.execute(
                """
                UPDATE user_affinity 
                SET mood_state = ?, mood_reason = ?, mood_ttl = ?, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (clean_state, clean_reason, actual_ttl, now, group_key, uid, pid),
            )
            conn.commit()

    def decay_mood(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> None:
        """轮次自然衰减：每轮心境 TTL 减 1，归零时重置为平常心。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT mood_ttl, mood_state FROM user_affinity 
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (group_key, uid, pid),
            )
            row = cursor.fetchone()
            if not row:
                return

            ttl = int(row["mood_ttl"] or 0)
            if ttl <= 1:
                if row["mood_state"] != self.DEFAULT_MOOD or ttl != 0:
                    conn.execute(
                        """
                        UPDATE user_affinity 
                        SET mood_state = ?, mood_reason = '', mood_ttl = 0
                        WHERE group_key = ? AND user_id = ? AND persona_id = ?
                        """,
                        (self.DEFAULT_MOOD, group_key, uid, pid),
                    )
                    conn.commit()
            else:
                conn.execute(
                    """
                    UPDATE user_affinity 
                    SET mood_ttl = mood_ttl - 1
                    WHERE group_key = ? AND user_id = ? AND persona_id = ?
                    """,
                    (group_key, uid, pid),
                )
                conn.commit()

    # ── 排行榜与重置 ──────────────────────────────────────────────

    def get_leaderboard(
        self,
        group_key: str,
        persona_id: str = "default",
        reverse: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取群好感度排行榜。"""
        pid = (persona_id or "").strip() or "default"
        order = "ASC" if reverse else "DESC"
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT * FROM user_affinity 
                WHERE group_key = ? AND persona_id = ?
                ORDER BY score {order}
                LIMIT ?
                """,
                (group_key, pid, limit),
            )
            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "user_id": row["user_id"],
                        "user_name": row["user_name"] or row["user_id"],
                        "score": int(row["score"]),
                        "relation": row["relation"] or self.DEFAULT_RELATION,
                        "eval": row["eval"] or self.DEFAULT_EVAL,
                        "mood_state": row["mood_state"] or self.DEFAULT_MOOD,
                    }
                )
            return results

    def reset_user(
        self, group_key: str, user_id: str, persona_id: str = "default"
    ) -> None:
        """重置个人好感度（分数归零，关系回到初始状态）。"""
        pid = (persona_id or "").strip() or "default"
        uid = extract_user_id(str(user_id))
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE user_affinity 
                SET score = 0, relation = ?, pending_rel = NULL, 
                    rel_cooldown_until = NULL, eval = ?, mood_state = ?, 
                    mood_reason = '', mood_ttl = 0, updated_at = ?
                WHERE group_key = ? AND user_id = ? AND persona_id = ?
                """,
                (self.DEFAULT_RELATION, self.DEFAULT_EVAL, self.DEFAULT_MOOD, now, group_key, uid, pid),
            )
            conn.commit()

    def list_users(
        self,
        keyword: str = "",
        group_key: str = "",
        persona_id: str = "",
        sort: str = "score_desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """按多条件筛选、搜索和分页查询好感度记录（供 WebUI 后台使用）。"""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        where_clauses = []
        params: list[Any] = []

        if keyword:
            kw = f"%{keyword.strip()}%"
            where_clauses.append(
                "(user_id LIKE ? OR user_name LIKE ? OR relation LIKE ? OR eval LIKE ?)"
            )
            params.extend([kw, kw, kw, kw])

        if group_key:
            where_clauses.append("group_key = ?")
            params.append(group_key.strip())

        if persona_id:
            where_clauses.append("persona_id = ?")
            params.append(persona_id.strip())

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        order_map = {
            "score_desc": "score DESC, updated_at DESC",
            "score_asc": "score ASC, updated_at DESC",
            "updated_desc": "updated_at DESC",
            "updated_asc": "updated_at ASC",
        }
        order_sql = order_map.get(sort, "score DESC, updated_at DESC")

        with self._get_connection() as conn:
            count_cur = conn.execute(
                f"SELECT COUNT(*) FROM user_affinity {where_sql}", params
            )
            total = count_cur.fetchone()[0]

            query_sql = f"""
                SELECT group_key, user_id, persona_id, user_name, score, 
                       relation, eval, mood_state, mood_reason, mood_ttl, updated_at
                FROM user_affinity
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()

            items = []
            for r in rows:
                items.append({
                    "group_key": r["group_key"],
                    "user_id": r["user_id"],
                    "persona_id": r["persona_id"],
                    "user_name": r["user_name"] or "",
                    "score": int(r["score"] or 0),
                    "relation": r["relation"] or self.DEFAULT_RELATION,
                    "eval": r["eval"] or self.DEFAULT_EVAL,
                    "mood_state": r["mood_state"] or self.DEFAULT_MOOD,
                    "mood_reason": r["mood_reason"] or "",
                    "mood_ttl": int(r["mood_ttl"] or 0),
                    "updated_at": float(r["updated_at"] or 0),
                })

            personas = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT persona_id FROM user_affinity ORDER BY persona_id"
                ).fetchall()
                if row[0]
            ]
            groups = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT group_key FROM user_affinity ORDER BY group_key"
                ).fetchall()
                if row[0]
            ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "personas": personas,
            "groups": groups,
        }

    def get_summary_stats(self) -> dict[str, Any]:
        """获取好感度与羁绊系统总览统计（供 WebUI 仪表盘概览使用）。"""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_records,
                    COUNT(DISTINCT user_id) as total_users,
                    COUNT(DISTINCT persona_id) as total_personas,
                    AVG(score) as avg_score,
                    MAX(score) as max_score
                FROM user_affinity
                """
            ).fetchone()
            top_rel_rows = conn.execute(
                """
                SELECT relation, COUNT(*) as cnt
                FROM user_affinity
                GROUP BY relation
                ORDER BY cnt DESC
                LIMIT 6
                """
            ).fetchall()

        return {
            "total_records": row["total_records"] if row else 0,
            "total_users": row["total_users"] if row else 0,
            "total_personas": row["total_personas"] if row else 0,
            "avg_score": round(row["avg_score"] or 0.0, 1) if row else 0.0,
            "max_score": row["max_score"] if (row and row["max_score"] is not None) else 0,
            "relations": {r["relation"]: r["cnt"] for r in top_rel_rows},
        }

    # ── 历史旧数据自动迁移（Zero Data Loss）──────────────────────────

    def _find_legacy_json_files(self, custom_path: Path | str | None = None) -> list[tuple[str, Path]]:
        """智能多源探测 favorability.json 及所有人格/备份数据文件。"""
        targets: list[tuple[str, Path]] = []
        visited_files: set[str] = set()

        def add_file(pid: str, f: Path):
            try:
                rf = str(f.resolve()).lower()
                if rf not in visited_files and f.is_file() and f.stat().st_size > 2:
                    visited_files.add(rf)
                    targets.append((pid, f))
            except Exception:
                pass

        def scan_dir(d: Path):
            if not d.exists() or not d.is_dir():
                return
            try:
                for f in d.iterdir():
                    if f.is_file() and ("favorability" in f.name.lower() and (f.name.lower().endswith((".json", ".bak")) or ".bak." in f.name.lower())):
                        add_file("default", f)
            except Exception:
                pass
            p_dir = d / "personas"
            if p_dir.exists() and p_dir.is_dir():
                try:
                    for sub in p_dir.iterdir():
                        if sub.is_dir():
                            for f in sub.iterdir():
                                if f.is_file() and "favorability" in f.name.lower():
                                    add_file(sub.name, f)
                except Exception:
                    pass

        # 1. 显式路径（若提供且存在有效数据，直接以显式路径为准，避免测试或指定路径时跨域污染）
        if custom_path:
            cp = Path(custom_path)
            if cp.is_file():
                add_file("default", cp)
            elif cp.is_dir():
                scan_dir(cp)
            if targets:
                return targets

        # 2. 仅扫描标准 AstrBot 插件数据目录
        candidate_dirs = [
            Path("data/plugin_data/astrbot_plugin_favorability"),
            Path("AstrBot/data/plugin_data/astrbot_plugin_favorability"),
            Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_favorability",
        ]
        for cd in candidate_dirs:
            scan_dir(cd)

        return targets

    def migrate_from_legacy_plugin(self, legacy_root: Path | str | None = None) -> int:
        """自动无损迁移 astrbot_plugin_favorability 的存量 JSON 数据。

        仅扫描显式传入路径或 AstrBot 标准插件数据目录 (data/plugin_data/astrbot_plugin_favorability)，
        严禁跨目录扫描任何用户私有文件夹。
        返回迁移成功的用户条目数。
        """
        json_targets = self._find_legacy_json_files(legacy_root)
        if not json_targets:
            return 0

        migrated_count = 0
        now = time.time()
        self.detected_legacy_groups = set()

        with self._get_connection() as conn:
            for pid, file_path in json_targets:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        continue

                    for raw_gk, users in data.items():
                        if not isinstance(users, dict):
                            continue
                        for raw_uid, u_data in users.items():
                            if not isinstance(u_data, dict):
                                continue

                            uid = extract_user_id(str(raw_uid))
                            group_key = group_storage_key(raw_gk, uid)

                            # 提取群号
                            if ":GroupMessage:" in group_key:
                                gid = group_key.split(":GroupMessage:")[-1]
                                if gid and not gid.startswith("isolated_queue__"):
                                    self.detected_legacy_groups.add(gid)

                            score = int(u_data.get("score", 0))
                            relation = str(u_data.get("relation") or self.DEFAULT_RELATION)
                            eval_text = str(u_data.get("eval") or self.DEFAULT_EVAL)
                            user_name = str(u_data.get("name") or "")

                            pending_json = None
                            if isinstance(u_data.get("pending_rel"), dict):
                                pending_json = json.dumps(u_data["pending_rel"], ensure_ascii=False)

                            cooldown = u_data.get("rel_cooldown_until")

                            conn.execute(
                                """
                                INSERT INTO user_affinity (
                                    group_key, user_id, persona_id, user_name, 
                                    score, relation, pending_rel, rel_cooldown_until, 
                                    eval, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(group_key, user_id, persona_id) DO UPDATE SET
                                    score = CASE WHEN excluded.score > user_affinity.score THEN excluded.score ELSE user_affinity.score END,
                                    relation = CASE WHEN user_affinity.relation = '普通朋友' AND excluded.relation != '普通朋友' THEN excluded.relation ELSE user_affinity.relation END,
                                    eval = CASE WHEN user_affinity.eval = '初次见面' AND excluded.eval != '初次见面' THEN excluded.eval ELSE user_affinity.eval END,
                                    user_name = COALESCE(NULLIF(user_affinity.user_name, ''), excluded.user_name),
                                    updated_at = excluded.updated_at
                                """,
                                (
                                    group_key,
                                    uid,
                                    pid,
                                    user_name,
                                    score,
                                    relation,
                                    pending_json,
                                    cooldown,
                                    eval_text,
                                    now,
                                ),
                            )
                            migrated_count += 1
                except Exception as exc:
                    logger.warning(f"[AffinityManager] 迁移旧文件 {file_path} 异常: {exc}")

            conn.commit()

        if migrated_count > 0:
            logger.info(
                f"[AffinityManager] 历史好感度数据迁移完成：成功导入 {migrated_count} 位用户档案，检测到群聊: {sorted(list(self.detected_legacy_groups))}"
            )
        return migrated_count

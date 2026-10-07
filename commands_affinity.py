"""
commands_affinity.py - 好感度、自由关系与即时心境指令集

包含面向普通用户与管理员的指令：
普通用户指令：
  - /查询好感度 [或 /好感度] [@用户/UID]
  - /好感度排行 [或 /好感排行]
  - /好感度倒序
  - /重置好感度
  - /确认关系
  - /取消关系
管理员指令：
  - /设置好感度 <@用户> <分数>
  - /设置关系 <@用户> <关系名称>
  - /重置指定好感度 <@用户>
"""

from typing import Any
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .affinity_manager import extract_user_id
from .mentions import extract_at_target_id


class AffinityCommands:
    """好感度与关系指令处理器。"""

    def __init__(self, main_plugin):
        self.plugin = main_plugin

    @property
    def affinity_mgr(self):
        return self.plugin.affinity_mgr

    @property
    def renderer(self):
        return self.plugin.affinity_renderer

    # ── 用户指令：查询好感度 ──────────────────────────────────────

    async def cmd_query(self, event: AstrMessageEvent):
        """查询自己或指定用户的好感度与关系档案。"""
        if not self.plugin.affinity_enabled:
            yield event.plain_result("⚠️ 好感度与羁绊系统当前未启用。")
            return

        group_key, self_id = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)

        # 优先提取 @ 目标
        target_id = extract_at_target_id(event)
        if target_id:
            label = f"用户 {target_id}"
        else:
            # 兼容纯文本后接 ID 参数
            parts = (event.message_str or "").split()
            if len(parts) >= 2:
                target_id = extract_user_id(parts[1])
                label = f"用户 {target_id}"
            else:
                target_id = self_id
                label = "你"

        info = self.affinity_mgr.get_user_info(group_key, target_id, persona_id=persona_id)
        score = info["score"]
        relation = info["relation"]
        evaluation = info["eval"]
        mood_state = info["mood_state"]
        pending_rel = self.affinity_mgr.effective_pending(info)

        # 尝试使用 Pillow 现代渲染器出图
        if self.renderer:
            try:
                display_name = event.get_sender_name() if target_id == self_id else label
                img_path = self.renderer.render_favorability_card(
                    user_name=display_name,
                    user_id=target_id,
                    score=score,
                    relation=relation,
                    evaluation=evaluation,
                    mood_state=mood_state,
                    persona_name=persona_id if persona_id != "default" else "",
                )
                yield event.image_result(img_path)
                return
            except Exception as e:
                logger.warning(f"[Affinity] 图片渲染失败，自动回退纯文本: {e}")

        # 纯文本降级输出
        lines = [
            f"📊 {label}的羁绊档案",
            f"• 关系定位：{relation}",
            f"• 好感累计：{score:+d} 分",
            f"• 当前心境：{mood_state}",
            f"• 直观印象：{evaluation}",
        ]
        if target_id == self_id and pending_rel:
            lines.append(
                f"\n⏳ 待确认的关系变动：「{pending_rel['from']}」→「{pending_rel['to']}」"
                f"\n（回复「/确认关系」生效，或「/取消关系」拒绝）"
            )
        yield event.plain_result("\n".join(lines))

    # ── 用户指令：好感度排行榜 ────────────────────────────────────

    async def cmd_rank(self, event: AstrMessageEvent, reverse: bool = False):
        """查看当前群聊好感度排行榜（高分在前或低分在前）。"""
        if not self.plugin.affinity_enabled:
            yield event.plain_result("⚠️ 好感度与羁绊系统当前未启用。")
            return

        group_key, _ = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)

        leaderboard = self.affinity_mgr.get_leaderboard(
            group_key, persona_id=persona_id, reverse=reverse, limit=10
        )
        if not leaderboard:
            yield event.plain_result("📊 当前会话暂无好感度记录。")
            return

        # 尝试 Pillow 出图
        if self.renderer:
            try:
                group_title = "当前群聊"
                img_path = self.renderer.render_leaderboard(
                    ranked_list=leaderboard,
                    group_title=group_title,
                    persona_name=persona_id if persona_id != "default" else "",
                    reverse=reverse,
                )
                yield event.image_result(img_path)
                return
            except Exception as e:
                logger.warning(f"[Affinity] 排行榜图片渲染失败，回退纯文本: {e}")

        # 纯文本降级
        mode_str = "逆序榜（低分在前）" if reverse else "排行榜"
        lines = [f"🏆 好感度{mode_str}"]
        for idx, item in enumerate(leaderboard, 1):
            name = item["user_name"] or item["user_id"]
            lines.append(
                f"{idx}. {name} | {item['relation']} | {item['score']:+d}分"
            )
        yield event.plain_result("\n".join(lines))

    # ── 用户指令：重置自己的好感度 ────────────────────────────────

    async def cmd_reset_self(self, event: AstrMessageEvent):
        """用户重置自己的好感度记录。"""
        if not self.plugin.affinity_enabled:
            yield event.plain_result("⚠️ 好感度与羁绊系统当前未启用。")
            return

        group_key, self_id = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        self.affinity_mgr.reset_user(group_key, self_id, persona_id=persona_id)
        yield event.plain_result("🔄 你的好感度与关系记录已重置。")

    # ── 用户指令：确认与取消关系 ──────────────────────────────────

    async def cmd_confirm_relation(self, event: AstrMessageEvent):
        """确认待生效的关系变动提议。"""
        if not self.plugin.affinity_enabled:
            yield event.plain_result("⚠️ 好感度与羁绊系统当前未启用。")
            return

        group_key, self_id = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        ok, old_rel, new_rel = self.affinity_mgr.confirm_relation(
            group_key, self_id, persona_id=persona_id
        )
        if not ok:
            yield event.plain_result("⚠️ 当前没有待确认的关系提议（或已过期失效）。")
            return

        sender_name = event.get_sender_name() if hasattr(event, "get_sender_name") else ""
        notice = (
            f" 🎉 双方关系已确认为：「{new_rel}」！\n"
            f"（原关系「{old_rel}」已更新）"
        )
        if hasattr(event, "chain_result"):
            from astrbot.core.message.components import At, Plain
            yield event.chain_result([
                At(name=sender_name or "", qq=self_id),
                Plain(notice)
            ])
        else:
            yield event.plain_result(notice.strip())

    async def cmd_cancel_relation(self, event: AstrMessageEvent):
        """取消待生效的关系变动提议。"""
        if not self.plugin.affinity_enabled:
            yield event.plain_result("⚠️ 好感度与羁绊系统当前未启用。")
            return

        group_key, self_id = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        ok, rejected_rel = self.affinity_mgr.cancel_relation(
            group_key, self_id, persona_id=persona_id
        )
        if not ok:
            yield event.plain_result("⚠️ 当前没有待确认的关系提议。")
            return

        sender_name = event.get_sender_name() if hasattr(event, "get_sender_name") else ""
        notice = f" 🍃 已拒绝将关系调整为「{rejected_rel}」，保持当前关系不变。"
        if hasattr(event, "chain_result"):
            from astrbot.core.message.components import At, Plain
            yield event.chain_result([
                At(name=sender_name or "", qq=self_id),
                Plain(notice)
            ])
        else:
            yield event.plain_result(notice.strip())

    # ── 管理员指令 ────────────────────────────────────────────────

    async def cmd_admin_set_score(self, event: AstrMessageEvent):
        """(管理员) 强制设置指定用户好感度。/设置好感度 <@用户> <分数>"""
        if getattr(event, "role", "") != "admin":
            yield event.plain_result("❌ 此命令仅限管理员使用。")
            return

        target_id = extract_at_target_id(event)
        parts = (event.message_str or "").split()

        if target_id:
            if len(parts) < 2:
                yield event.plain_result("❌ 用法: /设置好感度 <@用户> <分数>")
                return
            try:
                score_val = int(parts[-1])
            except ValueError:
                yield event.plain_result("❌ 分数必须是整数。")
                return
        else:
            if len(parts) < 3:
                yield event.plain_result("❌ 用法: /设置好感度 <@用户/UID> <分数>")
                return
            target_id = extract_user_id(parts[1])
            try:
                score_val = int(parts[2])
            except ValueError:
                yield event.plain_result("❌ 分数必须是整数。")
                return

        group_key, _ = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        self.affinity_mgr.set_score(
            group_key, target_id, score_val, persona_id=persona_id
        )
        yield event.plain_result(f"✅ 已将用户 {target_id} 的好感度设为 {score_val}。")

    async def cmd_admin_set_relation(self, event: AstrMessageEvent):
        """(管理员) 强制设置指定用户关系定位。/设置关系 <@用户> <关系名称>"""
        if getattr(event, "role", "") != "admin":
            yield event.plain_result("❌ 此命令仅限管理员使用。")
            return

        target_id = extract_at_target_id(event)
        parts = (event.message_str or "").split()

        if target_id:
            if len(parts) < 2:
                yield event.plain_result("❌ 用法: /设置关系 <@用户> <关系名称>")
                return
            rel_name = parts[-1].strip()
        else:
            if len(parts) < 3:
                yield event.plain_result("❌ 用法: /设置关系 <@用户/UID> <关系名称>")
                return
            target_id = extract_user_id(parts[1])
            rel_name = parts[2].strip()

        group_key, _ = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        self.affinity_mgr.set_relation(
            group_key, target_id, rel_name, persona_id=persona_id
        )
        yield event.plain_result(f"✅ 已将用户 {target_id} 的关系设为「{rel_name}」。")

    async def cmd_admin_reset_user(self, event: AstrMessageEvent):
        """(管理员) 重置指定用户的好感度与关系。/重置指定好感度 <@用户>"""
        if getattr(event, "role", "") != "admin":
            yield event.plain_result("❌ 此命令仅限管理员使用。")
            return

        target_id = extract_at_target_id(event)
        parts = (event.message_str or "").split()
        if not target_id:
            if len(parts) >= 2:
                target_id = extract_user_id(parts[1])
            else:
                yield event.plain_result("❌ 用法: /重置指定好感度 <@用户/UID>")
                return

        group_key, _ = self.plugin.affinity_keys(event)
        persona_id = await self.plugin.resolve_affinity_persona(event)
        self.affinity_mgr.reset_user(group_key, target_id, persona_id=persona_id)
        yield event.plain_result(f"✅ 已重置用户 {target_id} 的好感度档案。")

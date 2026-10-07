"""
mentions.py - 消息提及与 @ 目标用户安全解析工具

统一忽略指向机器人自身以及 @全体成员 的 At 段。
确保「@机器人 查询好感度」查询发送者自己，而「@机器人 查询好感度 @某人」查询某人。
"""

import astrbot.api.message_components as Comp

ALL_MENTION_IDS = {"all", "everyone", "allmember", "全体成员"}


def extract_at_target_id(event) -> str | None:
    """提取消息链中第一个非机器人、非全体成员的 @ 目标用户 ID。"""
    self_id = ""
    get_self_id = getattr(event, "get_self_id", None)
    if callable(get_self_id):
        try:
            self_id = str(get_self_id() or "").strip()
        except Exception:
            self_id = ""

    for comp in _iter_message_components(event):
        if not isinstance(comp, Comp.At):
            continue

        qq = str(getattr(comp, "qq", "") or "").strip()
        if not qq or qq.lower() in ALL_MENTION_IDS:
            continue
        if self_id and qq == self_id:
            continue
        return qq

    return None


def _iter_message_components(event) -> list:
    """兼容提取消息链组件列表。"""
    getter = getattr(event, "get_messages", None)
    if callable(getter):
        try:
            return list(getter() or [])
        except Exception:
            return []
    message_obj = getattr(event, "message_obj", None)
    return list(getattr(message_obj, "message", None) or [])

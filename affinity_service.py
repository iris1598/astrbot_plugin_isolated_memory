"""
affinity_service.py - 好感度、自由关系与即时心境服务模块

核心职责：
1. 请求注入：在 on_llm_request 向 LLM 注入极简高密度的情感与认知上下文（伴随提示词 < 150 字）；
2. 响应解析：从 LLM 最终回复中提取好感微调 [FAV]、即时心境 [MOOD]、关系提议 [REL] 与印象 [EVAL]；
3. 兜底自愈机制：若大模型漏输出 [FAV] 标签，自动按常态对话执行默认活跃自愈（+1），保障用户每轮必定有即时反馈；
4. 绝对防泄漏清洗：三重清洗管道彻底清除正文中的所有内部标签，杜绝给用户带来任何格式污染。
"""

import re
from datetime import datetime
from typing import Any, Optional

WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def format_system_time(current_time: Optional[datetime] = None) -> str:
    """格式化注入 LLM 的系统时间，附带中文星期。"""
    if current_time is None:
        current_time = datetime.now()
    return f"{current_time:%Y-%m-%d %H:%M:%S} {WEEKDAY_NAMES[current_time.weekday()]}"

# ── 多变体鲁棒正则匹配器 ──────────────────────────────────────

# 匹配 [FAV:+1], [FAV:2], [FAV:-2], [+1], [-2], 【+1】, **[FAV:2]** 等
RE_FAV = re.compile(
    r"\*{0,2}[\[【(](?:(?:(?:FAV|好感度?)\s*[:：]\s*([+-]?\s*\d+))|([+-]\d+))[\]】)]\*{0,2}",
    re.IGNORECASE,
)

# 匹配 [MOOD:开心/被夸奖了], [心境:委屈], 【情绪:傲娇赌气】 等
RE_MOOD = re.compile(
    r"\*{0,2}[\[【(](?:MOOD|心境|情绪)\s*[:：]\s*([^\[\]【】()]+?)[\]】)]\*{0,2}",
    re.IGNORECASE,
)

# 匹配 [REL:互怼损友], [关系:并肩战友], 【REL:知心密友】 等自由式关系提议
RE_REL = re.compile(
    r"\*{0,2}[\[【(](?:REL|关系)\s*[:：]\s*([^\[\]【】()]+?)[\]】)]\*{0,2}",
    re.IGNORECASE,
)

# 匹配 [EVAL:喜欢聊游戏的前辈], [印象:开朗], [评价:耐心] 等阶段性印象更新
RE_EVAL = re.compile(
    r"\*{0,2}[\[【(](?:EVAL|印象|评价)\s*[:：]\s*([^\[\]【】()]+?)[\]】)]\*{0,2}",
    re.IGNORECASE,
)


def clean_affinity_tags(text: str) -> str:
    """彻底从正文中剥离所有好感度、心境、关系及旧版遗留标签。"""
    if not text:
        return ""
    cleaned = RE_FAV.sub("", text)
    cleaned = RE_MOOD.sub("", cleaned)
    cleaned = RE_REL.sub("", cleaned)
    cleaned = RE_EVAL.sub("", cleaned)
    # 兼容清理旧版遗留的 MUTE 标签
    cleaned = re.sub(r"\*{0,2}[\[【(]MUTE\s*[:：]\s*\d+[\]】)]\*{0,2}", "", cleaned, flags=re.I)
    # 清理多余空行
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    return cleaned.strip()


def format_bond_depth(score: int) -> str:
    """把无上下限累计数值转化为富有陪伴深度的自然语言描述。"""
    if score >= 3000:
        return f"{score} 分（极深羁绊与漫长陪伴，有极高默契与信赖）"
    if score >= 1000:
        return f"{score} 分（深厚陪伴，相当熟悉与默契）"
    if score >= 300:
        return f"{score} 分（频繁往来，相处熟络）"
    if score >= 50:
        return f"{score} 分（日常交往，彼此熟悉）"
    if score >= -20:
        return f"{score} 分（标准日常相处）"
    if score >= -100:
        return f"{score} 分（略有生疏或隔阂）"
    return f"{score} 分（关系紧张或有明显隔阂）"


class AffinityService:
    """封装 LLM 上下文注入与响应标签解析。"""

    @staticmethod
    def build_prompt_context(
        user_info: Optional[dict[str, Any]] = None,
        affinity_enabled: bool = True,
        mood_enabled: bool = True,
        system_time_enabled: bool = True,
        sender_name: str = "",
        user_id: str = "",
    ) -> str:
        """为当前对话构造极简、高拟人的情感、认知与时间环境上下文。"""
        lines = []

        # 1. 物理真实时间（固定注入，方便 bot 掌握时间感知与星期）
        if system_time_enabled:
            time_str = format_system_time()
            lines.append(f"• 当前时间：{time_str}")

        # 2. 对话用户身份
        if sender_name or user_id:
            user_desc = sender_name or "用户"
            id_desc = f"（ID: {user_id}）" if user_id else ""
            lines.append(f"• 对话用户：{user_desc}{id_desc}")

        # 3. 好感度、自由羁绊与心境设定
        if affinity_enabled and user_info:
            score = int(user_info.get("score", 0))
            relation = str(user_info.get("relation") or "普通朋友")
            eval_text = str(user_info.get("eval") or "初次见面")
            mood_state = str(user_info.get("mood_state") or "平常心")
            mood_reason = str(user_info.get("mood_reason") or "")
            mood_ttl = int(user_info.get("mood_ttl", 0))
            pending = user_info.get("pending_rel")

            lines.append(f"• 关系定位：【{relation}】（请在该关系框架下自然相处）")
            lines.append(f"• 累计好感：{format_bond_depth(score)}")

            if eval_text and eval_text != "初次见面":
                lines.append(f"• 对其印象：{eval_text}")

            # 仅当非平常心且 TTL > 0 时注入当前心境
            if mood_enabled and mood_state != "平常心" and mood_ttl > 0:
                reason_str = f"（因{mood_reason}）" if mood_reason else ""
                lines.append(
                    f"• 即时心境：此刻心里微有【{mood_state}】{reason_str}，请顺应人设自然流露此心境。"
                )

            if isinstance(pending, dict):
                lines.append(
                    f"• 关系提议中：你此前已向对方提议将关系升华/调整为「{pending.get('to')}」，正等待对方表态。"
                )

            lines.append(
                "--- 内部控制指令与格式纪律（后台静默解析，严禁向用户解释或提及） ---\n"
                "1. 绝密防泄漏：所有控制标签（[FAV]、[MOOD]、[REL]、[EVAL]）仅供系统后台自动提取，最终回复中绝不可向用户解释、展示或提及任何好感度、心境、标签等机制！\n"
                "2. 放置位置纪律：若本轮回复需要输出控制标签，必须且仅能放置在回复最终正文的最末尾单行输出，禁止夹杂在正文段落中。\n"
                "3. 可选控制标签协议：\n"
                "   • [FAV:±N]：根据本轮交互情感与态度波动微调好感（N为1~5，如 [FAV:+2]、[FAV:2] 或 [FAV:-1]）。\n"
                "     - 友好互动/日常交流/趣味接梗：+1 ~ +2；深度共鸣/暖心关切/深度认同：+3 ~ +5；恶意冒犯/挑衅辱骂：-1 ~ -5；平稳无波动或机械复读可不输出（好感默认不变）。\n"
                "   • [MOOD:心境/原因]：若情绪起伏显著时输出（如 [MOOD:开心/被夸奖了]、[MOOD:害羞/被调侃]、[MOOD:傲娇赌气/被捉弄]）。\n"
                "   • [REL:新关系]：长期交往关系水到渠成时提议双方关系升华（如 [REL:并肩战友]、[REL:知心密友]）。\n"
                "   • [EVAL:简短印象]：对用户认知有阶段性刷新时输出（20字以内）。"
            )

        if not lines:
            return ""

        if affinity_enabled and user_info:
            header = "[双方情感与相处设定（内部提示，严禁向用户提及或解释本段）]"
        else:
            header = "[当前环境与对话信息（内部提示，严禁向用户提及或解释本段）]"

        return f"{header}\n" + "\n".join(lines)

    @staticmethod
    def parse_response(
        text: str, default_active_boost: bool = False
    ) -> dict[str, Any]:
        """解析模型回复，提取变动并提供兜底自愈。

        Returns:
            dict with:
                fav_delta: int (好感度增减分)
                has_fav_tag: bool (模型是否明确输出了 FAV 标签)
                mood: tuple[str, str] | None (心境名称, 触发原因)
                rel_proposal: str | None (提议的新关系名称)
                eval_text: str | None (新的阶段印象)
                clean_text: str (剥离所有标签后的纯净正文)
        """
        result = {
            "fav_delta": 0,
            "has_fav_tag": False,
            "mood": None,
            "rel_proposal": None,
            "eval_text": None,
            "clean_text": text,
        }

        if not text:
            return result

        # 1. 解析 FAV（兼容 [FAV:+2], [FAV:2], [FAV:-1], [+2], [-1] 等）
        fav_match = RE_FAV.search(text)
        if fav_match:
            try:
                raw_str = (fav_match.group(1) or fav_match.group(2) or "").replace(" ", "")
                val = int(raw_str.replace("+", ""))
                # 限制单次合理增减幅 [-5, 5]，非 0
                if -5 <= val <= 5 and val != 0:
                    result["fav_delta"] = val
                    result["has_fav_tag"] = True
            except (ValueError, TypeError):
                pass

        # 兜底自愈：若模型没有输出标签，但开启了活跃成长，且回复文本正常，默认 +1 即时反馈
        if not result["has_fav_tag"] and default_active_boost:
            clean_len = len(text.strip())
            if clean_len >= 2:
                result["fav_delta"] = 1

        # 2. 解析 MOOD
        mood_match = RE_MOOD.search(text)
        if mood_match:
            raw_mood = mood_match.group(1).strip()
            if "/" in raw_mood:
                parts = raw_mood.split("/", 1)
                state = parts[0].strip()[:10]
                reason = parts[1].strip()[:40]
            else:
                state = raw_mood[:10]
                reason = ""
            if state:
                result["mood"] = (state, reason)

        # 3. 解析 REL
        rel_match = RE_REL.search(text)
        if rel_match:
            raw_rel = rel_match.group(1).strip()
            # 兼容旧版的 up / down 标签
            if raw_rel.lower() not in ("up", "down", "升", "降"):
                result["rel_proposal"] = raw_rel[:20]

        # 4. 解析 EVAL
        eval_match = RE_EVAL.search(text)
        if eval_match:
            raw_eval = eval_match.group(1).strip()
            if raw_eval and len(raw_eval) <= 30:
                result["eval_text"] = raw_eval

        # 5. 彻底剥离所有标签
        result["clean_text"] = clean_affinity_tags(text)
        return result

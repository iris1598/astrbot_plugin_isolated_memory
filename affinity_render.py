"""
affinity_render.py - 现代好感度档案与群排行榜 Pillow 渲染器

特性：
1. 继承原版高质感设计：双主题（dark/light）、圆角渐变、磨砂玻璃胶囊、柔和光晕；
2. 自由式关系徽章：支持任意长度的关系名自适应徽章尺寸与色相哈希匹配；
3. 即时心境徽章：在档案卡直观展示当前心境（如 💖 开心 / 💢 傲娇赌气 / ☕ 平常心）；
4. 无上下限分数高位自适应：千分位格式化（如 +3,855），自适应字号防止溢出；
5. 零网络依赖，毫秒级直出，环境异常自动优雅降级为纯文本。
"""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False
    Image = ImageDraw = ImageFilter = ImageFont = None

_FONT_CANDIDATES = {
    "regular": [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/deng.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ],
    "bold": [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/dengb.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ],
}


def _find_font(bold: bool = False) -> str | None:
    key = "bold" if bold else "regular"
    for candidate in _FONT_CANDIDATES[key]:
        if Path(candidate).exists():
            return candidate
    return None


_FONT_PATHS = {"regular": _find_font(), "bold": _find_font(True)}
_FONT_CACHE: dict[tuple[int, bool], "ImageFont.FreeTypeFont"] = {}


def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = _FONT_PATHS["bold" if bold else "regular"] or _FONT_PATHS["regular"]
    try:
        font = ImageFont.truetype(path, size=size) if path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _rgba(value: str | tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    rgb = _hex(value) if isinstance(value, str) else value
    return (*rgb, alpha)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


# 预设经典关系颜色池
_RELATION_COLORS = {
    "挚爱恋人": "#FF5C7A",
    "知心挚友": "#FF7A5C",
    "熟络好友": "#36C98F",
    "普通朋友": "#8290A8",
    "生疏之交": "#F2A93B",
    "不合对头": "#F05B68",
    "决裂陌路": "#8B5CF6",
    "互怼损友": "#38BDF8",
    "摸鱼搭子": "#34D399",
    "并肩战友": "#F59E0B",
}

# 自由式关系颜色调色盘
_FREE_COLOR_PALETTE = [
    "#FF5C7A", "#FF7A5C", "#36C98F", "#38BDF8", "#818CF8",
    "#A78BFA", "#F472B6", "#FB923C", "#4ADE80", "#2DD4BF"
]


def get_relation_badge_color(relation: str) -> str:
    """自适应获取关系徽章色彩（经典匹配 + 自由式哈希选取）。"""
    rel = (relation or "").strip()
    if rel in _RELATION_COLORS:
        return _RELATION_COLORS[rel]
    if not rel:
        return "#8290A8"
    # 哈希色彩
    h = int(hashlib.md5(rel.encode("utf-8")).hexdigest()[:6], 16)
    return _FREE_COLOR_PALETTE[h % len(_FREE_COLOR_PALETTE)]


_THEMES = {
    "dark": {
        "top": "#242B3F",
        "bottom": "#12161F",
        "surface": "#FFFFFF",
        "text": "#F5F7FC",
        "secondary": "#AEB6C8",
        "tertiary": "#78849A",
        "border": "#FFFFFF",
        "shadow": 135,
        "glow": 34,
        "surface_alpha": 14,
        "surface_strong": 22,
        "border_alpha": 25,
    },
    "light": {
        "top": "#FFFFFF",
        "bottom": "#F1F4F9",
        "surface": "#182033",
        "text": "#1A2130",
        "secondary": "#55607A",
        "tertiary": "#8C95A9",
        "border": "#1B2233",
        "shadow": 48,
        "glow": 18,
        "surface_alpha": 9,
        "surface_strong": 14,
        "border_alpha": 16,
    },
}


class AffinityRenderer:
    """现代化好感度、自由关系与心境卡片渲染器。"""

    def __init__(
        self,
        render_dir: str | Path,
        cache_max_age: int = 3600,
        theme: str = "dark",
    ):
        self.render_dir = Path(render_dir)
        self.render_dir.mkdir(parents=True, exist_ok=True)
        self.cache_max_age = cache_max_age
        self.theme_name = theme if theme in _THEMES else "dark"

    @property
    def theme(self) -> dict:
        return _THEMES[self.theme_name]

    def cleanup_cache(self, max_age: int | None = None) -> tuple[int, int]:
        max_age = self.cache_max_age if max_age is None else max_age
        now = time.time()
        deleted = remaining = 0
        if not self.render_dir.exists():
            return 0, 0
        for file in self.render_dir.iterdir():
            if not file.is_file() or not file.name.startswith("aff_") or file.suffix != ".png":
                continue
            try:
                if now - file.stat().st_mtime > max_age:
                    file.unlink()
                    deleted += 1
                else:
                    remaining += 1
            except OSError:
                remaining += 1
        return deleted, remaining

    def _save_img(self, img: "Image.Image") -> str:
        path = self.render_dir / f"aff_{uuid.uuid4().hex[:12]}.png"
        img.convert("RGBA").save(path, format="PNG", optimize=True)
        return str(path)

    @staticmethod
    def _gradient(size: tuple[int, int], top: str, bottom: str) -> "Image.Image":
        width, height = size
        top_rgb, bottom_rgb = _hex(top), _hex(bottom)
        strip = Image.new("RGB", (1, max(height, 1)))
        for y in range(max(height, 1)):
            strip.putpixel((0, y), _mix(top_rgb, bottom_rgb, y / max(height - 1, 1)))
        return strip.resize((width, height)).convert("RGBA")

    @staticmethod
    def _radial_glow(size: tuple[int, int], color: tuple[int, int, int], alpha: int) -> "Image.Image":
        width, height = size
        glow_size = max(width, height)
        dot = Image.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(dot)
        radius = glow_size // 3
        cx, cy = glow_size // 2, glow_size // 2
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*color, alpha))
        return dot.filter(ImageFilter.GaussianBlur(max(30, radius // 2)))

    def _base_card(self, width: int, height: int, accent: tuple[int, int, int]) -> "Image.Image":
        theme = self.theme
        margin = 24
        canvas = Image.new("RGBA", (width + margin * 2, height + margin * 2), (0, 0, 0, 0))
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (margin + 8, margin + 10, margin + width - 8, margin + height - 5),
            radius=32,
            fill=(0, 0, 0, theme["shadow"]),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))

        card = self._gradient((width, height), theme["top"], theme["bottom"])
        glow = self._radial_glow((width, height), accent, theme["glow"])
        card.alpha_composite(glow, (width - glow.width // 2, -glow.height // 2))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=30, fill=255)
        card.putalpha(mask)
        canvas.alpha_composite(card, (margin, margin))

        border = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(border).rounded_rectangle(
            (margin, margin, margin + width - 1, margin + height - 1),
            radius=30,
            outline=_rgba(theme["border"], theme["border_alpha"]),
            width=1,
        )
        canvas.alpha_composite(border)
        return canvas

    def _surface(
        self,
        canvas: "Image.Image",
        box: tuple[int, int, int, int],
        *,
        radius: int = 18,
        strong: bool = False,
        accent: tuple[int, int, int] | None = None,
    ) -> None:
        theme = self.theme
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        alpha = theme["surface_strong"] if strong else theme["surface_alpha"]
        fill = accent if accent else _hex(theme["surface"])
        ImageDraw.Draw(layer).rounded_rectangle(
            box,
            radius=radius,
            fill=(*fill, alpha if not accent else max(alpha, 18)),
            outline=_rgba(theme["border"], theme["border_alpha"]),
            width=1,
        )
        canvas.alpha_composite(layer)

    @staticmethod
    def _text_width(draw: "ImageDraw.ImageDraw", text: str, font: "ImageFont.FreeTypeFont") -> int:
        return math.ceil(draw.textlength(text, font=font))

    def _ellipsize(self, draw, text: str, font, max_width: int) -> str:
        text = str(text or "")
        if self._text_width(draw, text, font) <= max_width:
            return text
        while text and self._text_width(draw, text + "…", font) > max_width:
            text = text[:-1]
        return text + "…"

    def _fit_font(
        self,
        draw,
        text: str,
        max_width: int,
        preferred_size: int,
        min_size: int,
        *,
        bold: bool = False,
    ):
        for size in range(preferred_size, min_size - 1, -1):
            font = _load_font(size, bold)
            if self._text_width(draw, text, font) <= max_width:
                return font
        return _load_font(min_size, bold)

    def _wrap(self, draw, text: str, font, max_width: int, max_lines: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in str(text or "初次见面"):
            if char == "\n":
                lines.append(current)
                current = ""
            elif self._text_width(draw, current + char, font) <= max_width:
                current += char
            else:
                lines.append(current)
                current = char
            if len(lines) == max_lines:
                break
        if len(lines) < max_lines and current:
            lines.append(current)
        if len(lines) == max_lines:
            consumed = "".join(lines)
            raw = str(text or "初次见面").replace("\n", "")
            if len(consumed) < len(raw):
                lines[-1] = self._ellipsize(draw, lines[-1] + raw[len(consumed):], font, max_width)
        return lines or ["初次见面"]

    @staticmethod
    def _center_text(draw, box, text, font, fill) -> None:
        x0, y0, x1, y1 = box
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - bbox[1]), text, font=font, fill=fill)

    def render_favorability_card(
        self,
        user_name: str,
        user_id: str,
        score: int,
        relation: str = "普通朋友",
        evaluation: str = "初次见面",
        mood_state: str = "平常心",
        persona_name: str = "",
    ) -> str:
        """渲染高颜值个人好感度与心境档案卡。"""
        if not HAS_PIL:
            raise RuntimeError("Pillow 未就绪，无法渲染图片")

        width, height, margin = 720, 430, 24
        badge_color_hex = get_relation_badge_color(relation)
        accent = _hex(badge_color_hex)
        canvas = self._base_card(width, height, accent)
        draw = ImageDraw.Draw(canvas)
        theme = self.theme
        ox, oy = margin, margin

        # 顶部品牌条
        draw.rounded_rectangle((ox + 42, oy + 32, ox + 108, oy + 38), radius=3, fill=accent)

        # 1. 关系徽章（自适应宽度）
        rel_label = relation or "普通朋友"
        badge_font = _load_font(18, True)
        badge_w = self._text_width(draw, rel_label, badge_font) + 26
        badge_box = (ox + 42, oy + 56, ox + 42 + badge_w, oy + 92)
        self._surface(canvas, badge_box, radius=18, accent=accent)
        self._center_text(draw, badge_box, rel_label, badge_font, accent)

        # 2. 心境微胶囊（紧随关系徽章右侧）
        cur_x = badge_box[2] + 12
        if mood_state and mood_state != "平常心":
            mood_tag = f"心境 · {mood_state}"
            mood_font = _load_font(15, True)
            mood_w = self._text_width(draw, mood_tag, mood_font) + 20
            mood_box = (cur_x, oy + 58, cur_x + mood_w, oy + 90)
            mood_color = _hex("#F472B6")
            self._surface(canvas, mood_box, radius=16, accent=mood_color)
            self._center_text(draw, mood_box, mood_tag, mood_font, mood_color)
            cur_x += mood_w + 14

        draw.text(
            (cur_x, oy + 65),
            "BOND & AFFINITY",
            font=_load_font(14, True),
            fill=_hex(theme["tertiary"]),
        )

        # 用户姓名与角色名
        name_font = _load_font(32, True)
        display_name = user_name or f"用户 {user_id}"
        if persona_name and persona_name != "default":
            display_name = f"{display_name} · {persona_name}"
        name = self._ellipsize(draw, display_name, name_font, 380)
        draw.text((ox + 42, oy + 114), name, font=name_font, fill=_hex(theme["text"]))

        id_font = _load_font(16)
        draw.text((ox + 43, oy + 158), f"UID · {user_id}", font=id_font, fill=_hex(theme["tertiary"]))

        # 分数区域（千分位格式化，无上下限高分自适应）
        score_text = f"{score:+,.0f}" if score else "0"
        score_font = self._fit_font(draw, score_text, 250, 64, 26, bold=True)
        score_w = self._text_width(draw, score_text, score_font)
        draw.text((ox + width - 48 - score_w, oy + 76), score_text, font=score_font, fill=accent)

        label_font = _load_font(15, True)
        label = "好 感 累 计"
        label_w = self._text_width(draw, label, label_font)
        draw.text((ox + width - 49 - label_w, oy + 154), label, font=label_font, fill=_hex(theme["tertiary"]))

        # 评价面板
        panel = (ox + 42, oy + 204, ox + width - 42, oy + 346)
        self._surface(canvas, panel, radius=22, strong=True)
        draw.rounded_rectangle((panel[0] + 18, panel[1] + 22, panel[0] + 24, panel[3] - 22), radius=3, fill=accent)
        draw.text((panel[0] + 42, panel[1] + 20), "直观印象", font=_load_font(16, True), fill=_hex(theme["tertiary"]))

        eval_font = _load_font(21)
        eval_lines = self._wrap(draw, evaluation or "初次见面", eval_font, panel[2] - panel[0] - 76, 2)
        for index, line in enumerate(eval_lines):
            draw.text((panel[0] + 42, panel[1] + 52 + index * 32), line, font=eval_font, fill=_hex(theme["text"]))

        # 页脚
        footer_note = f"关系：{rel_label}  |  心境：{mood_state}"
        draw.text((ox + 43, oy + 375), footer_note, font=_load_font(16), fill=_hex(theme["secondary"]))

        wm = "ASTRBOT MEMORY"
        wm_font = _load_font(14, True)
        wm_w = self._text_width(draw, wm, wm_font)
        draw.ellipse((ox + width - 48 - wm_w - 18, oy + 381, ox + width - 40 - wm_w, oy + 389), fill=accent)
        draw.text((ox + width - 34 - wm_w, oy + 375), wm, font=wm_font, fill=_hex(theme["tertiary"]))

        return self._save_img(canvas)

    def render_leaderboard(
        self,
        ranked_list: list[dict[str, Any]],
        group_title: str = "",
        persona_name: str = "",
        reverse: bool = False,
    ) -> str:
        """渲染群好感度排行榜海报。"""
        if not HAS_PIL:
            raise RuntimeError("Pillow 未就绪，无法渲染图片")

        rows = ranked_list[:10]
        width, margin = 760, 24
        row_h = 68
        height = 224 + max(len(rows), 1) * row_h + 60
        accent = _hex("#8B5CF6" if reverse else "#FF5C7A")
        canvas = self._base_card(width, height, accent)
        draw = ImageDraw.Draw(canvas)
        theme = self.theme
        ox, oy = margin, margin

        # 头部标题
        draw.rounded_rectangle((ox + 42, oy + 32, ox + 108, oy + 38), radius=3, fill=accent)
        title_font = _load_font(32, True)
        rank_mode = "逆序榜" if reverse else "排行榜"
        title_text = f"好感度{rank_mode}"
        if persona_name and persona_name != "default":
            title_text += f" · {persona_name}"
        draw.text((ox + 42, oy + 54), title_text, font=title_font, fill=_hex(theme["text"]))

        sub_font = _load_font(16)
        sub_text = group_title or "当前群聊"
        draw.text((ox + 43, oy + 104), sub_text, font=sub_font, fill=_hex(theme["tertiary"]))

        # 列表表头
        th_font = _load_font(15, True)
        oy_table = oy + 144
        draw.text((ox + 50, oy_table), "#", font=th_font, fill=_hex(theme["tertiary"]))
        draw.text((ox + 100, oy_table), "用户", font=th_font, fill=_hex(theme["tertiary"]))
        draw.text((ox + 390, oy_table), "关系定位", font=th_font, fill=_hex(theme["tertiary"]))
        draw.text((ox + width - 110, oy_table), "好感度", font=th_font, fill=_hex(theme["tertiary"]))

        # 绘制每行
        start_y = oy_table + 32
        for idx, item in enumerate(rows):
            row_y = start_y + idx * row_h
            row_box = (ox + 36, row_y, ox + width - 36, row_y + row_h - 10)
            self._surface(canvas, row_box, radius=14, strong=(idx < 3))

            # 名次数字或奖牌色
            rank_num = idx + 1
            rank_color = (
                _hex("#F59E0B") if rank_num == 1
                else _hex("#94A3B8") if rank_num == 2
                else _hex("#B45309") if rank_num == 3
                else _hex(theme["tertiary"])
            )
            draw.text((ox + 50, row_y + 16), str(rank_num), font=_load_font(20, True), fill=rank_color)

            # 用户名
            name_text = self._ellipsize(draw, item.get("user_name") or item.get("user_id"), _load_font(19, True), 260)
            draw.text((ox + 100, row_y + 16), name_text, font=_load_font(19, True), fill=_hex(theme["text"]))

            # 关系胶囊
            rel_name = item.get("relation") or "普通朋友"
            rel_color = _hex(get_relation_badge_color(rel_name))
            rel_font = _load_font(14, True)
            pill_w = self._text_width(draw, rel_name, rel_font) + 18
            pill_box = (ox + 390, row_y + 14, ox + 390 + pill_w, row_y + 44)
            self._surface(canvas, pill_box, radius=12, accent=rel_color)
            self._center_text(draw, pill_box, rel_name, rel_font, rel_color)

            # 分数
            score_val = int(item.get("score", 0))
            score_str = f"{score_val:+,.0f}" if score_val else "0"
            score_font = _load_font(20, True)
            sw = self._text_width(draw, score_str, score_font)
            draw.text((ox + width - 52 - sw, row_y + 16), score_str, font=score_font, fill=accent)

        return self._save_img(canvas)

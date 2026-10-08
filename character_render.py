"""鸣潮「人格弹珠」风格角色共鸣海报渲染器。

负责将记忆系统计算出的角色共鸣报告渲染为高质量图片：
- 自动按角色名 / ID 检索并加载对应头像（圆角卡片，无溢出）；
- 默认只展示契合度最高的 Top 5 角色分布，防止角色过多时画面冗长；
- 原生「人格弹珠」暖杏桃色波点、深紫红边框与胶囊徽章；
- 矢量四角星标，完全避免由于字体缺失导致的方框乱码。
"""

from __future__ import annotations

import os
import random
import re
import tempfile
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFont = None

# 内置角色素材目录
PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGES_DIR = PLUGIN_DIR / "characters" / "images"

# 字体候选列表（跨平台支持）
FONT_CANDIDATES_BOLD = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

FONT_CANDIDATES_REGULAR = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _get_font(size: int, bold: bool = False) -> Any:
    """获取指定字号的字体对象，带跨平台多路径降级机制。"""
    if ImageFont is None:
        return None
    candidates = FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REGULAR
    for path_str in candidates:
        try:
            if os.path.exists(path_str):
                return ImageFont.truetype(path_str, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _normalize_name(name: str) -> str:
    """将角色名或文件名标准化（去除标点符号、空格与小人后缀），用于模糊匹配。"""
    n = name.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if n.endswith(ext):
            n = n[: -len(ext)]
    n = re.sub(r"(?:_chibi|-chibi|chibi|_avatar|avatar)", "", n)
    n = re.sub(r"[\s\-_·・\.,/\\!！?？:：]", "", n)
    return n.strip()


def find_character_image(
    name: str,
    char_id: str = "",
    custom_dir: Path | str | None = None,
) -> Path | None:
    """在素材目录中自动检索匹配角色名的图片。

    匹配优先级：
    1. 自定义目录（如果提供）
    2. 插件内置 characters/images 目录
    3. 插件 characters 目录
    4. 工作区角色素材目录（本地环境）

    匹配名称规则：
    - 精确匹配：<name>.png / <name>_chibi.png / <id>.png / <id>_chibi.png
    - 模糊匹配：忽略标点符号（如 `陆赫斯` 自动匹配 `陆·赫斯` 或 `陆赫斯_chibi.png`）
    """
    search_dirs: list[Path] = []
    if custom_dir:
        cd = Path(custom_dir)
        if cd.is_dir():
            search_dirs.append(cd)
            img_sub = cd / "images"
            if img_sub.is_dir():
                search_dirs.append(img_sub)

    if DEFAULT_IMAGES_DIR.is_dir():
        search_dirs.append(DEFAULT_IMAGES_DIR)

    char_dir = PLUGIN_DIR / "characters"
    if char_dir.is_dir() and char_dir not in search_dirs:
        search_dirs.append(char_dir)

    clean_name = _normalize_name(name)
    clean_id = _normalize_name(char_id) if char_id else ""

    exact_prefixes = [name, f"{name}_chibi"]
    if char_id:
        exact_prefixes += [char_id, f"{char_id}_chibi"]

    exts = [".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG"]

    # 1. 优先尝试精确文件名比对
    for d in search_dirs:
        for prefix in exact_prefixes:
            for ext in exts:
                candidate = d / f"{prefix}{ext}"
                if candidate.is_file():
                    return candidate

    # 2. 遍历目录进行归一化模糊匹配（例如 陆·赫斯 -> 陆赫斯）
    for d in search_dirs:
        try:
            for item in d.iterdir():
                if not item.is_file() or item.suffix.lower() not in (
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                ):
                    continue
                file_norm = _normalize_name(item.name)
                if clean_name and (file_norm == clean_name or clean_name in file_norm or file_norm in clean_name):
                    return item
                if clean_id and (file_norm == clean_id or clean_id in file_norm):
                    return item
        except Exception as e:
            logger.debug(f"[CharacterRender] 扫描素材目录异常 {d}: {e}")

    return None


def _draw_rounded_rect(
    draw: Any,
    box: tuple[int, int, int, int],
    radius: int,
    fill=None,
    outline=None,
    width: int = 1,
) -> None:
    """安全绘制圆角矩形。"""
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_halftone_dots(
    img: Any,
    box: tuple[int, int, int, int],
    dot_color=(255, 170, 110, 35),
    spacing: int = 16,
    dot_radius: int = 2,
) -> None:
    """绘制流行漫画半色调网点背景纹理。"""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    x0, y0, x1, y1 = box
    for y in range(y0, y1, spacing):
        for x in range(x0, x1, spacing):
            d.ellipse(
                [x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius],
                fill=dot_color,
            )
    img.alpha_composite(overlay)


def _draw_sparkle(
    draw: Any,
    cx: float,
    cy: float,
    radius: float,
    fill=(255, 255, 255, 255),
) -> None:
    """绘制鸣潮四角星闪光矢量标（绝无缺字方框乱码）。"""
    inner = radius * 0.32
    points = [
        (cx, cy - radius),
        (cx + inner, cy - inner),
        (cx + radius, cy),
        (cx + inner, cy + inner),
        (cx, cy + radius),
        (cx - inner, cy + inner),
        (cx - radius, cy),
        (cx - inner, cy - inner),
    ]
    draw.polygon(points, fill=fill)


def render_character_resonance_poster(
    report: dict[str, Any],
    custom_dir: Path | str | None = None,
    output_path: Path | str | None = None,
    top_k: int = 5,
) -> Path | None:
    """将鸣潮角色匹配报告渲染为「人格弹珠」风格海报图片。

    Args:
        report: 包含 top_character、rankings、commentary、sample_count、used_count 的字典。
        custom_dir: 可选的外部角色素材/配置目录。
        output_path: 可选的输出图片路径，若未提供则写入临时文件。
        top_k: 全域共鸣分布展示角色数量上限，默认仅展示前 5 名。

    Returns:
        Path: 生成的海报图片路径；若 Pillow 缺失或渲染异常则返回 None。
    """
    if Image is None or ImageDraw is None:
        logger.warning("[CharacterRender] 未安装 Pillow 库，跳过海报渲染并降级为纯文本")
        return None

    try:
        top = report.get("top_character") or {}
        char_name = str(top.get("name") or "漂泊者")
        char_id = str(top.get("id") or "")
        title = str(top.get("title") or "共鸣者")
        resonance = int(top.get("resonance") or 50)
        tagline = str(top.get("tagline") or "")
        tags = [str(t) for t in (top.get("tags") or []) if str(t)]
        commentary = str(report.get("commentary") or "")
        if not commentary:
            commentary = f"你在日常记录中展现出鲜明的心智特征，与【{char_name}】的特质最为共振同频。"

        # 默认只展示前 top_k (5) 名角色
        all_rankings = report.get("rankings") or []
        rankings = all_rankings[: max(1, top_k)]

        used_count = report.get("used_count", 0)

        # 画布尺寸
        W, H = 880, 1260
        canvas = Image.new("RGBA", (W, H), (255, 241, 226, 255))
        draw = ImageDraw.Draw(canvas)

        # 1. 顶部到底部暖桃微渐变底板
        for y in range(H):
            ratio = y / float(H)
            r = 255
            g = int(242 * (1 - ratio) + 222 * ratio)
            b = int(226 * (1 - ratio) + 188 * ratio)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        # 绘制半色调漫画波点底纹
        _draw_halftone_dots(
            canvas,
            (20, 20, W - 20, H - 20),
            dot_color=(255, 150, 90, 42),
            spacing=18,
            dot_radius=2,
        )

        # 2. 外部深紫红双层圆角边框
        _draw_rounded_rect(
            draw,
            (18, 18, W - 18, H - 18),
            radius=34,
            outline=(66, 24, 38, 255),
            width=6,
        )
        _draw_rounded_rect(
            draw,
            (26, 26, W - 26, H - 26),
            radius=28,
            outline=(255, 255, 255, 255),
            width=3,
        )

        # 3. 顶部 Header 栏
        header_y = 42
        badge_w, badge_h = 160, 48
        badge_x = 44
        # 人格弹珠胶囊 Badge
        _draw_rounded_rect(
            draw,
            (badge_x, header_y, badge_x + badge_w, header_y + badge_h),
            radius=24,
            fill=(206, 41, 75, 255),
            outline=(66, 24, 38, 255),
            width=3,
        )
        draw.ellipse(
            [badge_x + 12, header_y + 14, badge_x + 32, header_y + 34],
            fill=(255, 255, 255, 255),
        )
        draw.ellipse(
            [badge_x + 16, header_y + 18, badge_x + 22, header_y + 24],
            fill=(206, 41, 75, 255),
        )
        draw.text(
            (badge_x + 40, header_y + 10),
            "人格弹珠",
            font=_get_font(20, bold=True),
            fill=(255, 255, 255, 255),
        )

        # 档案标题
        draw.text(
            (badge_x + badge_w + 18, header_y + 10),
            "漂泊者记忆 · 角色共鸣档案",
            font=_get_font(24, bold=True),
            fill=(66, 24, 38, 255),
        )
        archive_code = f"#{random.randint(10000000, 99999999)}"
        draw.text(
            (W - 200, header_y + 16),
            f"档案码: {archive_code}",
            font=_get_font(14, bold=False),
            fill=(138, 92, 102, 255),
        )
        draw.line([(44, 106), (W - 44, 106)], fill=(230, 180, 150, 255), width=2)

        # 4. Hero 区域：中央角色卡片（纯白实心无透明度底板）
        hero_card_top = 126
        hero_card_h = 360
        hero_box = (44, hero_card_top, W - 44, hero_card_top + hero_card_h)

        _draw_rounded_rect(
            draw,
            hero_box,
            radius=24,
            fill=(255, 255, 255, 255),
            outline=(242, 192, 158, 255),
            width=2,
        )
        # 装饰小角标
        draw.polygon(
            [
                (hero_box[0] + 16, hero_box[1] + 16),
                (hero_box[0] + 36, hero_box[1] + 16),
                (hero_box[0] + 16, hero_box[1] + 36),
            ],
            fill=(255, 215, 60, 255),
        )
        draw.polygon(
            [
                (hero_box[2] - 16, hero_box[1] + 16),
                (hero_box[2] - 36, hero_box[1] + 16),
                (hero_box[2] - 16, hero_box[1] + 36),
            ],
            fill=(58, 224, 198, 255),
        )

        # 自动检索角色对应头像图片
        chibi_img_path = find_character_image(
            char_name, char_id=char_id, custom_dir=custom_dir
        )
        chibi_size = 320
        chibi_cx = hero_box[0] + 20
        chibi_cy = hero_card_top + 20

        if chibi_img_path and chibi_img_path.exists():
            try:
                with Image.open(chibi_img_path) as c_img:
                    c_resized = c_img.convert("RGBA").resize(
                        (chibi_size, chibi_size), Image.Resampling.LANCZOS
                    )
                    # 严密圆角蒙版（不露出任何多余底色，彻底杜绝圆底泄漏）
                    mask = Image.new("L", (chibi_size, chibi_size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle(
                        (0, 0, chibi_size, chibi_size), radius=22, fill=255
                    )
                    c_resized.putalpha(mask)
                    canvas.alpha_composite(c_resized, (chibi_cx, chibi_cy))
                    # 角色卡片圆角微描边
                    _draw_rounded_rect(
                        draw,
                        (
                            chibi_cx,
                            chibi_cy,
                            chibi_cx + chibi_size,
                            chibi_cy + chibi_size,
                        ),
                        radius=22,
                        outline=(242, 192, 158, 255),
                        width=3,
                    )
            except Exception as e:
                logger.warning(
                    f"[CharacterRender] 加载角色图片失败 ({chibi_img_path}): {e}"
                )
        else:
            # 未找到图片时的优雅降级底座
            _draw_rounded_rect(
                draw,
                (
                    chibi_cx,
                    chibi_cy,
                    chibi_cx + chibi_size,
                    chibi_cy + chibi_size,
                ),
                radius=22,
                fill=(255, 235, 215, 255),
                outline=(242, 192, 158, 255),
                width=3,
            )
            _draw_sparkle(
                draw,
                chibi_cx + chibi_size // 2,
                chibi_cy + chibi_size // 2 - 20,
                radius=36,
                fill=(238, 76, 90, 255),
            )
            draw.text(
                (chibi_cx + chibi_size // 2 - 28, chibi_cy + chibi_size // 2 + 30),
                char_name[:2],
                font=_get_font(28, bold=True),
                fill=(66, 24, 38, 255),
            )

        # Hero 右侧信息
        info_x = hero_box[0] + chibi_size + 44
        cur_y = hero_card_top + 34

        # 称号胶囊
        if title:
            title_w = len(title) * 16 + 26
            _draw_rounded_rect(
                draw,
                (info_x, cur_y, info_x + title_w, cur_y + 26),
                radius=13,
                fill=(255, 230, 200, 255),
                outline=(230, 160, 120, 255),
                width=1,
            )
            draw.text(
                (info_x + 13, cur_y + 4),
                title,
                font=_get_font(13, bold=True),
                fill=(180, 70, 40, 255),
            )

        # 核心共鸣角色大名
        cur_y += 34
        draw.text(
            (info_x, cur_y),
            char_name,
            font=_get_font(42, bold=True),
            fill=(66, 24, 38, 255),
        )

        # 契合度徽章 (纯色饱满药丸胶囊，去除任何超格的高光横线)
        cur_y += 62
        pct_box = (info_x, cur_y, info_x + 230, cur_y + 54)
        _draw_rounded_rect(
            draw,
            pct_box,
            radius=27,
            fill=(238, 76, 90, 255),
            outline=(66, 24, 38, 255),
            width=3,
        )
        draw.text(
            (info_x + 22, cur_y + 14),
            "契合度",
            font=_get_font(18, bold=True),
            fill=(255, 255, 255, 255),
        )
        draw.text(
            (info_x + 104, cur_y + 1),
            f"{resonance}%",
            font=_get_font(34, bold=True),
            fill=(255, 255, 255, 255),
        )

        # 特质标签胶囊排
        cur_y += 74
        tag_x = info_x
        for tag in tags[:4]:
            tag_w = len(tag) * 16 + 22
            _draw_rounded_rect(
                draw,
                (tag_x, cur_y, tag_x + tag_w, cur_y + 30),
                radius=15,
                fill=(255, 242, 230, 255),
                outline=(220, 150, 100, 255),
                width=1,
            )
            draw.text(
                (tag_x + 11, cur_y + 5),
                tag,
                font=_get_font(13, bold=True),
                fill=(130, 60, 40, 255),
            )
            tag_x += tag_w + 10
            if tag_x > W - 180:
                break

        # 经典金句
        if tagline:
            cur_y += 44
            draw.text(
                (info_x, cur_y),
                f"“{tagline[:26]}”",
                font=_get_font(14, bold=False),
                fill=(140, 80, 90, 255),
            )

        # 5. 中间：漫画气泡风格的共鸣解析（纯白实心无透明度底板）
        bubble_top = hero_card_top + hero_card_h + 20
        bubble_h = 170
        bubble_box = (44, bubble_top, W - 44, bubble_top + bubble_h)

        _draw_rounded_rect(
            draw,
            bubble_box,
            radius=22,
            fill=(255, 255, 255, 255),
            outline=(238, 76, 90, 255),
            width=2,
        )

        # 气泡标题标头
        sec_title_box = (
            bubble_box[0] + 20,
            bubble_top - 14,
            bubble_box[0] + 160,
            bubble_top + 18,
        )
        _draw_rounded_rect(
            draw,
            sec_title_box,
            radius=16,
            fill=(238, 76, 90, 255),
        )
        _draw_sparkle(
            draw,
            sec_title_box[0] + 18,
            (sec_title_box[1] + sec_title_box[3]) / 2,
            radius=5,
            fill=(255, 255, 255, 255),
        )
        draw.text(
            (sec_title_box[0] + 28, sec_title_box[1] + 5),
            "频率共振解析",
            font=_get_font(14, bold=True),
            fill=(255, 255, 255, 255),
        )

        # 共鸣解析正文（按宽度折行）
        commentary_y = bubble_top + 32
        max_line_chars = 34
        for i in range(0, len(commentary), max_line_chars):
            line = commentary[i : i + max_line_chars]
            draw.text(
                (bubble_box[0] + 24, commentary_y),
                line,
                font=_get_font(17, bold=False),
                fill=(66, 24, 38, 255),
            )
            commentary_y += 32

        # 金句引述条
        if tagline:
            quote_y = bubble_top + bubble_h - 40
            draw.text(
                (bubble_box[0] + 24, quote_y),
                f"核心共振语：{tagline}",
                font=_get_font(14, bold=True),
                fill=(190, 60, 75, 255),
            )

        # 6. 下部：全域角色共鸣度分布卡片（纯白实心无透明度底板）
        dist_top = bubble_top + bubble_h + 24
        dist_h = 390
        dist_box = (44, dist_top, W - 44, dist_top + dist_h)

        _draw_rounded_rect(
            draw,
            dist_box,
            radius=22,
            fill=(255, 255, 255, 255),
            outline=(242, 192, 158, 255),
            width=2,
        )

        dist_title_w = 210
        _draw_rounded_rect(
            draw,
            (
                dist_box[0] + 20,
                dist_top - 14,
                dist_box[0] + 20 + dist_title_w,
                dist_top + 18,
            ),
            radius=16,
            fill=(66, 24, 38, 255),
        )
        _draw_sparkle(
            draw,
            dist_box[0] + 36,
            dist_top + 2,
            radius=5,
            fill=(255, 255, 255, 255),
        )
        draw.text(
            (dist_box[0] + 46, dist_top - 9),
            "全域角色共鸣度分布",
            font=_get_font(14, bold=True),
            fill=(255, 255, 255, 255),
        )

        row_y = dist_top + 36
        bar_x = dist_box[0] + 150
        bar_max_w = W - 44 - 150 - 120

        bar_colors = [
            (238, 76, 90, 255),   # 1st: 珊瑚绯红
            (255, 150, 60, 255),  # 2nd: 活力橙黄
            (240, 180, 50, 255),  # 3rd: 柠檬琥珀
            (58, 190, 170, 255),  # 4th: 碧波青绿
            (140, 120, 210, 255), # 5th: 幻梦浅紫
        ]

        for idx, r in enumerate(rankings):
            r_name = str(r.get("name") or "")
            r_pct = int(r.get("resonance") or 50)
            c_fill = bar_colors[idx % len(bar_colors)]

            # 编号与角色名
            rank_label = f"0{idx+1} "
            draw.text(
                (dist_box[0] + 24, row_y + 6),
                rank_label,
                font=_get_font(16, bold=True),
                fill=(206, 41, 75, 255) if idx == 0 else (160, 110, 120, 255),
            )
            draw.text(
                (dist_box[0] + 54, row_y + 4),
                r_name,
                font=_get_font(18, bold=True),
                fill=(66, 24, 38, 255),
            )

            # 进度条背景槽
            bar_h = 24
            _draw_rounded_rect(
                draw,
                (bar_x, row_y + 5, bar_x + bar_max_w, row_y + 5 + bar_h),
                radius=12,
                fill=(255, 235, 222, 255),
                outline=(235, 205, 185, 255),
                width=1,
            )

            # 纯色进度条填充（平整圆润，绝无切边溢出）
            fill_w = int(bar_max_w * (r_pct / 100.0))
            if fill_w > 12:
                _draw_rounded_rect(
                    draw,
                    (bar_x, row_y + 5, bar_x + fill_w, row_y + 5 + bar_h),
                    radius=12,
                    fill=c_fill,
                )

            # 百分比数字
            draw.text(
                (bar_x + bar_max_w + 18, row_y + 3),
                f"{r_pct}%",
                font=_get_font(20, bold=True),
                fill=c_fill if idx == 0 else (66, 24, 38, 255),
            )

            row_y += 64

        # 7. 底部说明
        footer_y = H - 84
        sample_label = f"• 样本依据：基于最近 {used_count} 条长期记忆推测生成"
        draw.text(
            (44, footer_y),
            sample_label,
            font=_get_font(14, bold=False),
            fill=(120, 70, 80, 255),
        )
        draw.text(
            (44, footer_y + 26),
            "注：本档案由记忆向量与角色特质比对生成，仅供娱乐参考",
            font=_get_font(13, bold=False),
            fill=(160, 110, 120, 255),
        )
        draw.text(
            (W - 220, footer_y + 12),
            "WUTHERING WAVES",
            font=_get_font(14, bold=True),
            fill=(220, 160, 130, 200),
        )

        # 保存生成的海报文件
        if output_path is None:
            fd, tmp_file = tempfile.mkstemp(prefix="resonance_", suffix=".png")
            os.close(fd)
            target = Path(tmp_file)
        else:
            target = Path(output_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(target), format="PNG")
        logger.info(f"[CharacterRender] 角色共鸣海报渲染完成: {target}")
        return target

    except Exception as e:
        logger.error(f"[CharacterRender] 渲染角色共鸣海报失败: {e}", exc_info=True)
        return None

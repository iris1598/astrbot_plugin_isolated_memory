"""鸣潮角色原图固定位置裁切脚本。

用于从 1920x1080 游戏界面截图中精确截出中央 Q 版角色小人（尺寸 549x549）。
固定坐标范围：
  X: 569 -> 1118
  Y: 296 -> 845

典型用法：
  1. 为新角色裁切并直接存入插件素材库：
     python crop_characters.py 新截图.png -n 忌炎
     -> 自动生成 characters/images/忌炎_chibi.png

  2. 自定义输出路径：
     python crop_characters.py 新截图.png -o 自定义路径.png

  3. 批量扫描目录：
     python crop_characters.py 截图文件夹/ -o characters/images/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("❌ 未安装 Pillow 库，请运行: pip install Pillow", file=sys.stderr)
    sys.exit(1)

PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGES_DIR = PLUGIN_DIR / "characters" / "images"

# 1920x1080 原图下的固定角色框坐标：(left, top, right, bottom)
CROP_BOX = (569, 296, 1118, 845)
TARGET_SIZE = (549, 549)

# 已知原图文件名前缀与角色名映射
DEFAULT_NAME_MAP = {
    "4b21f70b": "爱弥斯",
    "703c034e": "莫宁",
    "ad4bc79b": "达妮娅",
    "b390682b": "陆赫斯",
    "c99b3465": "西格莉卡",
}


def crop_image(input_path: Path, output_path: Path) -> Path:
    """按固定坐标裁切角色小人并保存为 PNG。支持任意分辨率等比自适应映射。"""
    with Image.open(input_path) as img:
        w, h = img.size
        if (w, h) == (1920, 1080):
            box = CROP_BOX
        else:
            scale_x = w / 1920.0
            scale_y = h / 1080.0
            box = (
                int(round(CROP_BOX[0] * scale_x)),
                int(round(CROP_BOX[1] * scale_y)),
                int(round(CROP_BOX[2] * scale_x)),
                int(round(CROP_BOX[3] * scale_y)),
            )

        cropped = img.crop(box)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(str(output_path), format="PNG")
        print(f"✅ 已裁切: {input_path.name} -> {output_path} (尺寸: {cropped.size})")
        return output_path


def batch_crop(directory: Path, output_dir: Path | None = None) -> list[Path]:
    """批量裁切指定目录下所有 1920x1080 的游戏截图。"""
    out_dir = output_dir or DEFAULT_IMAGES_DIR
    results: list[Path] = []
    for file in sorted(directory.glob("*.png")):
        if "chibi" in file.name or "样例" in file.name or "demo" in file.name:
            continue
        try:
            with Image.open(file) as img:
                if img.size != (1920, 1080):
                    continue
        except Exception:
            continue

        base_id = file.stem[:8]
        char_name = DEFAULT_NAME_MAP.get(base_id, file.stem)
        target_name = f"{char_name}_chibi.png"
        out_p = out_dir / target_name
        crop_image(file, out_p)
        results.append(out_p)
    return results


def main():
    parser = argparse.ArgumentParser(description="鸣潮角色原图固定位置裁切工具")
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="原图路径或包含多张原图的目录",
    )
    parser.add_argument(
        "-n",
        "--name",
        default="",
        help="角色中文名（例如: -n 忌炎，自动保存至 characters/images/忌炎_chibi.png）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="自定义输出文件路径或输出目录（可选）",
    )
    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        sys.exit(0)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"❌ 路径不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    if in_path.is_file():
        if args.output:
            out_p = Path(args.output)
            if out_p.is_dir() or str(args.output).endswith(("/", "\\")):
                char_name = args.name or in_path.stem
                out_p = out_p / f"{char_name}_chibi.png"
        elif args.name:
            out_p = DEFAULT_IMAGES_DIR / f"{args.name}_chibi.png"
        else:
            out_p = in_path.with_name(f"{in_path.stem}_chibi.png")

        crop_image(in_path, out_p)

    elif in_path.is_dir():
        out_dir = Path(args.output) if args.output else DEFAULT_IMAGES_DIR
        batch_crop(in_path, out_dir)


if __name__ == "__main__":
    main()

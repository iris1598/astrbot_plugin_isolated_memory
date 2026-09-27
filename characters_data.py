"""鸣潮角色档案数据与加载器。

支持从 characters 目录动态加载 YAML/JSON 配置文件，便于未来随时扩充新角色。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from astrbot.api import logger

DEFAULT_CHARACTERS_DIR = Path(__file__).resolve().parent / "characters"


@dataclass
class CharacterProfile:
    """鸣潮角色档案。"""

    id: str
    name: str
    title: str = ""
    tagline: str = ""
    tags: list[str] = field(default_factory=list)
    desc: str = ""
    quotes: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterProfile | None:
        """从字典构建 CharacterProfile，缺少核心标识或名称时返回 None。"""
        if not isinstance(data, dict):
            return None
        char_id = str(data.get("id") or "").strip()
        name = str(data.get("name") or "").strip()
        if not char_id or not name:
            return None

        tags = [str(t).strip() for t in data.get("tags") or [] if str(t).strip()]
        quotes = [str(q).strip() for q in data.get("quotes") or [] if str(q).strip()]
        anchors = [str(a).strip() for a in data.get("anchors") or [] if str(a).strip()]

        return cls(
            id=char_id,
            name=name,
            title=str(data.get("title") or "").strip(),
            tagline=str(data.get("tagline") or "").strip(),
            tags=tags,
            desc=str(data.get("desc") or "").strip(),
            quotes=quotes,
            anchors=anchors,
        )


_CACHE: dict[str, list[CharacterProfile]] = {}


def load_character_file(file_path: Path) -> CharacterProfile | None:
    """读取单个 YAML/JSON 文件为 CharacterProfile。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return CharacterProfile.from_dict(data)
    except Exception as e:
        logger.warning(f"[IsolatedMemory] 读取角色文件失败 ({file_path}): {e}")
        return None


def get_characters(
    custom_dir: str | Path | None = None, force_reload: bool = False
) -> list[CharacterProfile]:
    """获取所有已注册的鸣潮角色列表。

    优先加载 custom_dir（若有效），否则加载插件自带的 characters 目录。
    """
    target_dir = Path(custom_dir) if custom_dir else DEFAULT_CHARACTERS_DIR
    cache_key = str(target_dir.resolve()) if target_dir.exists() else "default"

    if not force_reload and cache_key in _CACHE:
        return _CACHE[cache_key]

    characters: list[CharacterProfile] = []
    if target_dir.is_dir():
        for file in sorted(target_dir.glob("*.yaml")) + sorted(target_dir.glob("*.yml")):
            char = load_character_file(file)
            if char:
                characters.append(char)

    # 如果指定自定义目录但未读取到角色，回退内置目录
    if not characters and target_dir != DEFAULT_CHARACTERS_DIR and DEFAULT_CHARACTERS_DIR.is_dir():
        for file in sorted(DEFAULT_CHARACTERS_DIR.glob("*.yaml")) + sorted(DEFAULT_CHARACTERS_DIR.glob("*.yml")):
            char = load_character_file(file)
            if char:
                characters.append(char)

    _CACHE[cache_key] = characters
    return characters

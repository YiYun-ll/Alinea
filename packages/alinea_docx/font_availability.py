from __future__ import annotations

import os
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".fon"}


def font_key(value: str) -> str:
    return "".join(value.split()).casefold()


def _font_directories() -> list[Path]:
    workspace = Path(__file__).resolve().parents[2]
    directories = [
        workspace / ".tools" / "fonts",
        workspace / ".tools" / "LibreOffice" / "share" / "fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / "Library" / "Fonts",
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
    ]
    if os.environ.get("WINDIR"):
        directories.append(Path(os.environ["WINDIR"]) / "Fonts")
    if os.environ.get("ALINEA_FONT_PATHS"):
        directories.extend(
            Path(value)
            for value in os.environ["ALINEA_FONT_PATHS"].split(os.pathsep)
            if value
        )
    return directories


def _families_from_font(font: TTFont) -> set[str]:
    families = {
        record.toUnicode()
        for record in font["name"].names
        if record.nameID in {1, 4, 16, 17, 22, 25}
    }
    return {font_key(family) for family in families if family.strip()}


@lru_cache(maxsize=1)
def installed_font_families() -> frozenset[str]:
    families: set[str] = set()
    for directory in _font_directories():
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
                continue
            try:
                if path.suffix.lower() == ".ttc":
                    with TTCollection(path, lazy=True) as collection:
                        for font in collection.fonts:
                            families.update(_families_from_font(font))
                else:
                    with TTFont(path, lazy=True) as font:
                        families.update(_families_from_font(font))
            except (OSError, TTLibError, KeyError):
                continue
    return frozenset(families)


def normalize_font_families(values: Iterable[str]) -> frozenset[str]:
    return frozenset(font_key(value) for value in values if value.strip())

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Sequence

Rect = Sequence[float]
LineBox = tuple[Hashable, Rect]


def _finite_values(rect: Rect) -> list[float]:
    values = list(rect)
    if len(values) != 4:
        raise ValueError("a rectangle must contain exactly four coordinates")
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value) for value in values
    ):
        raise ValueError("rectangle coordinates must be finite numbers")
    return [float(value) for value in values]


def validate_normalized_rect(rect: Rect) -> list[float]:
    x0, top, x1, bottom = _finite_values(rect)
    if not 0 <= x0 < x1 <= 1 or not 0 <= top < bottom <= 1:
        raise ValueError(
            "normalized rectangle must satisfy "
            "0 <= x0 < x1 <= 1 and 0 <= top < bottom <= 1"
        )
    return [x0, top, x1, bottom]


def normalize_rect(rect: Rect, page_width: float, page_height: float) -> list[float]:
    if not math.isfinite(page_width) or not math.isfinite(page_height):
        raise ValueError("page dimensions must be finite")
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page dimensions must be positive")
    x0, top, x1, bottom = _finite_values(rect)
    if not 0 <= x0 < x1 <= page_width or not 0 <= top < bottom <= page_height:
        raise ValueError("rectangle must be non-empty and inside the page bounds")
    return validate_normalized_rect(
        [x0 / page_width, top / page_height, x1 / page_width, bottom / page_height]
    )


def rects_by_line(
    boxes: Iterable[LineBox],
    page_width: float,
    page_height: float,
) -> list[list[float]]:
    lines: dict[Hashable, list[float]] = {}
    for line_id, rect in boxes:
        x0, top, x1, bottom = _finite_values(rect)
        if line_id not in lines:
            lines[line_id] = [x0, top, x1, bottom]
        else:
            current = lines[line_id]
            current[0] = min(current[0], x0)
            current[1] = min(current[1], top)
            current[2] = max(current[2], x1)
            current[3] = max(current[3], bottom)
    return [normalize_rect(rect, page_width, page_height) for rect in lines.values()]

from __future__ import annotations

import math

import pytest
from alinea_mapping.coordinates import normalize_rect, rects_by_line, validate_normalized_rect


def test_normalize_rect_uses_top_left_page_coordinates():
    assert normalize_rect([10, 20, 30, 60], 100, 200) == [0.1, 0.1, 0.3, 0.3]
    assert validate_normalized_rect([0, 0, 1, 1]) == [0.0, 0.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("rect", "width", "height"),
    [
        ([-1, 0, 10, 10], 100, 100),
        ([0, 0, 101, 10], 100, 100),
        ([10, 0, 10, 10], 100, 100),
        ([20, 0, 10, 10], 100, 100),
        ([0, 0, 10, math.nan], 100, 100),
        ([0, 0, 10], 100, 100),
        ([0, 0, 10, 10], 0, 100),
    ],
)
def test_normalize_rect_rejects_invalid_geometry(rect, width, height):
    with pytest.raises(ValueError):
        normalize_rect(rect, width, height)


def test_rects_are_merged_per_line_not_per_page():
    rects = rects_by_line(
        [
            (0, [10, 10, 15, 20]),
            (0, [15, 10, 25, 20]),
            (1, [10, 30, 20, 40]),
        ],
        100,
        100,
    )
    assert rects == [
        [0.1, 0.1, 0.25, 0.2],
        [0.1, 0.3, 0.2, 0.4],
    ]


def test_normalized_rect_rejects_out_of_range_and_empty_rectangles():
    for rect in ([0, 0, 1.01, 1], [0, 0, 0, 1], [0.5, 0.5, 0.4, 0.6]):
        with pytest.raises(ValueError):
            validate_normalized_rect(rect)

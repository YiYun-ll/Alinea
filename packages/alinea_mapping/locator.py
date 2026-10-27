from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pdfplumber
from alinea_contracts import (
    DocumentSnapshot,
    Issue,
    LocationFragment,
    LocationMapping,
    ParagraphNode,
)

from alinea_mapping.coordinates import rects_by_line

LOCATION_METHOD = "TEXT_ANCHOR_CONTEXT"
DEFAULT_MIN_SCORE = 0.90
DEFAULT_MIN_MARGIN = 0.08


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    source_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PDFChar:
    text: str
    page_index: int
    x0: float
    top: float
    x1: float
    bottom: float
    line_index: int = 0

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return self.x0, self.top, self.x1, self.bottom


@dataclass(frozen=True, slots=True)
class PDFWord:
    text: str
    page_index: int
    x0: float
    top: float
    x1: float
    bottom: float
    line_index: int = 0


@dataclass(frozen=True, slots=True)
class PDFPageIndex:
    page_index: int
    width: float
    height: float
    rotation: int
    chars: tuple[PDFChar, ...]
    words: tuple[PDFWord, ...]
    normalized_text: str
    normalized_char_map: tuple[PDFChar, ...]
    compact_text: str
    compact_char_map: tuple[PDFChar, ...]


@dataclass(frozen=True, slots=True)
class PDFTextIndex:
    pages: tuple[PDFPageIndex, ...]
    normalized_text: str
    normalized_char_map: tuple[PDFChar | None, ...]
    compact_text: str
    compact_char_map: tuple[PDFChar, ...]


PDFIndex = PDFTextIndex


@dataclass(frozen=True, slots=True)
class _Candidate:
    start: int
    end: int
    score: float
    chars: tuple[PDFChar, ...]


def _nfkc_source_map(text: str, normalized_text: str) -> list[int]:
    per_character_parts: list[str] = []
    atom_sources: list[int] = []
    for source_index, source_char in enumerate(text):
        part = unicodedata.normalize("NFKC", source_char)
        per_character_parts.append(part)
        atom_sources.extend([source_index] * len(part))
    per_character_text = "".join(per_character_parts)
    if per_character_text == normalized_text:
        return atom_sources

    mapped: list[int] = []
    matcher = SequenceMatcher(
        None,
        per_character_text,
        normalized_text,
        autojunk=False,
    )
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            mapped.extend(atom_sources[i1:i2])
            continue
        if operation == "delete":
            continue
        output_length = j2 - j1
        input_length = i2 - i1
        for offset in range(output_length):
            if input_length:
                input_offset = min(
                    offset * input_length // output_length,
                    input_length - 1,
                )
                mapped.append(atom_sources[i1 + input_offset])
            else:
                nearest = i1 - 1 if i1 else 0
                mapped.append(atom_sources[nearest])
    if len(mapped) != len(normalized_text):
        raise RuntimeError("NFKC source mapping length mismatch")
    return mapped


def normalize_with_mapping(text: str) -> NormalizedText:
    normalized_text = unicodedata.normalize("NFKC", text)
    normalized_sources = _nfkc_source_map(text, normalized_text)
    characters: list[str] = []
    source_indices: list[int] = []
    for normalized_char, source_index in zip(
        normalized_text,
        normalized_sources,
        strict=True,
    ):
        if normalized_char.isspace():
            if not characters or characters[-1] == " ":
                continue
            characters.append(" ")
            source_indices.append(source_index)
        else:
            characters.append(normalized_char)
            source_indices.append(source_index)
    if characters and characters[-1] == " ":
        characters.pop()
        source_indices.pop()
    return NormalizedText("".join(characters), tuple(source_indices))


def normalize(text: str) -> str:
    return normalize_with_mapping(text).text


def _compact(text: str) -> str:
    return "".join(char for char in normalize(text) if not char.isspace())


def _finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("PDF geometry must be finite")
    return result


def _coerce_char(item: PDFChar | Mapping[str, Any], page_index: int) -> PDFChar | None:
    if isinstance(item, PDFChar):
        return item if item.text else None
    text = str(item.get("text", ""))
    if not text:
        return None
    return PDFChar(
        text=text,
        page_index=page_index,
        x0=_finite_float(item["x0"]),
        top=_finite_float(item["top"]),
        x1=_finite_float(item["x1"]),
        bottom=_finite_float(item["bottom"]),
        line_index=int(item.get("line_index", -1)),
    )


def _order_chars(chars: list[PDFChar], line_tolerance: float) -> tuple[PDFChar, ...]:
    if not chars:
        return ()
    if all(char.line_index >= 0 for char in chars):
        return tuple(sorted(chars, key=lambda char: (char.line_index, char.x0)))

    lines: list[list[PDFChar]] = []
    centers: list[float] = []
    for char in sorted(chars, key=lambda item: (item.top, item.x0)):
        center = (char.top + char.bottom) / 2
        distances = [abs(center - line_center) for line_center in centers]
        line_index = min(range(len(lines)), key=distances.__getitem__) if lines else -1
        if line_index >= 0:
            line_height = sum(c.bottom - c.top for c in lines[line_index]) / len(lines[line_index])
            tolerance = max(line_tolerance, min(char.bottom - char.top, line_height) * 0.5)
            if distances[line_index] > tolerance:
                line_index = -1
        if line_index < 0:
            lines.append([char])
            centers.append(center)
        else:
            lines[line_index].append(char)
            centers[line_index] = sum(
                (item.top + item.bottom) / 2 for item in lines[line_index]
            ) / len(lines[line_index])

    lines.sort(key=lambda line: min(char.top for char in line))
    ordered: list[PDFChar] = []
    for line_index, line in enumerate(lines):
        for char in sorted(line, key=lambda item: item.x0):
            ordered.append(replace(char, line_index=line_index))
    return tuple(ordered)


def _nearest_line(rect: tuple[float, float, float, float], chars: tuple[PDFChar, ...]) -> int:
    if not chars:
        return -1
    center = (rect[1] + rect[3]) / 2
    char = min(chars, key=lambda item: abs((item.top + item.bottom) / 2 - center))
    return char.line_index


def _coerce_word(
    item: PDFWord | Mapping[str, Any],
    page_index: int,
    chars: tuple[PDFChar, ...],
) -> PDFWord | None:
    if isinstance(item, PDFWord):
        return item if item.text else None
    text = str(item.get("text", ""))
    if not text:
        return None
    rect = (
        _finite_float(item["x0"]),
        _finite_float(item["top"]),
        _finite_float(item["x1"]),
        _finite_float(item["bottom"]),
    )
    line_index = int(item.get("line_index", _nearest_line(rect, chars)))
    return PDFWord(text, page_index, *rect, line_index)


def build_page_index(
    page_index: int,
    width: float,
    height: float,
    chars: Iterable[PDFChar | Mapping[str, Any]],
    words: Iterable[PDFWord | Mapping[str, Any]] = (),
    *,
    rotation: int = 0,
    line_tolerance: float = 3.0,
) -> PDFPageIndex:
    if page_index < 0:
        raise ValueError("page_index must be zero-based and non-negative")
    width = _finite_float(width)
    height = _finite_float(height)
    if width <= 0 or height <= 0:
        raise ValueError("page dimensions must be positive")
    raw_chars = [char for item in chars if (char := _coerce_char(item, page_index)) is not None]
    ordered_chars = _order_chars(raw_chars, line_tolerance)
    page_words = tuple(
        word
        for item in words
        if (word := _coerce_word(item, page_index, ordered_chars)) is not None
    )
    raw_text = "".join(char.text for char in ordered_chars)
    raw_char_map = tuple(char for char in ordered_chars for _ in char.text)
    normalized = normalize_with_mapping(raw_text)
    normalized_char_map = tuple(raw_char_map[index] for index in normalized.source_indices)
    compact_pairs = [
        (char, source_char)
        for char, source_char in zip(normalized.text, normalized_char_map, strict=True)
        if not char.isspace()
    ]
    return PDFPageIndex(
        page_index=page_index,
        width=width,
        height=height,
        rotation=rotation,
        chars=ordered_chars,
        words=page_words,
        normalized_text=normalized.text,
        normalized_char_map=normalized_char_map,
        compact_text="".join(pair[0] for pair in compact_pairs),
        compact_char_map=tuple(pair[1] for pair in compact_pairs),
    )


def build_text_index(pages: Iterable[PDFPageIndex]) -> PDFTextIndex:
    ordered_pages = tuple(sorted(pages, key=lambda page: page.page_index))
    if any(page.page_index != index for index, page in enumerate(ordered_pages)):
        raise ValueError("PDF page indices must be contiguous and zero-based")
    normalized_parts: list[str] = []
    normalized_map: list[PDFChar | None] = []
    for page in ordered_pages:
        if normalized_parts:
            normalized_parts.append("\n")
            normalized_map.append(None)
        normalized_parts.append(page.normalized_text)
        normalized_map.extend(page.normalized_char_map)
    return PDFTextIndex(
        pages=ordered_pages,
        normalized_text="".join(normalized_parts),
        normalized_char_map=tuple(normalized_map),
        compact_text="".join(page.compact_text for page in ordered_pages),
        compact_char_map=tuple(
            char for page in ordered_pages for char in page.compact_char_map
        ),
    )


def build_pdf_index(pdf_path: str | Path) -> PDFTextIndex:
    pages: list[PDFPageIndex] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            pages.append(
                build_page_index(
                    page_index=page_index,
                    width=page.width,
                    height=page.height,
                    chars=page.chars,
                    words=page.extract_words(use_text_flow=False),
                    rotation=page.rotation,
                )
            )
    return build_text_index(pages)


def _context_text(context: str | ParagraphNode | None) -> str | None:
    if context is None:
        return None
    return context if isinstance(context, str) else context.text


def _find_candidates(
    paragraph_text: str,
    pdf_index: PDFTextIndex,
    context_before: str | None,
    context_after: str | None,
) -> list[_Candidate]:
    needle = _compact(paragraph_text)
    if not needle:
        return []
    before = _compact(context_before) if context_before else ""
    after = _compact(context_after) if context_after else ""
    context_count = bool(before) + bool(after)
    main_weight = 1.0 - (0.2 if context_count else 0.0)
    context_weight = 0.2 / context_count if context_count else 0.0

    candidates: list[_Candidate] = []
    start = pdf_index.compact_text.find(needle)
    while start >= 0:
        end = start + len(needle)
        before_score = 0.0
        after_score = 0.0
        if before:
            before_score = float(pdf_index.compact_text[:start].endswith(before))
        if after:
            after_score = float(pdf_index.compact_text[end:].startswith(after))
        score = (
            main_weight
            + context_weight * before_score
            + context_weight * after_score
        )
        candidates.append(
            _Candidate(start, end, score, pdf_index.compact_char_map[start:end])
        )
        start = pdf_index.compact_text.find(needle, start + 1)
    return candidates


def _excerpt(text: str) -> str:
    return " ".join(text.split())[:120]


def _fragments(candidate: _Candidate, pdf_index: PDFTextIndex) -> list[LocationFragment]:
    pages = {page.page_index: page for page in pdf_index.pages}
    chars_by_page: dict[int, list[PDFChar]] = {}
    seen: set[tuple[Any, ...]] = set()
    for char in candidate.chars:
        identity = (
            char.page_index,
            char.line_index,
            char.text,
            *char.rect,
        )
        if identity in seen:
            continue
        seen.add(identity)
        chars_by_page.setdefault(char.page_index, []).append(char)

    fragments: list[LocationFragment] = []
    for page_index, chars in sorted(chars_by_page.items()):
        page = pages[page_index]
        rects = rects_by_line(
            ((char.line_index, char.rect) for char in chars),
            page.width,
            page.height,
        )
        if not rects:
            continue
        fragments.append(
            LocationFragment(
                page_index=page_index,
                page_size_pt={"width": page.width, "height": page.height},
                rects_normalized=rects,
            )
        )
    return fragments


def locate_paragraph(
    paragraph: ParagraphNode,
    pdf_index: PDFTextIndex,
    *,
    context_before: str | ParagraphNode | None = None,
    context_after: str | ParagraphNode | None = None,
    issue_id: str = "",
    preview_sha256: str | None = None,
    renderer_profile_id: str | None = None,
    min_score: float = DEFAULT_MIN_SCORE,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> LocationMapping:
    if not 0 <= min_score <= 1 or not 0 <= min_margin <= 1:
        raise ValueError("location thresholds must be between zero and one")
    common = {
        "issue_id": issue_id,
        "revision_id": paragraph.element_ref.revision_id,
        "preview_pdf_sha256": preview_sha256,
        "renderer_profile_id": renderer_profile_id,
        "anchor_excerpt": _excerpt(paragraph.text),
        "method": LOCATION_METHOD,
    }
    candidates = _find_candidates(
        paragraph.text,
        pdf_index,
        _context_text(context_before),
        _context_text(context_after),
    )
    if not candidates:
        reason = "EMPTY_PARAGRAPH_TEXT" if not _compact(paragraph.text) else "TEXT_NOT_FOUND"
        return LocationMapping(
            **common,
            status="UNLOCATED",
            score=0.0,
            candidate_count=0,
            reason=reason,
        )

    ranked = sorted(candidates, key=lambda candidate: (-candidate.score, candidate.start))
    best = ranked[0]
    candidate_count = len(ranked)
    if best.score < min_score:
        return LocationMapping(
            **common,
            status="UNLOCATED",
            score=best.score,
            candidate_count=candidate_count,
            reason="LOW_LOCATION_SCORE",
        )
    if len(ranked) > 1 and best.score - ranked[1].score < min_margin:
        return LocationMapping(
            **common,
            status="AMBIGUOUS",
            score=best.score,
            candidate_count=candidate_count,
            reason="AMBIGUOUS_TEXT_CANDIDATES",
        )
    try:
        fragments = _fragments(best, pdf_index)
    except ValueError:
        return LocationMapping(
            **common,
            status="UNLOCATED",
            score=best.score,
            candidate_count=candidate_count,
            reason="INVALID_PDF_COORDINATES",
        )
    if not fragments:
        return LocationMapping(
            **common,
            status="UNLOCATED",
            score=best.score,
            candidate_count=candidate_count,
            reason="EMPTY_LOCATION_GEOMETRY",
        )
    return LocationMapping(
        **common,
        status="LOCATED",
        page_index=fragments[0].page_index,
        fragments=fragments,
        score=best.score,
        candidate_count=candidate_count,
    )


def _paragraph_key(paragraph: ParagraphNode) -> tuple[str, int, str]:
    ref = paragraph.element_ref
    return ref.part_uri, ref.paragraph_ordinal, ref.xml_path


def _issue_paragraph_key(issue: Issue) -> tuple[str, int, str]:
    ref = issue.element_ref
    return ref.part_uri, ref.paragraph_ordinal, ref.xml_path


def _neighbors(
    paragraphs: Sequence[ParagraphNode],
    index: int,
) -> tuple[ParagraphNode | None, ParagraphNode | None]:
    paragraph = paragraphs[index]
    before = None
    for candidate in reversed(paragraphs[:index]):
        if candidate.element_ref.part_uri != paragraph.element_ref.part_uri:
            break
        if _compact(candidate.text):
            before = candidate
            break
    after = None
    for candidate in paragraphs[index + 1 :]:
        if candidate.element_ref.part_uri != paragraph.element_ref.part_uri:
            break
        if _compact(candidate.text):
            after = candidate
            break
    return before, after


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _not_rendered(
    issue: Issue,
    preview_sha256: str | None,
    renderer_profile_id: str | None,
) -> Issue:
    location = LocationMapping(
        issue_id=issue.issue_id,
        revision_id=issue.revision_id,
        preview_pdf_sha256=preview_sha256,
        renderer_profile_id=renderer_profile_id,
        status="NOT_RENDERED",
        score=0.0,
        candidate_count=0,
        anchor_excerpt=_excerpt(issue.element_ref.text_excerpt),
        method=LOCATION_METHOD,
        reason="PDF_NOT_RENDERED",
    )
    return issue.model_copy(update={"location": location})


def locate_issues(
    snapshot: DocumentSnapshot,
    issues: Iterable[Issue],
    pdf_path: str | Path | None,
    preview_sha256: str | None,
    renderer_profile_id: str | None,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> list[Issue]:
    issue_list = list(issues)
    path = Path(pdf_path) if pdf_path is not None else None
    if path is None or not path.is_file():
        return [
            _not_rendered(issue, preview_sha256, renderer_profile_id)
            for issue in issue_list
        ]

    pdf_index = build_pdf_index(path)
    preview_sha256 = preview_sha256 or _sha256_file(path)
    paragraphs = {
        _paragraph_key(paragraph): (index, paragraph)
        for index, paragraph in enumerate(snapshot.paragraphs)
    }
    located_issues: list[Issue] = []
    for issue in issue_list:
        entry = paragraphs.get(_issue_paragraph_key(issue))
        mismatch = (
            issue.revision_id != snapshot.revision_id
            or entry is None
            or issue.element_ref.text_sha256 != entry[1].element_ref.text_sha256
        )
        if mismatch:
            location = LocationMapping(
                issue_id=issue.issue_id,
                revision_id=issue.revision_id,
                preview_pdf_sha256=preview_sha256,
                renderer_profile_id=renderer_profile_id,
                status="UNLOCATED",
                score=0.0,
                candidate_count=0,
                anchor_excerpt=_excerpt(issue.element_ref.text_excerpt),
                method=LOCATION_METHOD,
                reason="ANCHOR_MISMATCH",
            )
        else:
            index, paragraph = entry
            before, after = _neighbors(snapshot.paragraphs, index)
            location = locate_paragraph(
                paragraph,
                pdf_index,
                context_before=before,
                context_after=after,
                issue_id=issue.issue_id,
                preview_sha256=preview_sha256,
                renderer_profile_id=renderer_profile_id,
                min_score=min_score,
                min_margin=min_margin,
            ).model_copy(update={"revision_id": issue.revision_id})
        located_issues.append(issue.model_copy(update={"location": location}))
    return located_issues

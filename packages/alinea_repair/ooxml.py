from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import DocumentSnapshot, ElementRef, ParagraphNode, SectionNode
from alinea_docx.ooxml import paragraph_text
from lxml import etree

from alinea_repair._util import normalized_name, sha256_bytes, sha256_text

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
O_NS = "urn:schemas-microsoft-com:office:office"
XML_PATH = tuple[tuple[str, int], ...]

_NAMESPACES = {"w": W_NS, "w14": W14_NS, "r": R_NS, "m": M_NS, "a": A_NS, "o": O_NS}
_PATH_STEP_RE = re.compile(
    r"(?P<prefix>[A-Za-z_][A-Za-z0-9_.-]*):(?P<local>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?:\[(?P<index>[1-9][0-9]*)\])?"
)
_STORY_PART_RE = re.compile(
    r"^word/(?:document|header[0-9]*|footer[0-9]*|footnotes|endnotes|comments)\.xml$"
)

RPR_ORDER = (
    "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint "
    "noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u "
    "effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange"
).split()
PPR_ORDER = (
    "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers "
    "pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE "
    "autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents "
    "suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle "
    "rPr sectPr pPrChange"
).split()
SECTPR_ORDER = (
    "headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders "
    "lnNumType pgNumType cols formProt vAlign noEndnote titlePg textDirection bidi rtlGutter "
    "docGrid printerSettings sectPrChange"
).split()
_ORDERS = {
    f"{{{W_NS}}}rPr": RPR_ORDER,
    f"{{{W_NS}}}pPr": PPR_ORDER,
    f"{{{W_NS}}}sectPr": SECTPR_ORDER,
}


def qname(name: str) -> str:
    if name.startswith("{"):
        return name
    prefix, separator, local = name.partition(":")
    if not separator or prefix not in _NAMESPACES:
        raise ValueError(f"Unsupported qualified XML name: {name}")
    return f"{{{_NAMESPACES[prefix]}}}{local}"


def xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
        remove_comments=False,
        remove_pis=False,
        strip_cdata=False,
        huge_tree=False,
    )


def parse_xml(data: bytes) -> etree._ElementTree:
    return etree.parse(__import__("io").BytesIO(data), xml_parser())


def normalize_package_part(part_uri: str) -> str:
    from alinea_repair.refs import part_name

    return part_name(part_uri)


def is_supported_target_part(part_uri: str) -> bool:
    return bool(_STORY_PART_RE.fullmatch(normalize_package_part(part_uri)))


def require_supported_target_part(part_uri: str) -> str:
    name = normalize_package_part(part_uri)
    if not is_supported_target_part(name):
        raise AlineaError(
            "UNSAFE_REPAIR_OPERATION",
            "Only explicit story parts can be patched; styles and global parts are forbidden",
            status_code=422,
            details={"part_uri": "/" + name},
        )
    return name


def locate_snapshot_element(root: etree._Element, ref: ElementRef) -> etree._Element:
    path = ref.xml_path
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/") or "//" in path:
        raise _stale("ElementRef.xml_path is not an internal absolute element path", ref)
    steps = path[1:].split("/")
    current = root
    for position, raw_step in enumerate(steps):
        match = _PATH_STEP_RE.fullmatch(raw_step)
        if match is None or match.group("prefix") != "w":
            raise _stale("ElementRef.xml_path contains a forbidden XPath construct", ref)
        tag = qname(f"w:{match.group('local')}")
        index = int(match.group("index") or 1)
        if position == 0:
            if current.tag != tag or index != 1:
                raise _stale("ElementRef.xml_path does not match the part root", ref)
            continue
        children = [child for child in current if child.tag == tag]
        if index > len(children):
            raise _stale("ElementRef.xml_path no longer resolves to the target", ref)
        current = children[index - 1]
    if ref.kind == "paragraph" and current.tag != qname("w:p"):
        raise _stale("A paragraph ElementRef did not resolve to w:p", ref)
    if ref.kind == "section" and current.tag not in {
        qname("w:sectPr"),
        qname("w:p"),
        qname("w:body"),
    }:
        raise _stale("A section ElementRef did not resolve to a section container", ref)
    return current


def section_properties(element: etree._Element) -> etree._Element:
    if element.tag == qname("w:sectPr"):
        return element
    if element.tag == qname("w:p"):
        ppr = next((child for child in element if child.tag == qname("w:pPr")), None)
        matches = [] if ppr is None else [child for child in ppr if child.tag == qname("w:sectPr")]
    elif element.tag == qname("w:body"):
        matches = [child for child in element if child.tag == qname("w:sectPr")]
    else:
        matches = []
    if len(matches) != 1:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The section target must contain exactly one existing w:sectPr",
            status_code=409,
        )
    return matches[0]


def descendant_runs(paragraph: etree._Element) -> list[etree._Element]:
    return list(paragraph.iter(qname("w:r")))


def selected_runs(
    paragraph: etree._Element, ref: ElementRef
) -> tuple[list[etree._Element], list[int]]:
    if ref.run_range is None:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "A run operation has no run range",
            status_code=409,
        )
    runs = descendant_runs(paragraph)
    indices = list(range(ref.run_range.start, ref.run_range.end))
    if not indices or ref.run_range.end > len(runs):
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The approved run range is outside the fresh paragraph run list",
            status_code=409,
            details={
                "run_count": len(runs),
                "start": ref.run_range.start,
                "end": ref.run_range.end,
            },
        )
    return [runs[index] for index in indices], indices


def element_path(element: etree._Element) -> XML_PATH:
    reversed_path: list[tuple[str, int]] = []
    current: etree._Element | None = element
    while current is not None:
        parent = current.getparent()
        if parent is None:
            reversed_path.append((str(current.tag), 1))
        else:
            preceding = sum(
                1 for sibling in current.itersiblings(preceding=True) if sibling.tag == current.tag
            )
            reversed_path.append((str(current.tag), preceding + 1))
        current = parent
    return tuple(reversed(reversed_path))


def append_xml_path(base: XML_PATH, relative_path: str) -> XML_PATH:
    result = list(base)
    for step in relative_path.split("/"):
        result.append((qname(step), 1))
    return tuple(result)


def verify_para_id(element: etree._Element, ref: ElementRef) -> None:
    paragraph = (
        element if element.tag == qname("w:p") else next(element.iterancestors(qname("w:p")), None)
    )
    actual = None if paragraph is None else paragraph.get(f"{{{W14_NS}}}paraId")
    expected = ref.para_id
    if (actual.upper() if actual else None) != (expected.upper() if expected else None):
        raise _stale("The target w14:paraId does not match the approved anchor", ref)


def _text_variants(element: etree._Element, node: ParagraphNode | SectionNode) -> set[str]:
    text_nodes = [
        item
        for item in element.iter()
        if item.tag
        in {
            qname("w:t"),
            qname("w:instrText"),
            qname("w:delText"),
            f"{{{M_NS}}}t",
            f"{{{A_NS}}}t",
        }
    ]
    w_text = "".join(item.text or "" for item in text_nodes if item.tag == qname("w:t"))
    all_text = "".join(item.text or "" for item in text_nodes)
    variants = {w_text, all_text}
    if element.tag == qname("w:p"):
        variants.add(paragraph_text(element))
    if isinstance(node, ParagraphNode):
        variants.update((node.text, node.normalized_text))
    return variants


def verify_text_hash(
    element: etree._Element,
    ref: ElementRef,
    node: ParagraphNode | SectionNode,
) -> None:
    expected = ref.text_sha256.removeprefix("sha256:").casefold()
    if isinstance(node, SectionNode):
        actual = sha256_bytes(etree.tostring(element, encoding="utf-8", with_tail=False))
        if not expected or actual.casefold() != expected:
            raise _stale("The target section hash does not match the base XML", ref)
        return
    variants = _text_variants(element, node)
    if not expected or not any(
        sha256_text(candidate).casefold() == expected for candidate in variants
    ):
        raise _stale("The target text hash does not match the base XML", ref)


def verify_context_hashes(snapshot: DocumentSnapshot, ref: ElementRef) -> None:
    normalized_part = ref.part_uri.removeprefix("/")
    if ref.kind == "paragraph":
        refs = [
            paragraph.element_ref
            for paragraph in snapshot.paragraphs
            if paragraph.element_ref.part_uri.removeprefix("/") == normalized_part
        ]
        refs.sort(key=lambda item: item.paragraph_ordinal)
    else:
        refs = [
            section.element_ref
            for section in snapshot.sections
            if section.element_ref.part_uri.removeprefix("/") == normalized_part
        ]
        refs.sort(key=lambda item: (item.section_ordinal is None, item.section_ordinal or 0))
    positions = [
        index for index, item in enumerate(refs) if item.paragraph_ordinal == ref.paragraph_ordinal
    ]
    if len(positions) != 1:
        raise _stale("The target is ambiguous while checking context hashes", ref)
    position = positions[0]
    for context_name, neighbor_index in (
        ("context_before_sha256", position - 1),
        ("context_after_sha256", position + 1),
    ):
        expected = getattr(ref, context_name)
        if expected is None:
            continue
        if neighbor_index < 0 or neighbor_index >= len(refs):
            raise _stale("A context hash has no corresponding snapshot neighbor", ref)
        actual = refs[neighbor_index].text_sha256
        if actual.removeprefix("sha256:").casefold() != expected.removeprefix("sha256:").casefold():
            raise _stale("A target context hash does not match the fresh snapshot", ref)


def target_risks(element: etree._Element) -> list[str]:
    forbidden = {
        qname("w:fldSimple"): "field",
        qname("w:fldChar"): "field",
        qname("w:instrText"): "field",
        qname("w:txbxContent"): "textbox",
        qname("w:pict"): "legacy_drawing_or_textbox",
        qname("w:drawing"): "drawing",
        qname("w:object"): "ole_object",
        qname("w:sdt"): "content_control",
        qname("w:altChunk"): "alt_chunk",
        qname("w:subDoc"): "subdocument",
        f"{{{M_NS}}}oMath": "formula",
        f"{{{M_NS}}}oMathPara": "formula",
        f"{{{O_NS}}}OLEObject": "ole_object",
    }
    return sorted(
        {name for item in element.iter() if (name := forbidden.get(item.tag)) is not None}
    )


def ensure_path(
    base: etree._Element,
    relative_path: str,
    *,
    create: bool,
) -> etree._Element | None:
    current = base
    for step in relative_path.split("/"):
        tag = qname(step)
        matches = [child for child in current if child.tag == tag]
        if len(matches) > 1:
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "Duplicate singleton formatting containers are not safe to patch",
                status_code=422,
                details={"container": step},
            )
        if matches:
            current = matches[0]
            continue
        if not create:
            return None
        child = etree.Element(tag)
        _insert_in_schema_order(current, child)
        current = child
    return current


def _insert_in_schema_order(parent: etree._Element, child: etree._Element) -> None:
    if parent.tag == qname("w:r") and child.tag == qname("w:rPr"):
        parent.insert(0, child)
        return
    if parent.tag == qname("w:p") and child.tag == qname("w:pPr"):
        parent.insert(0, child)
        return
    order = _ORDERS.get(parent.tag)
    if order is None:
        raise AlineaError(
            "UNSAFE_REPAIR_OPERATION",
            "No OOXML insertion order is registered for this formatting container",
            status_code=422,
            details={"parent": str(parent.tag), "child": str(child.tag)},
        )
    local_name = etree.QName(child).localname
    if local_name not in order:
        raise AlineaError(
            "UNSAFE_REPAIR_OPERATION",
            "The requested formatting child is not in the OOXML order whitelist",
            status_code=422,
        )
    unknown = [
        etree.QName(existing).localname
        for existing in parent
        if isinstance(existing.tag, str)
        and existing.tag.startswith(f"{{{W_NS}}}")
        and etree.QName(existing).localname not in order
    ]
    if unknown:
        raise AlineaError(
            "UNSAFE_REPAIR_OPERATION",
            "Unknown formatting children make schema-order insertion unsafe",
            status_code=422,
            details={"children": unknown},
        )
    new_rank = order.index(local_name)
    for index, existing in enumerate(parent):
        if not isinstance(existing.tag, str) or not existing.tag.startswith(f"{{{W_NS}}}"):
            continue
        existing_name = etree.QName(existing).localname
        if order.index(existing_name) > new_rank:
            parent.insert(index, child)
            return
    parent.append(child)


def serialize_xml(tree: etree._ElementTree, original: bytes) -> bytes:
    prefix = original[:256]
    has_declaration = prefix.lstrip(b"\xef\xbb\xbf\xef\xfe\xff").startswith(b"<?xml")
    standalone_match = re.search(rb"standalone\s*=\s*['\"](yes|no)['\"]", prefix, re.IGNORECASE)
    standalone = None
    if standalone_match:
        standalone = standalone_match.group(1).lower() == b"yes"
    encoding = tree.docinfo.encoding or "UTF-8"
    return etree.tostring(
        tree,
        encoding=encoding,
        xml_declaration=has_declaration,
        standalone=standalone,
        pretty_print=False,
    )


@dataclass
class SafetyScan:
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def status(self) -> Literal["PASS", "WARN", "FAIL"]:
        if self.failures:
            return "FAIL"
        if self.warnings:
            return "WARN"
        return "PASS"

    def details(self) -> dict[str, list[dict[str, str]]]:
        return {"failures": self.failures[:100], "warnings": self.warnings[:100]}


def scan_high_risk(parts: dict[str, bytes]) -> SafetyScan:
    scan = SafetyScan()
    lowered_names = {name.casefold() for name in parts}
    if any(name.startswith("_xmlsignatures/") for name in lowered_names):
        scan.failures.append({"code": "DIGITAL_SIGNATURE", "part": "_xmlsignatures"})
    if any("vbaproject" in name or name.endswith(".vba") for name in lowered_names):
        scan.failures.append({"code": "MACRO", "part": "vbaProject"})
    if any(name.startswith("word/embeddings/") for name in lowered_names):
        scan.failures.append({"code": "OLE_OBJECT", "part": "word/embeddings"})
    content_types = parts.get("[Content_Types].xml", b"").lower()
    if b"macroenabled" in content_types or b"vnd.ms-office.vba" in content_types:
        scan.failures.append({"code": "MACRO", "part": "[Content_Types].xml"})

    for name, data in parts.items():
        if not name.casefold().endswith((".xml", ".rels")):
            continue
        if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
            scan.failures.append({"code": "DTD_OR_ENTITY", "part": name})
            continue
        try:
            root = parse_xml(data).getroot()
        except (etree.XMLSyntaxError, ValueError) as error:
            scan.failures.append(
                {"code": "XML_PARSE_ERROR", "part": name, "detail": str(error)[:300]}
            )
            continue
        if name.casefold().endswith(".rels"):
            for relationship in root:
                if relationship.tag != f"{{{PACKAGE_REL_NS}}}Relationship":
                    continue
                rel_type = relationship.get("Type", "")
                normalized_type = normalized_name(rel_type)
                target_mode = relationship.get("TargetMode", "Internal")
                if "oleobject" in normalized_type or "embeddedpackage" in normalized_type:
                    scan.failures.append({"code": "OLE_OBJECT", "part": name, "detail": rel_type})
                if "digitalsignature" in normalized_type or "digital_signature" in normalized_type:
                    scan.failures.append(
                        {"code": "DIGITAL_SIGNATURE", "part": name, "detail": rel_type}
                    )
                if normalized_name(target_mode) == "external":
                    if normalized_type.endswith("hyperlink"):
                        scan.warnings.append(
                            {
                                "code": "EXTERNAL_HYPERLINK",
                                "part": name,
                                "detail": relationship.get("Target", ""),
                            }
                        )
                    else:
                        scan.failures.append(
                            {"code": "EXTERNAL_RELATIONSHIP", "part": name, "detail": rel_type}
                        )
        for item in root.iter():
            if not isinstance(item.tag, str):
                continue
            if item.tag.startswith(f"{{{W_NS}}}"):
                local = etree.QName(item).localname
                normalized_local = normalized_name(local)
                if local in {"ins", "del", "delText", "moveFrom", "moveTo"} or local.endswith(
                    "Change"
                ):
                    scan.failures.append({"code": "TRACK_CHANGES", "part": name, "detail": local})
                if local in {"trackChanges", "documentProtection", "writeProtection", "formProt"}:
                    scan.failures.append(
                        {"code": "PROTECTION_OR_TRACKING", "part": name, "detail": local}
                    )
                if local == "object":
                    scan.failures.append({"code": "OLE_OBJECT", "part": name, "detail": local})
                if normalized_local == "ole_object":
                    scan.failures.append({"code": "OLE_OBJECT", "part": name, "detail": local})
            if item.tag == f"{{{O_NS}}}OLEObject":
                scan.failures.append({"code": "OLE_OBJECT", "part": name, "detail": "OLEObject"})
    return scan


def iter_story_text(root: etree._Element) -> Iterable[tuple[str, str | None]]:
    accepted = {
        qname("w:t"),
        qname("w:instrText"),
        qname("w:delText"),
        f"{{{M_NS}}}t",
        f"{{{A_NS}}}t",
    }
    for item in root.iter():
        if item.tag in accepted:
            yield str(item.tag), item.text


def _stale(message: str, ref: ElementRef) -> AlineaError:
    return AlineaError(
        "STALE_REPAIR_PLAN",
        message,
        status_code=409,
        details={"part_uri": ref.part_uri, "paragraph_ordinal": ref.paragraph_ordinal},
    )

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from alinea_contracts.errors import AlineaError
from alinea_docx import (
    SecurityLimits,
    assert_automatic_repair_allowed,
    parse_docx,
    read_secure_docx,
    validate_docx,
)
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _document_bytes(document: Document | None = None) -> bytes:
    document = document or Document()
    if not document.paragraphs:
        document.add_paragraph("security fixture")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _rewrite_part(data: bytes, name: str, content: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            if info.filename != name:
                target.writestr(info, source.read(info.filename))
        target.writestr(name, content)
    return output.getvalue()


def _append_part(data: bytes, name: str, content: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def _expect_code(code: str, data: bytes, limits: SecurityLimits | None = None) -> AlineaError:
    with pytest.raises(AlineaError) as caught:
        validate_docx(data, limits=limits)
    assert caught.value.code == code
    return caught.value


def test_valid_docx_returns_part_hashes_and_external_relationship_inventory() -> None:
    document = Document()
    document.add_paragraph("safe")
    document.part.relate_to("https://example.invalid/image.png", RT.IMAGE, is_external=True)
    data = _document_bytes(document)

    package = read_secure_docx(data)

    assert package.sha256
    assert package.report.main_part_uri == "/word/document.xml"
    assert {part.part_uri for part in package.report.parts} >= {
        "/[Content_Types].xml",
        "/word/document.xml",
        "/word/styles.xml",
    }
    assert all(len(part.sha256) == 64 for part in package.report.parts)
    external = package.report.external_relationships
    assert len(external) == 1
    assert external[0]["target"] == "https://example.invalid/image.png"
    assert package.report.automatic_repair_allowed


def test_invalid_header_and_compound_file_encryption_are_distinct() -> None:
    _expect_code("DOCX_INVALID_HEADER", b"not a docx")
    _expect_code("DOCX_ENCRYPTED", bytes.fromhex("d0cf11e0a1b11ae1") + b"payload")


def test_configurable_file_entry_and_uncompressed_limits() -> None:
    data = _document_bytes()
    _expect_code("DOCX_FILE_TOO_LARGE", data, SecurityLimits(max_file_bytes=16))
    _expect_code("DOCX_TOO_MANY_ENTRIES", data, SecurityLimits(max_zip_entries=1))
    _expect_code(
        "DOCX_UNCOMPRESSED_TOO_LARGE",
        data,
        SecurityLimits(max_uncompressed_bytes=128),
    )


def test_zip_bomb_ratio_and_path_traversal_are_rejected() -> None:
    data = _document_bytes()
    bomb = _append_part(data, "word/bomb.xml", b"<x>" + b"a" * 20000 + b"</x>")
    _expect_code("DOCX_COMPRESSION_RATIO", bomb)

    traversal = _append_part(data, "../outside.xml", b"<x/>")
    _expect_code("DOCX_PATH_TRAVERSAL", traversal)

    encoded_traversal = _append_part(data, "%2e%2e/outside.xml", b"<x/>")
    _expect_code("DOCX_PATH_TRAVERSAL", encoded_traversal)


def test_macro_and_missing_opc_parts_are_rejected() -> None:
    data = _document_bytes()
    macro = _append_part(data, "word/vbaProject.bin", b"vba")
    _expect_code("DOCX_MACRO_NOT_ALLOWED", macro)

    broken = _rewrite_part(data, "_rels/.rels", b"<Relationships />")
    _expect_code("DOCX_INVALID_OPC", broken)

    wrong_namespace = _rewrite_part(
        data, "[Content_Types].xml", b'<Types xmlns="urn:invalid"/>'
    )
    _expect_code("DOCX_INVALID_OPC", wrong_namespace)


def test_malformed_xml_and_xxe_are_rejected_before_entity_resolution() -> None:
    data = _document_bytes()
    malformed = _rewrite_part(data, "word/document.xml", b"<w:document")
    _expect_code("DOCX_INVALID_XML", malformed)

    xxe_xml = b"""<?xml version="1.0"?>
<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///definitely/not/read.txt">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body>
</w:document>
"""
    xxe = _rewrite_part(data, "word/document.xml", xxe_xml)
    error = _expect_code("DOCX_UNSAFE_XML", xxe)
    assert "definitely/not/read" not in error.message


def test_track_changes_ole_and_protection_block_automatic_repair() -> None:
    document = Document()
    paragraph = document.add_paragraph("risky")
    run = paragraph.add_run("object")
    run._r.append(OxmlElement("w:object"))
    field = OxmlElement("w:fldSimple")
    paragraph._p.append(field)
    math = OxmlElement("m:oMath")
    paragraph._p.append(math)
    text_box = OxmlElement("w:txbxContent")
    paragraph._p.append(text_box)
    insertion = OxmlElement("w:ins")
    inserted_run = OxmlElement("w:r")
    inserted_text = OxmlElement("w:t")
    inserted_text.text = "inserted"
    inserted_run.append(inserted_text)
    insertion.append(inserted_run)
    paragraph._p.append(insertion)
    settings = document.settings.element
    settings.append(OxmlElement("w:trackRevisions"))
    protection = OxmlElement("w:documentProtection")
    protection.set(qn("w:enforcement"), "1")
    settings.append(protection)

    snapshot = parse_docx(_document_bytes(document))

    expected_features = {
        "track_changes",
        "ole_object",
        "document_protection",
        "field",
        "equation",
        "text_box",
    }
    assert expected_features <= set(snapshot.unsupported_features)
    assert {"TRACK_CHANGES", "OLE_OBJECT", "DOCUMENT_PROTECTION"} <= set(
        snapshot.package_inventory["repair_blockers"]
    )
    assert snapshot.package_inventory["automatic_repair_allowed"] is False
    with pytest.raises(AlineaError) as caught:
        assert_automatic_repair_allowed(snapshot)
    assert caught.value.code == "DOCX_AUTO_REPAIR_BLOCKED"

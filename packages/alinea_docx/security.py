from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import DocumentSnapshot, PartDescriptor
from lxml import etree

MIB = 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 15 * MIB
DEFAULT_MAX_ZIP_ENTRIES = 3000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 120 * MIB
DEFAULT_MAX_COMPRESSION_RATIO = 100.0

type DocxSource = bytes | bytearray | memoryview | str | Path | BinaryIO

_DOCTYPE_RE = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_OFFICE_DOCUMENT_RELATIONSHIP = "officeDocument"
_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_RELATIONSHIP_NAMESPACES = {
    "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True, slots=True)
class SecurityLimits:
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_zip_entries: int = DEFAULT_MAX_ZIP_ENTRIES
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO

    def __post_init__(self) -> None:
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if self.max_zip_entries <= 0:
            raise ValueError("max_zip_entries must be positive")
        if self.max_uncompressed_bytes <= 0:
            raise ValueError("max_uncompressed_bytes must be positive")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")


@dataclass(slots=True)
class SecurityReport:
    main_part_uri: str
    parts: list[PartDescriptor]
    relationships: list[dict[str, str]] = field(default_factory=list)
    external_relationships: list[dict[str, str]] = field(default_factory=list)
    high_risk_objects: list[dict[str, str]] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)
    repair_blockers: list[str] = field(default_factory=list)

    @property
    def automatic_repair_allowed(self) -> bool:
        return not self.repair_blockers

    @property
    def auto_repair_allowed(self) -> bool:
        return self.automatic_repair_allowed

    def package_inventory(self) -> dict[str, object]:
        media = [
            {
                "part_uri": part.part_uri,
                "size": part.size,
                "sha256": part.sha256,
                "content_type": part.content_type,
            }
            for part in self.parts
            if part.part_uri.startswith("/word/media/")
        ]
        return {
            "main_part_uri": self.main_part_uri,
            "media": media,
            "relationships": [dict(item) for item in self.relationships],
            "external_relationships": [dict(item) for item in self.external_relationships],
            "high_risk_objects": [dict(item) for item in self.high_risk_objects],
            "repair_blockers": list(self.repair_blockers),
            "automatic_repair_allowed": self.automatic_repair_allowed,
            "auto_repair_allowed": self.automatic_repair_allowed,
        }


@dataclass(frozen=True, slots=True)
class SafeDocxPackage:
    data: bytes
    sha256: str
    report: SecurityReport


@dataclass(slots=True)
class _ValidationState:
    features: set[str] = field(default_factory=set)
    repair_blockers: set[str] = field(default_factory=set)
    high_risk_objects: list[dict[str, str]] = field(default_factory=list)
    _high_risk_keys: set[tuple[str, str]] = field(default_factory=set)

    def add(self, feature: str, part_uri: str, *, blocker: str | None = None) -> None:
        self.features.add(feature)
        key = (feature, part_uri)
        if key not in self._high_risk_keys:
            self._high_risk_keys.add(key)
            self.high_risk_objects.append({"feature": feature, "part_uri": part_uri})
        if blocker:
            self.repair_blockers.add(blocker)


def secure_xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
    )


def parse_xml_bytes(data: bytes, *, part_uri: str = "<xml>") -> etree._Element:
    if _DOCTYPE_RE.search(data):
        raise AlineaError(
            "DOCX_UNSAFE_XML",
            "DTD and entity declarations are not allowed in DOCX XML parts",
            details={"part_uri": part_uri},
        )
    try:
        parser = secure_xml_parser()
        return etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise AlineaError(
            "DOCX_INVALID_XML",
            "The DOCX contains malformed or unsupported XML",
            details={"part_uri": part_uri, "parser_error": str(exc)},
        ) from exc


def read_secure_docx(
    source: DocxSource, *, limits: SecurityLimits | None = None
) -> SafeDocxPackage:
    limits = limits or SecurityLimits()
    data = _read_source(source, limits)
    _check_file_header(data)
    digest = hashlib.sha256(data).hexdigest()

    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            infos = archive.infolist()
            _check_archive_metadata(infos, limits)
            names = {_entry_name(info) for info in infos if not info.is_dir()}
            _check_encryption_and_macros(names)
            parts, xml_roots = _read_entries(archive, infos, limits)
            content_types = _parse_content_types(xml_roots, names)
            relationships = _validate_relationships(xml_roots, names)
            main_part_uri = _find_main_part(relationships, content_types)
            state = _scan_high_risk_objects(parts, xml_roots, relationships)
            report = SecurityReport(
                main_part_uri=main_part_uri,
                parts=[
                    PartDescriptor(
                        part_uri=f"/{name}",
                        content_type=content_types.get(name),
                        size=size,
                        sha256=part_digest,
                    )
                    for name, size, part_digest in parts
                ],
                relationships=relationships,
                external_relationships=[
                    {key: value for key, value in item.items() if key != "resolved_target"}
                    for item in relationships
                    if item["target_mode"].lower() == "external"
                ],
                high_risk_objects=state.high_risk_objects,
                unsupported_features=sorted(state.features),
                repair_blockers=sorted(state.repair_blockers),
            )
    except AlineaError:
        raise
    except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
        raise AlineaError(
            "DOCX_INVALID_ZIP", "The DOCX ZIP container is corrupt or incomplete"
        ) from exc
    except RuntimeError as exc:
        if "encrypted" in str(exc).lower() or "password" in str(exc).lower():
            raise AlineaError(
                "DOCX_ENCRYPTED", "Encrypted DOCX packages are not supported"
            ) from exc
        raise AlineaError("DOCX_INVALID_ZIP", "The DOCX ZIP container cannot be read") from exc
    except NotImplementedError as exc:
        raise AlineaError(
            "DOCX_UNSUPPORTED_COMPRESSION", "The DOCX uses an unsupported ZIP compression method"
        ) from exc

    return SafeDocxPackage(data=data, sha256=digest, report=report)


def validate_docx(source: DocxSource, *, limits: SecurityLimits | None = None) -> SecurityReport:
    return read_secure_docx(source, limits=limits).report


def automatic_repair_blockers(snapshot: DocumentSnapshot) -> list[str]:
    blockers = snapshot.package_inventory.get("repair_blockers", [])
    if not isinstance(blockers, list):
        return ["INVALID_SECURITY_INVENTORY"]
    return sorted(str(blocker) for blocker in blockers)


def assert_automatic_repair_allowed(snapshot: DocumentSnapshot) -> None:
    blockers = automatic_repair_blockers(snapshot)
    if blockers:
        raise AlineaError(
            "DOCX_AUTO_REPAIR_BLOCKED",
            "The document contains features that block automatic repair",
            status_code=409,
            details={"repair_blockers": blockers},
        )


def _read_source(source: DocxSource, limits: SecurityLimits) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    elif isinstance(source, (str, Path)):
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise AlineaError(
                "DOCX_READ_ERROR", "The DOCX source cannot be read", details={"reason": str(exc)}
            ) from exc
        if size > limits.max_file_bytes:
            _raise_file_too_large(size, limits.max_file_bytes)
        try:
            with path.open("rb") as stream:
                data = stream.read(limits.max_file_bytes + 1)
        except OSError as exc:
            raise AlineaError("DOCX_READ_ERROR", "The DOCX source cannot be read") from exc
    elif hasattr(source, "read"):
        try:
            data = source.read(limits.max_file_bytes + 1)
        except (OSError, ValueError) as exc:
            raise AlineaError("DOCX_READ_ERROR", "The DOCX stream cannot be read") from exc
        if not isinstance(data, bytes):
            raise AlineaError("DOCX_READ_ERROR", "The DOCX stream must return bytes")
    else:
        raise TypeError("source must be bytes, a path, or a binary file-like object")

    if len(data) > limits.max_file_bytes:
        _raise_file_too_large(len(data), limits.max_file_bytes)
    return data


def _raise_file_too_large(actual: int, maximum: int) -> None:
    raise AlineaError(
        "DOCX_FILE_TOO_LARGE",
        "The DOCX exceeds the configured compressed-file size limit",
        status_code=413,
        details={"actual_bytes": actual, "max_bytes": maximum},
    )


def _check_file_header(data: bytes) -> None:
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise AlineaError(
            "DOCX_ENCRYPTED",
            "The compound-file input is encrypted or is not an OOXML DOCX package",
        )
    if not data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        raise AlineaError(
            "DOCX_INVALID_HEADER",
            "The input does not have a DOCX/ZIP file header",
            status_code=415,
        )


def _check_archive_metadata(infos: list[zipfile.ZipInfo], limits: SecurityLimits) -> None:
    if len(infos) > limits.max_zip_entries:
        raise AlineaError(
            "DOCX_TOO_MANY_ENTRIES",
            "The DOCX exceeds the configured ZIP entry-count limit",
            status_code=413,
            details={"actual_entries": len(infos), "max_entries": limits.max_zip_entries},
        )

    seen: set[str] = set()
    declared_total = 0
    for info in infos:
        name = _validate_entry_name(info.filename)
        normalized = name.casefold()
        if normalized in seen:
            raise AlineaError(
                "DOCX_DUPLICATE_PART",
                "The DOCX contains duplicate or case-ambiguous ZIP entries",
                details={"part_name": name},
            )
        seen.add(normalized)
        if info.flag_bits & 0x1:
            raise AlineaError(
                "DOCX_ENCRYPTED",
                "Password-protected ZIP entries are not supported",
                details={"part_name": name},
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise AlineaError("DOCX_INVALID_ZIP", "The DOCX has invalid ZIP size metadata")
        declared_total += info.file_size
        if (
            info.file_size > limits.max_uncompressed_bytes
            or declared_total > limits.max_uncompressed_bytes
        ):
            raise AlineaError(
                "DOCX_UNCOMPRESSED_TOO_LARGE",
                "The DOCX exceeds the configured uncompressed-size limit",
                status_code=413,
                details={
                    "part_name": name,
                    "declared_total_bytes": declared_total,
                    "max_bytes": limits.max_uncompressed_bytes,
                },
            )
        if not info.is_dir() and info.file_size:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > limits.max_compression_ratio:
                raise AlineaError(
                    "DOCX_COMPRESSION_RATIO",
                    "A DOCX entry exceeds the configured compression-ratio limit",
                    status_code=413,
                    details={
                        "part_name": name,
                        "compression_ratio": ratio,
                        "max_ratio": limits.max_compression_ratio,
                    },
                )


def _validate_entry_name(name: str) -> str:
    decoded = unquote(name)
    if "\x00" in name or "\x00" in decoded:
        raise AlineaError("DOCX_INVALID_PART_NAME", "A ZIP entry contains a NUL character")
    if name.startswith(("/", "\\")) or decoded.startswith(("/", "\\")):
        raise AlineaError(
            "DOCX_PATH_TRAVERSAL",
            "Absolute ZIP entry paths are not allowed",
            details={"part_name": name},
        )
    if _DRIVE_RE.match(name) or _DRIVE_RE.match(decoded):
        raise AlineaError(
            "DOCX_PATH_TRAVERSAL",
            "Drive-qualified ZIP entry paths are not allowed",
            details={"part_name": name},
        )
    if "\\" in decoded:
        raise AlineaError(
            "DOCX_INVALID_PART_NAME",
            "ZIP entry paths must use forward slashes",
            details={"part_name": name},
        )
    segments = decoded.split("/")
    if ".." in segments:
        raise AlineaError(
            "DOCX_PATH_TRAVERSAL",
            "ZIP entries may not traverse outside the package",
            details={"part_name": name},
        )
    if any(segment == "." for segment in segments):
        raise AlineaError(
            "DOCX_INVALID_PART_NAME",
            "ZIP entries may not contain relative path segments",
            details={"part_name": name},
        )
    return name


def _entry_name(info: zipfile.ZipInfo) -> str:
    return _validate_entry_name(info.filename)


def _check_encryption_and_macros(names: set[str]) -> None:
    lower_names = {name.casefold() for name in names}
    if {"encryptioninfo", "encryptedpackage"} & lower_names:
        raise AlineaError("DOCX_ENCRYPTED", "Encrypted OOXML packages are not supported")
    for name in lower_names:
        if name.endswith(("vbaproject.bin", "vbadata.xml")):
            raise AlineaError(
                "DOCX_MACRO_NOT_ALLOWED",
                "DOCX packages containing VBA macros are not supported",
                details={"part_name": name},
            )


def _read_entries(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo], limits: SecurityLimits
) -> tuple[list[tuple[str, int, str]], dict[str, etree._Element]]:
    parts: list[tuple[str, int, str]] = []
    xml_roots: dict[str, etree._Element] = {}
    total_actual = 0

    for info in infos:
        name = _entry_name(info)
        if info.is_dir():
            continue
        digest = hashlib.sha256()
        actual_size = 0
        xml_chunks: list[bytes] = []
        is_xml = name.casefold().endswith((".xml", ".rels"))
        with archive.open(info, mode="r") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                actual_size += len(chunk)
                total_actual += len(chunk)
                if total_actual > limits.max_uncompressed_bytes:
                    raise AlineaError(
                        "DOCX_UNCOMPRESSED_TOO_LARGE",
                        "Actual decompressed DOCX data exceeds the configured limit",
                        status_code=413,
                        details={"part_name": name, "max_bytes": limits.max_uncompressed_bytes},
                    )
                digest.update(chunk)
                if is_xml:
                    xml_chunks.append(chunk)
        if actual_size != info.file_size:
            raise AlineaError(
                "DOCX_INVALID_ZIP",
                "A ZIP entry's actual size differs from its declared size",
                details={"part_name": name},
            )
        parts.append((name, actual_size, digest.hexdigest()))
        if is_xml:
            xml_roots[name] = parse_xml_bytes(b"".join(xml_chunks), part_uri=f"/{name}")
    return parts, xml_roots


def _parse_content_types(
    xml_roots: dict[str, etree._Element], names: set[str]
) -> dict[str, str]:
    root = xml_roots.get("[Content_Types].xml")
    if (
        root is None
        or etree.QName(root).localname != "Types"
        or etree.QName(root).namespace
        != "http://schemas.openxmlformats.org/package/2006/content-types"
    ):
        raise AlineaError(
            "DOCX_INVALID_OPC", "The DOCX is missing a valid [Content_Types].xml part"
        )
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for child in root:
        local = etree.QName(child).localname
        if local == "Default":
            extension = child.get("Extension", "").casefold()
            content_type = child.get("ContentType", "")
            if extension and content_type:
                defaults[extension] = content_type
        elif local == "Override":
            part_name = child.get("PartName", "").lstrip("/")
            content_type = child.get("ContentType", "")
            if not part_name or not content_type:
                raise AlineaError(
                    "DOCX_INVALID_OPC", "A content-type override is incomplete"
                )
            if part_name not in names:
                raise AlineaError(
                    "DOCX_INVALID_OPC",
                    "A content-type override references a missing part",
                    details={"part_name": part_name},
                )
            overrides[part_name] = content_type

    result = {
        name: overrides.get(name) or defaults.get(name.rsplit(".", 1)[-1].casefold(), "")
        for name in names
    }
    for name, content_type in result.items():
        folded = content_type.casefold()
        if "macroenabled" in folded or "vba" in folded:
            raise AlineaError(
                "DOCX_MACRO_NOT_ALLOWED",
                "Macro-enabled WordprocessingML content is not supported",
                details={"part_name": name, "content_type": content_type},
            )
    return result


def _validate_relationships(
    xml_roots: dict[str, etree._Element], names: set[str]
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for rels_name, root in xml_roots.items():
        if not rels_name.casefold().endswith(".rels"):
            continue
        if etree.QName(root).localname != "Relationships":
            raise AlineaError(
                "DOCX_INVALID_OPC",
                "A relationship part has an invalid root element",
                details={"part_uri": f"/{rels_name}"},
            )
        namespace = etree.QName(root).namespace
        if namespace not in _RELATIONSHIP_NAMESPACES:
            raise AlineaError(
                "DOCX_INVALID_OPC",
                "A relationship part uses an unsupported namespace",
                details={"part_uri": f"/{rels_name}"},
            )
        source_name = _relationship_source(rels_name)
        for relationship in root:
            if etree.QName(relationship).localname != "Relationship":
                continue
            rel_id = relationship.get("Id", "")
            rel_type = relationship.get("Type", "")
            target = relationship.get("Target", "")
            target_mode = relationship.get("TargetMode", "Internal")
            if not rel_id or not rel_type or not target:
                raise AlineaError(
                    "DOCX_INVALID_RELATIONSHIP",
                    "A relationship is missing Id, Type, or Target",
                    details={"part_uri": f"/{rels_name}"},
                )
            record = {
                "part_uri": f"/{rels_name}",
                "source_part": f"/{source_name}" if source_name else "/",
                "id": rel_id,
                "type": rel_type,
                "target": target,
                "target_mode": target_mode,
            }
            if target_mode.casefold() == "external":
                records.append(record)
                continue
            if target_mode.casefold() != "internal":
                raise AlineaError(
                    "DOCX_INVALID_RELATIONSHIP",
                    "A relationship has an invalid TargetMode",
                    details={"part_uri": f"/{rels_name}", "target_mode": target_mode},
                )
            target_name = _resolve_relationship_target(source_name, target, rels_name)
            if target_name not in names:
                raise AlineaError(
                    "DOCX_MISSING_RELATIONSHIP_TARGET",
                    "An internal relationship target is missing from the package",
                    details={"part_uri": f"/{rels_name}", "target": target},
                )
            record["resolved_target"] = target_name
            records.append(record)
    return records


def _relationship_source(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    directory, filename = posixpath.split(rels_name)
    parent, rels_directory = posixpath.split(directory)
    if rels_directory != "_rels" or not filename.endswith(".rels"):
        raise AlineaError(
            "DOCX_INVALID_OPC",
            "A relationships part does not follow the OPC _rels layout",
            details={"part_uri": f"/{rels_name}"},
        )
    source = posixpath.join(parent, filename[: -len(".rels")])
    return source


def _resolve_relationship_target(source_name: str, target: str, rels_name: str) -> str:
    if "\\" in target or "\x00" in target:
        raise AlineaError(
            "DOCX_PATH_TRAVERSAL",
            "Relationship targets may not contain backslashes or NUL characters",
            details={"part_uri": f"/{rels_name}", "target": target},
        )
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        raise AlineaError(
            "DOCX_UNDECLARED_EXTERNAL_RELATIONSHIP",
            "An external relationship target must declare TargetMode=External",
            details={"part_uri": f"/{rels_name}", "target": target},
        )
    target_path = unquote(parsed.path)
    if target_path.startswith("/"):
        resolved = posixpath.normpath(target_path.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_name), target_path))
    if resolved in {"", ".", ".."} or resolved.startswith("../") or _DRIVE_RE.match(resolved):
        raise AlineaError(
            "DOCX_PATH_TRAVERSAL",
            "A relationship target resolves outside the OPC package",
            details={"part_uri": f"/{rels_name}", "target": target},
        )
    return resolved


def _find_main_part(
    relationships: list[dict[str, str]], content_types: dict[str, str]
) -> str:
    office_rels = [
        item
        for item in relationships
        if item["source_part"] == "/"
        and item["type"].rsplit("/", 1)[-1] == _OFFICE_DOCUMENT_RELATIONSHIP
        and item["target_mode"].casefold() == "internal"
    ]
    if len(office_rels) != 1:
        raise AlineaError(
            "DOCX_INVALID_OPC",
            "The package must have exactly one internal root officeDocument relationship",
        )
    main_name = office_rels[0].get("resolved_target", "")
    if content_types.get(main_name) != _DOCUMENT_CONTENT_TYPE:
        raise AlineaError(
            "DOCX_INVALID_OPC",
            "The officeDocument relationship does not target a DOCX main document part",
            details={"part_name": main_name, "content_type": content_types.get(main_name, "")},
        )
    return f"/{main_name}"


def _scan_high_risk_objects(
    parts: list[tuple[str, int, str]],
    xml_roots: dict[str, etree._Element],
    relationships: list[dict[str, str]],
) -> _ValidationState:
    state = _ValidationState()
    for name, _, _ in parts:
        folded = name.casefold()
        part_uri = f"/{name}"
        if "/embeddings/" in f"/{folded}":
            state.add("ole_object", part_uri, blocker="OLE_OBJECT")
        if "/activex/" in f"/{folded}":
            state.add("active_x", part_uri, blocker="ACTIVE_X")
    for item in relationships:
        if item["target_mode"].casefold() == "external":
            state.features.add("external_relationship")
            state.high_risk_objects.append(
                {
                    "feature": "external_relationship",
                    "part_uri": item["part_uri"],
                    "relationship_id": item["id"],
                }
            )

    feature_elements = {
        "ins": ("track_changes", "TRACK_CHANGES"),
        "del": ("track_changes", "TRACK_CHANGES"),
        "moveFrom": ("track_changes", "TRACK_CHANGES"),
        "moveTo": ("track_changes", "TRACK_CHANGES"),
        "trackRevisions": ("track_changes", "TRACK_CHANGES"),
        "object": ("ole_object", "OLE_OBJECT"),
        "OLEObject": ("ole_object", "OLE_OBJECT"),
        "control": ("active_x", "ACTIVE_X"),
        "documentProtection": ("document_protection", "DOCUMENT_PROTECTION"),
        "writeProtection": ("document_protection", "DOCUMENT_PROTECTION"),
        "altChunk": ("alt_chunk", "ALT_CHUNK"),
        "oMath": ("equation", None),
        "oMathPara": ("equation", None),
        "fldSimple": ("field", None),
        "fldChar": ("field", None),
        "instrText": ("field", None),
        "txbxContent": ("text_box", None),
        "textbox": ("text_box", None),
    }
    for name, root in xml_roots.items():
        part_uri = f"/{name}"
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            local = etree.QName(element).localname
            match = feature_elements.get(local)
            if match:
                feature, blocker = match
                state.add(feature, part_uri, blocker=blocker)
    return state

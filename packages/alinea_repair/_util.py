from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from alinea_contracts.errors import AlineaError

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_sha256(value: str, *, field: str = "sha256") -> str:
    normalized = value.removeprefix("sha256:").lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise AlineaError(
            "INVALID_SHA256",
            f"{field} must be a SHA-256 hex digest",
            status_code=422,
            details={"field": field},
        )
    return normalized


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def normalized_name(value: str) -> str:
    return "_".join(value.strip().casefold().replace("-", "_").split())


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

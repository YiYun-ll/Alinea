from __future__ import annotations

import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

_CATEGORIES = {
    "originals",
    "guidelines",
    "snapshots",
    "previews",
    "inspections",
    "repairs",
    "revisions",
    "reports",
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def _uuid(value: str | UUID) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Storage keys require UUID project and object identifiers") from exc


def _name(value: str, *, profile: bool = False) -> str:
    limit = 128 if profile else 255
    if (
        not isinstance(value, str)
        or len(value) > limit
        or not _SAFE_NAME.fullmatch(value)
        or value.endswith(".")
    ):
        raise ValueError("Unsafe storage path component")
    return value


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        path = Path(root).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        self.root = path.resolve(strict=False)
        if any(part.lower() in {"public", "static"} for part in self.root.parts):
            raise ValueError("Private object storage cannot be inside a static directory")
        web_root = (Path.cwd() / "apps" / "web").resolve(strict=False)
        if self.root.is_relative_to(web_root):
            raise ValueError("Private object storage cannot be inside the web application")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def build_key(
        project_id: str | UUID,
        category: str,
        object_id: str | UUID,
        filename: str,
        *,
        profile_id: str | None = None,
    ) -> str:
        if category not in _CATEGORIES:
            raise ValueError("Unsupported storage category")
        parts = [
            "projects",
            _uuid(project_id),
            category,
            _uuid(object_id),
        ]
        if category == "previews":
            if profile_id is None:
                raise ValueError("Preview keys require a profile identifier")
            parts.append(_name(profile_id, profile=True))
        elif profile_id is not None:
            raise ValueError("Only preview keys accept a profile identifier")
        parts.append(_name(filename))
        return "/".join(parts)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or "\\" in key or "\x00" in key or key.startswith("/"):
            raise ValueError("Invalid storage key")
        parts = key.split("/")
        if len(parts) not in (5, 6):
            raise ValueError("Invalid storage key")
        profile_id = parts[4] if len(parts) == 6 else None
        filename = parts[-1]
        canonical = self.build_key(parts[1], parts[2], parts[3], filename, profile_id=profile_id)
        if key != canonical:
            raise ValueError("Invalid storage key")
        candidate = (self.root / Path(*parts)).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Storage key escapes the private storage root") from exc
        return candidate

    def path_for(self, key: str) -> Path:
        return self._path(key)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def read(self, key: str) -> bytes:
        with self.open(key) as source:
            return source.read()

    def write(self, key: str, data: bytes | bytearray | memoryview) -> str:
        self._atomic_write(key, BytesIO(bytes(data)))
        return key

    def copy(self, source_key: str, destination_key: str) -> str:
        with self.open(source_key) as source:
            self._atomic_write(destination_key, source)
        return destination_key

    def copy_from(self, source_path: str | Path, destination_key: str) -> str:
        with Path(source_path).open("rb") as source:
            self._atomic_write(destination_key, source)
        return destination_key

    def _atomic_write(self, key: str, source: BinaryIO) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = self._path(key)
        fd, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def delete_project(self, project_id: str | UUID) -> None:
        project_path = (self.root / "projects" / _uuid(project_id)).resolve(strict=False)
        try:
            project_path.relative_to(self.root / "projects")
        except ValueError as exc:
            raise ValueError("Invalid project storage path") from exc
        if project_path.exists():
            shutil.rmtree(project_path)

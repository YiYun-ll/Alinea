from __future__ import annotations

from uuid import uuid4

import pytest
from app.storage.local import LocalStorage


def test_atomic_immutable_write_read_open_and_copy(tmp_path):
    storage = LocalStorage(tmp_path / "objects")
    project_id = str(uuid4())
    revision_id = str(uuid4())
    original = storage.build_key(project_id, "originals", revision_id, "source.docx")
    candidate = storage.build_key(project_id, "revisions", revision_id, "document.docx")

    assert storage.write(original, b"original bytes") == original
    assert storage.read(original) == b"original bytes"
    with storage.open(original) as stream:
        assert stream.read() == b"original bytes"
    with pytest.raises(FileExistsError):
        storage.write(original, b"changed")
    assert storage.read(original) == b"original bytes"

    storage.copy(original, candidate)
    assert storage.read(candidate) == b"original bytes"
    with pytest.raises(FileExistsError):
        storage.copy(original, candidate)
    assert storage.read(candidate) == b"original bytes"
    assert not list(storage.root.rglob("*.tmp"))


def test_copy_from_external_file_and_preview_key(tmp_path):
    storage = LocalStorage(tmp_path / "objects")
    source = tmp_path / "upload.tmp"
    source.write_bytes(b"uploaded")
    project_id = str(uuid4())
    object_id = str(uuid4())
    destination = storage.build_key(project_id, "guidelines", object_id, "source.pdf")
    preview = storage.build_key(
        project_id,
        "previews",
        object_id,
        "preview.pdf",
        profile_id="libreoffice-default",
    )
    storage.copy_from(source, destination)
    storage.write(preview, b"pdf")
    assert storage.read(destination) == b"uploaded"
    assert storage.read(preview) == b"pdf"


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "/absolute/path",
        "projects/not-a-uuid/originals/also-not-a-uuid/source.docx",
        "projects/{project}/unknown/{object}/source.docx",
        "projects/{project}/originals/{object}/../../escape",
        "projects/{project}/originals/{object}/..\\escape",
        "projects/{project}/originals/{object}/nested/source.docx",
        "projects/{project}/previews/{object}/preview.pdf",
    ],
)
def test_rejects_non_derived_and_traversal_keys(tmp_path, key):
    storage = LocalStorage(tmp_path / "objects")
    key = key.format(project=uuid4(), object=uuid4())
    with pytest.raises(ValueError):
        storage.path_for(key)
    assert not (tmp_path / "escape").exists()


def test_delete_project_does_not_remove_other_projects(tmp_path):
    storage = LocalStorage(tmp_path / "objects")
    first = str(uuid4())
    second = str(uuid4())
    first_key = storage.build_key(first, "originals", uuid4(), "source.docx")
    second_key = storage.build_key(second, "originals", uuid4(), "source.docx")
    storage.write(first_key, b"first")
    storage.write(second_key, b"second")

    storage.delete_project(first)

    with pytest.raises(FileNotFoundError):
        storage.read(first_key)
    assert storage.read(second_key) == b"second"
    storage.delete_project(first)


def test_rejects_static_storage_root(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "public" / "objects")
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "static")

"""Real encoded codec/storage tests; no model accuracy or live-feed claims."""
import hashlib
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

from sentinal.storage.video_library import VideoEntry, VideoImportCancelled, VideoImportError, VideoLibrary


def test_import_copies_decodable_video_and_preserves_original(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library with spaces")
    before = synthetic_video.read_bytes()
    progress = []
    entry = library.import_file(synthetic_video, progress=lambda done, total: progress.append((done, total)))
    assert isinstance(entry, VideoEntry)
    assert entry.path.parent == library.directory
    assert entry.path.read_bytes() == before == synthetic_video.read_bytes()
    assert entry.sha256 == hashlib.sha256(before).hexdigest()
    assert entry.display_name == synthetic_video.name
    assert (entry.width, entry.height, entry.frame_count) == (64, 48, 5)
    assert entry.fps == pytest.approx(10, abs=0.5)
    assert entry.duration_s == pytest.approx(0.5, abs=0.05)
    assert progress[0] == (0, len(before)) and progress[-1] == (len(before), len(before))
    assert library.list_entries() == [entry]
    manifest = json.loads(library.index_path.read_text())
    assert str(synthetic_video.parent) not in library.index_path.read_text()
    assert manifest["entries"][0]["filename"] == entry.path.name
    assert entry.path.stat().st_mode & 0o777 == 0o600
    assert library.index_path.stat().st_mode & 0o777 == 0o600
    assert not list(library.incoming.iterdir())


def test_same_bytes_different_name_deduplicate_by_full_hash(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    first = library.import_file(synthetic_video)
    different = tmp_path / "a completely different name.mov"
    shutil.copy2(synthetic_video, different)
    second = library.import_file(different)
    assert second == first
    assert len(library.list_entries()) == 1
    assert not list(library.incoming.iterdir())
    assert len([p for p in library.directory.iterdir() if p.suffix == ".avi"]) == 1


def test_file_already_in_managed_directory_is_registered_without_copy(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    local = library.directory / "my own clip.avi"
    shutil.copy2(synthetic_video, local)
    entry = library.import_file(local)
    assert entry.path == local
    assert entry.path.exists()
    assert [p for p in library.directory.glob("*.avi")] == [local]
    assert not list(library.incoming.iterdir())


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "corrupt"])
def test_bad_inputs_never_publish_partial_videos(tmp_path, kind):
    library = VideoLibrary(tmp_path / "library")
    candidate = tmp_path / "input.mp4"
    if kind == "directory":
        candidate.mkdir()
    elif kind == "empty":
        candidate.touch()
    elif kind == "corrupt":
        candidate.write_bytes(b"not video data")
    with pytest.raises(VideoImportError):
        library.import_file(candidate)
    assert library.list_entries() == []
    assert not list(library.incoming.iterdir())
    assert not list(library.directory.glob("*.mp4"))


def test_cancel_during_streaming_copy_cleans_up_and_preserves_input(tmp_path, synthetic_video, monkeypatch):
    library = VideoLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "CHUNK_BYTES", 32)
    cancel = threading.Event()
    before = synthetic_video.read_bytes()
    def progress(done, total):
        if done > 0:
            cancel.set()
    with pytest.raises(VideoImportCancelled):
        library.import_file(synthetic_video, progress=progress, cancel_event=cancel)
    assert synthetic_video.read_bytes() == before
    assert not list(library.incoming.iterdir())
    assert library.list_entries() == []


def test_no_space_is_clear_error_and_creates_no_partial(tmp_path, synthetic_video, monkeypatch):
    from sentinal.storage import video_library
    library = VideoLibrary(tmp_path / "library")
    monkeypatch.setattr(video_library.shutil, "disk_usage", lambda *_: SimpleNamespace(free=0))
    with pytest.raises(VideoImportError, match="free space"):
        library.import_file(synthetic_video)
    assert not list(library.incoming.iterdir())


def test_index_write_failure_removes_only_new_import_not_original(tmp_path, synthetic_video, monkeypatch):
    library = VideoLibrary(tmp_path / "library")
    def fail(_):
        raise OSError("disk error")
    monkeypatch.setattr(library, "_write_entries", fail)
    with pytest.raises(VideoImportError):
        library.import_file(synthetic_video)
    assert synthetic_video.is_file()
    assert not list(library.directory.glob("*.avi"))
    assert not list(library.incoming.iterdir())


def test_tampered_index_cannot_refer_to_external_files(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    entry = library.import_file(synthetic_video)
    manifest = json.loads(library.index_path.read_text())
    manifest["entries"][0]["filename"] = "../" + synthetic_video.name
    library.index_path.write_text(json.dumps(manifest))
    assert library.list_entries() == []
    # Metadata failure did not delete either original or managed bytes.
    assert synthetic_video.is_file() and entry.path.is_file()


def test_index_symlink_is_not_followed_and_replaced_on_new_import(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    external = tmp_path / "outside.json"
    external.write_text('{"private": "untouched"}')
    library.index_path.symlink_to(external)
    assert library.list_entries() == []
    library.import_file(synthetic_video)
    assert external.read_text() == '{"private": "untouched"}'
    assert not library.index_path.is_symlink()


def test_missing_or_corrupt_index_can_be_rebuilt_from_real_managed_clips(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    first = library.import_file(synthetic_video)
    library.index_path.write_text("broken json")
    assert library.list_entries() == []
    recovered = library.reindex()
    assert len(recovered) == 1
    assert recovered[0].path == first.path
    assert recovered[0].sha256 == first.sha256
    assert library.list_entries() == recovered


def test_long_unicode_filename_stays_within_filesystem_byte_limit(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    source = tmp_path / (("測試" * 40) + ".avi")
    shutil.copy2(synthetic_video, source)
    entry = library.import_file(source)
    assert len(entry.path.name.encode("utf-8")) < 255
    assert entry.path.is_file()


def test_modified_source_is_detected_before_any_publication(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / "library")
    changed = False
    def progress(done, total):
        nonlocal changed
        if done and not changed:
            with synthetic_video.open("ab") as output:
                output.write(b"changed")
            changed = True
    with pytest.raises(VideoImportError, match="changed during import"):
        library.import_file(synthetic_video, progress=progress)
    assert not list(library.incoming.iterdir())
    assert library.list_entries() == []


@pytest.mark.parametrize('reserved', ['library.json', '.library.lock'])
def test_managed_reserved_filename_cannot_destroy_video(tmp_path, synthetic_video, reserved):
    library = VideoLibrary(tmp_path / 'library')
    source = library.directory / reserved
    shutil.copy2(synthetic_video, source)
    before = source.read_bytes()
    with pytest.raises(VideoImportError, match='reserved'):
        library.import_file(source)
    assert source.read_bytes() == before


def test_nested_unfinished_import_is_rejected(tmp_path, synthetic_video):
    library = VideoLibrary(tmp_path / 'library')
    folder = library.incoming / 'nested'
    folder.mkdir()
    source = folder / 'unfinished.avi'
    shutil.copy2(synthetic_video, source)
    with pytest.raises(VideoImportError, match='unfinished'):
        library.import_file(source)
    assert source.read_bytes() == synthetic_video.read_bytes()

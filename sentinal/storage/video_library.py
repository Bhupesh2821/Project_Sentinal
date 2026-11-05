"""Local, bounded-memory video imports. Original user files are never changed."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
from uuid import uuid4

import cv2

from sentinal.config import ROOT


class VideoImportError(RuntimeError):
    """A readable import/storage/decoder failure."""


class VideoImportCancelled(VideoImportError):
    """A user cancelled the import before it was published."""


@dataclass(frozen=True)
class VideoEntry:
    path: Path
    display_name: str
    sha256: str
    size_bytes: int
    fps: float
    frame_count: int
    width: int
    height: int
    duration_s: float | None


class VideoLibrary:
    CHUNK_BYTES = 4 * 1024 * 1024
    RESERVE_BYTES = 256 * 1024 * 1024
    RESERVED_NAMES = frozenset({"library.json", ".library.lock", ".incoming"})
    VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".m4v", ".mkv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".wmv"})

    def __init__(self, directory=None):
        self.directory = Path(directory or ROOT / "data/videos").expanduser().resolve()
        self.incoming = self.directory / ".incoming"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.incoming.is_symlink():
                raise VideoImportError("The video import staging folder must be a local directory.")
            self.incoming.mkdir(mode=0o700, exist_ok=True)
            self.incoming.chmod(0o700)
        except OSError as exc:
            raise VideoImportError("The local video library is unavailable. Check project-folder access and free space.") from exc
        self.index_path = self.directory / "library.json"
        self._lock = threading.RLock()

    @contextmanager
    def _index_lock(self):
        with self._lock:
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.directory / ".library.lock", flags, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _entry_from_row(self, row):
        if not isinstance(row, dict):
            return None
        try:
            filename = row["filename"]
            if not isinstance(filename, str) or filename != Path(filename).name or filename in {"", ".", ".."}:
                return None
            if filename in self.RESERVED_NAMES:
                return None
            path = self.directory / filename
            # An index must not turn a library entry into an outside-file link.
            if path.is_symlink() or not path.is_file() or path.resolve().parent != self.directory:
                return None
            digest = row["sha256"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                return None
            size, count, width, height = (row[k] for k in ("size_bytes", "frame_count", "width", "height"))
            if any(type(v) is not int for v in (size, count, width, height)) or min(size, width, height) <= 0 or count < 0:
                return None
            if path.stat().st_size != size:
                return None
            fps, duration = row["fps"], row.get("duration_s")
            if type(fps) not in (int, float) or not math.isfinite(fps) or fps < 0:
                return None
            if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0):
                return None
            display_name = row["display_name"]
            if not isinstance(display_name, str) or not display_name:
                return None
            return VideoEntry(path, display_name, digest, size, float(fps), count, width, height, duration)
        except (KeyError, TypeError, ValueError, OSError):
            return None

    def _read_entries(self):
        if not self.index_path.exists() or self.index_path.is_symlink():
            return []
        try:
            data = json.loads(self.index_path.read_text())
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), list):
                return []
            return [entry for row in data["entries"] if (entry := self._entry_from_row(row)) is not None]
        except (OSError, ValueError, TypeError):
            # Existing videos remain untouched. reindex() can reconstruct metadata.
            return []

    def list_entries(self):
        """Return newest imports first, omitting missing or unsafe index entries."""
        try:
            # Publication uses replace(), so readers see a complete old or new
            # index and need not wait for a large import's deduplication hash.
            return self._read_entries()
        except OSError as exc:
            raise VideoImportError("The local video library could not be read. Check folder permissions.") from exc

    def _write_entries(self, entries):
        rows = [{"filename": e.path.name, "display_name": e.display_name, "sha256": e.sha256,
                 "size_bytes": e.size_bytes, "fps": e.fps, "frame_count": e.frame_count,
                 "width": e.width, "height": e.height, "duration_s": e.duration_s} for e in entries]
        temporary = self.incoming / f"index-{uuid4().hex}.part"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"version": 1, "updated_utc": datetime.now(timezone.utc).isoformat(), "entries": rows}, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.index_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _cancelled(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise VideoImportCancelled("Video import cancelled.")

    def _hash(self, path, progress=None, cancel_event=None, copy_to=None):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            initial = os.fstat(source.fileno())
            total = initial.st_size
            if total <= 0:
                raise VideoImportError("The selected file is empty.")
            processed = 0
            if progress:
                progress(0, total)
            while True:
                self._cancelled(cancel_event)
                chunk = source.read(self.CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                if copy_to is not None:
                    copy_to.write(chunk)
                processed += len(chunk)
                if progress:
                    progress(processed, total)
            final = os.fstat(source.fileno())
            if processed != total or (final.st_size, final.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
                raise VideoImportError("The selected video changed during import. Wait for its copy or recording to finish, then try again.")
            self._cancelled(cancel_event)
            return digest.hexdigest(), processed

    @staticmethod
    def _probe(path):
        capture = None
        try:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise VideoImportError("This file could not be decoded as a video. It may be damaged or use an unsupported codec.")
            ok, frame = capture.read()
            if not ok or frame is None or not frame.size or frame.ndim != 3:
                raise VideoImportError("No video frame could be decoded. The video may be empty, incomplete or use an unsupported codec.")
            height, width = frame.shape[:2]
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = fps if math.isfinite(fps) and fps > 0 else 0.0
            count = int(count) if math.isfinite(count) and count > 0 else 0
            return {"fps": fps, "frame_count": count, "width": width, "height": height,
                    "duration_s": count / fps if count and fps else None}
        except VideoImportError:
            raise
        except Exception as exc:
            raise VideoImportError("The video decoder could not read this file. Try a complete MP4, MOV, MKV or AVI video.") from exc
        finally:
            if capture is not None:
                capture.release()

    @staticmethod
    def _display_name(path):
        cleaned = "".join(c for c in path.name if c.isprintable()).strip()
        return cleaned[:180] or "Imported video"

    def _destination(self, source, digest):
        stem = re.sub(r"[^\w .-]", "_", source.stem, flags=re.UNICODE).strip(" .")
        stem = stem.encode("utf-8")[:140].decode("utf-8", errors="ignore") or "video"
        suffix = source.suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".video"
        candidate = self.directory / f"{digest[:20]}-{stem}{suffix}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        return self.directory / f"{digest[:20]}-{uuid4().hex[:10]}-{stem}{suffix}"

    def import_file(self, path, progress=None, cancel_event=None):
        """Import one arbitrary decodable local video without loading it into RAM."""
        temporary = None
        published = None
        try:
            source = Path(path).expanduser().resolve()
            if not source.is_file():
                raise VideoImportError("Choose an existing local video file.")
            if source.is_relative_to(self.incoming):
                raise VideoImportError("An unfinished import cannot be opened as a video.")
            self._cancelled(cancel_event)
            managed = source.parent == self.directory
            if managed and source.name in self.RESERVED_NAMES:
                raise VideoImportError("This filename is reserved for the video library. Rename the video before importing it.")
            if managed:
                digest, size = self._hash(source, progress, cancel_event)
                candidate = source
            else:
                size = source.stat().st_size
                if size <= 0:
                    raise VideoImportError("The selected file is empty.")
                if shutil.disk_usage(self.directory).free < size + self.RESERVE_BYTES:
                    raise VideoImportError("There is not enough free space to import this video into the project folder.")
                temporary = self.incoming / f"video-{uuid4().hex}.part"
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    digest, size = self._hash(source, progress, cancel_event, output)
                    output.flush()
                    os.fsync(output.fileno())
                candidate = temporary
            metadata = self._probe(candidate)
            self._cancelled(cancel_event)
            with self._index_lock():
                entries = self._read_entries()
                for entry in entries:
                    if entry.sha256 == digest and entry.size_bytes == size:
                        # Do not trust an edited index alone for deduplication.
                        actual, _ = self._hash(entry.path, cancel_event=cancel_event)
                        if actual == digest:
                            self._write_entries([entry] + [e for e in entries if e.path != entry.path])
                            return entry
                if managed:
                    destination = source
                else:
                    destination = self._destination(source, digest)
                    self._cancelled(cancel_event)
                    temporary.replace(destination)
                    temporary = None
                    published = destination
                entry = VideoEntry(destination, self._display_name(source), digest, size, **metadata)
                try:
                    self._write_entries([entry] + [e for e in entries if e.path != destination])
                except Exception:
                    if published is not None:
                        published.unlink(missing_ok=True)
                    raise
                return entry
        except (VideoImportError, VideoImportCancelled):
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise VideoImportError("The video could not be imported. Check file access and free space in the project folder.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def reindex(self, progress=None, cancel_event=None):
        """Explicitly rebuild the index from decodable files already in this library."""
        try:
            with self._index_lock():
                # Serialize against publication so a concurrent import cannot
                # disappear from an index rebuilt from an earlier directory view.
                entries = []
                files = sorted((p for p in self.directory.iterdir() if p.is_file() and not p.is_symlink()
                                and p.suffix.lower() in self.VIDEO_SUFFIXES), key=lambda p: p.stat().st_mtime_ns, reverse=True)
                for index, path in enumerate(files):
                    self._cancelled(cancel_event)
                    try:
                        metadata = self._probe(path)
                        digest, size = self._hash(path, cancel_event=cancel_event)
                        entries.append(VideoEntry(path, self._display_name(path), digest, size, **metadata))
                    except VideoImportCancelled:
                        raise
                    except (VideoImportError, OSError):
                        continue
                    if progress:
                        progress(index + 1, len(files))
                self._cancelled(cancel_event)
                self._write_entries(entries)
        except OSError as exc:
            raise VideoImportError("The video library index could not be saved. Check folder permissions.") from exc
        return entries

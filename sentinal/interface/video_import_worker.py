"""Copy/hash/decode validation outside the GUI thread."""
import logging
import threading

from PySide6.QtCore import QThread, Signal

from sentinal.storage.video_library import VideoImportCancelled, VideoImportError, VideoLibrary

log = logging.getLogger(__name__)


class VideoImportWorker(QThread):
    progress = Signal(object, object)  # Python integers support multi-GB files.
    imported = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, path, parent=None, library=None):
        super().__init__(parent)
        self.path = path
        self.library = library
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            library = self.library if self.library is not None else VideoLibrary()
            entry = library.import_file(self.path, progress=self.progress.emit, cancel_event=self._cancel)
            self.imported.emit(entry)
        except VideoImportCancelled:
            self.cancelled.emit()
        except VideoImportError as exc:
            self.failed.emit(str(exc))
        except Exception:
            log.exception("Video import failed")
            self.failed.emit("The video import stopped unexpectedly. Check the project folder and diagnostic log, then try again.")

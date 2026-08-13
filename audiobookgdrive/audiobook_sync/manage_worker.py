# -*- coding: utf-8 -*-
"""
audiobook_sync/manage_worker.py
=================================

``QThread`` wrappers quanh ``manage_ops.py`` -- hỗ trợ library_name.
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

from PyQt5.Qt import QThread, pyqtSignal

from . import manage_ops


class ListAudiobooksThread(QThread):
    finished_ok = pyqtSignal(str, list, str)  # root_id, list[ManagedAudiobook], source
    failed = pyqtSignal(str)

    def __init__(self, access_token, parent=None, library_name=None):
        QThread.__init__(self, parent)
        self.access_token = access_token
        self.library_name = library_name

    def run(self):
        try:
            root_id, books, source = manage_ops.list_audiobooks(
                self.access_token, library_name=self.library_name)
            self.finished_ok.emit(root_id, books, source or '')
        except Exception as e:
            self.failed.emit(str(e))


class CoverLoaderThread(QThread):
    cover_loaded = pyqtSignal(str, str)  # key, local_cache_path
    finished_ok = pyqtSignal()

    def __init__(self, access_token, books, parent=None):
        QThread.__init__(self, parent)
        self.access_token = access_token
        self.books = list(books)

    def run(self):
        # 1) Hiện ngay mọi cover đã cache (không mạng)
        need_download = []
        for book in self.books:
            if self.isInterruptionRequested():
                return
            if not book.cover_file_id:
                continue
            hit = manage_ops.peek_cached_cover_path(book.cover_file_id, key=book.key)
            if hit:
                self.cover_loaded.emit(book.key, hit)
            else:
                need_download.append(book)
        # 2) Chỉ tải những bìa chưa có trong cache
        for book in need_download:
            if self.isInterruptionRequested():
                return
            try:
                path = manage_ops.cached_cover_path(
                    self.access_token, book.key, book.cover_file_id)
            except Exception:
                path = None
            if path:
                self.cover_loaded.emit(book.key, path)
        self.finished_ok.emit()


class EditMetadataThread(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, access_token, key, title=None, creators_text=None,
                 publisher=None, language=None, description=None, parent=None,
                 library_name=None):
        QThread.__init__(self, parent)
        self.access_token = access_token
        self.key = key
        self.title = title
        self.creators_text = creators_text
        self.publisher = publisher
        self.language = language
        self.description = description
        self.library_name = library_name

    def run(self):
        try:
            manage_ops.edit_metadata(
                self.access_token, self.key,
                title=self.title, creators_text=self.creators_text,
                publisher=self.publisher, language=self.language,
                description=self.description,
                log_fn=lambda msg: self.log.emit(msg),
                library_name=self.library_name)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class ResyncBookThread(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, access_token, key, parent=None, library_name=None):
        QThread.__init__(self, parent)
        self.access_token = access_token
        self.key = key
        self.library_name = library_name

    def run(self):
        try:
            manage_ops.resync_book_from_drive(
                self.access_token, self.key,
                log_fn=lambda msg: self.log.emit(msg),
                library_name=self.library_name)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class DeleteAudiobooksThread(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, access_token, keys, purge_files, parent=None, library_name=None):
        QThread.__init__(self, parent)
        self.access_token = access_token
        self.keys = list(keys)
        self.purge_files = purge_files
        self.library_name = library_name

    def run(self):
        try:
            manage_ops.delete_audiobooks(
                self.access_token, self.keys, self.purge_files,
                log_fn=lambda msg: self.log.emit(msg),
                library_name=self.library_name)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))

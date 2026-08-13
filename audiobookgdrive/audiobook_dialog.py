# -*- coding: utf-8 -*-
"""
audiobook_dialog.py
=====================

Dialog tiến trình modal cho "Đồng bộ Audiobooks lên Google Drive".
Luôn chạy trong cửa sổ (không chạy dưới nền) để theo dõi log/tiến trình.
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

from PyQt5.Qt import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPlainTextEdit, QDialogButtonBox,
)

from audiobookgdrive.audiobook_sync.worker import AudiobookSyncThread


class AudiobookSyncProgressDialog(QDialog):
    def __init__(self, gui, access_token, root_folders, logger=None, library_name=None):
        QDialog.__init__(self, gui)
        lib = library_name or 'Audiobooks'
        self.setWindowTitle('Đồng bộ lên Google Drive — %s' % lib)
        self.resize(560, 360)

        outer = QVBoxLayout()
        self.setLayout(outer)

        self.status_label = QLabel('Đang chuẩn bị...')
        outer.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        outer.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        outer.addWidget(self.log_view)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.close)
        self.buttons.accepted.connect(self.close)
        self.buttons.button(QDialogButtonBox.Close).setEnabled(False)
        outer.addWidget(self.buttons)

        self.thread = AudiobookSyncThread(
            access_token, root_folders, parent=self, logger=logger, library_name=library_name)
        self.thread.progress.connect(self._on_progress)
        self.thread.log.connect(self._on_log)
        self.thread.finished_ok.connect(self._on_finished)
        self.thread.failed.connect(self._on_failed)

    def _on_progress(self, done, total):
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(done)
        self.status_label.setText('Đang đồng bộ... (%d/%d cuốn)' % (done, total))

    def _on_log(self, message):
        self.log_view.appendPlainText(message)

    def _on_finished(self, stats):
        self.status_label.setText(
            'Hoàn tất. Đã đồng bộ: %d, bỏ qua (không đổi): %d, lỗi: %d.' % (
                stats.get('books_synced', 0), stats.get('books_skipped', 0), stats.get('books_failed', 0)))
        self.buttons.button(QDialogButtonBox.Close).setEnabled(True)

    def _on_failed(self, message):
        self.status_label.setText('Thất bại: %s' % message)
        self.log_view.appendPlainText('LỖI: %s' % message)
        self.buttons.button(QDialogButtonBox.Close).setEnabled(True)

    def reject(self):
        # Không cho đóng khi đang chạy (Esc / nút X)
        if self.thread.isRunning():
            return
        QDialog.reject(self)

    def exec_(self, run_in_background=False):
        # run_in_background bị bỏ qua -- luôn hiện cửa sổ để theo dõi
        self.thread.start()
        return QDialog.exec_(self)

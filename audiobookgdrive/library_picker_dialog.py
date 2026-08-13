# -*- coding: utf-8 -*-
"""
library_picker_dialog.py
========================

Cửa sổ chọn Thư viện (folder trên GDrive) trước khi chạy
Đồng bộ / Kiểm tra / Quản lý / Mở / Thêm vào Voice.
"""

__copyright__ = '2026, AudiobookGdrive Authors'
__license__ = 'GPL v3'

from PyQt5.Qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QMessageBox,
)

from audiobookgdrive.config import prefs
from audiobookgdrive.audiobook_sync.state_store import DEFAULT_LIBRARY_NAME


class LibraryPickerDialog(QDialog):
    """Chọn 1 thư viện từ danh sách đã cấu hình.

    Nếu chỉ có đúng 1 thư viện (mặc định Audiobooks) thì có thể bỏ qua
    dialog và trả về luôn -- gọi :meth:`pick` để tiện dùng.
    """

    def __init__(self, parent=None, title='Chọn thư viện', message=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        self.resize(420, 140)
        self._selected = None

        layout = QVBoxLayout(self)
        hint = QLabel(message or 'Chọn thư viện sách nói trên Google Drive:')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel('Thư viện:'))
        self.combo = QComboBox(self)
        libraries = list(prefs.get('audiobook_library_folders') or [DEFAULT_LIBRARY_NAME])
        if not libraries:
            libraries = [DEFAULT_LIBRARY_NAME]
        # Đảm bảo mặc định luôn có trong list
        if DEFAULT_LIBRARY_NAME not in libraries:
            libraries = [DEFAULT_LIBRARY_NAME] + libraries
        active = prefs.get('audiobook_active_library') or DEFAULT_LIBRARY_NAME
        for name in libraries:
            self.combo.addItem(name)
        idx = self.combo.findText(active)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        row.addWidget(self.combo, stretch=1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self._selected = self.combo.currentText().strip()
        if not self._selected:
            QMessageBox.warning(self, self.windowTitle(), 'Vui lòng chọn thư viện.')
            return
        prefs['audiobook_active_library'] = self._selected
        self.accept()

    def selected_library(self):
        return self._selected

    @classmethod
    def pick(cls, parent=None, title='Chọn thư viện', message=None, force_show=False):
        """Trả về tên thư viện đã chọn, hoặc ``None`` nếu huỷ.

        Nếu chỉ có 1 thư viện và ``force_show=False`` thì không hiện
        dialog, trả về luôn tên đó (và ghi active).
        """
        libraries = list(prefs.get('audiobook_library_folders') or [DEFAULT_LIBRARY_NAME])
        if not libraries:
            libraries = [DEFAULT_LIBRARY_NAME]
        if DEFAULT_LIBRARY_NAME not in libraries:
            libraries = [DEFAULT_LIBRARY_NAME] + libraries

        if len(libraries) == 1 and not force_show:
            name = libraries[0]
            prefs['audiobook_active_library'] = name
            return name

        dialog = cls(parent, title=title, message=message)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.selected_library()

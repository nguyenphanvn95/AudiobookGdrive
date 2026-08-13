# -*- coding: utf-8 -*-
"""
audiobook_manage_dialog.py
=============================

"Quản lý Audiobooks trên Drive..." (nâng cấp 2.6.0) -- duyệt/quản lý
các audiobook đã có trong ``Audiobooks/metadata_public.json`` trên
Drive, cùng bố cục/tinh thần với ``book_manage_dialog.DeviceLibraryManageDialog``
("Quản lý sách trên Device Library"): tìm kiếm + lọc + sắp xếp, chế độ
Danh sách/Lưới, đa chọn + xoá hàng loạt, dialog "Chi tiết" khi bấm đúp.

Khác với Device Library, dữ liệu nguồn ở đây là 1 file JSON duy nhất
(``metadata_public.json``, không phải manifest có tombstone) -- xem
``audiobook_sync/manage_ops.py`` cho toàn bộ nghiệp vụ đọc/sửa/xoá.

Mọi thao tác mạng chạy trên background QThread
(``audiobook_sync/manage_worker.py``) -- không bao giờ gọi Drive API
trên GUI thread.
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

import html
import os
import time

from PyQt5.Qt import (
    Qt, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QSpinBox, QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QProgressBar, QPlainTextEdit, QMessageBox, QScrollArea, QFrame, QSizePolicy,
    QFileDialog, QIcon, QPixmap, QSize, QPainter, QColor, QFrame,
    QUrl, pyqtSignal,
)
from PyQt5.QtGui import QDesktopServices

from audiobookgdrive.audiobook_sync import manage_worker

VIEW_LIST = 'list'
VIEW_GRID = 'grid'

# Cùng mặc định với Device Library Manage (Lưới, 5 cuốn/hàng).
DEFAULT_VIEW = VIEW_GRID
DEFAULT_GRID_COLUMNS = 5

# (nhãn hiển thị, khoá dữ liệu combo) cho sắp xếp -- hàm khoá sort thật
# nằm trong SORT_FUNCS bên dưới (không lưu lambda làm userData của
# QComboBox, để tránh phụ thuộc vào việc PyQt5 có wrap được object Python
# tuỳ ý làm QVariant hay không).
SORT_OPTIONS = [
    ('Tên (A-Z)', 'title'),
    ('Mới thêm trước', 'added'),
    ('Kích thước lớn nhất trước', 'size'),
    ('Số chương nhiều nhất trước', 'chapters'),
]
SORT_FUNCS = {
    'title': lambda b: b.title.lower(),
    'added': lambda b: -b.added_at,
    'size': lambda b: -b.size_bytes,
    'chapters': lambda b: -b.chapter_count,
}

FILTER_OPTIONS = [
    ('Tất cả', 'all'),
    ('Có ảnh bìa', 'has_cover'),
    ('Không có ảnh bìa', 'no_cover'),
    ('Có chương', 'has_chapters'),
    ('Không có chương', 'no_chapters'),
    ('Có audio', 'has_audio'),
    ('Không có audio', 'no_audio'),
]


def _placeholder_icon(size=96):
    pm = QPixmap(size, size)
    pm.fill(QColor('#dfe3e8'))
    painter = QPainter(pm)
    painter.setPen(QColor('#8a8f98'))
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, 'No\nCover')
    painter.end()
    return QIcon(pm)


def _format_size(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.0f %s' % (n, unit) if unit == 'B' else '%.1f %s' % (n, unit)
        n /= 1024.0
    return '%.1f GB' % n


def _format_datetime(ms):
    if not ms:
        return 'Không rõ'
    try:
        return time.strftime('%d/%m/%Y %H:%M', time.localtime(ms / 1000.0))
    except (ValueError, OSError, OverflowError):
        return 'Không rõ'


def _matches_filter(book, filter_key):
    if filter_key == 'has_cover':
        return book.has_cover
    if filter_key == 'no_cover':
        return not book.has_cover
    if filter_key == 'has_chapters':
        return book.chapter_count > 0
    if filter_key == 'no_chapters':
        return book.chapter_count == 0
    if filter_key == 'has_audio':
        return book.has_audio
    if filter_key == 'no_audio':
        return not book.has_audio
    return True


class AudiobookDetailDialog(QDialog):
    """"Chi tiết audiobook" -- mở khi bấm đúp vào ảnh bìa/dòng của 1
    cuốn, cùng bố cục với ``book_manage_dialog.BookDetailDialog``. Bản
    thân dialog này KHÔNG gọi mạng -- chỉ hiển thị dữ liệu đã có sẵn
    trong bộ nhớ và phát tín hiệu khi người dùng bấm 1 trong 2 nút hành
    động; dialog cha (``AudiobookLibraryManageDialog``) là nơi thực sự
    chạy QThread tương ứng."""

    edit_requested = pyqtSignal(str)    # key
    delete_requested = pyqtSignal(str)  # key
    resync_requested = pyqtSignal(str)  # key

    def __init__(self, parent_dialog, book, cover_pixmap):
        QDialog.__init__(self, parent_dialog)
        self.book = book
        self.setWindowTitle('Chi tiết Audiobook')
        self.resize(460, 560)

        outer = QVBoxLayout()
        self.setLayout(outer)

        cover_label = QLabel(self)
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if cover_pixmap and not cover_pixmap.isNull():
            cover_label.setPixmap(cover_pixmap.scaledToHeight(
                220, Qt.TransformationMode.SmoothTransformation))
        else:
            cover_label.setPixmap(_placeholder_icon(180).pixmap(180, 180))
        outer.addWidget(cover_label)

        title_label = QLabel(
            '<div style="font-size:14pt; font-weight:bold;">%s</div>'
            % html.escape(book.title), self)
        title_label.setTextFormat(Qt.TextFormat.RichText)
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title_label)

        action_row = QHBoxLayout()
        self.edit_btn = QPushButton('✎  Sửa metadata', self)
        self.edit_btn.setToolTip(
            'Sửa tiêu đề/tác giả/NXB/ngôn ngữ/mô tả của cuốn này trong '
            'metadata_public.json (offline + trên Drive). Không đụng tới '
            'file metadata.opf hay file audio thật trên Drive.')
        self.edit_btn.clicked.connect(self._on_edit)
        action_row.addWidget(self.edit_btn)

        if book.drive_folder_id:
            open_btn = QPushButton('↗  Mở trên Drive', self)
            open_btn.clicked.connect(self._on_open_drive)
            action_row.addWidget(open_btn)

        self.delete_btn = QPushButton('🗑  Xóa', self)
        self.delete_btn.setToolTip('Xóa cuốn này khỏi metadata_public.json.')
        self.delete_btn.clicked.connect(self._on_delete)
        action_row.addWidget(self.delete_btn)

        if book.drive_folder_id:
            self.resync_btn = QPushButton('⟲  Đồng bộ từ Drive', self)
            self.resync_btn.setToolTip(
                'Đọc lại metadata.opf + ảnh bìa THẬT từ đúng thư mục của cuốn này trên '
                'Google Drive rồi ghi đè lại metadata_public.json (offline + Drive) -- '
                'khắc phục trường hợp "Không có ảnh bìa" do 1 lượt upload trước lỗi giữa '
                'chừng để lại nhiều file cover.jpg/metadata.opf trùng tên trong cùng thư '
                'mục (bản tạo sớm nhất được coi là bản chuẩn).')
            self.resync_btn.clicked.connect(self._on_resync)
            action_row.addWidget(self.resync_btn)
        outer.addLayout(action_row)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(line)

        outer.addWidget(QLabel('<b>Metadata</b>', self))
        audio_cell = '%d' % book.audio_file_count
        if not book.has_audio:
            audio_cell = '<span style="color:#c0392b;"><b>0 -- ⚠ không có audio!</b></span>'
        info_html = (
            '<table cellspacing="6">'
            '<tr><td><b>Tác giả</b></td><td colspan="3">%s</td></tr>'
            '<tr><td><b>NXB</b></td><td>%s</td>'
            '<td style="padding-left:24px;"><b>Ngôn ngữ</b></td><td>%s</td></tr>'
            '<tr><td><b>Kích thước</b></td><td>%s</td>'
            '<td style="padding-left:24px;"><b>Số chương</b></td><td>%s</td></tr>'
            '<tr><td><b>Số file audio</b></td><td colspan="3">%s</td></tr>'
            '<tr><td valign="top"><b>Đã thêm</b></td><td colspan="3">%s</td></tr>'
            '</table>'
        ) % (
            html.escape(book.creators_display),
            html.escape(book.publisher or 'Không rõ'),
            html.escape(book.language or 'Không rõ'),
            html.escape(_format_size(book.size_bytes)),
            book.chapter_count,
            audio_cell,
            html.escape(_format_datetime(book.added_at)),
        )
        info_label = QLabel(info_html, self)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setWordWrap(True)
        outer.addWidget(info_label)

        outer.addWidget(QLabel('<b>Mô tả</b>', self))
        desc_text = (book.description or '').strip() or '(Không có)'
        desc_label = QLabel(html.escape(desc_text), self)
        desc_label.setWordWrap(True)
        desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        desc_label.setMargin(6)

        desc_scroll = QScrollArea(self)
        desc_scroll.setWidgetResizable(True)
        desc_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        desc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desc_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        desc_scroll.setWidget(desc_label)
        desc_scroll.setMinimumHeight(80)
        desc_scroll.setMaximumHeight(160)
        desc_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(desc_scroll)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton('Đóng', self)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    def _on_open_drive(self):
        QDesktopServices.openUrl(
            QUrl('https://drive.google.com/drive/folders/%s' % self.book.drive_folder_id))

    # Đóng dialog chi tiết TRƯỚC khi phát tín hiệu, cùng lý do đã ghi
    # trong book_manage_dialog.BookDetailDialog: dialog cha sẽ reload()
    # sau khi hành động xong, làm mất hiệu lực mọi item mà dialog này
    # còn giữ tham chiếu gián tiếp.
    def _on_edit(self):
        self.accept()
        self.edit_requested.emit(self.book.key)

    def _on_delete(self):
        self.accept()
        self.delete_requested.emit(self.book.key)

    def _on_resync(self):
        self.accept()
        self.resync_requested.emit(self.book.key)


class AudiobookLibraryManageDialog(QDialog):
    def __init__(self, gui, access_token, library_name=None):
        QDialog.__init__(self, gui)
        self.gui = gui
        self.access_token = access_token
        self.library_name = library_name or 'Audiobooks'
        self.root_id = None
        self.books = []
        self._by_key = {}
        self._items_by_key = {}
        self._cover_paths = {}
        self.list_thread = None
        self.cover_thread = None
        self.action_thread = None
        self._placeholder = _placeholder_icon()

        self.setWindowTitle('Quản lý Audiobooks trên Drive — %s' % (library_name or 'Audiobooks'))
        self.resize(920, 640)

        outer = QVBoxLayout()
        self.setLayout(outer)

        top = QHBoxLayout()
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText('Tìm theo tiêu đề hoặc tác giả...')
        self.search_box.textChanged.connect(self._refresh_view)
        top.addWidget(self.search_box, 1)

        top.addWidget(QLabel('Lọc:'))
        self.filter_combo = QComboBox(self)
        for label, key in FILTER_OPTIONS:
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(self._refresh_view)
        top.addWidget(self.filter_combo)

        top.addWidget(QLabel('Sắp xếp:'))
        self.sort_combo = QComboBox(self)
        for label, key in SORT_OPTIONS:
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self._refresh_view)
        top.addWidget(self.sort_combo)
        outer.addLayout(top)

        top2 = QHBoxLayout()
        top2.addWidget(QLabel('Hiển thị:'))
        self.view_combo = QComboBox(self)
        self.view_combo.addItem('Danh sách', VIEW_LIST)
        self.view_combo.addItem('Lưới', VIEW_GRID)
        top2.addWidget(self.view_combo)

        top2.addWidget(QLabel('Cột:'))
        self.columns_spin = QSpinBox(self)
        self.columns_spin.setRange(2, 8)
        self.columns_spin.setValue(DEFAULT_GRID_COLUMNS)
        self.columns_spin.setEnabled(False)
        self.columns_spin.valueChanged.connect(self._apply_grid_geometry)
        top2.addWidget(self.columns_spin)
        top2.addStretch()
        outer.addLayout(top2)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setViewMode(QListWidget.ViewMode.ListMode)
        self.list_widget.setIconSize(QSize(32, 32))
        self.list_widget.itemSelectionChanged.connect(self._update_action_buttons)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self.list_widget, 1)

        # Kích hoạt chế độ hiển thị mặc định NGAY SAU khi list_widget đã
        # tồn tại, cùng thủ thuật book_manage_dialog dùng: kết nối tín
        # hiệu view_combo ở đây để setCurrentIndex() bên dưới tự gọi
        # _on_view_changed() đúng 1 lần.
        idx = self.view_combo.findData(DEFAULT_VIEW)
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)
        self.view_combo.currentIndexChanged.connect(self._on_view_changed)
        self._on_view_changed(self.view_combo.currentIndex())

        select_row = QHBoxLayout()
        self.select_all_btn = QPushButton('Chọn tất cả', self)
        self.select_all_btn.clicked.connect(self.list_widget.selectAll)
        select_row.addWidget(self.select_all_btn)
        self.select_none_btn = QPushButton('Bỏ chọn', self)
        self.select_none_btn.clicked.connect(self.list_widget.clearSelection)
        select_row.addWidget(self.select_none_btn)
        select_row.addStretch()
        self.count_label = QLabel('0 audiobook')
        select_row.addWidget(self.count_label)
        outer.addLayout(select_row)

        btn_row = QHBoxLayout()
        self.edit_btn = QPushButton('Sửa metadata...', self)
        self.edit_btn.clicked.connect(self._edit_selected)
        btn_row.addWidget(self.edit_btn)
        self.purge_checkbox = QCheckBox('Xóa cả thư mục trên Drive', self)
        self.purge_checkbox.setToolTip(
            'Bỏ trống: chỉ xóa khỏi metadata_public.json (app đọc sách nói '
            'sẽ không còn thấy cuốn này nữa, nhưng file thật trên Drive vẫn '
            'còn). Chọn: xóa vĩnh viễn cả thư mục cuốn sách trên Google '
            'Drive để giải phóng dung lượng -- không thể hoàn tác.')
        btn_row.addWidget(self.purge_checkbox)
        self.delete_btn = QPushButton('Xóa đã chọn', self)
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        self.refresh_btn = QPushButton('Làm mới', self)
        self.refresh_btn.clicked.connect(self.reload)
        btn_row.addWidget(self.refresh_btn)
        self.close_btn = QPushButton('Đóng', self)
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)
        outer.addLayout(btn_row)

        self.status_label = QLabel('Đang tải...')
        outer.addWidget(self.status_label)
        self.progress_bar = QProgressBar(self)
        outer.addWidget(self.progress_bar)
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        outer.addWidget(self.log_view)

        self._set_busy(True)
        self.reload()

    # -- loading -----------------------------------------------------
    def reload(self):
        self._set_busy(True)
        self.status_label.setText('Đang tải metadata_public.json từ Google Drive...')
        self.list_widget.clear()
        self._items_by_key = {}

        self.list_thread = manage_worker.ListAudiobooksThread(self.access_token, parent=self, library_name=self.library_name)
        self.list_thread.finished_ok.connect(self._on_list_finished)
        self.list_thread.failed.connect(self._on_list_failed)
        self.list_thread.start()

    def _on_list_finished(self, root_id, books, source):
        self.root_id = root_id
        self.books = books
        self._by_key = {b.key: b for b in books}
        source_label = 'Google Drive' if source == 'drive' else 'bản backup offline'
        # Nạp bìa đã cache trên đĩa ngay (không chờ thread / mạng)
        from audiobookgdrive.audiobook_sync.manage_ops import peek_cached_cover_path
        cached_n = 0
        for b in books:
            if not b.cover_file_id:
                continue
            path = peek_cached_cover_path(b.cover_file_id, key=b.key)
            if path:
                self._cover_paths[b.key] = path
                cached_n += 1
        self.status_label.setText(
            '%d audiobook (nguồn: %s)%s.' % (
                len(books), source_label,
                (', %d bìa từ cache' % cached_n) if cached_n else ''))
        self._set_busy(False)
        self._refresh_view()
        self._start_cover_loading(books)

    def _on_list_failed(self, message):
        self.status_label.setText('Tải danh sách thất bại: %s' % message)
        self._set_busy(False)

    # -- search/filter/sort -------------------------------------------
    def _refresh_view(self, *_args):
        text = self.search_box.text().strip().lower()
        filter_key = self.filter_combo.currentData()
        sort_fn = SORT_FUNCS.get(self.sort_combo.currentData(), SORT_FUNCS['title'])

        def matches(book):
            if text and text not in (book.title + ' ' + book.creators_display).lower():
                return False
            return _matches_filter(book, filter_key)

        visible = [b for b in self.books if matches(b)]
        visible.sort(key=sort_fn)
        self._populate(visible)

    def _populate(self, books):
        # Giữ lại lựa chọn hiện tại theo key khi sắp xếp/lọc lại -- đổi
        # tiêu chí sắp xếp không nên làm mất những gì người dùng đã chọn.
        selected_keys = {item.data(Qt.ItemDataRole.UserRole)
                          for item in self.list_widget.selectedItems()}
        self.list_widget.clear()
        self._items_by_key = {}
        for book in books:
            label = '%s — %s' % (book.title, book.creators_display)
            if not book.has_audio:
                # Đánh dấu nổi bật ngay trên nhãn (không chỉ trong tooltip)
                # để dễ phát hiện các cuốn "rỗng ruột" (0 audio) khi lướt
                # qua danh sách/lưới, ví dụ 2 cuốn trùng tên do 1 lượt
                # đồng bộ trước bị ngắt giữa chừng -- xem
                # ``audiobook_sync/checker.py``.
                label = '⚠ KHÔNG CÓ AUDIO — ' + label
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, book.key)
            cached = self._cover_paths.get(book.key)
            icon = self._placeholder
            if cached and os.path.exists(cached):
                pm = QPixmap(cached)
                if not pm.isNull():
                    icon = QIcon(pm)
            item.setIcon(icon)
            if not book.has_audio:
                item.setForeground(QColor('#c0392b'))
            item.setToolTip(
                '%s\n%s\n%s -- %d chương -- %d file audio -- thêm %s%s' % (
                    book.title, book.creators_display, _format_size(book.size_bytes),
                    book.chapter_count, book.audio_file_count, _format_datetime(book.added_at),
                    '\n⚠ Không có file audio nào!' if not book.has_audio else ''))
            self.list_widget.addItem(item)
            self._items_by_key[book.key] = item
            if book.key in selected_keys:
                item.setSelected(True)
        self.count_label.setText('%d / %d audiobook' % (len(books), len(self.books)))
        self._update_action_buttons()

    # -- covers --------------------------------------------------------
    def _start_cover_loading(self, books):
        if self.cover_thread and self.cover_thread.isRunning():
            self.cover_thread.requestInterruption()
            self.cover_thread.wait(200)
        self.cover_thread = manage_worker.CoverLoaderThread(self.access_token, books, parent=self)
        self.cover_thread.cover_loaded.connect(self._on_cover_loaded)
        self.cover_thread.start()

    def _on_cover_loaded(self, key, local_path):
        self._cover_paths[key] = local_path
        item = self._items_by_key.get(key)
        if not item or not local_path or not os.path.exists(local_path):
            return
        pm = QPixmap(local_path)
        if not pm.isNull():
            item.setIcon(QIcon(pm))

    # -- view mode -------------------------------------------------------
    def _on_view_changed(self, _index):
        mode = self.view_combo.currentData()
        self.columns_spin.setEnabled(mode == VIEW_GRID)
        if mode == VIEW_GRID:
            self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
            self.list_widget.setWrapping(True)
            self.list_widget.setMovement(QListWidget.Movement.Static)
            self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
            self._apply_grid_geometry()
        else:
            self.list_widget.setViewMode(QListWidget.ViewMode.ListMode)
            self.list_widget.setWrapping(False)
            self.list_widget.setIconSize(QSize(32, 32))
            self.list_widget.setGridSize(QSize())

    def _apply_grid_geometry(self):
        if self.view_combo.currentData() != VIEW_GRID:
            return
        columns = max(2, self.columns_spin.value())
        viewport_width = max(self.list_widget.viewport().width(), 400)
        cell_width = max(96, viewport_width // columns - 8)
        icon_size = int(cell_width * 0.75)
        self.list_widget.setIconSize(QSize(icon_size, icon_size))
        self.list_widget.setGridSize(QSize(cell_width, icon_size + 64))

    def resizeEvent(self, event):
        QDialog.resizeEvent(self, event)
        self._apply_grid_geometry()

    # -- actions ---------------------------------------------------------
    def _selected_books(self):
        return [b for item in self.list_widget.selectedItems()
                for b in [self._by_key.get(item.data(Qt.ItemDataRole.UserRole))] if b]

    def _update_action_buttons(self):
        n = len(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(n == 1)
        self.delete_btn.setEnabled(n >= 1)

    def _on_item_double_clicked(self, item):
        self._show_book_details(item)

    def _show_book_details(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        book = self._by_key.get(key)
        if not book:
            return
        cover_pm = item.icon().pixmap(220, 220) if not item.icon().isNull() else None
        if cover_pm is not None and cover_pm.isNull():
            cover_pm = None
        dlg = AudiobookDetailDialog(self, book, cover_pm)
        dlg.edit_requested.connect(self._edit_metadata_dialog)
        dlg.delete_requested.connect(self._delete_by_key)
        dlg.resync_requested.connect(self._resync_by_key)
        dlg.exec_()

    def _edit_selected(self):
        selected = self._selected_books()
        if len(selected) != 1:
            return
        self._edit_metadata_dialog(selected[0].key)

    def _edit_metadata_dialog(self, key):
        book = self._by_key.get(key)
        if not book:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle('Sửa metadata')
        dlg.resize(420, 360)
        layout = QVBoxLayout()
        dlg.setLayout(layout)

        layout.addWidget(QLabel('Tiêu đề:', dlg))
        title_edit = QLineEdit(book.title, dlg)
        layout.addWidget(title_edit)

        layout.addWidget(QLabel('Tác giả (phân tách bởi dấu phẩy):', dlg))
        creators_edit = QLineEdit(', '.join(book.creators), dlg)
        layout.addWidget(creators_edit)

        layout.addWidget(QLabel('Nhà xuất bản:', dlg))
        publisher_edit = QLineEdit(book.publisher, dlg)
        layout.addWidget(publisher_edit)

        layout.addWidget(QLabel('Ngôn ngữ:', dlg))
        language_edit = QLineEdit(book.language, dlg)
        layout.addWidget(language_edit)

        layout.addWidget(QLabel('Mô tả:', dlg))
        description_edit = QPlainTextEdit(book.description, dlg)
        description_edit.setMaximumHeight(100)
        layout.addWidget(description_edit)

        note = QLabel(
            'Chỉ cập nhật metadata_public.json (offline + trên Drive) -- '
            'không đụng tới metadata.opf hay file audio thật trên Drive.', dlg)
        note.setWordWrap(True)
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton('Lưu', dlg)
        save_btn.setDefault(True)
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton('Hủy', dlg)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        if dlg.exec_() != QDialog.DialogCode.Accepted:
            return

        new_title = title_edit.text().strip()
        new_creators_text = creators_edit.text().strip()
        new_publisher = publisher_edit.text().strip()
        new_language = language_edit.text().strip()
        new_description = description_edit.toPlainText().strip()

        if not new_title:
            QMessageBox.warning(self, 'Google Drive Sync', 'Tiêu đề không được để trống.')
            return

        changed = (
            new_title != book.title
            or new_creators_text != ', '.join(book.creators)
            or new_publisher != book.publisher
            or new_language != book.language
            or new_description != book.description
        )
        if not changed:
            return

        self._run_action(
            manage_worker.EditMetadataThread(
                self.access_token, key, title=new_title, creators_text=new_creators_text,
                publisher=new_publisher, language=new_language, description=new_description,
                parent=self, library_name=self.library_name),
            'Đang cập nhật metadata...')

    def _resync_by_key(self, key):
        """Nút "⟲ Đồng bộ từ Drive" trong Chi tiết Audiobook -- đọc lại
        metadata.opf + ảnh bìa chuẩn (bản tạo sớm nhất nếu có nhiều bản
        trùng tên do lỗi upload) từ đúng thư mục Drive của cuốn này rồi
        ghi đè lại metadata_public.json. Xem
        ``audiobook_sync/manage_ops.resync_book_from_drive``."""
        book = self._by_key.get(key)
        if not book:
            return
        reply = QMessageBox.question(
            self, 'Google Drive Sync',
            'Đồng bộ lại metadata + ảnh bìa của "%s" theo đúng file metadata.opf/cover '
            'đang có thật trên Google Drive (nếu có nhiều bản trùng tên do lỗi upload, '
            'lấy bản tạo sớm nhất làm chuẩn)?\n\nThao tác này sẽ GHI ĐÈ tiêu đề/tác giả/'
            'NXB/ngôn ngữ/mô tả/ảnh bìa hiện có trong metadata_public.json cho cuốn này.'
            % book.title,
            QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_action(
            manage_worker.ResyncBookThread(self.access_token, key, parent=self, library_name=self.library_name),
            'Đang đồng bộ từ Drive...')

    def _delete_by_key(self, key):
        """Nút thùng rác trong Chi tiết Audiobook -- xóa đúng 1 cuốn, tái
        dùng cùng luồng xác nhận + ``purge_checkbox`` như nút "Xóa đã
        chọn" hàng loạt phía dưới."""
        book = self._by_key.get(key)
        if not book:
            return
        self.list_widget.clearSelection()
        item = self._items_by_key.get(key)
        if item:
            item.setSelected(True)
        self._delete_selected()

    def _delete_selected(self):
        selected = self._selected_books()
        if not selected:
            return
        purge = self.purge_checkbox.isChecked()
        if purge:
            reply = QMessageBox.question(
                self, 'Google Drive Sync',
                'Xóa VĨNH VIỄN %d audiobook đã chọn (cả metadata_public.json '
                'lẫn thư mục thật trên Google Drive)? Hành động này không '
                'thể hoàn tác.' % len(selected),
                QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)
        else:
            reply = QMessageBox.question(
                self, 'Google Drive Sync',
                'Xóa %d audiobook đã chọn khỏi metadata_public.json? File '
                'thật trên Google Drive sẽ KHÔNG bị xóa.' % len(selected),
                QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        keys = [b.key for b in selected]
        self._run_action(
            manage_worker.DeleteAudiobooksThread(
                self.access_token, keys, purge, parent=self, library_name=self.library_name),
            'Đang xóa...')

    def _run_action(self, thread, status_text):
        self._set_busy(True)
        self.status_label.setText(status_text)
        self.action_thread = thread
        thread.log.connect(self.log_view.appendPlainText)
        thread.finished_ok.connect(self._on_action_finished)
        thread.failed.connect(self._on_action_failed)
        thread.start()

    def _on_action_finished(self):
        self.status_label.setText('Hoàn tất.')
        self.reload()

    def _on_action_failed(self, message):
        self._set_busy(False)
        self.status_label.setText('Thất bại: %s' % message)
        QMessageBox.warning(self, 'Google Drive Sync', message)

    # -- lifecycle ---------------------------------------------------------
    def _set_busy(self, busy):
        self.progress_bar.setMaximum(0 if busy else 1)
        self.progress_bar.setValue(0 if busy else 1)
        for w in (self.search_box, self.filter_combo, self.sort_combo, self.view_combo,
                  self.columns_spin, self.select_all_btn, self.select_none_btn,
                  self.refresh_btn, self.list_widget):
            w.setEnabled(not busy)
        if busy:
            self.edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
        else:
            self._update_action_buttons()

    def reject(self):
        for t in (self.list_thread, self.cover_thread, self.action_thread):
            if t and t.isRunning():
                QMessageBox.information(
                    self, 'Google Drive Sync', 'Đang xử lý, vui lòng đợi.')
                return
        QDialog.reject(self)

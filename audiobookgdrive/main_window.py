# -*- coding: utf-8 -*-
"""
main_window.py
================

Cửa sổ chính của AudiobookGdrive -- ứng dụng độc lập tách riêng từ nhánh
"Audiobook Sync" của plugin Calibre Gdrive Sync 2.7.7. Thay cho toolbar
dropdown trong Calibre (``ui.py`` gốc), đây là 1 cửa sổ Qt độc lập với
các nút bấm tương ứng 1-1 với từng hành động gốc:

* Đăng nhập / Đăng xuất Google
* Đồng bộ Audiobooks lên Google Drive (Upload)
* Kiểm tra Audiobooks trên Drive...
* Quản lý Audiobooks trên Drive...
* Mở thư mục Audiobooks trên Drive (trình duyệt)
* Thêm thư viện sách nói vào Voice... (ghép nối Android qua QR)
* Xem log
* Cài đặt...

Toàn bộ logic nghiệp vụ (OAuth, Drive API, upload, kiểm tra, quản lý,
chia sẻ) đều tái sử dụng NGUYÊN VẸN từ các module đã tách ra
(``audiobook_sync/``, ``oauth.py``, ``drive_api.py``, ...) -- file này
chỉ đóng vai trò tương đương ``ui.py`` gốc: điều phối UI, không chứa
logic Drive API nào của riêng nó.
"""

__copyright__ = '2026, AudiobookGdrive Authors'
__license__ = 'GPL v3'

from PyQt5.Qt import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QGroupBox, QFrame, QDesktopServices, QUrl, Qt, QIcon,
    QPixmap, QPainter, QColor, QSize,
)

from audiobookgdrive import oauth
from audiobookgdrive.config import prefs, SettingsDialog
from audiobookgdrive.logger import get_logger
from audiobookgdrive.log_dialog import LogDialog
from audiobookgdrive import tray

APP_TITLE = 'AudiobookGdrive'


def _resource_path(*parts):
    """Đường dẫn tài nguyên (icon...) -- hoạt động cả khi chạy source
    lẫn khi đóng gói PyInstaller (``sys._MEIPASS``)."""
    import os
    import sys
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base = sys._MEIPASS
        # Ưu tiên resources nằm cạnh exe / trong bundle
        candidates = [
            os.path.join(base, *parts),
            os.path.join(base, 'audiobookgdrive', *parts),
            os.path.join(os.path.dirname(sys.executable), *parts),
        ]
    else:
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(pkg_dir, *parts),
            os.path.join(pkg_dir, 'resources', *parts) if parts[0] != 'resources' else os.path.join(pkg_dir, *parts),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


def _app_icon():
    """Icon ứng dụng: ưu tiên ``resources/icon.png`` (hoặc .ico),
    fallback vẽ chữ A nếu thiếu file."""
    import os
    for name in ('resources/icon.png', 'resources/icon.ico', 'icon.png', 'icon.ico'):
        path = _resource_path(*name.split('/'))
        if path and os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    # Fallback vẽ bằng code
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor('#1a73e8'))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, size - 4, size - 4)
        painter.setPen(QColor('white'))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(28)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, 'A')
    finally:
        painter.end()
    return QIcon(pix)


def _precheck_signed_in(parent):
    """Trả về access_token hợp lệ, hoặc None (đã tự hiện thông báo lỗi
    phù hợp cho người dùng)."""
    if not (oauth.has_usable_client() and oauth.is_logged_in()):
        QMessageBox.information(
            parent, APP_TITLE,
            'Hãy đăng nhập Google Drive trước (nút "Đăng nhập Google" '
            'hoặc mở Cài đặt -> tab Tài khoản).')
        return None
    try:
        return oauth.get_valid_access_token(*oauth.get_effective_credentials())
    except oauth.OAuthError as e:
        QMessageBox.warning(parent, APP_TITLE, str(e))
        return None


class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        self.setWindowTitle(APP_TITLE)
        self.resize(520, 480)
        self.setWindowIcon(_app_icon())

        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # -- Account status -------------------------------------------
        account_box = QGroupBox('Tài khoản Google Drive')
        account_layout = QHBoxLayout(account_box)
        self.account_label = QLabel()
        account_layout.addWidget(self.account_label, stretch=1)
        self.login_btn = QPushButton('Đăng nhập Google')
        self.login_btn.clicked.connect(self.login)
        account_layout.addWidget(self.login_btn)
        self.logout_btn = QPushButton('Đăng xuất')
        self.logout_btn.clicked.connect(self.logout)
        account_layout.addWidget(self.logout_btn)
        outer.addWidget(account_box)

        # -- Audiobook actions ------------------------------------------
        actions_box = QGroupBox('Audiobook Sync')
        actions_layout = QVBoxLayout(actions_box)

        self.sync_btn = QPushButton('⬆  Đồng bộ Audiobooks lên Google Drive')
        self.sync_btn.clicked.connect(self.run_audiobook_sync)
        actions_layout.addWidget(self.sync_btn)

        self.check_btn = QPushButton('✓  Kiểm tra Audiobooks trên Drive...')
        self.check_btn.clicked.connect(self.run_audiobook_check)
        actions_layout.addWidget(self.check_btn)

        self.manage_btn = QPushButton('☰  Quản lý Audiobooks trên Drive...')
        self.manage_btn.clicked.connect(self.run_audiobook_manage)
        actions_layout.addWidget(self.manage_btn)

        self.open_drive_btn = QPushButton('🌐  Mở thư mục Audiobooks trên Drive')
        self.open_drive_btn.clicked.connect(self.open_audiobooks_on_drive)
        actions_layout.addWidget(self.open_drive_btn)

        outer.addWidget(actions_box)

        # -- Android pairing ----------------------------------------------
        pairing_box = QGroupBox('Ghép nối với ứng dụng nghe sách nói Voice (Android)')
        pairing_layout = QVBoxLayout(pairing_box)
        pairing_hint = QLabel(
            'Sau khi đã đồng bộ ít nhất 1 lần, bấm nút bên dưới để lấy link '
            '+ mã QR, dán/quét trong app Voice trên điện thoại để thêm thư '
            'viện sách nói.')
        pairing_hint.setWordWrap(True)
        pairing_layout.addWidget(pairing_hint)
        self.pairing_btn = QPushButton('📱  Thêm thư viện sách nói vào Voice...')
        self.pairing_btn.clicked.connect(self.show_audiobook_pairing_dialog)
        pairing_layout.addWidget(self.pairing_btn)
        outer.addWidget(pairing_box)

        outer.addStretch()

        # -- Bottom row: settings / logs -----------------------------------
        bottom_row = QHBoxLayout()
        self.log_btn = QPushButton('Xem log')
        self.log_btn.clicked.connect(self.show_log)
        bottom_row.addWidget(self.log_btn)
        bottom_row.addStretch()
        self.settings_btn = QPushButton('⚙  Cài đặt...')
        self.settings_btn.clicked.connect(self.show_settings)
        bottom_row.addWidget(self.settings_btn)
        outer.addLayout(bottom_row)

        self.status_bar = self.statusBar()
        self.status_bar.showMessage('Sẵn sàng.')

        self.logger = get_logger()
        self._refresh_account_label()

        # -- Menu bar: File > Thoát (thoát HẲN, khác nút [X] chỉ ẩn
        # xuống khay -- xem closeEvent) -----------------------------------
        file_menu = self.menuBar().addMenu('Tệp')
        exit_action = file_menu.addAction('Thoát')
        exit_action.triggered.connect(self._force_quit)
        self._quitting = False

    def _force_quit(self):
        from PyQt5.Qt import QApplication
        self._quitting = True
        QApplication.instance().quit()

    # -- Account -----------------------------------------------------------
    def _refresh_account_label(self):
        if oauth.is_logged_in():
            self.account_label.setText('Đã đăng nhập: %s' % (oauth.get_account_email() or '(không rõ)'))
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
        else:
            self.account_label.setText('Chưa đăng nhập.')
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)

    def login(self):
        from audiobookgdrive.login_dialog import run_login_flow
        client_id, client_secret = oauth.get_effective_credentials()
        if not client_id or not client_secret:
            QMessageBox.warning(
                self, APP_TITLE,
                'Chưa có Client ID/Secret hợp lệ. Kiểm tra lại tab '
                'Nâng cao trong Cài đặt.')
            return
        run_login_flow(self, client_id, client_secret)
        self._refresh_account_label()

    def logout(self):
        oauth.logout()
        self._refresh_account_label()

    # -- Audiobook Sync ------------------------------------------------
    def run_audiobook_sync(self):
        from audiobookgdrive.audiobook_dialog import AudiobookSyncProgressDialog
        from audiobookgdrive.library_picker_dialog import LibraryPickerDialog

        root_folders = [p for p in (prefs['audiobook_root_folders'] or []) if p]
        if not root_folders:
            QMessageBox.information(
                self, APP_TITLE,
                'Chưa cấu hình thư mục Audiobook nào. Mở Cài đặt -> tab '
                '"Audiobook Sync" và thêm ít nhất 1 thư mục.')
            return

        access_token = _precheck_signed_in(self)
        if not access_token:
            return

        library_name = LibraryPickerDialog.pick(
            self, title='Chọn thư viện để đồng bộ',
            message='Chọn thư mục thư viện trên Google Drive để upload sách nói:')
        if not library_name:
            return

        dialog = AudiobookSyncProgressDialog(
            self, access_token, root_folders, logger=self.logger, library_name=library_name)
        dialog.exec_()
        self.status_bar.showMessage('Đã chạy Đồng bộ Audiobooks [%s].' % library_name, 5000)

    def open_audiobooks_on_drive(self):
        from audiobookgdrive.audiobook_sync.state_store import AudiobookState
        from audiobookgdrive.library_picker_dialog import LibraryPickerDialog

        library_name = LibraryPickerDialog.pick(
            self, title='Chọn thư viện để mở',
            message='Chọn thư mục thư viện trên Google Drive:')
        if not library_name:
            return
        # Ưu tiên id đã cache trong state (không gọi mạng)
        state = AudiobookState(library_name=library_name)
        root_id = state.get_root_folder_id()
        if not root_id:
            access_token = _precheck_signed_in(self)
            if not access_token:
                return
            # Gọi mạng ngắn: chỉ tìm folder theo tên (không tải metadata 4MB)
            self.status_bar.showMessage('Đang tìm thư mục "%s" trên Drive...' % library_name)
            from audiobookgdrive.audiobook_sync.library_bind import discover_library_root
            from PyQt5.Qt import QApplication
            QApplication.processEvents()
            root_id = discover_library_root(access_token, library_name, state, log_fn=None)
            self.status_bar.clearMessage()
        if not root_id:
            QMessageBox.information(
                self, APP_TITLE,
                'Không tìm thấy thư mục "%s" trên Drive. Hãy chạy "Kiểm tra" trước.' % library_name)
            return
        QDesktopServices.openUrl(QUrl('https://drive.google.com/drive/folders/%s' % root_id))

    def run_audiobook_check(self):
        from audiobookgdrive.audiobook_check_dialog import AudiobookCheckProgressDialog
        from audiobookgdrive.audiobook_sync.state_store import AudiobookState
        from audiobookgdrive.library_picker_dialog import LibraryPickerDialog

        library_name = LibraryPickerDialog.pick(
            self, title='Chọn thư viện để kiểm tra',
            message='Chọn thư mục thư viện trên Google Drive để kiểm tra '
                    '(có thể là thư viện đã đồng bộ trước đó bằng app khác):')
        if not library_name:
            return

        access_token = _precheck_signed_in(self)
        if not access_token:
            return

        # Không chặn khi state local trống -- checker sẽ tự tìm thư mục
        # + metadata_public.json trên Drive và nạp vào state.
        dialog = AudiobookCheckProgressDialog(
            self, access_token, logger=self.logger, library_name=library_name)
        dialog.exec_()
        self.status_bar.showMessage('Đã chạy Kiểm tra [%s].' % library_name, 5000)

    def run_audiobook_manage(self):
        from audiobookgdrive.audiobook_manage_dialog import AudiobookLibraryManageDialog
        from audiobookgdrive.library_picker_dialog import LibraryPickerDialog

        library_name = LibraryPickerDialog.pick(
            self, title='Chọn thư viện để quản lý',
            message='Chọn thư mục thư viện trên Google Drive để quản lý:')
        if not library_name:
            return

        access_token = _precheck_signed_in(self)
        if not access_token:
            return

        # Không gọi Drive API trên UI thread -- dialog tự tải danh sách
        # qua ListAudiobooksThread (manage_ops._load sẽ discover + tải json).
        dialog = AudiobookLibraryManageDialog(self, access_token, library_name=library_name)
        dialog.exec_()

    def show_audiobook_pairing_dialog(self):
        from audiobookgdrive.audiobook_pairing_dialog import AudiobookPairingDialog
        from audiobookgdrive.audiobook_sync.state_store import AudiobookState
        from audiobookgdrive.audiobook_sync import sharing
        from audiobookgdrive.library_picker_dialog import LibraryPickerDialog

        library_name = LibraryPickerDialog.pick(
            self, title='Chọn thư viện để thêm vào Voice',
            message='Chọn thư mục thư viện trên Google Drive để ghép nối app Voice:')
        if not library_name:
            return

        access_token = _precheck_signed_in(self)
        if not access_token:
            return

        state = AudiobookState(library_name=library_name)
        file_id = state.get_metadata_json_id()
        root_id = state.get_root_folder_id()
        # Nếu chưa có cache: tìm folder + file metadata theo tên (không parse toàn bộ json)
        if not file_id or not root_id:
            from audiobookgdrive.audiobook_sync.library_bind import discover_library_root
            from audiobookgdrive import drive_api
            from audiobookgdrive.audiobook_sync.metadata_io import METADATA_JSON_NAME
            from PyQt5.Qt import QApplication
            self.status_bar.showMessage('Đang tìm metadata trên Drive...')
            QApplication.processEvents()
            if not root_id:
                root_id = discover_library_root(access_token, library_name, state, log_fn=None)
            if root_id and not file_id:
                try:
                    meta = drive_api.find_child_file(access_token, root_id, METADATA_JSON_NAME)
                    if meta and meta.get('id'):
                        file_id = meta['id']
                        state.set_metadata_json_id(file_id)
                except Exception:
                    pass
            self.status_bar.clearMessage()
        if not file_id:
            QMessageBox.information(
                self, APP_TITLE,
                'Chưa tìm thấy metadata_public.json trong thư viện "%s". '
                'Hãy chạy "Kiểm tra" hoặc "Đồng bộ" trước.' % library_name)
            return

        share_warning = None
        root_id = state.get_root_folder_id()
        if root_id:
            try:
                ok, failed_names = sharing.share_audiobooks_public(access_token, root_id)
                if not ok:
                    shown = ', '.join(failed_names[:5])
                    if len(failed_names) > 5:
                        shown += ', ...'
                    share_warning = (
                        '%d thư mục cuốn không tự chia sẻ công khai được (%s) -- thường '
                        'là cuốn được thêm THỦ CÔNG thẳng trên Drive (không qua "Đồng bộ '
                        'Audiobooks lên Google Drive"), ứng dụng không có quyền ghi lên đó. '
                        'Các cuốn còn lại đã chia sẻ công khai bình thường. Muốn chia sẻ '
                        'nốt (các) cuốn trên, vào drive.google.com, bấm chuột phải từng '
                        'thư mục đó trong "%s" -> Share -> "Anyone with the link".'
                        % (len(failed_names), shown, library_name))
            except Exception as e:
                share_warning = ('Không tự chia sẻ công khai được thư mục "%s" '
                                  '(%s) -- nếu app Voice không mở được link, hãy vào '
                                  'drive.google.com, bấm chuột phải thư mục "%s" -> '
                                  'Share -> "Anyone with the link".'
                                  % (library_name, e, library_name))

        book_count = len(state.all_keys())
        dialog = AudiobookPairingDialog(file_id, book_count, share_warning=share_warning, parent=self)
        dialog.exec_()

    # -- Settings / logs -------------------------------------------------
    def show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_():
            self._refresh_account_label()

    def show_log(self):
        dialog = LogDialog(self, active_logger=self.logger)
        dialog.exec_()


    def closeEvent(self, event):
        """Nhấn nút [X] chỉ ẩn cửa sổ xuống khay hệ thống (để các tác vụ
        đang chạy tác vụ không bị huỷ giữa chừng) -- muốn thoát hẳn,
        dùng menu Tệp -> Thoát, hoặc chuột phải icon khay -> Thoát."""
        if self._quitting or tray.get_tray_icon() is None:
            event.accept()
            return
        tray.notify(APP_TITLE, 'Đã thu nhỏ xuống khay hệ thống. Nhấp đúp icon để mở lại, '
                                'hoặc chuột phải icon -> Thoát để đóng hẳn.')
        self.hide()
        event.ignore()

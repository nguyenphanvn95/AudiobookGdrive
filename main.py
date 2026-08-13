# -*- coding: utf-8 -*-
"""
main.py
=======

Entry point của AudiobookGdrive -- khởi tạo QApplication, tray icon, và
cửa sổ chính. Chạy bằng:

    python main.py

(hoặc dùng ``run_AudiobookGdrive.bat`` đi kèm trên Windows).
"""

__copyright__ = '2026, AudiobookGdrive Authors'
__license__ = 'GPL v3'

import sys


def main():
    from PyQt5.Qt import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName('AudiobookGdrive')
    app.setQuitOnLastWindowClosed(False)  # cửa sổ có thể ẩn xuống khay mà không thoát app

    from audiobookgdrive.main_window import MainWindow, _app_icon
    from audiobookgdrive import tray

    icon = _app_icon()
    app.setWindowIcon(icon)

    window = MainWindow()
    tray.init_tray(icon, app, main_window=window)
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

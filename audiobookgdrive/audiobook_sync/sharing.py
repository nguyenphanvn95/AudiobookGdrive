# -*- coding: utf-8 -*-
"""
audiobook_sync/sharing.py
============================

Chia sẻ công khai ("Anyone with the link") thư mục ``Audiobooks/`` trên
Drive -- dùng bởi mục **"Thêm thư viện sách nói vào Voice..."**
(``ui.show_audiobook_pairing_dialog``).

Vì sao KHÔNG THỂ chỉ gọi ``drive_api.create_public_permission`` 1 lần
trên thư mục gốc rồi coi như xong (khác hẳn "Calibre Library" --
``sync_manager._maybe_share_root_public`` -- luôn thành công vì MỌI
file/thư mục dưới root đều do chính app tạo)::

    Google từ chối đặt permission trên 1 THƯ MỤC nếu app không có quyền
    ghi lên MỌI thứ bên trong nó (permission trên folder phải cascade
    xuống hết con cháu) -- trả về đúng lỗi HTTP 403 "The user may not
    have granted the app ... write access to all of the children of
    file ...". Với OAuth scope ``drive.file`` mà plugin dùng, app chỉ có
    quyền ghi lên file/thư mục CHÍNH NÓ đã tạo ra.

    Audiobook Sync (khác Calibre Library) có tính năng
    ``checker._add_missing_books_from_drive`` chủ động PHÁT HIỆN + THÊM
    vào ``metadata_public.json`` những thư mục cuốn sách người dùng tự
    kéo-thả thẳng lên Drive (đánh dấu ``origin = 'drive_manual'``),
    KHÔNG qua app -- các thư mục đó app không hề có quyền ghi. Chỉ cần
    1 cuốn kiểu này nằm trong ``Audiobooks/`` là lệnh share ở CẤP THƯ
    MỤC GỐC bị Google từ chối thẳng, dù mọi cuốn khác đều do app tạo và
    lẽ ra chia sẻ được bình thường.

Chiến lược 2 bước: thử share nguyên thư mục gốc trước (rẻ, 1 lệnh gọi,
đủ dùng cho đa số trường hợp không có cuốn thêm thủ công nào); nếu bị
từ chối, rơi xuống chia sẻ RIÊNG TỪNG thư mục cuốn con -- (các) cuốn
app không có quyền sẽ tự bị bỏ qua (best-effort, không raise), còn lại
vẫn chia sẻ được bình thường thay vì chặn đứng CẢ thư viện chỉ vì 1
cuốn.
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

from audiobookgdrive import drive_api


def share_audiobooks_public(access_token, root_id):
    """Trả về ``(ok, failed_names)``:

    * ``ok=True, failed_names=[]`` -- thư mục gốc (nên cả cây bên dưới)
      đã ở chế độ công khai, xong ngay ở bước rẻ.
    * ``ok=True, failed_names=[]`` -- bước rẻ bị từ chối nhưng SAU KHI
      chia sẻ riêng từng cuốn thì mọi cuốn đều thành công (thư mục gốc
      tự nó có thể vẫn ở chế độ riêng tư, nhưng không ảnh hưởng gì vì
      Drive chỉ cần TỪNG file/thư mục con công khai là app đọc anonymous
      truy cập được).
    * ``ok=False, failed_names=[...]`` -- ít nhất 1 thư mục cuốn con
      không chia sẻ được (thường là cuốn thêm thủ công trên Drive) --
      ``failed_names`` là tên các thư mục đó để nơi gọi báo cụ thể cho
      người dùng, thay vì 1 lỗi 403 chung chung khó hiểu.

    Có thể raise ``drive_api.DriveApiError``/``DriveRetryableError``
    nếu ngay cả việc LIỆT KÊ danh sách thư mục con cũng lỗi (mất mạng,
    token hết hạn...) -- nơi gọi (``ui.py``) tự bọc try/except quanh
    lệnh gọi hàm này.
    """
    try:
        drive_api.create_public_permission(access_token, root_id)
        return True, []
    except drive_api.DriveApiError:
        pass  # rơi xuống chia sẻ riêng từng cuốn bên dưới

    failed = []
    for child in drive_api.list_folder_children(access_token, root_id):
        try:
            drive_api.create_public_permission(access_token, child['id'])
        except Exception:
            failed.append(child.get('name') or child.get('id') or '?')
    return (not failed), failed

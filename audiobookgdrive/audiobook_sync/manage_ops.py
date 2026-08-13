# -*- coding: utf-8 -*-
"""
audiobook_sync/manage_ops.py
==============================

Nghiệp vụ đứng sau **"Quản lý Audiobooks trên Drive..."** (nâng cấp
2.6.0) -- đối ứng với ``device_sync/manage_ops.py`` (quản lý Device
Library), nhưng thao tác trên nguồn dữ liệu khác hẳn:

* Device Library quản lý qua ``calibre_sync_manifest.json``, xoá bằng
  tombstone (``deletedAt``), vì điện thoại cần thấy tombstone để tự gỡ
  file đã tải.
* Audiobook Sync là *một chiều* (chỉ upload từ máy tính lên Drive) và
  app đọc sách nói bên ngoài chỉ dựa vào **``metadata_public.json``**
  (xem ``uploader.py``) để biết audiobook nào tồn tại -- không có khái
  niệm tombstone/đồng bộ 2 chiều nào cần giữ lại. Vì vậy ở đây "xoá" đơn
  giản là loại hẳn entry khỏi ``audiobooks`` dict trong json (đủ để app
  đọc sách nói ngừng hiển thị cuốn đó), kèm tuỳ chọn xoá luôn thư mục
  thật trên Drive để giải phóng dung lượng.

Mọi thao tác ghi (sửa/xoá) đều TẢI LẠI ``metadata_public.json`` mới
nhất (ưu tiên từ Drive, dự phòng bản backup offline -- tái dùng
``checker.download_metadata_json``) ngay trước khi ghi đè, để giảm rủi
ro ghi đè mất dữ liệu nếu vừa có 1 lượt "Đồng bộ Audiobooks lên Google
Drive" khác chạy xong trong lúc dialog quản lý đang mở.

Không đụng Qt ở đây -- chạy trên background QThread qua
``manage_worker.py``, đúng nguyên tắc xuyên suốt plugin này (không bao
giờ gọi mạng trên GUI thread).
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

import hashlib
import json
import os
import tempfile
from datetime import datetime

from audiobookgdrive import drive_api

from . import backup, checker
from .opf_parser import parse_opf_file
from .scanner import COVER_NAMES, OPF_NAME
from .state_store import AudiobookState
from .uploader import METADATA_JSON_NAME, _upload_bytes_resumable, _with_retry


class ManageError(Exception):
    pass


class ManagedAudiobook(object):
    """View nhẹ quanh 1 entry thô (dict) trong ``audiobooks`` của
    ``metadata_public.json``, không copy dữ liệu. ``key`` là khoá
    ``<root_path>|<ten_thu_muc>`` (``scanner.AudiobookFolder.key``)."""

    def __init__(self, key, entry):
        self.key = key
        self.entry = entry or {}

    @property
    def title(self):
        return (self.entry.get('title') or '').strip() or self.folder_name or self.key

    @property
    def folder_name(self):
        return self.entry.get('folder_name') or ''

    @property
    def creators(self):
        return [c.get('name') for c in (self.entry.get('creators') or []) if c.get('name')]

    @property
    def creators_display(self):
        return ', '.join(self.creators) if self.creators else 'Không rõ tác giả'

    @property
    def publisher(self):
        return self.entry.get('publisher') or ''

    @property
    def language(self):
        return self.entry.get('language') or ''

    @property
    def description(self):
        return self.entry.get('description') or ''

    @property
    def chapters(self):
        return self.entry.get('chapters') or []

    @property
    def chapter_count(self):
        return len(self.chapters)

    @property
    def has_cover(self):
        cover = self.entry.get('cover')
        return bool(cover and cover.get('file_id'))

    @property
    def cover_file_id(self):
        cover = self.entry.get('cover')
        return cover.get('file_id') if cover else None

    @property
    def drive_folder_id(self):
        return self.entry.get('drive_folder_id') or ''

    @property
    def added_at(self):
        return self.entry.get('added_at') or 0

    @property
    def size_bytes(self):
        total = 0
        for finfo in (self.entry.get('audio_files') or {}).values():
            total += (finfo or {}).get('size') or 0
        return total

    @property
    def audio_file_count(self):
        """Số file audio ghi nhận trong ``metadata_public.json`` cho cuốn
        này. 0 nghĩa là cuốn "rỗng ruột" -- thường do 1 lượt "Đồng bộ
        Audiobooks lên Google Drive" bị ngắt giữa chừng ngay sau khi tạo
        xong thư mục + tải xong metadata.opf/cover nhưng chưa kịp tải
        audio nào (xem ``audiobook_sync/checker.py``, mục phát hiện
        "không có audio")."""
        return len(self.entry.get('audio_files') or {})

    @property
    def has_audio(self):
        return self.audio_file_count > 0


def _load(access_token, log_fn=None, library_name=None):
    """Trả về ``(state, root_id, payload, source)``. Raise
    :class:`ManageError` nếu chưa từng đồng bộ Audiobook lần nào, hoặc
    không tìm thấy ``metadata_public.json`` ở cả Drive lẫn bản backup
    offline. Tự tìm thư mục thư viện + file metadata nếu state local trống
    (thư viện đồng bộ trước đó bằng app khác)."""
    from .state_store import DEFAULT_LIBRARY_NAME
    from .library_bind import discover_library_root, import_state_from_payload
    lib_name = (library_name or DEFAULT_LIBRARY_NAME).strip() or DEFAULT_LIBRARY_NAME
    state = AudiobookState(library_name=lib_name)
    root_id = discover_library_root(access_token, lib_name, state, log_fn=log_fn)
    if not root_id:
        raise ManageError(
            'Không tìm thấy thư mục "%s" trên Google Drive '
            '(hoặc app không có quyền nhìn thấy với scope drive.file).' % lib_name)

    payload, source = checker.download_metadata_json(
        access_token, state, log_fn=log_fn, root_id=root_id)
    if payload is None:
        raise ManageError(
            'Không tìm thấy %s trên Drive lẫn bản backup offline (thư viện "%s").'
            % (METADATA_JSON_NAME, lib_name))
    import_state_from_payload(state, payload, log_fn=log_fn)
    return state, root_id, payload, source


def _save(access_token, state, root_id, payload, log_fn=None):
    log_fn = log_fn or (lambda msg: None)
    payload['generated_at'] = datetime.now().isoformat(sep='T', timespec='seconds')
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode('utf-8')

    existing_id = state.get_metadata_json_id() or None
    file_id = _with_retry(
        lambda: _upload_bytes_resumable(
            access_token, data, METADATA_JSON_NAME, root_id, 'application/json', existing_id),
        log_fn, METADATA_JSON_NAME)
    state.set_metadata_json_id(file_id or existing_id or '')
    # Yêu cầu nâng cấp 2.6.0: mọi thay đổi qua dialog quản lý phải phản
    # ánh cả ở bản offline lẫn trên Drive -- dùng lại đúng cơ chế backup
    # có xoay vòng của audiobook_sync/backup.py (2.5.1 #1) để 2 nơi luôn
    # khớp nhau, giống hệt sau mỗi lần Audiobook Sync/Check chạy xong.
    library_name = getattr(state, 'library_name', None)
    backup.save_backup(data, log_fn, library_name=library_name)


def list_audiobooks(access_token, log_fn=None, library_name=None):
    """Trả về ``(root_id, list[ManagedAudiobook], source)``, sắp xếp mặc
    định theo tiêu đề không phân biệt hoa/thường (dialog quản lý sẽ tự
    sắp lại theo tiêu chí người dùng chọn -- đây chỉ là thứ tự khởi
    điểm ổn định)."""
    _state, root_id, payload, source = _load(access_token, log_fn, library_name=library_name)
    books = payload.get('audiobooks') or {}
    result = [ManagedAudiobook(key, entry) for key, entry in books.items()]
    result.sort(key=lambda b: b.title.lower())
    return root_id, result, source


def _parse_creators(text):
    """"Nguyễn Nhật Ánh, Nguyễn Ngọc Thuần" -> [{"name": ..., "role": None}, ...].
    Không giữ lại `role` gốc (nếu opf có) khi sửa qua đây -- người dùng
    chỉ nhập tên phân tách bởi dấu phẩy, đơn giản hoá đúng tinh thần ô
    "Tác giả" một dòng của dialog sửa metadata."""
    names = [n.strip() for n in (text or '').split(',')]
    return [{'name': n, 'role': None} for n in names if n]


def edit_metadata(access_token, key, title=None, creators_text=None, library_name=None,
                   publisher=None, language=None, description=None, log_fn=None):
    """Sửa metadata của 1 entry -- CHỈ ghi vào ``metadata_public.json``
    (offline + Drive), KHÔNG đụng tới ``metadata.opf`` thật hay các file
    audio nằm trong thư mục cuốn sách trên Drive (đúng yêu cầu nâng cấp
    2.6.0 mục #2: "cập nhật metadata_public.json offline và trên
    drive"). Tham số nào truyền ``None`` nghĩa là giữ nguyên; truyền
    chuỗi rỗng nghĩa là xoá trắng trường đó."""
    log_fn = log_fn or (lambda msg: None)
    state, root_id, payload, _source = _load(access_token, log_fn, library_name=library_name)
    books = payload.get('audiobooks') or {}
    entry = books.get(key)
    if not entry:
        raise ManageError(
            'Không tìm thấy cuốn sách này trong %s (có thể đã bị xoá/đổi ở '
            'nơi khác -- hãy Làm mới danh sách rồi thử lại).' % METADATA_JSON_NAME)

    entry = dict(entry)
    if title is not None:
        title = title.strip()
        if not title:
            raise ManageError('Tiêu đề không được để trống.')
        entry['title'] = title
    if creators_text is not None:
        entry['creators'] = _parse_creators(creators_text)
    if publisher is not None:
        entry['publisher'] = publisher.strip() or None
    if language is not None:
        entry['language'] = language.strip() or None
    if description is not None:
        entry['description'] = description.strip() or None

    books[key] = entry
    payload['audiobooks'] = books
    _save(access_token, state, root_id, payload, log_fn)
    log_fn('Đã cập nhật metadata cho "%s".' % (entry.get('title') or key))


def _pick_earliest(candidates):
    """``candidates``: danh sách file THẬT (dict Drive API) cùng khớp 1
    tên logic (ví dụ nhiều file đều tên ``cover.jpg`` trong cùng 1 thư
    mục -- Google Drive, khác hệ điều hành thường, KHÔNG tự đổi tên file
    trùng nên cho phép nhiều bản cùng tên tồn tại song song). Đây là hậu
    quả thường gặp của 1 lượt "Đồng bộ Audiobooks lên Google Drive" bị
    lỗi/ngắt giữa chừng rồi chạy lại: bản upload đầu (SỚM NHẤT theo
    ``createdTime``) mới là bản chuẩn/đầy đủ, các bản sau chỉ là rác từ
    lần thử lại. Trả về ``None`` nếu ``candidates`` rỗng."""
    if not candidates:
        return None
    with_time = [c for c in candidates if c.get('createdTime')]
    if with_time:
        return min(with_time, key=lambda c: c['createdTime'])
    # Hiếm khi thiếu createdTime (API luôn trả về field đã yêu cầu) --
    # dự phòng bằng cách giữ nguyên thứ tự trả về từ Drive.
    return candidates[0]


def _find_canonical_opf_and_cover(folder_children):
    """``folder_children``: list file+thư mục con THẬT (dict Drive API,
    từ ``drive_api.list_folder_children``) nằm trực tiếp trong 1 thư
    mục cuốn audiobook. Trả về ``(opf_file, cover_file)`` -- mỗi phần tử
    là dict Drive API (có ``id``/``name``) của bản CHUẨN, hoặc ``None``
    nếu không tìm thấy loại đó. Nhận diện tên không phân biệt hoa/thường
    (giống ``scanner``/``checker``); nếu có NHIỀU bản trùng tên, chọn
    bản tạo sớm nhất qua :func:`_pick_earliest`."""
    opf_candidates = [c for c in folder_children
                       if (c.get('name') or '').lower() == OPF_NAME.lower()]
    opf_file = _pick_earliest(opf_candidates)

    cover_file = None
    for candidate_name in COVER_NAMES:
        matches = [c for c in folder_children
                   if (c.get('name') or '').lower() == candidate_name]
        if matches:
            cover_file = _pick_earliest(matches)
            break

    return opf_file, cover_file


def resync_book_from_drive(access_token, key, log_fn=None, library_name=None):
    """Nút "⟲ Đồng bộ từ Drive" trong "Chi tiết Audiobook" -- đọc lại
    ``metadata.opf`` + ảnh bìa THẬT từ đúng thư mục Drive của 1 cuốn rồi
    ghi đè lại entry tương ứng trong ``metadata_public.json`` (offline +
    Drive). Khắc phục trường hợp 1 cuốn bị hiển thị nhầm "Không có ảnh
    bìa" (hoặc thiếu metadata) do 1 lượt upload trước lỗi/chạy lại giữa
    chừng để lại NHIỀU file ``cover.jpg``/``metadata.opf`` trùng tên
    trong cùng 1 thư mục trên Drive mà entry vẫn trỏ tới ``file_id`` cũ
    hoặc rỗng -- xem :func:`_find_canonical_opf_and_cover`: file được
    TẠO SỚM NHẤT trong số các bản trùng tên được coi là bản chuẩn.

    CHỈ cập nhật ``metadata_opf``/``cover`` + các trường metadata suy ra
    từ opf (tiêu đề/tác giả/NXB/ngôn ngữ/mô tả/chương/...) -- không đụng
    tới ``audio_files`` (đúng phạm vi nút "Đồng bộ", khác nút "Sửa
    metadata" vốn chỉ sửa tay từng trường, và khác "Kiểm tra Audiobooks
    trên Drive..." vốn chạy hàng loạt cho MỌI cuốn thay vì 1 cuốn theo
    yêu cầu người dùng)."""
    log_fn = log_fn or (lambda msg: None)
    state, root_id, payload, _source = _load(access_token, log_fn, library_name=library_name)
    books = payload.get('audiobooks') or {}
    entry = books.get(key)
    if not entry:
        raise ManageError(
            'Không tìm thấy cuốn sách này trong %s (có thể đã bị xoá/đổi ở '
            'nơi khác -- hãy Làm mới danh sách rồi thử lại).' % METADATA_JSON_NAME)

    folder_id = entry.get('drive_folder_id')
    if not folder_id:
        raise ManageError('Cuốn sách này không có thư mục trên Google Drive để đồng bộ lại.')

    title = entry.get('title') or entry.get('folder_name') or key
    log_fn('"%s": đang quét thư mục trên Drive...' % title)
    children = _with_retry(
        lambda: drive_api.list_folder_children(access_token, folder_id),
        log_fn, 'Quét thư mục "%s"' % title)
    opf_file, cover_file = _find_canonical_opf_and_cover(children)

    entry = dict(entry)
    changed = False

    if opf_file:
        opf_matches = sum(1 for c in children if (c.get('name') or '').lower() == OPF_NAME.lower())
        if opf_matches > 1 and log_fn:
            log_fn('WARN: "%s" có %d file metadata.opf trùng tên trên Drive -- '
                   'đã lấy bản tạo sớm nhất (id %s) làm bản chuẩn.'
                   % (title, opf_matches, opf_file['id']))
        tmp_path = None
        try:
            data = _with_retry(
                lambda: drive_api.download_file_bytes(access_token, opf_file['id']),
                log_fn, 'Tải metadata.opf')
            fd, tmp_path = tempfile.mkstemp(suffix='.opf', prefix='gdrive_sync_')
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            opf_data = parse_opf_file(tmp_path)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        entry['metadata_opf'] = {'filename': opf_file.get('name'), 'file_id': opf_file['id']}
        if opf_data.get('title'):
            entry['title'] = opf_data['title']
        if opf_data.get('creators'):
            entry['creators'] = opf_data['creators']
        entry['publisher'] = opf_data.get('publisher') or entry.get('publisher')
        entry['language'] = opf_data.get('language') or entry.get('language')
        entry['description'] = opf_data.get('description') or entry.get('description')
        if opf_data.get('identifiers'):
            entry['identifiers'] = opf_data['identifiers']
        entry['modified'] = opf_data.get('modified') or entry.get('modified')
        if opf_data.get('chapters'):
            entry['chapters'] = opf_data['chapters']
        if opf_data.get('extra_meta'):
            entry['extra_meta'] = opf_data['extra_meta']
        state.update_file(key, opf_file.get('name'), file_id=opf_file['id'])
        changed = True
        log_fn('"%s": đã đọc lại metadata.opf chuẩn (id %s) từ Drive.' % (title, opf_file['id']))
    else:
        log_fn('WARN: "%s" không tìm thấy metadata.opf nào trong thư mục trên Drive.' % title)

    if cover_file:
        cover_matches = sum(1 for c in children if (c.get('name') or '').lower() == (cover_file.get('name') or '').lower())
        if cover_matches > 1 and log_fn:
            log_fn('WARN: "%s" có %d file ảnh bìa "%s" trùng tên trên Drive -- '
                   'đã lấy bản tạo sớm nhất (id %s) làm bản chuẩn.'
                   % (title, cover_matches, cover_file.get('name'), cover_file['id']))
        entry['cover'] = {'filename': cover_file.get('name'), 'file_id': cover_file['id']}
        state.update_file(key, cover_file.get('name'), file_id=cover_file['id'])
        changed = True
        log_fn('"%s": đã lấy lại ảnh bìa chuẩn (id %s) từ Drive.' % (title, cover_file['id']))
    else:
        log_fn('WARN: "%s" không tìm thấy file ảnh bìa nào (%s) trong thư mục trên Drive.'
               % (title, '/'.join(COVER_NAMES)))

    if not changed:
        raise ManageError(
            'Không tìm thấy metadata.opf lẫn ảnh bìa trong thư mục trên Drive của cuốn này.')

    books[key] = entry
    payload['audiobooks'] = books
    _save(access_token, state, root_id, payload, log_fn)
    log_fn('Hoàn tất đồng bộ lại "%s" từ Drive.' % title)


def delete_audiobooks(access_token, keys, purge_files=False, log_fn=None, library_name=None):
    """Xoá hẳn (các) entry khỏi ``metadata_public.json`` -- không có
    tombstone (xem docstring module). Nếu ``purge_files=True``, NGOÀI RA
    còn xoá vĩnh viễn thư mục cuốn sách thật trên Drive
    (``Audiobooks/<ten_thu_muc>/``) để giải phóng dung lượng; best-effort,
    lỗi xoá file không làm hỏng việc cập nhật json. Luôn xoá cache trong
    ``state_store.AudiobookState`` cho những key đã xoá, để lần "Đồng bộ
    Audiobooks lên Google Drive" kế tiếp (nếu thư mục local tương ứng
    vẫn còn) coi cuốn đó như mới hoàn toàn thay vì dùng nhầm id cũ."""
    log_fn = log_fn or (lambda msg: None)
    state, root_id, payload, _source = _load(access_token, log_fn, library_name=library_name)
    books = payload.get('audiobooks') or {}

    count = 0
    for key in keys:
        entry = books.get(key)
        if not entry:
            continue
        title = entry.get('title') or entry.get('folder_name') or key

        if purge_files:
            folder_id = entry.get('drive_folder_id')
            if folder_id:
                try:
                    drive_api.delete_file(access_token, folder_id)
                    log_fn('Đã xoá thư mục trên Drive: %s' % title)
                except drive_api.DriveNotFoundError:
                    log_fn('Thư mục trên Drive của "%s" đã không còn tồn tại từ trước.' % title)
                except Exception as e:
                    log_fn('WARN: không xoá được thư mục trên Drive cho "%s": %s' % (title, e))
            else:
                log_fn('WARN: "%s" không có drive_folder_id trong %s, bỏ qua xoá file trên Drive.'
                       % (title, METADATA_JSON_NAME))

        del books[key]
        state.remove_book(key)
        log_fn('Đã xoá khỏi %s: %s' % (METADATA_JSON_NAME, title))
        count += 1

    payload['audiobooks'] = books
    _save(access_token, state, root_id, payload, log_fn)
    log_fn('Hoàn tất: đã xoá %d cuốn.' % count)


# -- cover thumbnail cache ------------------------------------------------
# Cache theo cover.file_id (không phụ thuộc key sách) để lần mở Quản lý
# sau hiện bìa ngay từ đĩa, kể cả khi key local đổi (root_path khác máy).
# Tương thích file cache cũ dạng ``<hash16>_<file_id>.jpg``.

def _cover_cache_dir():
    from audiobookgdrive.jsonconfig import config_dir
    d = os.path.join(config_dir, 'plugins', 'gdrive_sync_audiobook_covers')
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError:
            pass
    return d


def _safe_file_id(cover_file_id):
    # Drive file id thường [A-Za-z0-9_-]; lọc để an toàn trên Windows path
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in (cover_file_id or ''))[:120]


def peek_cached_cover_path(cover_file_id, key=None):
    """Trả về đường dẫn cache nếu đã có trên đĩa -- KHÔNG tải mạng.

    Dùng để hiện bìa tức thì khi mở dialog Quản lý.
    """
    if not cover_file_id:
        return None
    cache_dir = _cover_cache_dir()
    primary = os.path.join(cache_dir, '%s.jpg' % _safe_file_id(cover_file_id))
    if os.path.exists(primary) and os.path.getsize(primary) > 0:
        return primary
    # Cache cũ: ``<sha16>_<file_id>.jpg``
    if key:
        safe_key = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
        legacy = os.path.join(cache_dir, '%s_%s.jpg' % (safe_key, cover_file_id))
        if os.path.exists(legacy) and os.path.getsize(legacy) > 0:
            return legacy
    # Quét legacy theo hậu tố file_id (key đã đổi)
    suffix = '_%s.jpg' % cover_file_id
    try:
        for name in os.listdir(cache_dir):
            if name.endswith(suffix):
                path = os.path.join(cache_dir, name)
                if os.path.getsize(path) > 0:
                    return path
    except OSError:
        pass
    return None


def cached_cover_path(access_token, key, cover_file_id):
    """Lấy path cover: cache hit thì trả ngay; miss thì tải từ Drive và lưu."""
    if not cover_file_id:
        return None
    hit = peek_cached_cover_path(cover_file_id, key=key)
    if hit:
        return hit
    cache_dir = _cover_cache_dir()
    cached = os.path.join(cache_dir, '%s.jpg' % _safe_file_id(cover_file_id))
    data = drive_api.download_file_bytes(access_token, cover_file_id, timeout=60)
    if not data:
        return None
    try:
        tmp = cached + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, cached)
    except OSError:
        try:
            with open(cached, 'wb') as f:
                f.write(data)
        except OSError:
            return None
    return cached

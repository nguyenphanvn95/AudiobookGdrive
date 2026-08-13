# -*- coding: utf-8 -*-
"""
audiobook_sync/library_bind.py
================================

Gắn thư viện local với thư mục / metadata_public.json đã có trên Drive.
"""

__copyright__ = '2026, Google Drive Sync Plugin Authors'
__license__ = 'GPL v3'

from audiobookgdrive import drive_api


def discover_library_root(access_token, library_name, state, log_fn=None):
    """Tìm thư mục thư viện trên Drive theo tên (dưới My Drive root)."""
    name = (library_name or 'Audiobooks').strip() or 'Audiobooks'
    root_id = state.get_root_folder_id()
    if root_id and drive_api.file_exists(access_token, root_id):
        return root_id
    if root_id:
        if log_fn:
            log_fn('WARN', 'Id thư mục "%s" trong cache không còn tồn tại -- tìm lại theo tên.' % name)
        state.reset_root()

    found = drive_api.find_child_folder(access_token, 'root', name)
    if found:
        state.set_root_folder_id(found)
        if log_fn:
            log_fn('INFO', 'Đã gắn thư viện "%s" với thư mục có sẵn trên Drive (id=%s).' % (name, found))
        return found
    if log_fn:
        log_fn('WARN', 'Không tìm thấy thư mục "%s" trên Drive (My Drive). '
                       'Lưu ý: với quyền drive.file, app chỉ thấy thư mục do chính nó '
                       '(cùng Client OAuth) tạo ra.' % name)
    return ''


def import_state_from_payload(state, payload, log_fn=None):
    """Nạp bookkeeping local từ metadata_public.json -- ghi đĩa 1 lần (bulk).

    Trả về số entry đã nạp.
    """
    books = (payload or {}).get('audiobooks') or {}
    bulk = {}
    for key, entry in books.items():
        if not isinstance(entry, dict):
            continue
        folder_id = entry.get('drive_folder_id') or ''
        folder_name = entry.get('folder_name') or ''
        root_path = entry.get('root_path') or ''
        if not folder_id and not folder_name:
            continue

        files = {}

        def _take(fname, finfo):
            if not fname or not isinstance(finfo, dict):
                return
            fid = finfo.get('file_id') or ''
            if not fid:
                return
            fe = {'file_id': fid}
            if finfo.get('size') is not None:
                fe['size'] = finfo['size']
            if finfo.get('mtime') is not None:
                fe['mtime'] = finfo['mtime']
            if finfo.get('digest'):
                fe['digest'] = finfo['digest']
            files[fname] = fe

        opf = entry.get('metadata_opf') or {}
        if opf.get('filename'):
            _take(opf['filename'], opf)
        cover = entry.get('cover') or {}
        if cover.get('filename'):
            _take(cover['filename'], cover)
        for fname, finfo in (entry.get('audio_files') or {}).items():
            _take(fname, finfo or {})

        book_entry = {
            'drive_folder_id': folder_id,
            'root_path': root_path,
            'name': folder_name,
            'files': files,
        }
        if entry.get('added_at'):
            book_entry['added_at'] = entry['added_at']
        if entry.get('origin'):
            book_entry['origin'] = entry['origin']
        bulk[key] = book_entry

    imported = state.import_books_bulk(bulk) if bulk else 0
    if log_fn and imported:
        log_fn('INFO', 'Đã nạp %d cuốn từ metadata_public.json vào bộ nhớ đệm local '
                        '(1 lần ghi đĩa, tránh upload trùng).' % imported)
    return imported


def folder_name_index(payload):
    """``{folder_name: key}`` từ payload metadata."""
    index = {}
    for k, ent in ((payload or {}).get('audiobooks') or {}).items():
        fn = (ent or {}).get('folder_name') or ''
        if fn:
            index[fn] = k
    return index

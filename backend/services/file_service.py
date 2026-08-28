import os
import time

from werkzeug.utils import secure_filename

from config import Config


def allowed_file(filename):

    return (
        '.' in filename
        and filename.rsplit(
            '.',
            1
        )[1].lower()
        in Config.ALLOWED_EXTENSIONS
    )


# 常见图片 MIME 到扩展名的映射
# （原文件名不含扩展名时兜底使用，避免保存出无扩展名的文件）
MIME_TO_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}


def save_file(file, upload_folder):

    # 先在 secure_filename 之前提取扩展名，
    # 否则中文文件名会被剥掉只剩裸扩展名（如 jpg）
    base, ext = os.path.splitext(
        file.filename or ''
    )

    # 原文件名没有扩展名时，用 MIME 类型兜底
    if not ext:
        ext = MIME_TO_EXT.get(
            file.mimetype or '',
            ''
        )

    # 中文等非 ASCII 字符会被 secure_filename 剥掉，
    # 可能得到空串，此时用 image 兜底保证文件名主体非空
    safe_base = (
        secure_filename(base)
        or 'image'
    )

    timestamp = int(
        time.time()
    )

    unique_name = (
        f"{timestamp}_{safe_base}{ext}"
    )

    filepath = os.path.join(
        upload_folder,
        unique_name
    )

    file.save(filepath)

    return unique_name, filepath


def delete_file_from_url(
    file_url,
    default_url=None
):
    """根据文件的 URL 删除对应的磁盘文件。

    传入 default_url 时，等于默认值（如默认头像）的文件不会被删除。
    """

    if not file_url:
        return

    if default_url and file_url == default_url:
        return

    relative_path = file_url.lstrip('/')

    filepath = os.path.join(
        Config.BASE_DIR,
        relative_path
    )

    if os.path.exists(filepath):
        os.remove(filepath)
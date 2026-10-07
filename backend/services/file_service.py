"""文件上传与删除工具。

安全要点：
1. 保存前校验扩展名、真实文件类型（魔数）与大小；
2. 文件名带时间戳 + 随机串，避免同名覆盖；
3. 删除时只允许删除 uploads 目录内的文件，防止越权删除任意文件。
"""

import os
import time
import uuid

from werkzeug.utils import secure_filename

from config import Config
from backend.utils.logging_config import get_logger
from backend.utils.validators import (
    allowed_extension,
    check_image_signature,
    check_image_size,
    resolve_upload_url
)


logger = get_logger('file')


# 常见图片 MIME 到扩展名的映射
# （原文件名不含扩展名时兜底使用，避免保存出无扩展名的文件）
MIME_TO_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}


def allowed_file(filename):
    """扩展名白名单校验（保留旧接口，供既有调用方使用）。"""

    return allowed_extension(filename)


def build_unique_name(filename, mimetype=None):
    """生成不会冲突的存储文件名。

    旧实现只用 `int(time.time())_原名`，同一秒内的同名文件会互相覆盖，
    这里加上随机串保证唯一。
    """

    base, ext = os.path.splitext(filename or '')

    if not ext:
        ext = MIME_TO_EXT.get(mimetype or '', '')

    ext = ext.lower()

    # 中文等非 ASCII 字符会被 secure_filename 剥掉，
    # 可能得到空串，此时用 image 兜底保证文件名主体非空
    safe_base = secure_filename(base) or 'image'

    # 限制主体长度，避免超长文件名
    safe_base = safe_base[:40]

    unique = uuid.uuid4().hex[:8]

    return f'{int(time.time())}_{safe_base}_{unique}{ext}'


def save_file(file, upload_folder):
    """保存上传文件并返回 (文件名, 绝对路径)。

    仅做落盘，校验由 validate_and_save_image 负责；
    保留本函数是为了兼容既有调用方。
    """

    os.makedirs(upload_folder, exist_ok=True)

    unique_name = build_unique_name(
        file.filename,
        getattr(file, 'mimetype', None)
    )

    filepath = os.path.join(upload_folder, unique_name)

    file.save(filepath)

    return unique_name, filepath


def validate_and_save_image(file, upload_folder):
    """校验并保存图片。

    返回 (文件名, 绝对路径, 错误说明)。
    校验通过时错误说明为空串。
    """

    ok, message, real_ext = check_image_signature(file)

    if not ok:
        return None, None, message

    ok, message, _size = check_image_size(file)

    if not ok:
        return None, None, message

    # 以真实类型为准修正扩展名，避免"改名的非图片"落盘后又被当成图片使用
    declared_ext = os.path.splitext(file.filename or '')[1].lower()

    if not declared_ext:
        file.filename = (file.filename or 'image') + '.' + real_ext

    os.makedirs(upload_folder, exist_ok=True)

    unique_name = build_unique_name(
        file.filename,
        getattr(file, 'mimetype', None)
    )

    filepath = os.path.join(upload_folder, unique_name)

    file.save(filepath)

    return unique_name, filepath, ''


def delete_file_from_url(file_url, default_url=None):
    """根据文件的 URL 删除对应的磁盘文件。

    - 传入 default_url 时，等于默认值（如默认头像）的文件不会被删除；
    - 只允许删除 uploads 目录内的文件，越界路径直接忽略并记录日志。
    """

    if not file_url:
        return False

    if default_url and file_url == default_url:
        return False

    filepath = resolve_upload_url(file_url)

    if not filepath:
        logger.warning('拒绝删除上传目录之外的文件: %s', file_url)
        return False

    if os.path.isfile(filepath):
        try:
            os.remove(filepath)
            return True
        except OSError as exc:
            logger.warning('删除文件失败 %s: %s', filepath, exc)

    return False

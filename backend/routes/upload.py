"""上传接口：题目图片与头像。

所有上传都经过扩展名、真实类型（魔数）、体积三重校验，
文件名带随机串避免覆盖，落盘目录固定在 uploads 下。
"""

import os

from flask import Blueprint, current_app, request, session

from backend.extensions.database import connect_db
from backend.services.file_service import (
    delete_file_from_url,
    validate_and_save_image
)
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, ok, unauthorized
from backend.utils.security import login_required
from backend.utils.validators import allowed_extension


upload_bp = Blueprint('upload', __name__)

logger = get_logger('upload')


def _save_image_or_error(file, folder, url_prefix):
    """校验并保存图片，返回 (响应, 是否成功)。"""

    if not file or not file.filename:
        return fail('未选择文件'), False

    if not allowed_extension(file.filename):
        return fail('不支持的文件格式，仅支持 png、jpg、jpeg、gif、webp'), False

    filename, _filepath, error = validate_and_save_image(file, folder)

    if error:
        return fail(error), False

    return ok(image_url=f'{url_prefix}/{filename}'), True


@upload_bp.route('/api/upload_image', methods=['POST'])
@login_required
def upload_image():
    """上传题目图片，返回可供引用的站内地址。"""

    if 'image' not in request.files:
        return fail('没有上传文件')

    response, success = _save_image_or_error(
        request.files['image'],
        current_app.config['IMAGE_UPLOAD_FOLDER'],
        '/uploads/problems'
    )

    if not success:
        return response

    return response


@upload_bp.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    """上传并更新头像。

    先保存新头像，再更新数据库，最后删除旧头像；
    数据库失败时回滚删除刚上传的新文件，避免产生孤儿文件。
    """

    if 'avatar' not in request.files:
        return fail('没有上传文件')

    file = request.files['avatar']

    if not file or not file.filename:
        return fail('未选择文件')

    if not allowed_extension(file.filename):
        return fail('不支持的文件格式，仅支持 png、jpg、jpeg、gif、webp')

    username = session['username']

    connection = connect_db()
    filepath = None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT avatar_path
                FROM users
                WHERE user_no = %s
                """,
                (username,)
            )

            old = cursor.fetchone()

            old_avatar_path = old['avatar_path'] if old else None

        filename, filepath, error = validate_and_save_image(
            file,
            current_app.config['AVATAR_UPLOAD_FOLDER']
        )

        if error:
            return fail(error)

        avatar_url = '/uploads/avatars/' + filename

        # 先更新数据库，成功后再删除旧头像，
        # 避免“旧头像已删但数据库更新失败”导致头像丢失
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET avatar_path = %s
                WHERE user_no = %s
                """,
                (avatar_url, username)
            )

            connection.commit()

        delete_file_from_url(
            old_avatar_path,
            default_url=current_app.config['DEFAULT_AVATAR']
        )

        session['avatar_path'] = avatar_url

        return ok(avatar_path=avatar_url)

    except Exception as exc:

        logger.error('上传头像失败 %s: %s', username, exc)

        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                logger.warning('回滚删除头像文件失败: %s', filepath)

        return fail('头像上传失败，请稍后重试', status=500)

    finally:
        connection.close()

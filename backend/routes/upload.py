import os
from flask import Blueprint, request, jsonify, session, current_app
from werkzeug.utils import secure_filename
from backend.extensions.database import connect_db
from backend.services.file_service import (
    allowed_file,
    save_file,
    delete_file_from_url
)


upload_bp = Blueprint(
    'upload',
    __name__
)


@upload_bp.route(
    '/api/upload_image',
    methods=['POST']
)
def upload_image():

    if 'username' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    if 'image' not in request.files:
        return jsonify({
            'success': False,
            'message': '没有上传文件'
        }), 400

    file = request.files['image']

    if file.filename == '':
        return jsonify({
            'success': False,
            'message': '未选择文件'
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            'success': False,
            'message':
                '不支持的文件格式，仅支持 png、jpg、jpeg、gif、webp'
        }), 400

    filename, filepath = save_file(
        file,
        current_app.config[
            'IMAGE_UPLOAD_FOLDER'
        ]
    )

    image_url = (
        '/uploads/problems/'
        + filename
    )

    return jsonify({
        'success': True,
        'image_url': image_url
    })


@upload_bp.route(
    '/upload_avatar',
    methods=['POST']
)
def upload_avatar():

    if 'username' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    if 'avatar' not in request.files:
        return jsonify({
            'success': False,
            'message': '没有上传文件'
        }), 400

    file = request.files['avatar']

    if file.filename == '':
        return jsonify({
            'success': False,
            'message': '未选择文件'
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            'success': False,
            'message': '不支持的文件格式'
        }), 400

    username = session['username']

    connection = connect_db()

    filepath = None

    try:

        # 1. 查询旧头像
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

            old_avatar_path = (
                old['avatar_path']
                if old
                else None
            )

        # 2. 保存新头像
        filename, filepath = save_file(
            file,
            current_app.config[
                'AVATAR_UPLOAD_FOLDER'
            ]
        )

        avatar_url = (
            '/uploads/avatars/'
            + filename
        )

        # 3. 删除旧头像
        delete_file_from_url(
            old_avatar_path,
            default_url=current_app.config[
                'DEFAULT_AVATAR'
            ]
        )

        # 4. 更新数据库
        with connection.cursor() as cursor:

            sql = """
                UPDATE users
                SET avatar_path = %s
                WHERE user_no = %s
            """

            cursor.execute(
                sql,
                (
                    avatar_url,
                    username
                )
            )

            connection.commit()

        # 5. 更新 session
        session['avatar_path'] = avatar_url

        return jsonify({
            'success': True,
            'avatar_path': avatar_url
        })

    except Exception as e:

        # 删除上传失败时产生的新文件
        if (
            filepath
            and os.path.exists(filepath)
        ):
            os.remove(filepath)

        return jsonify({
            'success': False,
            'message': f'上传失败: {str(e)}'
        }), 500

    finally:
        connection.close()
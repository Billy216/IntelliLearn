"""Flask 应用工厂。

职责：
- 加载配置并校验关键安全项（SECRET_KEY）；
- 初始化日志、上传目录、会话安全参数与请求体大小限制；
- 注册蓝图与统一的错误处理（/api/* 一律返回 JSON）。
"""

import os

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from config import Config, validate_secret_key
from backend.utils.logging_config import get_logger, setup_logging
from backend.utils.responses import (
    CODE_NOT_FOUND,
    CODE_PAYLOAD_TOO_LARGE,
    CODE_SERVER_ERROR,
    fail
)


logger = get_logger('app')


def _register_error_handlers(app):
    """统一错误返回格式。

    接口请求返回 JSON，页面请求保留 Flask 默认的 HTML 错误页。
    """

    def wants_json():
        return request.path.startswith('/api/')

    @app.errorhandler(404)
    def handle_404(error):
        if wants_json():
            return fail('接口不存在', status=404, code=CODE_NOT_FOUND)

        return error, 404

    @app.errorhandler(405)
    def handle_405(error):
        if wants_json():
            return fail(
                '请求方法不被允许',
                status=405,
                code='METHOD_NOT_ALLOWED'
            )

        return error, 405

    @app.errorhandler(413)
    def handle_413(error):
        limit_mb = app.config['MAX_CONTENT_LENGTH'] / 1024 / 1024

        if wants_json():
            return fail(
                f'上传内容过大，单次请求不能超过 {limit_mb:.0f}MB',
                status=413,
                code=CODE_PAYLOAD_TOO_LARGE
            )

        return error, 413

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        # HTTP 异常（如 401/403）按原状态码返回，不吞掉
        if isinstance(error, HTTPException):
            if wants_json():
                return fail(
                    error.description or '请求处理失败',
                    status=error.code or 500
                )

            return error

        logger.exception('未捕获的服务器异常: %s', error)

        if wants_json():
            return fail(
                '服务器内部错误，请稍后重试',
                status=500,
                code=CODE_SERVER_ERROR
            )

        return '服务器内部错误，请稍后重试', 500

    @app.after_request
    def add_security_headers(response):
        """补充基础安全响应头。"""

        response.headers.setdefault(
            'X-Content-Type-Options',
            'nosniff'
        )
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault(
            'Referrer-Policy',
            'same-origin'
        )

        return response


def create_app():

    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static'
    )

    # 加载配置
    app.config.from_object(Config)

    setup_logging(app)

    # 安全校验：SECRET_KEY 缺失或过弱时，生产模式直接拒绝启动
    validate_secret_key(app)

    # 创建上传目录
    os.makedirs(
        app.config['AVATAR_UPLOAD_FOLDER'],
        exist_ok=True
    )

    os.makedirs(
        app.config['IMAGE_UPLOAD_FOLDER'],
        exist_ok=True
    )

    # 提供 /uploads 下的文件访问
    # （头像与题目照片存放在根目录 uploads，不在 static 内）
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(
            app.config['UPLOAD_ROOT'],
            filename
        )

    # 兼容历史数据：早期版本把图片写在 static/uploads 下，
    # 数据库里仍存着 /static/uploads/xxx.png 这类地址。
    # 这里做一次尽力转发，文件确实不存在时仍返回 404。
    @app.route('/static/uploads/<path:filename>')
    def legacy_uploaded_file(filename):
        for folder in (
            app.config['IMAGE_UPLOAD_FOLDER'],
            app.config['AVATAR_UPLOAD_FOLDER']
        ):
            if os.path.isfile(os.path.join(folder, filename)):
                return send_from_directory(folder, filename)

        return jsonify({
            'success': False,
            'message': '图片不存在',
            'code': CODE_NOT_FOUND
        }), 404

    _register_error_handlers(app)

    # 注册路由
    from backend.routes.page import page_bp
    from backend.routes.auth import auth_bp
    from backend.routes.user import user_bp
    from backend.routes.upload import upload_bp
    from backend.routes.chat import chat_bp
    from backend.routes.wrong_questions import wrong_bp
    from backend.routes.practice import practice_bp
    from backend.routes.resources import resources_bp
    from backend.routes.teacher import teacher_bp
    from backend.routes.admin import admin_bp

    app.register_blueprint(page_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(wrong_bp)
    app.register_blueprint(practice_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(admin_bp)

    logger.info(
        'IntelliLearn 启动完成（debug=%s，模型=%s）',
        app.config.get('DEBUG'),
        app.config.get('AI_MODEL')
    )

    return app

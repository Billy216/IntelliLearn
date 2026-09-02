import os

from flask import Flask, send_from_directory

from config import Config


def create_app():

    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )

    # 加载配置
    app.config.from_object(Config)

    # 创建上传目录
    os.makedirs(
        app.config["AVATAR_UPLOAD_FOLDER"],
        exist_ok=True
    )

    os.makedirs(
        app.config["IMAGE_UPLOAD_FOLDER"],
        exist_ok=True
    )

    # 提供 /uploads 下的文件访问
    # （头像与题目照片存放在根目录 uploads，不在 static 内）
    @app.route(
        '/uploads/<path:filename>'
    )
    def uploaded_file(filename):
        return send_from_directory(
            os.path.join(
                Config.BASE_DIR,
                'uploads'
            ),
            filename
        )

    # 注册路由
    from backend.routes.page import page_bp
    from backend.routes.auth import auth_bp
    from backend.routes.user import user_bp
    from backend.routes.upload import upload_bp
    from backend.routes.chat import chat_bp

    app.register_blueprint(page_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(chat_bp)

    return app

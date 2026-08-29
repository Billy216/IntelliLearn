import os

from dotenv import load_dotenv


# 加载项目根目录下的 .env
load_dotenv()


class Config:

    # =========================
    # Flask
    # =========================

    SECRET_KEY = os.getenv("SECRET_KEY")

    # =========================
    # 项目路径
    # =========================

    BASE_DIR = os.path.abspath(
        os.path.dirname(__file__)
    )

    # =========================
    # 上传目录
    # =========================

    AVATAR_UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads",
        "avatars"
    )

    IMAGE_UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads",
        "problems"
    )

    ALLOWED_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }

    DEFAULT_AVATAR = (
        "/static/pic/userAvatar.png"
    )

    # =========================
    # MySQL
    # =========================

    DB_HOST = os.getenv(
        "DB_HOST",
        "127.0.0.1"
    )

    DB_PORT = int(
        os.getenv(
            "DB_PORT",
            "3306"
        )
    )

    DB_USER = os.getenv(
        "DB_USER",
        "root"
    )

    DB_PASSWORD = os.getenv(
        "DB_PASSWORD"
    )

    DB_NAME = os.getenv(
        "DB_NAME"
    )

    DB_CHARSET = os.getenv(
        "DB_CHARSET",
        "utf8"
    )

    DB_CONNECT_TIMEOUT = int(
        os.getenv(
            "DB_CONNECT_TIMEOUT",
            "10"
        )
    )

    # =========================
    # AI
    # =========================

    AI_API_KEY = os.getenv(
        "AI_API_KEY"
    )
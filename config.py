"""项目配置。

所有可变参数集中在 Config 中，敏感值一律从环境变量（.env）读取，
不在代码中硬编码任何密钥。
"""

import os

from dotenv import load_dotenv


# 加载项目根目录下的 .env
load_dotenv()


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _env_bool(name, default=False):
    """读取布尔型环境变量，接受 1/true/yes/on。"""

    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Config:

    # =========================
    # Flask
    # =========================

    # 生产环境必须通过环境变量提供强随机密钥；
    # 这里保留弱密钥占位以便本地启动时给出明确告警（见 validate_secret_key）。
    SECRET_KEY = os.getenv('SECRET_KEY')

    # 开发调试开关：默认关闭。
    # 生产环境绝不能开启 debug（Werkzeug 调试器可执行任意代码）。
    DEBUG = _env_bool('FLASK_DEBUG', False)

    # =========================
    # 项目路径
    # =========================

    BASE_DIR = BASE_DIR

    # 上传根目录（头像与题目图片都在其下）
    UPLOAD_ROOT = os.path.join(BASE_DIR, 'uploads')

    AVATAR_UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        'uploads',
        'avatars'
    )

    IMAGE_UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        'uploads',
        'problems'
    )

    # 日志目录
    LOG_DIR = os.path.join(BASE_DIR, 'logs')

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

    # =========================
    # 上传限制
    # =========================

    # 单次请求体上限（图片限制 5MB，预留表单与其他字段空间）
    MAX_CONTENT_LENGTH = _env_int(
        'MAX_CONTENT_LENGTH',
        8 * 1024 * 1024
    )

    # 单张图片大小上限
    MAX_IMAGE_SIZE = _env_int(
        'MAX_IMAGE_SIZE',
        5 * 1024 * 1024
    )

    ALLOWED_EXTENSIONS = {
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp'
    }

    # 允许的图片真实类型（魔数校验），键为后缀，值为文件头字节
    ALLOWED_IMAGE_SIGNATURES = {
        'png': (b'\x89PNG\r\n\x1a\n',),
        'jpg': (b'\xff\xd8\xff',),
        'jpeg': (b'\xff\xd8\xff',),
        'gif': (b'GIF87a', b'GIF89a'),
        'webp': (b'RIFF',)
    }

    DEFAULT_AVATAR = '/static/pic/userAvatar.png'

    # 是否允许 AI 识图时读取远程 http(s) 图片地址。
    # 默认关闭：开启后服务端会请求外部地址，存在 SSRF 风险。
    ALLOW_REMOTE_IMAGE_URL = _env_bool(
        'ALLOW_REMOTE_IMAGE_URL',
        False
    )

    # =========================
    # 会话安全
    # =========================

    SESSION_COOKIE_HTTPONLY = True

    SESSION_COOKIE_SAMESITE = 'Lax'

    # 仅在 HTTPS 部署时开启（本地 http 调试需为 False）
    SESSION_COOKIE_SECURE = _env_bool(
        'SESSION_COOKIE_SECURE',
        False
    )

    # 登录态有效期（秒），默认 7 天
    PERMANENT_SESSION_LIFETIME = _env_int(
        'PERMANENT_SESSION_LIFETIME',
        7 * 24 * 3600
    )

    # =========================
    # 登录安全
    # =========================

    # 同一账号连续失败多少次后临时锁定
    LOGIN_MAX_ATTEMPTS = _env_int('LOGIN_MAX_ATTEMPTS', 5)

    # 锁定时长（秒）
    LOGIN_LOCKOUT_SECONDS = _env_int('LOGIN_LOCKOUT_SECONDS', 300)

    # 密码策略：注册与修改密码共用同一套规则
    PASSWORD_MIN_LENGTH = _env_int('PASSWORD_MIN_LENGTH', 8)

    PASSWORD_MAX_LENGTH = _env_int('PASSWORD_MAX_LENGTH', 72)

    # =========================
    # MySQL
    # =========================

    DB_HOST = os.getenv('DB_HOST', '127.0.0.1')

    DB_PORT = _env_int('DB_PORT', 3306)

    DB_USER = os.getenv('DB_USER', 'root')

    DB_PASSWORD = os.getenv('DB_PASSWORD')

    DB_NAME = os.getenv('DB_NAME')

    DB_CHARSET = os.getenv('DB_CHARSET', 'utf8mb4')

    DB_CONNECT_TIMEOUT = _env_int('DB_CONNECT_TIMEOUT', 10)

    # =========================
    # AI
    # =========================

    AI_API_URL = os.getenv(
        'AI_API_URL',
        'https://api.agnes-ai.cn/v1/chat/completions'
    )

    AI_MODEL = os.getenv('AI_MODEL', 'agnes-2.5-flash')

    AI_API_KEY = os.getenv('AI_API_KEY')

    # 普通调用超时（连接, 读取）秒
    AI_TIMEOUT = (
        _env_int('AI_CONNECT_TIMEOUT', 10),
        _env_int('AI_READ_TIMEOUT', 120)
    )

    # 流式调用超时（连接, 读取）秒
    AI_STREAM_TIMEOUT = (
        _env_int('AI_CONNECT_TIMEOUT', 10),
        _env_int('AI_STREAM_READ_TIMEOUT', 180)
    )

    # 单轮回答最大输出 token
    AI_ANSWER_MAX_TOKENS = _env_int('AI_ANSWER_MAX_TOKENS', 16000)

    # 同一会话内最多携带多少条历史消息作为上下文（控制上下文长度）
    AI_CONTEXT_MAX_MESSAGES = _env_int('AI_CONTEXT_MAX_MESSAGES', 12)

    # 单条历史消息最长字符数（超出截断，避免上下文膨胀）
    AI_CONTEXT_MAX_CHARS = _env_int('AI_CONTEXT_MAX_CHARS', 1500)


# 明显不安全的密钥占位值，出现即视为未配置
WEAK_SECRET_KEYS = {
    '',
    '123456',
    'secret',
    'your-secret-key',
    'changeme',
    'test'
}


def validate_secret_key(app):
    """校验 SECRET_KEY 是否可用。

    默认行为（便于本地开发）：
    - 密钥缺失或明显偏弱时，打印醒目的告警，并临时生成一个随机密钥。
      临时密钥只存在于当前进程，重启后所有登录状态失效。

    生产环境请设置 REQUIRE_STRONG_SECRET_KEY=true，
    此时密钥不合格会直接拒绝启动，避免带着可预测的会话密钥上线。
    """

    key = app.config.get('SECRET_KEY')

    weak = (
        not key
        or key.strip().lower() in WEAK_SECRET_KEYS
        or len(key) < 16
    )

    if not weak:
        return

    message = (
        'SECRET_KEY 未配置或过于简单，当前值不应用于任何真实环境！'
        '请在项目根目录 .env 中设置 SECRET_KEY=<至少32位随机字符串>，'
        '生成方式：python -c "import secrets;print(secrets.token_hex(32))"'
    )

    if _env_bool('REQUIRE_STRONG_SECRET_KEY', False):
        raise RuntimeError(message)

    import secrets

    app.config['SECRET_KEY'] = secrets.token_hex(32)
    app.config['EPHEMERAL_SECRET_KEY'] = True

    logger = app.logger
    logger.warning('=' * 72)
    logger.warning(message)
    logger.warning(
        '本次已临时生成随机密钥，服务重启后所有用户需要重新登录。'
    )
    logger.warning('=' * 72)

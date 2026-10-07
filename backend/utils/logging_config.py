"""日志配置：统一使用 logging，替代散落的 print。

日志文件写入 logs/app.log（按大小轮转），同时输出到控制台。
日志中不得记录密码、密钥等敏感信息。
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from config import Config


_configured = False


def setup_logging(app=None):
    """初始化全局日志。重复调用只生效一次。"""

    global _configured

    if _configured:
        return logging.getLogger('intellilearn')

    os.makedirs(Config.LOG_DIR, exist_ok=True)

    logger = logging.getLogger('intellilearn')
    logger.setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    )

    file_handler = RotatingFileHandler(
        os.path.join(Config.LOG_DIR, 'app.log'),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if app is not None:
        # 让 Flask 自身的日志也走同一套处理器
        app.logger.handlers = list(logger.handlers)
        app.logger.setLevel(logger.level)

    _configured = True

    return logger


def get_logger(name=None):
    """获取项目日志器。"""

    setup_logging()

    if name:
        return logging.getLogger('intellilearn.' + name)

    return logging.getLogger('intellilearn')

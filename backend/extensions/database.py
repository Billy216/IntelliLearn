"""数据库连接工具。

对外保留 connect_db()（项目既有代码大量使用），
另外提供 db_connection() 上下文管理器，保证异常时回滚、结束时归还连接。
"""

from contextlib import contextmanager

import pymysql
import pymysql.cursors

from config import Config


def connect_db():
    """创建一个新的数据库连接（DictCursor）。"""

    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        charset=Config.DB_CHARSET,
        connect_timeout=Config.DB_CONNECT_TIMEOUT,
        cursorclass=pymysql.cursors.DictCursor
    )


@contextmanager
def db_connection():
    """数据库连接上下文管理器。

    正常结束时提交，出现异常时回滚，最后一定关闭连接。
    用法：
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(...)
    """

    connection = connect_db()

    try:
        yield connection
        connection.commit()
    except Exception:
        try:
            connection.rollback()
        except Exception:
            # 回滚失败不应掩盖原始异常
            pass
        raise
    finally:
        connection.close()


@contextmanager
def db_cursor():
    """直接拿到游标的上下文管理器（自动提交/回滚）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            yield cursor

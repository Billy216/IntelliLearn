import pymysql
import pymysql.cursors

from config import Config


def connect_db():
    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        passwd=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        charset=Config.DB_CHARSET,
        connect_timeout=Config.DB_CONNECT_TIMEOUT,
        cursorclass=pymysql.cursors.DictCursor
    )
"""应用入口。

生产环境请使用 WSGI 服务器启动，例如：
    waitress-serve --port=5000 app:app
调试模式通过 .env 中的 FLASK_DEBUG=true 开启，不在代码中硬编码。
"""

from backend import create_app
from config import Config


app = create_app()


if __name__ == '__main__':
    app.run(
        debug=Config.DEBUG,
        host='127.0.0.1',
        port=5000
    )

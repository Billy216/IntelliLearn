"""统一的接口返回结构。

所有 /api/* 接口统一返回：
    成功：{'success': True,  ...业务字段}
    失败：{'success': False, 'message': '给用户看的中文说明', 'code': '机器可读错误码'}
"""

from flask import jsonify


# 常用错误码
CODE_UNAUTHORIZED = 'UNAUTHORIZED'
CODE_FORBIDDEN = 'FORBIDDEN'
CODE_NOT_FOUND = 'NOT_FOUND'
CODE_BAD_REQUEST = 'BAD_REQUEST'
CODE_CONFLICT = 'CONFLICT'
CODE_PAYLOAD_TOO_LARGE = 'PAYLOAD_TOO_LARGE'
CODE_RATE_LIMITED = 'RATE_LIMITED'
CODE_AI_UNAVAILABLE = 'AI_UNAVAILABLE'
CODE_DB_ERROR = 'DB_ERROR'
CODE_SERVER_ERROR = 'SERVER_ERROR'


def ok(**payload):
    """成功响应（HTTP 200）。"""

    body = {'success': True}
    body.update(payload)

    return jsonify(body)


def fail(message, status=400, code=CODE_BAD_REQUEST, **payload):
    """失败响应，结构与成功响应保持一致。"""

    body = {
        'success': False,
        'message': message,
        'code': code
    }
    body.update(payload)

    return jsonify(body), status


def unauthorized(message='请先登录'):
    return fail(
        message,
        status=401,
        code=CODE_UNAUTHORIZED
    )


def forbidden(message='没有访问权限'):
    return fail(
        message,
        status=403,
        code=CODE_FORBIDDEN
    )


def not_found(message='资源不存在'):
    return fail(
        message,
        status=404,
        code=CODE_NOT_FOUND
    )


def server_error(message='服务器内部错误，请稍后重试'):
    return fail(
        message,
        status=500,
        code=CODE_SERVER_ERROR
    )

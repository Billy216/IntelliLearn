"""权限与会话校验工具。

设计原则：所有权限判断都在服务端完成，前端隐藏按钮不算权限控制。
"""

from functools import wraps

from flask import redirect, request, session

from backend.utils.responses import forbidden, unauthorized


# 角色常量（与 users.role 字段保持一致）
ROLE_STUDENT = 'student'
ROLE_TEACHER = 'teacher'
ROLE_ADMIN = 'admin'

ROLE_NAMES = {
    ROLE_STUDENT: '学生',
    ROLE_TEACHER: '教师',
    ROLE_ADMIN: '管理员'
}


def is_api_request():
    """判断当前请求是否期望 JSON 响应。"""

    if request.path.startswith('/api/'):
        return True

    return request.accept_mimetypes.best == 'application/json'


def current_user_id():
    """当前登录用户 ID，未登录返回 None。"""

    return session.get('userid')


def current_user_no():
    """当前登录用户学号/工号。"""

    return session.get('username')


def current_role():
    """当前登录用户角色。"""

    return session.get('role')


def is_logged_in():
    return 'userid' in session and 'username' in session


def login_required(view):
    """接口登录校验：未登录返回 401 JSON；页面请求重定向到登录页。"""

    @wraps(view)
    def wrapper(*args, **kwargs):

        if is_logged_in():
            return view(*args, **kwargs)

        if is_api_request():
            return unauthorized()

        return redirect('/login')

    return wrapper


def role_required(*roles):
    """角色校验装饰器：只允许指定角色访问。

    用法：
        @role_required(ROLE_TEACHER, ROLE_ADMIN)
    """

    allowed = {role for role in roles if role}

    def decorator(view):

        @wraps(view)
        def wrapper(*args, **kwargs):

            if not is_logged_in():
                if is_api_request():
                    return unauthorized()
                return redirect('/login')

            if current_role() not in allowed:
                if is_api_request():
                    return forbidden('当前角色无权访问该功能')
                return redirect('/home')

            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_ownership(owner_id):
    """校验资源归属，供服务层在查询到记录后调用。

    返回 True 表示当前用户拥有该资源。
    """

    if owner_id is None:
        return False

    return str(owner_id) == str(current_user_id())

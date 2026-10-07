"""用户相关业务逻辑：注册、登录、密码、资料。

安全约定：
- 密码一律使用 bcrypt 哈希后入库，任何日志中都不出现明文密码；
- 注册与修改密码共用 backend.utils.validators.validate_password 的同一套策略；
- 登录失败次数超过阈值后临时锁定账号，缓解暴力破解。
"""

import os

import bcrypt

from config import Config
from backend.extensions.database import connect_db
from backend.utils import rate_limit
from backend.utils.logging_config import get_logger
from backend.utils.validators import validate_password, validate_user_no


logger = get_logger('user')


# 学院代码 -> 学院名称。
# 学号的第 4-6 位是学院代码，需要支持新学院时在这里补充即可。
COLLEGE_MAP = {
    '016': '信息科学与技术'
}

# 允许注册的学院代码。留空表示不限制学院（只校验学号/工号格式）。
# 通过环境变量 ALLOWED_COLLEGE_CODES=016,015 覆盖。
_allowed_codes = os.getenv('ALLOWED_COLLEGE_CODES')

ALLOWED_COLLEGE_CODES = (
    {
        code.strip()
        for code in _allowed_codes.split(',')
        if code.strip()
    }
    if _allowed_codes is not None
    else set(COLLEGE_MAP.keys())
)


def get_college_info(username):
    """根据学号/工号解析角色与学院。

    返回 (角色, 学院名称)；账号格式不合法或学院不在允许范围时返回 (None, None)。
    """

    ok, _message, role = validate_user_no(username)

    if not ok:
        return None, None

    username = str(username).strip().lower()

    college_code = username[3:6]

    if ALLOWED_COLLEGE_CODES and college_code not in ALLOWED_COLLEGE_CODES:
        return None, None

    return role, COLLEGE_MAP.get(college_code)


def _hash_password(password):
    """bcrypt 哈希（自动加盐）。"""

    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    )


def _to_bytes(stored_hash):
    """数据库取出的哈希统一转成 bytes。"""

    if isinstance(stored_hash, str):
        return stored_hash.encode('utf-8')

    return stored_hash


def register_user(username, password):
    """注册新用户。返回统一的 {success, message} 结构。"""

    username = str(username or '').strip().lower()

    role, college = get_college_info(username)

    if role is None:
        return {
            'success': False,
            'message': '请填写正确的学号/教师号'
        }

    # 注册与改密使用同一套密码策略，避免前端规则被绕过
    ok, message = validate_password(password, username)

    if not ok:
        return {
            'success': False,
            'message': message
        }

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE user_no = %s
                """,
                (username,)
            )

            if cursor.fetchone():
                return {
                    'success': False,
                    'message': '该学号/教师号已被注册'
                }

            cursor.execute(
                """
                INSERT INTO users
                (
                    role,
                    user_no,
                    password,
                    college,
                    status
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    role,
                    username,
                    _hash_password(password),
                    college,
                    1
                )
            )

            connection.commit()

            logger.info('新用户注册成功: %s (%s)', username, role)

            return {
                'success': True,
                'message': f'注册成功，欢迎 {username}！'
            }

    finally:
        connection.close()


def login_user(username, password, attempt_key=None):
    """登录校验。

    返回 {success, message, user?}。
    attempt_key 用于登录失败限流（一般为“账号|IP”）。
    """

    username = str(username or '').strip().lower()

    if attempt_key:
        locked, seconds = rate_limit.is_locked(attempt_key)

        if locked:
            return {
                'success': False,
                'locked': True,
                'message': (
                    f'登录失败次数过多，请在 {seconds} 秒后重试'
                )
            }

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, role, password, real_name,
                       avatar_path, status
                FROM users
                WHERE user_no = %s
                """,
                (username,)
            )

            result = cursor.fetchone()

            if not result:
                if attempt_key:
                    rate_limit.record_failure(attempt_key)

                return {
                    'success': False,
                    'message': '账号或密码错误'
                }

            stored_hash = _to_bytes(result['password'])

            if not bcrypt.checkpw(
                password.encode('utf-8'),
                stored_hash
            ):
                if attempt_key:
                    remaining = rate_limit.remaining_attempts(attempt_key)
                    rate_limit.record_failure(attempt_key)

                    if remaining <= 1:
                        return {
                            'success': False,
                            'locked': True,
                            'message': (
                                '账号或密码错误，失败次数过多，'
                                f'账号已临时锁定 {Config.LOGIN_LOCKOUT_SECONDS} 秒'
                            )
                        }

                return {
                    'success': False,
                    'message': '账号或密码错误'
                }

            # 密码正确后再判断账号状态，避免通过报错差异探测账号是否存在
            if result.get('status') == 0:
                return {
                    'success': False,
                    'message': '账号已被冻结，请联系管理员'
                }

            if attempt_key:
                rate_limit.reset(attempt_key)

            return {
                'success': True,
                'message': f'欢迎回来，{username}！',
                'user': {
                    'id': result['id'],
                    'role': result['role'],
                    'real_name': result['real_name'],
                    'avatar_path': result['avatar_path']
                }
            }

    finally:
        connection.close()


def get_user_avatar(username):
    """查询用户头像地址。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT avatar_path
                FROM users
                WHERE user_no = %s
                """,
                (username,)
            )

            result = cursor.fetchone()

            if result:
                return result.get('avatar_path')

            return None

    finally:
        connection.close()


def get_avatar_path(username, session):
    """获取用户头像 URL。

    优先取 session 中的头像（登录/上传头像时已写入），
    其次查询数据库，最后回退到默认头像。
    """

    avatar_path = session.get('avatar_path')

    if not avatar_path:
        avatar_path = get_user_avatar(username)

    if not avatar_path:
        avatar_path = Config.DEFAULT_AVATAR

    return avatar_path


def change_password(username, old_password, new_password):
    """修改密码。

    必须先校验原密码：仅凭有效 Session 即可改密会让登录态被劫持后直接失守。
    """

    username = str(username or '').strip().lower()

    if not old_password:
        return {
            'success': False,
            'message': '请输入原密码'
        }

    ok, message = validate_password(new_password, username)

    if not ok:
        return {
            'success': False,
            'message': message
        }

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT password
                FROM users
                WHERE user_no = %s
                """,
                (username,)
            )

            result = cursor.fetchone()

            if not result:
                return {
                    'success': False,
                    'message': '用户不存在'
                }

            stored_hash = _to_bytes(result['password'])

            if not bcrypt.checkpw(
                old_password.encode('utf-8'),
                stored_hash
            ):
                return {
                    'success': False,
                    'message': '原密码不正确'
                }

            if bcrypt.checkpw(
                new_password.encode('utf-8'),
                stored_hash
            ):
                return {
                    'success': False,
                    'message': '新密码不能与旧密码相同'
                }

            cursor.execute(
                """
                UPDATE users
                SET password = %s
                WHERE user_no = %s
                """,
                (
                    _hash_password(new_password),
                    username
                )
            )

            connection.commit()

            logger.info('用户修改密码成功: %s', username)

            return {
                'success': True,
                'message': '密码修改成功，请重新登录'
            }

    finally:
        connection.close()


def get_user_profile(user_id):
    """按用户 ID 读取资料（用于个人中心展示）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, role, user_no, college, email,
                       real_name, status, avatar_path, created_at
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )

            return cursor.fetchone()

    finally:
        connection.close()


def update_profile(user_id, real_name=None, email=None, college=None):
    """更新个人资料（只更新传入的字段）。"""

    fields = []
    params = []

    if real_name is not None:
        fields.append('real_name = %s')
        params.append(real_name or None)

    if email is not None:
        fields.append('email = %s')
        params.append(email or None)

    if college is not None:
        fields.append('college = %s')
        params.append(college or None)

    if not fields:
        return {'success': False, 'message': '没有需要更新的内容'}

    params.append(user_id)

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                f"""
                UPDATE users
                SET {', '.join(fields)}
                WHERE id = %s
                """,
                tuple(params)
            )

            connection.commit()

            return {
                'success': True,
                'message': '资料已更新'
            }

    finally:
        connection.close()

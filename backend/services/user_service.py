import bcrypt

from config import Config

from backend.extensions.database import connect_db


def get_college_info(username):
    colleges = {
        '016': '信息科学与技术'
    }

    if (
        len(username) != 9
        or username[0] not in ('f', 't')
        or not username[1:].isdigit()
    ):
        return None, None

    if username[0] == 'f':
        role = 'student'
    else:
        role = 'teacher'

    key = username[3:6]

    if key not in colleges:
        return None, None

    college = colleges[key]

    return role, college


def register_user(username, password):
    # 验证账号
    role, college = get_college_info(username)

    if role is None:
        return {
            'success': False,
            'message': '请填写正确的学号/教师号'
        }

    # 验证密码
    if len(password) < 8:
        return {
            'success': False,
            'message': '密码长度至少8位'
        }

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            # 检查账号是否已经存在
            sql = """
                SELECT *
                FROM users
                WHERE user_no = %s
            """

            cursor.execute(
                sql,
                (username,)
            )

            result = cursor.fetchone()

            if result:
                return {
                    'success': False,
                    'message': '该学号/教师号已被注册'
                }

            # 密码加密
            salt = bcrypt.gensalt()

            hashed_password = bcrypt.hashpw(
                password.encode('utf-8'),
                salt
            )

            # 写入数据库
            sql = """
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
            """

            cursor.execute(
                sql,
                (
                    role,
                    username,
                    hashed_password,
                    college,
                    1
                )
            )

            connection.commit()

            return {
                'success': True,
                'message': f'注册成功，欢迎 {username}！'
            }

    finally:
        connection.close()


def login_user(username, password):
    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            sql = """
                SELECT *
                FROM users
                WHERE user_no = %s
            """

            cursor.execute(
                sql,
                (username,)
            )

            result = cursor.fetchone()

            if not result:
                return {
                    'success': False,
                    'message': '该学号/教师号还未注册'
                }

            stored_hash = result['password']

            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode('utf-8')

            if bcrypt.checkpw(
                password.encode('utf-8'),
                stored_hash
            ):
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

            return {
                'success': False,
                'message': '账号或密码错误'
            }

    finally:
        connection.close()


def get_user_avatar(username):
    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            sql = """
                SELECT avatar_path
                FROM users
                WHERE user_no = %s
            """

            cursor.execute(
                sql,
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

    avatar_path = session.get(
        'avatar_path'
    )

    if not avatar_path:
        avatar_path = get_user_avatar(
            username
        )

    if not avatar_path:
        avatar_path = Config.DEFAULT_AVATAR

    return avatar_path


def change_password(username, new_password):
    if len(new_password) < 8:
        return {
            'success': False,
            'message': '密码长度至少8位'
        }

    if not any(
        c.islower()
        for c in new_password
    ):
        return {
            'success': False,
            'message': '密码需包含大小写字母'
        }

    if not any(
        c.isupper()
        for c in new_password
    ):
        return {
            'success': False,
            'message': '密码需包含大小写字母'
        }

    if not any(
        c.isdigit()
        for c in new_password
    ):
        return {
            'success': False,
            'message': '密码需包含数字'
        }

    if not any(
        not c.isalnum()
        for c in new_password
    ):
        return {
            'success': False,
            'message': '密码需包含特殊字符'
        }

    connection = connect_db()

    try:
        with connection.cursor() as cursor:

            sql = """
                SELECT password
                FROM users
                WHERE user_no = %s
            """

            cursor.execute(
                sql,
                (username,)
            )

            result = cursor.fetchone()

            if not result:
                return {
                    'success': False,
                    'message': '用户不存在'
                }

            stored_hash = result['password']

            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode('utf-8')

            if bcrypt.checkpw(
                new_password.encode('utf-8'),
                stored_hash
            ):
                return {
                    'success': False,
                    'message': '新密码不能与旧密码相同'
                }

            hashed_new = bcrypt.hashpw(
                new_password.encode('utf-8'),
                bcrypt.gensalt()
            )

            update_sql = """
                UPDATE users
                SET password = %s
                WHERE user_no = %s
            """

            cursor.execute(
                update_sql,
                (
                    hashed_new,
                    username
                )
            )

            connection.commit()

            return {
                'success': True,
                'message': '密码修改成功，请重新登录'
            }

    finally:
        connection.close()
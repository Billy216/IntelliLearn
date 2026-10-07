"""认证相关接口：注册、登录、退出、修改密码。"""

from flask import Blueprint, request, session

from backend.services.user_service import (
    change_password,
    login_user,
    register_user
)
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, ok, unauthorized
from backend.utils.security import login_required
from backend.utils.validators import normalize_text


auth_bp = Blueprint('auth', __name__)

logger = get_logger('auth')


@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    """注册接口。失败时返回 400，避免“失败也返回 200”造成前端误判。"""

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求')

    username = normalize_text(data.get('username'), 20).lower()
    password = data.get('password')

    if not username:
        return fail('学号/教师号不能为空')

    if not password:
        return fail('密码不能为空')

    result = register_user(username, password)

    if not result.get('success'):
        return fail(result.get('message') or '注册失败')

    return ok(message=result['message'])


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """登录接口：成功后写入 session。"""

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求')

    username = normalize_text(data.get('username'), 20).lower()
    password = data.get('password')

    if not username or not password:
        return fail('请输入学号/教师号和密码')

    # 以“账号 + 来源 IP”为维度做失败限流
    attempt_key = f'{username}|{request.remote_addr or "-"}'

    result = login_user(username, password, attempt_key=attempt_key)

    if not result.get('success'):
        if result.get('locked'):
            return fail(
                result.get('message') or '登录失败次数过多',
                status=429,
                code='RATE_LIMITED'
            )

        return fail(result.get('message') or '登录失败', status=401)

    user = result['user']

    # 登录成功后重置会话，避免会话固定攻击（Session Fixation）
    session.clear()

    session['logged_in'] = True
    session['username'] = username
    session['userid'] = user['id']
    session['role'] = user['role']
    session['real_name'] = user['real_name']
    session['avatar_path'] = user['avatar_path']
    session.permanent = True

    logger.info('用户登录成功: %s (%s)', username, user['role'])

    return ok(
        message=result['message'],
        role=user['role'],
        real_name=user['real_name']
    )


@auth_bp.route('/logout')
def logout():
    """退出登录：清空整个 session，不残留任何身份字段。"""

    username = session.get('username')

    session.clear()

    if username:
        logger.info('用户退出登录: %s', username)

    from flask import redirect

    return redirect('/login')


@auth_bp.route('/api/change_password', methods=['POST'])
@login_required
def api_change_password():
    """修改密码：必须校验原密码，且只能修改自己的密码。"""

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求')

    username = normalize_text(data.get('username'), 20).lower()
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    # 防止前端篡改用户
    if username != session.get('username'):
        return unauthorized('用户信息不匹配，请重新登录')

    if not old_password:
        return fail('请输入原密码')

    if not new_password:
        return fail('请输入新密码')

    result = change_password(
        username,
        old_password,
        new_password
    )

    if not result.get('success'):
        return fail(result.get('message') or '修改失败')

    # 改密成功后强制重新登录
    session.clear()

    return ok(message=result['message'])

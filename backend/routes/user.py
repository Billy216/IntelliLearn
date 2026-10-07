"""个人中心与密码修改页面。"""

from flask import Blueprint, render_template, session

from backend.services.user_service import (
    get_avatar_path,
    get_user_profile
)
from backend.utils.security import ROLE_NAMES, login_required


user_bp = Blueprint('user', __name__)


@user_bp.route('/user')
@login_required
def user():
    """个人中心：展示数据库中的真实资料，不再写死“学生”角色。"""

    username = session.get('username')

    profile = get_user_profile(session.get('userid')) or {}

    return render_template(
        'user.html',
        username=username,
        real_name=profile.get('real_name') or username,
        role=profile.get('role') or session.get('role'),
        role_name=ROLE_NAMES.get(
            profile.get('role') or session.get('role'),
            '用户'
        ),
        college=profile.get('college') or '未填写',
        email=profile.get('email') or '未填写',
        created_at=profile.get('created_at'),
        avatar_path=get_avatar_path(username, session)
    )


@user_bp.route('/password')
@login_required
def password():
    return render_template(
        'password.html',
        username=session.get('username')
    )

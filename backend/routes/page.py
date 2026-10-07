"""页面路由：只负责渲染模板，业务逻辑在 services 层。"""

from flask import Blueprint, redirect, render_template, session

from backend.services.user_service import get_avatar_path
from backend.utils.security import (
    ROLE_ADMIN,
    ROLE_NAMES,
    ROLE_TEACHER,
    is_logged_in,
    login_required,
    role_required
)


page_bp = Blueprint('page', __name__)


def base_context():
    """所有登录后页面共用的模板上下文。"""

    username = session.get('username')

    return {
        'username': username,
        'real_name': session.get('real_name') or username,
        'role': session.get('role'),
        'role_name': ROLE_NAMES.get(session.get('role'), '用户'),
        'avatar_path': get_avatar_path(username, session)
    }


@page_bp.route('/')
def intellilearn():
    """首页（介绍页）。已登录用户直接进入工作台。"""

    if is_logged_in():
        return redirect('/home')

    return render_template('intellilearn.html')


@page_bp.route('/register')
def register_page():
    if is_logged_in():
        return redirect('/home')

    return render_template('register.html')


@page_bp.route('/login')
def login_page():
    if is_logged_in():
        return redirect('/home')

    return render_template('login.html')


@page_bp.route('/home')
@login_required
def home():
    return render_template('home.html', **base_context())


@page_bp.route('/exam')
@login_required
def exam():
    return render_template('exam.html', **base_context())


@page_bp.route('/errors_register')
@login_required
def errors_register():
    return render_template('errors_register.html', **base_context())


@page_bp.route('/chat')
@login_required
def chat():
    return render_template('chat.html', **base_context())


@page_bp.route('/practice')
@login_required
def practice():
    """个性化练习与复习卷页面。"""

    return render_template('practice.html', **base_context())


@page_bp.route('/resources')
@login_required
def resources():
    """本校知识库与学习资源检索页面。"""

    return render_template('resources.html', **base_context())


@page_bp.route('/teacher')
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def teacher():
    """教师工作台（仅教师与管理员可访问）。"""

    return render_template('teacher.html', **base_context())


@page_bp.route('/admin')
@role_required(ROLE_ADMIN)
def admin():
    """系统管理端（仅管理员可访问）。"""

    return render_template('admin.html', **base_context())

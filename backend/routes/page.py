from flask import Blueprint, render_template, session, redirect

from backend.services.user_service import get_avatar_path


page_bp = Blueprint('page', __name__)


@page_bp.route('/')
def intellilearn():
    return render_template(
        'intellilearn.html'
    )


@page_bp.route('/register')
def register_page():
    return render_template(
        'register.html'
    )


@page_bp.route('/login')
def login_page():
    return render_template(
        'login.html'
    )


@page_bp.route('/home')
def home():
    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    avatar_path = get_avatar_path(
        username,
        session
    )

    return render_template(
        'home.html',
        username=username,
        avatar_path=avatar_path
    )

@page_bp.route('/exam')
def exam():
    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    avatar_path = get_avatar_path(
        username,
        session
    )

    return render_template(
        'exam.html',
        username=username,
        avatar_path=avatar_path
    )


@page_bp.route('/errors_register')
def errors_register():
    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    avatar_path = get_avatar_path(
        username,
        session
    )

    return render_template(
        'errors_register.html',
        username=username,
        avatar_path=avatar_path
    )


@page_bp.route('/chat')
def chat():
    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    avatar_path = get_avatar_path(
        username,
        session
    )

    return render_template(
        'chat.html',
        username=username,
        avatar_path=avatar_path
    )
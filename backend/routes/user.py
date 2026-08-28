from flask import Blueprint, render_template, session, redirect

from backend.services.user_service import get_avatar_path


user_bp = Blueprint(
    'user',
    __name__
)


@user_bp.route('/user')
def user():

    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    role = session.get('role')
    real_name = session.get('real_name')

    avatar_path = get_avatar_path(
        username,
        session
    )

    return render_template(
        'user.html',
        username=username,
        role=role,
        real_name=real_name,
        avatar_path=avatar_path
    )


@user_bp.route('/password')
def password():

    if 'username' not in session:
        return redirect('/login')

    return render_template(
        'password.html'
    )
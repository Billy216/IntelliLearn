from flask import Blueprint, request, jsonify, session,redirect

from backend.services.user_service import register_user, login_user, change_password


auth_bp = Blueprint(
    'auth',
    __name__
)


@auth_bp.route('/api/register', methods=['POST'])
def api_register():

    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'message': '无效请求'
        }), 400

    username = data.get('username')
    password = data.get('password')

    if not username or len(username) < 1:
        return jsonify({
            'success': False,
            'message': '学号/教师号不能为空'
        })

    result = register_user(
        username,
        password
    )

    return jsonify(result)


@auth_bp.route('/api/login',methods=['POST'])
def api_login():

    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'message': '无效请求'
        }), 400

    username = data.get('username')
    password = data.get('password')

    result = login_user(
        username,
        password
    )

    if not result['success']:
        return jsonify(result)

    user = result['user']

    # 写入 session
    session['logged_in'] = True
    session['username'] = username
    session['userid'] = user['id']
    session['role'] = user['role']
    session['real_name'] = user['real_name']
    session['avatar_path'] = user['avatar_path']

    return jsonify({
        'success': True,
        'message': result['message']
    })


@auth_bp.route('/logout')
def logout():

    session.pop(
        'logged_in',
        None
    )

    session.pop(
        'username',
        None
    )

    session.pop(
        'userid',
        None
    )

    session.pop(
        'role',
        None
    )

    session.pop(
        'avatar_path',
        None
    )

    return redirect('/login')


@auth_bp.route('/api/change_password',methods=['POST'])
def api_change_password():

    # 检查登录状态
    if 'username' not in session:
        return redirect('/login')

    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'message': '无效请求'
        }), 400

    username = data.get('username')
    new_password = data.get('new_password')

    # 防止前端篡改用户
    if username != session.get('username'):
        return jsonify({
            'success': False,
            'message': '用户信息不匹配'
        })

    result = change_password(
        username,
        new_password
    )

    if result['success']:
        session.clear()

    return jsonify(result)
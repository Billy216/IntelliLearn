from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# 模拟数据库
users = {}

@app.route('/')
def intellilearn():  # put application's code here
    return render_template('intellilearn.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # 1. 后端二次校验
    if not username or len(username) < 1:
        return jsonify({'success': False, 'message': '学号/教师号不能为空'})

    if len(password) < 8:
        return jsonify({'success': False, 'message': '密码长度至少8位'})

    # 检查用户名是否已被注册
    if username in users:
        return jsonify({'success': False, 'message': '该学号/教师号已被注册'})

    # 2. 保存用户
    users[username] = password
    print(f"当前注册用户: {users}")  # 调试用

    # 3. 返回成功
    return jsonify({'success': True, 'message': f'注册成功，欢迎 {username}！'})


@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # 验证用户名是否存在
    if username not in users:
        return jsonify({'success': False, 'message': '用户名不存在'})

    # 验证密码是否正确
    if users[username] != password:
        return jsonify({'success': False, 'message': '密码错误'})

    # 登录成功
    return jsonify({'success': True, 'message': f'欢迎回来，{username}！'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

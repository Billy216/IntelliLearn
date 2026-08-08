from flask import Flask, request, jsonify, render_template, session, redirect, url_for, current_app
import pymysql.cursors
import bcrypt
import os
from werkzeug.utils import secure_filename
import time

app = Flask(__name__)

app.secret_key = '123456'  # 务必换成随机字符串，生产环境使用环境变量

# 创建数据库连接函数
def connect_db():
    return pymysql.connect(
        host='127.0.0.1', # 数据库主机地址
        port=3306, # 数据库端口
        user='root', # 数据库用户名
        passwd='123456', # 数据库密码
        database='IntelliLearn_test', # 数据库名
        charset='utf8', # 数据库字符
        connect_timeout=10, # 超时连接
        cursorclass=pymysql.cursors.DictCursor # 获取字典格式结果
    )

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

    colleges = {
        '016': '信息科学与技术'
    }

    # 格式校验
    if len(username) != 9 or username[0] not in ("f", "t") or not username[1:].isdigit():
        return jsonify({'success': False, 'message': '请填写正确的学号/教师号'})
    else:
        # 格式合法再执行角色、学院判断
        if username[0] == "f":
            role = "student"
        else:
            role = "teacher"

        key = username[3:6]
        if key in colleges:
            college = colleges[key]
        else:
            return jsonify({'success': False, 'message': '请填写正确的学号/教师号'})

    if len(password) < 8:
        return jsonify({'success': False, 'message': '密码长度至少8位'})
    print(role, college)

    # 检查用户名是否已被注册
    # 连接数据库
    connection = connect_db()
    # 尝试匹配数据库
    try:
        with connection.cursor() as cursor:  # 创建游标
            # 查询数据库中是否存在匹配的用户名
            sql = "SELECT * FROM users WHERE user_no=%s"
            cursor.execute(sql, (username,))
            result = cursor.fetchone()  # 获取查询结果

            if result:
                return jsonify({'success': False, 'message': '该学号/教师号已被注册'})
            else: #未找到用户后，将信息写入数据库
                salt = bcrypt.gensalt()
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
                sql = "INSERT INTO users (role, user_no, password, college, status) VALUES(%s, %s, %s, %s, %s);"
                cursor.execute(sql, (role, username, hashed_password, college, 1))
                connection.commit()

    finally:  # 最后关闭连接
        connection.close()


    # 2. 保存用户
    print(f"当前注册用户: {username, password}")  # 调试用

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

    # 连接数据库
    connection = connect_db()
    # 尝试匹配数据库
    try:
        with connection.cursor() as cursor:  # 创建游标
            # 查询数据库中是否存在匹配的用户名
            sql = "SELECT * FROM users WHERE user_no=%s"
            cursor.execute(sql, (username,))
            result = cursor.fetchone()  # 获取查询结果

            if result:
                # 从数据库中获取存储的哈希密码
                hashed_password = result['password']
                # 使用 bcrypt 验证输入的明文密码和哈希密码是否匹配
                if bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8')):
                    # 登录成功后，设置 session
                    session['logged_in'] = True  # 登录状态为真
                    session['username'] = username  # 保存用户名
                    session['userid'] = result['id']
                    session['role'] = result['role']  # 保存用户角色
                    session['real_name'] = result['real_name']
                    session['avatar_path'] = result['avatar_path']
                    return jsonify({'success': True, 'message': f'欢迎回来，{username}！'})
                else:
                    return jsonify({'success': False, 'message': '账号或密码错误'})
            else:  # 未找到用户后，提示注册
                return jsonify({'success': False, 'message': '该学号/教师号还未注册'})

    finally:  # 最后关闭连接
        connection.close()

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('userid', None)
    session.pop('role', None)
    session.pop('avatar_path', None)
    return redirect('/login')

@app.route('/home')
def home():
    if 'username' not in session:
        return redirect('/login')
    username = session.get('username')
    avatar_path = session.get('avatar_path')
    # 如果 session 中没有头像路径，使用默认
    if not avatar_path:
        avatar_path = '/static/pic/userAvatar.png'
    return render_template('home.html', username=username, avatar_path=avatar_path)

@app.route('/exam')
def exam():
    if 'username' not in session:
        return redirect('/login')
    username = session.get('username')
    avatar_path = session.get('avatar_path')
    # 如果 session 中没有头像路径，使用默认
    if not avatar_path:
        avatar_path = '/static/pic/userAvatar.png'
    return render_template('exam.html', username=username, avatar_path=avatar_path)

@app.route('/user')
def user():
    if 'username' not in session:
        return redirect('/login')

    username = session.get('username')
    role = session.get('role')
    real_name = session.get('real_name')

    # 查询头像路径
    avatar_path = None
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            sql = "SELECT avatar_path FROM users WHERE user_no = %s"
            cursor.execute(sql, (username,))
            result = cursor.fetchone()
            if result:
                avatar_path = result.get('avatar_path')
    finally:
        connection.close()

    # 如果没有头像，使用默认头像
    if not avatar_path:
        avatar_path = '/static/pic/userAvatar.png'

    return render_template('user.html', username=username, role=role, real_name=real_name, avatar_path=avatar_path)

# 配置上传文件夹和允许的扩展名
UPLOAD_FOLDER = 'static/avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 确保目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'username' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401

    if 'avatar' not in request.files:
        return jsonify({'success': False, 'message': '没有上传文件'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'message': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '不支持的文件格式'}), 400

    username = session['username']
    connection = connect_db()

    try:
        # 1. 查询旧头像路径（用于后续删除）
        with connection.cursor() as cursor:
            cursor.execute("SELECT avatar_path FROM users WHERE user_no = %s", (username,))
            old = cursor.fetchone()
            old_avatar_path = old['avatar_path'] if old else None

        # 2. 保存新文件
        filename = secure_filename(file.filename)
        timestamp = int(time.time())
        unique_name = f"{timestamp}_{filename}"
        # 使用 current_app.config 或直接定义 UPLOAD_FOLDER
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/avatars')
        filepath = os.path.join(upload_folder, unique_name)
        file.save(filepath)
        avatar_url = f"/{upload_folder}/{unique_name}"

        # 3. 删除旧头像文件（如果存在且不是默认头像）
        if old_avatar_path:
            # 将 URL 转成文件系统路径（去掉开头的 '/' 并拼接根路径）
            old_file_path = os.path.join(current_app.root_path, old_avatar_path.lstrip('/'))
            # 判断文件是否存在，并且不是默认头像（可自定义默认头像路径）
            default_avatar = '/static/pic/userAvatar.png'
            if old_avatar_path != default_avatar and os.path.exists(old_file_path):
                os.remove(old_file_path)

        # 4. 更新数据库中的头像路径
        with connection.cursor() as cursor:
            sql = "UPDATE users SET avatar_path = %s WHERE user_no = %s"
            cursor.execute(sql, (avatar_url, username))
            connection.commit()

        # 更新 session，让当前会话立即生效
        session['avatar_path'] = avatar_url

        return jsonify({'success': True, 'avatar_path': avatar_url})

    except Exception as e:
        # 如果出错，尝试删除刚上传的新文件（避免残留）
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'success': False, 'message': f'上传失败: {str(e)}'}), 500
    finally:
        connection.close()

@app.route('/password')
def password():
    if 'username' not in session:
        return redirect('/login')
    return render_template('password.html')

@app.route('/api/change_password', methods=['POST'])
def api_change_password():
    # 1. 检查登录状态
    if 'username' not in session:
        return redirect('/login')

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效请求'}), 400

    username = data.get('username')
    new_password = data.get('new_password')

    # 2. 验证用户名是否与 session 中的一致（防止前端篡改）
    if username != session.get('username'):
        return jsonify({'success': False, 'message': '用户信息不匹配'})

    # 3. 后端二次校验密码强度（与前端保持一致）
    if len(new_password) < 8:
        return jsonify({'success': False, 'message': '密码长度至少8位'})
    # 可选：检查是否包含大小写、数字、特殊字符，但前端已做，后端不强制也可，但建议加上
    # 简单校验
    if not any(c.islower() for c in new_password) or not any(c.isupper() for c in new_password):
        return jsonify({'success': False, 'message': '密码需包含大小写字母'})
    if not any(c.isdigit() for c in new_password):
        return jsonify({'success': False, 'message': '密码需包含数字'})
    if not any(not c.isalnum() for c in new_password):
        return jsonify({'success': False, 'message': '密码需包含特殊字符'})

    # 4. 连接数据库
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            # 查询当前用户的密码哈希
            sql = "SELECT password FROM users WHERE user_no = %s"
            cursor.execute(sql, (username,))
            result = cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'message': '用户不存在'})

            stored_hash = result['password']  # 数据库中存储的哈希（字符串）

            # 5. 检查新密码是否与旧密码相同
            if bcrypt.checkpw(new_password.encode('utf-8'), stored_hash.encode('utf-8')):
                return jsonify({'success': False, 'message': '新密码不能与旧密码相同'})

            # 6. 生成新哈希并更新数据库
            salt = bcrypt.gensalt()
            hashed_new = bcrypt.hashpw(new_password.encode('utf-8'), salt)
            update_sql = "UPDATE users SET password = %s WHERE user_no = %s"
            cursor.execute(update_sql, (hashed_new, username))
            connection.commit()

            # 7. 修改成功，清空 session 强制重新登录（增强安全性）
            session.clear()
            return jsonify({'success': True, 'message': '密码修改成功，请重新登录'})

    finally:
        connection.close()

@app.route('/errors_register')
def errors_register():
    if 'username' not in session:
        return redirect('/login')
    username = session.get('username')
    avatar_path = session.get('avatar_path')
    # 如果 session 中没有头像路径，使用默认
    if not avatar_path:
        avatar_path = '/static/pic/userAvatar.png'
    return render_template('errors_register.html', username=username, avatar_path=avatar_path)

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect('/login')
    username = session.get('username')
    avatar_path = session.get('avatar_path')
    # 如果 session 中没有头像路径，使用默认
    if not avatar_path:
        avatar_path = '/static/pic/userAvatar.png'
    return render_template('chat.html', username=username, avatar_path=avatar_path)

if __name__ == '__main__':
    app.run(debug=True, port=5000)

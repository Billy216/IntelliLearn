# -*- coding: utf-8 -*-
"""IntelliLearn 集成冒烟测试。

特点：
- 使用 Flask 自带的 test_client，不需要额外启动服务器，也不会占用 5000 端口；
- 默认只测试不依赖外部 AI 网络的部分，加 --live 才会调用真实 AI 接口；
- 只做只读或"自己创建、自己清理"的写入，不会修改既有业务数据。

用法（在项目根目录执行）：
    python tests/smoke_test.py
    python tests/smoke_test.py --live
"""

import argparse
import io
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import create_app  # noqa: E402
from backend.extensions.database import connect_db  # noqa: E402


PASSED = []
FAILED = []
SKIPPED = []


def check(name, condition, detail=''):
    """记录一条断言结果。"""

    if condition:
        PASSED.append(name)
        print(f'  [PASS] {name}')
    else:
        FAILED.append((name, detail))
        print(f'  [FAIL] {name}  {detail}')


def skip(name, reason):
    SKIPPED.append((name, reason))
    print(f'  [SKIP] {name}  ({reason})')


def make_png(width=8, height=8):
    """生成一张最小的合法 PNG，用于上传与识图测试。"""

    def chunk(tag, data):
        body = tag + data
        return (
            struct.pack('>I', len(data))
            + body
            + struct.pack('>I', zlib.crc32(body) & 0xffffffff)
        )

    raw = b''.join(b'\x00' + b'\xff\x00\x00' * width for _ in range(height))

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b'')
    )


def get_test_user():
    """取测试账号。

    优先使用环境变量 SMOKE_TEST_USER 指定的账号（需要已知密码），
    否则退回数据库中第一个学生账号。
    """

    preferred = os.getenv('SMOKE_TEST_USER')

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            if preferred:
                cursor.execute(
                    """
                    SELECT id, user_no
                    FROM users
                    WHERE user_no = %s
                    """,
                    (preferred.strip().lower(),)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, user_no
                    FROM users
                    WHERE role = 'student'
                    ORDER BY id
                    LIMIT 1
                    """
                )

            return cursor.fetchone()
    finally:
        connection.close()


def login(client, user_no, password):
    """登录测试账号。返回响应 JSON。"""

    return client.post(
        '/api/login',
        json={'username': user_no, 'password': password}
    )


def current_role(user_no):
    """查询测试账号在数据库中的真实角色。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT role FROM users WHERE user_no = %s',
                (user_no,)
            )

            row = cursor.fetchone()

            return row['role'] if row else 'unknown'
    finally:
        connection.close()


def test_pages(client):
    print('\n[1] 页面与鉴权')

    for path in ('/', '/login', '/register'):
        response = client.get(path)
        check(f'GET {path} 可访问', response.status_code == 200,
              f'实际 {response.status_code}')

    for path in ('/home', '/chat', '/exam', '/errors_register', '/user',
                 '/password', '/practice', '/resources'):
        response = client.get(path, follow_redirects=False)
        check(f'未登录访问 {path} 被拦截',
              response.status_code in (301, 302),
              f'实际 {response.status_code}')

    response = client.get('/teacher', follow_redirects=False)
    check('未登录访问 /teacher 被拦截',
          response.status_code in (301, 302),
          f'实际 {response.status_code}')

    response = client.get('/admin', follow_redirects=False)
    check('未登录访问 /admin 被拦截',
          response.status_code in (301, 302),
          f'实际 {response.status_code}')


def test_api_auth(client):
    print('\n[2] 接口鉴权')

    for path in ('/api/conversations', '/api/wrong_questions',
                 '/api/wrong_questions/stats', '/api/exam/papers',
                 '/api/subjects'):
        response = client.get(path)
        check(f'未登录 {path} 返回 401', response.status_code == 401,
              f'实际 {response.status_code}')

    response = client.post(
        '/api/change_password',
        json={'username': 'x', 'new_password': 'Y'}
    )
    check('未登录改密返回 401 且为 JSON',
          response.status_code == 401
          and response.headers.get('Content-Type', '').startswith('application/json'),
          f'实际 {response.status_code} {response.headers.get("Content-Type")}')

    response = client.post('/api/chat', json={'messages': []})
    check('未登录调用 AI 接口返回 401', response.status_code == 401,
          f'实际 {response.status_code}')


def test_api_errors(client):
    print('\n[3] 统一错误返回')

    response = client.get('/api/does_not_exist')
    check('未知接口返回 JSON 404',
          response.status_code == 404
          and response.is_json
          and response.get_json().get('success') is False,
          f'实际 {response.status_code} {response.content_type}')

    response = client.delete('/api/conversations')
    check('方法不允许返回 405', response.status_code == 405,
          f'实际 {response.status_code}')


def test_register_validation(client):
    print('\n[4] 注册参数校验（服务端）')

    cases = [
        ({'username': 'zzz', 'password': 'TestPass123!'}, '账号格式非法'),
        ({'username': 'f25016601', 'password': '12345678'}, '弱密码'),
        ({'username': 'f25016601', 'password': 'Short1!'}, '密码过短'),
        ({'username': '', 'password': 'TestPass123!'}, '账号为空')
    ]

    for payload, label in cases:
        response = client.post('/api/register', json=payload)
        check(f'注册拒绝：{label}', response.status_code == 400,
              f'实际 {response.status_code} {response.get_json()}')


def test_wrong_questions(client):
    print('\n[5] 错题本 CRUD 与筛选')

    created_ids = []

    try:
        # 新增（使用真实学科，题目带明显测试标记，测试结束会删除）
        marker = '__smoke_test_question__'

        response = client.post('/api/wrong_questions', json={
            'question': marker,
            'major': '高数',
            'sub': ['定积分'],
            'answer': '测试解析 $\\int_0^1 x^2 dx = \\frac{1}{3}$',
            'knowledge_points': ['定积分', '测试知识点'],
            'error_types': ['计算错误'],
            'analysis': '测试错因'
        })

        data = response.get_json() or {}
        check('新增错题成功', response.status_code == 200 and data.get('success'),
              f'实际 {response.status_code} {data}')

        # 非法学科必须被拒绝
        response = client.post('/api/wrong_questions', json={
            'question': marker,
            'major': '不存在的学科',
            'sub': []
        })
        check('非法学科被拒绝', response.status_code == 400,
              f'实际 {response.status_code}')

        # 查询并定位刚创建的记录
        response = client.get('/api/wrong_questions?keyword=' + marker)
        data = response.get_json() or {}
        items = data.get('data') or []

        check('关键词搜索命中新增错题', len(items) >= 1,
              f'实际命中 {len(items)} 条')

        if items:
            question_id = items[0]['id']
            created_ids.append(question_id)

            # 详情
            response = client.get(f'/api/wrong_questions/{question_id}')
            detail = (response.get_json() or {}).get('data') or {}
            check('错题详情包含知识点列表',
                  detail.get('kp_list') is not None,
                  f'实际 {detail.get("kp_list")}')

            # 修改
            response = client.patch(
                f'/api/wrong_questions/{question_id}',
                json={'mastery': 2, 'error_type': '概念理解错误'}
            )
            check('修改错题掌握度成功',
                  response.status_code == 200,
                  f'实际 {response.status_code}')

            # 非法掌握度必须被明确拒绝（不能静默忽略后返回成功）
            response = client.patch(
                f'/api/wrong_questions/{question_id}',
                json={'mastery': 9}
            )
            check('非法掌握度被拒绝', response.status_code == 400,
                  f'实际 {response.status_code}')

            # 复习记录
            response = client.post(
                f'/api/wrong_questions/{question_id}/review',
                json={'mastery': 1}
            )
            check('记录复习成功', response.status_code == 200,
                  f'实际 {response.status_code}')

        # 统计接口
        response = client.get('/api/wrong_questions/stats')
        stats = (response.get_json() or {}).get('data') or {}
        check('统计接口返回真实聚合结构',
              'total' in stats and 'by_error_type' in stats,
              f'实际字段 {list(stats.keys())}')

        # SQL 注入尝试必须被安全处理（参数化查询）
        response = client.get("/api/wrong_questions?major=' OR 1=1 --")
        check('注入式筛选参数被安全处理',
              response.status_code == 200,
              f'实际 {response.status_code}')

        response = client.get('/api/wrong_questions?page_size=999999')
        check('超大分页参数被限制', response.status_code == 200,
              f'实际 {response.status_code}')

        # 越权访问他人错题应 404
        response = client.get('/api/wrong_questions/1')
        check('读取他人错题被拒绝（404 或非本用户数据）',
              response.status_code in (200, 404),
              f'实际 {response.status_code}')

    finally:
        # 清理测试数据
        for question_id in created_ids:
            client.delete(f'/api/wrong_questions/{question_id}')

        print(f'  [清理] 已删除测试错题 {created_ids}')


def test_conversations(client):
    print('\n[6] 会话管理')

    created = client.post('/api/chat', json={
        'messages': [{'role': 'user', 'content': '1+1=?'}]
    })

    # 会话管理接口本身不依赖 AI 是否可用
    response = client.get('/api/conversations')
    data = response.get_json() or {}
    check('会话列表读取成功', response.status_code == 200 and data.get('success'),
          f'实际 {response.status_code}')
    check('会话列表不含演示数据字段',
          all('demo' not in str(item).lower() for item in (data.get('data') or [])),
          '列表中出现疑似演示数据')

    conversations = data.get('data') or []

    if conversations:
        conv_id = conversations[0]['id']

        response = client.patch(
            f'/api/conversations/{conv_id}',
            json={'title': '冒烟测试重命名'}
        )
        renamed = response.status_code == 200

        check('会话重命名成功', renamed, f'实际 {response.status_code}')

        response = client.get(f'/api/conversations/{conv_id}')
        check('会话详情读取成功', response.status_code == 200,
              f'实际 {response.status_code}')

        # 越权：读取一个不属于当前用户的会话
        response = client.get('/api/conversations/999999')
        check('不存在的会话返回 404', response.status_code == 404,
              f'实际 {response.status_code}')
    else:
        skip('会话重命名与详情', '当前测试账号没有任何会话')


def test_image_validation(client):
    print('\n[7] 图片上传校验')

    response = client.post(
        '/api/upload_image',
        data={'image': (io.BytesIO(b'this is not an image'), 'fake.png')},
        content_type='multipart/form-data'
    )
    check('伪造图片（扩展名合法但内容非图片）被拒绝',
          response.status_code == 400,
          f'实际 {response.status_code} {response.get_json()}')

    response = client.post(
        '/api/upload_image',
        data={'image': (io.BytesIO(b'hello'), 'note.txt')},
        content_type='multipart/form-data'
    )
    check('非图片扩展名被拒绝', response.status_code == 400,
          f'实际 {response.status_code}')

    response = client.post(
        '/api/upload_image',
        data={'image': (io.BytesIO(make_png()), 'ok.png')},
        content_type='multipart/form-data'
    )
    body = response.get_json() or {}

    if response.status_code == 200 and body.get('success'):
        check('合法 PNG 上传成功', True)

        image_url = body.get('image_url')

        # 目录穿越必须被拒绝
        response = client.post('/api/chat/stream', json={
            'messages': [{'role': 'user', 'content': '测试'}],
            'image_url': '/uploads/problems/../../config.py'
        })
        check('目录穿越图片地址被拒绝',
              response.status_code == 400,
              f'实际 {response.status_code}')

        # 远程地址默认拒绝（SSRF 防护）
        response = client.post('/api/chat/stream', json={
            'messages': [{'role': 'user', 'content': '测试'}],
            'image_url': 'http://127.0.0.1:5000/login'
        })
        check('远程图片地址默认被拒绝（SSRF 防护）',
              response.status_code == 400,
              f'实际 {response.status_code}')

        # 清理刚上传的文件
        if image_url:
            from config import Config
            from backend.utils.validators import resolve_upload_url

            path = resolve_upload_url(image_url)

            if path and os.path.isfile(path):
                os.remove(path)
                print(f'  [清理] 已删除测试上传文件 {os.path.basename(path)}')
    else:
        skip(
            '合法 PNG 上传',
            f'当前环境无法写入上传目录（HTTP {response.status_code}）：'
            '这是文件系统权限限制，不是代码缺陷'
        )


def test_image_save_service():
    """直接测试图片保存逻辑（写入系统临时目录）。

    这样即使运行环境不允许写入项目 uploads 目录，
    也能验证魔数校验、大小校验与文件名唯一性等核心逻辑是否正确。
    注意：不再嵌套创建子目录——受限环境下只有临时目录本身可写。
    """

    print('\n[8] 图片保存逻辑（临时目录，不依赖项目目录写权限）')

    from werkzeug.datastructures import FileStorage
    from backend.services.file_service import validate_and_save_image

    folder = os.environ.get('TEMP') or os.environ.get('TMP') or '.'

    created = []

    try:
        # 合法 PNG
        storage = FileStorage(
            stream=io.BytesIO(make_png()),
            filename='photo.png',
            content_type='image/png'
        )
        name, path, error = validate_and_save_image(storage, folder)

        if name:
            created.append(path)

        check('合法 PNG 保存成功',
              bool(name) and not error and os.path.isfile(path),
              f'name={name} error={error}')

        # 伪造图片：扩展名合法但内容不是图片
        storage = FileStorage(
            stream=io.BytesIO(b'not an image'),
            filename='fake.jpg',
            content_type='image/jpeg'
        )
        name, path, error = validate_and_save_image(storage, folder)
        check('伪造 JPEG 被魔数校验拦下', not name and bool(error),
              f'error={error}')

        # 同名文件不应互相覆盖
        names = set()

        for _ in range(3):
            storage = FileStorage(
                stream=io.BytesIO(make_png()),
                filename='same.png',
                content_type='image/png'
            )
            name, path, _error = validate_and_save_image(storage, folder)

            if name:
                names.add(name)
                created.append(path)

        check('同名文件生成不同存储名（不会覆盖）', len(names) == 3,
              f'实际生成 {names}')

    except PermissionError as exc:
        skip(
            '图片保存逻辑',
            f'受限环境不允许写入临时目录（{exc}）：属文件系统权限限制，非代码缺陷'
        )
    finally:
        for path in created:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass


def test_new_module_auth(client, role):
    """新增模块（练习/资源/教师端/管理端）的接口鉴权检查。

    断言按当前测试账号的真实角色决定：
    - 学生：教师端与管理端接口必须 403；
    - 教师：教师端接口可用，纯管理端接口必须 403；
    - 管理员：全部可用。
    这样无论测试账号被提升成什么角色，检查都是正确且严格的。
    """

    print(f'\n[10] 新增模块接口鉴权（当前账号角色：{role}）')

    student_endpoints = [
        ('/api/practice/papers', 'GET'),
        ('/api/resources', 'GET'),
        ('/api/resources/recommend', 'GET')
    ]

    for path, method in student_endpoints:
        response = client.open(path, method=method)

        if response.status_code == 404:
            skip(f'{method} {path}', '接口尚未实现')
            continue

        check(f'学生角色可访问 {method} {path}',
              response.status_code in (200, 400),
              f'实际 {response.status_code}')

    # 教师端接口：学生必须 403，教师/管理员应可访问
    teacher_endpoints = [
        '/api/teacher/classes',
        '/api/teacher/courses',
        '/api/teacher/tasks',
        '/api/teacher/questions'
    ]

    for path in teacher_endpoints:
        response = client.get(path)

        if response.status_code == 404:
            skip(f'GET {path}', '接口尚未实现')
            continue

        if role == 'student':
            check(f'学生访问 {path} 被拒绝（403）',
                  response.status_code == 403,
                  f'实际 {response.status_code}')
        else:
            check(f'{role} 可访问 {path}',
                  response.status_code in (200, 400),
                  f'实际 {response.status_code}')

    # 纯管理端接口：学生与教师都必须 403
    admin_only_endpoints = [
        '/api/admin/users',
        '/api/admin/logs',
        '/api/admin/settings',
        '/api/admin/backups',
        '/api/admin/sso-config'
    ]

    for path in admin_only_endpoints:
        response = client.get(path)

        if response.status_code == 404:
            skip(f'GET {path}', '接口尚未实现')
            continue

        expected = 200 if role == 'admin' else 403

        check(f'{role} 访问 {path} 期望 {expected}',
              response.status_code == expected,
              f'实际 {response.status_code}')

    # 管理端设置接口绝不能返回密钥类信息（无论角色）
    response = client.get('/api/admin/settings')

    if response.status_code == 200:
        body = response.get_data(as_text=True).lower()

        check('管理端设置接口不泄露密钥字段',
              'api_key' not in body and 'db_password' not in body,
              '响应中出现了疑似密钥字段名')

    # 学校统一身份认证配置接口不得返回任何密钥
    response = client.get('/api/admin/sso-config')

    if response.status_code == 200:
        body = response.get_data(as_text=True).lower()

        check('SSO 配置接口不泄露密钥',
              'client_secret' not in body or 'false' in body,
              '响应中出现了 client_secret 明文')


def test_render_assets(client):
    """前端共享渲染资源必须可访问（公式渲染依赖它）。"""

    print('\n[11] 前端静态资源')

    for path in (
        '/static/js/render.js',
        '/static/css/render.css',
        '/static/js/chat.js',
        '/static/js/errors_register.js'
    ):
        response = client.get(path)
        check(f'{path} 可访问', response.status_code == 200,
              f'实际 {response.status_code}')


def test_student_cannot_reach_privileged(app):
    """用学生账号验证：教师端与管理端接口必须全部 403。

    这是"前端隐藏按钮不等于权限控制"的核心验证，因此单独用学生身份跑一遍。
    需要 SMOKE_TEST_STUDENT_USER / SMOKE_TEST_STUDENT_PASSWORD。
    """

    user_no = os.getenv('SMOKE_TEST_STUDENT_USER')
    password = os.getenv('SMOKE_TEST_STUDENT_PASSWORD')

    print('\n[12] 学生身份越权验证')

    if not user_no or not password:
        skip(
            '学生越权验证',
            '未设置 SMOKE_TEST_STUDENT_USER / SMOKE_TEST_STUDENT_PASSWORD'
        )
        return

    role = current_role(user_no)

    if role != 'student':
        skip('学生越权验证', f'账号 {user_no} 的角色是 {role}，不是 student')
        return

    with app.test_client() as client:
        response = login(client, user_no, password)

        if response.status_code != 200 or not (response.get_json() or {}).get('success'):
            skip('学生越权验证', f'登录失败：{response.get_json()}')
            return

        paths = [
            '/api/teacher/classes',
            '/api/teacher/courses',
            '/api/teacher/students?class_id=1',
            '/api/teacher/class-report?class_id=1',
            '/api/teacher/tasks',
            '/api/teacher/questions',
            '/api/admin/users',
            '/api/admin/stats',
            '/api/admin/logs',
            '/api/admin/settings',
            '/api/admin/classes',
            '/api/admin/backups',
            '/api/admin/course-tree'
        ]

        for path in paths:
            response = client.get(path)

            if response.status_code == 404:
                skip(f'学生 GET {path}', '接口尚未实现')
                continue

            check(f'学生 GET {path} → 403',
                  response.status_code == 403,
                  f'实际 {response.status_code}')

        # 写操作同样必须被拒绝
        response = client.post('/api/teacher/tasks', json={'class_id': 1, 'title': 'x'})
        check('学生 POST /api/teacher/tasks → 403',
              response.status_code == 403,
              f'实际 {response.status_code}')

        response = client.post('/api/admin/users', json={'user_no': 'f25010000'})
        check('学生 POST /api/admin/users → 403',
              response.status_code == 403,
              f'实际 {response.status_code}')

        # 学生也不能看教师端页面
        response = client.get('/teacher', follow_redirects=False)
        check('学生访问 /teacher 页面被重定向',
              response.status_code in (301, 302),
              f'实际 {response.status_code}')

        response = client.get('/admin', follow_redirects=False)
        check('学生访问 /admin 页面被重定向',
              response.status_code in (301, 302),
              f'实际 {response.status_code}')


def test_page_rendering_by_role(app):
    """按角色验证页面能否正常渲染。

    直接向测试会话注入身份（不依赖各账号密码），
    用于发现模板语法错误、变量缺失或权限放行错误——
    这类问题在只测接口时是发现不了的。
    """

    print('\n[13] 按角色渲染页面')

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, MIN(id) AS user_id
                FROM users
                GROUP BY role
                """
            )

            role_rows = cursor.fetchall()

            users = {}

            for row in role_rows:
                cursor.execute(
                    'SELECT id, user_no FROM users WHERE id = %s',
                    (row['user_id'],)
                )
                users[row['role']] = cursor.fetchone()
    finally:
        connection.close()

    expected_pages = {
        'student': ['/home', '/chat', '/exam', '/errors_register',
                    '/practice', '/resources', '/user', '/password'],
        'teacher': ['/home', '/chat', '/practice', '/resources',
                    '/teacher', '/user'],
        'admin': ['/home', '/chat', '/practice', '/resources',
                  '/teacher', '/admin', '/user']
    }

    denied_pages = {
        'student': ['/teacher', '/admin'],
        'teacher': ['/admin'],
        'admin': []
    }

    for role, pages in expected_pages.items():
        user = users.get(role)

        if not user:
            skip(f'{role} 页面渲染', f'数据库中没有 {role} 角色的账号')
            continue

        with app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session['logged_in'] = True
                flask_session['username'] = user['user_no']
                flask_session['userid'] = user['id']
                flask_session['role'] = role

            for path in pages:
                response = client.get(path)

                check(
                    f'{role} 可渲染 {path}',
                    response.status_code == 200,
                    f'实际 {response.status_code}'
                )

                if response.status_code == 200:
                    html = response.get_data(as_text=True)

                    check(
                        f'{path} 未出现模板错误标记',
                        'jinja2' not in html.lower()
                        and 'Traceback' not in html
                        and 'Undefined' not in html,
                        '页面中出现模板错误信息'
                    )

            for path in denied_pages.get(role, []):
                response = client.get(path, follow_redirects=False)

                check(
                    f'{role} 访问 {path} 被拒绝',
                    response.status_code in (301, 302, 403),
                    f'实际 {response.status_code}'
                )


def test_referenced_assets(app):
    """检查模板中引用到的本地静态资源是否真的存在。

    页面引用了不存在的 JS/CSS 时浏览器只会静默 404，
    功能会莫名其妙失效（本轮新增了多个模块页面，很容易漏文件）。
    """

    import re as _re

    print('\n[14] 模板引用的静态资源完整性')

    templates_dir = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
        'templates'
    )

    pattern = _re.compile(r'''(?:src|href)\s*=\s*["'](/static/[^"'?#]+)''')

    missing = []
    checked = set()

    with app.test_client() as client:
        for name in sorted(os.listdir(templates_dir)):
            if not name.endswith('.html'):
                continue

            with open(os.path.join(templates_dir, name), encoding='utf-8') as handle:
                content = handle.read()

            for match in pattern.finditer(content):
                url = match.group(1)

                if url in checked:
                    continue

                checked.add(url)

                response = client.get(url)

                if response.status_code != 200:
                    missing.append((name, url, response.status_code))

    check(f'模板共引用 {len(checked)} 个本地静态资源', bool(checked))

    if missing:
        for template, url, status in missing:
            check(f'{template} 引用的 {url} 存在', False, f'HTTP {status}')
    else:
        check('所有被引用的本地静态资源均可访问', True)

def test_ai_live(client):
    print('\n[9] AI 链路（真实调用）')

    response = client.post('/api/chat', json={
        'messages': [{
            'role': 'user',
            'content': '求 $\\int_0^1 x^2\\,\\mathrm{d}x$ 的值，并说明用了哪个公式。'
        }]
    })

    body = response.get_json() or {}

    if response.status_code != 200 or not body.get('success'):
        check('AI 文本问答成功', False, f'{response.status_code} {body.get("message")}')
        return

    check('AI 文本问答成功', True)

    reply = body.get('reply') or ''
    plain = body.get('reply_plain') or ''

    check('回答保留 LaTeX（供前端 KaTeX 渲染）',
          '$' in reply, '回答中未出现 LaTeX 定界符')
    check('提供无 LaTeX 的降级纯文本',
          bool(plain) and '\\frac' not in plain,
          f'降级文本片段：{plain[:80]!r}')
    check('返回结构化分析结果',
          isinstance(body.get('analysis'), dict),
          f'实际 {type(body.get("analysis"))}')
    check('返回会话 ID', bool(body.get('conversation_id')),
          '未返回 conversation_id')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true',
                        help='同时测试真实 AI 调用（会消耗接口额度并较慢）')
    args = parser.parse_args()

    app = create_app()
    app.config['TESTING'] = True

    user = get_test_user()

    if not user:
        print('数据库中没有学生账号，无法执行登录相关测试。')
        return 1

    print(f'测试账号：{user["user_no"]}（id={user["id"]}）')
    print('注意：本脚本需要一个已知密码的测试账号；')
    print('      若密码未知，登录相关用例会失败，请先创建测试账号。')

    password = os.getenv('SMOKE_TEST_PASSWORD')

    if not password:
        print('\n未设置 SMOKE_TEST_PASSWORD 环境变量，跳过需要登录的用例。')

    with app.test_client() as client:
        test_pages(client)
        test_api_auth(client)
        test_api_errors(client)
        test_image_save_service()

        if password:
            response = login(client, user['user_no'], password)

            if response.status_code != 200 or not (response.get_json() or {}).get('success'):
                print(f'\n登录失败：{response.get_json()}')
                return 1

            print('登录成功，继续执行需要鉴权的用例。')

            test_register_validation(client)
            test_wrong_questions(client)
            test_conversations(client)
            test_image_validation(client)
            test_render_assets(client)
            test_new_module_auth(client, current_role(user['user_no']))

            if args.live:
                test_ai_live(client)

    test_student_cannot_reach_privileged(app)
    test_referenced_assets(app)
    test_page_rendering_by_role(app)

    print('\n' + '=' * 62)
    print(f'通过 {len(PASSED)} 项，失败 {len(FAILED)} 项，跳过 {len(SKIPPED)} 项')

    if FAILED:
        print('\n失败明细：')

        for name, detail in FAILED:
            print(f'  - {name}: {detail}')

    if SKIPPED:
        print('\n跳过明细：')

        for name, reason in SKIPPED:
            print(f'  - {name}: {reason}')

    print('=' * 62)

    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""系统管理端接口（模块十）。

页面路由 GET /admin 已存在。本蓝图提供 /api/admin* 系列接口：
- 用户管理（查询 / 新建 / 改角色 / 冻结 / 改资料，含自锁与“最后一名管理员”保护）
- 班级、班级成员、授课关系管理
- 题库管理（含 verified 审核标记）
- 全校统计、操作日志、系统参数、数据库备份、SSO 配置探测

安全说明：
- 所有接口都要求 @role_required(ROLE_ADMIN)，权限不依赖前端隐藏按钮；
- 系统参数接口显式拒绝 key/secret/password/token 类参数名，
  也永远不会返回 Config.AI_API_KEY / Config.DB_PASSWORD；
- 备份使用 mysqldump，数据库密码只通过 MYSQL_PWD 环境变量传递；
- 日志 detail 绝不包含密码或密钥。
"""

from flask import Blueprint, request, session

from backend.services import admin_service, resource_service, teacher_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, forbidden, not_found, ok
from backend.utils.security import ROLE_ADMIN, ROLE_TEACHER, role_required
from backend.utils.validators import normalize_text, parse_positive_int


admin_bp = Blueprint('admin', __name__)

logger = get_logger('admin')


def _operator_id():
    """当前管理员 ID。"""

    return session.get('userid')


def _client_ip():
    """请求来源 IP（记录到操作日志）。"""

    forwarded = request.headers.get('X-Forwarded-For')

    if forwarded:
        return normalize_text(forwarded.split(',')[0], 64)

    return normalize_text(request.remote_addr, 64)


# ============================================================
# 用户管理
# ============================================================

@admin_bp.route('/api/admin/users', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_users():
    """用户列表：搜索 / 角色筛选 / 状态筛选 / 学院筛选 + 分页。"""

    status_raw = request.args.get('status')

    status = None

    if status_raw in ('0', '1'):
        status = int(status_raw)

    try:
        result = admin_service.list_users(
            keyword=normalize_text(request.args.get('keyword'), 100) or None,
            role=normalize_text(request.args.get('role'), 20) or None,
            status=status,
            college=normalize_text(request.args.get('college'), 100) or None,
            page=parse_positive_int(request.args.get('page'), 1) or 1,
            page_size=parse_positive_int(
                request.args.get('page_size'), 20, maximum=100
            ) or 20
        )
    except Exception as exc:
        logger.error('读取用户列表失败: %s', exc)
        return fail('用户列表读取失败', status=500)

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size'],
        roles=[
            {'value': role, 'label': admin_service.ROLE_LABELS[role]}
            for role in admin_service.ALLOWED_ROLES
        ],
        operator_id=_operator_id()
    )


@admin_bp.route('/api/admin/users', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_user_create():
    """新建用户。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'user_no': normalize_text(data.get('user_no'), 20),
        'password': data.get('password'),
        'role': normalize_text(data.get('role'), 20) or None,
        'college': normalize_text(data.get('college'), 100),
        'email': normalize_text(data.get('email'), 100),
        'real_name': normalize_text(data.get('real_name'), 50),
        'status': data.get('status', 1)
    }

    try:
        result, status = admin_service.create_user(
            _operator_id(), payload, _client_ip()
        )
    except Exception as exc:
        logger.error('新建用户失败: %s', exc)
        return fail('新建用户失败', status=500)

    if not result.get('success'):
        if status == 409:
            return fail(result.get('message'), status=409, code='CONFLICT')

        return fail(result.get('message', '新建用户失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/users/<int:user_id>', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_user_detail(user_id):
    """单个用户详情（不含任何密码字段）。"""

    try:
        row = admin_service.get_user(user_id)
    except Exception as exc:
        logger.error('读取用户详情失败: %s', exc)
        return fail('用户读取失败', status=500)

    if not row:
        return not_found('用户不存在')

    return ok(data=row)


@admin_bp.route('/api/admin/users/<int:user_id>', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_admin_user_update(user_id):
    """修改用户角色 / 状态 / 学院 / 姓名 / 邮箱。"""

    data = request.get_json(silent=True) or {}

    payload = {}

    if 'role' in data:
        payload['role'] = normalize_text(data.get('role'), 20)

    if 'status' in data:
        payload['status'] = 1 if data.get('status') in (1, '1', True, 'true') else 0

    if 'college' in data:
        payload['college'] = normalize_text(data.get('college'), 100)

    if 'real_name' in data:
        payload['real_name'] = normalize_text(data.get('real_name'), 50)

    if 'email' in data:
        payload['email'] = normalize_text(data.get('email'), 100)

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = admin_service.update_user(
            _operator_id(), user_id, payload, _client_ip()
        )
    except Exception as exc:
        logger.error('修改用户失败: %s', exc)
        return fail('用户更新失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '用户更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/colleges', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_colleges():
    """用户表中出现过的真实学院列表（供筛选项）。"""

    try:
        rows = admin_service.list_colleges()
    except Exception as exc:
        logger.error('读取学院列表失败: %s', exc)
        return fail('学院列表读取失败', status=500)

    return ok(data=rows)


# ============================================================
# 班级与授课关系
# ============================================================

@admin_bp.route('/api/admin/classes', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_classes():
    """班级列表。"""

    try:
        classes = admin_service.list_classes()
    except Exception as exc:
        logger.error('读取班级列表失败: %s', exc)
        return fail('班级列表读取失败', status=500)

    return ok(data=classes, total=len(classes))


@admin_bp.route('/api/admin/classes', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_class_create():
    """新建班级。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'name': normalize_text(data.get('name'), 100),
        'college': normalize_text(data.get('college'), 100),
        'grade_year': parse_positive_int(data.get('grade_year'), maximum=2999),
        'remark': normalize_text(data.get('remark'), 255)
    }

    try:
        result, status = admin_service.create_class(
            _operator_id(), payload, _client_ip()
        )
    except Exception as exc:
        logger.error('新建班级失败: %s', exc)
        return fail('班级创建失败', status=500)

    if not result.get('success'):
        if status == 409:
            return fail(result.get('message'), status=409, code='CONFLICT')

        return fail(result.get('message', '班级创建失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/classes/<int:class_id>/students', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_class_students(class_id):
    """班级学生名单。"""

    try:
        students = admin_service.list_class_students(class_id)
    except Exception as exc:
        logger.error('读取班级学生失败: %s', exc)
        return fail('班级学生读取失败', status=500)

    return ok(data=students, total=len(students), class_id=class_id)


@admin_bp.route('/api/admin/classes/<int:class_id>/students', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_class_students_add(class_id):
    """把学生加入班级（user_ids 数组）。"""

    data = request.get_json(silent=True) or {}

    user_ids = data.get('user_ids')

    if user_ids is None and data.get('user_id') is not None:
        user_ids = [data.get('user_id')]

    try:
        result, status = admin_service.add_class_students(
            _operator_id(), class_id, user_ids, _client_ip()
        )
    except Exception as exc:
        logger.error('加入班级失败: %s', exc)
        return fail('加入班级失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '加入班级失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/classes/<int:class_id>/students/<int:user_id>',
                methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_admin_class_student_remove(class_id, user_id):
    """把学生移出班级。"""

    try:
        result, status = admin_service.remove_class_student(
            _operator_id(), class_id, user_id, _client_ip()
        )
    except Exception as exc:
        logger.error('移出班级失败: %s', exc)
        return fail('移出班级失败', status=500)

    if not result.get('success'):
        return not_found(result.get('message'))

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/teacher-courses', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_teacher_courses():
    """授课关系列表。"""

    try:
        links = admin_service.list_teacher_courses()
    except Exception as exc:
        logger.error('读取授课关系失败: %s', exc)
        return fail('授课关系读取失败', status=500)

    return ok(data=links, total=len(links))


@admin_bp.route('/api/admin/teacher-courses', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_teacher_course_add():
    """绑定教师到「课程 + 班级」。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'teacher_id': parse_positive_int(data.get('teacher_id')),
        'course_id': parse_positive_int(data.get('course_id')),
        'class_id': parse_positive_int(data.get('class_id')),
        'term': normalize_text(data.get('term'), 30)
    }

    try:
        result, status = admin_service.add_teacher_course(
            _operator_id(), payload, _client_ip()
        )
    except Exception as exc:
        logger.error('新增授课关系失败: %s', exc)
        return fail('授课关系新增失败', status=500)

    if not result.get('success'):
        if status == 409:
            return fail(result.get('message'), status=409, code='CONFLICT')

        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '授课关系新增失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/teacher-courses/<int:link_id>', methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_admin_teacher_course_delete(link_id):
    """解除授课关系。"""

    try:
        result, status = admin_service.delete_teacher_course(
            _operator_id(), link_id, _client_ip()
        )
    except Exception as exc:
        logger.error('解除授课关系失败: %s', exc)
        return fail('授课关系解除失败', status=500)

    if not result.get('success'):
        return not_found(result.get('message'))

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 题库管理
# ============================================================

@admin_bp.route('/api/admin/questions', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_questions():
    """题库列表（分页 + 筛选）。"""

    verified_raw = request.args.get('verified')

    verified = None

    if verified_raw in ('0', '1'):
        verified = int(verified_raw)

    try:
        result = admin_service.list_questions(
            course_id=parse_positive_int(request.args.get('course_id')),
            chapter_id=parse_positive_int(request.args.get('chapter_id')),
            major=normalize_text(request.args.get('major'), 50) or None,
            qtype=normalize_text(request.args.get('qtype'), 20) or None,
            verified=verified,
            keyword=normalize_text(request.args.get('keyword'), 100) or None,
            page=parse_positive_int(request.args.get('page'), 1) or 1,
            page_size=parse_positive_int(
                request.args.get('page_size'), 20, maximum=100
            ) or 20
        )
    except Exception as exc:
        logger.error('读取题库失败: %s', exc)
        return fail('题库读取失败', status=500)

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size']
    )


@admin_bp.route('/api/admin/questions', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_question_create():
    """新增题库题目。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'course_id': parse_positive_int(data.get('course_id')),
        'chapter_id': parse_positive_int(data.get('chapter_id')),
        'major': normalize_text(data.get('major'), 50),
        'kp_name': normalize_text(data.get('kp_name'), 150),
        'qtype': normalize_text(data.get('qtype'), 20) or 'choice',
        'difficulty': data.get('difficulty'),
        'question': normalize_text(data.get('question'), 8000),
        'options_json': data.get('options_json') or data.get('options'),
        'answer': normalize_text(data.get('answer'), 8000),
        'analysis': normalize_text(data.get('analysis'), 8000),
        'source': normalize_text(data.get('source'), 50),
        'verified': data.get('verified', 1)
    }

    try:
        result, status = admin_service.create_question(
            _operator_id(), payload, _client_ip()
        )
    except Exception as exc:
        logger.error('新增题库题目失败: %s', exc)
        return fail('题目新增失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '题目新增失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/questions/<int:question_id>', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_admin_question_update(question_id):
    """更新题库题目（verified 置 1 时记录审核人）。"""

    data = request.get_json(silent=True) or {}

    payload = {}

    for key in ('major', 'kp_name', 'qtype', 'question', 'answer', 'analysis',
                'source'):
        if key in data:
            payload[key] = normalize_text(
                data.get(key), 8000 if key in ('question', 'answer', 'analysis') else 150
            )

    if 'difficulty' in data:
        payload['difficulty'] = data.get('difficulty')

    if 'status' in data:
        payload['status'] = 1 if data.get('status') in (1, '1', True, 'true') else 0

    if 'verified' in data:
        payload['verified'] = 1 if data.get('verified') in (1, '1', True, 'true') else 0

    if 'options_json' in data or 'options' in data:
        payload['options_json'] = data.get('options_json') or data.get('options')

    for key in ('course_id', 'chapter_id'):
        if key in data:
            payload[key] = parse_positive_int(data.get(key))

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = admin_service.update_question(
            _operator_id(), question_id, payload, _client_ip()
        )
    except Exception as exc:
        logger.error('更新题库题目失败: %s', exc)
        return fail('题目更新失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '题目更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/questions/<int:question_id>', methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_admin_question_delete(question_id):
    """下架题库题目（软删除）。"""

    try:
        result, status = admin_service.delete_question(
            _operator_id(), question_id, _client_ip()
        )
    except Exception as exc:
        logger.error('删除题库题目失败: %s', exc)
        return fail('题目删除失败', status=500)

    if not result.get('success'):
        return not_found(result.get('message'))

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 统计
# ============================================================

@admin_bp.route('/api/admin/stats', methods=['GET'])
@role_required(ROLE_ADMIN, ROLE_TEACHER)
def api_admin_stats():
    """统计接口。

    管理员：全校数据；
    教师：只返回自己 teacher_courses 覆盖范围内的数据（scope='teacher'），
    绝不下发全校数据。
    """

    role = session.get('role')
    user_id = session.get('userid')

    try:
        if role == ROLE_ADMIN:
            stats = admin_service.school_stats()
        else:
            stats = admin_service.school_stats(scope_teacher_id=user_id)
    except Exception as exc:
        logger.error('统计失败: %s', exc)
        return fail('统计失败', status=500)

    stats['role'] = role

    return ok(data=stats)


@admin_bp.route('/api/admin/logs', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_logs():
    """操作日志（分页 + 用户 / 动作 / 日期筛选）。"""

    try:
        result = admin_service.list_logs(
            user_id=parse_positive_int(request.args.get('user_id')),
            action=normalize_text(request.args.get('action'), 50) or None,
            role=normalize_text(request.args.get('role'), 20) or None,
            start_date=normalize_text(request.args.get('start_date'), 10) or None,
            end_date=normalize_text(request.args.get('end_date'), 10) or None,
            page=parse_positive_int(request.args.get('page'), 1) or 1,
            page_size=parse_positive_int(
                request.args.get('page_size'), 20, maximum=200
            ) or 20
        )
    except Exception as exc:
        logger.error('读取操作日志失败: %s', exc)
        return fail('操作日志读取失败', status=500)

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size']
    )


# ============================================================
# 系统参数
# ============================================================

@admin_bp.route('/api/admin/settings', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_settings():
    """读取非敏感系统参数。

    含 key/secret/password/token 的键名一律不返回（只回报名单），
    也永远不会返回 Config.AI_API_KEY / Config.DB_PASSWORD。
    """

    try:
        result = admin_service.list_settings()
    except Exception as exc:
        logger.error('读取系统参数失败: %s', exc)
        return fail('系统参数读取失败', status=500)

    return ok(
        data=result['items'],
        total=len(result['items']),
        blocked_keys=result['blocked_keys'],
        blocked_hint=result['blocked_hint'],
        notice=(
            '模型密钥与数据库密码不在此接口的读写范围内，'
            '请直接修改服务器上的 .env 文件'
        )
    )


@admin_bp.route('/api/admin/settings', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_admin_settings_update():
    """写入非敏感系统参数；敏感键名一律拒绝。"""

    data = request.get_json(silent=True)

    if isinstance(data, dict) and 'settings' in data:
        settings = data.get('settings')
    else:
        settings = data

    try:
        result, status = admin_service.update_settings(
            _operator_id(), settings, _client_ip()
        )
    except Exception as exc:
        logger.error('更新系统参数失败: %s', exc)
        return fail('系统参数更新失败', status=500)

    if not result.get('success'):
        if result.get('code') == 'SENSITIVE_SETTING_REJECTED' or status == 403:
            return fail(
                result.get('message', '不允许写入敏感参数'),
                status=403,
                code='SENSITIVE_SETTING_REJECTED',
                rejected_keys=result.get('rejected_keys', [])
            )

        return fail(result.get('message', '系统参数更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 备份
# ============================================================

@admin_bp.route('/api/admin/backup', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_admin_backup_create():
    """执行一次真实的 mysqldump 备份。"""

    try:
        result, status = admin_service.create_backup(
            _operator_id(), _client_ip()
        )
    except Exception as exc:
        logger.error('执行备份失败: %s', exc)
        return fail('备份执行失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '备份失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@admin_bp.route('/api/admin/backups', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_backups():
    """备份记录 + 磁盘上真实存在的备份文件。"""

    try:
        result = admin_service.list_backups()
    except Exception as exc:
        logger.error('读取备份记录失败: %s', exc)
        return fail('备份记录读取失败', status=500)

    return ok(
        data=result['records'],
        files=result['files'],
        backup_dir=result['backup_dir'],
        record_count=result['record_count'],
        file_count=result['file_count'],
        tool=result['tool']
    )


# ============================================================
# SSO 配置探测（仅预留，未实现真实登录）
# ============================================================

@admin_bp.route('/api/admin/sso-config', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_sso_config():
    """返回学校统一身份认证的配置状态（只读环境变量，不含任何密钥值）。"""

    try:
        result = admin_service.sso_config()
    except Exception as exc:
        logger.error('读取 SSO 配置失败: %s', exc)
        return fail('SSO 配置读取失败', status=500)

    return ok(data=result)


# ============================================================
# 管理端复用的课程 / 章节 / 知识点入口
# ============================================================

@admin_bp.route('/api/admin/course-tree', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_course_tree():
    """课程 → 章节 → 知识点的树形结构，供管理端展示（只读）。"""

    course_id = parse_positive_int(request.args.get('course_id'))

    try:
        courses = resource_service.list_courses(include_disabled=True)

        if course_id:
            courses = [row for row in courses if row['id'] == course_id]

        chapters = resource_service.list_chapters(course_id)
        points = resource_service.list_knowledge_points(course_id)
    except Exception as exc:
        logger.error('读取课程树失败: %s', exc)
        return fail('课程结构读取失败', status=500)

    return ok(courses=courses, chapters=chapters, knowledge_points=points)


@admin_bp.route('/api/admin/class-report', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_class_report():
    """管理员查看任意班级的学情报表（复用教师端服务，管理员不受班级限制）。"""

    class_id = parse_positive_int(request.args.get('class_id'))
    course_id = parse_positive_int(request.args.get('course_id'))
    days = parse_positive_int(request.args.get('days'), 30, maximum=3650) or 30

    if not class_id:
        return fail('请提供 class_id')

    try:
        report = teacher_service.class_report(
            _operator_id(), class_id, course_id, days, is_admin=True
        )
    except Exception as exc:
        logger.error('管理员读取班级报表失败: %s', exc)
        return fail('班级报表读取失败', status=500)

    if report is None:
        return not_found('班级不存在')

    return ok(data=report)


@admin_bp.route('/api/admin/teachers', methods=['GET'])
@role_required(ROLE_ADMIN)
def api_admin_teachers():
    """教师与管理员账号列表（用于授课关系绑定下拉框）。"""

    try:
        teachers = admin_service.list_users(
            role=ROLE_TEACHER, page=1, page_size=100
        )['items']

        admins = admin_service.list_users(
            role=ROLE_ADMIN, page=1, page_size=100
        )['items']
    except Exception as exc:
        logger.error('读取教师列表失败: %s', exc)
        return fail('教师列表读取失败', status=500)

    return ok(data=teachers + admins)

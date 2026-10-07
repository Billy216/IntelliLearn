# -*- coding: utf-8 -*-
"""系统管理端数据服务（模块十）。

职责：
- 用户管理（查询 / 新建 / 改角色 / 冻结 / 改资料）与自锁保护；
- 班级、班级成员、授课关系（teacher_courses）管理；
- 题库管理（含 verified 审核标记与审核人）；
- 全校 / 教师授权范围内的统计；
- 操作日志（查询 + 主动写入）；
- 系统参数（system_settings，敏感键名一律拒绝）；
- 数据库备份（真实调用 mysqldump，密码只走 MYSQL_PWD 环境变量）。

安全约定：
- 任何写入都不会把密码、密钥写进 operation_logs.detail；
- 角色只能取 users.role 的三个真实枚举值；
- 动态列名全部走白名单，SQL 全部使用 %s 占位符。
"""

import os
import shutil
import subprocess
from datetime import datetime

import bcrypt

from config import Config
from backend.extensions.database import db_connection
from backend.utils.logging_config import get_logger
from backend.utils.security import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER


logger = get_logger('admin')


# 允许的角色（与 users.role 枚举完全一致）
ALLOWED_ROLES = (ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN)

ROLE_LABELS = {
    ROLE_STUDENT: '学生',
    ROLE_TEACHER: '教师',
    ROLE_ADMIN: '管理员'
}

# 用户可更新列白名单
USER_WRITABLE = {'role', 'status', 'college', 'real_name', 'email', 'avatar_path'}

# 题库可更新列白名单
QUESTION_WRITABLE = {
    'course_id', 'chapter_id', 'major', 'kp_name', 'qtype', 'difficulty',
    'question', 'options_json', 'answer', 'analysis', 'source', 'status'
}

QUESTION_TYPES = ('judge', 'choice', 'fill', 'essay')

# 敏感键名模式：命中即拒绝读写（模型密钥、数据库密码等绝不能经由此接口）
SENSITIVE_KEYWORDS = ('key', 'secret', 'password', 'passwd', 'token', 'pwd')

# 备份目录与 mysqldump 常见位置
BACKUP_DIR = os.path.join(Config.BASE_DIR, 'backups')

MYSQLDUMP_CANDIDATES = (
    r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe',
    r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe',
    r'C:\Program Files (x86)\MySQL\MySQL Server 8.0\bin\mysqldump.exe',
)


# ============================================================
# 内部工具
# ============================================================

def _stringify(rows, keys=('created_at', 'updated_at', 'submitted_at',
                           'joined_at', 'last_review_at')):
    """datetime -> 字符串。"""

    if isinstance(rows, dict):
        rows = [rows]

    for row in rows or []:
        for key in keys:
            if row.get(key) is not None:
                row[key] = str(row[key])

    return rows


def _to_str(value, max_length=None):
    if value is None:
        return None

    text = str(value).strip()

    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def _int_or_none(value):
    if value in (None, '', 'null'):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_sensitive_key(setting_key):
    """键名是否属于敏感参数（密钥 / 密码 / token 等）。"""

    if not setting_key:
        return True

    lowered = str(setting_key).strip().lower()

    return any(word in lowered for word in SENSITIVE_KEYWORDS)


def hash_password(password):
    """bcrypt 哈希（与 user_service 使用同一算法）。"""

    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    )


def write_log(user_id, role, action, target_type=None, target_id=None,
              detail=None, ip=None, status='ok'):
    """写入操作日志。

    绝不记录密码 / 密钥：调用方传入的 detail 会先被清洗。
    任何日志写入失败都不应影响主流程，因此这里吞掉异常并只记 logger。
    """

    safe_detail = detail

    if safe_detail is not None:
        safe_detail = str(safe_detail)

        # 兜底：即使调用方失误，也不让敏感键名带进日志
        lowered = safe_detail.lower()

        if any(word in lowered for word in SENSITIVE_KEYWORDS):
            safe_detail = '[detail 含敏感键名，已省略]'
        else:
            safe_detail = safe_detail[:500]

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO operation_logs
                    (user_id, role, action, target_type, target_id, detail, ip, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        role,
                        action,
                        target_type,
                        target_id,
                        safe_detail,
                        ip,
                        status
                    )
                )

                connection.commit()

        return True
    except Exception as exc:
        logger.error('写入操作日志失败: %s', exc)

        return False


# ============================================================
# 用户管理
# ============================================================

def list_users(keyword=None, role=None, status=None, college=None,
               page=1, page_size=20):
    """用户列表（支持搜索 / 角色筛选 / 状态筛选 / 学院筛选 + 分页）。"""

    clauses = []
    params = []

    if keyword:
        clauses.append(
            '(user_no LIKE %s OR real_name LIKE %s OR email LIKE %s)'
        )
        like = f'%{keyword}%'
        params.extend([like, like, like])

    if role in ALLOWED_ROLES:
        clauses.append('role = %s')
        params.append(role)

    if status in (0, 1):
        clauses.append('status = %s')
        params.append(status)

    if college:
        clauses.append('college = %s')
        params.append(college)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    offset = (page - 1) * page_size

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM users {where}',
                tuple(params)
            )

            total = cursor.fetchone()['total']

            cursor.execute(
                f"""
                SELECT
                    id, role, user_no, college, email, real_name, status,
                    avatar_path, created_at, updated_at
                FROM users
                {where}
                ORDER BY id
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset])
            )

            items = _stringify(cursor.fetchall())

    for item in items:
        item['role_label'] = ROLE_LABELS.get(item['role'], item['role'])
        item['status'] = int(item['status'] or 0)

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size
    }


def get_user(user_id):
    """读取单个用户（不含密码）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, role, user_no, college, email, real_name, status,
                       avatar_path, created_at, updated_at
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

    if not row:
        return None

    row['role_label'] = ROLE_LABELS.get(row['role'], row['role'])
    row['status'] = int(row['status'] or 0)

    return _stringify([row])[0]


def count_active_admins(exclude_user_id=None):
    """统计“未冻结的管理员”数量（用于最后一名管理员的保护判断）。"""

    sql = "SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND status = 1"
    params = []

    if exclude_user_id:
        sql += ' AND id <> %s'
        params.append(exclude_user_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))

            return cursor.fetchone()['total']


def create_user(operator_id, data, ip=None):
    """管理员新建用户。返回 (结果字典, 状态码)。"""

    user_no = _to_str(data.get('user_no'), 20)

    if not user_no:
        return {'success': False, 'message': '学号/教师号不能为空'}, 400

    user_no = user_no.lower()

    role = _to_str(data.get('role')) or None

    if role and role not in ALLOWED_ROLES:
        return {'success': False, 'message': '角色只能是 student/teacher/admin'}, 400

    if not role:
        # 未指定角色时按账号前缀推断（f 学生 / t 教师）
        role = ROLE_STUDENT if user_no.startswith('f') else (
            ROLE_TEACHER if user_no.startswith('t') else ROLE_STUDENT
        )

    password = data.get('password') or ''

    if not password or len(str(password)) < Config.PASSWORD_MIN_LENGTH:
        return {
            'success': False,
            'message': f'密码长度至少 {Config.PASSWORD_MIN_LENGTH} 位'
        }, 400

    status = 1 if data.get('status') in (None, 1, '1', True, 'true') else 0

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT id FROM users WHERE user_no = %s',
                    (user_no,)
                )

                if cursor.fetchone():
                    return {'success': False, 'message': '该账号已存在'}, 409

                cursor.execute(
                    """
                    INSERT INTO users
                    (role, user_no, password, college, email, real_name, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        role,
                        user_no,
                        hash_password(str(password)),
                        _to_str(data.get('college'), 100),
                        _to_str(data.get('email'), 100),
                        _to_str(data.get('real_name'), 50),
                        status
                    )
                )

                user_id = cursor.lastrowid

                connection.commit()
    except Exception as exc:
        logger.error('新建用户失败: %s', exc)

        return {'success': False, 'message': '新建用户失败，账号可能重复'}, 409

    write_log(
        operator_id, ROLE_ADMIN, 'user_create', 'user', user_id,
        f'新建用户 {user_no}（角色 {role}）', ip
    )

    logger.info('管理员 %s 新建用户 %s（%s）', operator_id, user_id, user_no)

    # 注意：返回体里不含任何密码字段
    return {
        'success': True,
        'message': '用户已创建',
        'user_id': user_id
    }, 200


def update_user(operator_id, user_id, data, ip=None):
    """管理员修改用户（角色 / 状态 / 学院 / 姓名 / 邮箱）。

    保护规则：
    - 管理员不能冻结或降级自己的账号；
    - 不能把最后一名未冻结的管理员降级或冻结。
    """

    target = get_user(user_id)

    if not target:
        return {'success': False, 'message': '用户不存在'}, 404

    updates = []
    params = []
    changes = []

    if 'role' in data:
        role = _to_str(data.get('role'))

        if role not in ALLOWED_ROLES:
            return {
                'success': False,
                'message': '角色只能是 student/teacher/admin'
            }, 400

        if role != target['role']:
            if user_id == operator_id and role != ROLE_ADMIN:
                return {
                    'success': False,
                    'message': '不能修改自己的管理员角色'
                }, 400

            if (target['role'] == ROLE_ADMIN
                    and count_active_admins(exclude_user_id=user_id) == 0):
                return {
                    'success': False,
                    'message': '系统必须保留至少一名未冻结的管理员，无法降级'
                }, 400

            updates.append('role = %s')
            params.append(role)
            changes.append(f"角色 {target['role']}→{role}")

    if 'status' in data:
        status = 1 if data.get('status') in (1, '1', True, 'true') else 0

        if status != target['status']:
            if user_id == operator_id and status == 0:
                return {
                    'success': False,
                    'message': '不能冻结自己的账号'
                }, 400

            if (status == 0 and target['role'] == ROLE_ADMIN
                    and count_active_admins(exclude_user_id=user_id) == 0):
                return {
                    'success': False,
                    'message': '系统必须保留至少一名未冻结的管理员，无法冻结'
                }, 400

            updates.append('status = %s')
            params.append(status)
            changes.append('冻结' if status == 0 else '解冻')

    for key in ('college', 'real_name', 'email', 'avatar_path'):
        if key in data:
            value = _to_str(data.get(key), 100 if key != 'real_name' else 50)

            if value != target.get(key):
                updates.append(f'{key} = %s')
                params.append(value)
                changes.append(f'{key} 已修改')

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(user_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = %s",
                tuple(params)
            )

            affected = cursor.rowcount

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'user_update', 'user', user_id,
        f"修改用户 {target['user_no']}：" + '；'.join(changes), ip
    )

    logger.info('管理员 %s 修改用户 %s：%s', operator_id, user_id, '；'.join(changes))

    return {
        'success': True,
        'message': '用户已更新',
        'affected': affected,
        'changes': changes
    }, 200


def list_colleges():
    """用户表中出现过的真实学院（供筛选项使用）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT college, COUNT(*) AS total
                FROM users
                WHERE college IS NOT NULL AND college <> ''
                GROUP BY college
                ORDER BY total DESC
                """
            )

            return cursor.fetchall()


# ============================================================
# 班级与授课关系
# ============================================================

def list_classes():
    """班级列表（含人数与授课关系数）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id, c.name, c.college, c.grade_year, c.remark, c.created_at,
                    (SELECT COUNT(*) FROM class_students cs
                      WHERE cs.class_id = c.id) AS student_count,
                    (SELECT COUNT(*) FROM teacher_courses tc
                      WHERE tc.class_id = c.id) AS link_count
                FROM classes c
                ORDER BY c.id DESC
                """
            )

            return _stringify(cursor.fetchall())


def create_class(operator_id, data, ip=None):
    """新建班级。"""

    name = _to_str(data.get('name'), 100)

    if not name:
        return {'success': False, 'message': '班级名称不能为空'}, 400

    grade_year = _int_or_none(data.get('grade_year'))

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO classes (name, college, grade_year, remark)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        name,
                        _to_str(data.get('college'), 100),
                        grade_year,
                        _to_str(data.get('remark'), 255)
                    )
                )

                class_id = cursor.lastrowid

                connection.commit()
    except Exception as exc:
        logger.error('新建班级失败: %s', exc)

        return {'success': False, 'message': '班级名称已存在'}, 409

    write_log(
        operator_id, ROLE_ADMIN, 'class_create', 'class', class_id,
        f'新建班级 {name}', ip
    )

    return {'success': True, 'message': '班级已创建', 'class_id': class_id}, 200


def add_class_students(operator_id, class_id, user_ids, ip=None):
    """把学生批量加入班级（忽略重复）。"""

    if not isinstance(user_ids, list) or not user_ids:
        return {'success': False, 'message': 'user_ids 必须是非空数组'}, 400

    ids = []

    for value in user_ids:
        number = _int_or_none(value)

        if number:
            ids.append(number)

    if not ids:
        return {'success': False, 'message': 'user_ids 中没有合法的用户 ID'}, 400

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM classes WHERE id = %s', (class_id,))

            if not cursor.fetchone():
                return {'success': False, 'message': '班级不存在'}, 404

            placeholders = ', '.join(['%s'] * len(ids))

            cursor.execute(
                f"""
                SELECT id, role FROM users WHERE id IN ({placeholders})
                """,
                tuple(ids)
            )

            found = {row['id']: row['role'] for row in cursor.fetchall()}

            missing = [value for value in ids if value not in found]

            if missing:
                return {
                    'success': False,
                    'message': f'以下用户不存在：{missing}'
                }, 404

            added = 0

            for user_id in ids:
                cursor.execute(
                    """
                    INSERT IGNORE INTO class_students (class_id, user_id)
                    VALUES (%s, %s)
                    """,
                    (class_id, user_id)
                )

                added += cursor.rowcount

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'class_add_students', 'class', class_id,
        f'向班级加入 {added} 名学生（提交 {len(ids)} 个 ID）', ip
    )

    logger.info('班级 %s 新增 %s 名学生', class_id, added)

    return {
        'success': True,
        'message': f'已加入 {added} 名学生（重复的已跳过）',
        'added': added
    }, 200


def remove_class_student(operator_id, class_id, user_id, ip=None):
    """把学生移出班级。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM class_students
                WHERE class_id = %s AND user_id = %s
                """,
                (class_id, user_id)
            )

            affected = cursor.rowcount

            connection.commit()

    if not affected:
        return {'success': False, 'message': '该学生不在此班级中'}, 404

    write_log(
        operator_id, ROLE_ADMIN, 'class_remove_student', 'class', class_id,
        f'把用户 {user_id} 移出班级', ip
    )

    return {'success': True, 'message': '已移出班级'}, 200


def list_class_students(class_id):
    """班级学生名单。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.user_no, u.real_name, u.college, u.status,
                       cs.joined_at
                FROM class_students cs
                JOIN users u ON u.id = cs.user_id
                WHERE cs.class_id = %s
                ORDER BY u.user_no
                """,
                (class_id,)
            )

            return _stringify(cursor.fetchall())


def list_teacher_courses():
    """授课关系列表。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tc.id, tc.teacher_id, tc.course_id, tc.class_id, tc.term,
                    tc.created_at,
                    u.user_no AS teacher_no,
                    u.real_name AS teacher_name,
                    co.name AS course_name,
                    c.name AS class_name
                FROM teacher_courses tc
                LEFT JOIN users u ON u.id = tc.teacher_id
                LEFT JOIN courses co ON co.id = tc.course_id
                LEFT JOIN classes c ON c.id = tc.class_id
                ORDER BY tc.id DESC
                """
            )

            return _stringify(cursor.fetchall())


def add_teacher_course(operator_id, data, ip=None):
    """绑定教师到「课程 + 班级」。"""

    teacher_id = _int_or_none(data.get('teacher_id'))
    course_id = _int_or_none(data.get('course_id'))
    class_id = _int_or_none(data.get('class_id'))

    if not (teacher_id and course_id and class_id):
        return {
            'success': False,
            'message': 'teacher_id / course_id / class_id 均为必填'
        }, 400

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, role FROM users WHERE id = %s', (teacher_id,))

            teacher = cursor.fetchone()

            if not teacher:
                return {'success': False, 'message': '教师不存在'}, 404

            if teacher['role'] not in (ROLE_TEACHER, ROLE_ADMIN):
                return {
                    'success': False,
                    'message': '只能把教师或管理员绑定为授课教师'
                }, 400

            cursor.execute('SELECT id FROM courses WHERE id = %s', (course_id,))

            if not cursor.fetchone():
                return {'success': False, 'message': '课程不存在'}, 404

            cursor.execute('SELECT id FROM classes WHERE id = %s', (class_id,))

            if not cursor.fetchone():
                return {'success': False, 'message': '班级不存在'}, 404

            cursor.execute(
                """
                INSERT IGNORE INTO teacher_courses
                (teacher_id, course_id, class_id, term)
                VALUES (%s, %s, %s, %s)
                """,
                (teacher_id, course_id, class_id, _to_str(data.get('term'), 30))
            )

            if cursor.rowcount == 0:
                return {'success': False, 'message': '该授课关系已存在'}, 409

            link_id = cursor.lastrowid

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'teacher_course_add', 'teacher_course', link_id,
        f'绑定教师 {teacher_id} / 课程 {course_id} / 班级 {class_id}', ip
    )

    logger.info('新增授课关系 %s', link_id)

    return {'success': True, 'message': '授课关系已建立', 'link_id': link_id}, 200


def delete_teacher_course(operator_id, link_id, ip=None):
    """解除授课关系。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT teacher_id, course_id, class_id
                FROM teacher_courses
                WHERE id = %s
                """,
                (link_id,)
            )

            link = cursor.fetchone()

            if not link:
                return {'success': False, 'message': '授课关系不存在'}, 404

            cursor.execute('DELETE FROM teacher_courses WHERE id = %s', (link_id,))

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'teacher_course_delete', 'teacher_course', link_id,
        '解除教师 {} / 课程 {} / 班级 {} 的授课关系'.format(
            link['teacher_id'], link['course_id'], link['class_id']
        ), ip
    )

    logger.info('解除授课关系 %s', link_id)

    return {'success': True, 'message': '授课关系已解除'}, 200


# ============================================================
# 题库管理
# ============================================================

def list_questions(course_id=None, chapter_id=None, major=None, qtype=None,
                   verified=None, keyword=None, page=1, page_size=20):
    """题库列表（分页）。"""

    clauses = []
    params = []

    if course_id:
        clauses.append('q.course_id = %s')
        params.append(course_id)

    if chapter_id:
        clauses.append('q.chapter_id = %s')
        params.append(chapter_id)

    if major:
        clauses.append('q.major = %s')
        params.append(major)

    if qtype in QUESTION_TYPES:
        clauses.append('q.qtype = %s')
        params.append(qtype)

    if verified in (0, 1):
        clauses.append('q.verified = %s')
        params.append(verified)

    if keyword:
        clauses.append('(q.question LIKE %s OR q.kp_name LIKE %s)')
        like = f'%{keyword}%'
        params.extend([like, like])

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    offset = (page - 1) * page_size

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM question_bank q {where}',
                tuple(params)
            )

            total = cursor.fetchone()['total']

            cursor.execute(
                f"""
                SELECT
                    q.id, q.course_id, q.chapter_id, q.major, q.kp_name, q.qtype,
                    q.difficulty, q.question, q.options_json, q.answer,
                    q.analysis, q.source, q.verified, q.created_by, q.status,
                    q.created_at, q.updated_at,
                    co.name AS course_name,
                    u.real_name AS creator_name,
                    u.user_no AS creator_no
                FROM question_bank q
                LEFT JOIN courses co ON co.id = q.course_id
                LEFT JOIN users u ON u.id = q.created_by
                {where}
                ORDER BY q.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset])
            )

            items = cursor.fetchall()

    from backend.services import resource_service

    for item in items:
        item['options'] = resource_service.parse_options_json(item.get('options_json'))
        item['verified'] = int(item['verified'] or 0)

    return {
        'items': _stringify(items),
        'total': total,
        'page': page,
        'page_size': page_size
    }


def create_question(operator_id, data, ip=None):
    """新建题库题目（管理员录入默认 verified=1，审核人记为操作者）。"""

    question = _to_str(data.get('question'), 8000)

    if not question:
        return {'success': False, 'message': '题干不能为空'}, 400

    qtype = _to_str(data.get('qtype')) or 'choice'

    if qtype not in QUESTION_TYPES:
        return {'success': False, 'message': '题型不在允许范围内'}, 400

    difficulty = _int_or_none(data.get('difficulty')) or 2

    if difficulty not in (1, 2, 3):
        return {'success': False, 'message': '难度取值为 1/2/3'}, 400

    options = data.get('options_json')

    if isinstance(options, (list, dict)):
        import json as _json
        options = _json.dumps(options, ensure_ascii=False)

    verified = 1 if data.get('verified') in (None, 1, '1', True, 'true') else 0

    source = _to_str(data.get('source'), 50) or (
        'teacher' if verified else 'ai'
    )

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO question_bank
                (course_id, chapter_id, major, kp_name, qtype, difficulty,
                 question, options_json, answer, analysis, source, verified,
                 created_by, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _int_or_none(data.get('course_id')),
                    _int_or_none(data.get('chapter_id')),
                    _to_str(data.get('major'), 50) or '',
                    _to_str(data.get('kp_name'), 150) or '',
                    qtype,
                    difficulty,
                    question,
                    options,
                    _to_str(data.get('answer'), 8000),
                    _to_str(data.get('analysis'), 8000),
                    source,
                    verified,
                    operator_id,
                    1
                )
            )

            question_id = cursor.lastrowid

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'question_create', 'question_bank', question_id,
        f'新增题库题目（题型 {qtype}，verified={verified}）', ip
    )

    return {
        'success': True,
        'message': '题目已创建',
        'question_id': question_id,
        'verified': verified
    }, 200


def update_question(operator_id, question_id, data, ip=None):
    """更新题库题目；把 verified 改成 1 时记录审核人。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, verified, created_by FROM question_bank WHERE id = %s',
                (question_id,)
            )

            current = cursor.fetchone()

            if not current:
                return {'success': False, 'message': '题目不存在'}, 404

            updates = []
            params = []
            changes = []

            for key in QUESTION_WRITABLE:
                if key not in data:
                    continue

                value = data.get(key)

                if key in ('course_id', 'chapter_id', 'created_by'):
                    value = _int_or_none(value)
                elif key == 'difficulty':
                    value = _int_or_none(value) or 2

                    if value not in (1, 2, 3):
                        return {'success': False, 'message': '难度取值为 1/2/3'}, 400
                elif key == 'qtype':
                    value = _to_str(value)

                    if value not in QUESTION_TYPES:
                        return {'success': False, 'message': '题型不在允许范围内'}, 400
                elif key == 'status':
                    value = 1 if value in (1, '1', True, 'true') else 0
                elif key == 'question':
                    value = _to_str(value, 8000)

                    if not value:
                        return {'success': False, 'message': '题干不能为空'}, 400
                elif key in ('major', 'source'):
                    value = _to_str(value, 50)
                elif key == 'kp_name':
                    value = _to_str(value, 150)
                else:
                    value = _to_str(value, 8000)

                updates.append(f'{key} = %s')
                params.append(value)
                changes.append(key)

            if 'verified' in data:
                verified = 1 if data.get('verified') in (1, '1', True, 'true') else 0

                updates.append('verified = %s')
                params.append(verified)

                if verified == 1 and int(current['verified'] or 0) != 1:
                    # 记录审核人：谁把它标记为已审核
                    updates.append('created_by = %s')
                    params.append(operator_id)
                    changes.append('verified=1（审核人已记录）')
                else:
                    changes.append(f'verified={verified}')

            if not updates:
                return {'success': False, 'message': '没有需要更新的字段'}, 400

            params.append(question_id)

            cursor.execute(
                f"UPDATE question_bank SET {', '.join(updates)} WHERE id = %s",
                tuple(params)
            )

            affected = cursor.rowcount

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'question_update', 'question_bank', question_id,
        '修改题库题目：' + '、'.join(changes), ip
    )

    return {
        'success': True,
        'message': '题目已更新',
        'affected': affected
    }, 200


def delete_question(operator_id, question_id, ip=None):
    """删除题库题目（软删除：status=0；hard=True 时物理删除）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, LEFT(question, 60) AS question FROM question_bank WHERE id = %s',
                (question_id,)
            )

            row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': '题目不存在'}, 404

            cursor.execute(
                'UPDATE question_bank SET status = 0 WHERE id = %s',
                (question_id,)
            )

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'question_delete', 'question_bank', question_id,
        f"下架题目：{row['question']}", ip
    )

    return {'success': True, 'message': '题目已下架'}, 200


# ============================================================
# 统计
# ============================================================

def school_stats(scope_teacher_id=None):
    """全校（或教师授权范围内）统计。

    scope_teacher_id 为 None 时统计全校；
    否则只统计该教师 teacher_courses 覆盖的班级学生数据。
    """

    scope_sql = None
    scope_params = ()

    if scope_teacher_id:
        scope_sql = (
            'SELECT DISTINCT cs.user_id FROM class_students cs '
            'JOIN teacher_courses tc ON tc.class_id = cs.class_id '
            'WHERE tc.teacher_id = %s'
        )
        scope_params = (scope_teacher_id,)

    user_clause = ''
    wq_clause = ''
    practice_clause = ''
    # scope 过滤放在 WHERE 内层，因此外层 AND 的条件写法统一用 'WHERE 1=1'
    wq_where = ''
    user_params = ()
    wq_params = ()
    practice_params = ()

    if scope_sql:
        user_clause = f'WHERE id IN ({scope_sql})'
        user_params = scope_params
        wq_where = f'WHERE w.user_id IN ({scope_sql})'
        wq_clause = wq_where
        wq_params = scope_params
        practice_clause = f'WHERE pr.user_id IN ({scope_sql})'
        practice_params = scope_params

    with db_connection() as connection:
        with connection.cursor() as cursor:
            # 用户数与角色分布
            cursor.execute(
                f"""
                SELECT role, COUNT(*) AS total,
                       SUM(status = 1) AS active,
                       SUM(status = 0) AS frozen
                FROM users
                {user_clause}
                GROUP BY role
                """,
                tuple(user_params)
            )

            by_role = cursor.fetchall()

            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(status = 1) AS active,
                    SUM(status = 0) AS frozen
                FROM users
                {user_clause}
                """,
                tuple(user_params)
            )

            user_summary = cursor.fetchone() or {}

            # 错题总量与掌握情况
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS wrong_total,
                    COUNT(DISTINCT w.user_id) AS wrong_students,
                    SUM(w.mastery = 0) AS not_mastered,
                    SUM(w.mastery = 1) AS vague,
                    SUM(w.mastery = 2) AS mastered
                FROM wrong_questions w
                {wq_clause}
                """,
                tuple(wq_params)
            )

            wrong_summary = cursor.fetchone() or {}

            # 全校高频知识点
            cursor.execute(
                f"""
                SELECT
                    k.kp_name,
                    COUNT(*) AS total,
                    COUNT(DISTINCT w.user_id) AS student_count
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                {wq_clause}
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT 20
                """,
                tuple(wq_params)
            )

            top_knowledge_points = cursor.fetchall()

            # 错误类型分布
            cursor.execute(
                f"""
                SELECT w.error_type, COUNT(*) AS total
                FROM wrong_questions w
                {wq_where}
                {'AND' if wq_where else 'WHERE'} w.error_type <> ''
                GROUP BY w.error_type
                ORDER BY total DESC
                """,
                tuple(wq_params)
            )

            by_error_type = cursor.fetchall()

            # 资源使用情况
            cursor.execute(
                """
                SELECT rtype, COUNT(*) AS total, SUM(download_count) AS downloads
                FROM resources
                WHERE status = 1
                GROUP BY rtype
                ORDER BY total DESC
                """
            )

            resources_by_type = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(is_demo = 1) AS demo_count,
                    SUM(download_count) AS downloads
                FROM resources
                WHERE status = 1
                """
            )

            resource_summary = cursor.fetchone() or {}

            # 练习情况
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS times,
                    COUNT(DISTINCT pr.user_id) AS student_count,
                    AVG(pr.score) AS avg_score,
                    SUM(pr.total_count) AS total_questions,
                    SUM(pr.correct_count) AS correct_questions
                FROM practice_records pr
                {practice_clause}
                """,
                tuple(practice_params)
            )

            practice_summary = cursor.fetchone() or {}

            # 教学内容规模
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM courses WHERE status = 1) AS courses,
                    (SELECT COUNT(*) FROM chapters) AS chapters,
                    (SELECT COUNT(*) FROM knowledge_points) AS knowledge_points,
                    (SELECT COUNT(*) FROM classes) AS classes,
                    (SELECT COUNT(*) FROM teacher_courses) AS teacher_courses,
                    (SELECT COUNT(*) FROM question_bank WHERE status = 1) AS questions,
                    (SELECT COUNT(*) FROM learning_tasks WHERE status = 1) AS tasks,
                    (SELECT COUNT(*) FROM qa_questions) AS questions_asked,
                    (SELECT COUNT(*) FROM qa_questions WHERE status = 'answered') AS questions_answered,
                    (SELECT COUNT(*) FROM resources WHERE status = 1) AS resources
                """
            )

            teaching = cursor.fetchone() or {}

    wrong_total = int(wrong_summary.get('wrong_total') or 0)

    for row in by_role:
        row['total'] = int(row['total'] or 0)
        row['active'] = int(row['active'] or 0)
        row['frozen'] = int(row['frozen'] or 0)
        row['role_label'] = ROLE_LABELS.get(row['role'], row['role'])

    for row in by_error_type:
        row['percent'] = round(row['total'] / wrong_total * 100, 1) if wrong_total else 0.0

    for row in top_knowledge_points:
        row['total'] = int(row['total'] or 0)
        row['student_count'] = int(row['student_count'] or 0)

    from backend.services import resource_service

    for row in resources_by_type:
        row['rtype_label'] = resource_service.RESOURCE_TYPE_LABELS.get(
            row['rtype'], '其他'
        )
        row['total'] = int(row['total'] or 0)
        row['downloads'] = int(row['downloads'] or 0)

    practice_times = int(practice_summary.get('times') or 0)

    return {
        'scope': 'teacher' if scope_teacher_id else 'school',
        'scope_teacher_id': scope_teacher_id,
        'users': {
            'total': int(user_summary.get('total') or 0),
            'active': int(user_summary.get('active') or 0),
            'frozen': int(user_summary.get('frozen') or 0),
            'by_role': by_role
        },
        'wrong_questions': {
            'total': wrong_total,
            'students': int(wrong_summary.get('wrong_students') or 0),
            'not_mastered': int(wrong_summary.get('not_mastered') or 0),
            'vague': int(wrong_summary.get('vague') or 0),
            'mastered': int(wrong_summary.get('mastered') or 0),
            'mastery_rate': round(
                int(wrong_summary.get('mastered') or 0) / wrong_total * 100, 1
            ) if wrong_total else 0.0
        },
        'top_knowledge_points': top_knowledge_points,
        'by_error_type': by_error_type,
        'resources': {
            'total': int(resource_summary.get('total') or 0),
            'demo_count': int(resource_summary.get('demo_count') or 0),
            'downloads': int(resource_summary.get('downloads') or 0),
            'by_type': resources_by_type
        },
        'practice': {
            'times': practice_times,
            'students': int(practice_summary.get('student_count') or 0),
            'avg_score': round(float(practice_summary.get('avg_score')), 1)
            if practice_summary.get('avg_score') is not None else None,
            'total_questions': int(practice_summary.get('total_questions') or 0),
            'correct_questions': int(practice_summary.get('correct_questions') or 0),
            'accuracy': round(
                int(practice_summary.get('correct_questions') or 0)
                / int(practice_summary.get('total_questions') or 1) * 100, 1
            ) if int(practice_summary.get('total_questions') or 0) else None
        },
        'teaching': {key: int(value or 0) for key, value in teaching.items()},
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


# ============================================================
# 操作日志
# ============================================================

def list_logs(user_id=None, action=None, role=None, start_date=None,
              end_date=None, page=1, page_size=20):
    """操作日志（分页 + 多条件筛选）。"""

    clauses = []
    params = []

    if user_id:
        clauses.append('l.user_id = %s')
        params.append(user_id)

    if action:
        clauses.append('l.action LIKE %s')
        params.append(f'%{action}%')

    if role:
        clauses.append('l.role = %s')
        params.append(role)

    if start_date:
        clauses.append('l.created_at >= %s')
        params.append(f'{start_date} 00:00:00')

    if end_date:
        clauses.append('l.created_at <= %s')
        params.append(f'{end_date} 23:59:59')

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 20)))
    offset = (page - 1) * page_size

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM operation_logs l {where}',
                tuple(params)
            )

            total = cursor.fetchone()['total']

            cursor.execute(
                f"""
                SELECT
                    l.id, l.user_id, l.role, l.action, l.target_type,
                    l.target_id, l.detail, l.ip, l.status, l.created_at,
                    u.user_no, u.real_name
                FROM operation_logs l
                LEFT JOIN users u ON u.id = l.user_id
                {where}
                ORDER BY l.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset])
            )

            items = _stringify(cursor.fetchall())

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size
    }


# ============================================================
# 系统参数（system_settings）
# ============================================================

def list_settings():
    """读取所有非敏感系统参数（敏感键名直接跳过，不出现在返回结果里）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT setting_key, setting_value, description, updated_at
                FROM system_settings
                ORDER BY setting_key
                """
            )

            rows = cursor.fetchall()

    safe = []
    blocked = []

    for row in rows:
        if is_sensitive_key(row['setting_key']):
            blocked.append(row['setting_key'])
            continue

        safe.append({
            'setting_key': row['setting_key'],
            'setting_value': row['setting_value'],
            'description': row['description'],
            'updated_at': str(row['updated_at']) if row['updated_at'] else None
        })

    return {
        'items': safe,
        # 明确告知前端：这些键存在但被拒绝读写，绝不返回其值
        'blocked_keys': blocked,
        'blocked_hint': (
            '以下参数名包含 key/secret/password/token，属于敏感配置，'
            '一律不通过本接口读写，请直接修改 .env 文件'
        ) if blocked else ''
    }


def update_settings(operator_id, settings, ip=None):
    """写入非敏感系统参数。

    settings 为 {key: value} 或 [{setting_key, setting_value, description}]。
    命中敏感键名模式的一律拒绝，且不会写进日志。
    """

    if isinstance(settings, dict):
        items = [
            {'setting_key': key, 'setting_value': value}
            for key, value in settings.items()
        ]
    elif isinstance(settings, list):
        items = settings
    else:
        return {'success': False, 'message': 'settings 必须是对象或数组'}, 400

    if not items:
        return {'success': False, 'message': '没有需要更新的参数'}, 400

    rejected = []
    accepted = []

    for item in items:
        if not isinstance(item, dict):
            continue

        key = _to_str(item.get('setting_key') or item.get('key'), 64)

        if is_sensitive_key(key):
            rejected.append(key or '(空键名)')
            continue

        accepted.append({
            'setting_key': key,
            'setting_value': _to_str(item.get('setting_value'), 500),
            'description': _to_str(item.get('description'), 200)
        })

    if not accepted:
        return {
            'success': False,
            'message': (
                '这些参数属于敏感配置（模型密钥 / 数据库密码等），'
                '不允许通过接口读写：' + '、'.join(rejected)
            ),
            'rejected_keys': rejected,
            'code': 'SENSITIVE_SETTING_REJECTED'
        }, 403

    written = []

    with db_connection() as connection:
        with connection.cursor() as cursor:
            for item in accepted:
                cursor.execute(
                    """
                    INSERT INTO system_settings
                    (setting_key, setting_value, description)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        description = COALESCE(VALUES(description), description)
                    """,
                    (
                        item['setting_key'],
                        item['setting_value'],
                        item['description']
                    )
                )

                written.append(item['setting_key'])

            connection.commit()

    # 只记录键名，不记录值（避免把可能的敏感内容写进日志）
    write_log(
        operator_id, ROLE_ADMIN, 'settings_update', 'system_settings', None,
        '更新系统参数：' + '、'.join(written), ip
    )

    logger.info('管理员 %s 更新系统参数：%s', operator_id, written)

    return {
        'success': True,
        'message': f'已更新 {len(written)} 项参数',
        'updated_keys': written,
        'rejected_keys': rejected
    }, 200


# ============================================================
# 备份
# ============================================================

def find_mysqldump():
    """定位 mysqldump 可执行文件，找不到返回 None。"""

    found = shutil.which('mysqldump')

    if found:
        return found

    for candidate in MYSQLDUMP_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate

    return None


def check_mysqldump():
    """探测 mysqldump 是否可用（用于 GET /api/admin/backups 的提示）。"""

    path = find_mysqldump()

    if not path:
        return {
            'available': False,
            'path': None,
            'version': None,
            'message': '未找到 mysqldump，请确认 MySQL 客户端已安装并在 PATH 中'
        }

    version = None

    try:
        result = subprocess.run(
            [path, '--version'],
            capture_output=True,
            text=True,
            timeout=20
        )

        version = (result.stdout or result.stderr or '').strip()
    except Exception as exc:
        logger.warning('执行 mysqldump --version 失败: %s', exc)

    return {
        'available': True,
        'path': path,
        'version': version,
        'message': ''
    }


def create_backup(operator_id, ip=None):
    """真实执行 mysqldump 备份，并写入 backup_records。

    安全要点：数据库密码只通过 MYSQL_PWD 环境变量传递，绝不出现在命令行里。
    返回 (结果字典, 状态码)。
    """

    dump_path = find_mysqldump()

    if not dump_path:
        write_log(
            operator_id, ROLE_ADMIN, 'backup_failed', 'backup', None,
            '未找到 mysqldump 可执行文件', ip, status='failed'
        )

        return {
            'success': False,
            'message': '未找到 mysqldump，无法执行备份，请联系运维安装 MySQL 客户端'
        }, 500

    if not Config.DB_PASSWORD:
        write_log(
            operator_id, ROLE_ADMIN, 'backup_failed', 'backup', None,
            '数据库密码未配置（DB_PASSWORD 为空）', ip, status='failed'
        )

        return {
            'success': False,
            'message': '数据库密码未配置，无法执行备份'
        }, 500

    os.makedirs(BACKUP_DIR, exist_ok=True)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'{Config.DB_NAME}_{stamp}.sql'
    file_path = os.path.join(BACKUP_DIR, file_name)

    command = [
        dump_path,
        f'--host={Config.DB_HOST}',
        f'--port={Config.DB_PORT}',
        f'--user={Config.DB_USER}',
        '--single-transaction',
        '--default-character-set=utf8mb4',
        '--routines',
        '--events',
        '--result-file=' + file_path,
        Config.DB_NAME
    ]

    # 密码只走环境变量：进程命令行（可被其他用户看到）里不含任何密码
    env = dict(os.environ)
    env['MYSQL_PWD'] = Config.DB_PASSWORD

    try:
        result = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=600
        )
    except Exception as exc:
        logger.error('执行 mysqldump 失败: %s', exc)

        write_log(
            operator_id, ROLE_ADMIN, 'backup_failed', 'backup', None,
            f'mysqldump 执行异常：{exc}', ip, status='failed'
        )

        return {'success': False, 'message': f'备份执行失败：{exc}'}, 500

    if result.returncode != 0:
        stderr = (result.stderr or '').strip()[:300]

        logger.error('mysqldump 返回非零退出码 %s: %s', result.returncode, stderr)

        # 失败时清理半成品文件，避免留下不可用的备份
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except OSError:
            pass

        write_log(
            operator_id, ROLE_ADMIN, 'backup_failed', 'backup', None,
            f'mysqldump 退出码 {result.returncode}：{stderr}', ip, status='failed'
        )

        return {
            'success': False,
            'message': f'备份失败（mysqldump 退出码 {result.returncode}）：{stderr}'
        }, 500

    file_size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO backup_records
                (file_name, file_size, method, operator_id)
                VALUES (%s, %s, 'mysqldump', %s)
                """,
                (file_name, file_size, operator_id)
            )

            record_id = cursor.lastrowid

            connection.commit()

    write_log(
        operator_id, ROLE_ADMIN, 'backup_create', 'backup', record_id,
        f'数据库备份成功：{file_name}（{file_size} 字节）', ip
    )

    logger.info('数据库备份成功: %s（%s 字节）', file_name, file_size)

    return {
        'success': True,
        'message': f'备份完成：{file_name}',
        'backup_id': record_id,
        'file_name': file_name,
        'file_size': file_size,
        'file_path': file_path
    }, 200


def list_backups():
    """备份记录 + 磁盘上真实存在的备份文件。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    b.id, b.file_name, b.file_size, b.method, b.operator_id,
                    b.created_at,
                    u.user_no AS operator_no,
                    u.real_name AS operator_name
                FROM backup_records b
                LEFT JOIN users u ON u.id = b.operator_id
                ORDER BY b.id DESC
                LIMIT 200
                """
            )

            records = _stringify(cursor.fetchall())

    recorded = {row['file_name'] for row in records}

    files = []

    if os.path.isdir(BACKUP_DIR):
        for name in sorted(os.listdir(BACKUP_DIR)):
            full = os.path.join(BACKUP_DIR, name)

            if not os.path.isfile(full):
                continue

            files.append({
                'file_name': name,
                'file_size': os.path.getsize(full),
                'modified_at': datetime.fromtimestamp(
                    os.path.getmtime(full)
                ).strftime('%Y-%m-%d %H:%M:%S'),
                'in_records': name in recorded
            })

    return {
        'records': records,
        'files': files,
        'backup_dir': BACKUP_DIR,
        'record_count': len(records),
        'file_count': len(files),
        'tool': check_mysqldump()
    }


# ============================================================
# 单点登录（SSO）配置探测 —— 仅预留，不实现
# ============================================================

# 说明：本函数只读取环境变量并报告是否已配置，
# 不提供任何真实的 SSO 登录流程（项目当前没有对接学校统一身份认证）。
SSO_ENV_KEYS = (
    'SSO_ENABLED',
    'SSO_PROVIDER',
    'SSO_LOGIN_URL',
    'SSO_CLIENT_ID',
    'SSO_METADATA_URL',
    'SSO_CALLBACK_URL'
)

SSO_IMPLEMENTED = False


def sso_config():
    """返回 SSO 的配置状态（不含任何密钥值）。"""

    enabled = str(os.getenv('SSO_ENABLED', '')).strip().lower() in (
        '1', 'true', 'yes', 'on'
    )

    provider = os.getenv('SSO_PROVIDER')
    login_url = os.getenv('SSO_LOGIN_URL')
    callback_url = os.getenv('SSO_CALLBACK_URL')

    configured = bool(enabled and provider and login_url)

    return {
        'enabled': enabled,
        'configured': configured,
        # 是否已经对接完成：当前项目明确为“未实现”，只预留配置位
        'implemented': SSO_IMPLEMENTED,
        'provider': provider,
        'login_url': login_url,
        'callback_url': callback_url,
        'client_id_configured': bool(os.getenv('SSO_CLIENT_ID')),
        'metadata_url_configured': bool(os.getenv('SSO_METADATA_URL')),
        'env_keys': list(SSO_ENV_KEYS),
        'message': (
            '学校统一身份认证（SSO）尚未实现，当前仅预留配置位，'
            '请勿把此接口当作可用的登录入口。'
            if not SSO_IMPLEMENTED else 'SSO 已启用'
        )
    }

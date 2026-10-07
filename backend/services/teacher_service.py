# -*- coding: utf-8 -*-
"""教师端数据服务（模块八：师生互动；模块九：学情分析与可视化报表）。

分层约定：
- 本模块只负责 SQL 与业务判断，不导入 Flask 请求对象；
- 所有权限判断都在 SQL 中完成，绝不信任前端传入的 id；
  教师必须通过 teacher_courses 与目标班级/课程建立关联才可读写，
  管理员（is_admin=True）在全校范围内不受限制。

所有查询都使用 %s 占位符，动态列名一律走白名单。
"""

from backend.extensions.database import db_connection
from backend.utils.logging_config import get_logger
from backend.utils.security import ROLE_ADMIN, ROLE_TEACHER


logger = get_logger('teacher')


# ============================================================
# 常量
# ============================================================

# 掌握度取值与文案（与 study_service.MASTERY_LABELS 保持一致）
MASTERY_LABELS = {
    0: '未掌握',
    1: '模糊',
    2: '已掌握'
}

# 允许的错误类型（与 ai_service.ERROR_TYPES 保持一致，服务层独立校验）
ALLOWED_ERROR_TYPES = {
    '概念理解错误',
    '计算错误',
    '步骤错误',
    '审题错误',
    '公式使用错误',
    '方法选择不当',
    '格式不规范',
    '无明显错误'
}

# 发布的通知标题前缀：错题讲解通知复用 learning_tasks，不新建表
NOTICE_TITLE_PREFIX = '【错题讲解通知】'

# 答疑状态取值
QA_STATUSES = ('open', 'answered', 'closed')

# 错题标注可更新的列（白名单，杜绝拼接客户端传来的列名）
WRONG_QUESTION_UPDATABLE = {
    'knowledge_points',
    'error_type',
    'mastery',
    'analysis',
    'standard_answer'
}

# 任务完成度统计口径
# 注意：学生从未开始任务时，learning_tasks 关联的 task_submissions 可能
# 根本没有行（历史数据），因此除了 pending 还要处理“无记录”的情况。
TASK_STATUS_LABELS = {
    'done': '已完成',
    'pending': '未完成',
    'not_started': '未开始'
}


# ============================================================
# 内部工具
# ============================================================

def _is_admin(role):
    """角色是否为管理员。"""

    return role == ROLE_ADMIN


def _stringify_datetimes(rows, keys=('created_at', 'updated_at',
                                     'due_at', 'submitted_at',
                                     'last_review_at', 'joined_at')):
    """把 datetime 统一转成字符串，便于 JSON 序列化。"""

    for row in rows or []:
        for key in keys:
            if row.get(key) is not None:
                row[key] = str(row[key])

    return rows


def _zero_fill_mastery(counts):
    """把掌握度计数补全为 0/1/2 三档，缺失档位补 0（不是编造，是口径固定）。"""

    mapped = {int(item['mastery']): int(item['total']) for item in counts
              if item.get('mastery') is not None}

    return [
        {
            'mastery': level,
            'label': MASTERY_LABELS[level],
            'total': mapped.get(level, 0)
        }
        for level in (0, 1, 2)
    ]


# ============================================================
# 权限：SQL 层面的关联校验
# ============================================================

def teacher_class_ids(teacher_id, is_admin=False):
    """当前教师被授权的班级 ID 列表（管理员为 None，表示不限制）。"""

    if is_admin:
        return None

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT class_id
                FROM teacher_courses
                WHERE teacher_id = %s AND class_id IS NOT NULL
                """,
                (teacher_id,)
            )

            return [row['class_id'] for row in cursor.fetchall()]


def teacher_course_ids(teacher_id, is_admin=False):
    """当前教师被授权的课程 ID 列表（管理员为 None，表示不限制）。"""

    if is_admin:
        return None

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT course_id
                FROM teacher_courses
                WHERE teacher_id = %s AND course_id IS NOT NULL
                """,
                (teacher_id,)
            )

            return [row['course_id'] for row in cursor.fetchall()]


def can_access_class(teacher_id, class_id, is_admin=False):
    """教师是否被授权访问该班级（SQL 实测，非前端隐藏按钮）。"""

    if is_admin:
        return True

    if not class_id:
        return False

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM teacher_courses
                WHERE teacher_id = %s AND class_id = %s
                LIMIT 1
                """,
                (teacher_id, class_id)
            )

            return cursor.fetchone() is not None


def can_access_student(teacher_id, student_id, is_admin=False):
    """教师是否被授权查看该学生。

    判定依据：存在一条 teacher_courses 记录，其 class_id 同时出现在
    该学生的 class_students 记录中。管理员直接放行。
    """

    if is_admin:
        return True

    if not student_id:
        return False

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM teacher_courses tc
                JOIN class_students cs ON cs.class_id = tc.class_id
                WHERE tc.teacher_id = %s AND cs.user_id = %s
                LIMIT 1
                """,
                (teacher_id, student_id)
            )

            return cursor.fetchone() is not None


def can_access_course(teacher_id, course_id, is_admin=False):
    """教师是否被授权访问该课程。"""

    if is_admin:
        return True

    if not course_id:
        return False

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM teacher_courses
                WHERE teacher_id = %s AND course_id = %s
                LIMIT 1
                """,
                (teacher_id, course_id)
            )

            return cursor.fetchone() is not None


def can_access_wrong_question(teacher_id, question_id, is_admin=False):
    """教师是否被授权修改该错题（错题归属的学生必须在自己的班级里）。"""

    if is_admin:
        return True

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT w.id, w.user_id
                FROM wrong_questions w
                JOIN teacher_courses tc ON tc.teacher_id = %s
                JOIN class_students cs
                     ON cs.user_id = w.user_id AND cs.class_id = tc.class_id
                WHERE w.id = %s
                LIMIT 1
                """,
                (teacher_id, question_id)
            )

            return cursor.fetchone()


# ============================================================
# 班级与学生
# ============================================================

def list_classes(teacher_id, is_admin=False):
    """教师可见的班级列表（附带本人授课课程数与班级人数）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            if is_admin:
                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.name,
                        c.college,
                        c.grade_year,
                        c.remark,
                        c.created_at,
                        (SELECT COUNT(*) FROM class_students cs
                          WHERE cs.class_id = c.id) AS student_count,
                        (SELECT COUNT(DISTINCT tc.course_id)
                           FROM teacher_courses tc
                          WHERE tc.class_id = c.id) AS course_count
                    FROM classes c
                    ORDER BY c.id DESC
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.name,
                        c.college,
                        c.grade_year,
                        c.remark,
                        c.created_at,
                        tc.course_id,
                        co.name AS course_name,
                        tc.term,
                        (SELECT COUNT(*) FROM class_students cs
                          WHERE cs.class_id = c.id) AS student_count
                    FROM teacher_courses tc
                    JOIN classes c ON c.id = tc.class_id
                    LEFT JOIN courses co ON co.id = tc.course_id
                    WHERE tc.teacher_id = %s
                    ORDER BY c.id DESC, tc.course_id
                    """,
                    (teacher_id,)
                )

            rows = cursor.fetchall()

    if is_admin:
        return _stringify_datetimes(rows)

    # 教师视角：按班级聚合，附带授课课程列表
    classes = {}
    order = []

    for row in rows:
        class_id = row['id']

        if class_id not in classes:
            classes[class_id] = {
                'id': class_id,
                'name': row['name'],
                'college': row['college'],
                'grade_year': row['grade_year'],
                'remark': row['remark'],
                'created_at': str(row['created_at']) if row['created_at'] else None,
                'student_count': row['student_count'],
                'courses': []
            }
            order.append(class_id)

        if row.get('course_id'):
            classes[class_id]['courses'].append({
                'course_id': row['course_id'],
                'course_name': row.get('course_name'),
                'term': row.get('term')
            })

    return [classes[class_id] for class_id in order]


def list_students(teacher_id, class_id, is_admin=False):
    """某班级的学生名单（要求教师已获授权）。

    返回 None 表示无权访问，调用方据此返回 403。
    """

    if not can_access_class(teacher_id, class_id, is_admin):
        return None

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.id,
                    u.user_no,
                    u.real_name,
                    u.college,
                    u.email,
                    u.status,
                    u.avatar_path,
                    cs.joined_at,
                    (SELECT COUNT(*) FROM wrong_questions w
                      WHERE w.user_id = u.id) AS wrong_count,
                    (SELECT COUNT(*) FROM practice_records pr
                      WHERE pr.user_id = u.id) AS practice_count
                FROM class_students cs
                JOIN users u ON u.id = cs.user_id
                WHERE cs.class_id = %s
                ORDER BY u.user_no
                """,
                (class_id,)
            )

            rows = cursor.fetchall()

    return _stringify_datetimes(rows)


def list_teacher_courses(teacher_id, is_admin=False):
    """教师本人的授课关系（班级 + 课程），用于前端筛选下拉框。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            if is_admin:
                cursor.execute(
                    """
                    SELECT
                        tc.id,
                        tc.teacher_id,
                        tc.course_id,
                        tc.class_id,
                        tc.term,
                        co.name AS course_name,
                        co.major AS course_major,
                        c.name AS class_name,
                        u.real_name AS teacher_name,
                        u.user_no AS teacher_no
                    FROM teacher_courses tc
                    LEFT JOIN courses co ON co.id = tc.course_id
                    LEFT JOIN classes c ON c.id = tc.class_id
                    LEFT JOIN users u ON u.id = tc.teacher_id
                    ORDER BY tc.id DESC
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        tc.id,
                        tc.course_id,
                        tc.class_id,
                        tc.term,
                        co.name AS course_name,
                        co.major AS course_major,
                        c.name AS class_name
                    FROM teacher_courses tc
                    LEFT JOIN courses co ON co.id = tc.course_id
                    LEFT JOIN classes c ON c.id = tc.class_id
                    WHERE tc.teacher_id = %s
                    ORDER BY tc.id DESC
                    """,
                    (teacher_id,)
                )

            return cursor.fetchall()


# ============================================================
# 模块九：学情报表
# ============================================================

def student_report(teacher_id, student_id, course_id=None, is_admin=False):
    """单个学生的真实学情报告。

    返回 None 表示该教师无权查看此学生（学生不在其班级内）。
    所有数字都来自 wrong_questions / wrong_question_kps / practice_records，
    没有任何估算或造数。
    """

    if not can_access_student(teacher_id, student_id, is_admin):
        return None

    # 课程过滤条件：可选，全部使用占位符
    wq_clause = 'w.user_id = %s'
    wq_params = [student_id]

    if course_id:
        wq_clause += ' AND w.course_id = %s'
        wq_params.append(course_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            # 学生基本信息
            cursor.execute(
                """
                SELECT id, user_no, real_name, college, email, status,
                       avatar_path, created_at
                FROM users
                WHERE id = %s
                """,
                (student_id,)
            )

            student = cursor.fetchone()

            if not student:
                return None

            # 总览
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(w.mastery = 0) AS not_mastered,
                    SUM(w.mastery = 1) AS vague,
                    SUM(w.mastery = 2) AS mastered,
                    SUM(w.review_count > 0) AS reviewed
                FROM wrong_questions w
                WHERE {wq_clause}
                """,
                tuple(wq_params)
            )

            summary = cursor.fetchone() or {}

            # 错误类型分布
            cursor.execute(
                f"""
                SELECT w.error_type, COUNT(*) AS total
                FROM wrong_questions w
                WHERE {wq_clause} AND w.error_type <> ''
                GROUP BY w.error_type
                ORDER BY total DESC
                """,
                tuple(wq_params)
            )

            by_error_type = cursor.fetchall()

            # 掌握度分布
            cursor.execute(
                f"""
                SELECT w.mastery, COUNT(*) AS total
                FROM wrong_questions w
                WHERE {wq_clause}
                GROUP BY w.mastery
                ORDER BY w.mastery
                """,
                tuple(wq_params)
            )

            by_mastery = _zero_fill_mastery(cursor.fetchall())

            # 知识点薄弱排行
            cursor.execute(
                f"""
                SELECT
                    k.kp_name,
                    COUNT(*) AS total,
                    SUM(w.mastery = 2) AS mastered,
                    SUM(w.mastery = 0) AS not_mastered
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE {wq_clause}
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT 20
                """,
                tuple(wq_params)
            )

            weak_points = cursor.fetchall()

            # 练习历史
            practice_clause = 'pr.user_id = %s'
            practice_params = [student_id]

            if course_id:
                practice_clause += ' AND p.course_id = %s'
                practice_params.append(course_id)

            cursor.execute(
                f"""
                SELECT
                    pr.id,
                    pr.paper_id,
                    p.title,
                    p.major,
                    p.source,
                    pr.total_count,
                    pr.correct_count,
                    pr.graded_count,
                    pr.score,
                    pr.submitted_at
                FROM practice_records pr
                LEFT JOIN practice_papers p ON p.id = pr.paper_id
                WHERE {practice_clause}
                ORDER BY pr.submitted_at DESC, pr.id DESC
                LIMIT 50
                """,
                tuple(practice_params)
            )

            practice_history = cursor.fetchall()

            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS times,
                    AVG(pr.score) AS avg_score,
                    MAX(pr.score) AS best_score,
                    SUM(pr.total_count) AS total_questions,
                    SUM(pr.correct_count) AS correct_questions
                FROM practice_records pr
                LEFT JOIN practice_papers p ON p.id = pr.paper_id
                WHERE {practice_clause}
                """,
                tuple(practice_params)
            )

            practice_summary = cursor.fetchone() or {}

            # 任务完成情况
            cursor.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    t.due_at,
                    s.status,
                    s.score,
                    s.submitted_at
                FROM learning_tasks t
                JOIN class_students cs
                     ON cs.class_id = t.class_id AND cs.user_id = %s
                LEFT JOIN task_submissions s
                     ON s.task_id = t.id AND s.student_id = %s
                WHERE t.status = 1
                ORDER BY t.created_at DESC
                LIMIT 50
                """,
                (student_id, student_id)
            )

            tasks = cursor.fetchall()

    total = int(summary.get('total') or 0)
    mastered = int(summary.get('mastered') or 0)
    times = int(practice_summary.get('times') or 0)

    # 错误类型占比的分母只算已标注错误类型的错题，保证占比之和为 100%
    typed_total = sum(int(row['total'] or 0) for row in by_error_type)

    for row in by_error_type:
        row['total'] = int(row['total'] or 0)
        row['percent'] = round(row['total'] / typed_total * 100, 1) \
            if typed_total else 0.0

    for row in weak_points:
        row['total'] = int(row['total'] or 0)
        row['mastered'] = int(row['mastered'] or 0)
        row['not_mastered'] = int(row['not_mastered'] or 0)

    return {
        'student': _stringify_datetimes([student])[0],
        'summary': {
            'wrong_total': total,
            'mastered': mastered,
            'not_mastered': int(summary.get('not_mastered') or 0),
            'vague': int(summary.get('vague') or 0),
            'reviewed': int(summary.get('reviewed') or 0),
            'mastery_rate': round(mastered / total * 100, 1) if total else 0.0
        },
        'by_error_type': by_error_type,
        'by_mastery': by_mastery,
        'weak_points': weak_points,
        'practice_history': _stringify_datetimes(practice_history),
        'practice_summary': {
            'times': times,
            'avg_score': round(float(practice_summary.get('avg_score')), 1)
            if practice_summary.get('avg_score') is not None else None,
            'best_score': round(float(practice_summary.get('best_score')), 1)
            if practice_summary.get('best_score') is not None else None,
            'total_questions': int(practice_summary.get('total_questions') or 0),
            'correct_questions': int(practice_summary.get('correct_questions') or 0)
        },
        'tasks': _stringify_datetimes(tasks)
    }


def class_report(teacher_id, class_id, course_id=None, days=30, is_admin=False):
    """班级层面的真实聚合报表。

    返回 None 表示该班级不在当前教师的授权范围内。
    days 控制“近期”窗口（按 wrong_questions.created_at 过滤）。
    """

    if not can_access_class(teacher_id, class_id, is_admin):
        return None

    days = max(1, min(int(days or 30), 3650))

    # 班级学生子查询（后续所有统计都以这批学生为范围）
    scope_sql = (
        'SELECT cs.user_id FROM class_students cs WHERE cs.class_id = %s'
    )
    scope_params = [class_id]

    wq_clause = f'w.user_id IN ({scope_sql})'
    wq_params = list(scope_params)

    if course_id:
        wq_clause += ' AND w.course_id = %s'
        wq_params.append(course_id)

    recent_clause = wq_clause + ' AND w.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)'
    recent_params = wq_params + [days]

    with db_connection() as connection:
        with connection.cursor() as cursor:
            # 班级概况
            cursor.execute(
                """
                SELECT
                    c.id, c.name, c.college, c.grade_year, c.remark, c.created_at,
                    (SELECT COUNT(*) FROM class_students cs
                      WHERE cs.class_id = c.id) AS student_count
                FROM classes c
                WHERE c.id = %s
                """,
                (class_id,)
            )

            klass = cursor.fetchone()

            if not klass:
                return None

            # 总览（错题数 / 参与学生数 / 掌握情况 / 复习次数）
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS wrong_total,
                    COUNT(DISTINCT w.user_id) AS wrong_students,
                    SUM(w.mastery = 0) AS not_mastered,
                    SUM(w.mastery = 1) AS vague,
                    SUM(w.mastery = 2) AS mastered,
                    SUM(w.review_count) AS review_total
                FROM wrong_questions w
                WHERE {wq_clause}
                """,
                tuple(wq_params)
            )

            summary = cursor.fetchone() or {}

            # 高频错题（题目原文 + 出现人次）
            cursor.execute(
                f"""
                SELECT
                    w.question,
                    w.major,
                    w.sub,
                    COUNT(*) AS total,
                    COUNT(DISTINCT w.user_id) AS student_count,
                    MAX(w.error_type) AS error_type
                FROM wrong_questions w
                WHERE {wq_clause}
                GROUP BY w.question, w.major, w.sub
                ORDER BY total DESC, student_count DESC
                LIMIT 20
                """,
                tuple(wq_params)
            )

            top_questions = cursor.fetchall()

            # 知识点错误分布
            cursor.execute(
                f"""
                SELECT
                    k.kp_name,
                    COUNT(*) AS total,
                    COUNT(DISTINCT w.user_id) AS student_count,
                    SUM(w.mastery = 2) AS mastered,
                    SUM(w.mastery = 0) AS not_mastered
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE {wq_clause}
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT 20
                """,
                tuple(wq_params)
            )

            by_knowledge_point = cursor.fetchall()

            # 错误类型分布
            cursor.execute(
                f"""
                SELECT w.error_type, COUNT(*) AS total
                FROM wrong_questions w
                WHERE {wq_clause} AND w.error_type <> ''
                GROUP BY w.error_type
                ORDER BY total DESC
                """,
                tuple(wq_params)
            )

            by_error_type = cursor.fetchall()

            # 掌握度分布
            cursor.execute(
                f"""
                SELECT w.mastery, COUNT(*) AS total
                FROM wrong_questions w
                WHERE {wq_clause}
                GROUP BY w.mastery
                ORDER BY w.mastery
                """,
                tuple(wq_params)
            )

            by_mastery = _zero_fill_mastery(cursor.fetchall())

            # 近期趋势（按天聚合真实新增错题数）
            cursor.execute(
                f"""
                SELECT DATE(w.created_at) AS day, COUNT(*) AS total
                FROM wrong_questions w
                WHERE {recent_clause}
                GROUP BY DATE(w.created_at)
                ORDER BY day
                """,
                tuple(recent_params)
            )

            trend = cursor.fetchall()

            # 任务完成情况（未开始的学生也要出现，因此以 class_students 为左表）
            cursor.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    t.course_id,
                    co.name AS course_name,
                    t.due_at,
                    t.created_at,
                    COUNT(DISTINCT cs.user_id) AS student_total,
                    COUNT(DISTINCT CASE WHEN s.status = 'done'
                           THEN s.student_id END) AS done_count,
                    AVG(CASE WHEN s.status = 'done' THEN s.score END) AS avg_score
                FROM learning_tasks t
                JOIN class_students cs ON cs.class_id = t.class_id
                LEFT JOIN task_submissions s
                     ON s.task_id = t.id AND s.student_id = cs.user_id
                LEFT JOIN courses co ON co.id = t.course_id
                WHERE t.class_id = %s AND t.status = 1
                GROUP BY t.id, t.title, t.course_id, co.name, t.due_at, t.created_at
                ORDER BY t.created_at DESC
                LIMIT 50
                """,
                (class_id,)
            )

            tasks = cursor.fetchall()

            # 练习情况（真实 practice_records）
            practice_clause = f'pr.user_id IN ({scope_sql})'
            practice_params = list(scope_params)

            if course_id:
                practice_clause += ' AND p.course_id = %s'
                practice_params.append(course_id)

            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS times,
                    COUNT(DISTINCT pr.user_id) AS student_count,
                    AVG(pr.score) AS avg_score,
                    MAX(pr.score) AS best_score,
                    SUM(pr.total_count) AS total_questions,
                    SUM(pr.correct_count) AS correct_questions
                FROM practice_records pr
                LEFT JOIN practice_papers p ON p.id = pr.paper_id
                WHERE {practice_clause}
                """,
                tuple(practice_params)
            )

            practice_summary = cursor.fetchone() or {}

            # 学生个体对比（错题数 + 平均分）
            cursor.execute(
                f"""
                SELECT
                    u.id,
                    u.user_no,
                    u.real_name,
                    (SELECT COUNT(*) FROM wrong_questions w
                      WHERE w.user_id = u.id
                        {'AND w.course_id = %s' if course_id else ''}) AS wrong_total,
                    (SELECT COUNT(*) FROM wrong_questions w
                      WHERE w.user_id = u.id AND w.mastery = 2
                        {'AND w.course_id = %s' if course_id else ''}) AS mastered_total
                FROM class_students cs
                JOIN users u ON u.id = cs.user_id
                WHERE cs.class_id = %s
                ORDER BY wrong_total DESC, u.user_no
                """,
                tuple(
                    ([course_id, course_id] if course_id else []) + [class_id]
                )
            )

            students = cursor.fetchall()

    wrong_total = int(summary.get('wrong_total') or 0)

    # 错误类型占比的分母是「已标注错误类型的错题数」，
    # 否则未标注的错题会让各项占比之和小于 100%，看起来像统计出错。
    typed_total = sum(int(row['total'] or 0) for row in by_error_type)

    for row in by_error_type:
        row['total'] = int(row['total'] or 0)
        row['percent'] = round(row['total'] / typed_total * 100, 1) \
            if typed_total else 0.0

    for row in by_knowledge_point:
        row['total'] = int(row['total'] or 0)
        row['student_count'] = int(row['student_count'] or 0)
        row['mastered'] = int(row['mastered'] or 0)
        row['not_mastered'] = int(row['not_mastered'] or 0)

    for row in tasks:
        total = int(row['student_total'] or 0)
        done = int(row['done_count'] or 0)

        row['student_total'] = total
        row['done_count'] = done
        row['pending_count'] = max(total - done, 0)
        row['rate'] = round(done / total * 100, 1) if total else 0.0
        row['avg_score'] = round(float(row['avg_score']), 1) \
            if row['avg_score'] is not None else None

    for row in students:
        row['wrong_total'] = int(row['wrong_total'] or 0)
        row['mastered_total'] = int(row['mastered_total'] or 0)
        row['mastery_rate'] = round(
            row['mastered_total'] / row['wrong_total'] * 100, 1
        ) if row['wrong_total'] else 0.0

    for row in trend:
        row['day'] = str(row['day'])
        row['total'] = int(row['total'] or 0)

    return {
        'class': _stringify_datetimes([klass])[0],
        'course_id': course_id,
        'days': days,
        'summary': {
            'wrong_total': wrong_total,
            'wrong_students': int(summary.get('wrong_students') or 0),
            'not_mastered': int(summary.get('not_mastered') or 0),
            'vague': int(summary.get('vague') or 0),
            'mastered': int(summary.get('mastered') or 0),
            'mastery_rate': round(
                int(summary.get('mastered') or 0) / wrong_total * 100, 1
            ) if wrong_total else 0.0,
            'review_total': int(summary.get('review_total') or 0),
            'practice_times': int(practice_summary.get('times') or 0),
            'practice_students': int(practice_summary.get('student_count') or 0),
            'practice_avg_score': round(float(practice_summary.get('avg_score')), 1)
            if practice_summary.get('avg_score') is not None else None,
            'practice_total_questions': int(
                practice_summary.get('total_questions') or 0
            ),
            'practice_correct_questions': int(
                practice_summary.get('correct_questions') or 0
            )
        },
        'top_questions': _stringify_datetimes(top_questions, keys=()),
        'by_knowledge_point': by_knowledge_point,
        'by_error_type': by_error_type,
        'by_mastery': by_mastery,
        'trend': trend,
        'tasks': _stringify_datetimes(tasks),
        'students': students
    }


# ============================================================
# 复习任务与通知
# ============================================================

def create_task(teacher_id, class_id, course_id, title, content=None,
                paper_id=None, due_at=None, is_admin=False):
    """发布复习任务。返回 (结果字典, HTTP 状态码)。"""

    if not can_access_class(teacher_id, class_id, is_admin):
        return {
            'success': False,
            'message': '该班级不在你的授课范围内，无法发布任务'
        }, 403

    title = (title or '').strip()

    if not title:
        return {'success': False, 'message': '任务标题不能为空'}, 400

    if course_id and not can_access_course(teacher_id, course_id, is_admin):
        return {
            'success': False,
            'message': '该课程不在你的授课范围内'
        }, 403

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_tasks
                (teacher_id, class_id, course_id, title, content,
                 paper_id, due_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    teacher_id,
                    class_id,
                    course_id,
                    title[:150],
                    content,
                    paper_id,
                    due_at
                )
            )

            task_id = cursor.lastrowid

            # 为班级内每位学生建立待完成记录（未开始的学生也要能在完成情况里看到）
            cursor.execute(
                """
                INSERT IGNORE INTO task_submissions
                (task_id, student_id, paper_id, status)
                SELECT %s, cs.user_id, %s, 'pending'
                FROM class_students cs
                WHERE cs.class_id = %s
                """,
                (task_id, paper_id, class_id)
            )

            created = cursor.rowcount

            connection.commit()

    logger.info(
        '教师 %s 向班级 %s 发布任务 %s（预置 %s 名学生）',
        teacher_id, class_id, task_id, created
    )

    return {
        'success': True,
        'message': '任务已发布',
        'task_id': task_id,
        'student_count': created
    }, 200


def create_notice(teacher_id, class_id, title, content, course_id=None,
                  is_admin=False):
    """发布错题讲解通知（复用 learning_tasks，不新建表）。

    标题统一加上 NOTICE_TITLE_PREFIX 前缀，便于与普通复习任务区分。
    """

    if not can_access_class(teacher_id, class_id, is_admin):
        return {
            'success': False,
            'message': '该班级不在你的授课范围内，无法发布通知'
        }, 403

    content = (content or '').strip()

    if not content:
        return {'success': False, 'message': '通知内容不能为空'}, 400

    raw_title = (title or '错题讲解').strip()
    title = f'{NOTICE_TITLE_PREFIX}{raw_title}'[:150]

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_tasks
                (teacher_id, class_id, course_id, title, content, status)
                VALUES (%s, %s, %s, %s, %s, 1)
                """,
                (teacher_id, class_id, course_id, title, content)
            )

            notice_id = cursor.lastrowid

            connection.commit()

    logger.info('教师 %s 向班级 %s 发布错题讲解通知 %s', teacher_id, class_id, notice_id)

    return {
        'success': True,
        'message': '通知已发布',
        'notice_id': notice_id,
        'title': title
    }, 200


def list_tasks(teacher_id, class_id=None, is_admin=False):
    """教师发布的任务列表（含每位学生的完成统计）。"""

    clauses = []
    params = []

    if not is_admin:
        clauses.append('t.teacher_id = %s')
        params.append(teacher_id)

    if class_id:
        clauses.append('t.class_id = %s')
        params.append(class_id)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    t.id,
                    t.title,
                    t.content,
                    t.class_id,
                    c.name AS class_name,
                    t.course_id,
                    co.name AS course_name,
                    t.paper_id,
                    t.due_at,
                    t.status,
                    t.created_at,
                    (SELECT COUNT(*) FROM class_students cs
                      WHERE cs.class_id = t.class_id) AS student_total,
                    (SELECT COUNT(*) FROM task_submissions s
                      WHERE s.task_id = t.id AND s.status = 'done') AS done_count,
                    (SELECT AVG(s.score) FROM task_submissions s
                      WHERE s.task_id = t.id AND s.status = 'done') AS avg_score
                FROM learning_tasks t
                LEFT JOIN classes c ON c.id = t.class_id
                LEFT JOIN courses co ON co.id = t.course_id
                {where}
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT 200
                """,
                tuple(params)
            )

            rows = cursor.fetchall()

    for row in rows:
        total = int(row['student_total'] or 0)
        done = int(row['done_count'] or 0)

        row['student_total'] = total
        row['done_count'] = done
        row['pending_count'] = max(total - done, 0)
        row['rate'] = round(done / total * 100, 1) if total else 0.0
        row['avg_score'] = round(float(row['avg_score']), 1) \
            if row['avg_score'] is not None else None
        row['is_notice'] = str(row['title'] or '').startswith(NOTICE_TITLE_PREFIX)

    return _stringify_datetimes(rows)


def task_submissions(teacher_id, task_id, is_admin=False):
    """某任务的逐人完成情况。

    以 class_students 为左表 LEFT JOIN task_submissions，
    因此“还没开始”的学生同样会出现在名单里（status 为 None）。
    无权访问返回 None。
    """

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, teacher_id, class_id, course_id, title,
                       content, due_at, created_at
                FROM learning_tasks
                WHERE id = %s
                """,
                (task_id,)
            )

            task = cursor.fetchone()

            if not task:
                return None

            if not is_admin and task['teacher_id'] != teacher_id:
                return None

            cursor.execute(
                """
                SELECT
                    u.id AS student_id,
                    u.user_no,
                    u.real_name,
                    u.college,
                    s.id AS submission_id,
                    s.status,
                    s.score,
                    s.paper_id,
                    s.submitted_at,
                    s.created_at AS assigned_at
                FROM class_students cs
                JOIN users u ON u.id = cs.user_id
                LEFT JOIN task_submissions s
                     ON s.task_id = %s AND s.student_id = u.id
                WHERE cs.class_id = %s
                ORDER BY s.status = 'done' DESC, u.user_no
                """,
                (task_id, task['class_id'])
            )

            rows = cursor.fetchall()

    for row in rows:
        raw_status = row.get('status')

        # 既区分“已布置但未完成”（pending）与“完全没有记录”（not_started），
        # 也保证前端拿到的 label 一定有值。
        if raw_status == 'done':
            row['status'] = 'done'
        elif raw_status == 'pending':
            row['status'] = 'pending'
        else:
            row['status'] = 'not_started'

        row['status_label'] = TASK_STATUS_LABELS[row['status']]

        if row.get('score') is not None:
            row['score'] = round(float(row['score']), 1)

    task = _stringify_datetimes([task])[0]

    done = len([row for row in rows if row['status'] == 'done'])

    return {
        'task': task,
        'submissions': _stringify_datetimes(rows),
        'summary': {
            'student_total': len(rows),
            'done_count': done,
            'pending_count': len(rows) - done,
            'rate': round(done / len(rows) * 100, 1) if rows else 0.0
        }
    }


# ============================================================
# 答疑（师生互动）
# ============================================================

def list_questions(teacher_id, status=None, class_id=None, is_admin=False):
    """教师收到的学生提问。

    非管理员只能看到：自己在授课班级里的提问，或已经指派给自己的提问。
    """

    clauses = []
    params = []

    if not is_admin:
        clauses.append(
            """
            (
                q.teacher_id = %s
                OR EXISTS (
                    SELECT 1 FROM teacher_courses tc
                    JOIN class_students cs
                         ON cs.class_id = tc.class_id AND cs.user_id = q.student_id
                    WHERE tc.teacher_id = %s
                      AND (q.class_id IS NULL OR q.class_id = tc.class_id)
                )
            )
            """
        )
        params.extend([teacher_id, teacher_id])

    if status in QA_STATUSES:
        clauses.append('q.status = %s')
        params.append(status)

    if class_id:
        clauses.append('q.class_id = %s')
        params.append(class_id)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    q.id,
                    q.title,
                    q.question,
                    q.image_url,
                    q.status,
                    q.class_id,
                    c.name AS class_name,
                    q.course_id,
                    co.name AS course_name,
                    q.student_id,
                    u.user_no AS student_no,
                    u.real_name AS student_name,
                    q.teacher_id,
                    t.real_name AS teacher_name,
                    q.created_at,
                    q.updated_at,
                    (SELECT COUNT(*) FROM qa_replies r
                      WHERE r.question_id = q.id) AS reply_count
                FROM qa_questions q
                LEFT JOIN users u ON u.id = q.student_id
                LEFT JOIN users t ON t.id = q.teacher_id
                LEFT JOIN classes c ON c.id = q.class_id
                LEFT JOIN courses co ON co.id = q.course_id
                {where}
                ORDER BY (q.status = 'open') DESC, q.created_at DESC, q.id DESC
                LIMIT 200
                """,
                tuple(params)
            )

            questions = cursor.fetchall()

            ids = [row['id'] for row in questions]

            replies = {}

            if ids:
                placeholders = ', '.join(['%s'] * len(ids))

                cursor.execute(
                    f"""
                    SELECT r.id, r.question_id, r.user_id, r.role,
                           r.content, r.created_at,
                           u.real_name, u.user_no
                    FROM qa_replies r
                    LEFT JOIN users u ON u.id = r.user_id
                    WHERE r.question_id IN ({placeholders})
                    ORDER BY r.id
                    """,
                    tuple(ids)
                )

                for row in cursor.fetchall():
                    replies.setdefault(row['question_id'], []).append(
                        _stringify_datetimes([row])[0]
                    )

    for row in questions:
        row['replies'] = replies.get(row['id'], [])

    return _stringify_datetimes(questions)


def reply_question(teacher_id, question_id, content, role=ROLE_TEACHER,
                   is_admin=False):
    """教师回答学生提问：写入 qa_replies，并把问题置为 answered。

    返回 (结果字典, HTTP 状态码)。
    """

    content = (content or '').strip()

    if not content:
        return {'success': False, 'message': '回复内容不能为空'}, 400

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, student_id, class_id, teacher_id, status
                FROM qa_questions
                WHERE id = %s
                """,
                (question_id,)
            )

            question = cursor.fetchone()

            if not question:
                return {'success': False, 'message': '提问不存在'}, 404

            if not is_admin:
                allowed = question['teacher_id'] == teacher_id

                if not allowed and question['student_id']:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM teacher_courses tc
                        JOIN class_students cs
                             ON cs.class_id = tc.class_id
                            AND cs.user_id = %s
                        WHERE tc.teacher_id = %s
                          AND (%s IS NULL OR tc.class_id = %s)
                        LIMIT 1
                        """,
                        (
                            question['student_id'],
                            teacher_id,
                            question['class_id'],
                            question['class_id']
                        )
                    )

                    allowed = cursor.fetchone() is not None

                if not allowed:
                    return {
                        'success': False,
                        'message': '该提问不属于你的班级，无法回复'
                    }, 403

            if question['status'] == 'closed':
                return {'success': False, 'message': '该提问已关闭'}, 400

            cursor.execute(
                """
                INSERT INTO qa_replies (question_id, user_id, role, content)
                VALUES (%s, %s, %s, %s)
                """,
                (question_id, teacher_id, role, content[:8000])
            )

            reply_id = cursor.lastrowid

            cursor.execute(
                """
                UPDATE qa_questions
                SET status = 'answered', teacher_id = %s
                WHERE id = %s
                """,
                (teacher_id, question_id)
            )

            connection.commit()

    logger.info('教师 %s 回复提问 %s（回复 %s）', teacher_id, question_id, reply_id)

    return {
        'success': True,
        'message': '回复已发送',
        'reply_id': reply_id
    }, 200


# ============================================================
# 错题标注纠正与题库
# ============================================================

def update_wrong_question(teacher_id, question_id, fields, is_admin=False):
    """教师纠正学生错题的知识点 / 错误类型 / 掌握度标注。

    返回 (结果字典, HTTP 状态码)。范围校验全部在 SQL 中完成。
    """

    allowed_scope = can_access_wrong_question(teacher_id, question_id, is_admin)

    if not allowed_scope:
        return {
            'success': False,
            'message': '该错题不属于你的授课班级，无法修改'
        }, 403

    updates = []
    params = []

    for key, value in (fields or {}).items():
        if key not in WRONG_QUESTION_UPDATABLE:
            continue

        if key == 'mastery':
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {'success': False, 'message': '掌握度取值不合法'}, 400

            if value not in (0, 1, 2):
                return {'success': False, 'message': '掌握度取值不合法'}, 400

        if key == 'error_type' and value and value not in ALLOWED_ERROR_TYPES:
            return {'success': False, 'message': '错误类型不在允许范围内'}, 400

        if key == 'knowledge_points':
            if isinstance(value, list):
                value = '、'.join(
                    str(item).strip() for item in value if str(item).strip()
                )

            value = (value or '')[:255]

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(question_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE wrong_questions
                SET {', '.join(updates)}
                WHERE id = %s
                """,
                tuple(params)
            )

            affected = cursor.rowcount

            # knowledge_points 变化时同步关联表，保证报表口径一致
            if 'knowledge_points' in (fields or {}):
                cursor.execute(
                    'DELETE FROM wrong_question_kps WHERE wrong_question_id = %s',
                    (question_id,)
                )

                raw = str(fields.get('knowledge_points') or '')

                for kp in {
                    item.strip()
                    for item in raw.replace('，', '、').replace(',', '、').split('、')
                    if item.strip()
                }:
                    cursor.execute(
                        """
                        INSERT INTO wrong_question_kps
                        (wrong_question_id, kp_name)
                        VALUES (%s, %s)
                        """,
                        (question_id, kp[:150])
                    )

            connection.commit()

    logger.info(
        '教师 %s 修正错题 %s 标注（受影响行数 %s）',
        teacher_id, question_id, affected
    )

    return {
        'success': True,
        'message': '标注已更新',
        'affected': affected
    }, 200


def add_question_bank(teacher_id, payload):
    """把教师确认过的题目写入题库（verified=1、source='teacher'）。

    返回 (结果字典, HTTP 状态码)。
    """

    question = (payload.get('question') or '').strip()

    if not question:
        return {'success': False, 'message': '题干不能为空'}, 400

    qtype = payload.get('qtype') or 'choice'

    if qtype not in ('judge', 'choice', 'fill', 'essay'):
        return {'success': False, 'message': '题型不在允许范围内'}, 400

    try:
        difficulty = int(payload.get('difficulty') or 2)
    except (TypeError, ValueError):
        return {'success': False, 'message': '难度取值不合法'}, 400

    if difficulty not in (1, 2, 3):
        return {'success': False, 'message': '难度取值不合法'}, 400

    options = payload.get('options')

    if isinstance(options, (list, dict)):
        import json as _json
        options = _json.dumps(options, ensure_ascii=False)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO question_bank
                (course_id, chapter_id, major, kp_name, qtype, difficulty,
                 question, options_json, answer, analysis, source, verified,
                 created_by, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'teacher', 1, %s, 1)
                """,
                (
                    payload.get('course_id'),
                    payload.get('chapter_id'),
                    (payload.get('major') or '')[:50],
                    (payload.get('kp_name') or '')[:150],
                    qtype,
                    difficulty,
                    question,
                    options,
                    payload.get('answer'),
                    payload.get('analysis'),
                    teacher_id
                )
            )

            question_id = cursor.lastrowid

            connection.commit()

    logger.info('教师 %s 向题库写入题目 %s', teacher_id, question_id)

    return {
        'success': True,
        'message': '已加入题库并标记为教师审核通过',
        'question_id': question_id,
        'verified': 1,
        'source': 'teacher'
    }, 200

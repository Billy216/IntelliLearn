# -*- coding: utf-8 -*-
"""教师端接口（模块八：师生互动；模块九：学情分析与可视化报表）。

本层只做 HTTP 参数解析与响应封装，全部 SQL 与权限判断在
backend/services/teacher_service.py 中完成。

权限说明：
- 所有接口都要求登录，角色限定为教师或管理员；
- 教师必须通过 teacher_courses 与目标班级/课程/学生建立关联，
  这一校验在服务层的 SQL 中完成，前端隐藏按钮不作为权限控制。
"""

from flask import Blueprint, request, session

from backend.services import teacher_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, forbidden, not_found, ok
from backend.utils.security import (
    ROLE_ADMIN,
    ROLE_TEACHER,
    login_required,
    role_required
)
from backend.utils.validators import normalize_text, parse_positive_int


teacher_bp = Blueprint('teacher', __name__)

logger = get_logger('teacher')


def _viewer():
    """当前操作者信息：user_id / role / 是否管理员。"""

    role = session.get('role')

    return {
        'user_id': session.get('userid'),
        'role': role,
        'is_admin': role == ROLE_ADMIN
    }


def _parse_due_at(raw):
    """把前端传来的日期时间规整为 MySQL 可接受的格式。

    接受 'YYYY-MM-DD' 或 'YYYY-MM-DDTHH:MM' 或 'YYYY-MM-DD HH:MM:SS'。
    """

    value = normalize_text(raw, 30)

    if not value:
        return None

    value = value.replace('T', ' ')

    if len(value) == 10:
        value = f'{value} 23:59:59'
    elif len(value) == 16:
        value = f'{value}:00'

    return value


# ============================================================
# 班级与学生
# ============================================================

@teacher_bp.route('/api/teacher/classes', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_classes():
    """当前教师被授权的班级列表（管理员可见全校班级）。"""

    viewer = _viewer()

    try:
        classes = teacher_service.list_classes(
            viewer['user_id'], viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取教师班级失败: %s', exc)
        return fail('班级列表读取失败', status=500)

    return ok(
        data=classes,
        total=len(classes),
        is_admin=viewer['is_admin'],
        scope_note=('管理员可见全校班级' if viewer['is_admin']
                    else '仅显示通过 teacher_courses 授权给你的班级')
    )


@teacher_bp.route('/api/teacher/courses', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_courses():
    """当前教师的授课关系（班级 + 课程），供前端筛选。"""

    viewer = _viewer()

    try:
        links = teacher_service.list_teacher_courses(
            viewer['user_id'], viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取授课关系失败: %s', exc)
        return fail('授课关系读取失败', status=500)

    return ok(data=links, total=len(links))


@teacher_bp.route('/api/teacher/students', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_students():
    """某班级的学生名单（需已授权该班级）。"""

    viewer = _viewer()

    class_id = parse_positive_int(request.args.get('class_id'))

    if not class_id:
        return fail('请提供 class_id')

    try:
        students = teacher_service.list_students(
            viewer['user_id'], class_id, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取班级学生失败: %s', exc)
        return fail('学生名单读取失败', status=500)

    if students is None:
        return forbidden('该班级不在你的授课范围内')

    return ok(data=students, total=len(students), class_id=class_id)


# ============================================================
# 模块九：学情报表
# ============================================================

@teacher_bp.route('/api/teacher/student-report', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_student_report():
    """单个学生的真实学习报告。"""

    viewer = _viewer()

    student_id = parse_positive_int(request.args.get('student_id'))
    course_id = parse_positive_int(request.args.get('course_id'))

    if not student_id:
        return fail('请提供 student_id')

    try:
        report = teacher_service.student_report(
            viewer['user_id'], student_id, course_id, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('生成学生报告失败: %s', exc)
        return fail('学生报告生成失败', status=500)

    if report is None:
        return forbidden('该学生不在你的授课班级中，无法查看其学情')

    return ok(data=report)


@teacher_bp.route('/api/teacher/class-report', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_class_report():
    """班级层面的真实聚合报表。"""

    viewer = _viewer()

    class_id = parse_positive_int(request.args.get('class_id'))
    course_id = parse_positive_int(request.args.get('course_id'))
    days = parse_positive_int(request.args.get('days'), 30, maximum=3650) or 30

    if not class_id:
        return fail('请提供 class_id')

    try:
        report = teacher_service.class_report(
            viewer['user_id'], class_id, course_id, days, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('生成班级报告失败: %s', exc)
        return fail('班级报告生成失败', status=500)

    if report is None:
        return forbidden('该班级不在你的授课范围内，无法查看学情')

    return ok(data=report)


# ============================================================
# 复习任务与通知
# ============================================================

@teacher_bp.route('/api/teacher/tasks', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_task_create():
    """向授权班级发布复习任务。"""

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    class_id = parse_positive_int(data.get('class_id'))
    course_id = parse_positive_int(data.get('course_id'))

    if not class_id:
        return fail('请选择要发布任务的班级')

    title = normalize_text(data.get('title'), 150)

    if not title:
        return fail('任务标题不能为空')

    try:
        result, status = teacher_service.create_task(
            viewer['user_id'],
            class_id,
            course_id,
            title,
            content=normalize_text(data.get('content'), 20000) or None,
            paper_id=parse_positive_int(data.get('paper_id')),
            due_at=_parse_due_at(data.get('due_at')),
            is_admin=viewer['is_admin']
        )
    except Exception as exc:
        logger.error('发布任务失败: %s', exc)
        return fail('任务发布失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '任务发布失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@teacher_bp.route('/api/teacher/tasks', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_tasks():
    """教师发布过的任务列表（含完成统计）。"""

    viewer = _viewer()

    class_id = parse_positive_int(request.args.get('class_id'))

    try:
        tasks = teacher_service.list_tasks(
            viewer['user_id'], class_id, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取任务列表失败: %s', exc)
        return fail('任务列表读取失败', status=500)

    return ok(data=tasks, total=len(tasks))


@teacher_bp.route('/api/teacher/tasks/<int:task_id>/submissions', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_task_submissions(task_id):
    """某任务的逐人完成情况（未开始的学生也会出现）。"""

    viewer = _viewer()

    try:
        result = teacher_service.task_submissions(
            viewer['user_id'], task_id, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取任务完成情况失败: %s', exc)
        return fail('任务完成情况读取失败', status=500)

    if result is None:
        return not_found('任务不存在，或该任务不是你发布的')

    return ok(
        data=result['submissions'],
        task=result['task'],
        summary=result['summary']
    )


@teacher_bp.route('/api/teacher/notices', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_notice_create():
    """发布错题讲解通知（复用 learning_tasks，标题带固定前缀）。"""

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    class_id = parse_positive_int(data.get('class_id'))
    course_id = parse_positive_int(data.get('course_id'))

    if not class_id:
        return fail('请选择要发布通知的班级')

    content = normalize_text(data.get('content'), 20000)

    if not content:
        return fail('通知内容不能为空')

    try:
        result, status = teacher_service.create_notice(
            viewer['user_id'],
            class_id,
            normalize_text(data.get('title'), 140) or '错题讲解',
            content,
            course_id=course_id,
            is_admin=viewer['is_admin']
        )
    except Exception as exc:
        logger.error('发布通知失败: %s', exc)
        return fail('通知发布失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '通知发布失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 答疑
# ============================================================

@teacher_bp.route('/api/teacher/questions', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_questions():
    """学生提问列表（按状态 / 班级筛选）。"""

    viewer = _viewer()

    status = normalize_text(request.args.get('status'), 20)

    if status not in teacher_service.QA_STATUSES:
        status = None

    class_id = parse_positive_int(request.args.get('class_id'))

    try:
        questions = teacher_service.list_questions(
            viewer['user_id'], status, class_id, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('读取学生提问失败: %s', exc)
        return fail('提问列表读取失败', status=500)

    return ok(data=questions, total=len(questions))


@teacher_bp.route('/api/teacher/questions/<int:question_id>/reply', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_question_reply(question_id):
    """回答学生提问：写入 qa_replies 并把问题置为 answered。"""

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    content = normalize_text(data.get('content'), 8000)

    if not content:
        return fail('回复内容不能为空')

    try:
        result, status = teacher_service.reply_question(
            viewer['user_id'],
            question_id,
            content,
            role=viewer['role'],
            is_admin=viewer['is_admin']
        )
    except Exception as exc:
        logger.error('回复提问失败: %s', exc)
        return fail('回复失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        if status == 403:
            return forbidden(result.get('message'))

        return fail(result.get('message', '回复失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 错题标注纠正与题库
# ============================================================

@teacher_bp.route('/api/teacher/wrong-questions/<int:question_id>', methods=['PATCH'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_wrong_question_update(question_id):
    """修正学生错题的知识点 / 错误类型 / 掌握度标注（限授权班级内）。"""

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    fields = {}

    if 'knowledge_points' in data:
        value = data.get('knowledge_points')

        if isinstance(value, list):
            value = '、'.join(
                normalize_text(item, 60) for item in value if item
            )

        fields['knowledge_points'] = normalize_text(value, 255)

    if 'error_type' in data:
        fields['error_type'] = normalize_text(data.get('error_type'), 30)

    if 'mastery' in data:
        fields['mastery'] = data.get('mastery')

    if 'analysis' in data:
        fields['analysis'] = normalize_text(data.get('analysis'), 8000)

    if 'standard_answer' in data:
        fields['standard_answer'] = normalize_text(
            data.get('standard_answer'), 8000
        )

    if not fields:
        return fail('没有需要更新的字段')

    try:
        result, status = teacher_service.update_wrong_question(
            viewer['user_id'], question_id, fields, viewer['is_admin']
        )
    except Exception as exc:
        logger.error('教师修正错题标注失败: %s', exc)
        return fail('标注更新失败', status=500)

    if not result.get('success'):
        if status == 403:
            return forbidden(result.get('message'))

        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '标注更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@teacher_bp.route('/api/teacher/question-bank', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_teacher_question_bank_create():
    """把教师确认过的题目写入题库（verified=1, source='teacher'）。"""

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    payload = {
        'course_id': parse_positive_int(data.get('course_id')),
        'chapter_id': parse_positive_int(data.get('chapter_id')),
        'major': normalize_text(data.get('major'), 50),
        'kp_name': normalize_text(data.get('kp_name'), 150),
        'qtype': normalize_text(data.get('qtype'), 20) or 'choice',
        'difficulty': data.get('difficulty'),
        'question': normalize_text(data.get('question'), 8000),
        'options': data.get('options') or data.get('options_json'),
        'answer': normalize_text(data.get('answer'), 8000),
        'analysis': normalize_text(data.get('analysis'), 8000)
    }

    try:
        result, status = teacher_service.add_question_bank(
            viewer['user_id'], payload
        )
    except Exception as exc:
        logger.error('写入题库失败: %s', exc)
        return fail('写入题库失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '写入题库失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})

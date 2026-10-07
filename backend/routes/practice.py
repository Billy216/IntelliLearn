# -*- coding: utf-8 -*-
"""个性化练习与复习卷接口（模块七）。

分层：本文件只处理 HTTP 关注点（取参、校验、鉴权、组织返回），
所有 SQL 与判分逻辑都在 backend/services/practice_service.py 中。

安全约定：
- 用户身份一律取 session['userid']，绝不接受客户端传来的用户 ID；
- 所有筛选参数在服务端按白名单校验，SQL 全部使用 %s 占位符；
- 未提交的练习卷不下发 answer / analysis / ai_comment 字段。
"""

from flask import Blueprint, request, session

from backend.services import practice_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, not_found, ok
from backend.utils.security import login_required
from backend.utils.validators import normalize_text, parse_positive_int


practice_bp = Blueprint('practice', __name__)

logger = get_logger('practice')


def _fail_from_exception(exc, action):
    """把服务层异常映射成统一失败响应（业务异常 4xx，其余 500）。"""

    if isinstance(exc, practice_service.PracticeError):
        return fail(exc.message, status=exc.status, code=exc.code)

    logger.error('%s失败: %s', action, exc)

    return fail(f'{action}失败，请稍后重试', status=500)


def _as_bool(value, default=False):
    """把前端传来的开关值解析为布尔（兼容 true/1/'1'/'true'）。"""

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


@practice_bp.route('/api/practice/options', methods=['GET'])
@login_required
def api_practice_options():
    """组卷筛选项：学科、知识点、课程、错误类型、掌握度、题型、难度。"""

    user_id = session.get('userid')

    try:
        data = practice_service.list_filter_options(user_id)
    except Exception as exc:
        return _fail_from_exception(exc, '读取筛选项')

    return ok(data=data)


@practice_bp.route('/api/practice/papers', methods=['POST'])
@login_required
def api_practice_generate():
    """生成个性化练习卷：错题优先 → 题库补充 → 必要时 AI 补题（标记未校验）。"""

    user_id = session.get('userid')

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求：请提交 JSON 请求体')

    try:
        result = practice_service.generate_paper(
            user_id,
            major=normalize_text(data.get('major'), 50) or None,
            kp=normalize_text(data.get('kp'), 150) or None,
            qtype=normalize_text(data.get('qtype'), 20) or None,
            difficulty=data.get('difficulty'),
            count=data.get('count'),
            course_id=data.get('course_id'),
            error_type=normalize_text(data.get('error_type'), 30) or None,
            mastery=data.get('mastery'),
            source=normalize_text(data.get('source'), 10) or practice_service.SOURCE_AUTO,
            verified_only=_as_bool(data.get('verified_only'), True),
            allow_ai=_as_bool(data.get('allow_ai'), True)
        )
    except Exception as exc:
        return _fail_from_exception(exc, '生成练习卷')

    return ok(
        paper=result['paper'],
        composition=result['composition'],
        notices=result['notices'],
        requested_count=result['requested_count'],
        created_count=result['created_count']
    )


@practice_bp.route('/api/practice/papers', methods=['GET'])
@login_required
def api_practice_papers():
    """练习历史：分页返回自己的练习卷与得分情况。"""

    user_id = session.get('userid')

    page = parse_positive_int(request.args.get('page'), 1) or 1
    page_size = parse_positive_int(request.args.get('page_size'), 10) or 10

    if page > 100000:
        return fail('页码超出范围')

    try:
        result = practice_service.list_papers(user_id, page=page, page_size=page_size)
    except Exception as exc:
        return _fail_from_exception(exc, '读取练习记录')

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size']
    )


@practice_bp.route('/api/practice/papers/<int:paper_id>', methods=['GET'])
@login_required
def api_practice_paper_detail(paper_id):
    """读取一份练习卷：未提交时不含答案，已提交时附带作答回顾。"""

    user_id = session.get('userid')

    try:
        result = practice_service.get_paper(user_id, paper_id)
    except Exception as exc:
        return _fail_from_exception(exc, '读取练习卷')

    if not result:
        return not_found('练习卷不存在')

    return ok(
        paper=result['paper'],
        submitted=result['submitted'],
        review=result['review'],
        notices=result.get('notices', [])
    )


@practice_bp.route('/api/practice/papers/<int:paper_id>/submit', methods=['POST'])
@login_required
def api_practice_submit(paper_id):
    """提交整份练习卷，服务端判分并返回逐题回顾。"""

    user_id = session.get('userid')

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求：请提交 JSON 请求体')

    answers = data.get('answers')

    if answers is None:
        return fail('缺少作答内容 answers')

    if not isinstance(answers, dict):
        return fail('answers 必须是 {题目ID: 作答} 结构')

    if len(answers) > 500:
        return fail('作答数量超出限制')

    try:
        result = practice_service.submit_paper(user_id, paper_id, answers)
    except Exception as exc:
        return _fail_from_exception(exc, '提交练习卷')

    if not result:
        return not_found('练习卷不存在')

    return ok(
        paper=result['paper'],
        review=result['review'],
        already_submitted=result['already_submitted']
    )


@practice_bp.route('/api/practice/papers/<int:paper_id>/wrongbook', methods=['POST'])
@login_required
def api_practice_add_wrongbook(paper_id):
    """把本卷答错的题目加入错题本（真实写入 wrong_questions）。"""

    user_id = session.get('userid')

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return fail('无效请求：请提交 JSON 请求体')

    item_ids = data.get('item_ids')

    if item_ids is not None and not isinstance(item_ids, list):
        return fail('item_ids 必须是数组')

    if isinstance(item_ids, list) and len(item_ids) > 500:
        return fail('题目数量超出限制')

    try:
        result = practice_service.add_items_to_wrongbook(user_id, paper_id, item_ids)
    except Exception as exc:
        return _fail_from_exception(exc, '加入错题本')

    if not result:
        return not_found('练习卷不存在')

    return ok(
        added=result['added'],
        existing=result['existing'],
        results=result['results'],
        message=result['message']
    )


@practice_bp.route('/api/practice/stats', methods=['GET'])
@login_required
def api_practice_stats():
    """练习统计：练习次数、平均分、知识点与题型正确率（全部真实聚合）。"""

    user_id = session.get('userid')

    try:
        data = practice_service.student_statistics(user_id)
    except Exception as exc:
        return _fail_from_exception(exc, '读取练习统计')

    return ok(data=data)


@practice_bp.route('/api/practice/tasks', methods=['GET'])
@login_required
def api_practice_tasks():
    """我所在班级的复习任务及完成情况（只读 learning_tasks）。"""

    user_id = session.get('userid')

    try:
        result = practice_service.list_student_tasks(user_id)
    except Exception as exc:
        return _fail_from_exception(exc, '读取复习任务')

    return ok(data=result['items'], total=result['total'])


@practice_bp.route('/api/practice/tasks/<int:task_id>/start', methods=['POST'])
@login_required
def api_practice_task_start(task_id):
    """打开教师任务对应的练习卷：已有试卷直接复用，否则现场组卷。"""

    user_id = session.get('userid')

    try:
        result = practice_service.generate_task_paper(user_id, task_id)
    except Exception as exc:
        return _fail_from_exception(exc, '打开复习任务')

    return ok(
        paper=result['paper'],
        reused=result.get('reused', False),
        submitted=result.get('submitted', False),
        review=result.get('review'),
        notices=result.get('notices', [])
    )

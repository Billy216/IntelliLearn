# -*- coding: utf-8 -*-
"""错题本接口：查询、筛选、新增、详情、修改、删除、复习记录、统计。

说明：从 chat.py 中拆分出来，保持原 URL 与返回字段不变，
仅在成功响应中附加 total/page 等分页字段，旧前端可继续使用。
"""

from flask import Blueprint, request, session

from backend.services import ai_service, study_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, not_found, ok
from backend.utils.security import login_required
from backend.utils.validators import normalize_text, parse_positive_int


wrong_bp = Blueprint('wrong_questions', __name__)

logger = get_logger('wrong')


@wrong_bp.route('/api/wrong_questions', methods=['GET'])
@login_required
def api_wrong_questions_list():
    """查询错题列表，支持按学科、错误类型、掌握度、知识点、关键词筛选与分页。"""

    user_id = session.get('userid')

    mastery_raw = request.args.get('mastery')

    mastery = None

    if mastery_raw not in (None, '', 'all'):
        try:
            mastery = int(mastery_raw)
        except (TypeError, ValueError):
            mastery = None

    try:
        result = study_service.list_wrong_questions(
            user_id,
            major=normalize_text(request.args.get('major'), 20) or None,
            error_type=normalize_text(request.args.get('error_type'), 30) or None,
            mastery=mastery,
            keyword=normalize_text(request.args.get('keyword'), 100) or None,
            kp=normalize_text(request.args.get('kp'), 60) or None,
            page=parse_positive_int(request.args.get('page'), 1) or 1,
            page_size=parse_positive_int(request.args.get('page_size'), 20) or 20
        )
    except Exception as exc:
        logger.error('读取错题集失败: %s', exc)
        return fail('错题集读取失败', status=500)

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size']
    )


@wrong_bp.route('/api/wrong_questions/stats', methods=['GET'])
@login_required
def api_wrong_questions_stats():
    """错题统计（全部来自真实记录，不做任何模拟）。"""

    user_id = session.get('userid')

    try:
        stats = study_service.wrong_question_stats(user_id)

        stats['majors'] = study_service.wrong_question_majors(user_id)

        stats['weak_points'] = study_service.weak_knowledge_points(user_id)
    except Exception as exc:
        logger.error('错题统计失败: %s', exc)
        return fail('统计失败', status=500)

    return ok(data=stats)


@wrong_bp.route('/api/wrong_questions', methods=['POST'])
@login_required
def api_wrong_questions_add():
    """把题目加入错题本。

    保留旧字段（question/major/sub/answer/image_url/source），
    新增 knowledge_points / error_type / user_answer / standard_answer /
    analysis / conversation_id / message_id。
    """

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}

    question = normalize_text(data.get('question'), 8000)
    major = normalize_text(data.get('major'), 20)

    if not question or major not in ai_service.MAJOR_CATEGORIES:
        return fail('题目或分类信息不完整')

    subs = data.get('sub') or []

    if isinstance(subs, str):
        subs = [subs]

    subs = [normalize_text(item, 100) for item in subs if item] or ['']

    knowledge_points = data.get('knowledge_points') or []

    if isinstance(knowledge_points, str):
        knowledge_points = [
            item for item in knowledge_points.replace('，', '、').split('、')
        ]

    knowledge_points = '、'.join(
        normalize_text(item, 60)
        for item in knowledge_points
        if normalize_text(item, 60)
    )

    error_types = data.get('error_types') or data.get('error_type') or []

    if isinstance(error_types, str):
        error_types = [error_types]

    error_types = [
        item for item in error_types
        if item in ai_service.ERROR_TYPES
    ]

    added = 0

    try:
        for sub in subs:
            if ai_service.add_wrong_question(
                user_id,
                major,
                sub,
                question,
                normalize_text(data.get('answer'), 20000),
                normalize_text(data.get('image_url'), 500),
                normalize_text(data.get('source'), 20) or 'AI',
                knowledge_points=knowledge_points,
                error_type='、'.join(error_types),
                user_answer=normalize_text(data.get('user_answer'), 8000) or None,
                standard_answer=normalize_text(data.get('standard_answer'), 8000) or None,
                analysis=normalize_text(data.get('analysis'), 8000) or None,
                conversation_id=parse_positive_int(data.get('conversation_id')),
                message_id=parse_positive_int(data.get('message_id'))
            ):
                added += 1
    except Exception as exc:
        logger.error('加入错题集失败: %s', exc)
        return fail('加入错题集失败，请稍后重试', status=500)

    if added:
        return ok(
            added=added,
            message=f'已加入错题集（{len(subs)} 个分类）'
        )

    return ok(added=0, message='该题已在错题集中')


@wrong_bp.route('/api/wrong_questions/<int:question_id>', methods=['GET'])
@login_required
def api_wrong_question_detail(question_id):
    """错题详情（含知识点列表与解题过程）。"""

    user_id = session.get('userid')

    try:
        row = study_service.get_wrong_question(user_id, question_id)
    except Exception as exc:
        logger.error('读取错题详情失败: %s', exc)
        return fail('错题读取失败', status=500)

    if not row:
        return not_found('错题不存在')

    return ok(data=row)


@wrong_bp.route('/api/wrong_questions/<int:question_id>', methods=['PATCH'])
@login_required
def api_wrong_question_update(question_id):
    """修改错题分类、知识点、错误类型或掌握度。"""

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}

    fields = {}

    if 'major' in data:
        major = normalize_text(data.get('major'), 20)

        if major and major not in ai_service.MAJOR_CATEGORIES:
            return fail('学科不在允许范围内')

        fields['major'] = major

    if 'sub' in data:
        fields['sub'] = normalize_text(data.get('sub'), 100)

    if 'knowledge_points' in data:
        value = data.get('knowledge_points')

        if isinstance(value, list):
            value = '、'.join(
                normalize_text(item, 60) for item in value if item
            )

        fields['knowledge_points'] = normalize_text(value, 255)

    if 'error_type' in data:
        error_type = normalize_text(data.get('error_type'), 30)

        if error_type and error_type not in ai_service.ERROR_TYPES:
            return fail('错误类型不在允许范围内')

        fields['error_type'] = error_type

    if 'mastery' in data:
        try:
            mastery = int(data.get('mastery'))
        except (TypeError, ValueError):
            return fail('掌握度取值不合法')

        if mastery not in (0, 1, 2):
            return fail('掌握度取值不合法（0 未掌握 / 1 模糊 / 2 已掌握）')

        fields['mastery'] = mastery

    if 'analysis' in data:
        fields['analysis'] = normalize_text(data.get('analysis'), 8000)

    if 'standard_answer' in data:
        fields['standard_answer'] = normalize_text(data.get('standard_answer'), 8000)

    if not fields:
        return fail('没有需要更新的字段')

    try:
        updated = study_service.update_wrong_question(
            user_id,
            question_id,
            fields
        )
    except Exception as exc:
        logger.error('更新错题失败: %s', exc)
        return fail('更新失败', status=500)

    if not updated:
        return not_found('错题不存在或没有可更新内容')

    return ok(message='已更新')


@wrong_bp.route('/api/wrong_questions/<int:question_id>/review', methods=['POST'])
@login_required
def api_wrong_question_review(question_id):
    """记录一次复习，可同时更新掌握度。"""

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}

    mastery = data.get('mastery')

    if mastery is not None:
        try:
            mastery = int(mastery)
        except (TypeError, ValueError):
            return fail('掌握度取值不合法')

        if mastery not in (0, 1, 2):
            return fail('掌握度取值不合法')

    try:
        updated = study_service.mark_reviewed(user_id, question_id, mastery)
    except Exception as exc:
        logger.error('记录复习失败: %s', exc)
        return fail('记录失败', status=500)

    if not updated:
        return not_found('错题不存在')

    return ok(message='已记录本次复习')


@wrong_bp.route('/api/wrong_questions/<int:question_id>', methods=['DELETE'])
@login_required
def api_wrong_question_delete(question_id):
    """删除错题。"""

    user_id = session.get('userid')

    try:
        deleted = study_service.delete_wrong_question(user_id, question_id)
    except Exception as exc:
        logger.error('删除错题失败: %s', exc)
        return fail('删除失败', status=500)

    if not deleted:
        return not_found('错题不存在')

    return ok(message='已从错题本删除')

# -*- coding: utf-8 -*-
"""AI 相关接口：对话（流式/非流式）、会话管理、试卷生成。

页面路由（/chat、/exam、/errors_register 等）由 page.py 提供。
错题本接口见 backend/routes/wrong_questions.py，
练习与复习卷接口见 backend/routes/practice.py。
"""

import json
import re

from flask import (
    Blueprint,
    Response,
    request,
    session,
    stream_with_context
)

from backend.services import ai_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, not_found, ok
from backend.utils.security import login_required
from backend.utils.validators import normalize_text, parse_positive_int


logger = get_logger('chat')

chat_bp = Blueprint('ai_chat', __name__)


def _load_image_or_error(image_url):
    """加载题目图片。

    返回 (data_url, 错误响应)。图片合法时错误响应为 None；
    不合法时给出可直接展示给用户的中文说明，
    避免"图片没读到"被误当成"AI 没识别出来"。
    """

    if not image_url:
        return None, None

    data_url, error = ai_service.load_question_image(image_url)

    if error:
        return None, fail(error)

    if not data_url:
        return None, fail('图片读取失败，请重新上传')

    return data_url, None


def _extract_question(messages):
    """从请求的消息数组中取最后一条用户消息文本。"""

    for message in reversed(messages or []):
        if message.get('role') == 'user':
            return normalize_text(message.get('content'), 4000)

    return ''


def _memory_context(user_id, question, has_image):
    """判断并读取跨会话的最近记忆。

    返回 (是否使用记忆, 记忆文本)。任何异常都不影响正常回答。
    """

    try:
        decision = ai_service.should_use_memory(question)

        if decision is None:
            recent = ai_service.get_recent_memories(user_id)

            if not recent or question == '请分析这张图片':
                decision = False
            else:
                decision = ai_service.ai_decide_memory(
                    question,
                    [m['question'] for m in recent]
                )

        if not decision:
            return False, ''

        memories = ai_service.get_recent_memories(user_id)

        if not memories:
            return False, ''

        lines = [
            '以下是该用户最近 5 次提问与解答记录（编号越大越新）。'
            '如果当前问题是在追问其中的题目，请结合记录理解他问的是哪一道，'
            '再针对性讲解，不要只说套话：'
        ]

        for index, memory in enumerate(reversed(memories), 1):
            lines.append(f'{index}. 题目：{memory["question"]}')

            answer = memory.get('answer') or '（无）'

            if len(answer) > 800:
                answer = answer[:800] + '……（已截断）'

            lines.append(f'   解答：{answer}')

        return True, '\n'.join(lines)

    except Exception as exc:
        logger.warning('读取记忆失败（将不带记忆继续回答）: %s', exc)
        return False, ''


def _prepare_context(user_id, data):
    """流式与非流式接口共用的上下文准备。

    返回 (context, error_response)。
    """

    messages = data.get('messages') or []
    image_url = normalize_text(data.get('image_url'), 500)
    conv_id = parse_positive_int(data.get('conversation_id'))

    question = _extract_question(messages)

    if not question:
        question = '请分析这张图片' if image_url else ''

    if not question:
        return None, fail('请输入问题')

    image_base64, image_error = _load_image_or_error(image_url)

    if image_error:
        return None, image_error

    # 校验会话归属（防止越权写入他人会话）
    if conv_id and not ai_service.conversation_belongs_to_user(user_id, conv_id):
        conv_id = None

    return {
        'user_id': user_id,
        'question': question,
        'image_url': image_url,
        'image_base64': image_base64,
        'conv_id': conv_id
    }, None


def _build_ai_messages(user_id, context):
    """组装发给模型的完整消息体。

    组成顺序：系统提示词 → 可选跨会话记忆 → 同会话历史 → 本轮用户消息。
    同会话历史受 AI_CONTEXT_MAX_MESSAGES / AI_CONTEXT_MAX_CHARS 限制，
    避免把全部历史无限制地传给模型。
    """

    analysis = context.get('analysis')

    msgs = ai_service.build_answer_messages(
        context['question'],
        context['image_base64'],
        analysis
    )

    ai_messages = [msgs[0]]

    memory_used, memory_text = _memory_context(
        user_id,
        context['question'],
        bool(context['image_base64'])
    )

    if memory_used and memory_text:
        ai_messages.append({
            'role': 'system',
            'content': memory_text
        })

    history_used = False

    if context.get('conv_id'):
        try:
            history = ai_service.get_conversation_context(
                user_id,
                context['conv_id']
            )

            if history:
                history_used = True
                ai_messages.extend(history)
        except Exception as exc:
            logger.warning('读取会话上下文失败（不影响本次回答）: %s', exc)

    ai_messages.append(msgs[1])

    context['memory_used'] = memory_used
    context['history_used'] = history_used

    return ai_messages


def _analysis_meta(analysis, memory_used=False, history_used=False):
    """把分析结果整理成前端展示与落库用的结构。"""

    if not analysis:
        return None

    return {
        'major': analysis.get('major') or '',
        'sub': analysis.get('sub') or [],
        'knowledge_points': analysis.get('knowledge_points') or [],
        'question_text': analysis.get('question_text') or '',
        'question_clear': analysis.get('question_clear', True),
        'unclear_reason': analysis.get('unclear_reason') or '',
        'has_student_work': bool(analysis.get('has_student_work')),
        'student_work': analysis.get('student_work') or '',
        'error_types': analysis.get('error_types') or [],
        'error_analysis': analysis.get('error_analysis') or '',
        'confidence': analysis.get('confidence') or 'unknown',
        'analyzed': bool(analysis.get('analyzed'))
    }


def _persist_turn(context, reply, reply_plain, meta, question_for_save):
    """把本轮问答写入 chat_messages，并更新 ai_memories。

    返回 (conversation_id, message_id)。落库失败不抛异常，
    由调用方决定是否提示用户，避免回答已经生成却因保存失败而丢失展示。
    """

    user_id = context['user_id']
    conv_id = context.get('conv_id')

    message_id = None

    try:
        if not conv_id:
            title = (question_for_save or context['question'])[:15] or '新对话'
            conv_id = ai_service.create_conversation(
                user_id,
                title,
                (meta or {}).get('major')
            )

        ai_service.save_chat_message(
            conv_id,
            user_id,
            'user',
            question_for_save,
            context.get('image_url'),
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None
        )

        message_id = ai_service.save_chat_message(
            conv_id,
            user_id,
            'assistant',
            reply,
            reply_plain=reply_plain,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None
        )

        context['conv_id'] = conv_id

    except Exception as exc:
        logger.error('保存会话消息失败: %s', exc)

    try:
        knowledge_points = '、'.join(
            (meta or {}).get('knowledge_points') or []
        )
        error_type = '、'.join((meta or {}).get('error_types') or [])

        ai_service.save_memory(
            user_id,
            question_for_save,
            reply_plain or reply,
            context.get('image_url'),
            (meta or {}).get('major'),
            knowledge_points or error_type or None
        )
    except Exception as exc:
        logger.error('保存记忆失败: %s', exc)

    return conv_id, message_id


def _save_question_only(context):
    """AI 失败时先把用户问题存下来，避免刷新后问题丢失。"""

    try:
        conv_id = context.get('conv_id')

        if not conv_id:
            conv_id = ai_service.create_conversation(
                context['user_id'],
                context['question'][:15] or '新对话'
            )

            context['conv_id'] = conv_id

        ai_service.save_chat_message(
            conv_id,
            context['user_id'],
            'user',
            (
                ''
                if context['question'] == '请分析这张图片'
                else context['question']
            ),
            context['image_url']
        )

        return conv_id
    except Exception as exc:
        logger.error('保存问题失败: %s', exc)
        return context.get('conv_id')


# ============================================================
# 非流式对话
# ============================================================

@chat_bp.route('/api/chat', methods=['POST'])
@login_required
def api_chat():

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}

    context, error = _prepare_context(user_id, data)

    if error:
        return error

    # 识别题目 + 分析学生作答（失败时 analyzed=False，不编造结果）
    context['analysis'] = ai_service.analyze_question(
        context['question'],
        context['image_base64']
    )

    meta = _analysis_meta(context['analysis'])

    ai_messages = _build_ai_messages(user_id, context)

    reply = ai_service.complete_ai_answer(ai_messages)

    if not reply:
        _save_question_only(context)

        return fail(
            'AI 服务暂时不可用，请稍后重试',
            status=503,
            code='AI_UNAVAILABLE'
        )

    question_for_save = (
        (meta or {}).get('question_text') or context['question']
    )

    conv_id, message_id = _persist_turn(
        context,
        reply,
        ai_service.format_ai_output(reply),
        meta,
        question_for_save
    )

    return ok(
        reply=reply,
        reply_plain=ai_service.format_ai_output(reply),
        conversation_id=conv_id,
        message_id=message_id,
        memory_used=context.get('memory_used', False),
        history_used=context.get('history_used', False),
        analysis=meta,
        question=question_for_save,
        image_url=context.get('image_url') or ''
    )


# ============================================================
# 流式对话（SSE）
# ============================================================

def _sse_data(obj):
    """把对象序列化成一行 SSE data。"""

    return (
        'data: '
        + json.dumps(obj, ensure_ascii=False)
        + '\n\n'
    )


@chat_bp.route('/api/chat/stream', methods=['POST'])
@login_required
def api_chat_stream():

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}

    context, error = _prepare_context(user_id, data)

    if error:
        return error

    def generate():

        # 真实阶段提示：只有确实在执行对应工作时才会推送，
        # 不伪造 AI 进度。
        yield _sse_data({
            'type': 'stage',
            'stage': 'analyzing',
            'message': '正在识别题目与作答…'
        })

        try:
            context['analysis'] = ai_service.analyze_question(
                context['question'],
                context['image_base64']
            )
        except Exception as exc:
            logger.warning('题目识别失败: %s', exc)
            context['analysis'] = None

        analysis = context['analysis'] or {}
        meta = _analysis_meta(context['analysis'])

        # 识别完全失败（含图片无法识别）时明确告知，不继续编造答案
        if context['image_base64'] and not analysis.get('analyzed'):
            _save_question_only(context)

            yield _sse_data({
                'type': 'error',
                'message': (
                    '题目识别失败（可能是图片不清晰或服务暂时不可用），'
                    '请换一张更清晰的图片或改用文字输入后重试'
                )
            })
            return

        yield _sse_data({
            'type': 'analysis',
            'analysis': meta
        })

        if analysis.get('analyzed') and not analysis.get('question_clear', True):
            yield _sse_data({
                'type': 'notice',
                'message': (
                    '图片中有内容未能识别清楚：'
                    + (analysis.get('unclear_reason') or '请补充更清晰的图片')
                )
            })

        try:
            ai_messages = _build_ai_messages(user_id, context)
        except Exception as exc:
            logger.error('组装上下文失败: %s', exc)
            _save_question_only(context)

            yield _sse_data({
                'type': 'error',
                'message': '请求处理失败，请稍后重试'
            })
            return

        yield _sse_data({
            'type': 'start',
            'memory_used': context.get('memory_used', False),
            'history_used': context.get('history_used', False)
        })

        yield _sse_data({
            'type': 'stage',
            'stage': 'answering',
            'message': '正在生成讲解…'
        })

        raw_parts = []
        got_error = False
        error_message = 'AI 服务暂时不可用，请稍后重试'

        try:
            for event in ai_service.stream_complete_ai_answer(ai_messages):
                event_type = event.get('type')

                if event_type == 'content':
                    text = event.get('text') or ''
                    raw_parts.append(text)
                    yield _sse_data({'type': 'delta', 'text': text})
                elif event_type == 'error':
                    got_error = True
                    error_message = event.get('message') or error_message
        except Exception as exc:
            got_error = True
            error_message = str(exc) or error_message
            logger.error('流式回答失败: %s', exc)

        raw_reply = ''.join(raw_parts)

        if not raw_reply:
            _save_question_only(context)

            yield _sse_data({
                'type': 'error',
                'message': error_message
            })
            return

        if got_error:
            logger.warning('回答过程中出现错误，已保留已生成内容: %s', error_message)

        reply = raw_reply
        reply_plain = ai_service.format_ai_output(raw_reply)

        question_for_save = (
            (meta or {}).get('question_text') or context['question']
        )

        conv_id, message_id = _persist_turn(
            context,
            reply,
            reply_plain,
            meta,
            question_for_save
        )

        yield _sse_data({
            'type': 'done',
            'reply': reply,
            'reply_plain': reply_plain,
            'analysis': meta,
            'question': question_for_save,
            'image_url': context.get('image_url') or '',
            'conversation_id': conv_id,
            'message_id': message_id,
            'memory_used': context.get('memory_used', False),
            'history_used': context.get('history_used', False),
            'partial': bool(got_error)
        })

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# ============================================================
# 学科分类（供前端下拉框使用，避免前端硬编码）
# ============================================================

@chat_bp.route('/api/subjects', methods=['GET'])
@login_required
def api_subjects():

    return ok(
        majors=ai_service.MAJOR_CATEGORIES,
        gaoshu_subs=ai_service.GAOSHU_SUB_CATEGORIES,
        error_types=ai_service.ERROR_TYPES
    )


# ============================================================
# 会话列表 / 详情 / 重命名 / 删除
# ============================================================

@chat_bp.route('/api/conversations', methods=['GET'])
@login_required
def api_conversations():

    user_id = session.get('userid')

    try:
        rows = ai_service.get_conversations(user_id)
    except Exception as exc:
        logger.error('读取对话列表失败: %s', exc)
        return fail('对话列表读取失败', status=500)

    data = []

    for row in rows:
        preview = (
            row.get('last_answer')
            or row.get('last_question')
            or ''
        )[:40]

        # 预览里去掉 Markdown 与 LaTeX 记号，避免列表出现乱码
        preview = re.sub(r'\$+', '', preview)
        preview = re.sub(r'[#*`>]', '', preview).strip()

        data.append({
            'id': row['id'],
            'title': row['title'] or '新对话',
            'major': row.get('major') or '',
            'preview': preview,
            'updated_at': str(row['updated_at'])
        })

    return ok(data=data)


@chat_bp.route('/api/conversations/<int:conv_id>', methods=['GET'])
@login_required
def api_conversation_detail(conv_id):

    user_id = session.get('userid')

    try:
        owned = ai_service.conversation_belongs_to_user(user_id, conv_id)
    except Exception as exc:
        logger.error('读取对话详情失败: %s', exc)
        return fail('对话读取失败', status=500)

    if not owned:
        return not_found('对话不存在')

    try:
        rows = ai_service.get_chat_messages(user_id, conv_id)
    except Exception as exc:
        logger.error('读取对话消息失败: %s', exc)
        return fail('对话读取失败', status=500)

    messages = []

    for row in rows:
        meta = None

        if row.get('meta_json'):
            try:
                meta = json.loads(row['meta_json'])
            except Exception:
                meta = None

        messages.append({
            'role': row['role'],
            'content': row['content'] or '',
            'reply_plain': row.get('reply_plain') or '',
            'image_url': row['image_url'] or '',
            'analysis': meta
        })

    return ok(data={'messages': messages})


@chat_bp.route('/api/conversations/<int:conv_id>', methods=['PATCH'])
@login_required
def api_conversation_rename(conv_id):

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}
    title = normalize_text(data.get('title'), 60)

    if not title:
        return fail('标题不能为空')

    try:
        renamed = ai_service.rename_conversation(user_id, conv_id, title)
    except Exception as exc:
        logger.error('重命名对话失败: %s', exc)
        return fail('重命名失败', status=500)

    if not renamed:
        return not_found('对话不存在')

    return ok(message='已重命名', title=title)


@chat_bp.route('/api/conversations/<int:conv_id>', methods=['DELETE'])
@login_required
def api_conversation_delete(conv_id):

    user_id = session.get('userid')

    try:
        deleted = ai_service.delete_conversation(user_id, conv_id)
    except Exception as exc:
        logger.error('删除对话失败: %s', exc)
        return fail('删除失败', status=500)

    if not deleted:
        return not_found('对话不存在')

    return ok(message='对话已删除')


# ============================================================
# 试卷生成 / 解答题讲评 / 历史试卷
# ============================================================

EXAM_PROMPT_TEMPLATE = (
    '你是出题老师。请根据学生以下错题涉及的知识点，为"{major}"出一份小试卷：\n'
    '3 道判断题（答案只能是对/错）、3 道单选题（4个选项）、'
    '3 道填空题、1 道解答题。\n'
    '要求：题目围绕错题涉及的知识点，随机变换数据和问法，不要照抄原题；难度适中。\n'
    '每道题都要给出答案与详细解析（解析用于学生做错后展示）。\n'
    '数学公式一律使用 LaTeX：行内用 $...$，独立公式用 $$...$$，'
    '不要用代码块包裹公式，不要用 ^ 表示幂。\n'
    '只输出JSON，格式：\n'
    '{{"judge": [{{"question": "判断题目", "answer": "对", '
    '"analysis": "解析"}}], '
    '"choice": [{{"question": "选择题目", '
    '"options": ["A选项", "B选项", "C选项", "D选项"], '
    '"answer": "A", "analysis": "解析"}}], '
    '"fill": [{{"question": "填空题目", "answer": "答案", '
    '"analysis": "解析"}}], '
    '"essay": [{{"question": "解答题题目", '
    '"answer": "参考答案", "analysis": "完整解题过程"}}]}}\n'
    '学生的错题如下：\n{wrong_text}'
)


@chat_bp.route('/api/exam/generate', methods=['POST'])
@login_required
def api_exam_generate():

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}
    major = normalize_text(data.get('major'), 20)

    if major not in ai_service.MAJOR_CATEGORIES:
        return fail('请选择正确的学科')

    try:
        wrong_rows = ai_service.get_exam_wrong_rows(user_id, major)
    except Exception as exc:
        logger.error('读取错题失败: %s', exc)
        return fail('错题读取失败，请检查数据库连接', status=500)

    if not wrong_rows:
        return fail('该学科暂无错题，请先在 AI 回答页把题目加入错题集')

    wrong_lines = []

    for index, wrong in enumerate(wrong_rows, 1):
        wrong_lines.append(f'{index}. 题目：{wrong["question"]}')

        if wrong.get('subs'):
            wrong_lines.append(f'   涉及小类：{wrong["subs"]}')

        answer = wrong.get('answer') or '（无）'

        if len(answer) > 1200:
            answer = answer[:1200] + '……'

        wrong_lines.append(f'   参考解答：{answer}')

    prompt = EXAM_PROMPT_TEMPLATE.format(
        major=major,
        wrong_text='\n'.join(wrong_lines)
    )

    content, _finish = ai_service.call_ai(
        [{'role': 'user', 'content': prompt}],
        max_tokens=4000,
        json_mode=True
    )

    if not content:
        return fail('出题失败，请稍后重试', status=503, code='AI_UNAVAILABLE')

    exam = ai_service.parse_json_object(content)

    if not exam:
        return fail('AI 返回格式异常，请重新生成', status=502)

    exam = {
        'judge': exam.get('judge') or [],
        'choice': exam.get('choice') or [],
        'fill': exam.get('fill') or [],
        'essay': exam.get('essay') or []
    }

    # 标记题目来源：AI 生成且未经人工校验，前端据此明确提示
    for item in (
        exam['judge'] + exam['choice'] + exam['fill'] + exam['essay']
    ):
        if isinstance(item, dict):
            item['answer_source'] = 'ai'
            item['verified'] = False

    paper_id = None

    try:
        paper_id = ai_service.save_exam_paper(user_id, major, exam)
    except Exception as exc:
        logger.error('保存试卷失败: %s', exc)

    return ok(
        exam=exam,
        major=major,
        paper_id=paper_id,
        notice='本卷由 AI 根据你的错题生成，答案仅供参考，请以课本与教师讲解为准'
    )


@chat_bp.route('/api/exam/process', methods=['POST'])
@login_required
def api_exam_process():

    data = request.get_json(silent=True) or {}
    question = normalize_text(data.get('question'), 4000)
    user_answer = normalize_text(data.get('user_answer'), 4000)

    if not question:
        return fail('题目不能为空')

    prompt = (
        '请为下面这道题写出详细、通俗易懂的解题过程（分步骤，方便学生理解）。\n'
        '数学公式必须使用 LaTeX：行内用 $...$，独立公式用 $$...$$。\n'
        f'题目：{question}\n'
    )

    if user_answer:
        prompt += (
            f'学生作答：{user_answer}\n'
            '请先指出学生作答正确的部分，再逐处指出与标准解法的差异'
            '（具体到哪一步、错在哪里）、判断错误类型并给出纠正建议；'
            '如果无法可靠判断错因，直接说明无法确定，不要编造。\n'
        )

    content = ai_service.complete_ai_answer([
        {'role': 'user', 'content': prompt}
    ])

    if not content:
        return fail('生成过程失败，请稍后重试', status=503, code='AI_UNAVAILABLE')

    return ok(
        process=content,
        process_plain=ai_service.format_ai_output(content)
    )


@chat_bp.route('/api/exam/papers', methods=['GET'])
@login_required
def api_exam_papers():

    user_id = session.get('userid')

    try:
        rows = ai_service.get_exam_papers(user_id)
    except Exception as exc:
        logger.error('读取试卷列表失败: %s', exc)
        return fail('试卷列表读取失败', status=500)

    return ok(data=[
        {
            'id': row['id'],
            'major': row['major'],
            'created_at': str(row['created_at'])
        }
        for row in rows
    ])


@chat_bp.route('/api/exam/papers/<int:paper_id>', methods=['GET'])
@login_required
def api_exam_paper_detail(paper_id):

    user_id = session.get('userid')

    try:
        row = ai_service.get_exam_paper(user_id, paper_id)
    except Exception as exc:
        logger.error('读取试卷失败: %s', exc)
        return fail('试卷读取失败', status=500)

    if not row:
        return not_found('试卷不存在')

    try:
        exam = json.loads(row['exam_json'])
    except Exception:
        return fail('试卷数据异常', status=500)

    return ok(exam=exam, major=row['major'], paper_id=paper_id)

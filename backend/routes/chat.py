# -*- coding: utf-8 -*-
"""AI 相关接口：对话、会话历史、错题集、试卷生成。

页面路由（/chat、/exam、/errors_register 等）由 page.py 提供，
本文件只负责 /api/* 接口，逻辑在 backend/services/ai_service.py。
"""

import json
import re

from flask import Blueprint, jsonify, request, session

from backend.services import ai_service


chat_bp = Blueprint(
    'ai_chat',
    __name__
)


# ============================================================
# AI 对话接口（识图 / 识别文字 / 回答问题 / 记忆）
# ============================================================

@chat_bp.route('/api/chat', methods=['POST'])
def api_chat():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}
    messages = data.get('messages') or []
    image_url = data.get('image_url') or ''
    conv_id = data.get('conversation_id')

    # 取最后一条用户消息
    question = ''

    for m in reversed(messages):
        if m.get('role') == 'user':
            question = (m.get('content') or '').strip()
            break

    if not question:
        question = '请分析这张图片' if image_url else ''

    if not question:
        return jsonify({
            'success': False,
            'message': '请输入问题'
        }), 400

    image_base64 = (
        ai_service.load_image_base64(image_url)
        if image_url
        else None
    )

    # 校验会话归属（防止串用户）
    if conv_id:
        try:
            conv_id = (
                conv_id
                if ai_service.conversation_belongs_to_user(
                    user_id,
                    conv_id
                )
                else None
            )
        except Exception as e:
            print('校验会话失败:', e)
            conv_id = None

    # 1. 判断是否需要调用历史记忆
    memory_used = False
    memories = []
    decision = ai_service.should_use_memory(question)

    try:
        if decision is None:
            recent = ai_service.get_recent_memories(user_id)
            decision = ai_service.ai_decide_memory(
                question,
                [m['question'] for m in recent]
            )

        if decision:
            memories = ai_service.get_recent_memories(user_id)

            if memories:
                memory_used = True
    except Exception as e:
        print('读取记忆失败（将不带记忆继续回答）:', e)

    # 2. 组装 AI 消息
    ai_messages = []

    if memory_used:
        ctx_lines = [
            '以下是用户最近 5 次提问与解答记录'
            '（按时间从早到晚编号，编号越大越新）。'
            '用户现在可能是在追问这些题，请先结合记录理解他到底问的是哪道题，'
            '再针对性地详细讲解，不要只说套话：'
        ]

        for i, m in enumerate(reversed(memories), 1):
            ctx_lines.append(f'{i}. 题目：{m["question"]}')
            ctx_lines.append(f'   解答：{m["answer"] or "（无）"}')

        ai_messages.append({
            'role': 'system',
            'content': '\n'.join(ctx_lines)
        })

    system_prompt = (
        '你是 IntelliLearn 的学习助手。请用最通俗的中文回答问题：'
        '1) 直接给出结论和分步骤过程，每步说明为什么这样做，像给同学讲题一样；'
        '2) 禁止出现用户看不懂的内容：不要 LaTeX、不要反斜杠、'
        '不要 Markdown 表格、不要内部术语；'
        '3) 数学公式用普通文字符号，例如 lim(x→0) sinx/x、'
        '∫0^1 x^2 dx、√2；幂用 ^ 写法（如 e^(x)、x^2）；'
        '4) 计算务必仔细，给出答案前在心里复核一遍；'
        '5) 如果题目信息不足或没有把握，直接说明哪里不确定，不要硬编答案；'
        '6) 回答要完整，不要中途截断。'
    )

    if image_base64:
        ai_messages.append({
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': system_prompt + '\n\n用户提问：' + question
                },
                {
                    'type': 'image_url',
                    'image_url': {'url': image_base64}
                }
            ]
        })
    else:
        ai_messages.append({
            'role': 'user',
            'content': system_prompt + '\n\n用户提问：' + question
        })

    # 3. 调用 AI（截断自动续写）
    reply = ai_service.complete_ai_answer(ai_messages)

    if not reply:
        # 回答失败也要把问题存下来，避免刷新丢失
        try:
            if not conv_id:
                conv_id = ai_service.create_conversation(
                    user_id,
                    question[:15] or '新对话'
                )

            ai_service.save_chat_message(
                conv_id,
                user_id,
                'user',
                (
                    ''
                    if question == '请分析这张图片'
                    else question
                ),
                image_url
            )
        except Exception as e:
            print('保存问题失败:', e)

        return jsonify({
            'success': False,
            'message': 'AI 服务暂时不可用，请稍后重试'
        })

    reply = ai_service.format_ai_output(reply)

    # 4. 拍图题目做双重分类 + 提取题目文字
    classification = None
    saved_question = question

    if image_base64:
        classification = ai_service.classify_question(
            question,
            image_base64
        )
        saved_question = (
            classification.get('question')
            or question
        )

        if not classification.get('major'):
            classification = None

    # 5. 保存会话消息（所有问答都保留，刷新不丢失）
    try:
        if not conv_id:
            title = (
                saved_question
                or question
            )[:15] or '新对话'
            conv_id = ai_service.create_conversation(
                user_id,
                title
            )

        ai_service.save_chat_message(
            conv_id,
            user_id,
            'user',
            saved_question,
            image_url
        )
        ai_service.save_chat_message(
            conv_id,
            user_id,
            'assistant',
            reply
        )
    except Exception as e:
        print('保存会话消息失败:', e)

    # 6. 保存记忆（每个用户只保留最近 5 条，作为 AI 上下文）
    try:
        sub_text = None

        if classification and classification.get('sub'):
            sub_text = '、'.join(classification['sub'])

        ai_service.save_memory(
            user_id,
            saved_question,
            reply,
            image_url,
            (
                classification.get('major')
                if classification
                else None
            ),
            sub_text
        )
    except Exception as e:
        print('保存记忆失败:', e)

    return jsonify({
        'success': True,
        'reply': reply,
        'conversation_id': conv_id,
        'memory_used': memory_used,
        'classification': classification,
        'question': saved_question,
        'image_url': image_url
    })


# ============================================================
# 对话列表 / 对话详情
# ============================================================

@chat_bp.route('/api/conversations', methods=['GET'])
def api_conversations():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')

    try:
        rows = ai_service.get_conversations(user_id)
    except Exception as e:
        print('读取对话列表失败:', e)
        return jsonify({
            'success': False,
            'message': '对话列表读取失败'
        }), 500

    data = []

    for r in rows:
        preview = (
            r.get('last_answer')
            or r.get('last_question')
            or ''
        )[:25]

        data.append({
            'id': r['id'],
            'title': r['title'] or '新对话',
            'preview': preview,
            'updated_at': str(r['updated_at'])
        })

    return jsonify({
        'success': True,
        'data': data
    })


@chat_bp.route(
    '/api/conversations/<int:conv_id>',
    methods=['GET']
)
def api_conversation_detail(conv_id):

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')

    try:
        owned = ai_service.conversation_belongs_to_user(
            user_id,
            conv_id
        )
    except Exception as e:
        print('读取对话详情失败:', e)
        return jsonify({
            'success': False,
            'message': '对话读取失败'
        }), 500

    if not owned:
        return jsonify({
            'success': False,
            'message': '对话不存在'
        }), 404

    try:
        rows = ai_service.get_chat_messages(
            user_id,
            conv_id
        )
    except Exception as e:
        print('读取对话消息失败:', e)
        return jsonify({
            'success': False,
            'message': '对话读取失败'
        }), 500

    return jsonify({
        'success': True,
        'data': {
            'messages': [
                {
                    'role': r['role'],
                    'content': r['content'] or '',
                    'image_url': r['image_url'] or ''
                }
                for r in rows
            ]
        }
    })


# ============================================================
# 错题集接口
# ============================================================

@chat_bp.route(
    '/api/wrong_questions',
    methods=['GET', 'POST']
)
def api_wrong_questions():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')

    if request.method == 'GET':
        try:
            rows = ai_service.get_wrong_questions(user_id)
        except Exception as e:
            print('读取错题集失败:', e)
            return jsonify({
                'success': False,
                'message': '错题集读取失败'
            }), 500

        data = []

        for r in rows:
            item = dict(r)
            item['created_at'] = str(
                r.get('created_at') or ''
            )
            data.append(item)

        return jsonify({
            'success': True,
            'data': data
        })

    # POST：加入错题集
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    major = data.get('major') or ''
    subs = data.get('sub') or []

    if not question or major not in ai_service.MAJOR_CATEGORIES:
        return jsonify({
            'success': False,
            'message': '题目或分类信息不完整'
        }), 400

    if isinstance(subs, str):
        subs = [subs]

    subs = [s for s in subs if s] or ['']
    answer = data.get('answer') or ''
    image_url = data.get('image_url') or ''
    source = data.get('source') or 'AI'
    added = 0

    try:
        for sub in subs:
            if ai_service.add_wrong_question(
                user_id,
                major,
                sub,
                question,
                answer,
                image_url,
                source
            ):
                added += 1
    except Exception as e:
        print('加入错题集失败:', e)

        if 'Access denied' in str(e) or '1045' in str(e):
            return jsonify({
                'success': False,
                'message': (
                    '数据库连接失败：MySQL 密码不正确，'
                    '请在 .env 中检查 DB_PASSWORD 后重试'
                )
            }), 500

        return jsonify({
            'success': False,
            'message': '加入错题集失败，请稍后重试'
        }), 500

    if added:
        return jsonify({
            'success': True,
            'added': added,
            'message': f'已加入错题集（{len(subs)} 个分类）'
        })

    return jsonify({
        'success': True,
        'added': 0,
        'message': '该题已在错题集中'
    })


# ============================================================
# 试卷生成接口
# ============================================================

@chat_bp.route('/api/exam/generate', methods=['POST'])
def api_exam_generate():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')
    data = request.get_json(silent=True) or {}
    major = data.get('major') or ''

    if major not in ai_service.MAJOR_CATEGORIES:
        return jsonify({
            'success': False,
            'message': '请选择正确的学科'
        }), 400

    # 调取该用户该大类的错题（随机抽取，最多 6 道）
    try:
        wrong_rows = ai_service.get_exam_wrong_rows(
            user_id,
            major
        )
    except Exception as e:
        print('读取错题失败:', e)
        return jsonify({
            'success': False,
            'message': '错题读取失败，请检查数据库连接'
        }), 500

    if not wrong_rows:
        return jsonify({
            'success': False,
            'message': (
                '该学科暂无错题，'
                '请先在 AI 回答页把题目加入错题集'
            )
        })

    wrong_lines = []

    for i, w in enumerate(wrong_rows, 1):
        wrong_lines.append(f'{i}. 题目：{w["question"]}')

        if w.get('subs'):
            wrong_lines.append(f'   涉及小类：{w["subs"]}')

        wrong_lines.append(
            f'   参考解答：{w["answer"] or "（无）"}'
        )

    wrong_text = '\n'.join(wrong_lines)

    prompt = (
        f'你是出题老师。请根据学生以下错题涉及的知识点，'
        f'为"{major}"出一份小试卷：\n'
        '3 道判断题（答案只能是对/错）、3 道单选题（4个选项）、'
        '3 道填空题、1 道解答题。\n'
        '要求：题目围绕错题涉及的知识点，随机变换数据和问法，'
        '不要照抄原题；难度适中。\n'
        '每道题都要给出答案与详细解析（解析用于学生做错后展示）。\n'
        '不要使用 LaTeX 语法（如 \\frac、\\lim_、\\sqrt），'
        '数学公式用普通文字符号表达，例如 lim(x→0) sinx/x、'
        '∫0^1 x^2 dx、√2；幂用 ^ 写法（如 x^2）。\n'
        '只输出JSON，格式：\n'
        '{"judge": [{"question": "判断题目", "answer": "对", '
        '"analysis": "解析"}], '
        '"choice": [{"question": "选择题目", '
        '"options": ["A选项", "B选项", "C选项", "D选项"], '
        '"answer": "A", "analysis": "解析"}], '
        '"fill": [{"question": "填空题目", "answer": "答案", '
        '"analysis": "解析"}], '
        '"essay": [{"question": "解答题题目", '
        '"answer": "参考答案", "analysis": "完整解题过程"}]}\n'
        f'学生的错题如下：\n{wrong_text}'
    )

    content, _ = ai_service.call_ai(
        [{'role': 'user', 'content': prompt}],
        max_tokens=4000,
        json_mode=True
    )

    if not content:
        return jsonify({
            'success': False,
            'message': '出题失败，请稍后重试'
        })

    try:
        exam = json.loads(content)
    except Exception:
        m = re.search(r'\{.*\}', content, re.S)

        if not m:
            return jsonify({
                'success': False,
                'message': 'AI 返回格式异常，请重新生成'
            })

        try:
            exam = json.loads(m.group(0))
        except Exception:
            return jsonify({
                'success': False,
                'message': 'AI 返回格式异常，请重新生成'
            })

    exam = {
        'judge': exam.get('judge') or [],
        'choice': exam.get('choice') or [],
        'fill': exam.get('fill') or [],
        'essay': exam.get('essay') or []
    }

    # 统一清理 LaTeX 并转上标，保证学生能直接看懂
    for item in (
        exam['judge']
        + exam['choice']
        + exam['fill']
        + exam['essay']
    ):
        for key in ('question', 'answer', 'analysis'):
            if key in item:
                item[key] = ai_service.format_ai_output(
                    item[key]
                )

        if 'options' in item and isinstance(item['options'], list):
            item['options'] = [
                ai_service.format_ai_output(o)
                for o in item['options']
            ]

    # 保存试卷，供“历史试卷”再次查看
    paper_id = None

    try:
        paper_id = ai_service.save_exam_paper(
            user_id,
            major,
            exam
        )
    except Exception as e:
        print('保存试卷失败:', e)

    return jsonify({
        'success': True,
        'exam': exam,
        'major': major,
        'paper_id': paper_id
    })


@chat_bp.route('/api/exam/process', methods=['POST'])
def api_exam_process():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    user_answer = (data.get('user_answer') or '').strip()

    if not question:
        return jsonify({
            'success': False,
            'message': '题目不能为空'
        }), 400

    prompt = (
        '请为下面这道解答题写出详细、通俗易懂的解题过程'
        '（分步骤，方便学生理解）。\n'
        '不要使用 LaTeX 语法（如 \\frac、\\lim_），'
        '数学公式用普通文字符号表达，例如 lim(x→0) sinx/x、'
        '∫0^1 x^2 dx、√2；幂用 ^ 写法（如 x^2）。\n'
        f'题目：{question}\n'
    )

    if user_answer:
        prompt += (
            f'学生作答：{user_answer}\n'
            '请先简单点评学生答案的对错，再给出完整解题过程。\n'
        )

    content = ai_service.complete_ai_answer([
        {'role': 'user', 'content': prompt}
    ])

    if not content:
        return jsonify({
            'success': False,
            'message': '生成过程失败，请稍后重试'
        })

    return jsonify({
        'success': True,
        'process': ai_service.format_ai_output(content)
    })


# ============================================================
# 历史试卷接口
# ============================================================

@chat_bp.route('/api/exam/papers', methods=['GET'])
def api_exam_papers():

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')

    try:
        rows = ai_service.get_exam_papers(user_id)
    except Exception as e:
        print('读取试卷列表失败:', e)
        return jsonify({
            'success': False,
            'message': '试卷列表读取失败'
        }), 500

    data = [
        {
            'id': r['id'],
            'major': r['major'],
            'created_at': str(r['created_at'])
        }
        for r in rows
    ]

    return jsonify({
        'success': True,
        'data': data
    })


@chat_bp.route(
    '/api/exam/papers/<int:paper_id>',
    methods=['GET']
)
def api_exam_paper_detail(paper_id):

    if 'userid' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401

    user_id = session.get('userid')

    try:
        row = ai_service.get_exam_paper(
            user_id,
            paper_id
        )
    except Exception as e:
        print('读取试卷失败:', e)
        return jsonify({
            'success': False,
            'message': '试卷读取失败'
        }), 500

    if not row:
        return jsonify({
            'success': False,
            'message': '试卷不存在'
        }), 404

    try:
        exam = json.loads(row['exam_json'])
    except Exception:
        return jsonify({
            'success': False,
            'message': '试卷数据异常'
        }), 500

    return jsonify({
        'success': True,
        'exam': exam,
        'major': row['major'],
        'paper_id': paper_id
    })

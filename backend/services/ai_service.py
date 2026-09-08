# -*- coding: utf-8 -*-
"""AI 服务层：AI 调用、输出格式化，以及记忆/会话/错题/试卷的数据访问。

从“尝试”合并而来，按 intelli-learn 的分层结构放在 backend/services 下。
"""

import base64
import json
import os
import re

import requests

from config import Config
from backend.extensions.database import connect_db


# ============================================================
# AI 配置（agnes）
# ============================================================

AI_API_URL = Config.AI_API_URL
AI_API_KEY = Config.AI_API_KEY
AI_MODEL = Config.AI_MODEL

# agnes-2.5-flash 文档标注最大输出为 65.5K token；
# 主回答给足预算，避免长答案被截断后出现“停一下再续写”。
AI_ANSWER_MAX_TOKENS = 16000


# 大类
MAJOR_CATEGORIES = [
    '语文',
    '高数',
    '大物',
    '离散',
    '英语',
    'py',
    '历史',
    '地理',
    '政治'
]


# 高数小类（后续可继续增加）
GAOSHU_SUB_CATEGORIES = [
    '函数与极限',
    '导数与微分',
    '微分中值定理与导数的应用',
    '不定积分',
    '定积分',
    '定积分的应用',
    '微分方程',
    '向量代数与空间解析几何',
    '多元函数微分法及其应用',
    '重积分',
    '曲线积分与曲面积分',
    '无穷级数'
]


def call_ai(messages, max_tokens=2000, json_mode=False):
    """调用 agnes AI 接口，返回 (回答文本, finish_reason)；失败返回 (None, None)。"""

    if not AI_API_KEY:
        print('AI 调用失败: 未配置 AI_API_KEY（请在 .env 中填写）')
        return None, None

    payload = {
        'model': AI_MODEL,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.7
    }

    if json_mode:
        payload['response_format'] = {'type': 'json_object'}

    try:
        resp = requests.post(
            AI_API_URL,
            headers={
                'Authorization': 'Bearer ' + AI_API_KEY,
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data['choices'][0]
        return (
            choice['message']['content'].strip(),
            choice.get('finish_reason')
        )
    except Exception as e:
        print('AI 调用失败:', e)
        return None, None


def complete_ai_answer(messages, max_tokens=AI_ANSWER_MAX_TOKENS):
    """调用 AI，若回答被截断则自动续写，返回完整回答文本；失败返回 None。"""

    content, finish_reason = call_ai(
        messages,
        max_tokens=max_tokens
    )

    if content is None:
        return None

    if finish_reason == 'length':
        # 被截断：让 AI 从上次结束处继续，最多续写一次
        continuation_messages = messages + [
            {
                'role': 'assistant',
                'content': content
            },
            {
                'role': 'user',
                'content': (
                    '你的回答还没写完，请接着继续写完整，'
                    '不要重复前面已经写过的内容，直接续写。'
                )
            }
        ]
        extra, _ = call_ai(
            continuation_messages,
            max_tokens=max_tokens
        )

        if extra:
            content = content + '\n' + extra

    return content


# ============================================================
# AI 流式调用（SSE）
# ============================================================

def iter_ai_chunks(messages, max_tokens=2000, json_mode=False):
    """流式调用 OpenAI 兼容接口，逐段产出事件 dict。

    type 为 content / finish / error 之一：
    - content: {'type': 'content', 'text': '本段文字'}
    - finish:  {'type': 'finish', 'reason': 'stop' 或 'length'}
    - error:   {'type': 'error', 'message': '错误说明'}
    """

    if not AI_API_KEY:
        print(
            'AI 流式调用失败: 未配置 AI_API_KEY'
            '（请在 .env 中填写）'
        )
        yield {
            'type': 'error',
            'message': 'AI_API_KEY 未配置'
        }
        return

    payload = {
        'model': AI_MODEL,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.7,
        'stream': True
    }

    if json_mode:
        payload['response_format'] = {'type': 'json_object'}

    try:
        resp = requests.post(
            AI_API_URL,
            headers={
                'Authorization': 'Bearer ' + AI_API_KEY,
                'Content-Type': 'application/json'
            },
            json=payload,
            stream=True,
            timeout=(30, 180)
        )
        resp.raise_for_status()
        resp.encoding = 'utf-8'

        sse_seen = False
        json_lines = []

        # 不依赖 Content-Type：只要出现 data: 就按 SSE 处理；
        # 完全没有 data: 时，把整段响应当普通 JSON 解析（兼容不支持流式的接口）。
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line.strip()

            if not line:
                continue

            if line.startswith('data:'):
                if not sse_seen:
                    sse_seen = True
                    json_lines = []

                data_text = line[5:].strip()

                if data_text == '[DONE]':
                    yield {'type': 'finish', 'reason': 'stop'}
                    return

                if not data_text:
                    continue

                try:
                    data = json.loads(data_text)
                except Exception:
                    continue

                error = data.get('error')

                if error:
                    yield {
                        'type': 'error',
                        'message': (
                            error.get('message')
                            if isinstance(error, dict)
                            else str(error)
                        ) or 'AI 流式调用失败'
                    }
                    return

                choices = data.get('choices') or []

                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get('delta') or {}
                text = delta.get('content')
                finish_reason = choice.get('finish_reason')

                if text:
                    yield {'type': 'content', 'text': text}

                if finish_reason:
                    yield {
                        'type': 'finish',
                        'reason': finish_reason
                    }
                    return

                continue

            # SSE 的事件名等附加行忽略；已进入 SSE 后其余行不再参与 JSON 解析
            if sse_seen:
                continue

            # 非流式响应可能是完整 JSON，也可能被换行美化
            json_lines.append(line)

        # 流正常结束但没给 finish 标记（可能是 [DONE] 前连接被关闭）
        if sse_seen:
            yield {'type': 'finish', 'reason': 'stop'}
            return

        # 非流式 JSON：读取完成后一次性解析
        if json_lines:
            try:
                data = json.loads('\n'.join(json_lines))
            except Exception as e:
                print('AI 非流式响应解析失败:', e)
                yield {'type': 'error', 'message': str(e)}
                return

            error = data.get('error')

            if error:
                yield {
                    'type': 'error',
                    'message': (
                        error.get('message')
                        if isinstance(error, dict)
                        else str(error)
                    ) or 'AI 流式调用失败'
                }
                return

            choices = data.get('choices') or []
            choice = choices[0] if choices else {}
            message = choice.get('message') or {}
            text = message.get('content')

            if text:
                yield {'type': 'content', 'text': text.strip()}

            yield {
                'type': 'finish',
                'reason': choice.get('finish_reason') or 'stop'
            }
            return

        yield {'type': 'finish', 'reason': 'stop'}
    except Exception as e:
        print('AI 流式调用失败:', e)
        yield {'type': 'error', 'message': str(e)}


def stream_complete_ai_answer(messages, max_tokens=AI_ANSWER_MAX_TOKENS):
    """流式生成完整回答（与 complete_ai_answer 同语义）。

    自动处理：
    1. 回答被截断（finish_reason=length）时续写一次；
    2. 接口不支持流式时回退到普通调用，保证仍能回答。
    产出与 iter_ai_chunks 相同的事件 dict。
    """

    raw_parts = []
    stream_ok = False
    continued = False
    current_messages = messages

    try:
        while True:
            finish_reason = 'stop'
            got_error = False
            error_message = 'AI 流式调用失败'

            for event in iter_ai_chunks(
                current_messages,
                max_tokens=max_tokens
            ):
                etype = event.get('type')

                if etype == 'content':
                    stream_ok = True
                    raw_parts.append(event.get('text') or '')
                    yield event
                elif etype == 'finish':
                    finish_reason = (
                        event.get('reason') or 'stop'
                    )
                elif etype == 'error':
                    got_error = True
                    error_message = (
                        event.get('message')
                        or error_message
                    )

            if got_error and not stream_ok:
                # 首次请求完全失败：回退到一次性接口
                content = complete_ai_answer(
                    messages,
                    max_tokens=max_tokens
                )

                if content:
                    yield {
                        'type': 'content',
                        'text': content
                    }
                    yield {
                        'type': 'finish',
                        'reason': 'stop'
                    }
                else:
                    yield {
                        'type': 'error',
                        'message': error_message
                    }
                return

            if (
                finish_reason == 'length'
                and not continued
            ):
                continued = True
                current_messages = messages + [
                    {
                        'role': 'assistant',
                        'content': ''.join(raw_parts)
                    },
                    {
                        'role': 'user',
                        'content': (
                            '你的回答还没写完，请接着继续写完整，'
                            '不要重复前面已经写过的内容，直接续写。'
                        )
                    }
                ]
                continue

            # 续写失败时保留已生成的部分，不再报错
            yield {
                'type': 'finish',
                'reason': (
                    'stop'
                    if got_error and raw_parts
                    else finish_reason
                )
            }
            return
    except Exception as e:
        print('流式生成回答失败:', e)
        content = complete_ai_answer(
            messages,
            max_tokens=max_tokens
        )

        if content:
            yield {
                'type': 'content',
                'text': content
            }
            yield {
                'type': 'finish',
                'reason': 'stop'
            }
        else:
            yield {
                'type': 'error',
                'message': str(e)
            }


# ============================================================
# AI 输出格式化：清 LaTeX + ^ 幂写法转上标
# ============================================================

SUPERSCRIPT_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵',
    '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ', 'f': 'ᶠ',
    'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ', 'k': 'ᵏ', 'l': 'ˡ',
    'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ', 'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ',
    't': 'ᵗ', 'u': 'ᵘ', 'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ',
    'z': 'ᶻ',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾'
}

SUPERSCRIPT_RE = re.compile(
    r'\^(\{[^}]*\}|\([^)]*\)|[A-Za-z]+|\d+|.)'
)


def superscript_of(text):
    return ''.join(
        SUPERSCRIPT_MAP.get(ch, ch)
        for ch in text
    )


def format_superscript(text):
    """把 ^ 幂写法转成 Unicode 上标。"""

    if not text:
        return text

    def repl(m):
        inner = m.group(1)
        if (
            inner.startswith('{') and inner.endswith('}')
        ) or (
            inner.startswith('(') and inner.endswith(')')
        ):
            inner = inner[1:-1]
        return superscript_of(inner)

    return SUPERSCRIPT_RE.sub(repl, text)


LATEX_REPLACEMENTS = [
    (r'\\left|\\right', ''),
    (r'\\,|\\;|\\!', ''),
    (r'\\cdot', '·'),
    (r'\\times', '×'),
    (r'\\div', '÷'),
    (r'\\to|\\rightarrow|\\Rightarrow', '→'),
    (r'\\infty', '∞'),
    (r'\\pi', 'π'),
    (r'\\alpha', 'α'),
    (r'\\beta', 'β'),
    (r'\\gamma', 'γ'),
    (r'\\theta', 'θ'),
    (r'\\Delta', 'Δ'),
    (r'\\lambda', 'λ'),
    (r'\\mu', 'μ'),
    (r'\\sigma', 'σ'),
    (r'\\omega', 'ω'),
    (r'\\ge', '≥'),
    (r'\\le', '≤'),
    (r'\\neq|\\ne', '≠'),
    (r'\\pm', '±'),
    (r'\\approx', '≈'),
    (r'\\sqrt\{([^}]*)\}', r'√(\1)'),
    (r'\\frac\{([^}]*)\}\{([^}]*)\}', r'(\1)/(\2)'),
    (r'\\lim_\{([^}]*)\}', r'lim(\1)'),
    (r'\\int_\{([^}]*)\}\^\{([^}]*)\}', r'∫\1^\2'),
    (r'\\int\^\{([^}]*)\}_\{([^}]*)\}', r'∫\1^\2'),
    (r'\\text\{([^}]*)\}', r'\1'),
    (r'\\\(|\\\)|\\\[|\\\]', ''),
]


def clean_latex(text):
    """清理 AI 偶尔输出的 LaTeX 片段，转成普通可读文本。"""

    if not text:
        return text

    # 先合并可能的双反斜杠（JSON 转义后常见）
    result = text.replace('\\\\', '\\')

    for pattern, repl in LATEX_REPLACEMENTS:
        result = re.sub(pattern, repl, result)

    # 去掉残留的 $ 和反斜杠
    result = result.replace('$', '').replace('\\', '')

    return result


def format_ai_output(text):
    """AI 输出最终处理：清 LaTeX + 上标转换。"""

    return format_superscript(clean_latex(text))


# ============================================================
# 记忆：关键词判断 + AI 兜底判断
# ============================================================

MEMORY_USE_KEYWORDS = [
    '之前', '刚才', '上次', '先前', '早先', '前面', '上面',
    '上一题', '上一道', '前几', '之前那', '刚才那', '上次那',
    '还记得', '记得', '回忆', '回顾', '继续', '接着', '那题',
    '那道', '这题', '这道', '然后', '另外', '再说',
    '第一题', '第二题', '第三题', '第四题', '第五题', '第几题',
    '下一题', '下一道', '刚才那道', '之前那道', '刚才问的',
    '上一问', '下一问', '第二道', '第三道'
]

MEMORY_SKIP_KEYWORDS = [
    '不用记忆', '不要记忆', '无需记忆', '忽略之前',
    '忘记之前', '重新开始', '新题目', '无关'
]


def should_use_memory(question):
    """返回 True=需要记忆 / False=不需要 / None=无法判断。"""

    for kw in MEMORY_SKIP_KEYWORDS:
        if kw in question:
            return False

    for kw in MEMORY_USE_KEYWORDS:
        if kw in question:
            return True

    return None


def ai_decide_memory(question, memory_summary):
    """无法用关键词判断时，把语境交给 AI 判断是否需要历史记忆。"""

    if (
        not memory_summary
        or question == '请分析这张图片'
    ):
        # 没有历史记录，或只是默认拍图分析，不需要再额外调用 AI 判断
        return False

    try:
        summary_text = (
            '\n'.join(
                f'{i + 1}. {q}'
                for i, q in enumerate(memory_summary)
            )
            or '（暂无）'
        )

        prompt = (
            '你是记忆判断助手。根据用户当前问题，'
            '判断是否需要参考他最近的历史提问记录。\n'
            '如果当前问题是在追问、对比、回忆、延续之前的题目，回答 true；'
            '如果当前问题与历史无关或明显是新话题，回答 false。\n'
            f'用户最近的提问记录：\n{summary_text}\n'
            f'用户当前问题：{question}\n'
            '只输出JSON，格式：{"use_memory": true 或 false}'
        )

        content, _ = call_ai(
            [{'role': 'user', 'content': prompt}],
            max_tokens=60,
            json_mode=True
        )

        if content:
            data = json.loads(content)
            return bool(data.get('use_memory'))
    except Exception as e:
        print('记忆判断失败:', e)

    return False


# ============================================================
# 记忆/会话/错题/试卷：数据库操作
# ============================================================

def get_recent_memories(user_id):
    """取某用户最近 5 条记忆。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, question, answer, image_url
                FROM ai_memories
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT 5
                """,
                (user_id,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def save_memory(
    user_id,
    question,
    answer,
    image_url=None,
    major=None,
    sub=None
):
    """保存一条记忆并只保留最近 5 条，返回新记忆 ID。"""

    new_id = None
    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ai_memories
                (user_id, question, answer, image_url, major, sub)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    question,
                    answer,
                    image_url or None,
                    major,
                    sub
                )
            )

            new_id = cursor.lastrowid

            # 每个用户只保留最近 5 条
            cursor.execute(
                """
                DELETE FROM ai_memories
                WHERE user_id = %s
                  AND id NOT IN (
                    SELECT id
                    FROM (
                      SELECT id
                      FROM ai_memories
                      WHERE user_id = %s
                      ORDER BY id DESC
                      LIMIT 5
                    ) t
                  )
                """,
                (user_id, user_id)
            )

            connection.commit()
    finally:
        connection.close()

    return new_id


def load_image_base64(image_url):
    """把图片地址转成 base64 data URL，供 AI 识图。"""

    if not image_url:
        return None

    if image_url.startswith('data:image'):
        return image_url

    try:
        if (
            image_url.startswith('http://')
            or image_url.startswith('https://')
        ):
            resp = requests.get(image_url, timeout=20)
            resp.raise_for_status()
            raw = resp.content
        else:
            # intelli-learn 的上传目录位于项目根目录 uploads 下，
            # 因此以 Config.BASE_DIR 为根解析本地 URL。
            file_path = os.path.join(
                Config.BASE_DIR,
                image_url.lstrip('/')
            )

            if not os.path.exists(file_path):
                return None

            with open(file_path, 'rb') as f:
                raw = f.read()

        ext = os.path.splitext(
            image_url.split('?')[0]
        )[1].lower()

        mime = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }.get(ext, 'image/jpeg')

        return (
            'data:' + mime + ';base64,'
            + base64.b64encode(raw).decode('utf-8')
        )
    except Exception as e:
        print('读取图片失败:', e)
        return None


def classify_question(question, image_base64=None):
    """双重分类：大类 + 高数小类，同时提取题目原文。"""

    sub_list = '、'.join(GAOSHU_SUB_CATEGORIES)

    prompt = (
        '你是一个学科分类助手。请把下面的题目分类到大类：'
        + '、'.join(MAJOR_CATEGORIES)
        + '。\n'
        '如果大类是"高数"，再从以下小类中选择（可多选，最多3个）：'
        + sub_list
        + '。\n'
        '同时提取题目原文（用于记忆和错题集，保持题目内容不变）。\n'
        '只输出JSON：'
        '{"question": "题目原文", "major": "大类", "sub": ["小类1", "小类2"]}'
    )

    if image_base64:
        extra = (
            question
            if question and question != '请分析这张图片'
            else '（用户未输入文字，请以图片为准）'
        )
        messages = [{
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': prompt + '\n\n用户附加说明：' + extra
                },
                {
                    'type': 'image_url',
                    'image_url': {'url': image_base64}
                }
            ]
        }]
    else:
        messages = [{
            'role': 'user',
            'content': prompt + '\n\n题目：' + question
        }]

    content, _ = call_ai(
        messages,
        max_tokens=200,
        json_mode=True
    )

    fallback = {
        'question': question,
        'major': '',
        'sub': []
    }

    if not content:
        return fallback

    try:
        data = json.loads(content)
    except Exception:
        try:
            match = re.search(r'\{.*\}', content, re.S)
            data = json.loads(match.group(0)) if match else {}
        except Exception:
            return fallback

    major = data.get('major') or ''

    if major not in MAJOR_CATEGORIES:
        major = ''

    subs = data.get('sub') or []

    if major != '高数':
        subs = []
    else:
        subs = [
            s for s in subs
            if s in GAOSHU_SUB_CATEGORIES
        ][:3]

    q_text = (
        data.get('question')
        or question
        or ''
    ).strip()

    return {
        'question': q_text,
        'major': major,
        'sub': subs
    }


def add_wrong_question(
    user_id,
    major,
    sub,
    question,
    answer,
    image_url=None,
    source='AI'
):
    """加入错题集，已存在则跳过，返回是否新增。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM wrong_questions
                WHERE user_id = %s
                  AND major = %s
                  AND sub = %s
                  AND question = %s
                LIMIT 1
                """,
                (
                    user_id,
                    major,
                    sub,
                    question
                )
            )

            if cursor.fetchone():
                return False

            cursor.execute(
                """
                INSERT INTO wrong_questions
                (
                    user_id,
                    major,
                    sub,
                    question,
                    answer,
                    image_url,
                    source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    major,
                    sub,
                    question,
                    answer,
                    image_url or None,
                    source
                )
            )

            connection.commit()
            return True
    finally:
        connection.close()


def create_conversation(user_id, title='新对话'):
    """新建一个会话，返回会话 ID。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_conversations (user_id, title)
                VALUES (%s, %s)
                """,
                (
                    user_id,
                    (title or '新对话')[:100]
                )
            )
            connection.commit()
            return cursor.lastrowid
    finally:
        connection.close()


def save_chat_message(
    conversation_id,
    user_id,
    role,
    content,
    image_url=None
):
    """保存一条会话消息。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_messages
                (
                    conversation_id,
                    user_id,
                    role,
                    content,
                    image_url
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    user_id,
                    role,
                    content,
                    image_url or None
                )
            )

            cursor.execute(
                """
                UPDATE chat_conversations
                SET updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id)
            )

            connection.commit()
    finally:
        connection.close()


def conversation_belongs_to_user(user_id, conv_id):
    """校验会话归属，返回 True/False。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM chat_conversations
                WHERE id = %s AND user_id = %s
                """,
                (conv_id, user_id)
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def get_conversations(user_id):
    """返回用户会话列表（含最近一条提问/回答用于预览）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.updated_at,
                    (
                        SELECT content
                        FROM chat_messages m
                        WHERE m.conversation_id = c.id
                          AND m.role = 'assistant'
                        ORDER BY m.id DESC
                        LIMIT 1
                    ) AS last_answer,
                    (
                        SELECT content
                        FROM chat_messages m
                        WHERE m.conversation_id = c.id
                          AND m.role = 'user'
                        ORDER BY m.id DESC
                        LIMIT 1
                    ) AS last_question
                FROM chat_conversations c
                WHERE c.user_id = %s
                ORDER BY c.updated_at DESC
                """,
                (user_id,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def get_chat_messages(user_id, conv_id):
    """按时间正序返回会话的全部消息。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content, image_url
                FROM chat_messages
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY id ASC
                """,
                (conv_id, user_id)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def get_wrong_questions(user_id):
    """返回用户错题列表（新的在前）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    major,
                    sub,
                    question,
                    answer,
                    image_url,
                    source,
                    created_at
                FROM wrong_questions
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def get_exam_wrong_rows(user_id, major):
    """取某用户某大类的错题，随机抽最多 6 道用于组卷。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    question,
                    MAX(answer) AS answer,
                    GROUP_CONCAT(DISTINCT sub) AS subs
                FROM wrong_questions
                WHERE user_id = %s AND major = %s
                GROUP BY question
                ORDER BY RAND()
                LIMIT 6
                """,
                (user_id, major)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def save_exam_paper(user_id, major, exam):
    """保存一份生成的试卷，返回试卷 ID。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO exam_papers
                (user_id, major, exam_json)
                VALUES (%s, %s, %s)
                """,
                (
                    user_id,
                    major,
                    json.dumps(exam, ensure_ascii=False)
                )
            )
            connection.commit()
            return cursor.lastrowid
    finally:
        connection.close()


def get_exam_papers(user_id):
    """返回用户试卷列表（新的在前）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, major, created_at
                FROM exam_papers
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def get_exam_paper(user_id, paper_id):
    """返回指定试卷（同时校验归属）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT major, exam_json
                FROM exam_papers
                WHERE id = %s AND user_id = %s
                """,
                (paper_id, user_id)
            )
            return cursor.fetchone()
    finally:
        connection.close()

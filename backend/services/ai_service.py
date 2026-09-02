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


def complete_ai_answer(messages, max_tokens=4000):
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

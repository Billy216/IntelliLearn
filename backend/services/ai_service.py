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
from backend.utils.logging_config import get_logger
from backend.utils.validators import resolve_upload_url


logger = get_logger('ai')


# ============================================================
# AI 配置（agnes）
# ============================================================

AI_API_URL = Config.AI_API_URL
AI_API_KEY = Config.AI_API_KEY
AI_MODEL = Config.AI_MODEL

# 请求超时（连接, 读取）
AI_TIMEOUT = Config.AI_TIMEOUT
AI_STREAM_TIMEOUT = Config.AI_STREAM_TIMEOUT

# agnes-2.5-flash 文档标注最大输出为 65.5K token；
# 主回答给足预算，避免长答案被截断后出现“停一下再续写”。
AI_ANSWER_MAX_TOKENS = Config.AI_ANSWER_MAX_TOKENS

# 同一会话内携带的历史消息条数与单条字符上限（控制上下文长度）
AI_CONTEXT_MAX_MESSAGES = Config.AI_CONTEXT_MAX_MESSAGES
AI_CONTEXT_MAX_CHARS = Config.AI_CONTEXT_MAX_CHARS


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
        logger.error('AI 调用失败: 未配置 AI_API_KEY（请在 .env 中填写）')
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
            timeout=AI_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data['choices'][0]
        return (
            choice['message']['content'].strip(),
            choice.get('finish_reason')
        )
    except Exception as e:
        logger.error('AI 调用失败: %s', e)
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
            timeout=AI_STREAM_TIMEOUT
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


def _encode_image_file(file_path, image_url):
    """读取图片文件并编码为 data URL。失败返回 None。"""

    try:
        size = os.path.getsize(file_path)

        if size <= 0:
            logger.warning('图片文件为空: %s', image_url)
            return None

        if size > Config.MAX_IMAGE_SIZE:
            logger.warning(
                '图片超过大小上限(%s 字节)，拒绝识别: %s',
                Config.MAX_IMAGE_SIZE,
                image_url
            )
            return None

        with open(file_path, 'rb') as f:
            raw = f.read()
    except OSError as exc:
        logger.warning('读取图片失败 %s: %s', image_url, exc)
        return None

    ext = os.path.splitext(file_path)[1].lower()

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


def load_question_image(image_url):
    """把题目图片地址转成 base64 data URL，供 AI 识图。

    安全约束（重要）：
    1. 只允许读取项目 uploads 目录内的文件，`..` 等穿越写法一律拒绝，
       避免通过 image_url 读取服务器任意文件；
    2. 默认拒绝 http(s) 远程地址（存在 SSRF 风险），
       确需远程取图时需在 .env 中显式开启 ALLOW_REMOTE_IMAGE_URL；
    3. 只接受白名单内的图片扩展名，并限制文件体积。

    返回 (data_url, 错误说明)。成功时错误说明为空串。
    """

    if not image_url or not isinstance(image_url, str):
        return None, ''

    image_url = image_url.strip()

    # 前端可能直接提交 data URL，限制体积后放行
    if image_url.startswith('data:image'):

        if len(image_url) > Config.MAX_IMAGE_SIZE * 2:
            return None, '图片过大，请压缩后重试'

        if ';base64,' not in image_url:
            return None, '图片数据格式不正确，请重新上传'

        return image_url, ''

    # 远程地址：默认关闭
    if image_url.startswith(('http://', 'https://')):

        if not Config.ALLOW_REMOTE_IMAGE_URL:
            logger.warning('已拒绝远程图片地址（未开启 ALLOW_REMOTE_IMAGE_URL）: %s', image_url)
            return None, '不支持直接使用网络图片地址，请先上传图片'

        try:
            resp = requests.get(image_url, timeout=20, stream=True)
            resp.raise_for_status()

            length = resp.headers.get('Content-Length')

            if length and int(length) > Config.MAX_IMAGE_SIZE:
                return None, '远程图片过大，请先下载后上传'

            raw = resp.content

            if len(raw) > Config.MAX_IMAGE_SIZE:
                return None, '远程图片过大，请先下载后上传'
        except Exception as exc:
            logger.warning('读取远程图片失败 %s: %s', image_url, exc)
            return None, '远程图片读取失败，请重新上传图片'

        ext = os.path.splitext(image_url.split('?')[0])[1].lower()

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
        ), ''

    # 站内路径：必须落在 uploads 目录之内
    file_path = resolve_upload_url(image_url)

    if not file_path:
        logger.warning('拒绝读取 uploads 之外的图片路径: %s', image_url)
        return None, '图片地址不合法'

    if not os.path.isfile(file_path):
        return None, '图片不存在或已被删除，请重新上传'

    if os.path.splitext(file_path)[1].lower().lstrip('.') not in Config.ALLOWED_EXTENSIONS:
        logger.warning('拒绝读取非图片扩展名文件: %s', image_url)
        return None, '图片格式不受支持'

    data_url = _encode_image_file(file_path, image_url)

    if not data_url:
        return None, '图片读取失败，请重新上传'

    return data_url, ''


def load_image_base64(image_url):
    """兼容旧调用：只返回 data URL，失败返回 None。"""

    data_url, _error = load_question_image(image_url)

    return data_url


# ============================================================
# 题目识别、作答分析与解题提示词
# ============================================================

# 错误类型（与 wrong_questions.error_type 取值保持一致）
ERROR_TYPES = [
    '概念理解错误',
    '计算错误',
    '步骤错误',
    '审题错误',
    '公式使用错误',
    '方法选择不当',
    '格式不规范',
    '无明显错误'
]

# 讲解类回答的系统提示词：允许并鼓励使用 LaTeX，前端用 KaTeX 渲染。
ANSWER_SYSTEM_PROMPT = (
    '你是 IntelliLearn 的学习助手，面向高校学生讲题。输出要求：\n'
    '1) 用中文，分步骤讲解，每一步说明"为什么这样做"，像给同学讲题一样；\n'
    '2) 所有数学公式必须使用 LaTeX 语法：行内公式用 $...$，'
    '独立公式用 $$...$$ 单独成行；'
    '例如 $\\lim_{x\\to 0}\\frac{\\sin x}{x}=1$、'
    '$\\int_0^1 x^2\\,\\mathrm{d}x$、$\\sqrt{2}$、'
    '$\\sum_{n=1}^{\\infty}\\frac{1}{n^2}$；'
    '矩阵、分段函数用 \\begin{pmatrix}...\\end{pmatrix}、'
    '\\begin{cases}...\\end{cases}；'
    '不要用代码块包裹公式，不要用 ^ 表示幂（用 $x^2$ 这样的 LaTeX）；\n'
    '3) 使用 Markdown 组织内容：用 "## 小标题" 分节，用有序列表列步骤，'
    '用 **加粗** 强调关键结论；\n'
    '4) 必须给出最终答案，并单独用 "## 最终答案" 一节列出；\n'
    '5) 结尾用 "## 相关知识点" 一节列出本题考查的知识点，'
    '再用 "## 同类练习建议" 一节给 1-2 条练习方向（只描述考点，不要编造具体题目答案）；\n'
    '6) 如果题目信息不足或图片模糊，必须明确说明哪一部分看不清、需要用户补充什么，'
    '严禁凭空编造题目内容；\n'
    '7) 如果没有把握，明确说明不确定之处，不要给出看似确定但可能错误的结论；\n'
    '8) 回答要完整，不要中途截断。'
)

# 学生作答比对提示词（在识别到学生手写作答时追加）
STUDENT_WORK_PROMPT = (
    '\n9) 已识别到学生的作答过程，请务必增加 "## 你的作答分析" 一节：\n'
    '   - 先指出学生作答中正确的部分；\n'
    '   - 再逐处指出与标准解法的差异（写出具体是哪一步、错在哪里）；\n'
    '   - 判断错误类型（概念理解错误/计算错误/步骤错误/审题错误/公式使用错误/'
    '方法选择不当/格式不规范），并说明判断依据；\n'
    '   - 给出针对性的纠正建议。\n'
    '   如果无法可靠判断学生错因，必须直接说明"无法确定具体错因"，不要编造。'
)


ANALYSIS_PROMPT = (
    '你是学科识别与作答分析助手。请阅读下面的题目（可能来自图片），完成四件事：\n'
    '1. 识别题目原文，尽量完整并保留数学符号；\n'
    '   如果图片模糊、被裁切或信息不足，把 question_clear 设为 false，'
    '并在 unclear_reason 中说明缺什么，不要猜测或补全题目。\n'
    '2. 判断学科大类，只能从以下列表中选择一个：'
    + '、'.join(MAJOR_CATEGORIES)
    + '。\n'
    '3. 如果是"高数"，再从以下小类中选择（最多 3 个）：'
    + '、'.join(GAOSHU_SUB_CATEGORIES)
    + '；其他学科 sub 返回空数组。\n'
    '4. 提炼知识点（knowledge_points，2-5 个简短词组），'
    '并识别图中是否包含学生自己的作答（has_student_work）。\n'
    '   只有在图中确实能看到学生的手写或打印作答过程时，'
    'has_student_work 才设为 true，并且必须把作答原文完整写进 student_work；'
    '只看到题目、看不到作答时，has_student_work 设为 false，student_work 留空。\n'
    '   如果学生作答与标准解法有差异，给出错误类型 error_types'
    '（只能从：' + '、'.join(ERROR_TYPES) + ' 中选择）'
    '和简短错误说明 error_analysis；没有学生作答时两者留空。\n'
    '只输出 JSON，不要输出任何解释文字，格式：\n'
    '{"question_text": "题目原文", "question_clear": true, '
    '"unclear_reason": "", "major": "高数", "sub": ["定积分"], '
    '"knowledge_points": ["牛顿-莱布尼茨公式"], '
    '"has_student_work": false, "student_work": "", '
    '"error_types": [], "error_analysis": "", '
    '"confidence": "high"}'
)


def _parse_json_object(content):
    """从 AI 返回文本中解析 JSON 对象，容忍前后多余文字。"""

    if not content:
        return None

    try:
        return json.loads(content)
    except Exception:
        pass

    match = re.search(r'\{.*\}', content, re.S)

    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None


# 对外公开名（供路由层复用同一套容错解析）
parse_json_object = _parse_json_object


def _empty_analysis(question):
    """分析失败时的兜底结构（明确标记为未识别，而不是伪造结果）。"""

    return {
        'question_text': question or '',
        'question_clear': bool(question),
        'unclear_reason': '',
        'major': '',
        'sub': [],
        'knowledge_points': [],
        'has_student_work': False,
        'student_work': '',
        'error_types': [],
        'error_analysis': '',
        'confidence': 'unknown',
        'analyzed': False
    }


def analyze_question(question, image_base64=None):
    """识别题目并对学生作答做结构化分析。

    返回 dict：
        question_text    识别出的题目原文
        question_clear   题目是否清晰可读
        unclear_reason   不清晰时的说明
        major / sub      学科大类与高数小类
        knowledge_points 知识点列表
        has_student_work 是否识别到学生作答
        student_work     学生作答原文
        error_types      错误类型列表
        error_analysis   错误原因说明
        confidence       模型自评置信度
        analyzed         是否真正完成了分析（AI 失败时为 False）

    识别失败时返回 analyzed=False 的结构，调用方据此提示用户重试，
    绝不编造识别结果。
    """

    user_text = (
        question
        if question and question != '请分析这张图片'
        else '（用户未输入文字，请以图片为准）'
    )

    if image_base64:
        messages = [{
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': ANALYSIS_PROMPT + '\n\n用户附加说明：' + user_text
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
            'content': ANALYSIS_PROMPT + '\n\n题目：' + user_text
        }]

    content, _finish = call_ai(messages, max_tokens=900, json_mode=True)

    data = _parse_json_object(content)

    if not data:
        return _empty_analysis(question)

    major = data.get('major') or ''

    if major not in MAJOR_CATEGORIES:
        major = ''

    subs = data.get('sub') or []

    if isinstance(subs, str):
        subs = [subs]

    if major != '高数':
        subs = []
    else:
        subs = [s for s in subs if s in GAOSHU_SUB_CATEGORIES][:3]

    knowledge_points = data.get('knowledge_points') or []

    if isinstance(knowledge_points, str):
        knowledge_points = [knowledge_points]

    knowledge_points = [
        str(kp).strip()[:60]
        for kp in knowledge_points
        if str(kp).strip()
    ][:6]

    error_types = data.get('error_types') or []

    if isinstance(error_types, str):
        error_types = [error_types]

    error_types = [e for e in error_types if e in ERROR_TYPES][:3]

    question_text = (
        str(data.get('question_text') or '').strip()
        or question
        or ''
    )

    student_work = str(data.get('student_work') or '').strip()[:4000]

    # 只有确实提取到作答内容时才算"识别到学生作答"：
    # 否则会出现"提示词说已识别到作答、正文却说看不到"的自相矛盾。
    has_student_work = bool(data.get('has_student_work')) and bool(student_work)

    return {
        'question_text': question_text,
        'question_clear': bool(data.get('question_clear', True)),
        'unclear_reason': str(data.get('unclear_reason') or '').strip()[:300],
        'major': major,
        'sub': subs,
        'knowledge_points': knowledge_points,
        'has_student_work': has_student_work,
        'student_work': student_work,
        'error_types': error_types if has_student_work else [],
        'error_analysis': (
            str(data.get('error_analysis') or '').strip()[:1000]
            if has_student_work else ''
        ),
        'confidence': str(data.get('confidence') or 'unknown')[:20],
        'analyzed': True
    }


def classify_question(question, image_base64=None):
    """兼容旧调用：只返回 {question, major, sub}。"""

    analysis = analyze_question(question, image_base64)

    return {
        'question': analysis['question_text'],
        'major': analysis['major'],
        'sub': analysis['sub']
    }


def build_answer_messages(question, image_base64=None, analysis=None):
    """组装讲解请求的消息体。

    - 系统提示词要求使用 LaTeX 与结构化 Markdown；
    - 若已识别到题目原文，则以识别结果为准，避免模型重新"看图猜题"；
    - 若识别到学生作答，追加作答比对要求。
    """

    system_prompt = ANSWER_SYSTEM_PROMPT

    if analysis and analysis.get('has_student_work'):
        system_prompt += STUDENT_WORK_PROMPT

    parts = []

    if analysis and analysis.get('analyzed'):
        parts.append('【已识别的题目】')
        parts.append(analysis['question_text'])

        if analysis.get('major'):
            parts.append('【学科】' + analysis['major'])

        if analysis.get('knowledge_points'):
            parts.append(
                '【可能涉及的知识点】'
                + '、'.join(analysis['knowledge_points'])
            )

        if analysis.get('has_student_work') and analysis.get('student_work'):
            parts.append('【识别到的学生作答】')
            parts.append(analysis['student_work'])

        if not analysis.get('question_clear'):
            parts.append(
                '【注意】图片中的题目信息可能不完整：'
                + (analysis.get('unclear_reason') or '存在看不清的内容')
                + '。请先说明哪里看不清，不要编造题目。'
            )

        if question and question != '请分析这张图片':
            parts.append('【用户补充说明】' + question)
    else:
        parts.append(question or '请分析这张图片')

    text = '\n'.join(parts)

    if image_base64:
        return [
            {'role': 'system', 'content': system_prompt},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': text},
                    {
                        'type': 'image_url',
                        'image_url': {'url': image_base64}
                    }
                ]
            }
        ]

    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': text}
    ]


def add_wrong_question(
    user_id,
    major,
    sub,
    question,
    answer,
    image_url=None,
    source='AI',
    knowledge_points='',
    error_type='',
    user_answer=None,
    standard_answer=None,
    analysis=None,
    conversation_id=None,
    message_id=None
):
    """加入错题集，已存在则跳过，返回是否新增。

    新增字段（知识点、错误类型、学生作答、标准答案、分析、来源会话）
    为错题本检索、复习推荐和学情统计提供数据基础。
    """

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

            existing = cursor.fetchone()

            if existing:
                # 已存在：补充本次新识别到的分析信息，不重复插入
                if knowledge_points or error_type or analysis:
                    cursor.execute(
                        """
                        UPDATE wrong_questions
                        SET knowledge_points = CASE
                                WHEN %s = '' THEN knowledge_points
                                ELSE %s END,
                            error_type = CASE
                                WHEN %s = '' THEN error_type
                                ELSE %s END,
                            analysis = COALESCE(%s, analysis),
                            user_answer = COALESCE(%s, user_answer),
                            standard_answer = COALESCE(%s, standard_answer),
                            conversation_id = COALESCE(conversation_id, %s),
                            message_id = COALESCE(message_id, %s)
                        WHERE id = %s
                        """,
                        (
                            knowledge_points, knowledge_points,
                            error_type, error_type,
                            analysis,
                            user_answer,
                            standard_answer,
                            conversation_id,
                            message_id,
                            existing['id']
                        )
                    )

                    connection.commit()

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
                    source,
                    knowledge_points,
                    error_type,
                    user_answer,
                    standard_answer,
                    analysis,
                    conversation_id,
                    message_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    major,
                    sub,
                    question,
                    answer,
                    image_url or None,
                    source,
                    knowledge_points or '',
                    error_type or '',
                    user_answer,
                    standard_answer,
                    analysis,
                    conversation_id,
                    message_id
                )
            )

            new_id = cursor.lastrowid

            # 知识点冗余写入关联表，便于按知识点检索与统计
            if knowledge_points:
                for kp in {
                    item.strip()
                    for item in str(knowledge_points).replace('，', '、').split('、')
                    if item.strip()
                }:
                    cursor.execute(
                        """
                        INSERT IGNORE INTO wrong_question_kps
                        (wrong_question_id, kp_name)
                        VALUES (%s, %s)
                        """,
                        (new_id, kp[:150])
                    )

            connection.commit()
            return True
    finally:
        connection.close()


def create_conversation(user_id, title='新对话', major=None):
    """新建一个会话，返回会话 ID。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_conversations (user_id, title, major)
                VALUES (%s, %s, %s)
                """,
                (
                    user_id,
                    (title or '新对话')[:100],
                    major or None
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
    image_url=None,
    reply_plain=None,
    meta_json=None
):
    """保存一条会话消息。

    content 保存含 LaTeX 的原文，reply_plain 保存降级纯文本，
    meta_json 保存学科/知识点/错误类型等结构化信息。
    """

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
                    image_url,
                    reply_plain,
                    meta_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    user_id,
                    role,
                    content,
                    image_url or None,
                    reply_plain,
                    meta_json
                )
            )

            message_id = cursor.lastrowid

            cursor.execute(
                """
                UPDATE chat_conversations
                SET updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id)
            )

            connection.commit()

            return message_id
    finally:
        connection.close()


def conversation_belongs_to_user(user_id, conv_id):
    """校验会话归属（已软删除的会话视为不存在），返回 True/False。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM chat_conversations
                WHERE id = %s AND user_id = %s AND is_deleted = 0
                """,
                (conv_id, user_id)
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def get_conversations(user_id):
    """返回用户会话列表（含最近一条提问/回答用于预览）。

    只返回未软删除的会话。
    """

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.major,
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
                  AND c.is_deleted = 0
                ORDER BY c.updated_at DESC
                """,
                (user_id,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def delete_conversation(user_id, conv_id):
    """软删除会话，返回是否删除成功。

    采用软删除：聊天记录仍保留在库中，管理员可追溯，
    用户列表中不再出现。
    """

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chat_conversations
                SET is_deleted = 1, deleted_at = NOW()
                WHERE id = %s AND user_id = %s AND is_deleted = 0
                """,
                (conv_id, user_id)
            )

            affected = cursor.rowcount

            connection.commit()

            return affected > 0
    finally:
        connection.close()


def rename_conversation(user_id, conv_id, title):
    """重命名会话，返回是否成功。"""

    title = (title or '').strip()[:100]

    if not title:
        return False

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chat_conversations
                SET title = %s
                WHERE id = %s AND user_id = %s AND is_deleted = 0
                """,
                (title, conv_id, user_id)
            )

            affected = cursor.rowcount

            connection.commit()

            return affected > 0
    finally:
        connection.close()


def get_chat_messages(user_id, conv_id):
    """按时间正序返回会话的全部消息（含降级纯文本与结构化元信息）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content, image_url, reply_plain, meta_json
                FROM chat_messages
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY id ASC
                """,
                (conv_id, user_id)
            )
            return cursor.fetchall()
    finally:
        connection.close()


def get_conversation_context(user_id, conv_id, max_messages=None, max_chars=None):
    """取同一会话最近若干轮消息，用于保持上下文连续性。

    - 只取最近 max_messages 条（默认取配置值），避免无限制地把全部历史传给模型；
    - 单条消息超过 max_chars 时截断；
    - 图片不重复回传（只传文字），控制请求体积。
    """

    max_messages = max_messages or AI_CONTEXT_MAX_MESSAGES
    max_chars = max_chars or AI_CONTEXT_MAX_CHARS

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (conv_id, user_id, max_messages)
            )

            rows = cursor.fetchall()
    finally:
        connection.close()

    rows.reverse()

    context = []

    for row in rows:
        content = (row.get('content') or '').strip()

        if not content:
            continue

        if len(content) > max_chars:
            content = content[:max_chars] + '……（内容过长已截断）'

        context.append({
            'role': row['role'] if row['role'] in ('user', 'assistant') else 'user',
            'content': content
        })

    return context


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

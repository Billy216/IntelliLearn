# -*- coding: utf-8 -*-
"""个性化练习与复习卷服务（模块七）。

职责：
- 组卷：优先取学生自己的错题，其次取共享题库，两者都不足时才调用 AI 补充，
  并把 AI 题目明确标记为「未校验」；
- 判分：判断/选择/填空由服务端自动判分，解答题不自动判分（is_correct = NULL），
  需要时调用一次 AI 生成讲评；
- 复习与统计：历史练习卷、逐题回顾、知识点正确率，全部来自真实数据。

本模块只做数据库读写与判分逻辑，不依赖 Flask 请求对象，
可以直接在脚本中调用，便于测试与其他模块（教师端/管理端）复用。

数据来源与可信度约定（practice_items.answer_source / verified）：
    wrong  错题本原题，答案取自该错题，verified = 1
    bank   共享题库，verified 复制题库行的 verified
    ai     AI 现场生成，verified = 0，答案仅供参考，不得当作标准答案
"""

import json
import re
import unicodedata
from decimal import Decimal

from backend.extensions.database import connect_db, db_connection
from backend.services import ai_service
from backend.utils.logging_config import get_logger
from backend.utils.validators import normalize_text, parse_positive_int


logger = get_logger('practice')


# ============================================================
# 常量
# ============================================================

# 题型（与 practice_items.qtype / question_bank.qtype 保持一致）
QTYPE_JUDGE = 'judge'
QTYPE_CHOICE = 'choice'
QTYPE_FILL = 'fill'
QTYPE_ESSAY = 'essay'

QTYPES = (QTYPE_JUDGE, QTYPE_CHOICE, QTYPE_FILL, QTYPE_ESSAY)

QTYPE_NAMES = {
    QTYPE_JUDGE: '判断题',
    QTYPE_CHOICE: '选择题',
    QTYPE_FILL: '填空题',
    QTYPE_ESSAY: '解答题'
}

# 可自动判分的题型（解答题永远不自动判分）
AUTO_GRADED_QTYPES = (QTYPE_JUDGE, QTYPE_CHOICE, QTYPE_FILL)

DIFFICULTY_NAMES = {1: '简单', 2: '中等', 3: '较难'}

MASTERY_NAMES = {0: '未掌握', 1: '模糊', 2: '已掌握'}

ANSWER_SOURCE_NAMES = {
    'wrong': '错题本原题',
    'bank': '题库题目',
    'ai': 'AI 生成'
}

# 练习卷来源（practice_papers.source）
PAPER_SOURCE_NAMES = {
    'wrong': '错题驱动',
    'kp': '知识点练习',
    'task': '教师任务'
}

# 组卷来源偏好
SOURCE_AUTO = 'auto'
SOURCE_WRONG = 'wrong'
SOURCE_BANK = 'bank'
PAPER_SOURCES = (SOURCE_AUTO, SOURCE_WRONG, SOURCE_BANK)

# 单张练习卷的题量上限与默认题量
MAX_ITEM_COUNT = 30
DEFAULT_ITEM_COUNT = 10

# 单次组卷最多现场生成多少道 AI 题目（控制等待时间）
AI_MAX_ITEMS = 5

# 未校验题目的统一下发提示（前端必须可见）
AI_UNVERIFIED_NOTICE = 'AI 生成，未经校验，答案仅供参考'

# 解答题讲评的 AI 上限 token
ESSAY_COMMENT_MAX_TOKENS = 700


class PracticeError(Exception):
    """练习模块的业务异常，路由层据此返回 4xx。"""

    def __init__(self, message, status=400, code='BAD_REQUEST'):

        super().__init__(message)

        self.message = message
        self.status = status
        self.code = code


# ============================================================
# 通用小工具
# ============================================================

def _stringify_times(row, keys=('created_at', 'updated_at', 'submitted_at',
                                'last_review_at', 'due_at')):
    """把行里的 datetime 字段转成字符串，方便 JSON 序列化。"""

    if not isinstance(row, dict):
        return row

    for key in keys:
        value = row.get(key)

        if value is not None and not isinstance(value, str):
            row[key] = str(value)

    return row


def _to_number(value, default=0):
    """把 SUM/AVG 返回的 Decimal 转成 int/float。

    直接下发 Decimal 时 Flask 会把它序列化成字符串，
    前端拿到 "12" 这类字符串容易出错，这里统一转成数字。
    """

    if value is None:
        return default

    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)

        return float(value)

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return value

    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


def _json_loads(text):
    """尽力解析 JSON，失败返回 None（不抛异常）。"""

    if not text:
        return None

    if isinstance(text, (list, dict)):
        return text

    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _option_label(index):
    """把选项下标转成 A/B/C… 标签（最多 8 个选项）。"""

    if 0 <= index < 26:
        return chr(ord('A') + index)

    return str(index + 1)


# 选项文本开头可能已经带了标签，例如 label='A' 而 text='A. 存在…'。
# 若不剥离，展示会出现「A. A. 存在…」，并且把该题写进错题本后再解析时
# 会因标签重复而识别不出选项，导致选择题被误判为解答题、无法自动判分。
_LEADING_OPTION_LABEL_RE = re.compile(r'^\s*([A-H])\s*[.．、)）:：]\s*')


def _strip_option_label(text, label):
    """去掉选项正文开头与标签重复的「A. 」前缀。"""

    if not text:
        return text

    match = _LEADING_OPTION_LABEL_RE.match(text)

    if not match:
        return text

    letter = match.group(1).upper()

    # 只剥离与当前标签一致的（或未指定标签时的任意标签），避免误伤正文
    if label and letter != str(label).upper():
        return text

    stripped = text[match.end():].strip()

    # 剥完不能为空，否则保留原文本
    return stripped or text


def _normalize_options(raw):
    """把各种形态的选项统一成 [{'label': 'A', 'text': '...'}]。

    支持：JSON 数组（字符串或对象）、纯文本选项串、None。
    题库里历史数据格式不统一，这里做一次归一化，判分与展示都依赖标签。
    """

    if not raw:
        return []

    parsed = _json_loads(raw) if isinstance(raw, str) else raw

    options = []

    if isinstance(parsed, list):
        for index, item in enumerate(parsed[:8]):
            if isinstance(item, dict):
                label = normalize_text(item.get('label'), 4) or _option_label(index)
                text = normalize_text(item.get('text') or item.get('content'), 1000)
            else:
                label = _option_label(index)
                text = normalize_text(item, 1000)

            if not text:
                continue

            label = label.upper()
            text = _strip_option_label(text, label)

            options.append({'label': label, 'text': text})

        if options:
            return options

    if isinstance(parsed, dict):
        # 形如 {"A": "选项内容", ...}
        for index, key in enumerate(sorted(parsed.keys())[:8]):
            text = normalize_text(parsed.get(key), 1000)

            if text:
                label = normalize_text(key, 4).upper() or _option_label(index)

                options.append({
                    'label': label,
                    'text': _strip_option_label(text, label)
                })

        if options:
            return options

    if isinstance(raw, str):
        return _split_options(raw)

    return []


# 选项标记：行首或空白/左括号之后的 A. / B、 / C) / D： 等写法
_OPTION_MARKER_RE = re.compile(r'(?:^|(?<=[\s（(]))([A-H])\s*[.．、)）:：]\s*')

# 重复标签：形如「A. A. 选项内容」。
# 历史数据与部分模型输出会出现标签重复，若不折叠，
# 选项解析会在第一个空正文处中断，导致选择题被当成解答题（无法判分）。
_DOUBLED_OPTION_LABEL_RE = re.compile(
    r'(?:^|(?<=[\s（(]))([A-H])\s*[.．、)）:：]\s*(?=\1\s*[.．、)）:：])'
)


def _collapse_doubled_option_labels(text):
    """折叠「A. A. 」这类重复选项标签。"""

    if not text:
        return text

    previous = None

    while previous != text:
        previous = text
        text = _DOUBLED_OPTION_LABEL_RE.sub('', text)

    return text


def _split_options(text):
    """从题干文本里拆出选项；拆不出（少于 2 个）返回空列表。

    同时兼容「每个选项独占一行」与「A. xx B. yy C. zz」两种排版。
    """

    if not text:
        return []

    text = _collapse_doubled_option_labels(text)

    matches = list(_OPTION_MARKER_RE.finditer(text))

    if len(matches) < 2:
        return []

    # 选项必须从 A 开始且连续，避免把正文里的字母误判成选项
    if matches[0].group(1).upper() != 'A':
        return []

    options = []

    for index, match in enumerate(matches[:8]):
        letter = match.group(1).upper()

        if letter != _option_label(index):
            break

        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)

        body = text[match.end():end].strip()

        if not body or len(body) > 500:
            break

        options.append({'label': letter, 'text': body})

    if len(options) < 2:
        return []

    return options


def split_question_and_options(text):
    """把题干与选项分开，返回 (题干, 选项列表)。"""

    if not text:
        return '', []

    text = _collapse_doubled_option_labels(text)

    options = _split_options(text)

    if not options:
        return normalize_text(text, 8000), []

    first = _OPTION_MARKER_RE.search(text)

    stem = text[:first.start()].strip() if first else text

    if not stem:
        stem = text.strip()

    return normalize_text(stem, 8000), options


# ============================================================
# 答案归一化与判分
# ============================================================

# 判断题可接受的「正确/错误」写法
_JUDGE_TRUE = {
    '对', '对的', '正确', '正确的', '是', '√', '✓', '✔', 't', 'true', 'y', 'yes', '1'
}

_JUDGE_FALSE = {
    '错', '错的', '错误', '错误的', '不对', '否', '×', '✗', '✘', 'x', 'f', 'false',
    'n', 'no', '0'
}

# 去掉干扰的标点（判分前统一清理）
_NOISE_CHARS = '。，,．.、：:；;！!？?（）()【】[]《》""\'\' \t\r\n'


def normalize_judge(text):
    """把判断题作答归一化为 '对' / '错'；无法识别返回 None。"""

    if text is None:
        return None

    value = str(text).strip().lower()

    if not value:
        return None

    value = value.strip(_NOISE_CHARS)

    if value in _JUDGE_TRUE:
        return '对'

    if value in _JUDGE_FALSE:
        return '错'

    # 形如“答案：正确”“我认为是对的”这类写法，取首个可识别的关键词
    compact = value.strip(_NOISE_CHARS)

    for token in ('正确', '错误', '不对'):
        if token in compact:
            return '对' if token == '正确' else '错'

    for token in ('√', '✓', '✔', '×', '✗', '✘'):
        if token in compact:
            return '对' if token in ('√', '✓', '✔') else '错'

    return None


def _normalize_fill(text):
    """填空题归一化：去掉全部空白与 $ 包裹，全角转半角，忽略大小写。"""

    if text is None:
        return ''

    value = unicodedata.normalize('NFKC', str(text))

    value = ''.join(
        ch for ch in value
        if not ch.isspace() and ch not in ('$', '\u3000')
    )

    return value.casefold()


def _first_option_letter(text):
    """取作答里的第一个选项字母（忽略“选/答案：”等前缀），无字母返回 None。"""

    if text is None:
        return None

    value = str(text).strip()

    if not value:
        return None

    match = re.search(r'[A-Ha-h]', value)

    if not match:
        # 没有字母时退化为「取第一个字符」
        first = value.strip(_NOISE_CHARS)[:1]

        return first.upper() if first else None

    return match.group(0).upper()


def _fill_alternatives(reference):
    """填空题参考答案的等价写法集合。

    规则（按题目要求）：忽略全部空白与大小写，并接受参考答案中用
    或 / ； ; 分隔的等价写法。为了不把分数（如 1/3）误拆成两个答案，
    参考答案里出现「或/；/;」时只按这些分隔符切分，否则才按 / 切分。
    """

    text = str(reference or '')

    parts = {_normalize_fill(text)}

    if re.search(r'[或；;]', text):
        pieces = re.split(r'[或；;]', text)
    else:
        pieces = re.split(r'[/]', text)

    for piece in pieces:
        normalized = _normalize_fill(piece)

        if normalized:
            parts.add(normalized)

    parts.discard('')

    return parts


def grade_answer(qtype, user_answer, standard_answer):
    """服务端判分单一题目，返回 {'is_correct': True/False/None, 'note': '...'}。

    is_correct 为 None 表示无法自动判分（解答题，或参考答案不可用于比对）。
    """

    qtype = qtype if qtype in QTYPES else QTYPE_ESSAY

    user_answer = normalize_text(user_answer, 8000)
    standard_answer = normalize_text(standard_answer, 8000)

    if qtype == QTYPE_ESSAY:
        return {
            'is_correct': None,
            'note': '解答题不做自动判分，由 AI 讲评（分数只统计可自动判分的题目）'
        }

    if qtype == QTYPE_JUDGE:
        reference = normalize_judge(standard_answer)

        if reference is None:
            return {'is_correct': None, 'note': '参考答案不是可识别的判断题结论，未自动判分'}

        if not user_answer:
            return {'is_correct': False, 'note': '未作答'}

        answer = normalize_judge(user_answer)

        if answer is None:
            return {'is_correct': False, 'note': '作答无法识别为对/错，按错误处理'}

        return {'is_correct': answer == reference, 'note': '判断题按 对/错 比对'}

    if qtype == QTYPE_CHOICE:
        reference = _first_option_letter(standard_answer)

        if not reference or _normalize_fill(standard_answer) in ('', '无'):
            return {'is_correct': None, 'note': '参考答案不是选项字母，未自动判分'}

        if not user_answer:
            return {'is_correct': False, 'note': '未作答'}

        answer = _first_option_letter(user_answer)

        if not answer:
            return {'is_correct': False, 'note': '作答中没有选项字母，按错误处理'}

        return {'is_correct': answer == reference, 'note': '选择题比对选项字母（忽略大小写）'}

    # 填空题
    reference_parts = _fill_alternatives(standard_answer)

    if not reference_parts:
        return {'is_correct': None, 'note': '参考答案为空，未自动判分'}

    if not user_answer:
        return {'is_correct': False, 'note': '未作答'}

    answer = _normalize_fill(user_answer)

    return {
        'is_correct': answer in reference_parts,
        'note': '填空题忽略全部空白与大小写，并接受 或 / ； ; 分隔的等价写法'
    }


# ============================================================
# 筛选选项（全部来自真实数据）
# ============================================================

def list_filter_options(user_id):
    """返回组卷可用的筛选项：学科、知识点、课程、错误类型、题型、难度。"""

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT major, COUNT(*) AS total
                FROM wrong_questions
                WHERE user_id = %s AND major <> ''
                GROUP BY major
                """,
                (user_id,)
            )

            wrong_majors = {row['major']: row['total'] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT major, COUNT(*) AS total
                FROM question_bank
                WHERE status = 1 AND major <> ''
                GROUP BY major
                """
            )

            bank_majors = {row['major']: row['total'] for row in cursor.fetchall()}

            # 知识点：错题关联表 + 错题 sub（章节级知识点）+ 题库 kp_name
            cursor.execute(
                """
                SELECT k.kp_name AS name, COUNT(*) AS total
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE w.user_id = %s AND k.kp_name <> ''
                GROUP BY k.kp_name
                """,
                (user_id,)
            )

            kp_map = {}

            for row in cursor.fetchall():
                kp_map.setdefault(row['name'], {'name': row['name'], 'wrong_count': 0, 'bank_count': 0})
                kp_map[row['name']]['wrong_count'] += row['total']

            cursor.execute(
                """
                SELECT sub AS name, COUNT(*) AS total
                FROM wrong_questions
                WHERE user_id = %s AND sub <> ''
                GROUP BY sub
                """,
                (user_id,)
            )

            for row in cursor.fetchall():
                kp_map.setdefault(row['name'], {'name': row['name'], 'wrong_count': 0, 'bank_count': 0})
                kp_map[row['name']]['wrong_count'] += row['total']

            cursor.execute(
                """
                SELECT kp_name AS name, COUNT(*) AS total
                FROM question_bank
                WHERE status = 1 AND kp_name <> ''
                GROUP BY kp_name
                """
            )

            for row in cursor.fetchall():
                kp_map.setdefault(row['name'], {'name': row['name'], 'wrong_count': 0, 'bank_count': 0})
                kp_map[row['name']]['bank_count'] += row['total']

            cursor.execute(
                """
                SELECT id, name, major
                FROM courses
                WHERE status = 1
                ORDER BY name
                """
            )

            courses = cursor.fetchall()

            cursor.execute(
                """
                SELECT qtype, COUNT(*) AS total
                FROM question_bank
                WHERE status = 1
                GROUP BY qtype
                """
            )

            bank_qtypes = {row['qtype']: row['total'] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT difficulty, COUNT(*) AS total
                FROM question_bank
                WHERE status = 1
                GROUP BY difficulty
                """
            )

            bank_difficulties = {row['difficulty']: row['total'] for row in cursor.fetchall()}

    majors = []

    for name in ai_service.MAJOR_CATEGORIES:
        majors.append({
            'name': name,
            'wrong_count': wrong_majors.get(name, 0),
            'bank_count': bank_majors.get(name, 0)
        })

    # 题库/错题里出现过但不属于预置大类的学科也如实展示
    for name in sorted(set(bank_majors) | set(wrong_majors)):
        if name not in ai_service.MAJOR_CATEGORIES:
            majors.append({
                'name': name,
                'wrong_count': wrong_majors.get(name, 0),
                'bank_count': bank_majors.get(name, 0)
            })

    knowledge_points = sorted(
        kp_map.values(),
        key=lambda item: (-(item['wrong_count'] + item['bank_count']), item['name'])
    )

    return {
        'majors': majors,
        'knowledge_points': knowledge_points,
        'courses': courses,
        'error_types': list(ai_service.ERROR_TYPES),
        'mastery_options': [
            {'value': value, 'label': MASTERY_NAMES[value]} for value in (0, 1, 2)
        ],
        'qtypes': [
            {
                'value': qtype,
                'label': QTYPE_NAMES[qtype],
                'bank_count': bank_qtypes.get(qtype, 0)
            }
            for qtype in QTYPES
        ],
        'difficulties': [
            {
                'value': value,
                'label': DIFFICULTY_NAMES[value],
                'bank_count': bank_difficulties.get(value, 0)
            }
            for value in (1, 2, 3)
        ],
        'limits': {
            'default_count': DEFAULT_ITEM_COUNT,
            'max_count': MAX_ITEM_COUNT,
            'ai_max_items': AI_MAX_ITEMS
        },
        'ai_available': bool(ai_service.AI_API_KEY)
    }


# ============================================================
# 候选题目检索
# ============================================================

def _weak_knowledge_point_names(user_id, limit=5):
    """学生错题中出现最多的知识点名称（用于题库的同知识点匹配）。"""

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT k.kp_name AS name, COUNT(*) AS total
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE w.user_id = %s AND k.kp_name <> ''
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT %s
                """,
                (user_id, limit)
            )

            return [row['name'] for row in cursor.fetchall()]


def _fetch_wrong_candidates(user_id, major=None, kp=None, error_type=None,
                            mastery=None, course_id=None, limit=DEFAULT_ITEM_COUNT):
    """取学生的错题候选（未掌握、复习次数少的优先）。"""

    clauses = ['w.user_id = %s']
    params = [user_id]

    if major:
        clauses.append('w.major = %s')
        params.append(major)

    if error_type:
        clauses.append('w.error_type = %s')
        params.append(error_type)

    if mastery is not None:
        clauses.append('w.mastery = %s')
        params.append(mastery)

    if course_id:
        clauses.append('w.course_id = %s')
        params.append(course_id)

    if kp:
        like = f'%{kp}%'
        clauses.append(
            '(w.knowledge_points LIKE %s OR w.sub LIKE %s '
            'OR EXISTS (SELECT 1 FROM wrong_question_kps k '
            'WHERE k.wrong_question_id = w.id AND k.kp_name LIKE %s))'
        )
        params.extend([like, like, like])

    params.append(limit)

    sql = f"""
        SELECT
            w.id, w.major, w.sub, w.course_id, w.knowledge_points, w.error_type,
            w.mastery, w.question, w.answer, w.standard_answer, w.analysis,
            w.image_url, w.created_at
        FROM wrong_questions w
        WHERE {' AND '.join(clauses)}
        ORDER BY w.mastery ASC, w.review_count ASC, w.id DESC
        LIMIT %s
    """

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))

            return cursor.fetchall()


def _fetch_bank_candidates(major=None, kp=None, qtype=None, difficulty=None,
                           course_id=None, verified_only=True,
                           weak_kps=None, limit=DEFAULT_ITEM_COUNT):
    """取题库候选：按 verified / 难度排序，题库内随机抽取，避免每次都一样。"""

    clauses = ['status = 1']
    params = []

    if major:
        clauses.append('major = %s')
        params.append(major)

    if qtype:
        clauses.append('qtype = %s')
        params.append(qtype)

    if difficulty:
        clauses.append('difficulty = %s')
        params.append(difficulty)

    if course_id:
        clauses.append('course_id = %s')
        params.append(course_id)

    if verified_only:
        clauses.append('verified = 1')

    if kp:
        clauses.append('kp_name LIKE %s')
        params.append(f'%{kp}%')
    elif weak_kps:
        # 未指定知识点时，按学生最薄弱的知识点匹配题库
        clauses.append('(' + ' OR '.join(['kp_name LIKE %s'] * len(weak_kps)) + ')')
        params.extend([f'%{name}%' for name in weak_kps])

    params.append(limit)

    sql = f"""
        SELECT
            id, course_id, major, kp_name, qtype, difficulty, question,
            options_json, answer, analysis, source, verified
        FROM question_bank
        WHERE {' AND '.join(clauses)}
        ORDER BY verified DESC, difficulty ASC, RAND()
        LIMIT %s
    """

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))

            return cursor.fetchall()


# ============================================================
# 候选题目 → 练习题目
# ============================================================

def _infer_qtype(question, options, requested=None):
    """推断错题的题型：选项可解析 → 选择题；否则按主观题处理。

    学生显式指定题型时以指定值为准（选择题仍要求能解析出选项）。
    """

    if requested in QTYPES:
        if requested == QTYPE_CHOICE and not options:
            return None

        return requested

    if options:
        return QTYPE_CHOICE

    return QTYPE_ESSAY


def _extract_letter_from_answer(answer_text):
    """从错题的解答文本里提取选择题的正确选项字母；提取不到返回 None。"""

    if not answer_text:
        return None

    text = str(answer_text)

    patterns = [
        r'答案[是为：:\s]*([A-Ha-h])(?![A-Za-z0-9])',
        r'正确选项[是为：:\s]*([A-Ha-h])(?![A-Za-z0-9])',
        r'应选\s*([A-Ha-h])(?![A-Za-z0-9])',
        r'选\s*([A-Ha-h])(?![A-Za-z0-9])',
        r'^\s*([A-Ha-h])\s*$'
    ]

    found = set()

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            found.add(match.group(1).upper())

        if len(found) == 1:
            return found.pop()

        if len(found) > 1:
            return None

    return None


def _extract_judge_from_answer(answer_text):
    """从错题解答文本里提取判断题结论（对/错）；提取不到返回 None。"""

    if not answer_text:
        return None

    text = str(answer_text)

    direct = normalize_judge(text)

    if direct:
        return direct

    patterns = [
        r'答案[是为：:\s]*([对错正确误√×✓✗]{1,4})',
        r'(?:该)?(?:命题|说法|结论)[是为：:\s]*([对错正确误]{1,2})'
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            verdict = normalize_judge(match.group(1))

            if verdict:
                return verdict

    return None


def _item_from_wrong_row(row, requested_qtype=None):
    """把一条错题转成练习题目（答案与解析都取自该错题），无法使用时返回 None。"""

    raw_question = normalize_text(row.get('question'), 8000)

    if not raw_question:
        return None

    stem, options = split_question_and_options(raw_question)

    qtype = _infer_qtype(stem, options, requested_qtype)

    if not qtype:
        return None

    source_answer = normalize_text(row.get('standard_answer'), 8000) \
        or normalize_text(row.get('answer'), 8000)
    source_analysis = normalize_text(row.get('analysis'), 8000) \
        or normalize_text(row.get('answer'), 8000)

    if not source_answer:
        # 错题里没有答案，不能当作「已校验」的标准答案使用
        return None

    answer = source_answer
    analysis = source_analysis

    if qtype == QTYPE_CHOICE:
        letter = _extract_letter_from_answer(source_answer)

        if not letter:
            # 解答文本里找不出选项字母：保留题目，但判分时会标为「无法自动判分」
            letter = None
        else:
            answer = letter
            analysis = source_analysis

    elif qtype == QTYPE_JUDGE:
        verdict = _extract_judge_from_answer(source_answer)

        if verdict:
            answer = verdict

    kp_name = normalize_text(row.get('knowledge_points'), 150) \
        or normalize_text(row.get('sub'), 150)

    return {
        'wrong_question_id': row.get('id'),
        'question_id': None,
        'qtype': qtype,
        'question': stem,
        'options': options,
        'answer': answer,
        'analysis': analysis,
        'kp_name': kp_name,
        'answer_source': 'wrong',
        'verified': 1,
        'error_type': normalize_text(row.get('error_type'), 30),
        'image_url': normalize_text(row.get('image_url'), 500),
        'difficulty': None
    }


def _item_from_bank_row(row, requested_qtype=None):
    """把一条题库题目转成练习题目，题型不符或缺少答案时返回 None。"""

    question = normalize_text(row.get('question'), 8000)

    if not question:
        return None

    qtype = row.get('qtype') if row.get('qtype') in QTYPES else QTYPE_CHOICE

    if requested_qtype and qtype != requested_qtype:
        return None

    answer = normalize_text(row.get('answer'), 8000)

    if not answer:
        return None

    if qtype == QTYPE_CHOICE:
        stem, options = split_question_and_options(question)

        options = _normalize_options(row.get('options_json')) or options

        if not options:
            return None

        question = stem
    else:
        options = []

    return {
        'wrong_question_id': None,
        'question_id': row.get('id'),
        'qtype': qtype,
        'question': question,
        'options': options,
        'answer': answer,
        'analysis': normalize_text(row.get('analysis'), 8000),
        'kp_name': normalize_text(row.get('kp_name'), 150),
        'answer_source': 'bank',
        'verified': 1 if row.get('verified') else 0,
        'error_type': '',
        'image_url': '',
        'difficulty': row.get('difficulty')
    }


# ============================================================
# AI 补题（仅在错题与题库都不足时使用）
# ============================================================

def _ai_question_messages(major, kp, qtype, difficulty, count):
    """构造要求 AI 出题的提示词（只输出 JSON）。"""

    major_name = major or '综合'
    kp_name = kp or '该学科的核心知识点'
    qtype_name = QTYPE_NAMES.get(qtype, QTYPE_NAMES[QTYPE_CHOICE])
    difficulty_name = DIFFICULTY_NAMES.get(difficulty, '中等')

    if qtype == QTYPE_CHOICE:
        answer_rule = '4) answer 只能是单个选项字母（如 "B"），options 必须给出 4 个选项；'
    elif qtype == QTYPE_JUDGE:
        answer_rule = '4) answer 只能是 "对" 或 "错"，options 返回空数组；'
    elif qtype == QTYPE_FILL:
        answer_rule = '4) answer 必须是简短标准答案，等价写法用 "或" 分隔，options 返回空数组；'
    else:
        answer_rule = '4) answer 给出完整参考答案，options 返回空数组；'

    system = (
        '你是高校命题老师，负责按知识点出练习题。'
        '题目必须自洽、条件完整、有唯一确定的答案，不得编造教材上不存在的结论。'
        '只输出 JSON，不要输出任何解释文字。'
    )

    user = (
        f'请围绕学科「{major_name}」的知识点「{kp_name}」，'
        f'出 {count} 道{difficulty_name}难度的{qtype_name}。\n'
        '要求：\n'
        '1) 每道题都要能独立作答；\n'
        '2) 数学公式用 LaTeX（行内 $...$）；\n'
        '3) analysis 用一两句话说明解题思路；\n'
        f'{answer_rule}\n'
        '5) 输出格式（严格 JSON）：\n'
        '{"questions": [{"question": "题干", "options": [], '
        '"answer": "答案", "analysis": "解析"}]}'
    )

    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user}
    ]


def generate_ai_items(major=None, kp=None, qtype=None, difficulty=None,
                      count=AI_MAX_ITEMS):
    """调用 AI 现场生成题目，返回 (题目列表, 失败原因)。

    生成的题目一律标记 answer_source='ai'、verified=0：
    它们只能作为练习使用，绝不代表标准答案。
    """

    count = parse_positive_int(count, AI_MAX_ITEMS, AI_MAX_ITEMS) or AI_MAX_ITEMS

    qtype = qtype if qtype in QTYPES else QTYPE_CHOICE

    text, finish_reason = ai_service.call_ai(
        _ai_question_messages(major, kp, qtype, difficulty, count),
        max_tokens=2000,
        json_mode=True
    )

    if not text:
        return [], 'AI 出题调用失败（未配置密钥或网络不可用）'

    data = ai_service.parse_json_object(text)

    if not isinstance(data, dict) or not isinstance(data.get('questions'), list):
        return [], 'AI 返回内容不是预期的 JSON 结构'

    items = []

    for raw in data['questions'][:count]:
        if not isinstance(raw, dict):
            continue

        question = normalize_text(raw.get('question'), 8000)
        answer = normalize_text(raw.get('answer'), 8000)

        if not question or not answer:
            continue

        options = _normalize_options(raw.get('options')) if qtype == QTYPE_CHOICE else []

        if qtype == QTYPE_CHOICE and len(options) < 2:
            continue

        if qtype == QTYPE_JUDGE:
            answer = normalize_judge(answer) or ''

            if not answer:
                continue

        items.append({
            'wrong_question_id': None,
            'question_id': None,
            'qtype': qtype,
            'question': question,
            'options': options,
            'answer': answer,
            'analysis': normalize_text(raw.get('analysis'), 8000),
            'kp_name': normalize_text(kp, 150),
            'answer_source': 'ai',
            'verified': 0,
            'error_type': '',
            'image_url': '',
            'difficulty': difficulty
        })

    if not items:
        return [], 'AI 返回的题目不完整，已忽略'

    return items, None


# ============================================================
# 组卷
# ============================================================

def _course_exists(course_id):
    """课程是否存在且启用（用于服务端校验 course_id）。"""

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM courses WHERE id = %s AND status = 1 LIMIT 1',
                (course_id,)
            )

            return cursor.fetchone() is not None


def _normalize_filters(major=None, kp=None, qtype=None, difficulty=None,
                       course_id=None, error_type=None, mastery=None,
                       source=SOURCE_AUTO, count=DEFAULT_ITEM_COUNT):
    """校验并归一化组卷参数，非法取值直接抛 PracticeError（对应 400）。"""

    major = normalize_text(major, 50) or None

    if major and major not in ai_service.MAJOR_CATEGORIES:
        raise PracticeError('学科不在允许范围内')

    kp = normalize_text(kp, 150) or None

    qtype = normalize_text(qtype, 20) or None

    if qtype and qtype not in QTYPES:
        raise PracticeError('题型不在允许范围内（judge/choice/fill/essay）')

    if difficulty not in (None, ''):
        difficulty = parse_positive_int(difficulty)

        if difficulty not in (1, 2, 3):
            raise PracticeError('难度只能是 1（简单）、2（中等）、3（较难）')
    else:
        difficulty = None

    if course_id not in (None, ''):
        course_id = parse_positive_int(course_id)

        if not course_id or not _course_exists(course_id):
            raise PracticeError('课程不存在或已被停用')
    else:
        course_id = None

    error_type = normalize_text(error_type, 30) or None

    if error_type and error_type not in ai_service.ERROR_TYPES:
        raise PracticeError('错误类型不在允许范围内')

    if mastery not in (None, '', 'all'):
        # 掌握度 0/1/2 都合法，不能用 parse_positive_int（它不接受 0）
        try:
            mastery = int(mastery)
        except (TypeError, ValueError):
            raise PracticeError('掌握度取值不合法')

        if mastery not in (0, 1, 2):
            raise PracticeError('掌握度取值不合法')
    else:
        mastery = None

    source = normalize_text(source, 10) or SOURCE_AUTO

    if source not in PAPER_SOURCES:
        raise PracticeError('组卷来源只能是 auto/wrong/bank')

    count = parse_positive_int(count, DEFAULT_ITEM_COUNT, MAX_ITEM_COUNT) \
        or DEFAULT_ITEM_COUNT

    return {
        'major': major,
        'kp': kp,
        'qtype': qtype,
        'difficulty': difficulty,
        'course_id': course_id,
        'error_type': error_type,
        'mastery': mastery,
        'source': source,
        'count': count
    }


def _course_major(course_id):
    """课程的学科大类（用于任务组卷时推断学科），查不到返回 None。"""

    if not course_id:
        return None

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT major FROM courses WHERE id = %s',
                (course_id,)
            )

            row = cursor.fetchone()

    return normalize_text(row['major'], 50) if row and row.get('major') else None


def _insert_paper(user_id, title, major, course_id, source, task_id, items):
    """把练习卷与题目写入数据库，返回试卷 ID（一个事务）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO practice_papers
                (user_id, title, major, course_id, source, task_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    normalize_text(title, 150) or '个性化练习',
                    major or '',
                    course_id,
                    source,
                    task_id
                )
            )

            paper_id = cursor.lastrowid

            for seq, item in enumerate(items, start=1):
                cursor.execute(
                    """
                    INSERT INTO practice_items
                    (paper_id, seq, question_id, wrong_question_id, qtype, question,
                     options_json, answer, analysis, kp_name, answer_source, verified)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        paper_id,
                        seq,
                        item.get('question_id'),
                        item.get('wrong_question_id'),
                        item['qtype'],
                        item['question'],
                        json.dumps(item.get('options') or [], ensure_ascii=False),
                        item.get('answer'),
                        item.get('analysis'),
                        normalize_text(item.get('kp_name'), 150) or '',
                        item.get('answer_source') or 'wrong',
                        1 if item.get('verified') else 0
                    )
                )

    return paper_id


def _public_item(row):
    """下发给学生的题目结构：不含 answer / analysis / ai_comment。"""

    return {
        'id': row['id'],
        'seq': row['seq'],
        'qtype': row['qtype'],
        'qtype_name': QTYPE_NAMES.get(row['qtype'], row['qtype']),
        'question': row['question'],
        'options': _normalize_options(row.get('options_json')),
        'kp_name': row.get('kp_name') or '',
        'answer_source': row.get('answer_source') or '',
        'answer_source_name': ANSWER_SOURCE_NAMES.get(row.get('answer_source'), ''),
        'verified': 1 if row.get('verified') else 0
    }


def _public_paper(row, items):
    """下发给学生的试卷结构（不含任何答案字段）。"""

    return {
        'id': row['id'],
        'title': row['title'],
        'major': row['major'],
        'course_id': row.get('course_id'),
        'source': row['source'],
        'task_id': row.get('task_id'),
        'created_at': str(row['created_at']) if row.get('created_at') else None,
        'item_count': len(items),
        'items': [_public_item(item) for item in items]
    }


def _paper_notices(items):
    """按题目可信度生成提示语（AI 题与未校验题必须显式提示）。"""

    notices = []

    ai_count = sum(1 for item in items if item.get('answer_source') == 'ai')
    unverified_count = sum(
        1 for item in items
        if not item.get('verified') and item.get('answer_source') != 'ai'
    )

    if ai_count:
        notices.append(f'{ai_count} 道题为 {AI_UNVERIFIED_NOTICE}')

    if unverified_count:
        notices.append(f'{unverified_count} 道题来自题库但未经人工校验，答案仅供参考')

    return notices


def generate_paper(user_id, major=None, kp=None, qtype=None, difficulty=None,
                   count=DEFAULT_ITEM_COUNT, course_id=None, error_type=None,
                   mastery=None, source=SOURCE_AUTO, verified_only=True,
                   allow_ai=True, task_id=None, title=None):
    """组卷：错题优先 → 题库补充 → 最后才由 AI 补题。

    返回 {'paper': 不含答案的试卷, 'composition': 各来源题数, 'notices': [...]}。
    找不到任何题目时抛 PracticeError（不返回假题目）。
    """

    user_id = parse_positive_int(user_id)

    if not user_id:
        raise PracticeError('用户信息无效')

    filters = _normalize_filters(
        major=major, kp=kp, qtype=qtype, difficulty=difficulty,
        course_id=course_id, error_type=error_type, mastery=mastery,
        source=source, count=count
    )

    wanted = filters['count']
    selected = []
    composition = {'wrong': 0, 'bank': 0, 'ai': 0}
    notices = []

    # ---- 来源 a：学生自己的错题 ----
    if filters['source'] in (SOURCE_AUTO, SOURCE_WRONG):
        rows = _fetch_wrong_candidates(
            user_id,
            major=filters['major'],
            kp=filters['kp'],
            error_type=filters['error_type'],
            mastery=filters['mastery'],
            course_id=filters['course_id'],
            limit=wanted
        )

        for row in rows:
            item = _item_from_wrong_row(row, filters['qtype'])

            if item:
                selected.append(item)

            if len(selected) >= wanted:
                break

    composition['wrong'] = len(selected)

    # ---- 来源 b：共享题库（同一知识点）----
    if len(selected) < wanted and filters['source'] in (SOURCE_AUTO, SOURCE_BANK):
        weak_kps = None

        if not filters['kp'] and filters['source'] == SOURCE_AUTO:
            weak_kps = _weak_knowledge_point_names(user_id)

        rows = _fetch_bank_candidates(
            major=filters['major'],
            kp=filters['kp'],
            qtype=filters['qtype'],
            difficulty=filters['difficulty'],
            course_id=filters['course_id'],
            verified_only=verified_only,
            weak_kps=weak_kps,
            # 多取一些候选：题干重复的会被去掉，避免去重后题量不足
            limit=min(wanted * 3 + 5, 200)
        )

        seen_questions = {
            normalize_text(item['question'], 8000)[:200] for item in selected
        }

        for row in rows:
            item = _item_from_bank_row(row, filters['qtype'])

            if not item:
                continue

            # 同一份卷子里不出现完全相同的题干
            fingerprint = normalize_text(item['question'], 8000)[:200]

            if fingerprint in seen_questions:
                continue

            seen_questions.add(fingerprint)

            selected.append(item)

            if len(selected) >= wanted:
                break

    composition['bank'] = len(selected) - composition['wrong']

    # ---- 兜底：AI 现场补题（明确标记未校验）----
    shortage = wanted - len(selected)
    notice_ai_error = None

    if shortage > 0 and allow_ai:
        ai_wanted = min(shortage, AI_MAX_ITEMS)

        logger.info(
            '错题与题库不足，尝试 AI 补题：需要 %s 道，本次请求 %s 道',
            shortage, ai_wanted
        )

        ai_items, ai_error = generate_ai_items(
            major=filters['major'],
            kp=filters['kp'],
            qtype=filters['qtype'],
            difficulty=filters['difficulty'],
            count=ai_wanted
        )

        selected.extend(ai_items)

        composition['ai'] = len(ai_items)

        if ai_error:
            notice_ai_error = ai_error

            notices.append(
                f'错题本与题库只找到 {composition["wrong"] + composition["bank"]} 道题，'
                f'AI 补题未成功（{ai_error}），本次未使用任何 AI 生成的题目'
            )

        if shortage > AI_MAX_ITEMS and composition['ai']:
            notices.append(
                f'AI 补题单次最多 {AI_MAX_ITEMS} 道，实际题量少于请求数量'
            )

    if not selected:
        detail = ''

        if notice_ai_error:
            detail = f'（{notice_ai_error}）'

        raise PracticeError(
            '没有找到符合条件的题目：错题本与题库中都没有匹配的题目。'
            '请放宽学科/知识点/题型/难度筛选后重试，'
            '或先在 AI 问答与错题集中积累题目。' + detail
        )

    if composition['ai']:
        notices.append(f'{composition["ai"]} 道题为 {AI_UNVERIFIED_NOTICE}')

    # 题库中未经人工校验的题目也要显式提示（AI 题的提示已在上方给出）
    for notice in _paper_notices(selected):
        if notice not in notices:
            notices.append(notice)

    if not filters['major']:
        major_for_paper = ''
    else:
        major_for_paper = filters['major']

    if not title:
        parts = [major_for_paper or '综合']

        if filters['kp']:
            parts.append(filters['kp'])

        if filters['qtype']:
            parts.append(QTYPE_NAMES[filters['qtype']])

        title = '·'.join(parts) + ' 个性化练习'

    source_flag = 'wrong' if composition['wrong'] else 'kp'

    if task_id:
        source_flag = 'task'

    paper_id = _insert_paper(
        user_id,
        title,
        major_for_paper,
        filters['course_id'],
        source_flag,
        task_id,
        selected
    )

    logger.info(
        '生成练习卷 #%s（用户 %s）：错题 %s / 题库 %s / AI %s',
        paper_id, user_id, composition['wrong'], composition['bank'], composition['ai']
    )

    paper = get_paper(user_id, paper_id)

    return {
        'paper': paper['paper'],
        'composition': composition,
        'notices': notices,
        'requested_count': wanted,
        'created_count': len(selected)
    }


# ============================================================
# 试卷读取
# ============================================================

def _load_paper_row(cursor, user_id, paper_id):
    """读取试卷并做归属校验；返回 (paper 行, 拒绝原因)。"""

    cursor.execute(
        """
        SELECT id, user_id, title, major, course_id, source, task_id, created_at
        FROM practice_papers
        WHERE id = %s
        """,
        (paper_id,)
    )

    paper = cursor.fetchone()

    if not paper:
        return None, 'not_found'

    if paper['user_id'] == user_id:
        return paper, None

    # 教师任务里的练习卷：只有该任务面向班级的学生可以访问
    cursor.execute(
        """
        SELECT 1
        FROM learning_tasks t
        JOIN class_students cs ON cs.class_id = t.class_id
        WHERE cs.user_id = %s
          AND (t.id = %s OR t.paper_id = %s)
        LIMIT 1
        """,
        (user_id, paper.get('task_id'), paper['id'])
    )

    if cursor.fetchone():
        return paper, None

    return None, 'forbidden'


def _load_items(cursor, paper_id):
    """读取试卷题目（按题号排序）。"""

    cursor.execute(
        """
        SELECT
            i.id, i.paper_id, i.seq, i.question_id, i.wrong_question_id,
            i.qtype, i.question, i.options_json, i.answer, i.analysis,
            i.kp_name, i.answer_source, i.verified,
            w.error_type AS source_error_type
        FROM practice_items i
        LEFT JOIN wrong_questions w ON w.id = i.wrong_question_id
        WHERE i.paper_id = %s
        ORDER BY i.seq, i.id
        """,
        (paper_id,)
    )

    return cursor.fetchall()


def _load_record(cursor, paper_id, user_id):
    """读取该学生这份试卷的提交记录，没有返回 None。"""

    cursor.execute(
        """
        SELECT id, paper_id, user_id, total_count, correct_count, score,
               graded_count, submitted_at
        FROM practice_records
        WHERE paper_id = %s AND user_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (paper_id, user_id)
    )

    return cursor.fetchone()


def _review_payload(cursor, paper, items, record):
    """组装「已提交试卷」的完整回顾数据（含答案、解析与错因统计）。"""

    cursor.execute(
        """
        SELECT item_id, user_answer, is_correct, ai_comment
        FROM practice_answers
        WHERE record_id = %s
        """,
        (record['id'],)
    )

    answers = {row['item_id']: row for row in cursor.fetchall()}

    review_items = []
    wrong_points = {}

    for item in items:
        answer_row = answers.get(item['id']) or {}

        is_correct = answer_row.get('is_correct')

        review_items.append({
            'id': item['id'],
            'seq': item['seq'],
            'qtype': item['qtype'],
            'qtype_name': QTYPE_NAMES.get(item['qtype'], item['qtype']),
            'question': item['question'],
            'options': _normalize_options(item.get('options_json')),
            'kp_name': item.get('kp_name') or '',
            'answer_source': item.get('answer_source') or '',
            'answer_source_name': ANSWER_SOURCE_NAMES.get(item.get('answer_source'), ''),
            'verified': 1 if item.get('verified') else 0,
            'user_answer': answer_row.get('user_answer'),
            'is_correct': None if is_correct is None else bool(is_correct),
            'graded': is_correct is not None,
            'correct_answer': item.get('answer'),
            'analysis': item.get('analysis'),
            'ai_comment': answer_row.get('ai_comment'),
            'error_type': item.get('source_error_type') or ''
        })

        kp_name = (item.get('kp_name') or '未标注知识点').strip() or '未标注知识点'

        bucket = wrong_points.setdefault(
            kp_name,
            {'kp_name': kp_name, 'total': 0, 'wrong': 0, 'ungraded': 0}
        )

        bucket['total'] += 1

        if is_correct is None:
            bucket['ungraded'] += 1
        elif not is_correct:
            bucket['wrong'] += 1

    graded_count = record.get('graded_count') or 0

    record_payload = {
        'id': record['id'],
        'paper_id': record['paper_id'],
        'total_count': record['total_count'],
        'graded_count': graded_count,
        'correct_count': record['correct_count'],
        'score': float(record['score']) if record.get('score') is not None else 0.0,
        'accuracy': round(record['correct_count'] / graded_count * 100, 1) if graded_count else 0.0,
        'submitted_at': str(record['submitted_at']) if record.get('submitted_at') else None
    }

    notices = _paper_notices(items)

    if graded_count == 0:
        notices.append(
            '本次练习没有可自动判分的题目，得分按 0 分记录，'
            '请以逐题回顾中的参考答案与讲评为准'
        )

    ungraded = sum(1 for item in review_items if not item['graded'])

    if ungraded:
        notices.append(f'{ungraded} 道题未自动判分（主观题或参考答案无法比对）')

    return {
        'record': record_payload,
        'items': review_items,
        'wrong_points': sorted(
            wrong_points.values(),
            key=lambda row: (-row['wrong'], -row['total'], row['kp_name'])
        ),
        'notices': notices
    }


def get_paper(user_id, paper_id):
    """读取一份练习卷：未提交时不含任何答案；已提交时附带作答与解析。

    返回 {'paper': {...}, 'submitted': bool, 'review': {...} 或 None}；
    试卷不存在返回 None，无权限抛 PracticeError(403)。
    """

    user_id = parse_positive_int(user_id)
    paper_id = parse_positive_int(paper_id)

    if not user_id or not paper_id:
        return None

    with connect_db() as connection:
        with connection.cursor() as cursor:
            paper, reason = _load_paper_row(cursor, user_id, paper_id)

            if reason == 'forbidden':
                raise PracticeError('无权访问该练习卷', status=403, code='FORBIDDEN')

            if not paper:
                return None

            items = _load_items(cursor, paper_id)

            record = _load_record(cursor, paper_id, user_id)

            _stringify_times(paper)

            review = None

            if record:
                review = _review_payload(cursor, paper, items, record)

    result = {
        'paper': _public_paper(paper, items),
        'submitted': bool(review),
        'review': review
    }

    if not review:
        result['notices'] = _paper_notices(items)

    return result


def list_papers(user_id, page=1, page_size=10):
    """学生可见的练习卷列表（自己创建的 + 班级任务里的），含得分与提交时间。"""

    user_id = parse_positive_int(user_id)
    page = parse_positive_int(page, 1) or 1
    page_size = parse_positive_int(page_size, 10, 50) or 10

    where = """
        p.user_id = %s
        OR (p.task_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM learning_tasks t
                JOIN class_students cs ON cs.class_id = t.class_id
                WHERE t.id = p.task_id AND cs.user_id = %s))
        OR EXISTS (
                SELECT 1 FROM learning_tasks t2
                JOIN class_students cs2 ON cs2.class_id = t2.class_id
                WHERE t2.paper_id = p.id AND cs2.user_id = %s)
    """

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM practice_papers p WHERE {where}',
                (user_id, user_id, user_id)
            )

            total = cursor.fetchone()['total']

            cursor.execute(
                f"""
                SELECT
                    p.id, p.title, p.major, p.course_id, p.source, p.task_id, p.created_at,
                    (SELECT COUNT(*) FROM practice_items i WHERE i.paper_id = p.id) AS item_count,
                    r.id AS record_id, r.score, r.correct_count, r.graded_count,
                    r.total_count, r.submitted_at
                FROM practice_papers p
                LEFT JOIN practice_records r
                       ON r.paper_id = p.id AND r.user_id = %s
                WHERE {where}
                ORDER BY p.id DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, user_id, user_id, user_id, page_size, (page - 1) * page_size)
            )

            rows = cursor.fetchall()

    items = []

    for row in rows:
        _stringify_times(row)

        submitted = row.get('record_id') is not None

        items.append({
            'id': row['id'],
            'title': row['title'],
            'major': row['major'],
            'course_id': row.get('course_id'),
            'source': row['source'],
            'source_name': PAPER_SOURCE_NAMES.get(row['source'], '练习卷'),
            'task_id': row.get('task_id'),
            'created_at': row['created_at'],
            'item_count': row['item_count'],
            'submitted': submitted,
            'record_id': row.get('record_id'),
            'score': float(row['score']) if row.get('score') is not None else None,
            'correct_count': row.get('correct_count'),
            'graded_count': row.get('graded_count'),
            'total_count': row.get('total_count'),
            'submitted_at': row.get('submitted_at')
        })

    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


# ============================================================
# 提交与判分
# ============================================================

def _essay_comment(question, reference, user_answer):
    """为一道解答题生成 AI 讲评；失败返回 (None, 失败原因)。"""

    messages = [
        {
            'role': 'system',
            'content': (
                '你是高校课程的评卷助教。请比较学生的作答与参考答案，'
                '指出学生答对的部分、遗漏或错误的地方，并给出改进建议。'
                '不要编造学生没有写过的内容，不要给出具体分数，'
                '无法判断时直接说明无法判断。用中文，200 字以内。'
            )
        },
        {
            'role': 'user',
            'content': (
                f'题目：\n{normalize_text(question, 4000)}\n\n'
                f'参考答案：\n{normalize_text(reference, 4000) or "（本题没有提供参考答案）"}\n\n'
                f'学生作答：\n{normalize_text(user_answer, 4000)}'
            )
        }
    ]

    text, finish_reason = ai_service.call_ai(
        messages,
        max_tokens=ESSAY_COMMENT_MAX_TOKENS
    )

    if not text:
        return None, 'AI 讲评调用失败'

    return normalize_text(text, 4000), None


def _upsert_task_submission(cursor, task_id, student_id, paper_id, score):
    """学生完成教师任务后写回 task_submissions（存在则更新）。"""

    cursor.execute(
        """
        INSERT INTO task_submissions
        (task_id, student_id, paper_id, status, score, submitted_at)
        VALUES (%s, %s, %s, 'done', %s, NOW())
        ON DUPLICATE KEY UPDATE
            paper_id = VALUES(paper_id),
            status = 'done',
            score = VALUES(score),
            submitted_at = NOW()
        """,
        (task_id, student_id, paper_id, score)
    )


def submit_paper(user_id, paper_id, answers):
    """提交练习卷并在服务端判分，返回逐题回顾数据。

    answers 为 {item_id: 学生作答}，必须覆盖本卷题目（缺答按未作答处理）。
    同一份试卷重复提交时返回已有记录，不重复判分。
    """

    user_id = parse_positive_int(user_id)
    paper_id = parse_positive_int(paper_id)

    if not user_id or not paper_id:
        raise PracticeError('参数不合法')

    if answers is None:
        answers = {}

    if not isinstance(answers, dict):
        raise PracticeError('答案格式不正确，应为 {题目ID: 作答}')

    # 统一 key 为字符串，兼容前端 JSON
    normalized_answers = {}

    for key, value in answers.items():
        try:
            item_id = int(key)
        except (TypeError, ValueError):
            continue

        normalized_answers[item_id] = normalize_text(value, 8000)

    with connect_db() as connection:
        with connection.cursor() as cursor:
            paper, reason = _load_paper_row(cursor, user_id, paper_id)

            if reason == 'forbidden':
                raise PracticeError('无权提交该练习卷', status=403, code='FORBIDDEN')

            if not paper:
                return None

            items = _load_items(cursor, paper_id)

            if not items:
                raise PracticeError('该练习卷没有题目，无法提交')

            existing = _load_record(cursor, paper_id, user_id)

            if existing:
                _stringify_times(paper)

                return {
                    'paper': _public_paper(paper, items),
                    'already_submitted': True,
                    'review': _review_payload(cursor, paper, items, existing)
                }

    if not items:
        raise PracticeError('该练习卷没有题目，无法提交')

    # ---- 判分（AI 讲评在数据库事务之外进行，避免长时间占用连接）----
    graded = []
    notices = []
    essay_failed = 0
    essay_skipped = 0

    for item in items:
        user_answer = normalized_answers.get(item['id'], '')

        verdict = grade_answer(item['qtype'], user_answer, item.get('answer'))

        ai_comment = None

        if item['qtype'] == QTYPE_ESSAY:
            if not user_answer:
                essay_skipped += 1
            else:
                ai_comment, ai_error = _essay_comment(
                    item['question'], item.get('answer'), user_answer
                )

                if ai_error:
                    essay_failed += 1

        graded.append({
            'item_id': item['id'],
            'user_answer': user_answer,
            'is_correct': None if verdict['is_correct'] is None else (1 if verdict['is_correct'] else 0),
            'ai_comment': ai_comment,
            'note': verdict['note']
        })

    total_count = len(graded)
    graded_count = sum(1 for row in graded if row['is_correct'] is not None)
    correct_count = sum(1 for row in graded if row['is_correct'] == 1)
    score = round(correct_count / graded_count * 100, 1) if graded_count else 0.0

    if essay_failed:
        notices.append(f'{essay_failed} 道解答题的 AI 讲评调用失败，未生成讲评（不做评分）')

    if essay_skipped:
        notices.append(f'{essay_skipped} 道解答题未作答，未调用 AI 讲评')

    with db_connection() as connection:
        with connection.cursor() as cursor:
            # 并发提交兜底：事务内再查一次
            existing = _load_record(cursor, paper_id, user_id)

            if existing:
                _stringify_times(paper)

                return {
                    'paper': _public_paper(paper, items),
                    'already_submitted': True,
                    'review': _review_payload(cursor, paper, items, existing)
                }

            cursor.execute(
                """
                INSERT INTO practice_records
                (paper_id, user_id, total_count, correct_count, score, graded_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (paper_id, user_id, total_count, correct_count, score, graded_count)
            )

            record_id = cursor.lastrowid

            for row in graded:
                cursor.execute(
                    """
                    INSERT INTO practice_answers
                    (record_id, item_id, user_answer, is_correct, ai_comment)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        record_id,
                        row['item_id'],
                        row['user_answer'],
                        row['is_correct'],
                        row['ai_comment']
                    )
                )

            task_id = paper.get('task_id')

            if task_id:
                _upsert_task_submission(cursor, task_id, user_id, paper_id, score)

            cursor.execute(
                """
                SELECT id, paper_id, user_id, total_count, correct_count, score,
                       graded_count, submitted_at
                FROM practice_records
                WHERE id = %s
                """,
                (record_id,)
            )

            record = cursor.fetchone()

            _stringify_times(paper)

            review = _review_payload(cursor, paper, items, record)

    review['notices'] = notices + [
        note for note in review['notices'] if note not in notices
    ]

    logger.info(
        '练习卷 #%s 提交完成（用户 %s）：%s/%s 正确，自动判分 %s 题，得分 %s',
        paper_id, user_id, correct_count, total_count, graded_count, score
    )

    return {
        'paper': _public_paper(paper, items),
        'already_submitted': False,
        'review': review
    }


# ============================================================
# 错题回填
# ============================================================

def add_items_to_wrongbook(user_id, paper_id, item_ids=None):
    """把练习卷中答错的题目写进错题本（真实写入，走 ai_service）。"""

    user_id = parse_positive_int(user_id)
    paper_id = parse_positive_int(paper_id)

    if not user_id or not paper_id:
        raise PracticeError('参数不合法')

    with connect_db() as connection:
        with connection.cursor() as cursor:
            paper, reason = _load_paper_row(cursor, user_id, paper_id)

            if reason == 'forbidden':
                raise PracticeError('无权操作该练习卷', status=403, code='FORBIDDEN')

            if not paper:
                return None

            items = _load_items(cursor, paper_id)

            record = _load_record(cursor, paper_id, user_id)

            if not record:
                raise PracticeError('请先提交练习卷，再加入错题本')

            cursor.execute(
                """
                SELECT item_id, user_answer, is_correct
                FROM practice_answers
                WHERE record_id = %s
                """,
                (record['id'],)
            )

            answer_map = {row['item_id']: row for row in cursor.fetchall()}

    wanted_ids = None

    if item_ids:
        wanted_ids = set()

        for value in item_ids:
            try:
                wanted_ids.add(int(value))
            except (TypeError, ValueError):
                continue

    added = 0
    skipped = 0
    results = []

    for item in items:
        answer_row = answer_map.get(item['id'])

        if not answer_row:
            continue

        is_correct = answer_row.get('is_correct')

        if is_correct == 1:
            continue

        if wanted_ids is not None and item['id'] not in wanted_ids:
            continue

        question_text = item['question']

        options = _normalize_options(item.get('options_json'))

        if options:
            option_text = '\n'.join(
                f'{option["label"]}. {option["text"]}' for option in options
            )
            question_text = f'{question_text}\n{option_text}'

        answer_text = normalize_text(item.get('analysis'), 8000) \
            or normalize_text(item.get('answer'), 8000) \
            or '（本题暂无解析）'

        created = ai_service.add_wrong_question(
            user_id,
            normalize_text(paper.get('major'), 20) or '综合',
            normalize_text(item.get('kp_name'), 100) or '练习错题',
            normalize_text(question_text, 8000),
            answer_text,
            None,
            source='AI',
            knowledge_points=normalize_text(item.get('kp_name'), 255) or '',
            error_type=normalize_text(item.get('source_error_type'), 30) or '',
            user_answer=normalize_text(answer_row.get('user_answer'), 8000) or None,
            standard_answer=normalize_text(item.get('answer'), 8000) or None,
            analysis=normalize_text(item.get('analysis'), 8000) or None
        )

        if created:
            added += 1
        else:
            skipped += 1

        results.append({
            'item_id': item['id'],
            'seq': item['seq'],
            'created': bool(created)
        })

    if not results and wanted_ids is None:
        raise PracticeError('本次练习没有答错的题目，无需加入错题本')

    if not results:
        raise PracticeError('没有找到可加入错题本的题目（答对的题目不会加入错题本）')

    return {
        'added': added,
        'existing': skipped,
        'results': results,
        'message': f'已加入错题本 {added} 道' + (f'，{skipped} 道已存在' if skipped else '')
    }


# ============================================================
# 统计
# ============================================================

def student_statistics(user_id):
    """学生练习统计：全部为真实聚合值，不做任何模拟。"""

    user_id = parse_positive_int(user_id)

    if not user_id:
        raise PracticeError('用户信息无效')

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS papers,
                    COALESCE(SUM(total_count), 0) AS total_items,
                    COALESCE(SUM(graded_count), 0) AS graded_items,
                    COALESCE(SUM(correct_count), 0) AS correct_items,
                    ROUND(AVG(score), 1) AS avg_score,
                    MAX(score) AS best_score,
                    MAX(submitted_at) AS last_submitted_at
                FROM practice_records
                WHERE user_id = %s
                """,
                (user_id,)
            )

            summary = cursor.fetchone() or {}

            cursor.execute(
                """
                SELECT
                    i.kp_name,
                    COUNT(*) AS total,
                    COALESCE(SUM(a.is_correct IS NOT NULL), 0) AS graded,
                    COALESCE(SUM(a.is_correct = 1), 0) AS correct
                FROM practice_answers a
                JOIN practice_items i ON i.id = a.item_id
                JOIN practice_records r ON r.id = a.record_id
                WHERE r.user_id = %s AND i.kp_name <> ''
                GROUP BY i.kp_name
                ORDER BY total DESC, i.kp_name
                LIMIT 20
                """,
                (user_id,)
            )

            by_knowledge_point = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    i.qtype,
                    COUNT(*) AS total,
                    COALESCE(SUM(a.is_correct IS NOT NULL), 0) AS graded,
                    COALESCE(SUM(a.is_correct = 1), 0) AS correct
                FROM practice_answers a
                JOIN practice_items i ON i.id = a.item_id
                JOIN practice_records r ON r.id = a.record_id
                WHERE r.user_id = %s
                GROUP BY i.qtype
                ORDER BY total DESC
                """,
                (user_id,)
            )

            by_qtype = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    r.id AS record_id, r.paper_id, p.title, r.score,
                    r.correct_count, r.graded_count, r.total_count, r.submitted_at
                FROM practice_records r
                JOIN practice_papers p ON p.id = r.paper_id
                WHERE r.user_id = %s
                ORDER BY r.id DESC
                LIMIT 10
                """,
                (user_id,)
            )

            recent = cursor.fetchall()

            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(mastery = 2), 0) AS mastered
                FROM wrong_questions
                WHERE user_id = %s
                """,
                (user_id,)
            )

            wrong_row = cursor.fetchone() or {}

            cursor.execute(
                """
                SELECT i.id, i.paper_id, i.seq, i.question, i.kp_name
                FROM practice_items i
                JOIN practice_answers a ON a.item_id = i.id
                JOIN practice_records r ON r.id = a.record_id
                WHERE r.user_id = %s AND a.is_correct = 0
                ORDER BY a.id DESC
                LIMIT 5
                """,
                (user_id,)
            )

            recent_wrong = cursor.fetchall()

    for row in by_knowledge_point:
        row['total'] = _to_number(row.get('total'))
        row['graded'] = _to_number(row.get('graded'))
        row['correct'] = _to_number(row.get('correct'))

        graded = row['graded']
        row['accuracy'] = round(row['correct'] / graded * 100, 1) if graded else 0.0

    for row in by_qtype:
        row['total'] = _to_number(row.get('total'))
        row['graded'] = _to_number(row.get('graded'))
        row['correct'] = _to_number(row.get('correct'))

        graded = row['graded']
        row['qtype_name'] = QTYPE_NAMES.get(row['qtype'], row['qtype'])
        row['accuracy'] = round(row['correct'] / graded * 100, 1) if graded else 0.0

    for row in recent:
        _stringify_times(row)
        row['score'] = float(row['score']) if row.get('score') is not None else 0.0
        row['correct_count'] = _to_number(row.get('correct_count'))
        row['graded_count'] = _to_number(row.get('graded_count'))
        row['total_count'] = _to_number(row.get('total_count'))

    papers = _to_number(summary.get('papers'))
    graded_items = _to_number(summary.get('graded_items'))
    correct_items = _to_number(summary.get('correct_items'))

    return {
        'papers': papers,
        'total_items': _to_number(summary.get('total_items')),
        'graded_items': graded_items,
        'correct_items': correct_items,
        'avg_score': float(summary['avg_score']) if summary.get('avg_score') is not None else 0.0,
        'best_score': float(summary['best_score']) if summary.get('best_score') is not None else 0.0,
        'accuracy': round(correct_items / graded_items * 100, 1) if graded_items else 0.0,
        'last_submitted_at': str(summary['last_submitted_at']) if summary.get('last_submitted_at') else None,
        'by_knowledge_point': by_knowledge_point,
        'by_qtype': by_qtype,
        'recent': recent,
        'recent_wrong_items': recent_wrong,
        'wrong_question_total': _to_number(wrong_row.get('total')),
        'wrong_question_mastered': _to_number(wrong_row.get('mastered'))
    }


# ============================================================
# 教师任务
# ============================================================

def _load_task(cursor, task_id):
    """读取复习任务（含课程名称）。"""

    cursor.execute(
        """
        SELECT t.id, t.teacher_id, t.class_id, t.course_id, t.title, t.content,
               t.paper_id, t.due_at, t.status, c.name AS course_name, c.major AS course_major
        FROM learning_tasks t
        LEFT JOIN courses c ON c.id = t.course_id
        WHERE t.id = %s
        """,
        (task_id,)
    )

    return cursor.fetchone()


def _student_in_class(cursor, class_id, user_id):
    """学生是否属于该班级。"""

    cursor.execute(
        """
        SELECT 1
        FROM class_students
        WHERE class_id = %s AND user_id = %s
        LIMIT 1
        """,
        (class_id, user_id)
    )

    return cursor.fetchone() is not None


def list_student_tasks(user_id):
    """学生所在班级的复习任务及自己的完成情况。"""

    user_id = parse_positive_int(user_id)

    if not user_id:
        raise PracticeError('用户信息无效')

    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    t.id, t.title, t.content, t.course_id, t.paper_id,
                    t.due_at, t.status, c.name AS course_name,
                    ts.status AS submission_status, ts.score, ts.submitted_at,
                    (SELECT COUNT(*) FROM practice_papers p WHERE p.id = t.paper_id) AS paper_ready
                FROM learning_tasks t
                JOIN class_students cs ON cs.class_id = t.class_id AND cs.user_id = %s
                LEFT JOIN courses c ON c.id = t.course_id
                LEFT JOIN task_submissions ts ON ts.task_id = t.id AND ts.student_id = %s
                WHERE t.status = 1
                ORDER BY (t.due_at IS NULL), t.due_at ASC, t.id DESC
                LIMIT 50
                """,
                (user_id, user_id)
            )

            rows = cursor.fetchall()

    for row in rows:
        _stringify_times(row)
        row['score'] = float(row['score']) if row.get('score') is not None else None
        row['done'] = row.get('submission_status') == 'done'

    return {'items': rows, 'total': len(rows)}


def generate_task_paper(user_id, task_id):
    """打开/生成教师任务对应的练习卷。

    教师已经指定试卷时直接复用；否则按任务描述为该学生现场组卷，
    并把 task_submissions 置为 pending（提交时会更新为 done）。
    """

    user_id = parse_positive_int(user_id)
    task_id = parse_positive_int(task_id)

    if not user_id or not task_id:
        raise PracticeError('参数不合法')

    with connect_db() as connection:
        with connection.cursor() as cursor:
            task = _load_task(cursor, task_id)

            if not task:
                raise PracticeError('复习任务不存在', status=404, code='NOT_FOUND')

            if task.get('status') != 1:
                raise PracticeError('该复习任务已关闭')

            if not _student_in_class(cursor, task['class_id'], user_id):
                raise PracticeError('该复习任务不在你所在的班级', status=403, code='FORBIDDEN')

            existing_paper_id = task.get('paper_id')

            if existing_paper_id:
                paper, reason = _load_paper_row(cursor, user_id, existing_paper_id)

                if paper:
                    items = _load_items(cursor, existing_paper_id)
                    record = _load_record(cursor, existing_paper_id, user_id)

                    _stringify_times(paper)

                    review = _review_payload(cursor, paper, items, record) if record else None

                    return {
                        'paper': _public_paper(paper, items),
                        'reused': True,
                        'submitted': bool(review),
                        'review': review,
                        'notices': _paper_notices(items)
                    }

                # 教师指定的试卷不存在或无权访问：改为现场组卷
                logger.warning('任务 #%s 关联的试卷 %s 不可用，改为现场组卷', task_id, existing_paper_id)

    major = normalize_text(task.get('course_major'), 50) or None

    if major and major not in ai_service.MAJOR_CATEGORIES:
        major = None

    result = generate_paper(
        user_id,
        major=major,
        kp=None,
        qtype=None,
        difficulty=None,
        count=DEFAULT_ITEM_COUNT,
        course_id=task.get('course_id'),
        source=SOURCE_AUTO,
        allow_ai=True,
        task_id=task_id,
        title=normalize_text(task.get('title'), 150) or '教师复习任务'
    )

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO task_submissions
                (task_id, student_id, paper_id, status)
                VALUES (%s, %s, %s, 'pending')
                ON DUPLICATE KEY UPDATE paper_id = VALUES(paper_id)
                """,
                (task_id, user_id, result['paper']['id'])
            )

    result['reused'] = False
    result['submitted'] = False
    result['review'] = None

    return result

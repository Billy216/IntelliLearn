# -*- coding: utf-8 -*-
"""学习数据服务：错题本、知识点、学情统计。

本模块只负责数据库读写，不涉及 Flask 请求对象，
便于单元测试与其他模块（练习、教师端、管理端）复用。
"""

from backend.extensions.database import connect_db
from backend.utils.logging_config import get_logger


logger = get_logger('study')


# 允许筛选的错误类型（与 ai_service.ERROR_TYPES 对应）
MASTERY_LABELS = {
    0: '未掌握',
    1: '模糊',
    2: '已掌握'
}


def _build_filters(user_id, major=None, error_type=None, mastery=None,
                   keyword=None, kp=None, course_id=None):
    """构造错题查询的 WHERE 子句与参数（全部使用参数化占位符）。"""

    clauses = ['user_id = %s']
    params = [user_id]

    if major:
        clauses.append('major = %s')
        params.append(major)

    if error_type:
        clauses.append('error_type = %s')
        params.append(error_type)

    if mastery is not None:
        clauses.append('mastery = %s')
        params.append(mastery)

    if course_id:
        clauses.append('course_id = %s')
        params.append(course_id)

    if kp:
        clauses.append('knowledge_points LIKE %s')
        params.append(f'%{kp}%')

    if keyword:
        clauses.append('(question LIKE %s OR answer LIKE %s OR analysis LIKE %s)')
        like = f'%{keyword}%'
        params.extend([like, like, like])

    return ' AND '.join(clauses), params


def list_wrong_questions(user_id, major=None, error_type=None, mastery=None,
                         keyword=None, kp=None, course_id=None,
                         page=1, page_size=20):
    """分页查询错题。

    返回 {'items': [...], 'total': n, 'page': p, 'page_size': s}
    """

    where, params = _build_filters(
        user_id, major, error_type, mastery, keyword, kp, course_id
    )

    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    offset = (page - 1) * page_size

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM wrong_questions WHERE {where}',
                tuple(params)
            )

            total = list(cursor.fetchone().values())[0]

            cursor.execute(
                f"""
                SELECT
                    id, major, sub, question, answer, image_url, source,
                    course_id, chapter_id, knowledge_points, error_type,
                    user_answer, standard_answer, analysis, mastery,
                    review_count, last_review_at, conversation_id,
                    created_at, updated_at
                FROM wrong_questions
                WHERE {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset])
            )

            items = cursor.fetchall()

    finally:
        connection.close()

    for item in items:
        for key in ('created_at', 'updated_at', 'last_review_at'):
            if item.get(key) is not None:
                item[key] = str(item[key])

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size
    }


def get_wrong_question(user_id, question_id):
    """读取单条错题（带归属校验）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM wrong_questions
                WHERE id = %s AND user_id = %s
                """,
                (question_id, user_id)
            )

            row = cursor.fetchone()

            if not row:
                return None

            cursor.execute(
                """
                SELECT kp_name
                FROM wrong_question_kps
                WHERE wrong_question_id = %s
                ORDER BY id
                """,
                (question_id,)
            )

            row['kp_list'] = [item['kp_name'] for item in cursor.fetchall()]

    finally:
        connection.close()

    for key in ('created_at', 'updated_at', 'last_review_at'):
        if row.get(key) is not None:
            row[key] = str(row[key])

    return row


def update_wrong_question(user_id, question_id, fields):
    """更新错题的分类与掌握度等字段。

    只允许更新白名单内的列，避免拼接任意列名。
    """

    allowed = {
        'major', 'sub', 'knowledge_points', 'error_type', 'mastery',
        'analysis', 'user_answer', 'standard_answer', 'course_id',
        'chapter_id'
    }

    updates = []
    params = []

    for key, value in (fields or {}).items():
        if key not in allowed:
            continue

        if key == 'mastery':
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue

            if value not in (0, 1, 2):
                continue

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return False

    params.extend([question_id, user_id])

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE wrong_questions
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                """,
                tuple(params)
            )

            affected = cursor.rowcount

            # 知识点变化时同步更新关联表
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
                        INSERT IGNORE INTO wrong_question_kps
                        (wrong_question_id, kp_name)
                        VALUES (%s, %s)
                        """,
                        (question_id, kp[:150])
                    )

            connection.commit()

            return affected >= 0
    finally:
        connection.close()


def mark_reviewed(user_id, question_id, mastery=None):
    """记录一次复习：复习次数 +1，可同时更新掌握度。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            if mastery is None:
                cursor.execute(
                    """
                    UPDATE wrong_questions
                    SET review_count = review_count + 1,
                        last_review_at = NOW()
                    WHERE id = %s AND user_id = %s
                    """,
                    (question_id, user_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE wrong_questions
                    SET review_count = review_count + 1,
                        last_review_at = NOW(),
                        mastery = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (mastery, question_id, user_id)
                )

            affected = cursor.rowcount

            connection.commit()

            return affected > 0
    finally:
        connection.close()


def delete_wrong_question(user_id, question_id):
    """删除错题（同时清理知识点关联），返回是否删除成功。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM wrong_questions
                WHERE id = %s AND user_id = %s
                """,
                (question_id, user_id)
            )

            affected = cursor.rowcount

            if affected:
                cursor.execute(
                    """
                    DELETE FROM wrong_question_kps
                    WHERE wrong_question_id = %s
                    """,
                    (question_id,)
                )

            connection.commit()

            return affected > 0
    finally:
        connection.close()


def wrong_question_majors(user_id):
    """该用户错题中出现过的学科及数量（用于筛选项，全部来自真实数据）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT major, COUNT(*) AS total
                FROM wrong_questions
                WHERE user_id = %s
                GROUP BY major
                ORDER BY total DESC
                """,
                (user_id,)
            )

            return cursor.fetchall()
    finally:
        connection.close()


def wrong_question_stats(user_id):
    """错题统计：按错误类型、掌握度、知识点聚合。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT error_type, COUNT(*) AS total
                FROM wrong_questions
                WHERE user_id = %s AND error_type <> ''
                GROUP BY error_type
                ORDER BY total DESC
                """,
                (user_id,)
            )

            by_error_type = cursor.fetchall()

            cursor.execute(
                """
                SELECT mastery, COUNT(*) AS total
                FROM wrong_questions
                WHERE user_id = %s
                GROUP BY mastery
                ORDER BY mastery
                """,
                (user_id,)
            )

            by_mastery = [
                {
                    'mastery': row['mastery'],
                    'label': MASTERY_LABELS.get(row['mastery'], '未知'),
                    'total': row['total']
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT kp_name, COUNT(*) AS total
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE w.user_id = %s
                GROUP BY kp_name
                ORDER BY total DESC
                LIMIT 20
                """,
                (user_id,)
            )

            by_knowledge_point = cursor.fetchall()

            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(mastery = 2) AS mastered
                FROM wrong_questions
                WHERE user_id = %s
                """,
                (user_id,)
            )

            summary_row = cursor.fetchone() or {}

    finally:
        connection.close()

    total = summary_row.get('total') or 0
    mastered = summary_row.get('mastered') or 0

    return {
        'total': total,
        'mastered': mastered,
        'mastery_rate': round(mastered / total * 100, 1) if total else 0.0,
        'by_error_type': by_error_type,
        'by_mastery': by_mastery,
        'by_knowledge_point': by_knowledge_point
    }


def weak_knowledge_points(user_id, limit=10):
    """学生薄弱知识点：按错题数量排序（数据来自真实错题记录）。"""

    connection = connect_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    k.kp_name,
                    COUNT(*) AS total,
                    SUM(w.mastery = 2) AS mastered
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                WHERE w.user_id = %s
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT %s
                """,
                (user_id, limit)
            )

            return cursor.fetchall()
    finally:
        connection.close()

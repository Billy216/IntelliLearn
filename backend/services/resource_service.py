# -*- coding: utf-8 -*-
"""本校知识库与学习资源检索服务（模块五）。

职责：
- courses / chapters / knowledge_points 的增删改查；
- resources 的检索、推荐、班级薄弱知识点匹配、批量导入；
- 统计资源的下载次数（真实计数，不做假）。

重要说明（数据真实性）：
项目内没有任何真实校方课件或历年真题。因此凡是为演示而创建的资源，
必须显式写入 is_demo=1，接口把 is_demo 原样返回，前端必须标注
“演示数据（非真实校方资源）”。批量导入接口 /api/resources/import
用于学校导入真实资源，写入 is_demo=0。

所有 SQL 使用 %s 占位符；动态更新列名一律走白名单。
"""

import json

from backend.extensions.database import db_connection
from backend.utils.logging_config import get_logger


logger = get_logger('resource')


# 资源类型白名单（与 resources.rtype 取值一致）
RESOURCE_TYPES = ('courseware', 'exam', 'summary', 'errors', 'other')

RESOURCE_TYPE_LABELS = {
    'courseware': '课件',
    'exam': '试卷',
    'summary': '总结',
    'errors': '错题集',
    'other': '其他'
}

# 难度取值
DIFFICULTY_LABELS = {
    1: '简单',
    2: '中等',
    3: '困难'
}

# resources 可写列白名单
RESOURCE_WRITABLE = {
    'title', 'rtype', 'course_id', 'chapter_id', 'kp_name', 'major',
    'description', 'file_path', 'external_url', 'source', 'is_demo',
    'uploader_id', 'status'
}

# courses 可写列白名单
COURSE_WRITABLE = {
    'code', 'name', 'major', 'college', 'credit', 'description', 'status'
}

# chapters 可写列白名单
CHAPTER_WRITABLE = {
    'course_id', 'name', 'sort_order', 'description'
}

# knowledge_points 可写列白名单
KP_WRITABLE = {
    'course_id', 'chapter_id', 'name', 'description', 'difficulty',
    'parent_id', 'exam_weight'
}


# ============================================================
# 内部工具
# ============================================================

def _to_str(value, max_length=None):
    """转成干净字符串，可截断。"""

    if value is None:
        return None

    text = str(value).strip()

    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def _int_or_none(value):
    """转 int，失败返回 None。"""

    if value in (None, '', 'null'):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stringify(rows, keys=('created_at', 'updated_at')):
    """datetime 转字符串。"""

    if isinstance(rows, dict):
        rows = [rows]

    for row in rows or []:
        for key in keys:
            if row.get(key) is not None:
                row[key] = str(row[key])

    return rows


def _rows_to_dicts(rows):
    """结果集统一补充类型中文名与演示标记文案。"""

    for row in rows or []:
        if 'rtype' in row:
            row['rtype_label'] = RESOURCE_TYPE_LABELS.get(row['rtype'], '其他')

        if 'is_demo' in row:
            row['is_demo'] = int(row['is_demo'] or 0)
            row['demo_label'] = (
                '演示数据（非真实校方资源）' if row['is_demo'] else ''
            )

        if 'difficulty' in row and row['difficulty'] is not None:
            row['difficulty_label'] = DIFFICULTY_LABELS.get(
                int(row['difficulty']), '中等'
            )

    return rows


# ============================================================
# 课程
# ============================================================

def list_courses(keyword=None, major=None, include_disabled=False):
    """课程列表（只读，所有登录用户可见）。"""

    clauses = []
    params = []

    if not include_disabled:
        clauses.append('co.status = 1')

    if keyword:
        clauses.append('(co.name LIKE %s OR co.code LIKE %s)')
        params.extend([f'%{keyword}%', f'%{keyword}%'])

    if major:
        clauses.append('co.major = %s')
        params.append(major)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    co.id, co.code, co.name, co.major, co.college, co.credit,
                    co.description, co.status, co.created_at, co.updated_at,
                    (SELECT COUNT(*) FROM chapters ch
                      WHERE ch.course_id = co.id) AS chapter_count,
                    (SELECT COUNT(*) FROM knowledge_points kp
                      WHERE kp.course_id = co.id) AS kp_count,
                    (SELECT COUNT(*) FROM resources r
                      WHERE r.course_id = co.id AND r.status = 1) AS resource_count
                FROM courses co
                {where}
                ORDER BY co.id DESC
                """,
                tuple(params)
            )

            return _stringify(cursor.fetchall())


def get_course(course_id):
    """单门课程详情。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, code, name, major, college, credit, description,
                       status, created_at, updated_at
                FROM courses
                WHERE id = %s
                """,
                (course_id,)
            )

            row = cursor.fetchone()

    if not row:
        return None

    return _stringify([row])[0]


def create_course(data):
    """新建课程，返回 (结果字典, 状态码)。"""

    name = _to_str(data.get('name'), 100)

    if not name:
        return {'success': False, 'message': '课程名称不能为空'}, 400

    fields = {}
    values = {}

    for key in ('code', 'major', 'college', 'description'):
        if key in data:
            fields[key] = _to_str(data.get(key), 500 if key == 'description' else 100)

    if 'credit' in data and data.get('credit') not in (None, ''):
        try:
            fields['credit'] = round(float(data.get('credit')), 1)
        except (TypeError, ValueError):
            return {'success': False, 'message': '学分必须是数字'}, 400

    if 'status' in data:
        fields['status'] = 1 if int(data.get('status') or 0) else 0

    columns = ['name'] + [key for key in fields if key in COURSE_WRITABLE]
    values_list = [name] + [fields[key] for key in columns[1:]]

    placeholders = ', '.join(['%s'] * len(columns))

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO courses ({', '.join(columns)})
                    VALUES ({placeholders})
                    """,
                    tuple(values_list)
                )

                course_id = cursor.lastrowid

                connection.commit()
    except Exception as exc:
        logger.error('新建课程失败: %s', exc)

        return {'success': False, 'message': '课程名称或课程代码已存在'}, 409

    logger.info('新建课程 %s（%s）', course_id, name)

    return {'success': True, 'message': '课程已创建', 'course_id': course_id}, 200


def update_course(course_id, data):
    """更新课程（列名白名单）。"""

    updates = []
    params = []

    for key in COURSE_WRITABLE:
        if key not in data:
            continue

        value = data.get(key)

        if key == 'credit':
            if value in (None, ''):
                updates.append('credit = NULL')
                continue

            try:
                value = round(float(value), 1)
            except (TypeError, ValueError):
                return {'success': False, 'message': '学分必须是数字'}, 400
        elif key == 'status':
            value = 1 if int(value or 0) else 0
        else:
            value = _to_str(value, 500 if key == 'description' else 100)

            if key == 'name' and not value:
                return {'success': False, 'message': '课程名称不能为空'}, 400

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(course_id)

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE courses SET {', '.join(updates)} WHERE id = %s",
                    tuple(params)
                )

                affected = cursor.rowcount

                connection.commit()
    except Exception as exc:
        logger.error('更新课程失败: %s', exc)

        return {'success': False, 'message': '更新失败，课程名称可能重复'}, 409

    if affected == 0 and not get_course(course_id):
        return {'success': False, 'message': '课程不存在'}, 404

    return {'success': True, 'message': '课程已更新', 'affected': affected}, 200


def delete_course(course_id):
    """删除课程。

    课程下仍有章节 / 知识点 / 资源时拒绝删除，避免留下悬空外键数据。
    """

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM courses WHERE id = %s', (course_id,))

            if not cursor.fetchone():
                return {'success': False, 'message': '课程不存在'}, 404

            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM chapters WHERE course_id = %s) AS chapters,
                    (SELECT COUNT(*) FROM knowledge_points WHERE course_id = %s) AS kps,
                    (SELECT COUNT(*) FROM resources WHERE course_id = %s) AS resources,
                    (SELECT COUNT(*) FROM teacher_courses WHERE course_id = %s) AS links
                """,
                (course_id, course_id, course_id, course_id)
            )

            counts = cursor.fetchone()

            blocking = {
                key: counts[key] for key in counts if counts[key]
            }

            if blocking:
                return {
                    'success': False,
                    'message': (
                        '该课程下仍有章节/知识点/资源/授课关系，'
                        '请先清理后再删除'
                    ),
                    'blocking': blocking
                }, 409

            cursor.execute('DELETE FROM courses WHERE id = %s', (course_id,))

            connection.commit()

    logger.info('删除课程 %s', course_id)

    return {'success': True, 'message': '课程已删除'}, 200


# ============================================================
# 章节
# ============================================================

def list_chapters(course_id=None):
    """章节列表（可按课程过滤）。"""

    clauses = []
    params = []

    if course_id:
        clauses.append('ch.course_id = %s')
        params.append(course_id)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    ch.id, ch.course_id, ch.name, ch.sort_order,
                    ch.description, ch.created_at,
                    co.name AS course_name,
                    (SELECT COUNT(*) FROM knowledge_points kp
                      WHERE kp.chapter_id = ch.id) AS kp_count
                FROM chapters ch
                LEFT JOIN courses co ON co.id = ch.course_id
                {where}
                ORDER BY ch.course_id, ch.sort_order, ch.id
                """,
                tuple(params)
            )

            return _stringify(cursor.fetchall())


def create_chapter(data):
    """新建章节。"""

    course_id = _int_or_none(data.get('course_id'))
    name = _to_str(data.get('name'), 150)

    if not course_id:
        return {'success': False, 'message': '必须指定所属课程'}, 400

    if not name:
        return {'success': False, 'message': '章节名称不能为空'}, 400

    if not get_course(course_id):
        return {'success': False, 'message': '课程不存在'}, 404

    sort_order = _int_or_none(data.get('sort_order')) or 0

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chapters (course_id, name, sort_order, description)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    course_id,
                    name,
                    sort_order,
                    _to_str(data.get('description'), 2000)
                )
            )

            chapter_id = cursor.lastrowid

            connection.commit()

    logger.info('新建章节 %s（课程 %s）', chapter_id, course_id)

    return {'success': True, 'message': '章节已创建', 'chapter_id': chapter_id}, 200


def update_chapter(chapter_id, data):
    """更新章节。"""

    updates = []
    params = []

    for key in CHAPTER_WRITABLE:
        if key not in data:
            continue

        if key == 'course_id':
            value = _int_or_none(data.get(key))

            if not value:
                return {'success': False, 'message': '所属课程不合法'}, 400
        elif key == 'sort_order':
            value = _int_or_none(data.get(key)) or 0
        elif key == 'name':
            value = _to_str(data.get(key), 150)

            if not value:
                return {'success': False, 'message': '章节名称不能为空'}, 400
        else:
            value = _to_str(data.get(key), 2000)

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(chapter_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE chapters SET {', '.join(updates)} WHERE id = %s",
                tuple(params)
            )

            affected = cursor.rowcount

            connection.commit()

    return {'success': True, 'message': '章节已更新', 'affected': affected}, 200


def delete_chapter(chapter_id):
    """删除章节（下面还有知识点时拒绝）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM chapters WHERE id = %s', (chapter_id,))

            if not cursor.fetchone():
                return {'success': False, 'message': '章节不存在'}, 404

            cursor.execute(
                'SELECT COUNT(*) AS total FROM knowledge_points WHERE chapter_id = %s',
                (chapter_id,)
            )

            total = cursor.fetchone()['total']

            if total:
                return {
                    'success': False,
                    'message': f'该章节下还有 {total} 个知识点，请先删除知识点'
                }, 409

            cursor.execute('DELETE FROM chapters WHERE id = %s', (chapter_id,))

            connection.commit()

    logger.info('删除章节 %s', chapter_id)

    return {'success': True, 'message': '章节已删除'}, 200


# ============================================================
# 知识点
# ============================================================

def list_knowledge_points(course_id=None, chapter_id=None, keyword=None):
    """知识点列表。"""

    clauses = []
    params = []

    if course_id:
        clauses.append('kp.course_id = %s')
        params.append(course_id)

    if chapter_id:
        clauses.append('kp.chapter_id = %s')
        params.append(chapter_id)

    if keyword:
        clauses.append('kp.name LIKE %s')
        params.append(f'%{keyword}%')

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    kp.id, kp.course_id, kp.chapter_id, kp.name, kp.description,
                    kp.difficulty, kp.parent_id, kp.exam_weight, kp.created_at,
                    co.name AS course_name,
                    ch.name AS chapter_name
                FROM knowledge_points kp
                LEFT JOIN courses co ON co.id = kp.course_id
                LEFT JOIN chapters ch ON ch.id = kp.chapter_id
                {where}
                ORDER BY kp.course_id, kp.chapter_id, kp.id
                """,
                tuple(params)
            )

            return _rows_to_dicts(_stringify(cursor.fetchall()))


def create_knowledge_point(data):
    """新建知识点。"""

    name = _to_str(data.get('name'), 150)

    if not name:
        return {'success': False, 'message': '知识点名称不能为空'}, 400

    course_id = _int_or_none(data.get('course_id'))

    if course_id and not get_course(course_id):
        return {'success': False, 'message': '课程不存在'}, 404

    difficulty = _int_or_none(data.get('difficulty')) or 2

    if difficulty not in (1, 2, 3):
        return {'success': False, 'message': '难度取值为 1/2/3'}, 400

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO knowledge_points
                    (course_id, chapter_id, name, description, difficulty,
                     parent_id, exam_weight)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        course_id,
                        _int_or_none(data.get('chapter_id')),
                        name,
                        _to_str(data.get('description'), 2000),
                        difficulty,
                        _int_or_none(data.get('parent_id')),
                        data.get('exam_weight') or None
                    )
                )

                kp_id = cursor.lastrowid

                connection.commit()
    except Exception as exc:
        logger.error('新建知识点失败: %s', exc)

        return {'success': False, 'message': '同一课程下已存在同名知识点'}, 409

    logger.info('新建知识点 %s（%s）', kp_id, name)

    return {'success': True, 'message': '知识点已创建', 'kp_id': kp_id}, 200


def update_knowledge_point(kp_id, data):
    """更新知识点。"""

    updates = []
    params = []

    for key in KP_WRITABLE:
        if key not in data:
            continue

        if key in ('course_id', 'chapter_id', 'parent_id'):
            value = _int_or_none(data.get(key))
        elif key == 'difficulty':
            value = _int_or_none(data.get(key)) or 2

            if value not in (1, 2, 3):
                return {'success': False, 'message': '难度取值为 1/2/3'}, 400
        elif key == 'name':
            value = _to_str(data.get(key), 150)

            if not value:
                return {'success': False, 'message': '知识点名称不能为空'}, 400
        elif key == 'exam_weight':
            value = data.get(key) or None
        else:
            value = _to_str(data.get(key), 2000)

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(kp_id)

    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE knowledge_points SET {', '.join(updates)} WHERE id = %s",
                    tuple(params)
                )

                affected = cursor.rowcount

                connection.commit()
    except Exception as exc:
        logger.error('更新知识点失败: %s', exc)

        return {'success': False, 'message': '更新失败，名称可能重复'}, 409

    return {'success': True, 'message': '知识点已更新', 'affected': affected}, 200


def delete_knowledge_point(kp_id):
    """删除知识点（被错题引用时把 wrong_question_kps.knowledge_point_id 置空）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id FROM knowledge_points WHERE id = %s',
                (kp_id,)
            )

            if not cursor.fetchone():
                return {'success': False, 'message': '知识点不存在'}, 404

            cursor.execute(
                """
                UPDATE wrong_question_kps
                SET knowledge_point_id = NULL
                WHERE knowledge_point_id = %s
                """,
                (kp_id,)
            )

            cursor.execute('DELETE FROM knowledge_points WHERE id = %s', (kp_id,))

            connection.commit()

    logger.info('删除知识点 %s', kp_id)

    return {'success': True, 'message': '知识点已删除'}, 200


# ============================================================
# 资源：检索与推荐
# ============================================================

def list_resources(rtype=None, course_id=None, chapter_id=None, keyword=None,
                   major=None, kp_name=None, is_demo=None, include_disabled=False,
                   page=1, page_size=20):
    """资源检索（分页）。

    所有筛选条件都是真实字段匹配，返回 is_demo 供前端标注演示数据。
    """

    clauses = []
    params = []

    if not include_disabled:
        clauses.append('r.status = 1')

    if rtype:
        clauses.append('r.rtype = %s')
        params.append(rtype)

    if course_id:
        clauses.append('r.course_id = %s')
        params.append(course_id)

    if chapter_id:
        clauses.append('r.chapter_id = %s')
        params.append(chapter_id)

    if major:
        clauses.append('r.major = %s')
        params.append(major)

    if kp_name:
        clauses.append('r.kp_name LIKE %s')
        params.append(f'%{kp_name}%')

    if is_demo in (0, 1):
        clauses.append('r.is_demo = %s')
        params.append(is_demo)

    if keyword:
        clauses.append(
            '(r.title LIKE %s OR r.description LIKE %s OR r.kp_name LIKE %s)'
        )
        like = f'%{keyword}%'
        params.extend([like, like, like])

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''

    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    offset = (page - 1) * page_size

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) AS total FROM resources r {where}',
                tuple(params)
            )

            total = cursor.fetchone()['total']

            cursor.execute(
                f"""
                SELECT
                    r.id, r.title, r.rtype, r.course_id, r.chapter_id,
                    r.kp_name, r.major, r.description, r.file_path,
                    r.external_url, r.source, r.is_demo, r.uploader_id,
                    r.download_count, r.status, r.created_at, r.updated_at,
                    co.name AS course_name,
                    ch.name AS chapter_name,
                    u.real_name AS uploader_name,
                    u.user_no AS uploader_no
                FROM resources r
                LEFT JOIN courses co ON co.id = r.course_id
                LEFT JOIN chapters ch ON ch.id = r.chapter_id
                LEFT JOIN users u ON u.id = r.uploader_id
                {where}
                ORDER BY r.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset])
            )

            items = _rows_to_dicts(_stringify(cursor.fetchall()))

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size
    }


def get_resource(resource_id):
    """资源详情。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.*, co.name AS course_name, ch.name AS chapter_name,
                    u.real_name AS uploader_name, u.user_no AS uploader_no
                FROM resources r
                LEFT JOIN courses co ON co.id = r.course_id
                LEFT JOIN chapters ch ON ch.id = r.chapter_id
                LEFT JOIN users u ON u.id = r.uploader_id
                WHERE r.id = %s
                """,
                (resource_id,)
            )

            row = cursor.fetchone()

    if not row:
        return None

    return _rows_to_dicts(_stringify([row]))[0]


def create_resource(uploader_id, data, allow_demo=True):
    """新建资源。

    安全约定：只有显式传入 is_demo=1 才会写成演示数据；
    allow_demo 为 False 时直接拒绝 is_demo。
    """

    title = _to_str(data.get('title'), 200)

    if not title:
        return {'success': False, 'message': '资源标题不能为空'}, 400

    rtype = _to_str(data.get('rtype')) or 'other'

    if rtype not in RESOURCE_TYPES:
        return {'success': False, 'message': '资源类型不在允许范围内'}, 400

    is_demo = 0

    if data.get('is_demo') in (1, '1', True, 'true'):
        if not allow_demo:
            return {'success': False, 'message': '该接口不允许写入演示数据'}, 400

        is_demo = 1

    external_url = _to_str(data.get('external_url'), 500)
    file_path = _to_str(data.get('file_path'), 255)

    if not external_url and not file_path:
        return {
            'success': False,
            'message': '必须提供 external_url 或上传后的 file_path'
        }, 400

    if file_path and not file_path.startswith('/uploads/'):
        return {
            'success': False,
            'message': 'file_path 必须是 /uploads/ 下的站内路径，'
                       '外链请使用 external_url'
        }, 400

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO resources
                (title, rtype, course_id, chapter_id, kp_name, major,
                 description, file_path, external_url, source, is_demo,
                 uploader_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    title,
                    rtype,
                    _int_or_none(data.get('course_id')),
                    _int_or_none(data.get('chapter_id')),
                    _to_str(data.get('kp_name'), 150) or '',
                    _to_str(data.get('major'), 50),
                    _to_str(data.get('description'), 4000),
                    file_path,
                    external_url,
                    _to_str(data.get('source'), 200),
                    is_demo,
                    uploader_id
                )
            )

            resource_id = cursor.lastrowid

            connection.commit()

    logger.info(
        '新增资源 %s（类型 %s，演示数据=%s）',
        resource_id, rtype, is_demo
    )

    return {
        'success': True,
        'message': ('已新增资源（演示数据，非真实校方资源）' if is_demo
                    else '资源已新增'),
        'resource_id': resource_id,
        'is_demo': is_demo
    }, 200


def update_resource(resource_id, data):
    """更新资源（列名白名单）。"""

    updates = []
    params = []

    for key in RESOURCE_WRITABLE:
        if key not in data:
            continue

        value = data.get(key)

        if key in ('course_id', 'chapter_id', 'uploader_id'):
            value = _int_or_none(value)
        elif key in ('is_demo', 'status'):
            value = 1 if value in (1, '1', True, 'true') else 0
        elif key == 'rtype':
            value = _to_str(value) or 'other'

            if value not in RESOURCE_TYPES:
                return {'success': False, 'message': '资源类型不在允许范围内'}, 400
        elif key == 'title':
            value = _to_str(value, 200)

            if not value:
                return {'success': False, 'message': '资源标题不能为空'}, 400
        elif key == 'file_path':
            value = _to_str(value, 255)

            if value and not value.startswith('/uploads/'):
                return {
                    'success': False,
                    'message': 'file_path 必须是 /uploads/ 下的站内路径'
                }, 400
        else:
            limit = 4000 if key == 'description' else 500
            value = _to_str(value, limit)

        updates.append(f'{key} = %s')
        params.append(value)

    if not updates:
        return {'success': False, 'message': '没有需要更新的字段'}, 400

    params.append(resource_id)

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE resources SET {', '.join(updates)} WHERE id = %s",
                tuple(params)
            )

            affected = cursor.rowcount

            connection.commit()

    if affected == 0 and not get_resource(resource_id):
        return {'success': False, 'message': '资源不存在'}, 404

    return {'success': True, 'message': '资源已更新', 'affected': affected}, 200


def delete_resource(resource_id):
    """删除资源（软删除：status 置 0，保留下载统计与历史）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE resources SET status = 0 WHERE id = %s',
                (resource_id,)
            )

            affected = cursor.rowcount

            connection.commit()

    if not affected:
        return {'success': False, 'message': '资源不存在'}, 404

    logger.info('下架资源 %s', resource_id)

    return {'success': True, 'message': '资源已下架（软删除）'}, 200


def increase_download(resource_id):
    """下载计数 +1，返回资源地址（真实计数）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE resources
                SET download_count = download_count + 1
                WHERE id = %s AND status = 1
                """,
                (resource_id,)
            )

            affected = cursor.rowcount

            connection.commit()

    if not affected:
        return None

    return get_resource(resource_id)


def import_resources(uploader_id, items, is_demo=0):
    """批量导入资源（JSON 数组）。

    真实校方资源请传 is_demo=0；上传者、时间等由服务端写入，不接受客户端伪造。
    返回 (结果字典, 状态码)。
    """

    if not isinstance(items, list) or not items:
        return {'success': False, 'message': '请求体必须是至少含 1 条记录的数组'}, 400

    if len(items) > 500:
        return {'success': False, 'message': '单次最多导入 500 条'}, 400

    is_demo = 1 if is_demo in (1, '1', True, 'true') else 0

    created = []
    errors = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append({'index': index, 'message': '记录必须是对象'})
            continue

        result, status = create_resource(
            uploader_id,
            dict(item, is_demo=is_demo),
            allow_demo=True
        )

        if status == 200 and result.get('success'):
            created.append(result['resource_id'])
        else:
            errors.append({
                'index': index,
                'title': item.get('title'),
                'message': result.get('message')
            })

    logger.info(
        '批量导入资源：成功 %s 条，失败 %s 条（演示数据=%s）',
        len(created), len(errors), is_demo
    )

    return {
        'success': True,
        'message': f'导入完成：成功 {len(created)} 条，失败 {len(errors)} 条',
        'created_ids': created,
        'created_count': len(created),
        'failed_count': len(errors),
        'errors': errors[:20],
        'is_demo': is_demo
    }, 200


def recommend_for_student(student_id, limit=10):
    """按学生自己的薄弱知识点推荐资源（模块五「根据我的易错点检索」）。

    薄弱点来自 study_service.weak_knowledge_points（真实错题数据）。
    """

    from backend.services import study_service

    weak_points = study_service.weak_knowledge_points(student_id, limit=20)

    kp_names = [row['kp_name'] for row in weak_points if row.get('kp_name')]

    # 学生错题涉及的真实学科
    majors = [
        row['major'] for row in study_service.wrong_question_majors(student_id)
        if row.get('major')
    ]

    matched = []

    if kp_names or majors:
        # 知识点逐个 LIKE 匹配（命中数用于排序），学科用 IN 匹配，两者取并集
        clauses = []
        params = []

        if kp_names:
            clauses.append(
                '(' + ' OR '.join(['r.kp_name LIKE %s'] * len(kp_names)) + ')'
            )
            params.extend([f'%{name}%' for name in kp_names])

        if majors:
            clauses.append(
                'r.major IN (' + ', '.join(['%s'] * len(majors)) + ')'
            )
            params.extend(majors)

        where = ' OR '.join(clauses)

        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        r.id, r.title, r.rtype, r.course_id, r.chapter_id,
                        r.kp_name, r.major, r.description, r.file_path,
                        r.external_url, r.source, r.is_demo, r.download_count,
                        r.created_at,
                        co.name AS course_name,
                        ch.name AS chapter_name
                    FROM resources r
                    LEFT JOIN courses co ON co.id = r.course_id
                    LEFT JOIN chapters ch ON ch.id = r.chapter_id
                    WHERE r.status = 1 AND ({where})
                    ORDER BY r.download_count DESC, r.id DESC
                    LIMIT %s
                    """,
                    tuple(params + [limit])
                )

                matched = _rows_to_dicts(_stringify(cursor.fetchall()))

    # 计算每个资源命中的薄弱点个数，用于前端排序展示（真实计算，不是估算）
    for row in matched:
        hits = [name for name in kp_names if name and name in (row['kp_name'] or '')]

        row['matched_points'] = hits
        row['matched_count'] = len(hits)

    matched.sort(key=lambda item: (-item['matched_count'], -item['download_count']))

    return {
        'weak_points': weak_points,
        'majors': majors,
        'items': matched,
        'total': len(matched)
    }


def resources_for_class(class_id, limit=20):
    """班级薄弱知识点对应的资源（教师端「哪些资源能覆盖本班薄弱点」）。

    班级薄弱点来自该班学生真实错题的知识点聚合。
    """

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    k.kp_name,
                    COUNT(*) AS total,
                    COUNT(DISTINCT w.user_id) AS student_count
                FROM wrong_question_kps k
                JOIN wrong_questions w ON w.id = k.wrong_question_id
                JOIN class_students cs ON cs.user_id = w.user_id
                WHERE cs.class_id = %s
                GROUP BY k.kp_name
                ORDER BY total DESC, k.kp_name
                LIMIT 20
                """,
                (class_id,)
            )

            weak_points = cursor.fetchall()

            kp_names = [row['kp_name'] for row in weak_points if row.get('kp_name')]

            items = []

            if kp_names:
                clause_sql = ' OR '.join(['r.kp_name LIKE %s'] * len(kp_names))

                cursor.execute(
                    f"""
                    SELECT
                        r.id, r.title, r.rtype, r.course_id, r.kp_name, r.major,
                        r.description, r.file_path, r.external_url, r.source,
                        r.is_demo, r.download_count, r.created_at,
                        co.name AS course_name
                    FROM resources r
                    LEFT JOIN courses co ON co.id = r.course_id
                    WHERE r.status = 1 AND ({clause_sql})
                    ORDER BY r.download_count DESC, r.id DESC
                    LIMIT %s
                    """,
                    tuple([f'%{name}%' for name in kp_names] + [limit])
                )

                items = _rows_to_dicts(_stringify(cursor.fetchall()))

    for row in items:
        row['matched_points'] = [
            name for name in kp_names if name and name in (row['kp_name'] or '')
        ]

    # 覆盖情况：哪些薄弱点还没有对应资源（真实的覆盖缺口分析）
    covered = set()

    for row in items:
        covered.update(row['matched_points'])

    return {
        'weak_points': weak_points,
        'items': items,
        'total': len(items),
        'uncovered_points': [name for name in kp_names if name not in covered]
    }


def resource_stats():
    """资源总览统计（按类型、演示数据、下载量）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rtype, COUNT(*) AS total, SUM(download_count) AS downloads
                FROM resources
                WHERE status = 1
                GROUP BY rtype
                ORDER BY total DESC
                """
            )

            by_type = cursor.fetchall()

            for row in by_type:
                row['rtype_label'] = RESOURCE_TYPE_LABELS.get(row['rtype'], '其他')
                row['downloads'] = int(row['downloads'] or 0)

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(is_demo = 1) AS demo_count,
                    SUM(download_count) AS downloads
                FROM resources
                WHERE status = 1
                """
            )

            summary = cursor.fetchone() or {}

    return {
        'total': int(summary.get('total') or 0),
        'demo_count': int(summary.get('demo_count') or 0),
        'downloads': int(summary.get('downloads') or 0),
        'by_type': by_type
    }


def resource_majors():
    """资源中出现过的真实学科列表（用于筛选下拉框）。"""

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT major, COUNT(*) AS total
                FROM resources
                WHERE status = 1 AND major IS NOT NULL AND major <> ''
                GROUP BY major
                ORDER BY total DESC
                """
            )

            return cursor.fetchall()


def parse_options_json(raw):
    """把 options_json 文本解析成对象，解析失败返回原文（不静默丢数据）。"""

    if not raw:
        return None

    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw

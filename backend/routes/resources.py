# -*- coding: utf-8 -*-
"""本校知识库与学习资源检索接口（模块五）。

页面路由已存在（GET /resources）。本蓝图提供 /api/resources* 系列接口：
- 课程 / 章节 / 知识点：所有人可只读，仅管理员可写；
- 资源检索与推荐：所有登录用户可用；
- 资源增删改与批量导入：教师 / 管理员。

数据真实性约定：
项目内没有真实校方课件或试卷，因此演示资源必须写 is_demo=1，
接口原样返回该字段，前端必须标注「演示数据（非真实校方资源）」。
/api/resources/import 用于学校导入真实资源（is_demo=0）。
"""

from flask import Blueprint, request, session

from backend.services import resource_service
from backend.utils.logging_config import get_logger
from backend.utils.responses import fail, forbidden, not_found, ok
from backend.utils.security import (
    ROLE_ADMIN,
    ROLE_TEACHER,
    login_required,
    role_required
)
from backend.utils.validators import normalize_text, parse_positive_int


resources_bp = Blueprint('resources', __name__)

logger = get_logger('resource')


def _viewer():
    """当前操作者信息。"""

    role = session.get('role')

    return {
        'user_id': session.get('userid'),
        'role': role,
        'is_admin': role == ROLE_ADMIN,
        'can_manage': role in (ROLE_TEACHER, ROLE_ADMIN)
    }


def _parse_mastery_filter(raw):
    """把 is_demo 查询参数解析成 0/1/None。"""

    if raw in ('0', '1'):
        return int(raw)

    return None


# ============================================================
# 资源检索
# ============================================================

@resources_bp.route('/api/resources', methods=['GET'])
@login_required
def api_resources_list():
    """资源检索：课程 / 章节 / 关键词 / 类型 / 学科 / 知识点。"""

    viewer = _viewer()

    page = parse_positive_int(request.args.get('page'), 1) or 1
    page_size = parse_positive_int(request.args.get('page_size'), 20, maximum=100) or 20

    try:
        result = resource_service.list_resources(
            rtype=normalize_text(request.args.get('rtype'), 30) or None,
            course_id=parse_positive_int(request.args.get('course_id')),
            chapter_id=parse_positive_int(request.args.get('chapter_id')),
            keyword=normalize_text(request.args.get('keyword'), 100) or None,
            major=normalize_text(request.args.get('major'), 50) or None,
            kp_name=normalize_text(request.args.get('kp_name'), 150) or None,
            is_demo=_parse_mastery_filter(request.args.get('is_demo')),
            include_disabled=viewer['can_manage']
            and request.args.get('include_disabled') == '1',
            page=page,
            page_size=page_size
        )
    except Exception as exc:
        logger.error('资源检索失败: %s', exc)
        return fail('资源检索失败', status=500)

    demo_count = len([item for item in result['items'] if item.get('is_demo')])

    return ok(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        page_size=result['page_size'],
        demo_count=demo_count,
        demo_notice='列表中标记「演示数据（非真实校方资源）」的条目不是学校真实资料'
    )


@resources_bp.route('/api/resources/filters', methods=['GET'])
@login_required
def api_resources_filters():
    """筛选下拉框数据（课程 / 学科 / 类型），全部来自真实数据表。"""

    try:
        courses = resource_service.list_courses()
        majors = resource_service.resource_majors()
    except Exception as exc:
        logger.error('读取筛选项失败: %s', exc)
        return fail('筛选条件读取失败', status=500)

    return ok(
        courses=courses,
        majors=majors,
        rtypes=[
            {'value': value, 'label': label}
            for value, label in resource_service.RESOURCE_TYPE_LABELS.items()
        ]
    )


@resources_bp.route('/api/resources/stats', methods=['GET'])
@login_required
def api_resources_stats():
    """资源总览（真实计数，含演示数据条数）。"""

    try:
        stats = resource_service.resource_stats()
    except Exception as exc:
        logger.error('资源统计失败: %s', exc)
        return fail('资源统计失败', status=500)

    stats['demo_notice'] = (
        f"其中 {stats['demo_count']} 条为演示数据（非真实校方资源）"
        if stats['demo_count'] else '当前没有演示数据'
    )

    return ok(data=stats)


@resources_bp.route('/api/resources/recommend', methods=['GET'])
@login_required
def api_resources_recommend():
    """根据当前用户的错题易错点推荐资源（学生视角）。"""

    user_id = session.get('userid')

    limit = parse_positive_int(request.args.get('limit'), 10, maximum=50) or 10

    try:
        result = resource_service.recommend_for_student(user_id, limit=limit)
    except Exception as exc:
        logger.error('资源推荐失败: %s', exc)
        return fail('资源推荐失败', status=500)

    return ok(
        data=result['items'],
        total=result['total'],
        weak_points=result['weak_points'],
        majors=result['majors'],
        recommend_note=(
            '推荐依据是你自己错题本里的知识点与学科，没有数据时不会编造推荐'
        )
    )


@resources_bp.route('/api/resources/for-class', methods=['GET'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_resources_for_class():
    """教师视角：哪些资源覆盖了本班的薄弱知识点。"""

    from backend.services import teacher_service

    viewer = _viewer()

    class_id = parse_positive_int(request.args.get('class_id'))

    if not class_id:
        return fail('请提供 class_id')

    # 班级范围必须由服务端校验，不能只靠前端隐藏
    if not teacher_service.can_access_class(
        viewer['user_id'], class_id, viewer['is_admin']
    ):
        return forbidden('该班级不在你的授课范围内')

    limit = parse_positive_int(request.args.get('limit'), 20, maximum=100) or 20

    try:
        result = resource_service.resources_for_class(class_id, limit=limit)
    except Exception as exc:
        logger.error('读取班级薄弱点资源失败: %s', exc)
        return fail('班级薄弱点资源读取失败', status=500)

    result['class_id'] = class_id

    return ok(**result)


# ============================================================
# 资源详情与维护
# ============================================================

@resources_bp.route('/api/resources/<int:resource_id>', methods=['GET'])
@login_required
def api_resource_detail(resource_id):
    """资源详情。"""

    try:
        row = resource_service.get_resource(resource_id)
    except Exception as exc:
        logger.error('读取资源详情失败: %s', exc)
        return fail('资源读取失败', status=500)

    if not row:
        return not_found('资源不存在')

    return ok(data=row)


@resources_bp.route('/api/resources', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_resource_create():
    """新增资源（教师 / 管理员）。

    演示数据必须显式传 is_demo=1，响应会明确提示这不是真实校方资源。
    """

    viewer = _viewer()
    data = request.get_json(silent=True) or {}

    payload = {
        'title': normalize_text(data.get('title'), 200),
        'rtype': normalize_text(data.get('rtype'), 30) or 'other',
        'course_id': parse_positive_int(data.get('course_id')),
        'chapter_id': parse_positive_int(data.get('chapter_id')),
        'kp_name': normalize_text(data.get('kp_name'), 150),
        'major': normalize_text(data.get('major'), 50),
        'description': normalize_text(data.get('description'), 4000),
        'file_path': normalize_text(data.get('file_path'), 255),
        'external_url': normalize_text(data.get('external_url'), 500),
        'source': normalize_text(data.get('source'), 200),
        'is_demo': 1 if data.get('is_demo') in (1, '1', True, 'true') else 0
    }

    try:
        result, status = resource_service.create_resource(
            viewer['user_id'], payload
        )
    except Exception as exc:
        logger.error('新增资源失败: %s', exc)
        return fail('资源新增失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '资源新增失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/resources/<int:resource_id>', methods=['PATCH'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_resource_update(resource_id):
    """更新资源。"""

    data = request.get_json(silent=True) or {}

    # 只接受出现过的字段，且交给服务层的列名白名单过滤
    payload = {}

    for key in ('title', 'rtype', 'kp_name', 'major', 'description',
                'file_path', 'external_url', 'source'):
        if key in data:
            payload[key] = normalize_text(data.get(key), 4000 if key == 'description' else 500)

    for key in ('course_id', 'chapter_id'):
        if key in data:
            payload[key] = parse_positive_int(data.get(key))

    if 'status' in data:
        payload['status'] = 1 if data.get('status') in (1, '1', True, 'true') else 0

    if 'is_demo' in data:
        payload['is_demo'] = 1 if data.get('is_demo') in (1, '1', True, 'true') else 0

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = resource_service.update_resource(resource_id, payload)
    except Exception as exc:
        logger.error('更新资源失败: %s', exc)
        return fail('资源更新失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '资源更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/resources/<int:resource_id>', methods=['DELETE'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_resource_delete(resource_id):
    """下架资源（软删除，保留下载统计）。"""

    try:
        result, status = resource_service.delete_resource(resource_id)
    except Exception as exc:
        logger.error('删除资源失败: %s', exc)
        return fail('资源删除失败', status=500)

    if not result.get('success'):
        return not_found(result.get('message'))

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/resources/<int:resource_id>/download', methods=['POST'])
@login_required
def api_resource_download(resource_id):
    """记录一次下载并返回真实地址（计数来自真实点击）。"""

    try:
        row = resource_service.increase_download(resource_id)
    except Exception as exc:
        logger.error('记录资源下载失败: %s', exc)
        return fail('下载记录失败', status=500)

    if not row:
        return not_found('资源不存在或已下架')

    return ok(
        data={
            'id': row['id'],
            'title': row['title'],
            'file_path': row.get('file_path'),
            'external_url': row.get('external_url'),
            'download_count': row['download_count'],
            'is_demo': row.get('is_demo', 0)
        }
    )


@resources_bp.route('/api/resources/import', methods=['POST'])
@role_required(ROLE_TEACHER, ROLE_ADMIN)
def api_resources_import():
    """批量导入真实校方资源（JSON 数组）。

    请求体可以是数组本身，也可以是 {"items": [...]}；
    is_demo 默认 0（真实资源），显式传 1 时才会写成演示数据。
    """

    viewer = _viewer()
    data = request.get_json(silent=True)

    if isinstance(data, dict):
        items = data.get('items')
        is_demo = data.get('is_demo', 0)
    elif isinstance(data, list):
        items = data
        is_demo = 0
    else:
        return fail('请求体必须是 JSON 数组或包含 items 的对象')

    try:
        result, status = resource_service.import_resources(
            viewer['user_id'], items, is_demo=is_demo
        )
    except Exception as exc:
        logger.error('批量导入资源失败: %s', exc)
        return fail('批量导入失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '批量导入失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


# ============================================================
# 课程 / 章节 / 知识点
# ============================================================

@resources_bp.route('/api/courses', methods=['GET'])
@login_required
def api_courses_list():
    """课程列表（只读，所有人可见）。"""

    viewer = _viewer()

    try:
        courses = resource_service.list_courses(
            keyword=normalize_text(request.args.get('keyword'), 100) or None,
            major=normalize_text(request.args.get('major'), 50) or None,
            include_disabled=viewer['is_admin']
            and request.args.get('include_disabled') == '1'
        )
    except Exception as exc:
        logger.error('读取课程列表失败: %s', exc)
        return fail('课程列表读取失败', status=500)

    return ok(data=courses, total=len(courses))


@resources_bp.route('/api/courses', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_course_create():
    """新建课程（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'name': normalize_text(data.get('name'), 100),
        'code': normalize_text(data.get('code'), 50),
        'major': normalize_text(data.get('major'), 50),
        'college': normalize_text(data.get('college'), 100),
        'description': normalize_text(data.get('description'), 4000)
    }

    if data.get('credit') not in (None, ''):
        payload['credit'] = data.get('credit')

    try:
        result, status = resource_service.create_course(payload)
    except Exception as exc:
        logger.error('新建课程失败: %s', exc)
        return fail('课程创建失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '课程创建失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/courses/<int:course_id>', methods=['GET'])
@login_required
def api_course_detail(course_id):
    """课程详情。"""

    try:
        row = resource_service.get_course(course_id)
    except Exception as exc:
        logger.error('读取课程失败: %s', exc)
        return fail('课程读取失败', status=500)

    if not row:
        return not_found('课程不存在')

    return ok(data=row)


@resources_bp.route('/api/courses/<int:course_id>', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_course_update(course_id):
    """更新课程（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {}

    for key in ('name', 'code', 'major', 'college', 'description'):
        if key in data:
            payload[key] = normalize_text(
                data.get(key), 4000 if key == 'description' else 100
            )

    if 'credit' in data:
        payload['credit'] = data.get('credit')

    if 'status' in data:
        payload['status'] = 1 if data.get('status') in (1, '1', True, 'true') else 0

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = resource_service.update_course(course_id, payload)
    except Exception as exc:
        logger.error('更新课程失败: %s', exc)
        return fail('课程更新失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '课程更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/courses/<int:course_id>', methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_course_delete(course_id):
    """删除课程（仅管理员；有下级数据时拒绝）。"""

    try:
        result, status = resource_service.delete_course(course_id)
    except Exception as exc:
        logger.error('删除课程失败: %s', exc)
        return fail('课程删除失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '课程删除失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/chapters', methods=['GET'])
@login_required
def api_chapters_list():
    """章节列表（可按课程过滤）。"""

    try:
        chapters = resource_service.list_chapters(
            course_id=parse_positive_int(request.args.get('course_id'))
        )
    except Exception as exc:
        logger.error('读取章节列表失败: %s', exc)
        return fail('章节列表读取失败', status=500)

    return ok(data=chapters, total=len(chapters))


@resources_bp.route('/api/chapters', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_chapter_create():
    """新建章节（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'course_id': parse_positive_int(data.get('course_id')),
        'name': normalize_text(data.get('name'), 150),
        'sort_order': data.get('sort_order'),
        'description': normalize_text(data.get('description'), 2000)
    }

    try:
        result, status = resource_service.create_chapter(payload)
    except Exception as exc:
        logger.error('新建章节失败: %s', exc)
        return fail('章节创建失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '章节创建失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/chapters/<int:chapter_id>', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_chapter_update(chapter_id):
    """更新章节（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {}

    if 'name' in data:
        payload['name'] = normalize_text(data.get('name'), 150)

    if 'description' in data:
        payload['description'] = normalize_text(data.get('description'), 2000)

    if 'sort_order' in data:
        payload['sort_order'] = data.get('sort_order')

    if 'course_id' in data:
        payload['course_id'] = parse_positive_int(data.get('course_id'))

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = resource_service.update_chapter(chapter_id, payload)
    except Exception as exc:
        logger.error('更新章节失败: %s', exc)
        return fail('章节更新失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '章节更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/chapters/<int:chapter_id>', methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_chapter_delete(chapter_id):
    """删除章节（仅管理员；下面还有知识点时拒绝）。"""

    try:
        result, status = resource_service.delete_chapter(chapter_id)
    except Exception as exc:
        logger.error('删除章节失败: %s', exc)
        return fail('章节删除失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '章节删除失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/knowledge-points', methods=['GET'])
@login_required
def api_knowledge_points_list():
    """知识点列表（只读）。"""

    try:
        points = resource_service.list_knowledge_points(
            course_id=parse_positive_int(request.args.get('course_id')),
            chapter_id=parse_positive_int(request.args.get('chapter_id')),
            keyword=normalize_text(request.args.get('keyword'), 100) or None
        )
    except Exception as exc:
        logger.error('读取知识点失败: %s', exc)
        return fail('知识点读取失败', status=500)

    return ok(data=points, total=len(points))


@resources_bp.route('/api/knowledge-points', methods=['POST'])
@role_required(ROLE_ADMIN)
def api_knowledge_point_create():
    """新建知识点（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {
        'course_id': parse_positive_int(data.get('course_id')),
        'chapter_id': parse_positive_int(data.get('chapter_id')),
        'name': normalize_text(data.get('name'), 150),
        'description': normalize_text(data.get('description'), 2000),
        'difficulty': data.get('difficulty'),
        'parent_id': parse_positive_int(data.get('parent_id')),
        'exam_weight': data.get('exam_weight')
    }

    try:
        result, status = resource_service.create_knowledge_point(payload)
    except Exception as exc:
        logger.error('新建知识点失败: %s', exc)
        return fail('知识点创建失败', status=500)

    if not result.get('success'):
        if status == 404:
            return not_found(result.get('message'))

        return fail(result.get('message', '知识点创建失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/knowledge-points/<int:kp_id>', methods=['PATCH'])
@role_required(ROLE_ADMIN)
def api_knowledge_point_update(kp_id):
    """更新知识点（仅管理员）。"""

    data = request.get_json(silent=True) or {}

    payload = {}

    if 'name' in data:
        payload['name'] = normalize_text(data.get('name'), 150)

    if 'description' in data:
        payload['description'] = normalize_text(data.get('description'), 2000)

    for key in ('difficulty', 'exam_weight'):
        if key in data:
            payload[key] = data.get(key)

    for key in ('course_id', 'chapter_id', 'parent_id'):
        if key in data:
            payload[key] = parse_positive_int(data.get(key))

    if not payload:
        return fail('没有需要更新的字段')

    try:
        result, status = resource_service.update_knowledge_point(kp_id, payload)
    except Exception as exc:
        logger.error('更新知识点失败: %s', exc)
        return fail('知识点更新失败', status=500)

    if not result.get('success'):
        return fail(result.get('message', '知识点更新失败'), status=status)

    return ok(**{key: value for key, value in result.items() if key != 'success'})


@resources_bp.route('/api/knowledge-points/<int:kp_id>', methods=['DELETE'])
@role_required(ROLE_ADMIN)
def api_knowledge_point_delete(kp_id):
    """删除知识点（仅管理员）。"""

    try:
        result, status = resource_service.delete_knowledge_point(kp_id)
    except Exception as exc:
        logger.error('删除知识点失败: %s', exc)
        return fail('知识点删除失败', status=500)

    if not result.get('success'):
        return not_found(result.get('message'))

    return ok(**{key: value for key, value in result.items() if key != 'success'})

"""参数与文件校验工具。

集中放置校验逻辑，避免各路由重复实现导致规则不一致。
"""

import os
import re
import unicodedata

from config import Config


# ============================================================
# 账号与密码
# ============================================================

# 学号/教师号：首字母 f（学生）或 t（教师）+ 8 位数字
USER_NO_PATTERN = re.compile(r'^[ft]\d{8}$')


def validate_user_no(user_no):
    """校验学号/教师号格式，返回 (是否合法, 错误说明, 角色)。"""

    if not user_no:
        return False, '学号/教师号不能为空', None

    user_no = str(user_no).strip().lower()

    if not USER_NO_PATTERN.match(user_no):
        return (
            False,
            '学号/教师号格式不正确（学生以 f 开头、教师以 t 开头，共 9 位）',
            None
        )

    role = 'student' if user_no[0] == 'f' else 'teacher'

    return True, '', role


def validate_password(password, username=None):
    """统一密码策略，注册与修改密码共用。

    返回 (是否合法, 错误说明)。规则：
    - 长度在 PASSWORD_MIN_LENGTH 与 PASSWORD_MAX_LENGTH 之间
    - 同时包含大写字母、小写字母、数字、特殊字符
    - 不能与账号相同
    - 不能为纯数字或纯字母
    """

    if not password or not isinstance(password, str):
        return False, '密码不能为空'

    if len(password) < Config.PASSWORD_MIN_LENGTH:
        return (
            False,
            f'密码长度至少 {Config.PASSWORD_MIN_LENGTH} 位'
        )

    if len(password) > Config.PASSWORD_MAX_LENGTH:
        return (
            False,
            f'密码长度不能超过 {Config.PASSWORD_MAX_LENGTH} 位'
        )

    if not any(c.islower() for c in password):
        return False, '密码需包含小写字母'

    if not any(c.isupper() for c in password):
        return False, '密码需包含大写字母'

    if not any(c.isdigit() for c in password):
        return False, '密码需包含数字'

    if not any(not c.isalnum() for c in password):
        return False, '密码需包含特殊字符'

    if username and password.lower() == str(username).lower():
        return False, '密码不能与账号相同'

    return True, ''


# ============================================================
# 图片上传校验
# ============================================================

def image_extension(filename):
    """从文件名取出小写扩展名（不含点），无扩展名返回空串。"""

    if not filename or '.' not in filename:
        return ''

    return filename.rsplit('.', 1)[1].strip().lower()


def allowed_extension(filename):
    """扩展名是否在白名单内。"""

    return image_extension(filename) in Config.ALLOWED_EXTENSIONS


def check_image_signature(file_storage):
    """按文件头魔数校验图片真实类型。

    仅信任扩展名是不够的：把任意文件改名成 .jpg 也能通过扩展名检查。
    校验后会 seek(0) 复位，便于后续保存。

    返回 (是否合法, 错误说明, 实际扩展名)。
    """

    header = file_storage.stream.read(16)

    try:
        file_storage.stream.seek(0)
    except Exception:
        return False, '文件读取失败，请重新选择图片', ''

    if not header:
        return False, '文件内容为空', ''

    if header.startswith(b'RIFF'):
        # webp 需要检查第 8-12 字节是否为 WEBP
        if header[8:12] != b'WEBP':
            return False, '文件不是有效的图片', ''

        return True, '', 'webp'

    for ext, signatures in Config.ALLOWED_IMAGE_SIGNATURES.items():
        for signature in signatures:
            if header.startswith(signature):
                return True, '', ext

    return False, '文件内容不是有效的图片（仅支持 png/jpg/gif/webp）', ''


def check_image_size(file_storage):
    """按实际字节数校验图片大小。

    返回 (是否合法, 错误说明, 字节数)。
    """

    stream = file_storage.stream

    try:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current)
    except Exception:
        return True, '', 0

    if size <= 0:
        return False, '文件内容为空', 0

    if size > Config.MAX_IMAGE_SIZE:
        limit_mb = Config.MAX_IMAGE_SIZE / 1024 / 1024

        return (
            False,
            f'图片大小不能超过 {limit_mb:.0f}MB',
            size
        )

    return True, '', size


# ============================================================
# 路径安全
# ============================================================

def resolve_under(base_dir, url_path):
    """把 URL 路径安全地解析到 base_dir 之内。

    用于阻止 `../` 目录穿越：解析后的绝对路径必须仍在 base_dir 内，
    否则返回 None。只接受以 '/' 开头的站内路径。
    """

    if not url_path or not isinstance(url_path, str):
        return None

    # 去掉查询串与锚点
    clean = url_path.split('?', 1)[0].split('#', 1)[0]

    # 拒绝协议、绝对盘符等写法
    if '://' in clean or clean.startswith('//'):
        return None

    clean = clean.lstrip('/\\')

    base_abs = os.path.realpath(base_dir)

    candidate = os.path.realpath(
        os.path.join(base_abs, *[
            part for part in clean.replace('\\', '/').split('/')
            if part not in ('', '.')
        ])
    )

    if candidate == base_abs:
        return None

    if not candidate.startswith(base_abs + os.sep):
        return None

    return candidate


def resolve_upload_url(url_path):
    """把形如 `/uploads/problems/xxx.jpg` 的地址解析为 uploads 内的真实路径。

    先在 BASE_DIR 下解析（数据库里存的是站内 URL），再确认结果落在 uploads 之内；
    任何越界写法（`..`、绝对路径、协议地址）都返回 None。
    """

    if not url_path or not isinstance(url_path, str):
        return None

    # 先按项目根解析出真实路径
    candidate = resolve_under(Config.BASE_DIR, url_path)

    if not candidate:
        return None

    # 再确认它确实位于 uploads 目录内
    upload_root = os.path.realpath(Config.UPLOAD_ROOT)

    if not candidate.startswith(upload_root + os.sep):
        return None

    return candidate


def normalize_text(value, max_length=None):
    """清理文本输入：去首尾空白、去控制字符、限制长度。"""

    if value is None:
        return ''

    text = str(value)

    # 去掉零宽字符与控制字符（保留换行与制表）
    text = ''.join(
        ch for ch in text
        if ch in '\n\t' or unicodedata.category(ch)[0] != 'C'
    )

    text = text.strip()

    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def parse_positive_int(value, default=None, maximum=None):
    """把输入解析为正整数，失败返回 default。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return default

    if number <= 0:
        return default

    if maximum is not None and number > maximum:
        return maximum

    return number

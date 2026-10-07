"""登录失败限流（进程内实现）。

说明：当前项目以单进程方式部署（`python app.py`），因此用进程内计数即可。
若将来使用多进程/多实例部署，需要改为 Redis 或数据库计数，
本模块对外接口保持不变即可平滑替换。
"""

import time
from collections import defaultdict

from config import Config


# key -> [失败次数, 首次失败时间, 锁定到期时间]
_attempts = defaultdict(lambda: [0, 0.0, 0.0])


def _now():
    return time.time()


def is_locked(key):
    """返回 (是否锁定, 剩余秒数)。"""

    record = _attempts.get(key)

    if not record:
        return False, 0

    locked_until = record[2]

    if locked_until and locked_until > _now():
        return True, int(locked_until - _now())

    # 锁定已过期：清空计数
    if locked_until and locked_until <= _now():
        _attempts.pop(key, None)

    return False, 0


def record_failure(key):
    """记录一次登录失败，达到阈值后锁定。"""

    record = _attempts[key]

    record[0] += 1

    if record[1] == 0.0:
        record[1] = _now()

    if record[0] >= Config.LOGIN_MAX_ATTEMPTS:
        record[2] = _now() + Config.LOGIN_LOCKOUT_SECONDS

    return record[0]


def reset(key):
    """登录成功后清空失败计数。"""

    _attempts.pop(key, None)


def remaining_attempts(key):
    """剩余可尝试次数。"""

    record = _attempts.get(key)

    if not record:
        return Config.LOGIN_MAX_ATTEMPTS

    return max(0, Config.LOGIN_MAX_ATTEMPTS - record[0])

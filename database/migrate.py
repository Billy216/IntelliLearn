# -*- coding: utf-8 -*-
"""数据库迁移工具（版本化管理，可重复执行）。

用法（在项目根目录执行）：

    # 查看待执行的迁移
    python database/migrate.py --status

    # 先备份再执行迁移（推荐）
    python database/migrate.py --backup

    # 只执行迁移（不备份）
    python database/migrate.py

    # 演练：只打印将要执行的语句，不真正执行
    python database/migrate.py --dry-run

设计说明：
- 迁移文件放在 database/migrations/ 下，按文件名排序依次执行；
- 已执行的版本记录在 schema_migrations 表，重复运行不会重复执行；
- 所有迁移必须是非破坏性语句（只增不删），如需回滚请使用备份文件还原；
- 执行前若加 --backup，会用 mysqldump 生成一份完整备份。
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config  # noqa: E402
from backend.extensions.database import connect_db  # noqa: E402


MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')

DEFAULT_BACKUP_DIR = os.path.join(Config.BASE_DIR, 'backups')


def ensure_migration_table(connection):
    """创建迁移版本表。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version VARCHAR(64) NOT NULL,
              name VARCHAR(200) NOT NULL DEFAULT '',
              applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (version)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            COMMENT='数据库迁移版本记录'
            """
        )

    connection.commit()


def applied_versions(connection):
    """已执行的版本集合。"""

    with connection.cursor() as cursor:
        cursor.execute('SELECT version FROM schema_migrations')

        return {row['version'] for row in cursor.fetchall()}


def split_statements(sql_text):
    """把 SQL 文件拆成单条语句。

    - 跳过 `--` 与 `#` 注释行、`/* */` 块注释；
    - 以分号结尾切分，忽略空语句；
    - 本项目的迁移文件只包含 DDL 与简单 DML，不包含存储过程，
      因此不需要处理 DELIMITER 切换。
    """

    # 去掉块注释
    sql_text = re.sub(r'/\*.*?\*/', '', sql_text, flags=re.S)

    lines = []

    for line in sql_text.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith('--') or stripped.startswith('#'):
            continue

        lines.append(line)

    statements = []
    buffer = []

    for line in lines:
        buffer.append(line)

        if line.rstrip().endswith(';'):
            statement = '\n'.join(buffer).strip().rstrip(';').strip()
            buffer = []

            if statement:
                statements.append(statement)

    tail = '\n'.join(buffer).strip()

    if tail:
        statements.append(tail)

    return statements


def discover_migrations():
    """按文件名顺序返回迁移文件列表 [(version, name, path)]。"""

    if not os.path.isdir(MIGRATIONS_DIR):
        return []

    items = []

    for filename in sorted(os.listdir(MIGRATIONS_DIR)):
        if not filename.endswith('.sql'):
            continue

        version = filename.split('_', 1)[0]
        name = filename[:-4]
        items.append((version, name, os.path.join(MIGRATIONS_DIR, filename)))

    return items


def run_backup():
    """用 mysqldump 生成一份完整备份，返回备份文件路径（失败返回 None）。"""

    os.makedirs(DEFAULT_BACKUP_DIR, exist_ok=True)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = os.path.join(
        DEFAULT_BACKUP_DIR,
        f'{Config.DB_NAME}_{stamp}.sql'
    )

    command = [
        'mysqldump',
        '--host=' + str(Config.DB_HOST),
        '--port=' + str(Config.DB_PORT),
        '--user=' + str(Config.DB_USER),
        '--single-transaction',
        '--routines',
        '--events',
        '--default-character-set=utf8mb4',
        Config.DB_NAME
    ]

    env = dict(os.environ, MYSQL_PWD=str(Config.DB_PASSWORD or ''))

    print(f'[备份] 正在执行 mysqldump -> {target}')

    try:
        with open(target, 'w', encoding='utf-8', errors='replace') as handle:
            result = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.PIPE,
                env=env,
                check=False
            )

        if result.returncode != 0:
            print('[备份] 失败：' + result.stderr.decode('utf-8', 'replace')[:500])
            return None

    except FileNotFoundError:
        print('[备份] 未找到 mysqldump，请将其加入 PATH，或手动备份后再执行迁移。')
        return None

    size = os.path.getsize(target)
    print(f'[备份] 完成，大小 {size} 字节')

    return target


def apply_migrations(dry_run=False, do_backup=False):
    """执行所有未执行的迁移。"""

    migrations = discover_migrations()

    if not migrations:
        print('未找到任何迁移文件。')
        return 0

    connection = connect_db()

    try:
        ensure_migration_table(connection)

        done = applied_versions(connection)

        pending = [
            item for item in migrations
            if item[0] not in done
        ]

        if not pending:
            print('数据库结构已是最新，无待执行迁移。')
            return 0

        print('待执行迁移：')

        for version, name, _path in pending:
            print(f'  - {version}  {name}')

        if dry_run:
            print('\n[dry-run] 以下为将要执行的语句：')

            for version, name, path in pending:
                with open(path, 'r', encoding='utf-8') as handle:
                    statements = split_statements(handle.read())

                print(f'\n--- {name} （{len(statements)} 条语句）---')

                for statement in statements:
                    first_line = statement.strip().splitlines()[0]
                    print('  * ' + first_line[:110])

            return 0

        if do_backup:
            if not run_backup():
                print('备份失败，已中止迁移（避免无备份变更结构）。')
                return 1

        for version, name, path in pending:
            with open(path, 'r', encoding='utf-8') as handle:
                statements = split_statements(handle.read())

            print(f'\n[迁移] {version} {name}（{len(statements)} 条语句）')

            for index, statement in enumerate(statements, 1):
                preview = statement.strip().splitlines()[0][:80]

                try:
                    with connection.cursor() as cursor:
                        cursor.execute(statement)
                except Exception as exc:
                    message = str(exc)

                    # 1060 字段已存在 / 1061 索引已存在：视为已手动应用，继续
                    if 'Duplicate column name' in message or 'Duplicate key name' in message:
                        print(f'  [{index}] 跳过（已存在）: {preview}')
                        continue

                    print(f'  [{index}] 失败: {preview}')
                    print('  错误：' + message)
                    connection.rollback()
                    return 1

                print(f'  [{index}] OK  {preview}')

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, name)
                    VALUES (%s, %s)
                    """,
                    (version, name)
                )

            connection.commit()

            print(f'[迁移] {version} 完成')

        print('\n全部迁移执行完成。')

        return 0

    finally:
        connection.close()


def show_status():
    """打印迁移状态。"""

    connection = connect_db()

    try:
        ensure_migration_table(connection)

        done = applied_versions(connection)
    finally:
        connection.close()

    print(f'数据库：{Config.DB_NAME}@{Config.DB_HOST}:{Config.DB_PORT}')
    print(f'迁移目录：{MIGRATIONS_DIR}\n')

    for version, name, _path in discover_migrations():
        mark = '已执行' if version in done else '待执行'
        print(f'  [{mark}] {version}  {name}')

    return 0


def main():
    parser = argparse.ArgumentParser(description='数据库迁移工具')
    parser.add_argument('--status', action='store_true', help='只查看迁移状态')
    parser.add_argument('--dry-run', action='store_true', help='只打印将执行的语句')
    parser.add_argument('--backup', action='store_true', help='执行前先用 mysqldump 备份')

    args = parser.parse_args()

    if args.status:
        return show_status()

    return apply_migrations(
        dry_run=args.dry_run,
        do_backup=args.backup
    )


if __name__ == '__main__':
    sys.exit(main())

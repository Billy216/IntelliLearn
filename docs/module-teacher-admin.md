# 模块八 / 九 / 十 / 五 实施报告（教师端 · 学情报表 · 系统管理端 · 本校知识库）

实施范围：模块八（教师端与师生互动）、模块九（教师学情分析与可视化报表）、
模块十（系统管理端）、模块五（本校知识库与学习资源检索）。

本文件记录：交付文件、接口清单、**真实执行过的命令与真实输出**、
数据库临时夹具清单（供验收后清理），以及没有验证到的部分。

---

## 1. 环境与前置事实

| 项目 | 值 |
| --- | --- |
| 工作目录 | `E:\IntelliLearn` |
| Python | `E:\IntelliLearn\.venv\Scripts\python.exe`（Python 3.14） |
| 数据库 | MySQL 8.0.39，库名 `IntelliLearn_test`（`IntelliLearn_test`） |
| 迁移状态 | 迁移 001 已应用，本模块**未新增任何迁移** |
| mysqldump | `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.EXE`（8.0.39） |
| 未启动的服务 | Flask 开发服务器（端口 5000 预留给集成测试，本模块全程未占用） |

> 重要：数据库是**多个 Agent 共用**的。验证期间另一模块（模块七）也在写入
> `wrong_questions` / `wrong_question_kps`，因此凡是依赖"全班总错题数"的断言
> 都改成**与服务层/接口返回值做数据库实时交叉校验**，而不是写死数字。
> 这样断言在别人继续插数据时依然成立。

---

## 2. 交付文件

### 2.1 服务层（新增）

| 文件 | 职责 |
| --- | --- |
| `backend/services/teacher_service.py` | 班级/学生授权校验、学生报告、班级报表、任务与通知、答疑、错题标注纠正、题库写入 |
| `backend/services/resource_service.py` | 课程/章节/知识点 CRUD、资源检索与推荐、批量导入、班级薄弱点资源匹配、资源统计 |
| `backend/services/admin_service.py` | 用户管理、班级与授课关系、题库管理、全校统计、操作日志、系统参数、数据库备份、SSO 配置探测 |

### 2.2 路由层（替换原桩文件，蓝图名保持不变）

| 文件 | 蓝图 |
| --- | --- |
| `backend/routes/teacher.py` | `teacher_bp` |
| `backend/routes/resources.py` | `resources_bp` |
| `backend/routes/admin.py` | `admin_bp` |

### 2.3 前端

| 文件 | 说明 |
| --- | --- |
| `templates/teacher.html` + `static/css/teacher.css` + `static/js/teacher.js` | 教师工作台：5 个标签页（班级学情 / 学生报告 / 复习任务与通知 / 学生答疑 / 错题标注纠正） |
| `templates/resources.html` + `static/css/resources.css` + `static/js/resources.js` | 知识库：5 个标签页（资源检索 / 易错点检索 / 课程与知识点 / 资源管理 / 班级薄弱点匹配） |
| `templates/admin.html` + `static/css/admin.css` + `static/js/admin.js` | 管理端：7 个标签页（全校统计 / 用户管理 / 班级与授课关系 / 课程结构 / 题库 / 日志 / 系统参数与备份） |

图表全部是**手写内联 SVG**（`barChart()` / `pieChart()`），不依赖任何 CDN 或图表库；
每个图表旁边都同时渲染**真实数据表格**，即使 SVG 无法显示也能读到数字。

前端富文本（题干、答疑内容）统一走：

```js
// TODO: window.ILRender 由 static/js/render.js 提供；未加载时退化为转义 + <br>
function markup(text) {
    if (window.ILRender && typeof window.ILRender.render === 'function') { ... }
    return esc(text).replace(/\n/g, '<br>');
}
```

`static/js/render.js` 已存在且导出 `renderInto` / `render` / `escapeHtml`，
已在三个模板中以 `<script src="/static/js/render.js"></script>` 引入；
引入失败时仍然只会输出**已转义**的文本。

> 未修改 `backend/__init__.py`、`backend/routes/page.py`、`backend/routes/chat.py`、
> `backend/routes/practice.py` 及任何清单外文件。

---

## 3. 接口清单

### 3.1 教师端 `/api/teacher/*`（`@role_required(ROLE_TEACHER, ROLE_ADMIN)`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/teacher/classes` | 仅返回 `teacher_courses` 授权班级；管理员返回全校班级（响应含 `scope_note`） |
| GET | `/api/teacher/courses` | 本人授课关系（班级+课程），供筛选 |
| GET | `/api/teacher/students?class_id=` | 授权班级学生名单（含错题数、练习数） |
| GET | `/api/teacher/student-report?student_id=&course_id=` | 单个学生真实报告 |
| GET | `/api/teacher/class-report?class_id=&course_id=&days=` | 班级聚合报表 |
| POST | `/api/teacher/tasks` | 发布复习任务（同时为学生预置 `task_submissions`） |
| GET | `/api/teacher/tasks?class_id=` | 任务列表（含完成统计） |
| GET | `/api/teacher/tasks/<id>/submissions` | 逐人完成情况（`class_students` LEFT JOIN `task_submissions`） |
| POST | `/api/teacher/notices` | 发布错题讲解通知（复用 `learning_tasks`，标题前缀 `【错题讲解通知】`） |
| GET | `/api/teacher/questions?status=&class_id=` | 学生提问列表 |
| POST | `/api/teacher/questions/<id>/reply` | 回复提问（写 `qa_replies`，置 `status='answered'`、记 `teacher_id`） |
| PATCH | `/api/teacher/wrong-questions/<id>` | 纠正知识点/错误类型/掌握度（仅限授权班级内学生） |
| POST | `/api/teacher/question-bank` | 教师确认题目入库（固定 `verified=1, source='teacher'`） |

### 3.2 知识库 `/api/resources` 与课程结构

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| GET | `/api/resources`（course_id/chapter_id/keyword/rtype/major/kp_name/is_demo/page） | 登录用户 |
| GET | `/api/resources/filters` | 登录用户 |
| GET | `/api/resources/stats` | 登录用户 |
| GET | `/api/resources/recommend` | 登录用户（依据本人 `study_service.weak_knowledge_points`） |
| GET | `/api/resources/for-class?class_id=` | 教师/管理员，且**服务端校验班级授权** |
| GET | `/api/resources/<id>` | 登录用户 |
| POST / PATCH / DELETE | `/api/resources`（`/api/resources/<id>`） | 教师/管理员 |
| POST | `/api/resources/import` | 教师/管理员（JSON 数组，默认 `is_demo=0`） |
| GET | `/api/courses`、`/api/chapters`、`/api/knowledge-points` | 登录用户（只读） |
| POST / PATCH / DELETE | `/api/courses`、`/api/chapters`、`/api/knowledge-points` | 仅管理员 |

### 3.3 管理端 `/api/admin/*`（`@role_required(ROLE_ADMIN)`）

`GET/POST /api/admin/users`、`GET/PATCH /api/admin/users/<id>`、`GET /api/admin/colleges`、
`GET/POST /api/admin/classes`、`GET/POST /api/admin/classes/<id>/students`、
`DELETE /api/admin/classes/<id>/students/<user_id>`、
`GET/POST /api/admin/teacher-courses`、`DELETE /api/admin/teacher-courses/<id>`、
`GET/POST /api/admin/questions`、`PATCH/DELETE /api/admin/questions/<id>`、
`GET /api/admin/stats`（教师调用返回 `scope='teacher'` 的授权范围数据，管理员为 `scope='school'`）、
`GET /api/admin/logs`、`GET/PATCH /api/admin/settings`、
`POST /api/admin/backup`、`GET /api/admin/backups`、`GET /api/admin/sso-config`、
`GET /api/admin/course-tree`、`GET /api/admin/class-report`、`GET /api/admin/teachers`。

---

## 4. 真实验证命令与输出

### 4.1 应用工厂 + 路由注册（必做项）

```powershell
E:\IntelliLearn\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'E:/IntelliLearn'); from backend import create_app; app=create_app(); print('OK'); print(sorted(str(r) for r in app.url_map.iter_rules() if '/api/teacher' in str(r) or '/api/admin' in str(r) or '/api/resources' in str(r)))"
```

真实输出（stderr 的 SECRET_KEY 警告属预期，非失败）：

```
[WARNING in config] SECRET_KEY 未配置或过于简单……本次已临时生成随机密钥
INFO [intellilearn.app] IntelliLearn 启动完成（debug=False，模型=agnes-2.5-flash）
OK
['/api/admin/backup', '/api/admin/backups', '/api/admin/class-report', '/api/admin/classes',
 '/api/admin/classes', '/api/admin/classes/<int:class_id>/students', '/api/admin/classes/<int:class_id>/students',
 '/api/admin/classes/<int:class_id>/students/<int:user_id>', '/api/admin/colleges', '/api/admin/course-tree',
 '/api/admin/logs', '/api/admin/questions', '/api/admin/questions', '/api/admin/questions/<int:question_id>',
 '/api/admin/questions/<int:question_id>', '/api/admin/settings', '/api/admin/settings',
 '/api/admin/sso-config', '/api/admin/stats', '/api/admin/teacher-courses', '/api/admin/teacher-courses',
 '/api/admin/teacher-courses/<int:link_id>', '/api/admin/teachers', '/api/admin/users',
 '/api/admin/users', '/api/admin/users/<int:user_id>', '/api/admin/users/<int:user_id>',
 '/api/resources', '/api/resources', '/api/resources/<int:resource_id>', '/api/resources/<int:resource_id>',
 '/api/resources/<int:resource_id>', '/api/resources/<int:resource_id>/download', '/api/resources/filters',
 '/api/resources/for-class', '/api/resources/import', '/api/resources/recommend', '/api/resources/stats',
 '/api/teacher/class-report', '/api/teacher/classes', '/api/teacher/courses', '/api/teacher/notices',
 '/api/teacher/question-bank', '/api/teacher/questions', '/api/teacher/questions/<int:question_id>/reply',
 '/api/teacher/student-report', '/api/teacher/students', '/api/teacher/tasks', '/api/teacher/tasks',
 '/api/teacher/tasks/<int:task_id>/submissions', '/api/teacher/wrong-questions/<int:question_id>']
```

PowerShell 报 `[exit code: 1]` 只是因为日志走 stderr 触发了 `NativeCommandError`；
上面 `OK` 与路由列表说明应用工厂构建成功。

### 4.2 服务层逐函数验证（62 条断言）

验证脚本（临时文件，已删除）通过 `python -` 方式执行，逐函数打印真实 JSON。
最终一轮结果：

```
断言通过 62/62
```

覆盖到的关键点（每条都打印了真实 JSON，此处摘录结论）：

| 验证项 | 真实结果 |
| --- | --- |
| `list_classes(teacher=5)` | 只返回 1 个授权班级（`测试班级-勿用`，4 人） |
| `list_classes(admin)` | 返回全部 2 个班级 |
| `list_students(5, class=1)` | 4 名学生，含各自真实 `wrong_count` |
| `list_students(5, class=2)`（未授权） | 返回 `None` → 路由层 403 |
| `student_report(5, 3)` | `wrong_total=8, mastered=2, mastery_rate=25.0`，错误类型 `计算错误 4 / 公式使用错误 2 / 方法选择不当 2`，薄弱点 `无穷级数敛散性 6`、`曲线积分与格林公式 2`，练习 `times=1, avg_score=16.7` |
| `class_report(5, 1, days=3650)` | 与服务端数据库实时聚合一致（验证时 `wrong_total=14`，因为模块七同时给学生 6 写入了 4 条错题）；错误类型百分比合计 100%；掌握度固定 0/1/2 三档 |
| `create_task` | 返回 `task_id`，并为 4 名学生预置 `task_submissions`（`student_count=4`） |
| `create_task` 到未授权班级 | `status=403`，消息「该班级不在你的授课范围内，无法发布任务」 |
| `task_submissions` | 1 人 `done`（88.5 分）、3 人 `pending`；`rate=25.0`；未开始的学生同样出现在名单里 |
| `create_notice` | 标题 `【错题讲解通知】第 8 周错题讲解`，写入 `learning_tasks` |
| `list_questions(teacher=5)` | 只返回本班那 1 条提问 |
| `reply_question` | 写入 `qa_replies`，提问 `status` 由 `open` 变 `answered`，`teacher_id=5` |
| `reply_question` 到未授权班级提问 | `status=403` |
| `update_wrong_question(5, wq=1)` | `status=200`，`kp_list` 同步重建为「交错级数、无穷级数敛散性」 |
| `update_wrong_question(8, wq=1)`（未授课教师） | `status=403` |
| `add_question_bank` | 返回 `verified=1, source='teacher'` |
| 知识点 → 章节 → 课程 CRUD | 全部 `200`；章节下仍有知识点时删除得 `409`；课程有下级数据时删除得 `409`（`blocking={chapters:1, kps:2, links:1}`） |
| `create_resource(is_demo=1)` | `is_demo=1`，提示语「已新增资源（演示数据，非真实校方资源）」 |
| `create_resource(file_path='C:/windows/...')` | `400`「file_path 必须是 /uploads/ 下的站内路径」 |
| `create_resource` 无文件也无外链 | `400` |
| `list_resources(kp_name='无穷级数')` | 命中演示资源，返回 `demo_label='演示数据（非真实校方资源）'` |
| `import_resources(is_demo=0)` | 3 条里 2 条成功 1 条失败（标题为空），`is_demo=0` |
| `recommend_for_student(3)` | 依据真实薄弱点返回资源，`matched_points` 由真实字符串匹配算出 |
| `resources_for_class(1)` | 返回班级薄弱点、命中资源、以及**未被覆盖的薄弱点** |
| `delete_resource` | 软删除后不再出现在检索结果 |
| `create_user` / `update_user` | 角色 `student→teacher` 生效；非法角色 `superadmin` → `400`；密码过短 → `400` |
| 管理员冻结/降级自己 | 均 `400`（「不能冻结自己的账号」/「不能修改自己的管理员角色」） |
| 最后一名管理员降级/冻结 | 均 `400`（「系统必须保留至少一名未冻结的管理员」） |
| `add_class_students` 重复提交 | `added=0`（`INSERT IGNORE`） |
| `add_teacher_course` 重复 | `409`；把学生绑为授课教师 → `400` |
| 授权生效/失效 | 新建 `teacher_courses` 后 `can_access_class` 立即为真；删除后立即为假 |
| 题库 `verified 0→1` | `created_by` 被改写为审核人（管理员 ID `7`） |
| `school_stats()` | `scope='school'`，含真实角色分布、错题总数、知识点 TOP、资源下载量、练习平均分 |
| `school_stats(scope_teacher_id=5)` | `scope='teacher'`，用户数 4 < 全校 8 |
| 操作日志 | 21 条管理动作被主动写入（`user_create`/`user_update`/`class_add_students`/`teacher_course_add`/`question_create`/`question_update`/`question_delete`/`settings_update`/`backup_create`） |
| `update_settings({'ai_api_key': ...})` | `403`，`code=SENSITIVE_SETTING_REJECTED` |
| `update_settings({'db_password': ...})` | `403` |
| 混合提交（合法 + 敏感） | 合法项写入、敏感项被拒（`rejected_keys=['ai_api_key']`） |
| `system_settings` 表实际内容 | 只有 `ai_model_display`、`max_practice_count`，**没有**任何敏感键 |
| 参数变更日志 `detail` | `更新系统参数：ai_model_display`（只有键名，不含值，不含 `sk-`） |
| `check_mysqldump()` | `available=True`，`mysqldump Ver 8.0.39 for Win64 on x86_64` |
| `sso_config()` | `implemented=false`，`message` 明确写「尚未实现，请勿当作可用的登录入口」 |

### 4.3 HTTP 层权限验证（62 条断言，全部使用 `app.test_client()` + 预置 session）

```
断言通过 62/62
```

**核心权限用例的真实状态码：**

```
GET    /api/teacher/students?class_id=2（未授权班级）        -> 403  {"code":"FORBIDDEN","message":"该班级不在你的授课范围内"}
GET    /api/teacher/class-report?class_id=2（未授权班级）    -> 403  {"code":"FORBIDDEN","message":"该班级不在你的授课范围内，无法查看学情"}
GET    /api/teacher/student-report?student_id=2（不在其班级）-> 403  {"code":"FORBIDDEN","message":"该学生不在你的授课班级中，无法查看其学情"}
POST   /api/teacher/tasks（未授权班级）                      -> 403  {"message":"该班级不在你的授课范围内，无法发布任务"}
POST   /api/teacher/notices（未授权班级）                    -> 403  {"message":"该班级不在你的授课范围内，无法发布通知"}
GET    /api/teacher/class-report（完全未授课教师 client）    -> 403
GET    /api/teacher/students（完全未授课教师 client）        -> 403
GET    /api/resources/for-class（完全未授课教师）            -> 403
PATCH  /api/teacher/wrong-questions/1（未授课教师）          -> 403  {"message":"该错题不属于你的授课班级，无法修改"}
PATCH  /api/teacher/wrong-questions/1（已授权教师）          -> 200  {"message":"标注已更新"}

GET    /api/admin/users                学生 -> 403
GET    /api/admin/classes              学生 -> 403
GET    /api/admin/teacher-courses      学生 -> 403
GET    /api/admin/logs                 学生 -> 403
GET    /api/admin/settings             学生 -> 403
GET    /api/admin/stats                学生 -> 403
GET    /api/admin/backups              学生 -> 403
GET    /api/admin/sso-config           学生 -> 403
POST   /api/admin/users                学生 -> 403
POST   /api/admin/backup               学生 -> 403
PATCH  /api/admin/settings             学生 -> 403
（以上 11 条响应体均为 {"code":"FORBIDDEN","message":"当前角色无权访问该功能"}）

GET /api/teacher/classes   未登录 -> 401
GET /api/admin/users       未登录 -> 401
GET /api/resources         未登录 -> 401
```

**统计范围隔离：**

```
GET /api/admin/stats（教师 client）  -> 200 scope=teacher users.total=4
GET /api/admin/stats（管理员 client）-> 200 scope=school  users.total=8
断言：教师范围用户数严格小于全校用户数  -> PASS（4 vs 8）
```

**系统参数敏感键（重点项）：**

```
GET   /api/admin/settings -> 200
      {"blocked_keys":[], "data":[{"setting_key":"ai_model_display",...},
       {"setting_key":"max_practice_count",...}],
       "notice":"模型密钥与数据库密码不在此接口的读写范围内，请直接修改服务器上的 .env 文件"}
PATCH /api/admin/settings {"settings":{"ai_api_key":"sk-must-be-rejected"}}
      -> 403 {"code":"SENSITIVE_SETTING_REJECTED",
              "message":"这些参数属于敏感配置（模型密钥 / 数据库密码等），不允许通过接口读写：ai_api_key",
              "rejected_keys":["ai_api_key"]}
PATCH /api/admin/settings {"settings":{"db_password":"p@ssw0rd"}}   -> 403 同上
PATCH /api/admin/settings {"settings":{"AI_SECRET_TOKEN":"abc"}}    -> 403 同上
PATCH /api/admin/settings {"settings":{"ai_model_display":"agnes-2.5-flash","max_practice_count":"30"}}
      -> 200 {"updated_keys":["ai_model_display","max_practice_count"]}
```

**管理端其它真实用例：**

```
GET   /api/admin/users -> 200 total=8，响应体中不含 password 字段（断言用整串 JSON 检查）
PATCH /api/admin/users/7（冻结自己）  -> 400 "不能冻结自己的账号"
PATCH /api/admin/users/7（降级自己）  -> 400 "不能修改自己的管理员角色"
PATCH /api/admin/users/5（非法角色）  -> 400 "角色只能是 student/teacher/admin"
POST  /api/admin/questions            -> 200 question_id=25
PATCH /api/admin/questions/25 verified=1 -> 200
DELETE /api/admin/questions/25        -> 200 已下架
POST  /api/resources（学生）          -> 403
POST  /api/courses（学生）            -> 403
POST  /api/courses（教师）            -> 403（仅管理员可建课程）
GET   /api/admin/course-tree          -> 200 courses=1 chapters=1 kps=2
POST  /api/resources/import           -> 200 created_count=1 is_demo=0
GET   /api/admin/sso-config           -> 200 implemented=false
```

### 4.4 数据库备份（真实执行，成功）

```
POST /api/admin/backup -> 200
{"backup_id":1,
 "file_name":"IntelliLearn_test_20261006_091258.sql",
 "file_path":"E:\\IntelliLearn\\backups\\IntelliLearn_test_20261006_091258.sql",
 "file_size":129941,
 "message":"备份完成：IntelliLearn_test_20261006_091258.sql"}
```

对生成文件的真实校验：

```
文件大小 : 129941 字节
首行     : -- MySQL dump 10.13  Distrib 8.0.39, for Win64 (x86_64)
           -- Host: 127.0.0.1    Database: IntelliLearn_test
           -- Server version	8.0.39
CREATE TABLE 语句数 : 27
INSERT INTO `users` 语句数 : 1
```

**密码传递方式**（`backend/services/admin_service.py:create_backup`）：

```python
command = [dump_path, f'--host={...}', f'--port={...}', f'--user={...}',
           '--single-transaction', '--default-character-set=utf8mb4',
           '--routines', '--events', '--result-file=' + file_path, Config.DB_NAME]
env = dict(os.environ)
env['MYSQL_PWD'] = Config.DB_PASSWORD     # 只走环境变量
subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
```

命令行里只有 host/port/user/库名，**没有 `--password`、没有明文密码**。
`mysqldump` 返回非零退出码时会删除半成品文件、写 `backup_failed` 日志并返回 500。

### 4.5 页面模板与静态资源渲染

```
admin    GET /admin      -> 200 len=20862 leftover_jinja=0
admin    GET /teacher    -> 200 len=14958 leftover_jinja=0
admin    GET /resources  -> 200 len=11945 leftover_jinja=0
teacher  GET /teacher    -> 200 len=14830 leftover_jinja=0
teacher  GET /resources  -> 200 len=10409 leftover_jinja=0
student  GET /resources  -> 200 len=5503  leftover_jinja=0
student  GET /admin      -> 302 location=/home     （页面路由的角色限制生效）
student  GET /teacher    -> 302 location=/home

GET /static/css/teacher.css     -> 200 text/css
GET /static/css/resources.css   -> 200 text/css
GET /static/css/admin.css       -> 200 text/css
GET /static/js/teacher.js       -> 200 text/javascript
GET /static/js/resources.js     -> 200 text/javascript
GET /static/js/admin.js         -> 200 text/javascript
GET /static/js/render.js        -> 200 text/javascript
```

`leftover_jinja=0` 表示模板中不存在未渲染的 `{{ }}` / `{% %}`。

### 4.6 前端调用与后端路由一致性

用正则抽出三个 JS 中全部 `api(...)` 调用点（含 `API + '...'` 拼接形式）共 **48 处**，
逐个与 `app.url_map` 匹配。所有"未匹配"项都是我的正则把 `+ id` 截断后的产物
（例如 `/api/teacher/tasks/` 实际是 `/api/teacher/tasks/1/submissions`），
这些完整形态已用真实请求验证：

```
GET    /api/teacher/tasks                      -> 200
GET    /api/teacher/questions                  -> 200
PATCH  /api/admin/users/6                      -> 200 用户已更新
DELETE /api/admin/teacher-courses/999999       -> 404 授课关系不存在
DELETE /api/admin/classes/999999/students/2    -> 404 该学生不在此班级中
PATCH  /api/admin/questions/999999             -> 404 题目不存在
PATCH  /api/courses/999999                     -> 404 课程不存在
DELETE /api/knowledge-points/999999            -> 404 知识点不存在
GET    /api/resources/999999                   -> 404 资源不存在
```

（不存在时统一返回结构化 404 而不是 500，前端可以安全 `response.json()`。）

### 4.7 JS 语法检查

```
node --check static/js/teacher.js    -> SYNTAX OK
node --check static/js/resources.js  -> SYNTAX OK
node --check static/js/admin.js      -> SYNTAX OK
```

### 4.8 验证过程中真正发现并修掉的 3 个缺陷

| 缺陷 | 现象 | 修复 |
| --- | --- | --- |
| `task_submissions` 状态映射不完整 | 学生尚未开始时 `task_submissions.status` 是 `pending`，前端 `TASK_STATUS_LABELS` 里没有 `not_started` 的映射路径，会出现"状态为空" | 明确区分 `done` / `pending`（已布置未完成）/ `not_started`（完全无记录），label 三态齐全 |
| 错误类型百分比分母错误 | 分母用了"全部错题数"，未标注 `error_type` 的错题会把各项占比摊薄（实测合计只有 71.4%），看起来像统计错误 | 分母改为"已标注错误类型的错题数"，保证合计 100%（`student_report` 与 `class_report` 都已修正） |
| 测试脚本对"最后一名管理员"的构造有误 | 先把唯一管理员降级，再断言"不能降级最后一名管理员"，断言本身不成立 | 改为插入第二名管理员 → 正常降级（允许）→ 使目标成为唯一管理员 → 降级/冻结均被拒（400） |

---

## 5. 数据库临时夹具清单（**验收后需要清理**）

原始库中：`users` 5 行（全部 student）、其余业务表均为 0 行（`wrong_questions` 有 10 条历史数据）。
以下为我新增/修改的内容。

### 5.1 新增行

| 表 | id | 名称 / 内容 | 说明 |
| --- | --- | --- | --- |
| `courses` | 1 | `测试课程-勿用`（code `TEST-0001`, major `高数`） | 主测试课程 |
| `chapters` | 1 | `测试章节-勿用`（course_id=1） | 主测试章节 |
| `knowledge_points` | 1 | `无穷级数敛散性`（course_id=1, chapter_id=1） | 测试知识点 A |
| `knowledge_points` | 2 | `曲线积分与格林公式`（course_id=1, chapter_id=1） | 测试知识点 B |
| `classes` | 1 | `测试班级-勿用` | 已授权班级 |
| `classes` | 2 | `测试班级二-勿用（未授权）` | 用于 403 验证 |
| `users` | 7 | `admin_test`（role=admin，密码 `Admin@2026test`） | 测试管理员 |
| `users` | 8 | `teacher_noclass`（role=teacher，密码 `Teacher@2026test`） | 无任何授课关系，用于 403 验证 |
| `users` | 11 | `f25019999`（role 已被测试改为 teacher，密码 `TestPass@2026`） | 用户 CRUD 验证 |
| `teacher_courses` | 1 | teacher_id=5 / course_id=1 / class_id=1 / term `2025-2026-1` | 教师授权来源 |
| `class_students` | 1 | class_id=1, user_id=3 | 班级 1 成员 |
| `class_students` | 2 | class_id=1, user_id=4 | 班级 1 成员 |
| `class_students` | 3 | class_id=1, user_id=5 | 班级 1 成员 |
| `class_students` | 4 | class_id=1, user_id=6 | 班级 1 成员 |
| `class_students` | 5 | class_id=2, user_id=2 | 未授权班级成员 |
| `qa_questions` | 1 | `测试提问-授权班`（student 3 / class 1，现为 answered） | 答疑验证 |
| `qa_questions` | 2 | `测试提问-未授权班`（student 2 / class 2，open） | 403 验证 |
| `learning_tasks` | 7, 10, 12, 14 | `测试复习任务-勿用` | 多轮验证重复产生，可整批删除 |
| `learning_tasks` | 8, 11, 13, 15 | `【错题讲解通知】第 8 周错题讲解` | 同上 |
| `task_submissions` | 22–25, 31–34, 38–41, 45–48 | 上述任务的逐人记录 | 随任务一起删除 |
| `qa_replies` | 4, 5, 6, 7 | 教师 5 对提问 1 的回复 | 多轮验证重复产生 |
| `question_bank` | 23, 34, 37, 40 | `测试题-勿用：…`（source=teacher, verified=1, created_by=5） | 教师入库验证 |
| `question_bank` | 24, 25, 35, 36, 38, 39, 41, 42 | `测试题-勿用…`（status=0 已下架） | 管理端题库验证 |
| `resources` | 10, 14, 18, 22 | `演示课件-勿用：无穷级数敛散性讲义`（is_demo=1, status=0） | **唯一允许的演示数据**，已明确标注 |
| `resources` | 11, 15, 19, 23 | `测试真实资源-勿用A`（is_demo=0） | 批量导入验证 |
| `resources` | 12, 16, 20, 24 | `测试真实资源-勿用B`（is_demo=0） | 批量导入验证 |
| `resources` | 13, 17, 21, 25 | `测试导入-勿用C`（is_demo=0） | 批量导入验证 |
| `system_settings` | — | `ai_model_display` = `agnes-2.5-flash`；`max_practice_count` = `30` | 参数读写验证 |
| `backup_records` | 1–4 | `IntelliLearn_test_2026*.sql` | 4 次真实备份记录 |
| `operation_logs` | 16–90 | 全部为本次管理员测试动作（user_id=7） | 可整表清空 |

### 5.2 修改过的既有行（需还原）

| 表 | id | 原值 | 现值 |
| --- | --- | --- | --- |
| `users` | 5（`f25016699`） | role = `student` | role = `teacher` ← **测试后需改回 student** |
| `users` | 5 | college = `信息科学与技术` | `信息科学与技术`（已还原，仅历史上有过一次写入） |
| `wrong_questions` | 1–11 | `course_id=NULL, error_type='', knowledge_points=''` | `course_id=1`，`error_type` 已填（`计算错误`/`公式使用错误`/`方法选择不当`），`knowledge_points` 已填，`mastery` 按 id%3 赋值 |
| `wrong_question_kps` | 6–14、44、45 | 不存在 | 为上述错题补的知识点关联（`无穷级数敛散性` / `曲线积分与格林公式` / `交错级数`） |

> 错题上的 `course_id` / `error_type` / `knowledge_points` / `mastery` 是**为了让学生报告和班级报表有真实聚合数据**而填的；
> 如果验收后要恢复"干净的原始状态"，把这 11 行的这几个字段置回
> `course_id=NULL, error_type='', knowledge_points='', mastery=0`，
> 并删除 `wrong_question_kps` 中 id 6–14、44、45 即可（**不要动 `模块七测试夹具` 相关的行**，那是另一个模块的数据）。

### 5.3 备份文件（磁盘）

`E:\IntelliLearn\backups\` 下由本次产生：

- `IntelliLearn_test_20261006_091258.sql`（129941 字节）
- 后续几轮验证另生成 3 个 `IntelliLearn_test_2026*.sql`（178011 / 189592 / 202578 字节）

---

## 6. 没有验证 / 无法验证的部分（如实说明）

1. **没有在真实浏览器中打开过页面。** 端口 5000 预留给集成测试，我全程未启动 Flask 服务。
   页面验证方式是 Flask `test_client()`：三种角色分别请求 `/teacher`、`/resources`、`/admin`，
   均为 `200` 且无未渲染的 Jinja 片段；JS 只做了 `node --check` 语法检查 +
   前端调用点与后端路由的静态一致性比对。**DOM 交互、SVG 图表的实际观感未经浏览器验证。**
2. **`/resources` 缺少入口链接。** 现有 `templates/home.html`、`errors_register.html` 等页面的左侧导航里没有"知识库与资源"入口，
   而我不在允许修改的文件清单内，因此学生/教师目前只能通过直接输入 `/resources` 访问。
   **建议 lead agent 在 `home.html` 等页面的 `lf_nav` 中补一个 `<a href="/resources">` 链接**（一行改动）。
3. **演示资源仅覆盖"检索 → 标注 → 软删除"链路。** UI 上的"获取文件"按钮指向的
   `/uploads/problems/does-not-exist-demo.txt` 是我写的占位路径，**文件并不存在**，
   点击会 404（这是刻意的：项目里没有真实课件，我不会伪造文件内容）。
   下载计数接口本身已验证真实自增。
4. **`mysqldump` 备份只在 Windows 本机验证。** 已验证完整 dump 成功且文件含 27 条 `CREATE TABLE`；
   未验证磁盘写满、并发备份、`backups\` 目录权限不足等异常场景（代码里有失败清理与 `backup_failed` 日志，但未构造该场景）。
5. **SSO 只做配置探测，未做任何登录流程**（按需求要求）。`GET /api/admin/sso-config` 返回
   `implemented=false`，界面也用 `warn-box` 明确写了"尚未实现，请勿当作可用的登录入口"。
6. **`learning_tasks.paper_id` 关联的 `practice_papers` 由练习模块写入。** 我读取了
   `practice_records` / `practice_papers` 做统计（学生 3 的真实练习记录被正确统计到
   `times=1, avg_score=16.7`），但**没有测试"发布任务并关联真实试卷 → 学生完成 → 成绩回写"**这条跨模块链路，
   因为它依赖另一个模块的实现。
7. **`/api/admin/stats` 对教师的策略选择**：教师调用返回 `200` + 自己授权范围的数据
   （`scope='teacher'`），而不是 `403`。这是我在代码注释和响应字段里**显式声明**的策略，
   管理员得到 `scope='school'`。已用真实请求验证两者用户数不同（4 vs 8）。
8. **并发写入干扰**：验证期间模块七持续向 `wrong_questions` 写入数据，导致"全班错题总数"
   从 10 变成 14。我已把相关断言改为与数据库实时聚合交叉校验，
   最终 62/62 + 62/62 全通过；但如果验收时数据库还在变化，请以"接口返回值 == 数据库实时值"为准，而不要用固定数字。

---

## 7. 安全约定自查

| 要求 | 实现位置 |
| --- | --- |
| 不信任客户端 id | 教师端全部读写都先跑 `teacher_service.can_access_class / can_access_student / can_access_course / can_access_wrong_question`，这些函数只做 SQL 关联查询 |
| 隐藏按钮不等于权限 | `admin.html`/`admin.js` 只隐藏不能做的操作；服务端 `@role_required` + 服务层 SQL 校验独立生效，并已用学生/未授课教师的真实 403 验证 |
| 角色白名单 | `admin_service.ALLOWED_ROLES = ('student','teacher','admin')`，`superadmin` 实测返回 400 |
| 自锁与最后管理员保护 | `update_user()` 中三道判断，实测 4 条断言全通过 |
| 动态列名 | `WRONG_QUESTION_UPDATABLE`、`RESOURCE_WRITABLE`、`COURSE_WRITABLE`、`CHAPTER_WRITABLE`、`KP_WRITABLE`、`USER_WRITABLE`、`QUESTION_WRITABLE` 全部白名单化 |
| SQL 注入 | 所有值绑定使用 `%s`；唯一的 f-string 只拼接白名单列名与固定片段 |
| 敏感参数 | `is_sensitive_key()` 命中 `key/secret/password/passwd/token/pwd` 即拒绝；`list_settings()` 跳过敏感键并在 `blocked_keys` 中回报名单 |
| 密码不入日志 | `write_log()` 会先扫描 `detail`，命中敏感词就替换为 `[detail 含敏感键名，已省略]`；`update_settings` 只记录键名不记录值；实测日志中无 `sk-` |
| 备份密码 | 只走 `MYSQL_PWD` 环境变量，实测命令行不含 `--password` |
| 响应不含密码 | `list_users` / `get_user` / `create_user` 的 SELECT 与返回体都不含 `password` 列，实测断言通过 |
| 演示数据不冒充真实资料 | 演示资源必须显式 `is_demo=1`，接口返回 `demo_label`，前端渲染 `badge.demo`「演示数据（非真实校方资源）」，管理端统计页另有 `warn-box` 提示 |

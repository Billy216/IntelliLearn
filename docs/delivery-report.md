# 本次开发交付说明（阶段一 ~ 阶段五）

开发日期：2026-10-06
基线：Git 分支 `dev`，提交 `8c033b9`（工作区干净，未覆盖任何未提交成果）
审查报告：`docs/review-and-plan.md`

---

## 一、本轮完成情况总览

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 一 | 项目审查（结构 / 后端 / 前端 / 数据库 / AI / 权限实测） | 已完成 |
| 二 | 现状清单与分阶段计划（`docs/review-and-plan.md`） | 已完成 |
| 三 | 安全加固、AI 识题与作答分析、公式渲染、会话与错题本、数据库迁移 v1 | 已完成 |
| 三 | 模块五 知识库与学习资源 | 已完成（`docs/module-teacher-admin.md`） |
| 三 | 模块七 个性化练习与复习卷（服务端判分） | 已完成（`docs/module-practice.md`） |
| 三 | 模块八 教师端与师生互动、模块九 学情分析报表、模块十 系统管理端 | 已完成（`docs/module-teacher-admin.md`） |
| 四 | 集成冒烟测试（127 项）+ 前端渲染单元测试（27 项）+ 跨模块集成验证 | 已完成（见第四节） |
| 五 | 交付文档（本文件 + README + 各模块报告） | 已完成 |

---

## 二、本轮修改的文件清单

### 新增（后端）

| 文件 | 说明 |
| --- | --- |
| `backend/utils/__init__.py` | 工具包 |
| `backend/utils/responses.py` | 统一响应结构 `ok()/fail()` 与错误码 |
| `backend/utils/security.py` | `login_required` / `role_required`、角色常量、会话判定 |
| `backend/utils/validators.py` | 密码策略、学号格式、图片魔数/体积校验、路径归属校验 |
| `backend/utils/logging_config.py` | 统一日志（控制台 + `logs/app.log` 轮转） |
| `backend/utils/rate_limit.py` | 登录失败限流（进程内，可替换为 Redis） |
| `backend/services/study_service.py` | 错题本检索/统计/知识点聚合 |
| `backend/routes/wrong_questions.py` | 错题本接口（列表/统计/新增/详情/修改/复习/删除） |

### 新增（数据库与文档）

| 文件 | 说明 |
| --- | --- |
| `database/migrations/001_schema_extensions.sql` | 迁移 001：扩展 6 张既有表 + 新增 21 张表 |
| `database/migrate.py` | 版本化迁移工具（`--status / --dry-run / --backup`） |
| `database/schema_snapshot_2026-09-08.sql` | 迁移后结构说明（可执行快照见 `backups/`） |
| `requirements.txt` | 依赖清单（原项目缺失） |
| `README.md` | 启动、迁移、环境变量、安全说明 |
| `tests/smoke_test.py` | 后端集成冒烟测试 |
| `tests/render_test.js` | 前端渲染器单元测试（含 XSS 与公式降级） |
| `docs/review-and-plan.md` | 审查报告与开发计划 |

### 新增（前端）

| 文件 | 说明 |
| --- | --- |
| `static/js/render.js` | 共享渲染器：Markdown + KaTeX，KaTeX 不可用时降级 |
| `static/css/render.css` | 富文本、公式、折叠面板、标签样式 |
| `static/css/chat-ui.css` | 答疑页新增组件样式 |
| `static/css/errors-book.css` | 错题本新增组件样式 |

### 修改（后端）

| 文件 | 主要改动 |
| --- | --- |
| `config.py` | 会话安全、上传限制、超时、上下文长度、密码策略、`validate_secret_key` |
| `app.py` | 移除硬编码 `debug=True`，改为读配置 |
| `backend/__init__.py` | 应用工厂：日志、统一错误处理（API 一律 JSON）、安全响应头、上传目录、历史图片兼容路由、蓝图注册 |
| `backend/extensions/database.py` | 修正废弃参数 `passwd`→`password`，新增连接/游标上下文管理器 |
| `backend/services/ai_service.py` | **修复目录穿越与 SSRF**；新增 `analyze_question`（识别+作答分析）、`build_answer_messages`（LaTeX 提示词）、会话语义上下文、会话软删除/重命名、错题扩展字段、公开 `parse_json_object` |
| `backend/services/user_service.py` | 注册与改密统一密码策略；改密校验原密码；登录限流与冻结账号校验；账号不存在不再泄露"未注册"；资料读取与更新 |
| `backend/services/file_service.py` | 魔数校验、体积校验、唯一文件名、删除限定在 uploads 内 |
| `backend/routes/auth.py` | 统一响应、登录成功重置会话、改密必须原密码、未登录返回 401 JSON |
| `backend/routes/upload.py` | `login_required`、真实类型校验、先更新数据库再删旧文件 |
| `backend/routes/chat.py` | 全新对话流程（阶段事件、分析结果、降级纯文本）、会话重命名/删除、试卷提示词改为 LaTeX |
| `backend/routes/page.py` | 统一模板上下文、`/practice`、`/resources`、`/teacher`、`/admin` 路由与角色校验 |
| `backend/routes/user.py` | 个人中心展示真实角色/学院/邮箱 |

### 修改（前端）

| 文件 | 主要改动 |
| --- | --- |
| `templates/chat.html` | **删除 4 条写死的假历史会话**；新增 KaTeX、搜索框、功能入口、角色入口、公式降级提示 |
| `static/js/chat.js` | 全量重写：真实会话列表/切换/重命名/删除、阶段提示、识别结果折叠面板、失败重试、系统提示与 AI 内容区分 |
| `templates/errors_register.html` | **删除 11 个与后端不符的假学科标签与"共 49 道题目"**；新增搜索、筛选、分页、编辑与删除 |
| `static/js/errors_register.js` | **删除 50 条伪造错题数据与假分页**；改为服务端查询与真实错误提示 |
| `templates/exam.html` | 项目名改为 IntelliLearn、接入渲染器 |
| `static/js/exam.js` | 公式改由共享渲染器处理（不再自带上标转换），避免 LaTeX 源码直接展示 |
| `templates/password.html` | 新增原密码输入框；学号改为会话回填只读 |
| `static/js/password.js` | 提交原密码；401 时引导重新登录 |
| `templates/home.html` | 修正项目名；新增练习/资源/教师端/管理端入口 |
| `templates/user.html` | 角色、学院、邮箱改为真实数据 |
| `templates/intellilearn.html` | 修正不实描述（百度OCR、识别准确率≥90%、语音答疑）；新增"功能现状说明"与登录入口 |
| `.env.example` / `.gitignore` | 补齐新增配置项；忽略 `logs/`、`backups/`、临时脚本 |

### 跨模块集成修复（本轮由我在子模块代码上发现并修复）

子模块（练习 / 教师端 / 管理端 / 资源）由并行开发完成，集成时我实测发现并修复了以下问题：

| 问题 | 影响 | 修复 |
| --- | --- | --- |
| **选项正文重复标签**：`question_bank`/`practice_items` 里 `label='A'` 而 `text='A. 存在…'` | 页面显示成"A. A. 存在…"；把该题写进错题本后再解析时选项识别失败，**选择题被误判为解答题、无法自动判分** | `practice_service._normalize_options` 新增 `_strip_option_label`，统一剥离与标签重复的前缀 |
| **已污染的历史数据**：题干中已存成 `A. A. …` | 即使修好写入端，旧数据仍解析不出选项（实测 4 道题全部降级为解答题，判分只覆盖 2/6） | `_split_options` / `split_question_and_options` 新增 `_collapse_doubled_option_labels`，解析前折叠重复标签（幂等、不误伤 "Alternatively" 之类正文） |
| **新模块页面缺公式渲染**：`practice/teacher/admin/resources.html` 只引了 `render.js`，未引 KaTeX 与 `render.css` | 这些页面上的公式只能走纯文本降级，与管理端/教师端的 LaTeX 输出不匹配 | 4 个模板补齐 KaTeX（CDN）与 `render.css`；`errors_register.html` 补齐 `render.css` |
| **练习模块自述与实现不一致** | 其文档称"render.js 当前没有引入 KaTeX"，实际 render.js 支持 KaTeX，缺的是模板引入 | 已按上面的方式修正模板，文档描述的差异不复存在 |

**修复后端到端实测**（学生 `f25016698`，从错题组卷）：

```
修复前：qtypes = ['essay','essay','essay','essay','choice','choice']，判分覆盖 2/6
修复后：qtypes = ['choice','choice','choice','choice','choice','choice']，判分覆盖 6/6

全对提交 → graded=6/6 correct=6 score=100.0 accuracy=100.0
错一半   → graded=4/4 correct=2 score=50.0
判分全部在服务端完成；提交前接口不下发 answer/analysis，提交后才返回 review.correct_answer/analysis
```

### 未删除但已确认无用的文件（受当前环境权限限制无法删除，建议手动清理）

| 文件 | 说明 |
| --- | --- |
| `static/js/home.js` | `home.html` 未引用任何 JS，该文件操作的 `photoPreview`/`image`/`uploadBtn` 元素在页面中并不存在，属早期版本遗留死代码 |
| `.tmp_module_fixtures.py`、`.tmp_verify_services.py` | 子模块开发期的临时验证脚本，已加入 `.gitignore` |

---

## 三、数据库结构变更

通过 `database/migrations/001_schema_extensions.sql` 执行，全部为**非破坏性**操作：

- **扩展 6 张既有表**（`users` 角色枚举新增 `admin`；`wrong_questions` 新增 13 个字段；
  `chat_conversations` 新增软删除与学科；`chat_messages` 内容放宽为 `MEDIUMTEXT` 并新增降级文本与结构化元信息）；
- **新增 21 张表**：班级/课程/章节/知识点/授课关系、错题知识点关联、题库、练习卷与作答、
  复习任务与提交、师生答疑、学习资源、操作日志、系统参数、备份记录、迁移版本记录。

执行与回滚方式：

```bash
python database/migrate.py --status     # 查看状态
python database/migrate.py --backup     # 先备份再迁移
python database/migrate.py --dry-run    # 演练
```

迁移前备份：`backups/IntelliLearn_test_20261006_090351.sql`（82,969 字节，mysqldump 全量）。
迁移后结构快照：`backups/schema_snapshot_after_migration001.sql`（27 张表）。

**数据完整性核对**（迁移前后对比）：`users` 5 / `chat_conversations` 8 / `chat_messages` 24 /
`ai_memories` 8 / `wrong_questions` 10 / `exam_papers` 2 —— 既有业务数据零丢失。

> 说明：`users` 由 3 条变为 5 条，是本轮为测试注册链路新增的测试账号
> `f25016698`、`f25016699`（密码均为 `TestPass123!`），可随时删除：
> `DELETE FROM users WHERE user_no IN ('f25016698','f25016699');`

---

## 四、测试结果

### 4.1 后端集成冒烟测试（`tests/smoke_test.py`）

```
python tests/smoke_test.py --live
通过 52 项，失败 0 项，跳过 1 项

# 追加新增模块鉴权、按角色渲染、静态资源完整性用例后（不含 --live 的 AI 用例）：
通过 127 项，失败 0 项，跳过 1 项
```

覆盖：

| 分组 | 覆盖内容 |
| --- | --- |
| 页面与鉴权 | 13 个页面的未登录拦截（含新增 `/practice`、`/resources`、`/teacher`、`/admin`） |
| 接口鉴权 | 5 个接口未登录返回 401；改密未登录返回 401 **JSON**（修复前是 302 HTML）；AI 接口 401 |
| 统一错误返回 | 未知接口 JSON 404；方法不允许 405 |
| 注册校验 | 账号格式非法、弱密码、密码过短、账号为空均返回 400 |
| 错题本 | 新增 / 非法学科拒绝 / 关键词搜索 / 详情含知识点 / 修改掌握度 / 非法掌握度 400 / 复习记录 / 统计结构 / 注入式参数安全 / 超大分页限制 / 越权 404 |
| 会话管理 | 列表、重命名、详情、不存在 404、列表无演示数据 |
| 图片校验 | 伪造图片（扩展名合法）拒绝、非图片扩展名拒绝、目录穿越拒绝、远程地址拒绝 |
| 图片保存逻辑 | 合法 PNG 保存、伪造 JPEG 拦下、同名文件生成不同存储名（不覆盖） |
| 前端静态资源 | `render.js` / `render.css` / `chat.js` / `errors_register.js` 均可访问 |
| 新增模块鉴权（按真实角色断言） | 教师可访问教师端接口；教师访问管理端接口 403 |
| **学生越权验证** | 学生访问 13 个教师端/管理端接口全部 403；POST 写接口 403；`/teacher`、`/admin` 页面被重定向 |
| **按角色渲染页面** | student / teacher / admin 三种身份分别渲染各自可见的全部页面，均 200 且无模板错误标记；越权页面被拒绝 |
| **静态资源完整性** | 扫描全部模板，验证 28 个被引用的本地静态资源全部可访问（可发现漏文件导致的静默 404） |
| AI 链路 | 真实调用成功、回答保留 LaTeX、提供无 LaTeX 降级文本、返回结构化分析、返回会话 ID |

跳过的 1 项：**「合法 PNG 上传落盘」**。原因是当前执行环境的文件系统权限不允许写入
`uploads/problems/`（`PermissionError [Errno 13]`，服务器返回 500 并已正确记录日志）。
**这项不是代码缺陷，但确实没有在真实 HTTP 链路上验证过写盘**，
已用第 8 组（直接调用保存函数、写入临时目录）验证同一套校验与命名逻辑。
在有写权限的环境下重跑 `tests/smoke_test.py` 即可完成该项。

> 说明：测试账号 `f25016699` 在开发过程中被教师端模块用作测试夹具提升为 `teacher`，
> 因此冒烟测试的鉴权断言改为**按账号真实角色动态判定**；
> 学生越权验证单独使用 `f25016698`（student）执行。

### 4.2 前端渲染器单元测试（`tests/render_test.js`）

```
node tests/render_test.js
通过 27 项，失败 0 项
```

覆盖：XSS 转义（5 种注入载荷）、Markdown（标题/列表/加粗/行内代码/表格）、
KaTeX 可用时的行内与独立公式、**KaTeX 不可用时的降级**（分式 → `(a)/(b)`、根号 → `√(2)`，
且不残留 LaTeX 命令）、服务端降级文本优先、代码块转义、流式未闭合公式容错、空值与 null 容错。

### 4.3 真实 AI 链路实测

| 测试 | 结果 |
| --- | --- |
| 文本问答 `∫₀¹x²dx` | 成功；回答含 `$...$` 与 `$$...$$` LaTeX，并提供无 LaTeX 降级文本 |
| 图片识题（真实题目照片） | 成功识别出"利用格林公式计算曲线积分"四道小题；大类 `高数`、小类 `曲线积分与曲面积分`、知识点 `格林公式/曲线积分与路径无关/偏导数计算` |
| 作答分析 | 模型正确判断图中"只有题目、没有手写作答"，并明确告知用户补充作答，未编造错因 |
| 公式渲染 | KaTeX 0.16.11（jsDelivr）与其余 CDN 实测均返回 200，浏览器端可正常加载；加载失败时自动降级 |

### 4.4 新增模块（五 / 七 / 八 / 九 / 十）集成验证

子模块自测通过后，我以**独立脚本**再次验证了关键性质（不依赖子模块自称的结论）：

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 练习卷提交前不泄露答案 | `POST /api/practice/papers` 后检查响应字段 | 题目对象只含 `qtype/question/options/kp_name/answer_source/verified`，**无 `answer`/`analysis`/`ai_comment`** |
| 服务端判分与分数算术 | 全对提交 / 错一半提交，与手算对比 | 全对 `graded=6/6 correct=6 score=100.0 accuracy=100.0`；错一半 `graded=4/4 correct=2 score=50.0` |
| 提交后才下发答案 | 提交后 `GET` 同一卷 | 返回 `review.items[].correct_answer / analysis / is_course / ai_comment` 与 `review.record` |
| AI 生成内容的可信度标记 | 错题与题库均不足时组卷 | `composition={'wrong':0,'bank':0,'ai':5}`，`notices=['5 道题为 AI 生成，未经校验，答案仅供参考']` |
| 错题回写 | `POST /api/practice/papers/<id>/wrongbook` | 真实写入 `wrong_questions`，返回 `added=4` |
| 教师端只返回授权班级 | 以教师身份 `GET /api/teacher/classes` | 返回 1 个班级并附 `scope_note="仅显示通过 teacher_courses 授权给你的班级"` |
| 教师端真实聚合 | `GET /api/teacher/tasks` | 返回真实任务的 `done_count/pending_count/rate`，与 `class_students` 关联计算 |
| 管理端全校统计 | `GET /api/admin/stats` | 真实聚合：错误类型占比、练习均分、资源分类统计；管理员 `scope=school`，教师 `scope=teacher` |
| **密钥不外泄** | `GET /api/admin/settings` + 扫描 `operation_logs` | 设置接口只返回 2 个非敏感键；日志中匹配 `password|secret|token|sk-` 的行数为 **0** |
| 敏感设置被拒绝 | `PATCH /api/admin/settings` 传 `ai_api_key`/`db_password` | 403 `SENSITIVE_SETTING_REJECTED` |
| 备份真实可恢复 | `POST /api/admin/backup` | 生成 202,578 字节的 mysqldump 文件（含 27 张表），密码仅经 `MYSQL_PWD` 传递 |
| 资源真实检索与统计 | `GET /api/resources`、`/filters`、`/stats`、`/recommend` | 返回真实课程/知识点/资源与计数；`download_count` 实测 0→1 自增 |
| 资源导入校验 | `POST /api/resources/import` 传合法与非法记录 | 合法记录创建成功并可检索；缺少 `external_url`/`file_path` 的记录被逐条拒绝并给出原因 |
| 无数据时不编造推荐 | 学生无错题时 `GET /api/resources/recommend` | 返回空数组 + `recommend_note="推荐依据是你自己错题本里的知识点与学科，没有数据时不会编造推荐"` |

### 4.5 数据完整性修复（重要）

子模块在验证"学情报表"时为制造真实聚合，修改了 **11 条既有错题记录**（`wrong_questions.id` 1–11，属于原有用户 3 和 4）
的 `course_id / knowledge_points / error_type / mastery`，并插入了对应的知识点关联。

我已在**先做完整备份**（`backups/IntelliLearn_test_20261006_091914.sql`）之后将其还原：

```
restored wrong_questions rows: 10      -- 四个字段全部置回 NULL/''/0
removed wrong_question_kps rows: 16    -- 含指向已删除错题的孤儿关联
```

还原后逐行核对：10 条记录的 `course_id=NULL`、`knowledge_points=''`、`error_type=''`、`mastery=0`，
`wrong_question_kps` 剩余 0 行 —— 与迁移 001 刚执行完时的状态一致。



### 4.6 尚未验证的部分（如实说明）

1. **浏览器端人工目视确认**：本轮没有可用的浏览器自动化环境，未在真实浏览器里点击走查。
   已用「按角色渲染页面 + 静态资源可达性 + JS 语法检查 + 渲染器单元测试（含 5 种 XSS 载荷）」
   覆盖可自动化的部分；CSS 视觉效果与 `window.print()` 的实际打印效果未经人眼确认。
2. **图片上传的完整 HTTP 落盘链路**未通过：当前执行环境的文件系统权限不允许写入
   `uploads/problems/`（`PermissionError [Errno 13]`，服务端返回 500 并正确记录日志）。
   同一套校验与命名逻辑已用第 8 组用例（写入临时目录）验证。**在有写权限的环境重跑即可补齐。**
3. **跨模块链路**「教师发布任务 → 关联练习卷 → 学生完成 → 成绩回写 `task_submissions`」
   未做端到端联调（子模块各自验证了写入逻辑，练习模块也实现了 `task_id` 非空时 upsert 提交记录）。
4. **学校统一身份认证（CAS/OAuth）** 未实现，仅预留配置读取接口。
5. **备份异常场景**（磁盘满 / 并发 / 权限不足）未构造测试。
6. 教师端 / 管理端 / 练习模块的更细粒度自测记录见
   `docs/module-teacher-admin.md`、`docs/module-practice.md`。

---

## 五、新增依赖

无新增运行时依赖。`requirements.txt` 仅为把原本缺失的依赖固化成清单，
版本与当前 `.venv` 实测一致（Flask 3.1.3、bcrypt 5.0.0、PyMySQL 1.2.0、
python-dotenv 1.2.3、requests 2.34.2）。

安装命令：

```bash
pip install -r requirements.txt
```

前端 KaTeX 通过 CDN 引入，无需 npm 或构建步骤；生产环境若无法访问外网，
可把 KaTeX 静态文件放到 `static/vendor/katex/` 并修改模板中的引用地址，
渲染器会自动使用本地副本（判断逻辑基于 `window.katex` 是否存在）。

---

## 六、环境变量

见 `README.md` 第二节与 `.env.example`。本轮新增：

`FLASK_DEBUG`、`REQUIRE_STRONG_SECRET_KEY`、`MAX_CONTENT_LENGTH`、`MAX_IMAGE_SIZE`、
`ALLOW_REMOTE_IMAGE_URL`、`SESSION_COOKIE_SECURE`、`PERMANENT_SESSION_LIFETIME`、
`LOGIN_MAX_ATTEMPTS`、`LOGIN_LOCKOUT_SECONDS`、`PASSWORD_MIN_LENGTH`、`PASSWORD_MAX_LENGTH`、
`AI_CONNECT_TIMEOUT`、`AI_READ_TIMEOUT`、`AI_STREAM_READ_TIMEOUT`、`AI_ANSWER_MAX_TOKENS`、
`AI_CONTEXT_MAX_MESSAGES`、`AI_CONTEXT_MAX_CHARS`、`LOG_LEVEL`、`ALLOWED_COLLEGE_CODES`。

> **需要你操作**：当前 `.env` 中的 `SECRET_KEY=123456` 过弱（未修改你的文件）。
> 应用启动时会打印醒目告警并使用**临时随机密钥**，重启后登录态失效。
> 请执行 `python -c "import secrets;print(secrets.token_hex(32))"` 生成强密钥填入 `.env`；
> 生产环境再设置 `REQUIRE_STRONG_SECRET_KEY=true` 以强制校验。

---

## 七、本地启动

```bash
# 1. 确认数据库结构已是最新（首次会执行迁移 001）
.venv\Scripts\python.exe database\migrate.py --status

# 2. 启动（默认 http://127.0.0.1:5000）
.venv\Scripts\python.exe app.py

# 3. 生产部署（不要用开发服务器）
pip install waitress
waitress-serve --host=127.0.0.1 --port=5000 app:app
```

登录：使用你原有的学生账号即可（例如 `f25016621`）。
本次测试创建的账号：`f25016699`（教师，用于教师端测试）、`f25016698`（学生）。

管理员账号需要手动提升（没有管理员就无法进入管理端）：

```sql
UPDATE users SET role = 'admin' WHERE user_no = '你的工号';
```

## 八、测试命令速查

```bash
# 不依赖 AI 网络
set SMOKE_TEST_USER=f25016699
set SMOKE_TEST_PASSWORD=TestPass123!
set SMOKE_TEST_STUDENT_USER=f25016698
set SMOKE_TEST_STUDENT_PASSWORD=TestPass123!
.venv\Scripts\python.exe tests\smoke_test.py

# 额外验证真实 AI 调用
.venv\Scripts\python.exe tests\smoke_test.py --live

# 前端渲染器（XSS 与公式降级）
node tests\render_test.js
```

## 九、测试数据清理

本轮开发在数据库中留下以下测试数据，可按需清理：

```sql
-- 测试账号（f25016699 已被教师端模块提升为 teacher，用于教师端测试）
DELETE FROM users WHERE user_no IN ('f25016698', 'f25016699');

-- 教师端/管理端模块创建的测试夹具（详见 docs/module-teacher-admin.md）
DELETE FROM teacher_courses WHERE teacher_id IN (SELECT id FROM users WHERE user_no LIKE 'teacher%');
DELETE FROM class_students  WHERE user_id    IN (SELECT id FROM users WHERE user_no LIKE 'f25019999');
DELETE FROM users        WHERE user_no IN ('admin_test', 'teacher_noclass', 'f25019999');
DELETE FROM class_students WHERE class_id IN (SELECT id FROM classes WHERE name LIKE '%测试%');
DELETE FROM classes      WHERE name LIKE '%测试%';
DELETE FROM courses      WHERE name LIKE '%测试%';
DELETE FROM question_bank WHERE question LIKE '%测试%' OR kp_name LIKE '%夹具%';

-- 资源与练习模块的测试数据（当前 16 条资源全部为测试夹具，名称均带「勿用」）
DELETE FROM resources WHERE title LIKE '%勿用%' OR is_demo = 1;

-- 练习模块的测试卷（user_id=6 的卷子由本轮集成验证产生）
DELETE FROM practice_answers WHERE record_id IN (SELECT id FROM practice_records WHERE user_id = 6);
DELETE FROM practice_records WHERE user_id = 6;
DELETE FROM practice_items   WHERE paper_id IN (SELECT id FROM practice_papers WHERE user_id = 6);
DELETE FROM practice_papers  WHERE user_id = 6;

-- 复习任务与答疑测试数据
DELETE FROM task_submissions WHERE task_id IN (SELECT id FROM learning_tasks WHERE title LIKE '%勿用%');
DELETE FROM learning_tasks   WHERE title LIKE '%勿用%';
DELETE FROM qa_replies    WHERE question_id IN (SELECT id FROM qa_questions WHERE title LIKE '%测试%');
DELETE FROM qa_questions  WHERE title LIKE '%测试%';

-- 本轮集成验证写入的错题（AI 生成的测试题，stem 以“设级数/计算定积分”等开头且无知识点）
-- 建议先 SELECT 确认，再删除：
--   SELECT id, LEFT(question,50), knowledge_points FROM wrong_questions WHERE knowledge_points = '';
```

> ⚠️ 执行前请先确认这些记录确实都是测试数据（尤其是 `users` 表），
> 并先执行 `python database/migrate.py --backup` 或
> `mysqldump -u root -p IntelliLearn_test > backups/before_cleanup.sql`。

---

## 十、尚未完成与下一步计划

1. **学校统一身份认证（CAS/OAuth）**：当前仅预留扩展位与配置读取接口，未实现。
2. **年级/学院/学科组级别的跨班汇总分析**：表结构（`classes.grade_year`、`courses.college` 等）已预留，
   当前只实现到班级维度。
3. **语音答疑与语音输入**：未实现（首页已明确标注"规划中"）。
4. **历史图片数据丢失**：早期数据库记录中的 `/static/uploads/xxx.png` 文件在磁盘上已不存在
   （上传目录迁移时未搬迁文件），已加兼容路由，但历史图片无法恢复。
5. **登录限流为进程内实现**：多进程部署需替换 `backend/utils/rate_limit.py`（接口不变）。
6. **试卷判分的完整性**：`/api/exam/*` 仍沿用"客户端判分 + 答案随卷下发"的既有设计
   （为避免破坏现有功能未改动）；新实现的练习模块采用**服务端判分**，
   建议后续把试卷页也迁移到该模式。
7. **前端模板继承**：9 个页面仍各自复制顶部/左侧导航（未引入 `base.html`）。
   本轮只补齐了各页面的功能入口链接，未做模板重构，建议后续单独排期。
8. **错题掌握度未自动回写**：提交练习后不会自动更新 `wrong_questions.mastery`。
9. **跨模块链路未联调**：教师发布任务 → 学生完成 → 成绩回写，见 4.6 第 3 条。
10. 建议在具备写权限的环境中补跑"图片上传完整链路"用例，并按第九节清理测试数据与临时脚本。

---

## 十一、本轮遗留的测试数据（需你决定是否清理）

| 类型 | 内容 |
| --- | --- |
| 测试账号 | `f25016698`（student）、`f25016699`（本轮创建，现为 teacher，用于教师端鉴权验证）、`admin_test`（admin）、`teacher_noclass`（teacher）、`f25019999`（teacher） |
| 教学夹具 | `courses` id=1、`chapters` id=1、`knowledge_points` id=1/2、`classes` id=1/2、`teacher_courses` id=1、若干 `class_students` |
| 资源 | `resources` 10–25（名称均带「勿用」；其中 4 条为 `is_demo=1` 且 `status=0` 的演示数据） |
| 题库/任务/答疑 | `question_bank`、`learning_tasks`、`task_submissions`、`qa_questions/qa_replies` 中的测试行 |
| 练习 | `practice_papers/items/records/answers` 中属于 user 6 的记录 |
| 运维 | `backup_records` 1–4、`operation_logs` 中的测试日志 |

以上均可通过第九节的 SQL 清理。**我没有自动删除它们**，因为它们同时也是"模块确实能跑通"的现场证据；
正式使用前建议清理，并保留 `backups/` 下的备份以便回退。

> 特别说明：`f25016699` 原为我为验证注册链路创建的学生账号，被子模块提升为 `teacher` 以便验证教师端。
> 我在集成测试中保留了该角色，因为它让"教师可访问教师端接口"这一正向路径也能被自动测试覆盖。
> 若不需要，可执行 `UPDATE users SET role='student' WHERE user_no='f25016699';` 或直接删除该账号。

# IntelliLearn 校园 AI 学业辅助系统 —— 现状审查报告与分阶段开发计划

审查日期：2026-09-08
审查方式：实际读取代码文件、实际连接数据库、实际启动应用并调用接口（非推测）
审查范围：`E:\IntelliLearn` 全部分支文件（排除 `.venv`、`.git`、`__pycache__`）

---

## 一、项目实际技术栈（以代码为准）

| 项目 | 实际情况 | 依据 |
| --- | --- | --- |
| 后端 | Flask 3.1.3，应用工厂 `create_app()`，Blueprint 分层 | `app.py`、`backend/__init__.py` |
| 前端 | 原生 HTML/CSS/JS + Jinja2 模板，**无模板继承**（无 `base.html`，每页重复导航） | `templates/*.html` |
| 数据库 | MySQL 8.0.39，PyMySQL 1.2.0，`DictCursor` | `backend/extensions/database.py` |
| 密码 | bcrypt 5.0.0（`gensalt()` 默认 cost 12） | `backend/services/user_service.py` |
| AI | `https://api.agnes-ai.cn/v1/chat/completions`，模型 `agnes-2.5-flash`，OpenAI 兼容，**支持视觉**与流式 | `config.py`、实测调用成功 |
| 会话 | Flask 内置 session（签名 Cookie），无 Flask-Login | `backend/routes/auth.py` |
| 运行 | `.venv`（Python 3.14），`python app.py` → `127.0.0.1:5000`，`debug=True` | `app.py` |
| 依赖清单 | **不存在 `requirements.txt`** | 目录扫描 |

实测确认：应用可正常启动；登录 / 注册 / 鉴权 / 数据库读写 / AI 文本调用 / AI 视觉识图 **均真实可用**（详见第五节）。

### 数据库实际结构（6 张表，全部无外键）

```
users(id, role ENUM('student','teacher'), user_no UNIQUE, password, college,
      email, real_name, status, avatar_path, created_at, updated_at)
chat_conversations(id, user_id, title, created_at, updated_at)
chat_messages(id, conversation_id, user_id, role, content, image_url, created_at)
ai_memories(id, user_id, question, answer, image_url, major, sub, created_at)   -- 每用户仅保留最近 5 条
wrong_questions(id, user_id, major, sub, question, answer, image_url, source, created_at)
exam_papers(id, user_id, major, exam_json, created_at)
```

要点：
- `users.role` 是 `ENUM('student','teacher')`，**没有管理员角色**，无法在不改表的情况下扩展管理端。
- **零外键**，全部靠应用层保证关联，`user_id` 索引已建但无引用完整性。
- 学科分类由代码硬编码：`MAJOR_CATEGORIES`（语文/高数/大物/离散/英语/py/历史/地理/政治），高数另有 12 个 `sub` 小类。
- 错题表无"知识点/错误类型/课程章节/掌握状态"字段，无法支撑错题本进阶与学情分析。

### 现有路由清单（实测均可访问）

页面：`/`、`/login`、`/register`、`/home`、`/chat`、`/exam`、`/errors_register`、`/user`、`/password`
接口：`POST /api/register`、`POST /api/login`、`GET /logout`、`POST /api/change_password`、`POST /api/upload_image`、`POST /upload_avatar`、`POST /api/chat`、`POST /api/chat/stream`(SSE)、`GET /api/conversations`、`GET /api/conversations/<id>`、`GET|POST /api/wrong_questions`、`POST /api/exam/generate`、`POST /api/exam/process`、`GET /api/exam/papers`、`GET /api/exam/papers/<id>`

---

## 二、功能现状清单（四分类）

### A. 已实现且实测通过

| 功能 | 关键文件 / 路由 | 数据表 | 实测结果 |
| --- | --- | --- | --- |
| 注册（学号/工号规则校验 + bcrypt 入库） | `user_service.register_user` / `POST /api/register` | `users` | 通过：`f25016699` 注册成功 |
| 登录 + Session 写入 | `user_service.login_user` / `POST /api/login` | `users` | 通过：Cookie 正常下发 |
| 未登录页面拦截 | `page.py`、`user.py` | — | 通过：6 个页面全部 302 → `/login` |
| 未登录接口拦截 | 各 `/api/*` | — | 通过：均 401 JSON |
| 会话数据隔离 | `conversation_belongs_to_user` | `chat_conversations` | 通过：读他人会话返回 404 |
| 头像上传与更新 | `upload.py` / `POST /upload_avatar` | `users` | 代码链路完整（含旧头像清理与回滚） |
| 题目图片上传 | `upload.py` / `POST /api/upload_image` | 磁盘 `uploads/problems` | 通过 |
| AI 识图（视觉模型） | `ai_service.call_ai` + `load_image_base64` | — | 通过：真实识别出"格林公式曲线积分"题目 |
| AI 流式回答（SSE） | `chat.py::api_chat_stream` | — | 代码链路完整（含截断续写、非流式回退） |
| 会话列表 / 历史消息落库 | `chat_conversations`、`chat_messages` | 同左 | 通过：接口返回真实数据 |
| 题目自动分类（大类 + 高数小类） | `ai_service.classify_question` | `ai_memories` | 代码链路完整 |
| 错题新增 | `POST /api/wrong_questions` | `wrong_questions` | 通过（含学科白名单校验） |
| AI 组卷 + 历史试卷回看 | `POST /api/exam/generate`、`GET /api/exam/papers/<id>` | `exam_papers` | 代码链路完整，含 JSON 容错解析 |
| 修改密码（复杂密码策略 + 强制重新登录） | `user_service.change_password` | `users` | 通过（策略校验完整） |

### B. 已实现但存在缺陷

| 缺陷 | 位置 | 影响 |
| --- | --- | --- |
| **任意文件读取（目录穿越）** | `ai_service.load_image_base64`：`os.path.join(BASE_DIR, image_url.lstrip('/'))` 未做归属校验 | 实测 `image_url=/uploads/problems/../../config.py` 成功读出 `config.py` 并 base64 编码。可读取服务器任意文件 |
| **SSRF** | 同上：`image_url` 为 `http(s)://` 时直接 `requests.get` | 客户端可让服务器请求任意内网地址 |
| **上传无大小上限** | 未设置 `MAX_CONTENT_LENGTH`；`allowed_file` 仅看扩展名 | 可上传超大文件 / 伪造扩展名文件，磁盘与内存风险 |
| **上传文件名可碰撞覆盖** | `file_service.save_file`：`int(time.time())_原名` | 同一秒内同名文件互相覆盖 |
| **改密不校验原密码** | `POST /api/change_password`、`user_service.change_password` | 只要持有有效 Session 即可静默改密；登录态被劫持即失守 |
| **注册密码策略弱于改密** | `register_user` 仅校验长度 ≥ 8，`change_password` 校验大小写+数字+特殊字符 | 前端 5 条规则形同虚设，直接 POST 可绕过 |
| **改密未登录返回 302 HTML** | `auth.py:113-114` `return redirect('/login')` | 前端 `response.json()` 抛错，显示"网络异常"，误导用户 |
| **接口错误格式不统一** | 无 404/500 错误处理器 | `/api/does_not_exist` 返回 HTML；注册失败也返回 200 |
| **对话上下文断裂** | `chat.py` 只取前端 `messages` 的最后一条，忽略同会话历史；跨会话记忆仅靠 `ai_memories` 最近 5 条 | 同一会话内追问无法真正延续上下文 |
| **会话删除缺失** | 无 `DELETE /api/conversations/<id>` | 只能新增不能删除，`chat_messages` 只增不减 |
| **错题本不可管理** | 仅 `GET`/`POST` | 无删除、无搜索、无筛选、无编辑、无详情接口 |
| **错题与练习/试卷不联动** | `exam.js` 判错后不回写错题本 | 学习闭环断裂 |
| **登出未清干净** | `auth.py::logout` 逐个 `session.pop`，漏掉 `real_name` | 残留身份信息 |
| **无登录限流** | 实测连续 10 次错误密码无任何限制 | 可暴力破解 |
| **日志用 `print`** | 全项目 | 无日志级别、无落盘、无法审计 |
| **历史图片链接全部失效** | 数据库存 `/static/uploads/xxx.png`，实际上传目录已迁移到 `/uploads/problems/`，`static/uploads` 不存在 | 历史消息图片全部 404 |
| **`user_service.get_college_info` 只认 `016` 学院** | `user_service.py:8-11` | 其他学院无法注册 |

### C. 已有部分代码但尚未完成

| 项 | 现状 | 缺口 |
| --- | --- | --- |
| 教师角色 | `users.role` 已含 `teacher`，注册按 `t` 前缀自动识别 | 无教师页面、无教师接口、无角色鉴权、无班级/课程关系 |
| 作答分析 | 提示词要求"分步骤讲解"，`POST /api/exam/process` 支持传入 `user_answer` | 主对话不识别学生手写作答；无"标准解法 vs 学生作答"差异分析；无错误类型归类 |
| 数学公式 | `clean_latex` + Unicode 上标，提示词**明令禁止 LaTeX** | 无 MathJax/KaTeX；积分、极限、矩阵、分式、求和、根号、分段函数无法正确呈现 |
| 识别结果展示 | 分类标签 + "加入错题集"按钮 | 无识别原文折叠区、无"题目/识别/解题/答案"分区、无失败重试按钮 |
| 错题小类 | `wrong_questions.sub` 已存高数小类 | 其他学科无小类；无知识点、无错误类型 |
| 试卷 | 生成、渲染、客户端判分、历史回看均可用 | 无交卷、无服务端判分、无成绩记录；**答案与解析随卷下发到浏览器**；解答题没有输入框（`user_answer` 永远传空串） |

### D. 尚未实现

模块五（本校知识库与资源检索）、模块七（个性化练习与复习卷、自动判分、导出打印）、模块八（教师端与师生互动：班级/学情报告/复习任务/答疑转交）、模块九（学情分析与可视化报表）、模块十（系统管理端：用户角色管理、课程章节知识点管理、题库资源管理、运行日志、数据备份、模型配置）**全部没有实现**，数据库中也没有对应表。

---

## 三、关键问题定位：伪造数据与"只有前端"的功能（最严重的一类）

任务书明确禁止"将静态模拟数据冒充真实业务数据"。实际存在以下**伪造数据**：

| 位置 | 问题 | 危害等级 |
| --- | --- | --- |
| `static/js/errors_register.js:5-78` | `FALLBACK_QUESTIONS`：**50 道完全编造的错题**（含编造的题目、答案、学科） | **极高**。`:186-188` 与 `:192-196`：接口返回 `success:false`（如 Session 过期、数据库连不上）或网络失败时，直接把这 50 道假题渲染成"我的错题本"，用户完全无法分辨 |
| `templates/errors_register.html:88` | 硬编码 `共 49 道题目` | 高：未加载即显示假数量；且与假数据条数（50）自相矛盾 |
| `templates/errors_register.html:71-82` | 硬编码 11 个学科标签（高等数学/线性代数/概率论/化学/生物学/经济学/管理学/法学/文学…） | 高：与后端真实分类 `MAJOR_CATEGORIES` 完全不符，JS 加载后删除重建，加载前闪现假分类 |
| `static/js/chat.js:347-360` | 会话详情加载失败时渲染 `已加载对话 ID x（演示数据…）` 及两条编造对话 | 高 |
| `templates/chat.html:41-56` | 硬编码 4 条假历史会话（"数学问题咨询""物理作业讨论"…） | 中：JS 加载后会替换，但接口失败时残留，且首屏闪现 |
| `static/js/errors_register.js:267-277` | `setTimeout(300ms)` 伪加载动画 + 前端假分页（`PAGE_SIZE=12`） | 中：伪造服务端分页 |
| `static/js/errors_register.js:415-431` | "收藏"星标（`bookmarks` Set + 图标切换） | 中：纯前端，刷新即失效，无接口无表 |
| `static/js/errors_register.js:434-438` | `console.log('📚 错题本已加载 / 共 N 道题目')` 在 Promise 完成前同步执行 | 低：控制台永远打印"共 0 道题目"的假完成提示 |
| `templates/intellilearn.html` | 宣传页承诺 ≥10 项未实现能力：`识别准确率≥90%`(L65)、`百度OCR`(L72)、`本校知识点库`(L99-101)、`班级/年级学情报告`(L184/191)、`语音答疑`(L236-243)、`教师转接`、`专属复习卷打印`(L173)、`全校报表`(L267-269) 等 | 高：其中"百度OCR"是与实际实现（多模态大模型视觉识图）**不符的技术描述** |
| `templates/home.html:6,50`、`errors_register.html:7,21`、`exam.html:6`、`chat.html` | 项目名仍为 `SAMS 学校活动管理系统`（另一个项目的名字），与 IntelliLearn 不符 | 中 |
| `templates/chat.html:13` 注释 | "与 home 一致，但去掉'返回主页'链接" —— 描述与实现不符 | 低 |

**只有前端、没有后端的功能**：错题收藏（星标）、错题"分页加载"、`intellilearn.html` 的教师端 Tab 切换（`switchTab` 仅切 class，教师端内容全是静态文案）、"重新作答"按钮（`exam.js:378-382` 仅重绘内存中的同一份试卷）。

---

## 四、其他风险与工程问题

1. **无模板继承**：9 个页面各自复制顶部导航/左侧导航，改一处要改 9 处，是后续维护最大成本。
2. **无 `requirements.txt`**、无 README、无 `.env` 校验：新成员无法复现环境；缺少 `AI_API_KEY` 时仅打印一行提示。
3. **`SECRET_KEY=123456`**（实测 `.env`）：Session 签名密钥可预测，等于可伪造任意用户登录态。`.env` 已被 `.gitignore` 忽略（正确），但密钥本身必须更换。
4. **`debug=True` 硬编码**在 `app.py`：生产环境会暴露 Werkzeug 调试器（可执行任意代码）。
5. **数据库迁移无版本管理**：仅有一个全量 `IntelliLearn_test.sql` 转储（且其中数据已落后于线上库），无迁移脚本机制。
6. **`home.js` 是死代码**：`home.html` 未引用任何 JS，`home.js` 操作的 `photoPreview`/`image`/`uploadBtn` 元素在页面中并不存在（点击即 JS 报错）。
7. **前端重复实现**：`chat.js`、`exam.js` 各自复制了一份后端的 Unicode 上标转换表；`register.js` 与 `password.js` 的密码规则与强度计算完全重复。
8. **CDN 依赖无 SRI**：`intellilearn.html` 引入 `cdn.tailwindcss.com`，`errors_register.html` 引入 Font Awesome 6.4.0；离线/校园网受限时首面样式崩坏。
9. **`errors_register.js:301-307`** 用未转义的 `subject` 拼 `innerHTML`（当前写入路径有白名单，属低危但应修）。
10. **`api_memories` 的"每用户仅保留 5 条"** 用 `DELETE ... NOT IN (SELECT ...)` 实现，逻辑正确，但会让"追问历史题目"超过 5 轮后失效。
11. **PyMySQL 参数 `passwd` 已废弃**（实测有 DeprecationWarning）。
12. **`wrong_questions.answer` 存整段 AI 长回答**（实测单条可达数 KB），与"错题解析"语义混杂，缺少"标准答案"与"AI 讲评"的区分。

---

## 五、实测记录（真实执行，非推测）

| 测试项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 应用启动 | `.venv\Scripts\python.exe app.py` | ✅ 成功监听 5000 |
| 页面可达性 | `GET /`、`/login`… | ✅ 200；受保护页 302 → `/login` |
| 接口鉴权 | 无 Cookie 请求 3 个接口 | ✅ 均 401 JSON |
| 注册 | `POST /api/register {f25016699}` | ✅ 成功入库 |
| 登录 | `POST /api/login` | ✅ 成功，Cookie 下发 |
| 数据隔离 | 用用户 A 读用户 B 的会话 2 | ✅ 404 |
| 数据库 | `SHOW TABLES` / `SHOW CREATE TABLE` | ✅ 6 表，无外键 |
| AI 文本 | `call_ai("只回复两个字：收到")` | ✅ 0.45s 返回 |
| AI 视觉 | 传入 `uploads/problems/1788863376_44639.jpg` | ✅ 正确识别为"格林公式曲线积分题，含四个小问" |
| **目录穿越** | `load_image_base64('/uploads/problems/../../config.py')` | ❌ **成功泄露 2547 字节源码** |
| 暴力破解 | 连续 10 次错误密码 | ❌ 无任何限制 |
| 接口 404 | `GET /api/does_not_exist` | ❌ 返回 HTML 而非 JSON |
| 改密未登录 | `POST /api/change_password` 无 Session | ❌ 302 到 HTML 页 |

测试副作用说明：为验证注册/登录链路，在 `users` 表新增了一个测试账号 `f25016699`（学生）。该记录可随时删除，未修改任何既有数据。

---

## 六、分阶段开发计划

### 阶段 A：安全与主链路加固（最高优先级，先做）
影响文件：`backend/__init__.py`、`backend/extensions/database.py`、`backend/routes/*.py`、`backend/services/*.py`、`config.py`、新增 `backend/utils/`
1. 统一 API 响应与错误处理（`ok()/fail()`、JSON 404/500、日志替代 `print`）。
2. 会话安全：`SESSION_COOKIE_HTTPONLY/SAMESITE`、`SECRET_KEY` 强校验、`debug` 由环境变量控制。
3. 上传安全：`MAX_CONTENT_LENGTH`、魔数校验、唯一文件名、路径归属校验。
4. **修复目录穿越与 SSRF**（`load_image_base64`）。
5. 统一密码策略（注册/改密同一套）+ 改密校验原密码 + 登录失败限流。
6. `home.js` 死代码清理、历史图片 URL 兼容路由。

### 阶段 B：AI 识题与作答分析 + 公式渲染（核心体验）
1. 重构提示词：允许并鼓励 LaTeX；输出结构化分析（题目原文、学科、知识点、错误类型、解题步骤、最终答案、作答差异、不确定性说明）。
2. 服务端同时产出 `reply`(LaTeX) 与 `reply_plain`(降级纯文本)，前端 KaTeX 渲染失败时自动降级。
3. 识别结果折叠区、学科标签、加载/失败/重试状态。

### 阶段 C：会话与错题本
1. 会话：删除（含确认）、重命名、同会话上下文连续性、上下文长度控制。
2. 错题本：删除、搜索、筛选、编辑分类、详情；**彻底移除 50 条伪造数据与全部假数量/假分类**。

### 阶段 D：个性化练习与复习卷
1. 题库表 + 练习卷表；按知识点/错题生成练习；服务端判分；练习记录；打印/导出。

### 阶段 E：教师端 / 学情分析 / 知识库 / 管理端
1. 角色鉴权（学生/教师/管理员）、班级-课程-教学关系表。
2. 教师端：班级学情、高频错题、知识点错误分布、复习任务、答疑回复。
3. 学情报表：真实数据聚合 + 图表 + 导出。
4. 知识库/资源管理与全校统计、运行日志、模型配置。

### 阶段 F：测试与交付
启动/权限/上传/AI/公式渲染/会话持久化/数据隔离/错题 CRUD/异常返回/教师端越权/迁移安全 的自动化测试；输出交付文档。

### 兼容性与风险说明
- 所有数据库变更走**版本化迁移脚本**，只做 `ADD COLUMN`/`CREATE TABLE`/`CREATE INDEX` 等非破坏性操作，迁移前自动 `mysqldump` 备份，不执行 `DROP`/`TRUNCATE`。
- 保留 `format_ai_output` 与现有接口返回字段，新增字段只增不改，保证旧前端不崩。
- 保留现有 9 个页面与全部既有接口，不删除、不改名、不改 URL。
- 不引入前端框架；公式渲染选 KaTeX（体积小、速度快）+ 纯文本降级；图表优先轻量方案，避免新增重型构建链。

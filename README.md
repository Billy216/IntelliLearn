# IntelliLearn 校园 AI 学业辅助系统

面向高校学生、教师与教学管理人员的 AI 学业辅助平台：拍照/文字提问 → AI 识题与作答分析 →
知识点与错因提炼 → 错题本与个性化复习 → 教师学情分析。

- 后端：Python 3.14 + Flask 3（Blueprint 分层：routes → services → extensions）
- 数据库：MySQL 8（PyMySQL，参数化查询，版本化迁移）
- 前端：原生 HTML/CSS/JavaScript + Jinja2 模板（无前端框架、无构建步骤）
- AI：OpenAI 兼容接口（默认 `agnes-2.5-flash`，支持多模态识图与流式输出）
- 公式渲染：KaTeX（CDN，加载失败自动降级为服务端生成的纯文本）

---

## 一、快速开始

```bash
# 1. 准备虚拟环境
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 2. 配置环境变量
copy .env.example .env            # 然后按下面「环境变量」一节填写

# 3. 初始化/升级数据库结构（首次执行会自动建表并记录版本）
python database/migrate.py --status
python database/migrate.py --backup      # 建议：先备份再迁移

# 4. 启动
python app.py                     # 默认 http://127.0.0.1:5000
```

生产部署请勿使用开发服务器：

```bash
pip install waitress
waitress-serve --host=127.0.0.1 --port=5000 app:app
```

---

## 二、环境变量（`.env`）

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 是 | 会话签名密钥。未配置或过弱时会打印告警并使用临时随机密钥（重启后登录态失效）；设 `REQUIRE_STRONG_SECRET_KEY=true` 可强制拒绝启动 |
| `FLASK_DEBUG` | 否 | 默认 `false`。**生产环境必须保持 false**（true 会开启调试器） |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | 是 | MySQL 连接信息 |
| `DB_CHARSET` | 否 | 默认 `utf8mb4` |
| `AI_API_KEY` | 是 | AI 接口密钥，仅服务端使用，绝不返回前端 |
| `AI_API_URL` / `AI_MODEL` | 否 | 覆盖默认接口地址与模型名 |
| `MAX_CONTENT_LENGTH` / `MAX_IMAGE_SIZE` | 否 | 请求体与单图大小上限（默认 8MB / 5MB） |
| `ALLOW_REMOTE_IMAGE_URL` | 否 | 默认 `false`。开启后允许 AI 读取远程图片地址，存在 SSRF 风险 |
| `SESSION_COOKIE_SECURE` | 否 | HTTPS 部署时设为 `true` |
| `PERMANENT_SESSION_LIFETIME` | 否 | 登录态有效期（秒），默认 7 天 |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_SECONDS` | 否 | 登录失败限流（默认 5 次 / 300 秒） |
| `ALLOWED_COLLEGE_CODES` | 否 | 允许注册的学院代码，逗号分隔；默认取 `user_service.COLLEGE_MAP` 的键 |

生成密钥：

```bash
python -c "import secrets;print(secrets.token_hex(32))"
```

---

## 三、数据库迁移

结构变更全部通过 `database/migrations/*.sql` 版本化管理，执行记录写入 `schema_migrations` 表。

```bash
python database/migrate.py --status     # 查看哪些已执行、哪些待执行
python database/migrate.py --dry-run    # 只打印将要执行的语句
python database/migrate.py --backup     # 先用 mysqldump 备份，再执行
python database/migrate.py              # 直接执行
```

约定：
- 迁移只允许非破坏性语句（`ADD COLUMN` / `CREATE TABLE` / `CREATE INDEX` / 放宽类型的 `MODIFY`），
  不执行 `DROP`、`TRUNCATE`、`DELETE`；
- 调整既有字段前，必须先用 `--backup` 生成完整备份；
- 备份文件默认输出到 `backups/`，还原方式：`mysql -u root -p 库名 < 备份文件`。

---

## 四、目录结构

```
app.py                    应用入口（生产请用 WSGI 服务器）
config.py                 集中配置（全部从环境变量读取）
backend/
  __init__.py             应用工厂：日志、错误处理、安全响应头、蓝图注册
  extensions/database.py  PyMySQL 连接与上下文管理器
  routes/                 路由层（只处理 HTTP）
    page.py auth.py user.py upload.py chat.py
    wrong_questions.py practice.py resources.py teacher.py admin.py
  services/               业务与数据访问层
    ai_service.py         模型调用、提示词、题目识别与作答分析
    user_service.py       注册/登录/密码/资料
    study_service.py      错题本、知识点、学情统计
    file_service.py       上传校验与文件保存
    practice_service.py   练习与复习卷（含服务端判分）
    teacher_service.py    教师端学情、任务、答疑
    resource_service.py   课程/章节/知识点/资源
    admin_service.py      用户、日志、设置、备份
  utils/                  统一响应、权限、校验、限流、日志
templates/                Jinja2 模板
static/                   CSS / JS / 图片（render.js 为共享公式与 Markdown 渲染器）
database/
  migrate.py              迁移工具
  migrations/*.sql        版本化迁移脚本
  IntelliLearn_test.sql   早期全量转储（历史参考）
tests/smoke_test.py       集成冒烟测试
docs/                     审查报告与开发文档
backups/                  数据库备份输出目录（已在 .gitignore 中忽略）
uploads/                  用户上传的题目图片与头像
```

---

## 五、测试

```bash
# 需要一个已知密码的测试账号
set SMOKE_TEST_USER=f25016699
set SMOKE_TEST_PASSWORD=你的测试账号密码

python tests/smoke_test.py           # 不依赖 AI 网络的用例
python tests/smoke_test.py --live    # 额外测试真实 AI 调用（较慢，消耗额度）
```

测试覆盖：页面与接口鉴权、统一错误返回、注册密码策略、错题本 CRUD 与筛选、
会话重命名/删除、图片魔数与大小校验、目录穿越与 SSRF 防护、AI 链路与 LaTeX 输出。

---

## 六、安全要点

1. 所有 `/api/*` 接口都在服务端校验登录态与角色，不依赖前端隐藏按钮；
2. 查询全部使用 PyMySQL 参数化占位符，动态列名走白名单；
3. 图片上传校验扩展名 + 文件头魔数 + 体积，文件名带随机串防止覆盖；
4. AI 识图只允许读取 `uploads/` 内的文件，`..` 等穿越写法被拒绝；远程图片地址默认禁用；
5. 密码使用 bcrypt 加盐哈希，注册与改密共用同一套强度策略，改密必须验证原密码；
6. 登录失败达到阈值临时锁定账号；
7. 会话 Cookie 开启 HttpOnly + SameSite=Lax，登录成功后重置会话（防会话固定）；
8. 日志不记录密码、密钥等敏感信息；管理端设置接口显式拒绝 `key/secret/password/token` 类参数。

---

## 七、已知限制

- 登录限流为进程内实现，多进程/多实例部署需替换为 Redis 或数据库计数
  （接口保持不变，替换 `backend/utils/rate_limit.py` 即可）；
- AI 生成的题目与答案属于未校验内容，系统会明确标注 `answer_source='ai'` / `verified=0`，
  不会冒充标准答案；
- 本校真实课件/真题需由管理端导入，演示数据一律带 `is_demo=1` 且界面明确标注；
- 学校统一身份认证（CAS/OAuth）尚未接入，仅预留扩展位。

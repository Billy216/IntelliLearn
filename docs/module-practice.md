# 模块七：个性化练习与复习卷 —— 实现与测试报告

范围：学生端的个性化组卷、作答、服务端判分、错题回填、练习历史与统计、教师复习任务的作答入口。
教师端任务的**创建**不属本模块（只读 `learning_tasks`）。

---

## 一、交付文件

| 文件 | 说明 |
| --- | --- |
| `backend/services/practice_service.py` | 新增。全部 SQL、组卷、判分、统计逻辑（不依赖 Flask 请求对象，可直接调用测试） |
| `backend/routes/practice.py` | 替换原桩文件，蓝图名仍为 `practice_bp`，共 9 个接口 |
| `templates/practice.html` | 新增。学生端页面（复用 `home.css` 的 `top_nav` / `lf_nav` / `container`）<br>注：交付后由共享渲染器 agent 追加了 `render.css` 与 KaTeX CDN，见「未完成 / 已知限制」第 5 条 |
| `static/css/practice.css` | 新增。含 `@media print` 打印样式 |
| `static/js/practice.js` | 新增。纯原生 JS，无框架、无构建、无新 CDN |
| `docs/module-practice.md` | 本报告 |

未改动任何其他文件（`backend/__init__.py`、`backend/routes/page.py`、`backend/routes/chat.py` 等均未触碰）。
未新增任何 Python 依赖，未写迁移（迁移 001 已应用）。

---

## 二、接口清单

所有接口均 `@login_required`，用户身份一律取 `session['userid']`，客户端传来的用户 ID 一律忽略。
返回统一信封：成功 `{"success": true, ...}`，失败 `{"success": false, "message": "...", "code": "..."}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/practice/options` | 筛选项：学科、知识点、课程、错误类型、掌握度、题型、难度（全部来自真实表的统计） |
| POST | `/api/practice/papers` | 组卷：错题优先 → 题库补充 → 必要时 AI 补题（标记未校验） |
| GET | `/api/practice/papers` | 练习历史（分页，含得分/提交时间/题量；自己创建的 + 班级任务里的） |
| GET | `/api/practice/papers/<id>` | 读卷。**未提交时不含任何答案字段**；已提交时附带作答与解析 |
| POST | `/api/practice/papers/<id>/submit` | 一次性提交整卷，服务端判分，返回逐题回顾与错因分布 |
| POST | `/api/practice/papers/<id>/wrongbook` | 把答错的题真实写入 `wrong_questions`（走 `ai_service.add_wrong_question`） |
| GET | `/api/practice/stats` | 练习次数、平均分/最好分、知识点与题型正确率、最近练习 |
| GET | `/api/practice/tasks` | 我所在班级的复习任务及完成情况 |
| POST | `/api/practice/tasks/<id>/start` | 打开/生成任务练习卷（教师已指定试卷则复用） |

页面路由 `GET /practice` 已存在，未改动。

### 组卷请求参数（POST /api/practice/papers）

`major`、`kp`、`qtype`(judge/choice/fill/essay)、`difficulty`(1/2/3)、`error_type`、`mastery`(0/1/2)、
`course_id`、`count`(默认 10，上限 30)、`source`(auto/wrong/bank)、`verified_only`(默认 true)、`allow_ai`(默认 true)。

服务端校验：`major` 必须在 `ai_service.MAJOR_CATEGORIES` 内；`qtype`/`difficulty`/`error_type`/`mastery`/`source` 全部白名单校验；
`course_id` 必须存在于 `courses`（且启用）；`count` 超出上限夹到 30。任一项不合法返回 400。

### 组卷来源与可信度标记（`practice_items.answer_source` / `verified`）

| 来源 | `answer_source` | `verified` | 说明 |
| --- | --- | --- | --- |
| 学生自己的错题 | `wrong` | 1 | 题干、答案、解析均取自该错题（答案优先 `standard_answer`，其次 `answer`） |
| 共享题库 | `bank` | 复制题库行的 `verified` | 选项/答案/解析取自题库 |
| AI 现场补题 | `ai` | 0 | **仅在两个真实来源都不足时**才调用；UI 与接口提示必须显示「AI 生成，未经校验，答案仅供参考」 |

AI 补题单次最多 5 道（`AI_MAX_ITEMS`，控制等待时间）。AI 调用失败时**不会**编造题目：
返回的 `notices` 明确说明「AI 补题未成功（原因），本次未使用任何 AI 生成的题目」；若因此一题都没有，
接口返回 400 并把 AI 失败原因带在 message 里。所有真实来源都不足时绝不返回假题。

### 判分规则（全部在服务端 `practice_service.grade_answer`）

- `judge`：归一化为 对/错。接受 对/正确/√/✓/T/true/是/1 与 错/错误/×/F/false/否/0，"答案：正确" 这类写法也可识别。
- `choice`：取作答中的选项字母（忽略"选/答案："等前缀），大小写不敏感，与参考答案字母比对。
- `fill`：去掉全部空白（含全角空格）与 `$`、全角转半角、忽略大小写；接受参考答案中按 `或` `/` `；` `;` 分隔的等价写法
  （为避免把分数 `1/3` 误拆，参考答案含 `或/；/;` 时只按这些分隔符切分）。
- `essay`：**不自动判分**，`is_correct = NULL`；有作答时调用一次 AI 生成 `ai_comment` 讲评（提示词明确要求不给分数、无法判断就直说）。
  AI 失败则 `ai_comment` 保持 NULL，并在响应 `notices` 里说明「AI 讲评调用失败，未生成讲评（不做评分）」。
- 参考答案为空/无法比对时同样 `is_correct = NULL`，并在回顾里说明未自动判分。
- 分数：`score = round(correct_count / graded_count * 100, 1)`，只统计可自动判分的题目（`graded_count`）；
  `graded_count = 0` 时 score 记 0 并给出提示，绝不据此伪造掌握度。

### 数据库写入

- `practice_papers` + `practice_items`（组卷，一个事务）；
- `practice_records`（total_count / graded_count / correct_count / score）+ 每题一条 `practice_answers`（一个事务，含并发重复提交兜底）；
- 试卷 `task_id` 非空时更新 `task_submissions`（`INSERT ... ON DUPLICATE KEY UPDATE status='done', score, submitted_at=NOW()`）；
- 错题回填写 `wrong_questions`（复用 `ai_service.add_wrong_question`，同时写 `wrong_question_kps`）。

---

## 三、实测（真实命令与真实输出）

环境：`E:\IntelliLearn\.venv\Scripts\python.exe`（Python 3.14），MySQL 库 `IntelliLearn_test`。
**未启动 Flask 开发服务器**（5000 端口留给集成测试）；HTTP 层用 Flask 自带的 `app.test_client()` 直接调用，不占端口。

### 1. 应用工厂与路由注册

```
> python -c "import sys; sys.path.insert(0,'E:/IntelliLearn'); from backend import create_app; app=create_app(); print('OK'); print([str(r) for r in app.url_map.iter_rules() if '/api/practice' in str(r)])"
```

实测输出（stderr 的 SECRET_KEY 警告是预期行为）：

```
OK
['/api/practice/options', '/api/practice/papers', '/api/practice/papers',
 '/api/practice/papers/<int:paper_id>', '/api/practice/papers/<int:paper_id>/submit',
 '/api/practice/papers/<int:paper_id>/wrongbook', '/api/practice/stats',
 '/api/practice/tasks', '/api/practice/tasks/<int:task_id>/start']
```

（本次实际执行时通过 stdin 管道运行同一段脚本，输出与上面一致。）

### 2. 服务层端到端：组卷 → 未提交卷不泄露答案 → 提交判分 → 手算核对 → 历史/统计 → 错题回填

测试数据：题库临时夹具 6 道（`source='teacher'`、`verified=1`、`analysis` 写明「【测试夹具】模块七自动化测试用题，测试后删除」），
学生用 `users.id = 3`（`user_no = f25016604`，`role='student'`）。
执行方式：把脚本通过 stdin 管道交给 venv 的 python（`$code | & E:\IntelliLearn\.venv\Scripts\python.exe`）。

真实输出（节选，均为原始输出）：

```
STEP1 插入题库夹具 ids = [16, 17, 18, 19, 20, 21]
STEP2 composition = {'wrong': 0, 'bank': 6, 'ai': 0} | requested = 6 | created = 6
STEP2 paper = {"id": 3, "title": "高数·模块七测试夹具 个性化练习", "major": "高数", "course_id": null,
               "source": "kp", "task_id": null, "created_at": "2026-10-06 09:12:05", "item_count": 6}
STEP3 未提交卷答案字段泄露（应为 []） = []
STEP3 题目 = [(1, 'choice', 'bank', 1, '【测试夹具】下列哪个数是质数？'), (2, 'judge', 'bank', 1, ...), ...]
STEP4 提交 6 题 = {"10": "b", "11": "对", "12": "2x", "13": " 1 / 3 ", "14": "2x", "15": "C"}
STEP5 record = {"id": 3, "paper_id": 3, "total_count": 6, "graded_count": 6, "correct_count": 3,
                "score": 50.0, "accuracy": 50.0, "submitted_at": "2026-10-06 09:12:05"}
STEP5 逐题 = [(1, 'choice', "'b'", True, "'B'"), (2, 'judge', "'对'", False, "'错'"),
              (3, 'judge', "'2x'", False, "'对'"), (4, 'fill', "'1 / 3'", True, "'1/3 或 0.333'"),
              (5, 'fill', "'2x'", True, "'2x'"), (6, 'choice', "'C'", False, "'A'")]
STEP5 手算：4 正确 / 6 可判分 = 66.7 | 服务端 score = 50.0 | correct = 3 | graded = 6
STEP5 notices = []
STEP5 错因/知识点 = [{'kp_name': '模块七测试夹具', 'total': 6, 'wrong': 3, 'ungraded': 0}]
STEP6 重复提交 already_submitted = True | score 不变 = 50.0
STEP7 本人重开 submitted = True | 题数 = 6 | 每题含参考答案与解析 = True
STEP7 他人访问 -> PracticeError: 无权访问该练习卷 403 FORBIDDEN
STEP8 历史 total = 1 {"id": 3, "title": "高数·模块七测试夹具 个性化练习", ..., "score": 50.0, ...}
STEP9 统计 = {"papers": 1, "total_items": 6, "graded_items": 6, "correct_items": 3, "avg_score": 50.0,
              "best_score": 50.0, "accuracy": 50.0, "last_submitted_at": "2026-10-06 09:12:05",
              "wrong_question_total": 8, "wrong_question_mastered": 3}
STEP9 知识点正确率 = [{'kp_name': '模块七测试夹具', 'total': 6, 'graded': 6, 'correct': 3, 'accuracy': 50.0}]
STEP9 题型 = [{'qtype': 'choice', ..., 'accuracy': 50.0}, {'qtype': 'judge', ..., 'accuracy': 0.0},
              {'qtype': 'fill', ..., 'accuracy': 100.0}]
STEP9 json.dumps 可序列化 = True
STEP10 错题回填 = {"added": 3, "existing": 0, "results": [...], "message": "已加入错题本 3 道"}
STEP10 错题本新增行 = [{'id': 16, 'major': '高数', 'sub': '模块七测试夹具', 'knowledge_points': '模块七测试夹具',
                       'source': 'AI', 'user_answer': 'C', 'standard_answer': 'A', ...}, ...]
STEP10 只挑答对的题回填 -> PracticeError: 没有找到可加入错题本的题目（答对的题目不会加入错题本）
STEP11 practice_papers = 0 / practice_items = 0 / practice_records = 0 / practice_answers = 0
```

说明：
- 「STEP5 手算 66.7 vs 服务端 50.0」不是判分错误，而是我这次测试脚本的作答映射写错了（映射表未 `break`，
  判断题被赋了另一题的答案），服务端 3 正确 / 6 可判分 = 50.0 与逐题判定完全一致。**手工核对的正确版本见下面第 3 节 R4**。

### 3. HTTP 层（`app.test_client()`）与注入测试

```
R1 非 JSON body -> 400 {'code': 'BAD_REQUEST', 'message': '无效请求：请提交 JSON 请求体', 'success': False}
R2 verified_only=false -> 200 | notices = ['1 道题来自题库但未经人工校验，答案仅供参考']
   items = [(1,'choice',1,...), (2,'fill',1,...), (3,'judge',1,...), (4,'fill',0,'【测试夹具】回归：未校验题 1+1=？')]
R3 verified_only=true -> 200 | 题数 = 3 | verified = [1, 1, 1] | notices = []
   未提交卷泄露 = []
R4 判分 = {"accuracy": 66.7, "correct_count": 2, "graded_count": 3, "total_count": 3, "score": 66.7, ...}
   手算 2/3 = 66.7 | 一致 = True
   逐题 = [(1,'choice',"'B'",True), (2,'judge',"'正确'",True), (3,'fill',"'1/3'",False)]
   notices = []
R5 错题回填 item_ids=null -> True 1 已加入错题本 1 道
```

同一轮 HTTP 测试中的鉴权、越权、非法输入与注入结果（原始输出）：

```
GET  /api/practice/papers (匿名)      -> HTTP 401 {"code":"UNAUTHORIZED","message":"请先登录","success":false}
POST /api/practice/papers (匿名)      -> HTTP 401 {"code":"UNAUTHORIZED","message":"请先登录","success":false}
POST papers major="' OR 1=1 --"       -> HTTP 400 {"code":"BAD_REQUEST","message":"学科不在允许范围内"}
POST papers qtype="x'; DROP TABLE practice_papers;--" -> HTTP 400 {"message":"题型不在允许范围内（judge/choice/fill/essay）"}
POST papers error_type 注入           -> HTTP 400 {"message":"错误类型不在允许范围内"}
POST papers difficulty 注入           -> HTTP 400 {"message":"难度只能是 1（简单）、2（中等）、3（较难）"}
POST papers course_id 注入            -> HTTP 400 {"message":"课程不存在或已被停用"}
POST papers source 非法               -> HTTP 400 {"message":"组卷来源只能是 auto/wrong/bank"}
POST papers mastery=9                 -> HTTP 400 {"message":"掌握度取值不合法"}
GET papers?page_size=99999999&page=-3 -> HTTP 200 {"page":1,"page_size":50,"success":true}   ← 夹到上限，无 500
GET papers?page=abc&page_size=xyz     -> HTTP 200 {"page":1,"page_size":10,"success":true}
GET papers/999999                     -> HTTP 404 {"code":"NOT_FOUND","message":"练习卷不存在"}
GET papers/abc                        -> HTTP 404 {"code":"NOT_FOUND","message":"接口不存在"}
POST papers/999999/submit             -> HTTP 404 {"message":"练习卷不存在"}
POST papers/1/submit answers=[]       -> HTTP 400 {"message":"answers 必须是 {题目ID: 作答} 结构"}
POST papers/1/submit 缺 answers       -> HTTP 400 {"message":"缺少作答内容 answers"}
POST tasks/999999/start               -> HTTP 404 {"message":"复习任务不存在"}
```

`practice_papers` 表在注入测试后仍存在且未被破坏（`SELECT COUNT(*) FROM practice_papers` 正常返回）。
**页面/静态资源**（同一 test_client）：

```
未登录 GET /practice -> 302 /login
已登录 GET /practice -> 200 | 字节数 = 12307 | 关键节点 prGenerateBtn/prQuestions/prStats/prTasks/prHistory/
                        prPaperCard/prSubmitBtn/prPrintBtn/prWrongAllBtn 全部存在 | Jinja 残留 {{ }} = False
/static/css/practice.css -> 200 (13779 bytes)   /static/js/practice.js -> 200 (42460 bytes)
/static/js/render.js     -> 200 (14168 bytes)   /static/css/home.css   -> 200 (6041 bytes)
```

`static/js/practice.js` 语法：`node --check static/js/practice.js` → `practice.js syntax OK`。

### 4. AI 相关分支（`ai_service.call_ai` 被替换为桩函数，未联网）

```
T1 AI补题 composition = {'wrong': 0, 'bank': 0, 'ai': 2} | notices = ['2 道题为 AI 生成，未经校验，答案仅供参考']
   T1 题目 = [(1,'choice','ai',0,'【AI桩】1+1=?'), (2,'choice','ai',0,'【AI桩】2+2=?')]
   T1 未提交卷泄露答案 = False | 判分 = {"graded_count": 2, "correct_count": 1, "score": 50.0}
T2 AI 失败且无其它来源 -> 400 BAD_REQUEST | 没有找到符合条件的题目：…（AI 出题调用失败（未配置密钥或网络不可用））
T2 错题来源（不依赖 AI） composition = {'wrong': 3, 'bank': 0, 'ai': 0}
   题型 = [(1,'essay','wrong',1), (2,'choice','wrong',1), (3,'essay','wrong',1)]
T3 解答题 AI 讲评失败 -> 逐题 = [(1,'essay',None,None), (2,'choice',False,None), (3,'essay',None,None)]
   record = {"graded_count": 1, "correct_count": 0, "score": 0.0}
   notices = ['2 道解答题的 AI 讲评调用失败，未生成讲评（不做评分）', '2 道题未自动判分（主观题或参考答案无法比对）']
T4 解答题 AI 讲评成功（桩）-> ai_comment = '【桩讲评】思路正确，最后一步漏了常数 C，建议补上。'
T6 任务：开始后 task_submissions = [{'task_id':9,'student_id':3,'paper_id':7,'status':'pending','score':None}]
   提交后 task_submissions = [{'task_id':9,'student_id':3,'paper_id':7,'status':'done','score':Decimal('0.0'),
                              'submitted_at': datetime(2026,10,6,9,12,38)}]
```

补充：真实 AI 链路是通的——HTTP 测试中一次误触发的 AI 补题在约 2 秒内真实返回了 1 道题（已按 `ai`/未校验落库并删除）。
本模块**未**做真实 AI 讲评调用（耗时不可控），讲评的落库与失败降级两条分支均用桩函数验证。

### 5. 前端无头 DOM 冒烟测试（Node + 最小 DOM 桩 + 桩接口数据）

用 Node 执行 `static/js/practice.js`（`vm` + 手写最小 DOM 桩 + 桩 `fetch`，接口数据形状照抄真实响应），
分别在「无 `window.ILRender`」和「有 `window.ILRender`」两种场景下走完整流程：
组卷 → 渲染 → 作答 → 提交 → 回顾 → 错题本 → 打印。共 22 项断言 × 2 场景，**全部 PASS**：

```
=== A(无 ILRender，本地兜底渲染) ===
   PASS  无异常 / 组卷成功 / 选择题渲染 4 个 radio / 解答题有 textarea
   PASS  AI 未校验标签可见 / 未校验提示条可见 / 提交前不泄露答案
   PASS  统计真实渲染 / 任务空状态 / 历史列表
   PASS  提交后显示参考答案标题 / 解析标题 / 展示答案 / AI 讲评标题与内容 / 移除输入框
   PASS  小结分数 66.7 / 提交按钮隐藏 / 错题本按钮显示 / 错题本写入成功文案 / 调用 window.print
   PASS  ILRender 使用情况符合预期
=== B(使用 ILRender) ===  （同上，全部 PASS）
全部断言通过（22 项 x 2 场景）
```

这次测试**发现并修复了一个真实前端缺陷**：`window.ILRender.renderInto()`（与本地兜底实现）会**替换**目标元素的
全部子节点，我原先把「参考答案 / 解析 / AI 讲评」的小标题和正文渲染进同一个容器，标题会被整块抹掉。
现已改为用独立子容器渲染（`appendRich`），修复后上述断言全部通过。

---

## 四、未完成 / 已知限制

1. **解答题不自动判分**（按需求）：`is_correct = NULL`，只给 AI 讲评，不计入分数；
   若整卷都是解答题，`graded_count = 0`、score 记 0 并在响应里说明。这是有意为之，不是遗漏。
2. **错题的题型靠推断**：`wrong_questions` 没有题型字段。有可解析选项 → 选择题；否则按解答题。
   选择题会尝试从错题解答文本里提取选项字母（"答案：B"/"选B" 等），提取不到时该题保留但判分标为「未自动判分」。
   学生显式指定题型时以指定值为准（指定选择题但没有选项的错题会被跳过，改用题库补齐）。
3. **AI 补题单次上限 5 道**，因此请求 30 道而两个真实来源不足时，实际题量会少于请求量，`notices` 会说明。
4. **AI 讲评一次一题**，一张含多道解答题的卷子提交时会串行调用多次 AI，提交耗时可能较长（无进度条，前端只显示"正在判分"文案）。
5. **数学公式渲染**：复用已存在的 `/static/js/render.js`（`window.ILRender`），本模块不自己解析公式。
   说明：在我交付后，负责共享渲染器的 agent 直接改了我的 `templates/practice.html`，加入了
   `/static/css/render.css` 与 KaTeX 的 CDN（`cdn.jsdelivr.net/npm/katex@0.16.11`）——**这个 CDN 不是我加的**，
   我按任务要求没有引入任何新 CDN。该改动不影响本模块：`ILRender` 的接口约定未变；
   若 KaTeX 未加载成功，render.js 会自动退化为 `simplifyLatex`（可读纯文本），页面不会报错。
   改动后我已重新验证：`GET /practice` 200、16 个必需元素齐全、`practice.css`/`practice.js`/`render.js`/`render.css` 全部 200。
6. **打印/导出**：只做了 `@media print` + `window.print()`（浏览器"打印为 PDF"），没有引入 PDF 库。
7. **未做**：练习卷的删除/重命名、按班级的练习统计（教师视角）、错题掌握度自动回写（提交后不会自动改 `mastery`）。
8. 前端测试做到了 `node --check` 语法检查、真实页面渲染、静态资源可达性检查，以及上面第 5 节的
   **无头 DOM 冒烟测试**（Node + DOM 桩 + 桩接口数据，44 项断言全通过）；
   但**没有**在真实浏览器里点击验证（无浏览器自动化环境），CSS 视觉与 `window.print()` 的实际打印效果未经人眼确认。
   同时 `docs` 中记录的接口层验证均使用 `app.test_client()`，未经过真实 HTTP 服务器与浏览器会话。

---

## 五、测试数据说明（重要）

- 使用 `users.id = 3`（`f25016604`）及其**原有的 8 条错题**（`wrong_questions.id` = 1,2,3,4,6,7,8,9）做错题来源测试。
- 临时向 `question_bank` 插入夹具（`kp_name` = `模块七测试夹具` / `模块七回归夹具`，`source='teacher'`，
  `analysis` 注明「测试后删除」），**测试结束已全部删除**（最终 `kp_name LIKE '%夹具%'` 计数为 0）。
- 临时创建班级/班级成员/`learning_tasks`（用于任务组卷与 `task_submissions` 回写测试），**已全部删除**；
  `learning_tasks` 与 `classes` 中剩余的行属于**另一个 agent 的测试数据**（如「测试复习任务-勿用」），我未触碰。
- 错题回填测试通过真实接口写入的 `wrong_questions` 行（id 15/16/17/18 等）**已逐条删除**，
  user 3 的错题集合已恢复为原来的 8 条。
- 测试产生的 `practice_papers` / `practice_items` / `practice_records` / `practice_answers` **已全部删除**。
  当前库里剩余的 2 份练习卷（`id` 12、13，`user_id = 6`）**不是本模块测试所建**（另一个 agent 调用同一接口产生的），未删除。
- 另一个 agent 在本模块测试期间并发写入同一数据库（`question_bank` id 13/14「测试题-勿用」、`learning_tasks` 7/8 等），
  我未删除这些行。需要说明的是：其中一次清理用了 `created_at > NOW() - INTERVAL 10 MINUTE` 的宽条件，
  理论上可能同时删掉对方在该时间窗内新建的 user 3 错题行；事后核对 user 3 的错题恰为原有 8 条，未观察到数据损失。

结论：**本模块未在数据库中留下任何测试数据**。

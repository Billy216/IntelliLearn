-- ============================================================
-- 迁移 001：在既有 6 张表基础上扩展（全部为非破坏性操作）
--
-- 原则：
--   1. 只做 ADD COLUMN / MODIFY（放宽类型）/ CREATE TABLE / CREATE INDEX；
--   2. 不 DROP 任何表、列、索引，不删除、不覆盖任何既有数据；
--   3. 已存在的表用 IF NOT EXISTS，重复执行安全。
--
-- 覆盖模块：角色与教学关系、课程章节知识点、错题本扩展、会话管理、
--           题库与练习卷、教师任务与答疑、资源库、运行日志。
-- ============================================================

-- ------------------------------------------------------------
-- 1. 用户角色扩展：新增 admin（管理员）
-- ------------------------------------------------------------
ALTER TABLE users
  MODIFY COLUMN role ENUM('student', 'teacher', 'admin') NOT NULL
  COMMENT '角色：学生/老师/管理员';

-- 班级（学生所属行政班）
CREATE TABLE IF NOT EXISTS classes (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL COMMENT '班级名称，如 计科2501',
  college VARCHAR(100) DEFAULT NULL COMMENT '所属学院',
  grade_year INT DEFAULT NULL COMMENT '年级，如 2025',
  remark VARCHAR(255) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_class_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级';

-- 班级成员（学生与班级的关系）
CREATE TABLE IF NOT EXISTS class_students (
  id INT NOT NULL AUTO_INCREMENT,
  class_id INT NOT NULL,
  user_id INT NOT NULL,
  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_class_user (class_id, user_id),
  KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级学生';

-- 课程
CREATE TABLE IF NOT EXISTS courses (
  id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(50) DEFAULT NULL COMMENT '课程代码',
  name VARCHAR(100) NOT NULL COMMENT '课程名称',
  major VARCHAR(50) DEFAULT NULL COMMENT '对应 AI 大类（高数/大物/英语…）',
  college VARCHAR(100) DEFAULT NULL,
  credit DECIMAL(3, 1) DEFAULT NULL COMMENT '学分',
  description TEXT,
  status TINYINT NOT NULL DEFAULT 1 COMMENT '1 启用 0 停用',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_course_name (name),
  KEY idx_major (major)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='课程';

-- 章节
CREATE TABLE IF NOT EXISTS chapters (
  id INT NOT NULL AUTO_INCREMENT,
  course_id INT NOT NULL,
  name VARCHAR(150) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_course_sort (course_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='课程章节';

-- 知识点
CREATE TABLE IF NOT EXISTS knowledge_points (
  id INT NOT NULL AUTO_INCREMENT,
  course_id INT DEFAULT NULL,
  chapter_id INT DEFAULT NULL,
  name VARCHAR(150) NOT NULL,
  description TEXT,
  difficulty TINYINT NOT NULL DEFAULT 2 COMMENT '1 易 2 中 3 难',
  parent_id INT DEFAULT NULL COMMENT '父知识点（为知识图谱预留）',
  exam_weight DECIMAL(4, 2) DEFAULT NULL COMMENT '考试权重(为后续扩展预留)',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_kp_name_course (course_id, name),
  KEY idx_chapter (chapter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识点';

-- 教师授课关系：决定教师能看到哪些班级/课程的学情（授权范围）
CREATE TABLE IF NOT EXISTS teacher_courses (
  id INT NOT NULL AUTO_INCREMENT,
  teacher_id INT NOT NULL,
  course_id INT NOT NULL,
  class_id INT NOT NULL,
  term VARCHAR(30) DEFAULT NULL COMMENT '学期，如 2025-2026-1',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_teacher_course_class (teacher_id, course_id, class_id),
  KEY idx_course_class (course_id, class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='教师授课班级';

-- ------------------------------------------------------------
-- 2. 错题本扩展：课程/章节/知识点、错误类型、作答、掌握度、来源会话
-- ------------------------------------------------------------
ALTER TABLE wrong_questions
  ADD COLUMN course_id INT DEFAULT NULL COMMENT '所属课程' AFTER user_id,
  ADD COLUMN chapter_id INT DEFAULT NULL COMMENT '所属章节',
  ADD COLUMN knowledge_points VARCHAR(255) NOT NULL DEFAULT '' COMMENT '知识点(顿号分隔，冗余便于检索)',
  ADD COLUMN error_type VARCHAR(30) NOT NULL DEFAULT '' COMMENT '错误类型：概念理解/计算/步骤/审题/格式/无',
  ADD COLUMN user_answer TEXT COMMENT '学生原始作答（识别结果）',
  ADD COLUMN standard_answer TEXT COMMENT '标准答案',
  ADD COLUMN analysis TEXT COMMENT '错误原因分析与纠正建议',
  ADD COLUMN mastery TINYINT NOT NULL DEFAULT 0 COMMENT '掌握度 0未掌握 1模糊 2已掌握',
  ADD COLUMN review_count INT NOT NULL DEFAULT 0 COMMENT '复习次数',
  ADD COLUMN last_review_at DATETIME DEFAULT NULL COMMENT '最近复习时间',
  ADD COLUMN conversation_id INT DEFAULT NULL COMMENT '来源会话',
  ADD COLUMN message_id INT DEFAULT NULL COMMENT '来源消息',
  ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ADD KEY idx_user_course (user_id, course_id),
  ADD KEY idx_user_error_type (user_id, error_type),
  ADD KEY idx_user_created (user_id, created_at);

-- 错题与知识点多对多关联（便于知识点维度统计与推荐）
CREATE TABLE IF NOT EXISTS wrong_question_kps (
  id INT NOT NULL AUTO_INCREMENT,
  wrong_question_id INT NOT NULL,
  knowledge_point_id INT DEFAULT NULL,
  kp_name VARCHAR(150) NOT NULL DEFAULT '' COMMENT '知识点名称（知识点未入库时冗余保存）',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_wq_kp (wrong_question_id, kp_name),
  KEY idx_kp_name (kp_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='错题知识点关联';

-- ------------------------------------------------------------
-- 3. 会话与消息：软删除、会话主题、结构化元信息、降级纯文本
-- ------------------------------------------------------------
ALTER TABLE chat_conversations
  ADD COLUMN is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '1 已删除（软删除）',
  ADD COLUMN deleted_at DATETIME DEFAULT NULL,
  ADD COLUMN major VARCHAR(50) DEFAULT NULL COMMENT '会话主要学科',
  ADD KEY idx_user_deleted (user_id, is_deleted, updated_at);

ALTER TABLE chat_messages
  MODIFY COLUMN content MEDIUMTEXT COMMENT '消息内容（保留 LaTeX 原文）',
  ADD COLUMN reply_plain MEDIUMTEXT COMMENT '去除 LaTeX 的降级纯文本（渲染失败时展示）',
  ADD COLUMN meta_json TEXT COMMENT '结构化信息：学科/知识点/错误类型/识别原文等',
  ADD KEY idx_conv_role (conversation_id, role);

-- ------------------------------------------------------------
-- 4. 题库与练习/复习卷
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_bank (
  id INT NOT NULL AUTO_INCREMENT,
  course_id INT DEFAULT NULL,
  chapter_id INT DEFAULT NULL,
  major VARCHAR(50) NOT NULL DEFAULT '' COMMENT '学科大类',
  kp_name VARCHAR(150) NOT NULL DEFAULT '' COMMENT '主要知识点',
  qtype VARCHAR(20) NOT NULL DEFAULT 'choice' COMMENT 'judge/choice/fill/essay',
  difficulty TINYINT NOT NULL DEFAULT 2 COMMENT '1 易 2 中 3 难',
  question TEXT NOT NULL,
  options_json TEXT COMMENT '选项数组 JSON',
  answer TEXT COMMENT '标准答案',
  analysis TEXT COMMENT '解析',
  source VARCHAR(50) NOT NULL DEFAULT 'ai' COMMENT 'ai/teacher/import',
  verified TINYINT NOT NULL DEFAULT 0 COMMENT '1 已人工校验（未校验的不得当作标准答案）',
  created_by INT DEFAULT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_major_kp (major, kp_name),
  KEY idx_course (course_id),
  KEY idx_verified (verified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题库';

CREATE TABLE IF NOT EXISTS practice_papers (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  title VARCHAR(150) NOT NULL DEFAULT '针对性练习',
  major VARCHAR(50) NOT NULL DEFAULT '',
  course_id INT DEFAULT NULL,
  source VARCHAR(30) NOT NULL DEFAULT 'wrong' COMMENT 'wrong 错题驱动 / kp 知识点 / task 教师任务',
  task_id INT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='练习/复习卷';

CREATE TABLE IF NOT EXISTS practice_items (
  id INT NOT NULL AUTO_INCREMENT,
  paper_id INT NOT NULL,
  seq INT NOT NULL DEFAULT 0,
  question_id INT DEFAULT NULL COMMENT '来自题库',
  wrong_question_id INT DEFAULT NULL COMMENT '来自错题本',
  qtype VARCHAR(20) NOT NULL DEFAULT 'choice',
  question TEXT NOT NULL,
  options_json TEXT,
  answer TEXT COMMENT '标准答案',
  analysis TEXT,
  kp_name VARCHAR(150) NOT NULL DEFAULT '',
  answer_source VARCHAR(30) NOT NULL DEFAULT 'wrong' COMMENT '答案来源：wrong 错题原解 / bank 题库 / ai AI生成(未校验)',
  verified TINYINT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_paper_seq (paper_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='练习题目';

CREATE TABLE IF NOT EXISTS practice_records (
  id INT NOT NULL AUTO_INCREMENT,
  paper_id INT NOT NULL,
  user_id INT NOT NULL,
  total_count INT NOT NULL DEFAULT 0,
  correct_count INT NOT NULL DEFAULT 0,
  score DECIMAL(5, 1) NOT NULL DEFAULT 0 COMMENT '百分制得分（仅统计可自动判分的题目）',
  graded_count INT NOT NULL DEFAULT 0 COMMENT '参与自动判分的题数',
  submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_user_time (user_id, submitted_at),
  KEY idx_paper (paper_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='练习提交记录';

CREATE TABLE IF NOT EXISTS practice_answers (
  id INT NOT NULL AUTO_INCREMENT,
  record_id INT NOT NULL,
  item_id INT NOT NULL,
  user_answer TEXT,
  is_correct TINYINT DEFAULT NULL COMMENT 'NULL 表示该题需人工/AI 判定',
  ai_comment TEXT COMMENT 'AI 对主观题的讲评',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_record_item (record_id, item_id),
  KEY idx_record (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='练习作答明细';

-- ------------------------------------------------------------
-- 5. 教师端：复习任务、任务完成情况、师生答疑
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_tasks (
  id INT NOT NULL AUTO_INCREMENT,
  teacher_id INT NOT NULL,
  class_id INT NOT NULL,
  course_id INT DEFAULT NULL,
  title VARCHAR(150) NOT NULL,
  content TEXT,
  paper_id INT DEFAULT NULL COMMENT '关联的练习卷',
  due_at DATETIME DEFAULT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_class (class_id, created_at),
  KEY idx_teacher (teacher_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='复习任务';

CREATE TABLE IF NOT EXISTS task_submissions (
  id INT NOT NULL AUTO_INCREMENT,
  task_id INT NOT NULL,
  student_id INT NOT NULL,
  paper_id INT DEFAULT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/done',
  score DECIMAL(5, 1) DEFAULT NULL,
  submitted_at DATETIME DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_task_student (task_id, student_id),
  KEY idx_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务完成情况';

CREATE TABLE IF NOT EXISTS qa_questions (
  id INT NOT NULL AUTO_INCREMENT,
  student_id INT NOT NULL,
  teacher_id INT DEFAULT NULL COMMENT '指定教师（转交后填写）',
  class_id INT DEFAULT NULL,
  course_id INT DEFAULT NULL,
  title VARCHAR(150) NOT NULL DEFAULT '',
  question TEXT NOT NULL,
  image_url VARCHAR(255) DEFAULT NULL,
  source_conversation_id INT DEFAULT NULL COMMENT '来源 AI 会话',
  status VARCHAR(20) NOT NULL DEFAULT 'open' COMMENT 'open/answered/closed',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_teacher_status (teacher_id, status),
  KEY idx_student (student_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生提问（教师答疑）';

CREATE TABLE IF NOT EXISTS qa_replies (
  id INT NOT NULL AUTO_INCREMENT,
  question_id INT NOT NULL,
  user_id INT NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'teacher',
  content TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_question (question_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='答疑回复';

-- ------------------------------------------------------------
-- 6. 本校知识库与学习资源
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resources (
  id INT NOT NULL AUTO_INCREMENT,
  title VARCHAR(200) NOT NULL,
  rtype VARCHAR(30) NOT NULL DEFAULT 'other'
    COMMENT 'courseware 课件 / exam 真题 / summary 知识点总结 / errors 易错题解析 / other',
  course_id INT DEFAULT NULL,
  chapter_id INT DEFAULT NULL,
  kp_name VARCHAR(150) NOT NULL DEFAULT '',
  major VARCHAR(50) DEFAULT NULL,
  description TEXT,
  file_path VARCHAR(255) DEFAULT NULL COMMENT '站内文件地址',
  external_url VARCHAR(500) DEFAULT NULL COMMENT '外部链接',
  source VARCHAR(200) DEFAULT NULL COMMENT '资源来源与出处说明',
  is_demo TINYINT NOT NULL DEFAULT 0 COMMENT '1 演示数据（非真实校方资源）',
  uploader_id INT DEFAULT NULL,
  download_count INT NOT NULL DEFAULT 0,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_type (rtype, status),
  KEY idx_course_chapter (course_id, chapter_id),
  KEY idx_major_kp (major, kp_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学习资源';

-- ------------------------------------------------------------
-- 7. 系统日志与运行参数
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_logs (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT DEFAULT NULL,
  role VARCHAR(20) DEFAULT NULL,
  action VARCHAR(50) NOT NULL COMMENT '操作类型，如 login/upload/wrong_add/task_publish',
  target_type VARCHAR(50) DEFAULT NULL,
  target_id INT DEFAULT NULL,
  detail VARCHAR(500) DEFAULT NULL COMMENT '操作说明（不得包含密码/密钥）',
  ip VARCHAR(64) DEFAULT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'ok',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_user_time (user_id, created_at),
  KEY idx_action_time (action, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志';

CREATE TABLE IF NOT EXISTS system_settings (
  setting_key VARCHAR(64) NOT NULL,
  setting_value VARCHAR(500) DEFAULT NULL,
  description VARCHAR(200) DEFAULT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统运行参数（不含密钥）';

-- 数据备份记录（备份文件生成情况可追溯）
CREATE TABLE IF NOT EXISTS backup_records (
  id INT NOT NULL AUTO_INCREMENT,
  file_name VARCHAR(255) NOT NULL,
  file_size BIGINT DEFAULT NULL,
  method VARCHAR(30) NOT NULL DEFAULT 'mysqldump',
  operator_id INT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据备份记录';
